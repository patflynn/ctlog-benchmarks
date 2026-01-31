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

    def cost_per_1m(r):
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
    print("✅ README.md updated with latest results")

if __name__ == "__main__":
    update_readme()
