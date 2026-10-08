# ICO-Cache Deployment Infrastructure

This directory contains all production deployment infrastructure for ICO-Cache.

## Structure

```
deploy/
├── docker/production/           # Production Dockerfiles and Docker Compose
├── helm/ico-cache/             # Helm chart for Kubernetes deployment
├── kubernetes/                 # Kustomize overlays for each environment
│   ├── base/                   # Base manifests (namespace, quotas, limits)
│   └── overlays/
│       ├── dev/                # Development overlay
│       ├── staging/            # Staging overlay
│       └── prod/               # Production overlay
├── scripts/deployment/         # Deployment automation scripts
└── README.md                   # This file
```

## Quick Start

### Docker Compose (Production)

```bash
# Set required environment variables
export REDIS_PASSWORD="your-secure-password"
export GEMINI_API_KEY="your-gemini-key"
export API_KEYS='{"your-api-key": "default"}'

# Deploy
docker compose -f docker/production/docker-compose.prod.yml up -d
```

### Kubernetes (Helm)

```bash
# Add Helm repos
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install for development
helm install ico-cache-dev ./deploy/helm/ico-cache \
  -n ico-cache-dev --create-namespace \
  -f ./deploy/helm/ico-cache/values/dev.yaml \
  --set secrets.redisPassword=devredissecret

# Install for staging
helm install ico-cache-staging ./deploy/helm/ico-cache \
  -n ico-cache-staging --create-namespace \
  -f ./deploy/helm/ico-cache/values/staging.yaml \
  --set secrets.redisPassword=$REDIS_PASSWORD \
  --set secrets.geminiApiKey=$GEMINI_API_KEY

# Install for production
helm install ico-cache ./deploy/helm/ico-cache \
  -n ico-cache --create-namespace \
  -f ./deploy/helm/ico-cache/values/prod.yaml \
  --set secrets.redisPassword=$REDIS_PASSWORD \
  --set secrets.geminiApiKey=$GEMINI_API_KEY \
  --set secrets.qdrantApiKey=$QDRANT_API_KEY
```

### Kubernetes (Kustomize)

```bash
# Deploy to development
kubectl apply -k ./deploy/kubernetes/overlays/dev

# Deploy to staging
kubectl apply -k ./deploy/kubernetes/overlays/staging

# Deploy to production
kubectl apply -k ./deploy/kubernetes/overlays/prod
```

## Environment Variables

### Required
- `REDIS_PASSWORD` - Redis authentication password
- `GEMINI_API_KEY` - Google Gemini API key for LLM calls

### Optional
- `QDRANT_API_KEY` - Qdrant API key (if authentication enabled)
- `LANGFUSE_PUBLIC_KEY` - Langfuse public key for observability
- `LANGFUSE_SECRET_KEY` - Langfuse secret key for observability
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OpenTelemetry collector endpoint

## Deployment Scripts

### Automated Deployment
```bash
# Deploy to staging
./scripts/deployment/deploy.sh -e staging -v v1.0.0

# Deploy to production (with approval)
./scripts/deployment/deploy.sh -e prod -v v1.0.0
```

### Rollback
```bash
# Rollback to previous revision
./scripts/deployment/rollback.sh -e prod

# Rollback to specific revision
./scripts/deployment/rollback.sh -e prod -v 3

# List revisions
./scripts/deployment/rollback.sh -e prod -l
```

### Backup/Restore
```bash
# Create backup
./scripts/deployment/backup-restore.sh backup -e prod

# List backups
./scripts/deployment/backup-restore.sh list -e prod

# Restore from backup
./scripts/deployment/backup-restore.sh restore -e prod -v 20240115-020000
```

### Smoke Tests
```bash
# Run smoke tests against staging
./scripts/deployment/smoke-tests.sh -e staging

# Run smoke tests against production with API key
./scripts/deployment/smoke-tests.sh -e prod -k $API_KEY
```

### Validation
```bash
# Validate all infrastructure
./scripts/deployment/validate-infrastructure.sh
```

## Monitoring

### Prometheus Metrics
- API: `/v1/metrics` (port 8000)
- Worker: `/metrics` (port 8081)
- Redis Exporter: `/metrics` (port 9121)
- Qdrant: `/metrics` (port 6333)

### Grafana Dashboard
Import `docker/production/grafana/dashboards/ico-cache-overview.json` into Grafana.

### Key Metrics to Monitor
- `http_requests_total` - Request rate and error rate
- `http_request_duration_seconds` - Request latency (p50, p95, p99)
- `ico_cache_hit_rate_l1/l2/l3` - Cache hit rates by layer
- `redis_memory_used_bytes` - Redis memory usage
- `qdrant_collections_vectors_count` - Vector count in Qdrant

## Security

### Network Policies
- API pods can communicate with Redis and Qdrant
- Worker pods can communicate with Redis and Qdrant
- External access only via Ingress
- DNS resolution allowed for external dependencies

### Pod Security Standards
- All pods run as non-root (UID 10001)
- Read-only root filesystem
- All capabilities dropped
- Seccomp profile: RuntimeDefault

### Secrets Management
- Use External Secrets Operator with Vault/Secrets Manager
- Never commit secrets to git
- Rotate secrets regularly

## CI/CD Pipeline

### GitHub Actions Workflows
- `.github/workflows/ci-python.yml` - Python package CI
- `.github/workflows/ci-docker.yml` - Docker image build and scan
- `.github/workflows/ci-helm.yml` - Helm chart validation
- `.github/workflows/cd-staging.yml` - Deploy to staging on develop branch
- `.github/workflows/cd-production.yml` - Deploy to production on release
- `.github/workflows/security-scan.yml` - Weekly security scanning

### Required Secrets
- `KUBECONFIG_STAGING` - Staging cluster kubeconfig
- `KUBECONFIG_PROD` - Production cluster kubeconfig
- `REDIS_PASSWORD_STAGING` - Staging Redis password
- `REDIS_PASSWORD_PROD` - Production Redis password
- `GEMINI_API_KEY` - Gemini API key
- `QDRANT_API_KEY_STAGING` - Staging Qdrant API key
- `QDRANT_API_KEY_PROD` - Production Qdrant API key

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Ingress (TLS)                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────┐        ┌─────────┐        ┌─────────┐
   │ API Pod │        │ API Pod │        │ API Pod │  (HPA: 3-10)
   └────┬────┘        └────┬────┘        └────┬────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────┐        ┌─────────┐        ┌─────────┐
   │  Redis  │        │  Qdrant │        │ Worker  │  (1-2 replicas)
   │ (StatefulSet)     │ (StatefulSet)    │ (Deployment)
   └─────────┘        └─────────┘        └─────────┘
        │                  │
        ▼                  ▼
   ┌─────────────────────────────────────┐
   │       Persistent Volumes            │
   │  (Redis AOF + Qdrant Collections)  │
   └─────────────────────────────────────┘
```

## Troubleshooting

### Pods not starting
```bash
# Check pod events
kubectl describe pod -n ico-cache -l app.kubernetes.io/name=ico-cache

# Check logs
kubectl logs -n ico-cache -l app.kubernetes.io/component=api
```

### Redis connection issues
```bash
# Test Redis connectivity
kubectl exec -n ico-cache -it <redis-pod> -- redis-cli -a $REDIS_PASSWORD ping
```

### Qdrant connection issues
```bash
# Test Qdrant connectivity
kubectl exec -n ico-cache -it <qdrant-pod> -- curl http://localhost:6333/readyz
```

### High memory usage
```bash
# Check Redis memory
kubectl exec -n ico-cache -it <redis-pod> -- redis-cli -a $REDIS_PASSWORD INFO memory

# Check Qdrant memory
curl http://<qdrant-pod>:6333/metrics | grep qdrant_memory
```

## Backup Strategy

- **Frequency**: Daily at 2 AM UTC
- **Retention**: 3 successful backups, 1 failed backup
- **Components**: Redis (RDB), Qdrant (tar.gz), ConfigMaps, Secrets
- **Storage**: PVC with 10Gi capacity
- **Recovery**: Manual restore via `backup-restore.sh` script

## Rollback Procedure

1. Identify target revision: `helm history ico-cache -n ico-cache`
2. Initiate rollback: `./scripts/deployment/rollback.sh -e prod -v <revision>`
3. Verify: `./scripts/deployment/smoke-tests.sh -e prod`
4. Monitor: Check Grafana dashboards for 15 minutes

## Support

For issues with deployment infrastructure, check:
1. GitHub Actions workflow logs
2. Kubernetes events: `kubectl get events -n ico-cache --sort-by=.metadata.creationTimestamp`
3. Pod logs: `kubectl logs -n ico-cache -l app.kubernetes.io/component=api --tail=100`