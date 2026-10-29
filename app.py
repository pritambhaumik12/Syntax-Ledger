"""Flask entry point for the C Compiler Error Detector."""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from analyzer import SUPPORTED_LANGUAGES, analyze_source

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    source = payload.get("code", "")
    language = payload.get("language", "c")
    if not isinstance(source, str):
        return jsonify({"error": "The code field must contain text."}), 400
    if not isinstance(language, str) or language.lower().strip() not in SUPPORTED_LANGUAGES:
        return jsonify({"error": "Choose one of the supported languages: C, Python, Java, or JavaScript."}), 400
    if not source.strip():
        return jsonify({"error": "Paste or type some C source code before analyzing."}), 400
    if len(source) > 45_000:
        return jsonify({"error": "For a responsive study session, analyze at most 45,000 characters at once."}), 413
    return jsonify(analyze_source(source, language))


@app.errorhandler(413)
def source_too_large(_error):
    return jsonify({"error": "The submitted source file is too large."}), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
