from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from src.data_types import VALID_ENTITY_TYPES


GENERATOR_VERSION = "ner5-v1.0.0"
MARKER_RE = re.compile(r"\[\[(/?)E(\d+)\]\]")


def load_concept_inventory(config: Mapping[str, Any], project_root: str | Path) -> dict[str, list[dict[str, str]]]:
    root = Path(project_root)
    limits = dict(config.get("concepts_per_type", {}))
    symptoms = _read_csv_concepts(root / str(config["sources"]["symptoms"]), "alias", "canonical", None)
    labs = _read_csv_concepts(root / str(config["sources"]["labs"]), "alias", "canonical", None)
    diagnosis_manual = _read_csv_concepts(
        root / str(config["sources"]["diagnosis_manual"]), "alias", "canonical_hint", "code_hint",
    )
    diagnosis = _read_parquet_concepts(
        root / str(config["sources"]["diagnosis"]), "alias", "code",
        filters=lambda row: (
            str(row.get("alias_lang", "")) == "vi"
            and str(row.get("alias_source", "")) == "disease_name_vi"
            and not bool(row.get("is_group_alias", False))
            and _diagnosis_code_allowed(str(row.get("code", "")))
            and _clean_diagnosis_surface(str(row.get("alias", "")))
        ),
    )
    drugs_manual = _read_csv_concepts(
        root / str(config["sources"]["drugs_manual"]), "alias", "generic_hint", "rxcui_hint",
    )
    drugs = _read_parquet_concepts(
        root / str(config["sources"]["drugs"]), "alias", "rxcui",
        filters=lambda row: (
            str(row.get("tty", "")) in {"IN", "PIN", "MIN", "BN"}
            and _clean_drug_surface(str(row.get("alias", "")))
        ),
    )
    diagnosis_limit = int(limits.get("CHẨN_ĐOÁN", 20))
    drug_limit = int(limits.get("THUỐC", 20))
    return {
        "TRIỆU_CHỨNG": _select_concepts(symptoms, int(limits.get("TRIỆU_CHỨNG", 20))),
        "CHẨN_ĐOÁN": _merge_priority_concepts(diagnosis_manual, diagnosis, diagnosis_limit),
        "THUỐC": _merge_priority_concepts(drugs_manual, drugs, drug_limit),
        "TÊN_XÉT_NGHIỆM": _select_concepts(labs, int(limits.get("TÊN_XÉT_NGHIỆM", 20))),
    }


def generate_task_aligned_samples(
    inventory: Mapping[str, Sequence[Mapping[str, str]]], *, seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    counters: dict[str, int] = {key: 0 for key in VALID_ENTITY_TYPES}

    for entity_type in ("TRIỆU_CHỨNG", "CHẨN_ĐOÁN", "THUỐC"):
        for index, concept in enumerate(inventory.get(entity_type, [])):
            surface = str(concept["surface"])
            concept_id = str(concept.get("concept_id") or _slug(surface))
            if entity_type == "TRIỆU_CHỨNG":
                templates = [
                    ("symptom_present", f"Bệnh nhân ghi nhận [[E0]]{surface}[[/E0]]."),
                    ("symptom_negated", f"Bệnh nhân không có [[E0]]{surface}[[/E0]]."),
                ]
            elif entity_type == "CHẨN_ĐOÁN":
                templates = [
                    ("diagnosis_confirmed", f"Chẩn đoán hiện tại: [[E0]]{surface}[[/E0]]."),
                    ("diagnosis_suspected", f"Bác sĩ nghi ngờ [[E0]]{surface}[[/E0]]."),
                ]
            else:
                suffix = ("25 mg po bid", "10 mg uống hàng ngày")[index % 2]
                formulation = f"{surface} {suffix}"
                templates = [
                    ("drug_name", f"Thuốc đang dùng: [[E0]]{surface}[[/E0]]."),
                    ("drug_full_formulation", f"Điều trị với [[E0]]{formulation}[[/E0]]."),
                ]
            for family, marked in templates:
                rows.append(_from_marked_text(
                    file_id=f"clean_{_short_type(entity_type)}_{counters[entity_type]:05d}",
                    marked_text=marked, entity_types=[entity_type], source="task_aligned_synthetic",
                    confidence_tier="TASK_ALIGNED_BY_CONSTRUCTION", seed=seed,
                    template_family=family, concept_families=[f"{_short_type(entity_type)}:{concept_id}"],
                    concept_ids=[concept_id], noise_profile="clean",
                ))
                counters[entity_type] += 1

    results = ("12 mg/L", "6,3 mmol/L", "âm tính", "dương tính", "bình thường", "tăng nhẹ")
    for index, concept in enumerate(inventory.get("TÊN_XÉT_NGHIỆM", [])):
        test = str(concept["surface"])
        concept_id = str(concept.get("concept_id") or _slug(test))
        result = results[index % len(results)]
        marked = f"Kết quả [[E0]]{test}[[/E0]]: [[E1]]{result}[[/E1]]."
        rows.append(_from_marked_text(
            file_id=f"clean_test_result_{index:05d}", marked_text=marked,
            entity_types=["TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"],
            source="task_aligned_synthetic", confidence_tier="TASK_ALIGNED_BY_CONSTRUCTION",
            seed=seed, template_family="test_result_pair",
            concept_families=[f"test:{concept_id}", f"result:{concept_id}"],
            concept_ids=[concept_id, concept_id], noise_profile="clean",
        ))

    imaging_rows = [
        ("MRI sọ não", "tổn thương kích thước 3,7 x 0,7 cm", "KẾT_QUẢ_XÉT_NGHIỆM"),
        ("chụp cắt lớp vi tính ngực", "bóc tách động mạch chủ Stanford loại B", "CHẨN_ĐOÁN"),
        ("siêu âm gan mật", "giãn đường mật", "KẾT_QUẢ_XÉT_NGHIỆM"),
    ]
    for index, (test, finding, finding_type) in enumerate(imaging_rows):
        rows.append(_from_marked_text(
            file_id=f"clean_imaging_{index:05d}",
            marked_text=f"[[E0]]{test}[[/E0]] ghi nhận [[E1]]{finding}[[/E1]].",
            entity_types=["TÊN_XÉT_NGHIỆM", finding_type], source="task_aligned_synthetic",
            confidence_tier="TASK_ALIGNED_BY_CONSTRUCTION", seed=seed,
            template_family="imaging_procedure_finding",
            concept_families=[f"imaging_test:{index}", f"imaging_finding:{index}"],
            concept_ids=[f"imaging:{index}", f"imaging:{index}"], noise_profile="clean",
        ))

    negatives = [
        ("hard_negative_bare_number", "Kết quả được ghi nhận là 12."),
        ("hard_negative_section", "THUỐC ĐANG DÙNG"),
        ("hard_negative_substance", "Bệnh nhân uống cà phê mỗi sáng."),
        ("hard_negative_followup", "Bệnh nhân đến tái khám định kỳ."),
    ]
    for index, (family, text) in enumerate(negatives):
        rows.append({
            "file_id": f"clean_negative_{index:05d}", "text": text,
            "source": "task_aligned_synthetic", "confidence_tier": "TASK_ALIGNED_BY_CONSTRUCTION",
            "generator_version": GENERATOR_VERSION, "seed": seed, "entities": [],
        })
    rng.shuffle(rows)
    return sorted(rows, key=lambda item: item["file_id"])


def generate_noisy_samples(clean_samples: Sequence[Mapping[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    transformations: tuple[tuple[str, Callable[[str], str]], ...] = (
        ("no_diacritics", _remove_diacritics),
        ("missing_whitespace", _remove_spaces),
        ("repeated_token", _repeat_first_token),
        ("single_typo", _drop_first_internal_vowel),
    )
    output: list[dict[str, Any]] = []
    for index, sample in enumerate(clean_samples):
        if not sample.get("entities"):
            continue
        name, transform = transformations[index % len(transformations)]
        noisy = _transform_sample(sample, transform, name=name, seed=seed)
        if noisy["text"] == sample["text"]:
            name, transform = "missing_whitespace", _remove_spaces
            noisy = _transform_sample(sample, transform, name=name, seed=seed)
        output.append(noisy)
    return sorted(output, key=lambda item: item["file_id"])


def convert_gold_split(
    *, input_dir: str | Path, gold_dir: str | Path, ids: Iterable[int | str], split: str, seed: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    samples: list[dict[str, Any]] = []
    stats = {"input_entities": 0, "accepted_entities": 0, "rejected_duplicate_or_overlap": 0}
    for value in ids:
        file_id = str(value)
        text = (Path(input_dir) / f"{file_id}.txt").read_text(encoding="utf-8")
        rows = json.loads((Path(gold_dir) / f"{file_id}.json").read_text(encoding="utf-8"))
        stats["input_entities"] += len(rows)
        selected = _select_non_overlapping_gold(rows)
        stats["accepted_entities"] += len(selected)
        stats["rejected_duplicate_or_overlap"] += len(rows) - len(selected)
        entities = []
        for index, row in enumerate(selected):
            start, end = map(int, row["position"][:2])
            entity_type = unicodedata.normalize("NFC", str(row["type"]))
            if entity_type not in VALID_ENTITY_TYPES or text[start:end] != row["text"]:
                continue
            entities.append({
                "text": text[start:end], "start": start, "end": end, "type": entity_type,
                "source": "competition_gold",
                "metadata": {
                    "template_family": f"legacy_gold:{split}:{file_id}",
                    "concept_family": f"legacy_gold:{split}:{file_id}:{index}",
                    "noise_profile": "legacy_gold_v1", "concept_id": None,
                },
            })
        samples.append({
            "file_id": f"{split}_{file_id}", "text": text, "source": "competition_gold",
            "confidence_tier": "GOLD_VERIFIED", "generator_version": GENERATOR_VERSION,
            "seed": seed, "entities": entities,
        })
    return samples, stats


def dataset_hash(samples: Sequence[Mapping[str, Any]]) -> str:
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in samples)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _from_marked_text(
    *, file_id: str, marked_text: str, entity_types: Sequence[str], source: str,
    confidence_tier: str, seed: int, template_family: str,
    concept_families: Sequence[str], concept_ids: Sequence[str | None], noise_profile: str,
) -> dict[str, Any]:
    plain_parts: list[str] = []
    positions: dict[int, list[int | None]] = {}
    cursor = 0
    plain_length = 0
    for match in MARKER_RE.finditer(marked_text):
        segment = marked_text[cursor:match.start()]
        plain_parts.append(segment)
        plain_length += len(segment)
        marker_id = int(match.group(2))
        positions.setdefault(marker_id, [None, None])[1 if match.group(1) else 0] = plain_length
        cursor = match.end()
    plain_parts.append(marked_text[cursor:])
    text = "".join(plain_parts)
    entities: list[dict[str, Any]] = []
    for marker_id, entity_type in enumerate(entity_types):
        start, end = positions.get(marker_id, [None, None])
        if start is None or end is None or start >= end:
            raise ValueError(f"Invalid entity markers in {file_id}: E{marker_id}")
        entities.append({
            "text": text[start:end], "start": start, "end": end, "type": entity_type,
            "source": "marker_construction",
            "metadata": {
                "template_family": template_family,
                "concept_family": concept_families[marker_id],
                "noise_profile": noise_profile,
                "concept_id": concept_ids[marker_id],
            },
        })
    return {
        "file_id": file_id, "text": text, "source": source,
        "confidence_tier": confidence_tier, "generator_version": GENERATOR_VERSION,
        "seed": seed, "entities": entities,
    }


def _transform_sample(sample: Mapping[str, Any], transform: Callable[[str], str], *, name: str, seed: int) -> dict[str, Any]:
    text = str(sample["text"])
    entities = sorted(sample.get("entities", []), key=lambda item: (int(item["start"]), int(item["end"])))
    parts: list[str] = []
    output_entities: list[dict[str, Any]] = []
    cursor = 0
    output_length = 0
    for entity in entities:
        start, end = int(entity["start"]), int(entity["end"])
        prefix = transform(text[cursor:start])
        transformed_entity = transform(text[start:end])
        parts.append(prefix)
        output_length += len(prefix)
        new_start = output_length
        parts.append(transformed_entity)
        output_length += len(transformed_entity)
        updated = deepcopy(entity)
        updated.update({"text": transformed_entity, "start": new_start, "end": output_length})
        metadata = dict(updated["metadata"])
        metadata.update({
            "noise_profile": name, "original_sample_id": str(sample["file_id"]),
            "transformations": [name],
        })
        updated["metadata"] = metadata
        output_entities.append(updated)
        cursor = end
    parts.append(transform(text[cursor:]))
    return {
        "file_id": f"noisy_{sample['file_id']}_{name}", "text": "".join(parts),
        "source": "competition_noise_augmentation", "confidence_tier": "AUGMENTED_HIGH",
        "generator_version": GENERATOR_VERSION, "seed": seed, "entities": output_entities,
    }


def _select_non_overlapping_gold(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    valid = []
    seen: set[tuple[int, int, str]] = set()
    for row in rows:
        try:
            start, end = map(int, row.get("position", [0, 0])[:2])
        except (TypeError, ValueError):
            continue
        key = (start, end, unicodedata.normalize("NFC", str(row.get("type", ""))))
        if key in seen:
            continue
        seen.add(key)
        valid.append((start, end, row))
    valid.sort(key=lambda item: (item[0], -(item[1] - item[0]), str(item[2].get("type", ""))))
    selected = []
    cursor = -1
    for start, end, row in valid:
        if start < cursor:
            continue
        selected.append(row)
        cursor = end
    return selected


def _read_csv_concepts(path: Path, surface_col: str, canonical_col: str, id_col: str | None) -> list[dict[str, str]]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    return [
        {
            "surface": str(row[surface_col]),
            "concept_id": str((row.get(id_col, "") if id_col else "") or row.get(canonical_col, "")),
        }
        for row in frame.to_dict("records")
    ]


def _read_parquet_concepts(path: Path, surface_col: str, id_col: str, filters) -> list[dict[str, str]]:
    frame = pd.read_parquet(path)
    return [
        {"surface": str(row.get(surface_col, "")), "concept_id": str(row.get(id_col, ""))}
        for row in frame.to_dict("records") if filters(row)
    ]


def _select_concepts(rows: Sequence[Mapping[str, str]], limit: int) -> list[dict[str, str]]:
    seen: set[str] = set()
    eligible: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda item: (str(item.get("surface", "")).casefold(), str(item.get("concept_id", "")))):
        surface = unicodedata.normalize("NFC", str(row.get("surface", "")).strip())
        key = surface.casefold()
        if key in seen or not _valid_surface(surface):
            continue
        seen.add(key)
        eligible.append({"surface": surface, "concept_id": str(row.get("concept_id", ""))})
    if len(eligible) <= limit:
        return eligible
    # Deterministically cover the full terminology instead of taking an
    # alphabetically biased prefix.
    indices = [round(index * (len(eligible) - 1) / (limit - 1)) for index in range(limit)]
    return [eligible[index] for index in indices]


def _merge_priority_concepts(
    preferred: Sequence[Mapping[str, str]], fallback: Sequence[Mapping[str, str]], limit: int,
) -> list[dict[str, str]]:
    preferred_limit = min(len(preferred), max(1, limit // 2))
    selected = _select_concepts(preferred, preferred_limit)
    seen = {row["surface"].casefold() for row in selected}
    for row in _select_concepts(fallback, limit):
        if row["surface"].casefold() in seen:
            continue
        selected.append(row)
        seen.add(row["surface"].casefold())
        if len(selected) >= limit:
            break
    return selected


def _valid_surface(surface: str) -> bool:
    return 3 <= len(surface) <= 80 and any(char.isalpha() for char in surface) and "\n" not in surface


def _clean_diagnosis_surface(surface: str) -> bool:
    lowered = surface.casefold()
    return (
        _valid_surface(surface)
        and not surface.lstrip().startswith(("-", "+", "*"))
        and "loại trừ:" not in lowered
        and "†" not in surface
        and len(surface.split()) <= 12
    )


def _diagnosis_code_allowed(code: str) -> bool:
    # A-Q contains named diseases/disorders and congenital conditions. Exclude
    # symptom, injury/external-cause and encounter-factor chapters for the clean
    # diagnosis construction set.
    return bool(code and "A" <= code[0].upper() <= "Q")


def _clean_drug_surface(surface: str) -> bool:
    return bool(
        3 <= len(surface) <= 40
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9 -]*", surface)
        and len(surface.split()) <= 5
        and not re.search(r"\d{2,}", surface)
    )


def _remove_diacritics(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")


def _remove_spaces(text: str) -> str:
    return text.replace(" ", "", 1)


def _repeat_first_token(text: str) -> str:
    match = re.search(r"[A-Za-zÀ-ỹĐđ]{2,}", text)
    if not match:
        return text
    token = match.group(0)
    return text[:match.end()] + token + text[match.end():]


def _drop_first_internal_vowel(text: str) -> str:
    match = re.search(r"(?<=[A-Za-zÀ-ỹĐđ])[aeiouyăâêôơưAEIOUYĂÂÊÔƠƯ](?=[A-Za-zÀ-ỹĐđ])", text)
    if not match:
        return text
    return text[:match.start()] + text[match.end():]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _remove_diacritics(value).lower()).strip("_")


def _short_type(entity_type: str) -> str:
    return {
        "TRIỆU_CHỨNG": "symptom", "CHẨN_ĐOÁN": "diagnosis", "THUỐC": "drug",
        "TÊN_XÉT_NGHIỆM": "test", "KẾT_QUẢ_XÉT_NGHIỆM": "result",
    }[entity_type]