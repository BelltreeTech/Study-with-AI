"""
ドキュメント検索コアモジュール。

PDF読み込み → チャンク分割 → Embedding生成 → ベクトル検索 → LLM回答生成
の一連のRAG検索処理を担当する。教育コンテンツ生成ロジックは含まない。

🧮 【RAG（Retrieval-Augmented Generation）のアーキテクチャ】
RAGは、LLMの「知識の限界」を外部データベースで補完する手法。
LLMは事前学習データに含まれない最新情報や専門知識を持たないため、
「検索（Retrieval）」で関連文書を取得し、「生成（Generation）」のプロンプトに注入する。

処理フロー:
  1. PDF → ページ抽出 → チャンク分割（LLMのContext Window制限に対応）
  2. 各チャンク → Embedding（高次元ベクトルへの変換）
  3. ユーザー質問 → Query Expansion → Embedding → ハイブリッド検索（Vector + BM25）
  4. 検索結果のチャンク → LLMのプロンプトに注入（In-Context Learning）
  5. LLM → 根拠に基づく回答生成

💡 【直感的意味】
RAGは「試験前に教科書の該当ページを開いてから回答する学生」のようなもの。
LLM単体は「暗記だけで答える学生」に相当し、記憶にない情報には答えられないか、
でたらめ（ハルシネーション）を生成するリスクがある。
"""

import numpy as np
import time
import math
from openai import OpenAI
from janome.tokenizer import Tokenizer
from rank_bm25 import BM25Okapi

from src.embedder import (
    generate_cache_key,
    generate_embeddings,
    load_cache,
    save_cache,
    _get_client,
)
from src.pdf_reader import extract_text_from_pdf
from src.text_chunker import chunk_text
from src.vector_search import search
from src.config import (
    LLM_MODEL,
    TEMPERATURE_QUERY_EXPANSION,
    MAX_TOKENS_QUERY_EXPANSION,
    TEMPERATURE_RAG_ANSWER,
    MAX_TOKENS_RAG_ANSWER,
)


class RAGCore:
    """
    ドキュメント検索コア。

    初期化時に指定された科目フォルダ内のPDFを自動読み込み・チャンク分割・Embedding生成し、
    query()メソッドで質問応答を行う。

    🧮 【内部データ構造】
    - _chunks: List[Dict] — 分割されたテキストチャンクのリスト
      各要素: {"text": str, "page_number": int, "chunk_index": int, "source_file": str}
    - _embeddings: np.ndarray — 全チャンクの埋め込みベクトル行列
      📐 Shape: (n_chunks, embedding_dim) — 例: (500, 1536)
    - _bm25: BM25Okapi | None — BM25キーワード検索用のインデックス
    """

    def __init__(self, target_subject: str) -> None:
        """
        RAGコアを初期化する。

        指定された科目のPDFを data/{target_subject}/ から読み込み、
        キャッシュを vector_stores/{target_subject}/ に保存する。

        💡 【初期化の流れ】
        1. キャッシュ確認 → 存在すれば即復元（高速起動）
        2. キャッシュなし → PDF読み込み → チャンク分割 → Embedding生成 → キャッシュ保存
        Embedding生成はOpenAI APIを呼ぶため、初回はネットワーク通信コストが発生する。

        Args:
            target_subject: 科目名（data/配下のサブフォルダ名）
        """
        from pathlib import Path

        self._client: OpenAI = _get_client()
        # 📐 型: List[Dict] — チャンク情報のリスト
        self._chunks: list[dict] = []
        # 📐 型: np.ndarray, Shape: (0,) → 初期化後: (n_chunks, embedding_dim)
        self._embeddings: np.ndarray = np.array([])
        self._subject: str = target_subject
        self._skipped_files: list[str] = []
        self.docs: list[dict] = []
        # 💡 Janome: 日本語形態素解析エンジン。BM25のために日本語テキストを単語に分割する。
        #    英語ではスペースで分割できるが、日本語は形態素解析が必要。
        self._tokenizer: Tokenizer = Tokenizer()
        self._bm25: BM25Okapi | None = None

        # 科目ごとのパスを設定
        data_dir: Path = Path("data") / target_subject
        cache_dir: Path = Path("vector_stores") / target_subject

        # 対象PDFを自動検出
        if not data_dir.exists():
            raise FileNotFoundError(f"科目ディレクトリが見つかりません: {data_dir}")
        pdf_paths: list[str] = sorted(
            str(p) for p in data_dir.rglob("*.pdf")
        )
        if not pdf_paths:
            raise FileNotFoundError(f"PDFファイルが見つかりません: {data_dir}")

        # 💡 PDF組み合わせに基づくキャッシュキー生成
        #    PDFファイル名とサイズからハッシュを計算し、PDFが変更されたらキャッシュを無効化する
        cache_key: str = generate_cache_key(pdf_paths)

        # キャッシュの読み込みを試行（科目別ディレクトリ）
        cached = load_cache(cache_key, cache_dir)
        if cached is not None:
            self._embeddings, self._chunks = cached
            print(f"[{target_subject}] キャッシュからインデックスを復元: {len(self._chunks)} チャンク")
            return

        # キャッシュがない場合、PDFから新規構築
        print(f"[{target_subject}] PDFからインデックスを構築中...")

        # 1. 全PDFからテキストを抽出し、チャンクを統合
        print(f"1/3: PDF読み込み中... ({len(pdf_paths)} ファイル)")
        all_pages: list[dict] = []
        for pdf_path in pdf_paths:
            print(f"  読み込み中: {pdf_path}")
            try:
                pages: list[dict] = extract_text_from_pdf(pdf_path)
            except Exception as e:
                file_name: str = Path(pdf_path).name
                print(f"  ⚠️ 読み込みスキップ: {file_name} ({e})")
                self._skipped_files.append(file_name)
                continue
            # テキストが空の場合もスキップ
            if not pages:
                file_name = Path(pdf_path).name
                print(f"  ⚠️ テキスト抽出結果が空: {file_name}")
                self._skipped_files.append(file_name)
                continue
            # ソース元PDFのファイル名をページ情報に付加
            for page in pages:
                page["source_file"] = pdf_path
            all_pages.extend(pages)
            self.docs.extend(pages)

        if not all_pages:
            raise FileNotFoundError(
                f"すべてのPDFの読み込みに失敗しました: {data_dir}"
            )
        print(f"  抽出完了: 合計 {len(all_pages)} ページ")

        # 2. 統合されたページ群をチャンク分割
        # 💡 LLMのContext Window（入力可能なトークン数）には上限があるため、
        #    長い文書を適切なサイズの「チャンク」に分割して管理する
        print("2/3: チャンク分割中...")
        self._chunks = chunk_text(all_pages)
        print(f"  分割完了: {len(self._chunks)} チャンク")

        # 3. Embedding生成
        # 💡 テキスト → 高次元ベクトルへの変換。OpenAIのtext-embedding-3-smallモデルを使用。
        #    各チャンクが1536次元の「意味の座標」に変換される。
        print("3/3: Embedding生成中...")
        texts: list[str] = [c["text"] for c in self._chunks]
        # 📐 Shape: (n_chunks, embedding_dim) — 例: (500, 1536)
        self._embeddings = generate_embeddings(texts)
        print(f"  生成完了: 形状 {self._embeddings.shape}")

        # キャッシュに保存（科目別ディレクトリ）
        save_cache(self._embeddings, self._chunks, cache_key, cache_dir)
        print(f"[{target_subject}] インデックス構築完了!")

    # ================================================================
    # BM25 キーワード検索インデックス
    # ================================================================

    def _build_bm25_index(self) -> None:
        """
        チャンクのテキストを形態素解析しBM25インデックスを構築する。

        🧮 【BM25（Best Matching 25）の数学的定義】
        BM25スコア = Σ IDF(t) * (tf(t,d) * (k1 + 1)) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))

        ここで:
        - IDF(t) = log((N - df(t) + 0.5) / (df(t) + 0.5)) : 逆文書頻度
        - tf(t,d): 文書d中の語tの出現頻度
        - k1, b: パラメータ（通常 k1=1.5, b=0.75）
        - |d|: 文書dの長さ, avgdl: 全文書の平均長

        💡 【直感的意味】
        BM25は「キーワードがどれだけ珍しいか（IDF）」×「どれだけ多く出現するか（TF）」
        で文書の関連度を測る、古典的だが強力な情報検索アルゴリズム。
        ベクトル検索が「意味的な類似性」を捉えるのに対し、
        BM25は「キーワードの一致」を捉える。両者は相補的。
        """
        if not self._chunks:
            return
        # 💡 Janomeで日本語テキストを単語（形態素）のリストに分割
        # 📐 型: List[List[str]] — 例: [["勾配", "消失", "問題"], ["活性化", "関数"]]
        tokenized_corpus: list[list[str]] = [
            [token.surface for token in self._tokenizer.tokenize(chunk["text"])]
            for chunk in self._chunks
        ]
        # 💡 BM25Okapiインデックスを構築。これはTF-IDFの改良版で、
        #    文書長の正規化（b パラメータ）と飽和関数（k1 パラメータ）を含む。
        self._bm25 = BM25Okapi(tokenized_corpus)

    # ================================================================
    # ハイブリッド検索（Vector + BM25 + RRF）
    # ================================================================

    def _hybrid_search(
        self,
        query_embedding: np.ndarray,
        query_text: str,
        top_k: int = 5,
    ) -> dict:
        """
        ベクトル検索とBM25検索をRRF（Reciprocal Rank Fusion）で統合する。

        🧮 【RRF（Reciprocal Rank Fusion）の数学的定義】
        RRF_score(d) = Σ 1 / (k + rank_i(d))

        ここで:
        - k = 60（定数。オリジナル論文の推奨値）
        - rank_i(d) = ランキングシステム i における文書 d の順位（1始まり）

        本実装では i ∈ {ベクトル検索, BM25} の2つのランキングを融合する。

        💡 【直感的意味】
        ベクトル検索は「意味的な近さ」を、BM25は「キーワードの一致」を捉える。
        RRFは両方のランキングを統合することで、どちらか片方だけでは見逃す文書も拾える。
        例えば「Transformer」という固有名詞はBM25が得意、
        「注意機構の仕組み」という言い換えはベクトル検索が得意。

        📐 【Shape の流れ】
        query_embedding: (embedding_dim,)
        → cosine_similarity → vec_similarities: (n_chunks,)
        → BM25 → bm25_scores: (n_chunks,)
        → RRF融合 → rrf_scores: List[Tuple[int, float]]
        → Top-K選択 → results: List[Tuple[Dict, float]]

        戻り値の型・構造は既存のvector_search.searchと完全に互換。

        Args:
            query_embedding: クエリの埋め込みベクトル
            query_text: クエリのテキスト（BM25用）
            top_k: 返却する上位件数

        Returns:
            {"results": [(chunk, rrf_score), ...], "debug_info": dict}
        """
        from src.vector_search import cosine_similarity

        # BM25インデックスが未構築なら構築（遅延初期化パターン）
        if self._bm25 is None:
            self._build_bm25_index()

        n_chunks: int = len(self._chunks)
        # 🧮 RRFの定数k。値が大きいほどランキング上位と下位のスコア差が小さくなる。
        #    k=60はオリジナル論文（Cormack et al., 2009）の推奨値。
        k_rrfConstant: int = 60

        # --- ベクトル検索（Semantic Search）---
        # 💡 コサイン類似度で全チャンクとの意味的近さを計算
        t_cosine_start: float = time.time()
        # 📐 Shape: (n_chunks,) — 各チャンクとのコサイン類似度
        vec_similarities: np.ndarray = cosine_similarity(query_embedding, self._embeddings)
        t_cosine_end: float = time.time()
        # 📐 Shape: (n_chunks,) — 類似度降順のインデックス配列
        vec_ranked_indices: np.ndarray = np.argsort(vec_similarities)[::-1]
        # 💡 インデックス → 順位のマッピングを構築（RRF計算で使用）
        # 📐 型: Dict[int, int] — {チャンクインデックス: 順位(1始まり)}
        vec_rank_map: dict[int, int] = {int(idx): rank + 1 for rank, idx in enumerate(vec_ranked_indices)}

        # --- BM25検索（Keyword Search）---
        # 💡 クエリを形態素解析し、BM25スコアを計算
        tokenized_query: list[str] = [token.surface for token in self._tokenizer.tokenize(query_text)]
        if self._bm25 is not None and tokenized_query:
            # 📐 Shape: (n_chunks,) — 各チャンクのBM25スコア
            bm25_scores: np.ndarray = self._bm25.get_scores(tokenized_query)
        else:
            bm25_scores = np.zeros(n_chunks)
        # 📐 Shape: (n_chunks,) — BM25スコア降順のインデックス配列
        bm25_ranked_indices: np.ndarray = np.argsort(bm25_scores)[::-1]
        # 📐 型: Dict[int, int] — {チャンクインデックス: BM25順位(1始まり)}
        bm25_rank_map: dict[int, int] = {int(idx): rank + 1 for rank, idx in enumerate(bm25_ranked_indices)}

        # --- RRFスコア計算 ---
        # 🧮 RRF_score(d) = 1/(k + vec_rank(d)) + 1/(k + bm25_rank(d))
        # 💡 各チャンクに対して、2つのランキングからのRRFスコアを合算する
        rrf_scores: list[tuple[int, float]] = []
        for i in range(n_chunks):
            v_rank: int = vec_rank_map.get(i, n_chunks)
            b_rank: int = bm25_rank_map.get(i, n_chunks)
            # 🧮 1/(60+1) ≈ 0.0164 （1位） vs 1/(60+500) ≈ 0.0018 （500位）
            #    上位の文書ほどスコアへの寄与が大きい（非線形な重み付け）
            rrf_score: float = (1.0 / (k_rrfConstant + v_rank)) + (1.0 / (k_rrfConstant + b_rank))
            rrf_scores.append((i, rrf_score))

        # RRFスコアの降順でソートし、上位top_k件を取得
        rrf_scores.sort(key=lambda x: x[1], reverse=True)
        top_indices: list[int] = [idx for idx, _ in rrf_scores[:top_k]]

        # 📐 型: List[Tuple[Dict, float]] — [(チャンク辞書, RRFスコア), ...]
        results: list[tuple[dict, float]] = [
            (self._chunks[idx], rrf_scores_val)
            for idx, rrf_scores_val in rrf_scores[:top_k]
        ]

        # debug_infoは既存のsearchの出力と互換にする
        top1_idx: int = top_indices[0] if top_indices else 0
        query_l2: float = float(np.linalg.norm(query_embedding))
        top1_doc_l2: float = float(np.linalg.norm(self._embeddings[top1_idx]))
        raw_dot: float = float(np.dot(query_embedding, self._embeddings[top1_idx]))

        debug_info: dict = {
            "query_shape": query_embedding.shape,
            "docs_shape": self._embeddings.shape,
            "similarities_shape": vec_similarities.shape,
            "max_similarity": float(np.max(vec_similarities)),
            "all_similarities": vec_similarities.tolist(),
            "latency_cosine_ms": (t_cosine_end - t_cosine_start) * 1000,
            "latency_sort_ms": 0.0,
            "query_l2_norm": round(query_l2, 6),
            "top1_doc_l2_norm": round(top1_doc_l2, 6),
            "raw_dot_product": round(raw_dot, 6),
            "search_mode": "hybrid_rrf",
        }

        # PCA 2D投影（vector_search.pyと同一ロジック）
        # 💡 高次元ベクトル空間を2Dに射影して視覚化するためのデバッグ情報
        try:
            from sklearn.decomposition import PCA
            np_top_indices = np.array(top_indices)
            n_total: int = self._embeddings.shape[0]
            k_sampleSize: int = min(500, n_total)
            rng = np.random.default_rng(seed=42)
            sample_indices: np.ndarray = rng.choice(n_total, size=k_sampleSize, replace=False)
            all_indices: np.ndarray = np.unique(np.concatenate([sample_indices, np_top_indices]))
            sampled_docs: np.ndarray = self._embeddings[all_indices]
            combined: np.ndarray = np.vstack([query_embedding.reshape(1, -1), sampled_docs])
            pca = PCA(n_components=2)
            coords_2d: np.ndarray = pca.fit_transform(combined)
            top_k_positions: set = set()
            for tk_idx in np_top_indices:
                pos = np.where(all_indices == tk_idx)[0]
                if len(pos) > 0:
                    top_k_positions.add(int(pos[0]) + 1)
            debug_info["pca_plot_data"] = {
                "query": {"x": float(coords_2d[0, 0]), "y": float(coords_2d[0, 1])},
                "chunks_x": coords_2d[1:, 0].tolist(),
                "chunks_y": coords_2d[1:, 1].tolist(),
                "top_k_positions": list(top_k_positions),
                "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
            }
        except Exception as e:
            debug_info["pca_plot_data"] = None
            print(f"PCA投影に失敗: {e}")

        return {
            "results": results,
            "debug_info": debug_info,
        }

    # ================================================================
    # 検索メソッド
    # ================================================================

    def get_client(self) -> OpenAI:
        """OpenAIクライアントを返す（AITutorへの共有用）。"""
        return self._client

    def get_chunks(self) -> list[dict]:
        """チャンク一覧を返す。"""
        return self._chunks

    def get_embeddings(self) -> np.ndarray:
        """Embedding行列を返す。"""
        return self._embeddings

    def expand_query(self, question: str) -> str:
        """
        LLMを用いてユーザーの質問を検索に最適なクエリに拡張する。

        🧮 【Query Expansionの原理】
        ユーザーの自然言語クエリは曖昧であることが多い。
        例: 「勾配消失問題について教えて」→ 教科書には「Vanishing Gradient Problem」と英語で書かれている可能性。
        LLMに専門用語の翻訳・補完を依頼し、検索クエリの「語彙のギャップ」を埋める。

        💡 【直感的意味とDL概念との紐付け】
        これはInformation Retrievalにおける「Query Expansion」技術であり、
        近年のRAGでは「HyDE（Hypothetical Document Embedding）」など、
        LLMを使って仮想的な回答文書を生成し、そのEmbeddingで検索する手法も存在する。
        本実装はそのシンプル版で、キーワード補完に特化している。

        Args:
            question: ユーザーの元の質問文

        Returns:
            拡張されたクエリ文字列
        """
        expansion_prompt: str = (
            "あなたは検索クエリの最適化AIです。"
            "ユーザーの入力した質問に含まれる機械学習や数学の専門用語を、"
            "対応する英語の専門用語（例：誤差逆伝播 → Backpropagation）に翻訳し、"
            "元の質問文と英語のキーワードを併記した"
            "『検索に最適な文字列』を生成してください。"
            "余計な説明は一切加えず、拡張されたクエリ文字列のみを出力してください。"
        )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": expansion_prompt},
                    {"role": "user", "content": question},
                ],
                temperature=TEMPERATURE_QUERY_EXPANSION,
                max_tokens=MAX_TOKENS_QUERY_EXPANSION,
            )
            expanded: str = response.choices[0].message.content or question
            return expanded.strip()
        except Exception as e:
            # 拡張に失敗した場合は元の質問をそのまま使用
            print(f"クエリ拡張に失敗（元の質問を使用）: {e}")
            return question

    def search_chunks(self, query: str, top_k: int = 5) -> dict:
        """
        クエリ文字列でベクトル検索を実行する。

        💡 【処理フロー】
        query → expand_query（LLMでキーワード補完）→ Embedding生成 → ハイブリッド検索

        Args:
            query: 検索クエリ
            top_k: 取得するチャンク数

        Returns:
            search結果辞書（results, debug_info）
        """
        expanded_query: str = self.expand_query(query)
        # 📐 Shape: (embedding_dim,) — 拡張クエリの埋め込みベクトル
        query_embedding: np.ndarray = generate_embeddings([expanded_query])[0]
        search_result: dict = self._hybrid_search(
            query_embedding, expanded_query, top_k=top_k
        )
        search_result["expanded_query"] = expanded_query
        return search_result

    def query(
        self,
        question: str,
        top_k: int = 5,
        style: str = "初心者向け (Beginner)",
        length: str = "普通 (Normal)",
    ) -> dict:
        """
        質問に対してRAGで回答を生成する。

        🧮 【RAGパイプライン全体像】
        1. Query Expansion: LLMでクエリを拡張（語彙ギャップの解消）
        2. Embedding: クエリをベクトル化
        3. Hybrid Search: Vector + BM25 + RRFで関連チャンクを検索
        4. Context Injection: 検索結果をLLMのプロンプトに注入（In-Context Learning）
        5. LLM Generation: 根拠に基づく回答を生成

        💡 【In-Context Learningとの関係】
        LLMのプロンプトに検索結果を「コンテキスト」として注入する行為は、
        In-Context Learning（文脈内学習）の一形態である。
        LLMは追加学習（Fine-tuning）なしに、プロンプト内の情報を「一時的な知識」として活用できる。
        これにより、LLMの固定された知識ベースを実質的に拡張する。

        Args:
            question: ユーザーの質問文
            top_k: 検索する関連チャンク数
            style: 回答のターゲット層（"初心者向け" or "専門家向け"）
            length: 回答の長さ（"簡潔" or "普通" or "長め・詳細"）

        Returns:
            回答情報を含む辞書。
            {"answer": str, "sources": list[dict], "debug_info": dict} の形式。
        """
        # クエリ拡張：LLMで専門用語の英訳キーワードを補完
        expanded_query: str = self.expand_query(question)

        # 💡 元の質問と拡張クエリの両方をEmbedding化
        #    Semantic Shift Score の計算に元の質問のEmbeddingも必要
        t_embed_start: float = time.time()
        # 📐 Shape: (2, embedding_dim) — 2つのテキストを一括でEmbedding化
        embeddings_pair: np.ndarray = generate_embeddings([question, expanded_query])
        # 📐 Shape: (embedding_dim,)
        original_embedding: np.ndarray = embeddings_pair[0]
        query_embedding: np.ndarray = embeddings_pair[1]
        t_embed_end: float = time.time()

        # 🧮 Semantic Shift Score：元クエリ↔拡張クエリのコサイン類似度
        # 💡 Query Expansionによって意味がどれだけ「ズレた」かを定量化する指標。
        #    1.0に近ければ意味が保存されている、0.5未満なら拡張が暴走した可能性がある。
        dot_val: float = float(np.dot(original_embedding, query_embedding))
        norm_orig: float = float(np.linalg.norm(original_embedding))
        norm_exp: float = float(np.linalg.norm(query_embedding))
        semantic_shift_score: float = dot_val / (norm_orig * norm_exp + 1e-10)

        # 🧮 Top-K Dimensions：質問ベクトルの絶対値上位5次元を抽出
        # 💡 Embeddingの各次元が「意味の特定の側面」を捉えていると解釈できる。
        #    絶対値が大きい次元は、その質問の意味を最も強く特徴づける次元。
        #    DLではFeature Importance / Saliencyに相当する概念。
        # 📐 Shape: (embedding_dim,)
        abs_vals: np.ndarray = np.abs(query_embedding)
        # 📐 Shape: (5,) — 上位5次元のインデックス
        top5_indices: np.ndarray = np.argsort(abs_vals)[::-1][:5]
        top_k_dimensions: list[dict] = [
            {"dim_index": int(idx), "value": round(float(query_embedding[idx]), 6)}
            for idx in top5_indices
        ]

        # ハイブリッド検索（ベクトル + BM25 + RRF）
        search_result: dict = self._hybrid_search(
            query_embedding, expanded_query, top_k=top_k
        )
        results: list[tuple[dict, float]] = search_result["results"]
        debug_info: dict = search_result["debug_info"]
        debug_info["expanded_query"] = expanded_query
        debug_info["latency_embedding_ms"] = (t_embed_end - t_embed_start) * 1000
        debug_info["semantic_shift_score"] = round(semantic_shift_score, 4)
        debug_info["top_k_dimensions"] = top_k_dimensions

        # 💡 検索結果のチャンクテキストを結合して「コンテキスト文字列」を構築
        #    これがLLMのプロンプトに注入される「外部知識」
        context_parts: list[str] = []
        sources: list[dict] = []
        for chunk, score in results:
            source_file: str = chunk.get("source_file", "不明")
            context_parts.append(
                f"[{source_file} - Page {chunk['page_number']}] {chunk['text']}"
            )
            sources.append({
                "source_file": source_file,
                "page_number": chunk["page_number"],
                "chunk_index": chunk["chunk_index"],
                "similarity": round(score, 4),
                "text_preview": chunk["text"][:100] + "...",
            })

        context: str = "\n\n---\n\n".join(context_parts)

        # ================================================================
        # LLMへのプロンプト構築（In-Context Learning）
        # ================================================================
        # 💡 System Promptは「AIの人格と制約」を定義するメタ命令。
        #    User Promptは「実際のタスク（質問＋コンテキスト）」を含む。
        #    この構造はLLMのInstruction Tuning（SFT）で学習された形式に対応する。
        if "Expert" in style:
            style_instruction: str = (
                "大学レベルの数学（線形代数・微積分）や計算機科学の専門用語を"
                "躊躇なく使用し、学術的かつ厳密に説明してください。"
            )
        else:
            style_instruction = (
                "専門用語を極力避け、中高生でもわかるように"
                "具体的な比喩を用いて説明してください。"
            )

        if "Concise" in length:
            length_instruction: str = "要点のみを3文以内で端的に答えてください。"
        elif "Detailed" in length:
            length_instruction = (
                "背景知識から段階を追って、非常に詳細かつ網羅的に解説してください。"
            )
        else:
            length_instruction = "標準的な段落数で、過不足なく答えてください。"

        # 💡 【グラウンディング制約】
        #    LLMがコンテキスト外の知識（事前学習で学んだ情報）を使って
        #    ハルシネーション（もっともらしい虚偽）を生成するのを防ぐための厳格な制約。
        system_prompt: str = (
            "# 制約（最優先）\n"
            "あなたは提供された【コンテキスト】に含まれる情報『のみ』を用いて回答を構成しなければなりません。\n"
            "コンテキストの情報が断片的であったり、質問に対する完全な答えでなかったとしても、\n"
            "コンテキストから読み取れる範囲の事実を組み合わせて最善の回答を作成してください。\n"
            "その際、絶対にあなたの事前知識（外部知識）を補完してはいけません。\n"
            "もしコンテキストが質問と『完全に無関係』である場合のみ、\n"
            "「提供された文献には十分な情報がありません」と回答してください。\n"
            "\n"
            
            "# スタイルの適用\n"
            "回答は日本語で行い、参照したソースファイル名とページ番号も明記してください。\n"
            f"\n【回答スタイル】{style_instruction}\n"
            f"【回答の長さ】{length_instruction}\n"
            "\n"
            "# 数式出力フォーマット（厳守）\n"
            "数式を出力する際は、必ず以下のStreamlit互換Markdownフォーマットを使用してください。\n"
            "- インライン数式: 単一の $ で囲む（例: $x = 1$）\n"
            "- ディスプレイ数式: 二重の $$ で囲む（例: $$y = ax + b$$）\n"
            "- \\[ \\] や \\( \\) といった括弧を用いたLaTeXデリミタは絶対に使用しないでください。"
        )

        # 💡 User Promptにコンテキスト（検索結果）と質問を注入
        #    これがIn-Context Learningの核心：プロンプト内に「教科書の該当ページ」を埋め込む
        user_prompt: str = (
            f"## コンテキスト（書籍からの抜粋）\n\n{context}\n\n"
            f"## 質問\n\n{question}"
        )

        # ================================================================
        # LLM呼び出しとLogprobs解析
        # ================================================================
        # 💡 Logprobs（対数確率）: LLMが各トークンを出力する際の「自信度」
        #    確率が低いトークン = LLMが「自信がない」部分 = ハルシネーションの疑いがある箇所
        token_usage: dict = {}
        low_prob_tokens: list[dict] = []
        t_llm_start: float = time.time()
        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=TEMPERATURE_RAG_ANSWER,
                max_tokens=MAX_TOKENS_RAG_ANSWER,
                # 💡 logprobs=True: 各出力トークンの対数確率を返す
                #    top_logprobs=1: 各位置で最も確率の高いトークンの情報を1つ返す
                logprobs=True,
                top_logprobs=1,
            )
            answer: str = response.choices[0].message.content or "（回答を生成できませんでした）"
            # トークン消費量を取得
            if response.usage:
                token_usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            # 🧮 Logprobs解析：exp(logprob) < 0.90 のトークンを「低確信度」として抽出
            # 💡 logprob → probability の変換: prob = e^(logprob)
            #    例: logprob = -0.105 → prob = 0.90 (90%)
            #    確率90%未満のトークンはLLMが「迷っている」証拠であり、
            #    ハルシネーション検出の手がかりになる
            k_lowProbThreshold: float = 0.90
            logprobs_content = response.choices[0].logprobs
            if logprobs_content and logprobs_content.content:
                for token_info in logprobs_content.content:
                    # 🧮 対数確率 → 確率への変換: prob = exp(logprob)
                    prob: float = math.exp(token_info.logprob)
                    if prob < k_lowProbThreshold:
                        low_prob_tokens.append({
                            "token": token_info.token,
                            "probability": round(prob * 100, 1),
                        })
        except Exception as e:
            answer = f"LLM応答の生成に失敗しました: {e}"
        t_llm_end: float = time.time()

        # 💡 マイクロコスト計算（OpenAI API利用料の推定）
        #    各モデルの料金体系に基づき、1回のクエリあたりのコストを計算
        k_embeddingCostPer1k: float = 0.00002
        k_promptCostPer1k: float = 0.00015
        k_completionCostPer1k: float = 0.0006

        prompt_tokens: int = token_usage.get("prompt_tokens", 0)
        completion_tokens: int = token_usage.get("completion_tokens", 0)
        embedding_tokens_est: int = max(len(expanded_query) // 4, 1)

        cost_embedding: float = embedding_tokens_est / 1000 * k_embeddingCostPer1k
        cost_prompt: float = prompt_tokens / 1000 * k_promptCostPer1k
        cost_completion: float = completion_tokens / 1000 * k_completionCostPer1k
        cost_total: float = cost_embedding + cost_prompt + cost_completion

        # debug_infoにLLM通信ペイロードを追加
        llm_latency_sec: float = (t_llm_end - t_llm_start)
        total_tokens_count: int = token_usage.get("total_tokens", 0)
        # 💡 Token Velocity: 1秒あたりの生成トークン数。LLMの推論速度の指標。
        token_velocity: float = total_tokens_count / llm_latency_sec if llm_latency_sec > 0 else 0.0

        debug_info["system_prompt"] = system_prompt
        debug_info["raw_context"] = context
        debug_info["user_prompt"] = user_prompt
        debug_info["token_usage"] = token_usage
        debug_info["llm_model"] = LLM_MODEL
        debug_info["latency_llm_ms"] = llm_latency_sec * 1000
        debug_info["low_prob_tokens"] = low_prob_tokens
        debug_info["token_velocity"] = round(token_velocity, 1)
        debug_info["cost"] = {
            "embedding_usd": cost_embedding,
            "prompt_usd": cost_prompt,
            "completion_usd": cost_completion,
            "total_usd": cost_total,
        }

        return {
            "answer": answer,
            "sources": sources,
            "debug_info": debug_info,
        }

    def get_sample_chunks_for_analysis(self, max_chars: int = 15000) -> str:
        """
        出題傾向分析等のため、インデックス全体のチャンクからテキストをランダム抽出・結合する。

        LLMのトークン上限（Context Window）を考慮し、指定した文字数(max_chars)を
        超えない範囲でチャンクを選択する。15000文字はおよそ1.5万〜2万トークン弱に相当し、
        GPT-4o等の上限内に安全に収まる。

        Args:
            max_chars: 抽出するテキストの最大推定文字数

        Returns:
            結合されたテキスト文字列（マークダウン区切り）
        """
        import random

        if not self._chunks:
            return ""

        # ランダムサンプリング用にチャンクのインデックスリストをシャッフル
        indices = list(range(len(self._chunks)))
        random.shuffle(indices)

        sampled_parts = []
        current_chars = 0

        for idx in indices:
            chunk = self._chunks[idx]
            text = chunk.get("text", "")
            source = chunk.get("source_file", "不明")
            page = chunk.get("page_number", "?")

            chunk_len = len(text)
            if current_chars + chunk_len > max_chars:
                break

            part_str = f"[{source} - Page {page}]\n{text}"
            sampled_parts.append(part_str)
            current_chars += chunk_len

        # 元の順序に近いほうが文脈がわかりやすいためソート
        # ※実際には元のインデックスでソートするほうがより自然（ドキュメント順）
        # ですが、ここでは抽出された順序のままで構いません。
        return "\n\n---\n\n".join(sampled_parts)
