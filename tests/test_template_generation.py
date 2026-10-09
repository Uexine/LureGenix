import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("template_generator", Path(__file__).resolve().parents[1] / "services/honeytoken_service/generator.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class TemplateGenerationTests(unittest.TestCase):
    def test_all_types_without_network(self):
        with patch.dict(os.environ, {"GENERATION_MODE": "template"}), patch.object(generator.requests, "post", side_effect=AssertionError("Unexpected network request")):
            for token_type in generator.TOKEN_TYPES:
                with self.subTest(token_type=token_type):
                    payload, source = generator.generate_file(token_type)
                    self.assertTrue(payload)
                    self.assertEqual(source, "local" if token_type in ("ssh_key", "api_key", "password") else "template")

    def test_invalid_mode_rejected(self):
        with patch.dict(os.environ, {"GENERATION_MODE": "invalid"}):
            with self.assertRaises(generator.GenerationError):
                generator.generate_file("txt")
