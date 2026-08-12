"""Thread-safe lifecycle and cancellation controls for active chat requests."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Condition, Event, Lock
from time import monotonic
from typing import Dict


class RequestCancelled(RuntimeError):
    """Raised when the user stops an active Veridex request."""


@dataclass
class ActiveRequest:
    request_id: str
    session_id: str
    cancelled: Event


class ActiveRequestRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._changed = Condition(self._lock)
        self._requests: Dict[str, ActiveRequest] = {}

    def begin(self, request_id: str, session_id: str) -> ActiveRequest:
        request_id = str(request_id or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        with self._changed:
            if request_id in self._requests:
                raise ValueError("request_id is already active")
            active = ActiveRequest(request_id=request_id, session_id=str(session_id or ""), cancelled=Event())
            self._requests[request_id] = active
            self._changed.notify_all()
            return active

    def cancel(self, request_id: str, session_id: str = "", wait_seconds: float = 0.0) -> bool:
        request_id = str(request_id or "").strip()
        session_id = str(session_id or "")
        deadline = monotonic() + max(0.0, float(wait_seconds))
        with self._changed:
            while True:
                active = self._requests.get(request_id)
                if active:
                    if session_id and active.session_id != session_id:
                        return False
                    active.cancelled.set()
                    return True
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._changed.wait(remaining)

    def finish(self, request_id: str) -> None:
        with self._lock:
            self._requests.pop(str(request_id or "").strip(), None)

    def is_active(self, request_id: str) -> bool:
        with self._lock:
            return str(request_id or "").strip() in self._requests
