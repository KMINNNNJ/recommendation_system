# 포트폴리오 실행 안내

신규 사용자 스킨케어 추천의 **데모·재현 안내·최종 결과**를 모은 폴더입니다. 원본 서비스와 별도로 실행하며 API 키, MariaDB, S3 연결이 필요하지 않습니다. 학습 완료한 원본 설정 재현 모델과 개선 모델을 로컬에서 불러옵니다.

최종 설명은 [FINAL_REPORT.md](FINAL_REPORT.md), 면접·발표용 요약은 [PRESENTATION.md](PRESENTATION.md)를 확인하세요.

## 1. 지금 PC에서 데모 실행

PowerShell에서 아래를 실행합니다. 다른 폴더에서 실행해도 됩니다.

```powershell
& 'C:\Users\user\Desktop\recommend_system\optimized\portfolio\run_demo.ps1'
```

브라우저에서 **http://127.0.0.1:8502**를 엽니다. 종료는 실행한 터미널에서 `Ctrl+C`입니다. 기존 서비스와 다른 포트를 쓰며 로컬 PC에서만 접속합니다.

스크립트 실행 정책으로 `.ps1`이 차단되면 정책을 바꾸지 않고 다음 명령을 실행할 수 있습니다.

```powershell
& 'C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe' -m streamlit run 'C:\Users\user\Desktop\recommend_system\optimized\portfolio\app.py' --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false
```

데모 사용 순서:

1. 피부 타입을 선택하고 필요하면 피부톤·눈동자색·머리색을 입력합니다. 모르는 값은 ‘선택 안 함’으로 둡니다.
2. 제품 종류를 고르고, 예산을 적용하려면 체크한 뒤 USD 금액을 입력합니다.
3. 필요하면 데이터셋에 기록된 성분명을 선택해 제외합니다.
4. ‘추천 비교하기’를 누르면 원본 설정 재학습 모델과 개선 모델이 같은 조건으로 추천됩니다.
5. ‘브랜드 중복 줄이기’를 켜면 개선 모델에 후속 재정렬을 적용합니다. 기본값은 정확도 비교에 사용한 재정렬 전 모델입니다.

현재 PC에서 건성·보습제·50 USD 조건으로 브라우저 시연까지 확인했습니다. [저장한 비교 화면](artifacts/demo_comparison.png)은 로컬 파일이며 Git에서는 제외됩니다.

성분 제외는 이름 완전 일치만 처리하며 동의어·농도·알레르기 적합성을 판단하지 않습니다. 원본 모델이 학습하지 않은 상품은 원본 추천 목록에 표시하지 않습니다. 두 목록이 다르다는 사실 자체는 정확도 개선의 증거가 아니므로 하단의 고정된 오프라인 평가표를 함께 보여줍니다.

## 2. 설치와 검증

검증 환경은 Python **3.11.9**입니다. 현재 PC에는 필요한 패키지와 실험 전용 LightFM 빌드가 준비돼 있어 다시 설치할 필요가 없습니다.

프로젝트 루트에서:

```powershell
Set-Location 'C:\Users\user\Desktop\recommend_system'
$benchmarkPython = 'C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe'
& $benchmarkPython -m optimized.portfolio.verify
```

검증은 사용자 분리·라벨·평가 지표·모델 직렬화·저장된 두 모델의 추천·Streamlit 화면 입력과 빈 결과를 확인합니다. 전체 데이터 재학습은 실행하지 않습니다. 결과는 `artifacts/verification.json`에 기록됩니다.

다른 PC에 설치하는 경우 Python 3.11 가상환경에서:

```powershell
python -m venv .venv
$benchmarkPython = (Resolve-Path '.venv\Scripts\python.exe').Path
& $benchmarkPython -m pip install -r optimized/portfolio/requirements.txt
& $benchmarkPython -m pip install --target optimized/cold_start_benchmark/.packages --no-deps lightfm-next==1.19.0
```

데모에는 아래 학습 산출물이 필요합니다. 모델은 Git에서 제외돼 있어 코드만 clone하면 바로 실행되지는 않습니다. 같은 실험의 산출물을 해당 경로로 가져오거나, 아래 전체 재학습을 수행해야 합니다. 이 파일들은 이 프로젝트에서 생성한 신뢰할 수 있는 파일만 사용하세요.

| 실행 폴더 | 필요한 파일 |
|---|---|
| `optimized/cold_start_benchmark/artifacts/cold_users_v2/` | `features.joblib`, `lightfm_profile.joblib`, `data_summary.json`, `comparison.csv` |
| `optimized/cold_start_benchmark/artifacts/original_same_users_v1/` | `original_notebook_30_epochs.joblib`, `comparison.csv` |
| `optimized/cold_start_improvements/artifacts/improvements_v1/` | `config.json`, `selection.json`, `completed.json`, `comparison.csv` |

데모 자체는 원본 리뷰 CSV나 `*_per_user.csv`를 읽지 않습니다. 위 표의 모델·메타데이터만으로 추천할 수 있습니다. 전체 검증 중 데이터 정제 테스트는 작은 임시 데이터를 사용합니다. 원래 학습 사용자 ID가 포함된 원본 Dataset 모델은 외부 공개용으로 배포하지 말고 로컬 재현에 사용하세요. 공개 데모 배포가 필요하면 사용자 ID 매핑을 제거하는 별도 내보내기 작업이 필요합니다.

현재 PC의 실행과 검증은 완료했습니다. 새 가상환경을 처음부터 만드는 절차는 이 문서로 제공하며, 이번 마감 작업에서 별도 새 PC 환경까지 실행하지는 않았습니다.

## 3. 전체 학습을 다시 실행하려면

전체 학습은 데모 확인과 별개입니다. 새 실행 이름을 사용하여 이전 결과를 덮어쓰지 않습니다.

먼저 Kaggle [Sephora 데이터셋](https://www.kaggle.com/datasets/nadyinky/sephora-products-and-skincare-reviews)의 파일을 `data/raw/cosmetics/`에 준비합니다. 데이터의 사용·재배포 조건은 원본 데이터셋 안내를 확인하세요.

- `product_info.csv`
- `reviews_0-250.csv`, `reviews_250-500.csv`, `reviews_500-750.csv`, `reviews_750-1250.csv`, `reviews_1250-end.csv`
- `reviews_all (1).csv`는 선택 사항입니다. 있으면 분할본과 중복 여부를 확인하며 함께 합치지 않습니다.

학습에 필요한 추가 패키지:

```powershell
& $benchmarkPython -m pip install -r optimized/cold_start_benchmark/requirements.txt
```

**Windows 재학습 전 필수:** MSVC Build Tools가 필요합니다. 기존 LightFM 네이티브 WARP에서 확인한 난수 변환 문제를 실험 전용 빌드에서 수정합니다. 시스템 설치본은 수정하지 않습니다. `.packages`를 새로 설치한 환경에서는 아래를 실행하세요.

```powershell
& $benchmarkPython optimized/cold_start_benchmark/build_windows_lightfm.py --openmp
```

자세한 원인과 빌드는 [기존 실험 안내](../cold_start_benchmark/README.md#windows-lightfm-실행-수정)에 있습니다. 데모의 저장 모델 추론과 전체 WARP 재학습을 구분하세요. 저장 모델 추론 확인만으로 Windows 학습 빌드가 올바르다고 판정할 수 없습니다.

이제 순서대로:

```powershell
# 1) 데이터 감사·정제·사용자 분리와 8개 모델 설정 학습/평가
& $benchmarkPython -m optimized.cold_start_benchmark.run --run-name cold_users_portfolio_repro --lightfm-threads 4

# 2) 같은 사용자 분리에서 원본 노트북의 학습 설정 재현
& $benchmarkPython -m optimized.cold_start_benchmark.compare_original --source-run cold_users_portfolio_repro --run-name original_portfolio_repro

# 3) 부정 리뷰 학습·조건별 평가·다양성 실험
& $benchmarkPython -m optimized.cold_start_improvements.experiment --source optimized/cold_start_benchmark/artifacts/cold_users_portfolio_repro --run-name improvements_portfolio_repro
& $benchmarkPython -m optimized.cold_start_improvements.summarize --run-name improvements_portfolio_repro
```

모델 선택은 검증 데이터에서 하고 테스트 점수는 선택 이후에 계산합니다. seed가 같아도 병렬 학습의 업데이트 순서 때문에 과거 점수와 정확히 일치하지 않을 수 있습니다. 각 명령의 `config.json`과 결과표를 함께 보관하세요. 이번 마감에서는 위 전체 재학습을 반복하지 않았습니다.

새 실행 결과로 데모를 보려면 실행 전에:

```powershell
$env:RECOMMENDER_BENCHMARK_RUN = 'cold_users_portfolio_repro'
$env:RECOMMENDER_ORIGINAL_RUN = 'original_portfolio_repro'
$env:RECOMMENDER_FOLLOWUP_RUN = 'improvements_portfolio_repro'
& .\optimized\portfolio\run_demo.ps1 -PythonPath $benchmarkPython
```

앱은 해당 결과표를 읽어 성능 수치를 표시합니다. 이 환경변수는 실행 이름만 받습니다. 기존 서버가 실행 중이라면 종료 후 다시 시작하세요.

## 포트폴리오에 남길 파일

- 코드와 이 README
- [최종 결과 문서](FINAL_REPORT.md)와 [발표 요약](PRESENTATION.md)
- 직접 실행한 데모 화면 캡처 또는 짧은 시연 영상
- 개인정보를 제거한 집계 결과표·그래프

`.env`, API 키, 원본 리뷰 데이터, 사용자별 결과·ID 매핑은 공개 저장소에 올리지 않습니다. `artifacts/`, 모델, 데이터가 Git에서 제외돼 있으므로 공개할 집계 수치는 이 폴더의 최종 결과 문서에서 확인할 수 있습니다.
