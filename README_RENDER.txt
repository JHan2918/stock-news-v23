Render 배포 방법

1. 이 폴더 전체를 GitHub 저장소에 올립니다.
2. Render > New > Web Service > 해당 GitHub 저장소 연결
3. 설정값
   - Environment: Python
   - Build Command: pip install -r requirements.txt
   - Start Command: python app.py
4. 배포 후 Render가 제공하는 URL로 접속합니다.

수정사항
- Render에서는 PORT 환경변수를 자동 사용합니다.
- HOST는 Render 배포 시 0.0.0.0으로 동작합니다.
- 서버 실행 시 브라우저 자동열기는 로컬에서만 작동합니다.
