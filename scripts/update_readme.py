import json
import os


MARKER_START = "<!-- BENCHMARK-RESULTS-START -->"
MARKER_END = "<!-- BENCHMARK-RESULTS-END -->"


def load_costs():
    """Load costs.json and return the tiers dict."""
    costs_path = "costs.json"
    if not os.path.exists(costs_path):
        return {}
    with open(costs_path, "r") as f:
        return json.load(f).get("tiers", {})


def tier_specs(tier_name, tiers):
    """Build a human-readable infrastructure spec string for a tier."""
    tier = tiers.get(tier_name)
    if not tier:
        return tier_name
    machine = tier.get("gke_machine_type", "?")
    nodes = tier.get("gke_node_count", "?")
    sql_tier = tier.get("cloud_sql_tier", "?")
    spanner_pu = tier.get("spanner_processing_units", "?")
    return f"{sql_tier} / Spanner {spanner_pu} PU / {nodes}× {machine}"


def cost_per_1m(r):
    """Format cost per 1M entries from a result dict."""
    if r.get("cost_per_1m_entries", 0) > 0:
        return f"${r['cost_per_1m_entries']:.2f}"
    qps = r.get("achieved_qps", 0)
    cost_hr = r.get("cost_per_hour", 0)
    if qps <= 0:
        return "N/A"
    return f"${(cost_hr / (qps * 3600) * 1_000_000):.2f}"


def generate_single_qps_block(results, tier_name, timestamp, tiers):
    """Generate the results block for a single-QPS run."""
    trillian = [r for r in results if r["log_type"] == "trillian"]
    tesseract = [r for r in results if r["log_type"] == "tesseract"]

    if not trillian or not tesseract:
        return "*Missing results for one or both systems.*"

    tr = max(trillian, key=lambda r: r.get("achieved_qps", 0))
    te = max(tesseract, key=lambda r: r.get("achieved_qps", 0))

    lines = []
    lines.append(f"**Tier: {tier_name}** — {tier_specs(tier_name, tiers)}")
    if timestamp:
        lines.append(f"  ")
        lines.append(f"*Last updated: {timestamp}*")
    lines.append("")
    lines.append("| Metric | Trillian (MySQL) | TesseraCT (Spanner) |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| **Achieved QPS** | {tr.get('achieved_qps', 0):.2f} | {te.get('achieved_qps', 0):.2f} |")
    lines.append(f"| **Infra Cost/hr** | ${tr.get('cost_per_hour', 0):.4f} | ${te.get('cost_per_hour', 0):.4f} |")
    lines.append(f"| **Cost per 1M Entries** | {cost_per_1m(tr)} | {cost_per_1m(te)} |")

    return "\n".join(lines)


def generate_sweep_block(results, tier_name, timestamp, tiers):
    """Generate the results block for a QPS sweep run."""
    lines = []
    lines.append(f"**Tier: {tier_name}** — {tier_specs(tier_name, tiers)}")
    if timestamp:
        lines.append(f"  ")
        lines.append(f"*Last updated: {timestamp}*")
    lines.append("")
    lines.append("| Target QPS | Trillian QPS | TesseraCT QPS | Trillian $/1M | TesseraCT $/1M |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")

    # Group results by target_qps
    qps_levels = sorted(set(r["target_qps"] for r in results))
    for qps in qps_levels:
        tr = next((r for r in results if r["log_type"] == "trillian" and r["target_qps"] == qps), None)
        te = next((r for r in results if r["log_type"] == "tesseract" and r["target_qps"] == qps), None)
        tr_qps = f"{tr['achieved_qps']:.2f}" if tr else "—"
        te_qps = f"{te['achieved_qps']:.2f}" if te else "—"
        tr_cost = cost_per_1m(tr) if tr else "—"
        te_cost = cost_per_1m(te) if te else "—"
        lines.append(f"| {qps} | {tr_qps} | {te_qps} | {tr_cost} | {te_cost} |")

    return "\n".join(lines)


def update_readme():
    if not os.path.exists("benchmark_summary.json"):
        print("benchmark_summary.json not found")
        return

    with open("benchmark_summary.json", "r") as f:
        data = json.load(f)

    # Support both new format ({tier, timestamp, results: [...]}) and legacy format ([...])
    if isinstance(data, dict) and "results" in data:
        all_results = data["results"]
        tier_name = data.get("tier", "unknown")
        timestamp = data.get("timestamp", "")
    elif isinstance(data, list):
        all_results = data
        tier_name = "unknown"
        timestamp = ""
    else:
        print("Unrecognized benchmark_summary.json format")
        return

    if not all_results:
        print("No results in benchmark_summary.json")
        return

    tiers = load_costs()

    # Detect sweep vs single-QPS: more than 1 unique target_qps = sweep
    unique_qps = set(r.get("target_qps", 0) for r in all_results)
    if len(unique_qps) > 1:
        block = generate_sweep_block(all_results, tier_name, timestamp, tiers)
    else:
        block = generate_single_qps_block(all_results, tier_name, timestamp, tiers)

    with open("README.md", "r") as f:
        content = f.read()

    start_idx = content.find(MARKER_START)
    end_idx = content.find(MARKER_END)
    if start_idx == -1 or end_idx == -1:
        print("Could not find benchmark result markers in README.md")
        return

    new_content = (
        content[:start_idx + len(MARKER_START)]
        + "\n"
        + block
        + "\n"
        + content[end_idx:]
    )

    with open("README.md", "w") as f:
        f.write(new_content)
    print("README.md updated with latest results")


if __name__ == "__main__":
    update_readme()
