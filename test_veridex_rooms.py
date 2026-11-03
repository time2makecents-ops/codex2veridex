from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from veridex_rooms import ROOMS, configure_room_catalog, resolve_room, room_directory_text, route_room_request, rooms_payload


class VeridexRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        # Server imports may configure a real catalog during full discovery.
        # These unit tests exercise the built-in registry independently of it.
        catalog = patch("veridex_rooms._ROOM_CATALOG_PATH", None)
        catalog.start()
        self.addCleanup(catalog.stop)

    def test_configured_catalog_can_add_a_room_without_changing_builtins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rooms.json"
            path.write_text(json.dumps({"rooms": [*ROOMS, {
                "id": "test_room", "title": "Test Room",
                "default_persona": "Test Guide", "is_active": True,
            }]}), encoding="utf-8")
            configure_room_catalog(path)
            self.assertEqual(len(rooms_payload()), 23)
            self.assertEqual(route_room_request("go to Test Room")["room"]["id"], "test_room")
            self.assertEqual(len(ROOMS), 22)
            configure_room_catalog(None)
            self.assertEqual(len(rooms_payload()), 22)

    def test_registry_matches_expected_governed_rooms(self) -> None:
        rooms = rooms_payload()
        self.assertEqual(len(rooms), 22)
        self.assertEqual(resolve_room('estate sales')['default_persona'],'Boss')
        self.assertEqual(rooms[0]["id"], "lobby")
        self.assertEqual(resolve_room("art room")["id"], "art_department")
        self.assertEqual(resolve_room("Visual Design")["title"], "Visual Design")
        self.assertEqual(resolve_room("Museum")["id"], "antiques_department")
        self.assertEqual(resolve_room("Marketing & Advertising")["id"], "marketing_room")
        video = resolve_room("video production")
        self.assertEqual(video["id"], "video_production")
        self.assertEqual(video["default_persona"], "Beta")
        self.assertIn("footage review and edit decision support", video["capabilities"])
        animation = resolve_room("animation studio")
        self.assertEqual(animation["id"], "animation_studio")
        self.assertEqual(animation["default_persona"], "Beta")
        self.assertIn("voice-over and Rhubarb mouth-cue workflows", animation["capabilities"])
        antiques = resolve_room("antiques")
        self.assertEqual(antiques["id"], "antiques_department")
        self.assertEqual(antiques["default_persona"], "Leo")
        self.assertIn("inventory and provenance tracking", antiques["capabilities"])
        ebay = resolve_room("eBay room")
        self.assertEqual(ebay["id"], "ebay")
        self.assertEqual(ebay["default_persona"], "Bob")
        self.assertIn("connected eBay seller listing synchronization", ebay["capabilities"])

    def test_only_explicit_navigation_routes_to_room_change(self) -> None:
        routed = route_room_request("take me to art room")
        self.assertEqual(routed["action"], "navigate")
        self.assertEqual(routed["room"]["id"], "art_department")
        self.assertEqual(route_room_request("take me to the video room")["room"]["id"], "video_production")
        self.assertEqual(route_room_request("take me to animation studio")["room"]["id"], "animation_studio")
        self.assertEqual(route_room_request("take me to the eBay room")["room"]["id"], "ebay")
        self.assertIsNone(route_room_request("Should my design use an art department?"))
        self.assertIsNone(route_room_request("move past the gate and give me the results"))

    def test_room_directory_requests_are_deterministic(self) -> None:
        self.assertEqual(route_room_request("list room controls")["action"], "directory")
        self.assertEqual(route_room_request("can you list available rooms?")["action"], "directory")
        directory = room_directory_text()
        self.assertIn("room selector", directory)
        self.assertIn("Creative Director", directory)
        self.assertIn("Video Production", directory)
        self.assertIn("Animation Studio", directory)
        self.assertIn("Beta", directory)
        self.assertIn("eBay", directory)
        self.assertIn("Bob", directory)


if __name__ == "__main__":
    unittest.main()
