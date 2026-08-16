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


if __name__ == "__main__":
    unittest.main()
