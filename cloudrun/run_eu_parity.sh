#!/bin/bash
# europe-west3 parity spot check, r5b-batch500 config at N=3.
# Creates EU-colocated subnet / Spanner / bucket / hammer job, then runs warmup + 2000 + 2500 QPS.
# Teardown of the EU Spanner instance is a separate step (after SPANNER_SYS stats are pulled).
set -u
cd "$(dirname "$0")/.."
source .env.local
EU=europe-west3
SA="tesseract-cloudrun-sa@${PROJECT_ID}.iam.gserviceaccount.com"
step() { echo; echo "##### $(date -u +%FT%TZ) $*"; }

step "subnet default-eu"
gcloud compute networks subnets create default-eu --network=default --region=$EU --range=10.20.0.0/20 \
  --enable-private-ip-google-access --project="$PROJECT_ID" 2>&1 | tail -1

step "Spanner tesseract-bench-eu (regional-$EU, 2000 PU) + DBs"
gcloud spanner instances create tesseract-bench-eu --config="regional-$EU" --description="TesseraCT bench EU" \
  --processing-units=2000 --project="$PROJECT_ID" 2>&1 | tail -1
gcloud spanner databases create tesseract-log --instance=tesseract-bench-eu --project="$PROJECT_ID" \
  --ddl="CREATE TABLE IF NOT EXISTS Tessera (id INT64 NOT NULL, compatibilityVersion INT64 NOT NULL) PRIMARY KEY (id)" 2>&1 | tail -1
gcloud spanner databases create tesseract-aspam --instance=tesseract-bench-eu --project="$PROJECT_ID" \
  --ddl="CREATE TABLE IF NOT EXISTS FollowCoord (id INT64 NOT NULL, nextIdx INT64 NOT NULL) PRIMARY KEY (id); CREATE TABLE IF NOT EXISTS IDSeq (h BYTES(32) NOT NULL, idx INT64 NOT NULL) PRIMARY KEY (h)" 2>&1 | tail -1

step "bucket"
gcloud storage buckets create "gs://${PROJECT_ID}-tesseract-bench-eu" --location=$EU --uniform-bucket-level-access \
  --project="$PROJECT_ID" 2>&1 | tail -1

step "hammer job tesseract-hammer-eu"
gcloud run jobs deploy tesseract-hammer-eu --image="$HAMMER_IMAGE" --region=$EU --service-account="$SA" \
  --network=default --subnet=default-eu --vpc-egress=all-traffic --cpu=8 --memory=8Gi --max-retries=0 \
  --task-timeout=600s --command=/busybox/sh,/var/run/ko/entrypoint.sh --project="$PROJECT_ID" --quiet 2>&1 | tail -1

step "run r7-eu-parity"
python3 -u cloudrun/run_cloudrun_bench.py --project_id="$PROJECT_ID" --region=$EU \
  --overlay=cloudrun/overlays/r7-eu-parity --service_name=tesseract-bench-eu --job_name=tesseract-hammer-eu \
  --bucket="${PROJECT_ID}-tesseract-bench-eu" --hammer_tasks=2 --warmup_seconds=60 --qps_levels=2000,2500 \
  2>&1 | grep --line-buffered -E '^\{|===|Warmup|Error|ERROR|URL|Saved'
step "EU DONE"
