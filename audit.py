"""audit.py -- repeatable code + security audit for the ICO-Cache repo.

Runs five audit phases and writes one JSON report:

  deps     pip-audit over requirements.txt            (dependency CVEs)
  sast     bandit SAST over src + apps                (security smells)
  static   ruff lint + mypy typecheck                 (code quality)
  ast      tree-sitter AST scan (py/js/go)            (structure + risk patterns)
  secrets  regex scan of git-tracked text files       (leaked credentials)

Audit only scans git-tracked files; nothing in venv/ or data/ is touched.
Deterministic and offline except `deps`, which refreshes the PyPI advisory DB.

  PYTHONPATH=packages/ico-cache-py/src:. venv/bin/python audit.py --all
  venv/bin/python audit.py --only ast --report-dir audit-reports
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

ROOT = os.path.dirname(os.path.abspath(__file__))

AST_GRAMMAR = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".go": "go"}
SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(api[_-]?key|apikey|password|passwd|secret|token|access[_-]?key)\b\s*[=:]\s*['\"][^'\"]{8,}"), "credential-assignment"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws-access-key"),
    (re.compile(r"-----BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY-----"), "private-key"),
    (re.compile(r"(?i)gemini[_-]?api[_-]?key\s*[=:]\s*['\"]?AQ\.\S+"), "gemini-key"),
]
BANNED_CHARS_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")


def run(cmd: List[str], cwd: Optional[str] = None) -> dict:
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd or ROOT, timeout=600
        )
        return {
            "returncode": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "duration_s": round(time.time() - start, 2),
        }
    except FileNotFoundError:
        return {"returncode": -1, "ok": False, "stdout": "", "stderr": "tool not installed", "duration_s": 0.0}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "ok": False, "stdout": "", "stderr": "timed out", "duration_s": round(time.time() - start, 2)}


def tracked_files() -> list:
    return subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=ROOT
    ).stdout.splitlines()


# ---------------------------------------------------------------------------
# AST phase -- the tree-sitter scan
# ---------------------------------------------------------------------------


def _tree_sitter_language(lang: str):
    if lang == "python":
        import tree_sitter_python
        return tree_sitter_python.language()
    if lang == "javascript":
        import tree_sitter_javascript
        return tree_sitter_javascript.language()
    import tree_sitter_go
    return tree_sitter_go.language()


def scan_file_ast(relpath: str, lang: str) -> dict:
    import tree_sitter
    with open(relpath, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    parser = tree_sitter.Parser(tree_sitter.Language(_tree_sitter_language(lang)))
    tree = parser.parse(source.encode())

    counts = {"functions": 0, "classes": 0, "imports": 0, "calls": 0, "parse_error": 0}
    risk_types = {"eval/exec": 0, "shell/subprocess": 0, "bare_except": 0, "dom_unsafe": 0}
    file_findings = []

    stack = [tree.root_node]
    while stack:
        cur = stack.pop()
        t = cur.type
        if t in ("function_definition", "method_definition", "function_declaration", "method_declaration"):
            counts["functions"] += 1
        elif t in ("class_definition", "class_declaration", "type_declaration"):
            counts["classes"] += 1
        elif t in ("import_statement", "import_from_statement", "import_declaration", "import_statement") or t.startswith("import_"):
            counts["imports"] += 1
        elif t == "call":
            counts["calls"] += 1
        elif t == "ERROR":
            counts["parse_error"] += 1
            file_findings.append(f"parse ERROR at row {cur.start_point[0] + 1}")
        elif t == "except_clause" and text_for_node(cur, source) == "except":
            risk_types["bare_except"] += 1
            file_findings.append(f"bare except at row {cur.start_point[0] + 1}")
        elif lang == "python" and t == "string" and "eval" in text_for_node(cur, source):
            risk_types["eval/exec"] += 1
        for child in cur.children:
            stack.append(child)

    scrub = re.sub(r"\s+", " ", source)
    for pat in ["eval(", "exec("]:
        if re.search(re.escape(pat), scrub):
            risk_types["eval/exec"] += 1
    if re.search(r"shell\s*=\s*True", scrub):
        risk_types["shell/subprocess"] += 1
    for line_no, line in enumerate(source.splitlines(), 1):
        if SECRET_PATTERNS[0][0].search(line):
            file_findings.append(f"possible credential assignment at line {line_no}")
        marker = BANNED_CHARS_RE.search(line)
        if marker:
            file_findings.append(f"marker {marker.group(0)} at line {line_no}")

    return {"file": relpath, "counts": counts, "risk_types": risk_types, "findings": file_findings[:20]}


def text_for_node(node, source: str) -> str:
    return source[node.start_byte:node.end_byte].strip()


def audit_ast(targets: list) -> dict:
    files = [f for f in tracked_files() if any(t in f for t in targets) and os.path.splitext(f)[1] in AST_GRAMMAR]
    per_file, totals, skipped, errors = [], {"functions": 0, "classes": 0, "imports": 0, "parse_error": 0}, [], []
    for rel in files:
        lang = AST_GRAMMAR[os.path.splitext(rel)[1]]
        try:
            result = scan_file_ast(rel, lang)
        except Exception as exc:
            errors.append({"file": rel, "error": str(exc)})
            continue
        per_file.append(result)
        for k in totals:
            totals[k] += result["counts"][k]
    return {
        "phase": "ast",
        "files_scanned": len(per_file),
        "files_skipped": len(skipped),
        "parse_errors_total": totals["parse_error"],
        "entity_totals": totals,
        "files": per_file,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def audit_deps() -> dict:
    req = os.path.join(ROOT, "requirements.txt")
    if not os.path.exists(req):
        return {"phase": "deps", "status": "skipped", "reason": "requirements.txt not found"}
    result = run([sys.executable, "-m", "pip_audit", "-r", req, "--progress-spinner", "off", "--format", "json"])
    stdout = result["stdout"]
    vulns = []
    try:
        parsed = json.loads(stdout)
        vulns = parsed.get("dependencies", [])
    except json.JSONDecodeError:
        pass
    return {
        "phase": "deps",
        "ok": result["returncode"] == 0,
        "returncode": result["returncode"],
        "vulnerable_packages": len(vulns),
        "vulnerabilities": vulns,
        "stderr": result["stderr"][-500:],
    }


def audit_sast(targets: list) -> dict:
    result = run([sys.executable, "-m", "bandit", "-r", "-q", "-ll", "--skip", "B101,B104", *targets])
    return {"phase": "sast", "ok": result["ok"], "returncode": result["returncode"], "output": result["stdout"] + result["stderr"]}


def audit_static(targets: list, mypy_targets: list) -> dict:
    lint = run([sys.executable, "-m", "ruff", "check", *targets])
    check = run([sys.executable, "-m", "mypy", *mypy_targets])
    return {
        "phase": "static",
        "ruff": {"ok": lint["ok"], "output": lint["stdout"].rstrip().splitlines()[-20:]},
        "mypy": {"ok": check["ok"], "output": check["stdout"].rstrip().splitlines()[-10:]},
    }


def audit_secrets() -> dict:
    findings = {}
    for rel in tracked_files():
        ext = os.path.splitext(rel)[1]
        if ext not in (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".toml", ".yaml", ".yml", ".sh", ".json", ".md", ".cfg", ".ini", ".env.example"):
            continue
        if not os.path.exists(rel):
            continue
        try:
            with open(rel, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue
        for line_no, line in enumerate(content.splitlines(), 1):
            for pattern, kind in SECRET_PATTERNS:
                if pattern.search(line):
                    value = re.sub(r"[0-9a-zA-Z]{6,}", "<redacted>", line).strip()[:120]
                    findings.setdefault(kind, []).append({"file": rel, "line": line_no, "redacted": value})
    return {"phase": "secrets", "interesting": findings}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="ICO-Cache code + security audit")
    parser.add_argument("--all", action="store_true", help="run every phase")
    parser.add_argument("--only", choices=["deps", "sast", "static", "ast", "secrets"], action="append")
    parser.add_argument("--report-dir", default="audit-reports")
    args = parser.parse_args()

    if args.only:
        phases = args.only
    elif args.all:
        phases = ["deps", "sast", "static", "ast", "secrets"]
    else:
        parser.error("pass --all or --only <phase>")

    targets = ["packages/ico-cache-py/src", "apps/financial-rag-demo"]
    fn_for = {
        "deps": lambda: audit_deps(),
        "sast": lambda: audit_sast(targets),
        "static": lambda: audit_static([*targets, "benchmark.py", "audit.py"], ["packages/ico-cache-py/src"]),
        "ast": lambda: audit_ast(targets),
        "secrets": lambda: audit_secrets(),
    }

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "repo": ROOT, "phases": {}}
    for name in phases:
        print(f"[audit] running phase: {name}")
        report["phases"][name] = fn_for[name]()

    os.makedirs(args.report_dir, exist_ok=True)
    path = os.path.join(args.report_dir, f"audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nAudit report written to {path}")

    for name, phase in report["phases"].items():
        status = "ok" if phase.get("ok", phase.get("status") == "ok") else ("FAIL" if phase.get("returncode") not in (None, 0) else "info")
        print(f"  {name:<8} {status}  {phase.get('files_scanned', '')}".strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
