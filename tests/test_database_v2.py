"""V2 database layer tests: schema plus all five repositories.

Every test uses an isolated tmp_path SQLite file. data/hakiscribe.db is
never touched here.
"""

from backend.repositories import corrections_repo, exports_repo, flags_repo
from backend.repositories import recordings_repo, segments_repo
from database.db import get_connection
from database.schema import init_db


def _recording(db):
    return recordings_repo.create_recording(
        filename="cr-123-synthetic.mp3",
        stored_path="storage/uploads/cr-123-synthetic.mp3",
        sha256="synthetic-sha",
        size_bytes=1024,
        duration_sec=120.0,
        uploaded_by="Reviewer Amina",
        db_path=db,
    )


def test_init_db_creates_all_tables(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    conn = get_connection(db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert {"recordings", "segments", "flags", "corrections", "exports"} <= tables


def test_recording_and_segments_preserve_original_after_edit(tmp_path):
    db = tmp_path / "t.db"
    rec_id = _recording(db)
    original = "Mheshimiwa, nilifika nyumbani saa mbili, and then I saw the accused."
    seg_id = segments_repo.create_segment(
        rec_id, 0, 0.0, 9.5, "WITNESS_PW1", 0.61, original,
        language="mixed", db_path=db,
    )
    corrected = (
        "Mheshimiwa, nilifika nyumbani saa mbili, "
        "and then I saw the accused person."
    )
    assert segments_repo.update_segment_current_text(seg_id, corrected, db_path=db)
    seg = segments_repo.get_segment(seg_id, db_path=db)
    assert seg["text_current"] == corrected
    assert seg["text_current"] != original
    assert seg["text_original"] == original


def test_flag_lifecycle_open_to_resolved(tmp_path):
    db = tmp_path / "t.db"
    rec_id = _recording(db)
    seg_id = segments_repo.create_segment(
        rec_id, 0, 0.0, 4.2, "MAGISTRATE", 0.5, "Court in session.", db_path=db
    )
    flag_id = flags_repo.create_flag(
        seg_id, "LOW_CONFIDENCE", "HIGH", "Confidence 0.5 < 0.75",
        created_by_model="muse-spark", db_path=db,
    )
    assert flag_id in [f["id"] for f in flags_repo.list_open_flags(db_path=db)]
    assert flags_repo.update_flag_status(
        flag_id, "RESOLVED", resolved_by="Reviewer Amina",
        resolution_note="Replayed audio", db_path=db,
    )
    flag = flags_repo.get_flag(flag_id, db_path=db)
    assert flag["status"] == "RESOLVED"
    assert flag["resolved_by"] == "Reviewer Amina"
    assert flag["resolved_at"] is not None
    assert flag_id not in [f["id"] for f in flags_repo.list_open_flags(db_path=db)]


def test_correction_records_reviewer_before_after_and_time(tmp_path):
    db = tmp_path / "t.db"
    rec_id = _recording(db)
    seg_id = segments_repo.create_segment(
        rec_id, 0, 0.0, 4.2, "ACCUSED", 0.6, "Sikuwa hapo.", db_path=db
    )
    flag_id = flags_repo.create_flag(
        seg_id, "SPEAKER_UNCERTAIN", "MEDIUM", "Speaker guessed", db_path=db
    )
    before = "Sikuwa hapo."
    after = "Si kweli, sikuwa hapo tarehe kumi na mbili."
    corr_id = corrections_repo.create_correction(
        seg_id, flag_id, before, after, "Reviewer Amina", "EDIT_TEXT",
        reason="Confirmed speaker wording from audio", db_path=db,
    )
    rows = corrections_repo.list_corrections_by_segment(seg_id, db_path=db)
    assert len(rows) == 1
    corr = rows[0]
    assert corr["id"] == corr_id
    assert corr["reviewer_name"] == "Reviewer Amina"
    assert corr["decision"] == "EDIT_TEXT"
    assert corr["before_text"] == before
    assert corr["after_text"] == after
    assert corr["reason"] == "Confirmed speaker wording from audio"
    assert corr["created_at"]


def test_export_metrics_are_stored(tmp_path):
    db = tmp_path / "t.db"
    rec_id = _recording(db)
    exp_id = exports_repo.create_export(
        rec_id, "CR-123-2026_DRAFT.docx", 0.12, 0.05, 25.0, 4, 3,
        "Reviewer Amina", db_path=db,
    )
    rows = exports_repo.list_exports_by_recording(rec_id, db_path=db)
    assert len(rows) == 1
    exp = rows[0]
    assert exp["id"] == exp_id
    assert exp["wer"] == 0.12
    assert exp["cer"] == 0.05
    assert exp["segments_changed_pct"] == 25.0
    assert exp["flags_total"] == 4
    assert exp["flags_resolved"] == 3
    assert exp["generated_by"] == "Reviewer Amina"


def test_segments_keep_mixed_language_and_kenyan_speakers(tmp_path):
    db = tmp_path / "t.db"
    rec_id = _recording(db)
    lines = [
        ("MAGISTRATE", "Case CR 123 of 2026, tunaendelea."),
        ("PROSECUTOR", "Mheshimiwa, mlalamikaji yupo kotini leo."),
        ("ACCUSED", "Si kweli, I was not there that night."),
        ("COMPLAINANT", "Nilikuwa nyumbani saa mbili usiku."),
        ("WITNESS_PW1", "Nalimwona, he was running towards the gate."),
    ]
    segments_repo.create_segments(
        rec_id,
        [
            {
                "idx": i,
                "start_sec": float(i * 10),
                "end_sec": float(i * 10 + 8),
                "speaker": speaker,
                "confidence": 0.9,
                "text_original": text,
            }
            for i, (speaker, text) in enumerate(lines)
        ],
        db_path=db,
    )
    rows = segments_repo.list_segments(rec_id, db_path=db)
    assert [(row["speaker"], row["text_original"]) for row in rows] == lines
    assert [row["idx"] for row in rows] == [0, 1, 2, 3, 4]
