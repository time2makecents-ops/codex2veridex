import io
import json
import unittest
from unittest.mock import patch

import betting_scores


class ScoresTests(unittest.TestCase):
    def test_normalizes_game_and_reports_source(self):
        data = {"events": [{"id": "1", "date": "2026-10-31T12:00Z", "competitions": [{"status": {"type": {"shortDetail": "Final"}}, "competitors": [{"team": {"displayName": "Home"}, "score": "4"}, {"team": {"displayName": "Away"}, "score": "2"}]}]}]}
        with patch("betting_scores.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            result = betting_scores.scores("nhl")
        self.assertEqual(result["events"][0]["competitors"][0]["score"], "4")
        self.assertEqual(result["events"][0]["status"], "Final")
        self.assertIn("unofficial", result["source"])
        self.assertTrue(result["retrieved_at"])

    def test_rejects_unknown_league_before_network_call(self):
        with patch("betting_scores.urlopen") as request:
            with self.assertRaises(ValueError):
                betting_scores.scores("other")
            request.assert_not_called()
