import tempfile
import unittest
from pathlib import Path
from betting_trades import add_trade, list_trades, positions


class BettingTradesTests(unittest.TestCase):
    def test_partial_sale_and_fees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            add_trade(root, {"market": "KXTEST", "action": "buy", "side": "yes", "quantity": "10", "price": "0.4", "fees": "0.2", "traded_at": "2026-01-01T00:00:00Z"})
            add_trade(root, {"market": "KXTEST", "action": "sell", "side": "yes", "quantity": "4", "price": "0.7", "fees": "0.04", "traded_at": "2026-01-02T00:00:00Z"})
            self.assertEqual(positions(root)[0], {"market": "KXTEST", "side": "yes", "quantity": "6", "cost": "2.52", "realized": "1.08", "incomplete": False})

    def test_unmatched_sell_does_not_invent_profit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            add_trade(root, {"market": "X", "action": "sell", "side": "no", "quantity": "1", "price": "0.8"})
            self.assertIsNone(positions(root)[0]["realized"])
            self.assertTrue(positions(root)[0]["incomplete"])
    def test_record_and_isolate_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            add_trade(first, {"market": "KXTEST", "action": "buy", "side": "yes", "quantity": "2", "price": "0.45", "fees": "0.03"})
            self.assertEqual(list_trades(first)[0]["price"], "0.45")
            self.assertEqual(list_trades(second), [])

    def test_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            for price in ("NaN", "1.1", "-0.1"):
                with self.assertRaises(ValueError):
                    add_trade(Path(directory), {"market": "X", "action": "buy", "side": "yes", "quantity": "1", "price": price})
