# 신규 사용자 추천 개선 실험

결과와 새 코드는 이 폴더에 저장합니다. 원본 데이터, 기존 벤치마크 모델, 서비스 API는 수정하지 않습니다.

## 이번 변경

1. 기존 `cold_users_v2`의 정제 데이터·사용자 분할·feature를 재사용합니다. 검증 3,000명, 테스트 10,000명의 ID와 순서도 확인합니다.
2. 기존 LightFM WARP를 기준으로 긍정 +1 / 명시적 부정 -1을 사용하는 LightFM logistic 두 설정을 학습합니다. 부정 샘플 가중치는 0.25, 1.0이며 모호한 리뷰와 미관측 상품은 logistic 학습에 넣지 않습니다.
3. 각 모델의 5/15/30 epoch 중 전체 후보의 검증 NDCG@10이 가장 높은 체크포인트를 저장합니다. 기존 WARP는 재학습하지 않습니다.
4. 전체 후보와 학습 긍정 리뷰가 가장 많은 4개 secondary_category에서 동일한 후보·정답으로 비교합니다.
5. 상위 200개 후보 안에서 관련성 점수와 브랜드·성분 유사도 중복 벌점을 조합해 재정렬합니다. 성분 유사도는 성분명 TF-IDF cosine이며 브랜드 중복과 1:1 비중으로 섞습니다. 성분 농도나 효능을 뜻하지 않습니다.
6. 범위별 raw 최고 모델 대비 검증 NDCG 하락이 2% 이내인 가중치(0/0.05/0.15/0.30) 중 상품 커버리지를 최대로 하는 설정을 선택합니다. 동률이면 브랜드 수, NDCG 순입니다. 0도 후보이므로 강제 다양화하지 않습니다.
7. 선택을 저장한 뒤 테스트하며 기존 모델, raw 최고 모델, 재정렬 포함 선택 결과를 함께 남깁니다. 사용자 bootstrap 구간과 피부 타입별 결과도 저장합니다.

## 실행

프로젝트 루트 `C:\Users\user\Desktop\recommend_system`에서:

```powershell
$benchmarkPython = 'C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe'
& $benchmarkPython -m unittest optimized.cold_start_improvements.test_improvements -v
& $benchmarkPython -m optimized.cold_start_improvements.experiment --run-name improvements_v2
& $benchmarkPython -m optimized.cold_start_improvements.summarize --run-name improvements_v2
```

이미 있는 실행 폴더는 덮어쓰지 않습니다. 기존 벤치마크 전용 `.packages`와 Windows LightFM 수정 빌드를 재사용하며, 설치 안내는 `../cold_start_benchmark/README.md`에 있습니다.

학습된 선택 설정으로 추천:

```powershell
& $benchmarkPython -m optimized.cold_start_improvements.predict --skin-type dry --category moisturizers --max-price-usd 50 --exclude-ingredient fragrance --top-k 5
```

`--category`는 catalogue의 secondary_category 완전 일치(대소문자 무시)입니다. `--exclude-ingredient`는 여러 번 지정할 수 있습니다. 예산은 **USD**이며 데이터셋에 저장된 가격입니다. `--no-diversity`는 해당 범위의 raw 최고 모델을 사용합니다. 출력의 `rank`가 최종 순위이고 `model_score`는 보정되지 않은 원래 모델 점수입니다.

상위 4개 이외 종류에는 전체 후보에서 선택한 정책을 적용하며 `policy_scope`에 표시합니다. 예산·성분 필터 이후에는 후보가 달라지므로 기존 검증의 2% 조건이 보장되지 않습니다. 후보가 없으면 빈 목록을 반환하고, 적으면 해당 수만 반환합니다.

## 결과 위치

`artifacts/improvements_v1/RESULTS.md`가 실행 결과입니다.

- `comparison.csv`: 범위별 baseline / raw_best / selected 테스트 결과
- `raw_model_comparison.csv`: 전체 후보에서 모든 raw 모델의 테스트 진단 결과
- `validation_policies.csv`, `selection.json`: 검증에서 비교한 설정과 선택 근거
- `paired_uncertainty.json`: selected와 baseline의 사용자 단위 NDCG 차이 구간
- `*_per_user.csv`, `*_by_skin.csv`, `*_top10.npy`: 상세 결과, 로컬에만 보관
- `lightfm_logistic_*.joblib`: 새로 학습한 모델
- `config.json`: 기존 model/feature 해시·실험 설정·평가 가정
- `completed.json`: 학습과 평가가 모두 완료됐을 때만 생성

## 해석 범위

- 종류별 평가는 사용자가 해당 종류를 요청했다고 가정합니다. 실제 요청 로그가 없어 관련 긍정 상품이 있는 사용자만 평가하는 조건부 대리지표입니다. 종류 안의 긍정 상품만 Recall 분모에 들어갑니다. 종류별 수치와 전체 수치를 직접 비교하지 마세요.
- 원래 평가의 10,000명 중 조건부 사용자를 고릅니다. 전체 테스트 사용자 중 해당 종류의 사용자를 새로 샘플링하지 않습니다.
- 예산·제외 성분 선호를 알려주는 정답은 없으므로 해당 필터의 성능 향상을 주장하지 않습니다. 성분은 파싱된 이름 완전 일치이며 동의어를 처리하지 않습니다. 제외 조건이 있으면 성분 미기재 상품도 제외합니다. 안전성 판정 기능은 아닙니다.
- 추천 슬롯이 10개보다 적으면 Precision·부정 비율은 실제 추천 개수를 분모로 씁니다. 상품 커버리지는 해당 범위 후보 대비 노출된 고유 상품 비율입니다.
- 동일 seed라도 4스레드 LightFM 업데이트 순서에 따라 결과가 달라질 수 있습니다. bootstrap은 학습 seed 변동을 포함하지 않습니다.
- 이전과 같은 검증·테스트를 이용한 후속 탐색입니다. 독립 최종 검증이나 실제 가입자 반응 평가를 대신하지 않습니다.
- 피부 고민·제형 취향은 실제 학습 라벨이 없어 이번 모델 입력에 추가하지 않았습니다.
