"""About page tests: AppTest navigation plus content constants."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.components.about_page import MODEL_STATUS

APP_PATH = Path(__file__).resolve().parent.parent / "frontend" / "app.py"


def _visible_text(app: AppTest) -> str:
    chunks = []
    for group in (
        "header",
        "subheader",
        "markdown",
        "caption",
        "info",
        "success",
        "warning",
    ):
        widgets = getattr(app, group)
        for index in range(len(widgets)):
            chunks.append(str(widgets[index].value))
    return "\n".join(chunks)


def test_app_loads_without_exception():
    app = AppTest.from_file(str(APP_PATH))
    app.run()
    assert not app.exception


def test_about_button_shows_hero():
    app = AppTest.from_file(str(APP_PATH))
    app.run()
    assert not app.exception
    app.button(key="about_us_button").click().run()
    assert not app.exception
    assert app.session_state["show_about"] is True
    assert "Karibu HakiScribe" in _visible_text(app)


def test_back_to_workflow_restores_step_unchanged():
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["current_step"] = "transcribe"
    app.run()
    assert not app.exception
    app.button(key="about_us_button").click().run()
    assert "Karibu HakiScribe" in _visible_text(app)
    app.button(key="back_to_workflow").click().run()
    assert not app.exception
    assert app.session_state["show_about"] is False
    assert app.session_state["current_step"] == "transcribe"
    assert "Step 1 - Upload Synthetic Hearing Recording" in _visible_text(app)


def test_model_status_complete():
    assert set(MODEL_STATUS) == {"voice", "spark", "export"}
    assert all(isinstance(value, str) and value for value in MODEL_STATUS.values())
