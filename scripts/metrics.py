import argparse
import json
import os
import sys

COSTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "costs.json")


def load_costs(tier="small"):
    with open(COSTS_FILE, "r") as f:
        data = json.load(f)

    # Support tiered format (new) and flat format (legacy)
    if "tiers" in data:
        if tier not in data["tiers"]:
            print(f"Unknown tier '{tier}'. Available: {', '.join(data['tiers'].keys())}", file=sys.stderr)
            sys.exit(1)
        return data["tiers"][tier]
    else:
        # Legacy flat format — return as-is
        return data


def analyze_benchmark(project_id, start_time, end_time, log_type, tier="small"):
    costs = load_costs(tier)
    duration_hours = (end_time - start_time) / 3600.0

    system_costs = costs[log_type]
    shared_costs = costs["shared"]

    report = {
        "log_type": log_type,
        "duration_hours": duration_hours,
        "cost_model": "deterministic",
        "line_items": {},
        "costs": {},
    }

    # Fixed costs: shared infrastructure (50/50 split)
    shared_hourly = shared_costs["total_hourly"] / 2.0
    report["line_items"]["shared_infra"] = {
        "description": "GKE cluster + nodes + LB (50% allocation)",
        "hourly_rate": shared_hourly,
        "components": {
            "gke_mgmt": shared_costs["gke_cluster_mgmt"]["hourly_rate"] / 2.0,
            "gke_nodes": shared_costs["gke_nodes"]["hourly_rate"] / 2.0,
            "load_balancer": shared_costs["load_balancers"]["hourly_rate"] / 2.0,
        },
    }
    report["costs"]["shared_infra"] = shared_hourly * duration_hours

    # Fixed costs: dedicated backend
    dedicated_hourly = system_costs["dedicated_hourly"]
    if log_type == "trillian":
        report["line_items"]["dedicated_backend"] = {
            "description": f"Cloud SQL {system_costs['cloud_sql']['tier']}",
            "hourly_rate": dedicated_hourly,
        }
    else:
        report["line_items"]["dedicated_backend"] = {
            "description": f"Spanner {system_costs['spanner']['processing_units']} PU",
            "hourly_rate": dedicated_hourly,
        }
    report["costs"]["dedicated_backend"] = dedicated_hourly * duration_hours

    # Total fixed cost
    cost_per_hour = shared_hourly + dedicated_hourly
    total_cost = sum(report["costs"].values())

    report["cost_per_hour"] = cost_per_hour
    report["total_cost"] = total_cost

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--start", type=float, required=True, help="Unix timestamp")
    parser.add_argument("--end", type=float, required=True, help="Unix timestamp")
    parser.add_argument("--type", choices=["trillian", "tesseract"], required=True)
    parser.add_argument("--tier", default="small", help="Infrastructure tier (small/medium/large)")
    args = parser.parse_args()

    result = analyze_benchmark(args.project_id, args.start, args.end, args.type, args.tier)
    print(json.dumps(result, indent=2))
