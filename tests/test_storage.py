from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verisure.domain import (
    EmployerResponseStatus,
    HRConclusion,
    VerificationStatus,
    create_employment_facts,
)
from verisure.input_intelligence import AnswerResolution
from verisure.questionnaire import AnswerValidation
from verisure.storage import CaseStore


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CaseStore(Path(self.temp_dir.name) / "test.db")
        self.facts = create_employment_facts(
            {
                "employer_name": "Northstar Labs",
                "job_title": "Senior Software Engineer",
                "start_date": "2022-01",
                "end_date": "2024-03",
                "employee_id": "NS-1042",
            }
        )
        self.case_id = self.store.create_case(
            candidate_name="Aarav Shah",
            candidate_email="aarav@example.test",
            candidate_facts=self.facts,
            document_facts=self.facts,
            document_name="experience.txt",
            document_sha256="abc123",
            extraction_method="test",
            extraction_warnings=(),
            consent_confirmed=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_full_verified_case_lifecycle(self) -> None:
        self.store.set_verifier_contact(self.case_id, "Riya Mehta", "+919876543210")
        self.store.mark_outreach_sent(
            self.case_id,
            body="verification request",
            twilio_sid="SM-OUT-1",
            delivery_status="queued",
        )
        created = self.store.record_employer_response(
            self.case_id,
            response_status=EmployerResponseStatus.RECEIVED,
            employer_facts=self.facts,
            body="structured response",
            twilio_sid="SM-IN-1",
        )
        duplicate = self.store.record_employer_response(
            self.case_id,
            response_status=EmployerResponseStatus.RECEIVED,
            employer_facts=self.facts,
            body="structured response",
            twilio_sid="SM-IN-1",
        )
        self.store.close_case(
            self.case_id,
            HRConclusion.INFORMATION_VERIFIED,
            "All three sources match.",
        )

        case = self.store.get_case(self.case_id)
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertIs(case.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(self.store.completed_verification_count(), 1)
        self.assertEqual(case.hr_conclusion, "Information verified")
        self.assertEqual(
            self.store.events_for_case(self.case_id)[-1]["event_type"],
            "HR_CONCLUSION_RECORDED",
        )

    def test_declined_verification_is_counted_once(self) -> None:
        self.store.set_verifier_contact(self.case_id, "Riya Mehta", "+919876543210")
        self.store.mark_outreach_sent(
            self.case_id,
            body="verification request",
            twilio_sid="SM-OUT-DECLINED",
            delivery_status="queued",
        )
        self.store.record_employer_response(
            self.case_id,
            response_status=EmployerResponseStatus.DECLINED,
            employer_facts=None,
            body="declined",
            twilio_sid="SM-IN-DECLINED-1",
        )
        self.store.record_employer_response(
            self.case_id,
            response_status=EmployerResponseStatus.DECLINED,
            employer_facts=None,
            body="same terminal outcome",
            twilio_sid="SM-IN-DECLINED-2",
        )

        case = self.store.get_case(self.case_id)
        self.assertIs(case.verification_status, VerificationStatus.UNABLE_TO_VERIFY)
        self.assertEqual(self.store.completed_verification_count(), 1)

    def test_ai_normalized_reply_does_not_store_the_source_sentence(self) -> None:
        self.store.set_verifier_contact(self.case_id, "Riya Mehta", "+919876543210")
        self.store.mark_outreach_sent(
            self.case_id,
            body="verification request",
            twilio_sid="SM-OUT-MINIMIZED",
            delivery_status="queued",
        )
        self.store.start_questionnaire(self.case_id)
        self.store.record_questionnaire_reply(self.case_id, body="YES")
        self.store.record_questionnaire_reply(self.case_id, body="Northstar Labs")
        self.store.record_questionnaire_reply(
            self.case_id, body="Senior Software Engineer"
        )
        with patch(
            "verisure.storage.InputAssistant.resolve",
            return_value=AnswerResolution(
                AnswerValidation("2020-01"),
                ai_used=True,
                ai_note="Extracted the stated start month.",
            ),
        ):
            self.store.record_questionnaire_reply(
                self.case_id,
                body="It is starting from 1st January 2020.",
            )

        with self.store._connection() as connection:
            row = connection.execute(
                """
                SELECT body FROM messages
                WHERE case_id = ? AND direction = 'INBOUND'
                ORDER BY id DESC LIMIT 1
                """,
                (self.case_id,),
            ).fetchone()
        self.assertEqual(row["body"], "2020-01")


if __name__ == "__main__":
    unittest.main()
