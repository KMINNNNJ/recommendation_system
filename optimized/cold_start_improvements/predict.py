"""Use validation-selected policies with explicit user constraints."""
import argparse
import hashlib
import sys
from pathlib import Path

from optimized.cold_start_benchmark.experiment import (
    PROFILE, clean, joblib, json, lightfm_scores, np, pd,
)
from .experiment import HERE
from .policy import candidate_mask, ingredient_similarity, rerank


def recommend(run_dir, profile, category=None, max_price_usd=None,
              excluded_ingredients=(), top_k=10, diversity=True):
    if not 1 <= top_k <= 50:
        raise ValueError("top_k must be between 1 and 50")
    if not (run_dir/"completed.json").is_file():
        raise ValueError("Experiment has not completed")
    config=json.loads((run_dir/"config.json").read_text(encoding="utf-8"))
    selection=json.loads((run_dir/"selection.json").read_text(encoding="utf-8"))
    source=Path(config["source"])
    for filename,key in [("features.joblib","source_feature_sha256"),("lightfm_profile.joblib","source_model_sha256")]:
        if hashlib.sha256((source/filename).read_bytes()).hexdigest() != config[key]:
            raise ValueError("Original model/features changed; rerun benchmark or restore source")
    features=joblib.load(source/"features.joblib")
    products=features.products
    category=clean(category) if category else None
    if category and category not in set(products.secondary_category.map(clean)):
        raise ValueError("Unknown category. Use a secondary_category from the catalogue")
    vocabulary=json.loads((source/"data_summary.json").read_text(encoding="utf-8"))["user_feature_vocabulary"]
    normalized={column:(value if value in vocabulary[column] else "unknown")
                for column in PROFILE for value in [clean(profile.get(column,"unknown"))]}
    scope=category if category in selection else "all"
    spec=selection[scope]["selected" if diversity else "raw_best"]
    model_dir=source if spec["model"] == "lightfm_profile" else run_dir
    bundle=joblib.load(model_dir/f"{spec['model']}.joblib")
    scores=lightfm_scores(bundle["model"],features,pd.DataFrame([normalized]))
    candidates=np.flatnonzero(candidate_mask(products,category,max_price_usd,excluded_ingredients))
    weight=spec["diversity_weight"] if diversity else 0
    similarity=ingredient_similarity(products) if weight else None
    top=rerank(scores,candidates,products.brand_name.map(clean).to_numpy(),similarity,weight,k=top_k)[0]
    columns=[column for column in ["product_id","product_name","brand_name","secondary_category","price_usd"] if column in products]
    result=products.iloc[top][columns].copy()
    result.insert(0,"rank",np.arange(1,len(result)+1))
    result["model_score"]=scores[0,top]
    return {"model":spec["model"], "policy_scope":scope, "diversity_weight":weight,
            "profile_used":normalized,"candidate_count":len(candidates),
            "constraints":{"secondary_category":category,"max_price_usd":max_price_usd,
                           "excluded_ingredients":list(excluded_ingredients)},
            "constraint_evaluation_note":"Price and ingredient constraints are not validated preference predictions; diversity was tuned before these additional constraints.",
            "ingredient_matching_note":"Exact parsed ingredient names; missing lists excluded when exclusions are set. No synonym or allergy-safety guarantee.",
            "score_note":"Uncalibrated ranking score; final order may differ after diversity reranking.",
            "recommendations":json.loads(result.to_json(orient="records",force_ascii=False))}


def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name",default="improvements_v1")
    for column in PROFILE:
        parser.add_argument("--"+column.replace("_","-"),default="unknown")
    parser.add_argument("--category",help="Exact secondary_category, e.g. moisturizers")
    parser.add_argument("--max-price-usd",type=float)
    parser.add_argument("--exclude-ingredient",action="append",default=[])
    parser.add_argument("--top-k",type=int,default=10)
    parser.add_argument("--no-diversity",action="store_true")
    args=parser.parse_args()
    if Path(args.run_name).name != args.run_name or args.run_name in (".",".."):
        parser.error("run-name must be a single folder name")
    try:
        result=recommend(HERE/"artifacts"/args.run_name,{column:getattr(args,column) for column in PROFILE},
                         args.category,args.max_price_usd,args.exclude_ingredient,args.top_k,not args.no_diversity)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
