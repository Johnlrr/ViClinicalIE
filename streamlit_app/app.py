from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from streamlit_app.data_loader import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_GOLD_DIR,
    DEFAULT_GOLDEN_INPUT_DIR,
    DEFAULT_PHASE9_PRED_DIR,
    DEFAULT_PHASE9_REPORT_DIR,
    DEFAULT_RAW_INPUT_DIR,
    DEFAULT_SUBMISSION_PRED_DIR,
    DEFAULT_SUBMISSION_REPORT_DIR,
    ERROR_FILES,
    filter_rows_for_file,
    list_file_ids,
    load_csv,
    load_error_rows,
    load_evaluation_summary,
    load_raw_text,
    load_records,
    load_validation_summary,
    records_to_dataframe,
    resolve_path,
    summarize_records_by_type,
)
from streamlit_app.highlight import render_highlighted_text, spans_from_error_rows, spans_from_records  # noqa: E402
from streamlit_app.pipeline_debug import build_pipeline, postprocess_report_to_dict  # noqa: E402
from streamlit_app.tables import compare_entity_rows, filter_error_frame, flatten_error_rows  # noqa: E402


st.set_page_config(page_title="ViClinicalIE Phase 13 Review UI", layout="wide")


@st.cache_data(show_spinner=False)
def cached_summary(report_dir: str) -> dict[str, Any]:
    return load_evaluation_summary(report_dir)


@st.cache_data(show_spinner=False)
def cached_csv(report_dir: str, file_name: str) -> pd.DataFrame:
    return load_csv(report_dir, file_name)


@st.cache_data(show_spinner=False)
def cached_error_rows(report_dir: str, label: str) -> list[dict[str, Any]]:
    return load_error_rows(report_dir, label)


@st.cache_data(show_spinner=False)
def cached_records(directory: str, file_id: str) -> list[dict[str, Any]]:
    return load_records(directory, file_id)


@st.cache_data(show_spinner=False)
def cached_raw_text(directory: str, file_id: str) -> str:
    return load_raw_text(directory, file_id)


@st.cache_resource(show_spinner=True)
def cached_pipeline(config_path: str, enable_sparse_retrieval: bool):
    return build_pipeline(config_path, enable_sparse_retrieval=enable_sparse_retrieval)


def main() -> None:
    st.title("ViClinicalIE Phase 13 — Streamlit Review UI")
    st.caption("Local dashboard để review Phase 9 predictions, golden errors, validation và live inference debug.")

    paths = sidebar_paths()
    tabs = st.tabs(["Overview", "File Reviewer", "Error Browser", "Live Inference", "Submission Review"])
    with tabs[0]:
        render_overview(paths)
    with tabs[1]:
        render_file_reviewer(paths)
    with tabs[2]:
        render_error_browser(paths)
    with tabs[3]:
        render_live_inference(paths)
    with tabs[4]:
        render_submission_review(paths)


def sidebar_paths() -> dict[str, str]:
    st.sidebar.header("Paths")
    default_values = {
        "config_path": DEFAULT_CONFIG_PATH,
        "golden_input_dir": DEFAULT_GOLDEN_INPUT_DIR,
        "gold_dir": DEFAULT_GOLD_DIR,
        "pred_dir": DEFAULT_PHASE9_PRED_DIR,
        "report_dir": DEFAULT_PHASE9_REPORT_DIR,
        "raw_input_dir": DEFAULT_RAW_INPUT_DIR,
        "submission_pred_dir": DEFAULT_SUBMISSION_PRED_DIR,
        "submission_report_dir": DEFAULT_SUBMISSION_REPORT_DIR,
    }
    labels = {
        "config_path": "Config YAML",
        "golden_input_dir": "Golden input dir",
        "gold_dir": "Golden gold dir",
        "pred_dir": "Phase 9 prediction dir",
        "report_dir": "Phase 9 report dir",
        "raw_input_dir": "Raw input dir",
        "submission_pred_dir": "Submission prediction dir",
        "submission_report_dir": "Submission validation report dir",
    }
    paths: dict[str, str] = {}
    for key, value in default_values.items():
        paths[key] = st.sidebar.text_input(labels[key], value=str(value))

    st.sidebar.divider()
    st.sidebar.write("Resolved status")
    for key, value in paths.items():
        path = resolve_path(value)
        icon = "✅" if path.exists() else "⚠️"
        st.sidebar.caption(f"{icon} {key}: `{path}`")
    return paths


def render_overview(paths: dict[str, str]) -> None:
    st.subheader("Phase 9 metric overview")
    summary = cached_summary(paths["report_dir"])
    if not summary:
        st.warning("Không tìm thấy evaluation_summary.json. Hãy kiểm tra report_dir.")
        return

    exact = summary.get("exact", {})
    relaxed = summary.get("relaxed", {})
    assertions = summary.get("assertions", {})
    candidates = summary.get("candidates", {})

    cols = st.columns(6)
    cols[0].metric("Files", summary.get("files_evaluated", 0))
    cols[1].metric("Gold", summary.get("gold_entities", 0))
    cols[2].metric("Pred", summary.get("pred_entities", 0))
    cols[3].metric("Exact F1", _fmt_float(exact.get("f1")))
    cols[4].metric("Relaxed F1", _fmt_float(relaxed.get("f1")))
    cols[5].metric("Candidate hit", _fmt_float(candidates.get("hit_rate")))

    cols = st.columns(4)
    cols[0].metric("Exact precision", _fmt_float(exact.get("precision")))
    cols[1].metric("Exact recall", _fmt_float(exact.get("recall")))
    cols[2].metric("Assertion exact", _fmt_float(assertions.get("exact_match_rate")))
    cols[3].metric("Error categories", sum((summary.get("error_category_counts") or {}).values()))

    per_file = cached_csv(paths["report_dir"], "per_file_metrics.csv")
    per_type = cached_csv(paths["report_dir"], "per_type_metrics.csv")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### Per-file metrics")
        if not per_file.empty:
            st.dataframe(per_file.sort_values("exact_f1", ascending=True), use_container_width=True, hide_index=True)
        else:
            st.info("per_file_metrics.csv not found")
    with col_b:
        st.markdown("#### Per-type metrics")
        if not per_type.empty:
            st.dataframe(per_type.sort_values("exact_f1", ascending=True), use_container_width=True, hide_index=True)
        else:
            st.info("per_type_metrics.csv not found")

    st.markdown("#### Raw summary JSON")
    with st.expander("Show evaluation_summary.json"):
        st.json(summary)


def render_file_reviewer(paths: dict[str, str]) -> None:
    st.subheader("Golden file reviewer")
    file_ids = list_file_ids(paths["golden_input_dir"], ".txt")
    if not file_ids:
        st.warning("Không tìm thấy golden input files.")
        return
    selected_file = st.selectbox("File ID", file_ids, key="file_reviewer_id")
    raw_text = cached_raw_text(paths["golden_input_dir"], selected_file)
    gold_records = cached_records(paths["gold_dir"], selected_file)
    pred_records = cached_records(paths["pred_dir"], selected_file)

    st.caption(f"Raw chars: {len(raw_text)} | Gold: {len(gold_records)} | Prediction: {len(pred_records)}")

    layer_cols = st.columns(6)
    show_gold = layer_cols[0].checkbox("Gold", value=True)
    show_pred = layer_cols[1].checkbox("Prediction", value=True)
    show_tp = layer_cols[2].checkbox("TP", value=False)
    show_fp = layer_cols[3].checkbox("FP", value=False)
    show_fn = layer_cols[4].checkbox("FN", value=False)
    show_mismatch = layer_cols[5].checkbox("Mismatches", value=False)

    spans = []
    if show_gold:
        spans.extend(spans_from_records(gold_records, source="gold"))
    if show_pred:
        spans.extend(spans_from_records(pred_records, source="prediction"))
    if show_tp:
        spans.extend(spans_from_error_rows(filter_rows_for_file(cached_error_rows(paths["report_dir"], "True positives"), selected_file), source="tp"))
    if show_fp:
        spans.extend(spans_from_error_rows(filter_rows_for_file(cached_error_rows(paths["report_dir"], "False positives"), selected_file), source="fp"))
    if show_fn:
        spans.extend(spans_from_error_rows(filter_rows_for_file(cached_error_rows(paths["report_dir"], "False negatives"), selected_file), source="fn"))
    if show_mismatch:
        for label, source in (
            ("Span mismatches", "span_mismatch"),
            ("Type mismatches", "type_mismatch"),
            ("Assertion mismatches", "assertion_mismatch"),
            ("Candidate mismatches", "candidate_mismatch"),
        ):
            spans.extend(spans_from_error_rows(filter_rows_for_file(cached_error_rows(paths["report_dir"], label), selected_file), source=source))

    st.markdown(render_highlighted_text(raw_text, spans), unsafe_allow_html=True)

    st.divider()
    table_tabs = st.tabs(["Gold", "Prediction", "Compare", "Errors in file", "Type counts"])
    with table_tabs[0]:
        st.dataframe(records_to_dataframe(gold_records), use_container_width=True, hide_index=True)
    with table_tabs[1]:
        st.dataframe(records_to_dataframe(pred_records), use_container_width=True, hide_index=True)
    with table_tabs[2]:
        st.dataframe(compare_entity_rows(gold_records, pred_records), use_container_width=True, hide_index=True)
    with table_tabs[3]:
        rows = []
        for label in ERROR_FILES:
            if label == "All error cases":
                continue
            for row in filter_rows_for_file(cached_error_rows(paths["report_dir"], label), selected_file):
                row = dict(row)
                row["_source_file"] = label
                rows.append(row)
        st.dataframe(flatten_error_rows(rows), use_container_width=True, hide_index=True)
    with table_tabs[4]:
        col_a, col_b = st.columns(2)
        col_a.markdown("Gold by type")
        col_a.dataframe(summarize_records_by_type(gold_records), use_container_width=True, hide_index=True)
        col_b.markdown("Prediction by type")
        col_b.dataframe(summarize_records_by_type(pred_records), use_container_width=True, hide_index=True)


def render_error_browser(paths: dict[str, str]) -> None:
    st.subheader("Error browser")
    label = st.selectbox("Error category", list(ERROR_FILES), index=1)
    rows = cached_error_rows(paths["report_dir"], label)
    frame = flatten_error_rows(rows)
    if frame.empty:
        st.info("Không có rows hoặc file report không tồn tại.")
        return

    file_values = ["All"] + sorted(frame["file_id"].astype(str).unique().tolist(), key=_natural_str_key)
    type_values = ["All"] + sorted(set(frame["pred_type"].dropna().astype(str)) | set(frame["gold_type"].dropna().astype(str)))
    subcategories = ["All"] + sorted(value for value in frame.get("subcategory", pd.Series(dtype=str)).dropna().astype(str).unique() if value)

    cols = st.columns([1, 1, 1, 2])
    file_id = cols[0].selectbox("File", file_values)
    entity_type = cols[1].selectbox("Type", type_values)
    subcategory = cols[2].selectbox("Subcategory", subcategories)
    text_query = cols[3].text_input("Text/context contains")
    filtered = filter_error_frame(frame, file_id=file_id, entity_type=entity_type, text_query=text_query, subcategory=subcategory)
    st.caption(f"Rows: {len(filtered)} / {len(frame)}")
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    if filtered.empty:
        return
    selected_row_id = st.number_input("Inspect row number", min_value=0, max_value=max(0, len(filtered) - 1), value=0, step=1)
    selected = filtered.iloc[int(selected_row_id)].to_dict()
    original_index = int(selected.get("row", 0))
    raw_row = rows[original_index]

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### Pred")
        st.json(raw_row.get("pred", {}))
    with col_b:
        st.markdown("#### Gold")
        st.json(raw_row.get("gold", {}))
    context = raw_row.get("context", {}) if isinstance(raw_row.get("context"), dict) else {}
    if context.get("text"):
        st.markdown("#### Context")
        st.code(context.get("text", ""), language="text")
    with st.expander("Raw error row"):
        st.json(raw_row)


def render_live_inference(paths: dict[str, str]) -> None:
    st.subheader("Live inference debug")
    source = st.radio("Input source", ["Paste text", "Load raw file"], horizontal=True)
    file_id = "live"
    raw_text = ""
    if source == "Load raw file":
        file_ids = list_file_ids(paths["raw_input_dir"], ".txt")
        if not file_ids:
            st.warning("Không tìm thấy raw input files.")
            return
        file_id = st.selectbox("Raw file ID", file_ids, key="live_raw_file")
        raw_text = cached_raw_text(paths["raw_input_dir"], file_id)
        st.text_area("Raw text", raw_text, height=220, disabled=True)
    else:
        raw_text = st.text_area("Paste clinical note", height=220, placeholder="Dán raw clinical note vào đây...")
        file_id = st.text_input("File/debug ID", value="live")

    enable_sparse = st.checkbox("Enable sparse linker retrieval", value=False, help="Tắt mặc định để live debug nhanh và giống Phase 9 submission run.")
    show_provenance = st.checkbox("Show entity provenance", value=False)
    if st.button("Run inference", type="primary", disabled=not raw_text.strip()):
        with st.spinner("Running pipeline..."):
            pipeline = cached_pipeline(str(resolve_path(paths["config_path"])), enable_sparse)
            result = pipeline.process_text(raw_text, file_id=file_id)
        st.success(f"Done. Records: {len(result.records)}")
        col_a, col_b, col_c = st.columns(3)
        col_a.json(result.counters)
        col_b.json(result.entities_by_type)
        col_c.json(postprocess_report_to_dict(result.postprocess_report))
        st.markdown(render_highlighted_text(raw_text, spans_from_records(result.records, source="live")), unsafe_allow_html=True)
        st.markdown("#### Submission records")
        st.dataframe(records_to_dataframe(result.records), use_container_width=True, hide_index=True)
        with st.expander("JSON output"):
            st.json(result.records)
        if show_provenance:
            with st.expander("FinalEntity debug objects"):
                st.json([_entity_to_debug_dict(entity) for entity in result.entities])


def render_submission_review(paths: dict[str, str]) -> None:
    st.subheader("100-file submission review")
    pred_dir = resolve_path(paths["submission_pred_dir"])
    json_files = sorted(pred_dir.glob("*.json"), key=lambda item: _natural_str_key(item.stem)) if pred_dir.is_dir() else []
    validation = load_validation_summary(paths["submission_report_dir"])

    cols = st.columns(5)
    cols[0].metric("JSON files", len(json_files))
    cols[1].metric("Validation errors", validation.get("error_count", "n/a"))
    cols[2].metric("Warnings", validation.get("warning_count", "n/a"))
    cols[3].metric("Entities checked", validation.get("entities_checked", "n/a"))
    cols[4].metric("OK", validation.get("ok", "n/a"))

    rows: list[dict[str, Any]] = []
    for path in json_files:
        records = load_records(pred_dir, path.stem)
        rows.append({"file_id": path.stem, "record_count": len(records), "path": str(path)})
    frame = pd.DataFrame(rows)
    if not frame.empty:
        st.dataframe(frame, use_container_width=True, hide_index=True)
        selected = st.selectbox("Inspect prediction file", frame["file_id"].tolist(), key="submission_file")
        records = load_records(pred_dir, str(selected))
        st.dataframe(records_to_dataframe(records), use_container_width=True, hide_index=True)
        with st.expander("Raw JSON"):
            st.json(records)
    else:
        st.warning("Không tìm thấy submission JSON files.")

    with st.expander("Validation summary"):
        st.json(validation)


def _fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _natural_str_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _entity_to_debug_dict(entity: Any) -> dict[str, Any]:
    return {
        "text": getattr(entity, "text", ""),
        "position": [getattr(entity, "start", 0), getattr(entity, "end", 0)],
        "type": str(getattr(entity, "type", "")),
        "assertions": list(getattr(entity, "assertions", []) or []),
        "candidates": list(getattr(entity, "candidates", []) or []),
        "confidence": getattr(entity, "confidence", None),
        "provenance": getattr(entity, "provenance", {}),
    }


if __name__ == "__main__":
    main()
