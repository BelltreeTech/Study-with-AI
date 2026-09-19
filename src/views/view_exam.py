"""Structured exams: secret answer fields are projected out until grading succeeds."""

from dataclasses import replace

import streamlit as st

from src.config import PASS_SCORES
from src.progress import get_weaknesses
from src.runtime import Runtime
from src.schemas import public_exam
from src.views.common import options, render_pending, scope_key, show_sources, submit


def display_exam(runtime: Runtime, scope: str, *, course_id: str = "") -> None:
    exam = runtime.store.get(scope, "quiz")
    if not exam:
        return
    pending_id = runtime.store.get(scope, "pending")
    pending_job = runtime.jobs.get(pending_id) if pending_id else None
    pending_active = bool(pending_job and pending_job["state"] in ("queued", "running", "succeeded"))
    public = public_exam(exam)
    st.subheader(public["title"])
    st.caption(
        f"難易度: {exam['difficulty']} · 合格ライン {PASS_SCORES[exam['difficulty']]}点 · attempt {exam['attempt_id'][:8]}"
    )
    for question in public["questions"]:
        st.markdown(f"**{question['id']}（{question['max_points']}点）**")
        st.markdown(question["prompt"])
    grade = runtime.store.get(scope, "grade")
    if not grade:
        answer = st.text_area("あなたの回答", key="answer_" + scope, height=250)
        pending = runtime.store.get(scope, "pending")
        running = runtime.jobs.get(pending) if pending else None
        active = bool(running and running["state"] in ("queued", "running"))
        if st.button("採点する", key="grade_" + scope, type="primary", disabled=active or not answer.strip()):
            # Scope claim deduplicates concurrent clicks; an explicit retry gets a fresh request ID.
            submit(runtime, scope, "grade", {"exam": exam, "answer": answer}, course_id=course_id)
    else:
        st.metric("スコア", f"{grade['score']} / 100")
        if grade["passed"]:
            st.success(f"合格（{grade['pass_line']}点以上）")
        else:
            st.info(f"今回は{grade['pass_line']}点未満です。フィードバックを使って復習しましょう。")
        st.markdown(grade["feedback"])
        for item in grade["items"]:
            st.markdown(f"**{item['question_id']}: {item['points']}/{item['max_points']}点**")
            st.write(item["reason"])
            st.write("改善点: " + item["improvement"])
        if grade["weaknesses"]:
            st.warning("復習候補: " + "、".join(grade["weaknesses"]))
        with st.expander("模範解答・採点基準（採点後）"):
            for question in exam["questions"]:
                st.markdown(f"**{question['id']}**")
                st.markdown(question["model_answer"])
                st.markdown(question["rubric"])
        show_sources(exam["sources"])
    if st.button("新しい試験attemptを開始", key="reset_" + scope, disabled=pending_active):
        runtime.store.set(scope, "quiz", None)
        runtime.store.set(scope, "grade", None)
        st.session_state.pop("answer_" + scope, None)
        st.rerun()


def render_exam_mode(runtime: Runtime) -> None:
    st.title("🎓 模擬試験 (Feynman Drill)")
    subject = st.session_state["selected_subject"]
    scope = scope_key(subject, st.session_state["study_session"], view="exam")
    active = render_pending(runtime, scope)
    difficulty = st.selectbox("難易度", list(PASS_SCORES), index=1, key="exam_difficulty")
    st.caption(f"合格ライン: {PASS_SCORES[difficulty]}点")
    topic = st.text_input("学習トピック", key="exam_topic")
    weakness = ""
    if st.toggle("弱点克服・復習モード"):
        weaknesses = get_weaknesses(subject)
        if weaknesses:
            weakness = st.selectbox("復習する概念", list(weaknesses))
            topic = weakness
        else:
            st.info("この科目に記録された弱点はありません。")
    if st.button("問題を生成", type="primary", disabled=active or not topic.strip()):
        submit(
            runtime,
            scope,
            "quiz",
            {"topic": topic, "_weakness": weakness},
            override_options=replace(options(), difficulty=difficulty),
        )
    display_exam(runtime, scope)
