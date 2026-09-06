from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from verisure import HRConclusion


class AppFlowTests(unittest.TestCase):
    def test_candidate_can_submit_demo_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_path = os.environ.get("DATABASE_PATH")
            previous_mode = os.environ.get("SOURCE_MODE")
            os.environ["DATABASE_PATH"] = str(Path(temp_dir) / "app-test.db")
            os.environ["SOURCE_MODE"] = "fixture"
            try:
                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(app_path, default_timeout=10).run()
                self.assertFalse(app.exception)
                app.checkbox[0].check()
                app.checkbox[1].check()
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(
                    any(
                        "Document extracted" in message.value
                        for message in app.success
                    )
                )
                self.assertTrue(app.session_state["selected_case_id"].startswith("BV-"))

                app.button[1].click().run()
                app.button[1].click().run()
                app.button[1].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[-1].value, "VERIFIED")

                app.selectbox[1].set_value(HRConclusion.INFORMATION_VERIFIED)
                app.text_area[0].set_value("All three approved evidence sources match.")
                app.button[1].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(
                    any("HR conclusion" in message.value for message in app.success)
                )
            finally:
                if previous_path is None:
                    os.environ.pop("DATABASE_PATH", None)
                else:
                    os.environ["DATABASE_PATH"] = previous_path
                if previous_mode is None:
                    os.environ.pop("SOURCE_MODE", None)
                else:
                    os.environ["SOURCE_MODE"] = previous_mode


if __name__ == "__main__":
    unittest.main()
