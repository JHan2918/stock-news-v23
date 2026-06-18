보고서/수출입 DB 연동 배포 메모

1. 서버 앱은 data/report_reports.db 파일을 읽습니다.
2. 증권사 보고서는 /api/research-reports API와 화면의 "보고서" 탭에서 조회합니다.
3. 산업부 수출입 자료는 /api/export-report API와 화면의 "산업데이터" 탭에서 조회합니다.
4. Render 서버에는 PDF 원문을 저장하지 않습니다. DB에는 요약/분석값과 원문 URL만 들어갑니다.
5. DB를 새로 만든 뒤 서버에 반영하려면 최신 report_reports.db를 data/report_reports.db로 교체해서 다시 배포하면 됩니다.
6. 환경변수 REPORT_DB_PATH를 지정하면 다른 경로의 SQLite DB를 읽을 수 있습니다.
