#!/bin/bash
set -euo pipefail

# Deployment Smoke Tests
# Validates that a deployed ICO-Cache instance is working correctly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Run smoke tests against a deployed ICO-Cache instance.

Options:
    -e, --environment ENV    Target environment (dev|staging|prod) [default: staging]
    -n, --namespace NS       Kubernetes namespace [default: ico-cache-\$ENV]
    -r, --release NAME       Helm release name [default: ico-cache-\$ENV]
    -u, --url URL            Base URL for API (overrides port-forward)
    -k, --api-key KEY        API key for authenticated endpoints
    -h, --help               Show this help message

Examples:
    $0 -e staging
    $0 -e prod -u https://ico-cache.example.com -k my-api-key
EOF
}

ENVIRONMENT="staging"
NAMESPACE=""
RELEASE=""
URL=""
API_KEY=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -r|--release)
            RELEASE="$2"
            shift 2
            ;;
        -u|--url)
            URL="$2"
            shift 2
            ;;
        -k|--api-key)
            API_KEY="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ -z "$NAMESPACE" ]]; then
    NAMESPACE="ico-cache-$ENVIRONMENT"
fi

if [[ -z "$RELEASE" ]]; then
    RELEASE="ico-cache-$ENVIRONMENT"
fi

# Determine base URL
if [[ -z "$URL" ]]; then
    echo "Setting up port-forward..."
    kubectl port-forward -n "$NAMESPACE" svc/"$RELEASE"-api 8000:8000 &
    PORT_FORWARD_PID=$!
    sleep 3
    URL="http://localhost:8000"
    CLEANUP_PORT_FORWARD=true
else
    CLEANUP_PORT_FORWARD=false
fi

cleanup() {
    if [[ "$CLEANUP_PORT_FORWARD" == "true" && -n "${PORT_FORWARD_PID:-}" ]]; then
        kill $PORT_FORWARD_PID 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "=== ICO-Cache Smoke Tests ==="
echo "Environment: $ENVIRONMENT"
echo "Base URL: $URL"
echo ""

# Test counter
PASSED=0
FAILED=0

run_test() {
    local name="$1"
    local cmd="$2"
    
    echo -n "Testing $name... "
    if eval "$cmd" > /dev/null 2>&1; then
        echo "✓ PASSED"
        ((PASSED++))
        return 0
    else
        echo "✗ FAILED"
        ((FAILED++))
        return 1
    fi
}

# Health endpoint
run_test "Health endpoint" \
    "curl -sf $URL/v1/health | jq -e '.status == \"ok\" or .status == \"degraded\"'"

# Readiness endpoint
run_test "Readiness endpoint" \
    "curl -sf $URL/v1/ready | jq -e '.status == \"ready\"'"

# Metrics endpoint
run_test "Metrics endpoint" \
    "curl -sf $URL/v1/metrics | grep -q '^# HELP'"

# Authenticated endpoints (if API key provided)
if [[ -n "$API_KEY" ]]; then
    AUTH_HEADER="X-API-Key: $API_KEY"
    
    run_test "Query endpoint" \
        "curl -sf -H '$AUTH_HEADER' -H 'Content-Type: application/json' -d '{\"query\":\"test\"}' $URL/v1/query | jq -e '.answer'"
    
    run_test "Invalidate endpoint" \
        "curl -sf -H '$AUTH_HEADER' -H 'Content-Type: application/json' -d '{}' $URL/v1/invalidate | jq -e '.status'"
    
    run_test "Clear cache endpoint" \
        "curl -sf -H '$AUTH_HEADER' -X POST $URL/v1/clear_cache | jq -e '.status'"
    
    run_test "Stats endpoint" \
        "curl -sf -H '$AUTH_HEADER' $URL/v1/stats | jq -e '.hit_rate_l1'"
else
    echo "Skipping authenticated tests (no API key provided)"
fi

# Check pod status
run_test "API pods ready" \
    "kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=api -o jsonpath='{.items[*].status.conditions[?(@.type==\"Ready\")].status}' | grep -q True"

run_test "Worker pods ready" \
    "kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=worker -o jsonpath='{.items[*].status.conditions[?(@.type==\"Ready\")].status}' | grep -q True" || true

run_test "Redis pod ready" \
    "kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=redis -o jsonpath='{.items[*].status.conditions[?(@.type==\"Ready\")].status}' | grep -q True"

run_test "Qdrant pod ready" \
    "kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=qdrant -o jsonpath='{.items[*].status.conditions[?(@.type==\"Ready\")].status}' | grep -q True"

# Check HPA (if enabled)
run_test "HPA configured" \
    "kubectl get hpa -n $NAMESPACE $RELEASE-api > /dev/null 2>&1"

# Check PDB
run_test "PodDisruptionBudget configured" \
    "kubectl get pdb -n $NAMESPACE $RELEASE-api > /dev/null 2>&1"

# Check NetworkPolicy
run_test "NetworkPolicy configured" \
    "kubectl get networkpolicy -n $NAMESPACE -l app.kubernetes.io/name=ico-cache > /dev/null 2>&1"

# Check ServiceMonitor
run_test "ServiceMonitor configured" \
    "kubectl get servicemonitor -n monitoring -l app.kubernetes.io/name=ico-cache > /dev/null 2>&1" || true

echo ""
echo "=== Smoke Test Summary ==="
echo "Passed: $PASSED"
echo "Failed: $FAILED"

if [[ $FAILED -gt 0 ]]; then
    echo "✗ Some tests failed"
    exit 1
else
    echo "✓ All tests passed"
    exit 0
fi