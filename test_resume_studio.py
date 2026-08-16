import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from pypdf import PdfReader

from resume_studio import (
    ResumeStudio,
    export_bundle,
    extract_json_object,
    fetch_job_description,
    keyword_analysis,
    normalize_draft,
    profile_from_text,
    quality_review,
)


class ResumeStudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.templates = Path(__file__).resolve().parent / "resume_templates"
        self.studio = ResumeStudio(self.root, self.templates)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def sample_draft(self):
        return {
            "contact": {
                "name": "Jordan Rivera",
                "email": "jordan@example.com",
                "phone": "555-212-9191",
                "location": "Seattle, WA",
                "links": ["linkedin.com/in/jordan"],
            },
            "target_title": "Operations Manager",
            "summary": "Operations leader with verified experience improving service delivery and team execution.",
            "skills": ["Operations", "Process Improvement", "Team Leadership"],
            "experience": [{
                "title": "Operations Lead",
                "employer": "Northwind",
                "location": "Seattle, WA",
                "start_date": "2021",
                "end_date": "Present",
                "bullets": ["Led a 12-person service team and reduced verified response time by 18 percent."],
            }],
            "education": [{"credential": "B.S. Business", "school": "State University", "location": "", "date": "2020"}],
            "certifications": [],
            "projects": [],
            "awards": [],
            "federal_details": [],
            "cover_letter": "Dear Hiring Manager,\n\nI am applying for the Operations Manager role.\n\nSincerely,\nJordan Rivera",
            "linkedin_headline": "Operations Leader | Process Improvement",
            "linkedin_about": "I build reliable operations and capable teams.",
            "recruiter_email_subject": "Operations Manager application",
            "recruiter_email": "Hello, I would welcome a conversation about the role.",
            "interview_talking_points": ["Improved response time by 18 percent."],
            "unconfirmed_claims": [],
        }

    def test_profile_import_and_explicit_versioned_save(self) -> None:
        imported = profile_from_text("Jordan Rivera\njordan@example.com\n555-212-9191\nOperations Lead at Northwind\nImproved service delivery.")
        self.assertEqual(imported["contact"]["email"], "jordan@example.com")
        saved = self.studio.save_profile("ws_abc123", imported, expected_version=0)
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["profile_version"], 1)
        with self.assertRaisesRegex(ValueError, "changed in another session"):
            self.studio.save_profile("ws_abc123", imported, expected_version=0)

    def test_templates_cover_private_and_federal(self) -> None:
        templates = self.studio.list_templates()
        ids = {row["id"] for row in templates}
        self.assertTrue({"ats_classic", "modern_professional", "executive", "technical_projects", "early_career", "federal"}.issubset(ids))

    def test_keyword_analysis_is_transparent(self) -> None:
        result = keyword_analysis("Lead operations teams and improve Salesforce reporting and inventory controls.", "Operations leader with Salesforce reporting experience.")
        self.assertIn("salesforce", result["matched_keywords"])
        self.assertIn("inventory", result["missing_keywords"])
        self.assertGreater(result["coverage_percent"], 0)

    def test_unconfirmed_claim_blocks_export(self) -> None:
        draft = self.sample_draft()
        draft["unconfirmed_claims"] = [{"claim_id": "claim_1", "text": "Maybe saved 30 percent", "reason": "Needs confirmation"}]
        review = quality_review(draft)
        self.assertFalse(review["ready_to_export"])
        with self.assertRaisesRegex(ValueError, "Confirm or remove"):
            export_bundle(draft, resume_type="private", template=self.studio.list_templates()[0])

    def test_docx_pdf_and_text_exports_are_valid_and_readable(self) -> None:
        template = next(row for row in self.studio.list_templates() if row["id"] == "ats_classic")
        bundle = export_bundle(self.sample_draft(), resume_type="private", template=template)
        self.assertTrue({"resume.docx", "resume.pdf", "resume.txt", "cover-letter.docx", "cover-letter.pdf", "cover-letter.txt", "application-kit.txt"}.issubset(bundle))
        with zipfile.ZipFile(io.BytesIO(bundle["resume.docx"])) as archive:
            self.assertIn("word/document.xml", archive.namelist())
        reader = PdfReader(io.BytesIO(bundle["resume.pdf"]))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("PROFESSIONAL EXPERIENCE", text)
        self.assertIn("JORDAN RIVERA", text)
        self.assertIn("PROFESSIONAL EXPERIENCE", bundle["resume.txt"].decode("utf-8"))

    def test_model_json_fences_are_tolerated(self) -> None:
        value = extract_json_object('```json\n{"summary":"Clear"}\n```')
        self.assertEqual(normalize_draft(value)["summary"], "Clear")

    def test_job_fetch_rejects_local_and_non_https_urls(self) -> None:
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            fetch_job_description("http://example.com/job")
        with self.assertRaisesRegex(ValueError, "Local or private-network"):
            fetch_job_description("https://127.0.0.1/job")


if __name__ == "__main__":
    unittest.main()
