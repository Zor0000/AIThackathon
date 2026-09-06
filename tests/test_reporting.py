from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from verisure.domain import EmployerResponseStatus, create_employment_facts
from verisure.report_email import (
    ReportEmailSettings,
    build_report_email_message,
    dispatch_completed_report,
)
from verisure.reporting import build_verification_report_pdf
from verisure.storage import CaseStore


class FakeReportEmailGateway:
    def __init__(self) -> None:
        self.settings = ReportEmailSettings(
            host="smtp.example.test",
            port=587,
            username="user",
            password="secret",
            sender="verisure@example.test",
            recipient="hr@example.test",
            use_tls=True,
        )
        self.sent: list[dict[str, object]] = []

    def send(self, **kwargs: object) -> str:
        self.sent.append(kwargs)
        return self.settings.recipient


class ReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CaseStore(Path(self.temp_dir.name) / "reporting.db")
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
            document_name="experience.pdf",
            document_sha256="abc123",
            extraction_method="test",
            extraction_warnings=(),
            consent_confirmed=True,
        )
        self.store.record_employer_response(
            self.case_id,
            response_status=EmployerResponseStatus.RECEIVED,
            employer_facts=self.facts,
            body="structured response",
            twilio_sid="SM-REPORT-1",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pdf_contains_three_source_comparison(self) -> None:
        case = self.store.get_case(self.case_id)
        assert case is not None
        from verisure.domain import compare_sources

        pdf = build_verification_report_pdf(
            case=case,
            comparisons=compare_sources(
                case.candidate_facts, case.document_facts, case.employer_facts
            ),
            generated_at="2026-09-06T12:00:00+00:00",
        )
        output = Path(self.temp_dir.name) / "report.pdf"
        output.write_bytes(pdf)
        extracted = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn("Evidence comparison", extracted)
        self.assertIn("Former employer", extracted)
        self.assertIn("Northstar Labs", extracted)

    def test_completed_report_is_emailed_once(self) -> None:
        gateway = FakeReportEmailGateway()

        first = dispatch_completed_report(self.store, self.case_id, gateway)
        repeated = dispatch_completed_report(self.store, self.case_id, gateway)

        self.assertEqual(first.status, "SENT")
        self.assertEqual(repeated.status, "SENT")
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(self.store.report_delivery_for_case(self.case_id).status, "SENT")

    def test_hr_email_has_context_and_human_review_instruction(self) -> None:
        message = build_report_email_message(
            sender="verisure@example.test",
            recipient="hr@example.test",
            case_id="BV-TEST1234",
            candidate_name="Aarav Shah",
            verification_status="VERIFIED",
            pdf=b"example-pdf",
        )
        body = message.get_body(preferencelist=("plain",))

        self.assertEqual(message["Subject"], "HR review needed: employment verification — BV-TEST1234")
        self.assertEqual(message["To"], "hr@example.test")
        self.assertIsNotNone(body)
        assert body is not None
        self.assertIn("Candidate: Aarav Shah", body.get_content())
        self.assertIn("Evidence status: VERIFIED", body.get_content())
        self.assertIn("not an automated hiring decision", body.get_content())
        attachments = list(message.iter_attachments())
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "bv-test1234-verification-report.pdf")


if __name__ == "__main__":
    unittest.main()
