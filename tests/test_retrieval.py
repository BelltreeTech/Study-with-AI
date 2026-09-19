import socket
from pathlib import Path
from unittest.mock import Mock

import fitz
import numpy as np
import pytest

from src.embedder import EmbeddingUnavailable, LocalEmbedder
from src.pdf_reader import ExtractionSettings, PDFExtractionError, extract_text_from_pdf
from src.retriever import LocalRetriever, RetrievalSettings, UnsafeMaterialPath
from src.text_chunker import chunk_text
from src.vector_search import search as vector_search


class MissingEmbedder:
    def __init__(self, revision="fake-v1"):
        self.revision = revision

    def identity(self):
        return {
            "model": "test-only",
            "revision": self.revision,
            "dimensions": 3,
            "query_prefix": "query: ",
            "passage_prefix": "passage: ",
            "normalize": True,
        }

    def diagnostics(self):
        return {"downloaded": False, "loaded": False}

    def encode(self, texts, *, query=False):
        raise EmbeddingUnavailable("test model absent")


class FakeEmbedder(MissingEmbedder):
    def diagnostics(self):
        return {"downloaded": True, "loaded": True}

    def encode(self, texts, *, query=False):
        return np.asarray([[1.0, float("memory" in t), float("orbit" in t)] for t in texts], dtype=np.float32)


def make_pdf(path: Path, texts: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for text in texts:
        page = document.new_page()
        page.insert_text((40, 60), text, fontname="japan", fontsize=12)
    document.save(path)
    document.close()
    return path


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "data"
    make_pdf(
        root / "Science" / "Learning" / "notes.pdf",
        [
            "間隔反復は復習の間隔を長くする学習法です。検索練習では答えを思い出します。",
            "Spaced repetition supports memory retention. Review on day one, three, and seven.",
        ],
    )
    make_pdf(root / "Science" / "Space" / "notes.pdf", ["Planets orbit stars. Gravity affects the orbit."])
    return root, tmp_path / "cache"


def retriever(fixture, **kwargs):
    return LocalRetriever(*fixture, embedder=kwargs.pop("embedder", MissingEmbedder()), **kwargs)


def test_bilingual_local_search_and_provenance(fixture, monkeypatch):
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("network forbidden")))
    r = retriever(fixture)
    assert r.discover_subjects() == ["Science/Learning", "Science/Space"]
    for query, expected_page in (("間隔反復", 1), ("memory retention", 2)):
        result = r.search("Science/Learning", query)
        assert result and result[0]["page_number"] == expected_page
        assert result[0]["source_file"] == "Science/Learning/notes.pdf"
        assert result[0]["source_id"].startswith("S-")
        assert len(result[0]["content_hash"]) == 64
        assert result[0]["mode"] == "bm25"
    assert r.search("Science/Learning", "orbit") == []
    assert r.search("Science/Space", "orbit")[0]["source_file"] == "Science/Space/notes.pdf"
    assert r.diagnostics("Science/Learning")["mode"] == "bm25"


def test_diagnostics_and_discovery_do_not_load_model(fixture):
    e = MissingEmbedder()
    e.encode = Mock(side_effect=AssertionError("must remain lazy"))
    r = retriever(fixture, embedder=e)
    assert r.diagnostics("Science/Learning")["indexed"] is False
    assert r.diagnostics()["subject_count"] == 2
    assert r.revision("Science/Learning")
    e.encode.assert_not_called()


def test_content_changes_even_same_size_and_deletion(fixture):
    r = retriever(fixture)
    subject = "Science/Space"
    path = fixture[0] / subject / "notes.pdf"
    first = r.revision(subject)
    original = path.read_bytes()
    # A valid PDF byte change of identical length changes the digest, regardless of mtime/size.
    changed = original.replace(b"/Type/Page", b"/Type/Page", 1).replace(b"/Producer", b"/Producer", 1)
    changed = changed.replace(b"%PDF-1.7", b"%PDF-1.6", 1)
    assert changed != original and len(changed) == len(original)
    path.write_bytes(changed)
    assert r.revision(subject) != first
    r.index(subject)
    path.unlink()
    assert r.search(subject, "orbit") == []
    assert r.diagnostics(subject)["pdf_count"] == 0


def test_added_material_and_model_revision_change_cache(fixture):
    r = retriever(fixture)
    original = r.revision("Science/Learning")
    make_pdf(fixture[0] / "Science/Learning/new.pdf", ["New material has photosynthesis."])
    assert r.revision("Science/Learning") != original
    changed = retriever(fixture, embedder=MissingEmbedder("fake-v2"))
    assert changed.revision("Science/Learning") != r.revision("Science/Learning")
    assert changed.search("Science/Learning", "photosynthesis")[0]["source_file"].endswith("new.pdf")


def test_settings_change_cache(fixture):
    a = retriever(fixture)
    b = retriever(fixture, settings=RetrievalSettings(chunk_size=200))
    assert a.revision("Science/Learning") != b.revision("Science/Learning")


def test_cache_reuse_and_integrity_no_legacy_mix(fixture, monkeypatch):
    r = retriever(fixture, embedder=FakeEmbedder())
    first = r.search("Science/Learning", "memory")
    assert first[0]["mode"] == "hybrid"
    namespace = fixture[1] / "local-retrieval-v2"
    cache = next(namespace.glob("*.npz"))
    legacy = fixture[1] / "embeddings_old.npy"
    np.save(legacy, np.ones((3, 1536)))
    e = FakeEmbedder()
    original_encode = e.encode
    e.encode = Mock(
        side_effect=lambda texts, query=False: (
            original_encode(texts, query=query) if query else pytest.fail("re-embedded valid cache")
        )
    )
    assert retriever(fixture, embedder=e).search("Science/Learning", "memory") == first
    with np.load(cache, allow_pickle=False) as archive:
        metadata = str(archive["metadata"].item())
    # A mismatched number of vector rows must rebuild the new namespace.
    with cache.open("wb") as stream:
        np.savez_compressed(stream, metadata=metadata, vectors=np.ones((1, 3)))
    assert retriever(fixture, embedder=FakeEmbedder()).search("Science/Learning", "memory")
    assert np.load(legacy).shape == (3, 1536)


@pytest.mark.parametrize(
    "subject",
    [
        "../private",
        "/etc/passwd",
        "Science/../Space",
        "Science//Learning",
        "Science\\Learning",
        "Science",
        "./Science/Learning",
    ],
)
def test_subject_path_rejected(fixture, subject):
    with pytest.raises(UnsafeMaterialPath):
        retriever(fixture).search(subject, "hello")


def test_symlink_paths_rejected(fixture, tmp_path):
    external = make_pdf(tmp_path / "outside.pdf", ["External secret must not be searched"])
    (fixture[0] / "Science/Learning/linked.pdf").symlink_to(external)
    (fixture[0] / "Science/Alias").symlink_to(fixture[0] / "Science/Space", target_is_directory=True)
    r = retriever(fixture)
    assert "Science/Alias" not in r.discover_subjects()
    assert r.search("Science/Learning", "External secret") == []
    assert "symlink_rejected" in [w["code"] for w in r.diagnostics("Science/Learning")["warnings"]]
    with pytest.raises(UnsafeMaterialPath):
        r.index("Science/Alias")


def test_broken_pdf_does_not_break_other_materials(fixture):
    (fixture[0] / "Science/Learning/broken.pdf").write_bytes(b"invalid pdf")
    r = retriever(fixture)
    assert r.search("Science/Learning", "memory")
    assert "pdf_extraction_failed" in [w["code"] for w in r.diagnostics("Science/Learning")["warnings"]]


def test_empty_query_empty_corpus_and_bounds(tmp_path, fixture):
    r = LocalRetriever(tmp_path / "empty", tmp_path / "cache", embedder=MissingEmbedder())
    assert r.discover_subjects() == []
    assert r.search("Sample/Empty", "anything") == []
    assert r.search("Sample/Empty", " ") == []
    assert r.search("Sample/Empty", "anything", 0) == []
    r = retriever(fixture, settings=RetrievalSettings(max_results=1, max_context_chars=400))
    assert len(r.search("Science/Learning", "repetition 間隔反復", 50)) == 1


def test_page_selective_ocr_mixed_pdf_and_missing_dependency(tmp_path):
    import io

    from PIL import Image

    image = Image.new("RGB", (100, 50), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 60), "Text layer is available and should never be OCR processed.")
    page = document.new_page()
    page.insert_image(fitz.Rect(40, 40, 240, 140), stream=buffer.getvalue())
    document.new_page()  # blank third page remains numbered
    raw = document.tobytes()
    document.close()
    ocr = Mock(return_value="画像だけのページをOCRしました")
    pages = extract_text_from_pdf(raw, ocr=ocr)
    assert len(pages) == 3 and pages[1]["page_number"] == 2
    assert pages[0]["method"] == "text" and pages[1]["method"] == "ocr"
    assert pages[2]["text"] == ""
    assert ocr.call_count == 1
    failed = extract_text_from_pdf(raw, ocr=Mock(side_effect=RuntimeError("no tesseract")))
    assert failed[0]["text"] == pages[0]["text"]
    assert failed[1]["warnings"] == ["ocr_unavailable_or_failed"]


def test_pdf_limits_and_corruption(tmp_path):
    with pytest.raises(PDFExtractionError):
        extract_text_from_pdf(b"not a pdf")
    path = make_pdf(tmp_path / "two.pdf", ["page one", "page two"])
    with pytest.raises(PDFExtractionError):
        extract_text_from_pdf(path, settings=ExtractionSettings(max_pages=1))
    with pytest.raises(PDFExtractionError):
        extract_text_from_pdf(path, settings=ExtractionSettings(max_pdf_bytes=10))


def test_chunks_have_no_duplicate_tail_and_keep_provenance():
    page = {
        "text": "A" * 1000,
        "page_number": 2,
        "source_file": "A/B/book.pdf",
        "document_id": "D-test",
        "content_hash": "a" * 64,
    }
    chunks = chunk_text([page], 400, 60)
    assert [c["char_start"] for c in chunks] == [0, 340, 680]
    assert chunks[-1]["char_end"] == 1000
    assert all(c["page_number"] == 2 and c["source_file"] == "A/B/book.pdf" for c in chunks)
    assert len({c["source_id"] for c in chunks}) == 3
    with pytest.raises(ValueError):
        chunk_text([page], 10, 10)


def test_local_embedder_prefixes_shape_and_normalization(tmp_path):
    e = LocalEmbedder(tmp_path)
    e._model = Mock()
    e._model.encode.return_value = np.ones((1, 384), dtype=np.float32)
    assert e.encode(["日本語"])[0].shape == (384,)
    assert e._model.encode.call_args.args[0] == ["passage: 日本語"]
    assert e._model.encode.call_args.kwargs["normalize_embeddings"] is True
    e.encode(["English"], query=True)
    assert e._model.encode.call_args.args[0] == ["query: English"]
    e._model.encode.return_value = np.ones((1, 1536))
    with pytest.raises(EmbeddingUnavailable):
        e.encode(["bad dimension"])


def test_missing_embedding_is_explicit_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("network forbidden")))
    e = LocalEmbedder(tmp_path)
    assert e.diagnostics()["downloaded"] is False
    with pytest.raises(EmbeddingUnavailable):
        e.encode(["test"])
    assert "BM25" in e.diagnostics()["error"]


def test_vector_search_empty_and_shape_validation():
    assert vector_search(np.zeros(3), np.empty((0, 3)), [])["results"] == []
    with pytest.raises(ValueError):
        vector_search(np.zeros(3), np.ones((1, 3)), [])
    with pytest.raises(ValueError):
        vector_search(np.zeros(4), np.ones((1, 3)), [{}])


def test_model_download_upgrades_existing_bm25_index(fixture):
    class SwitchableEmbedder(FakeEmbedder):
        downloaded = False

        def diagnostics(self):
            return {"downloaded": self.downloaded, "loaded": self.downloaded}

        def encode(self, texts, *, query=False):
            if not self.downloaded:
                raise EmbeddingUnavailable("missing")
            return super().encode(texts, query=query)

    embedder = SwitchableEmbedder()
    r = retriever(fixture, embedder=embedder)
    assert r.search("Science/Learning", "memory")[0]["mode"] == "bm25"
    embedder.downloaded = True
    assert r.search("Science/Learning", "memory")[0]["mode"] == "hybrid"


def test_query_embedding_failure_degrades_explicitly(fixture):
    class FailedQueryEmbedder(FakeEmbedder):
        def encode(self, texts, *, query=False):
            if query:
                raise EmbeddingUnavailable("query embedding failed")
            return super().encode(texts, query=query)

    r = retriever(fixture, embedder=FailedQueryEmbedder())
    results = r.search("Science/Learning", "memory")
    assert results and results[0]["mode"] == "bm25"
    assert r.diagnostics("Science/Learning")["mode"] == "bm25"
    assert r.diagnostics("Science/Learning")["embedding_error"] == "query embedding failed"


def test_runtime_package_metadata_is_stable_after_construction(fixture, tmp_path, monkeypatch):
    import importlib.metadata

    embedder = LocalEmbedder(tmp_path / "absent")
    r = retriever(fixture, embedder=embedder)
    original_identity = embedder.identity()
    original_revision = r.revision("Science/Learning")
    missing = Mock(side_effect=importlib.metadata.PackageNotFoundError("transient concurrent metadata lookup"))
    monkeypatch.setattr(importlib.metadata, "version", missing)
    assert embedder.identity() == original_identity
    assert r.revision("Science/Learning") == original_revision
    missing.assert_not_called()
    # Callers cannot mutate the owned runtime identity via a returned dict.
    identity = embedder.identity()
    identity["libraries"]["torch"] = "not-the-loaded-runtime"
    assert embedder.identity() == original_identity


def test_library_metadata_discovery_uses_frozen_path(monkeypatch):
    import importlib.metadata
    import sys
    from types import SimpleNamespace

    from src.embedder import installed_library_version

    before = tuple(sys.path)

    def discover(**kwargs):
        assert kwargs["context"].name == "synthetic-library"
        assert kwargs["context"].path is not sys.path
        assert kwargs["context"].path == list(before)
        return iter([SimpleNamespace(version="1.0-synthetic")])

    monkeypatch.setattr(importlib.metadata.Distribution, "discover", discover)
    assert installed_library_version("synthetic-library") == "1.0-synthetic"
