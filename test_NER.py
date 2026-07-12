# validate_and_test_vietmed_ner.py
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
import torch
import json
from pathlib import Path

BASE_TOKENIZER = "vinai/phobert-base-v2"
CKPT_DIR = r"D:\VKB_Projects\Viettel_AI_Race\models\phobert-base-v2-VietMed-NER"

EXPECTED_PROJECT_LABELS = {
    "TRIỆU_CHỨNG",
    "CHẨN_ĐOÁN",
    "THUỐC",
    "TÊN_XÉT_NGHIỆM",
    "KẾT_QUẢ_XÉT_NGHIỆM",
}

GENERIC_PREFIXES = {"LABEL_", "B-", "I-", "O"}

def normalize_label(label: str) -> str:
    if not isinstance(label, str):
        return str(label)
    if label.startswith("B-") or label.startswith("I-"):
        return label[2:]
    return label

def main():
    ckpt = Path(CKPT_DIR)
    config_path = ckpt / "config.json"

    if not ckpt.exists():
        raise FileNotFoundError(f"Checkpoint folder not found: {ckpt}")
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.json in: {ckpt}")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    id2label = cfg.get("id2label", {})
    if not id2label:
        raise ValueError("config.json has no id2label")

    labels = [id2label[k] for k in sorted(id2label, key=lambda x: int(x) if str(x).isdigit() else str(x))]
    norm_labels = {normalize_label(x) for x in labels}

    print("architectures:", cfg.get("architectures"))
    print("model_type:", cfg.get("model_type"))
    print("num_labels:", cfg.get("num_labels"))
    print("raw labels:", labels)
    print("normalized labels:", sorted(norm_labels))

    if all(str(x).startswith("LABEL_") for x in labels):
        raise ValueError("Checkpoint uses generic LABEL_n tags. Likely unsafe for your project.")

    overlap = EXPECTED_PROJECT_LABELS.intersection(norm_labels)
    print("project label overlap:", sorted(overlap))

    if not overlap:
        print("WARNING: No direct overlap with ViClinicalIE labels.")
        print("You may still run it, but you will probably need label mapping.")

    tokenizer = AutoTokenizer.from_pretrained(BASE_TOKENIZER, use_fast=True)
    model = AutoModelForTokenClassification.from_pretrained(str(ckpt))

    device = 0 if torch.cuda.is_available() else -1
    ner = pipeline(
        "ner",
        model=model,
        tokenizer=tokenizer,
        aggregation_strategy="simple",
        device=device,
    )

    sample = "Bệnh nhân dùng doxycycline điều trị viêm tuyến mồ hôi và làm xét nghiệm CRP."
    print("\nSample text:", sample)
    preds = ner(sample)
    for p in preds:
        print(p)

if __name__ == "__main__":
    main()