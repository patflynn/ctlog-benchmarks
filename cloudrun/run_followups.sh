#!/bin/bash
# Follow-ups after R8: stock-image failover baseline + r5 at batch_max_age=500ms. 2000 PU.
set -u
cd "$(dirname "$0")/.."
source .env.local   # IMAGE_URI = stock v0.2.0
run() { echo; echo "##### $(date -u +%FT%TZ) $*"; python3 -u cloudrun/run_cloudrun_bench.py --project_id="$PROJECT_ID" --region="$REGION" "$@" 2>&1 | grep --line-buffered -E '^\{|===|Warmup|Error|ERROR|URL|Saved'; }

# 1. Stock failover baseline: identical procedure to R8 failover (N=3 r5, 1000 QPS, 300s, new revision at ~90s).
run --overlay=cloudrun/overlays/r5-max-ceiling --warmup_seconds=0 --qps_levels=1000 --step_seconds=10 --label=stock-failover-deploy
TS=$(date -u +%Y%m%dT%H%M%SZ); OUT=cloudrun/results/${TS}_stock-failover; mkdir -p "$OUT"
python3 -u cloudrun/checkpoint_gap_poller.py "${PROJECT_ID}-tesseract-bench" 420 "$OUT/checkpoint_gaps.json" > "$OUT/poller.out" 2>&1 &
POLLER=$!
( sleep 90; echo "##### $(date -u +%FT%TZ) forcing new revision"; \
  gcloud run services update tesseract-bench --region="$REGION" --project="$PROJECT_ID" \
    --update-env-vars=FAILOVER_TEST="$TS" --quiet 2>&1 | tail -2 ) > "$OUT/revision_swap.log" 2>&1 &
run --overlay=cloudrun/overlays/r5-max-ceiling --skip_deploy --warmup_seconds=0 --qps_levels=1000 --step_seconds=300 --label=stock-failover
wait $POLLER; cat "$OUT/poller.out" "$OUT/revision_swap.log"

# 2. r5 with prod batching (500ms).
run --overlay=cloudrun/overlays/r5b-batch500 --hammer_tasks=2 --qps_levels=1000,1500,2000,2500,3000
echo "##### $(date -u +%FT%TZ) FOLLOWUPS DONE"
