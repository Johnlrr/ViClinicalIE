# test_vietmed_ner_local.py
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
import torch
import json
from pathlib import Path

BASE_TOKENIZER = "vinai/phobert-base-v2"
CKPT_DIR = r"D:\VKB_Projects\Viettel_AI_Race\models\phobert-base-v2-VietMed-NER"

def main():
    ckpt = Path(CKPT_DIR)
    if not ckpt.exists():
        raise FileNotFoundError(f"Checkpoint folder not found: {ckpt}")

    config_path = ckpt / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.json in: {ckpt}")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    print("architectures:", cfg.get("architectures"))
    print("model_type:", cfg.get("model_type"))
    print("id2label:", cfg.get("id2label"))

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

    texts = [
        "Bệnh nhân dùng doxycycline điều trị viêm tuyến mồ hôi.",
        "Bệnh nhân sốt, đau đầu, được chẩn đoán viêm phổi.",
        "Xét nghiệm CRP tăng cao."
    ]

    for text in texts:
        print("\nTEXT:", text)
        out = ner(text)
        for x in out:
            print(x)

if __name__ == "__main__":
    main()