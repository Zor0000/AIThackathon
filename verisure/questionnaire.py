"""Guided WhatsApp questionnaire prompts and field-level validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class QuestionnaireStep(StrEnum):
    AUTHORIZATION = "AUTHORIZATION"
    EMPLOYER_NAME = "EMPLOYER_NAME"
    JOB_TITLE = "JOB_TITLE"
    START_DATE = "START_DATE"
    END_DATE = "END_DATE"
    EMPLOYEE_ID = "EMPLOYEE_ID"
    COMPLETE = "COMPLETE"


QUESTION_STEPS = (
    QuestionnaireStep.AUTHORIZATION,
    QuestionnaireStep.EMPLOYER_NAME,
    QuestionnaireStep.JOB_TITLE,
    QuestionnaireStep.START_DATE,
    QuestionnaireStep.END_DATE,
    QuestionnaireStep.EMPLOYEE_ID,
)


@dataclass(frozen=True, slots=True)
class AnswerValidation:
    value: str
    error: str = ""
    declined: bool = False


def prompt_for(case_id: str, candidate_name: str, step: QuestionnaireStep) -> str:
    prefix = f"VeriSure verification · Case {case_id}"
    prompts = {
        QuestionnaireStep.AUTHORIZATION: (
            f"{prefix}\nThe candidate, {candidate_name}, has consented to this "
            "employment verification.\n\nQuestion 1 of 6: Are you authorized to "
            "confirm their employment record? Reply YES to continue or DECLINE to stop."
        ),
        QuestionnaireStep.EMPLOYER_NAME: (
            f"{prefix}\n\nQuestion 2 of 6: What is the legal name of the employer?"
        ),
        QuestionnaireStep.JOB_TITLE: (
            f"{prefix}\n\nQuestion 3 of 6: What was {candidate_name}'s job title?"
        ),
        QuestionnaireStep.START_DATE: (
            f"{prefix}\n\nQuestion 4 of 6: What was the employment start month? "
            "Reply as YYYY-MM, for example 2022-01."
        ),
        QuestionnaireStep.END_DATE: (
            f"{prefix}\n\nQuestion 5 of 6: What was the employment end month? "
            "Reply as YYYY-MM, for example 2024-03."
        ),
        QuestionnaireStep.EMPLOYEE_ID: (
            f"{prefix}\n\nQuestion 6 of 6: What was the employee ID? Reply SKIP "
            "if it cannot be shared or is unavailable."
        ),
    }
    return prompts[step]


def next_step(step: QuestionnaireStep) -> QuestionnaireStep:
    index = QUESTION_STEPS.index(step)
    if index == len(QUESTION_STEPS) - 1:
        return QuestionnaireStep.COMPLETE
    return QUESTION_STEPS[index + 1]


def validate_answer(step: QuestionnaireStep, body: str) -> AnswerValidation:
    value = " ".join(body.strip().split())
    upper = value.upper()
    if upper in {"DECLINE", "DECLINED", "NO"}:
        return AnswerValidation(value=upper, declined=True)

    if step is QuestionnaireStep.AUTHORIZATION:
        if upper == "YES":
            return AnswerValidation(value="YES")
        return AnswerValidation(
            value=value,
            error="Please reply YES to continue or DECLINE to stop.",
        )
    if step in {QuestionnaireStep.START_DATE, QuestionnaireStep.END_DATE}:
        if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            return AnswerValidation(value=value)
        return AnswerValidation(
            value=value,
            error="Please reply using YYYY-MM, for example 2022-01.",
        )
    if step is QuestionnaireStep.EMPLOYEE_ID and upper == "SKIP":
        return AnswerValidation(value="")
    if value:
        return AnswerValidation(value=value)
    return AnswerValidation(
        value=value, error="Please provide an answer or reply DECLINE."
    )
