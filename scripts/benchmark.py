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
        ip = run_cmd(f"kubectl get svc {service} -n {namespace} -o jsonpath='{{.status.loadBalancer.ingress[0].ip}}'")
        if ip:
            return ip
        time.sleep(10)
    print(f"❌ Timeout waiting for LoadBalancer IP for {service}")
    sys.exit(1)

def get_trillian_tree_id():
    print("🔍 Discovering Trillian Tree ID...")
    config = run_cmd("kubectl get configmap ctfe-config -n trillian -o jsonpath='{.data.ctfe\.cfg}'")
    for line in config.split("\n"):
        if "log_id:" in line:
            return line.split(":")[1].strip()
    print("❌ Could not find log_id in ctfe-config")
    sys.exit(1)

def get_trillian_pub_key():
    print("🔍 Fetching Trillian Public Key...")
    return run_cmd("kubectl get configmap ctfe-config -n trillian -o jsonpath='{.data.pubkey\.pem}'")

def get_tesseract_pub_key():
    print("🔍 Fetching TesseraCT Public Key...")
    return run_cmd("gcloud secrets versions access latest --secret='tesseract-signer-pub'")

def setup_root_ca():
    print("🔍 Fetching Benchmark Root CA...")
    root_priv = run_cmd("gcloud secrets versions access latest --secret='benchmark-root-priv'")
    root_pub = run_cmd("gcloud secrets versions access latest --secret='benchmark-root-pub'")
    with open("root-priv.pem", "w") as f:
        f.write(root_priv)
    with open("root-pub.pem", "w") as f:
        f.write(root_pub)
    return "root-priv.pem", "root-pub.pem"

def run_hammer(target_type, ip, tree_id=None, duration_min=5, qps=100, root_ca_files=None):
    print(f"🚀 Starting {target_type} load test ({qps} QPS for {duration_min} min)...")
    root_priv, root_pub = root_ca_files
    
    if target_type == "trillian":
        pub_key = get_trillian_pub_key()
        # Create temporary Trillian log config
        url = f"http://{ip}/benchmark"
        cfg = [{
            "name": "benchmark",
            "uri": url,
            "public_key": pub_key
        }]
        with open("trillian_cfg.json", "w") as f:
            json.dump(cfg, f)

        if not os.path.exists("bin/ct_hammer"):
            run_cmd("go build -o bin/ct_hammer github.com/google/certificate-transparency-go/trillian/integration/ct_hammer")
        
        total_ops = int(qps * duration_min * 60)
        # Note: Trillian hammer also needs the root CA to generate valid certs
        cmd = f"./bin/ct_hammer --log_config=trillian_cfg.json --ct_http_servers={url} --mmd=30s --rate_limit={qps} --operations={total_ops} --testdata_dir=."
        # We need to provide roots.pem in the current dir for Trillian hammer
        run_cmd(f"cp {root_pub} roots.pem")
        
    else: # tesseract
        if not os.path.exists("bin/hammer"):
             run_cmd("go build -o bin/hammer github.com/transparency-dev/tesseract/internal/hammer")
        
        url = f"http://{ip}"
        os.environ["CT_LOG_PUBLIC_KEY"] = get_tesseract_pub_key()
        # Tesseract hammer flags for custom CA
        cmd = f"./bin/hammer --log_url={url} --max_write_ops={qps} --max_read_ops={int(qps/10)} --max_runtime={duration_min}m --show_ui=false " \
              f"--intermediate_ca_cert_path={root_pub} --cert_sign_private_key_path={root_priv}"

    start_time = time.time()
    subprocess.run(cmd, shell=True, check=True)
    end_time = time.time()
    
    return start_time, end_time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--duration", type=int, default=5, help="Benchmark duration in minutes")
    parser.add_argument("--qps", type=int, default=100, help="Target QPS")
    args = parser.parse_args()

    # 1. Discover
    trillian_ip = get_lb_ip("ctfe", "trillian")
    tesseract_ip = get_lb_ip("tesseract-server", "tesseract")
    tree_id = get_trillian_tree_id()
    root_ca_files = setup_root_ca()

    print(f"✅ Discovered Endpoints:\n  Trillian:  {trillian_ip} (Tree: {tree_id})\n  TesseraCT: {tesseract_ip}")

    results = {}

    # 2. Run Trillian Benchmark
    print("\n" + "="*40)
    print("--- Phase 1: Trillian (MySQL) ---")
    print("="*40)
    t1_start, t1_end = run_hammer("trillian", trillian_ip, tree_id, args.duration, args.qps, root_ca_files)
    
    print("⏳ Waiting for metrics to settle...")
    time.sleep(30) 
    
    results["trillian"] = subprocess.check_output(
        f"python3 scripts/metrics.py --project_id {args.project_id} --start {t1_start} --end {t1_end} --type trillian",
        shell=True, text=True
    )

    # 3. Run TesseraCT Benchmark
    print("\n" + "="*40)
    print("--- Phase 2: TesseraCT (Spanner) ---")
    print("="*40)
    t2_start, t2_end = run_hammer("tesseract", tesseract_ip, None, args.duration, args.qps)
    
    print("⏳ Waiting for metrics to settle...")
    time.sleep(30)
    
    results["tesseract"] = subprocess.check_output(
        f"python3 scripts/metrics.py --project_id {args.project_id} --start {t2_start} --end {t2_end} --type tesseract",
        shell=True, text=True
    )

    # 4. Final Report
    print("\n" + "="*40)
    print("      BENCHMARK SUMMARY")
    print("="*40)
    
    try:
        tr_data = json.loads(results["trillian"])
        te_data = json.loads(results["tesseract"])

        print(f"Trillian Cost:  ${tr_data.get('total_cost', 0):.4f}")
        print(f"TesseraCT Cost: ${te_data.get('total_cost', 0):.4f}")
    except Exception as e:
        print(f"Error parsing results: {e}")
        print("Raw Trillian:", results.get("trillian"))
        print("Raw TesseraCT:", results.get("tesseract"))
        
    print("="*40)

if __name__ == "__main__":
    main()