"""Regression tests for the teaching-oriented C diagnostics engine."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer import analyze_source  # noqa: E402


class AnalyzerTests(unittest.TestCase):
    def diagnostic_codes(self, source: str) -> set[str]:
        return self.diagnostic_codes_for("c", source)

    def diagnostic_codes_for(self, language: str, source: str) -> set[str]:
        result = analyze_source(source, language)
        return {diagnostic["code"] for diagnostic in result["diagnostics"]}

    def test_detects_missing_semicolon(self):
        codes = self.diagnostic_codes("int main(void) {\n  int count = 3\n  return 0;\n}\n")
        self.assertIn("H101", codes)

    def test_detects_unclosed_brace(self):
        codes = self.diagnostic_codes("int main(void) {\n  return 0;\n")
        self.assertIn("H103", codes)

    def test_detects_malformed_include(self):
        codes = self.diagnostic_codes("include <stdio.h>\nint main(void) { return 0; }\n")
        self.assertIn("H201", codes)

    def test_detects_scanf_address_warning(self):
        codes = self.diagnostic_codes(
            '#include <stdio.h>\nint main(void) {\n  int age;\n  scanf("%d", age);\n  return 0;\n}\n'
        )
        self.assertIn("H402", codes)

    def test_clean_program_has_no_heuristic_errors(self):
        result = analyze_source(
            '#include <stdio.h>\nint main(void) {\n  int value = 42;\n  printf("%d\\n", value);\n  return 0;\n}\n'
        )
        self.assertEqual(result["summary"]["errors"], 0)

    def test_detects_python_missing_colon(self):
        codes = self.diagnostic_codes_for("python", "if True\n    print('hello')\n")
        self.assertTrue("PYH101" in codes or "PY102" in codes)

    def test_detects_java_missing_semicolon(self):
        codes = self.diagnostic_codes_for("java", "public class Main {\n  public static void main(String[] args) {\n    int count = 3\n  }\n}\n")
        self.assertIn("JH101", codes)

    def test_detects_javascript_assignment_condition(self):
        codes = self.diagnostic_codes_for("javascript", "let score = 0;\nif (score = 100) { console.log(score); }\n")
        self.assertIn("JSH401", codes)

    def test_reports_selected_language_in_summary(self):
        result = analyze_source("print('ok')\n", "python")
        self.assertEqual(result["summary"]["language"], "python")


if __name__ == "__main__":
    unittest.main()
