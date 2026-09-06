from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app
from verisure.domain import (
    EmployerResponseStatus,
    VerificationStatus,
    create_employment_facts,
)
from verisure.messaging import TwilioSettings
from verisure.storage import CaseStore


class WebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CaseStore(Path(self.temp_dir.name) / "api-test.db")
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
        self.store.set_verifier_contact(self.case_id, "Riya Mehta", "+919876543210")
        self.store.mark_outreach_sent(
            self.case_id,
            body="request",
            twilio_sid="SM-OUTBOUND",
            delivery_status="queued",
        )
        self.store.start_questionnaire(self.case_id)
        settings = TwilioSettings(
            account_sid="test",
            auth_token="test",
            whatsapp_from="whatsapp:+14155238886",
            public_base_url="https://example.test",
            validate_signature=False,
        )
        self.client = TestClient(create_app(self.store, settings))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_guided_whatsapp_replies_update_case(self) -> None:
        responses = []
        for index, body in enumerate(
            (
                "YES",
                "Northstar Labs",
                "Senior Software Engineer",
                "2022-01",
                "2024-03",
                "NS-1042",
            ),
            start=1,
        ):
            responses.append(
                self.client.post(
                    "/webhook/whatsapp",
                    data={
                        "From": "whatsapp:+919876543210",
                        "Body": body,
                        "MessageSid": f"SM-INBOUND-{index}",
                    },
                )
            )

        case = self.store.get_case(self.case_id)
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertIn("Question 2 of 6", responses[0].text)
        self.assertIn("response was recorded", responses[-1].text)
        self.assertIs(case.employer_response_status, EmployerResponseStatus.RECEIVED)
        self.assertIs(case.verification_status, VerificationStatus.VERIFIED)

    def test_unapproved_sender_cannot_update_case(self) -> None:
        response = self.client.post(
            "/webhooks/twilio/whatsapp",
            data={
                "From": "whatsapp:+919999999999",
                "Body": f"CASE: {self.case_id}\nSTATUS: DECLINED",
                "MessageSid": "SM-UNAPPROVED",
            },
        )

        case = self.store.get_case(self.case_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("not approved", response.text)
        self.assertIs(case.employer_response_status, EmployerResponseStatus.PENDING)


if __name__ == "__main__":
    unittest.main()
