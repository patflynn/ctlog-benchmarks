#!/usr/bin/env python3
"""Polls gs://<bucket>/checkpoint metadata ~every 0.5s and records publication gaps.

Usage: checkpoint_gap_poller.py BUCKET DURATION_SECONDS OUT_JSON
Used for the R8 lease failover test.
"""
import json
import subprocess
import sys
import time
import urllib.request

bucket, duration, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
token = subprocess.check_output(["gcloud", "auth", "application-default", "print-access-token"], text=True).strip()
url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/checkpoint?fields=generation,updated"
seen = []  # (generation, updated)
last_gen = None
t_end = time.time() + duration
errors = 0
while time.time() < t_end:
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        d = json.load(urllib.request.urlopen(req, timeout=5))
        if d["generation"] != last_gen:
            last_gen = d["generation"]
            seen.append({"generation": d["generation"], "updated": d["updated"], "observed": time.time()})
    except Exception:
        errors += 1
    time.sleep(0.5)

gaps = []
for a, b in zip(seen, seen[1:]):
    gaps.append({"from": a["updated"], "to": b["updated"], "gap_s": round(b["observed"] - a["observed"], 2)})
gaps.sort(key=lambda g: -g["gap_s"])
res = {"publications": len(seen), "poll_errors": errors, "top_gaps": gaps[:10],
       "median_gap_s": sorted(g["gap_s"] for g in gaps)[len(gaps) // 2] if gaps else None}
json.dump({"summary": res, "publications": seen}, open(out, "w"), indent=1)
print(json.dumps(res))
