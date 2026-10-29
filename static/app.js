/* Annotation Desk interaction: language-aware source review and correction flow. */
const sourceCode = document.getElementById("source-code");
const lineRail = document.getElementById("line-rail");
const diagnosticList = document.getElementById("diagnostic-list");
const summary = document.getElementById("summary");
const reviewStamp = document.getElementById("review-stamp");
const sourceCount = document.getElementById("source-count");
const engineLabel = document.getElementById("engine-label");
const analyzeButton = document.getElementById("analyze-button");
const languageSelect = document.getElementById("language-select");
const sourceFile = document.getElementById("source-file");

const languageInfo = {
  c: { extension: "c", captions: ["Trace a missing mark and closing brace", "Follow the address operator into scanf", "Separate assignment from comparison"] },
  python: { extension: "py", captions: ["Find a missing colon in a block header", "Trace a simple input statement", "Separate assignment from comparison"] },
  java: { extension: "java", captions: ["Trace a missing semicolon and brace", "Follow a Java console output statement", "Separate assignment from comparison"] },
  javascript: { extension: "js", captions: ["Trace a missing delimiter", "Follow a console output statement", "Separate assignment from strict comparison"] },
};

const examples = {
  c: {
    syntax: `#include <stdio.h>\n\nint main(void) {\n  int total = 10\n  printf("Total: %d\\n", total);\n  return 0;\n`,
    input: `#include <stdio.h>\n\nint main(void) {\n  int age;\n  scanf("%d", age);\n  printf("Age: %d\\n", age);\n  return 0;\n}\n`,
    condition: `#include <stdio.h>\n\nint main(void) {\n  int score = 80;\n  if (score = 100) {\n    printf("Perfect score\\n");\n  }\n  return 0;\n}\n`,
  },
  python: {
    syntax: `name = "Ada"\nif name == "Ada"\n    print("Hello, Ada")\n`,
    input: `name = input("What is your name? ")\nprint("Hello", name)\n`,
    condition: `score = 80\nif score = 100:\n    print("Perfect score")\n`,
  },
  java: {
    syntax: `public class Main {\n  public static void main(String[] args) {\n    int total = 10\n    System.out.println(total);\n  }\n`,
    input: `public class Main {\n  public static void main(String[] args) {\n    System.out.println("Hello, Java");\n  }\n}\n`,
    condition: `public class Main {\n  public static void main(String[] args) {\n    int score = 80;\n    if (score = 100) {\n      System.out.println("Perfect score");\n    }\n  }\n}\n`,
  },
  javascript: {
    syntax: `const total = 10;\nif (total > 0) {\n  console.log(total);\n`,
    input: `const name = "Ada";\nconsole.log("Hello, " + name);\n`,
    condition: `let score = 80;\nif (score = 100) {\n  console.log("Perfect score");\n}\n`,
  },
};

let diagnostics = [];
let selectedLine = null;

function escapeHtml(value) { return String(value).replace(/[&<>"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]); }

function updateLineRail() {
  const lines = sourceCode.value.split("\n");
  sourceCount.textContent = `${lines.length} ${lines.length === 1 ? "line" : "lines"}`;
  lineRail.innerHTML = lines.map((_, index) => `<div class="line-number ${selectedLine === index + 1 ? "active" : ""}">${index + 1}</div>`).join("");
}

function syncScroll() { lineRail.scrollTop = sourceCode.scrollTop; }

function updateLanguagePresentation() {
  const details = languageInfo[languageSelect.value];
  sourceFile.textContent = `untitled.${details.extension}`;
  document.getElementById("syntax-caption").textContent = details.captions[0];
  document.getElementById("input-caption").textContent = details.captions[1];
  document.getElementById("condition-caption").textContent = details.captions[2];
}

function selectDiagnostic(index) {
  const diagnostic = diagnostics[index];
  if (!diagnostic) return;
  selectedLine = diagnostic.line;
  updateLineRail();
  sourceCode.focus();
  sourceCode.scrollTop = Math.max(0, (diagnostic.line - 3) * 23);
  syncScroll();
  document.querySelectorAll(".diagnostic-card").forEach((card, cardIndex) => card.classList.toggle("selected", cardIndex === index));
}

function renderDiagnostics(result) {
  diagnostics = result.diagnostics || [];
  const { errors = 0, warnings = 0, engine = "Guided heuristics" } = result.summary || {};
  summary.innerHTML = `<span><b>${errors}</b> ${errors === 1 ? "error" : "errors"}</span><span><b>${warnings}</b> ${warnings === 1 ? "warning" : "warnings"}</span>`;
  engineLabel.textContent = engine;
  if (!diagnostics.length) {
    reviewStamp.className = "stamp sound";
    reviewStamp.innerHTML = "STRUCTURE<br />LOOKS SOUND";
    diagnosticList.innerHTML = `<div class="empty-state"><div class="empty-mark">✓</div><h3>Nothing urgent surfaced.</h3><p>The selected checks found no common errors in this ${escapeHtml(result.summary?.language_label || "program")} source. Keep testing edge cases as you refine it.</p></div>`;
    return;
  }
  reviewStamp.className = "stamp findings";
  reviewStamp.innerHTML = "REVIEW<br />FINDINGS";
  diagnosticList.innerHTML = diagnostics.map((diagnostic, index) => {
    const fixButton = diagnostic.fix ? `<button class="fix-button" type="button" data-fix-index="${index}">${escapeHtml(diagnostic.fix.label || "Apply suggestion")}</button>` : "";
    return `<article class="diagnostic-card ${diagnostic.severity}" data-index="${index}" tabindex="0"><div class="diagnostic-meta"><span>Line ${diagnostic.line} · ${escapeHtml(diagnostic.code)}</span><span>${escapeHtml(diagnostic.severity)}</span></div><h3>${escapeHtml(diagnostic.title)}</h3><p>${escapeHtml(diagnostic.message)}</p><div class="suggestion"><b>↳</b><span>${escapeHtml(diagnostic.suggestion)}</span></div>${fixButton}</article>`;
  }).join("");
  document.querySelectorAll(".diagnostic-card").forEach((card) => {
    const index = Number(card.dataset.index);
    card.addEventListener("click", (event) => { if (!event.target.matches(".fix-button")) selectDiagnostic(index); });
    card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectDiagnostic(index); } });
  });
  document.querySelectorAll(".fix-button").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); applyFix(Number(button.dataset.fixIndex)); }));
}

function applyFix(index) {
  const diagnostic = diagnostics[index];
  if (!diagnostic?.fix) return;
  const sourceLines = sourceCode.value.split("\n");
  const target = diagnostic.fix.line - 1;
  if (target < 0 || target >= sourceLines.length) return;
  sourceLines[target] = diagnostic.fix.replacement;
  sourceCode.value = sourceLines.join("\n");
  selectedLine = diagnostic.fix.line;
  updateLineRail();
  runAnalysis();
}

async function runAnalysis() {
  const code = sourceCode.value;
  if (!code.trim()) {
    renderDiagnostics({ diagnostics: [], summary: { errors: 0, warnings: 0, engine: "Guided heuristics", language_label: languageSelect.options[languageSelect.selectedIndex].text } });
    reviewStamp.className = "stamp";
    reviewStamp.innerHTML = "AWAITING<br />ANALYSIS";
    diagnosticList.innerHTML = `<div class="empty-state"><div class="empty-mark">?</div><h3>Start with a source listing.</h3><p>Choose a language, paste or type a program, then run a source review.</p></div>`;
    return;
  }
  analyzeButton.classList.add("running");
  analyzeButton.querySelector("span").textContent = "Reviewing source";
  try {
    const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, language: languageSelect.value }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The source review could not be completed.");
    renderDiagnostics(result);
  } catch (error) {
    reviewStamp.className = "stamp findings";
    reviewStamp.innerHTML = "REVIEW<br />PAUSED";
    diagnosticList.innerHTML = `<div class="empty-state"><div class="empty-mark">!</div><h3>Review unavailable.</h3><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    analyzeButton.classList.remove("running");
    analyzeButton.querySelector("span").textContent = "Trace & review";
  }
}

sourceCode.addEventListener("input", updateLineRail);
sourceCode.addEventListener("scroll", syncScroll);
sourceCode.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); runAnalysis(); }
  if (event.key === "Tab") { event.preventDefault(); const start = sourceCode.selectionStart; const end = sourceCode.selectionEnd; sourceCode.value = `${sourceCode.value.substring(0, start)}  ${sourceCode.value.substring(end)}`; sourceCode.selectionStart = sourceCode.selectionEnd = start + 2; updateLineRail(); }
});
languageSelect.addEventListener("change", () => { selectedLine = null; updateLanguagePresentation(); sourceCode.value = examples[languageSelect.value].syntax; updateLineRail(); runAnalysis(); });
analyzeButton.addEventListener("click", runAnalysis);
document.getElementById("clear-button").addEventListener("click", () => { sourceCode.value = ""; selectedLine = null; updateLineRail(); runAnalysis(); sourceCode.focus(); });
document.getElementById("copy-button").addEventListener("click", async (event) => { try { await navigator.clipboard.writeText(sourceCode.value); event.currentTarget.textContent = "Copied"; setTimeout(() => { event.currentTarget.textContent = "Copy listing"; }, 1200); } catch (_) { event.currentTarget.textContent = "Select source to copy"; } });
document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => { sourceCode.value = examples[languageSelect.value][button.dataset.example]; selectedLine = null; updateLineRail(); runAnalysis(); document.getElementById("workbench").scrollIntoView({ behavior: "smooth", block: "start" }); }));

updateLanguagePresentation();
sourceCode.value = examples.c.syntax;
updateLineRail();
runAnalysis();
