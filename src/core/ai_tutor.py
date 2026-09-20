"""Tutor facade shares generation and retrieval contracts; no client or embedding coupling."""

from src.config import LearningOptions
from src.service import StudyService


class AITutor:
    def __init__(self, service: StudyService, subject: str):
        self.service = service
        self.subject = subject

    def request(
        self,
        kind: str,
        payload: dict,
        *,
        session_id: str,
        options: LearningOptions | None = None,
        course_id: str = "",
        cancel_event=None,
    ) -> dict:
        prepared = self.service.prepare(
            kind, self.subject, session_id, payload, options or LearningOptions(), course_id=course_id
        )
        return self.service.execute(prepared, cancel_event)
