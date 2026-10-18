# 서비스 코드 수정 기록

기존 코드를 살펴보니 추천 요청마다 모델을 다시 읽고, 상품 필터와 DB 적재에서도 같은 처리가 반복되고 있었다. 원본과 결과를 비교할 수 있도록 코드를 이 폴더에 복사한 뒤 수정했다.

서비스 개선본은 기존 `models/sephora_hybrid_lightfm.joblib`을 사용한다. 새로 학습한 모델은 아래 실험과 비교 데모에 있으며, 서비스에는 아직 연결하지 않았다.

## 바꾼 부분

| 항목 | 기존 처리 | 변경 |
|---|---|---|
| 모델 로딩 | 요청마다 약 87MB 파일을 읽음 | 프로세스에서 한 번 읽고 재사용 |
| 모델 갱신 | 매번 다시 읽음 | 경로·수정 시각·크기가 바뀌면 다시 로딩 |
| 동시 첫 요청 | 요청마다 로딩할 수 있음 | 잠금으로 중복 로딩 방지 |
| 상위 N개 선택 | 후보 전체를 객체로 만들고 정렬 | `heapq.nlargest`로 필요한 개수만 선택 |
| 제품 종류 필터 | 행과 키워드를 반복 조회 | 열별 문자열 결합 후 정규식으로 필터 |
| DB 적재 | `iterrows()`로 행별 변환 | `itertuples()`와 배치 삽입 |
| 화면 | 답변 글자가 흰 배경에 묻히고 처리 상태가 잘 안 보임 | 글자 대비, 로딩·완료·오류 표시 수정 |
| S3 설정 | 개인 버킷 이름이 기본값으로 들어 있음 | `S3_BUCKET_NAME`을 직접 지정하도록 변경 |

모델 캐시는 프로세스별로 유지한다. 파일 내용만 바꾸고 크기와 수정 시각을 그대로 유지했다면 `clear_model_cache()`나 서버 재시작이 필요하다. NaN·무한대 점수와 음수 슬라이스는 원본 처리 방식을 유지했다.

DB 적재는 열 순서·배치 크기·NULL 처리를 유지했다. `itertuples()`로 바꾸면서 큰 정수 ID가 실수로 변환되는 문제도 피했다.

## 코드 위치

| 파일 | 하는 일 |
|---|---|
| `streamlit/streamlit.py` | 질문 입력, 추가 질문, 답변과 상품 카드 표시 |
| `src/api/main.py` | 요청 분류와 `/recommend`, `/chat/recommend` 처리 |
| `src/cosmetics/query/user_query_parser.py` | Gemini로 조건 추출, 값 정규화, 누락 정보 확인 |
| `src/cosmetics/ingredients/ingredient_repository.py` | 성분·제품 종류로 후보 조회, 추천과 대체 경로 선택 |
| `src/recommendation/sephora_lightfm.py` | 프로필 feature 생성, 모델 로딩, 후보 순위 계산 |
| `src/cosmetics/trends/` | 검색 관심도 조회와 DB 후보가 없을 때의 웹 검색 |

성분을 직접 입력하지 않은 스킨케어 요청은 피부 타입·고민별 목록에서 성분을 선택한다. 이 부분은 학습 모델이 아닌 규칙이다. 커버력·지속력 중심 요청은 성분을 임의로 정하지 않고 제품 종류로 후보를 찾는다.

LightFM은 피부 타입·피부톤·눈동자색·머리색을 사용한다. 학습에 없던 값은 `unknown`으로 처리하고, DB 후보 중 모델이 아는 상품의 점수를 계산한다. 결과의 `ranking_method`로 LightFM, 카탈로그 대체 순위, 웹 검색을 구분한다.

Google Trends는 한국의 최근 12개월 자료에서 최근 4주와 직전 4주의 평균을 비교한다. 실제 검색 건수나 추천 점수는 아니다. 현재 웹 검색은 주로 DB에 후보가 없을 때 사용하며, `get_trending_products()`가 있어도 기본 추천 응답의 `trending_products`는 빈 목록이다.

## 데이터 처리

| 파일 | 처리 흐름 |
|---|---|
| `airflow/dags/ingredient_pipeline.py` | S3 상품 CSV → 성분 정제 → 상품·성분·연결 테이블 적재 |
| `airflow/dags/review_pipeline.py` | S3 리뷰 CSV → 리뷰 정제 → 상호작용 생성 → DB 적재 |
| `src/cosmetics/ingredients/ingredient_extractor.py` | 성분 파싱과 표준 키 생성 |
| `src/cosmetics/ingredients/ingredient_dictionary_builder.py` | 식약처 성분 정보 연결 |
| `src/cosmetics/ingredients/ingredient_regulation_filter.py` | 규제·추가 검토 정보 결합 |
| `src/database/` | S3 파일 적재와 상품 URL 연결 |

리뷰 ETL의 `interaction_score`는 평균 평점이다. ETL을 실행한다고 모델이 다시 학습되지는 않는다. 규제 필터의 `recommendable` 값도 현재 온라인 조회의 거부 조건으로 적용하지 않았다.

DAG는 원본과 ID가 같아 한 Airflow에 둘 다 등록하면 충돌한다. 적용할 때는 해당 DAG를 교체해야 한다. 이 작업에서 실제 DAG 등록·스케줄 변경·데이터 적재는 하지 않았다.

성분 DAG와 서비스는 `DB_*`, 리뷰 DAG는 `MARIADB_*` 환경변수를 사용한다. 두 DAG 모두 `S3_BUCKET_NAME`이 필요하며, 누락되면 S3 요청 전에 오류를 낸다.

## 신규 사용자 모델 실험

코드 처리 속도와 추천 모델 성능은 따로 비교했다.

- [cold_start_benchmark](cold_start_benchmark/README.md): 중복 데이터 확인, 사용자 분리, 8개 설정 비교, 원본 노트북 설정 재현
- [cold_start_improvements](cold_start_improvements/README.md): 부정 리뷰 학습, 제품 종류별 평가, 다양성 재정렬
- [portfolio](portfolio/README.md): 저장된 원본·개선 모델을 비교하는 화면과 실행 안내

새 모델은 같은 신규 사용자 평가에서 원본 설정 재학습보다 NDCG@10이 약 35.3% 높았다. 상세 수치와 실패한 실험은 [최종 결과 문서](portfolio/FINAL_REPORT.md)에 정리했다. [비교 노트북](cold_start_benchmark/model_comparison.ipynb)에도 표와 그래프가 있다.

실행 결과는 각 폴더의 `artifacts/`에 저장하며 Git에는 올리지 않았다. 학습 데이터와 모델은 별도로 준비해야 한다.

## 실행

프로젝트 루트에서 실행한다. 기본 리소스 위치는 루트의 `.env`와 `models/`다. 다른 위치를 쓰려면 `RECOMMEND_RESOURCE_ROOT`를 지정한다. 필요한 DB·키·모델은 [루트 README](../README.md#실행)에 적었다.

```powershell
python -m uvicorn optimized.src.api.main:app --host 127.0.0.1 --port 8001
```

다른 터미널에서:

```powershell
$env:RECOMMEND_API_URL = 'http://127.0.0.1:8001/chat/recommend'
python -m streamlit run optimized/streamlit/streamlit.py --server.address 127.0.0.1 --server.port 8503 --server.headless true --browser.gatherUsageStats false
```

서비스는 이 폴더의 `requirements.txt`에 있는 `lightfm==1.17`, `streamlit==1.63.0`을 사용한다. 모델 실험은 별도 `lightfm-next==1.19.0` 설치를 사용한다. import 이름이 같아 설치 경로를 분리했으며, Windows 학습 빌드는 [실험 안내](cold_start_benchmark/README.md#windows-lightfm-실행-수정)를 따른다.

## 확인한 내용

```powershell
python -m unittest discover -s optimized/tests -v
python -m optimized.benchmark
```

서비스·화면 회귀 테스트 11개가 통과했다. 동점과 비정상 점수, 프로필 변환, 캐시 동시 접근·갱신·실패 재시도, 필터 결과, DB 배치 값, 채팅 성공·시간 초과, S3 설정 누락을 확인했다.

처음 코드를 수정할 때 같은 모델과 후보 500개로 비교한 추천 ID·순서·점수는 원본과 같았다. 로컬에서 한 번 측정한 시간은 다음과 같다.

| 측정 | 원본 | 개선본 |
|---|---:|---:|
| 추천 함수 · 모델 캐시 준비 후 | 약 1.139초 | 약 0.005초 |
| 후보 100,000개에서 상위 10개 선택 | 약 0.080초 | 약 0.0068초 |

개선본도 첫 모델 로딩에는 약 2.917초가 걸렸다. 위 시간은 캐시가 준비된 추천 함수와 합성 후보 선택을 측정한 값이며, 전체 API 응답 시간이 아니다. 수치는 [benchmark_results.json](benchmark_results.json)에 있다.

이후 로컬 DB 조회부터 LightFM 추천, S3 버킷 접근, 브라우저의 자연어 요청과 로딩 표시도 확인했다. Airflow 적재와 운영 환경의 전체 응답 시간은 아직 확인하지 않았다. 원본 파일의 작업 시작 시 해시는 [source_manifest.json](source_manifest.json)에 남겼다.

## 남은 작업

서비스에 새 학습 모델을 연결해야 한다. 성분 동의어와 제품 종류 조회에서 전체 테이블을 가져오는 부분, 자동 성분 탐색 후 후보를 다시 조회하는 부분도 남아 있다. 이 구간은 DB와 API 응답 시간을 나눠 측정한 뒤 손볼 예정이다.
