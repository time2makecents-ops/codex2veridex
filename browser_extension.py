"""Bounded, session-scoped queue for the optional local Chrome extension.

No browser is launched, no profile is read, and no access is installed here.
Mutations require a second, local approval in the extension popup.
"""
from __future__ import annotations

import copy
import json
import secrets
import threading
import time
from collections import OrderedDict
from typing import Callable
from urllib.parse import urlsplit

TOOLS = ("status", "read", "navigate", "click", "fill", "stop")
TERMINAL = {"completed", "limited", "failed", "stopped", "outcome_unknown", "blocked"}
MUTATIONS = {"navigate", "click", "fill"}


class BrowserRelayError(ValueError):
    """A fixed diagnostic code safe to return without page or credential data."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def origin(url: str) -> str:
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only HTTP(S) URLs without embedded credentials are supported")
    # URL parsing must reject malformed port numbers too.
    port = parsed.port
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    default = (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)
    return f"{parsed.scheme}://{host}" + (f":{port}" if port and not default else "")


class BrowserExtensionBroker:
    def __init__(self, context: Callable, guard: Callable, audit: Callable,
                 postflight: Callable | None = None, clock: Callable = time.monotonic):
        self.context, self.guard, self.audit = context, guard, audit
        self.postflight = postflight or (lambda *_: {"allowed": True})
        self.clock = clock
        self.lock = threading.RLock()
        self.jobs: OrderedDict[str, dict] = OrderedDict()
        self.connection: dict = {}
        self.last_seen = 0.0
        self.observations: dict = {}

    def _scope(self, args: dict) -> dict:
        resolved = self.context(args)
        scope = {key: str(resolved[key]) for key in ("workspace_id", "session_id", "room")}
        if any(not value for value in scope.values()):
            raise ValueError("Browser access requires an explicit workspace, session and active room")
        return scope

    def _valid_scope(self, scope: dict) -> bool:
        try:
            return self._scope(scope) == scope
        except (ValueError, KeyError):
            return False

    def _event(self, job: dict) -> None:
        # Never persist page bodies, query strings, form values or element labels.
        self.audit(job["scope"], {"request_id": job["request_id"], "action": job["action"],
                                 "status": job["status"], "timestamp": time.time()})

    def _end(self, job: dict, status: str, error: str = "") -> None:
        job["status"] = status
        job.pop("command", None)
        if error:
            job["error"] = error
        self._event(job)

    def _expire(self) -> None:
        for job in self.jobs.values():
            if job["status"] in TERMINAL:
                continue
            if not self._valid_scope(job["scope"]):
                self._end(job, "outcome_unknown" if job["status"] == "running" else "stopped", "Session or active room changed")
            elif self.clock() > job["deadline"]:
                self._end(job, "outcome_unknown" if job["status"] == "running" else "stopped", "Request expired; not retried")
            elif job.get("connection_id") and (self.clock() - self.last_seen > 12):
                self._end(job, "outcome_unknown" if job["status"] == "running" else "stopped", "Browser connection lost; not retried")

    @staticmethod
    def _public(job: dict) -> dict:
        return copy.deepcopy({key: value for key, value in job.items()
                              if key not in {"command", "deadline", "connection_id"}})

    def call(self, action: str, args: dict) -> dict:
        if action not in TOOLS:
            raise ValueError("Unknown browser action")
        with self.lock:
            scope = self._scope(args)
            self._expire()
            request_id = str(args.get("request_id") or "")
            if action in {"status", "stop"}:
                if request_id:
                    job = self.jobs.get(request_id)
                    if not job or job["scope"] != scope:
                        raise ValueError("Browser request is unavailable in this scope")
                    if action == "stop" and job["status"] not in TERMINAL:
                        self._end(job, "outcome_unknown" if job["status"] == "running" else "stopped",
                                  "Stop requested; an already dispatched action cannot be undone")
                    return self._public(job)
                if action == "stop":
                    raise ValueError("request_id is required to stop a browser request")
                connected = bool(self.connection) and self.clock() - self.last_seen <= 12
                selected = self.connection.get("selection") or {}
                return {"status": "connected" if connected else "disconnected", "scope": scope,
                        "authorized_tab": selected if connected and selected.get("scope") == scope else None,
                        "profile_verification": "operator must install in the dedicated Veridex profile",
                        "transport": "native_messaging", "approval": "mutations require extension popup approval"}
            if not isinstance(args.get("intent"), str) or not args["intent"].strip():
                raise ValueError("Describe the user-authorized intent for the browser request")
            decision = self.guard(scope, action, args)
            if not decision.get("allowed"):
                return {"status": "blocked", "governance": decision, "scope": scope}
            if request_id:
                raise ValueError("Do not reuse a request_id to submit or retry an action")
            command = {"intent": args["intent"][:2000]}
            selection = self.connection.get("selection") or {}
            if action in MUTATIONS and (self.clock() - self.last_seen > 12 or selection.get("scope") != scope):
                raise ValueError("Select an authorized tab in this scope before requesting actions")
            if action == "navigate":
                origin(str(args.get("url") or ""))
                if len(str(args["url"])) > 4096:
                    raise ValueError("URL is too long")
                command["url"] = str(args["url"])
            if action in {"click", "fill"}:
                for key in ("snapshot_id", "document_id", "target_id"):
                    value = str(args.get(key) or "")
                    if not value or len(value) > 128:
                        raise ValueError(f"{key} from a fresh browser.read observation is required")
                    command[key] = value
                observed = self.observations.get((tuple(scope.values()), selection.get("tab_id")), {})
                if any(command[key] != observed.get(key) for key in ("snapshot_id", "document_id")):
                    raise ValueError("Request requires the latest observation of the selected tab")
                target = next((row for row in observed.get("elements", []) if row.get("target_id") == command["target_id"]), None)
                if not target:
                    raise ValueError("Target is absent from the selected tab observation")
                command["target_preview"] = {key: target.get(key) for key in ("tag", "type", "role", "label", "disabled")}
                if "expect_text" in args:
                    command["expect_text"] = str(args["expect_text"])[:500]
                if "expect_url" in args:
                    origin(str(args["expect_url"]))
                    command["expect_url"] = str(args["expect_url"])[:4096]
            if action == "fill":
                if not isinstance(args.get("text"), str) or len(args["text"]) > 4000:
                    raise ValueError("text must be a string of at most 4000 characters")
                command["text"] = args["text"]
            if sum(job["status"] not in TERMINAL for job in self.jobs.values()) >= 16:
                raise ValueError("Browser queue is full")
            while len(self.jobs) >= 128:
                removable = next((key for key, row in self.jobs.items() if row["status"] in TERMINAL), None)
                if removable is None:
                    raise ValueError("Browser queue is full")
                del self.jobs[removable]
            request_id = secrets.token_hex(16)
            job = {"request_id": request_id, "scope": scope, "action": action, "status": "queued",
                   "created_at": time.time(), "deadline": self.clock() + 120, "command": command}
            self.jobs[request_id] = job
            self._event(job)
            return self._public(job)

    def relay(self, payload: dict) -> dict:
        """Called only by the token-authenticated local native host."""
        with self.lock:
            connection_id = str(payload.get("connection_id") or "")
            if not connection_id or len(connection_id) > 128:
                raise ValueError("Invalid connection identity")
            selection = payload.get("selection")
            if selection:
                if not isinstance(selection, dict):
                    raise ValueError("Invalid tab selection")
                selected_scope = self._scope(selection.get("scope") or {})
                origin(str(selection.get("url") or ""))
                if not isinstance(selection.get("tab_id"), int):
                    raise ValueError("Invalid tab identity")
                selection = {"scope": selected_scope, "url": selection["url"], "tab_id": selection["tab_id"]}
            # Validate before changing ownership or heartbeat state. An idle
            # connector in another profile must not steal an authorized tab.
            if self.connection and self.connection["connection_id"] != connection_id:
                if self.connection.get("selection") and self.clock() - self.last_seen <= 12:
                    if selection:
                        raise BrowserRelayError("connection_in_use", "Another browser connection already has a selected tab")
                    return {"active_request_ids": [], "connection_status": "another_connection_selected"}
                for job in self.jobs.values():
                    if job.get("connection_id") and job["status"] not in TERMINAL:
                        self._end(job, "outcome_unknown" if job["status"] == "running" else "stopped", "Connection replaced; not retried")
            self.last_seen = self.clock()
            self.connection = {"connection_id": connection_id, "selection": selection}
            self._expire()
            event = payload.get("event")
            if event:
                if not isinstance(event, dict):
                    raise ValueError("Invalid browser event")
                job = self.jobs.get(str(event.get("request_id") or ""))
                if not job or job.get("connection_id") != connection_id:
                    raise ValueError("Unknown or stale browser event")
                if job["status"] not in TERMINAL:
                    if not selection or selection["scope"] != job["scope"] or selection["tab_id"] != job["tab_id"]:
                        raise ValueError("Browser event does not match the selected scope/tab")
                    if event.get("type") == "claim":
                        if job["status"] != "awaiting_browser" or (job["action"] in MUTATIONS and event.get("approved_locally") is not True):
                            raise ValueError("An exact local approval is required before execution")
                        decision = self.guard(job["scope"], job["action"], job["command"])
                        if not decision.get("allowed"):
                            self._end(job, "blocked", "Navigator rejected execution")
                        else:
                            job["status"] = "running"
                            job["deadline"] = self.clock() + 120
                            self._event(job)
                            return {"execute": True, "request_id": job["request_id"], "selection": selection}
                    elif event.get("type") == "result":
                        if job["status"] != "running":
                            raise ValueError("Result arrived before an execution claim")
                        result = event.get("result")
                        if not isinstance(result, dict) or len(json.dumps(result)) > 160000:
                            raise ValueError("Invalid or oversized browser result")
                        status = str(result.get("status") or "failed")
                        if status not in {"completed", "limited", "failed"}:
                            raise ValueError("Invalid result status")
                        if status == "completed" and not isinstance(result.get("observation"), dict):
                            raise ValueError("Completed browser results require a page observation")
                        observation = result.get("observation")
                        if isinstance(observation, dict):
                            origin(str(observation.get("url") or ""))
                            if any(not isinstance(observation.get(key), str) or not 0 < len(observation[key]) <= 128
                                   for key in ("document_id", "snapshot_id")):
                                raise ValueError("Browser observation requires document and snapshot identities")
                            if (not isinstance(observation.get("elements"), list) or len(observation["elements"]) > 100
                                    or any(not isinstance(row, dict) for row in observation["elements"])):
                                raise ValueError("Browser observation has invalid targets")
                        if status == "completed" and job["action"] in MUTATIONS and result.get("effect_verified") is not True:
                            raise ValueError("Completed actions require a verified effect")
                        check = self.postflight(job, result)
                        if not check.get("allowed"):
                            self._end(job, "blocked", "Navigator rejected browser evidence")
                        else:
                            if isinstance(observation, dict):
                                self.observations[(tuple(job["scope"].values()), job["tab_id"])] = copy.deepcopy(observation)
                                while len(self.observations) > 128:
                                    self.observations.pop(next(iter(self.observations)))
                            job["result"] = copy.deepcopy(result)
                            self._end(job, status)
                    elif event.get("type") == "reject":
                        if job["status"] == "awaiting_browser":
                            self._end(job, "stopped", "Declined in the extension popup")
                    else:
                        raise ValueError("Unknown browser event type")
            valid_ids = [row["request_id"] for row in self.jobs.values()
                         if row.get("connection_id") == connection_id and row["status"] not in TERMINAL]
            if selection:
                for job in self.jobs.values():
                    if job["status"] != "queued" or job["scope"] != selection["scope"]:
                        continue
                    job.update(status="awaiting_browser", connection_id=connection_id, tab_id=selection["tab_id"])
                    if job["action"] in MUTATIONS:
                        # Human review can span chat turns. Keep transport/scope
                        # checks active, but do not expire a healthy approval in
                        # the original short delivery window.
                        job["deadline"] = self.clock() + 600
                    self._event(job)
                    command = {**job["command"], "request_id": job["request_id"], "action": job["action"],
                               "scope": job["scope"], "tab_id": job["tab_id"], "selected_url": selection["url"]}
                    return {"command": command, "active_request_ids": valid_ids + [job["request_id"]], "selection": selection}
                # Rebuild a lost popup queue on this same connection. This only
                # repeats an approval proposal, never a claimed/running action,
                # and does not reset the proposal's expiry deadline.
                for job in self.jobs.values():
                    if (job["status"] == "awaiting_browser" and job["action"] in MUTATIONS
                            and job.get("connection_id") == connection_id and job["scope"] == selection["scope"]
                            and job.get("tab_id") == selection["tab_id"]):
                        command = {**job["command"], "request_id": job["request_id"], "action": job["action"],
                                   "scope": job["scope"], "tab_id": job["tab_id"], "selected_url": selection["url"]}
                        return {"command": command, "active_request_ids": valid_ids, "selection": selection}
            return {"active_request_ids": valid_ids, "selection": selection}
