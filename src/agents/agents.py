import re
from datetime import date, timedelta
from src.agents.spark_client import call_muse_spark

CONFIDENCE_THRESHOLD = 0.75

def structure_transcript(segments: list[dict], force_mock: bool = False) -> dict:
    spark = call_muse_spark("Structure Kenyan court transcript", force_mock=force_mock)
    full_text = " ".join(s.get("text", "") for s in segments)
    m = re.search(r"(CR\s*\d+\s*(?:of|/)\s*\d+)", full_text, re.IGNORECASE)
    case_number = m.group(1).upper() if m else "UNKNOWN - HUMAN TO CONFIRM"

    structured = []
    for s in segments:
        raw_speaker = (s.get("speaker") or "UNKNOWN").replace("?", "").strip().upper()
        conf = float(s.get("confidence", 0))
        structured.append({
            "start": s.get("start"), "end": s.get("end"),
            "speaker": raw_speaker,
            "speaker_uncertain": (str(s.get("speaker", "")).endswith("?") or raw_speaker == "UNKNOWN"),
            "text": s.get("text", ""),
            "confidence": conf,
            "needs_verify": conf < CONFIDENCE_THRESHOLD,
        })

    return {
        "case_number": case_number,
        "structured_segments": structured,
        "spark_status": spark.get("status"),
        "needs_human_review": True,
        "certified": False,
    }

def guardian_check(structured_result: dict) -> dict:
    flags = []
    for i, s in enumerate(structured_result.get("structured_segments", [])):
        if s.get("confidence", 0) < CONFIDENCE_THRESHOLD:
            flags.append({"segment_index": i, "type": "LOW_CONFIDENCE", "message": f"Confidence {s['confidence']} < 0.75 - Clerk MUST replay audio", "requires_human": True})
        if s.get("speaker_uncertain"):
            flags.append({"segment_index": i, "type": "SPEAKER_UNCERTAIN", "message": "AI guessed speaker - Clerk MUST confirm role", "requires_human": True})
    return {"flags": flags, "flag_count": len(flags), "needs_human_review": True, "certified": False}

def calculate_deadlines(judgment_date_str: str) -> dict:
    d = date.fromisoformat(judgment_date_str)
    return {
        "judgment_date": d.isoformat(),
        "notice_of_appeal_due": (d + timedelta(days=14)).isoformat(),
        "record_of_appeal_due": (d + timedelta(days=60)).isoformat(),
        "note": "AI suggestion only - Clerk/Magistrate MUST confirm applicable timelines",
        "requires_human_confirmation": True,
        "certified": False,
    }

def run_all_agents(segments: list[dict], judgment_date_str: str | None = None, force_mock: bool = False) -> dict:
    structured = structure_transcript(segments, force_mock=force_mock)
    guardian = guardian_check(structured)
    deadline = calculate_deadlines(judgment_date_str) if judgment_date_str else None
    return {
        "structured": structured,
        "guardian": guardian,
        "deadline": deadline,
        "agent_trace": [
            f"Structurer: case={structured['case_number']}",
            f"Guardian: {guardian['flag_count']} flags for HUMAN",
            f"Deadline: {'calculated - needs human confirm' if deadline else 'no judgment date'}",
        ],
        "needs_human_review": True,
        "certified": False,
    }