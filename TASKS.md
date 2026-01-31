# Task Tracking

## Phase 1: Foundation & Infrastructure (Completed)
- [x] **Tooling:** Setup `ko`, `terraform`, `gcloud` within the repo.
- [x] **Infrastructure:** Define VPC, GKE, Cloud SQL, Spanner via Terraform.
- [x] **Auth:** Configure Workload Identity Federation (moved to `terraform/bootstrap`).
- [x] **Deployment Scripts:** Create `deploy_k8s.sh` for one-shot deployment.

## Phase 2: Orchestration & Automation (Completed)
- [x] **Verify Deployment:** Manually confirm `deploy_k8s.sh` succeeds end-to-end on a fresh cluster.
- [x] **Benchmark Script:** Create `scripts/benchmark.py` to:
    - [x] Invoke `deploy_k8s.sh`. (Note: Manual step for now, but script is ready)
    - [x] Wait for health checks.
    - [x] Run `ct_hammer` against both endpoints.
    - [x] Capture start/end timestamps.
    - [x] Call `metrics.py` to get resource stats.
- [x] **GitHub Action:** Create `.github/workflows/benchmark.yml` that:
    - [x] Authenticates to GCP.
    - [x] Runs `scripts/benchmark.py`.
    - [x] Opens a Pull Request with results.

## Phase 3: Analysis & Reliability (Completed)
- [x] **Benchmark Analysis:** Audited methodology, identified broken results (ANALYSIS.md).
- [x] **Cost Model Overhaul:** Replaced Cloud Monitoring scraping with deterministic `costs.json` pricing.
- [x] **Pipeline Fixes:**
    - [x] Fix `benchmark.yml` grep pattern (was `"Cost:"`, now `"Total Cost:"`).
    - [x] Fix `update_readme.py` regex escaping for `(p95)`.
    - [x] Fix Trillian key encryption (`-traditional` flag for OpenSSL 3.x compatibility).
    - [x] Add hammer exit code validation.
    - [x] Add minimum threshold guards on QPS calculation.
- [x] **Benchmark Quality:**
    - [x] Add smoke tests before main benchmark.
    - [x] Build hammer tools upfront.
    - [x] Scale TesseraCT writers with target QPS.
    - [x] Drop latency as comparison metric (TesseraCT 1s batch interval).
    - [x] Increase default duration to 15 minutes.
- [x] **Documentation:** Update PLAN.md, README.md, TASKS.md to match actual methodology.
    - [x] Remove false isolation claims (single shared node pool, not tainted pools).
    - [x] Document deterministic cost model.
    - [x] Remove latency from results table.

## Future Work
- [ ] **Scaling tests:** Run at multiple infrastructure tiers (bigger SQL instance, more Spanner PUs).
- [ ] **Visualization:** Generate throughput-vs-cost chart across scales.
- [ ] **Node pool isolation:** Add separate tainted pools if contention is observed.
