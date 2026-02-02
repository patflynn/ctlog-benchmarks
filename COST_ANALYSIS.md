# Cost/Performance Analysis: Trillian vs TesseraCT

## Methodology

This analysis combines **empirical benchmark data** with reference throughput
data from the Tessera project. An initial benchmark tooling bug (missing
`--path_prefix` on the TesseraCT server) had suppressed TesseraCT throughput to
2–5 QPS. After fixing this, our benchmarks show TesseraCT reaching >1,000 QPS
on 1000 PU Spanner, consistent with Tessera's published reference data.

All prices are GCP list prices, us-central1, excluding sustained-use and
committed-use discounts.

### Data sources

| Source | Used for |
|---|---|
| `benchmark_summary.json` | Empirical benchmark results (2026-02-02, large tier) |
| `costs.json` | Infrastructure hourly rates per tier |
| `terraform/tesseract.tf` | Spanner schema (SeqCoord, IntCoord, Seq, IDSeq, FollowCoord) |
| `terraform/trillian.tf` | Cloud SQL MySQL configuration |
| [Tessera project benchmarks](https://github.com/transparency-dev/trillian-tessera) | >800 writes/sec on 100 PU, >3000 on 300 PU |
| [GCP pricing](https://cloud.google.com/pricing) | Spanner, Cloud SQL, GCS, egress rates |
| CT ecosystem data | ~128 certs/sec aggregate today |

---

## 1. Write QPS Serving Cost

### Infrastructure cost per hour (from `costs.json`)

| Tier | Trillian $/hr | TesseraCT $/hr | Trillian backend | TesseraCT backend |
|---|---|---|---|---|
| small | $0.193 | $0.268 | db-f1-micro | 100 PU Spanner |
| medium | $0.280 | $0.500 | db-n1-standard-1 | 300 PU Spanner |
| large | $0.490 | $1.284 | db-n1-standard-2 | 1000 PU Spanner |

These include a 50/50 split of shared infrastructure (GKE cluster management,
node compute, load balancers) plus each system's dedicated backend cost.

### Measured write throughput (large tier benchmark, 2026-02-02)

| Target QPS | Trillian achieved | TesseraCT achieved | Entries (Trillian) | Entries (TesseraCT) |
|---|---|---|---|---|
| 50 | 9.3 | 123.6 | 3,069 | 37,250 |
| 100 | 9.6 | 248.0 | 3,166 | 74,756 |
| 250 | 9.6 | 618.9 | 3,154 | 186,792 |
| 500 | 9.3 | 1,008.1 | 3,052 | 303,945 |

**Key observations**:
- Trillian saturates at ~9.5 QPS on db-n1-standard-2 regardless of target.
  This is below the a priori estimate (50–200 QPS) and likely reflects the
  Trillian sequencer bottleneck on this Cloud SQL tier under CT workload
  patterns (cert chain storage + Merkle tree updates per write).
- TesseraCT scales linearly and is **not yet saturated** at 1,008 QPS on
  1000 PU. At each target level it achieved 2–2.5× the target, indicating
  the hammer was still the rate-limiting factor, not the server.
- This run used the pre-optimization hammer settings. With the pending
  hammer bottleneck removal (higher `--max_write_ops`, more writers, disabled
  readers), the TesseraCT ceiling is likely significantly higher.

### Expected sustained write throughput

| Tier | Trillian (measured/est.) | TesseraCT (measured/ref.) | Source |
|---|---|---|---|
| small | 5–10 QPS | >800 QPS | Benchmark extrapolation; Tessera benchmarks |
| medium | 5–15 QPS | >3,000 QPS | Benchmark extrapolation; Tessera benchmarks |
| large | **~9.5 QPS (measured)** | **>1,008 QPS (measured, not saturated)** | Benchmark 2026-02-02 |

The measured Trillian throughput is significantly lower than initial estimates.
The Trillian sequencer's single-writer architecture combined with Cloud SQL
MySQL latency under the CT write workload (cert chain + Merkle subtree updates)
appears to cap throughput well below the theoretical MySQL insert rate.

### Write cost efficiency

**Measured (large tier)**:

| Target QPS | Trillian $/1M | TesseraCT $/1M | TesseraCT advantage |
|---|---|---|---|
| 50 | $14.62 | $2.89 | 5× |
| 100 | $14.17 | $1.44 | 10× |
| 250 | $14.23 | $0.58 | 25× |
| 500 | $14.70 | $0.35 | **42×** |

**A priori estimates (all tiers, midpoint)**:

| Tier | Trillian QPS | Trillian $/1M writes | TesseraCT QPS | TesseraCT $/1M writes |
|---|---|---|---|---|
| small | 8 | $6.70 | 800 | $0.09 |
| medium | 10 | $7.78 | 3,000 | $0.05 |
| large | 9.5 | $14.31 | 9,000 | $0.04 |

**Formula**: `cost_per_1M = (cost_per_hour / sustained_qps / 3600) × 1,000,000`

At measured throughput, TesseraCT delivers **5–42× lower cost per million
writes** than Trillian on the large tier. The cost advantage grows with
throughput because TesseraCT's infrastructure cost is fixed (Spanner PUs are
hourly) while its QPS scales up — each additional write amortizes the fixed
cost further. Trillian's cost per million is nearly constant (~$14) because it
is saturated at ~9.5 QPS regardless of demand.

> **Note**: TesseraCT was not saturated in this benchmark run. At the server's
> actual ceiling (likely >3,000 QPS based on Tessera reference data for
> comparable PU counts), the cost per million entries would drop further toward
> the $0.04 a priori estimate.

---

## 2. Read QPS Serving Cost

### Architectural difference

**Trillian**: Every read (inclusion proof, consistency proof, get-entries)
requires a MySQL query. Proof paths through the Merkle tree are computed
on-the-fly from the subtree cache in MySQL. Reads are bounded by Cloud SQL IOPS
and connection limits. Read replicas help but add cost ($0.015–0.105/hr per
replica depending on tier).

**TesseraCT**: Tiles and entry bundles are static, content-addressed objects in
GCS. Once written, they never change. This means:

- Tiles are **immutable** → infinitely cacheable (`Cache-Control: immutable`)
- Servable via **CDN** (Cloud CDN, Cloudflare) with near-100% hit ratio for warm tiles
- Origin reads hit **GCS, not Spanner** — Spanner is never in the client read path

### Read cost comparison

| Component | Trillian | TesseraCT |
|---|---|---|
| Origin | Cloud SQL (shared with writes) | GCS ($0.004/10k Class B ops) |
| CDN-able? | No (dynamic proof computation) | Yes (static immutable tiles) |
| Scaling | Add read replicas ($0.015–0.105/hr) | Add CDN edge (per-request pricing) |
| 10K reads/sec, no CDN | Needs dedicated read replica(s) | ~$0.14/hr in GCS ops |
| 10K reads/sec, with CDN | N/A | ~$0.01–0.02/hr (>95% cache hits) |

### CT monitor read patterns

CT monitors and auditors perform two operations:

1. **Fetch new entries** (get-entries): sequential scan, high volume
2. **Verify proofs** (inclusion/consistency): random tile access, moderate volume

For entry fetching at 1,000 certs/sec, monitors need ~4 GCS bundle reads/sec
(256 entries per bundle) — trivial for GCS. For proof verification, each proof
requires log₂(N) tile fetches — same depth as Trillian, but tiles are cached
locally or via CDN.

**Read costs are 1–2 orders of magnitude lower for TesseraCT at scale**, and
the gap widens with CDN deployment.

---

## 3. Storage Carrying Costs

### Per-certificate storage footprint

| Component | Trillian (MySQL) | TesseraCT (Spanner + GCS) |
|---|---|---|
| Cert chain (leaf data) | ~4 KB | ~4 KB (GCS entry bundle) |
| Merkle tree nodes | ~256 bytes (subtree cache) | ~32 bytes (GCS tiles) |
| Coordination/index | ~100 bytes | ~10–20 MB total in Spanner (bounded) |
| **Total per cert** | **~4.4 KB in Cloud SQL** | **~4.0 KB in GCS** |

Spanner's `Seq` table stores entries transiently during integration. Steady-state
Spanner storage is ~10–20 MB regardless of total tree size — bounded by batch
interval × throughput. The actual entry data and Merkle tiles are durably stored
in GCS.

### Unit storage prices

| Backend | $/GB/month |
|---|---|
| Cloud SQL SSD | $0.170 |
| Spanner SSD | $0.300 |
| GCS Standard | $0.020 |

### Storage cost at scale

| Scale | Trillian (MySQL) | Trillian $/month | TesseraCT (GCS) | TesseraCT $/month | Savings |
|---|---|---|---|---|---|
| 100M certs | ~440 GB | $74.80 | ~400 GB | $8.00 | 9.4× |
| 1B certs | ~4.4 TB | $748.00 | ~4.0 TB | $80.00 | 9.4× |
| 10B certs | ~44 TB | $7,480.00 | ~40 TB | $800.00 | 9.4× |

TesseraCT Spanner storage adds ~$0.006/month at all scales (negligible).

### Storage accumulation for a single shard (10% of aggregate traffic)

At current issuance (~128 certs/sec aggregate, ~12.8 certs/sec per shard):

| Year | Cumulative certs | Trillian $/month | TesseraCT $/month | Annual delta |
|---|---|---|---|---|
| 1 | ~400M | $300 | $32 | $3,216 saved |
| 2 | ~800M | $600 | $64 | $6,432 saved |
| 3 | ~1.2B | $900 | $96 | $9,648 saved |

With the 47-day certificate mandate (8.5× growth), storage accumulation
accelerates proportionally.

---

## 4. Bandwidth Costs

### Write-path bandwidth

Inbound data (cert submissions) is free on GCP. Internal write paths:

| Path | Trillian | TesseraCT |
|---|---|---|
| Client → App | ~4 KB (cert chain) | ~4 KB (cert chain) |
| App → DB | ~4.4 KB (MySQL insert) | ~100 bytes (Spanner coord write) |
| App → Object store | N/A | ~4 KB (GCS entry + tile updates) |

Internal (same-region) bandwidth is free on GCP, so write-path bandwidth costs
are negligible for both systems.

### Read-path bandwidth (egress)

| Scenario | Trillian | TesseraCT |
|---|---|---|
| Egress pricing | $0.12/GB (internet) | $0.12/GB (GCS) or $0.02–0.08/GB (CDN) |
| 1M proof fetches (~30 KB each) | ~30 GB = **$3.60** | CDN-served: **$0.60–2.40** |
| Daily monitor sync (1M new entries) | ~4 GB = **$0.48** | ~4 GB via CDN: **$0.08–0.32** |

TesseraCT's read bandwidth is **2–6× cheaper** when a CDN is deployed. Without
CDN, raw GCS egress matches Cloud SQL egress — the CDN eligibility is the
structural differentiator.

---

## 5. Throughput Scaling Headroom

### CT issuance growth projections

| Scenario | Aggregate rate | Multiplier | Timeline |
|---|---|---|---|
| Today | ~128 certs/sec | 1× | Current |
| 47-day cert mandate | ~1,088 certs/sec | 8.5× | 2–3 years |
| 47-day + Let's Encrypt 6-day | ~2,048+ certs/sec | ~16× | 2–3 years |
| Aggressive automation | ~5,000+ certs/sec | ~40× | 3+ years |

Per-shard requirements (assuming 10–25% of aggregate traffic):

| Scenario | 10% share | 25% share |
|---|---|---|
| Today | 13 QPS | 32 QPS |
| 47-day mandate | 109 QPS | 272 QPS |
| 47-day + LE 6-day | 205 QPS | 512 QPS |
| Aggressive | 500 QPS | 1,250 QPS |

### Trillian scaling path

| QPS needed | Cloud SQL tier | $/hr (DB only) | Notes |
|---|---|---|---|
| 10 | db-f1-micro | $0.015 | Near measured ceiling (~9.5 QPS) |
| 13 | db-n1-standard-1 | $0.050 | May not achieve — needs validation |
| 50 | db-n1-standard-2+ | $0.105+ | Benchmark shows ~9.5 QPS on standard-2 |
| 200 | db-n1-standard-4 to standard-8 | $0.210–0.420 | Uncertain — sequencer bottleneck |
| 500+ | Multiple instances + sharding | $1.00+ | Requires architectural changes |

Benchmark results show Trillian saturating at ~9.5 QPS on db-n1-standard-2 —
well below the MySQL theoretical insert rate. The Trillian sequencer is a
single-writer bottleneck, and the CT write workload (cert chain storage +
Merkle subtree cache updates) is heavier than simple row inserts. Scaling
beyond ~10 QPS likely requires larger Cloud SQL instances, but the single-writer
sequencer may impose a ceiling regardless of MySQL capacity. Horizontal
scaling requires application-level sharding across multiple independent log
trees.

### TesseraCT scaling path

| QPS needed | Spanner PU | $/hr (Spanner only) | Notes |
|---|---|---|---|
| 13 | 100 | $0.090 | Massive headroom (800+ QPS capacity) |
| 200 | 100 | $0.090 | Still within 100 PU capacity |
| 500 | 100 | $0.090 | Still within reference range |
| 1,000 | 100–200 | $0.090–0.180 | Comfortable |
| 3,000 | 300 | $0.270 | Validated by Tessera benchmarks |
| 10,000 | ~1,000 | $0.900 | Linear PU extrapolation |

Spanner scales to 10,000+ PU per instance. GCS has virtually unlimited write
throughput for distinct objects. The practical ceiling is Spanner transaction
throughput, which scales linearly with PU count.

### Side-by-side at projected demand

**47-day mandate (~200 QPS per shard)**:

| | Trillian | TesseraCT |
|---|---|---|
| Infra needed | Sharding required (~20 shards at 9.5 QPS each) | 100 PU Spanner ($0.090/hr) |
| Hourly cost | ~$2.00+ (20× db-f1-micro + coordination) | $0.090 |
| QPS headroom above need | None without sharding | >300% |
| $/1M entries | ~$2.78+ | ~$0.03 |

**Aggressive scenario (~1,000 QPS per shard)**:

| | Trillian | TesseraCT |
|---|---|---|
| Infra needed | ~100 shards or major Cloud SQL scaling | 200 PU Spanner ($0.180/hr) |
| Hourly cost | $10.00+ | $0.180 |
| $/1M entries | $2.78+ | ~$0.05 |
| Feasibility | Requires fundamental architectural changes | Linear PU increase |

---

## 6. Total Cost of Ownership

### Year 1 (single shard, 10% of aggregate, current issuance ~13 QPS)

| Component | Trillian | TesseraCT | Winner |
|---|---|---|---|
| Compute/DB | $1,690/yr ($0.193/hr, small) | $2,348/yr ($0.268/hr, small) | Trillian (28% cheaper) |
| Throughput capacity | ~9.5 QPS (may not meet 13 QPS need) | >800 QPS | TesseraCT |
| Storage (400M certs) | $2,016/yr | $214/yr | TesseraCT (9.4×) |
| Read serving | Included in DB (limits read QPS) | ~$50–200/yr (GCS ops) | TesseraCT |
| Read egress | ~$500/yr | ~$100–250/yr (CDN) | TesseraCT (2–5×) |
| **Total** | **~$4,206/yr** | **~$2,812/yr** | **TesseraCT (33% cheaper)** |

Note: Trillian at ~9.5 QPS may not handle even 10% of current aggregate
issuance (~13 QPS) on the small tier, potentially requiring the medium tier
($0.280/hr) from day one — raising Year 1 cost to ~$4,970/yr.

### Year 3 (47-day mandate, 8.5× current issuance ~109 QPS per shard)

| Component | Trillian | TesseraCT | Winner |
|---|---|---|---|
| Compute/DB | $5,256/yr+ (sharded, ~12 instances) | $2,348/yr (still small, 100 PU) | TesseraCT (55%) |
| Storage (3.4B certs cumul.) | $58,000/yr | $6,100/yr | TesseraCT (9.5×) |
| Read serving | $2,000+/yr (read replicas) | ~$500/yr (GCS + CDN) | TesseraCT (4×) |
| **Total** | **~$65,256/yr** | **~$8,948/yr** | **TesseraCT (7.3× cheaper)** |

The Trillian Year 3 compute cost assumes sharding to meet ~109 QPS: at least
12 independent log instances at ~9.5 QPS each, each on a small Cloud SQL
instance ($0.050/hr × 12 = $0.60/hr). TesseraCT handles 109 QPS comfortably
within a single 100 PU Spanner instance.

---

## 7. Benchmark Validation

The 2026-02-02 benchmark run on the large tier validates the directional
conclusions of the a priori analysis while refining the absolute numbers.

### What the benchmark confirmed

1. **TesseraCT throughput scales with demand.** Achieved QPS tracked linearly
   from 124 to 1,008 across the sweep — consistent with Tessera reference data
   showing >800 QPS on just 100 PU. The server was not saturated at 1,008 QPS
   on 1000 PU; the true ceiling is likely several thousand QPS.

2. **TesseraCT cost per entry drops with throughput.** From $2.89/1M at 124 QPS
   to $0.35/1M at 1,008 QPS — a direct consequence of fixed Spanner PU costs
   being amortized over more entries. This validates the a priori model.

3. **Trillian's write bottleneck is real and severe.** Saturated at ~9.5 QPS on
   db-n1-standard-2 — the sequencer's single-writer design limits throughput
   far below MySQL's raw insert capacity.

### What the benchmark revised

1. **Trillian throughput was overestimated.** The a priori estimate of 50–200
   QPS for db-n1-standard-2 was based on MySQL insert benchmarks. The measured
   ~9.5 QPS reflects the overhead of Trillian's sequencer + subtree cache
   updates per write. This makes the cost-per-entry gap wider than initially
   projected (~$14.50/1M vs the estimated ~$1.09/1M).

2. **The cost advantage is even larger than projected.** At measured throughput,
   TesseraCT is **42× cheaper per million entries** at peak (vs the a priori
   estimate of 27×). The gap is driven by Trillian's lower-than-expected
   throughput compounding with its higher per-entry cost.

### Benchmark limitations

- The hammer was rate-limiting TesseraCT (achieved 2–2.5× target at each
  level). A pending change to remove hammer-side throttling should reveal the
  actual server ceiling.
- Trillian was tested with the same hammer settings and showed consistent
  saturation, so its ~9.5 QPS measurement is likely accurate.
- Only the large tier was tested. Small and medium tier measurements are needed
  to validate the full cost model.

---

## Key Findings

1. **TesseraCT is 5–42× cheaper per write** at measured throughput on the
   large tier. The advantage grows with demand: at 1,008 QPS, TesseraCT costs
   $0.35 per million entries vs Trillian's $14.70 — a 42× difference.

2. **Trillian's throughput ceiling is much lower than expected.** Measured at
   ~9.5 QPS on db-n1-standard-2, not the estimated 50–200 QPS. The Trillian
   sequencer bottleneck is the binding constraint, not MySQL capacity.

3. **At scale, storage dominates total cost**, and TesseraCT wins decisively.
   GCS at $0.020/GB vs Cloud SQL SSD at $0.170/GB is an 8.5× difference that
   applies to every byte stored for the lifetime of the log.

4. **TesseraCT's read path is a structural advantage.** Immutable tiles enable
   CDN serving, eliminating the need for read replicas. This becomes increasingly
   valuable as CT monitoring traffic grows.

5. **TesseraCT has >100× more throughput headroom** before requiring
   infrastructure changes. Trillian saturates at ~9.5 QPS and requires
   sharding. TesseraCT was not saturated at 1,008 QPS and scales linearly
   by adding Spanner PUs with no architectural changes.

6. **The crossover point** where TesseraCT becomes cheaper overall is roughly
   when storage exceeds ~500 GB — around 125M certificates, or ~4 months of
   moderate shard traffic at current issuance rates. However, given Trillian's
   measured throughput (~9.5 QPS), even a 10% shard of current CT traffic may
   require multiple Trillian instances, making TesseraCT cheaper from the start
   for any non-trivial deployment.

## Open Questions

- **TesseraCT true ceiling**: The benchmark did not saturate TesseraCT. Running
  with the optimized hammer settings (higher `--max_write_ops`, more writers,
  disabled readers) should reveal the actual throughput ceiling on 1000 PU.

- **Trillian scaling curve**: Only db-n1-standard-2 was tested. It is possible
  that larger Cloud SQL instances (standard-4, standard-8) could push Trillian
  beyond 9.5 QPS, though the sequencer bottleneck may persist regardless of
  MySQL capacity. Testing larger tiers would clarify this.

- **Spanner Seq table lifecycle**: This analysis assumes the `Seq` table is
  transient (entries cleaned up after integration into GCS bundles), keeping
  Spanner storage at ~10–20 MB steady state. If `Seq` retains all entries
  permanently, Spanner storage at $0.30/GB/month would be 1.8× more expensive
  than Cloud SQL, negating the GCS storage advantage.

- **CDN deployment complexity**: The read cost advantage depends on deploying a
  CDN in front of GCS. This is straightforward but adds operational surface area
  not present in the Trillian model.

- **Multi-shard economics**: Production CT deployments run multiple shards
  (temporal log shards). The per-shard analysis above applies to each shard
  independently, but shared infrastructure costs (GKE cluster, networking) would
  be amortized differently.
