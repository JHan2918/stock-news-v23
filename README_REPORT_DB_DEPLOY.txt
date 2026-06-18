보고서/수출입 DB 연동 배포 메모

1. 서버 앱은 data/report_reports.db 파일을 읽습니다.
   파일이 없으면 data/report_reports.db.zip을 자동으로 풀어서 report_reports.db를 만든 뒤 읽습니다.
2. 증권사 보고서는 /api/research-reports API와 화면의 "보고서" 탭에서 조회합니다.
3. 산업부 수출입 자료는 /api/export-report API와 화면의 "산업데이터" 탭에서 조회합니다.
4. Render 서버에는 PDF 원문을 저장하지 않습니다. DB에는 요약/분석값과 원문 URL만 들어갑니다.
5. GitHub에는 용량 문제를 피하려고 data/report_reports.db는 올리지 않고 data/report_reports.db.zip만 올립니다.
6. DB를 새로 만든 뒤 서버에 반영하려면 최신 report_reports.db를 압축해서 data/report_reports.db.zip으로 교체한 뒤 다시 배포하면 됩니다.
7. 환경변수 REPORT_DB_PATH 또는 REPORT_DB_ZIP_PATH를 지정하면 다른 경로의 SQLite DB/zip을 읽을 수 있습니다.
