## Benchmark Report — Tier: large

| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |
|---:|---:|---:|---:|---:|
| 50 | 9.3 | 123.6 | $14.62 | $2.89 |
| 100 | 9.6 | 248.0 | $14.17 | $1.44 |
| 250 | 9.6 | 618.9 | $14.23 | $0.58 |
| 500 | 9.2 | 1008.1 | $14.70 | $0.35 |

### Findings
- Trillian (db-n1-standard-2) saturates at ~9 QPS
- TesseraCT (1000 PU Spanner) sustains target through 500 QPS
- TesseraCT cost-per-entry becomes favorable above ~50 QPS

