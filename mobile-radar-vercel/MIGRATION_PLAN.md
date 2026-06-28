# MIGRATION PLAN
## Market Radar Mobile: Vercel + Supabase Migration

작성일: 2026-06-29

## 1. 목적

현재 Render에서 동작 중인 `mobile-radar` 앱을 건드리지 않고, 같은 GitHub 저장소 안에 Vercel용 새 앱을 만든다.

이번 1차 목표는 전체 기능 이식이 아니라 다음이다.

1. Vercel에서 새 모바일 앱이 정상 배포되는지 확인
2. 기존 Render 앱은 계속 운영
3. 보고서 DB 자동 업데이트 구조 유지
4. Supabase/PostgreSQL로 회원, 세션, 관심종목, 종목분석 캐시를 이전할 준비
5. 관심종목 기반 기업분석 엔진을 앱의 핵심 축으로 설계

## 2. 절대 유지해야 하는 것

- 기존 `mobile-radar/` Render 앱
- `backup-2` 태그
- `data/report_reports.db.zip`
- 자동 보고서 DB 생성 및 GitHub push 흐름
- 보고서 상세보기의 가독성 개선 상태
- 관심종목 저장값
- 산업수출데이터, 테마, 보고서 DB 조회 기능

## 3. 새 폴더 구조

```text
mobile-radar-vercel/
├─ README.md
├─ MIGRATION_PLAN.md
├─ requirements.txt
├─ vercel.json
└─ api/
   └─ index.py
```

현재는 최소 배포용 구조만 만든다.

## 4. Vercel 1차 배포

Vercel 프로젝트 생성 시:

```text
GitHub Repository: JHan2918/stock-news-v23
Root Directory: mobile-radar-vercel
Framework Preset: Other
Build Command: 비움
Output Directory: 비움
Install Command: pip install -r requirements.txt
Start Command: 사용하지 않음
```

## 5. Supabase 이전 원칙

Vercel은 로컬 SQLite 쓰기 저장소로 쓰면 안 된다.

Supabase/PostgreSQL로 옮길 대상:

- 회원
- 세션
- 관심종목
- 종목분석 프로필
- 분기 재무정보 캐시
- 평가점수

보고서 DB는 당장 Supabase로 옮기지 않는다.

보고서 DB는 기존처럼:

```text
로컬 자동화 -> report_reports.db.zip -> GitHub data/ -> 앱에서 읽기
```

구조를 유지한다.

## 6. 보고서 DB 자동화

현재 보고서 DB 자동화는 계속 유지한다.

향후 옵션:

- 기본: 규칙 기반 요약
- 선택: AI 요약 사용
- AI 사용 시 신규 보고서만 하루 10개 내외 분석
- AI 실패 시 기존 규칙 기반 요약으로 fallback
- 앱 화면에서는 AI를 직접 호출하지 않음
- 자동화 프로그램이 DB에 완성된 결과를 저장

AI 필드 후보:

```text
ai_summary
ai_key_points
ai_target_reason
ai_risks
ai_confidence
ai_model
ai_generated_at
```

## 7. 앱의 최종 핵심

이 앱의 핵심은 뉴스 목록이 아니라 관심종목 기반 기업분석이다.

유저가 관심종목을 등록하면 앱은 다음 데이터를 모아야 한다.

- 네이버금융: 현재가, PER, PBR, EPS, BPS, 배당, 실적표
- FnGuide: 분기 매출, 영업이익, 순이익, ROE, 부채비율, 컨센서스
- KRX: 가격, 거래대금, 시장 기본정보
- 보고서 DB: 목표가, 투자의견, 상승여력, 목표가 변화
- 뉴스: 종목 언급량, 핵심 키워드
- 수급: 외국인/기관 순매수
- 산업수출데이터와 테마 데이터

그리고 유저에게 어려운 숫자를 그대로 던지지 않고 쉽게 해석해야 한다.

예:

```text
이 종목은 업종 평균보다 PBR은 낮지만 ROE도 낮아 단순 저평가로 보기 어렵습니다.
최근 4개 분기 영업이익이 개선되고 있고 보고서 목표가도 상향되어 기대감이 커지는 구간입니다.
뉴스는 많지만 실적 개선 데이터는 아직 약해 테마성 관심으로 분류됩니다.
```

## 8. 제품 원칙

이 앱은 주식 고수용 터미널이 아니다.

주식 초보, 청년 투자자, 은퇴자, 노년층도 뉴스, 보고서, 실적, 수급, 산업데이터를 쉽게 이해할 수 있게 만드는 모바일 투자 인사이트 앱이다.

화면은 전문적이지만 설명은 쉬워야 한다.

중요한 질문:

- 이 종목이 왜 관심받는가?
- 실적은 좋아지고 있는가?
- 보고서 목표가는 올라가는가?
- 외국인과 기관은 사고 있는가?
- 산업 흐름과 맞는가?
- 지금은 기대감인가, 실적이 뒷받침되는가?
- 초보자가 조심해야 할 점은 무엇인가?

## 9. 다음 단계

1. Vercel 최소 앱 배포 확인
2. Supabase 프로젝트 생성
3. 환경변수 연결
4. 회원/세션/관심종목 API를 Supabase로 구현
5. 기존 모바일 UI 일부를 Vercel 앱으로 이식
6. 종목분석 DB/평가엔진 v1 구현
7. 보고서/산업/테마 기능 이식
8. Render 버전과 비교 테스트
9. 충분히 안정되면 Vercel 버전을 정식 모바일 앱으로 교체

