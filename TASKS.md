# Benchmarking Task List

## 1. Tooling & Build
- [x] **Build `ct_hammer`**
    - [x] Resolve dependencies for `certificate-transparency-go`.
    - [x] Verify `ct_hammer` binary functionality.
- [x] **Build `tesseract_hammer`**
    - [x] Resolve dependencies for `tesseract`.
    - [x] Verify `hammer` binary functionality.
- [ ] **Containerize Tools** (Using `ko` + distroless/static)
    - [ ] Configure `ko` for `ct_hammer`.
    - [ ] Configure `ko` for `tesseract_hammer`.
    - [ ] Push images to Artifact Registry.

## 2. Infrastructure (Terraform)
- [ ] **Base Networking & Cluster**
    - [ ] VPC, Subnets.
    - [ ] GKE Standard Cluster (or use Autopilot if simpler for benchmark).
- [ ] **Trillian Stack**
    - [ ] Cloud SQL Instance (MySQL).
    - [ ] Kubernetes Manifests/Helm for Trillian Log Server.
    - [ ] Kubernetes Manifests/Helm for Trillian Log Signer.
    - [ ] Kubernetes Manifests/Helm for CTFE.
    - [ ] Terraform glue to deploy manifests.
- [ ] **TesseraCT Stack**
    - [ ] Cloud Spanner Instance.
    - [ ] GCS Bucket.
    - [ ] Kubernetes Manifests for TesseraCT Server.
    - [ ] Terraform glue to deploy manifests.

## 3. Automation & Analysis Scripts
- [ ] **Metric Collection Script**
    - [ ] Write Python/Go script to query Cloud Monitoring API.
    - [ ] Implement query for CPU/Memory (GKE).
    - [ ] Implement query for Cloud SQL metrics.
    - [ ] Implement query for Spanner/GCS metrics.
    - [ ] Calculate "Derived Cost" based on constants.
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
