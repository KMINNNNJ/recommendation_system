# 신규 사용자 추천 모델 비교

원본 서비스·데이터·모델을 보존하고, 신규 사용자에게 프로필만 받아 추천하는 실험입니다. 소스는 이 폴더에 있고 실행 결과와 학습 모델은 `artifacts/<run-name>/`에 저장합니다. `.packages/`와 `artifacts/`는 Git에서 제외됩니다.

최종 실행 이름은 `cold_users_v2`입니다. [model_comparison.ipynb](model_comparison.ipynb)에서 데이터 요약·모델 비교·그래프·새 프로필 추천을 확인할 수 있습니다. `requirements.txt`는 실험에 사용한 별도 의존성 목록입니다.

## 원래 노트북 설정과 직접 비교

원래 노트북을 재현하는 비교는 `compare_original.py`와 `original_feature_recipe.py`에 있습니다. 결과는 `artifacts/original_same_users_v1/ORIGINAL_COMPARISON.md`에 저장합니다. 원래 전체 데이터 모델에는 현재 테스트 사용자 정보가 들어 있을 수 있어, 원래 feature 정의·k-core·64차원·ID 포함·하이퍼파라미터를 유지하면서 공통 학습 사용자만으로 다시 학습합니다. 원래 저장 모델에 해당하는 20회 설정과 기존 튜닝 결과의 30회 설정을 사전에 고정해서 평가합니다.

이 비교의 `original_notebook_*`와 이전 실험의 `lightfm_identity_ablation`은 다릅니다. 후자는 새 실험의 32차원·새 feature 구성을 유지한 ID 포함 통제 설정이고 원본 노트북의 정확한 재현은 아닙니다.

```powershell
& 'C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe' -m optimized.cold_start_benchmark.compare_original --run-name original_same_users_v2
```

이 재현도 기존 무작위 리뷰 분할의 과거 점수를 재현하는 실험은 아닙니다. 신규 사용자 목표에 맞는 공통 분리와 평가로 원래 학습 구성을 비교합니다. 원래 코드의 profile 최빈값 집계는 학습 사용자 안에서만 수행합니다. 테스트 입력은 새 실험과 같은 첫 리뷰 프로필을 사용합니다.

## 기존 모델에서 보완하는 부분

1. **사용자 분리:** 기존의 무작위 리뷰 분할 대신 사용자 ID를 70/15/15로 분리합니다. 학습·검증·테스트 사용자가 겹치지 않습니다. ID는 데이터 분리에만 사용하며, 검증·테스트 사용자 ID 임베딩은 입력하지 않습니다.
2. **프로필 고정:** 각 사용자의 가장 이른 날짜의 유효한 스킨케어 리뷰에 기재된 프로필만 입력으로 사용합니다. 미래 리뷰를 모아 최빈 프로필을 만들지 않습니다. 이는 실제 신규 사용자의 가입 시점 프로필을 대신하는 오프라인 근사입니다.
3. **단일 리뷰 사용자 유지:** 개인별 과거 이력이 없어도 평가하므로, 최소 2개 긍정 리뷰 등의 사용자 k-core 필터를 적용하지 않습니다.
4. **중복 확인:** 원본 리뷰 분할 CSV 5개와 통합 CSV의 전체 행 지문을 비교합니다. 원본 분할본이 있으면 분할본만 읽습니다. 통합본을 함께 연결하지 않습니다. 사용자–상품 중복은 가장 최근 유효 날짜의 리뷰를 남깁니다.
5. **정보 누수 억제:** 상품 전체 평점·리뷰 수·loves_count와 리뷰 텍스트를 모델 입력에서 제외합니다. 기준 모델의 반응 집계는 학습 사용자에게서만 계산합니다. 사용자 프로필 범주도 학습에서 확정합니다.
6. **같은 평가:** 모든 모델을 같은 신규 사용자, 같은 스킨케어 후보 전체, 같은 정답과 지표로 평가합니다. 기존 모델 파일은 전체 데이터로 학습됐을 수 있어 그대로 비교하지 않습니다.
7. **검증과 테스트 분리:** 검증으로 체크포인트·기준 모델 평활화·최종 모델을 선택한 뒤 테스트 결과를 한 번 계산합니다. 테스트 최고 점수를 보고 모델을 다시 고르지 않습니다.

## 비교하는 8개 설정

| 이름 | 학습·추천 방식 |
|---|---|
| `global_popularity` | 학습 사용자의 긍정 리뷰 수 순서, 반드시 넘어야 할 인기도 기준 모델 |
| `global_bayesian` | 학습 리뷰의 전체 상품별 긍정 비율을 평활화한 기준 모델 |
| `skin_type_bayesian` | 피부 타입별 상품 긍정 비율을 전체 상품별 추정값으로 평활화 |
| `lightfm_profile` | 사용자 ID 없이 피부 타입·피부톤·눈·머리 색상으로 학습 |
| `lightfm_skin_only` | 피부 타입만 사용, 나머지 프로필 효과를 점검 |
| `lightfm_identity_ablation` | 학습할 때 사용자 ID도 포함하고, 신규 사용자 예측에서는 ID를 제외 |
| `catboost` | 관측된 긍정·부정 리뷰를 프로필+상품 속성으로 분류하고 점수순 추천 |
| `lightgbm` | 같은 라벨과 입력을 사용하는 분류 모델의 점수순 추천 |

LightFM의 세 설정은 같은 상품 feature와 파라미터·학습 횟수 후보를 사용합니다. ID 포함 설정은 기존 구조에서 영감을 얻은 **통제 비교**이며 노트북을 그대로 재현한 모델은 아닙니다. LightGBM은 분류 모델이며 LambdaRank를 실행한 것으로 표현하지 않습니다. FM/DeepFM/Two-Tower는 이번 실험에 포함하지 않았습니다.

CatBoost·LightGBM은 관측된 부정 평가도 사용하고 LightFM WARP는 긍정 리뷰만 사용합니다. 따라서 알고리즘만 바꾼 엄밀한 손실 통제 비교가 아니라, 현재 데이터에서 사용 가능한 추천 접근법의 비교입니다.

입력 인코딩에도 차이가 있습니다. LightFM은 상품 ID 임베딩과 상품 속성을 함께 사용하지만, 현재 트리 설정은 상품 ID를 직접 넣지 않고 상품 속성을 사용합니다. 성분의 인코딩과 선택 범위도 다릅니다. 따라서 이 결과만으로 알고리즘 자체의 우열을 확정하지 않습니다. 다음 통제 실험에서는 트리에 상품 ID를 추가한 설정과 동일한 성분 선택 범위를 비교할 수 있습니다.

### 정답과 입력

- 긍정: 평점 4~5점이고 `is_recommended=1` 또는 결측.
- 부정: 평점 1~2점 또는 `is_recommended=0`.
- 나머지: 모호한 평가로 취급. 트리 모델의 분류 학습과 긍정 정답에서 제외.
- 리뷰가 없는 상품을 명시적 부정으로 만들지 않습니다. 다만 WARP는 관측되지 않은 상품을 학습 중 음성 후보로 샘플링하는 기존 목적 함수를 사용합니다.
- 사용자 입력: 첫 리뷰의 피부 타입·피부톤·눈 색상·머리 색상. 피부 타입 단독 설정은 첫 항목만 사용.
- 상품 입력: 브랜드·중분류·소분류·variation type·가격·성분. 트리는 빈번한 80개 성분의 유무를 사용하고, LightFM은 5개 이상 상품에 나오는 성분을 사용합니다. 상품별 성분 그룹의 총 가중치를 일정하게 유지합니다.
- 학습에서 보지 못한 사용자 프로필 값은 모든 모델에서 `unknown`으로 처리합니다.

## 실행

프로젝트 루트에서 Python 3.11을 사용합니다. 현재 PC는 다음 실행 파일을 사용합니다.

```powershell
$benchmarkPython = 'C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe'
& $benchmarkPython -m unittest cold_start_benchmark.test_experiment -v
& $benchmarkPython -m optimized.cold_start_benchmark.run --run-name cold_users_v3 --lightfm-threads 4
```

기본 데이터 위치는 `data/raw/cosmetics`입니다. 사용자가 겹치지 않는 전체 학습 세트를 학습하고, 검증은 긍정 리뷰가 있는 사용자 중 고정된 3,000명, 테스트는 10,000명을 샘플링합니다. 전체 사용자 평가는 `--validation-users 0 --test-users 0`으로 설정합니다. 기본 LightFM 후보는 5/15/30 epochs, 32차원이며 트리 모델은 최대 500회와 검증 logloss 조기 종료를 사용합니다. LightFM 체크포인트는 검증 NDCG@10으로 고릅니다. 따라서 모델별 탐색 예산·선택 손실이 완전히 같지는 않습니다.

```powershell
& $benchmarkPython -m optimized.cold_start_benchmark.run --run-name cold_users_v3 --epochs 5 15 30 --tree-iterations 500 --lightfm-threads 4
```

완료한 실행 이름은 덮어쓰지 않습니다. 가상 데이터로 모든 모델의 학습·직렬화·평가 연결을 시험하려면:

```powershell
& $benchmarkPython -m optimized.cold_start_benchmark.smoke_test
```

### 저장 모델로 추천

```powershell
& $benchmarkPython -m optimized.cold_start_benchmark.predict --skin-type dry --product-type serum --top-k 5
& $benchmarkPython -m optimized.cold_start_benchmark.predict --model catboost --skin-type oily --top-k 5
```

모델을 지정하지 않으면 검증 NDCG@10으로 선택한 모델을 사용합니다. 피부 타입은 데이터의 영문 값(예: `dry`, `oily`, `combination`, `normal`)으로 입력합니다. 제품 종류 필터는 상품명·카테고리의 영문 부분 문자열 필터입니다. 사용자 질의 해석이나 기존 API 교체는 이 실험에서 실행하지 않습니다.

## 결과 파일

- `source_audit.json`: 통합본/분할본의 전체 행 지문 비교와 실제 선택한 파일.
- `data_summary.json`: 정제·분리·누락값·정답 분포와 프로필 범주.
- `config.json`: seed, 라이브러리 버전, 모델 설정과 실험 제한.
- `validation_history.json`: 검증 점수와 학습 체크포인트.
- `comparison.csv`, `comparison.json`: 공통 테스트 지표와 학습·평가 시간.
- `selected_model.json`: 테스트 결과를 보기 전에 검증으로 선택한 모델.
- `paired_uncertainty.json`: 선택 모델과 다른 모델의 NDCG 차이에 대한 사용자 단위 paired bootstrap 95% 구간. 모델 초기화 seed의 불확실성까지 반영하지는 않습니다.
- `*_per_user.csv`, `*_by_skin.csv`: 사용자별 및 피부 타입별 결과.
- `features.joblib`, `*.joblib`, `catboost.cbm`: 학습 모델·전처리 저장본.
- `reviews_prepared.pkl`, `profiles.pkl`, `user_splits.csv`: 실험 데이터와 분리 재현용 자료. 사용자 ID가 들어 있어 Git에서 제외합니다.

Recall@10, NDCG@10을 주 지표로 보고 Precision@10, Hit Rate@10, 명시적 부정 상품의 추천 비율, 상품 커버리지를 함께 봅니다. `known_negative@10`은 낮을수록 좋지만, 리뷰가 없는 추천 상품의 실제 만족도를 알려주는 값은 아닙니다.

## Windows LightFM 실행 수정

현재 Python 환경의 원본 LightFM 1.17과 별도로 설치한 lightfm-next 1.19.0 모두 Windows 네이티브 WARP 학습에서 access violation이 발생했습니다. 생성된 C의 난수 함수가 `uint32`를 Windows의 signed 32-bit `long`으로 바꾼 뒤 2로 나누면서 음수 난수를 만들고, 음수 상품 행을 읽는 문제가 확인됐습니다.

실험 전용 `.packages`에 lightfm-next를 설치하고 `build_windows_lightfm.py`로 그 표현식 하나를 unsigned 오른쪽 shift로 수정해 다시 빌드했습니다. 이는 의도된 `uint32 // 2` 계산을 유지하는 수정이며 시스템 설치본은 변경하지 않았습니다. 빌드 스크립트는 알려진 표현식이 정확히 한 번 나올 때만 작동합니다. 재설치하면 수정이 사라지므로 Windows 재현 시 다시 빌드해야 합니다. Visual C++ Build Tools와 NumPy·setuptools가 필요합니다.

```powershell
& $benchmarkPython -m pip install --target optimized/cold_start_benchmark/.packages --no-deps catboost==1.2.10 lightgbm==4.7.0 graphviz==0.21 lightfm-next==1.19.0
& $benchmarkPython optimized/cold_start_benchmark/build_windows_lightfm.py
```

최종 `cold_users_v2` 실험은 수정한 OpenMP 빌드에서 LightFM과 트리 모델 모두 4스레드를 사용합니다. OpenMP 버전 빌드는 위 빌드 명령에 `--openmp`를 추가합니다. 단일 스레드의 초기 진단 실행 `cold_users_v1`은 중단된 예비 실행이며 최종 비교에 사용하지 않습니다. 동일 seed라도 병렬 LightFM의 업데이트 순서 때문에 재학습 결과가 완전히 같지는 않을 수 있습니다. 빌드한 확장 파일의 SHA-256과 스레드 수는 실행 설정에 기록합니다.

## 해석할 때 주의할 점

- 이 평가는 스킨케어 **리뷰 작성자**의 긍정 상품을 찾는 오프라인 실험입니다. 구매·노출 로그나 의학적 적합성 평가가 아닙니다.
- 사용자 분리는 신규 사용자 일반화를 평가하며, 미래 시점 성능을 평가하는 시간 분할과는 다릅니다. 다음 단계로 사용자 분리와 시간 경계를 함께 적용한 평가가 가능합니다.
- 상품 성분·가격은 데이터셋의 정적 스냅샷입니다. 과거 시점의 속성을 완전히 복원할 수 없습니다.
- 피부 고민·커버력·지속력의 직접 라벨이 없으므로 그런 효과를 학습한 모델로 설명하지 않습니다.
- 후보는 스킨케어 전체입니다. 실제 자연어 질의의 제품 종류·성분 필터 이후 평가까지 대신하지 않습니다.
- 같은 프로필과 조건에는 같은 순위를 제공합니다. 개인별 선호 입력이 더 없다면 사용자별 차이를 추가로 학습할 근거도 없습니다.
- 검증·테스트의 모든 리뷰가 부정/모호한 사용자는 긍정 상품 검색 지표를 정의할 수 없어 주 평가에서 제외됩니다. 사용자 수는 결과에 공개합니다.
