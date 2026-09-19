"""Validated NumPy cosine similarity, shared by the local retriever."""
from __future__ import annotations

import numpy as np


def cosine_similarity(query_vector: np.ndarray, document_vectors: np.ndarray) -> np.ndarray:
    query = np.asarray(query_vector, dtype=np.float32)
    documents = np.asarray(document_vectors, dtype=np.float32)
    if query.ndim != 1 or documents.ndim != 2 or documents.shape[1] != len(query):
        raise ValueError("Embeddingの次元が一致しません")
    if not np.isfinite(query).all() or not np.isfinite(documents).all():
        raise ValueError("Embeddingに非有限値があります")
    return documents @ query / np.maximum(np.linalg.norm(query) * np.linalg.norm(documents, axis=1), 1e-10)


def search(query_vector: np.ndarray, document_vectors: np.ndarray, chunks: list[dict], top_k: int = 5) -> dict:
    if len(document_vectors) != len(chunks):
        raise ValueError("Embeddingとchunk数が一致しません")
    scores = cosine_similarity(query_vector, document_vectors)
    indices = np.argsort(-scores, kind="stable")[:max(0, top_k)]
    return {"results": [(chunks[i], float(scores[i])) for i in indices],
            "debug_info": {"query_shape": query_vector.shape,
                           "docs_shape": document_vectors.shape,
                           "max_similarity": float(scores.max()) if len(scores) else None}}
