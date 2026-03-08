"""
NumPyベースのベクトル検索モジュール（スクラッチ実装）。

ブラックボックスなベクトルDB（Pinecone, Chroma, FAISS等）を使わず、NumPyの行列演算で
Cosine Similarityを計算し、類似チャンクを検索する。

🧮 【数学的背景】
ベクトル検索は、テキストを高次元空間上の「座標（ベクトル）」に変換し、
座標間の「距離」や「角度」で意味的な近さを測る技術である。
これはTransformerのAttention機構が「どのトークンに注目すべきか」を決めるために
Query-Key間の内積（Dot Product）を計算するのと、本質的に同じ原理である。

💡 【直感的な意味】
- テキストを「意味の座標」に変換 → Embedding
- 座標間の「角度の近さ」で類似度を測定 → Cosine Similarity
- 最も近いK個を返す → KNN（K-Nearest Neighbor）検索
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

    🧮 【数学的定義】
    Cosine Similarity(q, d) = (q · d) / (||q|| * ||d||)

    ここで:
    - q · d = Σ(q_i * d_i) は内積（Dot Product）。
      ニューラルネットワークの全結合層（Linear層）: y = Wx + b の Wx 部分と同一の計算。
    - ||q|| = sqrt(Σ(q_i^2)) はL2ノルム（ユークリッドノルム）。
      ベクトルの「長さ」を表し、正規化に使用される。

    📐 【Shape】
    - query_vector: (embedding_dim,) — 例: (1536,) for text-embedding-3-small
    - document_vectors: (n_docs, embedding_dim) — 例: (500, 1536)
    - 戻り値: (n_docs,) — 各ドキュメントとの類似度スコア

    💡 【直感的意味とDL概念との紐付け】
    この計算はTransformerのScaled Dot-Product Attentionの核心部分と等価である。
    Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V
    のうち、QK^T の計算がまさにこの内積計算に相当する。
    - Q（Query）= ユーザーの質問ベクトル
    - K（Key）= 各ドキュメントチャンクのベクトル
    ベクトルの「方向」が近いほど意味が近い、という幾何学的直感に基づく。
    コサイン類似度はベクトルの「大きさ」を無視し「方向」のみで比較するため、
    文章の長さに左右されない頑健な類似度指標となる。

    Args:
        query_vector: クエリの埋め込みベクトル。形状 (embedding_dim,)
        document_vectors: ドキュメント群の埋め込みベクトル。形状 (n_docs, embedding_dim)

    Returns:
        各ドキュメントとの類似度スコア。形状 (n_docs,)
    """
    # 🧮 L2ノルム（ユークリッドノルム）: ||q|| = sqrt(Σ(q_i^2))
    # 📐 Shape: スカラー値（float）
    # 💡 ベクトルの「長さ」。正規化の分母に使う。DLではWeight Normalizationと同じ考え方。
    query_norm: float = np.linalg.norm(query_vector)

    # 🧮 各ドキュメントベクトルのL2ノルム: ||d_j|| for j in [0, n_docs)
    # 📐 Shape: (n_docs,) — 各ドキュメントに対応するノルム値のベクトル
    # 💡 axis=1で「行方向」（各ドキュメント独立）にノルムを計算
    doc_norms: np.ndarray = np.linalg.norm(document_vectors, axis=1)

    # 🧮 内積（Dot Product）: q · d_j = Σ(q_i * d_j_i) for each document j
    # 📐 Shape: (n_docs, embedding_dim) @ (embedding_dim,) → (n_docs,)
    # 💡 行列×ベクトルの積。NNの全結合層（y = Wx）と完全に同じ計算。
    #    GPUではこの計算がGEMM（General Matrix Multiply）として超高速に実行される。
    dot_products: np.ndarray = np.dot(document_vectors, query_vector)

    # 🧮 Cosine Similarity = (q · d) / (||q|| * ||d|| + ε)
    # 📐 Shape: (n_docs,) — 要素ごとの除算（element-wise division）
    # 💡 ε = 1e-10 はゼロ除算防止の微小値。DLのLayerNormやBatchNormでも同様のトリックを使う。
    #    結果は [-1, 1] の範囲。1に近いほど意味が近い。
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

    🧮 【アルゴリズム】
    1. Cosine Similarityで全チャンクとの類似度を一括計算（ブルートフォース検索）
    2. np.argsort で類似度降順にソート
    3. 上位K件のインデックスを取得（KNN: K-Nearest Neighbor）

    💡 【直感的意味】
    大規模なベクトルDBでは近似最近傍探索（ANN: Approximate Nearest Neighbor）を使うが、
    本実装ではNumPyの行列演算による厳密検索（Exact Search）を行っている。
    数千チャンク規模であればブルートフォースでも十分高速（< 10ms）。

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
    # 📐 Shape: (n_docs,) — 全ドキュメントとの類似度スコア
    similarities: np.ndarray = cosine_similarity(query_vector, document_vectors)
    t_cosine_end: float = time.time()

    # 🧮 np.argsort: 類似度を昇順ソートしたインデックス配列を返す
    #    [::-1] で降順に反転し、[:top_k] で上位K件を切り出す
    # 📐 Shape: (top_k,) — 上位K件のドキュメントインデックス
    # 💡 これがKNN（K-Nearest Neighbor）の「K件選択」に相当する
    t_sort_start: float = time.time()
    top_indices: np.ndarray = np.argsort(similarities)[::-1][:top_k]

    # 💡 インデックスから実際のチャンクオブジェクトとスコアのペアを構築
    # 📐 型: List[Tuple[Dict, float]] — [(チャンク辞書, 類似度スコア), ...]
    results: list[tuple[dict, float]] = [
        (chunks[i], float(similarities[i]))
        for i in top_indices
    ]
    t_sort_end: float = time.time()

    # ベクトル演算のShape情報を収集（計算ロジックには一切影響しない）
    # 💡 デバッグモードでの「ベクトル演算の透明化」に使用。
    #    学習者がベクトル空間の構造を直感的に理解するための情報。
    # L2 Norm Breakdown: クエリとTop-1チャンクの因数分解
    top1_idx: int = int(top_indices[0]) if len(top_indices) > 0 else 0
    # 📐 query_l2, top1_doc_l2: スカラー値（float）
    query_l2: float = float(np.linalg.norm(query_vector))
    top1_doc_l2: float = float(np.linalg.norm(document_vectors[top1_idx]))
    # 🧮 正規化前の生の内積値。cosine_sim = raw_dot / (query_l2 * top1_doc_l2)
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

    # ================================================================
    # PCA 2D投影: 高次元ベクトル空間を人間が視覚的に理解するための次元削減
    # ================================================================
    # 🧮 【数学的定義】
    # PCA（Principal Component Analysis, 主成分分析）は、データの分散が最大となる
    # 直交軸（主成分）を見つけ、高次元データを低次元に射影する手法。
    # 具体的には、共分散行列の固有値分解を行い、固有値の大きい順に
    # 固有ベクトル（主成分軸）を選択する。
    #
    # 💡 【直感的意味】
    # 1536次元の埋め込み空間は人間には可視化できない。
    # PCAで2次元に「潰す」ことで、「クエリと各チャンクがどの程度近いか」を
    # 2Dの散布図として視覚的に理解できるようになる。
    # ただし情報の損失は避けられない（explained_variance_ratioで損失率を確認できる）。
    try:
        from sklearn.decomposition import PCA

        n_total: int = document_vectors.shape[0]
        k_sampleSize: int = min(500, n_total)

        # 💡 全チャンクをPCAに通すとメモリ・計算コストが大きいため、
        #    ランダムに500件をサンプリング（seed=42で再現性を担保）
        rng = np.random.default_rng(seed=42)
        sample_indices: np.ndarray = rng.choice(n_total, size=k_sampleSize, replace=False)
        # 📐 Shape: (k_sampleSize,) — サンプリングされたインデックス

        # top_kのインデックスも確実に含める（検索結果がプロット上で見えるように）
        all_indices: np.ndarray = np.unique(np.concatenate([sample_indices, top_indices]))
        # 📐 Shape: (n_unique,) — 重複除去後のインデックス
        sampled_docs: np.ndarray = document_vectors[all_indices]
        # 📐 Shape: (n_unique, embedding_dim)

        # 🧮 クエリベクトルを先頭に結合し、同一のPCA空間に射影する
        # 📐 Shape: (1 + n_unique, embedding_dim) → PCA後: (1 + n_unique, 2)
        # 💡 クエリとドキュメントを同じ変換行列で射影することで、
        #    2D上での相対的な位置関係が保存される
        combined: np.ndarray = np.vstack([query_vector.reshape(1, -1), sampled_docs])
        pca = PCA(n_components=2)
        coords_2d: np.ndarray = pca.fit_transform(combined)
        # 📐 coords_2d Shape: (1 + n_unique, 2) — [0]がクエリ、[1:]がドキュメント

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
            # 💡 explained_variance_ratio: 各主成分が元データの分散をどれだけ説明しているか
            #    例: [0.15, 0.08] → 第1主成分15%, 第2主成分8% → 合計23%の情報を保持
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
