# BeautyLens

> **자연어 질의 처리와 개인화 추천을 결합한 화장품 추천 프로토타입**

BeautyLens는 Sephora 상품/리뷰/성분 데이터와 MFDS 성분 정보를 활용해 사용자의 자연어 요청을 해석하고, 조건에 맞는 후보 상품을 찾은 뒤 LightFM으로 개인화 순위를 계산하는 추천 프로토타입입니다.

LLM이 상품 순위를 직접 결정하지 않도록 역할을 분리했습니다.

- **OpenAI API**: 요청 유형 분류, 일반 화장품 Q&A, 추천 결과 자연어 설명
- **Gemini**: 제품 추천 요청의 상세 조건 구조화
- **MariaDB**: 성분/제품 유형 기반 후보 상품 검증 및 필터링
- **LightFM**: 후보 상품의 개인화 Ranking
- **Bayesian Ranking**: LightFM 결과를 만들 수 없을 때 내부 Catalog Fallback
- **Gemini + Google Search**: 내부 DB에 후보 상품이 없을 때 외부 검색 Fallback
- **Google Trends**: 추천 점수와 분리된 검색 관심도 참고 정보

FastAPI와 Streamlit으로 전체 추천 흐름을 연결했고, AWS EC2 / RDS 환경에 프로토타입을 배포했습니다.

> 현재는 프로토타입 단계이며, 추천 모델은 Baseline 비교와 Top-K 성능 개선을 진행 중입니다.

---

## Key Highlights

- **2-Stage LLM Processing**  
  OpenAI API로 요청 유형을 먼저 분류한 뒤, 제품 추천 요청은 Gemini가 피부 타입/고민/성분/제품 유형 등 상세 조건으로 구조화

- **Candidate Filtering + Personalized Ranking**  
  MariaDB에서 조건에 맞는 상품을 먼저 찾고 LightFM이 후보군의 순위를 계산

- **Rule-based Validation**  
  Gemini 결과를 그대로 사용하지 않고 제품 유형, 피부 고민, 추천 모드 등을 서버 로직에서 다시 정규화/검증

- **Fallback Strategy**  
  `LightFM → Bayesian Ranking → Gemini + Google Search`로 결과 부재 상황을 단계적으로 처리

- **Offline Evaluation**  
  LightFM 튜닝 후 Precision@10 **+9.7%**, Recall@10 **+6.6%**, AUC **+1.2%**

- **End-to-End Prototype**  
  데이터 처리부터 추천 API, UI, AWS 배포까지 연결

---

## 1. Recommendation Flow

```text
사용자 자연어 입력
        ↓
OpenAI Intent Classification
        ↓
 ┌─────────────────────────────────────┐
 │ General Question → OpenAI Q&A       │
 │ Ingredient Trend → Google Trends    │
 │ Product Recommendation              │
 └─────────────────────────────────────┘
        ↓
Gemini Detailed Query Parsing
        ↓
Rule-based Normalization / Validation
        ↓
MariaDB Candidate Filtering
        ↓
LightFM Personalized Ranking
        ↓
Fallback Handling
        ↓
OpenAI Result Explanation
        ↓
FastAPI → Streamlit
```

OpenAI와 Gemini의 역할을 분리했습니다.

OpenAI API는 먼저 요청을 다음 세 유형으로 분류합니다.

```text
general_question
product_recommendation
ingredient_trend
```

제품 추천으로 분류된 요청은 Gemini가 다시 세부 조건을 추출합니다.

```text
skin_type
skin_tone
eye_color
hair_color
skin_concerns
ingredient
product_type
recommendation_mode
performance_goal
```

---

## 2. Query Parsing & Validation

### Gemini 상세 조건 파싱

예를 들어 다음 요청은

```text
"건성인데 모공 때문에 고민이야. 세럼 추천해줘."
```

다음과 같은 구조로 변환됩니다.

```text
skin_type = dry
skin_concerns = [pores]
product_type = serum
recommendation_mode = skincare
```

Gemini 출력은 바로 추천에 사용하지 않습니다.

서버에서 다음 항목을 다시 검증합니다.

- 피부 타입/피부톤/눈 색상/머리 색상 표준화
- 피부 고민 Alias 정규화
- 너무 넓은 제품 유형 제거
- `skincare` / `product_performance` 추천 모드 재판단
- 성능 목적 정규화
- 추천에 필요한 정보가 부족한 경우 `missing_fields` 생성

### 추천 모드 분리

BeautyLens는 요청을 크게 두 가지로 구분합니다.

**Skincare**

```text
"모공이 고민인데 세럼 추천해줘"
"건성 피부에 크림 추천해줘"
"나이아신아마이드 세럼 추천해줘"
```

**Product Performance**

```text
"모공 커버 잘 되는 프라이머 추천해줘"
"지속력 좋은 쿠션 추천해줘"
"발색 좋은 립스틱 추천해줘"
```

제품 성능 요청에서는 사용자가 성분을 지정하지 않았다면 성분을 임의로 자동 선택하지 않습니다.

---

## 3. Data Pipeline

### Review Data

Sephora 데이터에는 일반적인 구매 이력보다 리뷰 데이터가 중심이므로 리뷰 이력을 User-Item Interaction 형태로 가공했습니다.

```text
Sephora Review Data
        ↓
Review Cleaning
        ↓
Interaction Generation
        ↓
Validation
        ↓
MariaDB
        ↓
LightFM
```

### Ingredient Data

상품 성분은 문자열 형태로 제공되기 때문에 그대로 조건 검색에 사용하기 어렵습니다.

```text
Sephora Product Data
        ↓
Ingredient Parsing
        ↓
Ingredient Normalization
        ↓
MFDS Ingredient Matching
        ↓
Product-Ingredient Mapping
        ↓
MariaDB
```

MFDS 데이터는 성분명과 사용 제한 관련 정보를 보완하는 용도로 결합했습니다.

### 주요 데이터 구조

| Data | Role |
| --- | --- |
| `products` | 상품명, 브랜드, 가격, 평점, 리뷰 수 등 |
| `ingredients` | 정규화 성분 및 MFDS 연계 정보 |
| `product_ingredients` | 상품-성분 Mapping |
| `interactions` | LightFM 학습용 User-Item Interaction |
| `dataset_metadata` | 데이터셋 메타데이터 |

---

## 4. Candidate Filtering

사용자는 전체 상품이 아니라 특정 조건을 포함한 상품을 요청합니다.

```text
"나이아신아마이드 세럼 추천해줘"
"건성 피부에 크림 추천해줘"
```

따라서 전체 상품을 바로 Ranking하지 않고 먼저 MariaDB에서 후보를 찾습니다.

### 성분이 있는 요청

```text
Ingredient
   ↓
ingredients에서 성분명 / 한글명 / 동의어 확인
   ↓
product_ingredients JOIN
   ↓
Product Type Filter
   ↓
Candidate Pool
```

### 성분이 없는 Skincare 요청

피부 고민과 피부 타입을 기준으로 **미리 정의한 성분 후보**를 생성합니다.

```text
Skin Concern / Skin Type
        ↓
Rule-based Ingredient Candidates
        ↓
DB Ingredient Validation
        ↓
Candidate Search
        ↓
LightFM 추천 가능 여부 확인
```

즉, LLM이 임의로 성분을 만들어 추천하는 구조가 아니라 서버에 정의한 Mapping과 실제 DB를 함께 확인합니다.

---

## 5. LightFM Recommendation

DB에서 만들어진 후보군을 대상으로 LightFM Ranking을 수행합니다.

```text
Candidate Product IDs
        ↓
User Profile
- skin_type
- skin_tone
- eye_color
- hair_color
        ↓
recommend_new_user_from_candidates()
        ↓
LightFM Ranking
        ↓
Top-K
```

현재 추천 흐름에서는 사용자 프로필 값을 LightFM 추천 함수에 전달합니다.

다만 이 README에서는 내부 모델의 Side Feature 구성 방식이나 Cold-start 효과를 실제 모델 코드와 별도 평가 없이 과장하지 않습니다.

### 현재 모델 개선 상태

| Model | Precision@10 | Recall@10 | AUC |
| --- | ---: | ---: | ---: |
| Untuned LightFM | 0.015545 | 0.110722 | 0.854744 |
| Tuned LightFM | 0.017057 | 0.118033 | 0.865102 |

튜닝 후 상대 개선율:

- Precision@10: **+9.7%**
- Recall@10: **+6.6%**
- AUC: **+1.2%**

AUC에 비해 Precision@10과 Recall@10이 낮기 때문에 단순 추가 학습보다 평가 구조와 데이터 구성을 먼저 점검하고 있습니다.

```text
Interaction 정의
      ↓
Train / Test Split
      ↓
Data Sparsity
      ↓
Cold-start
      ↓
User / Item Feature
      ↓
Hyperparameter Tuning
```

현재 비교는 LightFM 내부의 튜닝 전후 비교이므로 다음 단계에서는 Popularity, Item-based CF, SVD를 동일한 조건에서 비교할 예정입니다.

---

## 6. Fallback Strategy

추천 결과가 생성되지 않는 상황을 세 단계로 처리합니다.

| Priority | Method | Condition |
| --- | --- | --- |
| 1 | **LightFM** | DB 후보가 있고 모델 추천이 가능한 경우 |
| 2 | **Bayesian Ranking** | DB 후보는 있지만 LightFM 결과가 없는 경우 |
| 3 | **Gemini + Google Search** | DB 후보 자체가 없는 경우 |

### Bayesian Ranking

내부 DB 후보가 있지만 LightFM 결과를 만들 수 없는 경우 평균 평점과 리뷰 수를 함께 고려해 순위를 계산합니다.

```text
Weighted Rating
= (v / (v + m)) × R
+ (m / (v + m)) × C
```

- `R`: 상품 평균 평점
- `v`: 상품 리뷰 수
- `C`: 후보 상품 평균 평점
- `m`: 후보 상품 리뷰 수 기준값

이 방식은 LightFM을 대체하는 주 모델이 아니라 내부 Catalog Fallback입니다.

### Gemini + Google Search

DB에 현재 조건과 일치하는 후보 상품이 없는 경우에만 외부 상품을 실시간 탐색합니다.

외부 검색 결과는:

- MariaDB에 자동 저장하지 않음
- 요청 시점에만 조회
- 데이터셋 기반 개인화 추천과 구분
- LightFM Score와 합산하지 않음
- 검색 결과에 없는 가격/평점/리뷰 수를 생성하지 않음

---

## 7. Google Trends

Google Trends는 추천 Ranking Score에 직접 반영하지 않습니다.

```text
LightFM
→ 개인화 추천

Bayesian Ranking
→ 내부 Catalog Fallback

Gemini + Google Search
→ DB 후보 부재 시 외부 검색

Google Trends
→ 검색 관심도 참고 정보
```

현재 서비스는 최근 12개월 데이터를 조회하며, 최근 4주 평균과 직전 4주 평균을 비교해 변화율을 제공합니다.

Google Trends의 0~100 값은 실제 검색 건수가 아니라 선택한 지역과 기간에서의 상대적 검색 관심도입니다.

---

## 8. Product Performance Request

현재 데이터셋에는 다음과 같은 제품 사용 성능에 대한 직접적인 Label이 없습니다.

```text
커버력
블러
지속력
밀착력
발색
```

따라서 `"지속력 좋은 쿠션"`과 같은 요청은 의도와 제품 유형을 파악할 수 있지만, 실제 지속력이 더 우수하다고 학습하거나 검증한 Ranking은 아닙니다.

현재 로직은:

```text
Performance Request
        ↓
Product Type / Performance Goal Parsing
        ↓
Product Type Candidate Filtering
        ↓
LightFM Ranking
```

DB 후보가 없는 경우에만 외부 검색 결과를 별도로 제공합니다.

---

## 9. API & Deployment

FastAPI는 요청 라우팅과 추천 엔진 호출을 담당하고, Streamlit은 사용자 UI를 담당합니다.

```text
Internet
   ↓
┌──────────── AWS EC2 ────────────┐
│ Nginx :80                       │
│      ↓                          │
│ Streamlit :8501                 │
│      ↓                          │
│ FastAPI :8000                   │
└─────────────────────────────────┘
              ↓
       RDS MariaDB :3306
```

AWS EC2에서 FastAPI와 Streamlit 서비스를 실행하고, systemd와 Nginx Reverse Proxy를 구성해 외부 접속 가능한 프로토타입 환경을 구축했습니다.

### Offline / Online 분리

```text
[Offline]

Sephora / MFDS
      ↓
Airflow
      ↓
S3 / Python ETL
      ↓
MariaDB / Model


[Online]

User Request
      ↓
OpenAI / Gemini
      ↓
Candidate Filtering
      ↓
LightFM / Fallback
      ↓
FastAPI
      ↓
Streamlit
```

Airflow와 ETL은 실시간 사용자 요청마다 실행되는 구조가 아닙니다.

---

## 10. Key Modules

| File | Role |
| --- | --- |
| `airflow/dags/ingredient_pipeline.py` | Sephora 성분 정제 및 MFDS 정보 결합 |
| `airflow/dags/review_pipeline.py` | 리뷰 전처리 및 Interaction 생성 |
| `src/cosmetics/query/user_query_parser.py` | Gemini 기반 상세 추천 조건 파싱 및 정규화 |
| `src/cosmetics/ingredients/ingredient_repository.py` | 후보 상품 필터링, 자동 성분 후보, 추천/Fallback 흐름 |
| `src/recommendation/sephora_lightfm.py` | LightFM Ranking |
| `src/cosmetics/trends/google_trends_collector.py` | Google Trends 조회 |
| `src/cosmetics/trends/product_trend_collector.py` | Gemini + Google Search 외부 상품 탐색 |
| `src/api/main.py` | OpenAI Intent 분류/응답 생성 및 FastAPI Backend |
| `streamlit/streamlit_app.py` | Streamlit UI |

---

## Tech Stack

| Category | Technology |
| --- | --- |
| Language | Python |
| Recommendation | LightFM |
| LLM | OpenAI API, Gemini API |
| Search | Google Search |
| Data Processing | Pandas, NumPy, SciPy |
| Backend | FastAPI, Uvicorn |
| Frontend | Streamlit |
| Database | MariaDB, PyMySQL |
| Pipeline | Apache Airflow |
| Storage | Amazon S3, Boto3 |
| Trend Data | Google Trends |
| External Data | Sephora Dataset, MFDS |
| Deployment | AWS EC2, RDS, Nginx, systemd |

---

## Current Limitations & Next Steps

### 현재 한계

1. 현재 모델 비교는 LightFM 튜닝 전후 결과에 한정되어 있음
2. AUC에 비해 Precision@10 / Recall@10이 낮음
3. 제품 성능에 대한 직접 Label이 없어 성능 우수성을 학습한 모델은 아님
4. 사용자 프로필을 전달하는 추천 구조는 구현했지만 Cold-start 효과는 별도 평가가 필요함

### 다음 실험

```text
Popularity
→ Item-based CF
→ SVD
→ LightFM
→ Feature / Tuned LightFM
```

- 동일한 Split / Metric으로 모델 비교
- Interaction Positive 기준 재검토
- Random Split 외 User-based / Temporal Split 검토
- User / Item Feature 효과 검증
- Cold-start User Cohort 분석
- Precision@K / Recall@K 중심 Top-K 성능 개선

---

## Summary

BeautyLens는 하나의 LLM이 추천을 모두 수행하는 구조가 아닙니다.

```text
OpenAI API
→ 요청 유형 분류 / 일반 Q&A / 추천 결과 설명

Gemini
→ 제품 추천 요청의 상세 조건 구조화

Server Rules
→ 값 정규화 / 추천 모드 판단 / 자동 성분 후보 생성

MariaDB
→ 성분/제품 유형 검증 및 Candidate Filtering

LightFM
→ Personalized Ranking

Bayesian Ranking
→ Internal Catalog Fallback

Gemini + Google Search
→ External Search Fallback

Google Trends
→ Search Interest Reference
```

현재는 서비스 기능을 더 추가하기보다 **Baseline 비교 → 평가 방식 점검 → Top-K 성능 개선** 순서로 추천 모델을 보강하고 있습니다.
