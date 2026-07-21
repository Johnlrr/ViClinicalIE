from __future__ import annotations

import argparse
import json
import sys

from gliner import GLiNER


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Load a real GLiNER checkpoint and run one smoke prediction.")
    parser.add_argument("--model", default="urchade/gliner_multi-v2.1")
    parser.add_argument("--threshold", type=float, default=0.35)
    args = parser.parse_args()
    model = GLiNER.from_pretrained(args.model)
    text = "Bệnh nhân đau ngực và dùng aspirin."
    predictions = model.predict_entities(text, ["symptom", "medication or drug"], threshold=args.threshold)
    print(json.dumps(predictions, ensure_ascii=False))
    if not isinstance(predictions, list):
        raise RuntimeError("GLiNER smoke output is not a list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())