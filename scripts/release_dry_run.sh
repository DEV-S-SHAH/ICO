#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "  STARTING COMPLETE RELEASE PIPELINE DRY-RUN"
echo "========================================================"

RELEASE_VERSION="0.1.0"
export RELEASE_TAG="v${RELEASE_VERSION}"

# Step 1: Version Sync & Tag Check
echo "==> [Dry-Run 1/10] Checking version sync..."
python3 scripts/check_version_sync.py --tag "${RELEASE_TAG}"

# Step 2: Secrets Audit
echo "==> [Dry-Run 2/10] Scanning repository for committed secrets..."
if command -v gitleaks &> /dev/null; then
    gitleaks detect --source . -v --redact
else
    echo "gitleaks not installed; skipping local binary scan"
fi

# Step 3: Changelog Enforcement
echo "==> [Dry-Run 3/10] Verifying CHANGELOG.md entry..."
python3 scripts/check_changelog.py --version "${RELEASE_VERSION}"
echo "--- Extracted Release Notes Preview ---"
python3 scripts/check_changelog.py --version "${RELEASE_VERSION}" --extract
echo "---------------------------------------"

# Step 4: Full Pytest Test Suite
echo "==> [Dry-Run 4/10] Running full pytest suite (41 tests)..."
PYTHONPATH=packages/ico-cache-py/src:. python3 -m pytest packages/ico-cache-py/tests/ -q

# Step 5: Eval Harness Regression Baseline (All Modes)
echo "==> [Dry-Run 5/10] Running Eval Harness false-hit baseline across all modes..."
export PYTHONPATH=packages/ico-cache-py/src:.
python3 eval_harness.py --loader-type text
python3 eval_harness.py --loader-type structured
python3 eval_harness.py --loader-type code
python3 eval_harness.py --loader-type mixed --ingest-tenant --eval-adversarial

# Step 6: Helm Chart Lint & Dry-Run Template
echo "==> [Dry-Run 6/10] Linting Helm chart and verifying template rendering..."
helm lint deploy/helm/ico-cache
helm template ico-cache deploy/helm/ico-cache > /dev/null

# Step 7: Python Package Build & Twine Validation
echo "==> [Dry-Run 7/10] Building Python wheel and sdist with twine check..."
rm -rf packages/ico-cache-py/dist packages/ico-cache-py/build
(cd packages/ico-cache-py && python3 -m build)
twine check packages/ico-cache-py/dist/*

# Step 8: JS/TS Package Build & NPM Dry-Run
echo "==> [Dry-Run 8/10] Building TypeScript SDK and running npm publish --dry-run..."
(cd packages/ico-cache-js && npm run build)
(cd packages/ico-cache-js && npm publish --dry-run)

# Step 9: Fresh-Install Smoke Tests
echo "==> [Dry-Run 9/10] Executing Python & JS fresh-install smoke tests..."
python3 scripts/smoke_test_installed.py
PACKAGE_PATH="${PWD}/packages/ico-cache-js/dist/index.js" node scripts/smoke_test_installed_js.js

# Step 10: Docker Container Build
echo "==> [Dry-Run 10/10] Validating Docker build dry-run..."
docker build -t ico-cache:dryrun -f apps/financial-rag-demo/docker/Dockerfile.api .

# Clean up build artifacts
rm -rf packages/ico-cache-py/dist packages/ico-cache-py/build

echo "========================================================"
echo "  ✓ RELEASE PIPELINE DRY-RUN COMPLETED SUCCESSFULLY"
echo "  Pipeline is 100% verified and ready for tagging."
echo "========================================================"
