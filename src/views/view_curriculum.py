"""On-demand courses, lectures, dialogue and deterministic advancement."""

import uuid
from dataclasses import replace

import streamlit as st

from src.config import PASS_SCORES
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


def render_curriculum_mode(runtime: Runtime) -> None:
    st.title("🏫 カリキュラム学習 (Curriculum)")
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
        topic = st.text_input("学習テーマ", key="course_topic")
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
    st.download_button("講義ノートをMarkdownで保存", _export(course), file_name="study-notes.md")
    summary = get_course_summary(course_id)
    st.progress(summary["progress"])
    st.caption(f"{summary['completed']} / {summary['total']}章完了")
    chapters = course["curriculum"]
    unlocked = [i for i, chapter in enumerate(chapters) if chapter.get("status") in ("unlocked", "completed")]
    if not unlocked:
        unlocked = [0]
    index = st.selectbox(
        "章", unlocked, format_func=lambda i: f"第{i + 1}章 {chapters[i]['title']}", key="chapter_" + course_id
    )
    chapter = chapters[index]
    scope = scope_key(subject, session, course_id, str(index), "lecture")
    active = render_pending(runtime, scope)
    lecture = chapter.get("lecture_content")
    st.subheader(chapter["title"])
    st.write(chapter.get("description", ""))
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
        )
    if not lecture:
        return
    if "markdown" in lecture:
        show_text(lecture)
    else:
        render_lecture_content(lecture.get("lecture_text", ""))
    dialogue_scope = scope_key(
        subject, session, course_id, str(index), "dialogue:" + lecture.get("lecture_id", "legacy")
    )
    with st.expander("教授との議論 (Socratic Debate)"):
        discussing = render_pending(runtime, dialogue_scope)
        history = runtime.store.get(dialogue_scope, "history", [])
        for message in history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        question = st.text_input("講義への質問・反論", key="dialogue_" + course_id + str(index))
        if st.button("対話する", disabled=discussing or not question.strip()):
            submit(
                runtime,
                dialogue_scope,
                "dialogue",
                {
                    "question": question,
                    "lecture": lecture.get("markdown", lecture.get("lecture_text", "")),
                    "lecture_revision": lecture.get("material_revision"),
                    "history": history[-20:],
                },
                course_id=course_id,
            )
    exam_scope = scope_key(subject, session, course_id, str(index), "exam:" + lecture.get("lecture_id", "legacy"))
    st.subheader("章の修了試験")
    testing = render_pending(runtime, exam_scope)
    if chapter.get("status") == "completed":
        st.success("この章は修了済みです。講義・対話・採点履歴は再閲覧できます。")
    difficulty = st.selectbox("修了試験の難易度", list(PASS_SCORES), index=1)
    if st.button("修了試験を生成", disabled=testing):
        submit(
            runtime,
            exam_scope,
            "quiz",
            {
                "topic": chapter["title"],
                "lecture": lecture.get("markdown", lecture.get("lecture_text", "")),
                "lecture_revision": lecture.get("material_revision"),
                "chapter_index": index,
                "lecture_id": lecture.get("lecture_id"),
            },
            course_id=course_id,
            override_options=replace(options(), difficulty=difficulty),
        )
    display_exam(runtime, exam_scope, course_id=course_id)
    grade = runtime.store.get(exam_scope, "grade")
    if grade and grade["passed"] and chapter.get("status") != "completed":
        if st.button("章を修了して次へ進む", type="primary"):
            complete_chapter(
                course_id, index, grade["attempt_id"], material_revision=runtime.retriever.revision(subject)
            )
            st.rerun()
    with st.expander("コース管理"):
        confirmed = st.checkbox("このコースを削除する（元のJSONバックアップは保持）")
        if st.button("選択コースを削除", disabled=not confirmed):
            delete_course(course_id)
            st.rerun()
