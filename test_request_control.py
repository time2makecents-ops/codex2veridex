from __future__ import annotations

import unittest
from threading import Thread
from time import sleep

from request_control import ActiveRequestRegistry


class ActiveRequestRegistryTests(unittest.TestCase):
    def test_cancel_targets_only_matching_active_request_and_session(self) -> None:
        registry = ActiveRequestRegistry()
        first = registry.begin("req_one", "sess_one")
        second = registry.begin("req_two", "sess_two")

        self.assertFalse(registry.cancel("req_one", "sess_wrong"))
        self.assertTrue(registry.cancel("req_one", "sess_one"))
        self.assertTrue(first.cancelled.is_set())
        self.assertFalse(second.cancelled.is_set())

        registry.finish("req_one")
        registry.finish("req_two")
        self.assertFalse(registry.is_active("req_one"))

    def test_duplicate_active_request_id_is_rejected(self) -> None:
        registry = ActiveRequestRegistry()
        registry.begin("req_duplicate", "sess_one")
        with self.assertRaises(ValueError):
            registry.begin("req_duplicate", "sess_two")

    def test_cancel_waits_for_request_registration(self) -> None:
        registry = ActiveRequestRegistry()
        registered = []

        def register_later() -> None:
            sleep(0.03)
            registered.append(registry.begin("req_late", "sess_one"))

        worker = Thread(target=register_later)
        worker.start()
        self.assertTrue(registry.cancel("req_late", "sess_one", wait_seconds=0.5))
        worker.join()
        self.assertTrue(registered[0].cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
