"""Workspace-scoped manual prediction-market trade journal."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


def connect(workspace_dir: Path):
    path = workspace_dir / "integrations" / "betting.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, market TEXT NOT NULL, side TEXT NOT NULL, action TEXT NOT NULL, quantity TEXT NOT NULL, price TEXT NOT NULL, fees TEXT NOT NULL, traded_at TEXT NOT NULL)")
    return db


def add_trade(workspace_dir: Path, data: dict) -> dict:
    market = str(data.get("market") or "").strip()
    side = str(data.get("side") or "").lower()
    action = str(data.get("action") or "").lower()
    if not market or len(market) > 200 or side not in {"yes", "no"} or action not in {"buy", "sell"}:
        raise ValueError("Enter a market, side, and buy or sell action.")
    try:
        quantity, price, fees = (Decimal(str(data.get(key, "0"))) for key in ("quantity", "price", "fees"))
        if not all(x.is_finite() for x in (quantity, price, fees)) or quantity <= 0 or not 0 <= price <= 1 or fees < 0:
            raise ValueError("Quantity must be positive, price between $0 and $1, and fees nonnegative.")
    except InvalidOperation as exc:
        raise ValueError("Enter valid numeric amounts.") from exc
    traded_at = str(data.get("traded_at") or datetime.now(timezone.utc).isoformat())
    try:
        parsed = datetime.fromisoformat(traded_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Trade time must include a timezone.")
    except ValueError as exc:
        raise ValueError("Enter a valid trade time with timezone.") from exc
    with closing(connect(workspace_dir)) as db:
        with db:
            cursor = db.execute("INSERT INTO trades (market, side, action, quantity, price, fees, traded_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (market, side, action, str(quantity), str(price), str(fees), traded_at))
            return dict(db.execute("SELECT * FROM trades WHERE id = ?", (cursor.lastrowid,)).fetchone())


def list_trades(workspace_dir: Path) -> list:
    with closing(connect(workspace_dir)) as db:
        return [dict(row) for row in db.execute("SELECT * FROM trades ORDER BY traded_at DESC, id DESC LIMIT 500")]


def positions(workspace_dir: Path) -> list:
    with closing(connect(workspace_dir)) as db:
        trades = [dict(row) for row in db.execute("SELECT * FROM trades")]
    trades.sort(key=lambda row: (datetime.fromisoformat(row["traded_at"].replace("Z", "+00:00")), row["id"]))
    groups = {}
    for trade in trades:
        key = (trade["market"].strip().casefold(), trade["side"])
        row = groups.setdefault(key, {"market": trade["market"], "side": trade["side"], "quantity": Decimal(0), "cost": Decimal(0), "realized": Decimal(0), "incomplete": False})
        quantity, price, fees = (Decimal(trade[name]) for name in ("quantity", "price", "fees"))
        if trade["action"] == "buy":
            row["quantity"] += quantity
            row["cost"] += quantity * price + fees
        elif quantity > row["quantity"]:
            row["quantity"] -= quantity
            row["incomplete"] = True
        elif row["quantity"] > 0:
            basis = row["cost"] * quantity / row["quantity"]
            row["quantity"] -= quantity
            row["cost"] -= basis
            row["realized"] += quantity * price - fees - basis
    return [{"market": row["market"], "side": row["side"], "quantity": str(row["quantity"]), "cost": None if row["incomplete"] else str(row["cost"].quantize(Decimal("0.01"))), "realized": None if row["incomplete"] else str(row["realized"].quantize(Decimal("0.01"))), "incomplete": row["incomplete"]} for row in groups.values()]
