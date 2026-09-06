# VeriSure

VeriSure is a consent-led employment verification assistant for HR teams. HR records a candidate's claimed employment facts, collects a former employer's response through an approved channel, compares the two, and reviews a traceable report before making any hiring-related decision.

The included Streamlit app is a **fixture-only MVP**. It simulates employer responses and does not send WhatsApp messages, contact real people, or make a hiring decision.

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit. Create a request, confirm candidate consent, choose a fixture response, and record an HR disposition. Try the title-mismatch and unavailable-response paths as well as the matching path.

## Product contract

| Stage | Input | Output |
|---|---|---|
| Create request | Candidate identity, consent confirmation, prior employer contact, claimed employer/title/dates | A traceable verification request |
| Employer verification | Employer-provided employment status, title, and dates through an approved channel | Structured evidence, response state, and source metadata |
| Compare | Claimed facts + employer-provided facts | Per-field match, mismatch, or incomplete result |
| HR review | Comparison report plus clarification/context where needed | HR disposition with rationale; no automatic hire/reject action |
| Export | Final reviewed run | Markdown verification report and audit trail |

See [the product brief](Employment-Verification-Product-Brief-v1.md) for the full requirements, data contract, decision rules, and Mermaid flowchart. The [visual guide](Employment-Verification-Visual-Guide.html) is a standalone, fictional walkthrough for the demo.

## Configuration and safety

Copy `.env.example` to `.env` for local configuration, or copy `.streamlit/secrets.toml.example` values into Streamlit Cloud Secrets. Keep `SOURCE_MODE=fixture` for the demo. Never commit credentials, candidate data, or former-employer contact details.

The dependency set now includes the implementation foundation in the supplied build reference: FastAPI/Uvicorn for Twilio webhooks, Twilio for WhatsApp, LangGraph for the verification state machine, OpenAI for constrained extraction, PostgreSQL/SQLAlchemy/Alembic for durable records, and Redis/RQ for retries and timeout jobs. The current Streamlit screen remains fixture-only; installing a dependency does not activate live messaging.

Before setting `SOURCE_MODE=live`, configure `DATABASE_URL`, `REDIS_URL`, all Twilio credentials, `PUBLIC_BASE_URL` (a public HTTPS API URL), and the selected LLM key/model. Twilio signature validation must stay enabled. Ensure candidate consent and the organization's legal, privacy, retention, and communication policies approve outreach before any live employer contact.
