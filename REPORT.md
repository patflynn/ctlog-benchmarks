## Benchmark Report — Tier: large

| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |
|---:|---:|---:|---:|---:|
| 50 | 18.0 | 2.0 | $7.55 | $178.70 |
| 100 | 16.8 | 2.0 | $8.09 | $178.72 |
| 250 | 16.0 | 2.5 | $8.50 | $142.95 |
| 500 | 17.3 | 5.0 | $7.87 | $71.50 |

### Findings
- Trillian (db-n1-standard-2) saturates at ~18 QPS
- TesseraCT (1000 PU Spanner) saturates at ~2 QPS
- No cost-per-entry crossover detected within tested QPS range

