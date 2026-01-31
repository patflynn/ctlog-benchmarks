import argparse
import subprocess
import time
import json
import sys
import os
import shutil

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

def generate_ct_testdata(root_priv, root_pub, dest_dir):
    print(f"🛠️ Generating CT testdata in {dest_dir}...")
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir)
    
    # Create extension file for CA
    ext_file = os.path.join(dest_dir, "v3_ca.ext")
    with open(ext_file, "w") as f:
        f.write("[ v3_ca ]\nbasicConstraints = critical,CA:TRUE\nkeyUsage = critical, digitalSignature, keyCertSign\n")

    shutil.copy(root_pub, os.path.join(dest_dir, "cacert.pem"))
    
    # Trillian Intermediate (RSA)
    tril_int_key = os.path.join(dest_dir, "tril-int.key")
    run_cmd(f"openssl genrsa -out {tril_int_key} 2048")
    run_cmd(f"openssl req -new -key {tril_int_key} -out {os.path.join(dest_dir, 'tril-int.csr')} -subj '/CN=Trillian Intermediate'")
    run_cmd(f"openssl x509 -req -in {os.path.join(dest_dir, 'tril-int.csr')} -CA {root_pub} -CAkey {root_priv} -CAcreateserial -out {os.path.join(dest_dir, 'tril-int.crt')} -days 365 -extfile {ext_file} -extensions v3_ca")
    # Encrypt for ct_hammer: needs legacy PEM encryption (Proc-Type/DEK-Info) wrapping
    # PKCS#8 DER. No single OpenSSL 3.x command produces this combination.
    run_cmd(f"go run scripts/pkcs8_encrypt.go {tril_int_key} {os.path.join(dest_dir, 'int-ca.privkey.pem')} babelfish")
    
    # Generate leaf01.chain for Trillian
    leaf_key = os.path.join(dest_dir, "leaf01.key")
    run_cmd(f"openssl genrsa -out {leaf_key} 2048")
    run_cmd(f"openssl req -new -key {leaf_key} -out {os.path.join(dest_dir, 'leaf01.csr')} -subj '/CN=benchmark-leaf-01'")
    run_cmd(f"openssl x509 -req -in {os.path.join(dest_dir, 'leaf01.csr')} -CA {os.path.join(dest_dir, 'tril-int.crt')} -CAkey {tril_int_key} -CAcreateserial -out {os.path.join(dest_dir, 'leaf01.crt')} -days 365")
    
    with open(os.path.join(dest_dir, "leaf01.chain"), "w") as f:
        with open(os.path.join(dest_dir, "leaf01.crt"), "r") as crt:
            f.write(crt.read())
        with open(os.path.join(dest_dir, "tril-int.crt"), "r") as icrt:
            f.write(icrt.read())

    # TesseraCT Intermediate (RSA)
    tess_int_key = os.path.join(dest_dir, "tess-int.key")
    run_cmd(f"openssl genrsa -out {tess_int_key} 2048")
    run_cmd(f"openssl req -new -key {tess_int_key} -out {os.path.join(dest_dir, 'tess-int.csr')} -subj '/CN=TesseraCT Intermediate'")
    run_cmd(f"openssl x509 -req -in {os.path.join(dest_dir, 'tess-int.csr')} -CA {root_pub} -CAkey {root_priv} -CAcreateserial -out {os.path.join(dest_dir, 'tess-int.crt')} -days 365 -extfile {ext_file} -extensions v3_ca")
    
    return {
        "trillian": {
            "int_crt": os.path.join(dest_dir, "tril-int.crt"),
            "int_key": os.path.join(dest_dir, "tril-int.key")
        },
        "tesseract": {
            "int_crt": os.path.join(dest_dir, "tess-int.crt"),
            "int_key": os.path.join(dest_dir, "tess-int.key")
        }
    }

def setup_root_ca():
    print("🔍 Fetching Benchmark Root CA...")
    # Use latest version from Secret Manager (which we just updated to RSA)
    root_priv = run_cmd("gcloud secrets versions access latest --secret='benchmark-root-priv'")
    root_pub = run_cmd("gcloud secrets versions access latest --secret='benchmark-root-pub'")
    with open("root-priv.pem", "w") as f:
        f.write(root_priv)
    with open("root-pub.pem", "w") as f:
        f.write(root_pub)
    return "root-priv.pem", "root-pub.pem"

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
        with open("testdata/leaf01.chain", "r") as f:
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


def run_hammer(target_type, ip, tree_id=None, duration_min=5, qps=100, root_ca_files=None, project_id=None, cert_info=None):
    print(f"🚀 Starting {target_type} load test ({qps} QPS for {duration_min} min)...")
    root_priv, root_pub = root_ca_files
    
    initial_size = get_log_size(target_type, ip, project_id)
    print(f"📈 Initial tree size: {initial_size}")

    if target_type == "trillian":
        der_hex = get_trillian_pub_key_der_hex()
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
        run_cmd(f"cp {root_pub} roots.pem")
        cmd = f"./bin/ct_hammer --log_config=trillian_cfg.textproto --ct_http_servers={url} --mmd=30s --rate_limit={qps} --operations={total_ops} --testdata_dir=testdata --ignore_errors"
    else:
        os.environ["CT_LOG_PUBLIC_KEY"] = get_tesseract_pub_key_b64()
        log_url = f"gs://tesseract-storage-{project_id}/"
        write_url = f"http://{ip}"
        int_crt = cert_info["tesseract"]["int_crt"]
        int_key = cert_info["tesseract"]["int_key"]
        total_ops = int(qps * duration_min * 60)
        # Scale writers with target QPS (1 writer per ~50 QPS, minimum 4)
        num_writers = max(4, qps // 50)
        cmd = f"./bin/hammer --log_url={log_url} --write_log_url={write_url} --origin=tesseract-benchmark --max_write_ops={qps} --max_read_ops={int(qps/10)} --max_runtime={duration_min}m --show_ui=false " \
              f"--num_writers={num_writers} --num_readers_random=1 --num_mmd_verifiers=1 --leaf_write_goal={total_ops} " \
              f"--intermediate_ca_cert_path={int_crt} --intermediate_ca_key_path={int_key} --cert_sign_private_key_path={int_key}"

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

    return start_time, end_time, achieved_qps

def main():
    # ... (rest of main setup)
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--duration", type=int, default=15, help="Benchmark duration in minutes")
    parser.add_argument("--qps", type=int, default=100, help="Target QPS")
    args = parser.parse_args()

    trillian_ip = get_lb_ip("ctfe", "trillian")
    tesseract_ip = get_lb_ip("tesseract-server", "tesseract")
    tree_id = get_trillian_tree_id()
    root_ca_files = setup_root_ca()
    cert_info = generate_ct_testdata(root_ca_files[0], root_ca_files[1], "testdata")

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

    final_results = []

    # 3. Run Trillian Benchmark
    print("\n" + "="*40)
    print("--- Phase 1: Trillian (MySQL) ---")
    print("="*40)
    t1_start, t1_end, qps1 = run_hammer("trillian", trillian_ip, tree_id, args.duration, args.qps, root_ca_files, args.project_id, cert_info)

    res1 = subprocess.check_output(
        f"python3 scripts/metrics.py --project_id {args.project_id} --start {t1_start} --end {t1_end} --type trillian",
        shell=True, text=True
    )
    data1 = json.loads(res1)
    data1["achieved_qps"] = qps1
    final_results.append(data1)

    # 4. Run TesseraCT Benchmark
    print("\n" + "="*40)
    print("--- Phase 2: TesseraCT (Spanner) ---")
    print("="*40)
    t2_start, t2_end, qps2 = run_hammer("tesseract", tesseract_ip, None, args.duration, args.qps, root_ca_files, args.project_id, cert_info)

    res2 = subprocess.check_output(
        f"python3 scripts/metrics.py --project_id {args.project_id} --start {t2_start} --end {t2_end} --type tesseract",
        shell=True, text=True
    )
    data2 = json.loads(res2)
    data2["achieved_qps"] = qps2
    final_results.append(data2)

    # Summary
    print("\n" + "="*40)
    print("      BENCHMARK SUMMARY")
    print("="*40)
    for r in final_results:
        print(f"{r['log_type'].capitalize()} Achieved QPS: {r['achieved_qps']:.2f}")
        print(f"{r['log_type'].capitalize()} Total Cost:  ${r['total_cost']:.4f}")
        print(f"{r['log_type'].capitalize()} Cost/hr:     ${r.get('cost_per_hour', 0):.4f}")
        print("-" * 20)
    print("="*40)
    with open("benchmark_summary.json", "w") as f:
        json.dump(final_results, f, indent=2)



if __name__ == "__main__":
    main()
