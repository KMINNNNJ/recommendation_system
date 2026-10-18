import tempfile
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from optimized.cold_start_benchmark.experiment import (
    Evaluation, PROFILE, Features, label_reviews, review_fingerprint,
    split_users, baseline_scores,
    prepare,
)


class BenchmarkTests(unittest.TestCase):
    def test_users_are_disjoint_and_split_is_reproducible(self):
        ids = [str(i) for i in range(1000)]
        first = split_users(ids)
        pd.testing.assert_frame_equal(first, split_users(ids[::-1]))
        self.assertEqual(first.groupby("split").size().to_dict(),
                         {"train": 700, "validation": 150, "test": 150})
        self.assertFalse(first.author_id.duplicated().any())

    def test_positive_negative_ambiguous_and_conflicting_ratings(self):
        df = pd.DataFrame({"rating": [5,4,4,3,2,1,3],
                           "is_recommended": [1,np.nan,0,np.nan,1,0,0]})
        self.assertEqual(label_reviews(df).tolist(), [1,1,0,-1,0,0,0])

    def test_review_fingerprint_ignores_order_and_saved_index_only(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/"a.csv", Path(directory)/"b.csv"
            pd.DataFrame({"author_id":["a","b"],"review_text":["line\nbreak", "nice"], "rating":[4,5]}).to_csv(first)
            pd.DataFrame({"rating":[5,4],"review_text":["nice","line\nbreak"],"author_id":["b","a"]}).to_csv(second,index=False)
            self.assertEqual(review_fingerprint([first]),review_fingerprint([second]))
            pd.DataFrame({"rating":[5,2],"review_text":["nice","line\nbreak"],"author_id":["b","a"]}).to_csv(second,index=False)
            self.assertNotEqual(review_fingerprint([first]),review_fingerprint([second]))

    def test_ranking_metrics_and_ties_are_exact(self):
        products = pd.DataFrame({"product_id": ["a","b","c","d","e","f","g","h","i","j","k"]})
        frame=pd.DataFrame({"author_id":["u","u","u"], "product_id":["a","c","k"],"label":[1,1,0],"split":["test"]*3,
                            **{col:["unknown"]*3 for col in PROFILE}})
        evaluation=Evaluation(frame,"test",products,0)
        metric, detail, top=evaluation.evaluate(np.zeros((1,11)))
        self.assertEqual(top.tolist(),[list(range(10))])
        self.assertEqual(metric["recall@10"],1.0)
        self.assertEqual(metric["precision@10"],.2)
        self.assertEqual(metric["known_negative@10"],0)
        expected=(1+1/np.log2(4))/(1+1/np.log2(3))
        self.assertAlmostEqual(metric["ndcg@10"],expected)

    def test_baseline_never_uses_catalogue_aggregate_ratings(self):
        products=pd.DataFrame({"product_id":["a","b"],"ingredients":["['water']","['water']"],"price_usd":[10,20],
                               **{col:["x","y"] for col in ["brand_name","secondary_category","tertiary_category","variation_type"]}})
        profiles=pd.DataFrame({col:["unknown"] for col in PROFILE})
        features=Features(products,profiles)
        train=pd.DataFrame({"product_id":["a","a","b"],"label":[1,1,0],"skin_type":["unknown"]*3})
        scores=baseline_scores(train,features,profiles)
        self.assertGreater(scores[0,0],scores[0,1])
        self.assertNotIn("rating",features.tree_products)
        self.assertNotIn("reviews",features.tree_products)
        self.assertEqual(features.tree_pairs(pd.DataFrame({"product_id":["b"],**{col:["unknown"] for col in PROFILE}})).iloc[0]["brand_name"],"y")

    def test_prepare_freezes_first_profile_and_training_vocabulary(self):
        ids=[f"u{i}" for i in range(20)]
        split=split_users(ids)
        heldout=split.loc[split.split.eq("test"),"author_id"].iloc[0]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/"output";output.mkdir()
            pd.DataFrame({"product_id":["p"],"primary_category":["Skincare"]}).to_csv(root/"product_info.csv",index=False)
            rows=[]
            for uid in ids:
                for date,skin,rating in [("2020-01-01","unseen-value" if uid==heldout else "dry",5),
                                         ("2022-01-01","oily",1)]:
                    rows.append({"author_id":uid,"product_id":"p","submission_time":date,"rating":rating,
                                 "is_recommended":int(rating==5),"skin_type":skin,
                                 "skin_tone":"light","eye_color":"brown","hair_color":"black"})
            pd.DataFrame(rows).to_csv(root/"reviews_all.csv",index=False)
            _,reviews,profiles=prepare(root,output,audit=False)
            self.assertEqual(len(reviews),20)
            self.assertTrue(reviews.label.eq(0).all())
            self.assertEqual(profiles.set_index("author_id").loc[heldout,"skin_type"],"unknown")
            self.assertEqual(set(profiles.loc[profiles.author_id.ne(heldout),"skin_type"]),{"dry"})

    def test_original_comparator_uses_original_api_new_user_vector(self):
        from optimized.cold_start_benchmark.compare_original import original_user_features
        from src.recommendation.sephora_lightfm import build_new_user_feature_matrix
        mapping={"training_user":0,"skin_type:dry":1,"skin_type:unknown":2,
                 "skin_tone:unknown":3,"eye_color:unknown":4,"hair_color:unknown":5}
        for skin in ["dry","unseen-skin-type","unknown"]:
            profile={"skin_type":skin,"skin_tone":"unknown","eye_color":"unknown","hair_color":"unknown"}
            actual=original_user_features(pd.DataFrame([profile]),mapping)
            expected=build_new_user_feature_matrix(mapping,**profile)
            np.testing.assert_allclose(actual.toarray(),expected.toarray(),rtol=0,atol=0)
            self.assertEqual(actual.toarray()[0,0],0)


if __name__ == "__main__":
    unittest.main()
