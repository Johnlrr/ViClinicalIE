from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.official_like_scorer import match_concepts, score_corpus
from src.io_utils import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Run diagnostic span/type oracle transformations.")
    parser.add_argument("--pred-dir", required=True)
    parser.add_argument("--gold-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    gold_dir, pred_dir = Path(args.gold_dir), Path(args.pred_dir)
    stems = [path.stem for path in sorted(gold_dir.glob("*.json"), key=lambda item: int(item.stem))]
    golds = {stem: read_json(gold_dir / f"{stem}.json") for stem in stems}
    preds = {stem: read_json(pred_dir / f"{stem}.json") for stem in stems}
    span_oracle = {stem: _oracle_span(preds[stem], golds[stem]) for stem in stems}
    type_oracle = {stem: _oracle_type(preds[stem], golds[stem]) for stem in stems}
    write_json(args.output, {
        "baseline": score_corpus(preds, golds, stems=stems).to_dict(),
        "oracle_span": score_corpus(span_oracle, golds, stems=stems).to_dict(),
        "oracle_type": score_corpus(type_oracle, golds, stems=stems).to_dict(),
        "warning": "Diagnostic ceiling under documented greedy-overlap assumptions; not a production component.",
    })
    return 0


def _oracle_span(pred, gold):
    output = [dict(record) for record in pred]
    for pred_index, gold_index in match_concepts(pred, gold).items():
        output[pred_index]["text"] = gold[gold_index]["text"]
        output[pred_index]["position"] = list(gold[gold_index]["position"])
    return output


def _oracle_type(pred, gold):
    output = [dict(record) for record in pred]
    pairs = []
    for pred_index, pred_record in enumerate(pred):
        ps, pe = pred_record["position"]
        for gold_index, gold_record in enumerate(gold):
            gs, ge = gold_record["position"]
            overlap = max(0, min(pe, ge) - max(ps, gs))
            if overlap:
                pairs.append((-overlap, pred_index, gold_index))
    used_pred, used_gold = set(), set()
    for _, pred_index, gold_index in sorted(pairs):
        if pred_index in used_pred or gold_index in used_gold:
            continue
        used_pred.add(pred_index); used_gold.add(gold_index)
        output[pred_index]["type"] = gold[gold_index]["type"]
        if gold[gold_index]["type"] not in {"CHẨN_ĐOÁN", "THUỐC"}:
            output[pred_index].pop("candidates", None)
    return output


if __name__ == "__main__":
    raise SystemExit(main())