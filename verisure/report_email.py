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

    def send(self, *, case_id: str, candidate_name: str, pdf: bytes) -> str:
        if not self.settings.ready:
            raise ValidationError(
                (
                    "SMTP report delivery is not fully configured. Missing: "
                    + ", ".join(self.settings.missing_fields),
                )
            )

        message = EmailMessage()
        message["Subject"] = f"Employment verification report - {case_id}"
        message["From"] = self.settings.sender
        message["To"] = self.settings.recipient
        message.set_content(
            f"The completed employment verification evidence report for {candidate_name} "
            f"(case {case_id}) is attached for HR review."
        )
        message.add_attachment(
            pdf,
            maintype="application",
            subtype="pdf",
            filename=f"{case_id.lower()}-verification-report.pdf",
        )
        with smtplib.SMTP(self.settings.host, self.settings.port, timeout=20) as client:
            if self.settings.use_tls:
                client.starttls()
            client.login(self.settings.username, self.settings.password)
            client.send_message(message)
        return self.settings.recipient


@dataclass(frozen=True, slots=True)
class ReportDispatch:
    status: str
    detail: str = ""


def dispatch_completed_report(
    store: "CaseStore", case_id: str, gateway: ReportEmailGateway | None = None
) -> ReportDispatch:
    """Create and email one evidence report after a terminal verification result.

    A database claim is made before SMTP delivery, so a repeated webhook or UI rerun
    cannot produce another automatic send. A failed SMTP transaction is deliberately
    retained for HR follow-up instead of being retried blindly.
    """

    from .domain import compare_sources
    from .reporting import build_verification_report_pdf

    active_gateway = gateway or ReportEmailGateway()
    if not active_gateway.settings.ready:
        return ReportDispatch("NOT_CONFIGURED")
    if not store.claim_report_delivery(case_id, active_gateway.settings.recipient):
        existing = store.report_delivery_for_case(case_id)
        return ReportDispatch(existing.status if existing else "ALREADY_CLAIMED")

    case = store.get_case(case_id)
    if case is None:  # Defensive guard; the claim verified the case exists.
        return ReportDispatch("FAILED", "Verification case was not found.")
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
            pdf=pdf,
        )
    except Exception as exc:
        store.mark_report_delivery_failed(case_id, str(exc))
        return ReportDispatch("FAILED", str(exc))
    store.mark_report_delivery_sent(case_id)
    return ReportDispatch("SENT", recipient)
