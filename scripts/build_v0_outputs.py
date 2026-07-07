"""Build V0 assertion, merge, JSON output, zip, and validation artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_span_candidates import load_resources
from src.assertion import add_assertions
from src.io_utils import load_input_files
from src.merge import merge_candidates
from src.output_writer import create_output_zip, write_output_files
from src.rule_extractors import (
    TARGET_ENTITY_TYPES,
    dedupe_candidates,
    extraction_summary,
    extract_diagnosis_candidates,
    extract_drug_candidates,
    extract_lab_candidates,
    extract_symptom_candidates,
    reject_non_target_candidates,
    validate_candidate_offsets,
    write_span_candidates_jsonl,
)
from src.section_parser import parse_documents
from src.validator import validate_output_artifacts, write_validation_report


def configure_stdout() -> None:
    """Make Vietnamese output safe on Windows consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_rule_extraction(documents: list) -> tuple[list, dict]:
    """Run day-09 extractors without writing artifacts."""
    resources = load_resources()
    documents_by_id = {doc.file_id: doc for doc in documents}
    all_candidates = []

    for doc in documents:
        all_candidates.extend(extract_lab_candidates(doc, resources["lab_terms"]))
        all_candidates.extend(extract_drug_candidates(doc, resources["drug_terms"]))
        all_candidates.extend(
            extract_diagnosis_candidates(
                doc,
                resources["diagnosis_terms"],
                resources["non_target_terms"],
            )
        )
        all_candidates.extend(extract_symptom_candidates(doc, resources["symptom_terms"]))
        all_candidates.extend(reject_non_target_candidates(doc, resources["non_target_terms"]))

    candidates = dedupe_candidates(all_candidates)
    before_validation = len(candidates)
    candidates = validate_candidate_offsets(documents_by_id, candidates)
    summary = extraction_summary(candidates, documents)
    summary["offset_errors"] = before_validation - len(candidates)
    return candidates, summary


def main() -> None:
    configure_stdout()

    analysis_dir = ROOT / "analysis"
    outputs_dir = ROOT / "outputs" / "v0"
    output_json_dir = outputs_dir / "output"
    reports_dir = ROOT / "reports"

    raw_candidates_path = analysis_dir / "span_candidates_v0.jsonl"
    raw_summary_path = analysis_dir / "span_candidates_v0_summary.json"
    asserted_path = analysis_dir / "span_candidates_v0_asserted.jsonl"
    merged_path = analysis_dir / "span_candidates_v0_merged.jsonl"
    zip_path = outputs_dir / "output.zip"
    validation_report_path = reports_dir / "validation_v0.md"

    documents = parse_documents(load_input_files(str(ROOT / "input")))
    if not documents:
        raise SystemExit("No input/*.txt files found; cannot build V0 outputs.")

    documents_by_id = {doc.file_id: doc for doc in documents}
    raw_candidates, raw_summary = run_rule_extraction(documents)
    asserted_candidates = add_assertions(raw_candidates, documents_by_id)
    merged_candidates = merge_candidates(asserted_candidates)

    analysis_dir.mkdir(parents=True, exist_ok=True)
    write_span_candidates_jsonl(raw_candidates, str(raw_candidates_path))
    raw_summary_path.write_text(json.dumps(raw_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_span_candidates_jsonl(asserted_candidates, str(asserted_path))
    write_span_candidates_jsonl(merged_candidates, str(merged_path))

    if output_json_dir.exists():
        for old_json in output_json_dir.glob("*.json"):
            old_json.unlink()
    write_output_files(merged_candidates, documents, output_json_dir)
    create_output_zip(output_json_dir, zip_path)

    report = validate_output_artifacts(
        output_json_dir,
        zip_path,
        documents_by_id,
        [doc.file_id for doc in documents],
    )
    missing_types = sorted(TARGET_ENTITY_TYPES - set(report.by_type))
    if missing_types:
        report.mark_error(report.schema_errors, f"missing output entity types: {missing_types}")
    write_validation_report(report, validation_report_path)

    print("=" * 70)
    print("V0 Output Build Complete")
    print("=" * 70)
    print(f"Raw candidates: {len(raw_candidates)}")
    print(f"Asserted candidates: {len(asserted_candidates)}")
    print(f"Merged output candidates: {len(merged_candidates)}")
    print(f"Validation: {'PASS' if report.ok else 'FAIL'}")
    print(f"Entities by type: {dict(report.by_type)}")
    print(f"Assertions: {dict(report.by_assertion)}")
    print(f"Empty files: {report.empty_files}")
    print(f"Saved {raw_candidates_path.relative_to(ROOT)}")
    print(f"Saved {asserted_path.relative_to(ROOT)}")
    print(f"Saved {merged_path.relative_to(ROOT)}")
    print(f"Saved {output_json_dir.relative_to(ROOT)}")
    print(f"Saved {zip_path.relative_to(ROOT)}")
    print(f"Saved {validation_report_path.relative_to(ROOT)}")

    if not report.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
