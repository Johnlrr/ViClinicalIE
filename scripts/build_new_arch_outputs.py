"""Build outputs for the new architecture.

New architecture composition:
  1. optional ViHealthBERT/Hugging Face NER semantic seeds
  2. specialized Drug parser using dictionary/RxNorm/NER seeds
  3. specialized Lab parser using curated dictionary/NER seeds
  4. dictionary/rule modules for diagnosis, symptoms, structural fallback
  5. assertion, merge, ICD/RxNorm linking, schema validation

The script can run without NER by omitting --ner-model. In that mode it still
exercises Drug parser + Lab parser + Dictionary/Rules modules and writes outputs
that can be compared with the old V0/V0-linked outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.assertion import add_assertions
from src.drug_parser import parse_drug_candidates
from src.io_utils import load_input_files
from src.lab_parser import load_lab_dictionary, parse_lab_candidates
from src.linking.candidate_linker import link_mapping_candidates, load_default_linkers
from src.merge import merge_candidates
from src.models import ClinicalDocument, SpanCandidate
from src.output_writer import create_output_zip, write_output_files
from src.rule_extractors import (
    ENTITY_DIAGNOSIS,
    ENTITY_DRUG,
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    ENTITY_SYMPTOM,
    TARGET_ENTITY_TYPES,
    dedupe_candidates,
    extract_diagnosis_candidates,
    extract_structural_candidates,
    extract_symptom_candidates,
    extraction_summary,
    read_term_csv,
    reject_non_target_candidates,
    validate_candidate_offsets,
    write_span_candidates_jsonl,
)
from src.section_parser import parse_documents
from src.validator import validate_output_artifacts, write_validation_report
from src.vihealthbert_ner import VIETMED_DEFAULT_THRESHOLDS, FastTokenizerRequiredError, HuggingFaceTokenPredictor, ViHealthBERTNER


LAB_TYPES = {ENTITY_LAB_NAME, ENTITY_LAB_RESULT}
MAPPING_TYPES = {ENTITY_DIAGNOSIS, ENTITY_DRUG}


def configure_stdout() -> None:
    """Make Vietnamese output safe on Windows consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def display_path(path: Path) -> str:
    """Return a readable path without failing for relative CLI paths."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def load_resources(resource_dir: Path) -> dict[str, list[str]]:
    """Load seed dictionaries used by the active hybrid architecture."""
    return {
        "lab_terms": read_term_csv(str(resource_dir / "lab_seed_terms.csv")),
        "drug_terms": read_term_csv(str(resource_dir / "drug_aliases.csv")),
        "drug_context_terms": read_term_csv(str(resource_dir / "drug_context_terms.csv")),
        "diagnosis_terms": read_term_csv(str(resource_dir / "diagnosis_seed_terms.csv")),
        "symptom_terms": read_term_csv(str(resource_dir / "symptom_seed_terms.csv")),
        "non_target_terms": read_term_csv(str(resource_dir / "non_target_medical_terms.csv")),
    }


def select_documents(documents: Sequence[ClinicalDocument], only: str | None, limit: int | None) -> list[ClinicalDocument]:
    """Select documents by explicit ids or first-N numeric order."""
    ordered = sorted(documents, key=lambda doc: int(doc.file_id) if doc.file_id.isdigit() else 1 << 30)
    if only:
        requested = {item.strip() for item in only.split(",") if item.strip()}
        ordered = [doc for doc in ordered if doc.file_id in requested]
    if limit is not None:
        ordered = ordered[:limit]
    return ordered


def write_csv(path: Path, rows: Sequence[dict], fieldnames: Sequence[str]) -> None:
    """Write UTF-8 CSV debug artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def mapping_summary(candidates: Iterable[SpanCandidate], debug_rows: Sequence[dict]) -> dict:
    """Build mapping coverage summary."""
    mappable = [candidate for candidate in candidates if candidate.type_candidate in MAPPING_TYPES]
    mapped = [candidate for candidate in mappable if candidate.mapping_candidates]
    by_type = Counter(candidate.type_candidate for candidate in mappable)
    mapped_by_type = Counter(candidate.type_candidate for candidate in mapped)
    source_counts = Counter(row["source"] for row in debug_rows)
    unmapped_rows = [row for row in debug_rows if not row["codes"]]
    unmapped_counter = Counter((row["type"], row["text"].lower(), row["reason"]) for row in unmapped_rows)

    coverage = {}
    for entity_type, total in by_type.items():
        coverage[entity_type] = (mapped_by_type[entity_type] / total) if total else 1.0

    return {
        "total_mappable": len(mappable),
        "total_mapped": len(mapped),
        "by_type": dict(by_type),
        "mapped_by_type": dict(mapped_by_type),
        "coverage": coverage,
        "source_counts": dict(source_counts),
        "unmapped_count": len(unmapped_rows),
        "top_unmapped": [
            {
                "type": entity_type,
                "text": text,
                "reason": reason,
                "count": count,
            }
            for (entity_type, text, reason), count in unmapped_counter.most_common(50)
        ],
    }


def write_mapping_report(summary: dict, validation_ok: bool, path: Path) -> None:
    """Write Markdown mapping coverage report for active architecture output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Mapping Coverage New Architecture",
        "",
        f"Validation: {'PASS' if validation_ok else 'FAIL'}",
        f"Total mappable diagnosis/drug spans: {summary['total_mappable']}",
        f"Mapped spans: {summary['total_mapped']}",
        f"Unmapped spans: {summary['unmapped_count']}",
        "",
        "## Coverage",
        "",
    ]
    for entity_type, total in summary["by_type"].items():
        mapped = summary["mapped_by_type"].get(entity_type, 0)
        coverage = summary["coverage"].get(entity_type, 0.0)
        lines.append(f"- {entity_type}: {mapped}/{total} ({coverage:.1%})")

    lines.extend(["", "## Mapping Sources", ""])
    for source, count in sorted(summary["source_counts"].items()):
        lines.append(f"- {source}: {count}")

    lines.extend(["", "## Top Unmapped", ""])
    if summary["top_unmapped"]:
        for row in summary["top_unmapped"][:30]:
            lines.append(f"- {row['count']} x {row['type']} | {row['text']} | {row['reason']}")
    else:
        lines.append("- None")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_threshold(value: str) -> Tuple[str, float]:
    """Parse ENTITY_TYPE=FLOAT threshold CLI values."""
    if "=" not in value:
        raise argparse.ArgumentTypeError("threshold must be ENTITY_TYPE=FLOAT")
    entity_type, raw_score = value.split("=", 1)
    entity_type = entity_type.strip()
    if entity_type not in TARGET_ENTITY_TYPES:
        raise argparse.ArgumentTypeError(f"unknown entity type: {entity_type}")
    try:
        score = float(raw_score)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid threshold score: {raw_score}") from exc
    if not 0.0 <= score <= 1.0:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 1")
    return entity_type, score


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ViClinicalIE new-architecture outputs.")
    parser.add_argument("--input-dir", type=Path, default=ROOT / "input", help="Input *.txt directory.")
    parser.add_argument("--outputs-dir", type=Path, default=ROOT / "outputs" / "new_arch", help="Output artifact directory.")
    parser.add_argument("--analysis-dir", type=Path, default=ROOT / "analysis", help="Analysis artifact directory.")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "reports", help="Report artifact directory.")
    parser.add_argument("--resource-dir", type=Path, default=ROOT / "data_resources", help="Dictionary/linker resource directory.")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N input files by numeric file id.")
    parser.add_argument("--only", default=None, help="Comma-separated input file ids to process, e.g. 1,2,3.")
    parser.add_argument("--ner-model", default=None, help="Hugging Face model id or local checkpoint for token classification.")
    parser.add_argument("--ner-device", default=None, help="NER device override, e.g. cpu, cuda, cuda:0. Default auto-detects.")
    parser.add_argument("--ner-max-length", type=int, default=512, help="NER tokenizer max_length.")
    parser.add_argument(
        "--ner-strict",
        action="store_true",
        help="Fail the run if the NER backend cannot be initialized. By default, NER init failures are reported and the pipeline continues without NER seeds.",
    )
    parser.add_argument(
        "--ner-threshold",
        action="append",
        type=parse_threshold,
        default=[],
        help="Per-type NER confidence threshold, e.g. --ner-threshold THUỐC=0.75. Can be repeated.",
    )
    parser.add_argument("--skip-ner", action="store_true", help="Force-disable NER even when --ner-model is provided.")
    parser.add_argument(
        "--ner-label-map",
        default="compact",
        choices=["compact", "vietmed"],
        help=(
            "How to interpret checkpoint label space. 'compact' (default) assumes the "
            "checkpoint emits the project's submission BIO labels. 'vietmed' enables the "
            "VietMed adapter for checkpoints like leduckhai/VietMed-NER: raw labels are "
            "mapped to submission types, DISEASESYMTOM is routed by section context, and "
            "per-type thresholds default to conservative VietMed values (THUỐC=0.75, "
            "TÊN_XÉT_NGHIỆM=0.70, KẾT_QUẢ_XÉT_NGHIỆM=0.80, CHẨN_ĐOÁN/TRIỆU_CHỨNG=0.80)."
        ),
    )
    return parser.parse_args()


def run_ner(
    documents: Sequence[ClinicalDocument],
    *,
    model_name_or_path: Optional[str],
    device: Optional[str],
    max_length: int,
    thresholds: dict[str, float],
    skip_ner: bool,
    strict: bool = False,
    label_map: str = "compact",
) -> List[SpanCandidate]:
    """Run optional NER and return raw semantic seed candidates.

    ``label_map`` selects between the project's compact BIO label space
    (``"compact"``; default) and the VietMed adapter (``"vietmed"``). In
    ``vietmed`` mode the raw checkpoint labels are mapped to submission types
    and any per-type thresholds not supplied by the caller are filled with
    the conservative defaults from :data:`VIETMED_DEFAULT_THRESHOLDS`. Section
    context (``document.lines``) is passed through :meth:`predict_document` so
    the ambiguous ``DISEASESYMTOM`` span can be routed to ``CHẨN_ĐOÁN`` or
    ``TRIỆU_CHỨNG`` by the adapter.
    """
    if skip_ner or not model_name_or_path:
        print("NER disabled: running parser + dictionary/rules only.")
        return []

    if label_map not in {"compact", "vietmed"}:
        raise ValueError(f"unknown NER label_map: {label_map!r}")

    effective_thresholds = dict(thresholds)
    if label_map == "vietmed":
        for entity_type, default_score in VIETMED_DEFAULT_THRESHOLDS.items():
            effective_thresholds.setdefault(entity_type, default_score)

    try:
        predictor = HuggingFaceTokenPredictor(
            model_name_or_path,
            device=device,
            max_length=max_length,
            label_map=label_map,
        )
    except FastTokenizerRequiredError as error:
        if strict:
            raise
        print(f"NER disabled: {error}")
        return []
    except Exception as error:
        if strict:
            raise
        print(f"NER disabled: could not initialize Hugging Face backend ({type(error).__name__}: {error})")
        return []
    ner = ViHealthBERTNER(predictor, thresholds=effective_thresholds, label_map=label_map)
    candidates: List[SpanCandidate] = []
    for doc in documents:
        doc_candidates = ner.predict_document(doc)
        candidates.extend(doc_candidates)
        print(f"NER {doc.file_id}: {len(doc_candidates)} candidates")
    return candidates


def candidates_for_type(candidates: Iterable[SpanCandidate], entity_types: set[str]) -> List[SpanCandidate]:
    """Filter candidates by entity type."""
    return [candidate for candidate in candidates if candidate.type_candidate in entity_types]


def run_new_arch_extraction(
    documents: Sequence[ClinicalDocument],
    *,
    resource_dir: Path,
    ner_candidates: Sequence[SpanCandidate],
) -> tuple[List[SpanCandidate], dict]:
    """Run parser + dictionary/rule extraction before assertions/merge/linking."""
    resources = load_resources(resource_dir)
    lab_entries = load_lab_dictionary(str(resource_dir / "lab_terms_curated.csv"))
    documents_by_id = {doc.file_id: doc for doc in documents}
    icd_linker, rxnorm_linker = load_default_linkers(resource_dir)

    ner_by_file: dict[str, List[SpanCandidate]] = {}
    for candidate in ner_candidates:
        ner_by_file.setdefault(candidate.file_id, []).append(candidate)

    all_candidates: List[SpanCandidate] = []
    for doc in documents:
        doc_ner = ner_by_file.get(doc.file_id, [])
        doc_drug_ner = candidates_for_type(doc_ner, {ENTITY_DRUG})
        doc_lab_ner = candidates_for_type(doc_ner, LAB_TYPES)
        doc_rule_ner = candidates_for_type(doc_ner, {ENTITY_DIAGNOSIS, ENTITY_SYMPTOM})

        all_candidates.extend(
            parse_lab_candidates(
                doc,
                resources["lab_terms"],
                ner_candidates=doc_lab_ner,
                lab_entries=lab_entries,
            )
        )
        all_candidates.extend(
            parse_drug_candidates(
                doc,
                resources["drug_terms"],
                linker=rxnorm_linker,
                ner_candidates=doc_drug_ner,
            )
        )
        all_candidates.extend(doc_rule_ner)
        all_candidates.extend(
            extract_diagnosis_candidates(
                doc,
                resources["diagnosis_terms"],
                resources["non_target_terms"],
            )
        )
        all_candidates.extend(extract_symptom_candidates(doc, resources["symptom_terms"]))
        all_candidates.extend(extract_structural_candidates(doc, resources["non_target_terms"]))
        all_candidates.extend(reject_non_target_candidates(doc, resources["non_target_terms"]))

    candidates = dedupe_candidates(all_candidates)
    before_validation = len(candidates)
    candidates = validate_candidate_offsets(documents_by_id, candidates)
    summary = extraction_summary(candidates, documents)
    summary["offset_errors"] = before_validation - len(candidates)
    summary["ner_candidates"] = len(ner_candidates)
    summary["parser_architecture"] = "ner_optional_drug_parser_lab_parser_dictionary_rules"
    return candidates, summary


def source_counts(candidates: Sequence[SpanCandidate]) -> dict[str, int]:
    """Count source tags across candidates."""
    counts: Counter[str] = Counter()
    for candidate in candidates:
        counts.update(candidate.source)
    return dict(counts)


def main() -> int:
    configure_stdout()
    args = parse_args()

    output_json_dir = args.outputs_dir / "output"
    zip_path = args.outputs_dir / "output.zip"
    raw_candidates_path = args.analysis_dir / "span_candidates_new_arch_raw.jsonl"
    asserted_path = args.analysis_dir / "span_candidates_new_arch_asserted.jsonl"
    merged_path = args.analysis_dir / "span_candidates_new_arch_merged.jsonl"
    linked_path = args.analysis_dir / "span_candidates_new_arch_linked.jsonl"
    summary_path = args.analysis_dir / "span_candidates_new_arch_summary.json"
    mapping_debug_path = args.analysis_dir / "mapping_debug_new_arch.csv"
    mapping_unmapped_path = args.analysis_dir / "mapping_unmapped_new_arch.csv"
    validation_report_path = args.reports_dir / "validation_new_arch.md"
    mapping_report_path = args.reports_dir / "mapping_coverage_new_arch.md"

    documents = parse_documents(load_input_files(str(args.input_dir)))
    documents = select_documents(documents, args.only, args.limit)
    if not documents:
        raise SystemExit("No input/*.txt files found for the requested selection; cannot build new-architecture outputs.")

    thresholds = dict(args.ner_threshold)
    ner_candidates = run_ner(
        documents,
        model_name_or_path=args.ner_model,
        device=args.ner_device,
        max_length=args.ner_max_length,
        thresholds=thresholds,
        skip_ner=args.skip_ner,
        strict=args.ner_strict,
        label_map=args.ner_label_map,
    )
    if args.ner_label_map == "vietmed":
        print(
            "NER label_map=vietmed: VietMed adapter active; raw labels will be mapped"
            " to submission types and DISEASESYMTOM spans routed by section context."
        )

    documents_by_id = {doc.file_id: doc for doc in documents}
    raw_candidates, raw_summary = run_new_arch_extraction(
        documents,
        resource_dir=args.resource_dir,
        ner_candidates=ner_candidates,
    )
    asserted_candidates = add_assertions(raw_candidates, documents_by_id)
    merged_candidates = merge_candidates(asserted_candidates)
    icd_linker, rxnorm_linker = load_default_linkers(args.resource_dir)
    linked_candidates, debug_rows = link_mapping_candidates(merged_candidates, icd_linker, rxnorm_linker)

    args.analysis_dir.mkdir(parents=True, exist_ok=True)
    write_span_candidates_jsonl(raw_candidates, str(raw_candidates_path))
    write_span_candidates_jsonl(asserted_candidates, str(asserted_path))
    write_span_candidates_jsonl(merged_candidates, str(merged_path))
    write_span_candidates_jsonl(linked_candidates, str(linked_path))

    raw_summary["documents"] = len(documents)
    raw_summary["source_counts_raw"] = source_counts(raw_candidates)
    raw_summary["source_counts_linked"] = source_counts(linked_candidates)
    summary_path.write_text(json.dumps(raw_summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    debug_fields = ["file_id", "text", "type", "start", "end", "codes", "source", "confidence", "matched_term", "reason"]
    write_csv(mapping_debug_path, debug_rows, debug_fields)
    write_csv(mapping_unmapped_path, [row for row in debug_rows if not row["codes"]], debug_fields)

    if output_json_dir.exists():
        for old_json in output_json_dir.glob("*.json"):
            old_json.unlink()
    write_output_files(linked_candidates, documents, output_json_dir)
    create_output_zip(output_json_dir, zip_path)

    validation_report = validate_output_artifacts(
        output_json_dir,
        zip_path,
        documents_by_id,
        [doc.file_id for doc in documents],
    )
    missing_types = sorted(TARGET_ENTITY_TYPES - set(validation_report.by_type))
    if missing_types:
        validation_report.mark_error(validation_report.schema_errors, f"missing output entity types: {missing_types}")
    write_validation_report(validation_report, validation_report_path)

    mapping = mapping_summary(linked_candidates, debug_rows)
    write_mapping_report(mapping, validation_report.ok, mapping_report_path)

    print("=" * 70)
    print("New Architecture Output Build Complete")
    print("=" * 70)
    print(f"Input dir: {args.input_dir}")
    print(f"Documents: {len(documents)}")
    print(f"NER candidates: {len(ner_candidates)}")
    print(f"Raw candidates: {len(raw_candidates)}")
    print(f"Asserted candidates: {len(asserted_candidates)}")
    print(f"Merged candidates: {len(merged_candidates)}")
    print(f"Linked candidates: {len(linked_candidates)}")
    print(f"Validation: {'PASS' if validation_report.ok else 'FAIL'}")
    print(f"Mapping total: {mapping['total_mapped']}/{mapping['total_mappable']}")
    print(f"Coverage: {mapping['coverage']}")
    print(f"Saved {display_path(output_json_dir)}")
    print(f"Saved {display_path(zip_path)}")
    print(f"Saved {display_path(summary_path)}")
    print(f"Saved {display_path(validation_report_path)}")
    print(f"Saved {display_path(mapping_report_path)}")

    if not validation_report.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
