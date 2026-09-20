"""Lazy application resources. Reading dashboards does not authenticate or build indexes."""

import atexit
from dataclasses import dataclass
from pathlib import Path

from src.codex_provider import CodexProvider
from src.jobs import JobManager
from src.learning_repository import LearningRepository
from src.retriever import LocalRetriever
from src.service import StudyService


@dataclass
class Runtime:
    service: StudyService
    jobs: JobManager
    store: LearningRepository
    retriever: LocalRetriever
    provider: CodexProvider


def create_runtime(data_root: str, state_root: str, cache_root: str) -> Runtime:
    provider = CodexProvider()
    retriever = LocalRetriever(Path(data_root), Path(cache_root))
    jobs = JobManager(Path(state_root) / "jobs.sqlite3")
    store = LearningRepository(Path(state_root) / "learning.sqlite3")
    runtime = Runtime(StudyService(provider, retriever), jobs, store, retriever, provider)
    atexit.register(jobs.shutdown)
    return runtime
