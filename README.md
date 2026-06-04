# Stock News Event Dashboard v24 Lite Render

사용자가 업로드한 라이트 버전을 기준으로 만든 Render 배포용 최소 수정본입니다.

## 포함 파일

- `app.py`
- `stock_event_dictionary.json`
- `requirements.txt`
- `render.yaml`
- `README.md`

## Render 설정

- Build Command: `pip install -r requirements.txt`
- Start Command: `python app.py`

Render에서는 자동으로 `PORT` 환경변수가 제공되며, 앱은 `0.0.0.0:$PORT`로 실행됩니다.

## 로컬 테스트

Windows에서 `run_local.bat` 실행.
