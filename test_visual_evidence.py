from __future__ import annotations

import unittest

from visual_evidence import normalize_lens_payload, normalize_visual_results


class VisualEvidenceTests(unittest.TestCase):
    def test_results_are_ranked_deduplicated_and_navigation_links_are_rejected(self) -> None:
        results = normalize_visual_results([
            {"title": "Sign in", "url": "https://accounts.google.com/login"},
            {"title": "Similar signed painting", "url": "https://example.org/item#detail", "snippet": "Auction record"},
            {"title": "Duplicate", "url": "https://example.org/item"},
            {"title": "Google search", "url": "https://www.google.com/search?q=painting"},
            {"title": "Museum collection", "url": "https://museum.example/works/7"},
            {"title": "Unsafe", "url": "javascript:alert(1)"},
        ])
        self.assertEqual([row["rank"] for row in results], [1, 2])
        self.assertEqual(results[0]["url"], "https://example.org/item")
        self.assertEqual(results[0]["source"], "visible_lens_result")
        self.assertEqual(results[1]["title"], "Museum collection")

    def test_google_redirects_are_unwrapped_before_deduplication(self) -> None:
        results = normalize_visual_results([
            {"title": "Auction result", "url": "https://www.google.com/url?url=https%3A%2F%2Fauction.example%2Flot%2F1"},
            {"title": "Same result", "url": "https://auction.example/lot/1"},
        ])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://auction.example/lot/1")

    def test_payload_distinguishes_completed_limited_blocked_and_failed(self) -> None:
        completed = normalize_lens_payload({"ok": True, "links": [{"title": "Match", "url": "https://example.com/match"}]})
        limited = normalize_lens_payload({"ok": True, "result_text": "Ideas for you", "links": []})
        blocked = normalize_lens_payload({"ok": True, "result_text": "Please confirm you are not a robot"})
        failed = normalize_lens_payload({"ok": False, "error": "bridge unavailable"})
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(limited["status"], "limited")
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(limited["results"], [])

    def test_raw_text_and_results_are_bounded(self) -> None:
        payload = normalize_lens_payload({
            "ok": True,
            "result_text": "x" * 20_000,
            "links": [{"title": f"Result {index}", "url": f"https://example.com/{index}"} for index in range(30)],
        })
        self.assertEqual(len(payload["raw_result_text"]), 12_000)
        self.assertEqual(len(payload["results"]), 12)


if __name__ == "__main__":
    unittest.main()
