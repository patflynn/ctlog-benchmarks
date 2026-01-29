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

echo "   Building and pushing Trillian images..."
ko apply -f build/k8s/trillian/

# 4. Deploy TesseraCT
echo "Deploying TesseraCT Stack..."
for f in k8s/tesseract/*.yaml; do
    envsubst < $f > build/$f
done

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
