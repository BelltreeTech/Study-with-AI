"""
カリキュラム学習モードのUI描画。

コースダッシュボード、講義表示（Mermaid図解含む）、ソクラテス対話、
進級試験の一連のフローを担当する。
"""

import streamlit as st
from pathlib import Path
import re

from streamlit_mermaid import st_mermaid

from src.core.ai_tutor import AITutor
from src.progress import (
    save_course_progress,
    load_course_progress,
    get_all_courses,
    delete_course,
    get_course_summary,
    set_last_active_course,
    add_exp,
)
from src.config import PASS_SCORE_NORMAL

# 修了試験の難易度とマッピング
EXAM_DIFFICULTIES: dict[str, dict] = {
    "🟢 学部級（基礎確認）": {"line": 70, "api": "Easy"},
    "🟡 修士級（応用・分析）": {"line": 90, "api": "Normal"},
    "🔴 博士級（批判的考察）": {"line": 95, "api": "Hard"},
}

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


def render_curriculum_mode(ai_tutor: AITutor) -> None:
    """カリキュラム学習モードのUI（複数コース対応）。"""

    # session_state はstate_managerで初期化済み

    active_course: str = st.session_state["active_course"]

    if active_course:
        _render_course_view(ai_tutor, active_course)
    else:
        _render_dashboard(ai_tutor)


def _render_dashboard(ai_tutor: AITutor) -> None:
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

    chapter_volume_str = st.selectbox(
        "📐 カリキュラムのボリューム（細かさ）を選択",
        [
            "🟢 おおざっぱに全体像を理解（約5章）",
            "🟡 標準的なペースで詳しく理解（約10章）",
            "🔴 スモールステップでめちゃ詳しく理解（約15章）",
        ],
        index=0,
        key="new_course_volume_select",
    )

    volume_map = {
        "🟢 おおざっぱに全体像を理解（約5章）": 5,
        "🟡 標準的なペースで詳しく理解（約10章）": 10,
        "🔴 スモールステップでめちゃ詳しく理解（約15章）": 15,
    }
    selected_chapter_length = volume_map[chapter_volume_str]

    if st.button("📋 カリキュラムを作成", type="primary", use_container_width=True):
        topic_stripped: str = new_topic.strip()
        if not topic_stripped:
            st.warning("学習テーマを入力してください。")
        elif topic_stripped in all_courses:
            st.warning(f"「{topic_stripped}」はすでに登録されています。「再開する」で学習を続けてください。")
        else:
            with st.spinner(f"🎓 全{selected_chapter_length}章のカリキュラムを設計中..."):
                result: list[dict] = ai_tutor.generate_curriculum(topic_stripped, chapter_length=selected_chapter_length)
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


def _render_course_view(ai_tutor: AITutor, course_name: str) -> None:
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

    # ---- 参考書エクスポート機能 (.md) ----
    md_lines: list[str] = [f"# {course_name} - 究極の学習ノート\n\n## 📋 目次（シラバス）\n"]
    for ch in curriculum:
        c_num = ch.get("chapter", "?")
        c_title = ch.get("title", "")
        c_desc = ch.get("description", "")
        md_lines.append(f"- **第{c_num}章: {c_title}**\n  - {c_desc}")

    md_lines.append("\n---\n\n## 📖 講義ノート\n")
    for ch in curriculum:
        c_num = ch.get("chapter", "?")
        c_title = ch.get("title", "")
        md_lines.append(f"### 第{c_num}章: {c_title}\n")

        lec_data = ch.get("lecture_content")
        if lec_data and "lecture_text" in lec_data:
            md_lines.append(lec_data["lecture_text"] + "\n")
        else:
            md_lines.append("*※この章の講義ノートはまだ生成されていません。学習を進めると追記されます。*\n")
        md_lines.append("---\n")

    st.download_button(
        label="📥 このコースを参考書としてダウンロード (.md)",
        data="\n".join(md_lines),
        file_name=f"{course_name}_Polymath_Note.md",
        mime="text/markdown",
        use_container_width=True,
    )

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
                current_style = st.session_state.get("tutor_style", "🧑🏫 標準モード")
                require_math = st.session_state.get("require_math", False)
                with st.spinner(f"📝 {current_style}で講義ノートを生成中..."):
                    result: dict = ai_tutor.generate_lecture(
                        ch_title, ch_desc, tutor_style=current_style, require_math=require_math
                    )
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

            # --- 講義の再生成ボタン (現在の章のみ表示) ---
            if is_viewing_current and not is_viewing_completed:
                st.write("")  # スペーサー
                if st.button("🔄 この講義を再生成する（表記バグ・内容修正用）", use_container_width=True):
                    current_style = st.session_state.get("tutor_style", "🧑🏫 標準モード")
                    require_math = st.session_state.get("require_math", False)
                    with st.spinner(f"📝 {current_style}で講義ノートを再構築中..."):
                        new_result: dict = ai_tutor.generate_lecture(
                            ch_title,
                            ch_desc,
                            tutor_style=current_style,
                            require_math=require_math,
                        )

                    # レクチャーデータを上書き
                    st.session_state["current_lecture"] = new_result
                    curriculum[current_idx]["lecture_content"] = new_result
                    st.session_state["curriculum"] = curriculum

                    # 再生成に伴い、現在の章の議論と試験状態をリセット
                    st.session_state["lecture_chat_history"] = []
                    st.session_state["exam_question"] = ""
                    st.session_state["exam_ref_chunks"] = []
                    st.session_state["exam_grading_result"] = None

                    _save_current_course()
                    st.rerun()
            # ---------------------------------------------

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

                    current_style = st.session_state.get("tutor_style", "🧑🏫 標準モード")
                    # 教授の応答を生成
                    with st.spinner(f"🧙 教授が{current_style}で思考中..."):
                        reply: str = ai_tutor.run_socratic_dialogue(
                            lecture_content=lecture_text,
                            chat_history=chat_history[:-1],  # 最新のuser入力は別途渡す
                            user_input=user_input,
                            tutor_style=current_style,
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

                # exam_*ステートはstate_managerで初期化済み

                exam_question: str = st.session_state["exam_question"]
                exam_grading: dict | None = st.session_state["exam_grading_result"]

                if not exam_question:
                    # 講義テキストを取得
                    exam_lecture_text: str = lecture_data.get("lecture_text", "") if lecture_data else ""
                    if not exam_lecture_text:
                        st.warning("⚠️ 修了試験を受けるには、まず講義を生成してください。")
                    else:
                        selected_diff = st.selectbox(
                            "📊 試験の難易度を選択",
                            options=list(EXAM_DIFFICULTIES.keys()),
                            index=list(EXAM_DIFFICULTIES.keys()).index(st.session_state.get("curriculum_exam_difficulty", "🟡 修士級（応用・分析）")),
                            key="curriculum_exam_diff_select"
                        )
                        st.session_state["curriculum_exam_difficulty"] = selected_diff

                        if st.button(
                            f"📝 第{ch_num}章の修了試験を受ける",
                            type="primary",
                            use_container_width=True,
                        ):
                            api_diff = EXAM_DIFFICULTIES[selected_diff]["api"]
                            with st.spinner("🎓 講義内容に基づいて修了試験を出題中..."):
                                quiz_result: dict = ai_tutor.generate_quiz(
                                    ch_title,
                                    difficulty=api_diff,
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
                                current_diff = st.session_state.get("curriculum_exam_difficulty", "🟡 修士級（応用・分析）")
                                api_diff = EXAM_DIFFICULTIES[current_diff]["api"]
                                with st.spinner("🧑‍🏫 鬼採点モードで採点中..."):
                                    grading: dict = ai_tutor.grade_answer(
                                        question=exam_question,
                                        user_answer=exam_answer.strip(),
                                        reference_context=ref_context,
                                        difficulty=api_diff,
                                    )
                                st.session_state["exam_grading_result"] = grading
                                st.rerun()
                    else:
                        current_diff = st.session_state.get("curriculum_exam_difficulty", "🟡 修士級（応用・分析）")
                        pass_line = EXAM_DIFFICULTIES[current_diff]["line"]
                        score: int = exam_grading["score"]
                        passed: bool = score >= pass_line

                        if passed:
                            st.success(f"🏆 合格！ スコア: **{score} / 100 点**")
                            # EXP付与（同一章の重複付与はしない）
                            selected_course = st.session_state.get("active_course", "")
                            chap_key = f"{selected_course}_ch{ch_num}"
                            if "exam_cleared_flags" not in st.session_state:
                                st.session_state["exam_cleared_flags"] = {}
                            if not st.session_state["exam_cleared_flags"].get(chap_key):
                                add_exp(selected_course, 50)
                                st.session_state["exam_cleared_flags"][chap_key] = True
                                st.toast("✨ カリキュラムクリアボーナス 50 EXP 獲得！", icon="✨")
                        else:
                            st.error(f"❌ 不合格。 スコア: **{score} / 100 点**（{pass_line}点以上で合格）")

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
