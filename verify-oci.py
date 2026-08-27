#!/usr/bin/env python3
"""Verify digests, compression, platform, and sensitive paths in an OCI layout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
from typing import Any


CHUNK_SIZE = 8 * 1024 * 1024
GITHUB_LAYER_LIMIT = 10_000_000_000
ZSTD_LAYER = "application/vnd.oci.image.layer.v1.tar+zstd"
SENSITIVE_HOME_FILES = {
    ".bash_history",
    ".git-credentials",
    ".netrc",
    ".zsh_history",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "known_hosts",
    "token",
}
ALLOWED_TENSOR_ASSETS = {
    "usr/local/lib/python3.12/dist-packages/compressed_tensors/transform/utils/hadamards.safetensors",
}


class HashingReader:
    def __init__(self, raw: Any) -> None:
        self.raw = raw
        self.hasher = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read(size)
        self.hasher.update(data)
        return data

    def hexdigest(self) -> str:
        return self.hasher.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("layout", type=Path)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def verify_blob(path: Path, descriptor: dict[str, Any]) -> None:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            hasher.update(chunk)
            size += len(chunk)
    actual_digest = f"sha256:{hasher.hexdigest()}"
    if actual_digest != descriptor["digest"]:
        raise RuntimeError(f"digest mismatch: {path.name}")
    if size != descriptor["size"]:
        raise RuntimeError(f"size mismatch: {path.name}")


def suspicious_path(name: str) -> bool:
    path = PurePosixPath(name)
    normalized = str(path).removeprefix("./").removeprefix("/")
    lowered = [part.lower() for part in path.parts]
    base = path.name.lower()
    if base.endswith((".safetensors", ".gguf")) and normalized not in ALLOWED_TENSOR_ASSETS:
        return True
    home_index = next(
        (index for index, part in enumerate(lowered) if part in {"root", "home"}),
        None,
    )
    if home_index is None:
        return False
    user_path = lowered[home_index:]
    if base in SENSITIVE_HOME_FILES:
        return True
    if ".ssh" in user_path:
        return True
    if ".aws" in user_path and base == "credentials":
        return True
    if ".docker" in user_path and base == "config.json":
        return True
    return False


def inspect_layer(path: Path) -> tuple[int, list[str], str]:
    process = subprocess.Popen(["zstd", "-q", "-d", "-c", path], stdout=subprocess.PIPE)
    assert process.stdout is not None
    reader = HashingReader(process.stdout)
    count = 0
    suspicious: list[str] = []
    try:
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                count += 1
                if member.isfile() and suspicious_path(member.name):
                    suspicious.append(member.name)
        while reader.read(CHUNK_SIZE):
            pass
        process.stdout.close()
        return_code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if return_code != 0:
        raise RuntimeError(f"zstd/tar validation failed: {path.name}")
    return count, suspicious, f"sha256:{reader.hexdigest()}"


def main() -> int:
    layout = parse_args().layout.resolve()
    index = load_json(layout / "index.json")
    if index.get("schemaVersion") != 2 or len(index.get("manifests", [])) != 1:
        raise RuntimeError("expected a single-manifest OCI index")

    manifest_descriptor = index["manifests"][0]
    manifest_path = layout / "blobs" / "sha256" / manifest_descriptor["digest"].split(":", 1)[1]
    verify_blob(manifest_path, manifest_descriptor)
    manifest = load_json(manifest_path)

    config_descriptor = manifest["config"]
    config_path = layout / "blobs" / "sha256" / config_descriptor["digest"].split(":", 1)[1]
    verify_blob(config_path, config_descriptor)
    config = load_json(config_path)
    if (config.get("os"), config.get("architecture")) != ("linux", "arm64"):
        raise RuntimeError("image platform is not linux/arm64")
    diff_ids = config.get("rootfs", {}).get("diff_ids", [])
    if len(diff_ids) != len(manifest["layers"]):
        raise RuntimeError("rootfs.diff_ids count does not match manifest layers")

    file_count = 0
    suspicious: list[str] = []
    layer_sizes: list[int] = []
    for number, descriptor in enumerate(manifest["layers"], start=1):
        if descriptor.get("mediaType") != ZSTD_LAYER:
            raise RuntimeError(f"layer {number} is not OCI zstd")
        path = layout / "blobs" / "sha256" / descriptor["digest"].split(":", 1)[1]
        verify_blob(path, descriptor)
        count, findings, uncompressed_digest = inspect_layer(path)
        if uncompressed_digest != diff_ids[number - 1]:
            raise RuntimeError(f"uncompressed digest mismatch for layer {number}")
        file_count += count
        suspicious.extend(findings)
        layer_sizes.append(descriptor["size"])
        print(f"verified layer {number:02d}/{len(manifest['layers'])}", flush=True)

    if suspicious:
        unique = sorted(set(suspicious))
        raise RuntimeError("sensitive or model paths found:\n" + "\n".join(unique))
    maximum = max(layer_sizes, default=0)
    if maximum >= GITHUB_LAYER_LIMIT:
        raise RuntimeError(f"layer exceeds GitHub's 10 GB limit: {maximum}")

    labels = config.get("config", {}).get("Labels", {}) or {}
    required_labels = {
        "org.opencontainers.image.title",
        "org.opencontainers.image.description",
        "org.opencontainers.image.source",
        "org.opencontainers.image.version",
        "org.opencontainers.image.revision",
        "org.opencontainers.image.created",
    }
    missing = sorted(required_labels - labels.keys())
    if missing:
        raise RuntimeError(f"missing OCI labels: {missing}")

    print(
        f"OK platform=linux/arm64 layers={len(layer_sizes)} files={file_count} "
        f"compressed={sum(layer_sizes) / 1e9:.3f}GB max_layer={maximum / 1e9:.3f}GB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
