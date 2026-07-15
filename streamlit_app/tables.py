from __future__ import annotations

from typing import Any

import pandas as pd


def flatten_error_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        pred = row.get("pred", {}) if isinstance(row.get("pred"), dict) else {}
        gold = row.get("gold", {}) if isinstance(row.get("gold"), dict) else {}
        context = row.get("context", {}) if isinstance(row.get("context"), dict) else {}
        output.append(
            {
                "row": idx,
                "file_id": row.get("file_id") or pred.get("file_id") or gold.get("file_id") or "",
                "category": row.get("category") or row.get("match_kind") or "",
                "subcategory": row.get("subcategory", ""),
                "pred_text": pred.get("text", ""),
                "pred_type": pred.get("type", ""),
                "pred_position": _position_to_string(pred.get("position")),
                "gold_text": gold.get("text", ""),
                "gold_type": gold.get("type", ""),
                "gold_position": _position_to_string(gold.get("position")),
                "span_iou": row.get("span_iou", ""),
                "containment_ratio": row.get("containment_ratio", ""),
                "context": context.get("text", ""),
            }
        )
    return pd.DataFrame(output)


def filter_error_frame(
    frame: pd.DataFrame,
    *,
    file_id: str | None = None,
    entity_type: str | None = None,
    text_query: str = "",
    subcategory: str | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    filtered = frame.copy()
    if file_id and file_id != "All":
        filtered = filtered[filtered["file_id"].astype(str) == str(file_id)]
    if entity_type and entity_type != "All":
        mask = (filtered["pred_type"].astype(str) == entity_type) | (filtered["gold_type"].astype(str) == entity_type)
        filtered = filtered[mask]
    if subcategory and subcategory != "All" and "subcategory" in filtered:
        filtered = filtered[filtered["subcategory"].astype(str) == subcategory]
    if text_query.strip():
        query = text_query.strip().lower()
        haystack = (
            filtered["pred_text"].astype(str).str.lower()
            + " "
            + filtered["gold_text"].astype(str).str.lower()
            + " "
            + filtered["context"].astype(str).str.lower()
        )
        filtered = filtered[haystack.str.contains(query, regex=False, na=False)]
    return filtered


def compare_entity_rows(gold_records: list[dict[str, Any]], pred_records: list[dict[str, Any]]) -> pd.DataFrame:
    gold_keys = {_record_key(record) for record in gold_records}
    pred_keys = {_record_key(record) for record in pred_records}
    rows: list[dict[str, Any]] = []
    for source, records in (("gold", gold_records), ("prediction", pred_records)):
        other_keys = pred_keys if source == "gold" else gold_keys
        for idx, record in enumerate(records):
            key = _record_key(record)
            rows.append(
                {
                    "source": source,
                    "index": idx,
                    "status": "exact_match" if key in other_keys else "unmatched",
                    "text": record.get("text", ""),
                    "position": _position_to_string(record.get("position")),
                    "type": record.get("type", ""),
                    "assertions": ", ".join(str(item) for item in record.get("assertions", []) or []),
                    "candidates": ", ".join(str(item) for item in record.get("candidates", []) or []),
                }
            )
    return pd.DataFrame(rows)


def _record_key(record: dict[str, Any]) -> tuple[Any, Any, Any]:
    position = record.get("position", [None, None])
    if not isinstance(position, list | tuple) or len(position) < 2:
        position = [None, None]
    return (position[0], position[1], record.get("type"))


def _position_to_string(position: Any) -> str:
    if isinstance(position, list | tuple) and len(position) >= 2:
        return f"{position[0]}:{position[1]}"
    return ""
