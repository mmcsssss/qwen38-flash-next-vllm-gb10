#!/usr/bin/env python3
"""Update the source label in an OCI layout without touching layer blobs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def compact_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_blob(blobs: Path, data: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    path = blobs / digest
    if not path.exists():
        path.write_bytes(data)
    return {"digest": f"sha256:{digest}", "size": len(data)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("layout", type=Path)
    parser.add_argument("source_url")
    args = parser.parse_args()

    layout = args.layout.resolve()
    blobs = layout / "blobs" / "sha256"
    index_path = layout / "index.json"
    index = json.loads(index_path.read_bytes())
    if len(index.get("manifests", [])) != 1:
        raise RuntimeError("expected one manifest")

    manifest_descriptor = index["manifests"][0]
    manifest_path = blobs / manifest_descriptor["digest"].split(":", 1)[1]
    manifest = json.loads(manifest_path.read_bytes())
    config_descriptor = manifest["config"]
    config_path = blobs / config_descriptor["digest"].split(":", 1)[1]
    config = json.loads(config_path.read_bytes())

    labels = config.setdefault("config", {}).setdefault("Labels", {})
    labels["org.opencontainers.image.source"] = args.source_url
    new_config = write_blob(blobs, compact_json(config))
    new_config["mediaType"] = config_descriptor["mediaType"]
    manifest["config"] = new_config

    new_manifest = write_blob(blobs, compact_json(manifest))
    for key in ("mediaType", "platform", "annotations"):
        if key in manifest_descriptor:
            new_manifest[key] = manifest_descriptor[key]
    index["manifests"][0] = new_manifest

    temporary = index_path.with_suffix(".json.building")
    temporary.write_bytes(compact_json(index))
    temporary.replace(index_path)
    print(new_config["digest"])
    print(new_manifest["digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
