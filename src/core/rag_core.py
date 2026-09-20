"""Small compatibility facade using the shared Service and Retriever."""

from src.config import LearningOptions
from src.service import StudyService


class RAGCore:
    def __init__(self, target_subject: str, service: StudyService):
        self.subject = target_subject
        self.service = service

    def search_chunks(self, query: str, top_k: int = 5) -> list[dict]:
        return self.service.retriever.search(self.subject, query, top_k)

    def query(
        self,
        question: str,
        *,
        session_id: str,
        top_k: int = 5,
        style: str = "初心者向け (Beginner)",
        length: str = "普通 (Normal)",
        cancel_event=None,
    ) -> dict:
        request = self.service.prepare(
            "answer",
            self.subject,
            session_id,
            {"question": question},
            LearningOptions(audience=style, length=length, top_k=top_k),
        )
        return self.service.execute(request, cancel_event)
