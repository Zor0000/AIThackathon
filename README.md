# VeriSure

VeriSure is an HR-led employment background-verification application. It compares candidate-entered facts, facts extracted from a supporting document, and a guided former-employer response received through Twilio WhatsApp. HR reviews the evidence and records the final conclusion.

## Application flow

1. The candidate submits prior-employment facts, a document, and consent.
2. VeriSure extracts employer, title, dates, and employee ID where available.
3. HR adds the approved former-employer contact and initiates WhatsApp verification.
4. Twilio asks one verification question at a time and posts each reply to the FastAPI webhook.
5. VeriSure compares all three sources field by field.
6. VeriSure records one completed verification count for every terminal result,
   including verified, discrepancy-found, and unable-to-verify outcomes.
7. HR reviews the evidence and records a final conclusion and rationale.
8. VeriSure generates a PDF with the candidate claim, extracted document facts,
   former-employer response, and field-by-field analysis. When SMTP is configured,
   it automatically emails the PDF to `neerajchormale39@gmail.com` (or the
   configured recipient) exactly once, after the HR conclusion is recorded.

The application does not make hiring decisions or automatically label information false. A decline or missing response produces `UNABLE TO VERIFY`.

## Local fixture demo

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

Keep `SOURCE_MODE=fixture`. In Candidate submission, select the fictional demo document and consent. This uses the text-based PDF fixture for Aarav Shah. In the HR dashboard, add the fictional verifier, initiate verification, and simulate the Twilio reply. Two additional PDF fixtures are available in `output/pdf/` for manual upload scenarios. Every person, employer, and employment fact in these files is synthetic and marked as demo-only.

## Live Twilio mode

Configure these values in `.env`:

```dotenv
SOURCE_MODE=live
SUPABASE_DB_URL=postgresql://...
PUBLIC_BASE_URL=https://your-public-api.example
INTERNAL_API_KEY=replace-with-a-long-random-value
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_VALIDATE_SIGNATURE=true
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=verifications@example.com
SMTP_USE_TLS=true
HR_RECIPIENT_EMAIL=neerajchormale39@gmail.com
# Optional LLM input repair for natural-language WhatsApp responses.
AI_INPUT_ASSIST_ENABLED=true
AI_INPUT_BASE_URL=https://opencode.ai/zen/go/v1
AI_INPUT_API_KEY=your-opencode-key
AI_INPUT_MODEL=your-structured-output-model
OPENAI_API_KEY=...
```

Run both services:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
streamlit run app.py --server.port 8501
```

Configure the Twilio incoming-message webhook as:

```text
POST https://your-public-api.example/webhook/whatsapp
```

Outbound messages use `/webhooks/twilio/status` as their delivery callback. The public URL must exactly match the URL Twilio signs. Signature validation should remain enabled outside isolated tests.

Completed reports are automatically sent only after an HR reviewer records a final
conclusion in the dashboard. SMTP configuration is intentionally server-side. If SMTP
is not configured, the dashboard still provides the PDF download and identifies the
missing delivery configuration. A delivery record prevents duplicate UI reruns from
issuing another automatic email.

## Input error handling with AI

The questionnaire first applies deterministic validation. If a verifier replies in a
natural format that does not pass it—for example, `it's starting from 1st January
2020` for a date—the
optional input assistant asks the configured OpenAI model to normalize only that
answer under a strict JSON schema. The normalized result must still pass the same
deterministic validator before it is accepted. The original message is retained in
the audit trail and an `AI_INPUT_NORMALIZED` event records the repair. Only the
validated field value—for example, `2020-01`—is retained in the questionnaire and
message records; invalid free text is discarded. If the model is not configured,
unavailable, or cannot safely normalize the answer, the verifier receives the
ordinary retry prompt. The assistant never invents missing facts or makes a
verification/hiring decision.

For OpenCode Go, set `AI_INPUT_BASE_URL=https://opencode.ai/zen/go/v1`, place the
provider key in `AI_INPUT_API_KEY`, and set `AI_INPUT_MODEL=mimo-v2.5`. This uses
its OpenAI-compatible Chat Completions API; the local validator still rejects any
invalid result.

Groq can be used as a fallback with
`AI_INPUT_BASE_URL=https://api.groq.com/openai/v1`, `GROQ_API_KEY`, and an active
Groq model ID. The application uses the same provider-compatible Chat Completions
path for both services.

## Storage backend

`SUPABASE_DB_URL` makes Supabase Postgres the active application database. Cases, audit events, WhatsApp messages, questionnaire sessions, and per-question answers are stored there. SQLite remains the local test and fixture fallback when no Postgres URL is configured.

To copy existing local records once, run:

```bash
python scripts/migrate_sqlite_to_supabase.py
```

The protected send endpoint is also available at `POST /api/cases/{case_id}/send-verification` with the `X-Internal-Key` header. The Streamlit HR dashboard sends directly through the same Twilio gateway.

## Document extraction

- Text-based PDF, TXT, and Markdown documents use local deterministic extraction.
- PNG/JPEG and scanned PDFs require `OPENAI_API_KEY` and `LLM_MODEL` for schema-constrained OCR.
- Raw uploaded bytes are processed in memory and are not stored. The database retains the extracted approved fields, filename, method, warnings, and SHA-256 fingerprint.

## Tests

```bash
python -m unittest discover -v
```

The suite covers domain comparison, conclusions, document extraction, SQLite lifecycle, WhatsApp parsing, sender checks, webhook handling, idempotency, and the Streamlit workflow.

See [Employment-Verification-Product-Brief-v2.md](Employment-Verification-Product-Brief-v2.md) for the current scope. The earlier v1 brief is retained as historical context.

## Production requirements

Before processing real candidate data, add authentication, role-based authorization, encryption, retention/deletion controls, secure secret management, operational monitoring, and an approved correction/dispute process. Confirm organizational legal, consent, privacy, and communication policies before contacting any former employer.
