"""Integration tests against saved models and Streamlit's real app runner."""
from pathlib import Path
import unittest

from optimized.portfolio.service import DemoModels, comparison_table, ingredient_tokens, pd, ORIGINAL, BENCHMARK


class SavedModelDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models=DemoModels()

    def test_shared_filters_and_original_support(self):
        result=self.models.compare({"skin_type":"dry"},"moisturizers",50,["glycerin"],5)
        catalogue=self.models.products.set_index("product_id")
        original_ids=set(self.models.original["dataset"].mapping()[2])
        for variant in ["original","improved"]:
            self.assertGreater(len(result[variant]),0)
            self.assertLessEqual(len(result[variant]),5)
            for row in result[variant]:
                item=catalogue.loc[row["product_id"]]
                self.assertLessEqual(row["price_usd"],50)
                self.assertEqual(item.secondary_category,"Moisturizers")
                self.assertNotIn("glycerin",ingredient_tokens(item.ingredients))
                if variant=="original":
                    self.assertIn(row["product_id"],original_ids)
        self.assertEqual(self.models.original["epochs"],30)

    def test_empty_candidates_and_unsupported_profile(self):
        result=self.models.compare({"skin_type":"unseen"},"moisturizers",0,top_k=5)
        self.assertEqual(result["candidate_count"],0)
        self.assertEqual(result["original"],[])
        self.assertEqual(result["improved"],[])
        self.assertEqual(result["profile_used"]["skin_type"],"unknown")

    def test_headline_matches_saved_reference(self):
        table=comparison_table()
        original=pd.read_csv(ORIGINAL/"comparison.csv").set_index("model")
        improved=pd.read_csv(BENCHMARK/"comparison.csv").set_index("model")
        self.assertAlmostEqual(table.iloc[0]["NDCG@10"],original.loc["original_notebook_30_epochs","ndcg@10"])
        self.assertAlmostEqual(table.iloc[1]["NDCG@10"],improved.loc["lightfm_profile","ndcg@10"])

    def test_streamlit_form_submission_and_empty_state(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=45)
        self.assertEqual(len(app.exception),0)
        app.selectbox(key="skin_type").set_value("dry")
        app.selectbox(key="category").set_value("moisturizers")
        app.checkbox(key="budget_enabled").check()
        app.number_input(key="max_price_usd").set_value(50.)
        app.button[0].click().run(timeout=45)
        self.assertEqual(len(app.exception),0)
        result=app.session_state["comparison_result"]
        self.assertEqual(len(result["original"]),10)
        self.assertEqual(len(result["improved"]),10)
        self.assertTrue(all(row["price_usd"]<=50 for row in result["improved"]))
        app.number_input(key="max_price_usd").set_value(0.)
        app.button[0].click().run(timeout=45)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state["comparison_result"]["improved"],[])


if __name__=="__main__":
    unittest.main()
