## Benchmark Report — Tier: large

| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |
|---:|---:|---:|---:|---:|
| 50 | 9.7 | 46.4 | $14.10 | $7.68 |

### Findings
- Trillian (db-n1-standard-2) saturates at ~9 QPS
- TesseraCT (1000 PU Spanner) sustains target through 50 QPS
- TesseraCT cost-per-entry becomes favorable above ~50 QPS

