# Benchmarking Task List

## 1. Tooling & Build
- [x] **Build `ct_hammer`**
    - [x] Resolve dependencies for `certificate-transparency-go`.
    - [x] Verify `ct_hammer` binary functionality.
- [x] **Build `tesseract_hammer`**
    - [x] Resolve dependencies for `tesseract`.
    - [x] Verify `hammer` binary functionality.
- [x] **Containerize Tools** (Using `ko` + distroless/static)
    - [x] Configure `ko` for `ct_hammer`.
    - [x] Configure `ko` for `tesseract_hammer`.
    - [x] Push images to Artifact Registry (Handled by `deploy_k8s.sh`).

## 2. Infrastructure (Terraform)
- [x] **Base Networking & Cluster**
    - [x] VPC, Subnets.
    - [x] GKE Standard Cluster (or use Autopilot if simpler for benchmark).
- [x] **Trillian Stack**
    - [x] Cloud SQL Instance (MySQL).
    - [x] Kubernetes Manifests/Helm for Trillian Log Server.
    - [x] Kubernetes Manifests/Helm for Trillian Log Signer.
    - [x] Kubernetes Manifests/Helm for CTFE.
    - [x] Script to deploy manifests (`scripts/deploy_k8s.sh`).
- [x] **TesseraCT Stack**
    - [x] Cloud Spanner Instance.
    - [x] GCS Bucket.
    - [x] Kubernetes Manifests for TesseraCT Server.
    - [x] Script to deploy manifests (`scripts/deploy_k8s.sh`).

## 3. Automation & Analysis Scripts
- [x] **Metric Collection Script**
    - [x] Write Python/Go script to query Cloud Monitoring API.
    - [x] Implement query for CPU/Memory (GKE).
    - [x] Implement query for Cloud SQL metrics.
    - [x] Implement query for Spanner/GCS metrics.
    - [x] Calculate "Derived Cost" based on constants.
- [ ] **Orchestration Script**
    - [ ] "Ramp-up" logic (start low QPS, increase, hold).
    - [ ] Latency/Error check loop (fail if SLO breached).
    - [ ] JSON output writer for results.

## 4. Execution
- [ ] **Phase 1: Trillian Scaling**
    - [ ] Run benchmark.
    - [ ] Collect data.
- [ ] **Phase 1: TesseraCT Scaling**
    - [ ] Run benchmark.
    - [ ] Collect data.
- [ ] **Phase 2: Capacity (Fixed Budget)**
    - [ ] Configure Trillian limited resources.
    - [ ] Measure Max QPS.
    - [ ] Configure TesseraCT limited resources.
    - [ ] Measure Max QPS.

## 5. Reporting
- [ ] **Data Aggregation**
    - [ ] Combine all JSON outputs.
- [ ] **Final Report**
    - [ ] Generate markdown summary with cost comparisons.
