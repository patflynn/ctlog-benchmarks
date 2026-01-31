# Benchmark Analysis & Improvement Recommendations

## Executive Summary

The current benchmark results (PR #4 and prior) are **not trustworthy**. The latest
run (5m @ 500 QPS) produced clearly broken data: Trillian reported "136.97 QPS"
from a hammer that crashed immediately, TesseraCT achieved only 1 QPS against a
500 QPS target, and cost numbers are off by orders of magnitude. There are bugs
in the reporting pipeline, the cost model, and the QPS measurement logic.

This document catalogs the specific issues, then proposes a revised approach.

---

## Part 1: PR #4 — What Went Wrong

### 1.1 Trillian Hammer Crashed Immediately

From the CI log (run 21533754146):

```
F0130 23:06:58.747939  main.go:197] Failed to make cert generator:
  failed to retrieve signer for re-signing:
  failed to decrypt file "testdata/int-ca.privkey.pem":
  x509: no DEK-Info header in block
```

`ct_hammer` exited with `FATAL` within milliseconds of starting. The DES3-encrypted
intermediate key (`benchmark.py:74`) was produced by `openssl rsa ... -des3 -passout
pass:babelfish`, but `ct_hammer` couldn't parse it. **Zero load was generated.**

The tree went from size 0 → 1 because the **latency probe thread** (which runs
concurrently) managed to submit one `add-chain` request before the hammer's failure
was noticed.

### 1.2 Bogus "136.97 QPS" for Trillian

The QPS formula (`benchmark.py:247`):

```python
achieved_qps = (final_size - initial_size) / (end_time - start_time)
```

Since the hammer crashed in milliseconds: `(1 - 0) / 0.0073 ≈ 137`. This is a
mathematical artifact of dividing by near-zero elapsed time, not real throughput.

### 1.3 TesseraCT Achieved 1 QPS (Target: 500)

The TesseraCT hammer ran for the full 5 minutes but only wrote 301 entries
(tree: 211 → 512). That's ~1 QPS, 0.2% of the 500 QPS target. The hammer
reported "Max runtime reached; exiting", meaning it ran out of time before reaching
its `--leaf_write_goal=150000`. The system was severely under-performing its target,
likely due to only 2 writers (`--num_writers=2`) against a 100 PU Spanner instance
with no warmup.

### 1.4 Empty Cost Fields in RESULTS.md and PR Body

The workflow's "Parse Results" step (`benchmark.yml:87`) greps for:

```bash
TR_COST=$(grep "Trillian Cost:" benchmark_output.txt | awk '{print $3}')
```

But `benchmark.py:314` prints `"Trillian Total Cost:  $1.4941"`. The grep pattern
`"Trillian Cost:"` doesn't match `"Trillian Total Cost:"`, so `$TR_COST` and
`$TE_COST` are empty strings. This is why RESULTS.md shows blank cost cells and
the PR body shows empty cost columns.

### 1.5 Latency (p95) Still Shows "Pending" in README

`update_readme.py:45` uses the metric label directly in a regex:

```python
pattern = rf"\| \*\*{label}\*\* \| .*? \| .*? \|"
```

When `label = "Latency (p95)"`, the parentheses become regex group syntax instead
of matching literal `(` and `)`. The pattern silently fails to match the README row,
so the "Latency (p95)" row is never updated from `*Pending*`.

### 1.6 Absurd Cost-per-1M Numbers

The PR shows:
- Trillian: **$181.80 / 1M entries**
- TesseraCT: **$10,243.98 / 1M entries**

These are derived by dividing a small infrastructure cost by the tiny number of
entries actually written. Since the hammers barely ran, these numbers reflect
infrastructure idle cost divided by near-zero throughput — not meaningful
cost-efficiency data.

### 1.7 Storage Shows "0.0000 GB" for Both

Cloud Monitoring storage metrics either weren't available in the query window
or returned zero. The `get_metric_avg` function silently returns 0 on any error
(`metrics.py:47`), masking the real issue.

---

## Part 2: Systemic Benchmark Methodology Problems

These issues exist independently of the PR #4 crash.

### 2.1 No Validation That Hammers Actually Ran

`benchmark.py` doesn't check the hammer subprocess exit code. `process.wait()`
returns the code, but it's ignored (`benchmark.py:233`). A `FATAL` crash, a
segfault, or a configuration error all produce "results" that get reported as if
the benchmark succeeded. The `--ignore_errors` flag on `ct_hammer` further masks
problems.

**Minimum fix:** Check `process.returncode != 0`, assert `final_size - initial_size
> reasonable_threshold`, and abort if either fails.

### 2.2 QPS Calculation Is Fragile

`(final_size - initial_size) / elapsed_time` is the right idea, but:

- If elapsed_time is near zero (crash), it produces infinity-scale numbers.
- If the hammer ran but most writes failed, `final_size` understates real
  throughput while `elapsed_time` includes the full duration.
- The TesseraCT `get_log_size` reads from GCS checkpoint which may lag behind
  actual writes by seconds to minutes.

**Better approach:** Use the hammer tools' own reported throughput metrics where
available, and cross-check against tree size delta. The TesseraCT hammer already
reports write throughput in its UI. `ct_hammer` logs operations completed.

### 2.3 Write Latency Is Not a Meaningful Comparison Metric

TesseraCT batches writes and blocks on full checkpoint integration, which runs on
a **1-second batch interval** by default. This means every `add-chain` call to
TesseraCT has a latency floor of ~1 second regardless of server performance — it's
an architectural choice, not a bottleneck. Trillian has no equivalent batching
mechanism.

Comparing write latency between the two systems is therefore not meaningful: it
measures a design decision (batching interval), not operational efficiency.

The current latency probe (`benchmark.py:142-183`) has additional problems that
make its numbers unreliable even for single-system analysis:

- Spawns a `curl` subprocess per probe (~5-10ms fork+exec overhead)
- No TCP connection reuse (measures connect time, not just server time)
- ~150 samples over 5 minutes is too few for reliable percentiles
- The probe adds load during the benchmark
- Reuses the same certificate (may trigger dedup logic)
- Runs during startup/teardown, not just steady state

**Recommendation:** Drop latency as a comparison metric entirely. Focus on
**throughput** (sustained write QPS) and **cost-efficiency** (QPS per $/hr) as
the primary comparison axes.

### 2.4 Cost Model Has Dimensional Errors

**`metrics.py` treats cumulative counters as gauges:**

`cloudsql.googleapis.com/database/cpu/usage_time` and
`kubernetes.io/container/cpu/core_usage_time` are **cumulative counters** (total
seconds of CPU consumed since container start). `get_metric_avg` averages the raw
counter values across data points, which gives the mean of an ever-increasing
counter — not the CPU utilization rate.

To get actual CPU rate from a cumulative counter, you need:
`(last_value - first_value) / (last_timestamp - first_timestamp)`

**Storage cost uses wrong pricing constant:**

`metrics.py:70`:
```python
report["costs"]["storage"] = report["metrics"]["storage_gb"] * \
    (duration_hours / (24 * 30)) * PRICING["sql_ram_gb_hour"]
```

This uses `sql_ram_gb_hour` ($0.0070) as a proxy for storage price. Cloud SQL
storage is ~$0.170/GB/month, not $0.007/GB/hour.

**Missing cost components:**

| Component | Status |
|:---|:---|
| GKE cluster management fee ($0.10/hr standard) | Not included |
| GKE node compute (fixed: 2× e2-standard-2) | Uses unreliable metric query |
| Cloud SQL instance hourly cost (db-f1-micro) | Not included — only CPU usage_time |
| Load Balancer cost (2× $0.025/hr) | Not included |
| Network egress | Not included |
| GCS Class A operations | Pricing defined but never queried |
| Cloud SQL storage ($/GB/month) | Wrong pricing constant |

### 2.5 Infrastructure Doesn't Match the Plan

**PLAN.md** specifies separate node pools with taints:
> Pool `trillian-pool`: Tainted `workload=trillian`
> Pool `tesseract-pool`: Tainted `workload=tesseract`

**gke.tf** has a single shared `benchmark-pool` with 2 nodes, no taints. Both
workloads share the same nodes, meaning CPU/memory contention between Trillian
and TesseraCT pods affects results. The README's claim of "isolated Node Pools to
ensure no CPU/Memory contention" is currently not true.

### 2.6 Tests Run Sequentially Without Isolation

Trillian runs first, then TesseraCT runs on the same cluster. The second test
inherits any resource pressure (disk I/O, memory cache state, network buffers)
from the first. The 30-second pause between tests is insufficient for system
state to fully reset.

### 2.7 No Warmup Phase

Neither system gets a warmup period before measurement begins. Spanner in
particular is known to need time to distribute load across its splits after a
cold start. Cloud SQL connection pools, Go runtime GC, and Kubernetes pod
scheduling all benefit from warmup.

### 2.8 Hammer Tools Have Different Semantics

| Aspect | ct_hammer (Trillian) | hammer (TesseraCT) |
|:---|:---|:---|
| Termination | Operations count | Time-based + write goal |
| Writers | Single-threaded rate limiter | Configurable num_writers |
| Reads | Integrated into operations | Separate reader goroutines |
| Metrics | Logs to stderr | Interactive UI |
| Error handling | `--ignore_errors` flag | Fails on error |

Direct QPS comparison between tools that work fundamentally differently requires
careful normalization. The current approach doesn't account for these differences.

---

## Part 3: What a Sound Cost Model Looks Like

The current approach of scraping Cloud Monitoring for resource usage and
multiplying by prices is fragile and error-prone. A better approach recognizes
that **most costs in this benchmark are fixed and deterministic** — they're
defined in the Terraform configuration.

### 3.1 Fixed Infrastructure Costs (Known from Terraform)

These costs are incurred for the duration of the benchmark regardless of
throughput:

| Component | Resource | Hourly Rate | Source |
|:---|:---|:---|:---|
| **GKE Cluster** | Standard management fee | $0.10/hr | [GKE pricing](https://cloud.google.com/kubernetes-engine/pricing) |
| **GKE Nodes** | 2× e2-standard-2 (2 vCPU, 8GB) | 2 × $0.0670 + 2 × $0.0360 = $0.2060/hr | [Compute pricing](https://cloud.google.com/compute/vm-instance-pricing) |
| **Cloud SQL** | db-f1-micro (shared vCPU, 0.6GB) | $0.0150/hr | [Cloud SQL pricing](https://cloud.google.com/sql/pricing) |
| **Spanner** | 100 Processing Units, regional | $0.0900/hr | [Spanner pricing](https://cloud.google.com/spanner/pricing) |
| **Load Balancers** | 2× forwarding rules | 2 × $0.025 = $0.0500/hr | [LB pricing](https://cloud.google.com/vpc/network-pricing) |
| | | **Total: $0.4610/hr** | |

#### Per-System Allocation

**Shared infrastructure** (GKE cluster + nodes + LBs) costs $0.3560/hr. A
reasonable split is 50/50 since both systems use one LB and roughly equal node
resources:

| | Trillian | TesseraCT |
|:---|:---|:---|
| Shared (50%) | $0.1780/hr | $0.1780/hr |
| Dedicated backend | $0.0150/hr (Cloud SQL) | $0.0900/hr (Spanner) |
| **Subtotal** | **$0.1930/hr** | **$0.2680/hr** |

For a 5-minute test:
- Trillian: $0.0161
- TesseraCT: $0.0223

### 3.2 Variable Costs (Usage-Dependent)

| Component | Rate | Notes |
|:---|:---|:---|
| Cloud SQL storage | $0.170/GB/month | Grows with entries |
| Spanner storage | $0.30/GB/month | Grows with entries |
| GCS storage | $0.020/GB/month | Checkpoint + tiles |
| GCS Class A ops | $0.05/10k ops | Writes |
| Network egress | $0.12/GB | Minimal for intra-region |

At the scale of these benchmarks (hundreds to thousands of entries), variable
costs are negligible — fractions of a cent. They become material only at
millions of entries sustained over hours.

### 3.3 The Right Cost Metric: $/hour at Sustained QPS

Rather than "cost per 1M entries" (which requires accurate entry counting),
the more robust metric is:

```
cost_efficiency = sustained_qps / cost_per_hour
```

This says: "For each dollar per hour of infrastructure, how many QPS can the
system sustain?" It's easy to compute because `cost_per_hour` is deterministic
(from Terraform) and `sustained_qps` is measurable from the tree size delta over
a stable measurement window.

**Example** (hypothetical, with working hammers):

| | Trillian | TesseraCT |
|:---|:---|:---|
| Sustained Write QPS | 200 | 400 |
| Cost/hour | $0.193 | $0.268 |
| QPS per $/hr | 1,036 | 1,493 |
| Cost per 1M entries | $0.27 | $0.19 |

Note: Write latency is **not** a useful comparison metric. TesseraCT blocks
writes on checkpoint integration at a 1-second batch interval by default —
this is an architectural choice, not a performance bottleneck. Throughput and
cost-efficiency are the meaningful comparison axes.

The "cost per 1M entries" is derived as:
```
entries_per_hour = sustained_qps × 3600
cost_per_1M = (cost_per_hour / entries_per_hour) × 1,000,000
```

### 3.4 Scaling Cost Analysis

The above covers the minimum viable infrastructure. A more complete analysis
would test at multiple infrastructure scales:

| Scale | Trillian Changes | TesseraCT Changes | Additional Cost/hr |
|:---|:---|:---|:---|
| Baseline | db-f1-micro, 2 nodes | 100 PU, 2 nodes | (as above) |
| Medium | db-n1-standard-2, 3 nodes | 200 PU, 3 nodes | +~$0.15 |
| Large | db-n1-standard-4, 4 nodes | 500 PU, 4 nodes | +~$0.50 |

This reveals whether cost scales linearly with throughput (ideal) or
super-linearly (diminishing returns).

---

## Part 4: Concrete Recommendations

### Phase 0: Fix the Broken Pipeline (Immediate)

1. **Fix `benchmark.yml` grep pattern**: Change `"Trillian Cost:"` to
   `"Trillian Total Cost:"` (and same for TesseraCT).

2. **Fix `update_readme.py` regex**: Escape parentheses in the label:
   ```python
   pattern = rf"\| \*\*{re.escape(label)}\*\* \| .*? \| .*? \|"
   ```

3. **Fix Trillian cert generation**: The DES3 encryption of the intermediate
   key needs to produce a valid PEM with DEK-Info header, or switch to
   unencrypted keys with `ct_hammer`'s expected format.

4. **Validate hammer exit codes**: Check `process.returncode` and abort the
   benchmark if the hammer crashed.

5. **Guard QPS calculation**: Require minimum elapsed time and minimum entry
   count before computing QPS:
   ```python
   if (end_time - start_time) < 60 or (final_size - initial_size) < 10:
       print("ERROR: Benchmark did not produce meaningful data")
       sys.exit(1)
   ```

6. **Close PR #4**: The data in it is not meaningful.

### Phase 1: Fix the Cost Model

1. **Use deterministic costs from Terraform config** instead of scraping Cloud
   Monitoring for fixed resources. The infrastructure is defined in code — use
   those definitions as the cost basis.

2. **Create a `costs.json` file** checked into the repo with the pricing
   constants and resource specs, so cost calculations are transparent and
   auditable:
   ```json
   {
     "gke_cluster_mgmt_hr": 0.10,
     "gke_node": {"type": "e2-standard-2", "count": 2, "hr": 0.1030},
     "cloud_sql": {"tier": "db-f1-micro", "hr": 0.0150},
     "spanner": {"pu": 100, "hr_per_100pu": 0.0900},
     "lb_forwarding_rule": {"count": 2, "hr": 0.025}
   }
   ```

3. **Reserve Cloud Monitoring** for variable-cost components only (GCS ops,
   storage growth), and validate that the metric queries actually return data
   before using the values.

4. **Include the cost calculation in `benchmark_summary.json`** with full
   line-item breakdown, not just a total. This makes it auditable.

### Phase 2: Fix the Benchmark Execution

1. **Add a warmup phase**: Run 60 seconds of load before the measurement
   window begins. Discard warmup data.

2. **Use a longer measurement window**: 5 minutes is borderline. 15-30 minutes
   would produce more stable throughput numbers. At minimum, validate that QPS
   is stable over the window (coefficient of variation < 10%).

3. **Add smoke tests**: Before the main benchmark, verify that each system can
   handle a small number of writes (10-20) successfully. This catches config
   errors (like the DEK-Info issue) before wasting a full run.

4. **Remove latency as a comparison metric**: TesseraCT's 1-second batch
   checkpoint integration means write latency is architecturally bounded, not
   a performance indicator. Latency comparison is not meaningful between these
   two systems.

5. **Implement node pool isolation**: Either create separate node pools with
   taints (as PLAN.md describes) or update PLAN.md and README.md to reflect
   the shared-pool reality and explain why it's acceptable.

6. **Consider parallel execution**: Run both benchmarks simultaneously on
   isolated node pools instead of sequentially. This halves wall-clock time and
   eliminates ordering effects.

### Phase 3: Make Results Auditable

1. **Commit raw data**: The `benchmark_summary.json` should be committed to the
   repo on every run (not just RESULTS.md). Include timestamps, tree sizes,
   elapsed time, and per-component cost breakdown.

2. **Include the cost model in the repo**: A `costs.json` or similar file that
   documents every pricing assumption and resource quantity. Anyone should be
   able to independently verify the final number by multiplying the line items.

3. **Show the math in the PR body**: The PR should include the calculation,
   not just the result:
   ```
   TesseraCT cost/hr: $0.178 (shared) + $0.090 (Spanner) = $0.268
   Achieved: 400 QPS sustained over 15 min (360,000 entries)
   Cost per 1M entries: ($0.268 / 400 / 3600) × 1,000,000 = $0.186
   ```

4. **Version the infrastructure spec**: If Terraform resources change (bigger
   SQL instance, more Spanner PUs), past results are no longer comparable. Tag
   each result set with the infrastructure configuration that produced it.

---

## Part 5: Revised Task Plan

### Completed
- [x] Infrastructure provisioning (Terraform)
- [x] Deployment automation (deploy_k8s.sh, ko)
- [x] GitHub Actions pipeline structure
- [x] TesseraCT ergonomic issues documented

### Phase 0: Pipeline Fixes
- [ ] Fix `benchmark.yml` grep pattern (`"Total Cost"` not `"Cost"`)
- [ ] Fix `update_readme.py` regex escaping for `(p95)`
- [ ] Fix Trillian intermediate key generation (DEK-Info header issue)
- [ ] Add hammer exit code validation in `benchmark.py`
- [ ] Add minimum threshold guards on QPS calculation
- [ ] Close PR #4 with explanation

### Phase 1: Cost Model Overhaul
- [ ] Create `costs.json` with all pricing constants and resource specs
- [ ] Rewrite cost calculation to use deterministic Terraform-derived costs
- [ ] Reserve Cloud Monitoring queries for variable costs only (GCS ops, storage delta)
- [ ] Fix cumulative-vs-gauge metric handling in `metrics.py` (or remove if not needed)
- [ ] Include full line-item cost breakdown in `benchmark_summary.json`

### Phase 2: Benchmark Quality
- [ ] Add 60-second warmup phase before measurement
- [ ] Add smoke test (10 writes to each system) before main benchmark
- [ ] Extend default benchmark duration to 15+ minutes
- [ ] Increase TesseraCT `--num_writers` to match target QPS
- [ ] Drop latency as a comparison metric (TesseraCT 1s batch interval makes it meaningless)
- [ ] Either implement node pool isolation (taints) or update docs to match reality
- [ ] Validate throughput stability (CoV < 10%) before reporting results

### Phase 3: Reporting & Auditability
- [ ] Commit `benchmark_summary.json` with full raw data on each run
- [ ] Include cost calculation breakdown in PR body
- [ ] Tag results with infrastructure configuration version
- [ ] Update README to reflect actual methodology (not aspirational)
- [ ] (Optional) Generate throughput-vs-latency visualization

---

## Appendix: Current vs. Proposed Cost Calculation

### Current (Broken)

```
1. Query Cloud Monitoring for cpu/usage_time (cumulative counter)
2. Average all data points (meaningless for cumulative metric)
3. Multiply by duration_hours × price (dimensional error)
4. Add storage cost using RAM price constant (wrong price)
5. Sum → "total cost"
```

Produces: $1.49 (Trillian), $3.08 (TesseraCT) for a ~5 min test where almost
nothing happened.

### Proposed (Deterministic)

```
1. Read infrastructure spec from costs.json:
   - Trillian: $0.193/hr (shared GKE + Cloud SQL)
   - TesseraCT: $0.268/hr (shared GKE + Spanner)
2. Multiply by benchmark duration:
   - 15 min = 0.25 hr
   - Trillian: $0.048, TesseraCT: $0.067
3. Add variable costs from validated Cloud Monitoring queries:
   - GCS ops: (measured op count) × $0.005/1k
   - Storage delta: (measured GB growth) × rate/month × fraction_of_month
4. Total = fixed + variable
5. Cost per 1M = total / entries_written × 1,000,000
```

The key difference: fixed costs are **known facts from Terraform**, not
error-prone metric queries. Variable costs are validated before use.
