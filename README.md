# 🗣️ English Native Expression Database

> **비원어민 직장인을 위한 영어 네이티브 표현 데이터베이스 자동 구축 파이프라인**

비즈니스 환경에서 실제로 사용되는 영어 표현 **2,000개**를 자동으로 수집·정제·저장하는 멀티 에이전트 시스템입니다. GitHub Actions를 통해 매일 자동 실행되며, 목표 수량 도달 시 스스로 종료됩니다.

---

## 📐 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    main.py (Orchestrator)                    │
│                                                             │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ Agent 1  │ →  │   Agent 2    │ →  │     Agent 3      │   │
│  │ Scraper  │    │ LLM Processor│    │  Database Manager │   │
│  └──────────┘    └──────────────┘    └──────────────────┘   │
│       ↓                ↓                      ↓             │
│  CNBC, BBC,       Gemini API로           Excel 파일에        │
│  HBR, Friends     표현 추출·정제        구조화된 데이터 저장    │
└─────────────────────────────────────────────────────────────┘
            ↕                    ↕
   expressions_index.json    run_log.json
   (중복 방지 인덱스)          (실행 기록)
```

### 파이프라인 흐름

1. **🔍 Agent 1 — Data Scraper**: 다양한 소스에서 원문 텍스트를 수집
2. **🤖 Agent 2 — LLM Processor**: Gemini API로 네이티브 표현을 추출하고 한국어 뜻·예문 생성
3. **💾 Agent 3 — Database Manager**: 정제된 데이터를 Excel 파일로 저장 (`data/english_expressions_db.xlsx`)

---

## 🔄 자동화

- **GitHub Actions**로 매일 자동 실행
- **케냐 시간 (EAT, UTC+3) 평일 오전 10시** 스케줄
- 수동 트리거도 가능 (`workflow_dispatch`)
- 실행 후 인덱스, 로그, 그리고 **업데이트된 엑셀 파일** 자동 커밋

---

## 🛡️ 중복 방지 — 3중 레이어

| 레이어 | 방식 | 설명 |
|--------|------|------|
| **1. 영구 인덱스** | `expressions_index.json` | 이전에 추출된 모든 표현을 기록 |
| **2. 퍼지 매칭** | 유사도 검사 | 미세한 변형도 중복으로 판별 (예: "pull off" ↔ "pulling off") |
| **3. 배치 내 중복** | 실시간 체크 | 같은 실행 내에서 중복 표현 제거 |

---

## 🛑 자동 종료

- 목표: **2,000개** 표현
- 매 실행 시작 시 현재 수량을 체크
- 2,000개 도달 시 파이프라인 자동 종료
- 일일 목표: **100개** (평일 기준 약 20영업일 = 1개월)

---

## 📊 데이터 스키마

Excel 파일(`data/english_expressions_db.xlsx`)에 저장되는 데이터 구조:

| 컬럼 | 필드 | 예시 |
|------|------|------|
| A | **UID** | `ENG-20260525-001` |
| B | **Date** | `2026-05-25` |
| C | **Source** | `CNBC` |
| D | **Expression** | `pull off` |
| E | **POS** | `phrasal verb` |
| F | **Pronunciation** | `/pʊl ɒf/` |
| G | **Meaning_KR** | `(어려운 일을) 해내다` |
| H | **Original_Text** | `They managed to pull off the deal...` |
| I | **Applied_Example** | `We need to pull off this presentation...` |

---

## 📰 소스

| 소스 | 유형 | 일일 목표 |
|------|------|-----------|
| 🏦 **CNBC** | 비즈니스 뉴스 | 25개 |
| 🌍 **BBC Business** | 글로벌 비즈니스 | 25개 |
| 📚 **HBR** | 고급 비즈니스 | 10개 |
| 📺 **Friends 자막** | 일상 구어체 | 40개 |

> **합계: 100개/일** → 20영업일 = 2,000개 (약 1개월)

---

## ⚠️ 수작업 설정 가이드

> **아래 단계를 반드시 1회 수행해야 파이프라인이 작동합니다.**

### Step 1: GitHub 저장소 생성

GitHub.com에서 새 **private** repository를 생성합니다 (이름: `eng-expression-db` 권장).

이 프로젝트의 모든 파일을 해당 repository에 push합니다:

```bash
cd eng-expression-db
git init
git add .
git commit -m "Initial commit: English Expression DB pipeline"
git remote add origin https://github.com/YOUR_USERNAME/eng-expression-db.git
git branch -M main
git push -u origin main
```

### Step 2: GitHub Secrets 등록 (1회)

Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

1개의 시크릿을 등록합니다:

| Secret Name | 값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API 키 | 모델 API 호출용 키 |

### Step 3: GitHub Actions 활성화 확인

1. Repository → **Actions** 탭으로 이동
2. `"I understand my workflows, go ahead and enable them"` 클릭
3. 첫 실행은 수동 트리거로 테스트:
   - **Actions** → **Daily English Expression DB** → **Run workflow**
4. 작업이 끝나면 깃허브 저장소의 `data/english_expressions_db.xlsx` 파일이 생성/업데이트된 것을 확인할 수 있습니다!

---

## 🧪 로컬 테스트

실제 엑셀에 저장하지 않고 파이프라인을 테스트할 수 있습니다:

```bash
python main.py --dry-run
```

`--dry-run` 모드에서는:
- ✅ 스크래핑 실행
- ✅ LLM 처리 실행
- ✅ 추출된 표현 미리보기 (처음 5개)
- ❌ Excel 저장 건너뜀

---

## 📁 프로젝트 구조

```
eng-expression-db/
├── main.py                  # 파이프라인 오케스트레이터
├── config.py                # 설정값 (소스, 경로, 타겟 등)
├── requirements.txt         # Python 의존성
├── README.md                # 이 문서
│
├── agents/
│   ├── scraper.py           # Agent 1: 데이터 수집
│   ├── processor.py         # Agent 2: LLM 처리
│   └── db_manager.py        # Agent 3: DB 저장
│
├── utils/
│   ├── dedup.py             # 중복 방지 유틸리티
│   └── logger.py            # 로깅 설정
│
├── data/
│   ├── expressions_index.json  # 영구 인덱스 (자동 업데이트)
│   ├── run_log.json            # 실행 기록 (자동 업데이트)
│   └── english_expressions_db.xlsx  # 최종 결과물 엑셀 파일
│
└── .github/
    └── workflows/
        └── daily_expressions.yml  # GitHub Actions 워크플로우
```

---

## 📈 모니터링

- **`data/run_log.json`**: 매 실행마다 결과가 기록됩니다
  ```json
  {
    "date": "2026-05-25",
    "expressions_added": 100,
    "total_count": 500,
    "sources_scraped": 4,
    "status": "success"
  }
  ```
- **GitHub Repository**: `data/` 폴더 내에서 업데이트된 엑셀 파일과 로그를 바로 다운로드하고 확인할 수 있습니다.
