"""Workspace-scoped account assignments for local Veridex integrations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from ebay_gateway import EbayGateway
from gmail_gateway import GmailGateway, _default_env


class ConnectedAccountError(RuntimeError):
    pass


class ConnectedAccounts:
    def __init__(self, data_root: Path, repo_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.repo_root = Path(repo_root).resolve()

    def _workspace_dir(self, workspace_id: str) -> Path:
        value = str(workspace_id or "").strip()
        path = (self.data_root / "workspaces" / value).resolve()
        if not value or self.data_root not in path.parents or not (path / "workspace.json").is_file():
            raise ConnectedAccountError("Unknown workspace.")
        return path

    def _path(self, workspace_id: str) -> Path:
        return self._workspace_dir(workspace_id) / "integrations" / "connected_accounts.json"

    def read(self, workspace_id: str) -> Dict[str, Any]:
        path = self._path(workspace_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def write(self, workspace_id: str, value: Dict[str, Any]) -> Dict[str, Any]:
        path = self._path(workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(path)
        return value

    def instagram_config(self, workspace_id: str, *, required: bool = False) -> Dict[str, Any]:
        stored = self.read(workspace_id).get("instagram")
        if not isinstance(stored, dict) or not stored.get("assigned"):
            if required:
                raise ConnectedAccountError("Instagram is not assigned to this workspace. Open Connected accounts to connect it.")
            return {}
        return dict(stored)

    def assign_instagram(self, workspace_id: str, username: str, *, profile_dir: str = "", debug_port: int = 0) -> Dict[str, Any]:
        handle = str(username or "").strip().lstrip("@")
        if not handle:
            raise ConnectedAccountError("Instagram username is required.")
        for workspace_path in (self.data_root / "workspaces").glob("*/integrations/connected_accounts.json"):
            other_id = workspace_path.parents[1].name
            if other_id == workspace_id:
                continue
            try:
                other = json.loads(workspace_path.read_text(encoding="utf-8")).get("instagram", {})
            except (OSError, json.JSONDecodeError):
                other = {}
            if isinstance(other, dict) and str(other.get("username") or "").lower() == handle.lower() and other.get("assigned"):
                raise ConnectedAccountError(f"@{handle} is already assigned to another workspace. Unassign it there first.")
        data = self.read(workspace_id)
        existing = data.get("instagram") if isinstance(data.get("instagram"), dict) else {}
        profile = Path(profile_dir).resolve() if profile_dir else self.repo_root / "data" / "browser_profiles" / "instagram" / workspace_id
        data["instagram"] = {
            "assigned": True,
            "username": handle,
            "profile_dir": str(profile.resolve()),
            "debug_port": int(debug_port or existing.get("debug_port") or self._instagram_port(workspace_id)),
        }
        self.write(workspace_id, data)
        return dict(data["instagram"])

    def unassign_instagram(self, workspace_id: str) -> None:
        data = self.read(workspace_id)
        data.pop("instagram", None)
        self.write(workspace_id, data)

    def _instagram_port(self, workspace_id: str) -> int:
        # Stable workspace-specific port; collisions are exceptionally unlikely and
        # detected by Chrome if they occur.
        return 9300 + (sum(ord(ch) for ch in workspace_id) % 500)

    def instagram_env(self, workspace_id: str, *, username: str = "", password: str = "") -> Dict[str, str]:
        config = self.instagram_config(workspace_id, required=True)
        env = {
            "VERIDEX_INSTAGRAM_PROFILE_DIR": str(config["profile_dir"]),
            "VERIDEX_INSTAGRAM_DEBUG_PORT": str(config["debug_port"]),
            "INSTAGRAM_USERNAME": str(username or config.get("username") or ""),
        }
        if password:
            env["INSTAGRAM_PASSWORD"] = password
        return env

    def gmail_env(self, workspace_id: str, *, account_email: str = "") -> Dict[str, str]:
        workspace_dir = self._workspace_dir(workspace_id)
        base = _default_env()
        stored = self.read(workspace_id).get("gmail")
        gmail = stored if isinstance(stored, dict) else {}
        base["VERIDEX_GMAIL_DB_PATH"] = str(workspace_dir / "integrations" / "gmail.db")
        base["VERIDEX_GOOGLE_ACCOUNT"] = str(account_email or gmail.get("account_email") or "")
        return base

    def gmail(self, workspace_id: str) -> GmailGateway:
        return GmailGateway(env=self.gmail_env(workspace_id))

    def assign_gmail(self, workspace_id: str, account_email: str) -> Dict[str, Any]:
        email = str(account_email or "").strip()
        for workspace_path in (self.data_root / "workspaces").glob("*/integrations/connected_accounts.json"):
            other_id = workspace_path.parents[1].name
            if other_id == workspace_id:
                continue
            try:
                other = json.loads(workspace_path.read_text(encoding="utf-8")).get("gmail", {})
            except (OSError, json.JSONDecodeError):
                other = {}
            if isinstance(other, dict) and str(other.get("account_email") or "").lower() == email.lower() and other.get("assigned"):
                raise ConnectedAccountError(f"{email} is already assigned to another workspace. Unassign it there first.")
        data = self.read(workspace_id)
        data["gmail"] = {"assigned": True, "account_email": email}
        self.write(workspace_id, data)
        return dict(data["gmail"])

    def unassign_gmail(self, workspace_id: str) -> None:
        data = self.read(workspace_id)
        data.pop("gmail", None)
        self.write(workspace_id, data)

    def ebay_config(self, workspace_id: str, *, required: bool = False) -> Dict[str, Any]:
        stored = self.read(workspace_id).get("ebay")
        if not isinstance(stored, dict) or not stored.get("assigned"):
            if required:
                raise ConnectedAccountError("eBay is not assigned to this workspace. Open Connected accounts to connect it.")
            return {}
        return dict(stored)

    def assign_ebay(
        self,
        workspace_id: str,
        username: str,
        *,
        environment: str = "sandbox",
        marketplace_id: str = "EBAY_US",
    ) -> Dict[str, Any]:
        seller = str(username or "").strip()
        target_environment = str(environment or "sandbox").strip().lower()
        market = str(marketplace_id or "EBAY_US").strip().upper()
        if not seller:
            raise ConnectedAccountError("eBay username is required.")
        if target_environment not in {"sandbox", "production"}:
            raise ConnectedAccountError("eBay environment must be sandbox or production.")
        for workspace_path in (self.data_root / "workspaces").glob("*/integrations/connected_accounts.json"):
            other_id = workspace_path.parents[1].name
            if other_id == workspace_id:
                continue
            try:
                other = json.loads(workspace_path.read_text(encoding="utf-8")).get("ebay", {})
            except (OSError, json.JSONDecodeError):
                other = {}
            if (
                isinstance(other, dict)
                and other.get("assigned")
                and str(other.get("username") or "").lower() == seller.lower()
                and str(other.get("environment") or "sandbox").lower() == target_environment
            ):
                raise ConnectedAccountError(
                    f"eBay {target_environment} account {seller} is already assigned to another workspace."
                )
        data = self.read(workspace_id)
        data["ebay"] = {
            "assigned": True,
            "username": seller,
            "environment": target_environment,
            "marketplace_id": market,
        }
        self.write(workspace_id, data)
        return dict(data["ebay"])

    def unassign_ebay(self, workspace_id: str) -> None:
        data = self.read(workspace_id)
        data.pop("ebay", None)
        self.write(workspace_id, data)

    def ebay_env(
        self,
        workspace_id: str,
        *,
        username: str = "",
        environment: str = "",
        marketplace_id: str = "",
        required: bool = False,
    ) -> Dict[str, str]:
        workspace_dir = self._workspace_dir(workspace_id)
        config = self.ebay_config(workspace_id, required=required)
        base = _default_env()
        base["VERIDEX_EBAY_DB_PATH"] = str(workspace_dir / "integrations" / "ebay.db")
        base["VERIDEX_EBAY_USERNAME"] = str(username or config.get("username") or "")
        base["EBAY_ENVIRONMENT"] = str(environment or config.get("environment") or base.get("EBAY_ENVIRONMENT") or "sandbox")
        base["EBAY_MARKETPLACE_ID"] = str(marketplace_id or config.get("marketplace_id") or base.get("EBAY_MARKETPLACE_ID") or "EBAY_US")
        return base

    def ebay(self, workspace_id: str) -> EbayGateway:
        return EbayGateway(env=self.ebay_env(workspace_id, required=True))

    def public_status(self, workspace_id: str) -> Dict[str, Any]:
        instagram = self.instagram_config(workspace_id)
        gmail_config = self.read(workspace_id).get("gmail")
        gmail = gmail_config if isinstance(gmail_config, dict) else {}
        ebay = self.ebay_config(workspace_id)
        gmail_status = self.gmail(workspace_id).connection_status() if gmail.get("assigned") else {
            "configured": bool(self.gmail_env(workspace_id).get("GOOGLE_OAUTH_CLIENT_ID")),
            "connected": False,
            "account_email": "",
        }
        ebay_status = self.ebay(workspace_id).connection_status() if ebay else {
            "configured": EbayGateway(env=self.ebay_env(workspace_id)).configured(),
            "connected": False,
            "username": "",
            "environment": str(self.ebay_env(workspace_id).get("EBAY_ENVIRONMENT") or "sandbox"),
            "marketplace_id": str(self.ebay_env(workspace_id).get("EBAY_MARKETPLACE_ID") or "EBAY_US"),
        }
        return {
            "workspace_id": workspace_id,
            "isolation": "strict",
            "instagram": {
                "assigned": bool(instagram),
                "username": str(instagram.get("username") or ""),
                "connected": False,
            },
            "gmail": {**gmail_status, "assigned": bool(gmail.get("assigned"))},
            "ebay": {**ebay_status, "assigned": bool(ebay)},
        }
