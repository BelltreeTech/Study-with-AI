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
    assert 'HINT_ONE' not in text_content(app)
    assert 'PRACTICE_SECRET_ANSWER' not in text_content(app)
    hint_calls = len(ui_environment.provider.calls)
    button(app, '次のヒントを見る').click().run()
    assert 'HINT_ONE' in text_content(app) and 'HINT_TWO' not in text_content(app)
    assert len(ui_environment.provider.calls) == hint_calls
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


def test_new_practice_selects_latest_preserves_old_draft_and_failed_generation(ui_environment):
    app = ui_environment.app()
    create_course(app, ui_environment)
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment)
    button(app, '練習を3問作る').click().run()
    finish_jobs(app, ui_environment)
    first_id = selectbox(app, '練習セット').value
    app.text_area[0].input('Saved draft from first set.').run()
    button(app, '練習を3問作る').click().run()
    finish_jobs(app, ui_environment)
    second_id = selectbox(app, '練習セット').value
    assert second_id != first_id
    assert app.text_area[0].value == ''
    selectbox(app, '練習セット').set_value(first_id).run()
    assert app.text_area[0].value == 'Saved draft from first set.'
    app.run()
    assert selectbox(app, '練習セット').value == first_id
    ui_environment.provider.fail = True
    button(app, '練習を3問作る').click().run()
    finish_jobs(app, ui_environment, allow_error=True)
    assert selectbox(app, '練習セット').value == first_id
    assert app.text_area[0].value == 'Saved draft from first set.'
    assert len(selectbox(app, '練習セット').options) == 2
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0


def test_completed_unpublished_lecture_is_labeled_and_applied_without_generation(ui_environment):
    app = ui_environment.app()
    course_id = create_course(app, ui_environment)
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment)
    original = progress.load_course_progress(course_id)['curriculum'][0]['lecture_content']
    # Model a durable successful checkpoint whose chapter publication is missing.
    progress.get_repository().update(lambda data: data['courses'][course_id]['curriculum'][0].pop('lecture_content'))
    app.run()
    assert '追加の生成要求はありません' in text_content(app)
    calls = len(ui_environment.provider.calls)
    button(app, '保存済みの講義を反映').click().run()
    finish_jobs(app, ui_environment)
    assert len(ui_environment.provider.calls) == calls
    assert progress.load_course_progress(course_id)['curriculum'][0]['lecture_content'] == original
    assert_clean(app)


def test_review_filter_preserves_hidden_drafts_without_generation(ui_environment):
    app = ui_environment.app()
    create_course(app, ui_environment)
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment)
    button(app, '練習を3問作る').click().run()
    finish_jobs(app, ui_environment)
    app.text_area[0].input('Hidden draft must survive.').run()
    review_boxes = [item for item in app.checkbox if item.label == '復習候補にする']
    review_boxes[1].set_value(True).run()
    calls = len(ui_environment.provider.calls)
    next(item for item in app.checkbox if item.label == 'このセットの復習候補だけ表示').set_value(True).run()
    assert len(app.text_area) == 1
    assert 'Explain retrieval 2.' in text_content(app)
    assert 'Explain retrieval 1.' not in text_content(app)
    next(item for item in app.checkbox if item.label == '復習候補にする').set_value(False).run()
    assert not app.text_area
    assert 'このセットに復習候補はありません' in text_content(app)
    next(item for item in app.checkbox if item.label == 'このセットの復習候補だけ表示').set_value(False).run()
    assert app.text_area[0].value == 'Hidden draft must survive.'
    assert len(ui_environment.provider.calls) == calls
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0
    assert_clean(app)


def test_reading_location_survives_navigation_and_isolated_by_edition(ui_environment, monkeypatch):
    from test_ui import navigate

    original = ui_environment.provider.generate

    def generate(prompt, schema, cancel_event=None):
        result = original(prompt, schema, cancel_event)
        if 'requires_code' in result:
            result['sections'].append({**result['sections'][0], 'section_id': 's2', 'title': 'Second reading section'})
        if 'section_id' in result:
            result['markdown'] += ' BODY_' + result['section_id']
        return result

    monkeypatch.setattr(ui_environment.provider, 'generate', generate)
    app = ui_environment.app()
    create_course(app, ui_environment)
    button(app, 'この章の講義を生成').click().run()
    finish_jobs(app, ui_environment)
    calls = len(ui_environment.provider.calls)
    assert 'BODY_s1' in text_content(app) and 'BODY_s2' in text_content(app)
    selectbox(app, '読む範囲').set_value('s2').run()
    assert 'BODY_s2' in text_content(app) and 'BODY_s1' not in text_content(app)
    assert button(app, '次の節').disabled
    button(app, '前の節').click().run()
    assert selectbox(app, '読む範囲').value == 's1'
    navigate(app, 'Dashboard')
    navigate(app, 'Curriculum')
    assert selectbox(app, '読む範囲').value == 's1'
    button(app, '次の節').click().run()
    assert selectbox(app, '読む範囲').value == 's2'
    assert len(ui_environment.provider.calls) == calls
    assert progress.get_dashboard_data()['profile']['total_exp'] == 0
    button(app, '新しい講義版を作る').click().run()
    finish_jobs(app, ui_environment)
    assert selectbox(app, '読む範囲').value == ''
    assert_clean(app)
