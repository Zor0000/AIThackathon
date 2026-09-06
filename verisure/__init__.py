"""Core package for the VeriSure employment-verification application."""

from .domain import (
    CaseState,
    ComparisonRow,
    EmployerResponseStatus,
    EmploymentFacts,
    FieldResult,
    HRConclusion,
    ValidationError,
    VerificationStatus,
    allowed_conclusions,
    compare_sources,
    create_employment_facts,
    derive_verification_status,
    render_markdown_report,
    validate_candidate,
)
from .extraction import ExtractionError, ExtractionResult, extract_document
from .input_intelligence import AnswerResolution, InputAssistant, InputAssistantSettings
from .messaging import (
    ParsedReply,
    TwilioGateway,
    TwilioSettings,
    build_verification_message,
    normalize_whatsapp_address,
    parse_whatsapp_reply,
)
from .report_email import (
    ReportDispatch,
    ReportEmailGateway,
    ReportEmailSettings,
    dispatch_completed_report,
)
from .reporting import build_verification_report_pdf
from .storage import CaseRecord, CaseStore, utc_now

__all__ = [
    "AnswerResolution",
    "CaseRecord",
    "CaseState",
    "CaseStore",
    "ComparisonRow",
    "EmployerResponseStatus",
    "EmploymentFacts",
    "ExtractionError",
    "ExtractionResult",
    "FieldResult",
    "HRConclusion",
    "InputAssistant",
    "InputAssistantSettings",
    "ParsedReply",
    "ReportDispatch",
    "ReportEmailGateway",
    "ReportEmailSettings",
    "TwilioGateway",
    "TwilioSettings",
    "ValidationError",
    "VerificationStatus",
    "allowed_conclusions",
    "build_verification_message",
    "build_verification_report_pdf",
    "compare_sources",
    "create_employment_facts",
    "derive_verification_status",
    "dispatch_completed_report",
    "extract_document",
    "normalize_whatsapp_address",
    "parse_whatsapp_reply",
    "render_markdown_report",
    "utc_now",
    "validate_candidate",
]
