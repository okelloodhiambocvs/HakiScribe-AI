"""Human review: edits, decisions, roles, history, unresolved, review view.

Offline: tmp databases only. Never touches data/hakiscribe.db or the
real storage/ folders.
"""

import sqlite3
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import backend.core.config as config
from backend.core.errors import EditConflictError
from backend.repositories import corrections_repo, flags_repo, segments_repo
from backend.repositories import review_events_repo
from backend.services import ingestion_service
from backend.services.ingestion_service import validate_and_store_upload
from backend.services.review_service import (
    assign_speaker_role,
    decide_flag,
    edit_segment,
    get_segment_history,
    get_speaker_roles,
    get_unresolved,
)
from database.db import get_connection
from database.schema import SCHEMA_SQL, SCHEMA_VERSION, init_db
from frontend.views import transcribe_view

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "frontend" / "app.py"

_SEGMENTS = [
    ("Speaker A", "A", 0.0, 4.0, "Court is now in session."),
    ("Speaker B", "B", 4.0, 9.0, "The accused was was present."),
    ("Speaker A", "A", 9.0, 14.0, "We adjourn until Friday."),
]


def _review_setup(tmp_path):
    """Recording + 3 segments + a text flag and a role flag; return ids."""
    recording = validate_and_store_upload(
        "hearing.mp3",
        b"synthetic-audio",
        "Reviewer Amina",
        upload_dir=tmp_path / "uploads",
        db_path=tmp_path / "t.db",
    )
    db = tmp_path / "t.db"
    segments_repo.create_segments(
        recording["id"],
        [
            {
                "idx": idx,
                "start_sec": start,
                "end_sec": end,
                "speaker": speaker,
                "speaker_label": label,
                "text_original": text,
            }
            for idx, (speaker, label, start, end, text) in enumerate(_SEGMENTS)
        ],
        db_path=db,
    )
    segments = {
        segment["idx"]: segment
        for segment in segments_repo.list_segments(recording["id"], db_path=db)
    }
    text_flag = flags_repo.create_flag(
        segments[1]["id"],
        "REPETITION_OR_DISFLUENCY",
        "LOW",
        "Repeated word; confirm.",
        evidence="was was",
        suggestion="was",
        db_path=db,
    )
    role_flag = flags_repo.create_flag(
        segments[0]["id"],
        "SPEAKER_ATTRIBUTION",
        "LOW",
        "Sounds like the chair.",
        evidence="Court is now in session.",
        suggestion="MAGISTRATE",
        db_path=db,
    )
    return {
        "recording_id": recording["id"],
        "db": db,
        "segments": segments,
        "text_flag": text_flag,
        "role_flag": role_flag,
    }


def _visible_text(app: AppTest) -> str:
    chunks = []
    for name in ("markdown", "caption", "info", "success", "warning", "text"):
        try:
            items = list(getattr(app, name))
        except Exception:
            continue
        for element in items:
            try:
                chunks.append(str(element.value))
            except Exception:
                pass
    return "\n".join(chunks)


def test_edit_writes_one_correction_and_updates_only_current(tmp_path):
    ctx = _review_setup(tmp_path)
    db, seg = ctx["db"], ctx["segments"][1]
    before_row = segments_repo.get_segment(seg["id"], db_path=db)
    result = edit_segment(
        seg["id"],
        "The accused was present.",
        "Reviewer Amina",
        "Confirmed from audio.",
        seg["text_current"],
        db_path=db,
    )
    history = get_segment_history(seg["id"], db_path=db)
    assert len(history) == 1
    assert history[0]["id"] == result["correction_id"]
    assert history[0]["decision"] == "EDIT_TEXT"
    assert history[0]["field"] == "text"
    assert history[0]["before_text"] == "The accused was was present."
    assert history[0]["after_text"] == "The accused was present."
    after_row = segments_repo.get_segment(seg["id"], db_path=db)
    for key, value in before_row.items():
        if key in ("text_current", "updated_at"):
            continue
        assert after_row[key] == value, key
    assert after_row["text_original"] == "The accused was was present."
    assert after_row["text_current"] == "The accused was present."


def test_text_original_trigger_still_blocks(tmp_path):
    ctx = _review_setup(tmp_path)
    conn = get_connection(ctx["db"])
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE segments SET text_original = 'rewritten' WHERE id = ?",
                (ctx["segments"][0]["id"],),
            )
    finally:
        conn.close()


def test_failure_midway_leaves_no_partial_state(tmp_path, monkeypatch):
    ctx = _review_setup(tmp_path)
    db, seg = ctx["db"], ctx["segments"][1]

    def boom(*args, **kwargs):
        raise RuntimeError("second write failed")

    monkeypatch.setattr(
        "backend.repositories.corrections_repo._insert_correction_row", boom
    )
    with pytest.raises(RuntimeError, match="second write failed"):
        edit_segment(
            seg["id"],
            "The accused was present.",
            "Reviewer Amina",
            "Confirmed from audio.",
            seg["text_current"],
            db_path=db,
        )
    assert (
        segments_repo.get_segment(seg["id"], db_path=db)["text_current"]
        == "The accused was was present."
    )
    assert get_segment_history(seg["id"], db_path=db) == []


def test_accept_suggestion_applies_text_and_resolves_atomically(
    tmp_path, monkeypatch
):
    ctx = _review_setup(tmp_path)
    db = ctx["db"]
    result = decide_flag(
        ctx["text_flag"], "ACCEPT_SUGGESTION", "Reviewer Amina", None,
        db_path=db,
    )
    assert result["status"] == "RESOLVED"
    segment = segments_repo.get_segment(ctx["segments"][1]["id"], db_path=db)
    assert segment["text_current"] == "The accused was present."
    assert segment["text_original"] == "The accused was was present."
    history = get_segment_history(ctx["segments"][1]["id"], db_path=db)
    assert len(history) == 1
    assert history[0]["decision"] == "ACCEPT_SUGGESTION"
    assert history[0]["before_text"] == "The accused was was present."
    assert history[0]["after_text"] == "The accused was present."
    assert flags_repo.get_flag(ctx["text_flag"], db_path=db)["status"] == "RESOLVED"

    def boom(*args, **kwargs):
        raise RuntimeError("flag write failed")

    monkeypatch.setattr(
        "backend.repositories.corrections_repo._set_flag_decided", boom
    )
    other = flags_repo.create_flag(
        ctx["segments"][2]["id"],
        "UNCLEAR_PASSAGE",
        "LOW",
        "Mumbly ending.",
        evidence="until Friday.",
        suggestion="until Friday morning.",
        db_path=db,
    )
    with pytest.raises(RuntimeError, match="flag write failed"):
        decide_flag(other, "ACCEPT_SUGGESTION", "Reviewer Amina", None, db_path=db)
    assert (
        segments_repo.get_segment(ctx["segments"][2]["id"], db_path=db)[
            "text_current"
        ]
        == "We adjourn until Friday."
    )
    assert get_segment_history(ctx["segments"][2]["id"], db_path=db) == []
    assert flags_repo.get_flag(other, db_path=db)["status"] == "OPEN"


def test_accept_role_suggestion_assigns_role(tmp_path):
    ctx = _review_setup(tmp_path)
    db = ctx["db"]
    result = decide_flag(
        ctx["role_flag"], "ACCEPT_SUGGESTION", "Reviewer Amina", None, db_path=db
    )
    assert result["status"] == "RESOLVED"
    assert get_speaker_roles(ctx["recording_id"], db_path=db) == {
        "A": "MAGISTRATE"
    }
    history = get_segment_history(ctx["segments"][0]["id"], db_path=db)
    assert len(history) == 1
    assert history[0]["decision"] == "ACCEPT_SUGGESTION"
    assert history[0]["field"] == "speaker_role"
    assert history[0]["before_text"] == ""
    assert history[0]["after_text"] == "MAGISTRATE"


def test_dismiss_without_reason_rejected(tmp_path):
    ctx = _review_setup(tmp_path)
    db = ctx["db"]
    with pytest.raises(ValueError, match="reason is required"):
        decide_flag(ctx["text_flag"], "DISMISS_FLAG", "Reviewer Amina", None,
                    db_path=db)
    with pytest.raises(ValueError, match="reason is required"):
        decide_flag(ctx["text_flag"], "DISMISS_FLAG", "Reviewer Amina", "  ",
                    db_path=db)
    assert flags_repo.get_flag(ctx["text_flag"], db_path=db)["status"] == "OPEN"
    assert get_segment_history(ctx["segments"][1]["id"], db_path=db) == []
    decide_flag(
        ctx["text_flag"], "DISMISS_FLAG", "Reviewer Amina", "False alarm.",
        db_path=db,
    )
    assert flags_repo.get_flag(ctx["text_flag"], db_path=db)["status"] == "DISMISSED"
    with pytest.raises(ValueError, match="reason is required"):
        corrections_repo.create_correction(
            ctx["segments"][1]["id"], None, "a", "b", "Reviewer Amina",
            "RETAIN_UNCERTAIN", db_path=db,
        )


def test_stale_edit_rejected_with_conflict(tmp_path):
    ctx = _review_setup(tmp_path)
    db, seg = ctx["db"], ctx["segments"][0]
    with pytest.raises(EditConflictError) as exc_info:
        edit_segment(
            seg["id"],
            "Court is now in session, please.",
            "Reviewer Amina",
            "Heard more.",
            "stale text the reviewer saw",
            db_path=db,
        )
    assert exc_info.value.code == "edit_conflict"
    assert (
        segments_repo.get_segment(seg["id"], db_path=db)["text_current"]
        == "Court is now in session."
    )
    assert get_segment_history(seg["id"], db_path=db) == []


def test_noop_empty_and_anonymous_edits_rejected(tmp_path):
    ctx = _review_setup(tmp_path)
    db, seg = ctx["db"], ctx["segments"][0]
    with pytest.raises(ValueError, match="identical"):
        edit_segment(
            seg["id"], seg["text_current"], "Reviewer Amina", "No change.",
            seg["text_current"], db_path=db,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        edit_segment(
            seg["id"], "   ", "Reviewer Amina", "Empty.", seg["text_current"],
            db_path=db,
        )
    with pytest.raises(ValueError, match="reviewer_name is required"):
        edit_segment(
            seg["id"], "New text.", "  ", "Nobody.", seg["text_current"],
            db_path=db,
        )
    with pytest.raises(ValueError, match="reason is required"):
        edit_segment(
            seg["id"], "New text.", "Reviewer Amina", None, seg["text_current"],
            db_path=db,
        )
    with pytest.raises(ValueError, match="segment not found"):
        edit_segment(
            999999, "New text.", "Reviewer Amina", "Why.", "seen", db_path=db
        )
    assert (
        segments_repo.get_segment(seg["id"], db_path=db)["text_current"]
        == "Court is now in session."
    )
    assert get_segment_history(seg["id"], db_path=db) == []


def test_role_assignment_taxonomy_and_label_scope(tmp_path):
    ctx = _review_setup(tmp_path)
    db, recording_id = ctx["db"], ctx["recording_id"]
    result = assign_speaker_role(
        recording_id, "A", "magistrate", "Reviewer Amina", "Opens the court.",
        db_path=db,
    )
    assert result["role"] == "MAGISTRATE"
    assert result["before_role"] == ""
    assert result["after_role"] == "MAGISTRATE"
    assign_speaker_role(
        recording_id, "B", "PROSECUTOR", "Reviewer Amina", "Presents the case.",
        db_path=db,
    )
    roles = get_speaker_roles(recording_id, db_path=db)
    assert roles == {"A": "MAGISTRATE", "B": "PROSECUTOR"}
    assert ctx["segments"][0]["speaker_label"] == "A"
    assert ctx["segments"][2]["speaker_label"] == "A"
    history = get_segment_history(ctx["segments"][0]["id"], db_path=db)
    assert len(history) == 1
    assert history[0]["decision"] == "ASSIGN_SPEAKER_ROLE"
    assert history[0]["field"] == "speaker_role"
    with pytest.raises(ValueError, match="locked speaker taxonomy"):
        assign_speaker_role(
            recording_id, "A", "POPE", "Reviewer Amina", "Nope.", db_path=db
        )
    with pytest.raises(ValueError, match="unknown speaker label"):
        assign_speaker_role(
            recording_id, "Z", "MAGISTRATE", "Reviewer Amina", "Nope.",
            db_path=db,
        )


def test_unresolved_contains_open_and_retained_only(tmp_path):
    ctx = _review_setup(tmp_path)
    db, recording_id = ctx["db"], ctx["recording_id"]
    extra = flags_repo.create_flag(
        ctx["segments"][2]["id"], "UNCLEAR_PASSAGE", "HIGH", "Mumbly.",
        evidence="until Friday.", db_path=db,
    )
    decide_flag(
        extra, "RETAIN_UNCERTAIN", "Reviewer Amina", "Still unsure.", db_path=db
    )
    decide_flag(
        ctx["role_flag"], "DISMISS_FLAG", "Reviewer Amina", "False alarm.",
        db_path=db,
    )
    unresolved = get_unresolved(recording_id, db_path=db)
    assert {flag["status"] for flag in unresolved} == {"OPEN", "RETAINED"}
    assert {flag["id"] for flag in unresolved} == {extra, ctx["text_flag"]}
    by_id = {flag["id"]: flag for flag in unresolved}
    assert by_id[extra]["segment_idx"] == 2
    assert by_id[extra]["start_sec"] == 9.0
    assert by_id[extra]["end_sec"] == 14.0
    assert by_id[extra]["message"] == "Mumbly."
    assert flags_repo.update_flag_status(
        ctx["text_flag"], "RETAINED", resolved_by="Reviewer Amina", db_path=db
    )
    assert {
        flag["status"] for flag in get_unresolved(recording_id, db_path=db)
    } == {"RETAINED"}


def test_history_order_and_fields(tmp_path):
    ctx = _review_setup(tmp_path)
    db, seg = ctx["db"], ctx["segments"][0]
    edit_segment(
        seg["id"], "Court is now in session today.", "Reviewer Amina",
        "Heard the last word.", seg["text_current"], db_path=db,
    )
    edit_segment(
        seg["id"], "Court is now in session today!", "Reviewer B",
        "Emphasis heard.", "Court is now in session today.", db_path=db,
    )
    history = get_segment_history(seg["id"], db_path=db)
    assert [entry["reviewer_name"] for entry in history] == [
        "Reviewer Amina",
        "Reviewer B",
    ]
    assert history[0]["before_text"] == "Court is now in session."
    assert history[0]["after_text"] == "Court is now in session today."
    assert history[1]["before_text"] == history[0]["after_text"]
    assert history[1]["reason"] == "Emphasis heard."
    assert history[1]["decision"] == "EDIT_TEXT"
    assert history[1]["field"] == "text"
    assert history[0]["created_at"] and history[1]["created_at"]
    assert [entry["id"] for entry in history] == sorted(
        entry["id"] for entry in history
    )


def test_migration_adds_review_structures(tmp_path):
    db = tmp_path / "old.db"
    conn = get_connection(db)
    try:
        conn.executescript(SCHEMA_SQL)
        cur = conn.execute(
            """INSERT INTO recordings
               (filename, stored_path, sha256, size_bytes, uploaded_by)
               VALUES (?, ?, ?, ?, ?)""",
            ("old.mp3", "storage/uploads/old.mp3", "old-sha", 64, "Reviewer Amina"),
        )
        rec_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO segments
               (recording_id, idx, start_sec, end_sec, speaker, text_original,
                text_current)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rec_id, 0, 0.0, 1.0, "MAGISTRATE", "Kept.", "Kept."),
        )
        conn.execute(
            """INSERT INTO corrections
               (segment_id, before_text, after_text, reviewer_name,
                decision, reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cur.lastrowid, "Kept.", "Kept!", "Reviewer Amina", "EDIT_TEXT", "Why."),
        )
        conn.commit()
    finally:
        conn.close()
    init_db(db)
    conn = get_connection(db)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        row = conn.execute("SELECT * FROM corrections").fetchone()
        assert row["field"] == "text"
        assert row["reason"] == "Why."
        (roles,) = conn.execute("SELECT COUNT(*) FROM speaker_roles").fetchone()
        (events,) = conn.execute("SELECT COUNT(*) FROM review_events").fetchone()
        assert roles == 0
        assert events == 0
    finally:
        conn.close()


def test_apptest_select_edit_save_history_and_audio(tmp_path, monkeypatch):
    db_path = tmp_path / "hakiscribe.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("HAKISCRIBE_DB_PATH", str(db_path))
    monkeypatch.setenv("HAKISCRIBE_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(config, "is_configured", lambda: False)
    demo_wav = tmp_path / "demo.wav"
    demo_wav.write_bytes(b"synthetic-demo-audio")
    monkeypatch.setattr(ingestion_service, "DEMO_RECORDING_PATH", demo_wav)
    monkeypatch.setattr(transcribe_view, "is_configured", lambda: False)

    audio_calls = []
    real_audio = st.audio

    def spy_audio(*args, **kwargs):
        audio_calls.append((args, kwargs))
        return real_audio(*args, **kwargs)

    monkeypatch.setattr(st, "audio", spy_audio)

    app = AppTest.from_file(str(APP_PATH))
    app.run()
    assert not app.exception
    app.text_input(key="reviewer_name").set_value("Reviewer Amina")
    app.run()
    app.button(key="load_demo_recording").click()
    app.run()
    app.button(key="transcribe_recording").click()
    app.run()
    app.run()
    assert not app.exception

    recording_id = app.session_state["recording_id"]
    segments = {
        segment["idx"]: segment
        for segment in segments_repo.list_segments(recording_id, db_path=db_path)
    }
    target = segments[1]
    assert (target["start_sec"], target["end_sec"]) == (4.5, 8.1)

    app.session_state["current_step"] = "review"
    app.run()
    assert not app.exception
    app.button(key=f"review_segment_{target['id']}").click()
    app.run()
    assert not app.exception
    assert app.session_state["selected_segment_idx"] == 1

    app.text_area(key=f"review_edit_{target['id']}").set_value(
        "Mheshimiwa, mlalamikaji yupo kotini leo asubuhi."
    )
    app.text_input(key=f"review_edit_reason_{target['id']}").set_value(
        "Confirmed from audio."
    )
    app.button(key=f"review_save_{target['id']}").click()
    app.run()
    app.run()
    assert not app.exception

    blob = _visible_text(app)
    assert "Reviewer Amina" in blob
    assert "Confirmed from audio." in blob
    assert "edited" in blob
    assert any(
        kwargs.get("start_time") == 4 and kwargs.get("end_time") == 8
        for _args, kwargs in audio_calls
    ), audio_calls

    events = review_events_repo.list_events_by_recording(
        recording_id, db_path=db_path
    )
    assert [event["event"] for event in events] == ["review_opened", "edit"]
    assert all(event["reviewer"] == "Reviewer Amina" for event in events)
