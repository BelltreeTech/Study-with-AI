"""Synthetic UI acceptance for explicit hints, durable drafts and edition isolation."""
from test_study_flow import create_course
from test_ui import assert_clean, button, finish_jobs, selectbox, text_content
from test_ui import ui_environment as ui_environment

from src import progress


def test_practice_hints_drafts_feedback_no_xp_and_edition_isolation(ui_environment):
    app = ui_environment.app()
    course_id = create_course(app, ui_environment)
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment)
    first = progress.load_course_progress(course_id)['curriculum'][0]['lecture_content']
    button(app, '練習を3問作る').click().run()
    finish_jobs(app, ui_environment)
    calls = len(ui_environment.provider.calls)
    assert 'PRACTICE_SECRET_ANSWER' not in text_content(app)
    assert 'HINT_ONE' not in text_content(app)
    button(app, '次のヒントを見る').click().run()
    assert 'HINT_ONE' in text_content(app) and 'HINT_TWO' not in text_content(app)
    button(app, '解答・解説を開く').click().run()
    assert 'PRACTICE_SECRET_ANSWER' in text_content(app)
    app.text_area[0].input('I retrieve the answer from memory.').run()
    app.run()
    assert app.text_area[0].value == 'I retrieve the answer from memory.'
    assert len(ui_environment.provider.calls) == calls
    button(app, '答案を送信してフィードバック').click().run()
    finish_jobs(app, ui_environment)
    assert 'Clear explanation' in text_content(app)
    assert next(item for item in app.checkbox if item.label == '復習候補にする').value is True
    assert len(ui_environment.provider.calls) == calls + 1
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0
    assert not progress.load_course_progress(course_id).get('grade_history')
    button(app, 'もう一度解く（提出履歴は保持）').click().run()
    assert app.text_area[0].value == ''
    assert 'Clear explanation' in text_content(app)
    button(app, '新しい講義版を作る').click().run()
    finish_jobs(app, ui_environment)
    chapter = progress.load_course_progress(course_id)['curriculum'][0]
    assert chapter['lecture_versions'] == [first]
    assert chapter['lecture_content']['lecture_id'] != first['lecture_id']
    assert 'Clear explanation' not in text_content(app)
    assert not app.text_area
    selectbox(app, '講義の版').set_value(1).run()
    assert 'Retrieval practice improves learning' in text_content(app)
    assert not any(item.label == '修了試験を生成' for item in app.button)
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0
    assert_clean(app)


def test_partial_lecture_explicit_resume_reuses_success(ui_environment, monkeypatch):
    import json

    from src.schemas import InvalidResult

    original = ui_environment.provider.generate
    failed = False

    def generate(prompt, schema, cancel_event=None):
        nonlocal failed
        data = json.loads(prompt.split('BEGIN_UNTRUSTED_DATA_JSON\n')[1].split('\nEND_UNTRUSTED_DATA_JSON')[0])
        if data['input'].get('section', {}).get('section_id') == 's2' and not failed:
            failed = True
            raise InvalidResult('synthetic interruption')
        result = original(prompt, schema, cancel_event)
        if 'requires_code' in result:
            result['sections'].append({**result['sections'][0], 'section_id': 's2', 'title': 'Retrieval example'})
        return result

    monkeypatch.setattr(ui_environment.provider, 'generate', generate)
    app = ui_environment.app()
    course_id = create_course(app, ui_environment)
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment, allow_error=True)
    assert '作成途中: 1節' in text_content(app)
    assert 'Retrieval practice improves learning' in text_content(app)
    assert not progress.load_course_progress(course_id)['curriculum'][0].get('lecture_content')
    calls = len(ui_environment.provider.calls)
    app.run()
    assert len(ui_environment.provider.calls) == calls
    assert ui_environment.worker_errors
    ui_environment.worker_errors.clear()
    button(app, '未完了の節から再開').click().run()
    finish_jobs(app, ui_environment)
    assert len(ui_environment.provider.calls) == calls + 1
    lecture = progress.load_course_progress(course_id)['curriculum'][0]['lecture_content']
    assert [section['section_id'] for section in lecture['sections']] == ['s1', 's2']
    app.run()
    assert len(ui_environment.provider.calls) == calls + 1
    assert_clean(app)


def test_legacy_lecture_converts_without_reinterpreting_settings_or_progress(ui_environment):
    from src.views.view_curriculum import _export

    app = ui_environment.app()
    course_id = create_course(app, ui_environment)
    legacy = {'lecture_id': 'legacy-lecture', 'lecture_text': 'OLD_LECTURE with 10/20/20/10 minutes.'}

    def install_old(state):
        course = state['courses'][course_id]
        course['learning_options'].pop('time_scope')
        course['learning_options']['session_minutes'] = 60
        course['curriculum'][0].update(lecture_content=legacy, status='completed')

    progress.get_repository().update(install_old)
    before = progress.get_dashboard_data()['profile']['total_exp']
    app.run()
    assert '旧方式の学習時間 60分' in text_content(app)
    assert 'OLD_LECTURE' in text_content(app)
    button(app, '新方式の講義を作る').click().run()
    finish_jobs(app, ui_environment)
    course = progress.load_course_progress(course_id)
    chapter = course['curriculum'][0]
    assert 'time_scope' not in course['learning_options']
    assert chapter['lecture_versions'] == [legacy]
    assert chapter['lecture_content']['learning_options']['time_scope'] == 'lecture_input'
    assert chapter['status'] == 'completed'
    assert progress.get_dashboard_data()['profile']['total_exp'] == before
    assert 'OLD_LECTURE' in _export(course)
    selectbox(app, '講義の版').set_value(1).run()
    assert 'OLD_LECTURE' in text_content(app)
    assert_clean(app)
