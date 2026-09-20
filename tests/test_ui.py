"""Streamlit UI regression/E2E using isolated synthetic PDF/state and a fake Provider."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_learning import FakeProvider

from src import config, progress
from src import runtime as runtime_module
from src.embedder import LocalEmbedder
from src.materials import save_pdf
from src.retriever import LocalRetriever

APP = Path(__file__).resolve().parents[1] / 'app.py'
SUBJECT = 'Synthetic/Learning'


@dataclass
class UIEnvironment:
    root: Path
    provider: FakeProvider
    runtimes: list
    worker_errors: list

    def app(self) -> AppTest:
        return AppTest.from_file(str(APP), default_timeout=15).run()

    def shutdown(self) -> None:
        for runtime in self.runtimes:
            runtime.jobs.shutdown()
        st.cache_resource.clear()


@pytest.fixture
def ui_environment(tmp_path, monkeypatch):
    """Patch every persistence/material owner before AppTest can import the app."""
    st.cache_resource.clear()
    data, state, cache = (tmp_path / name for name in ('data', 'state', 'cache'))
    for env_name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'AZURE_OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(env_name, raising=False)
    for env_name, directory in [('STUDY_DATA_DIR', data), ('STUDY_STATE_DIR', state), ('STUDY_CACHE_DIR', cache)]:
        monkeypatch.setenv(env_name, str(directory))
    monkeypatch.setattr(config, 'DATA_DIR', str(data))
    monkeypatch.setattr(config, 'USER_DATA_DIR', state)
    monkeypatch.setattr(config, 'CACHE_DIR', cache)
    monkeypatch.setattr(progress, 'k_progressDir', state)
    monkeypatch.setattr(progress, 'k_progressFile', state / 'progress.json')
    # Views cache imported constants across different AppTest sessions.
    from src.views import view_library
    monkeypatch.setattr(view_library, 'DATA_DIR', str(data))
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 80), 'Retrieval practice improves memory. Spaced repetition schedules reviews after a delay. ' * 3)
    save_pdf(data, SUBJECT, 'synthetic-learning.pdf', document.tobytes())
    document.close()
    provider = FakeProvider()
    monkeypatch.setattr(runtime_module, 'CodexProvider', lambda: provider)
    monkeypatch.setattr(runtime_module, 'LocalRetriever', lambda root, cache_root: LocalRetriever(
        root, cache_root, embedder=LocalEmbedder(model_dir=tmp_path / 'model-intentionally-absent')))
    created = []
    worker_errors = []
    original_create = runtime_module.create_runtime

    def create_runtime(data_root, state_root, cache_root):
        assert Path(data_root) == data and Path(state_root) == state and Path(cache_root) == cache
        instance = original_create(data_root, state_root, cache_root)
        original_execute = instance.service.execute

        def execute_with_synthetic_diagnostics(request, cancel_event=None):
            try:
                return original_execute(request, cancel_event)
            except Exception as exc:
                # This fixture contains synthetic data only. Keep the underlying
                # error in memory so a failure is diagnosed before job sanitizing.
                worker_errors.append({"kind": request.kind, "type": type(exc).__name__, "error": str(exc)})
                raise

        instance.service.execute = execute_with_synthetic_diagnostics
        created.append(instance)
        return instance

    monkeypatch.setattr(runtime_module, 'create_runtime', create_runtime)
    environment = UIEnvironment(tmp_path, provider, created, worker_errors)
    yield environment
    environment.shutdown()


def assert_clean(app):
    assert not app.exception, [item.message for item in app.exception]
    assert not app.error, [item.value for item in app.error]


def button(app, label):
    return next(item for item in app.button if item.label == label)


def selectbox(app, label):
    return next(item for item in app.selectbox if item.label == label)


def text_input(app, label):
    return next(item for item in app.text_input if item.label == label)


def navigate(app, mode):
    app.radio(key='mode').set_value(mode).run()
    assert_clean(app)
    return app


def finish_jobs(app, environment, *, allow_error=False):
    """Only wait for synthetic workers; rerun then applies persisted success receipts."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        runtime = environment.runtimes[-1]
        if not any(job['state'] in ('queued', 'running') for job in runtime.jobs.list_jobs()):
            app.run()
            assert not app.exception
            if not allow_error:
                assert not environment.worker_errors, str(environment.worker_errors)
                assert_clean(app)
            return app
        time.sleep(.01)
    pytest.fail('Synthetic UI job did not finish')


def text_content(app):
    return '\n'.join(str(item.value) for element in ('markdown', 'text', 'caption', 'info', 'success', 'warning', 'title', 'subheader')
                     for item in getattr(app, element))


def test_five_screens_start_without_api_keys_or_generation(ui_environment):
    app = ui_environment.app()
    assert_clean(app)
    assert '累計: 0 EXP' in text_content(app)
    for mode in ('Dashboard', 'RAG', 'Feynman Drill', 'Curriculum', 'Library'):
        navigate(app, mode)
    assert ui_environment.provider.calls == []
    assert ui_environment.runtimes[-1].retriever.diagnostics(SUBJECT)['mode'] == 'not_indexed'
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0
    assert not (ui_environment.root / 'state' / 'progress.json').exists()


def test_ui_pdf_search_answer_course_lecture_exam_grade_progress_and_restart(ui_environment):
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'Library')
    button(app, 'ローカル索引を構築・更新').click().run()
    assert_clean(app)
    assert ui_environment.runtimes[-1].retriever.diagnostics(SUBJECT)['mode'] == 'bm25'
    assert ui_environment.provider.calls == []

    navigate(app, 'RAG')
    text_input(app, '検索語・質問').input('retrieval practice').run()
    button(app, 'ローカル検索（生成なし）').click().run()
    assert_clean(app)
    assert 'Retrieval practice improves memory' in text_content(app)
    assert ui_environment.provider.calls == []
    button(app, '教材に基づいて回答').click().run()
    finish_jobs(app, ui_environment)
    assert 'Retrieval practice improves learning' in text_content(app)
    assert len(app.chat_message) == 2
    assert len(ui_environment.provider.calls) == 1
    app.run()
    assert len(ui_environment.provider.calls) == 1  # Streamlit rerun does not resubmit.
    assert len(app.chat_message) == 2

    navigate(app, 'Curriculum')
    text_input(app, '学習テーマ').input('retrieval practice').run()
    button(app, 'カリキュラムを作成').click().run()
    finish_jobs(app, ui_environment)
    assert 'Learning retrieval 1' in text_content(app)
    courses = [key for key in progress.get_all_courses() if progress.load_course_progress(key).get('subject') == SUBJECT]
    assert len(courses) == 1
    course_id = courses[0]
    assert len(progress.load_course_progress(course_id)['curriculum']) == 5
    assert all(not chapter.get('lecture_content') for chapter in progress.load_course_progress(course_id)['curriculum'])
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment)
    assert 'Retrieval practice improves learning' in text_content(app)
    chapters = progress.load_course_progress(course_id)['curriculum']
    assert chapters[0]['lecture_content']['sections'][0]['source_ids']
    assert all(not chapter.get('lecture_content') for chapter in chapters[1:])

    text_input(app, '講義への質問・反論').input('How does retrieval improve memory?').run()
    button(app, '対話する').click().run()
    finish_jobs(app, ui_environment)
    assert len(app.chat_message) == 2
    button(app, '修了試験を生成').click().run()
    finish_jobs(app, ui_environment)
    assert 'Retrieval practice exam' in '\n'.join(item.value for item in app.subheader)
    assert 'SECRET_MODEL_ANSWER' not in text_content(app)
    assert 'SECRET_RUBRIC' not in text_content(app)
    assert button(app, '採点する').disabled
    app.text_area[0].input('Retrieval practice uses active recall and spaced repetition.').run()
    button(app, '採点する').click().run()
    finish_jobs(app, ui_environment)
    assert next(item for item in app.metric if item.label == 'スコア').value == '100 / 100'
    assert 'SECRET_MODEL_ANSWER' in text_content(app)
    button(app, '章を修了して次へ進む').click().run()
    assert_clean(app)
    assert progress.load_course_progress(course_id)['curriculum'][0]['status'] == 'completed'
    assert progress.load_course_progress(course_id)['curriculum'][1]['status'] == 'unlocked'
    assert progress.get_dashboard_data()['profile']['total_exp'] == 50
    app.run()
    assert progress.get_dashboard_data()['profile']['total_exp'] == 50
    assert len(progress.load_course_progress(course_id)['grade_history']) == 1

    navigate(app, 'Feynman Drill')
    text_input(app, '学習トピック').input('retrieval practice').run()
    button(app, '問題を生成').click().run()
    finish_jobs(app, ui_environment)
    assert 'SECRET_MODEL_ANSWER' not in text_content(app)
    app.text_area[0].input('Recall and spaced review improve retention.').run()
    button(app, '採点する').click().run()
    finish_jobs(app, ui_environment)
    assert next(item for item in app.metric if item.label == 'スコア').value == '100 / 100'
    assert len(progress.load_course_progress(SUBJECT)['grade_history']) == 1
    assert progress.get_dashboard_data()['profile']['total_exp'] == 50

    calls_before_restart = len(ui_environment.provider.calls)
    ui_environment.shutdown()
    restarted = ui_environment.app()
    assert_clean(restarted)
    assert '累計: 50 EXP' in text_content(restarted)
    selectbox(restarted, '科目').select(SUBJECT).run()
    navigate(restarted, 'RAG')
    assert len(restarted.chat_message) == 2
    assert 'Retrieval practice improves learning' in text_content(restarted)
    navigate(restarted, 'Curriculum')
    assert '1 / 5章完了' in text_content(restarted)
    assert 'Retrieval practice improves learning' in text_content(restarted)
    assert len(ui_environment.provider.calls) == calls_before_restart
    assert progress.get_dashboard_data()['profile']['total_exp'] == 50


def test_ui_new_session_has_separate_history(ui_environment):
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'RAG')
    first_session = app.session_state['study_session']
    text_input(app, '検索語・質問').input('retrieval practice').run()
    button(app, '教材に基づいて回答').click().run()
    finish_jobs(app, ui_environment)
    assert len(app.chat_message) == 2
    button(app, '新しい学習セッション').click().run()
    assert_clean(app)
    assert app.session_state['study_session'] != first_session
    assert len(app.chat_message) == 0
    selectbox(app, '学習セッション').select(first_session).run()
    assert_clean(app)
    assert len(app.chat_message) == 2
    assert len(ui_environment.provider.calls) == 1


def test_ui_grading_failure_never_becomes_zero_score_or_progress(ui_environment):
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'Feynman Drill')
    text_input(app, '学習トピック').input('retrieval practice').run()
    button(app, '問題を生成').click().run()
    finish_jobs(app, ui_environment)
    assert 'SECRET_MODEL_ANSWER' not in text_content(app)
    before = progress.get_repository().read()
    ui_environment.provider.fail = True
    app.text_area[0].input('Synthetic answer that receives an invalid model result.').run()
    button(app, '採点する').click().run()
    finish_jobs(app, ui_environment, allow_error=True)
    assert app.error
    assert 'invalid_result' == ui_environment.runtimes[-1].jobs.list_jobs()[0]['error_code']
    assert not any(item.label == 'スコア' for item in app.metric)
    assert 'SECRET_MODEL_ANSWER' not in text_content(app)
    assert progress.get_repository().read() == before
    call_count = len(ui_environment.provider.calls)
    app.run()
    assert len(ui_environment.provider.calls) == call_count
    assert progress.get_repository().read() == before


def test_ui_cancel_discards_late_success(ui_environment, monkeypatch):
    started = threading.Event()
    original = ui_environment.provider.generate

    def delayed_generate(prompt, schema, cancel_event=None):
        started.set()
        assert cancel_event is not None
        assert cancel_event.wait(5), 'Test must cancel its own worker'
        return original(prompt, schema, cancel_event)

    monkeypatch.setattr(ui_environment.provider, 'generate', delayed_generate)
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'RAG')
    text_input(app, '検索語・質問').input('retrieval practice').run()
    button(app, '教材に基づいて回答').click().run()
    assert started.wait(3)
    app.run()
    assert button(app, '教材に基づいて回答').disabled
    button(app, 'キャンセル').click().run()
    finish_jobs(app, ui_environment, allow_error=True)
    assert ui_environment.runtimes[-1].jobs.list_jobs()[0]['state'] == 'cancelled'
    assert len(app.chat_message) == 0
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0


def test_ui_pomodoro_completion_awards_once(ui_environment):
    app = ui_environment.app()
    button(app, '25分集中スタート').click().run()
    assert_clean(app)
    event_id = app.session_state['pomodoro_id']
    app.session_state['pomodoro_start'] = time.time() - 1501
    app.run()
    assert_clean(app)
    profile = progress.get_dashboard_data()['profile']
    assert (profile['total_pomodoros'], profile['focused_minutes'], profile['total_exp']) == (1, 25, 20)
    # Replaying the same timer's completion cannot add a second reward.
    app.session_state['pomodoro_id'] = event_id
    app.session_state['pomodoro_start'] = time.time() - 1501
    app.run()
    assert_clean(app)
    assert progress.get_dashboard_data()['profile']['total_exp'] == 20
    assert progress.get_dashboard_data()['profile']['total_pomodoros'] == 1
    assert ui_environment.provider.calls == []


def test_ui_schema_failure_shows_safe_detail_without_progress(ui_environment, monkeypatch):
    from src.codex_provider import ProviderError

    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise ProviderError('schema_error', 'PRIVATE synthetic output', diagnostic={
            'category': 'schema_validation', 'keyword': 'maxLength',
            'path': ['title'], 'limit': 120, 'actual': 121})
    monkeypatch.setattr(ui_environment.provider, 'generate', fail)
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'RAG')
    before = progress.get_repository().read()
    text_input(app, '検索語・質問').input('retrieval practice').run()
    button(app, '教材に基づいて回答').click().run()
    finish_jobs(app, ui_environment, allow_error=True)
    messages = ' '.join(item.value for item in app.error)
    assert '文字数が上限' in messages and '121' in messages and 'PRIVATE' not in messages
    assert progress.get_repository().read() == before
    app.run()
    assert calls == [1]
