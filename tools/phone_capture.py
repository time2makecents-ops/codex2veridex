"""Short-lived, single-use screen capture requests; no image data is retained here."""

import secrets
import threading
import time


class CaptureRequests:
    def __init__(self, lifetime=120):
        self._lifetime = lifetime
        self._lock = threading.Lock()
        self._requests = {}

    def create(self, workspace_id, session_id):
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = time.monotonic()
            self._requests = {k: v for k, v in self._requests.items() if v[2] > now}
            self._requests[token] = (workspace_id, session_id, now + self._lifetime)
        return token

    def consume(self, token):
        with self._lock:
            value = self._requests.pop(str(token or ""), None)
            if not value or value[2] <= time.monotonic():
                raise ValueError("Capture request is invalid or expired.")
            return value[0], value[1]
