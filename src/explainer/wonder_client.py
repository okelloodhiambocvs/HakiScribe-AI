import requests
from src.utils.config import META_API_KEY, META_WONDER_MODEL, get_api_base, is_configured

def call_muse_wonder(prompt: str, force_mock: bool = False) -> dict:
    """
    LOCKED: Muse Wonder via Meta Model API.
    Mock = no key / offline. Real = POST to Meta.
    Update URL to match YOUR dev.meta.ai portal docs for Muse Wonder.
    """
    if force_mock or not is_configured():
        return {
            "model": "muse-wonder-mock",
            "status": "mock-no-key",
            "needs_human_review": True,
            "approved": False,
        }

    base = get_api_base()
    url = f"{base}/{META_WONDER_MODEL}/generate"
    headers = {"Authorization": f"Bearer {META_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "style": "plain-language, empathetic, Kenyan citizen explainer, English and Kiswahili, grade 6 reading level",
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return {
        "model": META_WONDER_MODEL,
        "status": "real",
        "raw": data,
        "needs_human_review": True,
        "approved": False,
    }