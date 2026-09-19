"""Subject-scoped learning UX; isolated synthetic AppTest fixtures, never live generation."""

from __future__ import annotations

import json
import threading

import fitz
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
from test_ui import ui_environment as ui_environment

from src import progress
from src.materials import save_pdf
from src.views.common import scope_key

OTHER_SUBJECT = 'Synthetic/Second'


def save_profile(app, *, goal, previous='I know the basics.', approach='例題を多く解く',
                 minutes=45, analogy='Cooking'):
    text_input(app, '学習ゴール').input(goal)
    text_input(app, 'すでに知っていること・苦手なこと').input(previous)
    selectbox(app, '学び方').set_value(approach)
    selectbox(app, '1回の学習時間').set_value(minutes)
    text_input(app, 'たとえ・例に使ってほしい分野').input(analogy)
    button(app, '学び方を保存').click().run()
    assert_clean(app)
    return dict(app.session_state['learning_options'])


def add_second_material(environment):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 80), 'Synthetic second subject: practice recalling before rereading. ' * 3)
    save_pdf(environment.root / 'data', OTHER_SUBJECT, 'second.pdf', document.tobytes())
    document.close()


def subject_courses(subject=SUBJECT):
    return {key: progress.load_course_progress(key) for key in progress.get_all_courses()
            if progress.load_course_progress(key).get('subject') == subject}


def test_profile_save_subject_switch_and_restart_preserve_separate_preferences(ui_environment):
    add_second_material(ui_environment)
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    first = save_profile(app, goal='Explain retrieval to a study group.', previous='Spaced review is familiar.')
    runtime = ui_environment.runtimes[-1]
    assert runtime.store.get(scope_key(SUBJECT, view='learning-profile'), 'options') == first

    selectbox(app, '科目').select(OTHER_SUBJECT).run()
    assert_clean(app)
    assert text_input(app, '学習ゴール').value == ''
    assert app.session_state['learning_options']['analogy_domain'] == ''
    second = save_profile(app, goal='Build a memory practice project.', approach='実践・プロジェクト',
                          minutes=15, analogy='Music')
    assert second != first
    selectbox(app, '科目').select(SUBJECT).run()
    assert text_input(app, '学習ゴール').value == first['learning_goal']
    assert dict(app.session_state['learning_options']) == first

    ui_environment.shutdown()
    restarted = ui_environment.app()
    for subject, saved in [(SUBJECT, first), (OTHER_SUBJECT, second)]:
        selectbox(restarted, '科目').select(subject).run()
        assert_clean(restarted)
        assert text_input(restarted, '学習ゴール').value == saved['learning_goal']
        assert selectbox(restarted, '学び方').value == saved['learning_approach']
        assert selectbox(restarted, '1回の学習時間').value == saved['session_minutes']
        assert dict(restarted.session_state['learning_options']) == saved
    assert ui_environment.provider.calls == []
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0


def test_dashboard_and_library_course_navigation_never_generates(ui_environment):
    app = ui_environment.app()
    assert button(app, 'PDFからコースを作る').disabled
    button(app, 'PDFを追加する').click().run()
    assert_clean(app)
    assert app.radio(key='mode').value == 'Library'
    app.button(key='study_' + SUBJECT).click().run()
    assert_clean(app)
    assert app.radio(key='mode').value == 'Curriculum'
    assert selectbox(app, '科目').value == SUBJECT
    assert not text_input(app, '学習テーマ').value
    assert button(app, 'カリキュラムを作成').disabled
    navigate(app, 'Dashboard')
    button(app, 'PDFからコースを作る').click().run()
    assert_clean(app)
    assert app.radio(key='mode').value == 'Curriculum'
    assert ui_environment.provider.calls == []
    assert ui_environment.runtimes[-1].jobs.list_jobs() == []


def test_course_keeps_creation_options_after_profile_change_and_restart(ui_environment):
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    original = save_profile(app, goal='Explain learning mechanisms with examples.')
    navigate(app, 'Curriculum')
    text_input(app, '学習テーマ').input('retrieval practice').run()
    button(app, 'カリキュラムを作成').click().run()
    finish_jobs(app, ui_environment)
    courses = subject_courses()
    assert len(courses) == 1
    course_id, course = next(iter(courses.items()))
    assert course['learning_options'] == original
    changed = save_profile(app, goal='Prepare for a written exam.', approach='試験に備える', minutes=60, analogy='Sports')
    assert changed != original
    assert progress.load_course_progress(course_id)['learning_options'] == original
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment)
    lecture = progress.load_course_progress(course_id)['curriculum'][0]['lecture_content']
    assert lecture['learning_options'] == original
    assert len(ui_environment.provider.calls) == 2
    for _ in range(2):
        app.run()
        assert_clean(app)
        assert len(subject_courses()) == 1
        assert progress.load_course_progress(course_id)['learning_options'] == original
    assert len(ui_environment.provider.calls) == 2
    navigate(app, 'Dashboard')
    app.button(key='home_resume').click().run()
    assert_clean(app)
    assert app.radio(key='mode').value == 'Curriculum'
    assert selectbox(app, '保存コース').value == course_id

    ui_environment.shutdown()
    restarted = ui_environment.app()
    app_course_button = restarted.button(key='open_' + course_id)
    app_course_button.click().run()
    assert_clean(restarted)
    assert selectbox(restarted, '科目').value == SUBJECT
    assert selectbox(restarted, '保存コース').value == course_id
    assert restarted.session_state['learning_options']['learning_goal'] == changed['learning_goal']
    saved = progress.load_course_progress(course_id)
    assert saved['learning_options'] == original
    assert saved['curriculum'][0]['lecture_content'] == lecture
    assert len(ui_environment.provider.calls) == 2
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0


def test_pending_refresh_and_profile_save_do_not_duplicate_or_rewrite_request(ui_environment, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original_generate = ui_environment.provider.generate
    entered = []

    def delayed_generate(prompt, schema, cancel_event=None):
        entered.append(prompt)
        started.set()
        assert release.wait(10), 'Synthetic worker must be released by this test'
        return original_generate(prompt, schema, cancel_event)

    monkeypatch.setattr(ui_environment.provider, 'generate', delayed_generate)
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    original = save_profile(app, goal='Original frozen goal.')
    navigate(app, 'Curriculum')
    text_input(app, '学習テーマ').input('retrieval practice').run()
    try:
        button(app, 'カリキュラムを作成').click().run()
        assert started.wait(3)
        runtime = ui_environment.runtimes[-1]
        job = runtime.jobs.list_jobs()[0]
        original_job_id = job['id']
        assert job['state'] == 'running'
        assert button(app, 'カリキュラムを作成').disabled
        for _ in range(2):
            button(app, '状態を更新').click().run()
            assert_clean(app)
            assert button(app, 'カリキュラムを作成').disabled
        save_profile(app, goal='New preference applies only to later requests.', minutes=15)
        assert len(runtime.jobs.list_jobs()) == 1
        assert runtime.jobs.get(original_job_id)['payload']['options'] == original
        assert len(entered) == 1
    finally:
        release.set()
    finish_jobs(app, ui_environment)
    assert len(subject_courses()) == 1
    course = next(iter(subject_courses().values()))
    assert course['learning_options'] == original
    app.run()
    assert_clean(app)
    assert len(entered) == 1 and len(ui_environment.provider.calls) == 1
    assert len(runtime.jobs.list_jobs()) == 1
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0


def test_corrupt_saved_profile_is_preserved_and_warns_without_generation(ui_environment):
    app = ui_environment.app()
    runtime = ui_environment.runtimes[-1]
    identity = scope_key(SUBJECT, view='learning-profile')
    invalid = {'learning_goal': 'Synthetic saved original', 'session_minutes': -1, 'unknown': 'preserve'}
    runtime.store.set(identity, 'options', invalid)
    selectbox(app, '科目').select(SUBJECT).run()
    assert_clean(app)
    assert '保存された学び方を読み取れません' in text_content(app)
    assert text_input(app, '学習ゴール').value == ''
    assert json.dumps(runtime.store.get(identity, 'options'), sort_keys=True) == json.dumps(invalid, sort_keys=True)
    assert ui_environment.provider.calls == []
