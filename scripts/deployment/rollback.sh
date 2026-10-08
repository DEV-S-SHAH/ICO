#!/bin/bash
set -euo pipefail

# Rollback Script
# Rolls back ICO-Cache Helm release to a previous revision

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Rollback ICO-Cache Helm release.

Options:
    -e, --environment ENV    Target environment (dev|staging|prod) [default: staging]
    -n, --namespace NS       Kubernetes namespace [default: ico-cache-\$ENV]
    -r, --release NAME       Helm release name [default: ico-cache-\$ENV]
    -v, --revision REV       Revision number to rollback to (default: previous)
    -l, --list               List available revisions
    -h, --help               Show this help message

Examples:
    $0 -e prod                    # Rollback to previous revision
    $0 -e prod -v 3               # Rollback to revision 3
    $0 -e staging -l              # List revisions
EOF
}

ENVIRONMENT="staging"
NAMESPACE=""
RELEASE=""
REVISION=""
LIST=false

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
        -v|--revision)
            REVISION="$2"
            shift 2
            ;;
        -l|--list)
            LIST=true
            shift
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

echo "=== ICO-Cache Rollback ==="
echo "Environment: $ENVIRONMENT"
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE"
echo ""

# Check if release exists
if ! helm status "$RELEASE" -n "$NAMESPACE" > /dev/null 2>&1; then
    echo "Error: Release '$RELEASE' not found in namespace '$NAMESPACE'"
    exit 1
fi

# List revisions
if [[ "$LIST" == "true" ]]; then
    echo "Available revisions for $RELEASE:"
    helm history "$RELEASE" -n "$NAMESPACE"
    exit 0
fi

# Get current revision
CURRENT_REVISION=$(helm status "$RELEASE" -n "$NAMESPACE" -o json | jq -r '.revision')
echo "Current revision: $CURRENT_REVISION"

# Determine target revision
if [[ -z "$REVISION" ]]; then
    TARGET_REVISION=$((CURRENT_REVISION - 1))
    if [[ $TARGET_REVISION -lt 1 ]]; then
        echo "Error: No previous revision to rollback to"
        exit 1
    fi
    echo "Rolling back to previous revision: $TARGET_REVISION"
else
    TARGET_REVISION=$REVISION
    echo "Rolling back to revision: $TARGET_REVISION"
fi

# Confirm rollback
read -p "Confirm rollback to revision $TARGET_REVISION? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Rollback cancelled"
    exit 0
fi

# Perform rollback
echo "Rolling back..."
helm rollback "$RELEASE" "$TARGET_REVISION" -n "$NAMESPACE" --wait --timeout 10m

# Verify rollback
echo "Verifying rollback..."
kubectl rollout status deployment/"$RELEASE"-api -n "$NAMESPACE" --timeout=300s
if helm list -n "$NAMESPACE" | grep -q "$RELEASE-worker"; then
    kubectl rollout status deployment/"$RELEASE"-worker -n "$NAMESPACE" --timeout=300s
fi

# Check pod status
echo ""
echo "Pod status after rollback:"
kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE"

NEW_REVISION=$(helm status "$RELEASE" -n "$NAMESPACE" -o json | jq -r '.revision')
echo ""
echo "=== Rollback Complete ==="
echo "Rolled back from revision $CURRENT_REVISION to $NEW_REVISION"