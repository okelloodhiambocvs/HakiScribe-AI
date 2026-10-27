import requests
from src.utils.config import META_API_KEY, META_REASONING_MODEL, get_api_base, is_configured

SYSTEM_PROMPT = """You are a Kenyan court clerk assistant.
Diarize into MAGISTRATE, CLERK, PROSECUTION, ACCUSED, WITNESS.
Do NOT paraphrase legal pleas. Do NOT invent facts.
If unsure, flag [VERIFY] and require human review.
Return structured JSON only."""

def call_muse_spark(prompt: str, force_mock: bool = False) -> dict:
    """
    LOCKED: Muse Spark via Meta Model API.
    Mock = no key / offline. Real = POST to Meta.
    """
    if force_mock or not is_configured():
        return {
            "model": "muse-spark-mock",
            "status": "mock-no-key",
            "needs_human_review": True,
            "certified": False,
        }

    base = get_api_base()
    url = f"{base}/{META_REASONING_MODEL}/chat"
    headers = {"Authorization": f"Bearer {META_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return {
        "model": META_REASONING_MODEL,
        "status": "real",
        "raw": data,
        "needs_human_review": True,
        "certified": False,
    }