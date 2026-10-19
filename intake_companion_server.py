"""Small paired-LAN capture companion for the Veridex Seller Intake catalog."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from seller_intake import SellerIntakeCatalog, SellerIntakeError


ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
WEB_ROOT = ROOT / "web" / "intake_companion"
ACCESS_PATH = DATA_ROOT / "system" / "remote_access.json"
REMOTE_COOKIE = "veridex_remote_session"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ASSET_ROUTE = re.compile(r"/api/items/([A-Za-z0-9_-]+)/photos")
CATALOG = SellerIntakeCatalog(DATA_ROOT)


def access_state() -> dict:
    try:
        value = json.loads(ACCESS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict) or not str(value.get("pairing_token") or ""):
        value = {"pairing_token": secrets.token_urlsafe(32), "sessions": [], "created_at": datetime.now().astimezone().isoformat()}
        save_access_state(value)
    return value


def save_access_state(value: dict) -> None:
    ACCESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = ACCESS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(ACCESS_PATH)


class CompanionHandler(BaseHTTPRequestHandler):
    server_version = "VeridexIntakeCompanion/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _is_remote(self) -> bool:
        host = str(self.headers.get("Host") or "").split(":", 1)[0].strip("[]").lower()
        return host not in {"", "127.0.0.1", "localhost", "::1"}

    def _authorized(self) -> bool:
        if not self._is_remote():
            return True
        cookies = {}
        for part in str(self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                cookies[key] = value
        supplied = cookies.get(REMOTE_COOKIE, "")
        return any(
            supplied and secrets.compare_digest(supplied, str(row.get("token") or ""))
            for row in access_state().get("sessions", [])
            if isinstance(row, dict)
        )

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("request body is too large")
        value = json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _pair(self, token: str) -> None:
        access = access_state()
        if not secrets.compare_digest(str(token or ""), str(access.get("pairing_token") or "")):
            self._json({"error": "Invalid or expired pairing token"}, HTTPStatus.UNAUTHORIZED)
            return
        session_token = secrets.token_urlsafe(32)
        sessions = [row for row in access.get("sessions", []) if isinstance(row, dict)][-9:]
        sessions.append({"token": session_token, "paired_at": datetime.now().astimezone().isoformat()})
        access.update({"pairing_token": secrets.token_urlsafe(32), "sessions": sessions})
        save_access_state(access)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"{REMOTE_COOKIE}={session_token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _static(self, route: str) -> None:
        relative = "index.html" if route in {"", "/"} else route.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT or not candidate.is_file():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/pair":
                self._pair(str(parse_qs(parsed.query).get("token", [""])[0]))
                return
            if not self._authorized():
                self._json({"error": "This phone is not paired. Open the one-time LAN pairing link first."}, HTTPStatus.UNAUTHORIZED)
                return
            if parsed.path == "/health":
                self._json({"ok": True, "service": "veridex-intake-companion"})
            elif parsed.path == "/api/bootstrap":
                query = parse_qs(parsed.query)
                batch_id = str(query.get("batch_id", [""])[0]).strip()
                item_id = str(query.get("item_id", [""])[0]).strip()
                batches = CATALOG.list_batches(include_archived=False)
                payload: dict = {"batches": batches, "upload_limit_bytes": MAX_UPLOAD_BYTES}
                if item_id:
                    payload["item"] = CATALOG.get_item(item_id)
                    payload["batch"] = CATALOG.get_batch(str(payload["item"]["batch_id"]), include_archived=False)
                elif batch_id:
                    payload["batch"] = CATALOG.get_batch(batch_id, include_archived=False)
                elif batches:
                    payload["batch"] = CATALOG.get_batch(str(batches[0]["batch_id"]), include_archived=False)
                self._json(payload)
            elif re.fullmatch(r"/api/items/[A-Za-z0-9_-]+/photos", parsed.path):
                item_id = parsed.path.split("/")[3]
                asset_id = str(parse_qs(parsed.query).get("asset_id", [""])[0])
                asset, source_path = CATALOG.asset_path(asset_id)
                asset_value = dict(asset)
                if str(asset_value.get("item_id") or "") != item_id or asset_value.get("role") != "photo":
                    raise KeyError("Unknown photo")
                body = source_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", str(asset_value.get("content_type") or "image/jpeg"))
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "private, no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                self._static(parsed.path)
        except (KeyError, SellerIntakeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if not self._authorized():
                self._json({"error": "This phone is not paired. Open the one-time LAN pairing link first."}, HTTPStatus.UNAUTHORIZED)
                return
            asset = ASSET_ROUTE.fullmatch(parsed.path)
            if asset:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_UPLOAD_BYTES:
                    raise ValueError("photo must be between 1 byte and 50 MB")
                query = parse_qs(parsed.query)
                row = CATALOG.add_asset(asset.group(1), str(query.get("name", [""])[0]), self.rfile.read(length), str(self.headers.get("Content-Type") or "image/jpeg"), "photo")
                self._json({"asset": row, "item": CATALOG.get_item(asset.group(1))}, HTTPStatus.CREATED)
                return
            payload = self._body()
            if parsed.path == "/api/batches":
                self._json({"batch": CATALOG.create_batch(payload)}, HTTPStatus.CREATED)
            elif parsed.path == "/api/items":
                self._json({"item": CATALOG.create_item(payload)}, HTTPStatus.CREATED)
            elif parsed.path == "/api/items/update":
                self._json({"item": CATALOG.update_item(payload)})
            elif parsed.path == "/api/items/archive":
                item_id = str(payload.get("item_id") or "")
                self._json({"item": CATALOG.update_item({"item_id": item_id, "status": "archived"})})
            elif parsed.path == "/api/items/delete":
                if payload.get("confirmation") != "DELETE":
                    raise SellerIntakeError("Type DELETE to permanently remove this item")
                self._json({"deleted": CATALOG.delete_item(str(payload.get("item_id") or ""))})
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (KeyError, SellerIntakeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Veridex intake companion")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8775)
    args = parser.parse_args()
    access_state()
    server = ThreadingHTTPServer((args.host, args.port), CompanionHandler)
    print(f"Veridex Intake Companion running at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
