<img width="1672" height="941" alt="데이터_흐름도_수정본" src="https://github.com/user-attachments/assets/c7462246-7820-4474-9ec1-5a4e6c489a49" />

## 3. System Architecture

BeautyLens는 Sephora 상품·리뷰 데이터를 기반으로 전처리 및 추천 데이터를 구성하고,  
LightFM 기반 개인화 추천 결과를 FastAPI와 Streamlit을 통해 제공합니다.

```mermaid
flowchart LR

    A["1. Data Source<br/><br/>Sephora<br/>Products · Reviews<br/><br/>MFDS<br/>Ingredient Data"]

    B["2. Airflow<br/><br/>ingredient_pipeline.py<br/>review_pipeline.py"]

    C["3. Amazon S3<br/><br/>Raw Data<br/>Processed Data"]

    D["4. Python ETL<br/><br/>Ingredient Processing<br/>Review Processing"]

    E["5. MariaDB<br/><br/>Products<br/>Ingredients<br/>Interactions"]

    F["6. Recommendation<br/><br/>LightFM Hybrid<br/>Bayesian Fallback"]

    G["7. FastAPI<br/><br/>POST /chat/recommend<br/>Recommendation API"]

    H["8. Streamlit<br/><br/>BeautyLens UI<br/>Recommendation Result"]


    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H


    I["Gemini<br/>Query Parsing"]
    J["Google Trends<br/>Search Interest"]
    K["Gemini + Google Search<br/>Web Search Fallback"]


    G -. Natural Language .-> I
    G -. Trend Lookup .-> J
    F -. No DB Candidate .-> K


    classDef data fill:#fff7f8,stroke:#d89bad,color:#222;
    classDef pipeline fill:#fff9e8,stroke:#d9b768,color:#222;
    classDef process fill:#f3f8f5,stroke:#8db49d,color:#222;
    classDef database fill:#f1f7fb,stroke:#84abc4,color:#222;
    classDef model fill:#f8f3fb,stroke:#ab91bc,color:#222;
    classDef service fill:#f1faf9,stroke:#79aaa6,color:#222;
    classDef ui fill:#fff3f7,stroke:#d990aa,color:#222;
    classDef external fill:#fafafa,stroke:#aaa,color:#333;

    class A data;
    class B,C pipeline;
    class D process;
    class E database;
    class F model;
    class G service;
    class H ui;
    class I,J,K external;
```

### Recommendation Flow

```text
사용자 질문
    ↓
Gemini 자연어 질의 분석
    ↓
DB 후보 상품 탐색
    ↓
LightFM Hybrid Recommendation
    ↓
추천 결과 반환
```

추천 결과를 생성할 수 없는 경우에는 다음 순서로 fallback을 적용합니다.

| 상황 | 처리 방식 |
|---|---|
| LightFM 추천 가능 | **LightFM Hybrid Recommendation** |
| DB 후보는 있지만 LightFM 추천 불가 | **Bayesian Ranking Fallback** |
| DB에 적합한 후보가 없음 | **Gemini + Google Search** |

> Google Trends는 추천 점수에 직접 반영하지 않고, 추천 결과와 함께 검색 관심도 정보를 제공하는 보조 기능으로 사용합니다.

| Priority | Method | Condition |
| --- | --- | --- |
| 1 | **LightFM Hybrid Recommendation** | DB 후보가 존재하고 LightFM에서 추천 가능한 경우 |
| 2 | **Bayesian Ranking Fallback** | DB 후보는 있지만 LightFM 추천 결과가 없는 경우 |
| 3 | **Gemini + Google Search** | DB에서 조건에 맞는 후보 상품을 찾을 수 없는 경우 |

LightFM은 사용자-상품 interaction과 사용자/상품 side information을 함께 활용합니다.  
신규 사용자의 경우 피부 타입, 피부톤 등의 profile feature를 이용해 cold-start 추천을 수행합니다.
