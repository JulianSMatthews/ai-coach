import os
import unittest
from unittest.mock import patch

from app.review_access import review_login


class ReviewAccessTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def configure(self, prefix, phone, code):
        os.environ.update({f"{prefix}_ENABLED": "1", f"{prefix}_PHONE": phone, f"{prefix}_CODE": code})

    def login(self, phone="+447700900002", email=None):
        return review_login(phone_raw=phone, email_raw=email, normalize_phone=lambda p: p.replace(" ", ""))

    def test_disabled_and_ordinary_accounts_never_receive_review_credentials(self):
        self.assertIsNone(self.login())
        self.configure("GOOGLE_PLAY_REVIEW_DEMO", "+447700900002", "654321")
        os.environ["GOOGLE_PLAY_REVIEW_DEMO_ENABLED"] = "0"
        self.assertIsNone(self.login())
        os.environ["GOOGLE_PLAY_REVIEW_DEMO_ENABLED"] = "1"
        self.assertIsNone(self.login("+447700900099"))
        self.assertIsNone(self.login(email="ordinary@example.com"))
        self.assertIsNone(self.login(None))

    def test_stores_have_independent_credentials(self):
        self.configure("APP_REVIEW_DEMO", "+447700900001", "123456")
        self.configure("GOOGLE_PLAY_REVIEW_DEMO", "+447700900002", "654321")
        apple = self.login("+447700900001")
        google = self.login("+44 7700 900002")
        self.assertEqual((apple.first_name, apple.code), ("Alex", "123456"))
        self.assertEqual((google.first_name, google.code), ("Alex", "654321"))

    def test_google_requires_explicit_six_digit_code(self):
        for code in ("", "12345", "1234567", "abcdef", "１２３４５６"):
            with self.subTest(code=code):
                self.configure("GOOGLE_PLAY_REVIEW_DEMO", "+447700900002", code)
                self.assertIsNone(self.login())
        self.configure("GOOGLE_PLAY_REVIEW_DEMO", "+447700900002", "012345")
        self.assertEqual(self.login().code, "012345")

    def test_legacy_apple_default_is_preserved(self):
        self.configure("APP_REVIEW_DEMO", "+447700900001", "")
        self.assertEqual(self.login("+447700900001").code, "123456")

    def test_duplicate_store_phones_do_not_choose_a_credential(self):
        self.configure("APP_REVIEW_DEMO", "+447700900002", "123456")
        self.configure("GOOGLE_PLAY_REVIEW_DEMO", "+447700900002", "654321")
        self.assertIsNone(self.login())

    def test_missing_or_invalid_phone_configuration_does_not_enable_demo(self):
        self.configure("GOOGLE_PLAY_REVIEW_DEMO", "", "654321")
        self.assertIsNone(self.login())
        def invalid_phone(_):
            raise ValueError("invalid phone")
        self.assertIsNone(review_login(phone_raw="invalid", email_raw=None, normalize_phone=invalid_phone))


if __name__ == "__main__":
    unittest.main()
