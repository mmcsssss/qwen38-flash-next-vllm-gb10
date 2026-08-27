# Publication artifact

Built and verified on 2026-08-27 for `linux/arm64`.

| Item | Value |
| --- | --- |
| Source image | `sha256:5520b3f65207ce2566d6f792e6de880dba88d85f504cbea99833f43700c5c870` |
| Publication-stage image | `sha256:d477b898ffd1662fca5d46a1e36bd146882c832123752fb402b0614f2b24aaa8` |
| OCI index SHA-256 | `1416ed7fb99608b4555188455584ab45d1089ca8323fed2a6ce2fbc6d3ee5ac4` |
| OCI manifest | `sha256:8c9a7cf4e3fcfac3207cf2ba4f125a093e2cc5269b272c0d0ce826cd0c75f5fb` |
| OCI config | `sha256:db2d9a9e02389836b20886ecbe5bf81c3cd496621be1a24bb86e3d27b9ae1ca9` |
| OCI layout bytes | `8,218,241,823` |
| Layers | `44` |
| Largest compressed layer | `3.935 GB` |
| Files inspected | `137,995` |

`verify-oci.py` independently verified every referenced blob digest and size,
decompressed and parsed every zstd layer, matched every uncompressed layer to
the config's `rootfs.diff_ids`, checked the platform, and enforced a strict
per-layer size limit below 10 GB.

The OCI layout contains the application image but no model snapshot, PLE model
store, prompt cache, runtime log, or registry credential. Model files remain a
separate read-only runtime mount.
