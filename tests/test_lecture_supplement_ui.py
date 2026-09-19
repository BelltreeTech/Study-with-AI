"""The course UI sends saved supplemental examples to dialogue and the quiz."""

from test_study_flow import create_course, prompt_data
from test_ui import assert_clean, button, finish_jobs, text_content, text_input
from test_ui import ui_environment as ui_environment

from src import progress


def test_saved_supplemental_example_reaches_dialogue_and_quiz(ui_environment, monkeypatch):
    supplement = "一般的な補足\n\n例題2: COOKING_SECOND_EXAMPLE uses retrieval practice while cooking."
    original_generate = ui_environment.provider.generate

    def generate_with_supplement(prompt, schema, cancel_event=None):
        result = original_generate(prompt, schema, cancel_event)
        if "markdown" in result:
            result["supplemental_markdown"] = supplement
        return result

    monkeypatch.setattr(ui_environment.provider, "generate", generate_with_supplement)
    app = ui_environment.app()
    course_id = create_course(app, ui_environment)
    button(app, "この章の講義を生成").click().run()
    finish_jobs(app, ui_environment)
    saved = progress.load_course_progress(course_id)["curriculum"][0]["lecture_content"]
    assert saved["supplemental_markdown"] == supplement
    assert "COOKING_SECOND_EXAMPLE" in text_content(app)
    assert "補足の例題や練習についても質問できます" in text_content(app)

    text_input(app, "講義への質問・反論").input("例題2をもう少し詳しく説明してください").run()
    button(app, "対話する").click().run()
    finish_jobs(app, ui_environment)
    dialogue_data = prompt_data(ui_environment.provider.calls[-1])
    assert "COOKING_SECOND_EXAMPLE" in dialogue_data["input"]["lecture_supplement"]
    assert "COOKING_SECOND_EXAMPLE" not in dialogue_data["input"]["lecture"]
    assert dialogue_data["input"]["lecture_context"]["sections"]["lecture_supplement"]["content_kind"] == (
        "general_supplement_not_material"
    )

    button(app, "修了試験を生成").click().run()
    finish_jobs(app, ui_environment)
    quiz_data = prompt_data(ui_environment.provider.calls[-1])
    assert "COOKING_SECOND_EXAMPLE" in quiz_data["input"]["lecture_supplement"]
    assert all("COOKING_SECOND_EXAMPLE" not in item["text"] for item in quiz_data["sources"])
    assert len(quiz_data["input"]["lecture"]) + len(quiz_data["input"]["lecture_supplement"]) <= 6000
    assert progress.load_course_progress(course_id)["curriculum"][0]["lecture_content"] == saved
    assert_clean(app)
