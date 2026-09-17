
# BeautyLens

> 자연어 질의와 사용자 특성을 기반으로 화장품을 추천하는 개인화 추천 프로토타입

BeautyLens는 사용자의 피부 정보와 자연어 질문을 분석해 적합한 화장품 후보를 탐색하고,  
**LightFM 기반 Hybrid Recommendation**, **Bayesian Fallback**, **Gemini + Google Search**, **Google Trends**를 활용해 추천 결과를 제공합니다.

단순 추천 모델 구현에 그치지 않고,  
**데이터 수집·전처리 → 성분 정제 → DB 적재 → 추천 → API → UI**까지 이어지는 전체 서비스 흐름을 구현했습니다.

> 현재는 포트폴리오 및 기능 검증을 위한 프로토타입 단계입니다.

---

## 1. Project Overview

BeautyLens는 사용자의 자연어 질문에서 추천 조건을 추출하고,  
조건에 맞는 상품 후보를 데이터베이스에서 탐색한 뒤 개인화 추천을 수행합니다.

### Example Queries

```text
모공이 고민인데 세럼 추천해줘
나이아신아마이드 세럼 추천해줘
건성 피부에 크림 추천해줘
지속력 좋은 쿠션 추천해줘
모공 커버 잘 되는 프라이머 추천해줘
```

추천에 필요한 정보가 부족한 경우에는 추가 질문을 통해 조건을 보완합니다.

```text
사용자: 지속력 좋은 거 추천해줘
BeautyLens: 원하는 제품 종류를 알려주세요.
사용자: 쿠션
```

후속 답변은 기존 질문과 결합해 다시 추천에 사용합니다.

---

## 2. Key Features

- 자연어 기반 화장품 추천 질의 처리
- 피부 타입·피부 고민·성분·제품 유형 기반 후보 필터링
- LightFM 기반 Hybrid Recommendation
- 신규 사용자 프로필을 활용한 Cold-start 추천
- LightFM 추천이 어려운 경우 Bayesian Ranking Fallback
- 내부 데이터에 후보가 없는 경우 Gemini + Google Search 기반 외부 상품 탐색
- Google Trends 기반 검색 관심도 제공
- Sephora 상품·리뷰 데이터 전처리 파이프라인
- MFDS 성분 사전 및 사용 제한 정보 결합
- FastAPI 기반 추천 API
- Streamlit 기반 사용자 인터페이스

---

## 3. System Architecture

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/2cc7cf04-1fa7-4602-ad7f-711e3149faea"
    alt="BeautyLens System Architecture"
    width="100%"
  />
</p>

### Architecture Flow

```text
Sephora / MFDS
      ↓
Apache Airflow
      ↓
Amazon S3
      ↓
Python ETL
      ↓
MariaDB
      ↓
Recommendation Engine
      ↓
FastAPI
      ↓
Streamlit
```

Google Trends는 추천 점수에 직접 합산하지 않고,  
추천 결과와 함께 확인할 수 있는 **검색 관심도 참고 정보**로 제공합니다.

---

## 4. Recommendation Flow

```text
사용자 자연어 질문
        ↓
Gemini Query Parsing
        ↓
추천 조건 구조화
        ↓
DB Candidate Filtering
        ↓
LightFM Hybrid Recommendation
        ↓
추천 결과 반환
```

LightFM으로 결과를 만들 수 없는 경우에는 다음 순서로 Fallback을 적용합니다.

| Priority | Method | Condition |
| --- | --- | --- |
| 1 | **LightFM Hybrid Recommendation** | DB 후보가 존재하고 LightFM에서 추천 가능한 경우 |
| 2 | **Bayesian Ranking Fallback** | DB 후보는 있지만 LightFM 추천 결과가 없는 경우 |
| 3 | **Gemini + Google Search** | DB에 조건과 맞는 후보 상품 자체가 없는 경우 |

외부 검색 결과는 데이터셋 기반 개인화 추천과 구분해 사용자에게 표시합니다.

---

## 5. Recommendation Logic

### 5.1 Natural Language Query Parsing

Gemini를 이용해 자연어 질문을 추천 시스템에서 사용할 수 있는 구조로 변환합니다.

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

추천 요청은 크게 두 가지 유형으로 구분합니다.

#### Skincare

피부 타입, 피부 고민, 성분을 중심으로 후보 상품을 탐색합니다.

```text
모공이 고민인데 세럼 추천해줘
건성 피부에 크림 추천해줘
```

#### Product Performance

커버력, 블러, 지속력, 밀착력, 발색 등 제품 사용 성능과 관련된 요청을 처리합니다.

```text
지속력 좋은 쿠션 추천해줘
모공 커버 잘 되는 프라이머 추천해줘
```

제품 성능 요청에서는 사용자가 성분을 직접 지정하지 않은 경우 성분을 자동 선택하지 않습니다.

### 5.2 Ingredient Selection

사용자가 성분을 직접 입력한 경우 해당 성분을 우선 사용합니다.

```text
나이아신아마이드 세럼 추천해줘
```

성분이 명시되지 않은 스킨케어 요청에서는 피부 타입과 피부 고민을 기준으로 성분 후보를 생성하고,  
실제 데이터베이스에 해당 성분을 포함한 상품이 존재하는지 확인한 뒤 추천에 사용합니다.

### 5.3 LightFM Hybrid Recommendation

추천 모델은 **LightFM 기반 Hybrid Recommendation** 구조를 사용합니다.

#### User Side Information

```text
skin_type
skin_tone
eye_color
hair_color
```

#### Item Side Information

모델 학습 시 구성한 상품 Feature Matrix를 활용합니다.

#### Interaction

리뷰 데이터를 기반으로 생성한 사용자-상품 Interaction 정보를 사용합니다.

신규 사용자는 기존 Interaction이 없더라도 사용자 프로필 Feature를 이용해 추천할 수 있도록 구성했습니다.

> Google Trends 데이터는 LightFM Ranking Score에 직접 반영하지 않습니다.

### 5.4 Bayesian Ranking Fallback

DB에 후보 상품은 존재하지만 LightFM으로 추천 가능한 상품이 없는 경우,  
평점과 리뷰 수를 함께 고려한 Bayesian Weighted Rating을 사용합니다.

단순 평균 평점만 사용하는 경우 리뷰 수가 적은 상품이 과대평가될 수 있기 때문에  
리뷰 수를 함께 반영해 대체 순위를 계산합니다.

### 5.5 Web Search Fallback

현재 데이터셋에서 조건과 맞는 후보 상품을 찾지 못한 경우  
Gemini + Google Search를 이용해 외부 상품을 탐색합니다.

이 결과는 DB에 저장하지 않고 요청 시점에만 사용하며,  
데이터셋 기반 개인화 추천과 구분해 표시합니다.

---

## 6. Key Modules

| File | Role |
| --- | --- |
| `airflow/dags/ingredient_pipeline.py` | Sephora 상품의 성분 데이터를 수집·정제하고 MFDS 정보와 결합하는 Airflow 파이프라인 |
| `airflow/dags/review_pipeline.py` | 리뷰 데이터를 전처리하고 추천 모델용 Interaction 데이터를 생성 |
| `src/cosmetics/query/user_query_parser.py` | Gemini를 이용해 자연어 질문에서 피부 정보, 제품 유형, 추천 의도 등을 구조화 |
| `src/cosmetics/ingredients/ingredient_repository.py` | 후보 상품 조회부터 LightFM·Bayesian·Web Search Fallback까지 추천 흐름을 통합 관리 |
| `src/recommendation/sephora_lightfm.py` | 사용자-상품 Interaction과 Side Information을 활용한 LightFM Hybrid Recommendation 추론 |
| `src/cosmetics/trends/google_trends_collector.py` | 추천 결과와 함께 보여줄 Google Trends 검색 관심도를 계산 |
| `src/cosmetics/trends/product_trend_collector.py` | DB 후보가 없을 때 Gemini + Google Search로 외부 상품을 탐색 |
| `src/api/main.py` | 자연어 추천 요청을 처리하고 결과를 반환하는 FastAPI 백엔드 |
| `streamlit/streamlit_app.py` | 자연어 입력, 추천 결과, 추천 기준 및 트렌드 정보를 제공하는 BeautyLens UI |

---

## 7. Data Pipeline

### 7.1 Ingredient Pipeline

```text
Sephora Product Data
        ↓
Ingredient Parsing
        ↓
Ingredient Normalization
        ↓
MFDS Ingredient Matching
        ↓
MFDS Regulation Filtering
        ↓
Product-Ingredient Mapping
        ↓
MariaDB
```

상품의 원재료 문자열을 파싱하고 정규화된 `ingredient_key`를 생성한 뒤,  
MFDS 성분 데이터와 매칭해 성분 정보와 사용 제한 정보를 결합합니다.

### 7.2 Review Pipeline

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
```

리뷰 데이터는 추천 모델에서 사용할 사용자-상품 Interaction 데이터로 가공합니다.

상품 카드에 표시되는 날짜는 가격 기준일이 아니라  
**해당 상품의 최신 리뷰 `submission_time`**을 기준으로 합니다.

---

## 8. Project Structure

```text
recommendation_system/
├─ airflow/
│  └─ dags/
│     ├─ ingredient_pipeline.py
│     └─ review_pipeline.py
│
├─ src/
│  ├─ api/
│  │  └─ main.py
│  │
│  ├─ cosmetics/
│  │  ├─ ingredients/
│  │  │  ├─ ingredient_candidate_selector.py
│  │  │  ├─ ingredient_dictionary_builder.py
│  │  │  ├─ ingredient_extractor.py
│  │  │  ├─ ingredient_regulation_filter.py
│  │  │  └─ ingredient_repository.py
│  │  ├─ query/
│  │  │  └─ user_query_parser.py
│  │  └─ trends/
│  │     ├─ google_trends_collector.py
│  │     └─ product_trend_collector.py
│  │
│  ├─ database/
│  │  ├─ check_sephora_product_urls.py
│  │  ├─ load_ingredients.py
│  │  ├─ load_product_ingredients.py
│  │  └─ load_products.py
│  │
│  └─ recommendation/
│     └─ sephora_lightfm.py
│
├─ streamlit/
│  └─ streamlit_app.py
│
├─ requirements.txt
├─ .gitignore
└─ README.md
```

---

## 9. Database

주요 데이터는 MariaDB에서 관리합니다.

| Data | Description |
| --- | --- |
| `products` | 상품명, 브랜드, 가격, 평점, 리뷰 수, 최신 리뷰일 등 상품 정보 |
| `ingredients` | 정규화된 성분명, MFDS 정보, 규제 정보 및 추천 가능 여부 |
| `product_ingredients` | 상품과 성분 간 연결 정보 |
| `interactions` | 추천 모델에서 활용하는 사용자-상품 Interaction |
| `dataset_metadata` | 데이터셋 최신 리뷰일 등 메타데이터 |

상품 URL은 Sephora Sitemap의 상품 ID와 `product_id`를 매칭해 저장합니다.

---

## 10. Tech Stack

| Category | Technology |
| --- | --- |
| Language | Python |
| Data Processing | Pandas, NumPy, SciPy |
| Recommendation | LightFM, Joblib |
| Backend | FastAPI, Uvicorn |
| Frontend | Streamlit |
| Database | MariaDB, PyMySQL |
| Pipeline | Apache Airflow |
| Storage | Amazon S3, Boto3 |
| LLM / Search | Gemini API, Google Search Grounding |
| Trend Data | Google Trends |
| External Data | Sephora Dataset, MFDS Ingredient API |



---

## 11. Current Limitations

### Product Performance Data

현재 데이터셋에는 다음과 같은 제품 사용 성능에 대한 직접 측정값이 없습니다.

```text
커버력
블러
지속력
밀착력
발색
```

따라서 제품 성능 관련 질문은 요청 의도와 제품 유형을 해석해 후보를 탐색할 수 있지만,  
실제 제품 성능이 우수하다고 검증한 순위는 아닙니다.

### Google Trends

Google Trends는 추천 결과를 설명하기 위한 참고 정보이며  
LightFM Ranking Score에는 직접 반영하지 않습니다.

### Web Search Fallback

Gemini + Google Search 결과는 데이터셋 기반 개인화 추천이 아니라  
내부 데이터에서 후보를 찾지 못했을 때 제공하는 보조 결과입니다.

### Model Evaluation

현재는 추천 파이프라인과 신규 사용자 추천 흐름 구현에 초점을 두고 있습니다.

향후 다음 지표를 이용해 추천 모델을 정량적으로 평가할 예정입니다.

```text
Precision@K
Recall@K
AUC
```


## 12. Future Work

- LightFM 추천 모델 정량 평가
- 신규 사용자 Cold-start 성능 분석
- 상품 Content Feature 확장
- 추천 설명 기능 개선
- Google Trends 활용 방식 고도화
- 배포 환경의 DB 및 모델 관리 개선

