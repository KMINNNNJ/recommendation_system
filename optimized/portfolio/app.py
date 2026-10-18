"""Run from any folder with: python -m streamlit run /absolute/path/app.py."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

import streamlit as st
from optimized.portfolio.service import DemoModels, comparison_table

st.set_page_config(page_title="처음 만나는 스킨케어 추천",page_icon="🧴",layout="wide")


@st.cache_resource(show_spinner="저장된 추천 모델을 불러오는 중입니다…")
def load_models():
    return DemoModels()


def show_products(rows):
    if not rows:
        st.info("조건에 맞는 추천 상품이 없습니다. 예산이나 제외 성분을 조정해 주세요.")
        return
    for row in rows:
        with st.container(border=True):
            st.markdown(f"**{row['rank']}. {row['product_name']}**")
            price=f"${row['price_usd']:.2f}" if row["price_usd"] is not None else "가격 미기재"
            st.caption(f"{row['brand_name']} · {price}")
    st.caption(f"표시 상품 {len(rows)}개 · 브랜드 {len({row['brand_name'] for row in rows})}개")


st.title("처음 만나는 스킨케어 추천")
st.write("사용 이력 없이 프로필과 원하는 조건을 입력하고, 원본 설정과 개선 모델의 추천을 비교해 보세요.")

try:
    models=load_models()
except (FileNotFoundError,ValueError,ImportError) as error:
    st.error("데모에 필요한 모델 또는 실행 환경을 확인해 주세요.")
    st.code(str(error))
    st.info("optimized/portfolio/README.md의 준비·실행 순서를 확인하세요.")
    st.stop()

labels={"unknown":"선택 안 함","dry":"건성","oily":"지성","combination":"복합성","normal":"중성"}
category_labels={"moisturizers":"보습제","treatments":"트리트먼트","cleansers":"클렌저",
                 "mini size":"미니사이즈","eye care":"아이 케어","masks":"마스크",
                 "sunscreen":"선케어","lip balms & treatments":"립 케어"}

with st.form("recommendation_form"):
    left,right=st.columns(2)
    with left:
        skin_options=["unknown"]+[value for value in models.vocabulary["skin_type"] if value != "unknown"]
        skin=st.selectbox("피부 타입",skin_options,format_func=lambda value:labels.get(value,value),key="skin_type")
        category=st.selectbox("제품 종류",[None]+models.categories,
                              format_func=lambda value:"전체 스킨케어" if value is None else category_labels.get(value,value),key="category")
        budget_enabled=st.checkbox("예산 설정",value=False,key="budget_enabled")
        budget=st.number_input("최대 가격 (USD)",min_value=0.,value=50.,step=5.,key="max_price_usd")
    with right:
        profile={"skin_type":skin}
        for column,label in [("skin_tone","피부톤"),("eye_color","눈동자색"),("hair_color","머리색")]:
            options=["unknown"]+[value for value in models.vocabulary[column] if value != "unknown"]
            profile[column]=st.selectbox(label,options,format_func=lambda value:"선택 안 함" if value=="unknown" else value,key=column)
    excluded=st.multiselect("제외할 성분명",models.ingredient_options,
                            help="데이터에 기록된 성분명과 완전히 일치하는 상품을 제외합니다. 동의어와 성분 농도는 판단하지 않습니다.")
    diversity=st.checkbox("브랜드 중복 줄이기",value=False,
                          help="검증에서 선택한 재정렬을 적용합니다. 정확도 향상이 확인된 기능은 아닙니다.")
    top_k=st.select_slider("추천 개수",options=[5,10],value=10)
    submitted=st.form_submit_button("추천 비교하기",type="primary")

st.caption("가격은 데이터셋에 저장된 USD 가격입니다. 제외 성분은 기록된 이름의 완전 일치이며 안전성 판정 기능이 아닙니다.")

if submitted:
    with st.spinner("같은 조건으로 두 모델의 추천을 계산하는 중입니다…"):
        result=models.compare(profile,category,budget if budget_enabled else None,excluded,top_k,diversity)
    st.session_state["comparison_result"]=result

if "comparison_result" in st.session_state:
    result=st.session_state["comparison_result"]
    st.subheader("추천 결과")
    st.caption(f"입력 후 ‘추천 비교하기’를 누른 결과입니다. 조건에 맞는 후보 {result['candidate_count']:,}개 · 원본 모델이 지원하는 후보 {result['original_supported_candidates']:,}개")
    left,right=st.columns(2)
    with left:
        st.markdown("### 원본 설정 재학습 모델")
        show_products(result["original"])
    with right:
        st.markdown("### 개선 모델"+(" · 브랜드 중복 조정" if result["diversity_weight"] else ""))
        show_products(result["improved"])
    st.caption("원본은 노트북의 30회 학습 설정을 공통 학습 사용자로 다시 학습한 모델입니다. 추천 목록만으로 정확도를 판정할 수는 없습니다.")

with st.expander("실험 결과와 해석",expanded=False):
    table=comparison_table()
    ndcg_gain=(table.iloc[1]["NDCG@10"]/table.iloc[0]["NDCG@10"]-1)*100
    st.metric("원본 설정 재학습 대비 NDCG@10 상대 향상",f"{ndcg_gain:.1f}%")
    st.dataframe(table,hide_index=True,width="stretch")
    st.write("동일한 신규 사용자 10,000명과 동일 후보를 평가했습니다. 위 표는 필터·브랜드 재정렬 적용 전의 오프라인 결과입니다.")
    st.write("브랜드 재정렬은 평균 브랜드 수를 7.70개에서 9.41개로 늘렸지만, NDCG 향상은 확인되지 않았고 노출된 고유 상품은 74개에서 73개로 줄었습니다.")
    st.caption("실제 만족도·피부 개선 효과는 측정하지 않았습니다. 원본 대비 향상에는 전처리·특징·학습 구성의 여러 변경이 함께 포함됩니다.")
