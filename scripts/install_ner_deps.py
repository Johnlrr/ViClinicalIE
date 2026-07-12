"""Install optional Hugging Face NER dependencies for ViClinicalIE.

This helper keeps the core deterministic pipeline dependency-free, while making it
one command to prepare the optional ViHealthBERT/Hugging Face token-classification
backend used by scripts/build_new_arch_outputs.py.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List


CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
CUDA_TORCH_INDEX = "https://download.pytorch.org/whl/cu121"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install optional NER dependencies.")
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
        help="Install PyTorch wheels for CPU or CUDA 12.1. Default: cpu.",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Extra pip package to install; can be repeated.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pip commands without executing them.",
    )
    return parser.parse_args()


def run_command(command: List[str], *, dry_run: bool) -> None:
    print(" ".join(command))
    if dry_run:
        return
    subprocess.check_call(command)


def main() -> int:
    args = parse_args()
    torch_index = CUDA_TORCH_INDEX if args.device == "cuda" else CPU_TORCH_INDEX
    pip = [sys.executable, "-m", "pip"]

    run_command([*pip, "install", "--upgrade", "pip", "setuptools", "wheel"], dry_run=args.dry_run)
    run_command([*pip, "install", "torch", "--index-url", torch_index], dry_run=args.dry_run)
    run_command([*pip, "install", "transformers>=4.40", "accelerate>=0.28", "sentencepiece"], dry_run=args.dry_run)
    if args.extra:
        run_command([*pip, "install", *args.extra], dry_run=args.dry_run)

    print("NER dependencies are ready. Pass a fine-tuned token-classification checkpoint to --ner-model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
