from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class WebUiTests(unittest.TestCase):
    def test_composer_send_control_becomes_a_server_side_stop_control(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="send-button" type="button"', html)
        self.assertIn('api("/api/chat/cancel"', script)
        self.assertIn("activeRequestId", script)
        self.assertIn("stop-glyph", script)
        self.assertIn(".stop-glyph", styles)

    def test_nancy_email_cards_and_compose_controls_are_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="compose-email"', html)
        self.assertIn('id="email-compose-dialog"', html)
        self.assertIn("function gmailCard", script)
        self.assertIn("Open in Gmail", script)
        self.assertIn("View original email list", script)
        self.assertIn('sendMessage("confirm send", { attachments: [] })', script)
        self.assertIn(".email-card", styles)
        self.assertIn(".email-review", styles)

    def test_chat_and_nancy_email_drag_drop_controls_are_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="chat-drop-overlay"', html)
        self.assertIn('id="email-attach-button"', html)
        self.assertIn('id="email-file-input" type="file" multiple', html)
        self.assertIn('id="email-drop-zone"', html)
        self.assertIn('bindFileDrop(el("chat-panel"), "chat"', script)
        self.assertIn('bindFileDrop(el("email-drop-zone"), "email"', script)
        self.assertIn("email_draft: emailDraft", script)
        self.assertIn(".chat-drop-overlay", styles)
        self.assertIn(".email-attachment-picker.drag-active", styles)

    def test_voice_dictation_and_read_aloud_controls_are_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="auto-read" type="checkbox"', html)
        self.assertIn('id="voice-input"', html)
        self.assertIn("SpeechRecognitionApi", script)
        self.assertIn("speechSynthesis", script)
        self.assertIn("veridex.readAutomatically", script)
        self.assertIn("function speakMessage", script)
        self.assertIn("function toggleDictation", script)
        self.assertIn(".read-message", styles)
        self.assertIn(".voice-input.listening", styles)

    def test_address_book_recipient_suggestions_and_delivery_alerts_are_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="address-book"', html)
        self.assertIn('id="address-book-dialog"', html)
        self.assertIn('id="email-recipient-suggestions"', html)
        self.assertIn('id="delivery-alerts"', html)
        self.assertIn("function syncContacts", script)
        self.assertIn("function renderRecipientSuggestions", script)
        self.assertIn("function recipientEditDistance", script)
        self.assertIn("function recipientMatchScore", script)
        self.assertIn("chooseRecipient(contact)", script)
        self.assertIn('button.addEventListener("click", () => chooseRecipient(contact))', script)
        self.assertIn("function emailContact", script)
        self.assertIn("function deleteContact", script)
        self.assertIn('api("/api/contacts/delete"', script)
        self.assertIn("contact-email-action", styles)
        self.assertIn("contact-delete-action", styles)
        self.assertIn("function checkDeliveryFailures", script)
        self.assertIn("Fix and resend", script)
        self.assertIn("DELIVERY_POLL_INTERVAL_MS = 15_000", script)
        self.assertIn("setTimeout(checkDeliveryFailures, 5_000)", script)
        self.assertIn(".address-book-dialog", styles)
        self.assertIn(".delivery-alert", styles)

    def test_art_department_gallery_is_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="art-actions"', html)
        self.assertIn('id="open-art-gallery"', html)
        self.assertIn('id="art-gallery-dialog"', html)
        self.assertIn("function renderArtTools", script)
        self.assertIn("function renderArtGallery", script)
        self.assertIn('api(`/api/art/images?', script)
        self.assertIn('api("/api/art/images/attach"', script)
        self.assertIn('state.session?.active_room === "art_department"', script)
        self.assertIn("Attach to next message", script)
        self.assertIn(".art-gallery-dialog", styles)
        self.assertIn(".art-gallery-preview", styles)

    def test_art_studio_full_free_provider_workflow_is_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="open-art-studio"', html)
        self.assertIn('id="art-studio-dialog"', html)
        self.assertIn('id="art-reference-input" type="file" accept="image/png,image/jpeg,image/webp" multiple', html)
        self.assertIn('id="art-reference-upload"', html)
        for mode in ("create", "edit", "finish", "projects"):
            self.assertIn(f'data-art-mode="{mode}"', html)
        self.assertIn("function renderArtStudio", script)
        self.assertIn("function artReferenceCandidates", script)
        self.assertIn('previewReferenceId: ""', script)
        self.assertIn('studio.previewReferenceId = image.file_id', script)
        self.assertIn('uploadFiles(event.target.files, "art")', script)
        self.assertIn('api("/api/art/jobs"', script)
        self.assertIn("function pollArtJob", script)
        self.assertIn('api("/api/art/projects/save"', script)
        self.assertIn('classList.toggle("failed", failed)', script)
        self.assertIn('generation route${configured === 1 ? "" : "s"} ready', script)
        self.assertIn(".art-studio-dialog", styles)
        self.assertIn(".art-canvas-column", styles)
        self.assertIn(".art-job-progress.failed", styles)
        self.assertIn(".art-reference-upload", styles)
        self.assertIn(".art-control-column .art-reference-choice", styles)
        self.assertIn(".art-reference-state", styles)
        self.assertIn(".art-canvas-empty[hidden], .art-canvas[hidden], .art-job-progress[hidden]", styles)

    def test_museum_visual_analysis_workflow_is_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="museum-analysis-dialog"', html)
        self.assertIn('id="museum-photo-roles"', html)
        self.assertIn('id="museum-crop-stage"', html)
        self.assertIn("function renderMuseumTools", script)
        self.assertIn("function startMuseumAnalysis", script)
        self.assertIn('api("/api/antiques/analysis"', script)
        self.assertIn('uploadFiles(event.target.files, "museum")', script)
        self.assertIn("comparison_pairs: comparisonPairs", script)
        self.assertIn(".museum-analysis-dialog", styles)
        self.assertIn(".museum-crop-box", styles)
        self.assertIn(".museum-evidence-grid", styles)

    def test_visual_design_and_museum_are_distinct(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<strong>Visual Design</strong>", html)
        self.assertIn("Museum · Leo", html)
        self.assertIn("Quick visual check", html)

    def test_room_file_libraries_and_four_file_tray_are_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="room-file-actions"', html)
        self.assertIn('id="open-room-files"', html)
        self.assertIn('id="room-file-dialog"', html)
        self.assertIn("function renderRoomFileTools", script)
        self.assertIn("function renderRoomFileLibrary", script)
        self.assertIn('api(`/api/room/files?', script)
        self.assertIn('api("/api/room/files/attach"', script)
        self.assertIn('["lobby", "art_department"].includes(room.id)', script)
        self.assertIn(".slice(0, 4)", script)
        self.assertIn(".room-file-document-preview", styles)

    def test_hr_resume_studio_guided_workflow_is_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="resume-actions"', html)
        self.assertIn('id="resume-studio-dialog"', html)
        self.assertIn('data-resume-step="profile"', html)
        self.assertIn('id="resume-profile-save"', html)
        self.assertIn('id="resume-export"', html)
        self.assertIn("function openResumeStudio", script)
        self.assertIn('api("/api/resume/draft"', script)
        self.assertIn('api("/api/resume/export"', script)
        self.assertIn("function resolveResumeClaim", script)
        self.assertIn("Review with Nancy", script)
        self.assertIn(".resume-studio-dialog", styles)
        self.assertIn(".resume-draft-layout", styles)

    def test_infrastructure_administration_and_navigator_approval_ui_are_present(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="open-administration"', html)
        self.assertIn('id="administration-panel"', html)
        self.assertIn('id="governance-proposals"', html)
        self.assertIn('id="admin-kind"', html)
        self.assertIn("function renderAdministration", script)
        self.assertIn('api("/api/admin/proposals"', script)
        self.assertIn('api("/api/admin/proposals/apply"', script)
        self.assertIn("second_confirmation_token", script)
        self.assertIn(".administration-panel", styles)
        self.assertIn(".administration-proposal-actions", styles)


if __name__ == "__main__":
    unittest.main()
