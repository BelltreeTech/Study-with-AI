"""Streamlit presentation of jobs and verified outputs; workers never touch session_state."""

import json
import re
import uuid
from dataclasses import asdict

import streamlit as st

from src import progress
from src.config import LearningOptions
from src.diagrams import mermaid_to_dot
from src.runtime import Runtime
from src.service import LearningRequest


def scope_key(subject: str, session: str = "", course: str = "", chapter: str = "", view: str = "") -> str:
    return json.dumps([subject, session, course, chapter, view], ensure_ascii=False)


def options() -> LearningOptions:
    return LearningOptions(**st.session_state["learning_options"])


def show_text(result: dict) -> None:
    if result.get("insufficient_evidence"):
        st.warning("教材の根拠が不足しています。この説明だけで理解・正しさを確定しないでください。")
    render_markdown(result.get("markdown", ""))
    if result.get("supplemental_markdown"):
        st.caption("一般的な補足（教材からの引用ではありません）")
        render_markdown(result["supplemental_markdown"])
    show_sources(result.get("sources", []))


def render_markdown(text: str) -> None:
    parts = re.split(r"```mermaid\s*\n(.*?)```", text, flags=re.DOTALL)
    for index, part in enumerate(parts):
        if index % 2 == 0:
            st.markdown(part)
        else:
            dot = mermaid_to_dot(part.strip())
            if dot:
                st.graphviz_chart(dot)
            else:
                st.caption("この図は安全に表示できる構文の範囲外のため、コードとして表示します。")
                st.code(part, language="mermaid")


def show_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander(f"📚 教材根拠（{len(sources)}件）"):
        for item in sources:
            st.caption(f"{item['source_id']} · {item['source_file']} · p.{item['page_number']}")
            st.text(item.get("text", ""))


def submit(
    runtime: Runtime,
    scope: str,
    kind: str,
    payload: dict,
    *,
    course_id: str = "",
    request_id: str | None = None,
    override_options: LearningOptions | None = None,
) -> None:
    if kind == "grade" and runtime.store.get(scope, "grade"):
        st.info("このattemptは採点済みです。新しいattemptを開始してください。")
        return
    try:
        req = runtime.service.prepare(
            kind,
            st.session_state["selected_subject"],
            st.session_state["study_session"],
            payload,
            override_options or options(),
            course_id=course_id,
            request_id=request_id,
        )

        def is_active(job_id: str) -> bool:
            previous = runtime.jobs.get(job_id)
            return bool(previous and previous["state"] in ("queued", "running", "succeeded"))

        def register() -> str:
            if kind == "grade":
                if runtime.store.get(scope, "grade"):
                    raise ValueError("このattemptは採点済みです。")
                exam = runtime.store.get(scope, "quiz")
                if not exam or exam["attempt_id"] != req.payload["exam"]["attempt_id"]:
                    raise ValueError("表示していた試験が変更されました。画面を更新してください。")
            return runtime.jobs.submit(
                kind,
                req.scope,
                req.to_dict(),
                req.request_id,
                lambda cancelled: runtime.service.execute(req, cancelled),
            )

        runtime.store.claim_submission(scope, register, is_active)
        st.rerun()
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))


def _apply(runtime: Runtime, scope: str, job: dict) -> None:
    if runtime.store.has_receipt(job["id"], scope):
        return
    req = LearningRequest.from_dict(job["payload"])
    runtime.service.validate_revision(req)
    # A stale tab cannot apply a job to another subject/session/course.
    expected_scope = json.loads(scope)
    if [req.subject, req.session_id, req.course_id] != expected_scope[:3]:
        raise ValueError("結果の保存先と科目・セッション・コースが一致しません。")
    result = job["result"]
    event = f"job:{job['id']}"
    updates = {req.kind: result}
    pair = None
    if req.kind in ("answer", "dialogue"):
        pair = [
            {"role": "user", "content": req.payload["question"], "material_revision": req.material_revision},
            {
                "role": "assistant",
                "content": result["markdown"],
                "result": result,
                "material_revision": req.material_revision,
            },
        ]
    elif req.kind == "curriculum":
        course_id = req.payload["_new_course_id"]
        progress.commit_learning_event(
            course_id,
            event,
            curriculum=result["chapters"],
            current_chapter_index=0,
            metadata={"subject": req.subject, "title": req.payload["topic"], "course_id": course_id},
        )
        updates["created_course"] = course_id
    elif req.kind == "lecture":

        def save_lecture(data: dict) -> None:
            course = data["courses"].get(req.course_id)
            if course is None:
                raise ValueError("保存先のコースがありません。")
            chapter = course["curriculum"][req.payload["_chapter_index"]]
            if chapter["title"] != req.payload["title"]:
                raise ValueError("章が変更されています。")
            if (chapter.get("lecture_content") or {}).get("lecture_id") != req.payload.get("_previous_lecture_id"):
                raise ValueError("別の学習セッションで講義が更新されています。この結果の上書きを停止しました。")
            chapter["lecture_content"] = {**result, "lecture_id": job["id"]}

        progress.get_repository().update(save_lecture, event_id=event, fingerprint=req.digest())
    elif req.kind == "grade":
        # A reset or a newer lecture must not accept a late result from this job.
        exam = runtime.store.get(scope, "quiz")
        if not exam or exam.get("attempt_id") != req.payload["exam"].get("attempt_id"):
            raise ValueError("採点対象の試験が変更されています。結果の反映を停止しました。")
        if req.course_id:
            course = progress.load_course_progress(req.course_id)
            index = req.payload["exam"]["chapter_index"]
            if not course or not 0 <= index < len(course.get("curriculum", [])):
                raise ValueError("採点対象のコース・章がありません。")
            lecture = course["curriculum"][index].get("lecture_content") or {}
            if (
                str(index) != expected_scope[3]
                or expected_scope[4] != "exam:" + req.payload["exam"]["lecture_id"]
                or lecture.get("lecture_id") != req.payload["exam"]["lecture_id"]
                or lecture.get("material_revision") != req.material_revision
            ):
                raise ValueError("採点対象の章・講義が変更されています。結果の反映を停止しました。")
        # All score and citation checks completed in StudyService before job success.
        target = req.course_id or req.subject
        progress.commit_learning_event(target, event, grading_result=result, weaknesses=result.get("weaknesses", []))
        challenge = req.payload["exam"].get("weakness_challenge", "")
        if challenge and result["passed"]:
            status = progress.process_weakness_clear(req.subject, challenge, event_id=event + ":review")
            if status in ("mastered", "leveled_up"):
                progress.add_exp(req.subject, 100 if status == "mastered" else 30, event_id=event + ":review-exp")
    elif req.kind == "quiz":
        if req.payload.get("_weakness"):
            result["weakness_challenge"] = req.payload["_weakness"]
        updates["grade"] = None
    runtime.store.apply_result(job["id"], scope, updates, message_pair=pair)


def render_pending(runtime: Runtime, scope: str) -> bool:
    """Returns True while active, false once terminal. Apply success receipts once."""
    job_id = runtime.store.get(scope, "pending")
    if not job_id:
        return False
    job = runtime.jobs.get(job_id)
    if job is None:
        st.error("ジョブが見つかりません。履歴を確認してください。")
        return False
    state = job["state"]
    if state in ("queued", "running"):
        st.info(f"生成ジョブ: {'待機中' if state == 'queued' else '実行中'} · {job_id[:8]} · GPT-6 / Medium")
        col1, col2 = st.columns(2)
        if col1.button("状態を更新", key="refresh_" + scope):
            st.rerun()
        if col2.button("キャンセル", key="cancel_" + scope):
            runtime.jobs.cancel(job_id)
            st.rerun()
        st.caption("画面を切り替えても処理は継続します。同じ学習セッションで結果を確認できます。")
        return True
    if state == "succeeded":
        try:
            _apply(runtime, scope, job)
        except (ValueError, RuntimeError) as exc:
            st.error(f"結果の反映を停止しました: {exc}")
            if st.button("この結果を破棄して再生成できる状態に戻す", key="reject_" + scope):
                runtime.store.set(scope, "rejected_result", {"job_id": job_id, "reason": "result_not_applied"})
                runtime.store.clear_pending(scope, job_id)
                st.rerun()
            return True
        runtime.store.clear_pending(scope, job_id)
        st.rerun()
    else:
        st.error(f"{state}: {job.get('error_message') or '処理は完了していません。進捗は更新されません。'}")
        st.caption("自動再試行はしません。再実行では利用枠を追加消費する場合があります。")
        if st.button("通知を閉じる", key="dismiss_" + scope):
            runtime.store.clear_pending(scope, job_id)
            st.rerun()
    return False


def new_session_id() -> str:
    return uuid.uuid4().hex


def set_options(values: LearningOptions) -> None:
    st.session_state["learning_options"] = asdict(values)
