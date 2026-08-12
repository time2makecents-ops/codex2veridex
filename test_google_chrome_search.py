from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import google_chrome_search


class GoogleChromeSearchTests(unittest.TestCase):
    def test_detects_explicit_google_requests_but_not_generic_search(self) -> None:
        self.assertTrue(google_chrome_search.wants_google_search("check Google for Stella Jones"))
        self.assertTrue(google_chrome_search.wants_google_search("use a google search to find the show"))
        self.assertFalse(google_chrome_search.wants_google_search("find information about Stella Jones"))

    def test_extracts_subject_from_original_search_wording(self) -> None:
        prompt = "check social media and google for a band called stella jones from portland oregon. give me info you find"
        self.assertEqual(
            google_chrome_search.extract_google_query(prompt),
            "stella jones from portland oregon",
        )

    def test_followup_reuses_prior_google_subject_instead_of_searching_again_and(self) -> None:
        history = [
            {
                "role": "user",
                "text": "do a google search for stella jones doing a music show in eugene oregon",
            }
        ]
        followup = "do the google search again and give me upcoming shows"
        self.assertTrue(google_chrome_search.continues_google_search(followup, history))
        self.assertEqual(
            google_chrome_search.resolve_google_query(followup, history),
            "stella jones doing a music show in eugene oregon upcoming shows",
        )

    def test_related_followup_keeps_google_without_repeating_provider_name(self) -> None:
        history = [
            {
                "role": "user",
                "text": "do a google search for stella jones doing a music show in eugene oregon",
            }
        ]
        followup = "give me upcoming show dates for the musician stella jones in oregon"
        self.assertTrue(google_chrome_search.continues_google_search(followup, history))
        self.assertEqual(
            google_chrome_search.resolve_google_query(followup, history),
            "stella jones doing a music show in eugene oregon upcoming shows",
        )

    def test_gate_wording_followup_reuses_subject_without_turning_past_into_date_scope(self) -> None:
        history = [
            {
                "role": "user",
                "text": "do a google search for stella jones doing a music show in eugene oregon",
            }
        ]
        followup = "move past the gate and give me the results"
        self.assertTrue(google_chrome_search.continues_google_search(followup, history))
        self.assertEqual(
            google_chrome_search.resolve_google_query(followup, history),
            "stella jones doing a music show in eugene oregon",
        )

    def test_saved_google_evidence_carries_provider_continuity(self) -> None:
        history = [
            {
                "role": "assistant",
                "execution_evidence": [
                    {
                        "type": "google_browser_search",
                        "provider": "google_chrome_profile",
                        "query": "stella jones eugene oregon musician",
                    }
                ],
            }
        ]
        followup = "show me the results again"
        self.assertTrue(google_chrome_search.continues_google_search(followup, history))
        self.assertEqual(
            google_chrome_search.resolve_google_query(followup, history),
            "stella jones eugene oregon musician",
        )

    def test_repeated_upcoming_followup_does_not_duplicate_query_refinement(self) -> None:
        history = [
            {
                "role": "assistant",
                "execution_evidence": [
                    {
                        "type": "google_browser_search",
                        "provider": "google_chrome_profile",
                        "query": "stella jones eugene oregon upcoming shows",
                    }
                ],
            }
        ]
        self.assertEqual(
            google_chrome_search.resolve_google_query("give me upcoming show dates for Stella Jones", history),
            "stella jones eugene oregon upcoming shows",
        )

    @patch("google_chrome_search.subprocess.run")
    @patch("google_chrome_search.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe")
    def test_search_uses_node_bridge_and_returns_provider_evidence(self, _which, run) -> None:
        payload = {
            "ok": True,
            "provider": "google_chrome_profile",
            "query": "Stella Jones Eugene Oregon show",
            "profile_email": "veridexcorp@gmail.com",
            "links": [{"title": "Stella Jones", "url": "https://www.instagram.com/the.stellajones/"}],
        }
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(payload), "")

        result = google_chrome_search.search_google("search Google for Stella Jones Eugene Oregon show")

        self.assertEqual(result["provider"], "google_chrome_profile")
        self.assertEqual(run.call_args.args[0][-2:], ["search", "Stella Jones Eugene Oregon show"])
        self.assertTrue(run.call_args.kwargs["capture_output"])


if __name__ == "__main__":
    unittest.main()
