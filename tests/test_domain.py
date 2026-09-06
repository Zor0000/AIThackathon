from __future__ import annotations

import unittest

from verisure.domain import (
    EmployerResponseStatus,
    FieldResult,
    HRConclusion,
    VerificationStatus,
    allowed_conclusions,
    compare_sources,
    create_employment_facts,
    derive_verification_status,
    render_markdown_report,
)


def facts(**overrides: str):
    values = {
        "employer_name": "Northstar Labs",
        "job_title": "Senior Software Engineer",
        "start_date": "2022-01",
        "end_date": "2024-03",
        "employee_id": "NS-1042",
        **overrides,
    }
    return create_employment_facts(values)


class DomainTests(unittest.TestCase):
    def test_three_matching_sources_are_verified(self) -> None:
        rows = compare_sources(facts(), facts(), facts())

        self.assertTrue(all(row.result is FieldResult.MATCH for row in rows))
        self.assertIs(
            derive_verification_status(EmployerResponseStatus.RECEIVED, rows),
            VerificationStatus.VERIFIED,
        )

    def test_employer_difference_is_a_discrepancy(self) -> None:
        rows = compare_sources(facts(), facts(), facts(job_title="Software Engineer"))

        title_row = next(row for row in rows if row.field == "Job title")
        self.assertIs(title_row.result, FieldResult.MISMATCH)
        self.assertIs(
            derive_verification_status(EmployerResponseStatus.RECEIVED, rows),
            VerificationStatus.DISCREPANCY_FOUND,
        )

    def test_employer_name_allows_spacing_and_one_character_variation(self) -> None:
        candidate = facts(employer_name="Northstar Caps")
        employer = facts(employer_name="north star cap")

        rows = compare_sources(candidate, candidate, employer)

        employer_row = next(row for row in rows if row.field == "Employer")
        self.assertIs(employer_row.result, FieldResult.MATCH)
        self.assertIs(
            derive_verification_status(EmployerResponseStatus.RECEIVED, rows),
            VerificationStatus.VERIFIED,
        )

    def test_substantially_different_employer_remains_a_mismatch(self) -> None:
        candidate = facts(employer_name="Northstar Caps")
        employer = facts(employer_name="Southwind Industries")

        rows = compare_sources(candidate, candidate, employer)

        employer_row = next(row for row in rows if row.field == "Employer")
        self.assertIs(employer_row.result, FieldResult.MISMATCH)

    def test_document_difference_requires_review(self) -> None:
        rows = compare_sources(facts(), facts(end_date="2024-02"), facts())

        end_row = next(row for row in rows if row.field == "End date")
        self.assertIs(end_row.result, FieldResult.NEEDS_REVIEW)

    def test_declined_response_is_unable_to_verify(self) -> None:
        rows = compare_sources(facts(), facts(), None)

        self.assertTrue(all(row.result is FieldResult.NOT_PROVIDED for row in rows))
        self.assertIs(
            derive_verification_status(EmployerResponseStatus.DECLINED, rows),
            VerificationStatus.UNABLE_TO_VERIFY,
        )

    def test_conclusions_are_constrained_by_evidence(self) -> None:
        self.assertNotIn(
            HRConclusion.INFORMATION_VERIFIED,
            allowed_conclusions(VerificationStatus.DISCREPANCY_FOUND),
        )
        self.assertEqual(allowed_conclusions(VerificationStatus.PENDING), ())

    def test_report_excludes_contact_information(self) -> None:
        report = render_markdown_report(
            case={
                "case_id": "BV-TEST0001",
                "candidate_name": "Aarav Shah",
                "verification_status": "VERIFIED",
                "hr_conclusion": "Information verified",
                "hr_rationale": "All approved facts match.",
                "document_name": "experience.pdf",
                "document_sha256": "abc123",
                "verifier_phone": "+919999999999",
            },
            comparisons=compare_sources(facts(), facts(), facts()),
            events=[
                {
                    "event_type": "CASE_SUBMITTED",
                    "detail": "Case submitted.",
                    "created_at": "2026-09-06T12:00:00+00:00",
                }
            ],
            generated_at="2026-09-06T12:01:00+00:00",
        )

        self.assertIn("Information verified", report)
        self.assertIn("| Job title |", report)
        self.assertNotIn("+919999999999", report)


if __name__ == "__main__":
    unittest.main()
