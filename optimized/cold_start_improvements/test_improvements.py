import unittest

from optimized.cold_start_benchmark.experiment import Evaluation, PROFILE, np, pd
from .experiment import paired_difference, select_policy
from .policy import candidate_mask, ingredient_similarity, ranking_metrics, rerank


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.products=pd.DataFrame({"product_id":["a","b","c","d"],
            "secondary_category":["Serums","Serums","Moisturizers","Serums"],
            "brand_name":["A","A","B","C"],"price_usd":[10,20,30,np.nan],
            "ingredients":["['water, glycerin']","['water, glycerin']","['water, oil']",np.nan]})
        self.similarity=ingredient_similarity(self.products)

    def test_constraints_intersect_and_missing_ingredients_are_not_verified(self):
        self.assertEqual(candidate_mask(self.products,"serums",15).tolist(),[True,False,False,False])
        self.assertEqual(candidate_mask(self.products,excluded_ingredients=["GLYCERIN"]).tolist(),[False,False,True,False])
        self.assertFalse(candidate_mask(self.products,"unknown category").any())
        with self.assertRaises(ValueError):
            candidate_mask(self.products,max_price_usd=-1)

    def test_reranking_is_stable_and_never_escapes_candidates(self):
        scores=np.array([[3.,2.99,2.9,0.]])
        brands=np.array(["a","a","b","c"])
        self.assertEqual(rerank(scores,[2,1,0],brands,self.similarity,0,k=2).tolist(),[[0,1]])
        diverse=rerank(scores,[0,1,2],brands,self.similarity,.8,k=2)
        self.assertEqual(diverse.tolist(),[[0,2]])
        self.assertEqual(rerank(np.zeros((1,4)),[2,0],brands,self.similarity,0,k=2).tolist(),[[0,2]])
        self.assertEqual(rerank(scores,[],brands,self.similarity,k=2).shape,(1,0))

    def test_conditional_truth_excludes_other_categories_and_counts_excluded_users(self):
        reviews=pd.DataFrame({"author_id":["u1","u1","u1","u2"],
            "product_id":["a","c","b","c"],"label":[1,1,0,1],"split":["test"]*4,
            **{col:["unknown"]*4 for col in PROFILE}})
        evaluation=Evaluation(reviews,"test",self.products,0)
        top=np.array([[0,1]])
        metrics,detail=ranking_metrics(evaluation,top,[0,1],self.products,self.similarity)
        self.assertEqual(metrics["evaluated_users"],1)
        self.assertEqual(metrics["excluded_no_category_positive"],1)
        self.assertEqual(metrics["recall@10"],1.)
        self.assertEqual(metrics["known_negative@10"],.5)
        self.assertEqual(metrics["unique_brands@10"],1)
        self.assertAlmostEqual(metrics["ingredient_similarity@10"],1.,places=5)
        self.assertEqual(detail.author_id.tolist(),["u1"])

    def test_selection_obeys_accuracy_budget(self):
        rows=[{"model":"warp","diversity_weight":weight,"ndcg@10":ndcg,
               "catalogue_coverage_at_10":coverage,"unique_brands@10":5}
              for weight,ndcg,coverage in [(0,.1,.03),(.05,.099,.04),(.3,.09,.1)]]
        raw,chosen=select_policy(rows)
        self.assertEqual(raw["diversity_weight"],0)
        self.assertEqual(chosen["diversity_weight"],.05)

    def test_full_catalogue_metrics_match_original_evaluator(self):
        products=pd.concat([self.products.assign(product_id=lambda frame:frame.product_id+str(i))
                            for i in range(3)],ignore_index=True)
        reviews=pd.DataFrame({"author_id":["u1","u1","u1","u2"],
            "product_id":["a0","c2","d2","b0"],"label":[1,1,0,1],"split":["test"]*4,
            **{column:["unknown"]*4 for column in PROFILE}})
        evaluation=Evaluation(reviews,"test",products,0)
        scores=-np.arange(12,dtype=float).reshape(1,-1)
        original,_,top=evaluation.evaluate(scores)
        improved,_=ranking_metrics(evaluation,top,np.arange(12),products,ingredient_similarity(products))
        for metric in ["precision@10","recall@10","ndcg@10","hit_rate@10",
                       "known_negative@10","catalogue_coverage_at_10"]:
            self.assertAlmostEqual(original[metric],improved[metric])

    def test_paired_difference_aligns_users(self):
        a=pd.DataFrame({"author_id":["u1","u2"],"ndcg@10":[.4,.8]})
        b=pd.DataFrame({"author_id":["u2","u1"],"ndcg@10":[.7,.3]})
        result=paired_difference(a,b)
        self.assertAlmostEqual(result["ndcg_difference"],.1)
        self.assertTrue(np.allclose(result["paired_bootstrap_95ci"],[.1,.1]))

    def test_logistic_supports_signed_observations_and_roundtrip(self):
        import tempfile
        from pathlib import Path
        from optimized.cold_start_benchmark.experiment import Features, sparse, joblib, lightfm_scores
        from lightfm import LightFM
        products=self.products.assign(tertiary_category="x",variation_type="x")
        profiles=pd.DataFrame({col:["dry","oily"] if col=="skin_type" else ["unknown"]*2 for col in PROFILE})
        features=Features(products,profiles)
        interactions=sparse.coo_matrix((np.array([1.,-1.,1.],dtype=np.float32),([0,0,1],[0,1,2])),shape=(2,4))
        weights=interactions.copy();weights.data=np.array([1.,.25,1.],dtype=np.float32)
        model=LightFM(loss="logistic",no_components=4,random_state=42)
        model.fit(interactions,sample_weight=weights,user_features=features.user_matrix(profiles),
                  item_features=features.item_matrix,epochs=2,num_threads=1)
        scores=lightfm_scores(model,features,profiles)
        self.assertTrue(np.isfinite(scores).all())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"model.joblib"
            joblib.dump(model,path)
            np.testing.assert_allclose(scores,lightfm_scores(joblib.load(path),features,profiles))


if __name__=="__main__":
    unittest.main()
