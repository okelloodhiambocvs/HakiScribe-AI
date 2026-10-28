"""Frontend UI constants tests: brand, speakers, bands, steps.

Import-only checks against frontend.theme and frontend.components.stepper.
No Streamlit server needed.
"""

from frontend.components.stepper import STEPS, can_access_step, get_step_index
from frontend.theme import BRAND, SPEAKER_COLORS, confidence_style


def test_brand_colors_are_locked():
    assert BRAND["primary_dark_green"] == "#0B3D2C"
    assert BRAND["accent_gold_brown"] == "#C9A86A"


def test_speaker_colors_include_kenyan_court_roles():
    for speaker in (
        "MAGISTRATE",
        "PROSECUTOR",
        "ADVOCATE",
        "ACCUSED",
        "COMPLAINANT",
        "WITNESS_PW1",
        "UNKNOWN",
    ):
        assert speaker in SPEAKER_COLORS


def test_confidence_style_flags_low_confidence():
    assert "Needs human review" in confidence_style(0.61)[0]
    assert "Needs human review" not in confidence_style(0.96)[0]


def test_stepper_steps_match_workflow():
    assert [key for key, _ in STEPS] == ["upload", "transcribe", "review", "export"]


def test_step_access_requires_recording_and_transcript():
    assert can_access_step("upload", False, False) == (True, "")
    allowed, reason = can_access_step("transcribe", False, False)
    assert allowed is False
    assert reason != ""
    assert can_access_step("review", True, False)[0] is False
    assert can_access_step("review", True, True) == (True, "")
    assert can_access_step("export", True, True) == (True, "")


def test_get_step_index_is_safe():
    assert get_step_index("review") == 2
    assert get_step_index("unknown-step") == 0
