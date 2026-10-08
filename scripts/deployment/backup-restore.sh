#!/bin/bash
set -euo pipefail

# Backup and Restore Script
# Handles backup and restore of ICO-Cache data (Redis, Qdrant)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
    cat <<EOF
Usage: $0 COMMAND [OPTIONS]

Backup and restore ICO-Cache data.

Commands:
    backup      Create a backup of Redis and Qdrant data
    restore     Restore from a backup
    list        List available backups

Options:
    -e, --environment ENV    Target environment (dev|staging|prod) [default: staging]
    -n, --namespace NS       Kubernetes namespace [default: ico-cache-\$ENV]
    -b, --backup-dir DIR     Local backup directory [default: ./backups]
    -s, --storage-class SC   Storage class for backup PVC [default: standard]
    -v, --version VER        Backup version/timestamp to restore
    -h, --help               Show this help message

Examples:
    $0 backup -e prod
    $0 restore -e prod -v 20240115-020000
    $0 list -e staging
EOF
}

COMMAND="${1:-}"
shift || true

ENVIRONMENT="staging"
NAMESPACE=""
BACKUP_DIR="./backups"
STORAGE_CLASS="standard"
VERSION=""

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
        -b|--backup-dir)
            BACKUP_DIR="$2"
            shift 2
            ;;
        -s|--storage-class)
            STORAGE_CLASS="$2"
            shift 2
            ;;
        -v|--version)
            VERSION="$2"
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

mkdir -p "$BACKUP_DIR"

get_redis_password() {
    kubectl get secret -n "$NAMESPACE" -l "app.kubernetes.io/name=ico-cache" -o jsonpath='{.items[0].data.REDIS_AUTH}' | base64 -d
}

backup_redis() {
    local backup_path="$1"
    echo "Backing up Redis..."
    
    REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l "app.kubernetes.io/component=redis" -o jsonpath='{.items[0].metadata.name}')
    REDIS_PASSWORD=$(get_redis_password)
    
    kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli -a "$REDIS_PASSWORD" --rdb "/data/dump.rdb"
    kubectl cp "$NAMESPACE/$REDIS_POD:/data/dump.rdb" "$backup_path/redis.rdb"
    
    echo "Redis backup saved to $backup_path/redis.rdb"
}

backup_qdrant() {
    local backup_path="$1"
    echo "Backing up Qdrant..."
    
    QDRANT_POD=$(kubectl get pod -n "$NAMESPACE" -l "app.kubernetes.io/component=qdrant" -o jsonpath='{.items[0].metadata.name}')
    
    kubectl exec -n "$NAMESPACE" "$QDRANT_POD" -- tar czf "/tmp/qdrant-backup.tar.gz" -C /qdrant/storage .
    kubectl cp "$NAMESPACE/$QDRANT_POD:/tmp/qdrant-backup.tar.gz" "$backup_path/qdrant.tar.gz"
    
    echo "Qdrant backup saved to $backup_path/qdrant.tar.gz"
}

backup_config() {
    local backup_path="$1"
    echo "Backing up configuration..."
    
    kubectl get configmap -n "$NAMESPACE" -l "app.kubernetes.io/name=ico-cache" -o yaml > "$backup_path/configmaps.yaml"
    kubectl get secret -n "$NAMESPACE" -l "app.kubernetes.io/name=ico-cache" -o yaml > "$backup_path/secrets.yaml"
    
    echo "Configuration backed up to $backup_path/"
}

cmd_backup() {
    local timestamp=$(date +%Y%m%d-%H%M%S)
    local backup_path="$BACKUP_DIR/$ENVIRONMENT-$timestamp"
    
    mkdir -p "$backup_path"
    
    echo "=== Creating Backup ==="
    echo "Environment: $ENVIRONMENT"
    echo "Backup path: $backup_path"
    echo ""
    
    backup_redis "$backup_path"
    backup_qdrant "$backup_path"
    backup_config "$backup_path"
    
    # Create manifest
    cat > "$backup_path/manifest.json" <<EOF
{
    "timestamp": "$timestamp",
    "environment": "$ENVIRONMENT",
    "namespace": "$NAMESPACE",
    "components": ["redis", "qdrant", "config"]
}
EOF
    
    echo ""
    echo "=== Backup Complete ==="
    echo "Backup saved to: $backup_path"
    echo "Manifest: $backup_path/manifest.json"
}

cmd_restore() {
    if [[ -z "$VERSION" ]]; then
        echo "Error: Version/timestamp required for restore (-v)"
        exit 1
    fi
    
    local backup_path="$BACKUP_DIR/$ENVIRONMENT-$VERSION"
    
    if [[ ! -d "$backup_path" ]]; then
        echo "Error: Backup not found: $backup_path"
        exit 1
    fi
    
    echo "=== Restoring Backup ==="
    echo "Environment: $ENVIRONMENT"
    echo "Backup: $backup_path"
    echo ""
    
    read -p "This will overwrite current data. Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Restore cancelled"
        exit 0
    fi
    
    # Scale down workloads
    echo "Scaling down workloads..."
    kubectl scale deployment -n "$NAMESPACE" -l "app.kubernetes.io/name=ico-cache" --replicas=0
    kubectl wait --for=delete pod -l "app.kubernetes.io/name=ico-cache" -n "$NAMESPACE" --timeout=120s
    
    # Restore Redis
    echo "Restoring Redis..."
    REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l "app.kubernetes.io/component=redis" -o jsonpath='{.items[0].metadata.name}')
    kubectl cp "$backup_path/redis.rdb" "$NAMESPACE/$REDIS_POD:/data/dump.rdb"
    kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli -a "$(get_redis_password)" SHUTDOWN NOSAVE
    sleep 5
    
    # Restore Qdrant
    echo "Restoring Qdrant..."
    QDRANT_POD=$(kubectl get pod -n "$NAMESPACE" -l "app.kubernetes.io/component=qdrant" -o jsonpath='{.items[0].metadata.name}')
    kubectl cp "$backup_path/qdrant.tar.gz" "$NAMESPACE/$QDRANT_POD:/tmp/qdrant-restore.tar.gz"
    kubectl exec -n "$NAMESPACE" "$QDRANT_POD" -- tar xzf "/tmp/qdrant-restore.tar.gz" -C /qdrant/storage
    
    # Scale up workloads
    echo "Scaling up workloads..."
    kubectl scale deployment -n "$NAMESPACE" -l "app.kubernetes.io/name=ico-cache" --replicas=2
    
    echo ""
    echo "=== Restore Complete ==="
    echo "Workloads are starting up. Check pod status with:"
    echo "  kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=ico-cache"
}

cmd_list() {
    echo "Available backups for $ENVIRONMENT:"
    echo ""
    
    if [[ -d "$BACKUP_DIR" ]]; then
        for backup in "$BACKUP_DIR"/$ENVIRONMENT-*; do
            if [[ -d "$backup" ]]; then
                local manifest="$backup/manifest.json"
                if [[ -f "$manifest" ]]; then
                    local timestamp=$(jq -r '.timestamp' "$manifest")
                    echo "  $timestamp"
                else
                    echo "  $(basename "$backup") (no manifest)"
                fi
            fi
        done | sort -r
    else
        echo "  No backups found"
    fi
}

case $COMMAND in
    backup)
        cmd_backup
        ;;
    restore)
        cmd_restore
        ;;
    list)
        cmd_list
        ;;
    *)
        echo "Error: Unknown command '$COMMAND'"
        usage
        exit 1
        ;;
esac