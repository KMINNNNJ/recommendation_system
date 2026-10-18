"""Retrain original notebook settings on the frozen cold-user training split.

The old full-data model cannot be tested honestly on these held-out users:
its training may already contain their reviews. Preserve original features,
k-core, identity embeddings and hyperparameters; change only evaluation split.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import time

from optimized.cold_start_benchmark.experiment import (
    HERE, PROFILE, REVIEW_COLUMNS, Evaluation, joblib, log, np, pd, save_json,
    sparse,
)
from optimized.cold_start_benchmark.original_feature_recipe import build_original_features


PARAMS={"loss":"warp","no_components":64,"learning_rate":.05,
        "user_alpha":1e-6,"item_alpha":1e-6,"max_sampled":10,"random_state":42}


def original_user_features(profiles, mapping):
    rows,columns=[],[]
    for i,values in enumerate(profiles[PROFILE].itertuples(index=False,name=None)):
        for name,value in zip(PROFILE,values):
            index=mapping.get(f"{name}:{value}",mapping.get(f"{name}:unknown"))
            if index is not None:
                rows.append(i);columns.append(index)
    matrix=sparse.csr_matrix((np.ones(len(rows),dtype=np.float32),(rows,columns)),shape=(len(profiles),len(mapping)))
    from sklearn.preprocessing import normalize
    return normalize(matrix,norm="l1").tocsr()


def score_original(model,data,profiles,catalogue):
    _,user_map,item_map,_=data["dataset"].mapping()
    user_features=original_user_features(profiles,user_map)
    user_bias,users=model.get_user_representations(user_features)
    item_bias,items=model.get_item_representations(data["item_feature_matrix"])
    scores=users@items.T+user_bias[:,None]+item_bias[None,:]
    # The original service drops products absent from its item mapping.
    # Retain the common catalogue and all relevant targets in evaluation;
    # unsupported items cannot win a top-k slot (rather than filtering targets).
    full=np.full((len(profiles),len(catalogue)),-1e20,dtype=np.float32)
    catalogue_map={pid:i for i,pid in enumerate(catalogue.product_id)}
    for pid,index in item_map.items():
        full[:,catalogue_map[pid]]=scores[:,index]
    return full


def load_original_training(data_dir,train_ids):
    parts=sorted(data_dir.glob("reviews_*-*.csv"))
    paths=parts or sorted(data_dir.glob("reviews_all*.csv"))
    frame=pd.concat([pd.read_csv(p,usecols=REVIEW_COLUMNS,dtype={"author_id":str,"product_id":str}) for p in paths],ignore_index=True)
    frame=frame.loc[frame.author_id.isin(train_ids)].copy()
    frame["submission_time"]=pd.to_datetime(frame.submission_time,errors="coerce")
    frame["rating"]=pd.to_numeric(frame.rating,errors="coerce")
    frame["is_recommended"]=pd.to_numeric(frame.is_recommended,errors="coerce")
    frame=frame.dropna(subset=["author_id","product_id","rating"])
    frame=(frame.sort_values(["author_id","product_id","submission_time"],na_position="first")
           .drop_duplicates(["author_id","product_id"],keep="last").copy())
    positive=frame.rating.ge(4)&(frame.is_recommended.isna()|frame.is_recommended.eq(1))
    interactions=frame.loc[positive,["author_id","product_id","submission_time","rating"]].copy()
    interactions["interaction"]=1.0
    return frame,interactions


def write_report(output,records,new_row,reference,coverage,uncertainty,sizes):
    lines=["# 원래 노트북 설정과 신규 사용자 모델 비교", "",
           "둘 다 LightFM입니다. 새 모델은 알고리즘 교체가 아니라 신규 사용자 목표에 맞춘 학습·특징·평가 변경입니다.", "",
           "## 원래 노트북에 기록된 수치", "",
           "| 기존 실험 | Precision@10 | Recall@10 | AUC |", "|---|---:|---:|---:|"]
    for name,values in reference["historical_random_split_metrics"].items():
        lines.append(f"| {name} | {values['precision@10']:.6f} | {values['recall@10']:.6f} | {values['auc']:.6f} |")
    lines += ["", "위 수치는 리뷰 무작위 분할·기존 사용자 ID 포함 평가입니다. 아래 신규 사용자 평가와 개선율을 직접 계산하면 안 됩니다.", "",
              "## 같은 신규 사용자 평가로 다시 비교", "",
              "원래 전체 데이터 학습 파일은 테스트 사용자 리뷰를 이미 봤을 수 있어 사용하지 않았습니다. 원래 노트북의 feature 생성 코드·k-core·ID 임베딩·64차원·규제값·학습률을 유지하고, 공통 학습 사용자만 사용해 다시 학습했습니다. 원래 20회 모델과 튜닝 후 30회 모델을 사전에 고정해 둘 다 평가했습니다. 테스트 점수로 재튜닝하거나 모델을 재선택하지 않았습니다.", "",
              "신규 모델은 이미 완료한 `cold_users_v2`의 `lightfm_profile`이며 다시 학습하거나 수정하지 않았습니다.", "",
              "| 설정 | Precision@10 | Recall@10 | NDCG@10 |", "|---|---:|---:|---:|"]
    for row in records+[new_row]:
        lines.append(f"| {row['model']} | {row['precision@10']:.5f} | {row['recall@10']:.5f} | {row['ndcg@10']:.5f} |")
    old=next(row for row in records if row["epochs"]==30)
    lines += ["", "기존 튜닝 설정(30회) 재학습 대비 신규 설정의 상대 차이:", ""]
    for key in ["precision@10","recall@10","ndcg@10"]:
        delta=(new_row[key]/old[key]-1)*100 if old[key] else None
        lines.append(f"- {key}: {delta:+.2f}%" if delta is not None else f"- {key}: 분모 0으로 계산 불가")
    lines += ["", "## 점수 차이의 불확실성", "", "신규 모델 − 원래 설정 재학습의 사용자별 NDCG 차이에 대한 paired bootstrap 95% 구간입니다.", ""]
    for value in uncertainty:
        low,high=value["ndcg_difference_95ci"]
        lines.append(f"- {value['original_model']}: 평균 차이 {value['ndcg_difference']:.5f}, 구간 [{low:.5f}, {high:.5f}]")
    lines += ["", "## 구성·범위 차이", "",
              f"- 공통 스킨케어 후보: {coverage['catalogue_items']:,}개. 원래 k-core 학습 범위: {coverage['original_train_items']:,}개.",
              f"- 원래 모델이 점수를 낼 수 있는 테스트 긍정 상품 비율: {coverage['original_positive_target_coverage']:.3%}. 범위 밖 정답도 평가 분모에 남겼습니다.",
              "- 원래 설정: 최소 사용자 긍정 2개·상품 긍정 10개, 사용자 ID 포함, 64차원, 원래 성분·highlight·상품 flag·가격 feature, 사용자 프로필 최빈값.",
              "- 신규 설정: 단일 리뷰 사용자 유지, 사용자 ID 제외, 32차원, 성분 그룹 가중치·희귀 성분 정리, 첫 리뷰 프로필.",
              "- 두 방식 모두 같은 사용자 분리·동일 테스트 10,000명·동일 프로필 입력·동일 후보와 정답·같은 지표를 사용했습니다.",
              "- 사용자 분리는 기존 평가를 고치기 위해 원본과 달라진 부분입니다. 날짜/ID 자료형 정리도 공통 프로토콜에 맞췄습니다.",
              "- 여러 구성 요소가 함께 달라지므로 점수 차이를 특정 변경 하나의 인과적 효과로 단정하지 않습니다.",
              "- 같은 수정된 Windows LightFM 네이티브 빌드와 4스레드를 사용했습니다. 원본 Colab 환경과 수치까지 동일하게 재현하는 실험은 아닙니다.",
              "- 모델의 순위 계산을 비교합니다. LLM·성분/제품 종류 필터·베이지안/웹 fallback을 포함한 서비스 전체 평가가 아닙니다.",
              "- 원래 서비스 파일과 API는 수정하지 않았습니다.", "",
              "## 저장 파일 크기", "",
              "원래 파일에는 Dataset과 상품 feature가 포함되고 새 모델은 feature 파일이 별도입니다. 체크포인트 크기와 feature 포함 합계를 구분해야 하며, 동일 직렬화 포맷만의 비교는 아닙니다.", ""]
    for name,size in sizes.items(): lines.append(f"- {name}: {size/1_000_000:.2f} MB")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows=records+[new_row]
    labels=["Original recipe: 20 epochs","Original recipe: 30 epochs","New cold-user recipe"]
    figure,axes=plt.subplots(1,2,figsize=(11,3.6),layout="constrained")
    for ax,key,title in zip(axes,["recall@10","ndcg@10"],["Test Recall@10","Test NDCG@10"]):
        values=[row[key] for row in rows]
        ax.barh(labels,values,color=["#94a3b8","#64748b","#2563eb"])
        ax.invert_yaxis();ax.set_title(title);ax.set_xlim(left=0,right=max(values)*1.2)
        ax.grid(axis="x",alpha=.2);ax.set_axisbelow(True)
        for i,value in enumerate(values): ax.text(value+max(values)*.02,i,f"{value:.4f}",va="center",fontsize=9)
    figure.suptitle("Same unseen users and evaluation catalogue; original recipe retrained")
    figure.savefig(output/"original_comparison.png",dpi=150);plt.close(figure)
    lines += ["", "![Original versus new](original_comparison.png)"]
    (output/"ORIGINAL_COMPARISON.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name",default="original_same_users_v1")
    parser.add_argument("--source-run",default="cold_users_v2")
    args=parser.parse_args()
    for name in [args.run_name,args.source_run]:
        if Path(name).name!=name or name in (".",".."): parser.error("Invalid run name")
    output=HERE/"artifacts"/args.run_name;output.mkdir(parents=True,exist_ok=True)
    if (output/"comparison.json").exists(): raise FileExistsError("Comparison already completed")
    source=HERE/"artifacts"/args.source_run
    config=json.loads((source/"config.json").read_text(encoding="utf-8"))
    reference=json.loads((HERE/"original_notebook_reference.json").read_text(encoding="utf-8"))
    plan={"original_params":PARAMS,"epochs_fixed_before_test":[20,30],"primary_original_comparator_epochs":30,
          "source_run":args.source_run,"same_test_users":True,"same_first_review_profile_inputs":True,
          "source_notebook_sha256":reference["sha256"],"recipe_sha256":hashlib.sha256((HERE/"original_feature_recipe.py").read_bytes()).hexdigest(),
          "no_test_based_tuning":True,"threads":4}
    save_json(output/"comparison_plan.json",plan)
    reviews=pd.read_pickle(source/"reviews_prepared.pkl")
    profiles=pd.read_pickle(source/"profiles.pkl")
    catalogue=pd.read_pickle(source/"catalogue.pkl")
    train_ids=set(profiles.loc[profiles.split.eq("train"),"author_id"])
    validation=Evaluation(reviews,"validation",catalogue,config["validation_users"])
    test=Evaluation(reviews,"test",catalogue,config["test_users"])
    expected=pd.read_csv(source/"test_users.csv",dtype={"author_id":str})
    assert expected.author_id.tolist()==test.users.author_id.tolist()
    assert not train_ids.intersection(test.users.author_id)
    log("Preparing original notebook recipe using training users only")
    raw,interactions=load_original_training(Path(config["data_dir"]),train_ids)
    products=pd.read_csv(Path(config["data_dir"])/"product_info.csv",dtype={"product_id":str})
    data=build_original_features(raw,interactions,products)
    item_map=data["dataset"].mapping()[2]
    indices={i for i,pid in enumerate(catalogue.product_id) if pid in item_map}
    denominator=sum(len(items) for items in test.positive)
    covered=sum(len(items & indices) for items in test.positive)
    coverage={"catalogue_items":len(catalogue),"original_train_users":data["n_train_users"],
              "original_train_items":data["n_train_items"],"original_training_positives":int(data["interactions"].nnz),
              "original_positive_target_coverage":covered/denominator}
    save_json(output/"coverage.json",coverage)
    from lightfm import LightFM
    model=LightFM(**PARAMS)
    previous=0;records=[];validation_scores=[];sizes={}
    start=time.perf_counter()
    # Train and record both fixed checkpoints before accessing test scores.
    for epoch in [20,30]:
        log(f"Original settings: training through epoch {epoch}")
        model.fit_partial(data["interactions"],user_features=data["user_feature_matrix"],
                          item_features=data["item_feature_matrix"],epochs=epoch-previous,num_threads=4)
        previous=epoch
        name=f"original_notebook_{epoch}_epochs"
        scores=score_original(model,data,validation.unique_profiles,catalogue)
        validation_scores.append({"model":name,"epochs":epoch,"validation_ndcg@10":validation.evaluate(scores)[0]["ndcg@10"]})
        path=output/f"{name}.joblib"
        joblib.dump({"model":model,"dataset":data["dataset"],"item_feature_matrix":data["item_feature_matrix"],
                     "item_features":data["item_features"],"epochs":epoch},path,compress=3)
        sizes[name]=path.stat().st_size
        save_json(output/"validation_checkpoints.json",validation_scores)
        log(f"Saved {name}: validation NDCG@10={validation_scores[-1]['validation_ndcg@10']:.6f}")
    selected_rows=json.loads((source/"comparison.json").read_text(encoding="utf-8"))
    new_row=next(row for row in selected_rows if row["model"]=="lightfm_profile")
    new_details=pd.read_csv(source/"lightfm_profile_per_user.csv",dtype={"author_id":str}).set_index("author_id")
    uncertainties=[]
    for epoch in [20,30]:
        name=f"original_notebook_{epoch}_epochs"
        bundle=joblib.load(output/f"{name}.joblib")
        scores=score_original(bundle["model"],bundle,test.unique_profiles,catalogue)
        metrics,detail,top=test.evaluate(scores)
        detail.to_csv(output/f"{name}_per_user.csv",index=False)
        np.save(output/f"{name}_top10_by_profile.npy",top)
        records.append({"model":name,"epochs":epoch,**metrics})
        aligned=detail.set_index("author_id").reindex(new_details.index)
        difference=(new_details["ndcg@10"]-aligned["ndcg@10"]).to_numpy()
        assert np.isfinite(difference).all()
        rng=np.random.default_rng(42)
        means=np.array([rng.choice(difference,len(difference),replace=True).mean() for _ in range(500)])
        uncertainties.append({"original_model":name,"ndcg_difference":float(difference.mean()),
                              "ndcg_difference_95ci":[float(x) for x in np.quantile(means,[.025,.975])]})
        log(f"{name}: TEST Recall@10={metrics['recall@10']:.6f} NDCG@10={metrics['ndcg@10']:.6f}")
    sizes["new_lightfm_profile"]=(source/"lightfm_profile.joblib").stat().st_size
    sizes["new_lightfm_profile_plus_features"]=sizes["new_lightfm_profile"]+(source/"features.joblib").stat().st_size
    save_json(output/"paired_comparison.json",uncertainties)
    save_json(output/"comparison.json",records+[new_row])
    pd.DataFrame(records+[new_row]).to_csv(output/"comparison.csv",index=False)
    save_json(output/"runtime.json",{"seconds":time.perf_counter()-start})
    write_report(output,records,new_row,reference,coverage,uncertainties,sizes)
    log(f"Original comparison complete: {output}")


if __name__=="__main__": main()
