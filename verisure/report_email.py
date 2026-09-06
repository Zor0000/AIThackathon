"""SMTP delivery for a completed verification report."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING

from .domain import ValidationError

if TYPE_CHECKING:
    from .storage import CaseStore


@dataclass(frozen=True, slots=True)
class ReportEmailSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str
    use_tls: bool

    @classmethod
    def from_env(cls) -> "ReportEmailSettings":
        port_text = os.getenv("SMTP_PORT", "587").strip()
        try:
            port = int(port_text)
        except ValueError:
            port = 0
        return cls(
            host=os.getenv("SMTP_HOST", "").strip(),
            port=port,
            username=os.getenv("SMTP_USERNAME", "").strip(),
            password=os.getenv("SMTP_PASSWORD", ""),
            sender=os.getenv("SMTP_FROM", "").strip(),
            recipient=os.getenv(
                "HR_RECIPIENT_EMAIL", "neerajchormale39@gmail.com"
            ).strip(),
            use_tls=os.getenv("SMTP_USE_TLS", "true").strip().lower()
            not in {"0", "false", "no"},
        )

    @property
    def ready(self) -> bool:
        return not self.missing_fields

    @property
    def missing_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        if not self.host:
            fields.append("SMTP_HOST")
        if self.port <= 0:
            fields.append("SMTP_PORT")
        if not self.username:
            fields.append("SMTP_USERNAME")
        if not self.password:
            fields.append("SMTP_PASSWORD")
        if not self.sender:
            fields.append("SMTP_FROM")
        if not self.recipient:
            fields.append("HR_RECIPIENT_EMAIL")
        return tuple(fields)


class ReportEmailGateway:
    def __init__(self, settings: ReportEmailSettings | None = None) -> None:
        self.settings = settings or ReportEmailSettings.from_env()

    def send(
        self,
        *,
        case_id: str,
        candidate_name: str,
        verification_status: str,
        pdf: bytes,
    ) -> str:
        if not self.settings.ready:
            raise ValidationError(
                (
                    "SMTP report delivery is not fully configured. Missing: "
                    + ", ".join(self.settings.missing_fields),
                )
            )

        message = build_report_email_message(
            sender=self.settings.sender,
            recipient=self.settings.recipient,
            case_id=case_id,
            candidate_name=candidate_name,
            verification_status=verification_status,
            pdf=pdf,
        )
        with smtplib.SMTP(self.settings.host, self.settings.port, timeout=20) as client:
            if self.settings.use_tls:
                client.starttls()
            client.login(self.settings.username, self.settings.password)
            client.send_message(message)
        return self.settings.recipient


def build_report_email_message(
    *,
    sender: str,
    recipient: str,
    case_id: str,
    candidate_name: str,
    verification_status: str,
    pdf: bytes,
) -> EmailMessage:
    """Build a clear HR notification while keeping the conclusion human-led."""

    message = EmailMessage()
    message["Subject"] = f"HR review needed: employment verification — {case_id}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Hello HR Team,\n\n"
        "An employment-verification evidence report is ready for your review.\n\n"
        f"Candidate: {candidate_name}\n"
        f"Case ID: {case_id}\n"
        f"Evidence status: {verification_status}\n\n"
        "Next steps:\n"
        "1. Review the attached verification report and field-by-field comparison.\n"
        "2. Open the VeriSure HR dashboard to record the final conclusion and rationale.\n"
        "3. Follow your organisation's consent, privacy, and retention procedures.\n\n"
        "This evidence status is not an automated hiring decision. Any employment "
        "decision must be made by an authorised HR reviewer.\n\n"
        "Regards,\n"
        "VeriSure\n"
        "Automated verification workflow\n"
    )
    message.add_attachment(
        pdf,
        maintype="application",
        subtype="pdf",
        filename=f"{case_id.lower()}-verification-report.pdf",
    )
    return message


@dataclass(frozen=True, slots=True)
class ReportDispatch:
    status: str
    detail: str = ""


def dispatch_completed_report(
    store: "CaseStore", case_id: str, gateway: ReportEmailGateway | None = None
) -> ReportDispatch:
    """Create and email one evidence report after a terminal verification result.

    Email delivery is held until an HR reviewer records the final conclusion. A database
    claim then prevents a repeated UI rerun from sending a duplicate report.
    """

    from .domain import compare_sources
    from .reporting import build_verification_report_pdf

    active_gateway = gateway or ReportEmailGateway()
    case = store.get_case(case_id)
    if case is None:
        return ReportDispatch("FAILED", "Verification case was not found.")
    if not case.hr_conclusion:
        return ReportDispatch(
            "AWAITING_HR_REVIEW",
            "HR must record a final conclusion before the report is emailed.",
        )
    if not active_gateway.settings.ready:
        return ReportDispatch("NOT_CONFIGURED")
    if not store.claim_report_delivery(case_id, active_gateway.settings.recipient):
        existing = store.report_delivery_for_case(case_id)
        return ReportDispatch(existing.status if existing else "ALREADY_CLAIMED")

    try:
        pdf = build_verification_report_pdf(
            case=case,
            comparisons=compare_sources(
                case.candidate_facts, case.document_facts, case.employer_facts
            ),
            generated_at=case.updated_at,
        )
        recipient = active_gateway.send(
            case_id=case.case_id,
            candidate_name=case.candidate_name,
            verification_status=case.verification_status.value,
            pdf=pdf,
        )
    except Exception as exc:
        store.mark_report_delivery_failed(case_id, str(exc))
        return ReportDispatch("FAILED", str(exc))
    store.mark_report_delivery_sent(case_id)
    return ReportDispatch("SENT", recipient)
