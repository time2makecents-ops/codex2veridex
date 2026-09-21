"""One-time local OAuth connection flow for Veridex Gmail access."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
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
    print(f"Opening Google authorization for {expected_account}...", flush=True)
    if not webbrowser.open(authorization_url, new=1):
        print(f"Open this URL in your browser:\n{authorization_url}", flush=True)
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
