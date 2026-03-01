"""
ドキュメント検索コアモジュール。

PDF読み込み → チャンク分割 → Embedding生成 → ベクトル検索 → LLM回答生成
の一連のRAG検索処理を担当する。教育コンテンツ生成ロジックは含まない。
"""

import numpy as np
import time
import math
from openai import OpenAI

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
    """

    def __init__(self, target_subject: str) -> None:
        """
        RAGコアを初期化する。

        指定された科目のPDFを data/{target_subject}/ から読み込み、
        キャッシュを vector_stores/{target_subject}/ に保存する。

        Args:
            target_subject: 科目名（data/配下のサブフォルダ名）
        """
        from pathlib import Path

        self._client: OpenAI = _get_client()
        self._chunks: list[dict] = []
        self._embeddings: np.ndarray = np.array([])
        self._subject: str = target_subject
        self._skipped_files: list[str] = []
        self.docs: list[dict] = []

        # 科目ごとのパスを設定
        data_dir: Path = Path("data") / target_subject
        cache_dir: Path = Path("vector_stores") / target_subject

        # 対象PDFを自動検出
        if not data_dir.exists():
            raise FileNotFoundError(f"科目ディレクトリが見つかりません: {data_dir}")
        pdf_paths: list[str] = sorted(
            str(p) for p in data_dir.glob("*.pdf")
        )
        if not pdf_paths:
            raise FileNotFoundError(f"PDFファイルが見つかりません: {data_dir}")

        # PDF組み合わせに基づくキャッシュキーを生成
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
        print("2/3: チャンク分割中...")
        self._chunks = chunk_text(all_pages)
        print(f"  分割完了: {len(self._chunks)} チャンク")

        # 3. Embedding生成
        print("3/3: Embedding生成中...")
        texts: list[str] = [c["text"] for c in self._chunks]
        self._embeddings = generate_embeddings(texts)
        print(f"  生成完了: 形状 {self._embeddings.shape}")

        # キャッシュに保存（科目別ディレクトリ）
        save_cache(self._embeddings, self._chunks, cache_key, cache_dir)
        print(f"[{target_subject}] インデックス構築完了!")

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

        専門用語の英訳キーワードを補完し、ベクトル検索の精度を向上させる。

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

        Args:
            query: 検索クエリ
            top_k: 取得するチャンク数

        Returns:
            search結果辞書（results, debug_info）
        """
        expanded_query: str = self.expand_query(query)
        query_embedding: np.ndarray = generate_embeddings([expanded_query])[0]
        search_result: dict = search(
            query_embedding, self._embeddings, self._chunks, top_k=top_k
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

        # 元の質問と拡張クエリの両方をEmbedding化（レイテンシ計測）
        t_embed_start: float = time.time()
        embeddings_pair: np.ndarray = generate_embeddings([question, expanded_query])
        original_embedding: np.ndarray = embeddings_pair[0]
        query_embedding: np.ndarray = embeddings_pair[1]
        t_embed_end: float = time.time()

        # Semantic Shift Score：元クエリ↔拡張クエリのコサイン類似度
        dot_val: float = float(np.dot(original_embedding, query_embedding))
        norm_orig: float = float(np.linalg.norm(original_embedding))
        norm_exp: float = float(np.linalg.norm(query_embedding))
        semantic_shift_score: float = dot_val / (norm_orig * norm_exp + 1e-10)

        # Top-K Dimensions：質問ベクトルの絶対値上位5次元を抽出
        abs_vals: np.ndarray = np.abs(query_embedding)
        top5_indices: np.ndarray = np.argsort(abs_vals)[::-1][:5]
        top_k_dimensions: list[dict] = [
            {"dim_index": int(idx), "value": round(float(query_embedding[idx]), 6)}
            for idx in top5_indices
        ]

        # ベクトル検索（NumPyベースのCosine Similarity）
        search_result: dict = search(
            query_embedding, self._embeddings, self._chunks, top_k=top_k
        )
        results: list[tuple[dict, float]] = search_result["results"]
        debug_info: dict = search_result["debug_info"]
        debug_info["expanded_query"] = expanded_query
        debug_info["latency_embedding_ms"] = (t_embed_end - t_embed_start) * 1000
        debug_info["semantic_shift_score"] = round(semantic_shift_score, 4)
        debug_info["top_k_dimensions"] = top_k_dimensions

        # コンテキスト文字列を構築
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

        # LLMへのプロンプト構築（style/lengthに応じて動的に生成）
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

        user_prompt: str = (
            f"## コンテキスト（書籍からの抜粋）\n\n{context}\n\n"
            f"## 質問\n\n{question}"
        )

        # LLM呼び出し（レイテンシ計測）
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
            # Logprobs解析：確率 90% 未満のトークンを抽出
            k_lowProbThreshold: float = 0.90
            logprobs_content = response.choices[0].logprobs
            if logprobs_content and logprobs_content.content:
                for token_info in logprobs_content.content:
                    prob: float = math.exp(token_info.logprob)
                    if prob < k_lowProbThreshold:
                        low_prob_tokens.append({
                            "token": token_info.token,
                            "probability": round(prob * 100, 1),
                        })
        except Exception as e:
            answer = f"LLM応答の生成に失敗しました: {e}"
        t_llm_end: float = time.time()

        # マイクロコスト計算（USD）
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
