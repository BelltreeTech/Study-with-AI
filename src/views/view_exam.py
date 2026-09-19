"""Structured exams: secret answer fields are projected out until grading succeeds."""

from dataclasses import replace

import streamlit as st

from src.config import PASS_SCORES, LearningOptions
from src.progress import get_weaknesses
from src.runtime import Runtime
from src.schemas import public_exam
from src.views.common import options, render_pending, scope_key, show_lecture_context, show_sources, submit


def _draft_name(exam: dict) -> str:
    return "answer_draft:" + exam["attempt_id"]


def _save_answer(runtime: Runtime, scope: str, name: str, key: str) -> None:
    runtime.store.set(scope, name, st.session_state.get(key, ""))


def _reset_exam(runtime: Runtime, scope: str, attempt_id: str) -> None:
    def is_active(job_id: str) -> bool:
        job = runtime.jobs.get(job_id)
        return bool(job and job["state"] in ("queued", "running", "succeeded"))

    runtime.store.reset_exam(scope, attempt_id, is_active)


def display_exam(
    runtime: Runtime, scope: str, *, course_id: str = "", override_options: LearningOptions | None = None
) -> None:
    archived = runtime.store.get(scope, "answer_archive", [])
    if archived:
        with st.expander("以前の試験の答案"):
            for item in reversed(archived):
                st.markdown("**" + item["exam"]["title"] + "**")
                for question in item["exam"]["questions"]:
                    st.markdown(f"{question['id']}: {question['prompt']}")
                st.text(item["answer"])
    exam = runtime.store.get(scope, "quiz")
    if not exam:
        return
    pending_id = runtime.store.get(scope, "pending")
    pending_job = runtime.jobs.get(pending_id) if pending_id else None
    pending_active = bool(pending_job and pending_job["state"] in ("queued", "running", "succeeded"))
    public = public_exam(exam)
    st.subheader(public["title"])
    show_lecture_context(exam)
    st.caption(
        f"{len(public['questions'])}問 / 100点 · 難易度: {exam['difficulty']} · 合格ライン {PASS_SCORES[exam['difficulty']]}点"
    )
    st.caption("自分の言葉で説明してみましょう。わからない部分や考えた途中経過も書けます。")
    for question in public["questions"]:
        with st.container(border=True):
            st.markdown(f"**{question['id']}（{question['max_points']}点）**")
            st.markdown(question["prompt"])
    grade = runtime.store.get(scope, "grade")
    draft_name = _draft_name(exam)
    answer_key = "answer_" + scope + ":" + exam["attempt_id"]
    saved_answer = runtime.store.get(scope, draft_name, "")
    if not grade:
        pending = runtime.store.get(scope, "pending")
        running = runtime.jobs.get(pending) if pending else None
        active = bool(running and running["state"] in ("queued", "running", "succeeded"))
        if answer_key not in st.session_state:
            st.session_state[answer_key] = saved_answer
        answer = st.text_area(
            "あなたの回答", key=answer_key, height=250, disabled=active,
            placeholder="q1: …\nq2: …\nわからなかったところ: …",
            on_change=_save_answer, args=(runtime, scope, draft_name, answer_key),
        )
        st.caption("入力を確定すると下書きを保存します。画面を移動したり、同じ学習セッションを開き直しても続きから書けます。")
        if st.button("採点する", key="grade_" + scope, type="primary", disabled=active or not answer.strip()):
            # Scope claim deduplicates concurrent clicks; an explicit retry gets a fresh request ID.
            runtime.store.set(scope, draft_name, answer)
            submit(runtime, scope, "grade", {"exam": exam, "answer": answer}, course_id=course_id,
                   override_options=override_options)
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
        with st.expander("提出した回答を振り返る"):
            st.text(saved_answer or "この以前の採点には答案の下書き記録がありません。")
        with st.expander("模範解答・採点基準（採点後）"):
            for question in exam["questions"]:
                st.markdown(f"**{question['id']}**")
                st.markdown(question["model_answer"])
                st.markdown(question["rubric"])
        show_sources(exam["sources"])
        st.caption("改善点を講義で確認し、説明し直してから次の問題へ進みましょう。")
    replace_confirmed = True
    if not grade and (saved_answer or st.session_state.get(answer_key, "")):
        replace_confirmed = st.checkbox(
            "この問題を終了し、新しい問題へ進む（下書きは保存済み）", key="confirm_reset_" + scope + ":" + exam["attempt_id"]
        )
    st.button("新しい試験attemptを開始", key="reset_" + scope,
              disabled=pending_active or not replace_confirmed,
              on_click=_reset_exam, args=(runtime, scope, exam["attempt_id"]))


def render_exam_mode(runtime: Runtime) -> None:
    st.title("テスト・復習")
    st.caption("教材の内容を自分の言葉で説明し、できたところと次に復習するところを見つけます。")
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
    existing_exam = runtime.store.get(scope, "quiz")
    if existing_exam:
        st.info("取り組み中の問題を表示しています。新しい問題に切り替えるときは、下の「新しい試験attemptを開始」を使います。")
    if st.button("問題を生成", type="primary", disabled=active or not topic.strip() or bool(existing_exam)):
        submit(
            runtime,
            scope,
            "quiz",
            {"topic": topic, "_weakness": weakness},
            override_options=replace(options(), difficulty=difficulty),
        )
    display_exam(runtime, scope)
