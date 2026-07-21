from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.official_like_scorer import score_directories
from src.io_utils import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the documented local, non-official Task 2 scorer profile.")
    parser.add_argument("--pred-dir", required=True)
    parser.add_argument("--gold-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    score = score_directories(args.pred_dir, args.gold_dir)
    write_json(args.output, score.to_dict())
    print(f"text_score: {score.text_score:.6f}")
    print(f"assertions_score: {score.assertions_score:.6f}")
    print(f"candidates_score: {score.candidates_score:.6f}")
    print(f"final_score: {score.final_score:.6f}")
    print("warning: this is an official-like local profile, not the organizer grader")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())