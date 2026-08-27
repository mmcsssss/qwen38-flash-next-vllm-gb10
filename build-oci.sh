#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_IMAGE="${BASE_IMAGE:-local/vllm-qwen38-next:ssd-ple-gb10-decode-f561}"
STAGE_IMAGE="${STAGE_IMAGE:-local/qwen38-flash-next-vllm:ghcr-stage}"
SOURCE_URL="${SOURCE_URL:-https://github.com/mmcsssss/qwen38-flash-next-vllm-gb10}"
VERSION="${VERSION:-2026.08.27-gb10}"
REVISION="${REVISION:-f561eca6ca4f3f79808a696b1521cb76dc8aafa2}"
OUTPUT="${OUTPUT:-${ROOT_DIR}/qwen38-flash-next-gb10-arm64.oci}"
REF_NAME="${REF_NAME:-2026.08.27}"
CREATED="${CREATED:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

if [[ -e "$OUTPUT" ]]; then
  echo "Refusing to overwrite existing OCI layout: $OUTPUT" >&2
  exit 1
fi

docker image inspect "$BASE_IMAGE" >/dev/null

docker build \
  --platform linux/arm64 \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --build-arg "SOURCE_URL=$SOURCE_URL" \
  --build-arg "VERSION=$VERSION" \
  --build-arg "REVISION=$REVISION" \
  --build-arg "CREATED=$CREATED" \
  --tag "$STAGE_IMAGE" \
  "$ROOT_DIR"

python3 "$ROOT_DIR/repack-oci.py" \
  --image "$STAGE_IMAGE" \
  --output "$OUTPUT" \
  --ref-name "$REF_NAME" \
  --zstd-level 3

echo "OCI layout: $OUTPUT"
