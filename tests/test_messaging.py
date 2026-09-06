from __future__ import annotations

import unittest

from verisure.domain import EmployerResponseStatus, ValidationError
from verisure.messaging import normalize_whatsapp_address, parse_whatsapp_reply


class MessagingTests(unittest.TestCase):
    def test_confirmed_reply_is_parsed(self) -> None:
        reply = parse_whatsapp_reply(
            """CASE: BV-ABC12345
STATUS: CONFIRMED
EMPLOYER: Northstar Labs
TITLE: Senior Software Engineer
START: 2022-01
END: 2024-03
EMPLOYEE_ID: NS-1042
"""
        )

        self.assertIs(reply.status, EmployerResponseStatus.RECEIVED)
        self.assertEqual(reply.facts.job_title, "Senior Software Engineer")

    def test_declined_reply_does_not_create_negative_facts(self) -> None:
        reply = parse_whatsapp_reply("CASE: BV-ABC12345\nSTATUS: DECLINED")

        self.assertIs(reply.status, EmployerResponseStatus.DECLINED)
        self.assertIsNone(reply.facts)

    def test_invalid_phone_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_whatsapp_address("9876543210")

    def test_phone_is_normalized_for_twilio(self) -> None:
        self.assertEqual(
            normalize_whatsapp_address("+91 98765 43210"),
            "whatsapp:+919876543210",
        )


if __name__ == "__main__":
    unittest.main()
