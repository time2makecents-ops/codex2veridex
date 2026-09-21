"""Interactive loopback OAuth connection for a workspace-scoped eBay seller account."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict

from connected_accounts import ConnectedAccounts
from ebay_gateway import EbayGateway, EbayGatewayError


ROOT = Path(__file__).resolve().parent


def connect(
    accounts: ConnectedAccounts,
    workspace_id: str,
    *,
    username: str = "",
    environment: str = "sandbox",
    marketplace_id: str = "EBAY_US",
) -> Dict[str, object]:
    env = accounts.ebay_env(
        workspace_id,
        username=username,
        environment=environment,
        marketplace_id=marketplace_id,
    )
    gateway = EbayGateway(env=env)
    if not gateway.configured():
        raise EbayGatewayError(
            "eBay OAuth is not configured. Add EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_RUNAME, "
            "EBAY_REDIRECT_URI, and VERIDEX_INTEGRATION_ENCRYPTION_KEY to .env.local."
        )
    callback_uri = str(env.get("EBAY_REDIRECT_URI") or "http://127.0.0.1:8079/integrations/ebay/callback")
    parsed_callback = urllib.parse.urlparse(callback_uri)
    if (
        parsed_callback.scheme != "http"
        or parsed_callback.hostname not in {"127.0.0.1", "localhost"}
        or not parsed_callback.port
    ):
        raise EbayGatewayError("EBAY_REDIRECT_URI must be an HTTP loopback address with an explicit port.")

    state = secrets.token_urlsafe(32)
    result: Dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != (parsed_callback.path or "/"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            query = urllib.parse.parse_qs(parsed.query)
            returned_state = str(query.get("state", [""])[0])
            if returned_state != state:
                body = (
                    "<!doctype html><meta charset='utf-8'><title>Expired eBay connection</title>"
                    "<style>body{font:18px system-ui;max-width:640px;margin:15vh auto;padding:24px;color:#17211b}</style>"
                    "<h1>This eBay connection attempt has expired.</h1>"
                    "<p>Close this tab and start a new connection from Veridex.</p>"
                ).encode("utf-8")
            else:
                result["state"] = returned_state
                result["code"] = str(query.get("code", [""])[0])
                result["error"] = str(query.get("error", [""])[0])
                body = (
                    "<!doctype html><meta charset='utf-8'><title>eBay connected</title>"
                    "<style>body{font:18px system-ui;max-width:640px;margin:15vh auto;padding:24px;color:#17211b}</style>"
                    "<h1>Return to Veridex</h1><p>The eBay authorization response was received. You may close this tab.</p>"
                ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((str(parsed_callback.hostname), int(parsed_callback.port)), CallbackHandler)
    server.timeout = 1
    authorization_url = gateway.authorization_url(state)
    print(f"Opening eBay {gateway.environment} authorization...", flush=True)
    if not webbrowser.open(authorization_url, new=1):
        print(f"Open this URL in your browser:\n{authorization_url}", flush=True)
    deadline = time.monotonic() + 1800
    while not result and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if not result:
        raise EbayGatewayError("eBay authorization timed out after thirty minutes.")
    if result.get("error"):
        raise EbayGatewayError(f"eBay authorization was not completed: {result['error']}")
    if result.get("state") != state or not result.get("code"):
        raise EbayGatewayError("eBay authorization returned an invalid callback.")

    tokens = gateway.exchange_authorization_code(result["code"])
    access_token = str(tokens.get("access_token") or "")
    refresh_token = str(tokens.get("refresh_token") or "")
    introspection = gateway.introspect(access_token)
    actual_username = str(introspection.get("username") or username or "eBay seller").strip()
    if not bool(introspection.get("active", True)):
        raise EbayGatewayError("eBay returned an inactive user token.")
    gateway.save_connection(
        username=actual_username,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(tokens.get("expires_in") or 7200),
        scopes=str(tokens.get("scope") or " ".join(gateway.scopes())).split(),
    )
    accounts.assign_ebay(
        workspace_id,
        actual_username,
        environment=gateway.environment,
        marketplace_id=gateway.marketplace_id,
    )
    return gateway.connection_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect a Veridex workspace to an eBay seller account")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--username", default="")
    parser.add_argument("--environment", choices=("sandbox", "production"), default="sandbox")
    parser.add_argument("--marketplace-id", default="EBAY_US")
    args = parser.parse_args()
    try:
        data_root = Path(os.environ.get("VERIDEX_DATA_DIR", str(ROOT / "data"))).resolve()
        status = connect(
            ConnectedAccounts(data_root, ROOT),
            args.workspace_id,
            username=args.username,
            environment=args.environment,
            marketplace_id=args.marketplace_id,
        )
        print(f"Connected eBay {status.get('environment')} account {status.get('username')}.", flush=True)
        return 0
    except (EbayGatewayError, OSError) as exc:
        print(f"eBay connection failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
