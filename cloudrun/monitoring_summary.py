#!/usr/bin/env python3
"""Quick Cloud Monitoring summaries for a benchmark step window.

Usage: PROJECT_ID=... monitoring_summary.py START_UTC END_UTC

Prints per-minute Cloud Run request rates/latency/CPU, TesseraCT response codes (incl. 429
reasons), antispam follower lag and Spanner CPU for a step window. Uses ADC.
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

P = os.environ["PROJECT_ID"]
TOKEN = subprocess.check_output(["gcloud", "auth", "application-default", "print-access-token"], text=True).strip()


def ts(filter_, start, end, aligner="ALIGN_RATE", reducer="REDUCE_SUM", group=(), period="60s"):
    q = {
        "filter": filter_,
        "interval.startTime": start,
        "interval.endTime": end,
        "aggregation.alignmentPeriod": period,
        "aggregation.perSeriesAligner": aligner,
    }
    if reducer:
        q["aggregation.crossSeriesReducer"] = reducer
        if group:
            q["aggregation.groupByFields"] = list(group)
    url = f"https://monitoring.googleapis.com/v3/projects/{P}/timeSeries?" + urllib.parse.urlencode(q, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        return json.load(urllib.request.urlopen(req)).get("timeSeries", [])
    except urllib.error.HTTPError as e:
        print("ERR", e.read().decode()[:300])
        return []


def val(p):
    v = p["value"]
    return v.get("doubleValue", v.get("int64Value"))


def show(title, series):
    print(f"--- {title}")
    for s in series:
        labels = {**s.get("metric", {}).get("labels", {}), **s.get("resource", {}).get("labels", {})}
        pts = [float(val(p)) for p in reversed(s.get("points", []))]
        print(f"  {json.dumps(labels)[:160]}: " + " ".join(f"{x:.3g}" for x in pts))


start, end = sys.argv[1], sys.argv[2]
show("tesseract responses/s by code+429 reason",
     ts('metric.type="workload.googleapis.com/tesseract.http.response.count"', start, end,
        group=("metric.labels.http_response_status_code", "metric.labels.tesseract_too_many_requests")))
show("antispam follower lag (max)",
     ts('metric.type="workload.googleapis.com/tessera.follower.lag"', start, end, aligner="ALIGN_MAX", reducer="REDUCE_MAX"))
show("Spanner CPU utilization (by db)",
     ts('metric.type="spanner.googleapis.com/instance/cpu/utilization_by_operation_type"', start, end,
        aligner="ALIGN_MEAN", group=("metric.labels.database",)))
show("Cloud Run container CPU util (p50 of distribution, per revision)",
     ts('metric.type="run.googleapis.com/container/cpu/utilizations" AND resource.labels.service_name="tesseract-bench"',
        start, end, aligner="ALIGN_PERCENTILE_99", reducer="REDUCE_MAX"))
show("Cloud Run instance count",
     ts('metric.type="run.googleapis.com/container/instance_count" AND resource.labels.service_name="tesseract-bench"',
        start, end, aligner="ALIGN_MAX", reducer="REDUCE_SUM"))
