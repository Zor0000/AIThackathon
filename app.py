"""VeriSure: consent-led employment verification for an HR review workflow.

This MVP intentionally uses fixture employer replies. It does not send WhatsApp
messages or make hiring decisions; HR must review the resulting report.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv


load_dotenv()
Path("data").mkdir(exist_ok=True)
st.set_page_config(page_title="VeriSure", page_icon="✓", layout="wide")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def add_event(step: str, detail: str) -> None:
    st.session_state.events.append({"time": now(), "step": step, "detail": detail})


def valid_period(start_date: str, end_date: str) -> bool:
    try:
        start = datetime.strptime(start_date, "%Y-%m")
        end = datetime.strptime(end_date, "%Y-%m")
    except ValueError:
        return False
    return start <= end


def start_run(values: dict) -> None:
    values["request_id"] = f"VR-{uuid4().hex[:8].upper()}"
    st.session_state.run = values
    st.session_state.events = []
    st.session_state.response = None
    st.session_state.hr_decision = None
    add_event("REQUEST_CREATED", "HR submitted the claimed employment details.")
    add_event("CONSENT_RECORDED", "Candidate consent was confirmed before outreach.")
    add_event("OUTREACH_QUEUED", "Employer verification request is ready to send.")


def employer_reply(kind: str) -> dict:
    claim = st.session_state.run
    if kind == "match":
        facts = {
            "Employer": claim["company"],
            "Employment status": "Employed",
            "Job title": claim["title"],
            "Start date": claim["start_date"],
            "End date": claim["end_date"],
        }
        return {"kind": kind, "facts": facts, "note": "The employer confirmed the requested facts."}
    if kind == "title_mismatch":
        facts = {
            "Employer": claim["company"],
            "Employment status": "Employed",
            "Job title": "Software Engineer",
            "Start date": claim["start_date"],
            "End date": claim["end_date"],
        }
        return {"kind": kind, "facts": facts, "note": "The employer confirmed employment but reported a different title."}
    return {
        "kind": kind,
        "facts": {},
        "note": "The employer declined to share details or did not respond. This is not a negative finding.",
    }


def comparison_rows() -> list[dict]:
    claim = st.session_state.run
    reply = st.session_state.response
    if reply["kind"] == "unavailable":
        return [{"Field": "Employer response", "Claimed": "—", "Verified": "—", "Result": "Needs HR follow-up"}]
    expected = {
        "Employer": claim["company"],
        "Job title": claim["title"],
        "Start date": claim["start_date"],
        "End date": claim["end_date"],
    }
    rows = []
    for field, claimed in expected.items():
        verified = reply["facts"][field]
        rows.append({
            "Field": field,
            "Claimed": claimed,
            "Verified": verified,
            "Result": "Match" if claimed == verified else "Mismatch — clarify",
        })
    return rows


def report_status(rows: list[dict]) -> str:
    if st.session_state.response["kind"] == "unavailable":
        return "INCOMPLETE — employer response unavailable"
    if any(row["Result"].startswith("Mismatch") for row in rows):
        return "REVIEW REQUIRED — one or more claimed facts differ"
    return "VERIFIED — all requested facts match"


st.title("VeriSure")
st.caption("Verify employment facts with consent. Keep people in the decision loop.")
mode = os.getenv("SOURCE_MODE", "fixture")
st.info(f"Mode: **{mode.title()} fixture**. No real messages are sent from this starter.")

if "run" not in st.session_state:
    st.session_state.run = None
    st.session_state.events = []
    st.session_state.response = None
    st.session_state.hr_decision = None

left, right = st.columns([1, 1.35], gap="large")

with left:
    st.subheader("1. Create verification request")
    with st.form("verification_request"):
        candidate = st.text_input("Candidate name", value="Aarav Shah")
        candidate_email = st.text_input("Candidate email", value="aarav@example.test")
        company = st.text_input("Previous employer", value="Northstar Labs")
        verifier = st.text_input("Employer contact name", value="Riya Mehta")
        contact = st.text_input("Employer contact (WhatsApp/email)", value="+91 90000 00000")
        title = st.text_input("Claimed job title", value="Senior Software Engineer")
        start_date = st.text_input("Claimed start date", value="2022-01")
        end_date = st.text_input("Claimed end date", value="2024-03")
        consent = st.checkbox("I confirm the candidate has consented to this verification.")
        submitted = st.form_submit_button("Create verification request", type="primary")
    if submitted:
        if not all([candidate, candidate_email, company, verifier, contact, title, start_date, end_date]):
            st.error("Complete all request fields before creating the verification.")
        elif not consent:
            st.error("Candidate consent is required before any employer outreach.")
        elif not valid_period(start_date, end_date):
            st.error("Use YYYY-MM dates and ensure the start date is not after the end date.")
        else:
            start_run({
                "candidate": candidate, "candidate_email": candidate_email, "company": company,
                "verifier": verifier, "contact": contact, "title": title,
                "start_date": start_date, "end_date": end_date,
            })
            st.success("Request created. Choose a fixture reply to continue the demo.")

with right:
    st.subheader("2. Verify and review")
    if not st.session_state.run:
        st.write("Create a consented request to begin. The report will show claimed facts, employer-provided facts, mismatches, and the audit history.")
    else:
        run = st.session_state.run
        st.write(f"**{run['candidate']}** · claimed employment at **{run['company']}** · `{run['request_id']}`")
        if not st.session_state.response:
            choice = st.radio(
                "Demo employer response",
                ["match", "title_mismatch", "unavailable"],
                format_func=lambda item: {
                    "match": "Confirm all requested facts",
                    "title_mismatch": "Confirm employment, but report a different title",
                    "unavailable": "Decline / no response",
                }[item],
            )
            if st.button("Record employer response", type="primary"):
                st.session_state.response = employer_reply(choice)
                add_event("EMPLOYER_RESPONSE_RECORDED", st.session_state.response["note"])
                add_event("COMPARISON_COMPLETE", "Claimed and employer-provided fields were compared.")
                st.rerun()
        else:
            rows = comparison_rows()
            status = report_status(rows)
            st.metric("Verification status", status)
            st.dataframe(rows, hide_index=True, width="stretch")
            st.caption(st.session_state.response["note"])
            if status.startswith("REVIEW REQUIRED"):
                st.warning("A mismatch is not an automatic rejection. HR should request clarification and document the outcome.")
            elif status.startswith("INCOMPLETE"):
                st.warning("Do not infer a negative result from an unavailable response. Use an approved follow-up path.")
            else:
                st.success("The requested employment facts match the recorded employer reply.")

            decision = st.selectbox(
                "HR disposition",
                ["Select after review", "Accept verification", "Request candidate clarification", "Escalate for manual review", "Close as incomplete"],
            )
            rationale = st.text_area("HR rationale", placeholder="Required when recording a disposition.")
            if st.button("Record HR disposition"):
                if decision == "Select after review" or not rationale.strip():
                    st.error("Select a disposition and provide the HR rationale.")
                else:
                    st.session_state.hr_decision = {"decision": decision, "rationale": rationale.strip()}
                    add_event("HR_DISPOSITION_RECORDED", f"{decision}: {rationale.strip()}")
                    st.success("HR disposition saved to the audit trail.")

            report = "\n".join([
                "# Employment Verification Report",
                f"Request ID: {run['request_id']}", f"Status: {status}", f"Candidate: {run['candidate']}",
                f"Previous employer: {run['company']}", "", "## Comparison",
                *[f"- {row['Field']}: claimed `{row['Claimed']}` | verified `{row['Verified']}` | {row['Result']}" for row in rows],
                "", "## Employer response", st.session_state.response["note"], "", "## HR disposition",
                (f"{st.session_state.hr_decision['decision']} — {st.session_state.hr_decision['rationale']}"
                 if st.session_state.hr_decision else "Pending HR review."),
            ])
            st.download_button("Download verification report (.md)", report, "employment-verification-report.md", "text/markdown")

if st.session_state.run:
    st.subheader("Audit trail")
    st.dataframe(st.session_state.events, hide_index=True, width="stretch")
    if st.button("Start a new verification"):
        st.session_state.run = None
        st.session_state.events = []
        st.session_state.response = None
        st.session_state.hr_decision = None
        st.rerun()
