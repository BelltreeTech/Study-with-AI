"""Optional local E5 embeddings. Normal application runs never download a model."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

E5_MODEL = "intfloat/multilingual-e5-small"
E5_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


@dataclass(frozen=True)
class EmbeddingSettings:
    model: str = E5_MODEL
    revision: str = E5_REVISION
    dimensions: int = 384
    max_tokens: int = 512
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    normalize: bool = True
    batch_size: int = 16


class EmbeddingUnavailable(RuntimeError):
    """BM25 can continue when the optional model/runtime is unavailable."""


def default_model_dir() -> Path:
    configured = os.environ.get("STUDY_EMBEDDING_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "models" / "multilingual-e5-small" / E5_REVISION


def installed_library_version(name: str) -> str:
    """Inspect a frozen search path; Streamlit can mutate sys.path during reruns."""
    context = importlib.metadata.DistributionFinder.Context(name=name, path=list(sys.path))
    distribution = next(iter(importlib.metadata.Distribution.discover(context=context)), None)
    return distribution.version if distribution is not None else "unavailable"


class LocalEmbedder:
    def __init__(self, model_dir: Path | None = None, settings: EmbeddingSettings | None = None):
        self.settings = settings or EmbeddingSettings()
        self.model_dir = Path(model_dir) if model_dir is not None else default_model_dir()
        self._model: Any = None
        self._error: str | None = None
        # Loaded runtime identities do not change mid-request. Metadata discovery
        # can transiently fail while another Streamlit script modifies sys.path.
        self._runtime_versions: dict[str, str] = {}
        for name in ("sentence-transformers", "transformers", "torch"):
            self._runtime_versions[name] = installed_library_version(name)

    def identity(self) -> dict:
        return {**asdict(self.settings), "libraries": dict(self._runtime_versions)}

    def diagnostics(self) -> dict:
        ready = (self.model_dir / "study-model.json").is_file()
        return {
            "model": self.settings.model,
            "revision": self.settings.revision,
            "downloaded": ready,
            "loaded": self._model is not None,
            "error": self._error,
            "network_required": False,
        }

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            manifest = json.loads((self.model_dir / "study-model.json").read_text())
            if manifest.get("model") != self.settings.model or manifest.get("revision") != self.settings.revision:
                raise ValueError("取得済みモデルのrevisionが設定と一致しません")
            from sentence_transformers import SentenceTransformer

            # A local path + local_files_only applies to transformer and tokenizer.
            # Remote custom Python is prohibited; the script downloads only safe weights.
            self._model = SentenceTransformer(
                str(self.model_dir.resolve()),
                device="cpu",
                local_files_only=True,
                trust_remote_code=False,
                model_kwargs={"use_safetensors": True},
            )
            self._model.max_seq_length = self.settings.max_tokens
            if self._model.get_sentence_embedding_dimension() != self.settings.dimensions:
                self._model = None
                raise ValueError("Embedding次元が設定と一致しません")
            self._error = None
            return self._model
        except Exception as exc:
            self._error = (
                "ローカルEmbeddingモデル未取得/読込不可。BM25のみで検索します。"
                "uv run --extra semantic python scripts/download_embedding.py を実行してください。"
            )
            raise EmbeddingUnavailable(self._error) from exc

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.empty((0, self.settings.dimensions), dtype=np.float32)
        prefix = self.settings.query_prefix if query else self.settings.passage_prefix
        try:
            values = np.asarray(
                self._load().encode(
                    [prefix + text for text in texts],
                    batch_size=self.settings.batch_size,
                    normalize_embeddings=self.settings.normalize,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            )
            if values.shape != (len(texts), self.settings.dimensions) or not np.isfinite(values).all():
                raise ValueError("Embedding shape/value mismatch")
            return values
        except EmbeddingUnavailable:
            raise
        except Exception as exc:
            self._error = "ローカルEmbedding計算に失敗したためBM25のみで検索します。"
            raise EmbeddingUnavailable(self._error) from exc


def generate_cache_key(pdf_paths: list[str]) -> str:
    """Compatibility helper uses full path and bytes, never basenames or sizes."""
    entries = [(str(Path(p).resolve()), hashlib.sha256(Path(p).read_bytes()).hexdigest()) for p in sorted(pdf_paths)]
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def generate_embeddings(texts: list[str], model: str = E5_MODEL, *, query: bool = False) -> np.ndarray:
    if model != E5_MODEL:
        raise ValueError("ローカルE5以外のEmbeddingモデルは設定されていません")
    return LocalEmbedder().encode(texts, query=query)
