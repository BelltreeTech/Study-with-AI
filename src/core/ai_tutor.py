"""
AI教育チューターモジュール。

LLMを用いた教育コンテンツ生成ロジックを担当する。
試験問題生成、採点、ソクラテス式対話、カリキュラム生成、講義ノート生成を行う。
ドキュメント検索ロジックはRAGCoreに委譲する。
"""

import re
import json
import numpy as np
from openai import OpenAI

from src.embedder import generate_embeddings
from src.vector_search import search
from src.config import (
    LLM_MODEL,
    TEMPERATURE_QUIZ,
    MAX_TOKENS_QUIZ,
    TEMPERATURE_GRADING,
    MAX_TOKENS_GRADING,
    TEMPERATURE_SOCRATIC,
    MAX_TOKENS_SOCRATIC,
    SOCRATIC_HISTORY_LIMIT,
    SOCRATIC_CONTEXT_LIMIT,
    TEMPERATURE_CURRICULUM,
    MAX_TOKENS_CURRICULUM,
    TEMPERATURE_LECTURE,
    MAX_TOKENS_LECTURE,
    QUIZ_TOP_K,
    LECTURE_TOP_K,
)


class AITutor:
    """
    AI教育チューター。

    LLMを利用した教育コンテンツの生成を担当する。
    検索機能が必要な場合はRAGCoreから取得したチャンク・Embeddingを使用する。
    """

    def __init__(self, client: OpenAI) -> None:
        """
        AITutorを初期化する。

        Args:
            client: OpenAI APIクライアント
        """
        self._client: OpenAI = client

    def set_search_index(
        self,
        chunks: list[dict],
        embeddings: np.ndarray,
        expand_query_fn=None,
    ) -> None:
        """
        RAGCoreからの検索インデックスを設定する。

        generate_quizやgenerate_lectureでベクトル検索が必要な場合に使用する。

        Args:
            chunks: チャンク辞書のリスト
            embeddings: Embedding行列
            expand_query_fn: クエリ拡張関数（RAGCore.expand_query）
        """
        self._chunks: list[dict] = chunks
        self._embeddings: np.ndarray = embeddings
        self._expand_query = expand_query_fn

    def _do_expand_query(self, query: str) -> str:
        """クエリ拡張（RAGCoreの関数が設定されていればそちらを使用）。"""
        if self._expand_query is not None:
            return self._expand_query(query)
        return query

    # ================================================================
    # 試験問題生成 (Feynman Drill / カリキュラム修了試験)
    # ================================================================

    def generate_quiz(
        self,
        topic_text: str,
        difficulty: str = "Normal",
        lecture_content: str = "",
    ) -> dict:
        """
        トピックに関する試験問題を生成する。

        lecture_contentが指定された場合は、講義内容のみに基づいて出題する。
        指定されない場合は、RAG検索結果に基づいて出題する。

        Args:
            topic_text: 学習したいトピック（例: 勾配消失問題）
            difficulty: 難易度（"Easy" / "Normal" / "Hard"）
            lecture_content: 講義ノート本文（カリキュラム修了試験用）

        Returns:
            {"question_text": str, "reference_chunks": list[dict]}
        """
        # 講義ベースの出題か RAG検索ベースの出題かを判定
        reference_chunks: list[dict] = []
        context: str = ""

        if lecture_content:
            # 講義ベース: RAG検索は裏付けデータとしてのみ使用
            expanded_topic: str = self._do_expand_query(topic_text)
            topic_embedding: np.ndarray = generate_embeddings([expanded_topic])[0]
            search_result: dict = search(
                topic_embedding, self._embeddings, self._chunks, top_k=QUIZ_TOP_K
            )
            results: list[tuple[dict, float]] = search_result["results"]
            context_parts: list[str] = []
            for chunk, score in results:
                source_file: str = chunk.get("source_file", "不明")
                context_parts.append(
                    f"[{source_file} - Page {chunk['page_number']}] {chunk['text']}"
                )
                reference_chunks.append({
                    "text": chunk["text"],
                    "source_file": source_file,
                    "page_number": chunk["page_number"],
                    "similarity": round(score, 4),
                })
            context = "\n\n---\n\n".join(context_parts)
        else:
            # RAG検索ベース: 従来通り
            expanded_topic = self._do_expand_query(topic_text)
            topic_embedding = generate_embeddings([expanded_topic])[0]
            search_result = search(
                topic_embedding, self._embeddings, self._chunks, top_k=QUIZ_TOP_K
            )
            results = search_result["results"]
            context_parts = []
            for chunk, score in results:
                source_file = chunk.get("source_file", "不明")
                context_parts.append(
                    f"[{source_file} - Page {chunk['page_number']}] {chunk['text']}"
                )
                reference_chunks.append({
                    "text": chunk["text"],
                    "source_file": source_file,
                    "page_number": chunk["page_number"],
                    "similarity": round(score, 4),
                })
            context = "\n\n---\n\n".join(context_parts)

        # 難易度別プロンプト
        if difficulty == "Easy":
            quiz_system_prompt: str = (
                "あなたは大学の教授です。学部1〜2年生向けの基礎確認テストを作成してください。\n"
                "以下のコンテキスト（教科書からの抜粋）を元に、"
                "指定されたトピックに関する**基礎問題**（100点満点）を作成してください。\n\n"
                "【出力形式】\n"
                "## パートA: 用語・定義の確認（各5点 × 10問 = 50点）\n"
                "Q1〜Q10: 基本的な用語の定義や概念の正誤判定。\n"
                "4択（A/B/C/D）で紛らわしくない明確な選択肢を提示すること。\n\n"
                "## パートB: 短答記述（各10点 × 5問 = 50点）\n"
                "Q11〜Q15: 概念を簡潔に説明させる短答式。\n"
                "1〜3文程度で回答可能な問題にすること。\n\n"
                "【ルール】\n"
                "- 答えは一切出力しないこと。問題文のみを出力すること。\n"
                "- 基本的な理解を確認する問題にすること。応用・発展は不要。\n"
                "- 日本語で記述すること。\n"
            )
        elif difficulty == "Hard":
            quiz_system_prompt = (
                "あなたは大学院博士課程の教授です。博士候補生の資格審査レベルの試験を作成してください。\n"
                "以下のコンテキスト（教科書からの抜粋）を元に、"
                "指定されたトピックに関する**博士級総合試験**（100点満点）を作成してください。\n\n"
                "【出力形式】\n"
                "## パートA: 批判的分析（各20点 × 2問 = 40点）\n"
                "Q1〜Q2: 理論の限界・前提条件の批判的検討、代替手法との比較考察。\n"
                "最新の研究動向を踏まえた高度な分析を要求すること。\n\n"
                "## パートB: 統合論述（各30点 × 2問 = 60点）\n"
                "Q3〜Q4: 複数の概念を統合した高度な問題。\n"
                "- 数学的証明や導出を含む理論問題\n"
                "- 未知の応用シナリオに対する設計・提案問題\n"
                "- 既存手法の欠点を克服する独自のアプローチを問う問題\n\n"
                "【ルール】\n"
                "- 答えは一切出力しないこと。問題文のみを出力すること。\n"
                "- 教科書の範囲を超えた洞察・独創性を要求する問題にすること。\n"
                "- 日本語で記述すること。\n"
            )
        else:  # Normal（修士級）
            quiz_system_prompt = (
                "あなたは大学院レベルの厳格な試験問題を作成する教授です。\n"
                "以下のコンテキスト（教科書からの抜粋）を元に、"
                "指定されたトピックに関する**複合問題形式の修了試験**（100点満点）を作成してください。\n\n"
                "【出力形式（この構造を厳守すること）】\n"
                "## パートA: 選択問題（各4点 × 5問 = 20点）\n"
                "Q1〜Q5の各問題について、4択（A/B/C/D）の選択肢を提示すること。\n"
                "問題は概念の正確な理解を問うものにし、紛らわしい選択肢を含めること。\n\n"
                "## パートB: 記述論述（各16点 × 5問 = 80点）\n"
                "Q6〜Q10の各問題は、以下のいずれかの形式で出題すること:\n"
                "- 概念の本質を問う論述問題\n"
                "- 数式の導出・証明問題\n"
                "- 具体例を用いた説明・比較問題\n"
                "- 実応用シナリオの分析問題\n"
                "- 批判的検討・限界の考察問題\n\n"
                "【ルール】\n"
                "- 答えは一切出力しないこと。問題文のみを出力すること。\n"
                "- 大学院レベルの深い理解を要求すること。\n"
                "- 日本語で記述すること。\n"
            )

        # 講義ベースの場合はプロンプトに「講義のみに基づく」制約を追加
        lecture_constraint: str = ""
        if lecture_content:
            lecture_constraint = (
                "\n\n【重要ルール（厳守）】\n"
                "1. 【講義ノート】に明記されていない用語や概念は、絶対に出題しないでください。\n"
                "2. 【参考文献】は、正解の正確性を担保するためだけに使用し、"
                "出題範囲の拡張には使用しないでください。\n"
                "3. 学生が講義を精読すれば、論理的に満点が取れる問題設計にしてください。\n"
            )

        final_system_prompt: str = quiz_system_prompt + lecture_constraint

        # ユーザープロンプトを構築
        if lecture_content:
            quiz_user_prompt: str = (
                f"【講義ノート (試験範囲)】\n\n{lecture_content[:4000]}\n\n"
                f"【参考文献 (裏付けデータ)】\n\n{context}\n\n"
                f"## 出題対象のトピック\n\n{topic_text}"
            )
        else:
            quiz_user_prompt = (
                f"## コンテキスト（教科書からの抜粋）\n\n{context}\n\n"
                f"## 出題対象のトピック\n\n{topic_text}"
            )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": final_system_prompt},
                    {"role": "user", "content": quiz_user_prompt},
                ],
                temperature=TEMPERATURE_QUIZ,
                max_tokens=MAX_TOKENS_QUIZ,
            )
            question_text: str = response.choices[0].message.content or "（問題を生成できませんでした）"
        except Exception as e:
            question_text = f"問題の生成に失敗しました: {e}"

        return {
            "question_text": question_text,
            "reference_chunks": reference_chunks,
        }

    # ================================================================
    # 採点 (Grading)
    # ================================================================

    def grade_answer(
        self,
        question: str,
        user_answer: str,
        reference_context: str,
        difficulty: str = "Normal",
    ) -> dict:
        """
        ユーザーの回答をLLMが採点する。

        Args:
            question: 出題された問題文
            user_answer: ユーザーの回答テキスト
            reference_context: 正解の根拠となるコンテキスト
            difficulty: 難易度（"Easy" / "Normal" / "Hard"）

        Returns:
            {"score": int, "feedback_text": str}
        """
        # 難易度別採点プロンプト
        if difficulty == "Easy":
            grading_system_prompt: str = (
                "あなたは優しい大学教授です。学部生の基礎テストを採点してください。\n"
                "学生の回答を、以下の「正解の根拠」と比較し、採点してください。\n\n"
                "【試験構成】100点満点\n"
                "- パートA（用語確認）: 各5点 × 10問 = 50点\n"
                "- パートB（短答記述）: 各10点 × 5問 = 50点\n\n"
                "【採点基準（合格ライン70点 / やや甘め）】\n"
                "- パートA: 正答は満点。惜しい誤答に部分点(2点)可。\n"
                "- パートB: 要点が含まれていれば高得点。完璧でなくても概念を理解していれば7割以上。\n\n"
                "【出力形式】\n"
                "## スコア: XX点\n\n"
                "## 採点詳細\n"
                "各問の得点。\n\n"
                "## 講評\n"
                "良い点を褒め、改善点を優しく指摘。\n\n"
                "## 模範解答のポイント\n"
                "要点を箇条書きで。\n"
                "- 日本語で出力すること。\n"
            )
        elif difficulty == "Hard":
            grading_system_prompt = (
                "あなたは博士課程の資格審査委員です。極めて厳格に採点してください。\n"
                "学生の回答を、以下の「正解の根拠」と比較し、独創性と論理性を最重視して採点してください。\n\n"
                "【試験構成】100点満点\n"
                "- パートA（批判的分析）: 各20点 × 2問 = 40点\n"
                "- パートB（統合論述）: 各30点 × 2問 = 60点\n\n"
                "【採点基準（合格ライン95点 / 極めて厳格）】\n"
                "- パートA: 各20点を以下で採点:\n"
                "  - 批判的洞察（10点）: 独自の視点・深い考察がなければ0点\n"
                "  - 論理的整合性（5点）: 矛盾があれば即0点\n"
                "  - 学術的根拠（5点）: 具体的な研究への言及がなければ減点\n"
                "- パートB: 各30点を以下で採点:\n"
                "  - 独創性（10点）: 教科書のコピーは0点。独自の洞察を要求\n"
                "  - 数学的厳密性（10点）: 証明の飛躍は即0点\n"
                "  - 実用性・応用力（10点）: 抽象論のみは減点\n\n"
                "【出力形式】\n"
                "## スコア: XX点\n\n"
                "## パートA 採点結果\n"
                "各問の詳細採点。\n\n"
                "## パートB 採点結果\n"
                "各問の3軸採点と得点内訳。\n\n"
                "## 総合講評\n"
                "博士候補生として不足している点を容赦なく指摘。\n\n"
                "## 模範解答のポイント\n"
                "要点を箇条書きで。\n"
                "- 日本語で出力すること。\n"
            )
        else:  # Normal（修士級）
            grading_system_prompt = (
                "あなたは大学院レベルの厳格な教授です。鬼採点モードで採点してください。\n"
                "学生の回答を、以下の「正解の根拠」と比較し、極めて厳密に採点してください。\n\n"
                "【試験構成】100点満点\n"
                "- パートA（選択問題）: 各4点 × 5問 = 20点\n"
                "- パートB（記述論述）: 各16点 × 5問 = 80点\n\n"
                "【採点基準（合格ライン90点）】\n"
                "- パートA: 正答のみ満点。誤答は0点。部分点なし。\n"
                "- パートB: 各問16点を以下の4軸で採点:\n"
                "  - 正確性（4点）: 事実の誤りがあれば即0点\n"
                "  - 網羅性（4点）: 重要概念の欠落があれば減点\n"
                "  - 論理性（4点）: 論理展開の飛躍・矛盾があれば減点\n"
                "  - 深度（4点）: 表面的な記述は0点\n\n"
                "【出力形式】\n"
                "## スコア: XX点\n\n"
                "## パートA 採点結果\n"
                "各問の正誤と得点を表で。\n\n"
                "## パートB 採点結果\n"
                "各問の4軸採点と得点内訳。\n\n"
                "## 総合講評\n"
                "容赦なく指摘。\n\n"
                "## 模範解答のポイント\n"
                "要点を箇条書きで。\n"
                "- 日本語で出力すること。\n"
            )
        grading_user_prompt: str = (
            f"## 出題された問題\n\n{question}\n\n"
            f"## 正解の根拠（コンテキスト）\n\n{reference_context}\n\n"
            f"## 学生の回答\n\n{user_answer}"
        )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": grading_system_prompt},
                    {"role": "user", "content": grading_user_prompt},
                ],
                temperature=TEMPERATURE_GRADING,
                max_tokens=MAX_TOKENS_GRADING,
            )
            feedback_text: str = response.choices[0].message.content or "（採点結果を生成できませんでした）"
        except Exception as e:
            feedback_text = f"採点に失敗しました: {e}"

        # スコアをテキストから抽出
        score: int = 0
        score_match = re.search(r"(\d{1,3})\s*点", feedback_text)
        if score_match:
            score = min(int(score_match.group(1)), 100)

        return {
            "score": score,
            "feedback_text": feedback_text,
        }

    # ================================================================
    # ソクラテス・バトル (Socratic Debate)
    # ================================================================

    def run_socratic_dialogue(
        self,
        lecture_content: str,
        chat_history: list[dict],
        user_input: str,
    ) -> str:
        """
        講義内容に基づくソクラテス式対話を行う。

        ユーザーの質問・反論に対し、直接答えるのではなく
        問い返しと誘導で深い思考へ導く。

        Args:
            lecture_content: 現在の講義ノート本文
            chat_history: これまでの議論履歴
            user_input: ユーザーの質問/反論

        Returns:
            教授の応答テキスト
        """
        system_prompt: str = (
            "あなたはソクラテス・メソッドを実践する厳格な大学院教授です。\n\n"
            "【行動原則】\n"
            "- ユーザーの質問に対し、単に答えるのではなく、"
            "**『なぜそう思うのか？』『その定義の根拠は？』**と問い返し、"
            "深い思考へ誘導してください。\n"
            "- 安易に正解を教えず、ユーザー自身に気づきを与えてください。\n"
            "- ユーザーの誤解や不正確な理解を発見したら、"
            "反例や矛盾を提示して自ら修正させてください。\n"
            "- ユーザーが正しい方向に進んでいる場合は認めつつ、"
            "さらに深い問いを投げかけてください。\n"
            "- 議論は常に以下の講義内容に基づいて行ってください。\n\n"
            "【応答スタイル】\n"
            "- 簡潔に（3〜5文程度）。冗長な説明は避ける。\n"
            "- 必ず1つ以上の問いかけを含める。\n"
            "- 数式が必要なら LaTeX ($...$, $$...$$) を使用。\n"
            "- 日本語で応答すること。\n\n"
            f"【講義内容（議論の根拠）】\n\n{lecture_content[:SOCRATIC_CONTEXT_LIMIT]}"
        )

        # メッセージ構築
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        # 直近の議論履歴を追加（トークン制限のため最大件数を制限）
        for msg in chat_history[-SOCRATIC_HISTORY_LIMIT:]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })
        messages.append({"role": "user", "content": user_input})

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=TEMPERATURE_SOCRATIC,
                max_tokens=MAX_TOKENS_SOCRATIC,
            )
            reply: str = response.choices[0].message.content or "（応答を生成できませんでした）"
        except Exception as e:
            reply = f"教授との対話に失敗しました: {e}"

        return reply

    # ================================================================
    # カリキュラム学習モード (Curriculum)
    # ================================================================

    def generate_curriculum(self, topic: str) -> list[dict]:
        """
        トピックに基づく体系的なカリキュラム（全5〜6章）を生成する。

        Args:
            topic: 学習したいテーマ（例: "Deep Learning"）

        Returns:
            [{"chapter": int, "title": str, "description": str, "status": str}, ...]
        """
        curriculum_prompt: str = (
            "あなたは大学院の教務主任です。以下のトピックについて、"
            "体系的な学習カリキュラム（全5〜6章）をJSON形式で生成してください。\n\n"
            "【出力形式（JSON配列のみ）】\n"
            "[\n"
            '  {"chapter": 1, "title": "章タイトル", "description": "1〜2文の概要", "status": "unlocked"},\n'
            '  {"chapter": 2, "title": "...", "description": "...", "status": "locked"},\n'
            "  ...\n"
            "]\n\n"
            "【ルール】\n"
            "- 第1章のstatusは必ず \"unlocked\"。それ以降は \"locked\"。\n"
            "- 前提知識から応用まで段階的に構成すること。\n"
            "- JSON配列以外のテキストは一切出力しないこと。\n"
        )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": curriculum_prompt},
                    {"role": "user", "content": f"トピック: {topic}"},
                ],
                temperature=TEMPERATURE_CURRICULUM,
                max_tokens=MAX_TOKENS_CURRICULUM,
            )
            raw_text: str = response.choices[0].message.content or "[]"
            # JSON部分を抽出（LLMが余計なテキストを付けた場合への防御）
            start_idx: int = raw_text.find("[")
            end_idx: int = raw_text.rfind("]") + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str: str = raw_text[start_idx:end_idx]
                curriculum: list[dict] = json.loads(json_str)
            else:
                curriculum = []
        except Exception as e:
            print(f"カリキュラム生成に失敗: {e}")
            curriculum = []

        # statusの正規化
        for i, ch in enumerate(curriculum):
            if i == 0:
                ch["status"] = "unlocked"
            elif ch.get("status") not in ("completed", "unlocked"):
                ch["status"] = "locked"

        return curriculum

    # ================================================================
    # 講義ノート生成 (Lecture)
    # ================================================================

    def generate_lecture(
        self,
        chapter_title: str,
        chapter_description: str,
    ) -> dict:
        """
        指定された章の講義ノートを、RAG検索結果を元に生成する。

        Args:
            chapter_title: 章のタイトル
            chapter_description: 章の概要

        Returns:
            {"lecture_text": str, "source_chunks": list[dict]}
        """
        # 章タイトルでベクトル検索（Top-K: 十分な情報量を確保）
        search_query: str = f"{chapter_title} {chapter_description}"
        expanded_query: str = self._do_expand_query(search_query)
        query_embedding: np.ndarray = generate_embeddings([expanded_query])[0]
        search_result: dict = search(
            query_embedding, self._embeddings, self._chunks, top_k=LECTURE_TOP_K
        )
        results: list[tuple[dict, float]] = search_result["results"]

        # コンテキスト構築
        source_chunks: list[dict] = []
        context_parts: list[str] = []
        for chunk, score in results:
            source_file: str = chunk.get("source_file", "不明")
            context_parts.append(
                f"[{source_file} - Page {chunk['page_number']}] {chunk['text']}"
            )
            source_chunks.append({
                "text": chunk["text"],
                "source_file": source_file,
                "page_number": chunk["page_number"],
                "similarity": round(score, 4),
            })
        context: str = "\n\n---\n\n".join(context_parts)

        # LLMで講義ノート生成（大学教授レベルの詳細さ）
        lecture_system_prompt: str = (
            "あなたは大学院の厳格な教授です。学部生向けの手加減は一切不要です。\n"
            "以下のコンテキスト（教科書からの抜粋）を元に、"
            "指定された章の**大学院レベルの極めて詳細な講義ノート**をMarkdown形式で作成してください。\n\n"
            "【構成ルール（この順番で必ず全セクション出力すること）】\n"
            "## ① 学術的背景と動機\n"
            "この分野が歴史的にどのように発展してきたか、なぜこの章のテーマが重要なのかを、"
            "学術的背景（先駆的研究、影響を与えた論文・研究者）を交えて解説すること。\n\n"
            "## ② 核心概念の体系的整理\n"
            "この章の核となる概念を階層構造で整理。各概念に厳密な定義（数学的定義を含む）を付与すること。\n\n"
            "## ③ 理論的詳細解説\n"
            "各概念を数式導出を含めて深掘り。定理の証明、アルゴリズムの計算量解析、"
            "コンテキストからの引用を豊富に含めること。\n\n"
            "## ④ 実験事例・応用例\n"
            "この理論が実際にどのような実験や応用で検証・活用されているか、"
            "具体的な実験設定・結果・ベンチマークを交えて解説すること。\n\n"
            "## ⑤ 批判的検討\n"
            "この理論やアプローチの限界・弱点・未解決問題を批判的に検討すること。"
            "代替手法との比較、今後の研究方向についても言及すること。\n\n"
            "## ⑥ まとめと展望\n"
            "学んだ内容の要約、本章と次章の接続、さらなる学習のための参考文献・リソースの提示。\n\n"
            "【品質要件（厳守）】\n"
            "- 文字数は**3000文字以上**であること。これを下回る出力は不可。\n"
            "- 専門用語には必ず厳密な定義と具体例を付けること。\n"
            "- 数式はLaTeX形式で記述すること（インライン: $...$, ディスプレイ: $$...$$）。\n"
            "- アルゴリズムや手続きは、ステップバイステップで番号付きリストで示すこと。\n"
            "- 計算量・複雑度の議論を含めること。\n"
            "- **概念の構造、プロセス、フロー、または階層関係を説明する場合、"
            "必ず Mermaid.js 記法を用いて図解（ダイアグラム）を作成すること。**\n"
            "- Mermaidコードは必ず ```mermaid ... ``` というコードブロックで囲むこと。\n"
            "- フローチャート (graph TD), シーケンス図 (sequenceDiagram), "
            "マインドマップ (mindmap) などを適切に使い分けること。\n"
            "- Mermaidのノードラベルに括弧 () や [] などの特殊文字を含む場合は、"
            "ラベル全体をダブルクォートで囲むこと（例: id[\"Label (Info)\"]）。\n"
            "- 日本語で出力すること。\n"
        )
        lecture_user_prompt: str = (
            f"## コンテキスト（教科書からの抜粋）\n\n{context}\n\n"
            f"## 章タイトル\n\n{chapter_title}\n\n"
            f"## 章の概要\n\n{chapter_description}"
        )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": lecture_system_prompt},
                    {"role": "user", "content": lecture_user_prompt},
                ],
                temperature=TEMPERATURE_LECTURE,
                max_tokens=MAX_TOKENS_LECTURE,
            )
            lecture_text: str = response.choices[0].message.content or "（講義の生成に失敗しました）"
        except Exception as e:
            lecture_text = f"講義の生成に失敗しました: {e}"

        return {
            "lecture_text": lecture_text,
            "source_chunks": source_chunks,
        }
