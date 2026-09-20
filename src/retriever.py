"""One offline retrieval boundary for questions, lessons and tests.

Caches are immutable snapshots in local-retrieval-v2, separate from legacy API
vectors. A snapshot includes byte hashes, provenance, extraction/chunk parameters,
model revision, prefixes, normalization, dimensions and runtime versions.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from src.embedder import EmbeddingUnavailable, LocalEmbedder, installed_library_version
from src.pdf_reader import ExtractionSettings, PDFExtractionError, extract_text_from_pdf
from src.text_chunker import chunk_text
from src.vector_search import cosine_similarity


@dataclass(frozen=True)
class RetrievalSettings:
    chunk_size: int = 400
    chunk_overlap: int = 60
    max_results: int = 12
    max_context_chars: int = 12000
    max_documents: int = 200
    max_subject_bytes: int = 512 * 1024 * 1024
    max_chunks: int = 30000
    extraction: ExtractionSettings = field(default_factory=ExtractionSettings)
    version: int = 2


class UnsafeMaterialPath(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class LocalRetriever:
    def __init__(
        self, data_root: Path, cache_root: Path, *, settings: RetrievalSettings | None = None, embedder: Any = None
    ):
        self.data_root = Path(data_root).expanduser().resolve()
        self.cache_root = Path(cache_root).expanduser().resolve() / "local-retrieval-v2"
        self.settings = settings or RetrievalSettings()
        self.embedder = embedder if embedder is not None else LocalEmbedder()
        self._indices: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._tokenizer: Any = None
        # A retriever owns one runtime snapshot. Re-querying package metadata
        # concurrently with Streamlit reruns can report temporary false misses.
        self._runtime_versions: dict[str, str] = {"numpy": np.__version__}
        for package in ("pymupdf", "pytesseract", "janome"):
            self._runtime_versions[package] = installed_library_version(package)

    def _subject_path(self, subject: str) -> Path:
        pure = PurePosixPath(subject)
        if (
            not subject
            or "\\" in subject
            or pure.is_absolute()
            or len(pure.parts) != 2
            or any(p in (".", "..") or p.startswith(".") for p in pure.parts)
            or pure.as_posix() != subject
        ):
            raise UnsafeMaterialPath("科目はdata配下のカテゴリ/科目を指定してください")
        candidate = self.data_root
        for part in pure.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise UnsafeMaterialPath("教材科目のsymlinkは利用できません")
        if not candidate.resolve().is_relative_to(self.data_root):
            raise UnsafeMaterialPath("教材ディレクトリの外は読み込めません")
        return candidate

    def discover_subjects(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        result = []
        for category in sorted(self.data_root.iterdir()):
            if category.is_symlink() or not category.is_dir() or category.name.startswith("."):
                continue
            for subject in sorted(category.iterdir()):
                if subject.is_symlink() or not subject.is_dir() or subject.name.startswith("."):
                    continue
                result.append(subject.relative_to(self.data_root).as_posix())
        return result

    def _files(self, subject: str) -> tuple[list[Path], list[dict]]:
        root = self._subject_path(subject)
        files: list[Path] = []
        warnings: list[dict] = []
        if not root.is_dir():
            return files, warnings
        for folder, directories, filenames in os.walk(root, followlinks=False):
            folder_path = Path(folder)
            kept = []
            for directory in sorted(directories):
                path = folder_path / directory
                if path.is_symlink():
                    warnings.append(
                        {"source_file": path.relative_to(self.data_root).as_posix(), "code": "symlink_rejected"}
                    )
                elif not directory.startswith("."):
                    kept.append(directory)
            directories[:] = kept
            for filename in sorted(filenames):
                path = folder_path / filename
                if path.suffix.lower() != ".pdf":
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                    warnings.append(
                        {"source_file": path.relative_to(self.data_root).as_posix(), "code": "symlink_rejected"}
                    )
                    continue
                files.append(path)
        if len(files) > self.settings.max_documents:
            raise ValueError("科目のPDF数が上限を超えています。科目を分けてください")
        return files, warnings

    def _read_material(self, path: Path) -> bytes:
        # Resolve each directory relative to an already-open parent. NOFOLLOW on
        # every component closes directory-symlink swap races during indexing.
        parts = path.relative_to(self.data_root).parts
        descriptors = []
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            parent = os.open(self.data_root, flags | getattr(os, "O_DIRECTORY", 0))
            descriptors.append(parent)
            for part in parts[:-1]:
                parent = os.open(part, flags | getattr(os, "O_DIRECTORY", 0), dir_fd=parent)
                descriptors.append(parent)
            fd = os.open(parts[-1], flags, dir_fd=parent)
            with os.fdopen(fd, "rb") as stream:
                return stream.read(self.settings.extraction.max_pdf_bytes + 1)
        except OSError as exc:
            raise UnsafeMaterialPath("教材パスが変更されたか安全に読み込めません") from exc
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _snapshot(self, subject: str) -> tuple[dict, list[tuple[dict, bytes]], list[dict]]:
        files, warnings = self._files(subject)
        materials = []
        total_bytes = 0
        for path in files:
            # NOFOLLOW rejects a file symlink swapped after enumeration. Resolved
            # ancestry is checked again immediately before opening it.
            if not path.resolve().is_relative_to(self._subject_path(subject).resolve()):
                raise UnsafeMaterialPath("教材のパスが変更されました")
            raw = self._read_material(path)
            total_bytes += len(raw)
            if total_bytes > self.settings.max_subject_bytes:
                raise ValueError("科目の教材合計サイズが上限を超えています")
            if len(raw) > self.settings.extraction.max_pdf_bytes:
                raise ValueError("PDFが読込サイズ上限を超えています")
            relative = path.relative_to(self.data_root).as_posix()
            metadata = {
                "source_file": relative,
                "document_id": "D-" + hashlib.sha256(relative.encode()).hexdigest()[:20],
                "content_hash": hashlib.sha256(raw).hexdigest(),
            }
            materials.append((metadata, raw))
        manifest = {
            "subject": subject,
            "settings": asdict(self.settings),
            "embedding": self.embedder.identity(),
            "libraries": dict(self._runtime_versions),
            "materials": [metadata for metadata, _ in materials],
            "path_warnings": warnings,
        }
        return manifest, materials, warnings

    def revision(self, subject: str) -> str:
        """Fingerprint without building the index, loading a model or generating."""
        return _digest(self._snapshot(subject)[0])

    def _load_cache(self, revision: str, manifest: dict) -> dict | None:
        path = self.cache_root / f"{revision}.npz"
        if not path.is_file() or path.is_symlink():
            return None
        try:
            with np.load(path, allow_pickle=False) as archive:
                payload = json.loads(str(archive["metadata"].item()))
                vectors = archive["vectors"]
            chunks = payload["chunks"]
            if payload["manifest"] != manifest or _digest(manifest) != revision:
                return None
            if payload["chunks_digest"] != _digest(chunks):
                return None
            dimensions = manifest["embedding"]["dimensions"]
            rows = len(chunks) if payload["mode"] == "hybrid" else 0
            if vectors.shape != (rows, dimensions) or not np.isfinite(vectors).all():
                return None
            if payload["vectors_digest"] != hashlib.sha256(vectors.tobytes()).hexdigest():
                return None
            expected = {m["source_file"]: m for m in manifest["materials"]}
            seen = set()
            for chunk in chunks:
                if (
                    chunk["content_hash"] != expected[chunk["source_file"]]["content_hash"]
                    or not isinstance(chunk["text"], str)
                    or not chunk["text"]
                    or chunk["page_number"] < 1
                    or chunk["chunk_id"] in seen
                ):
                    return None
                seen.add(chunk["chunk_id"])
            # Reattempt extraction after missing OCR dependencies are installed.
            if any(w["code"] == "ocr_unavailable_or_failed" for w in payload["warnings"]):
                return None
            return {**payload, "vectors": vectors, "revision": revision}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_cache(self, state: dict) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {k: v for k, v in state.items() if k not in ("vectors", "bm25", "tokens")}
        payload["chunks_digest"] = _digest(state["chunks"])
        payload["vectors_digest"] = hashlib.sha256(state["vectors"].tobytes()).hexdigest()
        fd, temp_name = tempfile.mkstemp(prefix="index-", suffix=".npz", dir=self.cache_root)
        try:
            with os.fdopen(fd, "wb") as stream:
                np.savez_compressed(stream, metadata=json.dumps(payload, ensure_ascii=False), vectors=state["vectors"])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.cache_root / f"{state['revision']}.npz")
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _tokens(self, text: str) -> list[str]:
        # Janome preserves the existing Japanese morphological search. Bigrams
        # also support compound fragments; the regex path works without Janome.
        text = text.lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        japanese = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", text)
        for span in japanese:
            tokens.extend(span[i : i + 2] for i in range(max(1, len(span) - 1)))
        if japanese:
            try:
                if self._tokenizer is None:
                    from janome.tokenizer import Tokenizer

                    self._tokenizer = Tokenizer()
                tokens.extend(
                    token.surface
                    for token in self._tokenizer.tokenize(text)
                    if token.surface.strip() and token.part_of_speech.split(",")[0] in ("名詞", "動詞", "形容詞")
                )
            except ImportError:
                pass
        return tokens

    def index(self, subject: str) -> dict:
        with self._lock:
            manifest, materials, path_warnings = self._snapshot(subject)
            revision = _digest(manifest)
            existing = self._indices.get(subject)
            model_available = bool(self.embedder.diagnostics().get("downloaded", False))
            if (
                existing
                and existing["revision"] == revision
                and existing.get("model_available", False) == model_available
            ):
                return self.diagnostics(subject)
            state = self._load_cache(revision, manifest)
            # A previously missing model may now be downloaded, so try to upgrade
            # a lexical snapshot (never download from the app).
            model_ready = self.embedder.diagnostics().get("downloaded", False)
            if state is None:
                chunks, warnings = [], list(path_warnings)
                for metadata, raw in materials:
                    try:
                        pages = extract_text_from_pdf(raw, settings=self.settings.extraction)
                    except PDFExtractionError:
                        warnings.append({"source_file": metadata["source_file"], "code": "pdf_extraction_failed"})
                        continue
                    for page in pages:
                        for warning in page["warnings"]:
                            warnings.append(
                                {
                                    "source_file": metadata["source_file"],
                                    "page_number": page["page_number"],
                                    "code": warning,
                                }
                            )
                        page.update(metadata)
                    chunks.extend(chunk_text(pages, self.settings.chunk_size, self.settings.chunk_overlap))
                    if len(chunks) > self.settings.max_chunks:
                        raise ValueError("科目のチャンク数が上限を超えています")
                dimensions = manifest["embedding"]["dimensions"]
                state = {
                    "manifest": manifest,
                    "revision": revision,
                    "chunks": chunks,
                    "mode": "bm25",
                    "warnings": warnings,
                    "vectors": np.empty((0, dimensions), dtype=np.float32),
                    "embedding_error": None,
                }
                model_ready = True  # One explicit attempt records a useful missing-model diagnostic.
            if state["mode"] == "bm25" and state["chunks"] and model_ready:
                try:
                    state["vectors"] = self.embedder.encode([c["text"] for c in state["chunks"]])
                    state["mode"] = "hybrid"
                    state["embedding_error"] = None
                except EmbeddingUnavailable as exc:
                    state["embedding_error"] = str(exc)
            state["model_available"] = model_available
            state["tokens"] = [Counter(self._tokens(c["text"])) for c in state["chunks"]]
            self._indices[subject] = state
            self._save_cache(state)
            return self.diagnostics(subject)

    def _bm25(self, state: dict, query: str) -> np.ndarray:
        corpus = state["tokens"]
        count = len(corpus)
        lengths = np.asarray([sum(tokens.values()) for tokens in corpus], dtype=float)
        average = max(float(lengths.mean()) if count else 0.0, 1.0)
        scores = np.zeros(count)
        for term in set(self._tokens(query)):
            frequencies = np.asarray([tokens[term] for tokens in corpus], dtype=float)
            df = int(np.count_nonzero(frequencies))
            # Positive Robertson IDF handles tiny/single-document local corpora.
            idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
            scores += idf * frequencies * 2.5 / (frequencies + 1.5 * (0.25 + 0.75 * lengths / average))
        return scores

    def search(self, subject: str, query: str, top_k: int = 5) -> list[dict]:
        if not query.strip() or top_k <= 0:
            self._subject_path(subject)
            return []
        with self._lock:
            self.index(subject)
            state = self._indices[subject]
            if not state["chunks"]:
                return []
            scores, lexical, mode = self._rank_chunks(state, query)
            result: list[dict] = []
            remaining = self.settings.max_context_chars
            for i in sorted(scores, key=lambda i: (-scores[i], i))[: min(top_k, self.settings.max_results)]:
                chunk = dict(state["chunks"][i])
                if len(chunk["text"]) > remaining:
                    break
                remaining -= len(chunk["text"])
                result.append({**chunk, "score": scores[i], "bm25_score": float(lexical[i]), "mode": mode})
            return result

    def _rank_chunks(self, state: dict, query: str) -> tuple[dict[int, float], np.ndarray, str]:
        """Shared E5/BM25 ranking; empty overview requests need no query embedding."""
        if not query.strip():
            return {}, np.zeros(len(state["chunks"])), "bm25"
        lexical = self._bm25(state, query)
        lexical_order = [int(i) for i in np.argsort(-lexical, kind="stable") if lexical[i] > 0]
        scores = {i: 1 / (60 + rank) for rank, i in enumerate(lexical_order, start=1)}
        mode = "bm25"
        if state["mode"] == "hybrid":
            try:
                query_vector = self.embedder.encode([query], query=True)[0]
                semantic = cosine_similarity(query_vector, state["vectors"])
                mode = "hybrid"
                for rank, i in enumerate(np.argsort(-semantic, kind="stable"), start=1):
                    scores[int(i)] = scores.get(int(i), 0.0) + 1 / (60 + rank)
            except (EmbeddingUnavailable, ValueError) as exc:
                state["embedding_error"] = str(exc)
                state["mode"] = "bm25"
        return scores, lexical, mode

    def course_context(self, subject: str, query: str, top_k: int = 8) -> list[dict]:
        """Bounded course overview: balance PDFs, page spread and query relevance.

        This selects representative excerpts, not an assertion of full coverage.
        Text and provenance stay identical to indexed chunks. Empty queries are
        useful for a general overview; regular search retains its empty-query rule.
        """
        if top_k <= 0:
            self._subject_path(subject)
            return []
        with self._lock:
            self.index(subject)
            state = self._indices[subject]
            chunks = state["chunks"]
            limit = min(top_k, self.settings.max_results, len(chunks))
            if limit <= 0 or self.settings.max_context_chars <= 0:
                return []
            scores, lexical, mode = self._rank_chunks(state, query)
            documents: dict[str, dict[int, list[int]]] = {}
            for i, chunk in enumerate(chunks):
                documents.setdefault(chunk["source_file"], {}).setdefault(chunk["page_number"], []).append(i)
            files = sorted(documents)
            file_indices = {name: i for i, name in enumerate(files)}
            ranked = sorted(scores, key=lambda i: (-scores[i], i))
            # If there are more PDFs than slots, retain the strongest match and
            # spread the remaining choices over the deterministic document order.
            chosen_files: list[str] = []

            def add_file(name: str) -> None:
                if name not in chosen_files and len(chosen_files) < limit:
                    chosen_files.append(name)

            if ranked:
                add_file(chunks[ranked[0]]["source_file"])
            add_file(files[0])
            add_file(files[-1])
            while len(chosen_files) < min(limit, len(files)):
                add_file(max((name for name in files if name not in chosen_files), key=lambda name: (
                    min(abs(file_indices[name] - file_indices[other]) for other in chosen_files),
                    -file_indices[name],
                )))
            most_relevant_file = chunks[ranked[0]]["source_file"] if ranked else None
            chosen_files.sort(key=lambda name: (name != most_relevant_file, name))
            quotas = {name: 0 for name in chosen_files}
            sizes = {name: sum(map(len, documents[name].values())) for name in chosen_files}
            for _ in range(limit):
                eligible = [name for name in chosen_files if quotas[name] < sizes[name]]
                name = min(eligible, key=lambda name: (quotas[name], file_indices[name]))
                quotas[name] += 1

            plans: dict[str, list[tuple[int, str]]] = {}
            for name in chosen_files:
                pages = documents[name]
                page_numbers = sorted(pages)
                page_positions = {page: i for i, page in enumerate(page_numbers)}
                selected: list[tuple[int, str]] = []
                seen: set[int] = set()
                seen_pages: set[int] = set()

                def add_chunk(i: int, role: str) -> None:
                    if i not in seen and len(selected) < quotas[name]:
                        selected.append((i, role))
                        seen.add(i)
                        seen_pages.add(chunks[i]["page_number"])

                def best_page(page: int) -> int:
                    return max(pages[page], key=lambda i: (scores.get(i, 0.0), -i))

                relevant = [i for i in ranked if chunks[i]["source_file"] == name]
                if relevant:
                    add_chunk(relevant[0], "query_relevance")
                anchors = [page_numbers[0], page_numbers[-1]]
                if seen_pages:
                    anchors.sort(key=lambda page: (
                        -min(abs(page_positions[page] - page_positions[other]) for other in seen_pages), page,
                    ))
                for page in anchors:
                    add_chunk(best_page(page), "representative")
                # A larger per-document budget may retain a second relevant
                # page. The other slots remain available for broad page spread.
                if quotas[name] >= 6:
                    extra = next((i for i in relevant if chunks[i]["page_number"] not in seen_pages), None)
                    if extra is not None:
                        add_chunk(extra, "query_relevance")
                while len(selected) < quotas[name]:
                    remaining_pages = [page for page in page_numbers if page not in seen_pages]
                    if remaining_pages:
                        page = max(remaining_pages, key=lambda page: (
                            min(abs(page_positions[page] - page_positions[other]) for other in seen_pages),
                            scores.get(best_page(page), 0.0), -page,
                        ))
                        add_chunk(best_page(page), "representative")
                    else:
                        # Once every readable page is represented, spread within
                        # long pages instead of returning the same chunk twice.
                        remaining = [i for page in page_numbers for i in pages[page] if i not in seen]
                        i = max(remaining, key=lambda i: (
                            min(abs(i - other) for other in seen), scores.get(i, 0.0), -i,
                        ))
                        add_chunk(i, "representative")
                plans[name] = selected

            result: list[dict] = []
            remaining_chars = self.settings.max_context_chars
            # Interleave PDFs so a tight character budget does not spend all
            # available room on the first document's plan. Start with the most
            # relevant PDF so an especially small budget still keeps its match.
            for row in range(max(quotas.values())):
                for name in chosen_files:
                    if row >= len(plans[name]):
                        continue
                    i, role = plans[name][row]
                    chunk = chunks[i]
                    if len(chunk["text"]) > remaining_chars:
                        continue
                    remaining_chars -= len(chunk["text"])
                    result.append({**chunk, "score": scores.get(i, 0.0), "bm25_score": float(lexical[i]),
                                   "mode": mode, "context_role": role})
            coverage = {
                "selection_method": "balanced_course_v1", "scope": "representative_excerpts",
                "material_revision": state["revision"], "pdf_count": len(state["manifest"]["materials"]),
                "indexed_pdf_count": len(documents), "indexed_page_count": sum(map(len, documents.values())),
                "selected_pdf_count": len({item["source_file"] for item in result}),
                "selected_page_count": len({(item["source_file"], item["page_number"]) for item in result}),
                "selected_chunk_count": len(result),
                "text_chars": self.settings.max_context_chars - remaining_chars,
            }
            return [{**item, "context_coverage": dict(coverage)} for item in result]

    def diagnostics(self, subject: str | None = None) -> dict:
        embedding = self.embedder.diagnostics()
        result: dict = {
            "embedding": embedding,
            "indexed": False,
            "mode": "not_indexed",
            "pdf_count": 0,
            "chunk_count": 0,
            "warnings": [],
            "revision": None,
        }
        if subject is None:
            return {**result, "subject_count": len(self.discover_subjects())}
        files, path_warnings = self._files(subject)
        result.update({"subject": subject, "pdf_count": len(files), "warnings": path_warnings})
        state = self._indices.get(subject)
        if state:
            result.update(
                {
                    "indexed": True,
                    "mode": state["mode"],
                    "chunk_count": len(state["chunks"]),
                    "revision": state["revision"],
                    "warnings": state["warnings"],
                    "embedding_error": state["embedding_error"],
                }
            )
        return result
