# BeautyLens

> **자연어 질의 해석과 개인화 추천을 결합한 화장품 추천 프로토타입**

BeautyLens는 Sephora 상품·리뷰·성분 데이터와 MFDS 성분 정보를 활용해
사용자의 자연어 요청을 구조화하고, 조건에 맞는 상품 후보를 찾은 뒤 개인화 순위를 제공하는 추천 프로토타입입니다.

현재는 **데이터 전처리 → 자연어 질의 해석 → 후보 상품 필터링 → LightFM Ranking → Fallback → FastAPI → Streamlit**까지 연결해 전체 추천 흐름을 검증했습니다.

> 현재 프로젝트는 프로토타입 단계이며, 추천 모델은 Baseline 비교와 Top-K 성능 개선을 진행 중입니다.

---

## 1. Project Overview

### 문제 정의

일반적인 인기순·평점순 추천만으로는 화장품 선택에 필요한 개인 조건을 충분히 반영하기 어렵습니다.

BeautyLens에서는 다음과 같은 정보를 추천 조건으로 활용합니다.

- 피부 타입
- 피부 고민
- 피부톤
- 눈 색상
- 머리 색상
- 원하는 성분
- 제품 유형
- 커버력·지속력·밀착력·발색 등 사용 목적

사용자의 자연어 요청을 구조화한 뒤, DB에서 조건에 맞는 후보 상품을 먼저 찾고 추천 모델이 후보군의 순위를 계산하도록 구성했습니다.

### 현재 구현 범위

- Gemini 기반 자연어 Query Parsing
- Sephora 리뷰 기반 User-Item Interaction 구성
- 성분 파싱·정규화 및 상품-성분 Mapping
- MFDS 성분 정보 결합
- MariaDB 기반 Candidate Filtering
- LightFM 기반 Personalized Ranking
- Bayesian Ranking Fallback
- DB 후보 부재 시 Gemini + Google Search 기반 외부 검색
- Google Trends 검색 관심도 참고 정보
- FastAPI + Streamlit 기반 추천 프로토타입
- AWS EC2 / RDS 환경 배포

---

## 2. System Architecture

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/2cc7cf04-1fa7-4602-ad7f-711e3149faea"
    alt="BeautyLens System Architecture"
    width="100%"
  />
</p>

```text
Sephora Dataset / MFDS
          ↓
      Airflow
          ↓
       S3
          ↓
     Python ETL
          ↓
      MariaDB
          ↓
Gemini Query Parsing
          ↓
 Candidate Filtering
          ↓
  LightFM Ranking
          ↓
   Fallback Logic
          ↓
       FastAPI
          ↓
      Streamlit
```

Google Trends는 LightFM Ranking Score에 합산하지 않고,
추천 결과와 함께 제공하는 **검색 관심도 참고 정보**로 분리했습니다.

---

## 3. Data Pipeline

### 3.1 Review Data

Sephora 데이터에는 일반적인 구매 이력 대신 리뷰 데이터가 중심이므로,
리뷰 이력을 추천 모델에서 사용할 User-Item Interaction 형태로 가공했습니다.

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

### 3.2 Ingredient Data

상품 성분은 문자열 형태로 제공되기 때문에 그대로 조건 검색에 사용하기 어렵습니다.

따라서 성분을 파싱·정규화한 뒤 상품과 성분을 별도 관계로 관리하도록 구조를 변경했습니다.

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
| `ingredients` | 정규화된 성분 정보 및 MFDS 연계 정보 |
| `product_ingredients` | 상품-성분 Mapping |
| `interactions` | LightFM 학습용 User-Item Interaction |
| `dataset_metadata` | 데이터셋 메타데이터 |

---

## 4. Natural Language Query Parsing

Gemini는 상품 Ranking을 직접 수행하지 않습니다.

사용자의 자연어 입력을 추천 시스템이 사용할 수 있는 구조화된 조건으로 변환하는 역할을 담당합니다.

### Parsed Fields

```text
skin_type
skin_tone
eye_color
hair_color
concerns
ingredient
product_type
recommendation_mode
performance_goal
```

예시:

```text
사용자 입력
"건성인데 모공 때문에 고민이야. 세럼 추천해줘."

        ↓

skin_type = dry
concerns = pores
product_type = serum
recommendation_mode = skincare
```

추천에 필요한 조건이 부족한 경우 추가 질문을 통해 정보를 보완합니다.

```text
사용자: 지속력 좋은 거 추천해줘
BeautyLens: 원하는 제품 종류를 알려주세요.
사용자: 쿠션
```

후속 답변은 이전 질문의 Context와 결합해 최종 추천 요청으로 처리합니다.

---

## 5. Recommendation Flow

BeautyLens의 추천 흐름은 크게 **조건 필터링 → 개인화 Ranking → Fallback**으로 구성됩니다.

```text
사용자 자연어 입력
        ↓
Gemini Query Parsing
        ↓
추천 조건 구조화
        ↓
MariaDB Candidate Filtering
        ↓
LightFM Personalized Ranking
        ↓
Fallback Handling
        ↓
추천 결과 반환
```

### Candidate Filtering

사용자는 전체 화장품이 아니라 특정 조건을 포함한 상품을 요청합니다.

예:

```text
"나이아신아마이드 세럼 추천해줘"
"건성 피부에 크림 추천해줘"
"모공 커버 잘 되는 프라이머 추천해줘"
```

따라서 전체 상품을 바로 Ranking하지 않고,
먼저 성분·제품 유형·사용 조건을 기준으로 후보 상품을 줄인 뒤 LightFM이 후보군의 순위를 계산하도록 구성했습니다.

---

## 6. LightFM Recommendation

현재 추천 모델은 **LightFM 기반 Personalized Ranking**을 사용합니다.

Sephora 리뷰 데이터를 기반으로 User-Item Interaction을 구성하고,
DB에서 필터링된 후보 상품을 대상으로 개인화 순위를 계산합니다.

```text
Review Interaction
        ↓
     LightFM
        ↓
Candidate Item Scores
        ↓
      Top-K
```

### 현재 구현과 다음 단계

| 구분 | 현재 구현 | 다음 개선 |
| --- | --- | --- |
| Interaction | 리뷰 기반 User-Item Interaction | Positive 정의 및 최소 Interaction 기준 재검토 |
| Candidate | 성분·제품 유형 기반 DB Filtering | 조건별 후보군 품질 분석 |
| User Feature | 입력 정보 수집 및 연동 구조 확보 | 피부 타입·고민·피부톤 등 Feature 실험 |
| Item Feature | 상품·성분 DB 구조 확보 | 성분·카테고리 Feature 연동 |
| Evaluation | LightFM 튜닝 전후 1차 비교 | Popularity / Item-CF / SVD Baseline 비교 |

> LightFM은 Side Feature를 함께 활용할 수 있는 모델이지만, 현재 README에서는 **구현 완료된 기능과 향후 Feature 확장 계획을 구분해 표현**합니다.

---

## 7. Offline Evaluation

현재 LightFM의 튜닝 전후 결과를 동일한 지표로 비교했습니다.

| Model | Precision@10 | Recall@10 | AUC |
| --- | ---: | ---: | ---: |
| Untuned LightFM | 0.015545 | 0.110722 | 0.854744 |
| Tuned LightFM | 0.017057 | 0.118033 | 0.865102 |

튜닝 후 세 지표 모두 개선됐습니다.

- Precision@10: 약 **+9.7%**
- Recall@10: 약 **+6.6%**
- AUC: 약 **+1.2%**

다만 AUC에 비해 Precision@10과 Recall@10이 낮게 나타났기 때문에,
현재는 단순히 Epoch을 더 늘리기보다 **Top-K 성능이 낮은 원인을 먼저 점검**하고 있습니다.

### 현재 확인 중인 항목

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

현재 비교는 LightFM 내부의 튜닝 전후 비교이므로,
다음 단계에서는 Popularity, Item-based CF, SVD를 동일한 Split과 동일한 Metric으로 비교할 예정입니다.

---

## 8. Fallback Strategy

추천 모델에서 결과가 생성되지 않는 상황을 별도로 처리합니다.

| Priority | Method | Condition |
| --- | --- | --- |
| 1 | LightFM | DB 후보가 존재하고 LightFM Ranking이 가능한 경우 |
| 2 | Bayesian Ranking | DB 후보는 존재하지만 LightFM 결과를 사용할 수 없는 경우 |
| 3 | Gemini + Google Search | DB에 조건과 맞는 후보 상품이 없는 경우 |

### Bayesian Ranking

리뷰 수가 적은 상품이 높은 평균 평점만으로 과대평가되는 문제를 줄이기 위해
Fallback Ranking에서는 평균 평점과 리뷰 수를 함께 고려합니다.

```text
Weighted Rating
= (v / (v + m)) × R
+ (m / (v + m)) × C
```

- `R`: 상품 평균 평점
- `v`: 상품 리뷰 수
- `C`: 전체 상품 평균 평점
- `m`: 최소 리뷰 기준값

Bayesian Ranking은 LightFM을 대체하는 주 모델이 아니라 **Fallback**으로 사용합니다.

### Web Search

내부 DB에 조건과 일치하는 후보 상품이 없는 경우 Gemini + Google Search를 이용해 외부 상품을 탐색합니다.

외부 검색 결과는:

- 내부 DB에 저장하지 않음
- 요청 시점에만 조회
- 내부 개인화 추천과 구분해 표시
- LightFM Score와 합산하지 않음

---

## 9. Google Trends

Google Trends는 추천 모델의 Ranking Score에 직접 사용하지 않습니다.

```text
LightFM
→ 개인화 추천

Gemini + Google Search
→ DB 후보 부재 시 외부 검색

Google Trends
→ 검색 관심도 참고 정보
```

개인화 추천과 외부 검색 관심도는 의미가 다르기 때문에 UI에서도 별도 영역으로 제공합니다.

---

## 10. API & Deployment

추천 로직은 FastAPI Backend로 분리하고 Streamlit에서 호출하도록 구성했습니다.

```text
Recommendation Request
        ↓
Query Parsing
        ↓
Candidate Filtering
        ↓
Recommendation Engine
        ↓
Fallback Handling
        ↓
API Response
```

### Deployment

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

AWS EC2 환경에서 FastAPI와 Streamlit 서비스를 실행하고,
systemd와 Nginx Reverse Proxy를 구성해 외부 접속 가능한 프로토타입 환경을 구성했습니다.

---

## 11. Key Modules

| File | Role |
| --- | --- |
| `airflow/dags/ingredient_pipeline.py` | Sephora 성분 정제 및 MFDS 정보 결합 |
| `airflow/dags/review_pipeline.py` | 리뷰 전처리 및 Interaction 생성 |
| `src/cosmetics/query/user_query_parser.py` | Gemini 기반 자연어 Query Parsing |
| `src/cosmetics/ingredients/ingredient_repository.py` | 후보 상품 검색 및 추천 흐름 관리 |
| `src/recommendation/sephora_lightfm.py` | LightFM Ranking |
| `src/cosmetics/trends/google_trends_collector.py` | Google Trends 조회 |
| `src/cosmetics/trends/product_trend_collector.py` | 외부 상품 검색 |
| `src/api/main.py` | FastAPI Backend |
| `streamlit/streamlit_app.py` | Streamlit UI |

---

## 12. Tech Stack

| Category | Technology |
| --- | --- |
| Language | Python |
| Recommendation | LightFM |
| LLM | Gemini API |
| Search | Google Search Grounding |
| Data Processing | Pandas, NumPy, SciPy |
| Backend | FastAPI, Uvicorn |
| Frontend | Streamlit |
| Database | MariaDB, PyMySQL |
| Pipeline | Apache Airflow |
| Storage | Amazon S3, Boto3 |
| Trend Data | Google Trends |
| External Data | Sephora Dataset, MFDS |

---

## 13. Current Limitations

### Recommendation Model

현재 모델 비교는 LightFM의 튜닝 전후 결과에 한정되어 있습니다.

따라서 LightFM의 상대적인 성능을 판단하기 위해 다음 Baseline 비교가 필요합니다.

```text
Popularity
→ Item-based CF
→ SVD
→ LightFM
→ Tuned / Feature LightFM
```

### Product Performance Data

현재 데이터셋에는 다음과 같은 사용 성능에 대한 직접적인 Label이 없습니다.

```text
커버력
블러
지속력
밀착력
발색
```

따라서 해당 요청의 의도와 제품 유형은 해석할 수 있지만,
해당 성능 자체가 더 우수하다고 학습하거나 검증한 Ranking은 아닙니다.

### Cold-start

LightFM은 User / Item Side Feature를 사용할 수 있지만,
현재는 Side Feature를 포함한 Cold-start 성능을 별도로 검증하는 단계가 남아 있습니다.

따라서 **Cold-start를 해결했다고 표현하지 않고, 향후 Feature 적용 및 평가 대상으로 구분**합니다.

---

## 14. Next Steps

1. Popularity / Item-CF / SVD Baseline 구축
2. 동일한 Split과 Metric으로 모델 비교
3. Interaction Positive 기준 재검토
4. Random Split 외 User-based / Temporal Split 검토
5. User / Item Side Feature 실험
6. Precision@K / Recall@K 중심 Top-K 성능 분석
7. Cold-start User Cohort 별 성능 비교
8. LightFM Hyperparameter 재튜닝
9. Query Parsing Validation 강화
10. 모델 및 데이터 모니터링 구조 개선

---

## Summary

BeautyLens는 단순히 추천 알고리즘 하나를 구현하는 것보다,

```text
Data Processing
      ↓
Database
      ↓
Natural Language Query Parsing
      ↓
Candidate Filtering
      ↓
Personalized Ranking
      ↓
Fallback
      ↓
API
      ↓
User Application
```

으로 이어지는 추천 흐름을 실제 프로토타입으로 연결하는 데 초점을 두었습니다.

현재는 서비스 기능을 더 추가하기보다
**Baseline 비교 → 평가 방식 점검 → Top-K 성능 개선** 순서로 추천 모델 자체를 보강하고 있습니다.
