"""On-demand courses, lectures, dialogue and deterministic advancement."""

import uuid
from dataclasses import replace

import streamlit as st

from src.config import PASS_SCORES, LearningOptions
from src.progress import (
    complete_chapter,
    delete_course,
    get_all_courses,
    get_course_summary,
    get_repository,
    load_course_progress,
)
from src.runtime import Runtime
from src.views.common import options, render_pending, scope_key, show_text, submit
from src.views.view_exam import display_exam

EXAM_DIFFICULTIES = {
    "🟢 学部級（基礎確認）": {"line": 70, "api": "Easy"},
    "🟡 修士級（応用・分析）": {"line": 80, "api": "Normal"},
    "🔴 博士級（批判的考察）": {"line": 90, "api": "Hard"},
}


def render_lecture_content(text: str) -> None:
    # Render model content as Markdown only; no custom HTML/JS or executable Mermaid.
    st.markdown(text.replace(r"\[", "$$").replace(r"\]", "$$").replace(r"\(", "$").replace(r"\)", "$"))


def _export(course: dict) -> str:
    lines = ["# " + course.get("title", "学習ノート")]
    for index, chapter in enumerate(course.get("curriculum", [])):
        lines += [
            f"## 第{chapter.get('chapter', index + 1)}章: {chapter.get('title', '無題の章')}",
            chapter.get("description", ""),
        ]
        lecture = chapter.get("lecture_content") or {}
        lines += [lecture.get("markdown", lecture.get("lecture_text", "（講義未生成）"))]
        if lecture.get("supplemental_markdown"):
            lines += ["### 一般的な補足", lecture["supplemental_markdown"]]
        for source in lecture.get("sources", lecture.get("source_chunks", [])):
            lines.append(f"- {source.get('source_id', '')}: {source['source_file']} p.{source['page_number']}")
    return "\n\n".join(lines)


def _course_options(course: dict) -> LearningOptions:
    """A saved course keeps its teaching choices when sidebar preferences change."""
    saved = course.get("learning_options")
    return LearningOptions(**saved) if saved is not None else options()


def _jump_to_chapter(course_id: str, index: int) -> None:
    st.session_state["course_jump_" + course_id] = index


def _question_starter(runtime: Runtime, scope: str, key: str, question: str) -> None:
    previous = st.session_state.get(key, runtime.store.get(scope, "question_draft", ""))
    st.session_state[key] = (previous.rstrip() + "\n\n" + question).strip() if previous else question
    runtime.store.set(scope, "question_draft", st.session_state[key])


def _save_question(runtime: Runtime, scope: str, key: str) -> None:
    runtime.store.set(scope, "question_draft", st.session_state.get(key, ""))


def _save_course_topic(runtime: Runtime, scope: str) -> None:
    runtime.store.set(scope, "course_topic_draft", st.session_state.get("course_topic", ""))


def _roadmap(course_id: str, chapters: list[dict], current_index: int) -> None:
    with st.expander("学習ロードマップ · 全章を見る"):
        for index, chapter in enumerate(chapters):
            status = chapter.get("status", "locked")
            label = "修了" if status == "completed" else "学習できます" if status == "unlocked" else "前の章の修了後に進めます"
            st.markdown(f"**{index + 1}. {chapter['title']}** · {label}")
            st.caption(chapter.get("description", ""))
            if status in ("unlocked", "completed") and index != current_index:
                st.button("この章を復習" if status == "completed" else "この章へ進む",
                          key=f"roadmap_{course_id}_{index}", on_click=_jump_to_chapter,
                          args=(course_id, index))


def render_curriculum_mode(runtime: Runtime) -> None:
    st.title("コース・授業")
    st.caption("教材から学習の道筋を作り、講義 → 相談 → 確認テストの順で、一章ずつ理解を積み重ねます。")
    subject = st.session_state.get("selected_subject", "")
    session = st.session_state.get("study_session", "")
    courses = {key: load_course_progress(key) for key in get_all_courses()}
    current = {
        key: value
        for key, value in courses.items()
        if value and value.get("subject") == subject and value.get("curriculum")
    }
    legacy = {
        key: value for key, value in courses.items() if value and not value.get("subject") and value.get("curriculum")
    }
    if legacy:
        with st.expander("旧形式の保存コース（科目未割当・閲覧のみ）"):
            for key, course in legacy.items():
                st.markdown("**" + key + "**")
                st.download_button(
                    "保存講義をダウンロード", _export(course), file_name="legacy-notes.md", key="legacy_" + key
                )
                if subject and st.button("この科目へ割り当てて学習を再開", key="assign_" + key):

                    def assign(data: dict) -> None:
                        old = data["courses"][key]
                        old.update(subject=subject, title=old.get("title", key), course_id=key)
                        current_index = old.get("current_chapter_index", 0)
                        for chapter_index, old_chapter in enumerate(old.get("curriculum", [])):
                            old_chapter.setdefault("chapter", chapter_index + 1)
                            old_chapter.setdefault("title", f"第{chapter_index + 1}章")
                            old_chapter.setdefault("description", "")
                            old_chapter.setdefault(
                                "status",
                                "completed"
                                if chapter_index < current_index
                                else "unlocked"
                                if chapter_index == current_index
                                else "locked",
                            )

                    get_repository().update(assign)
                    st.rerun()
                for chapter in course["curriculum"]:
                    st.write(chapter.get("title", ""))
                    lecture = chapter.get("lecture_content") or {}
                    render_lecture_content(lecture.get("markdown", lecture.get("lecture_text", "")))
    if not subject:
        st.info("教材の科目を選ぶとコースを作成・再開できます。旧履歴はそのまま閲覧できます。")
        return
    creation_scope = scope_key(subject, session, view="course-create")
    creating = render_pending(runtime, creation_scope)
    with st.expander("新しいコースを作成", expanded=not current):
        st.write("何ができるようになりたいかを、学習テーマに書いてください。自分向けの学び方は、画面上の「あなたの学び方を設定」で保存できます。")
        if st.session_state.get("course_topic_owner") != creation_scope or "course_topic" not in st.session_state:
            st.session_state["course_topic"] = runtime.store.get(creation_scope, "course_topic_draft", options().learning_goal)
            st.session_state["course_topic_owner"] = creation_scope
        topic = st.text_input("学習テーマ", key="course_topic", on_change=_save_course_topic,
                              args=(runtime, creation_scope))
        count = st.selectbox("章数", [5, 10, 15])
        if st.button("カリキュラムを作成", disabled=creating or not topic.strip(), type="primary"):
            submit(
                runtime,
                creation_scope,
                "curriculum",
                {"topic": topic, "chapter_count": count, "_new_course_id": uuid.uuid4().hex},
            )
    if not current:
        return
    course_id = st.selectbox(
        "保存コース",
        list(current),
        format_func=lambda key: current[key].get("title", key),
        key="course_selector_" + subject,
    )
    course = current[course_id]
    try:
        course_options = _course_options(course)
    except (TypeError, ValueError):
        st.error("保存された学習設定を確認できません。講義ノートは書き出せますが、設定を確認するまで新しい生成を止めます。")
        st.download_button("講義ノートをMarkdownで保存", _export(course), file_name="study-notes.md")
        return
    st.download_button("講義ノートをMarkdownで保存", _export(course), file_name="study-notes.md")
    summary = get_course_summary(course_id)
    st.progress(summary["progress"])
    st.caption(f"{summary['completed']} / {summary['total']}章完了")
    with st.container(border=True):
        st.markdown("**このコースの学習プラン**")
        goal = getattr(course_options, "learning_goal", "")
        st.write(goal or course.get("title", "この教材を理解する"))
        st.caption(f"1回 {getattr(course_options, 'session_minutes', 25)}分 · "
                   f"{getattr(course_options, 'learning_approach', '体系的に理解')} · {course_options.audience}")
        st.caption("このコースを作成したときの設定で講義・相談・テストを続けます。" if course.get("learning_options")
                   else "以前のコースのため、生成には現在の学習設定を使います。")
        coverage = course.get("context_coverage")
        if isinstance(coverage, dict):
            st.caption(f"教材 {coverage.get('pdf_count', '—')}冊から、代表的な抜粋 "
                       f"{coverage.get('provided_page_count', '—')}ページをもとに設計。"
                       "全ページの網羅を保証するものではありません。各章の教材根拠も確認できます。")
    chapters = course["curriculum"]
    unlocked = [i for i, chapter in enumerate(chapters) if chapter.get("status") in ("unlocked", "completed")]
    if not unlocked:
        unlocked = [0]
    jump = st.session_state.pop("course_jump_" + course_id, None)
    if jump in unlocked:
        st.session_state["chapter_" + course_id] = jump
    index = st.selectbox(
        "章", unlocked, format_func=lambda i: f"第{i + 1}章 {chapters[i]['title']}", key="chapter_" + course_id
    )
    _roadmap(course_id, chapters, index)
    chapter = chapters[index]
    scope = scope_key(subject, session, course_id, str(index), "lecture")
    active = render_pending(runtime, scope)
    lecture = chapter.get("lecture_content")
    st.subheader(f"第{index + 1}章 · {chapter['title']}")
    st.write(chapter.get("description", ""))
    st.caption("現在地: 修了済みの章を復習中" if chapter.get("status") == "completed"
               else f"現在地: 全{len(chapters)}章のうち第{index + 1}章")
    if summary["completed"] == summary["total"]:
        st.success("全章を修了しました。ロードマップから苦手な章を復習したり、講義ノートを保存できます。")
    if st.button("この章の講義を生成" if not lecture else "この章の講義を再生成", disabled=active):
        submit(
            runtime,
            scope,
            "lecture",
            {
                "title": chapter["title"],
                "description": chapter.get("description", ""),
                "_chapter_index": index,
                "_previous_lecture_id": (chapter.get("lecture_content") or {}).get("lecture_id"),
            },
            course_id=course_id,
            override_options=course_options,
        )
    if not lecture:
        st.info("まずこの章の講義を作成しましょう。教材に沿った説明を読み、疑問を相談してから確認テストへ進めます。")
        return
    reading_tab, dialogue_tab, exam_tab = st.tabs(["1 · 講義を読む", "2 · 相談・例で理解する", "3 · 理解を確かめる"])
    with reading_tab:
        st.caption("まず大まかな流れをつかみ、気になった用語や例を「相談」で掘り下げましょう。")
        if "markdown" in lecture:
            show_text(lecture)
        else:
            render_lecture_content(lecture.get("lecture_text", ""))
    dialogue_scope = scope_key(
        subject, session, course_id, str(index), "dialogue:" + lecture.get("lecture_id", "legacy")
    )
    with dialogue_tab:
        st.subheader("この章について相談")
        st.caption("短い疑問からで大丈夫です。下のきっかけを選び、必要なら書き換えて「対話する」を押してください。")
        if lecture.get("supplemental_markdown"):
            st.caption("相談・出題では講義本文と一般的な補足を区別して参照します。補足の例題や練習についても質問できます。")
        if len(lecture.get("markdown", lecture.get("lecture_text", ""))) + len(lecture.get("supplemental_markdown", "")) > 6000:
            st.caption("長い講義のため、相談・出題では冒頭と末尾、質問に関係する箇所などを抜粋して参照します。講義全文は「講義を読む」で確認できます。")
        discussing = render_pending(runtime, dialogue_scope)
        history = runtime.store.get(dialogue_scope, "history", [])
        for message in history:
            with st.chat_message(message["role"]):
                if message.get("result"):
                    show_text(message["result"])
                else:
                    st.markdown(message["content"])
        question_key = "dialogue_" + dialogue_scope
        if question_key not in st.session_state:
            st.session_state[question_key] = runtime.store.get(dialogue_scope, "question_draft", "")
        analogy = getattr(course_options, "analogy_domain", "")
        starters = [
            ("やさしく言い換える", "この章の大切な考え方を、初めて学ぶ人にもわかる言葉で説明してください。"),
            ("具体例で理解する", f"この章の考え方を{analogy or '身近な場面'}の具体例で説明し、例と理論の対応を示してください。"),
            ("自分の理解を確かめる", "この章を理解できたか、自分の言葉で説明するための問いを1つください。すぐに答えを示さず考えるのを手伝ってください。"),
        ]
        for column, (label, starter) in zip(st.columns(3), starters, strict=True):
            column.button(label, key=label + dialogue_scope, disabled=discussing,
                          on_click=_question_starter, args=(runtime, dialogue_scope, question_key, starter))
        question = st.text_input(
            "講義への質問・反論", key=question_key, on_change=_save_question,
            args=(runtime, dialogue_scope, question_key),
        )
        if st.button("対話する", disabled=discussing or not question.strip()):
            submit(
                runtime,
                dialogue_scope,
                "dialogue",
                {
                    "question": question,
                    "lecture": lecture.get("markdown", lecture.get("lecture_text", "")),
                    "lecture_supplement": lecture.get("supplemental_markdown", ""),
                    "lecture_revision": lecture.get("material_revision"),
                    "history": history[-20:],
                },
                course_id=course_id,
                override_options=course_options,
            )
    exam_scope = scope_key(subject, session, course_id, str(index), "exam:" + lecture.get("lecture_id", "legacy"))
    with exam_tab:
        st.subheader("章の修了試験")
        st.caption("講義を閉じても説明できるか試してみましょう。採点後に根拠と改善点を振り返れます。")
        testing = render_pending(runtime, exam_scope)
        if chapter.get("status") == "completed":
            st.success("この章は修了済みです。講義・対話・採点履歴は再閲覧できます。")
        difficulty = st.selectbox("修了試験の難易度", list(PASS_SCORES),
                                  index=list(PASS_SCORES).index(course_options.difficulty), key="course_difficulty_" + course_id)
        st.caption(f"合格ライン: {PASS_SCORES[difficulty]}点。合格後に章を修了すると、次の章へ進めます。")
        existing_exam = runtime.store.get(exam_scope, "quiz")
        if st.button("修了試験を生成", disabled=testing or bool(existing_exam)):
            submit(
                runtime,
                exam_scope,
                "quiz",
                {
                    "topic": chapter["title"],
                    "lecture": lecture.get("markdown", lecture.get("lecture_text", "")),
                    "lecture_supplement": lecture.get("supplemental_markdown", ""),
                    "lecture_revision": lecture.get("material_revision"),
                    "chapter_index": index,
                    "lecture_id": lecture.get("lecture_id"),
                },
                course_id=course_id,
                override_options=replace(course_options, difficulty=difficulty),
            )
        display_exam(runtime, exam_scope, course_id=course_id, override_options=course_options)
        grade = runtime.store.get(exam_scope, "grade")
        if grade and grade["passed"] and chapter.get("status") != "completed":
            if st.button("章を修了して次へ進む", type="primary"):
                complete_chapter(
                    course_id, index, grade["attempt_id"], material_revision=runtime.retriever.revision(subject)
                )
                if index + 1 < len(chapters):
                    _jump_to_chapter(course_id, index + 1)
                st.rerun()
        elif grade and not grade["passed"]:
            st.info("講義の該当箇所を読み直すか、相談で改善点を質問してから再挑戦しましょう。下書きと採点履歴は保存されています。")
        if chapter.get("status") == "completed" and index + 1 < len(chapters):
            st.button("次の章へ進む", key="next_chapter_" + course_id, type="primary",
                      on_click=_jump_to_chapter, args=(course_id, index + 1))
    with st.expander("コース管理"):
        confirmed = st.checkbox("このコースを削除する（元のJSONバックアップは保持）")
        if st.button("選択コースを削除", disabled=not confirmed):
            delete_course(course_id)
            st.rerun()
