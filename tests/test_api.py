"""API tests for the selected-language analysis endpoint."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app  # noqa: E402


class ApiTests(unittest.TestCase):
    samples = {
        "c": "int main(void) { return 0; }\n",
        "python": "print('ok')\n",
        "java": "public class Main { public static void main(String[] args) {} }\n",
        "javascript": "console.log('ok');\n",
    }


    def test_api_accepts_each_supported_language(self):
        client = app.test_client()
        for language, code in self.samples.items():
            response = client.post("/api/analyze", json={"language": language, "code": code})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["summary"]["language"], language)


    def test_api_rejects_unsupported_language(self):
        client = app.test_client()
        response = client.post("/api/analyze", json={"language": "ruby", "code": "puts 'hello'"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("supported languages", response.get_json()["error"])
