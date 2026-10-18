"""Offline regression tests. No API, S3, DB, or Airflow task is executed."""

import ast
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch, Mock

import numpy as np
import pandas as pd

from optimized.src.recommendation import sephora_lightfm as improved
from src.recommendation import sephora_lightfm as original


ROOT = Path(__file__).resolve().parents[1]


def read_functions(path, names, extra=None):
    """Load pure functions only, avoiding DAG registration and service clients."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"pd": pd, "re": re, "logger": logging.getLogger(__name__)}
    namespace.update(extra or {})
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class BucketConfigTests(unittest.TestCase):
    def test_dags_require_explicit_bucket_without_contacting_aws(self):
        for name in ("review_pipeline.py", "ingredient_pipeline.py"):
            boto = Mock()
            functions = read_functions(ROOT / "airflow/dags" / name, {"get_s3_client"},
                                       {"BUCKET_NAME": None, "AWS_REGION": "ap-northeast-2", "boto3": boto})
            with self.assertRaisesRegex(ValueError, "S3_BUCKET_NAME"):
                functions["get_s3_client"]()
            boto.client.assert_not_called()
            functions["BUCKET_NAME"] = "example-bucket"
            self.assertIs(functions["get_s3_client"](), boto.client.return_value)


class RankingTests(unittest.TestCase):
    def test_ranking_matches_original_with_ties_and_slice_boundaries(self):
        rng = np.random.default_rng(42)
        for size in (0, 1, 30, 1000):
            ids = [str(index) for index in range(size)]
            scores = rng.integers(-4, 5, size=size).astype(np.float32)
            for count in (-2, 0, 1, 10, size + 2):
                self.assertEqual(
                    original._build_ranked_results(ids, scores, count),
                    improved._build_ranked_results(ids, scores, count),
                )

    def test_nonfinite_scores_keep_original_order(self):
        scores = np.array([1, np.nan, 3, np.inf, -np.inf])
        before = original._build_ranked_results(list("abcde"), scores, 4)
        after = improved._build_ranked_results(list("abcde"), scores, 4)
        self.assertEqual([row["product_id"] for row in before],
                         [row["product_id"] for row in after])

    def test_profile_features_unchanged(self):
        mapping = {"skin_type:oily": 0, "skin_tone:unknown": 1,
                   "eye_color:unknown": 2, "hair_color:unknown": 3}
        before = original.build_new_user_feature_matrix(mapping, skin_type=" OILY ")
        after = improved.build_new_user_feature_matrix(mapping, skin_type=" OILY ")
        np.testing.assert_array_equal(before.toarray(), after.toarray())


class ModelCacheTests(unittest.TestCase):
    def tearDown(self):
        improved.clear_model_cache()

    def test_concurrent_requests_load_once_and_changes_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            model_path.write_bytes(b"one")
            with patch.object(improved, "MODEL_PATH", model_path), \
                    patch.object(improved, "_read_model_bundle", return_value={"model": "first"}) as reader:
                improved.clear_model_cache()
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: improved.load_model(), range(16)))
                self.assertEqual(reader.call_count, 1)
                self.assertTrue(all(item is results[0] for item in results))
                model_path.write_bytes(b"different length")
                reader.return_value = {"model": "second"}
                self.assertEqual(improved.load_model()["model"], "second")
                self.assertEqual(reader.call_count, 2)
                improved.clear_model_cache()
                improved.load_model()
                self.assertEqual(reader.call_count, 3)

    def test_failed_load_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            model_path.write_bytes(b"model")
            with patch.object(improved, "MODEL_PATH", model_path), \
                    patch.object(improved, "_read_model_bundle", side_effect=[ValueError("invalid"), {"model": "ok"}]) as reader:
                improved.clear_model_cache()
                with self.assertRaises(ValueError):
                    improved.load_model()
                self.assertEqual(improved.load_model(), {"model": "ok"})
                self.assertEqual(reader.call_count, 2)


class DataTests(unittest.TestCase):
    def test_product_filter_matches_original(self):
        relative = Path("src/cosmetics/ingredients/ingredient_repository.py")
        names = {"filter_products_by_product_type", "normalize_product_type"}
        extra = {"PRODUCT_TYPE_KEYWORDS": {"cream": ["cream", "moisturizer"]}}
        before = read_functions(ROOT.parent / relative, names, extra)
        after = read_functions(ROOT / relative, names, extra)
        products = pd.DataFrame({
            "product_name": ["CREAM", "serum", None, "C++", "day"],
            "primary_category": [None, "moisturizer", None, "other", "cream"],
        }, index=[5, 3, 8, 1, 4])
        for kind in (None, "", "cream", "C++", "day cream", "missing"):
            pd.testing.assert_frame_equal(
                before["filter_products_by_product_type"](products, kind),
                after["filter_products_by_product_type"](products, kind),
            )

    def test_batch_values_order_nulls_and_large_integers(self):
        for name in ("review_pipeline.py", "ingredient_pipeline.py"):
            functions = read_functions(ROOT / "airflow/dags" / name,
                                       {"_insert_dataframe", "_to_db_value"})
            calls = []
            class Cursor:
                def executemany(self, sql, rows):
                    calls.append((sql, rows))
            frame = pd.DataFrame({"id": [2**60 + 1, 2**60 + 3, 9],
                                  "score": [1.5, np.nan, 4.0],
                                  "unused": ["x", "y", "z"]})
            functions["_insert_dataframe"](Cursor(), "example", frame,
                                            ["score", "id"], batch_size=2)
            self.assertEqual(len(calls), 2)
            rows = [row for _, batch in calls for row in batch]
            self.assertEqual(rows, [(1.5, 2**60 + 1), (None, 2**60 + 3), (4.0, 9)])
            self.assertIn("`score`, `id`", calls[0][0])

    def test_empty_batches_do_not_insert(self):
        for name in ("review_pipeline.py", "ingredient_pipeline.py"):
            functions = read_functions(ROOT / "airflow/dags" / name,
                                       {"_insert_dataframe", "_to_db_value"})
            class Cursor:
                def executemany(self, *args):
                    raise AssertionError("Empty frame must not issue an insert")
            functions["_insert_dataframe"](Cursor(), "example", pd.DataFrame({"id": []}), ["id"])


if __name__ == "__main__":
    unittest.main()
