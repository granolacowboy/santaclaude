# Kubernetes Deployment - Phase 2 Santaclaude

This directory contains Kubernetes manifests for the Phase 2 microservices architecture as defined in `santaclaude-DESIGN-PLAN.md`.

## Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   AI Service    │    │Browser Pool Svc │    │ Audit Sink Svc  │
│    (Port 8001)  │    │    (Port 8002)  │    │   (Port 8003)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
         ┌─────────────────┐     │     ┌─────────────────┐
         │Message Queue Svc│─────┴─────│   Redis Streams │
         │   (Port 8004)   │           │   (Port 6379)   │
         └─────────────────┘           └─────────────────┘
                 │
         ┌─────────────────┐           ┌─────────────────┐
         │  ProjectFlow AI │           │   ClickHouse    │
         │   (Port 8000)   │           │  (Ports 9000,   │
         │                 │           │        8123)    │
         └─────────────────┘           └─────────────────┘
```

## Services

### Core Microservices (Phase 2 Extracted)

1. **AI Service** (`ai-service/`)
   - AI model routing and session management
   - Replicas: 2-10 (HPA enabled)
   - Dependencies: Redis

2. **Browser Pool Service** (`browser-pool-service/`)
   - Playwright browser automation
   - Replicas: 2-5 (resource intensive)
   - Dependencies: Redis, shared memory volume

3. **Audit Sink Service** (`audit-sink-service/`)
   - Append-only audit logging to ClickHouse
   - Replicas: 2-8 (HPA enabled)
   - Dependencies: Redis, ClickHouse

4. **Message Queue Service** (`message-queue-service/`)
   - Redis Streams event distribution
   - Replicas: 2-6 (HPA enabled)
   - Dependencies: Redis

### Infrastructure Services

5. **Redis** (`shared/redis.yaml`)
   - Event streaming and caching
   - Persistent storage with PVC
   - Health checks enabled

6. **ClickHouse** (`shared/clickhouse.yaml`)
   - Time-series analytics for audit logs
   - Persistent storage with PVC
   - HTTP and native TCP ports exposed

## Deployment

### Prerequisites

```bash
# Ensure kubectl is configured for your cluster
kubectl cluster-info

# Create namespace
kubectl apply -f shared/namespace.yaml
```

### Infrastructure First

```bash
# Deploy Redis and ClickHouse
kubectl apply -f shared/redis.yaml
kubectl apply -f shared/clickhouse.yaml

# Wait for infrastructure to be ready
kubectl wait --for=condition=ready pod -l app=redis -n santaclaude --timeout=300s
kubectl wait --for=condition=ready pod -l app=clickhouse -n santaclaude --timeout=300s
```

### Microservices Deployment

```bash
# Deploy in dependency order
kubectl apply -f message-queue-service/
kubectl apply -f ai-service/
kubectl apply -f browser-pool-service/
kubectl apply -f audit-sink-service/

# Verify deployments
kubectl get pods -n santaclaude
kubectl get services -n santaclaude
```

### Health Checks

```bash
# Check service health
kubectl get pods -n santaclaude -w

# Port forward for testing (in separate terminals)
kubectl port-forward -n santaclaude svc/ai-service 8001:8001
kubectl port-forward -n santaclaude svc/browser-pool-service 8002:8002
kubectl port-forward -n santaclaude svc/audit-sink-service 8003:8003
kubectl port-forward -n santaclaude svc/message-queue-service 8004:8004

# Test endpoints
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
```

## Configuration

### Secrets Management

Before deployment, create the required secrets:

```bash
# AI Service API Keys
kubectl create secret generic ai-service-secrets \
  --from-literal=openai-api-key="your-openai-key" \
  --from-literal=anthropic-api-key="your-anthropic-key" \
  -n santaclaude
```

### ConfigMaps

All services use ConfigMaps for non-sensitive configuration. Update the values in the respective deployment files before applying.

## Scaling and Performance

### Horizontal Pod Autoscaler (HPA)

All services have HPA configured:

- **AI Service**: 2-10 replicas (CPU 70%, Memory 80%)
- **Browser Pool**: 2-5 replicas (CPU 60%, Memory 70%)
- **Audit Sink**: 2-8 replicas (CPU 70%, Memory 80%)
- **Message Queue**: 2-6 replicas (CPU 70%, Memory 80%)

### Resource Requests/Limits

Services are configured with appropriate resource requests and limits:

```yaml
# Example from AI Service
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Node Affinity

Browser Pool Service prefers nodes with label `node-type=browser-pool` for optimal performance.

## Monitoring and Observability

### Prometheus Metrics

All services expose metrics on their main ports with annotations:

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/path: "/metrics"
  prometheus.io/port: "8001"
```

### Health Endpoints

- `/health` - Liveness probe endpoint
- `/ready` - Readiness probe endpoint
- `/metrics` - Prometheus metrics endpoint

### Logging

Services log to stdout/stderr for collection by your logging solution (Fluentd, Logstash, etc.).

## Security

### Pod Security Context

All services run with security contexts:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true  # where possible
```

### Network Policies

Consider implementing NetworkPolicies to restrict inter-service communication to only required connections.

## Troubleshooting

### Common Issues

1. **Browser Pool Service fails to start**
   - Check shared memory volume mount
   - Verify `ENABLE_SANDBOX=false` for containers
   - Ensure sufficient node resources

2. **AI Service connection errors**
   - Verify API key secrets are created
   - Check Redis connectivity
   - Validate environment variables

3. **Audit Sink connectivity issues**
   - Ensure ClickHouse is running and accessible
   - Check database initialization
   - Verify Redis streams configuration

### Debugging Commands

```bash
# Check pod logs
kubectl logs -n santaclaude deployment/ai-service -f

# Describe pod for events
kubectl describe pod -n santaclaude -l app=ai-service

# Check service endpoints
kubectl get endpoints -n santaclaude

# Test Redis connectivity
kubectl exec -it -n santaclaude deployment/redis -- redis-cli ping

# Check ClickHouse
kubectl exec -it -n santaclaude deployment/clickhouse -- clickhouse-client --query="SELECT 1"
```

## Backup and Recovery

### Persistent Volumes

The following services use persistent storage:

- Redis: `/data` (1Gi)
- ClickHouse: `/var/lib/clickhouse` (5Gi)  
- AI Service: `/app/data` (1Gi)

Ensure your cluster has a backup solution for PVCs.

### Database Backup

For ClickHouse backup:

```bash
# Create backup
kubectl exec -n santaclaude deployment/clickhouse -- \
  clickhouse-client --query="BACKUP DATABASE audit TO Disk('backups', 'audit-backup')"
```

## Next Steps

1. **Ingress Configuration**: Set up ingress controllers and rules
2. **TLS Certificates**: Configure cert-manager for HTTPS
3. **Monitoring Stack**: Deploy Prometheus, Grafana, and alerting
4. **Service Mesh**: Consider Istio for advanced traffic management
5. **GitOps**: Implement ArgoCD or Flux for automated deployments