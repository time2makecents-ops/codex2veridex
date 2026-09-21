import hashlib
import tempfile
import threading
import time
import unittest
from pathlib import Path

from openpyxl import Workbook

from price_search_controller import (
    PriceSearchController,
    PriceSearchJobManager,
    SEARCH_PRESETS,
    SearchRequest,
    exact_query_variants,
    provider_spelling_suggestion,
    workbook_search_subjects,
)


class PriceSearchControllerTests(unittest.TestCase):
    def test_exact_query_variants_reduce_uncertain_terms_and_add_marketplace_aliases(self) -> None:
        variants = exact_query_variants("Michael Jackson Cirque du Soleil magazine")
        self.assertEqual(
            [row["query"] for row in variants],
            [
                "Michael Jackson Cirque du Soleil magazine",
                "Michael Jackson Cirque du Soleil",
                "Michael Jackson Cirque du Soleil souvenir program",
                "Michael Jackson Cirque du Soleil program booklet",
            ],
        )
        self.assertEqual([row["rank"] for row in variants], [1, 2, 3, 4])

        typo = exact_query_variants("michael jackson cirque du soleil mazine", limit=2)
        self.assertEqual(typo[0]["query"], "michael jackson cirque du soleil magazine")
        self.assertEqual(typo[0]["kind"], "corrected_full")

        alternatives = exact_query_variants("Sport Chef Golf Bag Wine/Champagne Chiller")
        self.assertIn("Sport Chef Golf Bag Wine Chiller", [row["query"] for row in alternatives])
        self.assertIn("Sport Chef Golf Bag Champagne Chiller", [row["query"] for row in alternatives])

        blowtorch = [row["query"] for row in exact_query_variants("Antique brass gasoline blowtorch / blowlamp")]
        self.assertEqual(blowtorch, [
            "Antique brass gasoline blowtorch / blowlamp",
            "Antique brass gasoline blowtorch",
            "Antique brass gasoline blowlamp",
        ])

        uncertain = exact_query_variants("Disney Mickey boxed T-shirt or textile item")
        self.assertIn("Disney Mickey boxed T-shirt", [row["query"] for row in uncertain])

    def test_provider_spelling_suggestion_is_bounded_to_related_query(self) -> None:
        self.assertEqual(
            provider_spelling_suggestion(
                'Did you mean: "Sport Chek Golf Bag Wine Chiller sold price"',
                "Sport Chef Golf Bag Wine Chiller",
            ),
            "Sport Chek Golf Bag Wine Chiller",
        )
        self.assertEqual(
            provider_spelling_suggestion("Completely unrelated antique vase", "Sport Chef Golf Bag Wine Chiller"),
            "",
        )
        self.assertEqual(
            provider_spelling_suggestion(
                "Sport Chek/Chek Golf Bag wine cooler sold price",
                "Sport Chef/Chek Golf Bag wine cooler",
            ),
            "Sport Chek Golf Bag wine cooler",
        )

    def test_presets_and_request_validation(self) -> None:
        self.assertEqual(SEARCH_PRESETS["fast"], {"exact_seconds": 90, "all_likeness_seconds": 360})
        self.assertEqual(SEARCH_PRESETS["standard"], {"exact_seconds": 180, "all_likeness_seconds": 720})
        self.assertEqual(SEARCH_PRESETS["extended"], {"exact_seconds": 300, "all_likeness_seconds": 1200})
        self.assertEqual(SearchRequest.from_value({"query": "Roseville vase"}).scope, "exact")
        self.assertTrue(SearchRequest.from_value({"query": "Roseville vase", "scope": "all-likeness"}).similar_approved)
        with self.assertRaisesRegex(ValueError, "scope"):
            SearchRequest.from_value({"query": "vase", "scope": "similar_only"})

    def test_exact_is_default_and_similar_candidates_are_withheld(self) -> None:
        called = []

        def exact(request, context):
            called.append(context.phase)
            return {"candidates": [
                {"match_tier": "similar", "listing_or_lot_id": "similar-1", "title": "Looks close"},
                {"match_tier": "same_model_or_edition", "listing_or_lot_id": "exact-1", "title": "Catalog match"},
            ]}

        def similar(_request, _context):
            called.append("should_not_run")
            return []

        result = PriceSearchController().run({"item_id": "7", "query": "marked vase"}, exact, similar)
        self.assertEqual(called, ["exact"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([row["listing_or_lot_id"] for row in result["exact_results"]], ["exact-1"])
        self.assertEqual(result["similar_results"], [])
        self.assertEqual(result["ordered_results"][0]["match_tier"], "same_model_or_edition")

    def test_no_exact_result_requires_approval_before_similar_search(self) -> None:
        result = PriceSearchController().run(
            {"query": "unknown ceramic", "scope": "exact", "preset": "fast"},
            lambda _request, _context: [{"match_tier": "similar", "listing_or_lot_id": "withheld"}],
        )
        self.assertEqual(result["status"], "similar_approval_required")
        self.assertEqual(result["similar_results"], [])
        self.assertEqual(result["similar_search_prompt"], "No exact match found. Search similar items?")

    def test_all_likeness_runs_exact_first_and_deduplicates_results(self) -> None:
        called = []

        def exact(_request, context):
            called.append(context.phase)
            return {"candidates": [
                {"match_tier": "same_item_candidate", "source_url": "https://example.test/1", "title": "Exact"},
            ], "sources": [{"source_id": "exact-source"}]}

        def similar(_request, context):
            called.append(context.phase)
            return {"candidates": [
                {"match_tier": "similar", "source_url": "https://example.test/2", "title": "Similar"},
                {"match_tier": "similar", "source_url": "https://example.test/1", "title": "Duplicate weaker tier"},
            ], "sources": [{"source_id": "similar-source"}]}

        result = PriceSearchController().run(
            {"item_id": "A", "query": "signed print", "scope": "all_likeness", "preset": "standard"},
            exact,
            similar,
        )
        self.assertEqual(called, ["exact", "similar"])
        self.assertEqual([row["source_url"] for row in result["ordered_results"]], ["https://example.test/1", "https://example.test/2"])
        self.assertEqual(result["ordered_results"][0]["match_tier"], "same_item_candidate")
        self.assertEqual(result["ordered_results"][1]["match_tier"], "similar")
        self.assertEqual(len(result["sources"]), 2)

    def test_timeout_returns_truthful_partial_state(self) -> None:
        clock_value = [0.0]

        def clock():
            return clock_value[0]

        def exact(_request, context):
            clock_value[0] = 91.0
            context.checkpoint()
            return []

        result = PriceSearchController().run(
            {"query": "vintage clock", "preset": "fast"},
            exact,
            monotonic=clock,
        )
        self.assertEqual(result["status"], "timed_out")
        self.assertIn("budget expired", result["message"])
        self.assertEqual(result["ordered_results"], [])

    def test_timeout_after_adapter_return_retains_partial_evidence(self) -> None:
        clock_value = [0.0]

        def clock():
            return clock_value[0]

        def exact(_request, _context):
            clock_value[0] = 91.0
            return {
                "candidates": [{
                    "match_tier": "same_item_candidate",
                    "source_url": "https://example.test/partial",
                    "title": "Collected before timeout",
                }],
                "sources": [{"source_id": "ebay", "query_variant": "partial query"}],
                "query_variants": [{"rank": 1, "query": "partial query", "kind": "full"}],
            }

        result = PriceSearchController().run(
            {"query": "vintage clock", "preset": "fast"},
            exact,
            monotonic=clock,
        )

        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(len(result["exact_results"]), 1)
        self.assertEqual(result["sources"][0]["source_id"], "ebay")
        self.assertEqual(result["phases"][0]["status"], "timed_out")
        self.assertEqual(result["phases"][0]["metadata"]["query_variants"][0]["query"], "partial query")

    def test_async_job_reports_progress_and_cancels_cooperatively(self) -> None:
        manager = PriceSearchJobManager(workers=1)
        entered = threading.Event()

        def exact(_request, context):
            entered.set()
            while True:
                context.checkpoint()
                time.sleep(0.005)

        job = manager.submit({"query": "cancel me", "preset": "fast"}, exact)
        self.assertTrue(entered.wait(timeout=2))
        canceling = manager.cancel(job["job_id"])
        self.assertEqual(canceling["status"], "canceling")
        finished = manager.wait(job["job_id"], timeout=2)
        self.assertEqual(finished["status"], "canceled")
        self.assertEqual(finished["progress"], 100)

    def test_workbook_loader_is_read_only_and_builds_search_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "GS2.xlsx"
            workbook = Workbook()
            inventory = workbook.active
            inventory.title = "Inventory"
            inventory.append(("Item #", "Image", "Description", "Maker / Brand", "Title / Model"))
            inventory.append((12, "", "Blue art pottery vase", "Roseville", "Pinecone 842-8"))
            inventory.append((13, "", "", "", ""))
            workbook.save(source)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            result = workbook_search_subjects(source)
            self.assertEqual(result["subject_count"], 1)
            self.assertEqual(result["subjects"][0]["item_id"], "12")
            self.assertEqual(result["subjects"][0]["query"], "Roseville Pinecone 842-8 Blue art pottery vase")
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)


if __name__ == "__main__":
    unittest.main()
