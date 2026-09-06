from __future__ import annotations

import unittest

from verisure.extraction import ExtractionError, extract_document


class ExtractionTests(unittest.TestCase):
    def test_labelled_text_document_is_extracted(self) -> None:
        result = extract_document(
            "experience.txt",
            b"""Employer: Northstar Labs
Job Title: Senior Software Engineer
Employee ID: NS-1042
Start Date: January 2022
End Date: March 2024
""",
        )

        self.assertEqual(result.facts.employer_name, "Northstar Labs")
        self.assertEqual(result.facts.start_date, "2022-01")
        self.assertEqual(result.facts.end_date, "2024-03")
        self.assertEqual(len(result.document_sha256), 64)
        self.assertEqual(result.warnings, ())

    def test_employee_name_is_extracted_when_stated_in_pdf_text(self) -> None:
        result = extract_document(
            "experience.txt",
            b"""Employment record for Aarav Shah.
Employer: Northstar Labs
Job Title: Senior Software Engineer
Start Date: January 2022
End Date: March 2024
""",
        )

        self.assertEqual(result.candidate_name, "Aarav Shah")

    def test_missing_fields_are_reported_for_hr_review(self) -> None:
        result = extract_document("experience.txt", b"Employer: Northstar Labs")

        self.assertTrue(result.warnings)
        self.assertEqual(result.facts.job_title, "")

    def test_unsupported_document_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            extract_document("experience.exe", b"not a document")


if __name__ == "__main__":
    unittest.main()
