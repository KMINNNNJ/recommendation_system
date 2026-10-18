"""Load saved experiments once and compare recommendations under shared filters."""
from pathlib import Path
import hashlib
import os

from optimized.cold_start_benchmark.experiment import (
    PROFILE, clean, ingredient_tokens, joblib, json, lightfm_scores, np, pd,
)
from optimized.cold_start_benchmark.compare_original import score_original
from optimized.cold_start_improvements.policy import candidate_mask, ingredient_similarity, rerank

ROOT = Path(__file__).resolve().parents[2]


def run_path(parent, variable, default):
    name=os.environ.get(variable,default)
    if Path(name).name != name or name in (".",".."):
        raise ValueError(f"{variable} must be a single run directory name")
    return ROOT/parent/name


BENCHMARK = run_path("optimized/cold_start_benchmark/artifacts","RECOMMENDER_BENCHMARK_RUN","cold_users_v2")
ORIGINAL = run_path("optimized/cold_start_benchmark/artifacts","RECOMMENDER_ORIGINAL_RUN","original_same_users_v1")
FOLLOWUP = run_path("optimized/cold_start_improvements/artifacts","RECOMMENDER_FOLLOWUP_RUN","improvements_v1")


def required_files():
    return [BENCHMARK/name for name in ["features.joblib","lightfm_profile.joblib","data_summary.json","comparison.csv"]] + [
        ORIGINAL/"original_notebook_30_epochs.joblib", ORIGINAL/"comparison.csv",
        FOLLOWUP/"config.json", FOLLOWUP/"selection.json", FOLLOWUP/"completed.json", FOLLOWUP/"comparison.csv"]


def comparison_table():
    # All headline accuracy values come from saved evaluation artifacts.
    original=pd.read_csv(ORIGINAL/"comparison.csv")
    original=original.loc[original.model.eq("original_notebook_30_epochs")].iloc[0]
    improved=pd.read_csv(BENCHMARK/"comparison.csv")
    improved=improved.loc[improved.model.eq("lightfm_profile")].iloc[0]
    return pd.DataFrame([{"모델":label,"Precision@10":row["precision@10"],
                          "Recall@10":row["recall@10"],"NDCG@10":row["ndcg@10"]}
                         for label,row in [("원본 설정 재학습 · 30 epochs",original),("개선 · 프로필 LightFM",improved)]])


class DemoModels:
    def __init__(self):
        missing=[str(path) for path in required_files() if not path.is_file()]
        if missing:
            raise FileNotFoundError("Missing saved experiment files:\n"+"\n".join(missing))
        config=json.loads((FOLLOWUP/"config.json").read_text(encoding="utf-8"))
        for filename,key in [("features.joblib","source_feature_sha256"),("lightfm_profile.joblib","source_model_sha256")]:
            digest=hashlib.sha256((BENCHMARK/filename).read_bytes()).hexdigest()
            if digest != config[key]:
                raise ValueError("Saved follow-up policies refer to different original features/model")
        # Paths are derived from this checkout, not from machine-specific paths
        # serialized into config.json. This demo remains relocatable.
        self.features=joblib.load(BENCHMARK/"features.joblib")
        self.products=self.features.products
        self.improved=joblib.load(BENCHMARK/"lightfm_profile.joblib")
        self.original=joblib.load(ORIGINAL/"original_notebook_30_epochs.joblib")
        self.vocabulary=json.loads((BENCHMARK/"data_summary.json").read_text(encoding="utf-8"))["user_feature_vocabulary"]
        self.selection=json.loads((FOLLOWUP/"selection.json").read_text(encoding="utf-8"))
        self.brands=self.products.brand_name.map(clean).to_numpy()
        self.similarity=ingredient_similarity(self.products)
        original_items=set(self.original["dataset"].mapping()[2])
        self.original_supported=self.products.product_id.isin(original_items).to_numpy()
        self.ingredient_options=sorted({token for value in self.products.ingredients for token in ingredient_tokens(value)})

    @property
    def categories(self):
        return sorted(set(self.products.secondary_category.map(clean)) - {"unknown"})

    def normalize_profile(self, profile):
        return {column:value if value in self.vocabulary[column] else "unknown"
                for column in PROFILE for value in [clean(profile.get(column,"unknown"))]}

    def compare(self, profile, category=None, max_price_usd=None, excluded_ingredients=(), top_k=10, diversity=False):
        if not 1 <= top_k <= 50:
            raise ValueError("추천 개수는 1~50개여야 합니다.")
        category=clean(category) if category else None
        if category and category not in self.categories:
            raise ValueError("상품 카테고리를 확인해 주세요.")
        normalized=self.normalize_profile(profile)
        profiles=pd.DataFrame([normalized])
        candidates=np.flatnonzero(candidate_mask(self.products,category,max_price_usd,excluded_ingredients))
        original_candidates=candidates[self.original_supported[candidates]]
        old_scores=score_original(self.original["model"],self.original,profiles,self.products)
        new_scores=lightfm_scores(self.improved["model"],self.features,profiles)
        scope=category if category in self.selection else "all"
        selected=self.selection[scope]["selected"]
        if selected["model"] != "lightfm_profile":
            raise ValueError("Demo model differs from saved policy; update the demo for the new experiment")
        weight=selected["diversity_weight"] if diversity else 0.0
        old_top=rerank(old_scores,original_candidates,self.brands,self.similarity,0,k=top_k)[0]
        new_top=rerank(new_scores,candidates,self.brands,self.similarity,weight,k=top_k)[0]

        def present(indices):
            result=self.products.iloc[indices][["product_id","product_name","brand_name","price_usd"]].copy()
            result.insert(0,"rank",np.arange(1,len(result)+1))
            # Scores between separately trained models have different scales;
            # omit them from product-facing tables.
            return json.loads(result.to_json(orient="records",force_ascii=False))

        return {"profile_used":normalized,"candidate_count":len(candidates),
                "original_supported_candidates":len(original_candidates),"policy_scope":scope,
                "diversity_weight":weight,"original":present(old_top),"improved":present(new_top)}
