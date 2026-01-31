# CT Log Benchmarking Plan: Trillian vs. TesseraCT

## 1. Objective
Compare the performance and cost-efficiency of **Trillian** (Legacy) and **TesseraCT** (Modern) Certificate Transparency Log implementations on Google Cloud Platform (GCP).

## 2. Design Decisions & Architecture

### A. Single GCP Project Strategy
We will run both implementations in the **same GCP Project** and **same GKE Cluster**.
*   **Rationale:** Ensures identical network path, latency, and environment variables for a fair comparison.
*   **Node Pool:** Single shared `benchmark-pool` with 2x `e2-standard-2` nodes. Both workloads run on the same pool — isolation is achieved through sequential execution, not node taints.
*   **Costing:** We use **Deterministic Cost** calculated from known infrastructure pricing (Terraform config) via `costs.json`, not Cloud Monitoring queries or delayed GCP Billing exports.

### B. CI/CD Driven Benchmarking
The "Source of Truth" for performance is the GitHub Action run, not a developer's laptop.
*   **Workflow:** `Infra -> Deploy -> Smoke Test -> Bench -> Publish -> Destroy`
*   **Artifacts:** The run produces a summary JSON and markdown table committed back to the repo via Pull Request with full cost breakdown.

### C. Systems Under Test (SUT)
*   **Trillian (Legacy):**
    *   **Architecture:** CTFE -> Trillian Log Server -> Cloud SQL (MySQL).
    *   **Compute:** Shared `e2-standard-2` nodes.
    *   **Storage:** Cloud SQL MySQL 8.0 (db-f1-micro).
*   **TesseraCT (Modern):**
    *   **Architecture:** TesseraCT Server -> Spanner + GCS.
    *   **Compute:** Shared `e2-standard-2` nodes.
    *   **Storage:** Spanner (100 Processing Units), GCS (Standard).

## 3. Test Environment (Infrastructure as Code)
Managed via **Terraform** (`/terraform`) and **ko** for building container images.

*   **Common:** GKE Standard Cluster, Workload Identity.
*   **Trillian:** Cloud SQL Instance (MySQL), Secrets (Password), Service Accounts.
*   **TesseraCT:** Spanner Instance, GCS Bucket, Secrets (Signer Keys), Service Accounts.

## 4. Benchmarking Strategy

### Tools
*   **Trillian:** `ct_hammer` from `certificate-transparency-go`
*   **TesseraCT:** `hammer` from `tesseract/internal`

### Pre-flight
1.  **Smoke test:** Verify both systems accept add-chain requests before committing to a full benchmark run.
2.  **Build tools:** Compile both hammer binaries upfront.

### Measurement
*   **Primary metric:** Sustained write QPS (measured from tree size delta over elapsed time).
*   **Cost metric:** $/1M entries = (cost_per_hour / achieved_qps / 3600) × 1,000,000
*   **Validation:** Hammer exit codes are checked. Minimum thresholds on elapsed time (30s) and entries written (10) are enforced. Results with insufficient data are rejected.
*   **Duration:** Default 15 minutes per system. Longer runs produce more stable results.

### What We Don't Measure
*   **Write latency:** TesseraCT blocks writes on checkpoint integration at a 1-second batch interval. This is an architectural choice, not a bottleneck. Comparing write latency between the two systems would measure a design decision, not performance.

## 5. Cost Model

### Deterministic Infrastructure Costs
All costs are derived from the Terraform configuration and GCP list prices for `us-central1`. See [`costs.json`](costs.json) for the full machine-readable breakdown.

| | Trillian | TesseraCT |
|:---|:---|:---|
| Shared GKE (50%) | $0.178/hr | $0.178/hr |
| Dedicated Backend | $0.015/hr (Cloud SQL) | $0.090/hr (Spanner) |
| **Total** | **$0.193/hr** | **$0.268/hr** |

Variable costs (storage growth, GCS operations) are negligible at benchmark scale and not included in the base calculation.

### Why Not Cloud Monitoring?
GCP Billing data has 24-48 hour latency. Cloud Monitoring metrics for CPU usage are cumulative counters that require careful delta computation and are subject to collection delays. Since the infrastructure is defined in Terraform and the pricing is public, deterministic calculation is both simpler and more accurate.

## 6. Execution Steps
1.  **Build Tools:** Compile `ct_hammer` and `tesseract/hammer`.
2.  **Smoke Test:** Verify both systems accept writes.
3.  **Run Trillian:** Execute load test, record tree size delta and elapsed time.
4.  **Run TesseraCT:** Execute load test, record tree size delta and elapsed time.
5.  **Calculate Costs:** Apply deterministic cost model from `costs.json`.
6.  **Publish:** Open PR with results table, cost breakdown, and raw `benchmark_summary.json`.
