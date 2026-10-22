#!/bin/bash
# R8-lease-poc A/B. Run ONLY after run_queue.sh has finished.
# Same overlays/flags as R5/R6; only the server image is swapped to the lease PoC.
set -u
cd "$(dirname "$0")/.."
source .env.local
STOCK_IMAGE="$IMAGE_URI"
export IMAGE_URI="${LEASE_IMAGE_URI:-${REGION}-docker.pkg.dev/${PROJECT_ID}/tesseract-bench/tesseract-gcp:lease-poc}"
run() { echo; echo "##### $(date -u +%FT%TZ) $*"; python3 -u cloudrun/run_cloudrun_bench.py --project_id="$PROJECT_ID" --region="$REGION" "$@" 2>&1 | grep --line-buffered -E '^\{|===|Warmup|Error|ERROR|URL|Saved'; }

echo "##### $(date -u +%FT%TZ) Spanner -> 2000 PU"
gcloud spanner instances update tesseract-bench --processing-units=2000 --project="$PROJECT_ID" 2>&1 | tail -1

# 1. First PoC start at 1 instance so the LeaseCoord DDL runs once.
run --overlay=cloudrun/overlays/r4-scale1 --warmup_seconds=0 --qps_levels=500 --step_seconds=60 --label=r8-init
# 2./3. A/B sweeps vs r5-max-ceiling (N=3) and r6-scale4 (N=4).
run --overlay=cloudrun/overlays/r5-max-ceiling --hammer_tasks=2 --qps_levels=1000,1500,2000,2500,3000 --label=r8-lease-poc
run --overlay=cloudrun/overlays/r6-scale4 --hammer_tasks=3 --qps_levels=1500,2000,2500,3000 --label=r8-lease-poc

# 4. Failover: N=3 @ 1000 QPS for 300s; force a new revision ~90s in (all instances incl. holder replaced).
run --overlay=cloudrun/overlays/r5-max-ceiling --warmup_seconds=0 --qps_levels=1000 --step_seconds=10 --label=r8-failover-deploy
TS=$(date -u +%Y%m%dT%H%M%SZ); OUT=cloudrun/results/${TS}_r8-failover; mkdir -p "$OUT"
python3 -u cloudrun/checkpoint_gap_poller.py "${PROJECT_ID}-tesseract-bench" 420 "$OUT/checkpoint_gaps.json" > "$OUT/poller.out" 2>&1 &
POLLER=$!
( sleep 90; echo "##### $(date -u +%FT%TZ) forcing new revision"; \
  gcloud run services update tesseract-bench --region="$REGION" --project="$PROJECT_ID" \
    --update-env-vars=FAILOVER_TEST="$TS" --quiet 2>&1 | tail -2 ) > "$OUT/revision_swap.log" 2>&1 &
run --overlay=cloudrun/overlays/r5-max-ceiling --skip_deploy --warmup_seconds=0 --qps_levels=1000 --step_seconds=300 --label=r8-failover
wait $POLLER; cat "$OUT/poller.out" "$OUT/revision_swap.log"

# Restore the stock image so the playground is left in a known state.
export IMAGE_URI="$STOCK_IMAGE"
kubectl kustomize cloudrun/overlays/r1-baseline \
  | envsubst '${PROJECT_ID} ${PROJECT_NUMBER} ${IMAGE_URI} ${PUB_KEY_VERSION} ${PRIV_KEY_VERSION}' \
  | gcloud run services replace - --project="$PROJECT_ID" --region="$REGION" --quiet 2>&1 | tail -1
echo "##### $(date -u +%FT%TZ) R8 DONE"
