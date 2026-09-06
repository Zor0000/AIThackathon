"""Streamlit UI for candidate submission and HR-led verification."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException

from verisure import (
    EmployerResponseStatus,
    EmploymentFacts,
    HRConclusion,
    InputAssistantSettings,
    ReportEmailSettings,
    TwilioGateway,
    TwilioSettings,
    ValidationError,
    allowed_conclusions,
    build_verification_report_pdf,
    build_verification_message,
    compare_sources,
    create_employment_facts,
    dispatch_completed_report,
    extract_document,
    normalize_whatsapp_address,
    render_markdown_report,
    utc_now,
)
from verisure.extraction import ExtractionError
from verisure.storage import CaseRecord, CaseStore

load_dotenv()
st.set_page_config(page_title="VeriSure", page_icon="✓", layout="wide")

DEMO_DOCUMENT_PATH = (
    Path(__file__).resolve().parent
    / "output/pdf/fictional-experience-letter-aarav-shah.pdf"
)


@st.cache_resource
def get_store() -> CaseStore:
    return CaseStore.from_environment()


def facts_table(facts: EmploymentFacts | None) -> dict[str, str]:
    if facts is None:
        return {
            "Employer": "-",
            "Job title": "-",
            "Start date": "-",
            "End date": "-",
            "Employee ID": "-",
        }
    return {
        "Employer": facts.employer_name or "-",
        "Job title": facts.job_title or "-",
        "Start date": facts.start_date or "-",
        "End date": facts.end_date or "-",
        "Employee ID": facts.employee_id or "-",
    }


def show_facts(label: str, facts: EmploymentFacts | None) -> None:
    st.markdown(f"**{label}**")
    st.dataframe(
        [{"Field": key, "Value": value} for key, value in facts_table(facts).items()],
        hide_index=True,
        width="stretch",
    )


def render_candidate_submission(store: CaseStore) -> None:
    st.subheader("Upload employee document")
    st.caption(
        "Upload the employee's experience or relieving letter. VeriSure extracts the "
        "employment record from the PDF; no employment details are typed into the app. "
        "The original file is processed in memory and is not stored."
    )

    with st.form("candidate_submission", clear_on_submit=False):
        document = st.file_uploader(
            "Employee's experience or relieving letter (PDF)", type=["pdf"]
        )
        use_demo_document = st.checkbox("Use synthetic demo PDF")
        consent = st.checkbox(
            "The employee has consented to former-employer verification."
        )
        submitted = st.form_submit_button("Extract document and continue", type="primary")

    if not submitted:
        return
    if not consent:
        st.error("Consent is required before a verification case can be created.")
        return
    if document is None and not use_demo_document:
        st.error("Upload a supporting document or select the fictional demo document.")
        return

    try:
        if use_demo_document:
            document_name = DEMO_DOCUMENT_PATH.name
            document_bytes = DEMO_DOCUMENT_PATH.read_bytes()
        else:
            assert document is not None
            document_name = document.name
            document_bytes = document.getvalue()
        extraction = extract_document(document_name, document_bytes)
        case_id = store.create_case(
            candidate_name=extraction.candidate_name or "Employee name not extracted",
            candidate_email="",
            candidate_facts=extraction.facts,
            document_facts=None,
            document_name=document_name,
            document_sha256=extraction.document_sha256,
            extraction_method=extraction.method,
            extraction_warnings=extraction.warnings,
            consent_confirmed=True,
        )
    except (ValidationError, ExtractionError) as exc:
        messages = exc.messages if isinstance(exc, ValidationError) else (str(exc),)
        for message in messages:
            st.error(message)
        return

    st.session_state.selected_case_id = case_id
    st.session_state.redirect_to_hr = True
    st.success(f"Document extracted. Opening HR dashboard for case {case_id}.")
    if extraction.warnings:
        for warning in extraction.warnings:
            st.warning(warning)


def render_contact_step(store: CaseStore, case: CaseRecord) -> None:
    st.markdown("### Former-employer contact")
    if case.verifier_phone:
        st.write(
            f"**Approved verifier:** {case.verifier_name} · `{case.verifier_phone}`"
        )
        return

    with st.form("verifier_contact"):
        verifier_name = st.text_input("Verifier/HR contact name", value="Riya Mehta")
        verifier_phone = st.text_input(
            "WhatsApp number (E.164)",
            value="+919876543210",
            help="Include the country code, for example +919876543210.",
        )
        save_contact = st.form_submit_button("Save approved contact")
    if save_contact:
        try:
            normalized = normalize_whatsapp_address(verifier_phone).split(":", 1)[1]
            store.set_verifier_contact(case.case_id, verifier_name, normalized)
        except ValidationError as exc:
            for message in exc.messages:
                st.error(message)
        else:
            st.rerun()


def render_outreach_step(store: CaseStore, case: CaseRecord, source_mode: str) -> None:
    if not case.verifier_phone:
        return

    st.markdown("### WhatsApp verification")
    with st.expander("Preview structured verification request"):
        st.code(build_verification_message(case), language=None)

    if case.employer_response_status is EmployerResponseStatus.NOT_STARTED:
        if st.button("Initiate WhatsApp verification", type="primary"):
            if source_mode == "live":
                try:
                    result = TwilioGateway().send_verification(case)
                except (RuntimeError, ValidationError, TwilioRestException) as exc:
                    st.error(f"WhatsApp request was not sent: {exc}")
                    return
                store.mark_outreach_sent(
                    case.case_id,
                    body=result.body,
                    twilio_sid=result.sid,
                    delivery_status=result.status,
                )
                store.start_questionnaire(case.case_id)
            else:
                store.mark_outreach_sent(
                    case.case_id,
                    body=build_verification_message(case),
                    twilio_sid=f"FIXTURE-{uuid4().hex}",
                    delivery_status="simulated",
                )
                store.start_questionnaire(case.case_id)
            st.rerun()
        return

    if case.employer_response_status is not EmployerResponseStatus.PENDING:
        st.success(f"Employer response: {case.employer_response_status.value}")
        return

    st.info(
        "The guided WhatsApp questionnaire is awaiting the next former-employer reply."
    )
    if source_mode == "live":
        if st.button("Refresh case status"):
            st.rerun()
        return

    render_fixture_response(store, case)


def render_fixture_response(store: CaseStore, case: CaseRecord) -> None:
    st.caption("Fixture mode: simulate the structured reply that Twilio would deliver.")
    with st.form("fixture_response"):
        response_type = st.radio("Employer response", ("CONFIRMED", "DECLINED"))
        employer_name = st.text_input(
            "Employer-reported company", value=case.candidate_facts.employer_name
        )
        job_title = st.text_input(
            "Employer-reported title", value=case.candidate_facts.job_title
        )
        date_left, date_right = st.columns(2)
        with date_left:
            start_date = st.text_input(
                "Employer-reported start", value=case.candidate_facts.start_date
            )
        with date_right:
            end_date = st.text_input(
                "Employer-reported end", value=case.candidate_facts.end_date
            )
        employee_id = st.text_input(
            "Employer-reported employee ID", value=case.candidate_facts.employee_id
        )
        record_response = st.form_submit_button("Simulate Twilio webhook")

    if not record_response:
        return
    try:
        if response_type == "DECLINED":
            status = EmployerResponseStatus.DECLINED
            facts = None
            body = f"CASE: {case.case_id}\nSTATUS: DECLINED"
        else:
            status = EmployerResponseStatus.RECEIVED
            facts = create_employment_facts(
                {
                    "employer_name": employer_name,
                    "job_title": job_title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "employee_id": employee_id,
                }
            )
            body = f"CASE: {case.case_id}\nSTATUS: CONFIRMED"
        store.record_employer_response(
            case.case_id,
            response_status=status,
            employer_facts=facts,
            body=body,
            twilio_sid=f"FIXTURE-INBOUND-{uuid4().hex}",
        )
    except ValidationError as exc:
        for message in exc.messages:
            st.error(message)
    else:
        st.rerun()


def render_evidence_and_conclusion(store: CaseStore, case: CaseRecord) -> None:
    if case.employer_response_status not in {
        EmployerResponseStatus.RECEIVED,
        EmployerResponseStatus.DECLINED,
    }:
        return

    comparisons = compare_sources(
        case.candidate_facts,
        case.document_facts,
        case.employer_facts,
    )
    st.markdown("### Evidence comparison")
    st.metric("Verification status", case.verification_status.value)
    st.dataframe(
        [
            {
                "Field": row.field,
                "Employee PDF": row.candidate_value or "-",
                "Former employer": row.employer_value or "-",
                "Analysis": row.result.value,
            }
            for row in comparisons
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Differences are evidence for HR review. The system does not label a candidate truthful or false."
    )

    if case.hr_conclusion:
        st.success(f"HR conclusion: {case.hr_conclusion}")
        st.write(case.hr_rationale)
        dispatch = dispatch_completed_report(store, case.case_id)
        if dispatch.status == "SENT":
            st.success(f"Verification PDF automatically emailed to HR: {dispatch.detail}")
        elif dispatch.status == "FAILED":
            st.error("The automatic HR report email failed. See the audit trail for details.")
        elif dispatch.status == "NOT_CONFIGURED":
            missing = ", ".join(ReportEmailSettings.from_env().missing_fields)
            st.warning(
                "Automatic HR email is waiting for SMTP configuration. Missing: "
                f"{missing}. The comparison PDF is ready to download below."
            )
        else:
            delivery = store.report_delivery_for_case(case.case_id)
            if delivery and delivery.status == "SENT":
                st.caption(f"Verification PDF was emailed to HR: {delivery.recipient}")
            elif delivery and delivery.status == "FAILED":
                st.error("The automatic HR report email failed. See the audit trail for details.")
    else:
        st.info("The report will be emailed only after HR records a final conclusion.")
        with st.form("hr_conclusion"):
            conclusion = st.selectbox(
                "Final HR conclusion",
                allowed_conclusions(case.verification_status),
                format_func=lambda item: item.value,
                index=None,
                placeholder="Select after reviewing the evidence",
            )
            rationale = st.text_area(
                "HR rationale",
                placeholder="State the evidence supporting this conclusion.",
            )
            close_case = st.form_submit_button("Record final conclusion")
        if close_case:
            if conclusion is None:
                st.error("Select an HR conclusion.")
            else:
                try:
                    assert isinstance(conclusion, HRConclusion)
                    store.close_case(case.case_id, conclusion, rationale)
                except ValidationError as exc:
                    for message in exc.messages:
                        st.error(message)
                else:
                    st.rerun()

    events = store.events_for_case(case.case_id)
    report = render_markdown_report(
        case=case.as_report_mapping(),
        comparisons=comparisons,
        events=events,
        generated_at=utc_now(),
    )
    pdf_report = build_verification_report_pdf(
        case=case,
        comparisons=comparisons,
        generated_at=utc_now(),
    )
    st.download_button(
        "Download verification PDF",
        pdf_report,
        file_name=f"{case.case_id.lower()}-verification-report.pdf",
        mime="application/pdf",
    )
    st.download_button(
        "Download verification report",
        report,
        file_name=f"{case.case_id.lower()}-verification-report.md",
        mime="text/markdown",
    )


def render_hr_dashboard(store: CaseStore, source_mode: str) -> None:
    st.subheader("HR verification dashboard")
    cases = store.list_cases()
    if not cases:
        st.info("No cases yet. Submit a candidate case first.")
        return

    st.metric(
        "Completed verifications (all outcomes)", store.completed_verification_count()
    )

    case_by_id = {case.case_id: case for case in cases}
    preferred_id = st.session_state.get("selected_case_id")
    default_index = (
        list(case_by_id).index(preferred_id) if preferred_id in case_by_id else 0
    )
    selected_id = st.selectbox(
        "Verification case",
        case_by_id,
        index=default_index,
        format_func=lambda case_id: (
            f"{case_id} · {case_by_id[case_id].candidate_name} · "
            f"{case_by_id[case_id].state.value}"
        ),
    )
    st.session_state.selected_case_id = selected_id
    case = case_by_id[selected_id]

    metric_columns = st.columns(4)
    metric_columns[0].metric("Case", case.case_id)
    metric_columns[1].metric("Workflow", case.state.value)
    metric_columns[2].metric("Response", case.employer_response_status.value)
    metric_columns[3].metric("Result", case.verification_status.value)

    claim_column, document_column = st.columns(2, gap="large")
    with claim_column:
        show_facts("Employee document extraction", case.candidate_facts)
    with document_column:
        st.markdown("**Document processing**")
        st.write(f"File: {case.document_name}")
        st.caption(f"{case.extraction_method} · SHA-256 {case.document_sha256[:12]}…")
        for warning in case.extraction_warnings:
            st.warning(warning)

    render_contact_step(store, case)
    case = store.get_case(case.case_id) or case
    render_outreach_step(store, case, source_mode)
    case = store.get_case(case.case_id) or case
    render_evidence_and_conclusion(store, case)

    with st.expander("Audit trail"):
        st.dataframe(
            store.events_for_case(case.case_id), hide_index=True, width="stretch"
        )


store = get_store()
source_mode = os.getenv("SOURCE_MODE", "fixture").strip().lower()
if source_mode not in {"fixture", "live"}:
    source_mode = "fixture"

st.title("VeriSure")
st.caption("Candidate evidence in. Former-employer verification out. HR decides.")
if source_mode == "live":
    settings = TwilioSettings.from_env()
    if settings.ready:
        st.success("Live Twilio mode · Required connection settings found")
        if not settings.validate_signature:
            st.warning("Twilio webhook signature validation is disabled.")
    else:
        st.error(
            "Live mode is selected, but the required Twilio settings are incomplete."
        )
else:
    st.info("Fixture mode · WhatsApp delivery and replies are simulated locally")

input_assistant = InputAssistantSettings.from_env()
if input_assistant.ready:
    st.caption("AI input repair is enabled for natural-language verifier replies.")
elif os.getenv("AI_INPUT_ASSIST_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}:
    st.caption(
        "AI input repair is off until OPENAI_API_KEY and AI_INPUT_MODEL (or LLM_MODEL) are configured."
    )

default_tab = "HR dashboard" if st.session_state.pop("redirect_to_hr", False) else "Upload employee PDF"
candidate_tab, hr_tab = st.tabs(
    ("Upload employee PDF", "HR dashboard"), default=default_tab
)
with candidate_tab:
    render_candidate_submission(store)
with hr_tab:
    render_hr_dashboard(store, source_mode)
