# ViClinicalIE Phase 13 Streamlit Review UI

Local dashboard for reviewing Phase 9 predictions, golden evaluation reports, validation reports, and live pipeline inference.

## Run locally

From the project root:

```cmd
streamlit run streamlit_app/app.py
```

Recommended on Windows if Unicode output is needed:

```cmd
set PYTHONUTF8=1
streamlit run streamlit_app/app.py
```

## Default inputs

The app defaults to Phase 9 artifacts:

```text
configs/default.yaml
data/golden/input/
data/golden/gold/
outputs/predictions/phase9_golden20/
outputs/reports/phase9_eval/
data/raw/input/
outputs/predictions/submission_phase9/output/
outputs/reports/submission_phase9_validation/
```

You can override all paths in the sidebar.

## Tabs

- **Overview**: reads `evaluation_summary.json`, `per_file_metrics.csv`, and `per_type_metrics.csv`.
- **File Reviewer**: highlights gold/prediction/error spans on raw text and shows entity tables.
- **Error Browser**: filters FP/FN/span/type/assertion/candidate JSONL reports.
- **Live Inference**: runs `ClinicalIEPipeline` on pasted text or a raw file and displays counters, spans, records, and optional provenance.
- **Submission Review**: checks the 100-file Phase 9 prediction directory and validation summary.

## Notes

- This UI is for local debugging/review. Deploying to Streamlit Cloud is optional and may require uploading data/reports or including them in a private repository.
- The UI does not train models or change predictions. It only reads artifacts and optionally runs the existing deterministic pipeline.
