#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OCI_DIR="${OCI_DIR:-${ROOT_DIR}/qwen38-flash-next-gb10-arm64.oci}"
OCI_REF="${OCI_REF:-2026.08.27}"
AUTHFILE="${AUTHFILE:-${HOME}/.docker/config.json}"

: "${GHCR_IMAGE:?Set GHCR_IMAGE, for example ghcr.io/owner/qwen38-flash-next-vllm:2026.08.27}"

if [[ ! -d "$OCI_DIR" ]]; then
  echo "OCI layout not found: $OCI_DIR" >&2
  exit 1
fi
if ! command -v skopeo >/dev/null 2>&1; then
  echo "skopeo is required to copy the prepared OCI layout to GHCR." >&2
  echo "No package is installed automatically by this script." >&2
  exit 1
fi
if [[ ! -f "$AUTHFILE" ]]; then
  echo "Registry auth file not found: $AUTHFILE" >&2
  echo "Authenticate with: docker login ghcr.io" >&2
  exit 1
fi

skopeo copy \
  --dest-authfile "$AUTHFILE" \
  "oci:${OCI_DIR}:${OCI_REF}" \
  "docker://${GHCR_IMAGE}"
