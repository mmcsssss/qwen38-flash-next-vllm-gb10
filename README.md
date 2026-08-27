# Qwen3.8 Flash Next vLLM for DGX Spark

This is the publication bundle for the validated ARM64 image
`local/vllm-qwen38-next:ssd-ple-gb10-decode-f561`. It targets NVIDIA DGX
Spark / ASUS Ascent GX10 and keeps the local production image unchanged.

## Container image

GHCR image: `ghcr.io/mmcsssss/qwen38-flash-next-vllm-gb10:2026.08.27`

```bash
docker pull ghcr.io/mmcsssss/qwen38-flash-next-vllm-gb10:2026.08.27
```

For a reproducible deployment, pin the immutable digest:

```bash
docker pull ghcr.io/mmcsssss/qwen38-flash-next-vllm-gb10@sha256:8c9a7cf4e3fcfac3207cf2ba4f125a093e2cc5269b272c0d0ce826cd0c75f5fb
```

The package is currently private, so authenticate with `docker login ghcr.io`
before pulling it. Model weights are not included in the container.

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
| Observed KV pool at GPU utilization 0.85 | 692,291-721,258 tokens |
| Cold 100K effective prefill | 1,664 tok/s (100,086 tokens / 60.15 s TTFT) |
| Short-run C1 raw output decode | 34.4-37.2 tok/s |
| Corrected C1 visible-code decode | 25.9-27.4 tok/s |
| Sustained C4 aggregate decode | 52.89 tok/s |

The roughly 35 tok/s C1 result is a best-case, short-run rate calculated from
all generated output tokens after TTFT. The 25.9-27.4 tok/s range is the more
conservative sustained result after re-tokenizing only the code visible to the
client. It excludes hidden, special, and protocol overhead, so it is the better
number for estimating real code-generation speed. Throughput remains dependent
on prompt shape, MTP acceptance, context length, and thermals.

The C4 number is a throughput stress result. Four uncapped `xhigh` requests
continued for roughly 15 minutes without EOS, OOM, or throughput collapse and
were then disconnected manually.

## Vision validation

High-detail image input was exercised end to end through both the Responses and
Chat Completions APIs. A 10 MiB desktop screenshot completed through Responses
with correct OCR of `ASUS Ascent GX10 AI Supercomputer`, the displayed date and
time, desktop filenames, and correct identification of the GX10 and robot hand.

The configured image-count boundary was also tested through Responses. A
16-image request completed with HTTP 200 and 40,726 input tokens; a 17-image
request was rejected with the expected `At most 16 image(s)` HTTP 400 response.
These checks validate the multimodal transport, encoder, and admission limit,
not byte-perfect OCR or counting accuracy. The repeated-image stress request
counted 16 identical screenshots as 15, and one Chat Completions OCR run added
one character to a GitHub owner name.

## SSD-backed Engram/PLE

The large Engram/PLE table stays in the model snapshot on SSD instead of being
fully materialized in system memory. The implementation maps the safetensors
files read-only, gathers only the requested rows, and drops those mapped pages
from the page cache after lookup when `VLLM_PLE_SSD_DROP_CACHE=1` is enabled.
The model snapshot itself is also mounted read-only in the validated launcher.

Inference is therefore read-dominant: it does not rewrite the PLE weights or
maintain a model-sized write-back cache while decoding. Normal logs, container
metadata, and unrelated OS activity can still write small amounts, so this is
not a claim of literally zero SSD writes. It does avoid sustained model-sized
writes and should not materially consume SSD write endurance during inference.

## MTP depth

MTP depth is a runtime choice rather than an image build-time constant. The
validated default is 2, but vLLM accepts any positive integer through
`num_speculative_tokens`; omit the speculative configuration to disable MTP.
The companion launcher represents the same choice as `MTP_TOKENS=N`, with
`MTP_TOKENS=0` disabling speculative decoding.

```bash
# Validated default
--speculative-config '{"method":"mtp","num_speculative_tokens":2,"attention_backend":"FLASHINFER"}'

# Example: depth 3
--speculative-config '{"method":"mtp","num_speculative_tokens":3,"attention_backend":"FLASHINFER"}'
```

Only depths 0-3 were benchmarked on the GX10. This checkpoint has one native
predictor layer that vLLM reuses for additional draft positions, so larger
values are syntactically allowed but are not automatically faster. Benchmark
acceptance, latency, and memory before using a higher value; depth 2 remains
the recommended default for this image.

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
