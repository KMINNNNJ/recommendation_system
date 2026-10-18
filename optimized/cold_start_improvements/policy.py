"""Explicit candidate constraints and deterministic diversity reranking."""
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from optimized.cold_start_benchmark.experiment import clean, ingredient_tokens


def candidate_mask(products, category=None, max_price_usd=None, excluded_ingredients=()):
    mask = np.ones(len(products), dtype=bool)
    if category:
        # Exact catalogue category, not a regex or product-name heuristic.
        mask &= products.secondary_category.map(clean).eq(clean(category)).to_numpy()
    if max_price_usd is not None:
        if not np.isfinite(max_price_usd) or max_price_usd < 0:
            raise ValueError("max_price_usd must be finite and nonnegative")
        mask &= pd.to_numeric(products.price_usd, errors="coerce").le(max_price_usd).to_numpy()
    excluded = {clean(value) for value in excluded_ingredients if clean(value) != "unknown"}
    if excluded:
        # Exact parsed ingredient names only. Missing lists are excluded because
        # their compliance cannot be established; no allergy/safety guarantee.
        tokens = products.ingredients.map(ingredient_tokens)
        mask &= tokens.map(lambda values: bool(values) and excluded.isdisjoint(values)).to_numpy()
    return mask


def ingredient_similarity(products):
    tokens = products.ingredients.map(ingredient_tokens).tolist()
    if not any(tokens):
        return np.zeros((len(products), len(products)), dtype=np.float32)
    # IDF downweights common ingredients such as water; the result is similarity,
    # not an assertion about efficacy or ingredient concentrations.
    matrix = TfidfVectorizer(analyzer=lambda row: row, dtype=np.float32).fit_transform(tokens)
    return np.clip((matrix @ matrix.T).toarray(), 0, 1)


def rerank(scores, candidates, brands, similarity, weight=0.0, k=10, pool_size=200):
    if not 0 <= weight <= 1 or k < 1 or pool_size < k:
        raise ValueError("Invalid reranking parameters")
    scores = np.asarray(scores)
    candidates = np.asarray(candidates, dtype=int)
    if scores.ndim != 2 or not np.isfinite(scores).all():
        raise ValueError("Expected finite two-dimensional scores")
    if not len(candidates):
        return np.empty((len(scores), 0), dtype=int)
    # Sorted catalogue index breaks ties by product_id, shared with baseline.
    candidates = np.sort(candidates)
    pools = candidates[np.argsort(-scores[:, candidates], axis=1, kind="stable")[:, :pool_size]]
    size = min(k, len(candidates))
    if weight == 0:
        return pools[:, :size]
    result = np.empty((len(scores), size), dtype=int)
    for row, pool in enumerate(pools):
        values = scores[row, pool]
        relevance = (values - values.min()) / max(float(np.ptp(values)), 1e-12)
        penalty = np.zeros(len(pool), dtype=np.float32)
        available = np.ones(len(pool), dtype=bool)
        for rank in range(size):
            objective = (1-weight) * relevance - weight * penalty
            objective[~available] = -np.inf
            chosen = int(np.argmax(objective))
            item = pool[chosen]
            result[row, rank] = item
            available[chosen] = False
            same_brand = (brands[pool] == brands[item]) & (brands[item] != "unknown")
            penalty = np.maximum(penalty, .5 * same_brand + .5 * similarity[pool, item])
    return result


def ranking_metrics(evaluation, top, candidates, products, similarity):
    """Conditional relevance: only positives inside the fixed category count.

    Rows without a positive in that category are excluded and counted explicitly.
    The category is an oracle request proxy, not learned query prediction.
    """
    allowed = set(map(int, candidates))
    brands = products.brand_name.map(clean).to_numpy()
    skins = evaluation.unique_profiles.skin_type.to_numpy()
    rows = []
    used = set()
    for uid, profile_index in zip(evaluation.users.author_id, evaluation.profile_index):
        truth = evaluation.positive[uid] & allowed
        if not truth:
            continue
        selected = top[profile_index]
        used.update(map(int, selected))
        hits = np.array([item in truth for item in selected], dtype=float)
        length = len(selected)
        dcg = float(np.sum(hits / np.log2(np.arange(length)+2)))
        idcg = float(np.sum(1 / np.log2(np.arange(min(len(truth), length))+2)))
        negative = evaluation.negative.get(uid, set())
        pairs = similarity[np.ix_(selected, selected)]
        pair_mean = float(pairs[np.triu_indices(length, 1)].mean()) if length > 1 else 0.0
        rows.append({"author_id":uid, "skin_type":skins[profile_index],
                     "precision@10":float(hits.sum()/length) if length else 0.0,
                     "recall@10":float(hits.sum()/len(truth)), "ndcg@10":dcg/idcg if idcg else 0.0,
                     "hit_rate@10":float(hits.any()),
                     "known_negative@10":sum(item in negative for item in selected)/length if length else 0.0,
                     "unique_brands@10":len(set(brands[selected]) - {"unknown"}),
                     "ingredient_similarity@10":pair_mean})
    detail = pd.DataFrame(rows)
    columns = ["precision@10", "recall@10", "ndcg@10", "hit_rate@10", "known_negative@10",
               "unique_brands@10", "ingredient_similarity@10"]
    metrics = {column:float(detail[column].mean()) if len(detail) else None for column in columns}
    metrics.update(evaluated_users=len(detail), sampled_users=len(evaluation.users),
                   excluded_no_category_positive=len(evaluation.users)-len(detail),
                   candidate_items=len(candidates), recommended_items=len(used),
                   catalogue_coverage_at_10=len(used)/len(candidates) if len(candidates) else 0.0)
    return metrics, detail
