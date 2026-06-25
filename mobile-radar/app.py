# -*- coding: utf-8 -*-
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import traceback
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))
APP_TITLE = "Market Radar Mobile"

MARKET_QUERIES = [
    {"name": "시장전체", "query": "한국 증시 OR 코스피 OR 코스닥 OR 국내 증시 OR 주식시장"},
    {"name": "특징주", "query": "특징주 OR 상한가 OR 하한가 OR 급등주 OR 급락주 OR 장중 급등 OR 장중 급락"},
    {"name": "종목이벤트", "query": "실적 OR 수주 OR 공급계약 OR 증설 OR 임상 OR FDA OR 목표가 OR 증권사"},
    {"name": "수급", "query": "외국인 매도 OR 기관 매도 OR 외국인 순매수 OR 기관 순매수 OR 프로그램 매매"},
    {"name": "매크로", "query": "원달러 환율 OR 환율 급등 OR 국채금리 OR 금리 OR 유가 OR 관세"},
]

MACRO_KEYWORDS = [
    "코스피", "코스닥", "한국증시", "환율", "원달러", "달러", "금리", "국채금리",
    "유가", "관세", "외국인", "기관", "순매수", "순매도", "급락", "급등", "반등",
    "반도체", "HBM", "AI", "2차전지", "바이오", "방산", "조선", "전력기기", "원전",
    "실적", "수주", "공급계약", "증설", "목표가", "임상", "FDA", "자사주", "배당",
]

IMPACT_WORDS = {
    "속보": 3, "단독": 3, "긴급": 3, "급등": 3, "급락": 3, "상한가": 4, "하한가": 4,
    "승인": 4, "수주": 4, "계약": 4, "공급": 3, "인수": 4, "합병": 4, "최대주주": 4,
    "자사주": 4, "배당": 3, "흑자전환": 4, "적자전환": 4, "실적": 3, "영업이익": 3,
    "기술수출": 5, "임상": 4, "FDA": 5, "전쟁": 4, "휴전": 4, "금리": 3, "유가": 3,
    "환율": 3, "HBM": 5, "AI": 3, "반도체": 3, "로봇": 3,
}

DEFAULT_STOCKS = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
    {"code": "009150", "name": "삼성전기"},
    {"code": "011070", "name": "LG이노텍"},
    {"code": "034730", "name": "SK"},
    {"code": "402340", "name": "SK스퀘어"},
    {"code": "005380", "name": "현대차"},
    {"code": "000270", "name": "기아"},
    {"code": "034020", "name": "두산에너빌리티"},
]

HOT_CACHE = {"loaded_at": 0, "data": None}
STOCK_CACHE = {"items": None}


def app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def data_dirs():
    dirs = []
    env = os.environ.get("DATA_DIR")
    if env:
        dirs.append(env)
    dirs.append(os.path.join(app_dir(), "..", "data"))
    dirs.append(os.path.join(app_dir(), "data"))
    return dirs


def report_zip_path():
    for d in data_dirs():
        p = os.path.abspath(os.path.join(d, "report_reports.db.zip"))
        if os.path.exists(p):
            return p
    return ""


def extracted_report_db_path():
    zp = report_zip_path()
    if not zp:
        return ""
    out = os.path.join(tempfile.gettempdir(), "mobile_radar_report_reports.db")
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(zp):
        return out
    with zipfile.ZipFile(zp, "r") as zf:
        names = [n for n in zf.namelist() if n.endswith(".db")]
        if not names:
            return ""
        with zf.open(names[0]) as src, open(out, "wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
    return out


def normalize_stock_name(value):
    return re.sub(r"[\s\-_()./&]+", "", str(value or "").strip().lower())


def normalize_stock_code(value):
    m = re.search(r"\d{6}", str(value or ""))
    return m.group(0) if m else ""


def stock_master():
    if STOCK_CACHE["items"] is not None:
        return STOCK_CACHE["items"]
    items = []
    db = extracted_report_db_path()
    if db and os.path.exists(db):
        try:
            con = sqlite3.connect(db)
            rows = con.execute(
                """
                SELECT stock_name, stock_code, count(*) AS cnt
                FROM reports
                WHERE stock_name IS NOT NULL AND trim(stock_name)!=''
                  AND stock_code IS NOT NULL AND trim(stock_code)!=''
                GROUP BY stock_name, stock_code
                ORDER BY cnt DESC
                LIMIT 2500
                """
            ).fetchall()
            con.close()
            seen = set()
            for name, code, cnt in rows:
                code = normalize_stock_code(code)
                name = str(name or "").strip()
                norm = normalize_stock_name(name)
                if code and name and norm not in seen:
                    seen.add(norm)
                    items.append({"code": code, "name": name, "count": int(cnt or 0), "norm": norm})
        except Exception:
            items = []
    if not items:
        items = [{**s, "count": 0, "norm": normalize_stock_name(s["name"])} for s in DEFAULT_STOCKS]
    STOCK_CACHE["items"] = sorted(items, key=lambda r: (-len(r["norm"]), -int(r.get("count") or 0), r["name"]))
    return STOCK_CACHE["items"]


def http_get(url, timeout=12):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as res:
        return res.read()


def strip_tags(text):
    return re.sub(r"<[^>]+>", " ", unescape(text or "")).strip()


def parse_dt(text):
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST)
    except Exception:
        return None


def search_google_news(topic, query, max_results=70):
    url = "https://news.google.com/rss/search?q=" + quote_plus(query + " when:1d") + "&hl=ko&gl=KR&ceid=KR:ko"
    root = ET.fromstring(http_get(url))
    out = []
    today = datetime.now(KST).date()
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else "Google News"
        summary = strip_tags(item.findtext("description") or "")
        dt = parse_dt(pub)
        if not title or not link or not dt or dt.date() != today:
            continue
        out.append({
            "topic": topic, "title": title, "link": link, "source": source,
            "published": dt.strftime("%Y-%m-%d %H:%M"), "summary": summary,
        })
        if len(out) >= max_results:
            break
    return out


def dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = re.sub(r"\s+", "", it.get("title", "")).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def article_score(item):
    text = f"{item.get('title','')} {item.get('summary','')}"
    low = text.lower()
    score = 1
    for word, weight in IMPACT_WORDS.items():
        if word.lower() in low:
            score += weight
    if any(w in text for w in ("급락", "폭락", "하락", "순매도", "매도", "환율", "금리")):
        score += 4
    if any(w in text for w in ("코스피", "코스닥", "한국 증시", "국내 증시")):
        score += 3
    return score


def stock_mentioned(stock, text):
    name = stock["name"]
    code = stock["code"]
    if code and re.search(rf"(?<!\d){re.escape(code)}(?!\d)", text):
        return True
    if re.search(rf"(?<![가-힣A-Za-z0-9]){re.escape(name)}(?![가-힣A-Za-z0-9])", text, re.I):
        return True
    norm = stock.get("norm") or normalize_stock_name(name)
    return len(norm) >= 4 and norm in normalize_stock_name(text)


def collect_today_items():
    items = []
    errors = []
    for q in MARKET_QUERIES:
        try:
            found = search_google_news(q["name"], q["query"], 80)
            for it in found:
                it["score"] = article_score(it)
                it["query"] = q["name"]
            items.extend(found)
        except Exception as exc:
            errors.append(f"{q['name']}: {exc}")
    return dedupe(items), errors


def build_stock_hot(items):
    stocks = stock_master()
    stats = {}
    for item in items:
        text = f"{item.get('title','')} {item.get('summary','')}"
        matched = []
        for stock in stocks:
            if stock["name"] not in text and stock["code"] not in text and stock["norm"] not in normalize_stock_name(text):
                continue
            if stock_mentioned(stock, text):
                matched.append(stock)
            if len(matched) >= 5:
                break
        for stock in matched:
            key = stock["code"]
            row = stats.setdefault(key, {"stock": stock, "articles": [], "sources": set(), "score": 0})
            row["articles"].append(item)
            row["sources"].add(item.get("source", ""))
            row["score"] += item.get("score", 1)
    rows = []
    for data in stats.values():
        stock = data["stock"]
        articles = data["articles"]
        sources = sorted([s for s in data["sources"] if s])
        event_words = []
        joined = " ".join(a.get("title", "") + " " + a.get("summary", "") for a in articles)
        for word in ("급등", "급락", "상한가", "하한가", "실적", "수주", "공급", "목표가", "임상", "FDA", "자사주", "순매수", "순매도"):
            if word in joined:
                event_words.append(word)
        score = data["score"] + len(articles) * 10 + len(sources) * 6 + len(event_words) * 4
        rows.append({
            "stockName": stock["name"], "stockCode": stock["code"], "newsCount": len(articles),
            "score": round(score, 1), "keywords": event_words[:5], "sources": sources[:5],
            "title": articles[0].get("title", "") if articles else "",
            "url": articles[0].get("link", "") if articles else "",
            "articles": articles[:8],
        })
    rows.sort(key=lambda r: (r["score"], r["newsCount"]), reverse=True)
    return rows[:20]


def build_macro_hot(items):
    stats = {}
    for item in items:
        text = f"{item.get('title','')} {item.get('summary','')}"
        low = text.lower()
        for kw in MACRO_KEYWORDS:
            if kw.lower() in low:
                row = stats.setdefault(kw, {"articles": [], "sources": set(), "score": 0})
                row["articles"].append(item)
                row["sources"].add(item.get("source", ""))
                row["score"] += item.get("score", 1)
    rows = []
    for kw, data in stats.items():
        articles = data["articles"]
        sources = sorted([s for s in data["sources"] if s])
        score = data["score"] + len(articles) * 6 + len(sources) * 5
        rows.append({
            "keyword": kw, "newsCount": len(articles), "score": round(score, 1),
            "sources": sources[:5], "title": articles[0].get("title", "") if articles else "",
            "url": articles[0].get("link", "") if articles else "", "articles": articles[:8],
        })
    rows.sort(key=lambda r: (r["score"], r["newsCount"]), reverse=True)
    return rows[:20]


def report_summary():
    db = extracted_report_db_path()
    if not db or not os.path.exists(db):
        return {"latestDate": "", "count": 0, "items": []}
    try:
        con = sqlite3.connect(db)
        latest = con.execute("SELECT max(report_date) FROM reports WHERE report_date IS NOT NULL AND trim(report_date)!=''").fetchone()[0]
        if not latest:
            con.close()
            return {"latestDate": "", "count": 0, "items": []}
        rows = con.execute(
            """
            SELECT stock_name, stock_code, securities_firm, title, investment_opinion,
                   target_price, report_url, count(*) OVER () AS total_count
            FROM reports
            WHERE report_date=?
            ORDER BY
              CASE WHEN target_price IS NULL OR trim(cast(target_price AS text))='' THEN 1 ELSE 0 END,
              stock_name
            LIMIT 12
            """,
            (latest,),
        ).fetchall()
        con.close()
        items = []
        total = int(rows[0][-1]) if rows else 0
        for r in rows:
            items.append({
                "stockName": r[0] or "",
                "stockCode": normalize_stock_code(r[1]),
                "firm": r[2] or "",
                "title": r[3] or "",
                "opinion": r[4] or "",
                "targetPrice": r[5],
                "url": r[6] or "",
            })
        return {"latestDate": latest, "count": total, "items": items}
    except Exception:
        return {"latestDate": "", "count": 0, "items": []}


def rotating_static_cards():
    return {
        "macro": [
            {"name": "환율", "value": "원달러"},
            {"name": "금리", "value": "국채금리"},
            {"name": "유가", "value": "WTI"},
            {"name": "코스피", "value": "시장 방향"},
            {"name": "외국인", "value": "수급"},
        ],
        "industry": [
            {"name": "반도체", "value": "수출 핵심"},
            {"name": "조선", "value": "수주/선박"},
            {"name": "화장품", "value": "K뷰티"},
            {"name": "전력기기", "value": "변압기/전선"},
            {"name": "자동차", "value": "완성차/부품"},
        ],
        "theme": [
            {"name": "반도체/HBM", "value": "AI 수요"},
            {"name": "전력기기", "value": "데이터센터"},
            {"name": "조선", "value": "수주 사이클"},
            {"name": "방산", "value": "수출/지정학"},
            {"name": "바이오", "value": "임상/FDA"},
        ],
        "watch": [
            {"name": "관심종목", "value": "준비중"},
            {"name": "뉴스 발생", "value": "내 종목"},
            {"name": "보고서 발생", "value": "내 종목"},
            {"name": "수급 변화", "value": "내 종목"},
            {"name": "목표가 변화", "value": "내 종목"},
        ],
    }


def hot_payload(force=False):
    now = time.time()
    if not force and HOT_CACHE["data"] and now - HOT_CACHE["loaded_at"] < 3600:
        return HOT_CACHE["data"]
    items, errors = collect_today_items()
    data = {
        "ok": True,
        "generatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "today": datetime.now(KST).date().isoformat(),
        "sourceNewsCount": len(items),
        "stockHot": build_stock_hot(items),
        "macroHot": build_macro_hot(items),
        "reports": report_summary(),
        "cards": rotating_static_cards(),
        "errors": errors,
        "dbShared": bool(report_zip_path()),
    }
    HOT_CACHE["data"] = data
    HOT_CACHE["loaded_at"] = now
    return data


HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Market Radar Mobile</title>
<style>
:root{--bg:#0d131a;--panel:#111820;--card:#202832;--line:#344151;--text:#f2f7ff;--muted:#9fb0bf;--good:#8aff8a;--accent:#9dccff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,BlinkMacSystemFont,"Malgun Gothic",sans-serif}
.app{max-width:760px;margin:0 auto;padding:14px 12px 90px}.top{position:sticky;top:0;z-index:10;background:linear-gradient(#0d131a 80%,rgba(13,19,26,0));padding:10px 0 12px}
h1{font-size:24px;margin:0 0 4px}.status{font-size:12px;color:var(--muted);margin-top:8px}
.home-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.home-card{min-height:158px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:12px;overflow:hidden}.home-card.big{grid-column:span 2}.home-card h2{font-size:16px;margin:0 0 8px}.home-main{font-size:21px;font-weight:900;color:#d7e7ff;margin-bottom:8px}.ticker{height:78px;overflow:hidden}.ticker-track{display:grid;gap:5px;animation:roll 12s linear infinite}.ticker-line{display:grid;grid-template-columns:22px 1fr auto;gap:6px;align-items:center;color:#c7d4e0;font-size:13px}.ticker-rank{color:var(--accent);font-weight:900}.ticker-val{color:var(--good);font-weight:800;font-size:12px}@keyframes roll{0%,18%{transform:translateY(0)}25%,43%{transform:translateY(-25px)}50%,68%{transform:translateY(-50px)}75%,93%{transform:translateY(-75px)}100%{transform:translateY(0)}}.hint{font-size:11px;color:var(--muted);margin-top:8px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin:12px 0}.panel h2{font-size:18px;margin:0 0 10px}.list{display:grid;gap:9px}
.row{display:grid;grid-template-columns:34px 1fr auto;gap:8px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px}.rank{font-size:18px;font-weight:900;color:var(--accent)}.name{font-weight:900;font-size:16px}.meta{font-size:12px;color:var(--muted);line-height:1.45;margin-top:3px}.score{text-align:right;color:var(--good);font-weight:900;font-size:14px}.chip{display:inline-block;border:1px solid #4f77aa;border-radius:999px;padding:2px 7px;margin:3px 3px 0 0;color:#d7e7ff;background:#26384d;font-size:11px}
.empty{border:1px dashed #3d4a58;border-radius:12px;padding:18px;color:var(--muted);line-height:1.6}.refresh{width:100%;height:44px;border-radius:12px;border:0;background:#217c59;color:white;font-weight:900;margin-top:10px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:99;display:flex;align-items:flex-end}.modal.hidden{display:none}.sheet{width:100%;max-height:84vh;overflow:auto;background:#111820;border:1px solid #344151;border-radius:18px 18px 0 0;padding:16px}.sheet-head{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #344151;padding-bottom:10px;margin-bottom:10px}.close{border:1px solid #4f77aa;background:#26384d;color:#d7e7ff;border-radius:9px;padding:6px 10px}.news{border-bottom:1px solid #263544;padding:10px 0}.news a{color:#d7e7ff;text-decoration:none;font-weight:800}.news a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <h1>시장레이더 Mobile</h1>
    <div id="status" class="status">불러오는 중...</div>
    <button class="refresh" onclick="loadHot(true)">오늘 HOT 새로고침</button>
  </div>
  <div id="homeGrid" class="home-grid">
    <div class="home-card big"><h2>오늘의 종목 HOT</h2><div id="stockCard"></div></div>
    <div class="home-card big"><h2>시장·거시 HOT</h2><div id="macroCard"></div></div>
    <div class="home-card"><h2>보고서</h2><div id="reportCard"></div></div>
    <div class="home-card"><h2>매크로</h2><div id="macroMiniCard"></div></div>
    <div class="home-card"><h2>산업수출입</h2><div id="industryCard"></div></div>
    <div class="home-card"><h2>테마</h2><div id="themeCard"></div></div>
    <div class="home-card big"><h2>관심종목</h2><div id="watchCard"></div></div>
  </div>
  <section id="detailPanel" class="panel"><h2 id="detailTitle">오늘의 종목 HOT 이슈</h2><div id="detailList" class="list"></div></section>
</div>
<div id="modal" class="modal hidden" onclick="closeModal()">
  <div class="sheet" onclick="event.stopPropagation()">
    <div class="sheet-head"><div><b id="modalTitle">뉴스</b><div id="modalMeta" class="meta"></div></div><button class="close" onclick="closeModal()">닫기</button></div>
    <div id="modalBody"></div>
  </div>
</div>
<script>
let DATA=null;
function esc(s){return String(s||"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]))}
async function loadHot(force=false){const st=document.getElementById("status");st.textContent="오늘 HOT 계산 중...";try{const r=await fetch(`/api/hot?force=${force?1:0}&ts=${Date.now()}`);const d=await r.json();if(!d.ok)throw new Error(d.error||"로드 실패");DATA=d;render();st.innerHTML=`${esc(d.today)} / 뉴스 ${d.sourceNewsCount}건 / 업데이트 ${esc(d.generatedAt)} / 공유DB ${d.dbShared?"연결":"없음"}`}catch(e){st.innerHTML=`오류: ${esc(e.message)}`}}
function render(){renderHome();showDetail("stock")}
function ticker(rows,type){if(!rows.length)return "<div class='empty'>데이터 없음</div>";const first=rows[0];const main=type==="stock"?first.stockName:(type==="report"?first.stockName:first.name||first.keyword);const value=type==="report"?`${DATA.reports.count}개 리포트`:(first.newsCount?`뉴스 ${first.newsCount}건`:first.value||"");const lines=rows.slice(0,5).map((r,i)=>{const name=type==="stock"?r.stockName:(type==="report"?r.stockName:r.name||r.keyword);const val=type==="report"?(r.opinion||r.firm||"보고서"):(r.newsCount?`${r.newsCount}건`:r.value||"");return `<div class='ticker-line'><span class='ticker-rank'>${i+1}</span><span>${esc(name)}</span><span class='ticker-val'>${esc(val)}</span></div>`}).join("");return `<div class='home-main'>${esc(main||"-")}</div><div class='ticker'><div class='ticker-track'>${lines}${lines}</div></div><div class='hint'>눌러서 자세히 보기</div>`}
function renderHome(){document.getElementById("stockCard").innerHTML=ticker(DATA.stockHot||[],"stock");document.getElementById("macroCard").innerHTML=ticker(DATA.macroHot||[],"macro");document.getElementById("reportCard").innerHTML=ticker(DATA.reports?.items||[],"report");document.getElementById("macroMiniCard").innerHTML=ticker(DATA.cards?.macro||[],"static");document.getElementById("industryCard").innerHTML=ticker(DATA.cards?.industry||[],"static");document.getElementById("themeCard").innerHTML=ticker(DATA.cards?.theme||[],"static");document.getElementById("watchCard").innerHTML=ticker(DATA.cards?.watch||[],"static");document.getElementById("stockCard").parentElement.onclick=()=>showDetail("stock");document.getElementById("macroCard").parentElement.onclick=()=>showDetail("macro");document.getElementById("reportCard").parentElement.onclick=()=>showDetail("report");document.getElementById("macroMiniCard").parentElement.onclick=()=>showDetail("macro");document.getElementById("industryCard").parentElement.onclick=()=>showDetail("industry");document.getElementById("themeCard").parentElement.onclick=()=>showDetail("theme");document.getElementById("watchCard").parentElement.onclick=()=>showDetail("watch")}
function showDetail(type){const title={stock:"오늘의 종목 HOT 이슈",macro:"시장·거시 HOT 이슈",report:"최근 보고서",industry:"산업수출입",theme:"테마",watch:"관심종목"}[type]||"상세";document.getElementById("detailTitle").textContent=title;if(type==="stock")renderRows(DATA.stockHot||[],"stock");else if(type==="macro")renderRows(DATA.macroHot||[],"macro");else if(type==="report")renderReportRows(DATA.reports?.items||[]);else renderStaticRows(DATA.cards?.[type]||[],type)}
function renderRows(rows,type){const el=document.getElementById("detailList");if(!rows.length){el.innerHTML="<div class='empty'>표시할 데이터가 없습니다.</div>";return}el.innerHTML=rows.slice(0,15).map((r,i)=>{const name=type==="stock"?r.stockName:r.keyword;const sub=type==="stock"?r.stockCode:(r.sources||[]).slice(0,2).join(", ");const chips=(r.keywords||[]).slice(0,4).map(k=>`<span class='chip'>${esc(k)}</span>`).join("");return `<div class='row' onclick='openModal("${type}",${i})'><div class='rank'>${i+1}</div><div><div class='name'>${esc(name)}</div><div class='meta'>${esc(sub)} / 뉴스 ${Number(r.newsCount||0)}건 / 점수 ${Number(r.score||0).toFixed(0)}<br>${chips}<br>${esc(r.title||"")}</div></div><div class='score'>${Number(r.newsCount||0)}건<br><span class='meta'>${Number(r.score||0).toFixed(0)}</span></div></div>`}).join("")}
function renderReportRows(rows){const el=document.getElementById("detailList");if(!rows.length){el.innerHTML="<div class='empty'>보고서 데이터가 없습니다.</div>";return}el.innerHTML=rows.map((r,i)=>`<div class='row'><div class='rank'>${i+1}</div><div><div class='name'>${esc(r.stockName||"-")}</div><div class='meta'>${esc(r.firm||"")} / ${esc(r.opinion||"")} / 목표가 ${esc(r.targetPrice||"-")}<br>${esc(r.title||"")}</div></div><div class='score'>보고서</div></div>`).join("")}
function renderStaticRows(rows,type){const el=document.getElementById("detailList");el.innerHTML=rows.map((r,i)=>`<div class='row'><div class='rank'>${i+1}</div><div><div class='name'>${esc(r.name)}</div><div class='meta'>${esc(r.value)} / 상세 데이터 연결 예정</div></div><div class='score'>준비중</div></div>`).join("")}
function openModal(type,i){const r=(type==="stock"?DATA.stockHot:DATA.macroHot)[i];if(!r)return;document.getElementById("modalTitle").textContent=type==="stock"?`${r.stockName} 뉴스`:`${r.keyword} 뉴스`;document.getElementById("modalMeta").textContent=`뉴스 ${r.newsCount}건 / 점수 ${r.score}`;document.getElementById("modalBody").innerHTML=(r.articles||[]).map(a=>`<div class='news'><a href='${esc(a.link)}' target='_blank' rel='noreferrer'>${esc(a.title)}</a><div class='meta'>${esc(a.source)} ${esc(a.published)}</div></div>`).join("");document.getElementById("modal").classList.remove("hidden")}
function closeModal(){document.getElementById("modal").classList.add("hidden")}
loadHot(false);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def send(self, status, content, ctype="text/html; charset=utf-8"):
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/hot":
                force = "force=1" in self.path
                self.send(200, json.dumps(hot_payload(force), ensure_ascii=False), "application/json; charset=utf-8")
            else:
                self.send(200, HTML)
        except Exception as exc:
            self.send(500, json.dumps({"ok": False, "error": str(exc), "trace": traceback.format_exc()}, ensure_ascii=False), "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        return


def main():
    port = int(os.environ.get("PORT", "8766"))
    host = "0.0.0.0"
    print(APP_TITLE)
    print("URL:", f"http://{host}:{port}/")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
