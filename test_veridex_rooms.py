from __future__ import annotations

import unittest

from veridex_rooms import resolve_room, room_directory_text, route_room_request, rooms_payload


class VeridexRoomTests(unittest.TestCase):
    def test_registry_matches_expected_governed_rooms(self) -> None:
        rooms = rooms_payload()
        self.assertEqual(len(rooms), 17)
        self.assertEqual(rooms[0]["id"], "lobby")
        self.assertEqual(resolve_room("art room")["id"], "art_department")
        self.assertEqual(resolve_room("Marketing & Advertising")["id"], "marketing_room")

    def test_only_explicit_navigation_routes_to_room_change(self) -> None:
        routed = route_room_request("take me to art room")
        self.assertEqual(routed["action"], "navigate")
        self.assertEqual(routed["room"]["id"], "art_department")
        self.assertIsNone(route_room_request("Should my design use an art department?"))
        self.assertIsNone(route_room_request("move past the gate and give me the results"))

    def test_room_directory_requests_are_deterministic(self) -> None:
        self.assertEqual(route_room_request("list room controls")["action"], "directory")
        self.assertEqual(route_room_request("can you list available rooms?")["action"], "directory")
        directory = room_directory_text()
        self.assertIn("room selector", directory)
        self.assertIn("Creative Director", directory)


if __name__ == "__main__":
    unittest.main()
