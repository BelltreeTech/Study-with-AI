"""Synthetic learner journeys: retained drafts and course-specific teaching choices."""

import json
from dataclasses import asdict

from test_ui import (
    SUBJECT,
    assert_clean,
    button,
    finish_jobs,
    navigate,
    selectbox,
    text_content,
    text_input,
)
from test_ui import (
    ui_environment as shared_ui_environment,
)

from src import progress
from src.config import LearningOptions
from src.views.common import scope_key

ui_environment = shared_ui_environment


def answer_box(app):
    return next(item for item in app.text_area if item.label == "あなたの回答")


def prompt_data(prompt):
    return json.loads(prompt.split("BEGIN_UNTRUSTED_DATA_JSON\n")[1].split("\nEND_UNTRUSTED_DATA_JSON")[0])


def create_course(app, environment):
    selectbox(app, "科目").select(SUBJECT).run()
    navigate(app, "Curriculum")
    text_input(app, "学習テーマ").input("retrieval practice").run()
    button(app, "カリキュラムを作成").click().run()
    finish_jobs(app, environment)
    return next(key for key in progress.get_all_courses()
                if progress.load_course_progress(key).get("curriculum"))


def test_course_profile_and_question_starters_apply_through_grade(ui_environment):
    app = ui_environment.app()
    course_id = create_course(app, ui_environment)
    saved = LearningOptions(learning_goal="Explain retrieval practice to a classmate",
                            prior_knowledge="I know passive reading", analogy_domain="料理",
                            learning_approach="例題を多く解く", session_minutes=45)
    progress.get_repository().update(lambda state: state["courses"][course_id].update(learning_options=asdict(saved)))
    app.run()
    assert saved.learning_goal in text_content(app)
    assert "1回 45分" in text_content(app)
    assert "Learning retrieval 5" in text_content(app)  # Locked chapters remain visible on the roadmap.
    assert "前の章の修了後に進めます" in text_content(app)

    button(app, "この章の講義を生成").click().run()
    finish_jobs(app, ui_environment)
    assert prompt_data(ui_environment.provider.calls[-1])["options"] == asdict(saved)
    assert [tab.label for tab in app.tabs] == ["1 · 講義を読む", "2 · 相談・例で理解する", "3 · 理解を確かめる"]
    text_input(app, "講義への質問・反論").input("My existing question.").run()
    before = len(ui_environment.provider.calls)
    button(app, "具体例で理解する").click().run()
    assert len(ui_environment.provider.calls) == before
    question = text_input(app, "講義への質問・反論").value
    assert question.startswith("My existing question.") and "料理" in question
    button(app, "対話する").click().run()
    finish_jobs(app, ui_environment)
    assert prompt_data(ui_environment.provider.calls[-1])["options"] == asdict(saved)

    button(app, "修了試験を生成").click().run()
    finish_jobs(app, ui_environment)
    assert prompt_data(ui_environment.provider.calls[-1])["options"] == asdict(saved)
    assert "SECRET_MODEL_ANSWER" not in text_content(app)
    answer_box(app).input("Retrieval practice uses recall and spaced repetition.").run()
    button(app, "採点する").click().run()
    finish_jobs(app, ui_environment)
    assert prompt_data(ui_environment.provider.calls[-1])["options"] == asdict(saved)
    button(app, "章を修了して次へ進む").click().run()
    assert_clean(app)
    assert selectbox(app, "章").value == 1
    assert "現在地: 全5章のうち第2章" in text_content(app)
    assert progress.get_dashboard_data()["profile"]["total_exp"] == 50
    button(app, "この章を復習").click().run()
    assert selectbox(app, "章").value == 0
    assert "SECRET_MODEL_ANSWER" in text_content(app)
    assert progress.get_dashboard_data()["profile"]["total_exp"] == 50


def test_answer_draft_survives_navigation_restart_and_new_attempt(ui_environment):
    app = ui_environment.app()
    selectbox(app, "科目").select(SUBJECT).run()
    navigate(app, "Feynman Drill")
    text_input(app, "学習トピック").input("retrieval practice").run()
    button(app, "問題を生成").click().run()
    finish_jobs(app, ui_environment)
    session = app.session_state["study_session"]
    scope = scope_key(SUBJECT, session, view="exam")
    runtime = ui_environment.runtimes[-1]
    exam = runtime.store.get(scope, "quiz")
    draft_name = "answer_draft:" + exam["attempt_id"]
    draft = "q1: Recall without looking.\nq2: I am still working on this example."
    answer_box(app).input(draft).run()
    assert runtime.store.get(scope, draft_name) == draft
    assert button(app, "問題を生成").disabled
    assert button(app, "新しい試験attemptを開始").disabled
    navigate(app, "Library")
    navigate(app, "Feynman Drill")
    assert answer_box(app).value == draft
    assert len(ui_environment.provider.calls) == 1

    ui_environment.shutdown()
    app = ui_environment.app()
    selectbox(app, "科目").select(SUBJECT).run()
    navigate(app, "Feynman Drill")
    assert answer_box(app).value == draft
    assert len(ui_environment.provider.calls) == 1
    next(item for item in app.checkbox if item.label.startswith("この問題を終了し")).check().run()
    button(app, "新しい試験attemptを開始").click().run()
    assert draft in text_content(app)
    assert "SECRET_MODEL_ANSWER" not in text_content(app)
    text_input(app, "学習トピック").input("spaced repetition").run()
    button(app, "問題を生成").click().run()
    finish_jobs(app, ui_environment)
    assert answer_box(app).value == ""
    runtime = ui_environment.runtimes[-1]
    assert runtime.store.get(scope, "quiz")["attempt_id"] != exam["attempt_id"]
    assert runtime.store.get(scope, draft_name) == draft
    assert draft in text_content(app)
    assert "SECRET_MODEL_ANSWER" not in text_content(app)
    assert progress.get_dashboard_data()["profile"]["total_exp"] == 0
