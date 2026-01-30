import argparse
import time
import json
import sys
from google.cloud import monitoring_v3
from datetime import datetime, timezone

# Pricing Constants (us-central1 approximate hourly rates)
PRICING = {
    "gke_cpu_hour": 0.0335,      # e2-standard
    "gke_ram_gb_hour": 0.0045,   # e2-standard
    "sql_cpu_hour": 0.0413,      # Cloud SQL Enterprise
    "sql_ram_gb_hour": 0.0070,   # Cloud SQL Enterprise
    "spanner_100pu_hour": 0.090, # 100 PU
    "gcs_gb_month": 0.020,
    "gcs_10k_ops_a": 0.05,
}

def get_metric_avg(client, project_id, metric_type, start_time, end_time, filter_str):
    project_name = f"projects/{project_id}"
    interval = monitoring_v3.TimeInterval(
        {
            "end_time": {"seconds": int(end_time)},
            "start_time": {"seconds": int(start_time)},
        }
    )
    
    try:
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": f'metric.type = "{metric_type}" AND {filter_str}',
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )
        
        total_val = 0
        count = 0
        for series in results:
            for point in series.points:
                total_val += point.value.double_value
                count += 1
                
        return total_val / count if count > 0 else 0
    except Exception as e:
        print(f"⚠️ Error fetching {metric_type}: {e}", file=sys.stderr)
        return 0

def analyze_benchmark(project_id, start_time, end_time, log_type):
    client = monitoring_v3.MetricServiceClient()
    # Ensure window is at least 1 minute for Monitoring API to have data
    if (end_time - start_time) < 60:
        end_time = start_time + 60

    duration_hours = (end_time - start_time) / 3600.0
    
    report = {"log_type": log_type, "duration_hours": duration_hours, "metrics": {}, "costs": {}}

    if log_type == "trillian":
        # Cloud SQL Metrics
        sql_filter = f'resource.type = "cloudsql_database" AND resource.labels.database_id = "{project_id}:trillian-mysql"'
        cpu_usage = get_metric_avg(client, project_id, "cloudsql.googleapis.com/database/cpu/usage_time", start_time, end_time, sql_filter)
        
        report["metrics"]["sql_cpu_cores"] = cpu_usage 
        report["costs"]["sql_compute"] = cpu_usage * duration_hours * PRICING["sql_cpu_hour"]
    
    elif log_type == "tesseract":
        # Spanner Metrics
        span_filter = 'resource.type = "spanner_instance" AND resource.labels.instance_id = "tesseract-instance"'
        pu_count = get_metric_avg(client, project_id, "spanner.googleapis.com/instance/processing_units", start_time, end_time, span_filter)
        
        # Spanner metrics might be integer
        report["metrics"]["spanner_pu"] = pu_count
        report["costs"]["spanner_compute"] = (pu_count / 100.0) * duration_hours * PRICING["spanner_100pu_hour"]

    # GKE Shared Compute (Filtered by Namespace)
    gke_filter = f'resource.type = "k8s_container" AND resource.labels.namespace_name = "{log_type}"'
    gke_cpu = get_metric_avg(client, project_id, "kubernetes.io/container/cpu/core_usage_time", start_time, end_time, gke_filter)
    
    report["metrics"]["gke_cpu_cores"] = gke_cpu
    report["costs"]["gke_compute"] = gke_cpu * duration_hours * PRICING["gke_cpu_hour"]

    total_cost = sum(report["costs"].values())
    report["total_cost"] = total_cost
    
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--start", type=float, required=True, help="Unix timestamp")
    parser.add_argument("--end", type=float, required=True, help="Unix timestamp")
    parser.add_argument("--type", choices=["trillian", "tesseract"], required=True)
    args = parser.parse_args()
    
    result = analyze_benchmark(args.project_id, args.start, args.end, args.type)
    print(json.dumps(result, indent=2))