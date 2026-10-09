import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

spec = importlib.util.spec_from_file_location("tested_auth", Path(__file__).resolve().parents[1] / "services/auth_service/main.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


class AuthTests(unittest.TestCase):
    def test_old_default_password_has_no_bypass(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with patch.object(auth, "get_db", return_value=conn):
            with self.assertRaises(HTTPException) as caught:
                auth.login({"username": "admin", "password": "password"})
        self.assertEqual(caught.exception.status_code, 401)

    def test_admin_creation_disabled_without_secret(self):
        with patch.dict(auth.os.environ, {"ADMIN_SECRET": ""}):
            with self.assertRaises(HTTPException) as caught:
                auth.create_admin({"username": "new", "password": "password"})
        self.assertEqual(caught.exception.status_code, 403)
