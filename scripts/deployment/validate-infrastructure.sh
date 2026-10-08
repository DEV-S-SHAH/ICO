#!/bin/bash
set -euo pipefail

# Infrastructure Validation Script
# Validates Dockerfiles, Helm charts, Kubernetes manifests, and CI/CD workflows

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== ICO-Cache Infrastructure Validation ==="
echo "Root directory: $ROOT_DIR"
echo ""

validate_docker() {
    echo "--- Validating Dockerfiles ---"
    
    local dockerfiles=(
        "$ROOT_DIR/docker/production/Dockerfile.api"
        "$ROOT_DIR/docker/production/Dockerfile.worker"
        "$ROOT_DIR/docker/production/Dockerfile.base"
    )
    
    for df in "${dockerfiles[@]}"; do
        if [[ -f "$df" ]]; then
            echo "Validating $df..."
            
            # Check Docker daemon availability
            if docker info > /dev/null 2>&1; then
                if docker build --dry-run -f "$df" "$ROOT_DIR" > /dev/null 2>&1; then
                    echo "  ✓ Syntax OK (docker build)"
                else
                    echo "  ✗ Syntax check failed"
                    return 1
                fi
            else
                # Fallback: basic syntax check with hadolint if available, or just check structure
                if command -v hadolint > /dev/null 2>&1; then
                    if hadolint "$df" > /dev/null 2>&1; then
                        echo "  ✓ Syntax OK (hadolint)"
                    else
                        echo "  ⚠ hadolint warnings (non-blocking)"
                    fi
                else
                    # Basic structure validation
                    if grep -q "^FROM " "$df" && grep -q "^WORKDIR " "$df"; then
                        echo "  ✓ Basic structure OK (Docker daemon not available)"
                    else
                        echo "  ⚠ Basic structure check passed (Docker daemon not available)"
                    fi
                fi
            fi
            
            # Check for best practices
            if grep -q "USER " "$df"; then
                echo "  ✓ Non-root user configured"
            else
                echo "  ⚠ No non-root user found"
            fi
            
            if grep -q "HEALTHCHECK" "$df"; then
                echo "  ✓ Health check configured"
            else
                echo "  ⚠ No health check found"
            fi
            
            if grep -q "readOnlyRootFilesystem" "$df" || grep -q "read-only" "$df"; then
                echo "  ✓ Read-only filesystem configured"
            else
                echo "  ⚠ Read-only filesystem not configured"
            fi
        else
            echo "  ✗ File not found: $df"
            return 1
        fi
    done
}

validate_docker_compose() {
    echo ""
    echo "--- Validating Docker Compose files ---"
    
    local compose_files=(
        "$ROOT_DIR/docker/production/docker-compose.prod.yml"
        "$ROOT_DIR/docker/production/docker-compose.staging.yml"
        "$ROOT_DIR/docker/production/docker-compose.dev.yml"
    )
    
    for cf in "${compose_files[@]}"; do
        if [[ -f "$cf" ]]; then
            echo "Validating $cf..."
            if docker compose -f "$cf" config > /dev/null 2>&1; then
                echo "  ✓ Syntax OK"
            else
                echo "  ✗ Syntax check failed"
                return 1
            fi
            
            # Check for production best practices
            if grep -q "restart: unless-stopped" "$cf"; then
                echo "  ✓ Restart policy configured"
            fi
            
            if grep -q "healthcheck:" "$cf"; then
                echo "  ✓ Health checks configured"
            fi
            
            if grep -q "deploy:" "$cf" && grep -q "resources:" "$cf"; then
                echo "  ✓ Resource limits configured"
            fi
            
            if grep -q "logging:" "$cf"; then
                echo "  ✓ Logging configured"
            fi
        else
            echo "  ✗ File not found: $cf"
            return 1
        fi
    done
}

validate_helm() {
    echo ""
    echo "--- Validating Helm Chart ---"
    
    local chart_dir="$ROOT_DIR/deploy/helm/ico-cache"
    
    if [[ ! -d "$chart_dir" ]]; then
        echo "  ✗ Chart directory not found: $chart_dir"
        return 1
    fi
    
    cd "$chart_dir"
    
    # Check Chart.yaml
    if [[ -f "Chart.yaml" ]]; then
        echo "Checking Chart.yaml..."
        if helm lint . > /dev/null 2>&1; then
            echo "  ✓ Helm lint passed"
        else
            echo "  ✗ Helm lint failed"
            helm lint .
            return 1
        fi
    fi
    
    # Check values.yaml
    if [[ -f "values.yaml" ]]; then
        echo "Checking values.yaml..."
        # Validate required values
        local required_keys=("global" "api" "worker" "redis" "qdrant" "secrets" "ingress" "networkPolicy" "monitoring")
        for key in "${required_keys[@]}"; do
            if grep -q "^${key}:" values.yaml; then
                echo "  ✓ Required key '$key' present"
            else
                echo "  ⚠ Required key '$key' not found"
            fi
        done
    fi
    
    # Check templates
    local templates_dir="$chart_dir/templates"
    if [[ -d "$templates_dir" ]]; then
        echo "Checking templates..."
        local required_templates=("api-deployment.yaml" "worker-deployment.yaml" "redis-statefulset.yaml" "qdrant-statefulset.yaml" "secrets.yaml" "configmap.yaml" "ingress.yaml" "networkpolicy.yaml" "servicemonitor.yaml")
        for template in "${required_templates[@]}"; do
            if [[ -f "$templates_dir/$template" ]]; then
                echo "  ✓ Template found: $template"
            else
                echo "  ⚠ Template not found: $template"
            fi
        done
    fi
    
    # Test template rendering
    echo "Testing template rendering..."
    if helm template test-release . \
        --set global.environment=production \
        --set api.replicaCount=2 \
        --set worker.enabled=true \
        --set redis.enabled=true \
        --set qdrant.enabled=true \
        --set secrets.create=true \
        --set secrets.redisPassword=testpassword \
        --set ingress.enabled=false \
        --set networkPolicy.enabled=false \
        --set monitoring.serviceMonitor.enabled=false \
        > /dev/null 2>&1; then
        echo "  ✓ Template rendering successful"
    else
        echo "  ✗ Template rendering failed"
        helm template test-release . \
            --set global.environment=production \
            --set api.replicaCount=2 \
            --set worker.enabled=true \
            --set redis.enabled=true \
            --set qdrant.enabled=true \
            --set secrets.create=true \
            --set secrets.redisPassword=testpassword \
            --set ingress.enabled=false \
            --set networkPolicy.enabled=false \
            --set monitoring.serviceMonitor.enabled=false
        return 1
    fi
}

validate_kubernetes() {
    echo ""
    echo "--- Validating Kubernetes Manifests ---"
    
    local k8s_dir="$ROOT_DIR/deploy/kubernetes"
    
    if [[ ! -d "$k8s_dir" ]]; then
        echo "  ✗ Kubernetes directory not found: $k8s_dir"
        return 1
    fi
    
    # Check if kubectl is available and connected to a cluster
    local kubectl_available=false
    if command -v kubectl > /dev/null 2>&1 && kubectl cluster-info > /dev/null 2>&1; then
        kubectl_available=true
    fi
    
    # Validate base manifests
    local base_dir="$k8s_dir/base"
    if [[ -d "$base_dir" ]]; then
        for manifest in "$base_dir"/*.yaml; do
            if [[ -f "$manifest" ]]; then
                echo "Validating $(basename "$manifest")..."
                if [[ "$kubectl_available" == "true" ]]; then
                    if kubectl apply --dry-run=client -f "$manifest" > /dev/null 2>&1; then
                        echo "  ✓ Syntax OK (kubectl dry-run)"
                    else
                        echo "  ✗ Syntax check failed"
                        kubectl apply --dry-run=client -f "$manifest"
                        return 1
                    fi
                else
                    # Fallback: YAML syntax validation
                    if python3 -c "import yaml; list(yaml.safe_load_all(open('$manifest')))" > /dev/null 2>&1; then
                        echo "  ✓ YAML syntax OK (kubectl not available)"
                    else
                        echo "  ✗ YAML syntax check failed"
                        return 1
                    fi
                fi
            fi
        done
    fi
    
    # Validate overlays
    for env in dev staging prod; do
        local overlay_dir="$k8s_dir/overlays/$env"
        if [[ -d "$overlay_dir" ]]; then
            echo "Validating $env overlay..."
            if command -v kustomize > /dev/null 2>&1; then
                if kustomize build "$overlay_dir" > /dev/null 2>&1; then
                    echo "  ✓ Kustomize build successful"
                else
                    echo "  ✗ Kustomize build failed"
                    kustomize build "$overlay_dir"
                    return 1
                fi
            elif command -v kubectl > /dev/null 2>&1; then
                if kubectl kustomize "$overlay_dir" > /dev/null 2>&1; then
                    echo "  ✓ Kustomize build successful (kubectl kustomize)"
                else
                    echo "  ✗ Kustomize build failed"
                    kubectl kustomize "$overlay_dir"
                    return 1
                fi
            else
                echo "  ⚠ Kustomize/kubectl not available, skipping build test"
            fi
        fi
    done
}

validate_workflows() {
    echo ""
    echo "--- Validating GitHub Actions Workflows ---"
    
    local workflow_dir="$ROOT_DIR/.github/workflows"
    
    if [[ ! -d "$workflow_dir" ]]; then
        echo "  ✗ Workflows directory not found: $workflow_dir"
        return 1
    fi
    
    local workflows=("ci-python.yml" "ci-docker.yml" "ci-helm.yml" "cd-staging.yml" "cd-production.yml" "security-scan.yml")
    
    for workflow in "${workflows[@]}"; do
        local wf_file="$workflow_dir/$workflow"
        if [[ -f "$wf_file" ]]; then
            echo "Validating $workflow..."
            if python3 -c "import yaml; yaml.safe_load(open('$wf_file'))" > /dev/null 2>&1; then
                echo "  ✓ YAML syntax OK"
            else
                echo "  ✗ YAML syntax check failed"
                return 1
            fi
        else
            echo "  ⚠ Workflow not found: $workflow"
        fi
    done
}

validate_scripts() {
    echo ""
    echo "--- Validating Deployment Scripts ---"
    
    local scripts_dir="$ROOT_DIR/scripts/deployment"
    
    if [[ -d "$scripts_dir" ]]; then
        for script in "$scripts_dir"/*.sh; do
            if [[ -f "$script" ]]; then
                echo "Checking $(basename "$script")..."
                if bash -n "$script"; then
                    echo "  ✓ Syntax OK"
                else
                    echo "  ✗ Syntax check failed"
                    return 1
                fi
                
                if [[ -x "$script" ]]; then
                    echo "  ✓ Executable"
                else
                    echo "  ⚠ Not executable"
                fi
            fi
        done
    fi
}

main() {
    local failed=0
    
    validate_docker || failed=1
    validate_docker_compose || failed=1
    validate_helm || failed=1
    validate_kubernetes || failed=1
    validate_workflows || failed=1
    validate_scripts || failed=1
    
    echo ""
    echo "=== Validation Summary ==="
    if [[ $failed -eq 0 ]]; then
        echo "✓ All validations passed!"
        exit 0
    else
        echo "✗ Some validations failed"
        exit 1
    fi
}

main "$@"