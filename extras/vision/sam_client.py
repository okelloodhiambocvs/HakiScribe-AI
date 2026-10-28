import requests
from backend.core.config import META_API_KEY, META_SAM_MODEL, get_api_base, is_configured

MOCK_SEGMENTS = [
    {"label": "STAMP", "box": [10, 10, 120, 60], "confidence": 0.94, "sensitive": False, "action": "KEEP_VISIBLE"},
    {"label": "HANDWRITTEN_DATE", "box": [130, 15, 260, 45], "confidence": 0.88, "sensitive": False, "action": "KEEP_VISIBLE"},
    {"label": "SIGNATURE", "box": [20, 420, 180, 470], "confidence": 0.91, "sensitive": True, "action": "MASK_FOR_PUBLIC_COPY"},
    {"label": "ID_NUMBER", "box": [200, 420, 340, 460], "confidence": 0.89, "sensitive": True, "action": "MASK_FOR_PUBLIC_COPY"},
]

def call_sam_segment(image_path: str, force_mock: bool = False) -> dict:
    """
    LOCKED: SAM 3.1 via Meta Model API.
    Mock = no key / offline. Real = POST to Meta.
    Update URL to match YOUR dev.meta.ai portal docs for SAM 3.1.
    """
    if force_mock or not is_configured():
        return {
            "model": "sam-3.1-mock",
            "status": "mock-no-key",
            "segments": [dict(s) for s in MOCK_SEGMENTS],
            "needs_human_review": True,
            "approved": False,
        }

    base = get_api_base()
    url = f"{base}/{META_SAM_MODEL}/segment"
    headers = {"Authorization": f"Bearer {META_API_KEY}"}
    with open(image_path, "rb") as f:
        files = {"image": f}
        data = {"prompts": "STAMP,HANDWRITTEN_DATE,SIGNATURE,ID_NUMBER"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    r.raise_for_status()
    data = r.json()
    return {
        "model": META_SAM_MODEL,
        "status": "real",
        "raw": data,
        "segments": data.get("segments", []),
        "needs_human_review": True,
        "approved": False,
    }