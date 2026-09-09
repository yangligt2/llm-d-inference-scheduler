# Namespace request: 4-replica CPU-offloading stack (one namespace)

One additional namespace is sufficient for all queued experiments.
Fleet roles after it exists:

    igw-llm-d   8x no-offload (unchanged)
    yangligt    8x cpu-offload (unchanged)
    NEW         4x cpu-offload - the 4-replica tier geometry

First experiment on it (ready to run the moment the stack is up):
the scale-question falsifier - base 0.011 sps x 300 min + surge
0.125 sps x 2700 s at t ~ +62 min. DES prediction: waiting 75-142 at
min 270-295 (mild congestion); waiting ~0 falsifies the DES and
makes the 4x point genuinely stable (restore_boundary.csv, lam4x
rows). Afterwards: 4x tier ladder points and A4 variants.

## Blueprint: clone namespace yangligt, exactly

Clone these objects from yangligt (rename namespace only; keep every
name, arg, and parameter identical unless listed under Deltas):

1. Deployment cpu-offloading-tp4-vllm
   - KEEP the full vllm arg list byte-identical, in particular:
     --kv-offloading-backend=native --kv-offloading-size=500
     --block-size=256 --kv-cache-dtype=fp8 --tensor-parallel-size=4
     --kv-events-config '{"enable_kv_cache_events":true, "topic":
     "kv@$(POD_IP):8000@..."}' and VLLM_SERVER_DEV_MODE=1 (needed by
     bench.sh /reset_prefix_cache).
   - Model volume: gcsfuse CSI, bucket a4x-igw-testing, same
     volumeAttributes - no PVC/model copy needed. Preserve the
     ServiceAccount / workload-identity annotations that grant GCS
     read (check the pod SA in yangligt).
   - dshm emptyDir (Memory, 100Gi) and local-ssd volumes as-is.
2. Deployment + Service cpu-offloading-tp4-epp, the envoy ConfigMap,
   and ConfigMap cpu-offloading-tp4-epp (EPP plugins). Invariants
   recorded in that ConfigMap's comments:
   - blockSizeTokens (256) MUST equal vllm --block-size.
   - EPP replicas stay 1 (token-load-scorer state is per-process).
   - token-producer vllm url is namespace-scoped - update the
     namespace in http://cpu-offloading-tp4-vllm.<NS>.svc... .
   - peakPrefillThroughput 28888 stays (same pod type, per-replica).
3. The InferencePool CR fronted by the EPP service, plus any
   RBAC/ServiceAccount objects the EPP uses (list objects in
   yangligt and clone whatever references the pool/EPP).

## Deltas vs yangligt

    replicas            4 (not 8) on cpu-offloading-tp4-vllm
    namespace           new (suggestion: yangligt-4x)
    EPP configmap url   namespace string inside token-producer url

## bench-assets (required before any run)

Create bench-assets-seed PVC + seed pod WITH
nodeSelector topology.kubernetes.io/zone=us-central1-a on the pod -
GCE PD clones cannot cross zones and the GPU nodes are in -a; an
unpinned seed pod landing in -b bricks the ROX clone (hit on
2026-08-09; patched manifest pattern in lab notebook). Then seed
tokenizer + datasets (925M, from guides/subslicing/inf-perf assets;
bench.sh setup-assets flow) and create the ROX bench-assets clone.
The aiperf harness needs nothing else namespace-specific.

## Capacity

4 GPU hosts (4x GB200 each) for the vllm pods + CPU-pool capacity
for EPP/envoy (1 small node). Model load via gcsfuse ~20-30 min on
first rollout.

## Verification checklist (5 min, before first run)

    kubectl -n <NS> get pods                     # 4x vllm 2/2, epp 2/2
    bench.sh endpoints -N <NS>                   # lists the EPP service
    EPP log shows 4 discovered KV-event backends (port 5556)
    kubectl -n <NS> exec <vllm-pod> -c vllm -- \
      curl -s -X POST localhost:8000/reset_prefix_cache  # 200 OK
    bench-assets PVC Bound after first job mounts it

Run commands then follow the standard pattern, e.g.:

    ./bench.sh lifecycle -n cpuofl4x-b2a300 \
      -c bench-config-weka-b2-base-sps011-300m.yaml \
      -N <NS> -s cpu-offloading-tp4-epp -o ./reports
    (+ surge at t+62: bench-config-weka-b2-surge-sps0125-45min.yaml,
     -r false; config with duration 18000s to be created at kickoff)

Analysis note: the 4x fleet pool constant is POOL_4X in
extract_arcs.py; the yangligt service-IP exclusion list gains the new
namespace's EPP ClusterIP (add it to SERVICE_EPS when extracting).
