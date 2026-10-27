import streamlit as st
from src.transcription.client import transcribe_audio
from src.agents.agents import run_all_agents
from src.verification.service import (
    create_review_session, clerk_review_segment,
    can_clerk_complete, clerk_complete_review, magistrate_certify
)

st.set_page_config(page_title="HakiScribe-AI", layout="wide")
st.title("HakiScribe-AI — Clarity in Every Proceeding")
st.info("RULE: AI proposes. HUMAN disposes. No transcript is final until a Clerk verifies and a Magistrate certifies.")

if "session" not in st.session_state:
    st.session_state["session"] = None

st.subheader("Human-in-the-Loop Status")
session = st.session_state["session"]
col1, col2, col3 = st.columns(3)
col1.metric("AI Draft", "v1 - pending" if session is None else session["status"])
col2.metric("Clerk Review", "NOT DONE" if session is None or session["status"] == "AI_DRAFT" else session["status"])
col3.metric("Magistrate Certify", "BLOCKED" if session is None or not session.get("certified") else "CERTIFIED")

st.write("Step 5: Human verification. Load synthetic demo, Clerk reviews each flag, Magistrate certifies.")

clerk_name = st.text_input("Clerk name (HUMAN 1)", value="")
magistrate_name = st.text_input("Magistrate name (HUMAN 2 - must be different)", value="")

if st.button("Load Synthetic Demo CR 123/2026"):
    segs = transcribe_audio("demo-data/synthetic/cr-123-mock.mp3", force_mock=True)["segments"]
    agent_out = run_all_agents(segs, judgment_date_str="2026-10-27", force_mock=True)
    st.session_state["session"] = create_review_session(agent_out)
    st.success("AI Draft created. NOT certified. Clerk must review.")

session = st.session_state["session"]

if session is not None:
    st.subheader(f"Case: {session['case_number']}")
    st.write(session["agent_trace"])

    if session.get("deadline"):
        st.warning(f"Deadline suggestion only - HUMAN must confirm: Notice {session['deadline']['notice_of_appeal_due']}, Record {session['deadline']['record_of_appeal_due']}")

    for i, seg in enumerate(session["segments"]):
        st.write(f"Segment {i} | {seg['speaker']} | Confidence: {seg['confidence']} | Status: {seg['review_status']}")
        edited = st.text_area(f"Transcript segment {i}", value=seg["clerk_text"], key=f"text_{i}")
        if st.button(f"Clerk Confirm Segment {i}", key=f"confirm_{i}"):
            try:
                clerk_review_segment(session, i, clerk_name, edited_text=edited, confirmed_speaker=seg["speaker"])
                st.success(f"Segment {i} reviewed by {clerk_name}")
            except Exception as e:
                st.error(str(e))

    ok, pending = can_clerk_complete(session)
    st.write(f"Can Clerk complete? {ok} Pending: {pending}")

    if st.button("Clerk Complete Review"):
        try:
            clerk_complete_review(session, clerk_name)
            st.success("Clerk review complete. Now Magistrate can certify.")
        except Exception as e:
            st.error(str(e))

    if st.button("Magistrate CERTIFY"):
        try:
            magistrate_certify(session, magistrate_name)
            st.success(f"CERTIFIED. Hash: {session['final_hash']}")
        except Exception as e:
            st.error(str(e))

    if session.get("certified"):
        st.subheader("Certified Final Transcript (SYNTHETIC)")
        st.write(session["final_text"])
        st.write(f"SHA256 Hash: {session['final_hash']}")

    st.subheader("Audit Log - Who did what")
    for entry in session["audit_log"]:
        st.write(entry)