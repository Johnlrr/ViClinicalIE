"""Streamlit viewer for verifying ViClinicalIE raw text and JSON outputs."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]

ENTITY_TYPES = [
    "TRIỆU_CHỨNG",
    "CHẨN_ĐOÁN",
    "THUỐC",
    "TÊN_XÉT_NGHIỆM",
    "KẾT_QUẢ_XÉT_NGHIỆM",
]
ASSERTIONS = ["isNegated", "isHistorical", "isFamily"]

TYPE_STYLES = {
    "TRIỆU_CHỨNG": {"class": "symptom", "label": "SYM", "color": "#1d4ed8"},
    "CHẨN_ĐOÁN": {"class": "diagnosis", "label": "DX", "color": "#047857"},
    "THUỐC": {"class": "drug", "label": "DRUG", "color": "#b45309"},
    "TÊN_XÉT_NGHIỆM": {"class": "lab-name", "label": "LAB", "color": "#7c3aed"},
    "KẾT_QUẢ_XÉT_NGHIỆM": {"class": "lab-result", "label": "RES", "color": "#be123c"},
}


def resolve_path(value: str) -> Path:
    """Resolve absolute or repo-relative path input."""
    path = Path(value.strip().strip('"'))
    if path.is_absolute():
        return path
    return ROOT / path


def numeric_sort_key(path_or_id: Path | str) -> Tuple[int, str]:
    """Sort numeric ids naturally, then fall back to text."""
    value = path_or_id.stem if isinstance(path_or_id, Path) else str(path_or_id)
    return (int(value), value) if value.isdigit() else (10**9, value)


def discover_output_dirs() -> List[Path]:
    """Find output directories shaped like outputs/<version>/output."""
    outputs_root = ROOT / "outputs"
    if not outputs_root.exists():
        return []
    candidates = []
    for path in outputs_root.rglob("*"):
        if path.is_dir() and path.name == "output" and any(path.glob("*.json")):
            candidates.append(path)
    return sorted(candidates, key=lambda path: str(path.relative_to(ROOT)))


def list_file_ids(input_dir: Path, output_dir: Path) -> List[str]:
    """Return file ids available in either raw input or output JSON."""
    ids = set()
    if input_dir.exists():
        ids.update(path.stem for path in input_dir.glob("*.txt"))
    if output_dir.exists():
        ids.update(path.stem for path in output_dir.glob("*.json"))
    return sorted(ids, key=numeric_sort_key)


def read_text(path: Path) -> Tuple[str, str | None]:
    """Read UTF-8 text and return error message instead of raising."""
    if not path.exists():
        return "", f"Missing file: {path}"
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        return "", f"Cannot decode UTF-8: {path} ({exc})"


def read_entities(path: Path) -> Tuple[List[Dict[str, Any]], List[str], str]:
    """Read one output JSON file."""
    if not path.exists():
        return [], [f"Missing output JSON: {path}"], "[]"
    raw_json, read_error = read_text(path)
    if read_error:
        return [], [read_error], ""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return [], [f"Invalid JSON: {exc}"], raw_json
    if not isinstance(data, list):
        return [], ["Output root must be a JSON list."], raw_json

    entities = []
    errors = []
    for index, item in enumerate(data):
        if isinstance(item, dict):
            entity = dict(item)
            entity["_index"] = index
            entities.append(entity)
        else:
            errors.append(f"Entity {index}: expected object, got {type(item).__name__}.")
    return entities, errors, raw_json


def validate_entities(raw_text: str, entities: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Validate schema, offsets, and overlaps for display."""
    validated = []
    errors = []

    for entity in entities:
        item = dict(entity)
        index = item.get("_index", "?")
        position = item.get("position")
        text = item.get("text")
        entity_type = item.get("type")
        assertions = item.get("assertions", [])
        candidates = item.get("candidates", [])

        item["_schema_ok"] = True
        item["_offset_ok"] = False
        item["_range_ok"] = False
        item["_overlap"] = False

        if not isinstance(text, str) or not text:
            errors.append(f"Entity {index}: text must be a non-empty string.")
            item["_schema_ok"] = False
        if entity_type not in ENTITY_TYPES:
            errors.append(f"Entity {index}: invalid type {entity_type!r}.")
            item["_schema_ok"] = False
        if not isinstance(assertions, list) or any(assertion not in ASSERTIONS for assertion in assertions):
            errors.append(f"Entity {index}: invalid assertions {assertions!r}.")
            item["_schema_ok"] = False
        if entity_type in {"CHẨN_ĐOÁN", "THUỐC"} and not isinstance(candidates, list):
            errors.append(f"Entity {index}: candidates must be a list for diagnosis/drug.")
            item["_schema_ok"] = False
        if entity_type not in {"CHẨN_ĐOÁN", "THUỐC"} and "candidates" in item:
            errors.append(f"Entity {index}: candidates only allowed for diagnosis/drug.")
            item["_schema_ok"] = False

        if not isinstance(position, list) or len(position) != 2 or not all(isinstance(value, int) for value in position):
            errors.append(f"Entity {index}: position must be [start, end] integers.")
            item["_schema_ok"] = False
        else:
            start, end = position
            item["_range_ok"] = 0 <= start < end <= len(raw_text)
            if not item["_range_ok"]:
                errors.append(f"Entity {index}: invalid range {start}:{end}.")
            elif raw_text[start:end] == text:
                item["_offset_ok"] = True
            else:
                actual = raw_text[start:end].replace("\n", "\\n")
                errors.append(f"Entity {index}: offset mismatch {start}:{end}; actual={actual!r}, text={text!r}.")

        validated.append(item)

    sorted_ranges = sorted(
        [
            (item["position"][0], item["position"][1], item)
            for item in validated
            if item.get("_range_ok") and isinstance(item.get("position"), list)
        ],
        key=lambda value: (value[0], value[1]),
    )
    previous = None
    for start, end, item in sorted_ranges:
        if previous and start < previous[1]:
            item["_overlap"] = True
            previous[2]["_overlap"] = True
            errors.append(f"Overlap: entity {previous[2].get('_index')} and entity {item.get('_index')}.")
        if previous is None or end > previous[1]:
            previous = (start, end, item)

    return validated, errors


def entity_matches_filters(
    entity: Dict[str, Any],
    selected_types: Sequence[str],
    selected_assertions: Sequence[str],
    show_invalid_offsets: bool,
) -> bool:
    """Check UI filters for one entity."""
    if selected_types and entity.get("type") not in selected_types:
        return False
    if selected_assertions and not set(selected_assertions).intersection(entity.get("assertions", [])):
        return False
    if not show_invalid_offsets and not entity.get("_offset_ok"):
        return False
    return True


def tooltip_for(entity: Dict[str, Any]) -> str:
    """Build safe tooltip text."""
    bits = [
        f"type={entity.get('type', '')}",
        f"position={entity.get('position', '')}",
    ]
    if entity.get("assertions"):
        bits.append(f"assertions={', '.join(entity['assertions'])}")
    if entity.get("candidates"):
        bits.append(f"candidates={', '.join(map(str, entity['candidates']))}")
    if not entity.get("_offset_ok"):
        bits.append("offset mismatch")
    if entity.get("_overlap"):
        bits.append("overlap")
    return html.escape(" | ".join(bits), quote=True)


def annotation_label(entity: Dict[str, Any]) -> str:
    """Compact label shown next to highlighted text."""
    style = TYPE_STYLES.get(entity.get("type"), {"label": "UNK"})
    badges = []
    for assertion in entity.get("assertions", []):
        badges.append(assertion.replace("is", ""))
    suffix = " ".join(badges)
    return f"{style['label']} {suffix}".strip()


def render_annotated_text(raw_text: str, entities: Sequence[Dict[str, Any]]) -> str:
    """Render raw text with inline entity highlights."""
    renderable = [
        item
        for item in entities
        if item.get("_range_ok") and isinstance(item.get("position"), list)
    ]
    renderable.sort(key=lambda item: (item["position"][0], item["position"][1]))

    parts = []
    cursor = 0
    for entity in renderable:
        start, end = entity["position"]
        if start < cursor:
            continue
        parts.append(html.escape(raw_text[cursor:start]))
        entity_type = entity.get("type", "")
        style = TYPE_STYLES.get(entity_type, {"class": "unknown"})
        classes = ["entity", style["class"]]
        if not entity.get("_offset_ok"):
            classes.append("bad-offset")
        if entity.get("_overlap"):
            classes.append("overlap")
        label = html.escape(annotation_label(entity))
        text = html.escape(raw_text[start:end])
        title = tooltip_for(entity)
        parts.append(
            f'<span class="{" ".join(classes)}" title="{title}">{text}'
            f'<span class="entity-label">{label}</span></span>'
        )
        cursor = end
    parts.append(html.escape(raw_text[cursor:]))

    return f'<div class="raw-view">{"".join(parts)}</div>'


def build_table(entities: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """Create a compact entity table."""
    rows = []
    for entity in entities:
        position = entity.get("position", ["", ""])
        rows.append(
            {
                "#": entity.get("_index"),
                "text": entity.get("text", ""),
                "type": entity.get("type", ""),
                "start": position[0] if isinstance(position, list) and len(position) == 2 else "",
                "end": position[1] if isinstance(position, list) and len(position) == 2 else "",
                "assertions": ", ".join(entity.get("assertions", [])),
                "candidates": ", ".join(map(str, entity.get("candidates", []))),
                "offset_ok": entity.get("_offset_ok", False),
                "overlap": entity.get("_overlap", False),
            }
        )
    return pd.DataFrame(rows)


def type_counts(entities: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count entities by type."""
    return dict(Counter(entity.get("type", "") for entity in entities))


def assertion_counts(entities: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count assertion labels."""
    counter: Counter[str] = Counter()
    for entity in entities:
        counter.update(entity.get("assertions", []))
    return dict(counter)


def install_css() -> None:
    """Inject minimal app styling."""
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; max-width: 1500px; }
        .raw-view {
            border: 1px solid #d8dee9;
            border-radius: 8px;
            padding: 16px;
            min-height: 680px;
            max-height: 78vh;
            overflow: auto;
            white-space: pre-wrap;
            line-height: 1.65;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
            background: #fbfcfe;
            color: #111827;
        }
        .entity {
            display: inline;
            border-radius: 5px;
            padding: 2px 3px;
            box-decoration-break: clone;
            -webkit-box-decoration-break: clone;
            border-bottom: 2px solid rgba(17, 24, 39, 0.28);
        }
        .symptom { background: #dbeafe; border-color: #1d4ed8; }
        .diagnosis { background: #d1fae5; border-color: #047857; }
        .drug { background: #fef3c7; border-color: #b45309; }
        .lab-name { background: #ede9fe; border-color: #7c3aed; }
        .lab-result { background: #ffe4e6; border-color: #be123c; }
        .unknown { background: #e5e7eb; border-color: #4b5563; }
        .bad-offset { background: #fee2e2 !important; border-color: #dc2626 !important; }
        .overlap { outline: 2px dashed #dc2626; }
        .entity-label {
            display: inline-block;
            margin-left: 4px;
            padding: 0 4px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.78);
            color: #111827;
            font-size: 0.68rem;
            font-family: ui-sans-serif, system-ui, sans-serif;
            font-weight: 700;
            vertical-align: 10%;
        }
        .json-box {
            max-height: 460px;
            overflow: auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_controls() -> Tuple[Path, Path, str, List[str], List[str], bool, bool, bool]:
    """Render sidebar controls and return current selections."""
    st.sidebar.header("Verify Config")

    default_input = "input"
    discovered_outputs = discover_output_dirs()
    output_options = [str(path.relative_to(ROOT)) for path in discovered_outputs]
    if not output_options:
        output_options = ["outputs/v0/output"]

    input_value = st.sidebar.text_input("Input folder", value=default_input)
    selected_output = st.sidebar.selectbox("Detected output folder", output_options, index=0)
    output_value = st.sidebar.text_input("Output folder", value=selected_output)

    input_dir = resolve_path(input_value)
    output_dir = resolve_path(output_value)
    file_ids = list_file_ids(input_dir, output_dir)

    if file_ids:
        default_index = 0
        file_id = st.sidebar.selectbox("File ID", file_ids, index=default_index)
    else:
        file_id = st.sidebar.text_input("File ID", value="1")

    selected_types = st.sidebar.multiselect("Type filter", ENTITY_TYPES, default=ENTITY_TYPES)
    selected_assertions = st.sidebar.multiselect("Assertion filter", ASSERTIONS, default=[])
    show_invalid_offsets = st.sidebar.checkbox("Show invalid offsets", value=True)
    show_entity_table = st.sidebar.checkbox("Show entity table", value=True)
    show_raw_json = st.sidebar.checkbox("Show raw JSON", value=True)

    return (
        input_dir,
        output_dir,
        file_id,
        selected_types,
        selected_assertions,
        show_invalid_offsets,
        show_entity_table,
        show_raw_json,
    )


def main() -> None:
    """Run the Streamlit verifier."""
    st.set_page_config(page_title="ViClinicalIE Verify", layout="wide")
    install_css()

    st.title("ViClinicalIE Output Verifier")

    (
        input_dir,
        output_dir,
        file_id,
        selected_types,
        selected_assertions,
        show_invalid_offsets,
        show_entity_table,
        show_raw_json,
    ) = sidebar_controls()

    raw_path = input_dir / f"{file_id}.txt"
    output_path = output_dir / f"{file_id}.json"
    raw_text, raw_error = read_text(raw_path)
    entities, json_errors, raw_json = read_entities(output_path)
    entities, validation_errors = validate_entities(raw_text, entities)

    filtered_entities = [
        entity
        for entity in entities
        if entity_matches_filters(entity, selected_types, selected_assertions, show_invalid_offsets)
    ]

    top_cols = st.columns(4)
    top_cols[0].metric("File", file_id)
    top_cols[1].metric("Entities", len(filtered_entities))
    top_cols[2].metric("Offset errors", sum(1 for entity in entities if not entity.get("_offset_ok")))
    top_cols[3].metric("Overlaps", sum(1 for entity in entities if entity.get("_overlap")))

    if raw_error:
        st.error(raw_error)
    if json_errors:
        st.warning("\n".join(json_errors))

    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.subheader("Raw Text")
        st.caption(str(raw_path))
        if raw_text:
            st.markdown(render_annotated_text(raw_text, filtered_entities), unsafe_allow_html=True)
        else:
            st.info("No raw text loaded.")

    with right:
        st.subheader("Output JSON")
        st.caption(str(output_path))

        counts_col, assertions_col = st.columns(2)
        counts_col.write("Type counts")
        counts_col.json(type_counts(filtered_entities))
        assertions_col.write("Assertion counts")
        assertions_col.json(assertion_counts(filtered_entities))

        if validation_errors:
            with st.expander(f"Validation issues ({len(validation_errors)})", expanded=True):
                for error in validation_errors:
                    st.error(error)
        else:
            st.success("No schema, offset, or overlap issues for this file.")

        if show_entity_table:
            st.write("Entity table")
            table = build_table(filtered_entities)
            st.dataframe(table, use_container_width=True, hide_index=True)

        if show_raw_json:
            st.write("Raw JSON")
            if raw_json.strip():
                st.code(raw_json, language="json")
            else:
                st.code("[]", language="json")


if __name__ == "__main__":
    main()
