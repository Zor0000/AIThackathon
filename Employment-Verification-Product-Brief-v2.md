# VeriSure

## Candidate evidence, former-employer verification, human HR conclusion

VeriSure is an HR background-verification workflow. A candidate submits claimed prior-employment facts and a supporting document. HR reviews the extracted facts, records an approved former-employer contact, and initiates a structured WhatsApp verification through Twilio. The system compares the candidate claim, document evidence, and former-employer response. HR records the final conclusion with a rationale.

## End-to-end flow

1. Candidate enters identity and prior-employment facts.
2. Candidate uploads an experience/relieving document and records consent.
3. VeriSure extracts employer, title, dates, and employee ID where present.
4. HR reviews the case and adds the approved former-employer verifier.
5. HR initiates a structured WhatsApp request through Twilio.
6. The former employer replies with the case ID and requested fields.
7. The Twilio webhook validates the sender and records the response once.
8. VeriSure compares all three sources field by field.
9. HR records `Information verified`, `Discrepancy confirmed`, `Unable to verify`, or `Further manual review required` with a rationale.
10. VeriSure exports the comparison and audit trail as a Markdown report.

## Decision boundary

The system reports `MATCH`, `MISMATCH`, `NOT PROVIDED`, or `NEEDS REVIEW` for each approved field. It does not determine honesty, make a hiring recommendation, or treat a declined/missing response as false information. HR owns the final conclusion.

## MVP boundaries

- SQLite persistence for cases, extracted fields, message metadata, and audit events
- Raw uploaded documents processed in memory and not retained
- Text-based PDF/TXT extraction with optional schema-constrained AI OCR for images/scanned documents
- Fixture mode for local demos and live mode for Twilio
- Twilio signature validation, sender verification, structured replies, and idempotent message handling
- One prior employer per case

Production deployment still requires authentication, role-based authorization, encryption, retention/deletion policies, secure secret management, and organizational legal/privacy approval.
