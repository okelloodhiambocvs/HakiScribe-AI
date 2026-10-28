"""About page tests: AppTest navigation, content honesty, constants."""

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.components.about_page import BEYOND_PROTOTYPE, MODEL_STATUS

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
            value = str(widgets[index].value)
            if group == "markdown" and value.lstrip().startswith("<style>"):
                continue
            chunks.append(value)
    return "\n".join(chunks)


def test_app_loads_without_exception():
    app = AppTest.from_file(str(APP_PATH))
    app.run()
    assert not app.exception


def test_about_button_shows_hero_and_honest_content():
    app = AppTest.from_file(str(APP_PATH))
    app.run()
    assert not app.exception
    app.button(key="about_us_button").click().run()
    assert not app.exception
    assert app.session_state["show_about"] is True
    text = _visible_text(app)
    assert "Karibu HakiScribe" in text
    assert "Not legal advice" in text
    assert "synthetic" in text
    for chip in (
        "Judicial officers",
        "Court clerks and registry staff",
        "Advocates",
        "Litigants and appellants",
    ):
        assert chip in text
    assert not re.search(r"\d+\s*%", text)


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


def test_model_status_complete_and_live_matches_code():
    assert set(MODEL_STATUS) == {"voice", "spark", "export"}
    assert all(isinstance(value, str) and value for value in MODEL_STATUS.values())
    live = {key for key, value in MODEL_STATUS.items() if value == "Live"}
    assert live == {"voice"}


def test_beyond_prototype_all_not_built():
    assert len(BEYOND_PROTOTYPE) == 5
    assert all(label == "Not built" for _, label in BEYOND_PROTOTYPE)
