#!/bin/bash
# Runs the benchmark matrix sequentially (us-east4). Results land in cloudrun/results/.
set -u
cd "$(dirname "$0")/.."
source .env.local
run() { echo; echo "##### $(date -u +%FT%TZ) $*"; python3 -u cloudrun/run_cloudrun_bench.py --project_id="$PROJECT_ID" --region="$REGION" "$@" 2>&1 | grep --line-buffered -E '^\{|===|Warmup|Error|ERROR|URL|Saved'; }
spanner_pu() { echo "##### $(date -u +%FT%TZ) Spanner -> $1 PU"; gcloud spanner instances update tesseract-bench --processing-units="$1" --project="$PROJECT_ID" 2>&1 | tail -1; }

# --- 1000 PU ---
spanner_pu 1000
run --overlay=cloudrun/overlays/r4-scale1 --qps_levels=250,500,1000,1500
run --overlay=cloudrun/overlays/r4-scale3 --hammer_tasks=2 --qps_levels=250,500,1000,1500,2000,2500
run --overlay=cloudrun/overlays/r3-direct-vpc --qps_levels=250,500,1000,1500,2000
run --overlay=cloudrun/overlays/r3-direct-vpc --skip_deploy --warmup_seconds=0 --qps_levels=1000 --dup_chance=1.0 --label=dup-only
run --overlay=cloudrun/overlays/r1-baseline --warmup_seconds=30 --qps_levels=1000 --dup_chance=1.0 --label=dup-only
run --overlay=cloudrun/overlays/r2-cpu-throttled --qps_levels=250,500,1000
run --overlay=cloudrun/overlays/r4b-fast-batch --qps_levels=1000,1500,2000

# --- 2000 PU ---
spanner_pu 2000
run --overlay=cloudrun/overlays/r5-max-ceiling --hammer_tasks=2 --qps_levels=500,1000,1500,2000,2500,3000
run --overlay=cloudrun/overlays/r6-scale4 --hammer_tasks=3 --qps_levels=1500,2000,2500,3000
run --overlay=cloudrun/overlays/r6b-scale5 --hammer_tasks=3 --qps_levels=2000,2500,3000,3500
echo "##### $(date -u +%FT%TZ) QUEUE DONE"
