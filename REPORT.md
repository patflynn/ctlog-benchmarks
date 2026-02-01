## Benchmark Report — Tier: small

| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |
|---:|---:|---:|---:|---:|
| 500 | 2.0 | 5.0 | $26.41 | $14.94 |

### Findings
- Trillian (db-f1-micro) saturates at ~2 QPS
- TesseraCT (100 PU Spanner) saturates at ~4 QPS
- TesseraCT cost-per-entry becomes favorable above ~500 QPS

