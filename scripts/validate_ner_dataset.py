from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.io_utils import write_json
from src.ner.data_validator import validate_ner_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the shared Phase-1 NER JSONL contract.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    report = validate_ner_jsonl(args.input)
    if args.report:
        write_json(args.report, report.to_dict())
    print(f"samples: {report.samples}")
    print(f"entities: {report.entities}")
    print(f"errors: {len(report.errors)}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())