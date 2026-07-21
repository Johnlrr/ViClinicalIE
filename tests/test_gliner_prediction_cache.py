from __future__ import annotations

from src.ner.prediction_cache import PredictionCache, build_cache_key


def test_prediction_cache_round_trip_and_corruption(tmp_path) -> None:
    cache = PredictionCache(tmp_path)
    key = build_cache_key({"input_hash": "x", "model_hash": "y"})
    cache.put(key, [{"text": "sốt"}])
    assert cache.get(key) == [{"text": "sốt"}]
    (tmp_path / f"{key}.json").write_text("not-json", encoding="utf-8")
    assert cache.get(key) is None