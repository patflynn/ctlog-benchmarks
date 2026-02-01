#!/usr/bin/env python3
"""Generate a markdown benchmark report from benchmark_summary.json."""

import argparse
import json
import sys


def load_summary(path):
    with open(path, "r") as f:
        data = json.load(f)

    # Support both new format ({tier, results: [...]}) and legacy format ([...])
    if isinstance(data, dict) and "results" in data:
        return data.get("tier", "unknown"), data["results"]
    elif isinstance(data, list):
        return "small", data
    else:
        print("Unrecognized benchmark_summary.json format", file=sys.stderr)
        sys.exit(1)


def find_saturation(results, log_type):
    """Find the QPS level where achieved drops below 90% of target."""
    system_results = sorted(
        [r for r in results if r["log_type"] == log_type],
        key=lambda r: r["target_qps"],
    )
    for r in system_results:
        if r["target_qps"] > 0 and r["achieved_qps"] < r["target_qps"] * 0.9:
            return r["achieved_qps"]
    # No saturation detected
    if system_results:
        return None
    return None


def find_crossover(results):
    """Find QPS level where TesseraCT cost/1M becomes cheaper than Trillian."""
    trillian_by_qps = {}
    tesseract_by_qps = {}
    for r in results:
        if r["log_type"] == "trillian":
            trillian_by_qps[r["target_qps"]] = r
        else:
            tesseract_by_qps[r["target_qps"]] = r

    common_qps = sorted(set(trillian_by_qps.keys()) & set(tesseract_by_qps.keys()))
    for qps in common_qps:
        tr = trillian_by_qps[qps]
        te = tesseract_by_qps[qps]
        if te["cost_per_1m_entries"] > 0 and tr["cost_per_1m_entries"] > 0:
            if te["cost_per_1m_entries"] < tr["cost_per_1m_entries"]:
                return qps
    return None


def get_infra_label(results, tier):
    """Build infrastructure labels from cost data if available."""
    # These are inferred from the tier definitions in costs.json
    tier_info = {
        "small": {"sql": "db-f1-micro", "spanner": "100 PU"},
        "medium": {"sql": "db-n1-standard-1", "spanner": "300 PU"},
        "large": {"sql": "db-n1-standard-2", "spanner": "1000 PU"},
    }
    return tier_info.get(tier, {"sql": "unknown", "spanner": "unknown"})


def generate_report(tier, results):
    """Generate markdown report for a single tier."""
    lines = []
    lines.append(f"## Benchmark Report — Tier: {tier}")
    lines.append("")

    # Get unique QPS levels (sorted)
    qps_levels = sorted(set(r["target_qps"] for r in results))

    # Build lookup dicts
    trillian_by_qps = {r["target_qps"]: r for r in results if r["log_type"] == "trillian"}
    tesseract_by_qps = {r["target_qps"]: r for r in results if r["log_type"] == "tesseract"}

    # Table header
    lines.append("| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |")
    lines.append("|---:|---:|---:|---:|---:|")

    for qps in qps_levels:
        tr = trillian_by_qps.get(qps)
        te = tesseract_by_qps.get(qps)
        tr_qps = f"{tr['achieved_qps']:.1f}" if tr else "—"
        te_qps = f"{te['achieved_qps']:.1f}" if te else "—"
        tr_cost = f"${tr['cost_per_1m_entries']:.2f}" if tr and tr["cost_per_1m_entries"] > 0 else "—"
        te_cost = f"${te['cost_per_1m_entries']:.2f}" if te and te["cost_per_1m_entries"] > 0 else "—"
        lines.append(f"| {qps} | {tr_qps} | {te_qps} | {tr_cost} | {te_cost} |")

    lines.append("")
    lines.append("### Findings")

    infra = get_infra_label(results, tier)

    # Saturation analysis
    tr_sat = find_saturation(results, "trillian")
    te_sat = find_saturation(results, "tesseract")

    if tr_sat is not None:
        lines.append(f"- Trillian ({infra['sql']}) saturates at ~{int(tr_sat)} QPS")
    else:
        max_tr = max((r["target_qps"] for r in results if r["log_type"] == "trillian"), default=0)
        lines.append(f"- Trillian ({infra['sql']}) sustains target through {max_tr} QPS")

    if te_sat is not None:
        lines.append(f"- TesseraCT ({infra['spanner']} Spanner) saturates at ~{int(te_sat)} QPS")
    else:
        max_te = max((r["target_qps"] for r in results if r["log_type"] == "tesseract"), default=0)
        lines.append(f"- TesseraCT ({infra['spanner']} Spanner) sustains target through {max_te} QPS")

    # Cost crossover
    crossover = find_crossover(results)
    if crossover is not None:
        lines.append(f"- TesseraCT cost-per-entry becomes favorable above ~{crossover} QPS")
    else:
        lines.append("- No cost-per-entry crossover detected within tested QPS range")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate markdown benchmark report")
    parser.add_argument("input", nargs="?", default="benchmark_summary.json", help="Path to benchmark_summary.json")
    args = parser.parse_args()

    tier, results = load_summary(args.input)
    report = generate_report(tier, results)
    print(report)


if __name__ == "__main__":
    main()
