# VeriSure - 3-Hour Rebuild Plan

## Phase 1: Understand and scope (0:00–0:15)

- Lock the candidate submission, document extraction, HR review, WhatsApp, and conclusion contracts.
- Define the persistent case states and three evidence sources.

## Phase 2: Build submission and evidence storage (0:15-1:10)

- Build candidate fact entry, consent, and document upload.
- Extract approved fields and persist only extracted data plus the document fingerprint.
- Add the HR case dashboard and audit events.

## Phase 3: Add WhatsApp verification (1:10-2:00)

- Generate a structured former-employer request through Twilio.
- Add signature-validated, sender-checked, idempotent webhook handling.
- Preserve fixture mode for a credential-free demo.

## Phase 4: Compare and conclude (2:00-2:35)

- Compare candidate, document, and former-employer values field by field.
- Restrict final conclusions to valid evidence states and require HR rationale.
- Generate the downloadable audit report.

## Phase 5: Verify and demo (2:35-3:00)

- Test consent, extraction, match, mismatch, decline, webhook, and sender-check paths.
- Run both services and verify their health endpoints.
- Rehearse candidate submission to final HR report.
