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
- [ ] **GitHub Action:** Create `.github/workflows/benchmark.yml` that:
    - [ ] Provisions Infra.
    - [ ] Runs `scripts/benchmark.py`.
    - [ ] Commits updated results to `README.md`.
    - [ ] Destroys Infra (always).

## Phase 3: Analysis & Polishing
- [ ] **Cost Formula:** Refine `metrics.py` to include Spanner node costs and Cloud SQL instance sizing.
- [ ] **Visualization:** (Optional) Generate a simple graph of throughput vs. latency.