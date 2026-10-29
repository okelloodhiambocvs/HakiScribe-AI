"""Sidebar API-evidence expander: latest call per Meta category."""

import streamlit as st

from backend.services import workflow_service
from frontend.components.errors import show_error


def render_api_evidence() -> None:
    """Render the collapsed sidebar evidence expander; never raises."""
    with st.sidebar.expander("API evidence", expanded=False):
        try:
            calls = workflow_service.list_recent_api_calls(50)
        except Exception as exc:
            show_error(exc)
            return
        groups = [
            ("Voice batch", "/asr/transcribe"),
            ("Voice realtime", "/asr/realtime"),
            ("Spark", None),
        ]
        for label, path in groups:
            if path is None:
                match = next(
                    (
                        call
                        for call in calls
                        if call["endpoint_path"]
                        not in ("/asr/transcribe", "/asr/realtime")
                    ),
                    None,
                )
            else:
                match = next(
                    (call for call in calls if call["endpoint_path"] == path),
                    None,
                )
            if match is None:
                st.write(f"{label}: no calls yet.")
            else:
                if match["http_status"] is not None:
                    status = f"HTTP {match['http_status']}"
                else:
                    status = match["error_code"] or "?"
                if match["latency_ms"] is not None:
                    latency = f"{match['latency_ms']:.0f} ms"
                else:
                    latency = "n/a"
                st.write(
                    f"{label}: {match['model']} · {match['mode']} · "
                    f"{status} · {latency} · {match['created_at']}"
                )
        st.caption(
            "Full evidence: docs/API-EVIDENCE.md "
            "via scripts/generate_api_evidence.py."
        )
