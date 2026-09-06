from __future__ import annotations

import unittest
from unittest.mock import patch

from verisure.input_intelligence import (
    InputAssistant,
    InputAssistantSettings,
)
from verisure.questionnaire import QuestionnaireStep


class InputIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assistant = InputAssistant(
            InputAssistantSettings(
                api_key="test", model="test-model", base_url="", enabled=True
            )
        )

    def test_valid_answer_never_calls_ai(self) -> None:
        with patch.object(self.assistant, "_repair") as repair:
            result = self.assistant.resolve(QuestionnaireStep.START_DATE, "2022-01")

        self.assertFalse(result.ai_used)
        self.assertEqual(result.validation.value, "2022-01")
        repair.assert_not_called()

    def test_ai_repair_is_accepted_only_after_local_validation(self) -> None:
        with patch.object(
            self.assistant, "_repair", return_value=("2022-01", "Converted month name.")
        ):
            result = self.assistant.resolve(QuestionnaireStep.START_DATE, "January 2022")

        self.assertTrue(result.ai_used)
        self.assertEqual(result.validation.value, "2022-01")

    def test_ai_extracts_only_the_month_from_a_sentence(self) -> None:
        with patch.object(
            self.assistant,
            "_repair",
            return_value=("2020-01", "Extracted the stated start month."),
        ):
            result = self.assistant.resolve(
                QuestionnaireStep.START_DATE,
                "It is starting from 1st January 2020.",
            )

        self.assertTrue(result.ai_used)
        self.assertEqual(result.validation.value, "2020-01")

    def test_ai_cannot_make_an_invalid_date_valid(self) -> None:
        with patch.object(
            self.assistant, "_repair", return_value=("sometime last year", "Guess")
        ):
            result = self.assistant.resolve(QuestionnaireStep.START_DATE, "last year")

        self.assertFalse(result.ai_used)
        self.assertTrue(result.validation.error)


if __name__ == "__main__":
    unittest.main()
