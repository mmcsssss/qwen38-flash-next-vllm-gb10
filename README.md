# Qwen3.8 Flash Next vLLM for DGX Spark

This is the publication bundle for the validated ARM64 image
`local/vllm-qwen38-next:ssd-ple-gb10-decode-f561`. It targets NVIDIA DGX
Spark / ASUS Ascent GX10 and keeps the local production image unchanged.

## Contents

- CUDA 13 ARM64 vLLM at commit `f561eca6ca4f3f79808a696b1521cb76dc8aafa2`
- RadixArk Qwen3.8 Flash Next NVFP4 support
- SSD-backed PLE loading without sustained SSD writes during decode
- Native MTP with a validated default depth of 2
- PLE worker affinity for the ten Cortex-X925 performance cores
- OpenAI-compatible Chat Completions and Responses endpoints
- Text, tool calling, high-detail vision, prefix caching, and C1-C4 support

Model weights are deliberately excluded. Mount a separately downloaded model
snapshot read-only at runtime and comply with that model's license.

## Validated profile

| Setting | Value |
| --- | --- |
| Architecture | `linux/arm64` |
| Host | DGX Spark / ASUS Ascent GX10 |
| Context per request | 262,144 tokens |
| Maximum sequences | 4 |
| Model format | NVFP4 |
| Main KV cache | BF16 |
| Native MTP depth | 2 |
| KV pool at GPU utilization 0.85 | 692,291 tokens |
| Corrected C1 visible-code decode | 25.9-27.4 tok/s |
| Sustained C4 aggregate decode | 52.89 tok/s |

The C4 number is a throughput stress result. Four uncapped `xhigh` requests
continued for roughly 15 minutes without EOS, OOM, or throughput collapse and
were then disconnected manually.

## PLE CPU affinity

Only the SSD-backed PLE worker is pinned to CPUs `5-9,15-19`; the API server and
engine remain schedulable across all host CPUs. This produced about 6% higher
same-process post-TTFT decode throughput on the validated GX10. The tradeoffs
are concentrated power/thermal load and contention if another CPU-heavy job or
model server uses the same performance cores. Use disjoint core sets for
multiple servers, or set `PLE_CPU_AFFINITY=0-19` to restore unrestricted
scheduling. Invalid or unavailable CPU IDs fail explicitly at worker startup.

## Build a self-contained OCI layout

The release builder first creates a separate publication-stage image and then
streams it into a standalone OCI directory. Every layer is force-compressed
with zstd and verified by digest. The build fails if any compressed layer is
10 GB or larger. The production image and running server are not modified.

```bash
SOURCE_URL=https://github.com/OWNER/REPOSITORY ./build-oci.sh
```

The default output is the directory
`qwen38-flash-next-gb10-arm64.oci/`. Existing layouts are never overwritten
automatically. This avoids changing Docker's daemon or buildx driver settings.

Verify all blob digests, zstd streams, tar payloads, ARM64 metadata, registry
layer limits, and sensitive/model filenames before upload:

```bash
./verify-oci.py ./qwen38-flash-next-gb10-arm64.oci
```

## Push to GHCR

Authenticate outside the scripts so no token enters an image layer or shell
argument:

```bash
export CR_PAT=YOUR_CLASSIC_PAT_WITH_WRITE_PACKAGES
printf '%s' "$CR_PAT" | docker login ghcr.io -u OWNER --password-stdin
unset CR_PAT
```

Install `skopeo` through a vendor- or distro-supported ARM64 path, then copy the
already validated OCI layout to GHCR:

```bash
GHCR_IMAGE=ghcr.io/mmcsssss/qwen38-flash-next-vllm-gb10:2026.08.27 \
./push-ghcr.sh
```

The push helper never installs packages and never accepts a token as a command
line argument. It reuses the authentication created by `docker login`.

The package is private on first publication. Change visibility from the GitHub
package settings only after checking the licenses and release notes.

The layers use the standard OCI zstd media type. Pull with a current container
runtime that supports `application/vnd.oci.image.layer.v1.tar+zstd`.

## Licenses and source

The image contains mixed-license dependencies. vLLM and the included source
patch are Apache-2.0; NVIDIA components remain subject to NVIDIA's bundled
container and component licenses. `NOTICE` includes the NVIDIA source notice.
The exact local source diff is under `patches/`.

This bundle is not a legal opinion. Review the NVIDIA container distribution
terms before making the package public.
