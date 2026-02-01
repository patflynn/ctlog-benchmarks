#!/bin/bash
set -e

PROJECT_ID=${1}
REGION=${2:-us-central1}
ZONE=${3:-us-central1-a}
CLUSTER_NAME="ctlog-cluster"
REPO_NAME="ctlog-benchmarks"

if [ -z "$PROJECT_ID" ]; then
    echo "Usage: $0 <PROJECT_ID> [REGION] [ZONE]"
    exit 1
fi

echo "🚀 Starting Deployment to ${PROJECT_ID}..."

# 1. Auth to GKE
echo "🔑 Getting Cluster Credentials..."
gcloud container clusters get-credentials ${CLUSTER_NAME} --zone ${ZONE} --project ${PROJECT_ID}

# 2. Configure KO
export KO_DOCKER_REPO="gcr.io/${PROJECT_ID}/${REPO_NAME}"
echo "📦 Configuring ko to push to: ${KO_DOCKER_REPO}"

# Use pre-baked testdata from upstream projects (no dynamic key generation)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Ensure go.mod is tidy in the CI environment
go mod tidy

# 3. Deploy Trillian
echo "Deploying Trillian Stack..."
# We use 'ko resolve' to build images and replace placeholders, then pipe to kubectl
# Note: We need to substitute ${PROJECT_ID} and ${REGION} in the YAMLs first.
# simpler approach: export env vars and use envsubst, BUT ko needs valid YAML.
# So we substitute -> ko resolve -> kubectl apply.

# Create a temporary directory for processed manifests
mkdir -p build/k8s/trillian build/k8s/tesseract

# Process Trillian Manifests
for f in k8s/trillian/*.yaml; do
    envsubst < $f > build/$f
done

echo "   Creating Trillian Config Secret..."
DB_PASS=$(gcloud secrets versions access latest --secret="trillian-db-password" --project="${PROJECT_ID}")
# Format: user:password@tcp(host:port)/dbname
kubectl create secret generic trillian-config \
    --namespace trillian \
    --from-literal=MYSQL_URI="trillian:${DB_PASS}@tcp(127.0.0.1:3306)/trillian" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "   Building and pushing Trillian images..."
ko apply -f build/k8s/trillian/

# --- Provision Trillian Tree ---
echo "🌱 Provisioning Trillian Tree..."
# Wait for Log Server to be ready (it might be crashlooping if DB is empty, but sidecar should be up)
# Actually, if Log Server crashes, the Pod is Running but container is restarting. Port forward works!
kubectl rollout status deployment/trillian-logserver -n trillian --timeout=5m || true

echo "   Initializing Database Schema..."
POD_NAME=$(kubectl get pods -n trillian -l app=trillian-logserver -o jsonpath='{.items[0].metadata.name}')
# Port forward DB port from the Pod
kubectl port-forward -n trillian pod/$POD_NAME 3306:3306 > /dev/null 2>&1 &
DB_PF_PID=$!
sleep 5

# Run Init Script
go run scripts/init_db.go "trillian:${DB_PASS}@tcp(127.0.0.1:3306)/trillian"

# Stop DB Port Forward
kill $DB_PF_PID

# Install createtree
go install github.com/google/trillian/cmd/createtree

# Port Forward to Log Server
echo "   Starting Port Forward to Log Server..."
kubectl port-forward svc/trillian-logserver 8090:8090 -n trillian > /dev/null 2>&1 &
PF_PID=$!
sleep 5

# Create Tree
echo "   Creating Log Tree..."
CREATETREE_BIN="$(go env GOPATH)/bin/createtree"
TREE_ID=$($CREATETREE_BIN --admin_server=localhost:8090 --display_name="Benchmark")
echo "   Tree ID: ${TREE_ID}"

# Stop Port Forward
kill $PF_PID

# Use pre-baked CTFE keys and roots from upstream testdata
cp "${REPO_ROOT}/testdata/trillian/ct-http-server.privkey.pem" privkey.pem
cp "${REPO_ROOT}/testdata/trillian/ct-http-server.pubkey.pem" pubkey.pem
cp "${REPO_ROOT}/testdata/trillian/fake-ca.cert" roots.pem

cat <<EOF > ctfe.cfg
config {
  log_id: ${TREE_ID}
  prefix: "benchmark"
  roots_pem_file: "/config/roots.pem"
  private_key: {
    [type.googleapis.com/keyspb.PEMKeyFile] {
      path: "/config/privkey.pem"
      password: "dirk"
    }
  }
}
EOF

# Update/Create CTFE ConfigMap
kubectl create configmap ctfe-config \
    --namespace trillian \
    --from-file=ctfe.cfg=ctfe.cfg \
    --from-file=roots.pem=roots.pem \
    --from-file=privkey.pem=privkey.pem \
    --from-file=pubkey.pem=pubkey.pem \
    --dry-run=client -o yaml | kubectl apply -f -

# Restart CTFE to pick up config
kubectl rollout restart deployment/ctfe -n trillian

# Cleanup local keys for Trillian
rm -f privkey-raw.pem privkey.pem pubkey.pem roots.pem ctfe.cfg

# Tesseract signer keys are managed by Terraform — no generation needed here

# Resolve 'latest' to canonical version name (e.g., projects/.../versions/5)
# This bypasses Tesseract's strict name check which fails on 'latest' alias
export PUB_KEY_SECRET_NAME=$(gcloud secrets versions describe latest --secret="tesseract-signer-pub" --project="${PROJECT_ID}" --format="value(name)")
export PRIV_KEY_SECRET_NAME=$(gcloud secrets versions describe latest --secret="tesseract-signer-priv" --project="${PROJECT_ID}" --format="value(name)")

echo "   Resolved Secret Versions:"
echo "   Public:  ${PUB_KEY_SECRET_NAME}"
echo "   Private: ${PRIV_KEY_SECRET_NAME}"

# Create ConfigMap for Tesseract roots
kubectl create configmap tesseract-config \
    --namespace tesseract \
    --from-file=roots.pem="${REPO_ROOT}/testdata/tesseract/test_root_ca_cert.pem" \
    --dry-run=client -o yaml | kubectl apply -f -

# Process Tesseract Manifests (after exporting secret names)
for f in k8s/tesseract/*.yaml; do
    envsubst < $f > build/$f
done

# No local key files to clean up — all testdata lives in the repo

echo "   Building and pushing TesseraCT images..."
ko apply -f build/k8s/tesseract/

# 5. Wait for Rollout
echo "⏳ Waiting for Trillian..."
kubectl rollout status deployment/trillian-logserver -n trillian
kubectl rollout status deployment/trillian-logsigner -n trillian
kubectl rollout status deployment/ctfe -n trillian

echo "⏳ Waiting for TesseraCT..."
kubectl rollout status deployment/tesseract-server -n tesseract

echo "✅ Deployment Complete!"
echo "---------------------------------------------------"
echo "Trillian CTFE IP: $(kubectl get svc ctfe -n trillian -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
echo "TesseraCT IP:     $(kubectl get svc tesseract-server -n tesseract -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
echo "---------------------------------------------------"
