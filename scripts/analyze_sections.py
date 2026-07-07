"""Build section and line inventories for the 100 clinical documents."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io_utils import load_input_files
from src.section_parser import (
    export_line_inventory,
    export_section_inventory,
    parse_documents,
    write_section_aliases,
)


def configure_stdout() -> None:
    """Make Vietnamese output safe on Windows consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def write_record_stats(documents, path: str) -> None:
    """Write one record-level row per input file."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "file_id",
        "record_index",
        "char_len",
        "line_count",
        "has_numbered_sections",
        "num_sections",
        "num_lines",
        "detected_main_sections",
        "notes",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for doc in documents:
            main_sections = doc.metadata.get("detected_main_sections", [])
            notes = []
            if len(main_sections) < 2:
                notes.append("few_main_sections")
            if not doc.sections:
                notes.append("no_detected_sections")
            writer.writerow(
                {
                    "file_id": f"{doc.file_id}.txt",
                    "record_index": int(doc.file_id),
                    "char_len": doc.metadata["char_len"],
                    "line_count": doc.metadata["line_count"],
                    "has_numbered_sections": doc.metadata.get("has_numbered_sections", False),
                    "num_sections": len(doc.sections),
                    "num_lines": len(doc.lines),
                    "detected_main_sections": "|".join(main_sections),
                    "notes": "|".join(notes),
                }
            )


def main() -> None:
    configure_stdout()
    input_dir = ROOT / "input"
    analysis_dir = ROOT / "analysis"
    configs_dir = ROOT / "configs"

    print("=" * 70)
    print("Section and Line Inventory Builder")
    print("=" * 70)

    documents = parse_documents(load_input_files(str(input_dir)))
    section_counts = Counter(section.section_type for doc in documents for section in doc.sections)
    line_counts = Counter(line.line_kind for doc in documents for line in doc.lines)

    write_record_stats(documents, str(analysis_dir / "record_stats.csv"))
    export_section_inventory(documents, str(analysis_dir / "section_inventory.csv"))
    export_line_inventory(documents, str(analysis_dir / "line_inventory.csv"))
    write_section_aliases(str(configs_dir / "section_aliases.json"))

    print(f"Processed documents: {len(documents)}")
    print(f"Detected sections: {sum(section_counts.values())}")
    print(f"Detected lines: {sum(line_counts.values())}")
    print("Top section types:")
    for section_type, count in section_counts.most_common(12):
        print(f"  {section_type}: {count}")
    print("Line kinds:")
    for line_kind, count in sorted(line_counts.items()):
        print(f"  {line_kind}: {count}")

    print("Saved analysis/record_stats.csv")
    print("Saved analysis/section_inventory.csv")
    print("Saved analysis/line_inventory.csv")
    print("Saved configs/section_aliases.json")


if __name__ == "__main__":
    main()
