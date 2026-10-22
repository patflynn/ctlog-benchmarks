#!/busybox/sh
# Entrypoint for the tesseract-hammer Cloud Run Job.
# Mints a Google ID token for the job's service account from the metadata server
# (audience = $SERVICE_URL) so hammer can call the internal-ingress tesseract-bench
# service without passing user credentials around as job args.
#
# Multi-task executions (--tasks=N): each task gets a disjoint serial range via
# --serial_offset. hammer only generates real duplicates from serials it has
# submitted before, which in practice means task 0's range (it continues the
# log's single-task serial sequence). So tasks > 0 run with --dup_chance=0, and
# the runner passes dup_chance x N to all tasks. Go's flag package takes the
# last value given.
set -e
TOKEN="$(/busybox/wget -q -O - --header 'Metadata-Flavor: Google' \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${SERVICE_URL}")"
cd "${KO_DATA_PATH:-/var/run/ko}"
IDX="${CLOUD_RUN_TASK_INDEX:-0}"
if [ "$IDX" -gt 0 ]; then
  exec /ko-app/hammer --bearer_token_write="${TOKEN}" "$@" \
    --serial_offset="$((IDX * 1000000000))" --dup_chance=0
fi
exec /ko-app/hammer --bearer_token_write="${TOKEN}" "$@"
