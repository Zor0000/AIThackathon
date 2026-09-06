"""Employment-fact extraction from candidate-provided documents."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import strptime

from .domain import EmploymentFacts, create_employment_facts

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"}


class ExtractionError(ValueError):
    """Raised when an uploaded document cannot be safely extracted."""


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    facts: EmploymentFacts
    document_sha256: str
    method: str
    warnings: tuple[str, ...]
    candidate_name: str = ""


def extract_document(filename: str, content: bytes) -> ExtractionResult:
    """Extract approved employment fields without persisting raw document bytes."""

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(
            "Unsupported document type. Upload PDF, TXT, MD, PNG, JPG, or JPEG."
        )
    if not content:
        raise ExtractionError("The uploaded document is empty.")

    fingerprint = sha256(content).hexdigest()
    if suffix == ".pdf":
        text = _extract_pdf_text(content)
        if text.strip():
            facts, warnings = _extract_from_text(text)
            return ExtractionResult(
                facts,
                fingerprint,
                "PDF text extraction",
                warnings,
                _extract_candidate_name(text),
            )
        return _extract_with_openai(filename, content, "application/pdf", fingerprint)

    if suffix in {".txt", ".md"}:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExtractionError("The text document must use UTF-8 encoding.") from exc
        facts, warnings = _extract_from_text(text)
        return ExtractionResult(
            facts,
            fingerprint,
            "Deterministic text extraction",
            warnings,
            _extract_candidate_name(text),
        )

    mime_type = "image/png" if suffix == ".png" else "image/jpeg"
    return _extract_with_openai(filename, content, mime_type, fingerprint)


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractionError("PDF extraction requires the pypdf package.") from exc

    try:
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ExtractionError("The PDF could not be read or may be encrypted.") from exc


def _extract_from_text(text: str) -> tuple[EmploymentFacts, tuple[str, ...]]:
    values = {
        "employer_name": _label_value(text, ("employer", "company", "organization")),
        "job_title": _label_value(
            text, ("job title", "designation", "position", "role")
        ),
        "start_date": _label_value(text, ("start date", "date of joining", "joined")),
        "end_date": _label_value(
            text, ("end date", "last working date", "relieving date")
        ),
        "employee_id": _label_value(
            text, ("employee id", "employee number", "staff id")
        ),
    }
    _apply_natural_language_fallback(text, values)
    values["start_date"] = _normalize_month(values["start_date"])
    values["end_date"] = _normalize_month(values["end_date"])
    facts = create_employment_facts(values, partial=True)
    missing = [
        label
        for label, key in (
            ("employer", "employer_name"),
            ("job title", "job_title"),
            ("start date", "start_date"),
            ("end date", "end_date"),
        )
        if not values[key]
    ]
    warnings = (
        ("Could not extract: " + ", ".join(missing) + ". HR review is required.",)
        if missing
        else ()
    )
    return facts, warnings


def _label_value(text: str, labels: tuple[str, ...]) -> str:
    alternatives = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"(?im)^\s*(?:{alternatives})\s*[:\-]\s*([^\r\n]+?)\s*$")
    match = pattern.search(text)
    return match.group(1).strip(" .") if match else ""


def _apply_natural_language_fallback(text: str, values: dict[str, str]) -> None:
    pattern = re.compile(
        r"(?i)(?:worked|employed)\s+(?:as\s+)?(?P<title>[^,.]+?)\s+at\s+"
        r"(?P<employer>[^,.]+?)(?:\s+from\s+(?P<start>[^,.]+?)\s+to\s+"
        r"(?P<end>[^,.]+))?(?:[,.]|$)"
    )
    match = pattern.search(" ".join(text.split()))
    if not match:
        return
    values["job_title"] = values["job_title"] or match.group("title").strip()
    values["employer_name"] = values["employer_name"] or match.group("employer").strip()
    values["start_date"] = values["start_date"] or (match.group("start") or "").strip()
    values["end_date"] = values["end_date"] or (match.group("end") or "").strip()


def _extract_candidate_name(text: str) -> str:
    """Find a name only when the document explicitly identifies the employee."""

    patterns = (
        r"(?im)^\s*(?:employee|candidate|employee name|name)\s*[:\-]\s*([A-Za-z][A-Za-z .'-]{1,100})\s*$",
        r"(?i)employment\s+(?:record|history)\s+for\s+([A-Za-z][A-Za-z .'-]{1,100}?)(?:[.\n]|\s+is\s)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return " ".join(match.group(1).strip(" .").split())
    return ""


def _normalize_month(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", cleaned):
        return cleaned

    candidates = (
        "%B %Y",
        "%b %Y",
        "%m/%Y",
        "%m-%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    )
    for date_format in candidates:
        try:
            parsed = strptime(cleaned, date_format)
            return f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}"
        except ValueError:
            continue
    return cleaned


def _extract_with_openai(
    filename: str,
    content: bytes,
    mime_type: str,
    fingerprint: str,
) -> ExtractionResult:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if not api_key or not model:
        raise ExtractionError(
            "This document needs OCR. Configure OPENAI_API_KEY and LLM_MODEL, "
            "or upload a text-based PDF/TXT document."
        )

    from openai import OpenAI

    schema = {
        "type": "object",
        "properties": {
            "employer_name": {"type": "string"},
            "job_title": {"type": "string"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "employee_id": {"type": "string"},
        },
        "required": [
            "employer_name",
            "job_title",
            "start_date",
            "end_date",
            "employee_id",
        ],
        "additionalProperties": False,
    }
    data_url = f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"
    file_part = (
        {"type": "input_image", "image_url": data_url}
        if mime_type.startswith("image/")
        else {"type": "input_file", "filename": filename, "file_data": data_url}
    )
    try:
        response = OpenAI(api_key=api_key).responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Extract only employment facts visible in this document. "
                                "Use YYYY-MM for dates and an empty string when a field is absent."
                            ),
                        },
                        file_part,
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "employment_facts",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        payload = json.loads(response.output_text)
        facts = create_employment_facts(payload, partial=True)
    except Exception as exc:
        raise ExtractionError(
            "AI document extraction failed. Try a text-based PDF."
        ) from exc

    missing = [
        key
        for key, value in facts.to_dict().items()
        if key != "employee_id" and not value
    ]
    warnings = (
        (
            "Some employment fields were not visible in the document: "
            + ", ".join(missing),
        )
        if missing
        else ()
    )
    return ExtractionResult(
        facts, fingerprint, "Schema-constrained AI extraction", warnings
    )
