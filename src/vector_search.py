"""
NumPyベースのベクトル検索モジュール（スクラッチ実装）。

ブラックボックスなベクトルDBを使わず、NumPyの行列演算で
Cosine Similarityを計算し、類似チャンクを検索する。
"""

import numpy as np
import time


def cosine_similarity(
    query_vector: np.ndarray,
    document_vectors: np.ndarray,
) -> np.ndarray:
    """
    クエリベクトルとドキュメントベクトル群のCosine Similarityを計算する。

    NumPyの行列演算（np.dot, np.linalg.norm）を使用したスクラッチ実装。

    Args:
        query_vector: クエリの埋め込みベクトル。形状 (embedding_dim,)
        document_vectors: ドキュメント群の埋め込みベクトル。形状 (n_docs, embedding_dim)

    Returns:
        各ドキュメントとの類似度スコア。形状 (n_docs,)
    """
    # クエリベクトルのL2ノルム
    query_norm: float = np.linalg.norm(query_vector)

    # 各ドキュメントベクトルのL2ノルム
    doc_norms: np.ndarray = np.linalg.norm(document_vectors, axis=1)

    # 内積計算（行列×ベクトル）
    dot_products: np.ndarray = np.dot(document_vectors, query_vector)

    # Cosine Similarity = 内積 / (|q| * |d|)
    # ゼロ除算を防ぐため、微小値を加算
    similarities: np.ndarray = dot_products / (query_norm * doc_norms + 1e-10)

    return similarities


def search(
    query_vector: np.ndarray,
    document_vectors: np.ndarray,
    chunks: list[dict],
    top_k: int = 5,
) -> dict:
    """
    クエリベクトルに最も類似するチャンクを上位k件返す。

    Args:
        query_vector: クエリの埋め込みベクトル
        document_vectors: 全ドキュメントの埋め込みベクトル
        chunks: チャンク情報のリスト
        top_k: 返却する上位件数

    Returns:
        検索結果とデバッグ情報を含む辞書。
        {
            "results": [(チャンク辞書, 類似度スコア), ...],
            "debug_info": {Shape情報の辞書}
        }
    """
    t_cosine_start: float = time.time()
    similarities: np.ndarray = cosine_similarity(query_vector, document_vectors)
    t_cosine_end: float = time.time()

    # 類似度の高い順にインデックスをソート
    t_sort_start: float = time.time()
    top_indices: np.ndarray = np.argsort(similarities)[::-1][:top_k]

    results: list[tuple[dict, float]] = [
        (chunks[i], float(similarities[i]))
        for i in top_indices
    ]
    t_sort_end: float = time.time()

    # ベクトル演算のShape情報を収集（計算ロジックには一切影響しない）
    # L2 Norm Breakdown: クエリとTop-1チャンクの因数分解
    top1_idx: int = int(top_indices[0]) if len(top_indices) > 0 else 0
    query_l2: float = float(np.linalg.norm(query_vector))
    top1_doc_l2: float = float(np.linalg.norm(document_vectors[top1_idx]))
    raw_dot: float = float(np.dot(query_vector, document_vectors[top1_idx]))

    debug_info: dict = {
        "query_shape": query_vector.shape,
        "docs_shape": document_vectors.shape,
        "similarities_shape": similarities.shape,
        "max_similarity": float(np.max(similarities)),
        "all_similarities": similarities.tolist(),
        "latency_cosine_ms": (t_cosine_end - t_cosine_start) * 1000,
        "latency_sort_ms": (t_sort_end - t_sort_start) * 1000,
        "query_l2_norm": round(query_l2, 6),
        "top1_doc_l2_norm": round(top1_doc_l2, 6),
        "raw_dot_product": round(raw_dot, 6),
    }

    # PCA 2D投影: ランダムサンプリング500チャンク + クエリ + top_k結果
    try:
        from sklearn.decomposition import PCA

        n_total: int = document_vectors.shape[0]
        k_sampleSize: int = min(500, n_total)

        rng = np.random.default_rng(seed=42)
        sample_indices: np.ndarray = rng.choice(n_total, size=k_sampleSize, replace=False)
        # top_kのインデックスも確実に含める
        all_indices: np.ndarray = np.unique(np.concatenate([sample_indices, top_indices]))
        sampled_docs: np.ndarray = document_vectors[all_indices]

        # クエリベクトルを先頭に結合
        combined: np.ndarray = np.vstack([query_vector.reshape(1, -1), sampled_docs])
        pca = PCA(n_components=2)
        coords_2d: np.ndarray = pca.fit_transform(combined)

        # top_kインデックスの位置を特定（combined配列内のオフセット）
        top_k_positions: set = set()
        for tk_idx in top_indices:
            pos = np.where(all_indices == tk_idx)[0]
            if len(pos) > 0:
                top_k_positions.add(int(pos[0]) + 1)  # +1はクエリ分のオフセット

        pca_plot_data: dict = {
            "query": {"x": float(coords_2d[0, 0]), "y": float(coords_2d[0, 1])},
            "chunks_x": coords_2d[1:, 0].tolist(),
            "chunks_y": coords_2d[1:, 1].tolist(),
            "top_k_positions": list(top_k_positions),
            "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
        }
        debug_info["pca_plot_data"] = pca_plot_data
    except Exception as e:
        debug_info["pca_plot_data"] = None
        print(f"PCA投影に失敗: {e}")

    return {
        "results": results,
        "debug_info": debug_info,
    }


if __name__ == "__main__":
    # ユニットテスト
    print("=== Cosine Similarity ユニットテスト ===")

    # テスト1: 同一ベクトル → 類似度 1.0
    v1 = np.array([1.0, 0.0, 0.0])
    docs = np.array([
        [1.0, 0.0, 0.0],  # 同一: 1.0
        [0.0, 1.0, 0.0],  # 直交: 0.0
        [0.5, 0.5, 0.0],  # 中間: 0.707...
    ])
    sims = cosine_similarity(v1, docs)
    print(f"類似度: {sims}")

    assert abs(sims[0] - 1.0) < 1e-6, f"テスト失敗: 同一ベクトルの類似度が {sims[0]}"
    assert abs(sims[1] - 0.0) < 1e-6, f"テスト失敗: 直交ベクトルの類似度が {sims[1]}"
    assert abs(sims[2] - 0.7071067) < 1e-4, f"テスト失敗: 中間ベクトルの類似度が {sims[2]}"

    print("全テスト合格 ✓")

    # テスト2: search関数の動作確認
    test_chunks = [
        {"text": "chunk_0", "page_number": 1, "chunk_index": 0},
        {"text": "chunk_1", "page_number": 1, "chunk_index": 1},
        {"text": "chunk_2", "page_number": 2, "chunk_index": 2},
    ]
    results = search(v1, docs, test_chunks, top_k=2)
    print(f"\n検索結果 (top_k=2):")
    for chunk, score in results:
        print(f"  スコア: {score:.4f} - {chunk['text']}")

    assert results[0][0]["text"] == "chunk_0", "検索順序が不正"
    print("search関数テスト合格 ✓")
