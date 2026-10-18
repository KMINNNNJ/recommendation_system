"""Run from repository root: python -m optimized.benchmark (offline)."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np

from optimized.src.recommendation import sephora_lightfm as improved
from src.recommendation import sephora_lightfm as original


def timed(function):
    start = perf_counter()
    result = function()
    return result, perf_counter() - start


def main():
    improved.clear_model_cache()
    bundle, cold = timed(improved.load_model)
    cached, warm = timed(improved.load_model)
    assert bundle is cached
    ids = list(bundle["item_id_map"])[:500]
    before, original_time = timed(lambda: original.recommend_new_user_from_candidates(ids, top_n=10))
    after, improved_time = timed(lambda: improved.recommend_new_user_from_candidates(ids, top_n=10))
    assert before == after, "Real-model recommendation results differ"
    rng = np.random.default_rng(42)
    scores = rng.normal(size=100_000).astype(np.float32)
    candidates = [str(index) for index in range(len(scores))]
    ranked_before, full_sort = timed(lambda: original._build_ranked_results(candidates, scores, 10))
    ranked_after, top_k = timed(lambda: improved._build_ranked_results(candidates, scores, 10))
    assert ranked_before == ranked_after
    report = {
        "note": "Single local run; not an end-to-end API latency measurement.",
        "model_file_bytes": improved.MODEL_PATH.stat().st_size,
        "cold_model_load_seconds": cold,
        "warm_model_load_seconds": warm,
        "real_model_candidate_count": len(ids),
        "original_recommend_seconds": original_time,
        "optimized_warm_recommend_seconds": improved_time,
        "real_model_results_equal": True,
        "synthetic_candidate_count": len(scores),
        "full_sort_seconds": full_sort,
        "top_k_seconds": top_k,
        "synthetic_results_equal": True,
    }
    path = Path(__file__).resolve().parent / "benchmark_results.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
