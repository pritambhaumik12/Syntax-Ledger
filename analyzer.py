"""Safe, educational diagnostics for small C, Python, Java, and JavaScript files.

The module never executes submitted programs. It uses parse-only or compile-only
checks where supported tools are available, then adds guided heuristic messages
that are easier for beginners to understand.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from typing import Any


SUPPORTED_LANGUAGES = ("c", "python", "java", "javascript")
LANGUAGE_LABELS = {"c": "C", "python": "Python", "java": "Java", "javascript": "JavaScript"}


@dataclass
class Diagnostic:
    line: int
    column: int
    severity: str
    code: str
    title: str
    message: str
    suggestion: str
    source_line: str
    fix: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _line_at(lines: list[str], line_number: int) -> str:
    return lines[line_number - 1] if 1 <= line_number <= len(lines) else ""


def _diagnostic(
    lines: list[str], line: int, severity: str, code: str, title: str, message: str,
    suggestion: str, column: int = 1, fix: dict[str, Any] | None = None,
) -> Diagnostic:
    return Diagnostic(max(1, line), max(1, column), severity, code, title, message, suggestion, _line_at(lines, line), fix)


def _mask_noncode(source: str, language: str) -> str:
    """Mask comments and literals while keeping all original line positions."""

    result: list[str] = []
    index, state = 0, "code"
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "code" and language == "python" and char == "#":
            state = "line_comment"
            result.append(" ")
            index += 1
        elif state == "code" and language != "python" and char == "/" and next_char == "/":
            state = "line_comment"
            result.extend("  ")
            index += 2
        elif state == "code" and language != "python" and char == "/" and next_char == "*":
            state = "block_comment"
            result.extend("  ")
            index += 2
        elif state == "line_comment":
            if char == "\n":
                state = "code"
                result.append(char)
            else:
                result.append(" ")
            index += 1
        elif state == "block_comment" and char == "*" and next_char == "/":
            state = "code"
            result.extend("  ")
            index += 2
        elif state == "block_comment":
            result.append("\n" if char == "\n" else " ")
            index += 1
        elif state == "code" and char in {'"', "'"}:
            quote = char
            result.append(" ")
            index += 1
            while index < len(source):
                literal_char = source[index]
                result.append("\n" if literal_char == "\n" else " ")
                if literal_char == "\\" and index + 1 < len(source):
                    index += 1
                    result.append("\n" if source[index] == "\n" else " ")
                elif literal_char == quote:
                    index += 1
                    break
                index += 1
        else:
            result.append(char)
            index += 1
    return "".join(result)


def _delimiter_diagnostics(source: str, lines: list[str], language: str, code_prefix: str) -> list[Diagnostic]:
    clean_lines = _mask_noncode(source, language).splitlines()
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[tuple[str, int, int]] = []
    diagnostics: list[Diagnostic] = []
    for line_number, line in enumerate(clean_lines, start=1):
        for column, char in enumerate(line, start=1):
            if char in pairs:
                stack.append((char, line_number, column))
            elif char in pairs.values():
                if not stack or pairs[stack[-1][0]] != char:
                    diagnostics.append(_diagnostic(
                        lines, line_number, "error", f"{code_prefix}102", "Unexpected closing delimiter",
                        f"Found `{char}` without the matching opening delimiter.",
                        "Remove it or add the matching opening delimiter before this location.", column,
                    ))
                else:
                    stack.pop()
    for char, line_number, column in stack:
        diagnostics.append(_diagnostic(
            lines, line_number, "error", f"{code_prefix}103", "Unclosed delimiter",
            f"The opening `{char}` has no matching `{pairs[char]}`.",
            f"Add `{pairs[char]}` to close this expression or block.", column,
            {"line": len(lines), "replacement": f"{_line_at(lines, len(lines))}{pairs[char]}", "label": f"Add {pairs[char]}"},
        ))
    return diagnostics


def _run_process(command: list[str], source: str | None = None) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(command, input=source, text=True, capture_output=True, timeout=4, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _c_compiler_diagnostics(source: str, lines: list[str]) -> list[Diagnostic]:
    gcc = shutil.which("gcc")
    if not gcc:
        return []
    process = _run_process([gcc, "-x", "c", "-", "-fsyntax-only", "-std=c11", "-Wall", "-Wextra", "-fno-diagnostics-color"], source)
    if not process:
        return []
    diagnostics: list[Diagnostic] = []
    pattern = re.compile(r"(?:<stdin>|[^:\n]+):(\d+):(\d+):\s+(?:(?:fatal\s+)?error|warning):\s+(.+)")
    for match in pattern.finditer(process.stderr):
        line, column, message = int(match.group(1)), int(match.group(2)), match.group(3).strip().replace("‘", "'").replace("’", "'")
        severity = "error" if "error:" in match.group(0) else "warning"
        title, suggestion, code, fix = "Compiler diagnostic", "Inspect this token and the preceding statement against C syntax rules.", "GCC", None
        if "expected ';'" in message:
            title, suggestion, code = "Expected a semicolon", "End the preceding declaration or statement with a semicolon (`;`).", "C101"
            previous = max(1, line - 1)
            candidate = _line_at(lines, previous).rstrip()
            if candidate and not candidate.endswith((";", "{", "}")):
                fix = {"line": previous, "replacement": f"{candidate};", "label": "Add semicolon"}
        elif "undeclared" in message:
            title, suggestion, code = "Identifier was not declared", "Declare the identifier before use, or correct its spelling to match an existing declaration.", "C301"
        elif "implicit declaration" in message:
            title, suggestion, code = "Function used without a declaration", "Include the header that declares this function or add a matching prototype.", "C302"
        elif "No such file or directory" in message:
            title, suggestion, code = "Header file was not found", "Check the header name and make sure it is available to the compiler.", "C201"
        diagnostics.append(_diagnostic(lines, line, severity, code, title, message, suggestion, column, fix))
    return diagnostics


def _java_compiler_diagnostics(source: str, lines: list[str]) -> list[Diagnostic]:
    javac = shutil.which("javac")
    if not javac:
        return []
    class_match = re.search(r"\bpublic\s+class\s+([A-Za-z_]\w*)", source)
    file_name = f"{class_match.group(1) if class_match else 'Main'}.java"
    try:
        with tempfile.TemporaryDirectory(prefix="syntax-ledger-java-") as directory:
            path = os.path.join(directory, file_name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(source)
            process = _run_process([javac, "-proc:none", "-Xlint:none", "-d", directory, path])
    except OSError:
        return []
    if not process:
        return []
    diagnostics: list[Diagnostic] = []
    pattern = re.compile(r":(\d+):\s+error:\s+(.+)")
    for match in pattern.finditer(process.stderr):
        line, message = int(match.group(1)), match.group(2).strip()
        title, suggestion, code = "Java compiler diagnostic", "Read this line and the statement immediately before it.", "JAVAC"
        if "';' expected" in message:
            title, suggestion, code = "Expected a semicolon", "End this Java statement with a semicolon (`;`).", "J101"
        elif "reached end of file while parsing" in message:
            title, suggestion, code = "A block was not closed", "Check that each opening `{` has a matching `}`.", "J102"
        elif "cannot find symbol" in message:
            title, suggestion, code = "Name was not found", "Check the spelling and declare or import the name before using it.", "J301"
        diagnostics.append(_diagnostic(lines, line, "error", code, title, message, suggestion))
    return diagnostics


def _javascript_syntax_diagnostics(source: str, lines: list[str]) -> list[Diagnostic]:
    node = shutil.which("node")
    if not node:
        return []
    path = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        process = _run_process([node, "--check", path])
    finally:
        if path and os.path.exists(path):
            os.unlink(path)
    if not process or process.returncode == 0:
        return []
    line_match = re.search(r":(\d+)\s*$", process.stderr, flags=re.MULTILINE)
    message_match = re.search(r"SyntaxError:\s*(.+)", process.stderr)
    line = int(line_match.group(1)) if line_match else 1
    message = message_match.group(1).strip() if message_match else "JavaScript syntax could not be parsed."
    title, suggestion, code = "JavaScript syntax error", "Check the token near this line and the preceding statement.", "JS101"
    if "Unexpected token" in message:
        suggestion = "Check punctuation, quotes, commas, and brackets around this token."
    elif "Unexpected end of input" in message:
        title, suggestion, code = "JavaScript ended too early", "Close the missing quote, parenthesis, bracket, or brace.", "JS102"
    return [_diagnostic(lines, line, "error", code, title, message, suggestion)]


def _python_syntax_diagnostics(source: str, lines: list[str]) -> list[Diagnostic]:
    try:
        compile(source, "<submitted-python>", "exec")
    except SyntaxError as error:
        message = error.msg or "Python syntax error"
        line = error.lineno or 1
        column = error.offset or 1
        title, suggestion, code = "Python syntax error", "Read this line and check the previous line for missing punctuation or indentation.", "PY101"
        if "expected ':'" in message:
            title, suggestion, code = "Expected a colon", "End the Python block header with a colon (`:`).", "PY102"
        elif "was never closed" in message or "unterminated" in message:
            title, suggestion, code = "A delimiter or string was not closed", "Add the missing quote, parenthesis, bracket, or brace.", "PY103"
        elif "expected an indented block" in message:
            title, suggestion, code = "Expected an indented block", "Indent the lines that belong inside this Python block.", "PY104"
        return [_diagnostic(lines, line, "error", code, title, message, suggestion, column)]
    return []


def _c_heuristics(source: str, lines: list[str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if re.match(r"^include\s*[<\"]", stripped):
            diagnostics.append(_diagnostic(lines, line_number, "error", "H201", "Preprocessor marker is missing", "C header directives must begin with `#include`.", "Add `#` before `include`.", fix={"line": line_number, "replacement": f"#{stripped}", "label": "Add #include"}))
        elif re.match(r"^#\s*include\s*[<\"][^>\"]+$", stripped):
            diagnostics.append(_diagnostic(lines, line_number, "error", "H202", "Header delimiter is incomplete", "The header name is missing its closing `>` or `\"` delimiter.", "Close the header name, for example: `#include <stdio.h>`."))
    declaration_or_statement = re.compile(r"^(?:const\s+)?(?:unsigned\s+|signed\s+)?(?:int|char|float|double|long|short|void)\b|^(?:return|break|continue)\b|^[A-Za-z_]\w*\s*(?:=|\+\+|--|\+=|-=)")
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "//", "*")) and declaration_or_statement.search(stripped) and not stripped.endswith((";", "{", "}", ":")):
            if not re.search(r"\b(?:if|for|while|switch)\s*\(", stripped):
                diagnostics.append(_diagnostic(lines, line_number, "error", "H101", "Statement may be missing a semicolon", "This declaration or statement does not end with `;`.", "Place a semicolon at the end of the statement.", len(line.rstrip()) + 1, {"line": line_number, "replacement": f"{line.rstrip()};", "label": "Add semicolon"}))
    diagnostics.extend(_delimiter_diagnostics(source, lines, "c", "H"))
    clean_lines = _mask_noncode(source, "c").splitlines()
    for line_number, clean_line in enumerate(clean_lines, start=1):
        if re.search(r"\bif\s*\([^\n]*?(?<![=!<>])=(?!=)", clean_line):
            original = _line_at(lines, line_number)
            diagnostics.append(_diagnostic(lines, line_number, "warning", "H401", "Assignment inside an if condition", "`=` assigns a value; it does not compare values.", "If you intended a comparison, replace `=` with `==`.", fix={"line": line_number, "replacement": re.sub(r"(?<![=!<>])=(?!=)", "==", original, count=1), "label": "Use =="}))
    scanf_pattern = re.compile(r"\bscanf\s*\(\s*\"[^\"]*\"\s*,\s*([A-Za-z_]\w*)\s*\)")
    for line_number, line in enumerate(lines, start=1):
        match = scanf_pattern.search(line)
        if match:
            variable = match.group(1)
            replacement = line[:match.start(1)] + f"&{variable}" + line[match.end(1):]
            diagnostics.append(_diagnostic(lines, line_number, "warning", "H402", "scanf usually needs a variable address", f"`scanf` needs a writable address for `{variable}`, not its current value.", f"Pass `&{variable}` if `{variable}` is a scalar variable.", match.start(1) + 1, {"line": line_number, "replacement": replacement, "label": f"Use &{variable}"}))
    if not re.search(r"\b(?:int|void)\s+main\s*\(", _mask_noncode(source, "c")):
        diagnostics.append(_diagnostic(lines, 1, "warning", "H403", "Program entry point was not found", "A standalone C program conventionally begins execution in `main`.", "Add an `int main(void) { ... }` function if this source should be a complete program."))
    return diagnostics


def _python_heuristics(source: str, lines: list[str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    headers = re.compile(r"^(?:if|elif|else|for|while|def|class|try|except|finally|with)\b")
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if headers.search(stripped) and not stripped.endswith(":"):
            diagnostics.append(_diagnostic(lines, line_number, "error", "PYH101", "Python block header may be missing a colon", "Python uses a colon to start the indented body of an `if`, `for`, `def`, class, or similar block.", "Add `:` at the end of this block header.", len(line.rstrip()) + 1, {"line": line_number, "replacement": f"{line.rstrip()}:", "label": "Add colon"}))
        if re.match(r"^function\s+\w+", stripped):
            diagnostics.append(_diagnostic(lines, line_number, "warning", "PYH102", "JavaScript-style function keyword in Python", "Python functions begin with `def`, not `function`.", "Replace `function name(...)` with `def name(...):`."))
    return diagnostics


def _java_heuristics(source: str, lines: list[str]) -> list[Diagnostic]:
    diagnostics = _delimiter_diagnostics(source, lines, "java", "JH")
    statement = re.compile(r"^(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:final\s+)?(?:int|long|double|float|boolean|char|String|return|System\.out\.println)\b|^[A-Za-z_]\w*\s*(?:=|\+\+|--|\+=|-=)")
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(("//", "*", "@")) and statement.search(stripped) and not stripped.endswith((";", "{", "}", ":")):
            if not re.search(r"\b(?:if|for|while|switch|class)\s*\(", stripped):
                diagnostics.append(_diagnostic(lines, line_number, "error", "JH101", "Java statement may be missing a semicolon", "Most Java declarations and statements must end with `;`.", "Place a semicolon at the end of this statement.", len(line.rstrip()) + 1, {"line": line_number, "replacement": f"{line.rstrip()};", "label": "Add semicolon"}))
        if re.search(r"\bif\s*\([^\n]*?(?<![=!<>])=(?!=)", _mask_noncode(line, "java")):
            diagnostics.append(_diagnostic(lines, line_number, "warning", "JH401", "Assignment inside an if condition", "`=` assigns a value; it does not compare values.", "If you intended a comparison, replace `=` with `==`.", fix={"line": line_number, "replacement": re.sub(r"(?<![=!<>])=(?!=)", "==", line, count=1), "label": "Use =="}))
    if not re.search(r"\bstatic\s+void\s+main\s*\(", _mask_noncode(source, "java")):
        diagnostics.append(_diagnostic(lines, 1, "warning", "JH402", "Java main method was not found", "A standalone Java application normally begins in `public static void main(String[] args)`.", "Add a main method if this file should run as a complete Java program."))
    return diagnostics


def _javascript_heuristics(source: str, lines: list[str]) -> list[Diagnostic]:
    diagnostics = _delimiter_diagnostics(source, lines, "javascript", "JSH")
    statement = re.compile(r"^(?:let|const|var|return|throw)\b|^[A-Za-z_$][\w$]*\s*(?:=|\+\+|--|\+=|-=)")
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(("//", "*")) and statement.search(stripped) and not stripped.endswith((";", "{", "}", ",", ":")):
            diagnostics.append(_diagnostic(lines, line_number, "warning", "JSH101", "JavaScript statement may be missing a semicolon", "JavaScript can insert some semicolons automatically, but writing them makes the statement boundary clearer.", "Consider ending this statement with `;`.", len(line.rstrip()) + 1, {"line": line_number, "replacement": f"{line.rstrip()};", "label": "Add semicolon"}))
        if re.search(r"\bif\s*\([^\n]*?(?<![=!<>])=(?!=)", _mask_noncode(line, "javascript")):
            diagnostics.append(_diagnostic(lines, line_number, "warning", "JSH401", "Assignment inside an if condition", "`=` assigns a value; it does not compare values.", "If you intended a comparison, replace `=` with `===`.", fix={"line": line_number, "replacement": re.sub(r"(?<![=!<>])=(?!=)", "===", line, count=1), "label": "Use ==="}))
    return diagnostics


def _engine_name(language: str) -> str:
    if language == "python":
        return "Python parser + guided heuristics"
    if language == "javascript":
        return "Node syntax check + guided heuristics" if shutil.which("node") else "JavaScript guided heuristics"
    if language == "java":
        return "Java compiler + guided heuristics" if shutil.which("javac") else "Java guided heuristics"
    return "GCC + guided heuristics" if shutil.which("gcc") else "C guided heuristics"


def analyze_source(source: str, language: str = "c") -> dict[str, Any]:
    """Analyze a selected language without executing the submitted program."""

    language = language.lower().strip()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    if language == "c":
        heuristics, compiler = _c_heuristics(source, lines), _c_compiler_diagnostics(source, lines)
    elif language == "python":
        heuristics, compiler = _python_heuristics(source, lines), _python_syntax_diagnostics(source, lines)
    elif language == "java":
        heuristics, compiler = _java_heuristics(source, lines), _java_compiler_diagnostics(source, lines)
    else:
        heuristics, compiler = _javascript_heuristics(source, lines), _javascript_syntax_diagnostics(source, lines)
    seen: set[tuple[int, str, str]] = set()
    diagnostics: list[Diagnostic] = []
    for item in heuristics + compiler:
        key = (item.line, item.title, item.code)
        if key not in seen:
            seen.add(key)
            diagnostics.append(item)
    severity_order = {"error": 0, "warning": 1, "info": 2}
    diagnostics.sort(key=lambda item: (item.line, severity_order.get(item.severity, 3), item.column))
    return {
        "diagnostics": [item.to_dict() for item in diagnostics],
        "summary": {
            "errors": sum(item.severity == "error" for item in diagnostics),
            "warnings": sum(item.severity == "warning" for item in diagnostics),
            "engine": _engine_name(language),
            "language": language,
            "language_label": LANGUAGE_LABELS[language],
        },
    }
