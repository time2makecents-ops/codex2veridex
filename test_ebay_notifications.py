from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ebay_notifications import EbayNotificationConsumer, EbayNotificationError, EbayNotificationPoller


class _Response:
    def __init__(self, value):
        self.raw = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit=-1):
        return self.raw if limit < 0 else self.raw[:limit]


class EbayNotificationConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = {
            "VERIDEX_EBAY_NOTIFICATIONS_DB_PATH": str(self.root / "notifications.db"),
            "VERIDEX_EBAY_WORKER_URL": "https://worker.example.test",
            "VERIDEX_EBAY_WORKER_SHARED_SECRET": "shared-secret",
            "VERIDEX_EBAY_WORKER_WORKSPACE_ID": "ws_one",
            "VERIDEX_EBAY_USERNAME": "seller-one",
        }
        self.consumer = EbayNotificationConsumer(
            "ws_one",
            self.env,
            now_fn=lambda: "2026-09-24T18:00:00Z",
        )

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def event(notification_id="notification-1", topic="MARKETPLACE_ACCOUNT_DELETION", data=None, workspace_id="ws_one"):
        return {
            "id": 41,
            "notification_id": notification_id,
            "topic": topic,
            "workspace_id": workspace_id,
            "event_date": "2026-09-24T17:00:00Z",
            "received_at": "2026-09-24T17:00:01Z",
            "delivery_count": 0,
            "payload": {
                "metadata": {"topic": topic},
                "notification": {
                    "notificationId": notification_id,
                    "eventDate": "2026-09-24T17:00:00Z",
                    "data": data or {},
                },
            },
        }

    def test_deletion_event_is_recorded_without_raw_user_payload_then_acknowledged(self):
        event = self.event(data={"username": "unrelated-user", "userId": "private-user-id"})

        def urlopen(request, timeout=0):
            self.assertEqual(timeout, 30)
            self.assertEqual(request.headers["Authorization"], "Bearer shared-secret")
            if request.get_method() == "GET":
                return _Response({"workspace_id": "ws_one", "events": [event]})
            with closing(sqlite3.connect(self.env["VERIDEX_EBAY_NOTIFICATIONS_DB_PATH"])) as connection:
                stored = connection.execute(
                    "SELECT payload_json FROM ebay_notification_events WHERE notification_id = ?",
                    ("notification-1",),
                ).fetchone()
            self.assertEqual(stored, ("",), "the local transaction must commit before remote acknowledgement")
            return _Response({"acknowledged": True, "id": 41})

        with patch("ebay_notifications.urllib.request.urlopen", side_effect=urlopen):
            result = self.consumer.sync(max_events=10)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["compliance_events"], 1)
        self.assertEqual(result["acknowledged"], 1)
        self.assertEqual(result["alerts"], [])
        with closing(sqlite3.connect(self.env["VERIDEX_EBAY_NOTIFICATIONS_DB_PATH"])) as connection:
            stored = connection.execute(
                "SELECT payload_json, payload_sha256, disposition, acknowledged_at "
                "FROM ebay_notification_events WHERE notification_id = ?",
                ("notification-1",),
            ).fetchone()
        self.assertEqual(stored[0], "")
        self.assertEqual(len(stored[1]), 64)
        self.assertEqual(stored[2], "no_matching_local_user_data")
        self.assertTrue(stored[3])

    def test_order_and_message_events_become_workspace_alerts(self):
        order = self.event(
            "order-event",
            "ORDER_CONFIRMATION",
            {"order": {"orderId": "order-7", "orderLineItems": [{"listingId": "listing-2", "quantity": 1}]}},
        )
        order["id"] = 51
        message = self.event(
            "message-event",
            "NEW_MESSAGE",
            {
                "messageId": "message-8",
                "conversationId": "conversation-3",
                "listingId": "listing-2",
                "subject": "Question",
                "messageBody": "Is this still available?",
            },
        )
        message["id"] = 52
        responses = iter([
            _Response({"workspace_id": "ws_one", "events": [order, message]}),
            _Response({"acknowledged": True, "id": 51}),
            _Response({"acknowledged": True, "id": 52}),
        ])
        with patch("ebay_notifications.urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: next(responses)):
            result = self.consumer.sync(max_events=10)

        self.assertEqual(result["acknowledged"], 2)
        self.assertEqual([row["kind"] for row in result["alerts"]], ["sold", "message"])
        self.assertEqual(result["alerts"][0]["order_id"], "order-7")
        self.assertEqual(result["alerts"][1]["conversation_id"], "conversation-3")
        recent = self.consumer.recent()
        self.assertEqual(len(recent), 2)
        self.assertNotEqual(recent[0]["kind"], "compliance")
        with closing(sqlite3.connect(self.env["VERIDEX_EBAY_NOTIFICATIONS_DB_PATH"])) as connection:
            stored_payloads = connection.execute(
                "SELECT payload_json FROM ebay_notification_events ORDER BY notification_id"
            ).fetchall()
        self.assertEqual(stored_payloads, [("",), ("",)])

    def test_wrong_workspace_event_is_not_stored_or_acknowledged(self):
        event = self.event(workspace_id="ws_two")
        with patch(
            "ebay_notifications.urllib.request.urlopen",
            return_value=_Response({"workspace_id": "ws_one", "events": [event]}),
        ) as urlopen:
            result = self.consumer.sync(max_events=10)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["acknowledged"], 0)
        self.assertRegex(result["errors"][0]["error"], "different workspace")
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(self.consumer.status()["stored_events"], 0)

    def test_replayed_notification_is_idempotent(self):
        event = self.event(data={"username": "unrelated-user"})

        def run_once():
            responses = iter([
                _Response({"workspace_id": "ws_one", "events": [event]}),
                _Response({"acknowledged": True, "id": 41}),
            ])
            with patch("ebay_notifications.urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: next(responses)):
                return self.consumer.sync(max_events=10)

        first = run_once()
        second = run_once()
        self.assertEqual(first["new_events"], 1)
        self.assertEqual(second["new_events"], 0)
        self.assertEqual(self.consumer.status()["stored_events"], 1)

    def test_ack_failure_keeps_durable_local_copy_and_reports_partial(self):
        event = self.event(data={"username": "unrelated-user"})
        responses = iter([
            _Response({"workspace_id": "ws_one", "events": [event]}),
            _Response({"acknowledged": False, "id": 41}),
        ])
        with patch("ebay_notifications.urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: next(responses)):
            result = self.consumer.sync(max_events=10)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["acknowledged"], 0)
        self.assertEqual(self.consumer.status()["stored_events"], 1)

    def test_worker_workspace_binding_is_mandatory(self):
        env = {**self.env, "VERIDEX_EBAY_WORKER_WORKSPACE_ID": "ws_two"}
        consumer = EbayNotificationConsumer("ws_one", env)
        self.assertFalse(consumer.configured())
        with self.assertRaisesRegex(EbayNotificationError, "different workspace"):
            consumer.sync()

    def test_sync_is_serialized_for_the_same_workspace_database(self):
        first_entered = threading.Event()
        release_first = threading.Event()
        calls = []

        def request(_method, _path):
            calls.append(threading.current_thread().name)
            if len(calls) == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(2))
            return {"workspace_id": "ws_one", "events": []}

        first = EbayNotificationConsumer("ws_one", self.env)
        second = EbayNotificationConsumer("ws_one", self.env)
        first._request_json = request
        second._request_json = request
        workers = [
            threading.Thread(target=consumer.sync, name=f"sync-{index}")
            for index, consumer in enumerate((first, second), start=1)
        ]
        workers[0].start()
        self.assertTrue(first_entered.wait(1))
        workers[1].start()
        self.assertEqual(len(calls), 1)
        release_first.set()
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(calls), 2)


class EbayNotificationPollerTests(unittest.TestCase):
    class _Consumer:
        def __init__(self, workspace_id, completed, *, fail=False):
            self.workspace_id = workspace_id
            self.completed = completed
            self.fail = fail

        def configured(self):
            return True

        def sync(self, *, max_events):
            if self.fail:
                raise EbayNotificationError("temporary relay failure")
            self.completed.set()
            return {
                "status": "complete",
                "processed": 1,
                "new_events": 1,
                "acknowledged": 1,
                "alerts": [{"kind": "message"}],
                "errors": [],
                "max_events": max_events,
            }

    def test_background_poller_runs_immediately_and_stops_cleanly(self):
        completed = threading.Event()
        poller = EbayNotificationPoller(
            lambda: ["ws_one"],
            lambda workspace_id: self._Consumer(workspace_id, completed),
            interval_seconds=15,
            max_events=25,
            now_fn=lambda: "2026-09-24T20:00:00Z",
        )

        self.assertTrue(poller.start())
        self.assertTrue(completed.wait(1))
        state = poller.status("ws_one")
        self.assertTrue(state["running"])
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["acknowledged"], 1)
        self.assertTrue(poller.stop(timeout=1))
        self.assertFalse(poller.status("ws_one")["running"])

    def test_one_workspace_failure_does_not_block_another_workspace(self):
        completed = threading.Event()

        def consumer(workspace_id):
            return self._Consumer(workspace_id, completed, fail=workspace_id == "ws_one")

        poller = EbayNotificationPoller(
            lambda: ["ws_one", "ws_two"],
            consumer,
            interval_seconds=15,
            now_fn=lambda: "2026-09-24T20:00:00Z",
        )
        result = poller.poll_once()

        self.assertEqual(result, {"checked": 2, "failures": 1, "alerts": 1})
        self.assertEqual(poller.status("ws_one")["status"], "failed")
        self.assertEqual(poller.status("ws_two")["status"], "complete")

    def test_wake_requests_an_early_followup_poll(self):
        first = threading.Event()
        second = threading.Event()
        calls = []

        class Consumer:
            def configured(self):
                return True

            def sync(self, *, max_events):
                calls.append(max_events)
                (first if len(calls) == 1 else second).set()
                return {
                    "status": "complete",
                    "processed": 0,
                    "new_events": 0,
                    "acknowledged": 0,
                    "alerts": [],
                    "errors": [],
                }

        poller = EbayNotificationPoller(
            lambda: ["ws_one"],
            lambda _workspace_id: Consumer(),
            interval_seconds=15,
        )
        poller.start()
        self.assertTrue(first.wait(1))
        poller.wake()
        self.assertTrue(second.wait(1))
        self.assertTrue(poller.stop(timeout=1))
        self.assertGreaterEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
