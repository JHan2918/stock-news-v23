from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
import json


APP_VERSION = "vercel-bootstrap-2026-06-29"


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler, html, status=200):
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def home_html():
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Market Radar Mobile Vercel</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #07111c;
      --panel: #101c29;
      --line: #274058;
      --text: #e9f4ff;
      --muted: #9db6cd;
      --accent: #55c7e8;
      --accent2: #7df2b0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: radial-gradient(circle at 20% 0%, #10263a 0, transparent 38%), var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(720px, 100%);
      margin: 0 auto;
      padding: 28px 18px 42px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 22px;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      letter-spacing: 0;
    }}
    .badge {{
      border: 1px solid rgba(85, 199, 232, .55);
      color: var(--accent);
      border-radius: 999px;
      padding: 7px 10px;
      font-size: 12px;
      white-space: nowrap;
    }}
    .card {{
      border: 1px solid var(--line);
      background: rgba(16, 28, 41, .92);
      border-radius: 18px;
      padding: 18px;
      margin: 12px 0;
      box-shadow: 0 18px 40px rgba(0, 0, 0, .24);
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 18px;
    }}
    p {{
      margin: 8px 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .ok {{
      color: var(--accent2);
      font-weight: 700;
    }}
    code {{
      color: var(--accent);
      background: rgba(85, 199, 232, .08);
      border: 1px solid rgba(85, 199, 232, .22);
      border-radius: 8px;
      padding: 2px 6px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 14px;
    }}
    .mini {{
      border: 1px solid rgba(157, 182, 205, .22);
      border-radius: 14px;
      padding: 12px;
      color: var(--muted);
      min-height: 74px;
    }}
    .mini strong {{
      display: block;
      color: var(--text);
      margin-bottom: 6px;
    }}
    @media (max-width: 520px) {{
      main {{ padding: 22px 14px 34px; }}
      h1 {{ font-size: 26px; }}
      .brand {{ align-items: flex-start; flex-direction: column; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="brand">
      <h1>Market Radar Mobile</h1>
      <div class="badge">Vercel bootstrap</div>
    </section>

    <section class="card">
      <h2>새 Vercel 앱 연결 준비 완료</h2>
      <p><span class="ok">정상:</span> 이 화면이 보이면 GitHub 저장소의 <code>mobile-radar-vercel</code> 폴더를 Vercel 프로젝트로 연결할 수 있습니다.</p>
      <p>기존 Render 모바일 앱은 건드리지 않았고, 보고서 DB 자동 업데이트 구조도 그대로 유지합니다.</p>
    </section>

    <section class="card">
      <h2>다음 연결 단계</h2>
      <div class="grid">
        <div class="mini"><strong>1. Vercel</strong>Root Directory를 <code>mobile-radar-vercel</code>로 설정</div>
        <div class="mini"><strong>2. Supabase</strong>회원, 세션, 관심종목 DB 생성</div>
        <div class="mini"><strong>3. 공유 DB</strong><code>data/report_reports.db.zip</code> 읽기 유지</div>
        <div class="mini"><strong>4. 핵심 엔진</strong>관심종목 기업분석 모듈 추가</div>
      </div>
    </section>

    <section class="card">
      <h2>Health Check</h2>
      <p>API 확인: <code>/api/health</code></p>
      <p>Version: <code>{APP_VERSION}</code></p>
    </section>
  </main>
</body>
</html>"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            json_response(
                self,
                {
                    "ok": True,
                    "app": "market-radar-mobile-vercel",
                    "version": APP_VERSION,
                    "message": "Vercel bootstrap app is running.",
                },
            )
            return

        html_response(self, home_html())

