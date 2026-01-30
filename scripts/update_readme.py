import json
import os
import re

def update_readme():
    if not os.path.exists("benchmark_summary.json"):
        print("❌ benchmark_summary.json not found")
        return

    with open("benchmark_summary.json", "r") as f:
        results = json.load(f)

    trillian = next((r for r in results if r["log_type"] == "trillian"), None)
    tesseract = next((r for r in results if r["log_type"] == "tesseract"), None)

    if not trillian or not tesseract:
        print("❌ Missing results for one or both systems")
        return

    # Calculate Costs per 1M Entries
    def cost_per_1m(r):
        qps = r.get("achieved_qps", 0)
        cost_total = r.get("total_cost", 0)
        duration_sec = r.get("duration_hours", 0) * 3600
        total_entries = qps * duration_sec
        if total_entries == 0:
            return "N/A"
        return f"${(cost_total / total_entries * 1_000_000):.4f}"

    tr_cost_1m = cost_per_1m(trillian)
    te_cost_1m = cost_per_1m(tesseract)

    metrics = {
        "Max Throughput": (f"{trillian.get('achieved_qps', 0):.2f} QPS", f"{tesseract.get('achieved_qps', 0):.2f} QPS"),
        "Latency (p95)": (f"{trillian.get('p95_latency', 0):.2f} ms", f"{tesseract.get('p95_latency', 0):.2f} ms"),
        "Cost per 1M Entries": (tr_cost_1m, te_cost_1m),
        "Storage Efficiency": (f"{trillian['metrics'].get('storage_gb', 0):.4f} GB", f"{tesseract['metrics'].get('storage_gb', 0):.4f} GB")
    }

    with open("README.md", "r") as f:
        content = f.read()

    for label, (tr_val, te_val) in metrics.items():
        # Match | **Label** | *Pending* | *Pending* |
        pattern = rf"\| \*\*{label}\*\* \| .*? \| .*? \|"
        replacement = f"| **{label}** | {tr_val} | {te_val} |"
        content = re.sub(pattern, replacement, content)

    with open("README.md", "w") as f:
        f.write(content)
    print("✅ README.md updated with latest results")

if __name__ == "__main__":
    update_readme()
