# Namespace request: two no-offload shard namespaces (brief)

Names (owner-prefixed): yangligt-shard-a, yangligt-shard-b.
Purpose: the sharded-router control for the N-dependence experiment
(two independent 8-replica no-offload fleets vs one 16-replica fleet
at matched per-capacity load). Runs start the moment pods are ready.

## Blueprint: clone namespace igw-llm-d (the NO-offload stack)

Per namespace, clone:

1. Deployment no-offloading-tp4-vllm - INITIAL REPLICAS: 8.
   Args byte-identical (no offloading flags; --block-size=256,
   --kv-cache-dtype=fp8, KV events on port 5556,
   VLLM_SERVER_DEV_MODE=1). Same gcsfuse model volume (bucket
   a4x-igw-testing) and ServiceAccount.
2. Deployment + Service no-offloading-tp4-epp, envoy ConfigMap, and
   ConfigMap no-offloading-tp4-epp-precise-prefix-cache (the EPP
   deployment mounts THIS configmap - keep the mount reference).
   Patch the namespace string inside the token-producer vllm url
   (http://no-offloading-tp4-vllm.<NS>.svc...). EPP replicas stay 1;
   blockSizeTokens 256 unchanged.
3. InferencePool CR + SA/RBAC referenced by the EPP.

## Per-namespace prerequisites

- Bucket IAM (read-only suffices):
  gcloud storage buckets add-iam-policy-binding gs://a4x-igw-testing \
    --member="principalSet://iam.googleapis.com/projects/455207029971/locations/global/workloadIdentityPools/supercomputer-testing.svc.id.goog/namespace/<NS>" \
    --role="roles/storage.objectViewer"
  If pods stall Init with GCS PermissionDenied after the grant,
  bounce them once (propagation).
- bench-assets: seed PVC + pod with
  nodeSelector topology.kubernetes.io/zone=us-central1-a on the seed
  pod (PD clones cannot cross zones), seed tokenizer + datasets
  (925M), recreate the ROX bench-assets clone. Same drill as
  yangligt-4x.

## Capacity and readiness

8 GPU hosts per namespace (16 total) + CPU-pool room for EPP/envoy.
Ready = no-offloading-tp4-vllm readyReplicas 8/8 and `bench.sh
endpoints -N <NS>` listing the EPP service. I take over from there
(runs, collection, scale-down at window end).
