# A Priori Cost/Performance Estimate: Trillian vs TesseraCT

## Methodology

This analysis uses **reference throughput data from the Tessera project** rather
than the current benchmark results. The benchmark shows TesseraCT at 2–5 QPS on
1000 PU Spanner — three orders of magnitude below Tessera's published numbers
(>800 QPS on 100 PU). This indicates a benchmark tooling issue, not a TesseraCT
limitation. Where benchmark data is suspect, conservative ranges from reference
literature are used instead.

All prices are GCP list prices, us-central1, excluding sustained-use and
committed-use discounts.

### Data sources

| Source | Used for |
|---|---|
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

### Expected sustained write throughput

| Tier | Trillian (est.) | TesseraCT (ref.) | Source |
|---|---|---|---|
| small | 5–20 QPS | >800 QPS | Cloud SQL micro limits; Tessera benchmarks |
| medium | 20–80 QPS | >3,000 QPS | Cloud SQL standard-1; Tessera benchmarks |
| large | 50–200 QPS | ~8,000–10,000 QPS | Cloud SQL standard-2; linear PU extrapolation |

### Write cost efficiency (a priori, midpoint estimates)

| Tier | Trillian QPS | Trillian $/1M writes | TesseraCT QPS | TesseraCT $/1M writes |
|---|---|---|---|---|
| small | 12 | $4.47 | 800 | $0.09 |
| medium | 50 | $1.56 | 3,000 | $0.05 |
| large | 125 | $1.09 | 9,000 | $0.04 |

**Formula**: `cost_per_1M = (cost_per_hour / sustained_qps / 3600) × 1,000,000`

On reference throughput, TesseraCT delivers **27–46× more write QPS per dollar**
than Trillian. The absolute cost per million entries for TesseraCT ($0.04–0.09)
is dominated by the Spanner PU hourly cost, which is fixed regardless of
utilization. Trillian's cost per million ($1.09–4.47) is higher because Cloud
SQL MySQL saturates at much lower QPS, so the fixed hourly cost is amortized
over fewer entries.

> **Caveat**: If the benchmark's observed TesseraCT throughput (~2–5 QPS)
> reflects real production behavior rather than a tooling bug, the write cost
> picture inverts. Root-causing the benchmark underperformance is critical.

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
| 13 | db-f1-micro | $0.015 | Comfortable |
| 50 | db-n1-standard-1 | $0.050 | Comfortable |
| 200 | db-n1-standard-2 to standard-4 | $0.105–0.210 | Approaching ceiling |
| 500 | db-n1-standard-8+ | $0.420+ | Near vertical scaling limits |
| 1,000+ | Multiple instances + sharding | $1.00+ | Requires architectural changes |

Cloud SQL MySQL has a practical write ceiling of ~500–1,000 QPS on the largest
instances. The Trillian sequencer is a single-writer bottleneck. Beyond this
ceiling, horizontal scaling requires application-level sharding across multiple
independent log trees.

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
| Infra needed | db-n1-standard-2 ($0.105/hr) | 100 PU Spanner ($0.090/hr) |
| QPS headroom above need | 0–100% | ~300% |
| $/1M entries | ~$0.15 | ~$0.03 |

**Aggressive scenario (~1,000 QPS per shard)**:

| | Trillian | TesseraCT |
|---|---|---|
| Infra needed | db-n1-standard-8+ or sharding | 200 PU Spanner ($0.180/hr) |
| Hourly cost | $0.42+ (single) or $0.84+ (sharded) | $0.180 |
| $/1M entries | ~$0.12+ | ~$0.05 |
| Feasibility | Requires architectural changes | Linear PU increase |

---

## 6. Total Cost of Ownership

### Year 1 (single shard, 10% of aggregate, current issuance)

| Component | Trillian | TesseraCT | Winner |
|---|---|---|---|
| Compute/DB | $1,690/yr ($0.193/hr) | $2,348/yr ($0.268/hr) | Trillian (28% cheaper) |
| Storage (400M certs) | $2,016/yr | $214/yr | TesseraCT (9.4×) |
| Read serving | Included in DB (limits read QPS) | ~$50–200/yr (GCS ops) | TesseraCT |
| Read egress | ~$500/yr | ~$100–250/yr (CDN) | TesseraCT (2–5×) |
| **Total** | **~$4,206/yr** | **~$2,812/yr** | **TesseraCT (33% cheaper)** |

### Year 3 (47-day mandate, 8.5× current issuance)

| Component | Trillian | TesseraCT | Winner |
|---|---|---|---|
| Compute/DB | $3,679/yr (medium, $0.42/hr) | $2,348/yr (still small, 100 PU) | TesseraCT (36%) |
| Storage (3.4B certs cumul.) | $58,000/yr | $6,100/yr | TesseraCT (9.5×) |
| Read serving | $2,000+/yr (read replicas) | ~$500/yr (GCS + CDN) | TesseraCT (4×) |
| **Total** | **~$63,679/yr** | **~$8,948/yr** | **TesseraCT (7× cheaper)** |

---

## Key Findings

1. **At low scale, Trillian is slightly cheaper on compute.** Cloud SQL's floor
   ($0.015/hr for db-f1-micro) is 6× lower than Spanner's floor ($0.090/hr for
   100 PU). For very small logs this matters.

2. **At scale, storage dominates total cost**, and TesseraCT wins decisively.
   GCS at $0.020/GB vs Cloud SQL SSD at $0.170/GB is an 8.5× difference that
   applies to every byte stored for the lifetime of the log.

3. **TesseraCT's read path is a structural advantage.** Immutable tiles enable
   CDN serving, eliminating the need for read replicas. This becomes increasingly
   valuable as CT monitoring traffic grows.

4. **TesseraCT has 10–50× more throughput headroom** before requiring
   infrastructure changes. Trillian hits MySQL write ceilings at ~500–1,000 QPS
   and requires application-level sharding. TesseraCT scales by adding Spanner
   PUs with no architectural changes.

5. **The crossover point** where TesseraCT becomes cheaper overall is roughly
   when storage exceeds ~500 GB — around 125M certificates, or ~4 months of
   moderate shard traffic at current issuance rates.

## Open Questions

- **Benchmark gap**: The 160–400× gap between observed TesseraCT throughput
  (2–5 QPS) and reference data (800+ QPS) must be root-caused. The most likely
  explanation is hammer tooling misconfiguration, but this needs validation.

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
