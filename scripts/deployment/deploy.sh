#!/bin/bash
set -euo pipefail

# Production Deployment Script
# Deploys ICO-Cache to Kubernetes using Helm

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHART_DIR="$ROOT_DIR/deploy/helm/ico-cache"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Deploy ICO-Cache to Kubernetes using Helm.

Options:
    -e, --environment ENV    Target environment (dev|staging|prod) [default: staging]
    -n, --namespace NS       Kubernetes namespace [default: ico-cache-\$ENV]
    -v, --version VERSION    Image version/tag to deploy [default: latest]
    -r, --release NAME       Helm release name [default: ico-cache-\$ENV]
    -d, --dry-run            Perform a dry-run without applying changes
    -f, --force              Force deployment even if validation fails
    -h, --help               Show this help message

Environment Variables:
    KUBECONFIG               Path to kubeconfig file
    REDIS_PASSWORD           Redis password
    GEMINI_API_KEY           Gemini API key
    QDRANT_API_KEY           Qdrant API key
    LANGFUSE_PUBLIC_KEY      Langfuse public key
    LANGFUSE_SECRET_KEY      Langfuse secret key

Examples:
    $0 -e staging -v v1.0.0
    $0 -e prod -v v1.0.0 --dry-run
EOF
}

# Default values
ENVIRONMENT="staging"
NAMESPACE=""
VERSION="latest"
RELEASE=""
DRY_RUN=false
FORCE=false

# Parse arguments
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
        -v|--version)
            VERSION="$2"
            shift 2
            ;;
        -r|--release)
            RELEASE="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -f|--force)
            FORCE=true
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

# Set defaults based on environment
if [[ -z "$NAMESPACE" ]]; then
    NAMESPACE="ico-cache-$ENVIRONMENT"
fi

if [[ -z "$RELEASE" ]]; then
    RELEASE="ico-cache-$ENVIRONMENT"
fi

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(dev|staging|prod)$ ]]; then
    echo "Error: Invalid environment '$ENVIRONMENT'. Must be dev, staging, or prod."
    exit 1
fi

echo "=== ICO-Cache Deployment ==="
echo "Environment: $ENVIRONMENT"
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE"
echo "Version: $VERSION"
echo "Dry-run: $DRY_RUN"
echo ""

# Check required environment variables
required_vars=("REDIS_PASSWORD" "GEMINI_API_KEY")
missing_vars=()

for var in "${required_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        missing_vars+=("$var")
    fi
done

if [[ ${#missing_vars[@]} -gt 0 ]]; then
    echo "Error: Missing required environment variables: ${missing_vars[*]}"
    exit 1
fi

# Add optional variables
optional_vars=("QDRANT_API_KEY" "LANGFUSE_PUBLIC_KEY" "LANGFUSE_SECRET_KEY")
for var in "${optional_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo "Warning: Optional environment variable '$var' not set"
    fi
done

# Check kubectl context
echo "Checking Kubernetes context..."
CURRENT_CONTEXT=$(kubectl config current-context)
echo "Current context: $CURRENT_CONTEXT"

if [[ "$ENVIRONMENT" == "prod" && "$CURRENT_CONTEXT" != *"prod"* ]]; then
    echo "Warning: Deploying to production but context doesn't appear to be production"
    if [[ "$FORCE" != "true" ]]; then
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

# Check Helm chart
if [[ ! -d "$CHART_DIR" ]]; then
    echo "Error: Helm chart not found at $CHART_DIR"
    exit 1
fi

cd "$CHART_DIR"

# Update dependencies
echo "Updating Helm dependencies..."
helm dependency update

# Build values file arguments
VALUES_ARGS=(
    --set "global.environment=$ENVIRONMENT"
    --set "api.image.tag=$VERSION"
    --set "worker.image.tag=$VERSION"
    --set "secrets.create=true"
    --set "secrets.redisPassword=$REDIS_PASSWORD"
    --set "secrets.geminiApiKey=$GEMINI_API_KEY"
)

# Add optional secrets
[[ -n "${QDRANT_API_KEY:-}" ]] && VALUES_ARGS+=(--set "secrets.qdrantApiKey=$QDRANT_API_KEY")
[[ -n "${LANGFUSE_PUBLIC_KEY:-}" ]] && VALUES_ARGS+=(--set "secrets.langfusePublicKey=$LANGFUSE_PUBLIC_KEY")
[[ -n "${LANGFUSE_SECRET_KEY:-}" ]] && VALUES_ARGS+=(--set "secrets.langfuseSecretKey=$LANGFUSE_SECRET_KEY")

# Environment-specific settings
case $ENVIRONMENT in
    dev)
        VALUES_ARGS+=(
            --set "api.replicaCount=1"
            --set "worker.replicaCount=1"
            --set "ingress.enabled=false"
            --set "networkPolicy.enabled=false"
            --set "monitoring.serviceMonitor.enabled=false"
        )
        ;;
    staging)
        VALUES_ARGS+=(
            --set "api.replicaCount=2"
            --set "worker.replicaCount=1"
            --set "ingress.enabled=true"
            --set "networkPolicy.enabled=true"
            --set "monitoring.serviceMonitor.enabled=true"
        )
        ;;
    prod)
        VALUES_ARGS+=(
            --set "api.replicaCount=3"
            --set "worker.replicaCount=2"
            --set "qdrant.replicaCount=2"
            --set "ingress.enabled=true"
            --set "networkPolicy.enabled=true"
            --set "monitoring.serviceMonitor.enabled=true"
            --set "backup.enabled=true"
        )
        ;;
esac

# Deploy
HELM_CMD=(helm upgrade --install "$RELEASE" . --namespace "$NAMESPACE" --create-namespace "${VALUES_ARGS[@]}")

if [[ "$DRY_RUN" == "true" ]]; then
    HELM_CMD+=(--dry-run --debug)
    echo "Running dry-run..."
else
    HELM_CMD+=(--wait --timeout 15m --atomic)
    echo "Deploying..."
fi

echo "Executing: ${HELM_CMD[*]}"
"${HELM_CMD[@]}"

if [[ "$DRY_RUN" != "true" ]]; then
    echo ""
    echo "Waiting for pods to be ready..."
    kubectl wait --for=condition=ready pod -l "app.kubernetes.io/instance=$RELEASE" -n "$NAMESPACE" --timeout=300s
    
    echo ""
    echo "Deployment status:"
    kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE"
    
    echo ""
    echo "Service endpoints:"
    kubectl get svc -n "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE"
    
    echo ""
    echo "=== Deployment Complete ==="
    echo "Release: $RELEASE"
    echo "Namespace: $NAMESPACE"
    echo "Version: $VERSION"
fi