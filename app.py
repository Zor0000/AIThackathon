"""Groundtruth: review preparation with traceable claim checks."""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv


load_dotenv()
Path("data").mkdir(exist_ok=True)

st.set_page_config(page_title="Groundtruth", page_icon="✓", layout="wide")
st.title("Groundtruth")
st.caption("Check the claim. Understand the context. Then draft.")

mode = os.getenv("SOURCE_MODE", "fixture")
st.info(f"Starter environment is ready. Source mode: **{mode}**.")
st.write(
    "Next: add the review setup form, fixture records, and the claim-check workflow. "
    "Keep live integrations off until their read-only credentials are configured."
)
