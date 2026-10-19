from __future__ import annotations

import tempfile
import unittest
import io
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from antiques_department import AntiquesDepartment, ROOM_ID
from veridex_core import VeridexStore


class AntiquesDepartmentTests(unittest.TestCase):
    def service(self, root: Path) -> AntiquesDepartment:
        return AntiquesDepartment(root / "data")

    def test_shopping_mode_is_room_scoped_and_can_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            started = service.start_shopping_mode("ws_test", "sess_test", ROOM_ID)
            self.assertTrue(started["active"])
            self.assertEqual(service.may_upload_photo("ws_test", "sess_test", ROOM_ID, False), (True, "shopping_mode"))
            ended = service.end_shopping_mode("ws_test", "sess_test")
            self.assertFalse(ended["active"])
            self.assertEqual(service.may_upload_photo("ws_test", "sess_test", ROOM_ID, False), (False, "confirmation_required"))

    def test_leaving_room_ends_shopping_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            service.start_shopping_mode("ws_test", "sess_test", ROOM_ID)
            status = service.shopping_status("ws_test", "sess_test", "lobby")
            self.assertFalse(status["active"])
            self.assertEqual(status["ended_reason"], "room_exit")

    def test_max_buy_uses_lower_of_profit_model_and_percentage_cap(self) -> None:
        service = self.service(Path("."))
        result = service.calculate_max_buy(200)
        self.assertEqual(result["profit_formula_ceiling"], 105.0)
        self.assertEqual(result["percentage_cap"], 50.0)
        self.assertEqual(result["recommended_max_buy"], 50.0)

    def test_source_registry_includes_marks_and_comparable_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            source_ids = {row["id"] for row in service.bootstrap("ws_test", "sess_test", ROOM_ID)["sources"]}
            self.assertTrue({"google_lens", "ebay", "marks_project", "worthpoint"}.issubset(source_ids))

    def test_case_is_automatically_saved_and_revisioned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            first = service.save_case(
                "ws_test", "sess_test", ["file_1"],
                {"identification": "Studio pottery bowl", "category": "pottery"}, "quick",
            )
            second = service.save_case(
                "ws_test", "sess_test", ["file_1", "file_2"],
                {"identification": "Signed studio pottery bowl", "category": "pottery"}, "deep",
                case_id=first["case_id"],
            )
            self.assertEqual(len(second["revisions"]), 2)
            self.assertEqual(service.list_cases("ws_test")[0]["title"], "Signed studio pottery bowl")

    def test_case_builds_canonical_research_record_and_preserves_prior_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            first = service.save_case(
                "ws_test",
                "sess_test",
                ["file_front", "file_label"],
                {
                    "identification": "Busch NASCAR metal sign",
                    "category": "advertising sign",
                    "artist_or_maker": "Deco-Sign Products",
                    "likely_period": "November 2004",
                    "medium_or_material": "printed metal",
                    "dimensions": "23 x 31 in",
                    "product_code": "1029534",
                    "signature_or_mark": "Anheuser-Busch manufacturer's label",
                    "provenance": [{
                        "statement": "Acquired secondhand; earlier ownership is unknown.",
                        "status": "unconfirmed",
                    }],
                    "research_record": {
                        "correspondence": [{
                            "party": "Manufacturer archive",
                            "date": "2026-09-23",
                            "summary": "Inquiry sent; no response yet.",
                            "source_ref": "email:thread-1",
                        }],
                    },
                    "evidence_artifacts": [{
                        "file_id": "file_label_crop",
                        "artifact_number": 12,
                        "name": "label crop.jpg",
                        "scope_ref": "antiques_department",
                        "sha256": "a" * 64,
                    }],
                    "sourced_matches": [{
                        "source_id": "google",
                        "url": "https://example.test/catalog/1029534",
                        "claim": "Catalog record for product code 1029534.",
                    }],
                },
                "deep",
            )
            record = first["research_record"]
            self.assertEqual(record["schema_version"], 1)
            self.assertEqual(record["case_id"], first["case_id"])
            self.assertEqual(record["identity"]["artist_or_maker"], "Deco-Sign Products")
            self.assertEqual(record["identity"]["product_code"], "1029534")
            self.assertEqual(record["evidence"]["attachment_ids"], ["file_front", "file_label"])
            self.assertEqual(record["evidence"]["artifacts"][0]["file_id"], "file_label_crop")
            self.assertEqual(record["evidence"]["sources"][0]["source_id"], "google")
            self.assertEqual(record["correspondence"][0]["source_ref"], "email:thread-1")
            self.assertNotIn("research_record", first["latest_report"])
            self.assertEqual(first["revisions"][0]["research_record"], record)

            second = service.save_case(
                "ws_test",
                "sess_test",
                ["file_front", "file_label", "file_back"],
                {
                    "identification": "Busch Beer NASCAR pin-up metal sign",
                    "category": "advertising sign",
                    "correspondence": [{
                        "party": "Manufacturer archive",
                        "date": "2026-09-24",
                        "summary": "Product code was confirmed.",
                        "source_ref": "email:message-2",
                    }],
                },
                "deep",
                case_id=first["case_id"],
            )
            updated = second["research_record"]
            self.assertEqual(updated["identity"]["identification"], "Busch Beer NASCAR pin-up metal sign")
            self.assertEqual(updated["identity"]["artist_or_maker"], "Deco-Sign Products")
            self.assertEqual(updated["identity"]["product_code"], "1029534")
            self.assertEqual(updated["evidence"]["attachment_ids"], ["file_front", "file_label", "file_back"])
            self.assertEqual(len(updated["correspondence"]), 2)
            self.assertEqual(len(second["revisions"]), 2)
            self.assertNotEqual(
                second["revisions"][0]["research_record"]["latest_revision_id"],
                second["revisions"][1]["research_record"]["latest_revision_id"],
            )

    def test_existing_case_is_backfilled_on_its_next_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            case_id = "antique_legacy001"
            service._write_json(service.case_path("ws_test", case_id), {
                "case_id": case_id,
                "workspace_id": "ws_test",
                "created_at": "2026-09-20T00:00:00Z",
                "updated_at": "2026-09-20T00:00:00Z",
                "status": "researched",
                "title": "Legacy signed photograph",
                "attachment_ids": ["file_old"],
                "latest_report": {
                    "identification": "Legacy signed photograph",
                    "artist_or_maker": "Example Artist",
                    "medium_or_material": "photograph",
                    "product_code": "ARCHIVE-17",
                },
                "revisions": [{
                    "revision_id": "revision_legacy001",
                    "created_at": "2026-09-20T00:00:00Z",
                    "session_id": "sess_test",
                    "mode": "deep",
                    "attachment_ids": ["file_old"],
                    "notes": "",
                    "report": {"identification": "Legacy signed photograph"},
                }],
            })

            updated = service.save_case(
                "ws_test",
                "sess_test",
                ["file_old", "file_new"],
                {"identification": "Legacy signed photograph, label confirmed"},
                "deep",
                case_id=case_id,
            )
            record = updated["research_record"]
            self.assertEqual(record["identity"]["artist_or_maker"], "Example Artist")
            self.assertEqual(record["identity"]["medium_or_material"], "photograph")
            self.assertEqual(record["identity"]["product_code"], "ARCHIVE-17")
            self.assertEqual(record["evidence"]["attachment_ids"], ["file_old", "file_new"])
            self.assertEqual(len(updated["revisions"]), 2)

    def test_price_evidence_is_source_bound_deduplicated_and_sold_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            source_url = "https://www.ebay.com/sh/research/example"
            sources = [{
                "source_id": "ebay",
                "provider": "ebay_product_research_chrome_profile",
                "searched_at": "2026-09-19T12:00:00Z",
                "page_url": source_url,
                "result_text": "Sold $200.00; active asking $900; similar sold $120.",
            }]
            observations = [
                {
                    "match_tier": "same_model_or_edition",
                    "match_confidence": "high",
                    "match_reasons": ["Matching maker, pattern, and dimensions"],
                    "differences": ["Different example"],
                    "source_id": "ebay",
                    "source_url": source_url,
                    "listing_or_lot_id": "sold-1",
                    "title": "Matching studio pottery bowl",
                    "sale_status": "sold",
                    "price_basis": "sold_price",
                    "amount": 200,
                    "currency": "USD",
                    "sold_at": "2026-08-01T00:00:00Z",
                },
                {
                    "match_tier": "same_model_or_edition",
                    "match_confidence": "medium",
                    "source_id": "ebay",
                    "source_url": source_url,
                    "listing_or_lot_id": "active-1",
                    "title": "Active matching bowl",
                    "sale_status": "active",
                    "price_basis": "asking",
                    "amount": 900,
                    "currency": "USD",
                },
                {
                    "match_tier": "same_item_candidate",
                    "match_confidence": "low",
                    "source_id": "ebay",
                    "source_url": "https://example.invalid/not-captured",
                    "listing_or_lot_id": "limited-1",
                    "title": "Unsupported same-item claim",
                    "sale_status": "sold",
                    "price_basis": "sold_price",
                    "amount": 5000,
                    "currency": "USD",
                },
                {
                    "match_tier": "similar",
                    "match_confidence": "medium",
                    "source_id": "ebay",
                    "source_url": source_url,
                    "listing_or_lot_id": "similar-1",
                    "title": "Similar bowl",
                    "sale_status": "sold",
                    "price_basis": "sold_price",
                    "amount": 120,
                    "currency": "USD",
                },
            ]
            report = {
                "identification": "Signed studio pottery bowl",
                "category": "pottery",
                "price_observations": observations,
                "valuation": {"currency": "USD", "conservative_low": 5000, "likely_high": 9000},
            }
            first = service.save_case(
                "ws_test", "sess_test", ["file_1"], report, "quick",
                source_results=sources,
            )
            evaluation = first["latest_report"]["price_evaluation"]
            self.assertEqual(evaluation["expected_resale"]["low"], 200.0)
            self.assertEqual(evaluation["expected_resale"]["high"], 200.0)
            self.assertEqual(evaluation["expected_resale"]["match_tier"], "same_model_or_edition")
            self.assertEqual(evaluation["last_sold"]["listing_or_lot_id"], "sold-1")
            self.assertEqual(evaluation["exact_results"][0]["match_tier"], "same_item_candidate")
            self.assertEqual(evaluation["evidence_summary"]["similar"], 1)
            self.assertEqual(first["latest_report"]["valuation"]["conservative_low"], 200.0)
            self.assertEqual(first["latest_report"]["buying"]["recommended_max_buy"], 50.0)
            self.assertEqual(len(first["research_record"]["evidence"]["price_observation_ids"]), 4)
            self.assertEqual(len(first["research_record"]["evidence"]["sources"]), 4)
            limited_source = next(
                row for row in first["research_record"]["evidence"]["sources"]
                if row.get("listing_or_lot_id") == "limited-1"
            )
            self.assertEqual(limited_source["evidence_status"], "limited")

            second = service.save_case(
                "ws_test", "sess_test", ["file_1"], {
                    "identification": "Signed studio pottery bowl",
                    "category": "pottery",
                    "price_observations": observations,
                }, "deep", case_id=first["case_id"], source_results=sources,
            )
            self.assertEqual(len(service.price_observations("ws_test", first["case_id"])), 4)
            self.assertEqual(len(second["revisions"]), 2)
            self.assertIn("observation_ids", second["revisions"][-1]["report"]["price_evaluation"])
            self.assertNotIn("observations", second["revisions"][-1]["report"]["price_evaluation"])

            sold_update = {
                **observations[1],
                "sale_status": "sold",
                "price_basis": "sold_price",
                "sold_at": "2026-09-10T00:00:00Z",
            }
            third = service.save_case(
                "ws_test", "sess_test", ["file_1"], {
                    "identification": "Signed studio pottery bowl",
                    "category": "pottery",
                    "price_observations": [sold_update],
                }, "deep", case_id=first["case_id"], source_results=[{
                    **sources[0],
                    "searched_at": "2026-09-20T12:00:00Z",
                    "result_text": "Sold $900.",
                }],
            )
            self.assertEqual(len(service.price_observations("ws_test", first["case_id"])), 5)
            self.assertEqual(third["latest_report"]["price_evaluation"]["evidence_summary"]["exact_active_asking"], 0)
            self.assertEqual(third["latest_report"]["price_evaluation"]["expected_resale"]["high"], 900.0)

    def test_no_exact_match_withholds_value_and_prompts_for_similar(self) -> None:
        summary = AntiquesDepartment.summarize_price_observations([{
            "observation_id": "price_similar",
            "match_tier": "similar",
            "sale_status": "sold",
            "price_basis": "sold_price",
            "evidence_status": "supported",
            "amount": 125.0,
            "currency": "USD",
            "captured_at": "2026-09-19T12:00:00Z",
        }])
        self.assertIsNone(summary["expected_resale"]["low"])
        self.assertEqual(summary["similar_search_prompt"], "No exact match found. Search similar items?")
        self.assertEqual(summary["evidence_summary"]["exact"], 0)

    def test_realized_prices_require_known_premium_for_expected_resale(self) -> None:
        base = {
            "match_tier": "same_model_or_edition",
            "match_confidence": "medium",
            "sale_status": "sold",
            "evidence_status": "supported",
            "currency": "USD",
            "captured_at": "2026-09-19T12:00:00Z",
        }
        summary = AntiquesDepartment.summarize_price_observations([
            {**base, "observation_id": "hammer", "price_basis": "hammer", "amount": 100},
            {
                **base,
                "observation_id": "premium-known",
                "price_basis": "realized_with_premium",
                "amount": 150,
                "buyer_premium": 30,
            },
            {
                **base,
                "observation_id": "premium-unknown",
                "price_basis": "realized_with_premium",
                "amount": 180,
                "buyer_premium": None,
            },
        ])
        self.assertEqual(summary["expected_resale"]["low"], 100.0)
        self.assertEqual(summary["expected_resale"]["high"], 120.0)
        self.assertEqual(summary["expected_resale"]["median"], 110.0)
        self.assertEqual(summary["expected_resale"]["excluded_incomparable_basis_count"], 1)

    def test_structured_price_evidence_must_match_the_listing_row(self) -> None:
        service = self.service(Path("."))
        sources = [{
            "source_id": "ebay",
            "searched_at": "2026-09-20T12:00:00Z",
            "results": [
                {
                    "url": "https://example.test/item/one",
                    "listing_or_lot_id": "one",
                    "amount": 25,
                    "sale_status": "sold",
                    "title": "First item",
                },
                {
                    "url": "https://example.test/item/two",
                    "listing_or_lot_id": "two",
                    "amount": 500,
                    "sale_status": "sold",
                    "title": "Second item",
                },
            ],
        }]
        raw = {
            "match_tier": "same_model_or_edition",
            "match_confidence": "high",
            "source_id": "ebay",
            "source_url": "https://example.test/item/one",
            "listing_or_lot_id": "one",
            "title": "First item",
            "sale_status": "sold",
            "price_basis": "sold_price",
            "amount": 500,
            "currency": "USD",
        }
        wrong = service.normalize_price_observations([raw], sources)[0]
        self.assertEqual(wrong["evidence_status"], "limited")

        right = service.normalize_price_observations([{
            **raw,
            "amount": 25,
            "engagement": {"watchers": 0, "likes": 5},
        }], sources)[0]
        self.assertEqual(right["evidence_status"], "supported")
        self.assertEqual(right["engagement"], {"watchers": 0, "likes": 5})
        self.assertTrue(right["engagement_captured_at"])

    def test_low_confidence_and_engagement_do_not_change_expected_resale(self) -> None:
        eligible = {
            "observation_id": "eligible",
            "match_tier": "same_model_or_edition",
            "match_confidence": "medium",
            "sale_status": "sold",
            "price_basis": "sold_price",
            "evidence_status": "supported",
            "amount": 100,
            "currency": "USD",
            "captured_at": "2026-09-20T12:00:00Z",
            "engagement": {"watchers": 0},
        }
        low_confidence = {
            **eligible,
            "observation_id": "low-confidence",
            "match_confidence": "low",
            "amount": 900,
            "engagement": {"watchers": 1000},
        }
        first = AntiquesDepartment.summarize_price_observations([eligible, low_confidence])
        second = AntiquesDepartment.summarize_price_observations([
            {**eligible, "engagement": {"watchers": 999999}},
            {**low_confidence, "engagement": {"watchers": 0}},
        ])
        self.assertEqual(first["expected_resale"], second["expected_resale"])
        self.assertEqual(first["expected_resale"]["median"], 100.0)
        excluded = next(row for row in first["observations"] if row["observation_id"] == "low-confidence")
        self.assertFalse(excluded["valuation_eligible"])
        self.assertIn("low_match_confidence", excluded["valuation_exclusion_reasons"])
        self.assertEqual(first["evidence_summary"]["valuation_eligible_sold"], 1)

    def test_external_copy_is_jpeg_without_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            image = Image.new("RGB", (3200, 1600), "red")
            exif = Image.Exif()
            exif[0x010E] = "private note"
            image.save(source, exif=exif)
            service = self.service(root)
            target = service.prepare_external_image("ws_test", "file_1", source)
            with Image.open(target) as sanitized:
                self.assertEqual(sanitized.format, "JPEG")
                self.assertLessEqual(max(sanitized.size), 2400)
                self.assertFalse(dict(sanitized.getexif()))

    def test_server_research_requires_consent_then_saves_sourced_case(self) -> None:
        import veridex_server

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = VeridexStore(root / "data")
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            store.set_room(workspace_id, session_id, ROOM_ID)
            buffer = io.BytesIO()
            Image.new("RGB", (200, 200), "blue").save(buffer, "JPEG")
            saved = store.save_file(workspace_id, session_id, "painting.jpg", buffer.getvalue(), "image/jpeg")
            service = AntiquesDepartment(root / "data")
            payload = {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "attachment_ids": [saved["file_id"]],
                "mode": "quick",
            }
            visual = {
                "identification": "Framed landscape painting",
                "category": "art",
                "signature_or_mark": "L. Example",
                "medium_or_material": "oil on board",
                "search_query": "L Example oil landscape painting",
                "confidence": "medium",
            }
            report = {
                "identification": "Framed oil landscape",
                "category": "art",
                "artist_or_maker": "Unconfirmed L. Example",
                "signature_or_mark": "L. Example",
                "medium_or_material": "oil on board",
                "confidence": "medium",
                "valuation": {"currency": "USD", "conservative_low": 999, "likely_high": 1500},
                "price_observations": [{
                    "match_tier": "same_model_or_edition",
                    "match_confidence": "medium",
                    "match_reasons": ["Matching artist attribution, medium, and subject"],
                    "differences": ["Different example"],
                    "source_id": "ebay",
                    "platform": "eBay",
                    "source_url": "https://www.ebay.com/sh/research/example",
                    "listing_or_lot_id": "ebay-sold-200",
                    "title": "L Example oil landscape",
                    "sale_status": "sold",
                    "price_basis": "sold_price",
                    "amount": 200,
                    "currency": "USD",
                    "sold_at": "2026-08-01T00:00:00Z",
                }],
                "frame": {"assessment": "Carved wood-style frame", "currency": "USD", "resale_low": 30, "resale_high": 60},
            }
            route = {"provider": "codex_cli", "model": "gpt-5.6-sol", "reasoning_effort": "high", "task_type": "media"}
            with patch.object(veridex_server, "STORE", store), patch.object(veridex_server, "ANTIQUES", service):
                pending = veridex_server.antiques_research(payload)
                self.assertEqual(pending["status"], "confirmation_required")
                with patch.object(veridex_server, "invoke_codex", return_value={**route, "text": json.dumps(report)}) as invoke, patch.object(
                    veridex_server, "search_google_lens", return_value={
                        "provider": "google_lens_chrome_profile",
                        "status": "completed",
                        "result_text": "similar landscape",
                        "results": [{"title": "L Example oil landscape", "url": "https://example.com/lens-match"}],
                        "links": [{"title": "L Example oil landscape", "url": "https://example.com/lens-match"}],
                    }
                ), patch.object(
                    veridex_server, "search_google", return_value={"provider": "google_chrome_profile", "result_text": "artist reference", "links": []}
                ), patch.object(
                    veridex_server, "search_ebay_product_research", return_value={
                        "provider": "ebay_product_research_chrome_profile",
                        "result_text": "sold 200",
                        "page_url": "https://www.ebay.com/sh/research/example",
                        "links": [],
                    }
                ):
                    completed = veridex_server.antiques_research({**payload, "confirm_external": True})
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["report"]["buying"]["recommended_max_buy"], 50.0)
            self.assertEqual(completed["report"]["valuation"]["conservative_low"], 200.0)
            self.assertEqual(completed["report"]["price_evaluation"]["last_sold"]["listing_or_lot_id"], "ebay-sold-200")
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(invoke.call_args.args[0]["timeout_seconds"], 90)
            self.assertEqual(len(service.list_cases(workspace_id)), 1)
            self.assertEqual(service.external_uploads(workspace_id)[0]["destination"], "Google Lens")

    def test_multi_item_selection_requires_one_consent_and_saves_separate_cases(self) -> None:
        import veridex_server

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = VeridexStore(root / "data")
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            store.set_room(workspace_id, session_id, ROOM_ID)
            buffer = io.BytesIO()
            image = Image.new("RGB", (400, 200), "white")
            image.paste(Image.new("RGB", (160, 160), "red"), (20, 20))
            image.paste(Image.new("RGB", (160, 160), "blue"), (220, 20))
            image.save(buffer, "JPEG")
            source = store.save_file(workspace_id, session_id, "two-items.jpg", buffer.getvalue(), "image/jpeg")
            service = AntiquesDepartment(root / "data")
            payload = {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "batch_id": "batch_test",
                "source_file_id": source["file_id"],
                "search_mode": "visual_match",
                "research_depth": "quick",
                "selections": [
                    {"selection_id": "left", "label": "Red item", "region": {"x": .05, "y": .1, "width": .4, "height": .8}},
                    {"selection_id": "right", "label": "Blue item", "region": {"x": .55, "y": .1, "width": .4, "height": .8}},
                ],
            }
            with patch.object(veridex_server, "STORE", store), patch.object(veridex_server, "ANTIQUES", service):
                pending = veridex_server.submit_item_selection_job(payload)
                self.assertEqual(pending["status"], "confirmation_required")
                self.assertEqual(pending["pending"]["crop_count"], 2)
                self.assertEqual(service.list_cases(workspace_id), [])
                with patch.object(veridex_server, "search_google_lens", return_value={
                    "provider": "google_lens_chrome_profile",
                    "result_text": "visual candidates",
                    "links": [{"title": "Candidate", "url": "https://example.com/candidate"}],
                }) as lens:
                    submitted = veridex_server.submit_item_selection_job({**payload, "confirm_external": True})
                    completed = veridex_server.ITEM_SELECTION_JOBS.wait(submitted["job_id"], timeout=10)
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["result"]["completed_count"], 2)
            self.assertEqual(lens.call_count, 2)
            cases = service.list_cases(workspace_id)
            self.assertEqual(len(cases), 2)
            self.assertTrue(all(source["file_id"] in case["attachment_ids"] for case in cases))
            crop_ids = {item["crop"]["file_id"] for item in completed["result"]["items"]}
            self.assertTrue(all(any(file_id in crop_ids for file_id in case["attachment_ids"]) for case in cases))
            uploads = service.external_uploads(workspace_id)
            self.assertEqual(len(uploads), 2)
            self.assertTrue(all(source["file_id"] not in upload["file_ids"] for upload in uploads))
            self.assertTrue(all(set(upload["file_ids"]).issubset(crop_ids) for upload in uploads))
            crop_files = [row for row in store.list_files(workspace_id, session_id) if row["file_id"] in crop_ids]
            self.assertEqual(len(crop_files), 2)
            self.assertTrue(all(row["artifact_number"] and row["sha256"] and row["size"] > 0 for row in crop_files))
            self.assertEqual({row["metadata"]["item_selection"]["source_file_id"] for row in crop_files}, {source["file_id"]})

    def test_quick_research_stops_broad_search_and_second_model_when_lens_fails(self) -> None:
        import veridex_server

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = VeridexStore(root / "data")
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            store.set_room(workspace_id, session_id, ROOM_ID)
            buffer = io.BytesIO()
            Image.new("RGB", (200, 200), "blue").save(buffer, "JPEG")
            saved = store.save_file(workspace_id, session_id, "item.jpg", buffer.getvalue(), "image/jpeg")
            service = AntiquesDepartment(root / "data")
            visual = {
                "identification": "Decorative framed object",
                "category": "decorative arts",
                "observed_features": ["Blue field"],
                "confidence": "low",
            }
            route = {"provider": "codex_cli", "model": "gpt-5.6-sol", "reasoning_effort": "high", "task_type": "media"}

            with patch.object(veridex_server, "STORE", store), patch.object(
                veridex_server, "ANTIQUES", service
            ), patch.object(
                veridex_server,
                "search_google_lens",
                side_effect=veridex_server.GoogleChromeSearchError("Lens upload control was unavailable"),
            ) as lens, patch.object(
                veridex_server, "search_google"
            ) as google, patch.object(
                veridex_server, "search_ebay_product_research"
            ) as ebay, patch.object(
                veridex_server, "invoke_codex", return_value={**route, "text": json.dumps(visual)}
            ) as invoke:
                result = veridex_server.antiques_research({
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "attachment_ids": [saved["file_id"]],
                    "mode": "quick",
                    "confirm_external": True,
                })

            self.assertEqual(result["status"], "limited")
            self.assertEqual(result["source_errors"][0]["source_id"], "google_lens")
            self.assertEqual(invoke.call_count, 1)
            google.assert_not_called()
            ebay.assert_not_called()
            self.assertEqual(result["route"]["synthesis"]["provider"], "not_used")
            self.assertEqual(lens.call_args.kwargs["timeout"], 35)
            self.assertIn("Google Lens returned no usable", veridex_server.antiques_report_text(result["case"]))

    def test_multi_item_selection_rejects_tiny_or_out_of_bounds_regions(self) -> None:
        import veridex_server

        with self.assertRaisesRegex(ValueError, "too small"):
            veridex_server._validated_item_selections([
                {"selection_id": "tiny", "region": {"x": 0, "y": 0, "width": .005, "height": .5}},
            ], (1000, 1000))
        with self.assertRaisesRegex(ValueError, "inside"):
            veridex_server._validated_item_selections([
                {"selection_id": "outside", "region": {"x": .8, "y": .1, "width": .3, "height": .5}},
            ], (1000, 1000))

    def test_multi_item_full_research_uses_crop_for_analysis_and_source_for_case_context(self) -> None:
        import veridex_server

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = VeridexStore(root / "data")
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            store.set_room(workspace_id, session_id, ROOM_ID)
            buffer = io.BytesIO()
            Image.new("RGB", (300, 300), "green").save(buffer, "JPEG")
            source = store.save_file(workspace_id, session_id, "group.jpg", buffer.getvalue(), "image/jpeg")
            service = AntiquesDepartment(root / "data")
            payload = {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "source_file_id": source["file_id"],
                "search_mode": "full",
                "research_depth": "deep",
                "confirm_external": True,
                "selections": [{"selection_id": "one", "label": "Green item", "region": {"x": .1, "y": .1, "width": .8, "height": .8}}],
            }
            captured = []

            def fake_research(value, cancel_event=None):
                captured.append(value)
                return {"case": {"case_id": "case_one"}, "sources": [{"source_id": "google_lens"}]}

            with patch.object(veridex_server, "STORE", store), patch.object(veridex_server, "ANTIQUES", service), patch.object(
                veridex_server, "antiques_research", side_effect=fake_research
            ):
                submitted = veridex_server.submit_item_selection_job(payload)
                completed = veridex_server.ITEM_SELECTION_JOBS.wait(submitted["job_id"], timeout=10)
            self.assertEqual(completed["result"]["completed_count"], 1)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["mode"], "deep")
            self.assertEqual(len(captured[0]["attachment_ids"]), 1)
            self.assertNotEqual(captured[0]["attachment_ids"][0], source["file_id"])
            self.assertEqual(captured[0]["case_attachment_ids"][0], source["file_id"])
            self.assertEqual(captured[0]["case_attachment_ids"][1], captured[0]["attachment_ids"][0])
            self.assertEqual(captured[0]["selection_provenance"]["source_file_id"], source["file_id"])


if __name__ == "__main__":
    unittest.main()
