"""
模擬試験（Feynman Drill）モードのUI描画。

科目選択、難易度設定、出題、回答、採点の一連のフローを担当する。
"""

import streamlit as st
from pathlib import Path

from src.rag_pipeline import RAGPipeline
from src.progress import get_all_courses
from src.config import PASS_SCORES


def _build_pipeline(subject: str) -> RAGPipeline:
    """模擬試験用のパイプライン構築（app.pyの_build_pipelineを呼び出す代替）。"""
    if (
        "pipeline" in st.session_state
        and st.session_state.get("pipeline_key") == subject
    ):
        return st.session_state["pipeline"]

    with st.spinner(f"📚 {subject} のPDFを読み込み中... インデックスを構築しています"):
        pipeline = RAGPipeline(subject)

    if pipeline._skipped_files:
        skipped_list: str = "、".join(pipeline._skipped_files)
        st.warning(f"⚠️ 以下のファイルは読み込めませんでした: {skipped_list}")

    st.session_state["pipeline"] = pipeline
    st.session_state["pipeline_key"] = subject
    return pipeline


def render_exam_mode(pipeline: RAGPipeline) -> None:
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
    pass_line: int = PASS_SCORES.get(selected_difficulty, 90)
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
