"""Resumable chapter lectures inside one JobManager execution-lock lifetime.

Only an explicit new parent request can resume an unfinished edition. Successful
operations are persisted immediately and never regenerated during that resume.
The batch does not own processes: cancellation reaches the existing Provider,
which reaps its child before the parent worker releases the generation lock.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from src.config import LLM_MODEL, MODEL_EFFORT, PROMPT_VERSION, SCHEMA_VERSION
from src.jobs import ERROR_MESSAGES
from src.learning_repository import LearningRepository
from src.output_contract import sanitize_diagnostic
from src.repository import canonical_json, now_iso
from src.schemas import SCHEMAS, validate_lecture_plan, validate_lecture_section
from src.service import LearningRequest, StudyService

MAX_BATCH_SECONDS = 1800


class LectureBatchError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in ERROR_MESSAGES else "worker_error"
        self.diagnostic: dict = {}
        super().__init__(ERROR_MESSAGES[self.code])


def lecture_batch_scope(subject: str, course_id: str, chapter_index: int) -> str:
    """One scope per chapter, shared across browser tabs and learning sessions."""
    if not subject or not course_id or type(chapter_index) is not int or chapter_index < 0:
        raise LectureBatchError("invalid_request")
    return canonical_json([subject, "", course_id, str(chapter_index), "lecture-batch"])


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _seal(document: dict) -> dict:
    document = {key: value for key, value in document.items() if key != "document_sha256"}
    return document | {"document_sha256": _digest(document)}


class _Cancellation:
    """Relay user cancellation without changing the parent's cancellation reason."""

    def __init__(self, parent: threading.Event, seconds: float):
        self.parent = parent
        self.child = threading.Event()
        self.finished = threading.Event()
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds
        fd = getattr(parent, "execution_lock_fd", None)
        if type(fd) is not int or fd < 0:
            raise LectureBatchError("invalid_request")
        os.fstat(fd)
        self.child.execution_lock_fd = fd  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self._relay, name="lecture-batch-cancel", daemon=True)

    def _relay(self) -> None:
        while not self.finished.is_set():
            if self.parent.is_set() or time.monotonic() >= self.deadline:
                self.child.set()
                return
            self.finished.wait(min(0.02, max(0, self.deadline - time.monotonic())))

    def check(self) -> None:
        if self.parent.is_set():
            self.child.set()
            raise LectureBatchError("cancelled")
        if time.monotonic() >= self.deadline:
            self.child.set()
            failure = LectureBatchError("timeout")
            failure.diagnostic = {"category": "timeout", "stage": "lecture_batch", "limit": int(self.seconds)}
            raise failure

    def __enter__(self) -> _Cancellation:
        self.check()
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.finished.set()
        self.thread.join()


class LectureBatch:
    def __init__(
        self, service: StudyService, store: LearningRepository, *, deadline_seconds: float = MAX_BATCH_SECONDS
    ):
        if not 0 < deadline_seconds <= MAX_BATCH_SECONDS:
            raise ValueError("講義生成全体の制限時間は0秒より大きく1800秒以内で指定してください。")
        self.service, self.store, self.deadline_seconds = service, store, deadline_seconds

    @staticmethod
    def _identity(request: LearningRequest) -> dict:
        data = request.to_dict()
        # A deliberate restart gets a new request/session ID. Every other input,
        # including material evidence and the previous lecture, stays bound.
        data.pop("request_id")
        data.pop("session_id")
        return data

    @staticmethod
    def _validate_result(result: dict, request: LearningRequest, section: dict | None = None) -> None:
        expected = {
            "model": request.model,
            "effort": request.effort,
            "material_revision": request.material_revision,
            "learning_options": asdict(request.options),
        }
        if not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items()):
            raise LectureBatchError("invalid_result")
        if result.get("sources") != request.sources:
            raise LectureBatchError("invalid_result")
        body = {key: result[key] for key in SCHEMAS[request.kind]["properties"] if key in result}
        if section is None:
            validate_lecture_plan(body, request.sources)
        else:
            validate_lecture_section(body, section, request.sources)

    def _validate_checkpoint(self, document: dict, request: LearningRequest, identity: dict) -> None:
        try:
            if (
                not isinstance(document, dict)
                or document.get("format") != "lecture-batch-v1"
                or _seal(document) != document
                or document["request_identity"] != identity
                or document["fingerprint"] != _digest(identity)
                or document["edition_id"] != request.payload["_edition_id"]
                or document["material_revision"] != request.material_revision
                or type(document["state_version"]) is not int
                or document["status"] not in ("running", "succeeded", "failed", "cancelled", "interrupted")
                or not isinstance(document["attempts"], list)
                or not isinstance(document["sections"], list)
                or not isinstance(document["section_requests"], list)
            ):
                raise LectureBatchError("invalid_result")
            plan = document["plan"]
            if plan is None:
                if document["sections"] or document["section_requests"]:
                    raise LectureBatchError("invalid_result")
            else:
                self._validate_result(plan, request)
                sections = document["sections"]
                if len(sections) > len(plan["sections"]) or len(document["section_requests"]) != len(sections):
                    raise LectureBatchError("invalid_result")
                for index, result in enumerate(sections):
                    saved_request = LearningRequest.from_dict(document["section_requests"][index])
                    section = plan["sections"][index]
                    if (
                        saved_request.kind != "lecture_section"
                        or saved_request.subject != request.subject
                        or saved_request.course_id != request.course_id
                        or saved_request.material_revision != request.material_revision
                        or saved_request.options != request.options
                        or saved_request.model != request.model
                        or saved_request.effort != request.effort
                        or saved_request.prompt_version != request.prompt_version
                        or saved_request.schema_version != request.schema_version
                        or saved_request.payload.get("section") != section
                        or saved_request.payload.get("title") != request.payload["title"]
                        or saved_request.payload.get("plan")
                        != {key: plan[key] for key in SCHEMAS["lecture_plan"]["properties"]}
                        or saved_request.payload.get("prior_summaries")
                        != [{"section_id": item["section_id"], "summary": item["summary"]} for item in sections[:index]]
                    ):
                        raise LectureBatchError("invalid_result")
                    self._validate_result(result, saved_request, section)
                successful = [item for item in document["attempts"] if item["status"] == "succeeded"]
                expected = [
                    ("lecture_plan", None, plan),
                    *[("lecture_section", item["section_id"], item) for item in sections],
                ]
                if len(successful) != len(expected):
                    raise LectureBatchError("invalid_result")
                for attempt, (kind, section_id, result) in zip(successful, expected, strict=True):
                    if (
                        attempt["kind"] != kind
                        or attempt["section_id"] != section_id
                        or attempt["result_sha256"] != _digest(result)
                    ):
                        raise LectureBatchError("invalid_result")
                for attempt, stored in zip(successful[1:], document["section_requests"], strict=True):
                    if attempt["request_digest"] != LearningRequest.from_dict(stored).digest():
                        raise LectureBatchError("invalid_result")
            if document["status"] == "succeeded" and (
                plan is None or len(document["sections"]) != len(plan["sections"])
            ):
                raise LectureBatchError("invalid_result")
        except (KeyError, TypeError, ValueError) as exc:
            raise LectureBatchError("invalid_result") from exc

    def _start(self, request: LearningRequest, scope: str, name: str, identity: dict) -> dict:
        def start(current: dict | None) -> dict:
            if current is not None:
                self._validate_checkpoint(current, request, identity)
                if current["status"] == "succeeded":
                    return current
                if current["last_request_id"] == request.request_id:
                    raise LectureBatchError("invalid_request")
                # A running checkpoint can survive an app crash. The enclosing
                # JobManager lock proves that its previous worker has stopped.
                for attempt in current["attempts"]:
                    if attempt["status"] == "running":
                        attempt.update(status="interrupted", finished_at=now_iso(), error_code="interrupted")
                current.update(
                    status="running",
                    error_code=None,
                    last_request_id=request.request_id,
                    state_version=current["state_version"] + 1,
                    updated_at=now_iso(),
                )
                return _seal(current)
            return _seal(
                {
                    "format": "lecture-batch-v1",
                    "edition_id": request.payload["_edition_id"],
                    "material_revision": request.material_revision,
                    "request_identity": identity,
                    "fingerprint": _digest(identity),
                    "plan": None,
                    "sections": [],
                    "section_requests": [],
                    "attempts": [],
                    "status": "running",
                    "error_code": None,
                    "state_version": 0,
                    "last_request_id": request.request_id,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
            )

        return self.store.update_document(scope, name, start, mirror_name="lecture_batch")

    def _save(self, scope: str, name: str, old: dict, changed: dict) -> dict:
        def compare(current: dict | None) -> dict:
            if current != old:
                raise LectureBatchError("invalid_result")
            return _seal(changed | {"state_version": old["state_version"] + 1, "updated_at": now_iso()})

        return self.store.update_document(scope, name, compare, mirror_name="lecture_batch")

    @staticmethod
    def _result(document: dict, request: LearningRequest) -> dict:
        return {
            "format": "sections-v1",
            "lecture_id": document["edition_id"],
            "material_revision": request.material_revision,
            "learning_options": asdict(request.options),
            "model": request.model,
            "effort": request.effort,
            "prompt_version": request.prompt_version,
            "schema_version": request.schema_version,
            "plan": document["plan"],
            "sections": document["sections"],
        }

    def run(self, request: LearningRequest, cancel_event: threading.Event) -> dict:
        payload = request.payload
        chapter_index = payload.get("_chapter_index")
        if type(chapter_index) is not int:
            raise LectureBatchError("invalid_request")
        scope = lecture_batch_scope(request.subject, request.course_id, chapter_index)
        if (
            request.kind != "lecture_plan"
            or payload.get("_batch_scope") != scope
            or not isinstance(payload.get("_edition_id"), str)
            or not 1 <= len(payload["_edition_id"]) <= 128
            or (request.model, request.effort, request.prompt_version, request.schema_version)
            != (LLM_MODEL, MODEL_EFFORT, PROMPT_VERSION, SCHEMA_VERSION)
        ):
            raise LectureBatchError("invalid_request")
        identity = self._identity(request)
        name = "lecture_batch:" + payload["_edition_id"]
        # Validate the parent-lock handoff before writing state or generating.
        cancellation = _Cancellation(cancel_event, self.deadline_seconds)
        document = self._start(request, scope, name, identity)
        try:
            with cancellation:
                self.service.validate_revision(request)
                if document["status"] == "succeeded":
                    return self._result(document, request)
                while True:
                    cancellation.check()
                    self.service.validate_revision(request)
                    plan = document["plan"]
                    if plan is not None and len(document["sections"]) == len(plan["sections"]):
                        document = self._save(scope, name, document, document | {"status": "succeeded"})
                        return self._result(document, request)
                    section = None
                    if plan is None:
                        operation = request
                    else:
                        section = plan["sections"][len(document["sections"])]
                        operation = self.service.prepare(
                            "lecture_section",
                            request.subject,
                            request.session_id,
                            {
                                "title": payload["title"],
                                "plan": {key: plan[key] for key in SCHEMAS["lecture_plan"]["properties"]},
                                "section": section,
                                "prior_summaries": [
                                    {"section_id": item["section_id"], "summary": item["summary"]}
                                    for item in document["sections"]
                                ],
                            },
                            request.options,
                            course_id=request.course_id,
                            request_id=request.request_id + ":" + section["section_id"],
                        )
                        if operation.material_revision != request.material_revision:
                            raise LectureBatchError("invalid_result")
                    cancellation.check()
                    self.service.validate_revision(request)
                    changed = deepcopy(document)
                    changed["attempts"].append(
                        {
                            "kind": operation.kind,
                            "section_id": section["section_id"] if section else None,
                            "request_id": operation.request_id,
                            "request_digest": operation.digest(),
                            "status": "running",
                            "started_at": now_iso(),
                            "finished_at": None,
                            "error_code": None,
                        }
                    )
                    document = self._save(scope, name, document, changed)
                    result = self.service.execute(operation, cancellation.child)
                    cancellation.check()
                    self.service.validate_revision(request)
                    self._validate_result(result, operation, section)
                    changed = deepcopy(document)
                    changed["attempts"][-1].update(
                        status="succeeded", finished_at=now_iso(), result_sha256=_digest(result)
                    )
                    if section is None:
                        changed["plan"] = result
                    else:
                        changed["sections"].append(result)
                        changed["section_requests"].append(operation.to_dict())
                    document = self._save(scope, name, document, changed)
        except Exception as exc:
            cause = exc
            try:
                cancellation.check()
            except LectureBatchError as stopped:
                cause = stopped
            code = str(getattr(cause, "code", "worker_error"))
            failure = LectureBatchError(code)
            failure.diagnostic = sanitize_diagnostic(getattr(cause, "diagnostic", None))
            if (failure.diagnostic.get("category") == "timeout"
                    and failure.diagnostic.get("stage") == "lecture_section"
                    and document["attempts"]):
                section_id = document["attempts"][-1].get("section_id")
                if section_id in {f"s{i}" for i in range(1, 9)}:
                    failure.diagnostic["path"] = ["sections", int(section_id[1:]) - 1]
            if document["status"] == "succeeded":
                # Re-reading an already completed edition must not rewrite its
                # historical completion if this new job is stale or cancelled.
                raise failure from cause
            changed = deepcopy(document)
            changed.update(status="cancelled" if failure.code == "cancelled" else "failed", error_code=failure.code)
            if changed["attempts"] and changed["attempts"][-1]["status"] == "running":
                changed["attempts"][-1].update(status=changed["status"], error_code=failure.code, finished_at=now_iso())
            if changed["attempts"] and failure.diagnostic:
                changed["attempts"][-1]["diagnostic"] = failure.diagnostic
            self._save(scope, name, document, changed)
            raise failure from cause
