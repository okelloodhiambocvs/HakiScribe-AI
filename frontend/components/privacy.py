"""Privacy notice shared by upload and live capture."""

import streamlit as st

PRIVACY_NOTICE = (
    "Audio is sent to the Meta Model API for processing. "
    "Use only synthetic or consented recordings. No real case material."
)


def render_privacy_notice() -> None:
    """Show the pre-capture privacy notice."""
    st.info(PRIVACY_NOTICE)
