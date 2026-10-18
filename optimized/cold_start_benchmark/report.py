"""Generate a compact local report and static comparison figure."""
import argparse
import json

from optimized.cold_start_benchmark.experiment import HERE, pd


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name",default="cold_users_v2")
    args=parser.parse_args()
    root=HERE/"artifacts"/args.run_name
    results=json.loads((root/"comparison.json").read_text(encoding="utf-8"))
    summary=json.loads((root/"data_summary.json").read_text(encoding="utf-8"))
    audit=json.loads((root/"source_audit.json").read_text(encoding="utf-8"))
    selected=json.loads((root/"selected_model.json").read_text(encoding="utf-8"))["model"]
    config=json.loads((root/"config.json").read_text(encoding="utf-8"))
    uncertainty=json.loads((root/"paired_uncertainty.json").read_text(encoding="utf-8"))
    frame=pd.DataFrame(results).sort_values("validation_ndcg@10",ascending=False)
    lines=["# 신규 사용자 추천 모델 실험 결과", "",
           f"검증 NDCG@10으로 선택한 모델: **{selected}**. 테스트 결과로 모델을 다시 고르지 않았습니다.", "",
           f"원본 리뷰 {summary['raw_review_rows']:,}건 → 중복 정리 후 {summary['prepared_review_rows']:,}건. 스킨케어 후보 {summary['skincare_catalogue_items']:,}개.",
           f"사용자 분리: {summary['users_by_split']}. 검증 평가 {config['validation_users']:,}명, 테스트 평가 {frame.iloc[0]['evaluated_users']:,}명.",
           f"통합본과 원본 분할본의 전체 행 지문 일치: {audit.get('merged_matches_parts','not checked')}.", "",
           "아래 표는 검증 점수 순서입니다. 모든 테스트 사용자와 후보군은 같습니다.", "",
           "| 모델 | 검증 NDCG@10 | 테스트 Recall@10 | 테스트 NDCG@10 | 부정 상품 비율@10 ↓ | 상품 커버리지@10 |",
           "|---|---:|---:|---:|---:|---:|"]
    for _,row in frame.iterrows():
        name=f"**{row['model']}**" if row["model"]==selected else row["model"]
        lines.append(f"| {name} | {row['validation_ndcg@10']:.5f} | {row['recall@10']:.5f} | {row['ndcg@10']:.5f} | {row['known_negative@10']:.5f} | {row['catalogue_coverage_at_10']:.3%} |")
    selected_row=frame.loc[frame.model.eq(selected)].iloc[0]
    popular=frame.loc[frame.model.eq("global_popularity")].iloc[0]
    recall_gain=(selected_row["recall@10"]/popular["recall@10"]-1)*100
    ndcg_gain=(selected_row["ndcg@10"]/popular["ndcg@10"]-1)*100
    lines += ["", "## 이번 실행에서 알 수 있는 점", "",
              f"- 선택 설정의 인기도 기준 대비 상대 개선: Recall@10 {recall_gain:.1f}%, NDCG@10 {ndcg_gain:.1f}%.",
              "- 사용자 ID 포함/미포함 LightFM의 차이는 아래 paired bootstrap 구간으로 확인해야 합니다. 구간이 0을 포함하면 이 실행만으로 성능 우위를 확정하지 않습니다.",
              "- CatBoost·LightGBM은 이번 관측 리뷰 분류 구성에서 순위 지표가 낮았습니다. 긍정 리뷰의 노출·선택 빈도를 학습하는 WARP와 다른 목표이며, 트리의 상품 ID·입력 통제 및 ranking 목적 함수 실험 없이 알고리즘 자체가 열등하다고 일반화하지 않습니다.",
              f"- 선택 설정이 추천한 서로 다른 상품은 {round(selected_row['catalogue_coverage_at_10']*summary['skincare_catalogue_items']):,}/{summary['skincare_catalogue_items']:,}개입니다. 정확도 개선과 별도로 추천 집중도를 살펴볼 필요가 있습니다."]
    lines += ["", "## 저장된 LightFM 학습 체크포인트 크기", "", "| 설정 | 저장 크기 |", "|---|---:|"]
    for name in ["lightfm_profile","lightfm_skin_only","lightfm_identity_ablation"]:
        lines.append(f"| {name} | {(root/(name+'.joblib')).stat().st_size/1_000_000:.2f} MB |")
    lines += ["", "## 비교의 불확실성", "", "선택 모델의 NDCG@10에서 비교 모델의 값을 뺀 사용자별 차이에 대해 500회 paired bootstrap을 계산했습니다.", "",
              "| 비교 대상 | 평균 차이 | 95% 구간 |", "|---|---:|---|"]
    for row in uncertainty:
        if row["against"]==selected: continue
        low,high=row["paired_bootstrap_95ci"]
        lines.append(f"| {row['against']} | {row['ndcg_difference']:.5f} | [{low:.5f}, {high:.5f}] |")
    per_user=pd.read_csv(root/f"{selected}_per_user.csv",dtype={"author_id":str})
    by_skin=per_user.groupby("skin_type").agg(users=("author_id","size"),recall_at_10=("recall@10","mean"),
                                             ndcg_at_10=("ndcg@10","mean"),known_negative_at_10=("known_negative@10","mean"))
    by_skin.to_csv(root/"selected_by_skin_with_counts.csv")
    lines += ["", "## 선택 모델의 피부 타입별 결과", "", "| 피부 타입 | 평가 사용자 | Recall@10 | NDCG@10 |", "|---|---:|---:|---:|"]
    for skin,row in by_skin.iterrows():
        lines.append(f"| {skin} | {int(row['users']):,} | {row['recall_at_10']:.5f} | {row['ndcg_at_10']:.5f} |")
    lines += ["", "## 적용과 한계", "",
              "- 저장 모델은 `predict.py`로 새 프로필에 대해 조회할 수 있습니다. 기존 FastAPI의 모델 파일과 경로는 변경하지 않았습니다.",
              "- 원래 노트북의 Precision@10 등과는 평가 사용자·분할·후보가 달라 직접 비교할 수 없습니다.",
              "- LightFM은 긍정 리뷰, 트리 분류 모델은 관측된 긍정·부정 리뷰를 사용합니다. 단일 알고리즘 차이만 분리한 실험은 아닙니다.",
              "- LightFM에는 상품 ID 임베딩이 있고 트리에는 상품 속성만 넣었습니다. 성분 인코딩도 달라 알고리즘 자체의 우열을 확정할 수 없습니다. 트리에 상품 ID를 넣는 후속 통제 실험이 가능합니다.",
              "- 신규 사용자 분리는 적용했지만 시간 분할은 적용하지 않았습니다. 프로필은 첫 리뷰의 기재 정보이며 상품 정보는 정적 스냅샷입니다.",
              "- 지표는 리뷰 작성자의 긍정 상품 검색 성능이며 구매·효능·안전성·실제 전환율을 입증하지 않습니다.",
              "- 모델 초기화와 분할 seed는 하나입니다. bootstrap 구간은 모델 재학습의 변동성까지 반영하지 않습니다.",
              "- 피부 고민과 성능 목적의 직접 학습 라벨은 추가하지 않았습니다.",
              "", "![Model comparison](comparison.png)"]
    (root/"RESULTS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(1,3,figsize=(16,5.5),layout="constrained")
    labels=frame.model.tolist()
    colors=["#2563eb" if name==selected else "#94a3b8" for name in labels]
    for ax,column,title in zip(axes,["recall@10","ndcg@10","known_negative@10"],
                              ["Test Recall@10 (higher is better)","Test NDCG@10 (higher is better)","Known-negative@10 (lower is better)"]):
        ax.barh(labels,frame[column],color=colors)
        ax.invert_yaxis()
        ax.set_title(title,fontsize=10)
        ax.set_xlim(left=0)
        ax.grid(axis="x",alpha=.2)
        ax.set_axisbelow(True)
    figure.suptitle(f"Unseen users, fixed skincare catalogue | Blue: validation-selected {selected}",fontsize=12)
    figure.savefig(root/"comparison.png",dpi=150)
    plt.close(figure)
    print((root/"RESULTS.md").resolve())


if __name__=="__main__":
    main()
