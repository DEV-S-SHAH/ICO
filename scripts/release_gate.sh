#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "  STARTING RELEASE BUILD & TEST GATE"
echo "========================================================"

# 1. Version Sync & Tag Validation
echo "==> [Gate 1/5] Checking Version Sync..."
python3 scripts/check_version_sync.py

# 2. Changelog Enforcement
echo "==> [Gate 2/5] Enforcing CHANGELOG.md Entry..."
python3 scripts/check_changelog.py

# 3. Full Pytest Suite (41 tests)
echo "==> [Gate 3/5] Running Full Pytest Suite..."
PYTHONPATH=packages/ico-cache-py/src:. python3 -m pytest packages/ico-cache-py/tests/ -v

# 4. Evaluation Harness False-Hit Baseline Across All Modes (Must be 0% false hits)
echo "==> [Gate 4/5] Running Eval Harness False-Hit Regression Gate..."
export PYTHONPATH=packages/ico-cache-py/src:.

echo "  -> Evaluating Text Loader Baseline..."
python3 eval_harness.py --loader-type text

echo "  -> Evaluating Structured Loader Baseline..."
python3 eval_harness.py --loader-type structured

echo "  -> Evaluating Code Loader Baseline..."
python3 eval_harness.py --loader-type code

echo "  -> Evaluating Mixed Unified Ingestion & Adversarial Baseline..."
python3 eval_harness.py --loader-type mixed --ingest-tenant --eval-adversarial

# 5. Helm Chart Lint & Template Dry-Run
echo "==> [Gate 5/5] Running Helm Lint and Template Dry-Run..."
helm lint deploy/helm/ico-cache
helm template ico-cache deploy/helm/ico-cache > /dev/null

echo "========================================================"
echo "  ✓ RELEASE GATE PASSED: ALL GATES VERIFIED CLEANLY"
echo "========================================================"
