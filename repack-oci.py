#!/usr/bin/env python3
"""Export a local Docker image as a fully compressed OCI image layout.

The Docker daemon on this host uses the classic buildx driver, whose OCI
exporter is unavailable. This tool streams `docker image save`, recompresses
every uncompressed layer with zstd, and writes a standalone OCI directory.
It never modifies or removes the source image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from typing import BinaryIO, Any


OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER_ZSTD = "application/vnd.oci.image.layer.v1.tar+zstd"
GITHUB_LAYER_LIMIT = 10_000_000_000
CHUNK_SIZE = 8 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Local source image tag")
    parser.add_argument("--output", required=True, type=Path, help="OCI layout directory")
    parser.add_argument("--ref-name", default="2026.08.27", help="OCI reference annotation")
    parser.add_argument("--zstd-level", default=3, type=int)
    return parser.parse_args()


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def verify_named_blob(name: str, actual_hash: str) -> None:
    expected = Path(name).name
    if len(expected) == 64 and expected != actual_hash:
        raise RuntimeError(f"source blob digest mismatch: {expected} != {actual_hash}")


def is_tar_header(block: bytes) -> bool:
    if len(block) < 512:
        return False
    if block == b"\0" * len(block):
        return True
    if block[257:262] == b"ustar":
        return True
    raw = block[148:156].strip(b"\0 ")
    try:
        stored = int(raw or b"0", 8)
    except ValueError:
        return False
    calculated = sum(block[:148]) + sum(b" " * 8) + sum(block[156:512])
    return stored == calculated


def read_blob(stream: BinaryIO, first: bytes) -> tuple[bytes, str, int]:
    hasher = hashlib.sha256()
    chunks = [first]
    hasher.update(first)
    size = len(first)
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        chunks.append(chunk)
        hasher.update(chunk)
        size += len(chunk)
    return b"".join(chunks), hasher.hexdigest(), size


def compress_layer(
    stream: BinaryIO,
    first: bytes,
    source_name: str,
    blobs_dir: Path,
    level: int,
    layer_number: int,
) -> tuple[dict[str, Any], str]:
    source_hash = hashlib.sha256()
    source_hash.update(first)
    source_size = len(first)
    temporary = blobs_dir / f".layer-{layer_number:03d}-{Path(source_name).name}.zst.building"
    started = time.monotonic()

    with temporary.open("xb") as output:
        compressor = subprocess.Popen(
            ["zstd", f"-{level}", "-T0", "-q", "-c"],
            stdin=subprocess.PIPE,
            stdout=output,
        )
        assert compressor.stdin is not None
        try:
            compressor.stdin.write(first)
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                source_hash.update(chunk)
                source_size += len(chunk)
                compressor.stdin.write(chunk)
            compressor.stdin.close()
            return_code = compressor.wait()
        except BaseException:
            compressor.kill()
            compressor.wait()
            raise

    if return_code != 0:
        raise RuntimeError(f"zstd failed for {source_name}: exit {return_code}")

    source_digest = source_hash.hexdigest()
    verify_named_blob(source_name, source_digest)

    compressed_hash = hashlib.sha256()
    compressed_size = 0
    with temporary.open("rb") as compressed:
        while chunk := compressed.read(CHUNK_SIZE):
            compressed_hash.update(chunk)
            compressed_size += len(chunk)
    compressed_digest = compressed_hash.hexdigest()
    final_path = blobs_dir / compressed_digest
    if final_path.exists():
        raise RuntimeError(f"duplicate compressed blob: {compressed_digest}")
    temporary.rename(final_path)

    elapsed = max(time.monotonic() - started, 0.001)
    print(
        f"layer {layer_number:02d}: {source_size / 1e9:.3f} GB -> "
        f"{compressed_size / 1e9:.3f} GB in {elapsed:.1f}s",
        flush=True,
    )
    descriptor = {
        "mediaType": OCI_LAYER_ZSTD,
        "digest": f"sha256:{compressed_digest}",
        "size": compressed_size,
    }
    return descriptor, f"sha256:{source_digest}"


def write_blob(blobs_dir: Path, data: bytes) -> dict[str, Any]:
    digest = digest_bytes(data)
    path = blobs_dir / digest.removeprefix("sha256:")
    path.write_bytes(data)
    return {"digest": digest, "size": len(data)}


def load_source_manifest(
    top_level: dict[str, bytes], json_blobs: dict[str, bytes]
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if "index.json" in top_level:
        index = json.loads(top_level["index.json"])
        manifests = index.get("manifests", [])
        if len(manifests) != 1:
            raise RuntimeError(f"expected one image manifest, found {len(manifests)}")
        manifest_digest = manifests[0]["digest"].removeprefix("sha256:")
        manifest = json.loads(json_blobs[manifest_digest])
        config_digest = manifest["config"]["digest"].removeprefix("sha256:")
        config = json.loads(json_blobs[config_digest])
        layers = [item["digest"] for item in manifest["layers"]]
        return manifest, config, layers

    if "manifest.json" not in top_level:
        raise RuntimeError("docker save output has neither index.json nor manifest.json")
    docker_manifest = json.loads(top_level["manifest.json"])
    if len(docker_manifest) != 1:
        raise RuntimeError(f"expected one Docker manifest, found {len(docker_manifest)}")
    item = docker_manifest[0]
    config_name = Path(item["Config"]).name
    config = json.loads(json_blobs[config_name])
    layers = [f"sha256:{Path(path).name}" for path in item["Layers"]]
    manifest = {"schemaVersion": 2, "layers": [{"digest": value} for value in layers]}
    return manifest, config, layers


def validate_layout(output: Path) -> tuple[int, int, int]:
    index = json.loads((output / "index.json").read_text())
    descriptor = index["manifests"][0]
    manifest_digest = descriptor["digest"].removeprefix("sha256:")
    manifest_path = output / "blobs" / "sha256" / manifest_digest
    manifest_data = manifest_path.read_bytes()
    if digest_bytes(manifest_data) != descriptor["digest"]:
        raise RuntimeError("output manifest digest mismatch")
    if len(manifest_data) != descriptor["size"]:
        raise RuntimeError("output manifest size mismatch")
    manifest = json.loads(manifest_data)

    descriptors = [manifest["config"], *manifest["layers"]]
    for item in descriptors:
        path = output / "blobs" / "sha256" / item["digest"].removeprefix("sha256:")
        actual_size = path.stat().st_size
        if actual_size != item["size"]:
            raise RuntimeError(f"size mismatch for {path.name}")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                hasher.update(chunk)
        if f"sha256:{hasher.hexdigest()}" != item["digest"]:
            raise RuntimeError(f"digest mismatch for {path.name}")

    config = json.loads(
        (output / "blobs" / "sha256" / manifest["config"]["digest"].removeprefix("sha256:")).read_bytes()
    )
    if config.get("architecture") != "arm64" or config.get("os") != "linux":
        raise RuntimeError(
            f"unexpected platform: {config.get('os')}/{config.get('architecture')}"
        )

    layer_sizes = [item["size"] for item in manifest["layers"]]
    maximum = max(layer_sizes, default=0)
    if maximum >= GITHUB_LAYER_LIMIT:
        raise RuntimeError(
            f"largest compressed layer is {maximum} bytes; GitHub limit is below 10 GB"
        )
    return len(layer_sizes), sum(layer_sizes), maximum


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    staging = output.with_name(output.name + f".building-{os.getpid()}")
    if output.exists() or staging.exists():
        raise RuntimeError(f"refusing to overwrite existing path: {output} or {staging}")

    blobs_dir = staging / "blobs" / "sha256"
    blobs_dir.mkdir(parents=True)
    print(f"exporting {args.image}; source image remains unchanged", flush=True)

    docker = subprocess.Popen(
        ["docker", "image", "save", args.image],
        stdout=subprocess.PIPE,
    )
    assert docker.stdout is not None
    top_level: dict[str, bytes] = {}
    json_blobs: dict[str, bytes] = {}
    compressed_layers: dict[str, dict[str, Any]] = {}
    layer_number = 0

    try:
        with tarfile.open(fileobj=docker.stdout, mode="r|") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                normalized = member.name.removeprefix("./")
                first = stream.read(4096)

                if normalized in {"index.json", "manifest.json", "oci-layout", "repositories"}:
                    data, actual_hash, _ = read_blob(stream, first)
                    top_level[normalized] = data
                    print(f"metadata: {normalized}", flush=True)
                    continue

                if not normalized.startswith("blobs/sha256/"):
                    raise RuntimeError(f"unexpected file in docker save stream: {normalized}")

                if not is_tar_header(first):
                    data, actual_hash, _ = read_blob(stream, first)
                    verify_named_blob(normalized, actual_hash)
                    try:
                        json.loads(data)
                    except json.JSONDecodeError as error:
                        raise RuntimeError(f"non-layer blob is not JSON: {normalized}") from error
                    json_blobs[Path(normalized).name] = data
                    continue

                layer_number += 1
                descriptor, source_digest = compress_layer(
                    stream,
                    first,
                    normalized,
                    blobs_dir,
                    args.zstd_level,
                    layer_number,
                )
                compressed_layers[source_digest] = descriptor

        docker.stdout.close()
        return_code = docker.wait()
        if return_code != 0:
            raise RuntimeError(f"docker image save failed: exit {return_code}")
    except BaseException:
        docker.terminate()
        try:
            docker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            docker.kill()
            docker.wait()
        print(f"incomplete staging directory retained for inspection: {staging}", file=sys.stderr)
        raise

    source_manifest, config, source_layer_digests = load_source_manifest(top_level, json_blobs)
    missing = [digest for digest in source_layer_digests if digest not in compressed_layers]
    if missing:
        raise RuntimeError(f"missing exported layers: {missing}")

    diff_ids = config.get("rootfs", {}).get("diff_ids", [])
    if diff_ids and diff_ids != source_layer_digests:
        raise RuntimeError("source manifest layers do not match config rootfs.diff_ids")

    config_data = json_bytes(config)
    config_descriptor = write_blob(blobs_dir, config_data)
    config_descriptor["mediaType"] = OCI_CONFIG

    layers: list[dict[str, Any]] = []
    for original, source_digest in zip(source_manifest["layers"], source_layer_digests, strict=True):
        descriptor = dict(compressed_layers[source_digest])
        if "annotations" in original:
            descriptor["annotations"] = original["annotations"]
        layers.append(descriptor)

    manifest: dict[str, Any] = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": config_descriptor,
        "layers": layers,
    }
    for key in ("annotations", "artifactType", "subject"):
        if key in source_manifest:
            manifest[key] = source_manifest[key]
    manifest_data = json_bytes(manifest)
    manifest_descriptor = write_blob(blobs_dir, manifest_data)
    manifest_descriptor.update(
        {
            "mediaType": OCI_MANIFEST,
            "platform": {"architecture": "arm64", "os": "linux"},
            "annotations": {"org.opencontainers.image.ref.name": args.ref_name},
        }
    )

    index = {
        "schemaVersion": 2,
        "mediaType": OCI_INDEX,
        "manifests": [manifest_descriptor],
    }
    (staging / "index.json").write_bytes(json_bytes(index))
    (staging / "oci-layout").write_bytes(json_bytes({"imageLayoutVersion": "1.0.0"}))

    count, total, maximum = validate_layout(staging)
    staging.rename(output)
    print(f"validated OCI layout: {output}", flush=True)
    print(
        f"layers={count} compressed_total={total / 1e9:.3f} GB "
        f"largest_layer={maximum / 1e9:.3f} GB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
