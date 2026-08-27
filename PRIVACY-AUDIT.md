# Container privacy audit

Audited image:
`sha256:5520b3f65207ce2566d6f792e6de880dba88d85f504cbea99833f43700c5c870`

The merged filesystem, image configuration, build history, and every raw image
layer were scanned on 2026-08-27. No model weights are embedded.

The final publication OCI layout was independently checked after zstd
recompression. All 44 blobs passed digest and tar-stream verification, and
137,995 filesystem entries were inspected. The only `.safetensors` payload is
the 1.44 MB Hadamard transform constant shipped by the `compressed_tensors`
Python package; it is not a language-model weight.

No matches were found for:

- known Linux and Windows user-home paths
- known LAN addresses or the local host identity
- GitHub token formats
- Google, Slack, or Stripe credential formats
- credential-bearing files such as SSH private keys, `.netrc`, Docker auth,
  Git credentials, Hugging Face token files, or shell history

Apparent HF, OpenAI, AWS, URI credential, and private-key-marker matches were
mapped back to package binaries, parser constants, and SDK example files. No
runtime credential files or user-provided values were present. Examples include
`botocore` documentation fixtures, cryptography marker constants, and binary
symbol/hash substrings.

Residual limitation: pattern scanning cannot mathematically prove the absence
of every possible secret format. Publication should still use a fresh GHCR
credential supplied only through `docker login --password-stdin`.

The public source-provenance label intentionally contains the GitHub repository
URL. It is required for package-to-repository association and is not a secret.
