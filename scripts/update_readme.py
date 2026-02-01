import json
import os
import re

def update_readme():
    if not os.path.exists("benchmark_summary.json"):
        print("benchmark_summary.json not found")
        return

    with open("benchmark_summary.json", "r") as f:
        data = json.load(f)

    # Support both new format ({tier, results: [...]}) and legacy format ([...])
    if isinstance(data, dict) and "results" in data:
        all_results = data["results"]
    elif isinstance(data, list):
        all_results = data
    else:
        print("Unrecognized benchmark_summary.json format")
        return

    # For README, use the highest achieved QPS per system
    trillian_results = [r for r in all_results if r["log_type"] == "trillian"]
    tesseract_results = [r for r in all_results if r["log_type"] == "tesseract"]

    if not trillian_results or not tesseract_results:
        print("Missing results for one or both systems")
        return

    trillian = max(trillian_results, key=lambda r: r.get("achieved_qps", 0))
    tesseract = max(tesseract_results, key=lambda r: r.get("achieved_qps", 0))

    def cost_per_1m(r):
        # Prefer pre-computed cost_per_1m_entries if available
        if "cost_per_1m_entries" in r and r["cost_per_1m_entries"] > 0:
            return f"${r['cost_per_1m_entries']:.2f}"
        qps = r.get("achieved_qps", 0)
        cost_hr = r.get("cost_per_hour", 0)
        if qps <= 0:
            return "N/A"
        entries_per_hour = qps * 3600
        return f"${(cost_hr / entries_per_hour * 1_000_000):.2f}"

    tr_cost_1m = cost_per_1m(trillian)
    te_cost_1m = cost_per_1m(tesseract)

    metrics = {
        "Max Throughput": (f"{trillian.get('achieved_qps', 0):.2f} QPS", f"{tesseract.get('achieved_qps', 0):.2f} QPS"),
        "Infra Cost/hr": (f"${trillian.get('cost_per_hour', 0):.4f}", f"${tesseract.get('cost_per_hour', 0):.4f}"),
        "Cost per 1M Entries": (tr_cost_1m, te_cost_1m),
    }

    with open("README.md", "r") as f:
        content = f.read()

    for label, (tr_val, te_val) in metrics.items():
        pattern = rf"\| \*\*{re.escape(label)}\*\* \| .*? \| .*? \|"
        replacement = f"| **{label}** | {tr_val} | {te_val} |"
        content = re.sub(pattern, replacement, content)

    with open("README.md", "w") as f:
        f.write(content)
    print("README.md updated with latest results")

if __name__ == "__main__":
    update_readme()
