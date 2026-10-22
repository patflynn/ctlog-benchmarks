#!/bin/bash
# Builds the tesseract-hammer job image from a TesseraCT checkout (same tag as the server).
# Usage: cloudrun/hammer/build.sh <path-to-tesseract-checkout>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$1"
source "$HERE/../../.env.local"
mkdir -p "$SRC/internal/hammer/kodata"
cp "$SRC"/internal/hammer/testdata/*.pem "$HERE/entrypoint.sh" "$SRC/internal/hammer/kodata/"
cd "$SRC"
# ko must use /usr/bin/gcloud as the docker credential helper (not the Nix one).
KO_CONFIG_PATH="$HERE/.ko.yaml" KO_DOCKER_REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/tesseract-bench/tesseract-hammer" \
  PATH=/usr/bin:/bin:$PATH ko build --bare --tags="$(git describe --tags --always)" ./internal/hammer
