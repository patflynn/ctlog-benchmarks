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
    
    # Trillian Intermediate (EC)
    tril_int_key = os.path.join(dest_dir, "tril-int.key")
    run_cmd(f"openssl ecparam -name prime256v1 -genkey -noout -out {tril_int_key}")
    run_cmd(f"openssl req -new -key {tril_int_key} -out {os.path.join(dest_dir, 'tril-int.csr')} -subj '/CN=Trillian Intermediate'")
    run_cmd(f"openssl x509 -req -in {os.path.join(dest_dir, 'tril-int.csr')} -CA {root_pub} -CAkey {root_priv} -CAcreateserial -out {os.path.join(dest_dir, 'tril-int.crt')} -days 365 -extfile {ext_file} -extensions v3_ca")
    # Encrypt for ct_hammer
    run_cmd(f"openssl ec -in {tril_int_key} -out {os.path.join(dest_dir, 'int-ca.privkey.pem')} -des3 -passout pass:babelfish")
    
    # Generate leaf01.chain for Trillian
    leaf_key = os.path.join(dest_dir, "leaf01.key")
    run_cmd(f"openssl ecparam -name prime256v1 -genkey -noout -out {leaf_key}")
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

def run_hammer(target_type, ip, tree_id=None, duration_min=5, qps=100, root_ca_files=None, project_id=None, cert_info=None):
    print(f"🚀 Starting {target_type} load test ({qps} QPS for {duration_min} min)...")
    root_priv, root_pub = root_ca_files
    
    if target_type == "trillian":
        der_hex = get_trillian_pub_key_der_hex()
            
        # Create Trillian log config in Text Proto format using DER key
        with open("trillian_cfg.textproto", "w") as f:
            f.write(f'config {{\n')
            f.write(f'  log_id: {tree_id}\n')
            f.write(f'  prefix: "benchmark"\n')
            f.write(f'  roots_pem_file: "roots.pem"\n')
            f.write(f'  public_key {{\n')
            f.write(f'    der: "{der_hex}"\n')
            f.write(f'  }}\n')
            f.write(f'}}\n')

        # Always build locally to be safe
        run_cmd("go build -o bin/ct_hammer github.com/google/certificate-transparency-go/trillian/integration/ct_hammer")
        
        total_ops = int(qps * duration_min * 60)
        # ct_hammer appends prefix/ct/v1/ to the server URL
        url = f"http://{ip}"
        
        # We need roots.pem in the current dir
        run_cmd(f"cp {root_pub} roots.pem")
        
        cmd = f"./bin/ct_hammer --log_config=trillian_cfg.textproto --ct_http_servers={url} --mmd=30s --rate_limit={qps} --operations={total_ops} --testdata_dir=testdata"
        
    else: # tesseract
        # Build from local temp-tesseract to include ECDSA support patch
        run_cmd("go build -o bin/hammer github.com/transparency-dev/tesseract/internal/hammer")
        
        os.environ["CT_LOG_PUBLIC_KEY"] = get_tesseract_pub_key_b64()
        log_url = f"gs://tesseract-storage-{project_id}/tesseract-benchmark/"
        # Server serves directly at /ct/v1/
        write_url = f"http://{ip}"
        
        # TesseraCT hammer needs RSA Intermediate
        int_crt = cert_info["tesseract"]["int_crt"]
        int_key = cert_info["tesseract"]["int_key"]
        
        cmd = f"./bin/hammer --log_url={log_url} --write_log_url={write_url} --origin=tesseract-benchmark --max_write_ops={qps} --max_read_ops={int(qps/10)} --max_runtime={duration_min}m --show_ui=false " \
              f"--num_writers=1 --num_readers_random=1 --num_mmd_verifiers=1 " \
              f"--intermediate_ca_cert_path={int_crt} --intermediate_ca_key_path={int_key} --cert_sign_private_key_path={int_key}"

    start_time = time.time()
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Hammer returned error: {e}")
        
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
    
    # 2. Setup Certificates
    cert_info = generate_ct_testdata(root_ca_files[0], root_ca_files[1], "testdata")

    print(f"✅ Discovered Endpoints:\n  Trillian:  {trillian_ip} (Tree: {tree_id})\n  TesseraCT: {tesseract_ip}")

    results = {}

    # 3. Run Trillian Benchmark
    print("\n" + "="*40)
    print("--- Phase 1: Trillian (MySQL) ---")
    print("="*40)
    t1_start, t1_end = run_hammer("trillian", trillian_ip, tree_id, args.duration, args.qps, root_ca_files, args.project_id, cert_info)
    
    print("⏳ Waiting for metrics to settle...")
    time.sleep(30) 
    
    results["trillian"] = subprocess.check_output(
        f"python3 scripts/metrics.py --project_id {args.project_id} --start {t1_start} --end {t1_end} --type trillian",
        shell=True, text=True
    )

    # 4. Run TesseraCT Benchmark
    print("\n" + "="*40)
    print("--- Phase 2: TesseraCT (Spanner) ---")
    print("="*40)
    t2_start, t2_end = run_hammer("tesseract", tesseract_ip, None, args.duration, args.qps, root_ca_files, args.project_id, cert_info)
    
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
