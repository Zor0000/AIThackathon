"""Twilio WhatsApp transport and structured reply parsing."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .domain import (
    EmployerResponseStatus,
    EmploymentFacts,
    ValidationError,
    create_employment_facts,
)
from .questionnaire import QuestionnaireStep, prompt_for
from .storage import CaseRecord


@dataclass(frozen=True, slots=True)
class TwilioSettings:
    account_sid: str
    auth_token: str
    whatsapp_from: str
    public_base_url: str
    validate_signature: bool

    @classmethod
    def from_env(cls) -> TwilioSettings:
        return cls(
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
            whatsapp_from=os.getenv("TWILIO_WHATSAPP_FROM", "").strip(),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"),
            validate_signature=os.getenv("TWILIO_VALIDATE_SIGNATURE", "true").lower()
            not in {"0", "false", "no"},
        )

    @property
    def ready(self) -> bool:
        return all(
            (
                self.account_sid,
                self.auth_token,
                self.whatsapp_from,
                self.public_base_url,
            )
        )


@dataclass(frozen=True, slots=True)
class SendResult:
    sid: str
    status: str
    body: str


@dataclass(frozen=True, slots=True)
class ParsedReply:
    case_id: str
    status: EmployerResponseStatus
    facts: EmploymentFacts | None


class TwilioGateway:
    def __init__(self, settings: TwilioSettings | None = None) -> None:
        self.settings = settings or TwilioSettings.from_env()

    def send_verification(self, case: CaseRecord) -> SendResult:
        if not self.settings.ready:
            raise RuntimeError("Twilio live mode is not fully configured.")
        if not case.consent_confirmed:
            raise ValidationError(("Candidate consent is required before outreach.",))
        if not case.verifier_phone:
            raise ValidationError(("The former-employer WhatsApp number is required.",))

        from twilio.rest import Client

        body = build_verification_message(case)
        callback_url = f"{self.settings.public_base_url}/webhooks/twilio/status"
        message = Client(
            self.settings.account_sid,
            self.settings.auth_token,
        ).messages.create(
            from_=normalize_whatsapp_address(self.settings.whatsapp_from),
            to=normalize_whatsapp_address(case.verifier_phone),
            body=body,
            status_callback=callback_url,
        )
        return SendResult(
            sid=str(message.sid),
            status=str(message.status or "queued"),
            body=body,
        )


def build_verification_message(case: CaseRecord) -> str:
    return prompt_for(
        case.case_id,
        case.candidate_name,
        QuestionnaireStep.AUTHORIZATION,
    )


def parse_whatsapp_reply(body: str) -> ParsedReply:
    """Parse the narrow key-value contract sent to the former employer."""

    pairs: dict[str, str] = {}
    for raw_line in body.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        pairs[key.strip().upper()] = value.strip()

    case_id = pairs.get("CASE", "").upper()
    if not re.fullmatch(r"BV-[A-Z0-9]{8}", case_id):
        raise ValidationError(("Reply must contain a valid CASE identifier.",))

    status_text = pairs.get("STATUS", "").upper()
    if status_text == "DECLINED":
        return ParsedReply(case_id, EmployerResponseStatus.DECLINED, None)
    if status_text != "CONFIRMED":
        raise ValidationError(("STATUS must be CONFIRMED or DECLINED.",))

    facts = create_employment_facts(
        {
            "employer_name": pairs.get("EMPLOYER", ""),
            "job_title": pairs.get("TITLE", ""),
            "start_date": pairs.get("START", ""),
            "end_date": pairs.get("END", ""),
            "employee_id": pairs.get("EMPLOYEE_ID", ""),
        }
    )
    return ParsedReply(case_id, EmployerResponseStatus.RECEIVED, facts)


def normalize_whatsapp_address(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith("whatsapp:"):
        cleaned = cleaned.split(":", 1)[1]
    compact = re.sub(r"[\s()-]", "", cleaned)
    if not re.fullmatch(r"\+[1-9]\d{7,14}", compact):
        raise ValidationError(
            (
                "WhatsApp number must use international E.164 format, for example +919876543210.",
            )
        )
    return f"whatsapp:{compact}"
