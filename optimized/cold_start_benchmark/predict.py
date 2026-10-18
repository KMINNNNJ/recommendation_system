"""Use an offline experiment model without changing the existing API."""
import argparse
import json
import sys
from pathlib import Path

from optimized.cold_start_benchmark.experiment import (
    HERE, PROFILE, baseline_scores, clean, joblib, pd, tree_scores, lightfm_scores,
)


def recommend(run_dir, profile, top_k=10, product_type=None, model_name=None):
    summary=json.loads((run_dir/"data_summary.json").read_text(encoding="utf-8"))
    features=joblib.load(run_dir/"features.joblib")
    normalized={}
    for column in PROFILE:
        value=clean(profile.get(column,"unknown"))
        normalized[column]=value if value in summary["user_feature_vocabulary"][column] else "unknown"
    profiles=pd.DataFrame([normalized])
    name=model_name or json.loads((run_dir/"selected_model.json").read_text(encoding="utf-8"))["model"]
    if name in ("global_popularity","global_bayesian","skin_type_bayesian"):
        history=json.loads((run_dir/"validation_history.json").read_text(encoding="utf-8"))
        strength=max((entry for entry in history if entry["model"]==name),key=lambda entry:entry["ndcg@10"])["strength"]
        reviews=pd.read_pickle(run_dir/"reviews_prepared.pkl")
        scores=baseline_scores(reviews.loc[reviews.split.eq("train")],features,profiles,name=="skin_type_bayesian",strength,popularity=name=="global_popularity")[0]
    elif name.startswith("lightfm_"):
        bundle=joblib.load(run_dir/f"{name}.joblib")
        scores=lightfm_scores(bundle["model"],features,profiles,bundle["identity_count"],bundle["skin_only"])[0]
    elif name=="catboost":
        from catboost import CatBoostClassifier
        model=CatBoostClassifier();model.load_model(str(run_dir/"catboost.cbm"))
        scores=tree_scores(model,features,profiles,True)[0]
    elif name=="lightgbm":
        scores=tree_scores(joblib.load(run_dir/"lightgbm.joblib"),features,profiles)[0]
    else:
        raise ValueError(f"Unknown model: {name}")
    products=features.products.copy()
    products["ranking_score"]=scores
    if product_type:
        # Literal substring matching, consistent with this project's category filter.
        columns=[c for c in ["product_name","secondary_category","tertiary_category"] if c in products]
        text=products[columns].fillna("").astype(str).agg(" ".join,axis=1)
        products=products.loc[text.str.contains(product_type,case=False,regex=False)]
    products=products.sort_values(["ranking_score","product_id"],ascending=[False,True],kind="stable").head(top_k)
    columns=[c for c in ["product_id","product_name","brand_name","price_usd","ranking_score"] if c in products]
    return {"model":name,"profile_used":normalized,"product_type_filter":product_type,
            "note":"Offline ranking score; not a calibrated suitability or efficacy probability.",
            "recommendations":products[columns].to_dict(orient="records")}


def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name",default="cold_users_v2")
    parser.add_argument("--skin-type",default="unknown")
    parser.add_argument("--skin-tone",default="unknown")
    parser.add_argument("--eye-color",default="unknown")
    parser.add_argument("--hair-color",default="unknown")
    parser.add_argument("--product-type")
    parser.add_argument("--top-k",type=int,default=5)
    parser.add_argument("--model",choices=["global_popularity","global_bayesian","skin_type_bayesian","lightfm_profile","lightfm_skin_only","lightfm_identity_ablation","catboost","lightgbm"])
    args=parser.parse_args()
    if args.top_k<1 or Path(args.run_name).name!=args.run_name or args.run_name in (".",".."):
        parser.error("Invalid run name or top-k")
    result=recommend(HERE/"artifacts"/args.run_name,{key:getattr(args,key) for key in PROFILE},args.top_k,args.product_type,args.model)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
