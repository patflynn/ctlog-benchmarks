# TesseraCT on Cloud Run: write-throughput benchmark

Tooling and results for benchmarking [TesseraCT](https://github.com/transparency-dev/tesseract)
(`cmd/tesseract/gcp`, v0.2.0) on Cloud Run with Spanner + GCS. The aim was to find the
realistic maximum sustained write QPS of a single log shard, and what limits it.

## Headline results (us-east4, v0.2.0)

* **Single-shard write ceiling ≈ 680–710 QPS × N Cloud Run instances.** Measured steady-state
  2xx/s ceilings: N=1 ~677, N=2 ~1,330, N=3 ~2,040, N=4 ~2,740, N=5 ≥3,000 (3,430 peak). The
  limit is Cloud Run's hard cap of 1,000 concurrent requests per instance, divided by the
  ~1.15–1.45s each `add-chain` is held open by the publication awaiter (batch → integrate →
  `--checkpoint_interval=1100ms` publication). CPU (≤36%) and Spanner (≤7.5% at 2000 PU) were
  never the bottleneck. Spanner PU, connection pools and batch size don't move the ceiling.
  europe-west3 gives the same result.
* **Direct VPC egress (`all-traffic`) is mandatory.** For duplicates-only traffic at 1,000 QPS,
  Direct VPC served 1,000/s at p50 276ms with 0 errors. Default serverless egress managed
  only 440/s at p50 8.7s, with ~30% 5xx, because duplicate resolution reads GCS entry bundles.
* **Keep `--batch_max_age=500ms`.** At 100ms and 250ms there are intermittent integration
  stalls (8s `--http_deadline` 5xx) and the ceiling doesn't improve.
* `cpu-throttling: "true"` makes no difference under sustained load with `minScale≥2`.
  `false` remains the safe choice for publication during idle periods.
* Raise `--pushback_max_antispam_lag` (we used 10000). The default 2048 throttles at ~1,300+ QPS.
* An experimental Spanner lease that gates Tessera's singleton background jobs (draft PR
  [transparency-dev/tessera#1242](https://github.com/transparency-dev/tessera/pull/1242))
  removes ~99% of multi-instance coordinator lock wait and lowers sub-ceiling p50 by 10–18%.
  It raises the ceiling by only 0.5–4%.

## Topology

* `tesseract-bench`: a Cloud Run service (gen2, 8 vCPU, `ingress: internal`, no public
  endpoints), defined as a kustomize base in `base/` plus experiment overlays in `overlays/`.
* `tesseract-hammer`: a Cloud Run Job running TesseraCT's `internal/hammer` from inside the VPC
  (Direct VPC egress). `hammer/entrypoint.sh` mints an ID token from the metadata server for
  the job's service account, so no user credentials are passed as job args. Multi-task
  executions (`--hammer_tasks=N`) split the load. Tasks > 0 use a disjoint `--serial_offset`,
  and all duplicates come from task 0.
* Each QPS step is one job execution. Throughput is measured from the checkpoint size delta,
  and per-minute `run.googleapis.com/request_count` / `request_latencies`
  (`monitoring_summary.py`). For multi-task steps, prefer `request_count`, because tasks start
  up to ~20s apart.

## Overlays

| overlay | what it tests |
|---|---|
| `r1-baseline` | 2 instances, CPU always on, default egress |
| `r2-cpu-throttled` | request-scoped CPU |
| `r3-direct-vpc` | Direct VPC egress (`all-traffic`) |
| `r4-scale1` / `r4-scale3` | 1 / 3 instances |
| `r4b-fast-batch` | `--batch_max_age=100ms` |
| `r5-max-ceiling` | 3 instances, 16 GiB, Direct VPC, tuned flags (250ms batching) |
| `r5b-batch500` | `r5` with 500ms batching (recommended config) |
| `r6-scale4` / `r6b-scale5` | `r5` flags with 4 / 5 instances |
| `r7-eu-parity` | `r5b` in europe-west3 |

The base disables `--rate_limit_old_not_before`, because hammer's synthetic certificates have
`notBefore=2023-01-01` and would otherwise be rate-limited to 500/s per instance. Patches that
touch positional args use JSON-patch `test` ops, so a base change can't silently patch the
wrong flag.

## Running

1. Create `.env.local` in the repo root (gitignored). See `env.local.example`.
2. Bootstrap the project: APIs, runtime SA (`spanner.databaseUser`, `storage.objectAdmin`,
   `secretmanager.secretAccessor`, `logging.logWriter`, `monitoring.metricWriter`,
   `cloudtrace.agent`), a custom VPC + subnet with Private Google Access, the Spanner
   instance/DBs, the GCS bucket, ECDSA P-256 signer keys in Secret Manager (SEC1 private key,
   pinned numeric versions), and the roots PEM secret.
3. Build images from the same TesseraCT tag (server: `ko build ./cmd/tesseract/gcp`; hammer:
   `hammer/build.sh <tesseract-checkout>`), then deploy the job (see `run_eu_parity.sh` for the
   exact `gcloud run jobs deploy` flags).
4. Run a sweep:
   ```bash
   source .env.local
   python3 cloudrun/run_cloudrun_bench.py --project_id="$PROJECT_ID" --region="$REGION" \
     --overlay=cloudrun/overlays/r5b-batch500 --hammer_tasks=2 --qps_levels=1000,2000,3000
   ```
   `run_queue.sh`, `run_r8.sh`, `run_followups.sh` and `run_eu_parity.sh` are the exact
   sequences used for the results in `results/`.

`results/<timestamp>_<overlay>/` holds the per-step JSON (UTC windows, checkpoint deltas) and
the hammer logs. Project identifiers have been replaced with `PROJECT_ID` / `PROJECT_NUMBER`.
