"""FastAPI service exposing Twilio WhatsApp webhooks for VeriSure."""

from __future__ import annotations

import os

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from verisure.domain import ValidationError
from verisure.messaging import (
    TwilioGateway,
    TwilioSettings,
    normalize_whatsapp_address,
)
from verisure.report_email import dispatch_completed_report
from verisure.storage import CaseStore


# Keep direct `uvicorn api:app` launches consistent with the Streamlit app.
load_dotenv()


def create_app(
    store: CaseStore | None = None,
    settings: TwilioSettings | None = None,
) -> FastAPI:
    case_store = store or CaseStore.from_environment()
    twilio_settings = settings or TwilioSettings.from_env()
    gateway = TwilioGateway(twilio_settings)
    app = FastAPI(title="VeriSure WhatsApp API", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/cases/{case_id}/send-verification")
    def send_verification(
        case_id: str,
        x_internal_key: str = Header(default=""),
    ) -> dict[str, str]:
        expected_key = os.getenv("INTERNAL_API_KEY", "").strip()
        if not expected_key or x_internal_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid internal API key.")
        case = case_store.get_case(case_id.upper())
        if case is None:
            raise HTTPException(status_code=404, detail="Verification case not found.")
        try:
            result = gateway.send_verification(case)
            case_store.mark_outreach_sent(
                case.case_id,
                body=result.body,
                twilio_sid=result.sid,
                delivery_status=result.status,
            )
            case_store.start_questionnaire(case.case_id)
        except (RuntimeError, ValidationError, TwilioRestException) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "case_id": case.case_id,
            "message_sid": result.sid,
            "status": result.status,
        }

    @app.post("/webhook/whatsapp")
    @app.post("/webhooks/twilio/whatsapp", include_in_schema=False)
    async def whatsapp_webhook(
        request: Request, background_tasks: BackgroundTasks
    ) -> Response:
        form = await request.form()
        payload = {key: str(value) for key, value in form.items()}
        _validate_twilio_request(request, payload, twilio_settings)

        twiml = MessagingResponse()
        try:
            sender = normalize_whatsapp_address(payload.get("From", ""))
            case = next(
                (
                    item
                    for item in case_store.list_cases()
                    if normalize_whatsapp_address(item.verifier_phone) == sender
                    and item.employer_response_status.value == "PENDING"
                ),
                None,
            )
            if case is None:
                raise ValidationError(
                    ("This number is not approved for an active case.",)
                )
            progress = case_store.record_questionnaire_reply(
                case.case_id,
                body=payload.get("Body", ""),
                twilio_sid=payload.get("MessageSid", ""),
            )
            if progress.completed:
                background_tasks.add_task(
                    dispatch_completed_report, case_store, case.case_id
                )
            twiml.message(progress.reply)
        except (ValidationError, KeyError) as exc:
            twiml.message(f"We could not record the response: {exc}")
        return Response(content=str(twiml), media_type="application/xml")

    @app.post("/webhooks/twilio/status")
    async def twilio_status(request: Request) -> Response:
        form = await request.form()
        payload = {key: str(value) for key, value in form.items()}
        _validate_twilio_request(request, payload, twilio_settings)
        case_store.update_message_status(
            payload.get("MessageSid", ""),
            payload.get("MessageStatus", "unknown"),
        )
        return Response(status_code=204)

    return app


def _validate_twilio_request(
    request: Request,
    payload: dict[str, str],
    settings: TwilioSettings,
) -> None:
    if not settings.validate_signature:
        return
    signature = request.headers.get("X-Twilio-Signature", "")
    public_url = f"{settings.public_base_url}{request.url.path}"
    if request.url.query:
        public_url = f"{public_url}?{request.url.query}"
    if not settings.auth_token or not RequestValidator(settings.auth_token).validate(
        public_url, payload, signature
    ):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature.")


app = create_app()
