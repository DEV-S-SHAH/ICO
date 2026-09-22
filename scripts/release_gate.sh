#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "  STARTING RELEASE BUILD & TEST GATE"
echo "========================================================"

# 1. Version Sync & Tag Validation
echo "==> [Gate 1/6] Checking Version Sync..."
python3 scripts/check_version_sync.py

# 2. Secret Audit Scan (Gitleaks)
if command -v gitleaks &> /dev/null; then
    echo "==> [Gate 2/6] Running Gitleaks Secret Audit..."
    gitleaks detect --source . -v --redact
fi

# 3. Changelog Enforcement
echo "==> [Gate 3/6] Enforcing CHANGELOG.md Entry..."
python3 scripts/check_changelog.py

# 4. Full Pytest Suite (41 tests)
echo "==> [Gate 4/6] Running Full Pytest Suite..."
PYTHONPATH=packages/ico-cache-py/src:. python3 -m pytest packages/ico-cache-py/tests/ -v

# 5. Evaluation Harness False-Hit Baseline Across All Modes (Must be 0% false hits)
echo "==> [Gate 5/6] Running Eval Harness False-Hit Regression Gate..."
export PYTHONPATH=packages/ico-cache-py/src:.

echo "  -> Evaluating Text Loader Baseline..."
python3 eval_harness.py --loader-type text

echo "  -> Evaluating Structured Loader Baseline..."
python3 eval_harness.py --loader-type structured

echo "  -> Evaluating Code Loader Baseline..."
python3 eval_harness.py --loader-type code

echo "  -> Evaluating Mixed Unified Ingestion & Adversarial Baseline..."
python3 eval_harness.py --loader-type mixed --ingest-tenant --eval-adversarial

# 6. Helm Chart Lint & Template Dry-Run
echo "==> [Gate 6/6] Running Helm Lint and Template Dry-Run..."
helm lint deploy/helm/ico-cache
helm template ico-cache deploy/helm/ico-cache > /dev/null

echo "========================================================"
echo "  ✓ RELEASE GATE PASSED: ALL GATES VERIFIED CLEANLY"
echo "========================================================"
