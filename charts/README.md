# Remote Jobs API — Helm Chart

Kubernetes chart for the [Remote Jobs Data API](https://github.com/earnnova-dev/remote-jobs-api).
Deploys the normalized remote-job data API (5 boards, skill matching, per-plan
rate limits) as a single Deployment with a persistent key store.

## What it provisions

| Resource | Purpose |
|---|---|
| `Secret` | Admin token (random-generated, or your `existingSecret`) |
| `ServiceAccount` | For the pod |
| `Deployment` | The API server on port 8321 |
| `Service` | `ClusterIP` (or your `service.type`) |
| `PersistentVolumeClaim` | Persists the API-key store across restarts |
| `Ingress` | Optional, for a public hostname |
| `PodDisruptionBudget` | Optional |
| `NetworkPolicy` | Optional egress allowlist (HTTP/HTTPS + DNS) |

## Install

### 1. Build the image
```bash
git clone https://github.com/earnnova-dev/remote-jobs-api
cd remote-jobs-api
docker build -t <registry>/remote-jobs-api:latest .
docker push <registry>/remote-jobs-api:latest
```

### 2. Install the chart
```bash
# Using the packed chart:
helm install rja remote-jobs-api-1.0.0.tgz \
  --namespace rja --create-namespace \
  --set image.repository=<registry>/remote-jobs-api \
  --set image.tag=latest

# ...or from this directory:
helm install rja ./remote-jobs-api-chart \
  --namespace rja --create-namespace \
  --set image.repository=<registry>/remote-jobs-api
```

### 3. Get the admin token
The chart generates one. Retrieve it:
```bash
kubectl -n rja get secret rja-rja -o jsonpath="{.data.token}" | base64 -d
```

### 4. Create a customer key
```bash
ADMIN=<token-from-above>
# port-forward (ClusterIP) or use your ingress host
kubectl -n rja port-forward svc/rja-remote-jobs-api 8321:8321
curl -X POST http://localhost:8321/admin/keys \
  -H "Authorization: Bearer ***" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","label":"customer-1"}'
```
Returns a key like `rja_live_...` — hand that to the customer.

## Key values

| Value | Default | Notes |
|---|---|---|
| `image.repository` | `ghcr.io/earnnova-dev/remote-jobs-api` | Set to your registry |
| `image.tag` | `latest` | |
| `replicaCount` | `1` | Keep at 1 while PVC is `ReadWriteOnce`; scale only with `ReadWriteMany` |
| `adminToken.create` | `true` | Chart generates the secret |
| `adminToken.existingSecret` | `""` | Use your own pre-made secret instead |
| `adminToken.key` | `token` | Key name inside the secret |
| `service.type` | `ClusterIP` | Set `LoadBalancer`/`NodePort` to expose directly |
| `ingress.enabled` | `false` | Enable + set `ingress.host` for a public URL |
| `persistence.enabled` | `true` | Required for keys to survive restarts |
| `networkPolicy.enabled` | `false` | Restricts egress to feeds + DNS |

### Using your own admin secret
```bash
kubectl -n rja create secret generic rja-admin \
  --from-literal=token="<long-random-string>"
helm install rja ./remote-jobs-api-chart -n rja \
  --set adminToken.create=false --set adminToken.existingSecret=rja-admin
```

## Plans & limits
`free` = 100 calls/mo · `pro` = 10,000 · `team` = 100,000 (per key, reset monthly).

## Uninstall
```bash
helm uninstall rja -n rja   # removes resources incl. the PVC (keys are gone)
```
