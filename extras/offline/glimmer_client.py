import os
from pathlib import Path

def call_muse_glimmer_local(prompt: str, force_mock: bool = False) -> dict:
    """
    LOCKED: Muse Glimmer / Muse Spark Open - OPEN WEIGHTS, LOCAL ONLY.
    No Meta cloud API call here. Runs on court laptop.
    If GLIMMER_MODEL_PATH exists -> local weights ready.
    Else -> offline local fallback so demo/tests work with no internet / no GPU.
    """
    if force_mock:
        return {
            "model": "muse-glimmer-mock",
            "status": "mock-offline",
            "mode": "offline",
            "needs_human_review": True,
            "approved": False,
        }

    model_path = os.getenv("GLIMMER_MODEL_PATH", "")
    if model_path and Path(model_path).exists():
        return {
            "model": "muse-glimmer-open-weights",
            "status": "local-open-weights-ready",
            "mode": "offline",
            "model_path": model_path,
            "needs_human_review": True,
            "approved": False,
        }

    return {
        "model": "muse-glimmer-offline-fallback",
        "status": "offline-local-fallback",
        "mode": "offline",
        "needs_human_review": True,
        "approved": False,
    }