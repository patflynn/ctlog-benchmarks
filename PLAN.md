# CT Log Benchmarking Plan: Trillian vs. TesseraCT

## 1. Objective
Compare the performance and cost-efficiency of **Trillian** (Legacy) and **TesseraCT** (Modern) Certificate Transparency Log implementations on Google Cloud Platform (GCP).

## 2. Systems Under Test (SUT)

### A. Trillian (Legacy)
*   **Repositories:**
    *   `github.com/google/trillian` (Log Server/Signer)
    *   `github.com/google/certificate-transparency-go` (CT Front End - CTFE)
*   **Architecture:** CTFE -> Trillian Log Server -> Cloud SQL (MySQL).
*   **Storage:** Google Cloud SQL (MySQL).
    *   *Cost Driver:** Instance Type (vCPU/RAM), Storage Capacity (SSD), IOPS.

### B. TesseraCT (Modern)
*   **Repository:** `github.com/transparency-dev/tesseract`
*   **Architecture:** TesseraCT Server -> Spanner + GCS.
*   **Storage:**
    *   **Data Bundles:** Google Cloud Storage (GCS).
    *   **Metadata/Dedup:** Google Cloud Spanner.
    *   *Cost Driver:* Spanner Compute Capacity (Nodes/Processing Units), Spanner Storage, GCS Storage/Ops.

## 3. Test Environment (Infrastructure as Code)
We will use **Terraform** to provision the environments.

*   **Common:**
    *   GKE Standard Cluster or Managed Instance Groups (MIGs) for compute.
    *   Same region/zone placement.

*   **Trillian Specifics:**
    *   Cloud SQL Instance (e.g., `db-custom-4-16384` for baseline).
    *   Trillian Log Signer & Server deployments.
    *   CTFE deployment.

*   **TesseraCT Specifics:**
    *   Spanner Instance (e.g., 100 Processing Units or 1 Node).
    *   GCS Bucket.
    *   TesseraCT Server deployment (`src/tesseract/cmd/tesseract/gcp`).

## 4. Benchmarking Strategy

### Tools
*   **Trillian:** `src/certificate-transparency-go/trillian/integration/ct_hammer`
    *   *Build:* `go build github.com/google/certificate-transparency-go/trillian/integration/ct_hammer`
*   **TesseraCT:** `src/tesseract/internal/hammer`
    *   *Build:* `go build github.com/transparency-dev/tesseract/internal/hammer`

### Scenarios

#### Phase 1: Cost per Increment (Scaling)
*   **Goal:** Determine the marginal cost of adding 500 QPS (Write) and 1000 QPS (Read).
*   **Method:**
    1.  Start with minimal valid infrastructure.
    2.  Ramp up load using `hammer` tools (adjusting `--max_write_ops`, `--max_read_ops`).
    3.  Scale infrastructure (Auto-scaling or manual step-up) to maintain SLO (<500ms latency, <1% error).
    4.  Record resource usage at stable state.

#### Phase 2: Fixed Investment (Capacity)
*   **Goal:** Maximize QPS for a fixed daily budget (e.g., $50/day).
*   **Budget Allocation:**
    *   **Trillian:** ~2 vCPU Cloud SQL + 2 vCPU Compute.
    *   **TesseraCT:** ~100 PU Spanner + 2 vCPU Compute. (Note: Spanner minimums might dictate the budget floor).
*   **Method:**
    1.  Fix the backend resources.
    2.  Increase load until saturation (Latency spike or Error rate > 1%).
    3.  Compare max sustainable QPS.

## 5. Metrics & Cost Analysis
*   **Primary Metric:** `$/(1000 QPS)` for Writes and Reads.
*   **Secondary Metric:** Max QPS @ Fixed Budget.
*   **Data Collection:**
    *   GCP Cloud Monitoring (CPU, Memory, DB Load).
    *   Client-side metrics from `hammer` tools (Latency histograms, Throughput).

## 6. Execution Steps
1.  **Build Tools:** Compile `ct_hammer` and `tesseract/hammer`.
2.  **Provision Infra:** Create Terraform for both stacks.
3.  **Run Phase 1:** Execute scaling tests.
4.  **Run Phase 2:** Execute capacity tests.
5.  **Analyze:** Aggregate logs and billing estimates.