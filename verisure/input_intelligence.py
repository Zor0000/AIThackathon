"""Optional, schema-constrained AI repair for imperfect WhatsApp answers.

The model never decides an employment outcome.  It can only turn a natural-language
answer into the value requested by the current questionnaire step; the normal
deterministic validator remains the final authority.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from openai import OpenAIError

from .questionnaire import AnswerValidation, QuestionnaireStep, validate_answer


@dataclass(frozen=True, slots=True)
class InputAssistantSettings:
    api_key: str
    model: str
    base_url: str
    enabled: bool

    @classmethod
    def from_env(cls) -> InputAssistantSettings:
        base_url = os.getenv("AI_INPUT_BASE_URL", "").strip().rstrip("/")
        api_key = os.getenv("AI_INPUT_API_KEY", "").strip()
        if "api.groq.com" in base_url:
            api_key = os.getenv("GROQ_API_KEY", "").strip() or api_key
        return cls(
            api_key=api_key or os.getenv("OPENAI_API_KEY", "").strip(),
            model=(
                os.getenv("AI_INPUT_MODEL", "").strip()
                or os.getenv("LLM_MODEL", "").strip()
            ),
            base_url=base_url,
            enabled=os.getenv("AI_INPUT_ASSIST_ENABLED", "true").strip().lower()
            not in {"0", "false", "no"},
        )

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.api_key and self.model)


@dataclass(frozen=True, slots=True)
class AnswerResolution:
    validation: AnswerValidation
    ai_used: bool = False
    ai_note: str = ""


class InputAssistant:
    """Normalize an invalid response only when the configured model is available."""

    def __init__(self, settings: InputAssistantSettings | None = None) -> None:
        self.settings = settings or InputAssistantSettings.from_env()

    def resolve(self, step: QuestionnaireStep, raw_answer: str) -> AnswerResolution:
        deterministic = validate_answer(step, raw_answer)
        if not deterministic.error or deterministic.declined or not self.settings.ready:
            return AnswerResolution(deterministic)

        try:
            repaired, note = self._repair(step, raw_answer)
        except (
            AttributeError,
            json.JSONDecodeError,
            KeyError,
            OpenAIError,
            TypeError,
            ValueError,
        ):
            # An unavailable AI service must never interrupt the verifier's normal
            # retry path or make an unverified answer appear valid.
            return AnswerResolution(deterministic)

        repaired_validation = validate_answer(step, repaired)
        if repaired_validation.error or repaired_validation.declined:
            return AnswerResolution(deterministic)
        return AnswerResolution(repaired_validation, ai_used=True, ai_note=note)

    def _repair(self, step: QuestionnaireStep, raw_answer: str) -> tuple[str, str]:
        from openai import OpenAI

        schema = {
            "type": "object",
            "properties": {
                "normalized_answer": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["normalized_answer", "note"],
            "additionalProperties": False,
        }
        instructions = (
            "You normalize a former-employer's answer to one verification question. "
            "Do not infer or invent employment information. Preserve the answer's "
            "meaning while extracting only the value requested by the question. For "
            "AUTHORIZATION, return YES only when the answer clearly "
            "authorizes confirmation. For START_DATE and END_DATE, return YYYY-MM "
            "only when the provided answer unambiguously identifies a month and "
            "year. Extract the date from a longer sentence; for example, 'it started "
            "on 1st January 2020' becomes '2020-01'. Never guess a year, resolve "
            "ambiguous dates, or select between multiple dates. For "
            "EMPLOYEE_ID, return an empty value only when the user explicitly says "
            "SKIP or cannot share it. Otherwise return the answer trimmed, without "
            "labels, surrounding sentences, or commentary. Return a short explanation "
            "of any formatting fix."
        )
        client = OpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url or None,
        )
        if self.settings.base_url:
            return self._repair_with_chat_completions(client, instructions, step, raw_answer)

        response = client.responses.create(
            model=self.settings.model,
            instructions=instructions,
            input=(
                f"Question step: {step.value}\n"
                f"Raw verifier reply: {raw_answer.strip()}"
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "normalized_verifier_answer",
                    "strict": True,
                    "schema": schema,
                }
            },
            # Employment data is sensitive. Do not retain these short repair calls.
            store=False,
        )
        payload = json.loads(response.output_text)
        return str(payload["normalized_answer"]), str(payload["note"])

    def _repair_with_chat_completions(
        self,
        client: object,
        instructions: str,
        step: QuestionnaireStep,
        raw_answer: str,
    ) -> tuple[str, str]:
        """Use the OpenAI-compatible chat API exposed by providers such as OpenCode."""

        completion = client.chat.completions.create(  # type: ignore[attr-defined]
            model=self.settings.model,
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": (
                        f"Question step: {step.value}\n"
                        f"Raw verifier reply: {raw_answer.strip()}\n\n"
                        "Return JSON with normalized_answer and note only."
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        payload = json.loads(completion.choices[0].message.content or "")
        return str(payload["normalized_answer"]), str(payload["note"])
