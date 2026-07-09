"""Fill the `candidates` field via retrieve-then-rerank.

For every silver output file:
  1. Collect CHẨN_ĐOÁN (diagnosis) and THUỐC (drug) spans.
  2. Build a numbered shortlist of *real* codes per span using the full-catalog
     retrievers (ICD-10 for diagnoses, RxNorm for drugs).
  3. Make ONE LLM rerank call for the whole file: the model chooses, per span,
     only codes drawn from that span's shortlist (or [] if none fit).
  4. Validate the response against each shortlist (drop anything not present),
     dedupe, and write the chosen codes back into `candidates` from scratch.

The retrievers guarantee every emitted code exists in the source catalog, so a
hallucinating model cannot inject a fake code. Reuses the OpenAI-compatible
`chat_completion` client from build_silver_test.py.

Usage:
    python3 scripts/fill_candidates.py --api-key sk-... --model gpt-4o-mini
    python3 scripts/fill_candidates.py --only 1,2,3 --overwrite
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_silver_test import LLMError, chat_completion, extract_json_array
from src.linking.icd10_catalog import Icd10Catalog
from src.linking.rxnorm_catalog import RxNormCatalog

DIAGNOSIS_TYPE = "CHẨN_ĐOÁN"
DRUG_TYPE = "THUỐC"
MAPPING_TYPES = {DIAGNOSIS_TYPE, DRUG_TYPE}

DEFAULT_BASE_URL = "https://api.shopaikey.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
SHORTLIST_SIZE = 10

SYSTEM_PROMPT = (
    "Bạn là chuyên gia mã hóa y khoa. Nhiệm vụ của bạn là chọn mã chuẩn đúng cho "
    "mỗi khái niệm lâm sàng, CHỈ chọn từ danh sách mã được cung cấp cho khái niệm đó. "
    "Không được bịa mã. Chỉ trả về JSON hợp lệ, không giải thích, không markdown."
)


# --------------------------------------------------------------------------- #
# Shortlist / context helpers                                                 #
# --------------------------------------------------------------------------- #


def _context_sentence(raw_text: str, start: int, end: int, window: int = 120) -> str:
    """Return a trimmed context window around a span for the rerank prompt."""
    if not raw_text or start is None or end is None:
        return ""
    lo = max(0, start - window)
    hi = min(len(raw_text), end + window)
    snippet = raw_text[lo:hi]
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet


def _collect_spans(entities: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    """Return (entity_index, entity) for diagnosis/drug entities in file order."""
    spans: List[Tuple[int, Dict[str, Any]]] = []
    for idx, entity in enumerate(entities):
        if entity.get("type") in MAPPING_TYPES:
            spans.append((idx, entity))
    return spans


def build_shortlists(
    entities: List[Dict[str, Any]],
    raw_text: str,
    icd: Icd10Catalog,
    rxnorm: RxNormCatalog,
    shortlist_size: int = SHORTLIST_SIZE,
) -> List[Dict[str, Any]]:
    """Build a per-span shortlist record for every diagnosis/drug span."""
    records: List[Dict[str, Any]] = []
    for entity_idx, entity in _collect_spans(entities):
        text = str(entity.get("text", "")).strip()
        etype = entity.get("type")
        pos = entity.get("position") or [None, None]
        start, end = (pos + [None, None])[:2]
        if etype == DIAGNOSIS_TYPE:
            options = icd.top_n(text, shortlist_size)
        else:
            options = rxnorm.top_n(text, shortlist_size)
        records.append(
            {
                "entity_index": entity_idx,
                "text": text,
                "type": etype,
                "context": _context_sentence(raw_text, start, end),
                "options": options,  # list of (code, label)
            }
        )
    return records


# --------------------------------------------------------------------------- #
# Prompt / rerank                                                             #
# --------------------------------------------------------------------------- #


def build_rerank_prompt(records: List[Dict[str, Any]]) -> str:
    """Build the single batched rerank user prompt for a file."""
    lines: List[str] = [
        "Dưới đây là các khái niệm lâm sàng cần gán mã chuẩn "
        "(CHẨN_ĐOÁN -> ICD-10, THUỐC -> RxNorm RXCUI).",
        "Với MỖI khái niệm, chọn các mã PHÙ HỢP NHẤT, CHỈ lấy từ danh sách 'Lựa chọn' của chính khái niệm đó.",
        "Thường chỉ nên chọn 1 mã đúng nhất; có thể chọn thêm nếu thực sự phù hợp.",
        "Nếu KHÔNG có lựa chọn nào phù hợp, trả về mảng rỗng [] cho khái niệm đó. TUYỆT ĐỐI không bịa mã.",
        "",
        "Trả về DUY NHẤT một JSON object ánh xạ chỉ số khái niệm (dạng chuỗi) -> mảng mã đã chọn, ví dụ:",
        '{"0": ["I10"], "1": [], "2": ["308135"]}',
        "",
        "Danh sách khái niệm:",
    ]
    for i, rec in enumerate(records):
        label = "CHẨN_ĐOÁN" if rec["type"] == DIAGNOSIS_TYPE else "THUỐC"
        lines.append("")
        lines.append(f"[{i}] ({label}) văn bản: {rec['text']!r}")
        if rec["context"]:
            lines.append(f"    ngữ cảnh: {rec['context']}")
        if rec["options"]:
            lines.append("    Lựa chọn:")
            for code, opt_label in rec["options"]:
                lines.append(f"      - {code} — {opt_label}")
        else:
            lines.append("    Lựa chọn: (không có) -> phải trả về []")
    return "\n".join(lines)


def _parse_rerank_response(content: str, num_records: int) -> Dict[int, List[str]]:
    """Parse the model response into {record_index: [codes]}.

    Accepts either a JSON object keyed by index, or a JSON array of objects
    with {"index"/"id", "codes"/"candidates"} shapes.
    """
    mapping: Dict[int, List[str]] = {}

    def _coerce_codes(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            if isinstance(item, (str, int, float)):
                code = str(item).strip()
                if code:
                    out.append(code)
        return out

    parsed: Any = None
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        # Fall back to grabbing the first {...} object.
        start = content.find("{") if isinstance(content, str) else -1
        end = content.rfind("}") if isinstance(content, str) else -1
        if start != -1 and end > start:
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                parsed = None

    if isinstance(parsed, dict):
        for key, value in parsed.items():
            try:
                idx = int(str(key).strip())
            except (TypeError, ValueError):
                continue
            if 0 <= idx < num_records:
                mapping[idx] = _coerce_codes(value)
    elif isinstance(parsed, list):
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            raw_idx = entry.get("index", entry.get("id"))
            try:
                idx = int(str(raw_idx).strip())
            except (TypeError, ValueError):
                continue
            codes = entry.get("codes", entry.get("candidates"))
            if 0 <= idx < num_records:
                mapping[idx] = _coerce_codes(codes)

    return mapping


def validate_choices(
    records: List[Dict[str, Any]],
    chosen: Dict[int, List[str]],
) -> Dict[int, List[str]]:
    """Keep only codes present in each record's shortlist; dedupe; default []."""
    result: Dict[int, List[str]] = {}
    for i, rec in enumerate(records):
        allowed = {code for code, _ in rec["options"]}
        picked = chosen.get(i, [])
        clean: List[str] = []
        seen: set[str] = set()
        for code in picked:
            if code in allowed and code not in seen:
                seen.add(code)
                clean.append(code)
        result[i] = clean
    return result


# --------------------------------------------------------------------------- #
# Per-file worker                                                             #
# --------------------------------------------------------------------------- #


def process_file(
    out_path: Path,
    input_dir: Path,
    icd: Icd10Catalog,
    rxnorm: RxNormCatalog,
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    timeout: int,
    max_retries: int,
    max_tokens: Optional[int],
    stream: bool,
    shortlist_size: int,
) -> Dict[str, Any]:
    """Fill candidates for one silver output file."""
    file_id = out_path.stem
    result: Dict[str, Any] = {
        "file_id": file_id,
        "status": "ok",
        "spans": 0,
        "diagnosis_spans": 0,
        "drug_spans": 0,
        "codes_filled": 0,
        "error": None,
    }

    try:
        entities = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["status"] = "error"
        result["error"] = f"read/parse output: {exc}"
        return result
    if not isinstance(entities, list):
        result["status"] = "error"
        result["error"] = "output file is not a JSON array"
        return result

    raw_path = input_dir / f"{file_id}.txt"
    raw_text = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""

    records = build_shortlists(entities, raw_text, icd, rxnorm, shortlist_size)
    result["spans"] = len(records)
    result["diagnosis_spans"] = sum(1 for r in records if r["type"] == DIAGNOSIS_TYPE)
    result["drug_spans"] = sum(1 for r in records if r["type"] == DRUG_TYPE)

    # Re-fill from scratch: clear any previously emitted codes on mapping spans.
    for entity in entities:
        if entity.get("type") in MAPPING_TYPES:
            entity["candidates"] = []

    if not records:
        _write_entities(out_path, entities)
        return result

    prompt = build_rerank_prompt(records)
    try:
        content = chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system=SYSTEM_PROMPT,
            user=prompt,
            temperature=temperature,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            stream=stream,
        )
    except LLMError as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        # Still persist the cleared candidates so the file stays schema-valid.
        _write_entities(out_path, entities)
        return result

    chosen = _parse_rerank_response(content, len(records))
    validated = validate_choices(records, chosen)

    codes_filled = 0
    for i, rec in enumerate(records):
        codes = validated.get(i, [])
        entities[rec["entity_index"]]["candidates"] = codes
        codes_filled += len(codes)
    result["codes_filled"] = codes_filled

    _write_entities(out_path, entities)
    return result


def _write_entities(out_path: Path, entities: List[Dict[str, Any]]) -> None:
    """Persist entities preserving the silver JSON formatting conventions."""
    out_path.write_text(
        json.dumps(entities, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill the candidates field in silver outputs via retrieve-then-rerank.",
    )
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--input-dir", type=Path, default=ROOT / "input")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "silver_test" / "output")
    parser.add_argument("--resource-dir", type=Path, default=ROOT / "data_resources")
    parser.add_argument("--only", default="", help="Comma-separated file_ids, e.g. '1,2,7'.")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N files (0 = all).")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=1500, help="0 to disable.")
    parser.add_argument("--shortlist-size", type=int, default=SHORTLIST_SIZE)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Refill even files that already have non-empty candidates.",
    )
    return parser.parse_args(argv)


def select_output_files(output_dir: Path, only: str, limit: int) -> List[Path]:
    files = sorted(
        output_dir.glob("*.json"),
        key=lambda p: (int(p.stem) if p.stem.isdigit() else float("inf"), p.stem),
    )
    if only.strip():
        wanted = {tok.strip() for tok in only.split(",") if tok.strip()}
        files = [p for p in files if p.stem in wanted]
    if limit and limit > 0:
        files = files[:limit]
    return files


def _has_filled_candidates(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, list):
        return False
    return any(
        e.get("type") in MAPPING_TYPES and e.get("candidates")
        for e in data
        if isinstance(e, dict)
    )


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> int:
    configure_stdout()
    args = parse_args(argv)

    if not args.api_key:
        print("ERROR: no API key. Pass --api-key or set OPENAI_API_KEY.", file=sys.stderr)
        return 2

    output_dir: Path = args.output_dir
    if not output_dir.exists():
        print(f"ERROR: output dir not found: {output_dir}", file=sys.stderr)
        return 2

    files = select_output_files(output_dir, args.only, args.limit)
    if not args.overwrite:
        files = [p for p in files if not _has_filled_candidates(p)]
    if not files:
        print("No files to process (all already filled? use --overwrite).")
        return 0

    print("=" * 70)
    print("Candidate filler (retrieve-then-rerank)")
    print("=" * 70)
    print(f"base_url   : {args.base_url}")
    print(f"model      : {args.model}")
    print(f"output_dir : {output_dir}")
    print(f"files      : {len(files)}")
    print("Loading catalogs (ICD-10 + RxNorm)...")

    icd = Icd10Catalog.from_csv(args.resource_dir / "icd10_byt_source.csv")
    rxnorm = RxNormCatalog.from_rrf(args.resource_dir / "RXNCONSO.RRF")
    print(f"  ICD entries   : {len(icd.entries)}")
    print(f"  RxNorm entries: {len(rxnorm.entries)}")
    print("=" * 70)

    max_tokens_arg: Optional[int] = args.max_tokens if args.max_tokens and args.max_tokens > 0 else None
    stream_arg = not args.no_stream

    def _run(path: Path) -> Dict[str, Any]:
        return process_file(
            path,
            args.input_dir,
            icd,
            rxnorm,
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            temperature=args.temperature,
            timeout=args.timeout,
            max_retries=args.max_retries,
            max_tokens=max_tokens_arg,
            stream=stream_arg,
            shortlist_size=args.shortlist_size,
        )

    results: List[Dict[str, Any]] = []
    total = len(files)
    concurrency = max(1, args.concurrency)
    if concurrency == 1:
        for idx, path in enumerate(files, 1):
            res = _run(path)
            results.append(res)
            _report(idx, total, res)
    else:
        with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
            future_to_path = {pool.submit(_run, path): path for path in files}
            for idx, future in enumerate(cf.as_completed(future_to_path), 1):
                path = future_to_path[future]
                try:
                    res = future.result()
                except Exception as exc:  # noqa: BLE001
                    res = {
                        "file_id": path.stem,
                        "status": "error",
                        "spans": 0,
                        "diagnosis_spans": 0,
                        "drug_spans": 0,
                        "codes_filled": 0,
                        "error": repr(exc),
                    }
                results.append(res)
                _report(idx, total, res)

    manifest_path = output_dir.parent / "candidate_manifest.json"
    manifest = {
        "base_url": args.base_url,
        "model": args.model,
        "output_dir": str(output_dir),
        "shortlist_size": args.shortlist_size,
        "files": sorted(
            results,
            key=lambda r: (int(r["file_id"]) if r["file_id"].isdigit() else 1 << 30, r["file_id"]),
        ),
        "totals": {
            "files": total,
            "ok": sum(1 for r in results if r["status"] == "ok"),
            "errors": sum(1 for r in results if r["status"] == "error"),
            "spans": sum(r["spans"] for r in results),
            "diagnosis_spans": sum(r["diagnosis_spans"] for r in results),
            "drug_spans": sum(r["drug_spans"] for r in results),
            "codes_filled": sum(r["codes_filled"] for r in results),
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print("=" * 70)
    print(f"Manifest: {manifest_path}")
    print(f"Totals  : {manifest['totals']}")
    return 0 if manifest["totals"]["errors"] == 0 else 1


def _report(idx: int, total: int, res: Dict[str, Any]) -> None:
    tag = res["status"].upper()
    err = f" | {res['error']}" if res.get("error") else ""
    print(
        f"[{idx:>3}/{total}] {res['file_id']:>4}  {tag:<6} "
        f"spans={res['spans']:>2} (dx={res['diagnosis_spans']} rx={res['drug_spans']}) "
        f"codes={res['codes_filled']:>3}{err}"
    )


if __name__ == "__main__":
    sys.exit(main())
