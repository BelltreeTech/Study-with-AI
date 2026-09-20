"""A newly completed course opens once without overriding later manual navigation."""

from test_ui import SUBJECT, assert_clean, button, finish_jobs, navigate, selectbox, text_input
from test_ui import ui_environment as ui_environment

from src import progress


def test_second_course_opens_on_first_application_then_keeps_manual_selection(ui_environment):
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'Curriculum')
    text_input(app, '学習テーマ').input('retrieval practice').run()
    button(app, 'カリキュラムを作成').click().run()
    finish_jobs(app, ui_environment)
    first_id = selectbox(app, '保存コース').value
    text_input(app, '学習テーマ').input('spaced repetition').run()
    button(app, 'カリキュラムを作成').click().run()
    finish_jobs(app, ui_environment)
    courses = {key: progress.load_course_progress(key) for key in progress.get_all_courses()}
    assert len(courses) == 2
    second_id = next(key for key in courses if key != first_id)
    assert courses[second_id]['title'] == 'spaced repetition'
    assert selectbox(app, '保存コース').value == second_id
    assert len(ui_environment.provider.calls) == 2

    selectbox(app, '保存コース').select(first_id).run()
    app.run()
    assert_clean(app)
    assert selectbox(app, '保存コース').value == first_id
    navigate(app, 'Dashboard')
    app.button(key='open_' + second_id).click().run()
    assert_clean(app)
    assert selectbox(app, '保存コース').value == second_id
    navigate(app, 'Dashboard')
    app.button(key='open_' + first_id).click().run()
    app.run()
    assert_clean(app)
    assert selectbox(app, '保存コース').value == first_id
    assert len(ui_environment.provider.calls) == 2
