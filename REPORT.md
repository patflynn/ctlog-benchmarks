## Benchmark Report — Tier: large

| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |
|---:|---:|---:|---:|---:|
| 50 | 17.6 | 2.0 | $7.75 | $178.66 |

### Findings
- Trillian (db-n1-standard-2) saturates at ~17 QPS
- TesseraCT (1000 PU Spanner) saturates at ~2 QPS
- No cost-per-entry crossover detected within tested QPS range

