import argparse
import subprocess
import time
import json
import sys
import os

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error executing: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()

def get_lb_ip(service, namespace):
    print(f"🔍 Finding IP for {service} in {namespace}...")
    for _ in range(10):
        # Use raw string for jsonpath to avoid escape sequence warnings
        ip = run_cmd(fr"kubectl get svc {service} -n {namespace} -o jsonpath='{{.status.loadBalancer.ingress[0].ip}}'")
        if ip:
            return ip
        time.sleep(10)
    print(f"❌ Timeout waiting for LoadBalancer IP for {service}")
    sys.exit(1)

def get_trillian_tree_id():
    print("🔍 Discovering Trillian Tree ID...")
    config = run_cmd(r"kubectl get configmap ctfe-config -n trillian -o jsonpath='{.data.ctfe\.cfg}'")
    for line in config.split("\n"):
        if "log_id:" in line:
            return line.split(":")[1].strip()
    print("❌ Could not find log_id in ctfe-config")
    sys.exit(1)

def get_trillian_pub_key_der_hex():
    print("🔍 Fetching Trillian Public Key (DER)...")
    pem = run_cmd(r"kubectl get configmap ctfe-config -n trillian -o jsonpath='{.data.pubkey\.pem}'")
    with open("tmp_pub.pem", "w") as f:
        f.write(pem)
    # Convert PEM to DER hex
    der_hex = run_cmd("openssl pkey -in tmp_pub.pem -pubin -outform DER | xxd -p | tr -d '\\n' | sed 's/../\\\\x&/g'")
    os.remove("tmp_pub.pem")
    return der_hex

def get_tesseract_pub_key_b64():
    print("🔍 Fetching TesseraCT Public Key (B64)...")
    pem = run_cmd("gcloud secrets versions access latest --secret='tesseract-signer-pub'")
    # Extract base64 part
    lines = pem.split("\n")
    b64 = "".join([l for l in lines if "---" not in l]).strip()
    return b64

def get_log_size(target_type, ip, project_id):
    if target_type == "trillian":
        try:
            output = run_cmd(f"curl -s http://{ip}/benchmark/ct/v1/get-sth")
            data = json.loads(output)
            return int(data.get("tree_size", 0))
        except:
            return 0
    else: # tesseract
        try:
            output = run_cmd(f"gcloud storage cat gs://tesseract-storage-{project_id}/checkpoint")
            # Checkpoint format:
            # origin
            # size
            # ...
            lines = output.split("\n")
            if len(lines) >= 2:
                return int(lines[1])
            return 0
        except:
            return 0

def smoke_test(target_type, ip, project_id):
    """Verify the system can accept writes before running the full benchmark."""
    print(f"🔍 Smoke test: checking {target_type} can accept writes...")
    initial_size = get_log_size(target_type, ip, project_id)
    # Submit a single add-chain request via curl
    try:
        chain_file = "testdata/trillian/leaf01.chain" if target_type == "trillian" else "testdata/tesseract/leaf01.chain"
        with open(chain_file, "r") as f:
            pem_data = f.read()
        chain = []
        for block in pem_data.split("-----BEGIN CERTIFICATE-----"):
            if "-----END CERTIFICATE-----" in block:
                content = block.split("-----END CERTIFICATE-----")[0].replace("\n", "").strip()
                chain.append(content)
        payload = json.dumps({"chain": chain})
        url = f"http://{ip}/benchmark/ct/v1/add-chain" if target_type == "trillian" else f"http://{ip}/ct/v1/add-chain"
        result = subprocess.run(
            ["curl", "-s", "-w", "%{http_code}", "-X", "POST",
             "-H", "Content-Type: application/json",
             "--data-binary", payload, url],
            capture_output=True, text=True, timeout=30
        )
        status_code = result.stdout[-3:]
        if status_code != "200":
            print(f"❌ Smoke test failed for {target_type}: HTTP {status_code}")
            print(f"   Response: {result.stdout[:-3]}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Smoke test failed for {target_type}: {e}")
        sys.exit(1)

    # Allow time for checkpoint integration (TesseraCT batches on 1s interval)
    time.sleep(3)
    final_size = get_log_size(target_type, ip, project_id)
    if final_size <= initial_size:
        print(f"⚠️  Smoke test warning: tree size didn't increase ({initial_size} -> {final_size}), may be lagging")
    else:
        print(f"✅ Smoke test passed for {target_type} (tree: {initial_size} -> {final_size})")


def run_warmup(target_type, ip, tree_id=None, qps=100, warmup_seconds=60, project_id=None):
    """Run a warmup pass to eliminate cold-start noise (especially Spanner)."""
    print(f"🔥 Warming up {target_type} ({warmup_seconds}s at {qps} QPS)...")

    warmup_ops = int(qps * warmup_seconds)

    if target_type == "trillian":
        der_hex = get_trillian_pub_key_der_hex()
        run_cmd("cp testdata/trillian/fake-ca.cert roots.pem")
        with open("trillian_cfg.textproto", "w") as f:
            f.write(f'config {{\n')
            f.write(f'  log_id: {tree_id}\n')
            f.write(f'  prefix: "benchmark"\n')
            f.write(f'  roots_pem_file: "roots.pem"\n')
            f.write(f'  public_key {{\n')
            f.write(f'    der: "{der_hex}"\n')
            f.write(f'  }}\n')
            f.write(f'}}\n')
        url = f"http://{ip}"
        cmd = f"./bin/ct_hammer --log_config=trillian_cfg.textproto --ct_http_servers={url} --mmd=30s --rate_limit={qps} --operations={warmup_ops} --testdata_dir=testdata/trillian --ignore_errors"
    else:
        os.environ["CT_LOG_PUBLIC_KEY"] = get_tesseract_pub_key_b64()
        log_url = f"gs://tesseract-storage-{project_id}/"
        write_url = f"http://{ip}"
        num_writers = max(4, qps // 50)
        cmd = f"./bin/hammer --log_url={log_url} --write_log_url={write_url} --origin=tesseract-benchmark --max_write_ops={qps} --max_read_ops={int(qps/10)} --max_runtime=1m --show_ui=false " \
              f"--num_writers={num_writers} --num_readers_random=1 --num_mmd_verifiers=1 --leaf_write_goal={warmup_ops} " \
              f"--intermediate_ca_cert_path=testdata/tesseract/test_intermediate_ca_cert.pem --intermediate_ca_key_path=testdata/tesseract/test_intermediate_ca_private_key.pem --cert_sign_private_key_path=testdata/tesseract/test_leaf_cert_signing_private_key.pem"

    try:
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end='', flush=True)
        process.wait()
        if process.returncode != 0:
            print(f"⚠️  Warmup exited with code {process.returncode} (continuing anyway)")
    except Exception as e:
        print(f"⚠️  Warmup encountered error: {e} (continuing anyway)")

    print(f"🔥 Warmup complete, settling for 5s...")
    time.sleep(5)


def run_hammer(target_type, ip, tree_id=None, duration_min=5, qps=100, project_id=None, warmup_seconds=60):
    # Run warmup phase if enabled
    if warmup_seconds > 0:
        run_warmup(target_type, ip, tree_id, qps, warmup_seconds, project_id)

    print(f"🚀 Starting {target_type} load test ({qps} QPS for {duration_min} min)...")

    initial_size = get_log_size(target_type, ip, project_id)
    print(f"📈 Initial tree size: {initial_size}")

    if target_type == "trillian":
        der_hex = get_trillian_pub_key_der_hex()
        run_cmd("cp testdata/trillian/fake-ca.cert roots.pem")
        with open("trillian_cfg.textproto", "w") as f:
            f.write(f'config {{\n')
            f.write(f'  log_id: {tree_id}\n')
            f.write(f'  prefix: "benchmark"\n')
            f.write(f'  roots_pem_file: "roots.pem"\n')
            f.write(f'  public_key {{\n')
            f.write(f'    der: "{der_hex}"\n')
            f.write(f'  }}\n')
            f.write(f'}}\n')
        total_ops = int(qps * duration_min * 60)
        url = f"http://{ip}"
        cmd = f"./bin/ct_hammer --log_config=trillian_cfg.textproto --ct_http_servers={url} --mmd=30s --rate_limit={qps} --operations={total_ops} --testdata_dir=testdata/trillian --ignore_errors"
    else:
        os.environ["CT_LOG_PUBLIC_KEY"] = get_tesseract_pub_key_b64()
        log_url = f"gs://tesseract-storage-{project_id}/"
        write_url = f"http://{ip}"
        total_ops = int(qps * duration_min * 60)
        # Scale writers with target QPS (1 writer per ~50 QPS, minimum 4)
        num_writers = max(4, qps // 50)
        cmd = f"./bin/hammer --log_url={log_url} --write_log_url={write_url} --origin=tesseract-benchmark --max_write_ops={qps} --max_read_ops={int(qps/10)} --max_runtime={duration_min}m --show_ui=false " \
              f"--num_writers={num_writers} --num_readers_random=1 --num_mmd_verifiers=1 --leaf_write_goal={total_ops} " \
              f"--intermediate_ca_cert_path=testdata/tesseract/test_intermediate_ca_cert.pem --intermediate_ca_key_path=testdata/tesseract/test_intermediate_ca_private_key.pem --cert_sign_private_key_path=testdata/tesseract/test_leaf_cert_signing_private_key.pem"

    start_time = time.time()
    try:
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end='', flush=True)
        process.wait()
    except Exception as e:
        print(f"⚠️ Hammer encountered error: {e}")

    end_time = time.time()
    elapsed = end_time - start_time

    # Validate hammer actually ran
    if process.returncode != 0:
        print(f"❌ {target_type} hammer exited with code {process.returncode}")
        sys.exit(1)

    final_size = get_log_size(target_type, ip, project_id)
    entries_written = final_size - initial_size
    print(f"📈 Final tree size: {final_size} ({entries_written} new entries)")

    # Guard against bogus results from crashed or stalled hammers
    min_elapsed = 30  # seconds
    min_entries = 10
    if elapsed < min_elapsed:
        print(f"❌ Benchmark ran for only {elapsed:.1f}s (minimum {min_elapsed}s). Results not valid.")
        sys.exit(1)
    if entries_written < min_entries:
        print(f"❌ Only {entries_written} entries written (minimum {min_entries}). Results not valid.")
        sys.exit(1)

    achieved_qps = entries_written / elapsed
    print(f"📊 Achieved QPS: {achieved_qps:.2f} ({entries_written} entries / {elapsed:.1f}s)")

    return start_time, end_time, achieved_qps, entries_written, elapsed

def run_single_benchmark(target_type, ip, tree_id, duration_min, qps, project_id, warmup_seconds, tier):
    """Run a benchmark for one system at one QPS level and return a result dict."""
    t_start, t_end, achieved_qps, entries_written, elapsed = run_hammer(
        target_type, ip, tree_id, duration_min, qps, project_id, warmup_seconds
    )

    res = subprocess.check_output(
        f"python3 scripts/metrics.py --project_id {project_id} --start {t_start} --end {t_end} --type {target_type} --tier {tier}",
        shell=True, text=True
    )
    data = json.loads(res)

    cost_per_hour = data.get("cost_per_hour", 0)
    if achieved_qps > 0:
        cost_per_1m = cost_per_hour / (achieved_qps * 3600) * 1_000_000
    else:
        cost_per_1m = 0

    return {
        "log_type": target_type,
        "target_qps": qps,
        "achieved_qps": round(achieved_qps, 2),
        "entries_written": entries_written,
        "elapsed_seconds": round(elapsed, 1),
        "cost_per_hour": round(cost_per_hour, 4),
        "cost_per_1m_entries": round(cost_per_1m, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--duration", type=int, default=15, help="Benchmark duration in minutes (single-QPS mode)")
    parser.add_argument("--qps", type=int, default=100, help="Target QPS (single-QPS mode)")
    parser.add_argument("--warmup", type=int, default=60, help="Warmup duration in seconds (0 to disable)")
    parser.add_argument("--tier", default="small", help="Infrastructure tier (small/medium/large)")
    parser.add_argument("--qps_levels", default=None, help="Comma-separated QPS levels for sweep mode (e.g. 50,100,250,500)")
    parser.add_argument("--sweep_duration", type=int, default=5, help="Duration in minutes per QPS level during sweep")
    args = parser.parse_args()

    trillian_ip = get_lb_ip("ctfe", "trillian")
    tesseract_ip = get_lb_ip("tesseract-server", "tesseract")
    tree_id = get_trillian_tree_id()

    print(f"✅ Discovered Endpoints:\n  Trillian:  {trillian_ip} (Tree: {tree_id})\n  TesseraCT: {tesseract_ip}")

    # Build hammer tools upfront
    print("\n🔨 Building hammer tools...")
    run_cmd("go build -o bin/ct_hammer github.com/google/certificate-transparency-go/trillian/integration/ct_hammer")
    run_cmd("go build -o bin/hammer github.com/transparency-dev/tesseract/internal/hammer")

    # Smoke tests: verify both systems accept writes before committing to a full run
    print("\n" + "="*40)
    print("--- Smoke Tests ---")
    print("="*40)
    smoke_test("trillian", trillian_ip, args.project_id)
    smoke_test("tesseract", tesseract_ip, args.project_id)

    results = []

    if args.qps_levels:
        # Sweep mode: iterate over QPS levels
        qps_levels = [int(q.strip()) for q in args.qps_levels.split(",")]
        for qps_level in qps_levels:
            print("\n" + "="*40)
            print(f"--- Sweep: {qps_level} QPS — Trillian (MySQL) ---")
            print("="*40)
            r = run_single_benchmark("trillian", trillian_ip, tree_id, args.sweep_duration, qps_level, args.project_id, args.warmup, args.tier)
            results.append(r)

            print("\n" + "="*40)
            print(f"--- Sweep: {qps_level} QPS — TesseraCT (Spanner) ---")
            print("="*40)
            r = run_single_benchmark("tesseract", tesseract_ip, None, args.sweep_duration, qps_level, args.project_id, args.warmup, args.tier)
            results.append(r)
    else:
        # Single-QPS mode (backward compatible)
        print("\n" + "="*40)
        print("--- Phase 1: Trillian (MySQL) ---")
        print("="*40)
        r = run_single_benchmark("trillian", trillian_ip, tree_id, args.duration, args.qps, args.project_id, args.warmup, args.tier)
        results.append(r)

        print("\n" + "="*40)
        print("--- Phase 2: TesseraCT (Spanner) ---")
        print("="*40)
        r = run_single_benchmark("tesseract", tesseract_ip, None, args.duration, args.qps, args.project_id, args.warmup, args.tier)
        results.append(r)

    # Summary
    print("\n" + "="*40)
    print("      BENCHMARK SUMMARY")
    print("="*40)
    for r in results:
        print(f"{r['log_type'].capitalize()} @ {r['target_qps']} QPS: achieved {r['achieved_qps']:.2f} QPS, ${r['cost_per_hour']:.4f}/hr, ${r['cost_per_1m_entries']:.2f}/1M entries")
    print("="*40)

    summary = {
        "tier": args.tier,
        "results": results,
    }
    with open("benchmark_summary.json", "w") as f:
        json.dump(summary, f, indent=2)



if __name__ == "__main__":
    main()
