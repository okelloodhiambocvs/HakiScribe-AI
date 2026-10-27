import streamlit as st

st.set_page_config(page_title="HakiScribe-AI", layout="wide")
st.title("HakiScribe-AI — Clarity in Every Proceeding")
st.info("RULE: AI proposes. HUMAN disposes. No transcript is final until a Clerk verifies and a Magistrate certifies.")

st.subheader("Human-in-the-Loop Status")
col1, col2, col3 = st.columns(3)
col1.metric("AI Draft", "v1 - pending")
col2.metric("Clerk Review", "NOT DONE")
col3.metric("Magistrate Certify", "BLOCKED")

st.write("Step 2 OK - skeleton running. Meta API integration comes in Step 3-4.")