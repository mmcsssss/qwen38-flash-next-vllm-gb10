ARG BASE_IMAGE=local/vllm-qwen38-next:ssd-ple-gb10-decode-f561
FROM ${BASE_IMAGE}

ARG SOURCE_URL=https://github.com/mmcsssss/qwen38-flash-next-vllm-gb10
ARG VERSION=2026.08.27-gb10
ARG REVISION=f561eca6ca4f3f79808a696b1521cb76dc8aafa2
ARG CREATED

LABEL org.opencontainers.image.title="vLLM Qwen3.8 Flash Next for DGX Spark"
LABEL org.opencontainers.image.description="ARM64 CUDA 13 vLLM image with NVFP4, SSD-backed PLE, native MTP, and GX10 decode tuning. Model weights are not included."
LABEL org.opencontainers.image.source="${SOURCE_URL}"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.revision="${REVISION}"
LABEL org.opencontainers.image.created="${CREATED}"

COPY NOTICE /usr/share/doc/qwen38-flash-next-gb10/NOTICE
COPY licenses/ /usr/share/doc/qwen38-flash-next-gb10/licenses/
COPY patches/ /usr/share/doc/qwen38-flash-next-gb10/patches/
