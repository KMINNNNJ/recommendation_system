"""Train explicit-feedback alternatives and validate diversity before testing."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import time

from optimized.cold_start_benchmark.experiment import (
    HERE as BASE, PROFILE, SEED, Evaluation, clean, joblib, json, lightfm_scores,
    log, np, pd, save_json, sparse,
)
from .policy import candidate_mask, ingredient_similarity, ranking_metrics, rerank

HERE = Path(__file__).resolve().parent


def paired_difference(selected, baseline):
    left = selected.set_index("author_id")["ndcg@10"]
    right = baseline.set_index("author_id")["ndcg@10"].reindex(left.index)
    if right.isna().any() or not len(left):
        raise ValueError("Paired evaluation requires matching nonempty users")
    delta = (left-right).to_numpy()
    rng = np.random.default_rng(SEED)
    boot = [float(rng.choice(delta, len(delta), replace=True).mean()) for _ in range(500)]
    return {"ndcg_difference":float(delta.mean()),
            "paired_bootstrap_95ci":np.quantile(boot, [.025,.975]).tolist(), "users":len(delta)}


def select_policy(trials, tolerance=.02):
    # First select unmodified model by relevance, then maximize catalogue reach
    # subject to at most 2% relative validation NDCG loss from that best model.
    raw = max((row for row in trials if row["diversity_weight"] == 0), key=lambda row:row["ndcg@10"])
    eligible = [row for row in trials if row["ndcg@10"] >= raw["ndcg@10"]*(1-tolerance)]
    chosen = max(eligible, key=lambda row:(row["catalogue_coverage_at_10"], row["unique_brands@10"], row["ndcg@10"], -row["diversity_weight"]))
    return raw, chosen


def report(output, comparison, selection, uncertainty):
    baseline=next(row for row in comparison if row["scope"]=="all" and row["variant"]=="baseline")
    selected=next(row for row in comparison if row["scope"]=="all" and row["variant"]=="selected")
    lines = ["# 신규 사용자 추천 개선 실험", "",
             "기존 분할의 학습 사용자만 사용했습니다. 모델·다양성 가중치는 검증으로 선택한 뒤 테스트했습니다.", "",
             f"전체 후보의 평균 추천 브랜드 수는 {baseline['unique_brands@10']:.2f} → {selected['unique_brands@10']:.2f}개, NDCG는 {baseline['ndcg@10']:.6f} → {selected['ndcg@10']:.6f}입니다.",
             f"전체 사용자에게 추천된 고유 상품은 {baseline['recommended_items']} → {selected['recommended_items']}개입니다. 목록 안의 브랜드 다양성과 전체 상품 노출 범위는 서로 다른 지표입니다.", "",
             "종류별 평가는 해당 종류를 사용자가 요청했다고 가정한 조건부 평가입니다. 실제 질의 예측 성능이 아니며, 종류 안에 긍정 리뷰가 있는 기존 샘플 사용자만 포함합니다.", "",
             "| 범위 | 설정 | 모델 | 다양성 가중치 | 사용자 | Recall@10 | NDCG@10 | 추천 상품/후보 | 평균 브랜드 수 |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in comparison:
        lines.append(f"| {row['scope']} | {row['variant']} | {row['model']} | {row['diversity_weight']} | {row['evaluated_users']} | {row['recall@10']:.5f} | {row['ndcg@10']:.5f} | {row['recommended_items']}/{row['candidate_items']} | {row['unique_brands@10']:.2f} |")
    if (output/"raw_model_comparison.csv").exists():
        lines += ["", "## 부정 리뷰 모델 비교 (전체 후보, 재정렬 전)", "",
                  "이 표는 선택을 고정한 이후의 테스트 진단이며 설정 선택에 사용하지 않았습니다.", "",
                  "| 모델 | Recall@10 | NDCG@10 |", "|---|---:|---:|"]
        for row in pd.read_csv(output/"raw_model_comparison.csv").to_dict(orient="records"):
            lines.append(f"| {row['model']} | {row['recall@10']:.5f} | {row['ndcg@10']:.5f} |")
    lines += ["", "## 선택 방법", "",
              "범위별로 원래 WARP와 부정 가중치 0.25/1.0인 logistic 모델을 비교했습니다. 각 logistic 체크포인트는 전체 후보의 검증 NDCG로 선택했습니다.",
              "최고 raw 모델 대비 검증 NDCG 하락이 2% 이내인 설정 중 추천 상품 커버리지, 평균 브랜드 수, NDCG 순으로 선택했습니다. 가중치 0도 후보라서 다양성을 강제로 적용하지 않습니다.", "",
              "## 해석과 제한", "",
              "- 종류별 수치와 전체 수치는 후보와 정답 집합이 달라 직접 우열 비교하지 않습니다.",
              "- raw_best는 순위 모델 교체 효과, selected는 재정렬까지 합친 효과를 보여줍니다.",
              "- 예산과 제외 성분은 사용자가 지정하는 필터입니다. 가격은 데이터셋의 USD 스냅샷이며 원화나 실시간 가격이 아닙니다.",
              "- 제외 성분은 파싱된 성분명 완전 일치만 처리합니다. 동의어·농도·알레르기 안전성을 보장하지 않습니다. 제외 조건이 있으면 성분 미기재 상품도 제외합니다.",
              "- 성분 유사도와 브랜드 중복은 다양성을 위한 대리지표이며 효과의 유사성을 뜻하지 않습니다.",
              "- 같은 테스트 사용자를 이전 실험에서도 평가했으므로 후속 탐색 결과입니다. 독립적인 최종 검증이나 온라인 실험을 대신하지 않습니다.",
              "- seed 42, 4스레드 학습입니다. bootstrap은 사용자 표본의 차이만 반영하며 학습 seed 변동은 포함하지 않습니다.",
              "- 기존 모델·원본 데이터·서비스 API는 수정하지 않았습니다.", "", "## 선택 모델과 기존 모델의 NDCG 차이", ""]
    for row in uncertainty:
        lo,hi = row["paired_bootstrap_95ci"]
        lines.append(f"- {row['scope']}: {row['ndcg_difference']:+.6f}, 사용자 bootstrap 95% 구간 [{lo:+.6f}, {hi:+.6f}]")
    (output/"RESULTS.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def run(args):
    source = args.source.resolve()
    output = HERE/"artifacts"/args.run_name
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    features = joblib.load(source/"features.joblib")
    products = features.products
    reviews = pd.read_pickle(source/"reviews_prepared.pkl")
    profiles = pd.read_pickle(source/"profiles.pkl")
    validation = Evaluation(reviews, "validation", products, 3000)
    test = Evaluation(reviews, "test", products, 10000)
    # Do not silently change users relative to the original comparison.
    for split, evaluation in [("validation",validation),("test",test)]:
        saved = pd.read_csv(source/f"{split}_users.csv", dtype={"author_id":str})
        if saved.author_id.tolist() != evaluation.users.author_id.tolist():
            raise ValueError(f"{split} sample differs from frozen original sample")
        evaluation.users.to_csv(output/f"{split}_users.csv", index=False)
    train = reviews.loc[reviews.split.eq("train")]
    training_profiles = profiles.loc[profiles.split.eq("train")].reset_index(drop=True)
    user_map = {uid:i for i,uid in enumerate(training_profiles.author_id)}
    labelled = train.loc[train.label.ge(0)]
    interactions = sparse.coo_matrix((np.where(labelled.label.eq(1),1.,-1.).astype(np.float32),
                    (labelled.author_id.map(user_map), labelled.product_id.map(features.item_map))),
                    shape=(len(training_profiles), len(products)))
    user_matrix = features.user_matrix(training_profiles)
    negative = labelled.label.eq(0).to_numpy()
    category_counts = train.loc[train.label.eq(1),"product_id"].map(products.set_index("product_id").secondary_category).map(clean).value_counts()
    categories = [category for category in category_counts.index if category != "unknown"][:4]
    scopes = {"all":None, **{category:category for category in categories}}
    config = {"source":str(source), "seed":SEED, "threads":4, "epochs":args.epochs,
              "negative_weights":[.25,1.0], "diversity_weights":[0,.05,.15,.30],
              "pool_size":200, "validation_ndcg_relative_loss_budget":.02,
              "category_selection":"top 4 by training positive review count, no validation/test categories used",
              "scopes":scopes, "category_training_positive_counts":{key:int(category_counts[key]) for key in categories},
              "candidate_policy":"exact secondary_category; full catalogue for all",
              "category_truth":"positives within candidate category; oracle request proxy",
              "test_used_for_selection":False, "reused_previous_test":True,
              "source_model_sha256":hashlib.sha256((source/"lightfm_profile.joblib").read_bytes()).hexdigest(),
              "source_feature_sha256":hashlib.sha256((source/"features.joblib").read_bytes()).hexdigest()}
    save_json(output/"config.json", config)
    models = {"lightfm_profile":joblib.load(source/"lightfm_profile.joblib")}
    val_scores = {"lightfm_profile":lightfm_scores(models["lightfm_profile"]["model"],features,validation.unique_profiles)}
    history = []
    from lightfm import LightFM
    for negative_weight in config["negative_weights"]:
        name = f"lightfm_logistic_neg{negative_weight:g}"
        weights = interactions.copy()
        weights.data = np.where(negative,negative_weight,1.).astype(np.float32)
        model = LightFM(loss="logistic",no_components=32,learning_rate=.05,user_alpha=1e-5,
                        item_alpha=1e-5,random_state=SEED)
        best, previous = -1.,0
        log(f"Training {name}: {interactions.nnz:,} observed positive/negative pairs")
        for epoch in args.epochs:
            model.fit_partial(interactions, sample_weight=weights,user_features=user_matrix,
                              item_features=features.item_matrix,epochs=epoch-previous,num_threads=4)
            previous=epoch
            scores=lightfm_scores(model,features,validation.unique_profiles)
            metric=validation.evaluate(scores)[0]["ndcg@10"]
            history.append({"model":name,"epoch":epoch,"validation_ndcg@10":metric})
            log(f"{name} epoch {epoch}: validation NDCG@10={metric:.6f}")
            if metric > best:
                best=metric
                joblib.dump({"model":model,"epoch":epoch,"negative_weight":negative_weight,
                             "identity_count":0,"skin_only":False},output/f"{name}.joblib",compress=3)
        models[name]=joblib.load(output/f"{name}.joblib")
        val_scores[name]=lightfm_scores(models[name]["model"],features,validation.unique_profiles)
    save_json(output/"validation_history.json",history)
    similarity=ingredient_similarity(products)
    brands=products.brand_name.map(clean).to_numpy()
    trials, selection = [],{}
    for scope,category in scopes.items():
        candidates=np.flatnonzero(candidate_mask(products,category))
        scope_trials=[]
        for name,scores in val_scores.items():
            for weight in config["diversity_weights"]:
                top=rerank(scores,candidates,brands,similarity,weight)
                metrics,_=ranking_metrics(validation,top,candidates,products,similarity)
                if metrics["evaluated_users"] == 0:
                    raise ValueError(f"No validation users for {scope}")
                scope_trials.append({"scope":scope,"model":name,"diversity_weight":weight,**metrics})
        raw,chosen=select_policy(scope_trials)
        selection[scope]={"category":category,"raw_best":{"model":raw["model"],"diversity_weight":0},
                          "selected":{"model":chosen["model"],"diversity_weight":chosen["diversity_weight"]},
                          "validation_raw_ndcg":raw["ndcg@10"], "validation_selected_ndcg":chosen["ndcg@10"]}
        trials.extend(scope_trials)
        log(f"{scope}: selected {chosen['model']}, diversity weight={chosen['diversity_weight']}")
    pd.DataFrame(trials).to_csv(output/"validation_policies.csv",index=False)
    save_json(output/"selection.json",selection)
    log("Validation selection frozen; starting test evaluation")
    test_scores={name:lightfm_scores(bundle["model"],features,test.unique_profiles) for name,bundle in models.items()}
    results,uncertainty=[],[]
    for scope,choice in selection.items():
        candidates=np.flatnonzero(candidate_mask(products,choice["category"]))
        details={}
        for variant,spec in [("baseline",{"model":"lightfm_profile","diversity_weight":0}),
                             ("raw_best",choice["raw_best"]),("selected",choice["selected"])]:
            top=rerank(test_scores[spec["model"]],candidates,brands,similarity,spec["diversity_weight"])
            metrics,detail=ranking_metrics(test,top,candidates,products,similarity)
            stem=f"{scope.replace(' ','_')}_{variant}"
            detail.to_csv(output/f"{stem}_per_user.csv",index=False)
            detail.groupby("skin_type").agg(users=("author_id","size"),ndcg=("ndcg@10","mean"),recall=("recall@10","mean")).to_csv(output/f"{stem}_by_skin.csv")
            np.save(output/f"{stem}_top10.npy",top)
            results.append({"scope":scope,"variant":variant,**spec,**metrics})
            details[variant]=detail
            log(f"{scope} {variant}: NDCG={metrics['ndcg@10']:.6f}, coverage={metrics['recommended_items']}/{len(candidates)}")
        uncertainty.append({"scope":scope,**paired_difference(details["selected"],details["baseline"])})
    # Diagnostic full-catalogue test comparison of rejected logistic alternatives;
    # selection is already immutable and these scores cannot change it.
    diagnostics=[]
    for name,scores in test_scores.items():
        diagnostics.append({"model":name,**test.evaluate(scores)[0]})
    pd.DataFrame(diagnostics).to_csv(output/"raw_model_comparison.csv",index=False)
    save_json(output/"comparison.json",results)
    pd.DataFrame(results).to_csv(output/"comparison.csv",index=False)
    save_json(output/"paired_uncertainty.json",uncertainty)
    report(output,results,selection,uncertainty)
    save_json(output/"completed.json",{"elapsed_seconds":time.perf_counter()-started,"status":"complete"})
    log(f"Complete: {output}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=BASE/"artifacts/cold_users_v2")
    parser.add_argument("--run-name",default="improvements_v1")
    parser.add_argument("--epochs",type=int,nargs="+",default=[5,15,30])
    args=parser.parse_args()
    if Path(args.run_name).name != args.run_name or args.run_name in (".",".."):
        parser.error("run-name must be a single folder name")
    if not args.epochs or args.epochs != sorted(set(args.epochs)) or min(args.epochs)<1:
        parser.error("epochs must be positive and strictly increasing")
    run(args)


if __name__=="__main__":
    main()
