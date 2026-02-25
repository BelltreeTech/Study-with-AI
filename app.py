"""
RAGシステム Streamlit Webアプリケーション。

data/ ディレクトリ内のPDFを選択し、チャットインターフェースで質問応答を行う。
バックエンドには既存の src/ モジュール群（NumPyベースのベクトル検索）を使用。
"""

import streamlit as st
from pathlib import Path
import re
import uuid

from streamlit_mermaid import st_mermaid

from src.rag_pipeline import RAGPipeline
from src.progress import (
    save_course_progress,
    load_course_progress,
    get_all_courses,
    delete_course,
    get_course_summary,
    set_last_active_course,
    get_last_active_course,
)


# PDFデータディレクトリ
k_dataDir = Path("data")

# Mermaidコードブロック検出用の正規表現
k_mermaidPattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def render_lecture_content(text: str) -> None:
    """
    講義テキストを解析し、MarkdownとMermaid図解を交互に描画する。

    ```mermaid ... ``` ブロックはstreamlit_mermaidで描画し、
    それ以外のテキストはst.markdown()で表示する。

    Args:
        text: 講義ノートのテキスト（Markdown + Mermaid混在）
    """
    # LaTeX記法の正規化
    text = text.replace(r"\[", "$$").replace(r"\]", "$$")
    text = text.replace(r"\(", "$").replace(r"\)", "$")

    # Mermaidブロックを分割して交互に描画
    last_end: int = 0
    for match in k_mermaidPattern.finditer(text):
        # Mermaidブロック前のテキストをMarkdownで表示
        preceding_text: str = text[last_end:match.start()].strip()
        if preceding_text:
            st.markdown(preceding_text)

        # Mermaid図解を描画
        mermaid_code: str = match.group(1).strip()
        try:
            st_mermaid(mermaid_code, height=400)
        except Exception as e:
            # Mermaid描画失敗時はコードブロックでフォールバック
            st.warning(f"⚠️ Mermaid図解の描画に失敗しました: {e}")
            st.code(mermaid_code, language="mermaid")

        last_end = match.end()

    # 残りのテキストを表示
    remaining_text: str = text[last_end:].strip()
    if remaining_text:
        st.markdown(remaining_text)


def get_available_subjects(base_path: str = "data") -> list[str]:
    """data/配下のサブフォルダ名（科目名）のリストを返す。"""
    base: Path = Path(base_path)
    if not base.exists():
        return []
    return sorted(
        entry.name
        for entry in base.iterdir()
        if entry.is_dir() and any(entry.glob("*.pdf"))
    )


def _build_pipeline(subject: str) -> RAGPipeline:
    """
    指定された科目のRAGパイプラインを構築（またはキャッシュから復元）する。

    セッションステートにパイプラインを保持し、科目が変わった場合のみ再構築する。
    """
    if (
        "pipeline" in st.session_state
        and st.session_state.get("pipeline_key") == subject
    ):
        return st.session_state["pipeline"]

    with st.spinner(f"📚 {subject} のPDFを読み込み中... インデックスを構築しています"):
        pipeline = RAGPipeline(subject)

    # 読み込みスキップされたファイルがあればUIに警告
    if pipeline._skipped_files:
        skipped_list: str = "、".join(pipeline._skipped_files)
        st.warning(f"⚠️ 以下のファイルは読み込めませんでした: {skipped_list}")

    st.session_state["pipeline"] = pipeline
    st.session_state["pipeline_key"] = subject
    return pipeline


def _render_lobby() -> None:
    """科目選択ロビー画面を表示する。"""
    st.title("📖 Study With AI")
    st.caption("学びたい科目を選んでください。各科目には専用のPDF教材が格納されています。")

    subjects: list[str] = get_available_subjects()

    if not subjects:
        st.error(
            "data/ ディレクトリに科目フォルダが見つかりません。\n\n"
            "以下のようなフォルダ構造でPDFを配置してください:\n\n"
            "```\n"
            "data/\n"
            "├── DeepLearning/\n"
            "│   └── deep_learning.pdf\n"
            "├── Math/\n"
            "│   └── linear_algebra.pdf\n"
            "└── Science/\n"
            "    └── physics.pdf\n"
            "```"
        )
        st.stop()

    st.subheader(f"📂 利用可能な科目（{len(subjects)} 件）")

    for subject_name in subjects:
        subject_dir: Path = Path("data") / subject_name
        pdf_count: int = len(list(subject_dir.glob("*.pdf")))
        pdf_names: list[str] = [p.name for p in sorted(subject_dir.glob("*.pdf"))]

        with st.container(border=True):
            col_info, col_action = st.columns([3, 1])

            with col_info:
                st.markdown(f"### 📚 {subject_name}")
                st.caption(f"教材: {pdf_count} 冊 — {', '.join(pdf_names)}")

            with col_action:
                if st.button(
                    "📚 学習を開始する",
                    key=f"select_{subject_name}",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state["selected_subject"] = subject_name
                    st.rerun()


def main() -> None:
    """Streamlitアプリのメインエントリーポイント。"""
    # ページ設定
    st.set_page_config(
        page_title="まりによるRAG System - PDF質問応答",
        page_icon="📖",
        layout="wide",
    )

    # 科目未選択→ロビー画面
    if "selected_subject" not in st.session_state:
        st.session_state["selected_subject"] = ""

    selected_subject: str = st.session_state["selected_subject"]

    if not selected_subject:
        _render_lobby()
        return

    # ---- サイドバー ----
    with st.sidebar:
        # 科目名表示＋ロビーに戻るボタン
        st.markdown(f"### 📚 科目: **{selected_subject}**")
        if st.button("🏠 科目を選び直す（ロビーへ）", use_container_width=True):
            # セッションをクリアしてロビーに戻る
            st.session_state["selected_subject"] = ""
            st.session_state.pop("pipeline", None)
            st.session_state.pop("pipeline_key", None)
            st.rerun()

        st.divider()

        # デバッグモードトグル
        debug_mode: bool = st.toggle("🛠 テンソル透視鏡 (Debug Mode)", value=False)
        st.divider()

        # 検索パラメータ
        st.header("⚙️ 設定")
        top_k: int = st.slider("検索チャンク数 (top_k)", 1, 10, 5)

        st.divider()
        st.header("🎨 回答スタイル")
        style: str = st.selectbox(
            "ターゲット層",
            ["初心者向け (Beginner)", "専門家向け (Expert)"],
            index=0,
        )
        length: str = st.selectbox(
            "回答の長さ",
            ["簡潔 (Concise)", "普通 (Normal)", "長め・詳細 (Detailed)"],
            index=1,
        )

        st.divider()
        # モード選択
        st.header("🧭 モード")
        app_mode: str = st.radio(
            "モード選択",
            ["🔍 知識検索 (RAG)", "🎓 模擬試験 (Feynman Drill)", "🏫 カリキュラム学習 (Curriculum)"],
            index=0,
            label_visibility="collapsed",
        )

    # ---- パイプライン初期化（科目名で構築） ----
    pipeline: RAGPipeline = _build_pipeline(selected_subject)

    # ================================================================
    # モード分岐
    # ===============================================
    if app_mode == "🔍 知識検索 (RAG)":
        _render_rag_mode(pipeline, debug_mode, top_k, style, length)
    elif app_mode == "🎓 模擬試験 (Feynman Drill)":
        _render_quiz_mode(pipeline)
    else:
        _render_curriculum_mode(pipeline)


def _render_rag_mode(
    pipeline: RAGPipeline,
    debug_mode: bool,
    top_k: int,
    style: str,
    length: str,
) -> None:
    """知識検索（RAG）モードのUI。"""
    # ---- メイン画面：チャットUI ----
    st.title("📖 まりによるRAG System")
    st.caption("NumPyベースのベクトル検索（スクラッチ実装）によるPDF質問応答")

    # チャット履歴の初期化
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # 既存のチャット履歴を表示
    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            # デバッグ情報（履歴再表示時）
            if debug_mode and "debug_info" in message:
                _render_debug_info(message["debug_info"])
            st.markdown(message["content"])
            # 回答にソース情報がある場合表示
            if "sources" in message:
                _render_sources(message["sources"])

    # ユーザー入力
    if prompt := st.chat_input("PDFについて質問してください..."):
        # ユーザーメッセージを表示・保存
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # RAG回答を生成
        with st.chat_message("assistant"):
            with st.spinner("🔍 検索・回答生成中..."):
                result: dict = pipeline.query(prompt, top_k=top_k, style=style, length=length)

            # デバッグモードON → 回答の上にテンソル演算ログを表示
            if debug_mode:
                _render_debug_info(result.get("debug_info", {}))

            # 回答をMarkdownで表示（LaTeX数式も自動レンダリング）
            # LLMが非対応デリミタを使った場合のサニタイズ
            answer_text: str = result["answer"]
            answer_text = answer_text.replace(r"\[", "$$").replace(r"\]", "$$")
            answer_text = answer_text.replace(r"\(", "$").replace(r"\)", "$")
            st.markdown(answer_text)

            # 参照ソースを折りたたみ表示
            _render_sources(result["sources"])

        # アシスタントメッセージを保存
        st.session_state["messages"].append({
            "role": "assistant",
            "content": result["answer"],
            "sources": result["sources"],
            "debug_info": result.get("debug_info", {}),
        })


def _render_quiz_mode(pipeline: RAGPipeline) -> None:
    """模擬試験（Feynman Drill）モードのUI。"""
    st.title("🎓 Feynman Drill — 模擬試験モード")
    st.caption(
        "科目と難易度を選び、トピックを入力するとAIが出題します。"
        "あなたの理解度をテストしましょう！"
    )

    # session_state 初期化
    if "quiz_question" not in st.session_state:
        st.session_state["quiz_question"] = ""
    if "quiz_ref_chunks" not in st.session_state:
        st.session_state["quiz_ref_chunks"] = []
    if "quiz_grading_result" not in st.session_state:
        st.session_state["quiz_grading_result"] = None
    if "exam_subject" not in st.session_state:
        st.session_state["exam_subject"] = ""
    if "exam_difficulty" not in st.session_state:
        st.session_state["exam_difficulty"] = "Normal"
    if "exam_pipeline" not in st.session_state:
        st.session_state["exam_pipeline"] = None

    # ---- 科目・難易度設定 ----
    st.subheader("⚙️ 試験設定")
    col_subject, col_diff = st.columns([2, 1])

    # 科目一覧を取得（カリキュラムで登録済みのコース）
    all_courses: list[str] = get_all_courses()
    # 現在のパイプラインの科目もフォールバックとして含める
    current_subject: str = getattr(pipeline, "_subject", "")
    subject_options: list[str] = []
    if current_subject:
        subject_options.append(current_subject)
    for course in all_courses:
        if course not in subject_options:
            subject_options.append(course)
    if not subject_options:
        subject_options = [current_subject or "default"]

    with col_subject:
        # 前回のexam_subjectがあれば復元
        default_idx: int = 0
        saved_subject: str = st.session_state.get("exam_subject", "")
        if saved_subject in subject_options:
            default_idx = subject_options.index(saved_subject)
        selected_subject: str = st.selectbox(
            "📚 科目を選択",
            subject_options,
            index=default_idx,
            key="quiz_subject_select",
        )

    with col_diff:
        difficulty_labels: list[str] = ["Easy", "Normal", "Hard"]
        difficulty_descriptions: dict[str, str] = {
            "Easy": "🟢 学部級（基礎確認）",
            "Normal": "🟡 修士級（複合問題）",
            "Hard": "🔴 博士級（批判的考察）",
        }
        saved_diff: str = st.session_state.get("exam_difficulty", "Normal")
        default_diff_idx: int = difficulty_labels.index(saved_diff) if saved_diff in difficulty_labels else 1
        selected_difficulty: str = st.select_slider(
            "📊 難易度",
            options=difficulty_labels,
            value=difficulty_labels[default_diff_idx],
            format_func=lambda x: difficulty_descriptions.get(x, x),
            key="quiz_difficulty_slider",
        )

    # 設定をsession_stateに保存
    st.session_state["exam_subject"] = selected_subject
    st.session_state["exam_difficulty"] = selected_difficulty

    # 難易度に応じた合格ラインを表示
    pass_lines: dict[str, int] = {"Easy": 70, "Normal": 90, "Hard": 95}
    pass_line: int = pass_lines.get(selected_difficulty, 90)
    st.info(
        f"**科目:** {selected_subject}　|　"
        f"**難易度:** {difficulty_descriptions[selected_difficulty]}　|　"
        f"**合格ライン:** {pass_line}点"
    )

    # パイプライン切替: 選択科目が現在のパイプラインと異なる場合に再構築
    active_pipeline: RAGPipeline = pipeline
    if selected_subject != current_subject:
        # 異なる科目が選択されている場合
        if (
            st.session_state.get("exam_pipeline") is not None
            and st.session_state.get("exam_pipeline_subject") == selected_subject
        ):
            active_pipeline = st.session_state["exam_pipeline"]
        # 注: 実際のパイプライン初期化は試験開始時に行う

    st.divider()

    # ---- STEP 1: トピック入力 & 出題 ----
    st.subheader("① トピックを入力")
    topic: str = st.text_input(
        "学習したいトピック（例: 勾配消失問題、正規化、活性化関数）",
        placeholder="勾配消失問題",
        key="quiz_topic_input",
    )
    if st.button("🎲 出題スタート", type="primary", use_container_width=True):
        if not topic.strip():
            st.warning("トピックを入力してください。")
        else:
            # 科目が異なる場合はパイプラインを初期化
            if selected_subject != current_subject:
                with st.spinner(f"📚 {selected_subject} のインデックスを構築中..."):
                    active_pipeline = _build_pipeline(selected_subject)
                st.session_state["exam_pipeline"] = active_pipeline
                st.session_state["exam_pipeline_subject"] = selected_subject

            with st.spinner(f"📚 {difficulty_descriptions[selected_difficulty]} の問題を生成中..."):
                quiz_result: dict = active_pipeline.generate_quiz(
                    topic.strip(), difficulty=selected_difficulty
                )
            st.session_state["quiz_question"] = quiz_result["question_text"]
            st.session_state["quiz_ref_chunks"] = quiz_result["reference_chunks"]
            st.session_state["quiz_grading_result"] = None
            st.rerun()

    # ---- STEP 2: 問題表示 & 回答入力 ----
    if st.session_state["quiz_question"]:
        st.divider()
        st.subheader("② 出題された問題")
        st.markdown(st.session_state["quiz_question"])

        st.subheader("③ あなたの回答")
        # 難易度に応じたプレースホルダ
        placeholders: dict[str, str] = {
            "Easy": "パートA: Q1〜Q10の選択肢（例: A, B, C, ...）\nパートB: Q11〜Q15の短答を記述...",
            "Normal": "パートA: Q1〜Q5の選択肢（例: A, B, C, D, A）\nパートB: Q6〜Q10の論述を記述...",
            "Hard": "パートA: Q1〜Q2の批判的分析を記述...\nパートB: Q3〜Q4の統合論述を記述...",
        }
        user_answer: str = st.text_area(
            "この問題に対するあなたの回答を記述してください。",
            height=400,
            placeholder=placeholders.get(selected_difficulty, "ここに回答を入力..."),
            key="quiz_user_answer",
            label_visibility="collapsed",
        )

        if st.button("📝 採点する", type="primary", use_container_width=True):
            if not user_answer.strip():
                st.warning("回答を入力してください。")
            else:
                # 採点用パイプラインを取得
                grading_pipeline: RAGPipeline = st.session_state.get("exam_pipeline") or pipeline
                ref_context: str = "\n\n---\n\n".join(
                    chunk["text"] for chunk in st.session_state["quiz_ref_chunks"]
                )
                with st.spinner("🧑‍🏫 教授が採点中..."):
                    grading: dict = grading_pipeline.grade_answer(
                        question=st.session_state["quiz_question"],
                        user_answer=user_answer.strip(),
                        reference_context=ref_context,
                        difficulty=selected_difficulty,
                    )
                st.session_state["quiz_grading_result"] = grading
                st.rerun()

    # ---- STEP 3: 採点結果表示 ----
    grading_result: dict | None = st.session_state.get("quiz_grading_result")
    if grading_result:
        st.divider()
        st.subheader("④ 採点結果")

        # スコアバッジ（難易度別合格ライン対応）
        score: int = grading_result["score"]
        passed: bool = score >= pass_line
        if passed:
            score_badge: str = "🏆"
        elif score >= pass_line - 20:
            score_badge = "👍"
        elif score >= pass_line - 40:
            score_badge = "📝"
        else:
            score_badge = "💪"

        col_score, col_pass = st.columns([2, 1])
        with col_score:
            st.metric(f"{score_badge} スコア", f"{score} / 100 点")
        with col_pass:
            if passed:
                st.success(f"✅ 合格（{pass_line}点以上）")
            else:
                st.error(f"❌ 不合格（{pass_line}点以上で合格）")

        # プログレスバー
        st.progress(score / 100)

        # フィードバック
        st.markdown(grading_result["feedback_text"])

        # 正解の根拠
        with st.expander("📚 正解の根拠（参照コンテキスト）", expanded=False):
            for i, chunk in enumerate(st.session_state["quiz_ref_chunks"], 1):
                source_name: str = Path(chunk.get("source_file", "不明")).name
                st.markdown(
                    f"**[{i}] {source_name} — Page {chunk['page_number']}** "
                    f"(類似度: {chunk['similarity']:.4f})"
                )
                st.text(chunk["text"][:500] + ("..." if len(chunk["text"]) > 500 else ""))
                st.divider()

        # リセットボタン
        if st.button("🔄 新しい問題を出題する"):
            st.session_state["quiz_question"] = ""
            st.session_state["quiz_ref_chunks"] = []
            st.session_state["quiz_grading_result"] = None
            st.rerun()


def _render_curriculum_mode(pipeline: RAGPipeline) -> None:
    """カリキュラム学習モードのUI（複数コース対応）。"""

    # session_state 初期化
    if "active_course" not in st.session_state:
        st.session_state["active_course"] = ""
    if "curriculum" not in st.session_state:
        st.session_state["curriculum"] = []
    if "current_chapter_index" not in st.session_state:
        st.session_state["current_chapter_index"] = 0
    if "current_lecture" not in st.session_state:
        st.session_state["current_lecture"] = None
    if "lecture_chat_history" not in st.session_state:
        st.session_state["lecture_chat_history"] = []
    if "lecture_chat_chapter_idx" not in st.session_state:
        st.session_state["lecture_chat_chapter_idx"] = -1

    active_course: str = st.session_state["active_course"]

    if active_course:
        _render_course_view(pipeline, active_course)
    else:
        _render_dashboard(pipeline)


def _render_dashboard(pipeline: RAGPipeline) -> None:
    """コースダッシュボード: 受講中コース一覧 + 新規コース追加。"""
    st.title("🏫 カリキュラム学習")
    st.caption("複数のトピックを並行して体系的に学習できます。")

    all_courses: list[str] = get_all_courses()

    # ================================================================
    # 受講中コース一覧
    # ================================================================
    if all_courses:
        st.subheader(f"📚 受講中のコース一覧（{len(all_courses)} 件）")

        for course_name in all_courses:
            summary: dict = get_course_summary(course_name)
            total: int = summary["total"]
            completed: int = summary["completed"]
            progress: float = summary["progress"]

            with st.container(border=True):
                col_info, col_action = st.columns([3, 1])

                with col_info:
                    # 完了率に応じたアイコン
                    if progress >= 1.0:
                        badge = "🎓"
                    elif progress > 0:
                        badge = "📖"
                    else:
                        badge = "🆕"
                    st.markdown(f"### {badge} {course_name}")
                    st.progress(progress)
                    st.caption(f"進捗: {completed} / {total} 章完了")

                with col_action:
                    if st.button(
                        "▶️ 再開する",
                        key=f"resume_{course_name}",
                        use_container_width=True,
                    ):
                        _activate_course(course_name)
                        st.rerun()
                    if st.button(
                        "🗑️ 削除",
                        key=f"delete_{course_name}",
                        use_container_width=True,
                    ):
                        delete_course(course_name)
                        st.rerun()

    else:
        st.info("まだコースがありません。下のフォームから新しいコースを作成しましょう！")

    # ================================================================
    # 新規コース追加
    # ================================================================
    st.divider()
    st.subheader("➕ 新しいコースを追加")
    new_topic: str = st.text_input(
        "学習テーマを入力（例: Deep Learning、線形代数、確率論）",
        placeholder="Deep Learning",
        key="new_course_topic_input",
    )
    if st.button("📋 カリキュラムを作成", type="primary", use_container_width=True):
        topic_stripped: str = new_topic.strip()
        if not topic_stripped:
            st.warning("学習テーマを入力してください。")
        elif topic_stripped in all_courses:
            st.warning(f"「{topic_stripped}」はすでに登録されています。「再開する」で学習を続けてください。")
        else:
            with st.spinner("🎓 カリキュラムを設計中..."):
                result: list[dict] = pipeline.generate_curriculum(topic_stripped)
            if result:
                save_course_progress(topic_stripped, result, 0)
                _activate_course(topic_stripped)
                st.rerun()
            else:
                st.error("カリキュラムの生成に失敗しました。もう一度お試しください。")


def _activate_course(course_name: str) -> None:
    """指定コースをアクティブにし、session_stateを復元する。"""
    course_data: dict | None = load_course_progress(course_name)
    if course_data:
        st.session_state["active_course"] = course_name
        st.session_state["curriculum"] = course_data["curriculum"]
        st.session_state["current_chapter_index"] = course_data.get("current_chapter_index", 0)
        st.session_state["current_lecture"] = None
        st.session_state["exam_question"] = ""
        st.session_state["exam_ref_chunks"] = []
        st.session_state["exam_grading_result"] = None
        set_last_active_course(course_name)


def _deactivate_course() -> None:
    """コースビューからダッシュボードに戻る。"""
    st.session_state["active_course"] = ""
    st.session_state["curriculum"] = []
    st.session_state["current_chapter_index"] = 0
    st.session_state["current_lecture"] = None
    st.session_state["exam_question"] = ""
    st.session_state["exam_ref_chunks"] = []
    st.session_state["exam_grading_result"] = None


def _save_current_course() -> None:
    """アクティブなコースの現在の状態を永続化する。"""
    course_name: str = st.session_state.get("active_course", "")
    if course_name:
        save_course_progress(
            course_name,
            st.session_state["curriculum"],
            st.session_state["current_chapter_index"],
        )


def _render_course_view(pipeline: RAGPipeline, course_name: str) -> None:
    """選択されたコースの学習画面（シラバス・講義・試験）。"""
    curriculum: list[dict] = st.session_state["curriculum"]
    current_idx: int = st.session_state["current_chapter_index"]

    # ---- ヘッダー + ダッシュボードに戻るボタン ----
    col_back, col_title = st.columns([1, 5])
    with col_back:
        if st.button("⬅️ 戻る"):
            _deactivate_course()
            st.rerun()
    with col_title:
        st.title(f"🏫 {course_name}")

    # ---- サイドバー: 進捗状況表示 + 章ナビゲーション ----
    with st.sidebar:
        st.divider()
        st.header("📊 学習進捗")
        st.caption(f"📚 コース: {course_name}")

        # 章ナビゲーション用の選択肢を構築（第1章〜現在の章まで）
        nav_options: list[str] = []
        for i, ch in enumerate(curriculum):
            chapter_num: int = ch.get("chapter", i + 1)
            title: str = ch.get("title", f"第{chapter_num}章")
            status: str = ch.get("status", "locked")

            if status == "completed":
                icon = "✅"
            elif i == current_idx:
                icon = "🔥"
            else:
                icon = "🔒"

            label: str = f"{icon} 第{chapter_num}章 — {title}"
            # 現在の章以降（locked）はナビ対象外だが、表示はする
            nav_options.append(label)

        # 選択可能な章: 完了済み + 現在の章まで
        selectable_count: int = current_idx + 1
        selectable_options: list[str] = nav_options[:selectable_count]

        selected_nav: str = st.radio(
            "📚 章を選択",
            selectable_options,
            index=current_idx if current_idx < len(selectable_options) else 0,
            key="chapter_nav_radio",
        )
        viewing_idx: int = selectable_options.index(selected_nav) if selected_nav in selectable_options else current_idx

        # ロック中の章も非選択状態で表示
        if selectable_count < len(nav_options):
            st.caption("— 以下は未解放 —")
            for locked_label in nav_options[selectable_count:]:
                st.markdown(f"<span style='color:gray'>{locked_label}</span>", unsafe_allow_html=True)

        completed_count: int = sum(
            1 for ch in curriculum if ch.get("status") == "completed"
        )
        progress_ratio: float = completed_count / len(curriculum) if curriculum else 0.0
        st.progress(progress_ratio)
        st.caption(f"進捗: {completed_count} / {len(curriculum)} 章完了")

    # ---- メインエリア ----
    # サイドバーで選択された章を表示
    is_viewing_current: bool = (viewing_idx == current_idx)
    is_viewing_completed: bool = (
        viewing_idx < current_idx
        or curriculum[viewing_idx].get("status") == "completed"
    )

    if viewing_idx < len(curriculum):
        view_ch: dict = curriculum[viewing_idx]
        ch_num: int = view_ch.get("chapter", viewing_idx + 1)
        ch_title: str = view_ch.get("title", "")
        ch_desc: str = view_ch.get("description", "")

        if is_viewing_completed and not is_viewing_current:
            st.header(f"✅ 第{ch_num}章: {ch_title}（修了済み）")
        else:
            st.header(f"📖 第{ch_num}章: {ch_title}")
        st.markdown(f"**概要:** {ch_desc}")
        st.divider()

        # レクチャー表示（キャッシュ優先）
        cached_lecture: dict | None = view_ch.get("lecture_content")
        # 現在の章を見ている場合はsession_stateも参照
        if is_viewing_current:
            lecture_data: dict | None = st.session_state.get("current_lecture")
            if lecture_data is None and cached_lecture is not None:
                lecture_data = cached_lecture
                st.session_state["current_lecture"] = cached_lecture
        else:
            # 過去の章はキャッシュからのみ
            lecture_data = cached_lecture

        if lecture_data is None and is_viewing_current:
            # レクチャー未生成 → 開始ボタン（現在の章のみ）
            if st.button(
                f"📖 第{ch_num}章の学習を始める（レクチャー開始）",
                type="primary",
                use_container_width=True,
            ):
                with st.spinner("📝 大学院レベルの講義ノートを生成中...（3000文字以上の詳細版）"):
                    result: dict = pipeline.generate_lecture(ch_title, ch_desc)
                st.session_state["current_lecture"] = result
                curriculum[current_idx]["lecture_content"] = result
                st.session_state["curriculum"] = curriculum
                _save_current_course()
                st.rerun()
        elif lecture_data is None and not is_viewing_current:
            st.info("この章の講義はまだ生成されていません。")
        else:
            # レクチャー表示（Markdown + Mermaid図解）
            lecture_text: str = lecture_data.get("lecture_text", "")
            render_lecture_content(lecture_text)

            # 参照ソース
            source_chunks: list[dict] = lecture_data.get("source_chunks", [])
            if source_chunks:
                with st.expander(f"📚 参照ソース ({len(source_chunks)} 件)", expanded=False):
                    for i, chunk in enumerate(source_chunks, 1):
                        source_name: str = Path(chunk.get("source_file", "不明")).name
                        st.markdown(
                            f"**[{i}] {source_name} — Page {chunk['page_number']}** "
                            f"(類似度: {chunk['similarity']:.4f})"
                        )
                        st.text(chunk["text"][:400] + ("..." if len(chunk["text"]) > 400 else ""))
                        st.divider()

            # ============================================================
            # ソクラテス・バトル (Socratic Debate)
            # ============================================================
            st.divider()

            # 章が切り替わったら議論履歴をリセット
            if st.session_state.get("lecture_chat_chapter_idx") != viewing_idx:
                st.session_state["lecture_chat_history"] = []
                st.session_state["lecture_chat_chapter_idx"] = viewing_idx

            with st.expander("⚔️ 教授との議論 (Socratic Debate)", expanded=False):
                st.caption(
                    "講義内容について質問や反論をすると、AI教授がソクラテス式に問い返します。"
                    "深い思考への誘導を経験してください。"
                )

                chat_history: list[dict] = st.session_state["lecture_chat_history"]

                # 過去の議論履歴を表示
                for msg in chat_history:
                    with st.chat_message(msg["role"], avatar="🧑‍🎓" if msg["role"] == "user" else "🧙"):
                        st.markdown(msg["content"])

                # チャット入力
                user_input: str | None = st.chat_input(
                    "講義について質問・反論を入力...",
                    key="socratic_chat_input",
                )
                if user_input:
                    # ユーザーの入力を履歴に追加
                    chat_history.append({"role": "user", "content": user_input})

                    # 教授の応答を生成
                    with st.spinner("🧙 教授が思考中..."):
                        reply: str = pipeline.run_socratic_dialogue(
                            lecture_content=lecture_text,
                            chat_history=chat_history[:-1],  # 最新のuser入力は別途渡す
                            user_input=user_input,
                        )

                    # 教授の応答を履歴に追加
                    chat_history.append({"role": "assistant", "content": reply})
                    st.session_state["lecture_chat_history"] = chat_history
                    st.rerun()

                # 議論リセットボタン
                if chat_history:
                    if st.button("🗑️ 議論履歴をクリア", key="clear_socratic_chat"):
                        st.session_state["lecture_chat_history"] = []
                        st.rerun()

            # ============================================================
            # 進級試験 (Boss Fight) — 現在の章（未クリア）を見ている時のみ
            # ============================================================
            if is_viewing_current and not is_viewing_completed:
                st.divider()

                if "exam_question" not in st.session_state:
                    st.session_state["exam_question"] = ""
                if "exam_ref_chunks" not in st.session_state:
                    st.session_state["exam_ref_chunks"] = []
                if "exam_grading_result" not in st.session_state:
                    st.session_state["exam_grading_result"] = None

                exam_question: str = st.session_state["exam_question"]
                exam_grading: dict | None = st.session_state["exam_grading_result"]

                if not exam_question:
                    # 講義テキストを取得
                    exam_lecture_text: str = lecture_data.get("lecture_text", "") if lecture_data else ""
                    if not exam_lecture_text:
                        st.warning("⚠️ 修了試験を受けるには、まず講義を生成してください。")
                    elif st.button(
                        f"📝 第{ch_num}章の修了試験を受ける",
                        type="primary",
                        use_container_width=True,
                    ):
                        with st.spinner("🎓 講義内容に基づいて修了試験を出題中..."):
                            quiz_result: dict = pipeline.generate_quiz(
                                ch_title,
                                lecture_content=exam_lecture_text,
                            )
                        st.session_state["exam_question"] = quiz_result["question_text"]
                        st.session_state["exam_ref_chunks"] = quiz_result["reference_chunks"]
                        st.session_state["exam_grading_result"] = None
                        st.rerun()
                else:
                    st.subheader("📝 修了試験（100点満点 / 合格ライン90点）")
                    st.markdown(exam_question)

                    if exam_grading is None:
                        exam_answer: str = st.text_area(
                            "あなたの回答を入力してください",
                            height=400,
                            placeholder="パートA: Q1〜Q5の選択肢（例: A, B, C, D, A）\nパートB: Q6〜Q10の論述を記述...",
                            key="exam_answer_input",
                            label_visibility="collapsed",
                        )
                        if st.button("📝 回答を提出する", type="primary", use_container_width=True):
                            if not exam_answer.strip():
                                st.warning("回答を入力してください。")
                            else:
                                ref_context: str = "\n\n---\n\n".join(
                                    c["text"] for c in st.session_state["exam_ref_chunks"]
                                )
                                with st.spinner("🧑‍🏫 鬼採点モードで採点中..."):
                                    grading: dict = pipeline.grade_answer(
                                        question=exam_question,
                                        user_answer=exam_answer.strip(),
                                        reference_context=ref_context,
                                    )
                                st.session_state["exam_grading_result"] = grading
                                st.rerun()
                    else:
                        score: int = exam_grading["score"]
                        passed: bool = score >= 90

                        if passed:
                            st.success(f"🏆 合格！ スコア: **{score} / 100 点**")
                        else:
                            st.error(f"❌ 不合格。 スコア: **{score} / 100 点**（90点以上で合格）")

                        st.progress(score / 100)
                        st.markdown(exam_grading["feedback_text"])

                        if passed:
                            if st.button(
                                "🎉 合格！次の章へ進む",
                                type="primary",
                                use_container_width=True,
                            ):
                                curriculum[current_idx]["status"] = "completed"
                                if current_idx + 1 < len(curriculum):
                                    curriculum[current_idx + 1]["status"] = "unlocked"
                                    st.session_state["current_chapter_index"] = current_idx + 1
                                st.session_state["curriculum"] = curriculum
                                st.session_state["current_lecture"] = None
                                st.session_state["exam_question"] = ""
                                st.session_state["exam_ref_chunks"] = []
                                st.session_state["exam_grading_result"] = None
                                _save_current_course()
                                st.rerun()
                        else:
                            st.warning("講義を読み直して、もう一度挑戦してください。")
                            if st.button("🔄 再挑戦する"):
                                st.session_state["exam_question"] = ""
                                st.session_state["exam_ref_chunks"] = []
                                st.session_state["exam_grading_result"] = None
                                st.rerun()

            elif is_viewing_completed and not is_viewing_current:
                # 過去の章を閲覧中
                st.divider()
                st.success("✅ この章は修了済みです。")

        # ナビゲーション（レクチャー非表示時かつ現在の章を見ている時のみ）
        if lecture_data is None and is_viewing_current:
            st.divider()
            col_prev, _col_spacer, col_next = st.columns([1, 2, 1])

            with col_prev:
                if current_idx > 0:
                    if st.button("⬅️ 前の章"):
                        st.session_state["current_chapter_index"] = current_idx - 1
                        st.session_state["current_lecture"] = None
                        st.rerun()

            with col_next:
                if current_idx < len(curriculum) - 1:
                    if st.button("➡️ 次の章"):
                        st.session_state["current_chapter_index"] = current_idx + 1
                        st.session_state["current_lecture"] = None
                        st.rerun()

    else:
        st.success("🎉 全てのカリキュラムを完了しました！おめでとうございます！")

    # 全体のカリキュラム一覧
    st.divider()
    with st.expander("📋 カリキュラム全体を表示", expanded=False):
        for ch in curriculum:
            status_icon: str = {"completed": "✅", "unlocked": "🔓", "locked": "🔒"}.get(
                ch.get("status", "locked"), "🔒"
            )
            st.markdown(
                f"**{status_icon} 第{ch.get('chapter', '?')}章: {ch.get('title', '')}**\n\n"
                f"　{ch.get('description', '')}"
            )
            st.divider()

    # コース削除ボタン
    if st.button("🗑️ このコースを削除"):
        delete_course(course_name)
        _deactivate_course()
        st.rerun()


def _render_debug_info(debug_info: dict) -> None:
    """テンソル演算・LLM通信ペイロード・トークン消費をタブで可視化する。"""
    if not debug_info:
        return

    # 呼び出しごとに一意なIDを生成（キー重複防止）
    unique_suffix: str = str(uuid.uuid4())[:8]

    with st.expander("🛠 Deep Fluoroscopy（深淵の監視モニター）", expanded=True):
        # クエリ拡張結果の表示
        expanded_query: str = debug_info.get("expanded_query", "")
        if expanded_query:
            st.markdown(f"**🔄 拡張クエリ:** `{expanded_query}`")
            st.divider()

        tab1, tab2, tab3 = st.tabs([
            "🧮 テンソル演算",
            "📝 送信プロンプト (Payload)",
            "📊 パフォーマンス＆コスト",
        ])

        # ---- タブ1: テンソル演算 ----
        with tab1:
            query_shape = debug_info.get("query_shape", "N/A")
            docs_shape = debug_info.get("docs_shape", "N/A")
            sims_shape = debug_info.get("similarities_shape", "N/A")
            max_sim: float = debug_info.get("max_similarity", 0.0)

            n_docs: str = str(docs_shape[0]) if isinstance(docs_shape, tuple) else "N"
            emb_dim: str = str(docs_shape[1]) if isinstance(docs_shape, tuple) and len(docs_shape) > 1 else "D"

            st.code(
                f"1. Query Vector Shape     : {query_shape}\n"
                f"2. Document Matrix Shape  : {docs_shape}  ※N={n_docs} は全チャンク数\n"
                f"3. Dot Product (Cosine Similarity):\n"
                f"   ({n_docs}, {emb_dim}) ⋅ ({emb_dim},) ➔ ({n_docs},)\n"
                f"4. Resulting Similarities Shape: {sims_shape}\n"
                f"5. Max Similarity Score   : {max_sim:.4f}",
                language=None,
            )

            # 類似度スコアの分布チャート
            all_sims: list = debug_info.get("all_similarities", [])
            if all_sims:
                import pandas as pd
                st.subheader("類似度スコアの分布")
                # ヒストグラム用にビン分割
                import numpy as np
                sims_array = np.array(all_sims)
                hist_counts, bin_edges = np.histogram(sims_array, bins=50)
                bin_labels = [f"{bin_edges[i]:.2f}" for i in range(len(hist_counts))]
                df = pd.DataFrame({"チャンク数": hist_counts}, index=bin_labels)
                st.bar_chart(df)

            # ---- Semantic Shift Score ----
            semantic_shift: float = debug_info.get("semantic_shift_score", 0.0)
            if semantic_shift:
                st.subheader("🔀 Semantic Shift（クエリ拡張の意味移動距離）")
                shift_col1, shift_col2 = st.columns([1, 3])
                shift_col1.metric("類似度", f"{semantic_shift:.4f}")
                # 意味の解釈
                if semantic_shift >= 0.95:
                    shift_label = "🟢 ほぼ同義（微調整のみ）"
                elif semantic_shift >= 0.85:
                    shift_label = "🟡 適度な拡張"
                else:
                    shift_label = "🔴 大幅な意味変化"
                shift_col2.markdown(f"**解釈:** {shift_label}")

            # ---- L2 Norm Breakdown ----
            query_l2: float = debug_info.get("query_l2_norm", 0.0)
            top1_l2: float = debug_info.get("top1_doc_l2_norm", 0.0)
            raw_dot: float = debug_info.get("raw_dot_product", 0.0)
            if query_l2:
                st.subheader("📐 L2 Norm Breakdown（コサイン類似度の因数分解）")
                l2_cols = st.columns(3)
                l2_cols[0].metric("‖Query‖ (L2)", f"{query_l2:.4f}")
                l2_cols[1].metric("‖Top-1 Doc‖ (L2)", f"{top1_l2:.4f}")
                l2_cols[2].metric("A · B (内積)", f"{raw_dot:.4f}")
                st.caption(
                    f"cos(θ) = (A · B) / (‖A‖ × ‖B‖) = "
                    f"{raw_dot:.4f} / ({query_l2:.4f} × {top1_l2:.4f}) = "
                    f"{raw_dot / (query_l2 * top1_l2 + 1e-10):.4f}"
                )

            # ---- Top-K Dimensions ----
            top_dims: list = debug_info.get("top_k_dimensions", [])
            if top_dims:
                import pandas as pd
                st.subheader("🔥 Top-5 発火次元（Query Vector）")
                dim_df = pd.DataFrame(top_dims)
                dim_df.columns = ["次元 Index", "値"]
                dim_df.index = [f"#{i+1}" for i in range(len(dim_df))]
                st.dataframe(dim_df, width="stretch")

            # ---- PCA 2D マッピング ----
            pca_data: dict | None = debug_info.get("pca_plot_data")
            if pca_data:
                import pandas as pd
                st.subheader("🗺️ ベクトル空間 2Dマッピング (PCA投影)")

                # チャンクのカテゴリ分け（通常=青, top_k=緑）
                top_k_pos: set = set(pca_data.get("top_k_positions", []))
                chunk_labels: list[str] = []
                for i in range(len(pca_data["chunks_x"])):
                    if i in top_k_pos:
                        chunk_labels.append("Top-K チャンク")
                    else:
                        chunk_labels.append("チャンク")

                # クエリ + チャンク群を結合
                plot_df = pd.DataFrame({
                    "PC1": [pca_data["query"]["x"]] + pca_data["chunks_x"],
                    "PC2": [pca_data["query"]["y"]] + pca_data["chunks_y"],
                    "カテゴリ": ["🔴 クエリ"] + chunk_labels,
                })

                st.scatter_chart(
                    plot_df,
                    x="PC1",
                    y="PC2",
                    color="カテゴリ",
                    height=400,
                )
                evr = pca_data.get("explained_variance_ratio", [])
                if evr:
                    st.caption(
                        f"PCA累積寄与率: PC1={evr[0]:.2%}, PC2={evr[1]:.2%}, "
                        f"合計={sum(evr):.2%}"
                    )

        # ---- タブ2: 送信プロンプト (Payload) ----
        with tab2:
            st.subheader("System Prompt")
            system_prompt: str = debug_info.get("system_prompt", "（取得できません）")
            st.text_area(
                "LLMに渡されたシステムプロンプト全文",
                value=system_prompt,
                height=200,
                disabled=True,
                label_visibility="collapsed",
                key=f"debug_system_prompt_{unique_suffix}",
            )

            st.subheader("Context (Retrieved Chunks)")
            raw_context: str = debug_info.get("raw_context", "（取得できません）")
            st.text_area(
                "検索結果から構築されたコンテキスト全文",
                value=raw_context,
                height=300,
                disabled=True,
                label_visibility="collapsed",
                key=f"debug_raw_context_{unique_suffix}",
            )

            st.subheader("User Prompt")
            user_prompt: str = debug_info.get("user_prompt", "（取得できません）")
            st.text_area(
                "LLMに渡されたユーザープロンプト全文",
                value=user_prompt,
                height=200,
                disabled=True,
                label_visibility="collapsed",
                key=f"debug_user_prompt_{unique_suffix}",
            )

        # ---- タブ3: パフォーマンス＆コスト ----
        with tab3:
            llm_model: str = debug_info.get("llm_model", "不明")
            st.markdown(f"**モデル:** `{llm_model}`")

            # トークン消費量
            st.subheader("🎫 トークン消費")
            token_usage: dict = debug_info.get("token_usage", {})
            if token_usage:
                col1, col2, col3 = st.columns(3)
                col1.metric("Prompt Tokens", f"{token_usage.get('prompt_tokens', 0):,}")
                col2.metric("Completion Tokens", f"{token_usage.get('completion_tokens', 0):,}")
                col3.metric("Total Tokens", f"{token_usage.get('total_tokens', 0):,}")
            else:
                st.info("トークン消費量を取得できませんでした。")

            # レイテンシ
            st.subheader("⏱ レイテンシ")
            lat_cols = st.columns(4)
            lat_cols[0].metric(
                "① Embedding生成",
                f"{debug_info.get('latency_embedding_ms', 0):.0f} ms",
            )
            lat_cols[1].metric(
                "② 内積計算",
                f"{debug_info.get('latency_cosine_ms', 0):.1f} ms",
            )
            lat_cols[2].metric(
                "③ top_kソート",
                f"{debug_info.get('latency_sort_ms', 0):.1f} ms",
            )
            lat_cols[3].metric(
                "④ LLM回答生成",
                f"{debug_info.get('latency_llm_ms', 0):.0f} ms",
            )

            # コスト
            st.subheader("💰 概算コスト (USD)")
            cost: dict = debug_info.get("cost", {})
            if cost:
                cost_cols = st.columns(4)
                cost_cols[0].metric("Embedding", f"${cost.get('embedding_usd', 0):.6f}")
                cost_cols[1].metric("Prompt", f"${cost.get('prompt_usd', 0):.6f}")
                cost_cols[2].metric("Completion", f"${cost.get('completion_usd', 0):.6f}")
                cost_cols[3].metric("合計", f"${cost.get('total_usd', 0):.6f}")

            # 生成速度
            st.subheader("🚀 生成速度")
            velocity: float = debug_info.get("token_velocity", 0.0)
            st.metric("トークン生成速度", f"{velocity:.1f} tokens/sec")

            # 低確率トークン（ハルシネーション予備軍）
            st.subheader("⚠️ 低確率トークン（ハルシネーション予備軍）")
            low_prob: list = debug_info.get("low_prob_tokens", [])
            if low_prob:
                st.caption(f"確率 90% 未満のトークン: {len(low_prob)} 個検出")
                # 確率が低い順に並べ替え（上位20件）
                sorted_tokens = sorted(low_prob, key=lambda x: x["probability"])[:20]
                for item in sorted_tokens:
                    prob_val: float = item["probability"]
                    # 確率に応じたバッジ
                    if prob_val < 50:
                        badge = "🔴"
                    elif prob_val < 70:
                        badge = "🟠"
                    else:
                        badge = "🟡"
                    st.markdown(f"- {badge} `{item['token']}` : **{prob_val}%**")
            else:
                st.success("✅ 全トークンが 90% 以上の確率で生成されました。")


def _render_sources(sources: list[dict]) -> None:
    """参照ソースをエクスパンダーで折りたたんで表示する。"""
    with st.expander(f"📚 参照ソース ({len(sources)} 件)", expanded=False):
        for i, source in enumerate(sources, 1):
            source_name: str = Path(source.get("source_file", "不明")).name
            similarity: float = source.get("similarity", 0.0)

            # 類似度に応じた色
            if similarity >= 0.5:
                badge = "🟢"
            elif similarity >= 0.3:
                badge = "🟡"
            else:
                badge = "🔴"

            st.markdown(
                f"**{badge} [{i}] {source_name}** — "
                f"ページ {source['page_number']} "
                f"(類似度: `{similarity:.4f}`)"
            )
            st.caption(source.get("text_preview", ""))
            if i < len(sources):
                st.divider()


if __name__ == "__main__":
    main()
