"""SQLite persistence for verification cases, events, and message metadata."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .domain import (
    CaseState,
    EmployerResponseStatus,
    EmploymentFacts,
    HRConclusion,
    ValidationError,
    VerificationStatus,
    allowed_conclusions,
    compare_sources,
    derive_verification_status,
)
from .input_intelligence import InputAssistant
from .questionnaire import (
    QuestionnaireStep,
    next_step,
    prompt_for,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database_target_from_env() -> str | Path:
    """Prefer the server-only Supabase Postgres URL, otherwise use SQLite."""

    for name in ("SUPABASE_DB_URL", "DATABASE_URL"):
        value = os.getenv(name, "").strip()
        if value.startswith(("postgresql://", "postgres://")):
            return value
    return Path(os.getenv("DATABASE_PATH", "data/verisure.db"))


class _ConnectionAdapter:
    """Normalize SQLite and psycopg parameter styles behind a tiny interface."""

    def __init__(self, connection: Any, *, postgres: bool) -> None:
        self._connection = connection
        self._postgres = postgres

    def execute(self, statement: str, params: tuple[Any, ...] = ()) -> Any:
        if self._postgres:
            statement = statement.replace("?", "%s")
        return self._connection.execute(statement, params)

    def executescript(self, script: str) -> None:
        if not self._postgres:
            self._connection.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self._connection.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


@dataclass(frozen=True, slots=True)
class CaseRecord:
    case_id: str
    candidate_name: str
    candidate_email: str
    candidate_facts: EmploymentFacts
    document_facts: EmploymentFacts | None
    document_name: str
    document_sha256: str
    extraction_method: str
    extraction_warnings: tuple[str, ...]
    consent_confirmed: bool
    consent_at: str
    verifier_name: str
    verifier_phone: str
    employer_response_status: EmployerResponseStatus
    employer_facts: EmploymentFacts | None
    verification_status: VerificationStatus
    state: CaseState
    hr_conclusion: str
    hr_rationale: str
    created_at: str
    updated_at: str

    def as_report_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "candidate_name": self.candidate_name,
            "verification_status": self.verification_status.value,
            "hr_conclusion": self.hr_conclusion,
            "hr_rationale": self.hr_rationale,
            "document_name": self.document_name,
            "document_sha256": self.document_sha256,
        }


@dataclass(frozen=True, slots=True)
class QuestionnaireProgress:
    reply: str
    completed: bool = False
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ReportDelivery:
    case_id: str
    recipient: str
    status: str
    error: str
    created_at: str
    sent_at: str


class CaseStore:
    def __init__(self, database_target: str | Path) -> None:
        self.database_url = str(database_target)
        self.uses_postgres = self.database_url.startswith(
            ("postgresql://", "postgres://")
        )
        self.database_path = Path(database_target) if not self.uses_postgres else None
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_environment(cls) -> CaseStore:
        return cls(database_target_from_env())

    @contextmanager
    def _connection(self) -> Iterator[_ConnectionAdapter]:
        if self.uses_postgres:
            from psycopg import connect
            from psycopg.rows import dict_row

            raw_connection = connect(self.database_url, row_factory=dict_row)
        else:
            assert self.database_path is not None
            raw_connection = sqlite3.connect(self.database_path)
            raw_connection.row_factory = sqlite3.Row
            raw_connection.execute("PRAGMA foreign_keys = ON")
        connection = _ConnectionAdapter(raw_connection, postgres=self.uses_postgres)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        generated_id = (
            "BIGSERIAL PRIMARY KEY"
            if self.uses_postgres
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        )
        consent_type = (
            "BOOLEAN NOT NULL"
            if self.uses_postgres
            else "INTEGER NOT NULL CHECK (consent_confirmed = 1)"
        )
        valid_type = (
            "BOOLEAN NOT NULL"
            if self.uses_postgres
            else "INTEGER NOT NULL CHECK (is_valid IN (0, 1))"
        )
        with self._connection() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    candidate_name TEXT NOT NULL,
                    candidate_email TEXT NOT NULL,
                    candidate_facts_json TEXT NOT NULL,
                    document_facts_json TEXT,
                    document_name TEXT NOT NULL,
                    document_sha256 TEXT NOT NULL,
                    extraction_method TEXT NOT NULL,
                    extraction_warnings_json TEXT NOT NULL DEFAULT '[]',
                    consent_confirmed {consent_type},
                    consent_at TEXT NOT NULL,
                    verifier_name TEXT NOT NULL DEFAULT '',
                    verifier_phone TEXT NOT NULL DEFAULT '',
                    employer_response_status TEXT NOT NULL,
                    employer_facts_json TEXT,
                    verification_status TEXT NOT NULL,
                    state TEXT NOT NULL,
                    hr_conclusion TEXT NOT NULL DEFAULT '',
                    hr_rationale TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id {generated_id},
                    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id {generated_id},
                    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    direction TEXT NOT NULL,
                    body TEXT NOT NULL,
                    twilio_sid TEXT UNIQUE,
                    delivery_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS questionnaire_sessions (
                    case_id TEXT PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
                    current_step TEXT NOT NULL,
                    answers_json TEXT NOT NULL DEFAULT '{{}}',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS questionnaire_answers (
                    id {generated_id},
                    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    question_step TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    is_valid {valid_type},
                    twilio_sid TEXT UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS verification_completions (
                    case_id TEXT PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
                    verification_status TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS report_deliveries (
                    case_id TEXT PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    sent_at TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_cases_updated_at
                    ON cases(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_case_id
                    ON audit_events(case_id, id);
                CREATE INDEX IF NOT EXISTS idx_questionnaire_answers_case_id
                    ON questionnaire_answers(case_id, id);
                """
            )
            # Backfill pre-feature terminal cases without changing their audit trail.
            connection.execute(
                """
                INSERT INTO verification_completions (
                    case_id, verification_status, completed_at
                )
                SELECT case_id, verification_status, updated_at
                FROM cases
                WHERE verification_status IN (?, ?, ?)
                ON CONFLICT(case_id) DO NOTHING
                """,
                (
                    VerificationStatus.VERIFIED.value,
                    VerificationStatus.DISCREPANCY_FOUND.value,
                    VerificationStatus.UNABLE_TO_VERIFY.value,
                ),
            )

    def create_case(
        self,
        *,
        candidate_name: str,
        candidate_email: str,
        candidate_facts: EmploymentFacts,
        document_facts: EmploymentFacts | None,
        document_name: str,
        document_sha256: str,
        extraction_method: str,
        extraction_warnings: tuple[str, ...],
        consent_confirmed: bool,
    ) -> str:
        if not consent_confirmed:
            raise ValidationError(("Candidate consent is required.",))

        case_id = f"BV-{uuid4().hex[:8].upper()}"
        timestamp = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO cases (
                    case_id, candidate_name, candidate_email, candidate_facts_json,
                    document_facts_json, document_name, document_sha256,
                    extraction_method, extraction_warnings_json, consent_confirmed,
                    consent_at, employer_response_status, verification_status, state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    candidate_name,
                    candidate_email,
                    json.dumps(candidate_facts.to_dict()),
                    _facts_to_json(document_facts),
                    document_name,
                    document_sha256,
                    extraction_method,
                    json.dumps(extraction_warnings),
                    timestamp,
                    EmployerResponseStatus.NOT_STARTED.value,
                    VerificationStatus.PENDING.value,
                    CaseState.SUBMITTED.value,
                    timestamp,
                    timestamp,
                ),
            )
            self._add_event(
                connection,
                case_id,
                "CASE_SUBMITTED",
                "Candidate supplied employment facts and a supporting document.",
                timestamp,
            )
            self._add_event(
                connection,
                case_id,
                "CONSENT_RECORDED",
                "Candidate consented to former-employer verification.",
                timestamp,
            )
            self._add_event(
                connection,
                case_id,
                "DOCUMENT_EXTRACTED",
                f"Extracted approved employment fields using {extraction_method}.",
                timestamp,
            )
        return case_id

    def list_cases(self) -> list[CaseRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM cases ORDER BY updated_at DESC"
            ).fetchall()
        return [_row_to_case(row) for row in rows]

    def get_case(self, case_id: str) -> CaseRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return _row_to_case(row) if row else None

    def set_verifier_contact(self, case_id: str, name: str, phone: str) -> None:
        name = name.strip()
        phone = phone.strip()
        if not name or not phone:
            raise ValidationError(("Verifier name and WhatsApp number are required.",))
        timestamp = utc_now()
        with self._connection() as connection:
            self._require_case(connection, case_id)
            connection.execute(
                """
                UPDATE cases
                SET verifier_name = ?, verifier_phone = ?, state = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (name, phone, CaseState.READY_FOR_OUTREACH.value, timestamp, case_id),
            )
            self._add_event(
                connection,
                case_id,
                "VERIFIER_CONTACT_ADDED",
                "HR recorded the approved former-employer contact.",
                timestamp,
            )

    def mark_outreach_sent(
        self,
        case_id: str,
        *,
        body: str,
        twilio_sid: str,
        delivery_status: str,
    ) -> None:
        timestamp = utc_now()
        with self._connection() as connection:
            case = self._require_case(connection, case_id)
            if not case["consent_confirmed"]:
                raise ValidationError(
                    ("Outreach is blocked because consent is missing.",)
                )
            if not case["verifier_phone"]:
                raise ValidationError(
                    ("Add an approved verifier contact before outreach.",)
                )
            connection.execute(
                """
                UPDATE cases
                SET employer_response_status = ?, state = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (
                    EmployerResponseStatus.PENDING.value,
                    CaseState.OUTREACH_SENT.value,
                    timestamp,
                    case_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO messages (
                    case_id, direction, body, twilio_sid, delivery_status, created_at
                ) VALUES (?, 'OUTBOUND', ?, ?, ?, ?)
                """,
                (case_id, body, twilio_sid or None, delivery_status, timestamp),
            )
            self._add_event(
                connection,
                case_id,
                "WHATSAPP_OUTREACH_SENT",
                f"Verification request queued with status {delivery_status}.",
                timestamp,
            )

    def start_questionnaire(self, case_id: str) -> None:
        """Start or restart the guided former-employer questionnaire."""

        timestamp = utc_now()
        with self._connection() as connection:
            row = self._require_case(connection, case_id)
            if not row["consent_confirmed"]:
                raise ValidationError(
                    ("Candidate consent is required before outreach.",)
                )
            connection.execute(
                "DELETE FROM questionnaire_answers WHERE case_id = ?", (case_id,)
            )
            connection.execute(
                """
                INSERT INTO questionnaire_sessions (
                    case_id, current_step, answers_json, started_at, completed_at, updated_at
                ) VALUES (?, ?, '{}', ?, NULL, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    current_step = excluded.current_step,
                    answers_json = excluded.answers_json,
                    started_at = excluded.started_at,
                    completed_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (case_id, QuestionnaireStep.AUTHORIZATION.value, timestamp, timestamp),
            )
            self._add_event(
                connection,
                case_id,
                "QUESTIONNAIRE_STARTED",
                "Guided former-employer questionnaire started at authorization.",
                timestamp,
            )

    def record_questionnaire_reply(
        self,
        case_id: str,
        *,
        body: str,
        twilio_sid: str = "",
    ) -> QuestionnaireProgress:
        """Save one reply, then return the next WhatsApp prompt or completion notice."""

        timestamp = utc_now()
        with self._connection() as connection:
            if twilio_sid:
                duplicate = connection.execute(
                    "SELECT 1 FROM messages WHERE twilio_sid = ?", (twilio_sid,)
                ).fetchone()
                if duplicate:
                    return QuestionnaireProgress(
                        reply="This response was already recorded.", duplicate=True
                    )

            case = self._require_case(connection, case_id)
            session = connection.execute(
                "SELECT * FROM questionnaire_sessions WHERE case_id = ?", (case_id,)
            ).fetchone()
            if session is None:
                raise ValidationError(
                    ("No active questionnaire exists for this case.",)
                )

            step = QuestionnaireStep(session["current_step"])
            if step is QuestionnaireStep.COMPLETE:
                return QuestionnaireProgress(
                    reply="This questionnaire is already complete."
                )

            prompt = prompt_for(case_id, case["candidate_name"], step)
            resolution = InputAssistant().resolve(step, body)
            validation = resolution.validation
            # Store only the validated field value. The source sentence can contain
            # unrelated personal details and is not needed for the comparison.
            stored_answer = validation.value if not validation.error else ""
            stored_message = stored_answer or "[Invalid answer: value not retained]"
            connection.execute(
                """
                INSERT INTO messages (
                    case_id, direction, body, twilio_sid, delivery_status, created_at
                ) VALUES (?, 'INBOUND', ?, ?, 'RECEIVED', ?)
                """,
                (case_id, stored_message, twilio_sid or None, timestamp),
            )
            connection.execute(
                """
                INSERT INTO questionnaire_answers (
                    case_id, question_step, prompt, answer, is_valid, twilio_sid, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    step.value,
                    prompt,
                    stored_answer,
                    not validation.error,
                    twilio_sid or None,
                    timestamp,
                ),
            )

            if validation.declined:
                self._complete_questionnaire(
                    connection,
                    case_id,
                    EmployerResponseStatus.DECLINED,
                    None,
                    timestamp,
                )
                connection.execute(
                    """
                    UPDATE questionnaire_sessions
                    SET current_step = ?, completed_at = ?, updated_at = ?
                    WHERE case_id = ?
                    """,
                    (QuestionnaireStep.COMPLETE.value, timestamp, timestamp, case_id),
                )
                return QuestionnaireProgress(
                    reply="Thank you. Your decision was recorded for HR review.",
                    completed=True,
                )

            if validation.error:
                retry = f"{validation.error}\n\n{prompt}"
                self._record_questionnaire_prompt(connection, case_id, retry, timestamp)
                self._add_event(
                    connection,
                    case_id,
                    "QUESTIONNAIRE_ANSWER_INVALID",
                    f"Invalid answer for {step.value}; retry requested.",
                    timestamp,
                )
                return QuestionnaireProgress(reply=retry)

            if resolution.ai_used:
                self._add_event(
                    connection,
                    case_id,
                    "AI_INPUT_NORMALIZED",
                    f"AI normalized the verifier's {step.value} answer: "
                    f"{resolution.ai_note[:240]}",
                    timestamp,
                )

            answers = json.loads(session["answers_json"])
            if step is not QuestionnaireStep.AUTHORIZATION:
                answers[_answer_key(step)] = validation.value
            following = next_step(step)
            if following is QuestionnaireStep.COMPLETE:
                employer_facts = EmploymentFacts(**answers)
                self._complete_questionnaire(
                    connection,
                    case_id,
                    EmployerResponseStatus.RECEIVED,
                    employer_facts,
                    timestamp,
                )
                connection.execute(
                    """
                    UPDATE questionnaire_sessions
                    SET current_step = ?, answers_json = ?, completed_at = ?, updated_at = ?
                    WHERE case_id = ?
                    """,
                    (
                        QuestionnaireStep.COMPLETE.value,
                        json.dumps(answers),
                        timestamp,
                        timestamp,
                        case_id,
                    ),
                )
                return QuestionnaireProgress(
                    reply="Thank you. Your response was recorded for HR review.",
                    completed=True,
                )

            next_prompt = prompt_for(case_id, case["candidate_name"], following)
            connection.execute(
                """
                UPDATE questionnaire_sessions
                SET current_step = ?, answers_json = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (following.value, json.dumps(answers), timestamp, case_id),
            )
            self._record_questionnaire_prompt(
                connection, case_id, next_prompt, timestamp
            )
            self._add_event(
                connection,
                case_id,
                "QUESTIONNAIRE_ANSWER_RECORDED",
                f"Recorded answer for {step.value}.",
                timestamp,
            )
            return QuestionnaireProgress(reply=next_prompt)

    def record_employer_response(
        self,
        case_id: str,
        *,
        response_status: EmployerResponseStatus,
        employer_facts: EmploymentFacts | None,
        body: str,
        twilio_sid: str = "",
    ) -> bool:
        """Persist a response once. Returns False for a duplicate Twilio message SID."""

        timestamp = utc_now()
        with self._connection() as connection:
            if twilio_sid:
                duplicate = connection.execute(
                    "SELECT 1 FROM messages WHERE twilio_sid = ?", (twilio_sid,)
                ).fetchone()
                if duplicate:
                    return False

            row = self._require_case(connection, case_id)
            candidate = EmploymentFacts(**json.loads(row["candidate_facts_json"]))
            document = _facts_from_json(row["document_facts_json"])
            comparisons = compare_sources(candidate, document, employer_facts)
            status = derive_verification_status(response_status, comparisons)

            connection.execute(
                """
                UPDATE cases
                SET employer_response_status = ?, employer_facts_json = ?,
                    verification_status = ?, state = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (
                    response_status.value,
                    _facts_to_json(employer_facts),
                    status.value,
                    CaseState.RESPONSE_RECEIVED.value,
                    timestamp,
                    case_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO messages (
                    case_id, direction, body, twilio_sid, delivery_status, created_at
                ) VALUES (?, 'INBOUND', ?, ?, 'RECEIVED', ?)
                """,
                (case_id, body, twilio_sid or None, timestamp),
            )
            self._add_event(
                connection,
                case_id,
                "EMPLOYER_RESPONSE_RECORDED",
                f"Former-employer response status: {response_status.value}.",
                timestamp,
            )
            self._add_event(
                connection,
                case_id,
                "EVIDENCE_COMPARED",
                f"Three-source result: {status.value}.",
                timestamp,
            )
            self._record_verification_completion(connection, case_id, status, timestamp)
        return True

    def close_case(
        self,
        case_id: str,
        conclusion: HRConclusion,
        rationale: str,
    ) -> None:
        rationale = rationale.strip()
        if not rationale:
            raise ValidationError(("HR rationale is required.",))
        timestamp = utc_now()
        with self._connection() as connection:
            row = self._require_case(connection, case_id)
            status = VerificationStatus(row["verification_status"])
            if conclusion not in allowed_conclusions(status):
                raise ValidationError(
                    ("The selected conclusion is not valid for this evidence.",)
                )
            connection.execute(
                """
                UPDATE cases
                SET hr_conclusion = ?, hr_rationale = ?, state = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (
                    conclusion.value,
                    rationale,
                    CaseState.HR_REVIEWED.value,
                    timestamp,
                    case_id,
                ),
            )
            self._add_event(
                connection,
                case_id,
                "HR_CONCLUSION_RECORDED",
                f"{conclusion.value}: {rationale}",
                timestamp,
            )

    def events_for_case(self, case_id: str) -> list[dict[str, str]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_type, detail, created_at
                FROM audit_events WHERE case_id = ? ORDER BY id
                """,
                (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def completed_verification_count(self) -> int:
        """Return the durable count of finished verifications, regardless of result."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS completed_total FROM verification_completions"
            ).fetchone()
        return int(row["completed_total"])

    def claim_report_delivery(self, case_id: str, recipient: str) -> bool:
        """Reserve a completed case for one email send, avoiding duplicate webhooks."""

        recipient = recipient.strip()
        if not recipient:
            raise ValidationError(("An HR report recipient email is required.",))
        timestamp = utc_now()
        with self._connection() as connection:
            row = self._require_case(connection, case_id)
            status = VerificationStatus(row["verification_status"])
            if status is VerificationStatus.PENDING:
                raise ValidationError(("A report can be emailed after verification completes.",))
            existing = connection.execute(
                "SELECT 1 FROM report_deliveries WHERE case_id = ?", (case_id,)
            ).fetchone()
            if existing:
                return False
            connection.execute(
                """
                INSERT INTO report_deliveries (
                    case_id, recipient, status, error, created_at, sent_at
                ) VALUES (?, ?, 'SENDING', '', ?, '')
                """,
                (case_id, recipient, timestamp),
            )
            self._add_event(
                connection,
                case_id,
                "HR_REPORT_EMAIL_QUEUED",
                "Completed verification report queued for HR email delivery.",
                timestamp,
            )
        return True

    def mark_report_delivery_sent(self, case_id: str) -> None:
        timestamp = utc_now()
        with self._connection() as connection:
            self._require_case(connection, case_id)
            connection.execute(
                """
                UPDATE report_deliveries SET status = 'SENT', error = '', sent_at = ?
                WHERE case_id = ?
                """,
                (timestamp, case_id),
            )
            self._add_event(
                connection,
                case_id,
                "HR_REPORT_EMAIL_SENT",
                "Completed verification report emailed to the configured HR recipient.",
                timestamp,
            )

    def mark_report_delivery_failed(self, case_id: str, error: str) -> None:
        timestamp = utc_now()
        with self._connection() as connection:
            self._require_case(connection, case_id)
            connection.execute(
                """
                UPDATE report_deliveries SET status = 'FAILED', error = ?
                WHERE case_id = ?
                """,
                (error.strip()[:500], case_id),
            )
            self._add_event(
                connection,
                case_id,
                "HR_REPORT_EMAIL_FAILED",
                "Completed verification report could not be emailed; HR follow-up is required.",
                timestamp,
            )

    def report_delivery_for_case(self, case_id: str) -> ReportDelivery | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM report_deliveries WHERE case_id = ?", (case_id,)
            ).fetchone()
        if row is None:
            return None
        return ReportDelivery(
            case_id=row["case_id"],
            recipient=row["recipient"],
            status=row["status"],
            error=row["error"],
            created_at=row["created_at"],
            sent_at=row["sent_at"],
        )

    def update_message_status(self, twilio_sid: str, delivery_status: str) -> bool:
        timestamp = utc_now()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT case_id FROM messages WHERE twilio_sid = ?", (twilio_sid,)
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                """
                UPDATE messages SET delivery_status = ? WHERE twilio_sid = ?
                """,
                (delivery_status, twilio_sid),
            )
            self._add_event(
                connection,
                row["case_id"],
                "WHATSAPP_DELIVERY_UPDATED",
                f"Twilio delivery status: {delivery_status}.",
                timestamp,
            )
        return True

    def _complete_questionnaire(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        response_status: EmployerResponseStatus,
        employer_facts: EmploymentFacts | None,
        timestamp: str,
    ) -> None:
        row = self._require_case(connection, case_id)
        candidate = EmploymentFacts(**json.loads(row["candidate_facts_json"]))
        document = _facts_from_json(row["document_facts_json"])
        comparisons = compare_sources(candidate, document, employer_facts)
        status = derive_verification_status(response_status, comparisons)
        connection.execute(
            """
            UPDATE cases
            SET employer_response_status = ?, employer_facts_json = ?,
                verification_status = ?, state = ?, updated_at = ?
            WHERE case_id = ?
            """,
            (
                response_status.value,
                _facts_to_json(employer_facts),
                status.value,
                CaseState.RESPONSE_RECEIVED.value,
                timestamp,
                case_id,
            ),
        )
        self._add_event(
            connection,
            case_id,
            "EMPLOYER_RESPONSE_RECORDED",
            f"Former-employer response status: {response_status.value}.",
            timestamp,
        )
        self._add_event(
            connection,
            case_id,
            "EVIDENCE_COMPARED",
            f"Three-source result: {status.value}.",
            timestamp,
        )
        self._record_verification_completion(connection, case_id, status, timestamp)

    def _record_questionnaire_prompt(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        prompt: str,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO messages (
                case_id, direction, body, twilio_sid, delivery_status, created_at
            ) VALUES (?, 'OUTBOUND', ?, NULL, 'GENERATED', ?)
            """,
            (case_id, prompt, timestamp),
        )

    def _record_verification_completion(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        status: VerificationStatus,
        timestamp: str,
    ) -> None:
        """Persist a one-per-case completion marker for all terminal outcomes."""

        existing = connection.execute(
            "SELECT 1 FROM verification_completions WHERE case_id = ?", (case_id,)
        ).fetchone()
        if existing:
            return
        connection.execute(
            """
            INSERT INTO verification_completions (case_id, verification_status, completed_at)
            VALUES (?, ?, ?)
            """,
            (case_id, status.value, timestamp),
        )
        self._add_event(
            connection,
            case_id,
            "VERIFICATION_COUNTED",
            f"Verification completion recorded with result {status.value}.",
            timestamp,
        )

    def _require_case(
        self, connection: sqlite3.Connection, case_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown case: {case_id}")
        return row

    @staticmethod
    def _add_event(
        connection: sqlite3.Connection,
        case_id: str,
        event_type: str,
        detail: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (case_id, event_type, detail, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (case_id, event_type, detail, created_at),
        )


def _row_to_case(row: sqlite3.Row) -> CaseRecord:
    return CaseRecord(
        case_id=row["case_id"],
        candidate_name=row["candidate_name"],
        candidate_email=row["candidate_email"],
        candidate_facts=EmploymentFacts(**json.loads(row["candidate_facts_json"])),
        document_facts=_facts_from_json(row["document_facts_json"]),
        document_name=row["document_name"],
        document_sha256=row["document_sha256"],
        extraction_method=row["extraction_method"],
        extraction_warnings=tuple(json.loads(row["extraction_warnings_json"])),
        consent_confirmed=bool(row["consent_confirmed"]),
        consent_at=row["consent_at"],
        verifier_name=row["verifier_name"],
        verifier_phone=row["verifier_phone"],
        employer_response_status=EmployerResponseStatus(
            row["employer_response_status"]
        ),
        employer_facts=_facts_from_json(row["employer_facts_json"]),
        verification_status=VerificationStatus(row["verification_status"]),
        state=CaseState(row["state"]),
        hr_conclusion=row["hr_conclusion"],
        hr_rationale=row["hr_rationale"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _facts_to_json(facts: EmploymentFacts | None) -> str | None:
    return json.dumps(facts.to_dict()) if facts else None


def _facts_from_json(value: str | None) -> EmploymentFacts | None:
    return EmploymentFacts(**json.loads(value)) if value else None


def _answer_key(step: QuestionnaireStep) -> str:
    return {
        QuestionnaireStep.EMPLOYER_NAME: "employer_name",
        QuestionnaireStep.JOB_TITLE: "job_title",
        QuestionnaireStep.START_DATE: "start_date",
        QuestionnaireStep.END_DATE: "end_date",
        QuestionnaireStep.EMPLOYEE_ID: "employee_id",
    }[step]
