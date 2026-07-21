from __future__ import annotations

import argparse
import os

# Set transfer policy before importing huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from huggingface_hub import snapshot_download


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the GLiNER checkpoint with conservative Windows-safe downloads.")
    parser.add_argument("--model", default="urchade/gliner_multi-v2.1")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--tokenizer-only", action="store_true", help="Download config/tokenizer assets but not base-model weights.")
    args = parser.parse_args()
    allow_patterns = None
    if args.tokenizer_only:
        allow_patterns = [
            "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
            "spm.model", "sentencepiece.bpe.model", "vocab.json", "merges.txt", "added_tokens.json",
        ]
    path = snapshot_download(
        repo_id=args.model,
        revision=args.revision,
        max_workers=args.max_workers,
        resume_download=True,
        allow_patterns=allow_patterns,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())