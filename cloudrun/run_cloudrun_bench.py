#!/usr/bin/env python3
"""Normalized Cloud Run benchmark runner for TesseraCT.

Topology:
  * `tesseract-bench` Cloud Run service with `ingress: internal`.
  * `tesseract-hammer` Cloud Run Job (Direct VPC egress `all-traffic` on the `default`
    VPC) generates load from inside the project. Its entrypoint mints an ID token for
    the job SA from the metadata server (audience = SERVICE_URL), so no user
    credentials are passed as job args. Checkpoints are read via `gs://` with ADC.

Each QPS step is one `gcloud run jobs execute --wait`. Ground-truth integrated QPS is
computed from the checkpoint size delta over the step window.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

SERVICE = "tesseract-bench"  # overridable via --service_name
JOB = "tesseract-hammer"  # overridable via --job_name
ORIGIN = "tesseract-benchmark"


def run_cmd(cmd, check=True):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"Error executing: {cmd}\n{res.stderr}", file=sys.stderr)
        sys.exit(1)
    return res


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_checkpoint_size(bucket):
    res = run_cmd(f"gcloud storage cat gs://{bucket}/checkpoint", check=False)
    if res.returncode != 0:
        return 0
    lines = res.stdout.strip().splitlines()
    return int(lines[1]) if len(lines) >= 2 else 0


def deploy_overlay(overlay_dir, project_id, region):
    print(f"Deploying KRM overlay: {overlay_dir} ...", flush=True)
    run_cmd(
        f"kubectl kustomize {overlay_dir} "
        f"| envsubst '${{PROJECT_ID}} ${{PROJECT_NUMBER}} ${{IMAGE_URI}} ${{PUB_KEY_VERSION}} ${{PRIV_KEY_VERSION}}' "
        f"| gcloud run services replace - --project={project_id} --region={region} --quiet"
    )
    sa = f"tesseract-cloudrun-sa@{project_id}.iam.gserviceaccount.com"
    run_cmd(
        f"gcloud run services add-iam-policy-binding {SERVICE} --member=serviceAccount:{sa} "
        f"--role=roles/run.invoker --project={project_id} --region={region} --quiet --format=none"
    )


def service_url(project_id, region):
    return run_cmd(
        f"gcloud run services describe {SERVICE} "
        f"--project={project_id} --region={region} --format='value(status.url)'"
    ).stdout.strip()


def get_pub_key_b64(project_id):
    pem = run_cmd(
        f"gcloud secrets versions access latest --secret=tesseract-signer-pub --project={project_id}"
    ).stdout
    return "".join(l for l in pem.splitlines() if "---" not in l).strip()


def run_step(args, url, pub_key, bucket, qps, duration_sec, out_dir, name):
    tasks = max(1, args.hammer_tasks)
    num_writers = max(256, qps * 4)
    # Per-task load; tasks > 0 run with --dup_chance=0 (see hammer/entrypoint.sh),
    # so task 0 carries all duplicates to keep the overall duplicate ratio.
    task_dup = min(1.0, args.dup_chance * tasks)
    hammer_args = [
        f"--log_url=gs://{bucket}/",
        f"--write_log_url={url}/{ORIGIN}",
        f"--origin={ORIGIN}",
        f"--log_public_key={pub_key}",
        "--intermediate_ca_cert_path=test_intermediate_ca_cert.pem",
        "--intermediate_ca_key_path=test_intermediate_ca_private_key.pem",
        "--cert_sign_private_key_path=test_leaf_cert_signing_private_key.pem",
        f"--max_write_ops={-(-qps // tasks)}",
        f"--num_writers={-(-num_writers // tasks)}",
        "--max_read_ops=0",
        "--num_readers_random=0",
        "--num_readers_full=0",
        "--num_mmd_verifiers=0",
        "--leaf_write_goal=0",
        f"--dup_chance={task_dup}",
        f"--max_runtime={duration_sec}s",
        "--show_ui=false",
    ]
    assert not any("," in a for a in hammer_args), "job --args is comma-separated"
    initial_size = get_checkpoint_size(bucket)
    start_utc = now_utc()
    t0 = time.time()
    res = run_cmd(
        f"gcloud run jobs execute {JOB} --project={args.project_id} --region={args.region} "
        f"--wait --tasks={tasks} --task-timeout={duration_sec + 180}s --update-env-vars=SERVICE_URL={url} "
        f"--args='{','.join(hammer_args)}' --format='value(metadata.name)'",
        check=False,
    )
    # hammer exits 1 by design when --max_runtime elapses ("Fail after this amount of
    # time"), so the execution is reported as failed even on a clean step; the
    # execution name is then only present in stderr.
    m = re.search(rf"\b({JOB}-[a-z0-9]{{5}})\b", res.stdout + res.stderr)
    exec_name = m.group(1) if m else ""
    time.sleep(3)  # final batch checkpoint publication
    wall = time.time() - t0
    end_utc = now_utc()
    final_size = get_checkpoint_size(bucket)
    entries = max(0, final_size - initial_size)
    unique_qps = entries / duration_sec

    step = {
        "target_qps": qps,
        "dup_chance": args.dup_chance,
        "num_writers": num_writers,
        "hammer_tasks": tasks,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "wall_seconds": round(wall, 1),
        "checkpoint_size_start": initial_size,
        "checkpoint_size_end": final_size,
        "entries_integrated": entries,
        "integrated_unique_qps": round(unique_qps, 2),
        "est_total_write_qps_incl_dups": (round(unique_qps / (1.0 - args.dup_chance), 2)
                                          if args.dup_chance < 1.0 else None),
        "job_execution": exec_name,
        "job_exit_code": res.returncode,
    }
    if res.returncode != 0 and entries == 0:
        step["job_error"] = res.stderr.strip()[-500:]
    if exec_name:
        logs = run_cmd(
            f"gcloud logging read 'resource.type=\"cloud_run_job\" AND "
            f"labels.\"run.googleapis.com/execution_name\"=\"{exec_name}\"' "
            f"--project={args.project_id} --order=asc --limit=5000 --format='value(textPayload)'",
            check=False,
        ).stdout
        with open(os.path.join(out_dir, f"hammer_{name}.log"), "w") as f:
            f.write(logs)
    print(json.dumps(step), flush=True)
    return step


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--region", default="us-east4")
    parser.add_argument("--overlay", default="cloudrun/overlays/r1-baseline")
    parser.add_argument("--qps_levels", default="250,500,1000,1500,2000")
    parser.add_argument("--step_seconds", type=int, default=180)
    parser.add_argument("--warmup_seconds", type=int, default=60)
    parser.add_argument("--dup_chance", type=float, default=0.1)
    parser.add_argument("--skip_deploy", action="store_true")
    parser.add_argument("--hammer_tasks", type=int, default=1,
                        help="Parallel hammer job tasks (8 vCPU each); use 2+ for >= 2000 QPS")
    parser.add_argument("--label", default="", help="Suffix for the results directory/file name")
    parser.add_argument("--service_name", default=SERVICE)
    parser.add_argument("--job_name", default=JOB)
    parser.add_argument("--bucket", default="", help="Defaults to <project>-tesseract-bench")
    args = parser.parse_args()
    globals().update(SERVICE=args.service_name, JOB=args.job_name)

    bucket = args.bucket or f"{args.project_id}-tesseract-bench"
    pub_key = get_pub_key_b64(args.project_id)
    if not args.skip_deploy:
        deploy_overlay(args.overlay, args.project_id, args.region)
    url = service_url(args.project_id, args.region)
    print(f"Cloud Run URL (internal ingress): {url}", flush=True)

    name = os.path.basename(args.overlay.rstrip("/")) + (f"-{args.label}" if args.label else "")
    run_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join("cloudrun", "results", f"{run_ts}_{name}")
    os.makedirs(out_dir, exist_ok=True)

    qps_list = [int(x) for x in args.qps_levels.split(",")]
    warmup = None
    if args.warmup_seconds > 0:
        print(f"Warmup ({args.warmup_seconds}s @ {qps_list[0]} QPS)...", flush=True)
        warmup = run_step(args, url, pub_key, bucket, qps_list[0], args.warmup_seconds, out_dir, "warmup")

    results = []
    for q in qps_list:
        print(f"=== QPS step: {q} QPS for {args.step_seconds}s ===", flush=True)
        results.append(run_step(args, url, pub_key, bucket, q, args.step_seconds, out_dir, f"{q}qps"))
        time.sleep(10)

    summary = {
        "project_id": args.project_id,
        "region": args.region,
        "overlay": args.overlay,
        "image_uri": os.environ.get("IMAGE_URI", ""),
        "hammer_image": os.environ.get("HAMMER_IMAGE", ""),
        "service_url": url,
        "warmup": warmup,
        "results": results,
    }
    out_file = os.path.join(out_dir, f"cloudrun_results_{name}.json")
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved summary to {out_file}:\n" + json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
