"""Domain rules for evidence-based employment verification."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ValidationError(ValueError):
    """Raised when submitted data violates the case input contract."""

    def __init__(self, messages: Sequence[str]) -> None:
        self.messages = tuple(messages)
        super().__init__(" ".join(self.messages))


class CaseState(StrEnum):
    SUBMITTED = "SUBMITTED"
    READY_FOR_OUTREACH = "READY FOR OUTREACH"
    OUTREACH_SENT = "OUTREACH SENT"
    RESPONSE_RECEIVED = "RESPONSE RECEIVED"
    HR_REVIEWED = "HR REVIEWED"


class EmployerResponseStatus(StrEnum):
    NOT_STARTED = "NOT STARTED"
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    DECLINED = "DECLINED"


class FieldResult(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_PROVIDED = "NOT PROVIDED"
    NEEDS_REVIEW = "NEEDS REVIEW"


class VerificationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    DISCREPANCY_FOUND = "DISCREPANCY FOUND"
    UNABLE_TO_VERIFY = "UNABLE TO VERIFY"


class HRConclusion(StrEnum):
    INFORMATION_VERIFIED = "Information verified"
    DISCREPANCY_CONFIRMED = "Discrepancy confirmed"
    UNABLE_TO_VERIFY = "Unable to verify"
    MANUAL_REVIEW_REQUIRED = "Further manual review required"


@dataclass(frozen=True, slots=True)
class EmploymentFacts:
    employer_name: str
    job_title: str
    start_date: str
    end_date: str
    employee_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    field: str
    candidate_value: str
    document_value: str
    employer_value: str
    result: FieldResult

    def as_table_row(self) -> dict[str, str]:
        return {
            "Field": self.field,
            "Candidate": self.candidate_value or "-",
            "Document": self.document_value or "-",
            "Former employer": self.employer_value or "-",
            "Result": self.result.value,
        }


FACT_FIELDS = (
    ("Employer", "employer_name"),
    ("Job title", "job_title"),
    ("Start date", "start_date"),
    ("End date", "end_date"),
    ("Employee ID", "employee_id"),
)


def create_employment_facts(
    values: Mapping[str, str], *, partial: bool = False
) -> EmploymentFacts:
    """Normalize facts and validate required fields and YYYY-MM date values."""

    fields = {key for _, key in FACT_FIELDS}
    cleaned = {key: values.get(key, "").strip() for key in fields}
    errors: list[str] = []

    required = {"employer_name", "job_title", "start_date", "end_date"}
    if not partial:
        labels = {
            "employer_name": "Previous employer",
            "job_title": "Job title",
            "start_date": "Start date",
            "end_date": "End date",
        }
        errors.extend(
            f"{labels[key]} is required." for key in required if not cleaned[key]
        )

    for key, label in (("start_date", "Start date"), ("end_date", "End date")):
        if cleaned[key] and not MONTH_PATTERN.fullmatch(cleaned[key]):
            errors.append(f"{label} must use YYYY-MM.")

    if (
        MONTH_PATTERN.fullmatch(cleaned["start_date"])
        and MONTH_PATTERN.fullmatch(cleaned["end_date"])
        and cleaned["start_date"] > cleaned["end_date"]
    ):
        errors.append("Start date cannot be after the end date.")

    if errors:
        raise ValidationError(errors)
    return EmploymentFacts(**cleaned)


def validate_candidate(candidate_name: str, candidate_email: str) -> tuple[str, str]:
    name = candidate_name.strip()
    email = candidate_email.strip()
    errors: list[str] = []
    if not name:
        errors.append("Candidate name is required.")
    if not email:
        errors.append("Candidate email is required.")
    elif not EMAIL_PATTERN.fullmatch(email):
        errors.append("Candidate email must be valid.")
    if errors:
        raise ValidationError(errors)
    return name, email


def compare_sources(
    candidate: EmploymentFacts,
    document: EmploymentFacts | None,
    employer: EmploymentFacts | None,
) -> tuple[ComparisonRow, ...]:
    """Compare candidate claims against document and former-employer evidence."""

    rows: list[ComparisonRow] = []
    for label, attribute in FACT_FIELDS:
        candidate_value = getattr(candidate, attribute)
        document_value = getattr(document, attribute) if document else ""
        employer_value = getattr(employer, attribute) if employer else ""

        if not employer_value:
            result = FieldResult.NOT_PROVIDED
        elif _normalized(candidate_value) != _normalized(employer_value):
            result = FieldResult.MISMATCH
        elif document_value and _normalized(document_value) != _normalized(
            candidate_value
        ):
            result = FieldResult.NEEDS_REVIEW
        else:
            result = FieldResult.MATCH

        rows.append(
            ComparisonRow(
                field=label,
                candidate_value=candidate_value,
                document_value=document_value,
                employer_value=employer_value,
                result=result,
            )
        )
    return tuple(rows)


def derive_verification_status(
    response_status: EmployerResponseStatus,
    comparisons: Sequence[ComparisonRow],
) -> VerificationStatus:
    if response_status in {
        EmployerResponseStatus.NOT_STARTED,
        EmployerResponseStatus.PENDING,
    }:
        return VerificationStatus.PENDING
    if response_status is EmployerResponseStatus.DECLINED:
        return VerificationStatus.UNABLE_TO_VERIFY
    if any(
        row.result in {FieldResult.MISMATCH, FieldResult.NEEDS_REVIEW}
        for row in comparisons
    ):
        return VerificationStatus.DISCREPANCY_FOUND
    return VerificationStatus.VERIFIED


def allowed_conclusions(status: VerificationStatus) -> tuple[HRConclusion, ...]:
    if status is VerificationStatus.VERIFIED:
        return (
            HRConclusion.INFORMATION_VERIFIED,
            HRConclusion.MANUAL_REVIEW_REQUIRED,
        )
    if status is VerificationStatus.DISCREPANCY_FOUND:
        return (
            HRConclusion.DISCREPANCY_CONFIRMED,
            HRConclusion.MANUAL_REVIEW_REQUIRED,
        )
    if status is VerificationStatus.UNABLE_TO_VERIFY:
        return (
            HRConclusion.UNABLE_TO_VERIFY,
            HRConclusion.MANUAL_REVIEW_REQUIRED,
        )
    return ()


def render_markdown_report(
    *,
    case: Mapping[str, object],
    comparisons: Sequence[ComparisonRow],
    events: Sequence[Mapping[str, str]],
    generated_at: str,
) -> str:
    """Render an evidence report without contact details or uploaded document bytes."""

    def safe(value: object) -> str:
        return str(value or "-").replace("|", "\\|").replace("\n", " ")

    comparison_lines = [
        "| Field | Candidate | Document | Former employer | Result |",
        "|---|---|---|---|---|",
        *[
            f"| {safe(row.field)} | {safe(row.candidate_value)} | "
            f"{safe(row.document_value)} | {safe(row.employer_value)} | "
            f"{row.result.value} |"
            for row in comparisons
        ],
    ]
    event_lines = [
        "| Time | Event | Detail |",
        "|---|---|---|",
        *[
            f"| {safe(event['created_at'])} | {safe(event['event_type'])} | "
            f"{safe(event['detail'])} |"
            for event in events
        ],
    ]

    return "\n".join(
        [
            "# Employment Verification Report",
            "",
            (
                "> This report presents verification evidence for human HR review. "
                "It is not an automated hiring decision."
            ),
            "",
            f"- **Case ID:** {safe(case['case_id'])}",
            f"- **Generated:** {safe(generated_at)}",
            f"- **Candidate:** {safe(case['candidate_name'])}",
            f"- **Verification status:** {safe(case['verification_status'])}",
            f"- **HR conclusion:** {safe(case.get('hr_conclusion'))}",
            f"- **HR rationale:** {safe(case.get('hr_rationale'))}",
            f"- **Document:** {safe(case.get('document_name'))}",
            f"- **Document fingerprint:** {safe(case.get('document_sha256'))}",
            "",
            "## Evidence comparison",
            "",
            *comparison_lines,
            "",
            "## Audit trail",
            "",
            *event_lines,
            "",
        ]
    )


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())
