"""Workspace-scoped eBay Sell API gateway with explicit mutation gates."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional

from gmail_gateway import TokenCipher, _default_env


ROOT = Path(__file__).resolve().parent
DEFAULT_EBAY_DB = ROOT / "data" / "integrations" / "ebay.db"
DEFAULT_SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
]


class EbayGatewayError(RuntimeError):
    """A safe-to-display eBay integration failure."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise EbayGatewayError(f"{name} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise EbayGatewayError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def _clean_error_payload(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")[:4000]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return " ".join(text.split())[:1000]
    if not isinstance(payload, dict):
        return " ".join(text.split())[:1000]
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    details = []
    for row in errors[:5]:
        if not isinstance(row, dict):
            continue
        message = str(row.get("longMessage") or row.get("message") or row.get("errorId") or "").strip()
        if message:
            details.append(message)
    return "; ".join(details)[:1000] or str(payload.get("error_description") or payload.get("error") or "eBay request failed")[:1000]


class EbayGateway:
    def __init__(self, env: Optional[Dict[str, str]] = None, now_fn: Callable[[], str] = _now_iso) -> None:
        self.env = dict(env) if env is not None else _default_env()
        self.now_fn = now_fn
        self.db_path = Path(str(self.env.get("VERIDEX_EBAY_DB_PATH") or DEFAULT_EBAY_DB)).resolve()
        self.environment = str(self.env.get("EBAY_ENVIRONMENT") or "sandbox").strip().lower()
        if self.environment not in {"sandbox", "production"}:
            raise EbayGatewayError("EBAY_ENVIRONMENT must be sandbox or production.")
        self.marketplace_id = str(self.env.get("EBAY_MARKETPLACE_ID") or "EBAY_US").strip().upper()
        self.expected_username = str(self.env.get("VERIDEX_EBAY_USERNAME") or "").strip()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @property
    def api_root(self) -> str:
        return "https://api.sandbox.ebay.com" if self.environment == "sandbox" else "https://api.ebay.com"

    @property
    def finances_root(self) -> str:
        return "https://apiz.sandbox.ebay.com" if self.environment == "sandbox" else "https://apiz.ebay.com"

    @property
    def identity_root(self) -> str:
        return self.api_root

    @property
    def authorization_root(self) -> str:
        return "https://auth.sandbox.ebay.com" if self.environment == "sandbox" else "https://auth.ebay.com"

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise EbayGatewayError(f"The eBay credential store is unavailable at {self.db_path}.") from exc
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ebay_connection (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    username TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    marketplace_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    access_token_ciphertext TEXT NOT NULL,
                    refresh_token_ciphertext TEXT NOT NULL,
                    access_token_expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _cipher(self) -> TokenCipher:
        return TokenCipher(str(self.env.get("VERIDEX_INTEGRATION_ENCRYPTION_KEY") or ""))

    def configured(self) -> bool:
        return bool(
            self.env.get("VERIDEX_INTEGRATION_ENCRYPTION_KEY")
            and self.env.get("EBAY_CLIENT_ID")
            and self.env.get("EBAY_CLIENT_SECRET")
            and self.env.get("EBAY_RUNAME")
        )

    def scopes(self) -> list[str]:
        configured = str(self.env.get("EBAY_OAUTH_SCOPES") or "").replace(",", " ").split()
        return list(dict.fromkeys(configured or DEFAULT_SCOPES))

    def _connection_row(self) -> Dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM ebay_connection WHERE singleton_id = 1 AND status = 'connected'"
            ).fetchone()
        if not row:
            raise EbayGatewayError("eBay is not connected to this workspace. Open Connected accounts to authorize it.")
        value = dict(row)
        if str(value.get("environment") or "") != self.environment:
            raise EbayGatewayError("The stored eBay connection belongs to a different environment. Reconnect eBay.")
        return value

    def connection_status(self) -> Dict[str, Any]:
        try:
            row = self._connection_row()
        except EbayGatewayError:
            return {
                "configured": self.configured(),
                "connected": False,
                "username": self.expected_username,
                "environment": self.environment,
                "marketplace_id": self.marketplace_id,
            }
        try:
            scopes = json.loads(str(row.get("scopes_json") or "[]"))
        except json.JSONDecodeError:
            scopes = []
        return {
            "configured": self.configured(),
            "connected": True,
            "username": str(row.get("username") or self.expected_username),
            "environment": self.environment,
            "marketplace_id": str(row.get("marketplace_id") or self.marketplace_id),
            "scopes": scopes if isinstance(scopes, list) else [],
            "updated_at": str(row.get("updated_at") or ""),
        }

    def save_connection(
        self,
        *,
        username: str,
        access_token: str,
        refresh_token: str,
        expires_in: int = 7200,
        scopes: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        seller = str(username or "").strip()
        access = str(access_token or "").strip()
        refresh = str(refresh_token or "").strip()
        if not seller or not access or not refresh:
            raise EbayGatewayError("eBay authorization did not return a complete reusable connection.")
        if self.expected_username and seller.lower() != self.expected_username.lower():
            raise EbayGatewayError(
                f"eBay authorized {seller}, not the workspace account {self.expected_username}."
            )
        cipher = self._cipher()
        now = _parse_time(self.now_fn()) or datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=max(60, int(expires_in or 7200)))).isoformat().replace("+00:00", "Z")
        values = sorted({str(value).strip() for value in (scopes or self.scopes()) if str(value).strip()})
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO ebay_connection (
                    singleton_id, username, environment, marketplace_id, scopes_json, status,
                    access_token_ciphertext, refresh_token_ciphertext, access_token_expires_at,
                    created_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, 'connected', ?, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    username = excluded.username,
                    environment = excluded.environment,
                    marketplace_id = excluded.marketplace_id,
                    scopes_json = excluded.scopes_json,
                    status = excluded.status,
                    access_token_ciphertext = excluded.access_token_ciphertext,
                    refresh_token_ciphertext = excluded.refresh_token_ciphertext,
                    access_token_expires_at = excluded.access_token_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    seller,
                    self.environment,
                    self.marketplace_id,
                    json.dumps(values),
                    cipher.encrypt(access),
                    cipher.encrypt(refresh),
                    expires_at,
                    self.now_fn(),
                    self.now_fn(),
                ),
            )
        self.expected_username = seller
        return self.connection_status()

    def disconnect(self) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM ebay_connection WHERE singleton_id = 1")

    def authorization_url(self, state: str, scopes: Optional[Iterable[str]] = None) -> str:
        client_id = str(self.env.get("EBAY_CLIENT_ID") or "").strip()
        ru_name = str(self.env.get("EBAY_RUNAME") or "").strip()
        if not client_id or not ru_name:
            raise EbayGatewayError("eBay OAuth client configuration is incomplete.")
        query = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": ru_name,
                "scope": " ".join(scopes or self.scopes()),
                "state": str(state or ""),
            }
        )
        return f"{self.authorization_root}/oauth2/authorize?{query}"

    def _client_authorization(self) -> str:
        client_id = str(self.env.get("EBAY_CLIENT_ID") or "").strip()
        client_secret = str(self.env.get("EBAY_CLIENT_SECRET") or "").strip()
        if not client_id or not client_secret:
            raise EbayGatewayError("eBay OAuth client credentials are missing.")
        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    def _token_request(self, path: str, values: Dict[str, str]) -> Dict[str, Any]:
        body = urllib.parse.urlencode(values).encode("utf-8")
        request = urllib.request.Request(
            f"{self.identity_root}{path}",
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": self._client_authorization(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EbayGatewayError(f"eBay OAuth failed (HTTP {exc.code}): {_clean_error_payload(exc.read())}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EbayGatewayError(f"eBay OAuth is unavailable: {getattr(exc, 'reason', exc)}") from exc
        except json.JSONDecodeError as exc:
            raise EbayGatewayError("eBay OAuth returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise EbayGatewayError("eBay OAuth returned an invalid response.")
        return payload

    def exchange_authorization_code(self, code: str) -> Dict[str, Any]:
        value = str(code or "").strip()
        if not value:
            raise EbayGatewayError("eBay authorization did not return a code.")
        return self._token_request(
            "/identity/v1/oauth2/token",
            {
                "grant_type": "authorization_code",
                "code": value,
                "redirect_uri": str(self.env.get("EBAY_RUNAME") or ""),
            },
        )

    def introspect(self, access_token: str) -> Dict[str, Any]:
        return self._token_request(
            "/identity/v1/oauth2/token/introspect",
            {"token": str(access_token or ""), "token_type_hint": "access_token"},
        )

    def _refresh_access_token(self, row: Dict[str, Any], cipher: TokenCipher) -> str:
        refresh_token = cipher.decrypt(str(row.get("refresh_token_ciphertext") or ""))
        tokens = self._token_request(
            "/identity/v1/oauth2/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(self.scopes()),
            },
        )
        access_token = str(tokens.get("access_token") or "").strip()
        if not access_token:
            raise EbayGatewayError("eBay did not return a refreshed access token. Reconnect the account.")
        now = _parse_time(self.now_fn()) or datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=max(60, int(tokens.get("expires_in") or 7200)))).isoformat().replace("+00:00", "Z")
        with self._connection() as connection:
            connection.execute(
                "UPDATE ebay_connection SET access_token_ciphertext = ?, access_token_expires_at = ?, updated_at = ? WHERE singleton_id = 1",
                (cipher.encrypt(access_token), expires_at, self.now_fn()),
            )
        return access_token

    def _access_token(self, *, force_refresh: bool = False) -> str:
        row = self._connection_row()
        cipher = self._cipher()
        expires_at = _parse_time(str(row.get("access_token_expires_at") or ""))
        now = _parse_time(self.now_fn()) or datetime.now(timezone.utc)
        if not force_refresh and expires_at and expires_at > now + timedelta(seconds=60):
            return cipher.decrypt(str(row.get("access_token_ciphertext") or ""))
        return self._refresh_access_token(row, cipher)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        finances: bool = False,
        retry: bool = True,
    ) -> Dict[str, Any]:
        root = self.finances_root if finances else self.api_root
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            "Content-Language": "en-US",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{root}{path}", data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
                if not raw:
                    return {}
                value = json.loads(raw.decode("utf-8"))
                return value if isinstance(value, dict) else {"items": value}
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and retry:
                self._access_token(force_refresh=True)
                return self._request(method, path, payload=payload, finances=finances, retry=False)
            raise EbayGatewayError(f"eBay API failed (HTTP {exc.code}): {_clean_error_payload(exc.read())}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EbayGatewayError(f"eBay API is unavailable: {getattr(exc, 'reason', exc)}") from exc
        except json.JSONDecodeError as exc:
            raise EbayGatewayError("eBay API returned invalid JSON.") from exc

    def inventory_items(self, *, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
        count = _bounded_int(limit, default=25, minimum=1, maximum=200, name="limit")
        start = _bounded_int(offset, default=0, minimum=0, maximum=1000000, name="offset")
        return self._request("GET", f"/sell/inventory/v1/inventory_item?limit={count}&offset={start}")

    def offers(self, *, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
        count = _bounded_int(limit, default=25, minimum=1, maximum=200, name="limit")
        start = _bounded_int(offset, default=0, minimum=0, maximum=1000000, name="offset")
        return self._request("GET", f"/sell/inventory/v1/offer?limit={count}&offset={start}")

    def orders(self, *, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
        count = _bounded_int(limit, default=25, minimum=1, maximum=200, name="limit")
        start = _bounded_int(offset, default=0, minimum=0, maximum=1000000, name="offset")
        return self._request("GET", f"/sell/fulfillment/v1/order?limit={count}&offset={start}")

    def transactions(self, *, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
        count = _bounded_int(limit, default=25, minimum=1, maximum=1000, name="limit")
        start = _bounded_int(offset, default=0, minimum=0, maximum=1000000, name="offset")
        return self._request("GET", f"/sell/finances/v1/transaction?limit={count}&offset={start}", finances=True)

    def policies(self) -> Dict[str, Any]:
        market = urllib.parse.quote(self.marketplace_id)
        return {
            "payment": self._request("GET", f"/sell/account/v1/payment_policy?marketplace_id={market}"),
            "fulfillment": self._request("GET", f"/sell/account/v1/fulfillment_policy?marketplace_id={market}"),
            "return": self._request("GET", f"/sell/account/v1/return_policy?marketplace_id={market}"),
        }

    def preview_listing(self, values: Dict[str, Any]) -> Dict[str, Any]:
        source = values if isinstance(values, dict) else {}
        required_text = {
            "sku": 50,
            "title": 80,
            "description": 500000,
            "condition": 80,
            "category_id": 40,
            "merchant_location_key": 36,
            "payment_policy_id": 64,
            "fulfillment_policy_id": 64,
            "return_policy_id": 64,
        }
        listing: Dict[str, Any] = {}
        for key, maximum in required_text.items():
            text = str(source.get(key) or "").strip()
            if not text:
                raise EbayGatewayError(f"{key} is required.")
            if len(text) > maximum:
                raise EbayGatewayError(f"{key} exceeds {maximum} characters.")
            listing[key] = text
        listing["quantity"] = _bounded_int(source.get("quantity"), default=1, minimum=0, maximum=1000000, name="quantity")
        try:
            price = Decimal(str(source.get("price") or ""))
        except InvalidOperation as exc:
            raise EbayGatewayError("price must be a valid amount.") from exc
        if price <= 0 or price > Decimal("99999999.99"):
            raise EbayGatewayError("price must be greater than zero and within eBay limits.")
        listing["price"] = format(price.quantize(Decimal("0.01")), "f")
        listing["currency"] = str(source.get("currency") or "USD").strip().upper()
        if len(listing["currency"]) != 3:
            raise EbayGatewayError("currency must be a three-letter code.")
        listing["marketplace_id"] = str(source.get("marketplace_id") or self.marketplace_id).strip().upper()
        listing["format"] = str(source.get("format") or "FIXED_PRICE").strip().upper()
        if listing["format"] != "FIXED_PRICE":
            raise EbayGatewayError("This eBay Inventory API integration supports FIXED_PRICE listings only.")
        listing["listing_duration"] = str(source.get("listing_duration") or "GTC").strip().upper()
        image_urls = source.get("image_urls") if isinstance(source.get("image_urls"), list) else []
        normalized_images = []
        for value in image_urls:
            url = str(value or "").strip()
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise EbayGatewayError("Every image URL must be a public HTTPS URL.")
            normalized_images.append(url)
        if not normalized_images:
            raise EbayGatewayError("At least one public HTTPS image URL is required.")
        listing["image_urls"] = list(dict.fromkeys(normalized_images))[:24]
        raw_aspects = source.get("aspects") if isinstance(source.get("aspects"), dict) else {}
        aspects: Dict[str, list[str]] = {}
        for key, value in raw_aspects.items():
            name = str(key or "").strip()
            items = value if isinstance(value, list) else [value]
            cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
            if name and cleaned:
                aspects[name] = cleaned
        listing["aspects"] = aspects
        return {
            "status": "preview",
            "mutation": False,
            "listing": listing,
            "required_confirmation": "Publishing creates a live eBay listing and requires confirm=true.",
        }

    def publish_listing(self, values: Dict[str, Any], *, confirmed: bool = False) -> Dict[str, Any]:
        preview = self.preview_listing(values)
        listing = preview["listing"]
        if confirmed is not True:
            return {**preview, "status": "confirmation_required", "published": False}
        sku_path = urllib.parse.quote(str(listing["sku"]), safe="")
        inventory_payload = {
            "availability": {"shipToLocationAvailability": {"quantity": listing["quantity"]}},
            "condition": listing["condition"],
            "product": {
                "title": listing["title"],
                "description": listing["description"],
                "aspects": listing["aspects"],
                "imageUrls": listing["image_urls"],
            },
        }
        self._request("PUT", f"/sell/inventory/v1/inventory_item/{sku_path}", payload=inventory_payload)
        offer_payload = {
            "sku": listing["sku"],
            "marketplaceId": listing["marketplace_id"],
            "format": listing["format"],
            "listingDescription": listing["description"],
            "availableQuantity": listing["quantity"],
            "categoryId": listing["category_id"],
            "merchantLocationKey": listing["merchant_location_key"],
            "listingPolicies": {
                "paymentPolicyId": listing["payment_policy_id"],
                "fulfillmentPolicyId": listing["fulfillment_policy_id"],
                "returnPolicyId": listing["return_policy_id"],
            },
            "pricingSummary": {"price": {"value": listing["price"], "currency": listing["currency"]}},
            "listingDuration": listing["listing_duration"],
        }
        try:
            offer = self._request("POST", "/sell/inventory/v1/offer", payload=offer_payload)
        except EbayGatewayError as exc:
            raise EbayGatewayError(
                f"Inventory item {listing['sku']} was saved, but offer creation failed: {exc}"
            ) from exc
        offer_id = str(offer.get("offerId") or "").strip()
        if not offer_id:
            raise EbayGatewayError("eBay created the inventory item but did not return an offer ID; publishing stopped.")
        try:
            published = self._request("POST", f"/sell/inventory/v1/offer/{urllib.parse.quote(offer_id, safe='')}/publish")
        except EbayGatewayError as exc:
            raise EbayGatewayError(
                f"Offer {offer_id} exists for SKU {listing['sku']}, but publishing failed; inspect the offer before retrying: {exc}"
            ) from exc
        listing_id = str(published.get("listingId") or "").strip()
        if not listing_id:
            raise EbayGatewayError(f"eBay created offer {offer_id} but did not return a listing ID; verify the offer before retrying.")
        return {
            "status": "published",
            "published": True,
            "sku": listing["sku"],
            "offer_id": offer_id,
            "listing_id": listing_id,
            "marketplace_id": listing["marketplace_id"],
            "evidence": ["inventory_item_created", "offer_created", "offer_published"],
        }

    def withdraw_listing(self, offer_id: str, *, confirmed: bool = False) -> Dict[str, Any]:
        value = str(offer_id or "").strip()
        if not value:
            raise EbayGatewayError("offer_id is required.")
        if confirmed is not True:
            return {"status": "confirmation_required", "withdrawn": False, "offer_id": value}
        result = self._request("POST", f"/sell/inventory/v1/offer/{urllib.parse.quote(value, safe='')}/withdraw")
        return {"status": "withdrawn", "withdrawn": True, "offer_id": value, "result": result}

    def update_offer(self, offer_id: str, values: Dict[str, Any], *, confirmed: bool = False) -> Dict[str, Any]:
        value = str(offer_id or "").strip()
        payload = values if isinstance(values, dict) else {}
        if not value or not payload:
            raise EbayGatewayError("offer_id and the complete revised offer are required.")
        if confirmed is not True:
            return {
                "status": "confirmation_required",
                "updated": False,
                "offer_id": value,
                "offer": payload,
                "warning": "The Inventory API update replaces the offer representation supplied by the caller.",
            }
        result = self._request(
            "PUT", f"/sell/inventory/v1/offer/{urllib.parse.quote(value, safe='')}", payload=payload
        )
        return {"status": "updated", "updated": True, "offer_id": value, "result": result}

    def eligible_buyer_offer_items(self, *, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
        count = _bounded_int(limit, default=25, minimum=1, maximum=200, name="limit")
        start = _bounded_int(offset, default=0, minimum=0, maximum=1000000, name="offset")
        return self._request(
            "GET", f"/sell/negotiation/v1/find_eligible_items?limit={count}&offset={start}"
        )

    def create_fulfillment(self, order_id: str, values: Dict[str, Any], *, confirmed: bool = False) -> Dict[str, Any]:
        order = str(order_id or "").strip()
        payload = values if isinstance(values, dict) else {}
        if not order or not payload:
            raise EbayGatewayError("order_id and fulfillment details are required.")
        if confirmed is not True:
            return {"status": "confirmation_required", "fulfilled": False, "order_id": order, "fulfillment": payload}
        result = self._request(
            "POST",
            f"/sell/fulfillment/v1/order/{urllib.parse.quote(order, safe='')}/shipping_fulfillment",
            payload=payload,
        )
        return {"status": "fulfilled", "fulfilled": True, "order_id": order, "result": result}

    def issue_refund(self, order_id: str, values: Dict[str, Any], *, confirmed: bool = False) -> Dict[str, Any]:
        order = str(order_id or "").strip()
        payload = values if isinstance(values, dict) else {}
        if not order or not payload:
            raise EbayGatewayError("order_id and refund details are required.")
        if confirmed is not True:
            return {"status": "confirmation_required", "refunded": False, "order_id": order, "refund": payload}
        result = self._request(
            "POST",
            f"/sell/fulfillment/v1/order/{urllib.parse.quote(order, safe='')}/issue_refund",
            payload=payload,
        )
        return {"status": "refund_submitted", "refunded": True, "order_id": order, "result": result}

    def send_offer_to_buyers(self, values: Dict[str, Any], *, confirmed: bool = False) -> Dict[str, Any]:
        payload = values if isinstance(values, dict) else {}
        if not payload.get("offeredItems"):
            raise EbayGatewayError("offeredItems is required.")
        if confirmed is not True:
            return {"status": "confirmation_required", "sent": False, "offer": payload}
        result = self._request("POST", "/sell/negotiation/v1/send_offer_to_interested_buyers", payload=payload)
        return {"status": "sent", "sent": True, "result": result}
