## Benchmark Report — Tier: large

| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |
|---:|---:|---:|---:|---:|
| 50 | 8.9 | 2.0 | $15.35 | $178.90 |

### Findings
- Trillian (db-n1-standard-2) saturates at ~8 QPS
- TesseraCT (1000 PU Spanner) saturates at ~1 QPS
- No cost-per-entry crossover detected within tested QPS range

