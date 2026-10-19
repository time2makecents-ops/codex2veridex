"""One-time local OAuth connection flow for Veridex Gmail access."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional

from gmail_gateway import GmailGateway, GmailGatewayError, LOCAL_ENV, _load_env_file


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
LOCAL_KEYS = [
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REDIRECT_URI",
    "VERIDEX_GOOGLE_ACCOUNT",
    "VERIDEX_INTEGRATION_ENCRYPTION_KEY",
    "VERIDEX_GMAIL_DB_PATH",
]


def _chrome_path(env: Dict[str, str]) -> Path:
    candidates = [
        str(env.get("VERIDEX_CHROME_PATH") or os.environ.get("VERIDEX_CHROME_PATH") or ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path(os.environ.get("LOCALAPPDATA") or "") / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    for candidate in candidates:
        path = Path(candidate) if candidate else Path()
        if candidate and path.is_file():
            return path.resolve()
    raise GmailGatewayError("Google Chrome was not found. Set VERIDEX_CHROME_PATH.")


def _debug_json(port: int, route: str, *, method: str = "GET") -> Dict[str, object]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{route}", method=method)
    with urllib.request.urlopen(request, timeout=2.5) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise GmailGatewayError("The dedicated Google Chrome debugging endpoint returned invalid data.")
    return value


def _open_google_authorization(url: str, env: Dict[str, str]) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "accounts.google.com" or parsed.path != "/o/oauth2/v2/auth":
        raise GmailGatewayError("Refused to open a non-Google OAuth URL in the dedicated profile.")
    profile_root = Path(
        env.get("VERIDEX_GOOGLE_PROFILE_DIR")
        or os.environ.get("VERIDEX_GOOGLE_PROFILE_DIR")
        or LOCAL_ENV.parent / "data" / "browser_profiles" / "veridex_google"
    ).resolve()
    debug_port = int(
        env.get("VERIDEX_GOOGLE_DEBUG_PORT")
        or os.environ.get("VERIDEX_GOOGLE_DEBUG_PORT")
        or 9223
    )
    try:
        _debug_json(debug_port, "/json/version")
        _debug_json(debug_port, f"/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
        return
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, GmailGatewayError):
        pass
    profile_root.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(_chrome_path(env)),
            f"--user-data-dir={profile_root}",
            "--profile-directory=Default",
            f"--remote-debugging-port={debug_port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            url,
        ],
        cwd=str(LOCAL_ENV.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _read_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    _load_env_file(path, values)
    return values


def _upsert_local_env(updates: Dict[str, str]) -> None:
    existing_lines = LOCAL_ENV.read_text(encoding="utf-8").splitlines() if LOCAL_ENV.exists() else []
    replaced = set()
    output = []
    for line in existing_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            replaced.add(key)
        else:
            output.append(line)
    if output and output[-1].strip():
        output.append("")
    if not existing_lines:
        output.extend(["# Local-only Veridex configuration. Never commit this file.", ""])
    for key in LOCAL_KEYS:
        if key in updates and key not in replaced:
            output.append(f"{key}={updates[key]}")
    LOCAL_ENV.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def import_configuration(source: Path) -> None:
    """Copy only OAuth client configuration into Veridex's ignored local env."""
    source_values = _read_env(source)
    local_values = _read_env(LOCAL_ENV)
    client_id = local_values.get("GOOGLE_OAUTH_CLIENT_ID") or source_values.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = local_values.get("GOOGLE_OAUTH_CLIENT_SECRET") or source_values.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise GmailGatewayError("The selected configuration does not contain Google OAuth client credentials.")
    updates = {
        "GOOGLE_OAUTH_CLIENT_ID": client_id,
        "GOOGLE_OAUTH_CLIENT_SECRET": client_secret,
        "GOOGLE_OAUTH_REDIRECT_URI": (
            local_values.get("GOOGLE_OAUTH_REDIRECT_URI")
            or source_values.get("GOOGLE_OAUTH_REDIRECT_URI")
            or "http://127.0.0.1:8078/integrations/google/callback"
        ),
        "VERIDEX_GOOGLE_ACCOUNT": (
            local_values.get("VERIDEX_GOOGLE_ACCOUNT")
            or source_values.get("VERIDEX_GOOGLE_ACCOUNT")
            or source_values.get("GMAIL_ACCOUNT")
            or "veridexcorp@gmail.com"
        ),
        "VERIDEX_INTEGRATION_ENCRYPTION_KEY": (
            local_values.get("VERIDEX_INTEGRATION_ENCRYPTION_KEY") or secrets.token_urlsafe(48)
        ),
        "VERIDEX_GMAIL_DB_PATH": str((LOCAL_ENV.parent / "data" / "integrations" / "gmail.db").resolve()),
    }
    _upsert_local_env(updates)


def _json_request(
    url: str,
    *,
    data: Optional[bytes] = None,
    token: str = "",
) -> Dict[str, object]:
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GmailGatewayError(f"Google OAuth request failed (HTTP {exc.code}): {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise GmailGatewayError(f"Google OAuth is unavailable: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise GmailGatewayError("Google OAuth returned an invalid response.")
    return payload


def connect(env_override: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    env = dict(env_override) if env_override is not None else _read_env(LOCAL_ENV)
    client_id = str(env.get("GOOGLE_OAUTH_CLIENT_ID") or "")
    client_secret = str(env.get("GOOGLE_OAUTH_CLIENT_SECRET") or "")
    redirect_uri = str(env.get("GOOGLE_OAUTH_REDIRECT_URI") or "http://127.0.0.1:8078/integrations/google/callback")
    expected_account = str(env.get("VERIDEX_GOOGLE_ACCOUNT") or "").strip()
    encryption_key = str(env.get("VERIDEX_INTEGRATION_ENCRYPTION_KEY") or "")
    if not client_id or not client_secret or len(encryption_key) < 32:
        raise GmailGatewayError("Veridex Gmail OAuth is not configured in .env.local.")

    redirect = urllib.parse.urlparse(redirect_uri)
    if redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "localhost"} or not redirect.port:
        raise GmailGatewayError("GOOGLE_OAUTH_REDIRECT_URI must be an HTTP loopback address with an explicit port.")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    result: Dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != (redirect.path or "/"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            query = urllib.parse.parse_qs(parsed.query)
            returned_state = str(query.get("state", [""])[0])
            if returned_state != state:
                body = (
                    "<!doctype html><meta charset='utf-8'><title>Expired Gmail connection</title>"
                    "<style>body{font:18px system-ui;max-width:640px;margin:15vh auto;padding:24px;color:#17211b}</style>"
                    "<h1>This Gmail connection attempt has expired.</h1>"
                    "<p>Use the newest Google authorization tab opened by Veridex.</p>"
                ).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            result["state"] = returned_state
            result["code"] = str(query.get("code", [""])[0])
            result["error"] = str(query.get("error", [""])[0])
            ok = bool(result["code"]) and not result["error"]
            title = "Gmail connected" if ok else "Gmail connection failed"
            message = "You can close this tab and return to Veridex." if ok else "Return to the terminal for details."
            body = (
                "<!doctype html><meta charset='utf-8'><title>Veridex Gmail</title>"
                "<style>body{font:18px system-ui;max-width:640px;margin:15vh auto;padding:24px;color:#17211b}"
                "h1{font-size:30px}</style>"
                f"<h1>{title}</h1><p>{message}</p>"
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        server = ThreadingHTTPServer((redirect.hostname, redirect.port), CallbackHandler)
    except OSError as exc:
        raise GmailGatewayError(f"The Gmail callback port {redirect.port} is unavailable. Stop the app using it and try again.") from exc
    # Account selection, unverified-app warnings, and 2FA can easily take more
    # than five minutes when a user is being guided through the first setup.
    server.timeout = 1
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "login_hint": expected_account,
        }
    )
    authorization_url = f"{AUTH_URL}?{params}"
    print(f"Opening Google authorization for {expected_account} in the dedicated Veridex Chrome profile...", flush=True)
    _open_google_authorization(authorization_url, env)
    deadline = time.monotonic() + 1800
    while not result and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if not result:
        raise GmailGatewayError("Google authorization timed out after thirty minutes.")
    if result.get("error"):
        raise GmailGatewayError(f"Google authorization was not completed: {result['error']}")
    if result.get("state") != state or not result.get("code"):
        raise GmailGatewayError("Google authorization returned an invalid callback.")

    token_payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": result["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    tokens = _json_request(TOKEN_URL, data=token_payload)
    access_token = str(tokens.get("access_token") or "")
    refresh_token = str(tokens.get("refresh_token") or "")
    if not access_token or not refresh_token:
        raise GmailGatewayError("Google did not return a reusable Gmail connection. Revoke the prior grant and try again.")
    profile = _json_request(PROFILE_URL, token=access_token)
    account_email = str(profile.get("emailAddress") or "").strip()
    if expected_account and account_email.lower() != expected_account.lower():
        raise GmailGatewayError(f"Google authorized {account_email or 'an unknown account'}, not {expected_account}.")

    gateway = GmailGateway(env=env)
    return gateway.save_connection(
        account_email=account_email,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(tokens.get("expires_in") or 3600),
        scopes=str(tokens.get("scope") or " ".join(SCOPES)).split(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect Veridex to a local Gmail account")
    parser.add_argument("--import-env", type=Path, help="One-time source for OAuth client configuration")
    parser.add_argument("--configure-only", action="store_true")
    parser.add_argument("--workspace-id", help="Store the Gmail grant only for this workspace")
    parser.add_argument("--account-email", default="", help="Optional Google account hint")
    args = parser.parse_args()
    try:
        if args.import_env:
            import_configuration(args.import_env.resolve())
            print("Imported OAuth client configuration into Veridex's local .env.local.", flush=True)
        if args.configure_only:
            return 0
        env = None
        if args.workspace_id:
            from connected_accounts import ConnectedAccounts

            root = Path(__file__).resolve().parent
            data_root = Path(os.environ.get("VERIDEX_DATA_DIR", str(root / "data"))).resolve()
            env = ConnectedAccounts(data_root, root).gmail_env(args.workspace_id, account_email=args.account_email)
        status = connect(env)
        if args.workspace_id:
            ConnectedAccounts(data_root, root).assign_gmail(args.workspace_id, str(status.get("account_email") or ""))
        print(f"Connected Veridex Gmail as {status.get('account_email')}.", flush=True)
        return 0
    except (GmailGatewayError, OSError) as exc:
        print(f"Gmail connection failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
