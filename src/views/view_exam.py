"""
模擬試験（Feynman Drill）モードのUI描画。

科目選択、難易度設定、出題、回答、採点の一連のフローを担当する。
"""

import streamlit as st
from pathlib import Path

from src.core.rag_core import RAGCore
from src.core.ai_tutor import AITutor
from src.config import PASS_SCORES
from src.progress import update_weaknesses, get_weaknesses, remove_weakness


def _build_exam_pipeline(subject: str) -> tuple[RAGCore, AITutor]:
    """模擬試験用のコンポーネント構築。"""
    if (
        "exam_rag_core" in st.session_state
        and st.session_state.get("exam_pipeline_key") == subject
    ):
        return st.session_state["exam_rag_core"], st.session_state["exam_ai_tutor"]

    with st.spinner(f"📚 {subject} のPDFを読み込み中... インデックスを構築しています"):
        rag_core = RAGCore(subject)

    if rag_core._skipped_files:
        skipped_list: str = "、".join(rag_core._skipped_files)
        st.warning(f"⚠️ 以下のファイルは読み込めませんでした: {skipped_list}")

    ai_tutor = AITutor(rag_core.get_client())
    ai_tutor.set_search_index(
        chunks=rag_core.get_chunks(),
        embeddings=rag_core.get_embeddings(),
        expand_query_fn=rag_core.expand_query,
    )

    st.session_state["exam_rag_core"] = rag_core
    st.session_state["exam_ai_tutor"] = ai_tutor
    st.session_state["exam_pipeline_key"] = subject
    return rag_core, ai_tutor


def render_exam_mode(ai_tutor: AITutor) -> None:
    """模擬試験（Feynman Drill）モードのUI。"""
    st.title("🎓 Feynman Drill — 模擬試験モード")
    st.caption(
        "科目と難易度を選び、トピックを入力するとAIが出題します。"
        "あなたの理解度をテストしましょう！"
    )

    # session_state はstate_managerで初期化済み

    # ---- 科目・難易度設定 ----
    st.subheader("⚙️ 試験設定")
    col_subject, col_diff = st.columns([2, 1])

    # 科目一覧を取得（data/配下の2階層物理ディレクトリを使用）
    from app import get_grouped_subjects
    grouped: dict[str, list[str]] = get_grouped_subjects()
    # "category/subject" 形式のリストを構築
    available_subjects: list[str] = [
        f"{cat}/{subj}"
        for cat, subs in grouped.items()
        for subj in subs
    ]
    current_subject: str = st.session_state.get("selected_subject", "")
    subject_options: list[str] = []
    if current_subject and current_subject in available_subjects:
        subject_options.append(current_subject)
    for subj in available_subjects:
        if subj not in subject_options:
            subject_options.append(subj)
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
    active_tutor: AITutor = ai_tutor
    if selected_subject != current_subject:
        # 異なる科目が選択されている場合
        if (
            st.session_state.get("exam_ai_tutor_extra") is not None
            and st.session_state.get("exam_pipeline_subject") == selected_subject
        ):
            active_tutor = st.session_state["exam_ai_tutor_extra"]
        # 注: 実際のパイプライン初期化は試験開始時に行う

    st.divider()

    # ---- STEP 1: トピック入力 & 出題 ----
    st.subheader("① 出題設定")

    # 弱点克服モードのトグル
    weakness_mode = st.toggle("🔥 弱点克服特化モード")

    current_weaknesses = get_weaknesses(selected_subject)
    target_topic = ""
    is_weakness_challenge = False

    if weakness_mode:
        if not current_weaknesses:
            st.success("🎉 現在、この科目に記録されている弱点はありません！通常の学習を続けてください。")
        else:
            st.info("AIが分析したあなたの弱点一覧です。ここからランダムに出題されます。")
            # 弱点タグの表示
            tags = [f"{kw} (ミス: {data['error_count']}回)" for kw, data in current_weaknesses.items()]
            st.markdown(" ".join([f"`{tag}`" for tag in tags]))

            if st.button("🎲 弱点からランダム出題スタート", type="primary", use_container_width=True):
                import random
                # 苦手度（エラーカウント）を重みとしてランダム選択
                choices = list(current_weaknesses.keys())
                weights = [data["error_count"] for data in current_weaknesses.values()]
                target_topic = random.choices(choices, weights=weights, k=1)[0]
                is_weakness_challenge = True
                st.session_state["exam_challenge_weakness_keyword"] = target_topic
    else:
        topic_input: str = st.text_input(
            "学習したいトピック（例: 勾配消失問題、正規化、活性化関数）",
            placeholder="勾配消失問題",
            key="quiz_topic_input",
        )
        if st.button("🎲 出題スタート", type="primary", use_container_width=True):
            target_topic = topic_input.strip()
            st.session_state["exam_challenge_weakness_keyword"] = ""

    if target_topic:
        if not weakness_mode and not target_topic:
            st.warning("トピックを入力してください。")
        else:
            if selected_subject != current_subject:
                with st.spinner(f"📚 {selected_subject} のインデックスを構築中..."):
                    _, active_tutor = _build_exam_pipeline(selected_subject)
                st.session_state["exam_ai_tutor_extra"] = active_tutor
                st.session_state["exam_pipeline_subject"] = selected_subject

            with st.spinner(f"📚 {difficulty_descriptions[selected_difficulty]} の問題を生成中..."):
                quiz_result: dict = active_tutor.generate_quiz(
                    target_topic, difficulty=selected_difficulty
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
                # 採点用チューターを取得
                grading_tutor: AITutor = st.session_state.get("exam_ai_tutor_extra") or ai_tutor
                ref_context: str = "\n\n---\n\n".join(
                    chunk["text"] for chunk in st.session_state["quiz_ref_chunks"]
                )
                with st.spinner("🧑‍🏫 教授が採点中..."):
                    grading: dict = grading_tutor.grade_answer(
                        question=st.session_state["quiz_question"],
                        user_answer=user_answer.strip(),
                        reference_context=ref_context,
                        difficulty=selected_difficulty,
                    )
                st.session_state["quiz_grading_result"] = grading

                # 弱点の記録（精密モード：全採点結果から抽出された弱点を記録）
                extracted_weaknesses = grading.get("weaknesses", [])
                if extracted_weaknesses:
                    update_weaknesses(selected_subject, extracted_weaknesses)

                # 弱点克服モードでの出題だった場合、合格なら克服処理
                challenge_kw = st.session_state.get("exam_challenge_weakness_keyword", "")
                if challenge_kw:
                    pass_line_for_clear = PASS_SCORES.get(selected_difficulty, 90)
                    if grading["score"] >= pass_line_for_clear:
                        remove_weakness(selected_subject, challenge_kw)
                        st.session_state["exam_weakness_cleared"] = challenge_kw
                    else:
                        st.session_state["exam_weakness_cleared"] = ""

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

        # 弱点克服の通知
        cleared_kw = st.session_state.get("exam_weakness_cleared", "")
        if cleared_kw and passed:
            st.balloons()
            st.success(f"✨ 素晴らしい！弱点「{cleared_kw}」を見事克服しました！")
            st.session_state["exam_weakness_cleared"] = ""

        # 新たに発見された弱点
        new_weaknesses = grading_result.get("weaknesses", [])
        if new_weaknesses:
            st.warning(f"⚠️ 今回の回答から、以下の概念について理解が甚いと判定されました: **{', '.join(new_weaknesses)}** （弱点リストに追加しました）")

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
