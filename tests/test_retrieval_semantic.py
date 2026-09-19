"""Opt-in local model evaluation. No credentials, generation or network are used.

STUDY_TEST_LOCAL_EMBEDDING=1 uv run --extra semantic pytest tests/test_retrieval_semantic.py -q
"""
import os
import socket
from unittest.mock import Mock

import fitz
import numpy as np
import pytest

from src.embedder import LocalEmbedder
from src.retriever import LocalRetriever


@pytest.mark.skipif(os.environ.get("STUDY_TEST_LOCAL_EMBEDDING") != "1",
                    reason="opt-in: pinned local embedding model required")
def test_real_e5_offline_prefix_normalization_and_cross_language_search(tmp_path, monkeypatch):
    blocked = Mock(side_effect=AssertionError("Network is forbidden during local embedding/search"))
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    embedder = LocalEmbedder()
    vectors = embedder.encode(["間隔反復は復習を分散する学習法です。", "Spaced repetition supports memory."])
    assert vectors.shape == (2, 384)
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1.0, 1.0], abs=1e-5)
    data = tmp_path / "data" / "Example" / "Languages"
    data.mkdir(parents=True)
    texts = {
        "memory": "Spaced repetition improves memory retention by reviewing material at increasing intervals.",
        "gravity": "惑星は恒星の周りを公転します。太陽の重力が惑星の軌道を曲げます。",
        "plants": "Photosynthesis is the process by which plants convert sunlight into chemical energy, using water and carbon dioxide.",
        "calculus": "微分は関数の変化率を求める計算です。積分では小さな部分を合計して面積を求めます。",
    }
    for name, text in texts.items():
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 60), text, fontname="japan", fontsize=10)
            document.save(data / f"{name}.pdf")
    retriever = LocalRetriever(tmp_path / "data", tmp_path / "cache", embedder=embedder)
    queries = [("memory retention", "memory"), ("惑星の公転", "gravity"),
               ("植物が光からエネルギーを作るしくみ", "plants"),
               ("derivatives and integrals in mathematics", "calculus")]
    for query, expected in queries:
        results = retriever.search("Example/Languages", query, top_k=1)
        assert results[0]["source_file"].endswith(f"{expected}.pdf"), (query, results)
        assert results[0]["mode"] == "hybrid"
    blocked.assert_not_called()
