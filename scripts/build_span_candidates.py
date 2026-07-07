"""Run V0 rule extraction and write analysis/span_candidates_v0.jsonl."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io_utils import load_input_files
from src.rule_extractors import (
    dedupe_candidates,
    extraction_summary,
    extract_diagnosis_candidates,
    extract_drug_candidates,
    extract_lab_candidates,
    extract_symptom_candidates,
    read_term_csv,
    reject_non_target_candidates,
    validate_candidate_offsets,
    write_span_candidates_jsonl,
)
from src.section_parser import parse_documents


def configure_stdout() -> None:
    """Make Vietnamese output safe on Windows consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_resources() -> dict[str, list[str]]:
    """Load V0 seed dictionaries."""
    resource_dir = ROOT / "data_resources"
    return {
        "lab_terms": read_term_csv(str(resource_dir / "lab_seed_terms.csv")),
        "drug_terms": read_term_csv(str(resource_dir / "drug_aliases.csv")),
        "drug_context_terms": read_term_csv(str(resource_dir / "drug_context_terms.csv")),
        "diagnosis_terms": read_term_csv(str(resource_dir / "diagnosis_seed_terms.csv")),
        "symptom_terms": read_term_csv(str(resource_dir / "symptom_seed_terms.csv")),
        "non_target_terms": read_term_csv(str(resource_dir / "non_target_medical_terms.csv")),
    }


def run_extraction() -> tuple[list, dict]:
    """Run all V0 rule extractors across the input folder."""
    documents = parse_documents(load_input_files(str(ROOT / "input")))
    if not documents:
        raise SystemExit("No input/*.txt files found; cannot build span_candidates_v0.jsonl.")
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
    candidate_count_before_validation = len(candidates)
    candidates = validate_candidate_offsets(documents_by_id, candidates)
    summary = extraction_summary(candidates, documents)
    summary["offset_errors"] = candidate_count_before_validation - len(candidates)
    return candidates, summary


def main() -> None:
    configure_stdout()
    output_path = ROOT / "analysis" / "span_candidates_v0.jsonl"
    report_path = ROOT / "analysis" / "span_candidates_v0_summary.json"

    candidates, summary = run_extraction()
    write_span_candidates_jsonl(candidates, str(output_path))
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("V0 Rule Extraction Complete")
    print("=" * 70)
    print(f"Candidates written: {len(candidates)}")
    print(f"Output candidates: {summary['output_candidates']}")
    print(f"By type: {summary['by_type']}")
    print(f"Rejected: {summary['rejected']}")
    print(f"Offset errors: {summary['offset_errors']}")
    print(f"Empty output files: {summary['empty_output_files']}")
    print(f"Saved {output_path.relative_to(ROOT)}")
    print(f"Saved {report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
