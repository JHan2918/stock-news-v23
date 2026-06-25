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
from urllib.parse import parse_qs, quote_plus, urlparse
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


def report_db_exists():
    db = extracted_report_db_path()
    return db if db and os.path.exists(db) else ""


def db_connect():
    db = report_db_exists()
    if not db:
        raise RuntimeError("공유 DB를 찾지 못했습니다.")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def db_rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def iso_date(value):
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def latest_db_date(table, column):
    if not report_db_exists():
        return ""
    con = db_connect()
    try:
        row = con.execute(f"SELECT MAX({column}) FROM {table}").fetchone()
        return row[0] if row and row[0] else ""
    finally:
        con.close()


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


def yahoo_chart(symbol, days=30):
    now = int(time.time())
    start = now - days * 86400
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + quote_plus(symbol)
        + f"?period1={start}&period2={now}&interval=1d"
    )
    data = json.loads(http_get(url, timeout=10).decode("utf-8", errors="replace"))
    result = data.get("chart", {}).get("result") or []
    if not result:
        return []
    r = result[0]
    ts = r.get("timestamp") or []
    quote = (r.get("indicators", {}).get("quote") or [{}])[0]
    close = quote.get("close") or []
    out = []
    for t, c in zip(ts, close):
        if c is None:
            continue
        dt = datetime.fromtimestamp(t, KST)
        out.append({"date": dt.strftime("%m/%d"), "value": round(float(c), 4)})
    return out[-days:]


def macro_snapshot():
    symbols = [
        {"category": "미국시장", "key": "nasdaq", "name": "나스닥", "symbol": "^IXIC", "unit": ""},
        {"category": "미국시장", "key": "sp500", "name": "S&P500", "symbol": "^GSPC", "unit": ""},
        {"category": "미국시장", "key": "dow", "name": "다우", "symbol": "^DJI", "unit": ""},
        {"category": "금리/환율", "key": "dxy", "name": "달러지수", "symbol": "DX-Y.NYB", "unit": ""},
        {"category": "금리/환율", "key": "usdkrw", "name": "원달러환율", "symbol": "KRW=X", "unit": "원"},
        {"category": "금리/환율", "key": "us10y", "name": "미국10년물 국채금리", "symbol": "^TNX", "unit": "%"},
        {"category": "원자재/코인", "key": "wti", "name": "WTI 유가", "symbol": "CL=F", "unit": "$"},
        {"category": "원자재/코인", "key": "gold", "name": "금", "symbol": "GC=F", "unit": "$"},
        {"category": "원자재/코인", "key": "bitcoin", "name": "비트코인", "symbol": "BTC-USD", "unit": "$"},
    ]
    items = []
    errors = []
    for s in symbols:
        try:
            series = yahoo_chart(s["symbol"], 30)
            latest = series[-1]["value"] if series else None
            prev = series[-2]["value"] if len(series) >= 2 else None
            change = None if latest is None or prev is None else round(latest - prev, 4)
            pct = None if latest is None or prev in (None, 0) else round((latest - prev) / prev * 100, 2)
            items.append({**s, "latest": latest, "change": change, "pct": pct, "series": series})
        except Exception as exc:
            errors.append(f"{s['name']}: {exc}")
            items.append({**s, "latest": None, "change": None, "pct": None, "series": []})
    return items

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


def research_reports_payload(start="", end="", q="", limit=80):
    if not report_db_exists():
        return {"ok": False, "error": "공유 DB를 찾지 못했습니다."}
    con = db_connect()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    latest = con.execute("SELECT MAX(report_date) FROM reports WHERE report_date<=?", (today,)).fetchone()[0] or ""
    if not latest:
        latest = con.execute("SELECT MAX(report_date) FROM reports").fetchone()[0] or ""
    if not start and not end:
        start = latest
        end = latest
    elif start and not end:
        end = start
    elif end and not start:
        start = end
    where, args = [], []
    if start:
        where.append("report_date>=?")
        args.append(start)
    if end:
        where.append("report_date<=?")
        args.append(end)
    if q:
        like = "%" + q + "%"
        where.append("(stock_name LIKE ? OR stock_code LIKE ?)")
        args.extend([like, like])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    reports = db_rows(
        con,
        f"""
        SELECT report_id,title,report_date,securities_firm,analyst,report_url,stock_name,stock_code,sector,
               investment_opinion,target_price,previous_target_price,target_price_change_type,
               current_price_at_report_date,upside_potential,summary,target_price_reason,risk_summary
        FROM reports
        {where_sql}
        ORDER BY report_date DESC, report_id DESC
        LIMIT ?
        """,
        args + [int(limit or 80)],
    )
    ids = [r["report_id"] for r in reports]
    reasons_by, keywords_by = {}, {}
    if ids:
        ph = ",".join("?" for _ in ids)
        for row in db_rows(con, f"SELECT report_id,reason_keyword,reason_text,sentiment FROM report_reasons WHERE report_id IN ({ph}) ORDER BY reason_id", ids):
            reasons_by.setdefault(row["report_id"], []).append(row)
        for row in db_rows(con, f"SELECT report_id,keyword,keyword_type FROM report_keywords WHERE report_id IN ({ph}) ORDER BY keyword_id", ids):
            keywords_by.setdefault(row["report_id"], []).append(row)
    con.close()
    for r in reports:
        r["reasons"] = reasons_by.get(r["report_id"], [])[:5]
        r["keywords"] = keywords_by.get(r["report_id"], [])[:8]
    return {"ok": True, "reports": reports, "meta": {"start": start, "end": end, "q": q, "latestDate": latest, "count": len(reports)}}


def industry_payload_from_db(month=""):
    if not report_db_exists():
        return {"ok": False, "error": "공유 DB를 찾지 못했습니다."}
    con = db_connect()
    if not month:
        row = con.execute(
            """
            SELECT ir.report_month
            FROM industry_reports ir
            WHERE EXISTS (SELECT 1 FROM industry_items ii WHERE ii.industry_report_id=ir.industry_report_id)
            ORDER BY ir.report_month DESC
            LIMIT 1
            """
        ).fetchone()
        month = row["report_month"] if row else ""
    report = con.execute("SELECT * FROM industry_reports WHERE report_month=?", (month,)).fetchone()
    if not report:
        con.close()
        return {"ok": False, "error": "산업수출데이터가 없습니다."}
    report = dict(report)
    months = [r["report_month"] for r in db_rows(con, "SELECT report_month FROM industry_reports ORDER BY report_month")]
    extracted_months = [
        r["report_month"] for r in db_rows(
            con,
            """
            SELECT DISTINCT ir.report_month
            FROM industry_reports ir JOIN industry_items ii ON ii.industry_report_id=ir.industry_report_id
            ORDER BY ir.report_month
            """
        )
    ]
    items = []
    for item in db_rows(con, "SELECT * FROM industry_items WHERE industry_report_id=? ORDER BY rank", (report["industry_report_id"],)):
        monthly = db_rows(
            con,
            """
            SELECT ir.report_month AS month, ii.latest_amount AS amount, ii.latest_growth AS growth
            FROM industry_reports ir JOIN industry_items ii ON ii.industry_report_id=ir.industry_report_id
            WHERE ii.item_name=?
            ORDER BY ir.report_month
            """,
            (item["item_name"],),
        )
        by_month = {r["month"]: r for r in monthly}
        themes = [r["keyword"] for r in db_rows(con, "SELECT keyword FROM industry_keywords WHERE industry_report_id=? AND item_key=? AND keyword_type='theme' ORDER BY keyword_id", (report["industry_report_id"], item["item_key"]))]
        news = [r["keyword"] for r in db_rows(con, "SELECT keyword FROM industry_keywords WHERE industry_report_id=? AND item_key=? AND keyword_type='news' ORDER BY keyword_id", (report["industry_report_id"], item["item_key"]))]
        items.append({
            "rank": item["rank"], "key": item["item_key"], "name": item["item_name"],
            "latestAmount": item["latest_amount"], "latest": item["latest_growth"],
            "avg3": item["avg_3m_growth"], "acceleration": item["acceleration"], "score": item["score"],
            "comment": item["comment"], "themes": themes, "newsKeywords": news,
            "months": extracted_months,
            "amounts": [by_month.get(m, {}).get("amount") for m in extracted_months],
            "monthly": [by_month.get(m, {}).get("growth") for m in extracted_months],
        })
    countries = [{"name": r["country_name"], "amount": r["export_amount"], "latest": r["growth_rate"], "comment": r["comment"]} for r in db_rows(con, "SELECT * FROM industry_countries WHERE industry_report_id=? ORDER BY growth_rate DESC", (report["industry_report_id"],))]
    regions = [{"name": r["region_name"], "amount": r["export_amount"], "latest": r["growth_rate"], "comment": r["comment"]} for r in db_rows(con, "SELECT * FROM industry_regions WHERE industry_report_id=? ORDER BY growth_rate DESC", (report["industry_report_id"],))]
    con.close()
    return {
        "ok": True, "reportMonth": report["report_month"], "availableMonths": list(reversed(months)),
        "title": report["title"], "url": report["source_url"], "source": report["source"] or "산업통상자원부",
        "headline": report["headline"] or "", "generatedAt": report["generated_at"],
        "metrics": {
            "exportAmount": report["export_amount"] or "-", "exportYoY": report["export_yoy"] or "",
            "importAmount": report["import_amount"] or "-", "importYoY": report["import_yoy"] or "",
            "balance": report["trade_balance"] or "-", "balanceComment": report["balance_comment"] or "",
        },
        "months": extracted_months, "items": items, "countries": countries, "regions": regions,
    }


THEME_SEEDS = [
    {"key": "semiconductor", "name": "반도체/HBM", "keywords": ["HBM", "AI반도체", "메모리"], "stocks": ["삼성전자", "SK하이닉스", "한미반도체", "이오테크닉스", "원익IPS"]},
    {"key": "power", "name": "전력기기", "keywords": ["변압기", "전선", "전력망"], "stocks": ["HD현대일렉트릭", "LS ELECTRIC", "효성중공업", "제룡전기", "대한전선"]},
    {"key": "ship", "name": "조선", "keywords": ["LNG선", "수주", "해양플랜트"], "stocks": ["HD현대중공업", "한화오션", "삼성중공업", "HD한국조선해양", "HD현대미포"]},
    {"key": "defense", "name": "방산", "keywords": ["방산", "수출", "폴란드"], "stocks": ["한화에어로스페이스", "현대로템", "LIG넥스원", "한국항공우주", "한화시스템"]},
    {"key": "cosmetics", "name": "화장품/K뷰티", "keywords": ["K뷰티", "ODM", "미국수출"], "stocks": ["코스맥스", "한국콜마", "아모레퍼시픽", "LG생활건강", "실리콘투"]},
    {"key": "bio", "name": "바이오", "keywords": ["신약", "임상", "FDA"], "stocks": ["삼성바이오로직스", "셀트리온", "알테오젠", "리가켐바이오", "HLB"]},
    {"key": "battery", "name": "이차전지", "keywords": ["배터리", "양극재", "전기차"], "stocks": ["LG에너지솔루션", "삼성SDI", "POSCO홀딩스", "에코프로비엠", "엘앤에프"]},
]


def theme_date_range(start="", end=""):
    if not report_db_exists():
        today = datetime.now(KST).date()
        return (today - timedelta(days=30)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    con = db_connect()
    try:
        latest = con.execute("SELECT MAX(trade_date) FROM theme_investor_flows").fetchone()[0]
        if not latest:
            latest = datetime.now(KST).strftime("%Y-%m-%d")
        if not end:
            end = latest
        if not start:
            dates = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM theme_investor_flows WHERE trade_date<=? ORDER BY trade_date DESC LIMIT 5", (end,)).fetchall()]
            start = dates[-1] if dates else (iso_date(end) - timedelta(days=7)).strftime("%Y-%m-%d")
    finally:
        con.close()
    return start, end


def resolve_stock_by_name(con, raw_name):
    row = con.execute(
        """
        SELECT stock_code, stock_name, count(*) AS cnt
        FROM theme_investor_flows
        WHERE stock_name=?
        GROUP BY stock_code, stock_name
        ORDER BY cnt DESC
        LIMIT 1
        """,
        (raw_name,),
    ).fetchone()
    if row:
        return {"code": normalize_stock_code(row["stock_code"]), "name": row["stock_name"] or raw_name}
    row = con.execute(
        """
        SELECT stock_code, stock_name, count(*) AS cnt
        FROM reports
        WHERE stock_name=?
        GROUP BY stock_code, stock_name
        ORDER BY cnt DESC
        LIMIT 1
        """,
        (raw_name,),
    ).fetchone()
    if row:
        return {"code": normalize_stock_code(row["stock_code"]), "name": row["stock_name"] or raw_name}
    return {"code": "", "name": raw_name}


def theme_stock_snapshot(con, code, start, end):
    rows = db_rows(
        con,
        """
        SELECT trade_date, close_price, volume, foreign_net_volume, institution_net_volume,
               foreign_net_amount, institution_net_amount
        FROM theme_investor_flows
        WHERE stock_code=? AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        (code, start, end),
    )
    valid_close = [r for r in rows if r.get("close_price")]
    first = valid_close[0]["close_price"] if valid_close else 0
    last = valid_close[-1]["close_price"] if valid_close else 0
    change = round((last - first) / first * 100, 2) if first else 0
    return {
        "changePct": change,
        "amount": sum(int((r.get("close_price") or 0) * (r.get("volume") or 0)) for r in rows),
        "foreignNetBuy": sum(int(r.get("foreign_net_amount") or 0) for r in rows),
        "institutionNetBuy": sum(int(r.get("institution_net_amount") or 0) for r in rows),
        "foreignNetVolume": sum(int(r.get("foreign_net_volume") or 0) for r in rows),
        "institutionNetVolume": sum(int(r.get("institution_net_volume") or 0) for r in rows),
        "supplyAvailable": bool(rows),
    }


def theme_dashboard_payload(start="", end=""):
    if not report_db_exists():
        return {"ok": False, "error": "공유 DB를 찾지 못했습니다."}
    start, end = theme_date_range(start, end)
    con = db_connect()
    themes = []
    try:
        for seed in THEME_SEEDS:
            stocks = []
            for raw in seed["stocks"]:
                resolved = resolve_stock_by_name(con, raw)
                code = normalize_stock_code(resolved.get("code"))
                if not code:
                    stocks.append({"name": resolved["name"], "code": "", "changePct": 0, "amount": 0, "supplyAvailable": False})
                    continue
                snap = theme_stock_snapshot(con, code, start, end)
                stocks.append({"name": resolved["name"], "code": code, **snap})
            valid = [s for s in stocks if s.get("code")]
            avg_change = round(sum(s.get("changePct") or 0 for s in valid) / len(valid), 2) if valid else 0
            amount = sum(int(s.get("amount") or 0) for s in valid)
            supply_valid = [s for s in valid if s.get("supplyAvailable")]
            foreign = sum(int(s.get("foreignNetBuy") or 0) for s in supply_valid)
            inst = sum(int(s.get("institutionNetBuy") or 0) for s in supply_valid)
            net = foreign + inst
            score = round(max(0, avg_change) * 12 + min(35, amount / 100000000000) + max(0, net) / 10000000000, 1)
            stocks.sort(key=lambda r: (r.get("changePct") or 0, r.get("amount") or 0), reverse=True)
            themes.append({
                "key": seed["key"], "name": seed["name"], "keywords": seed["keywords"], "newsKeywords": seed["keywords"],
                "changePct": avg_change, "amount": amount, "foreignNetBuy": foreign, "institutionNetBuy": inst,
                "netBuyTotal": net, "supplyAvailable": bool(supply_valid), "score": score, "stocks": stocks,
            })
    finally:
        con.close()
    themes.sort(key=lambda t: (t["score"], t["changePct"], t["amount"]), reverse=True)
    return {"ok": True, "start": start, "end": end, "generatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "provider": "theme_investor_flows", "themes": themes}


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
        "macroCharts": macro_snapshot(),
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
:root{--bg:#0d131a;--panel:#111820;--card:#202832;--line:#344151;--text:#f2f7ff;--muted:#9fb0bf;--good:#8aff8a;--accent:#9dccff;--cyan:#42c7d8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,BlinkMacSystemFont,"Malgun Gothic",sans-serif}
.app{max-width:760px;margin:0 auto;padding:14px 12px 90px}.top{position:sticky;top:0;z-index:10;background:linear-gradient(#0d131a 80%,rgba(13,19,26,0));padding:10px 0 12px}
h1{font-size:24px;margin:0 0 4px}.status{font-size:12px;color:var(--muted);margin-top:8px}
.home-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.home-card{min-height:132px;background:linear-gradient(180deg,#141d27,#111820);border:1px solid var(--line);border-radius:16px;padding:12px;overflow:hidden;box-shadow:0 10px 22px rgba(0,0,0,.16)}.home-card.wide{grid-column:span 2}.home-card.action{min-height:84px;display:flex;flex-direction:column;justify-content:center}.home-card h2{font-size:15px;margin:0 0 9px;letter-spacing:0}.home-card:nth-child(1) h2{color:#9dccff}.home-card:nth-child(2) h2{color:#ffcf9b}.home-card:nth-child(3) h2{color:#c3a7ff}.home-card:nth-child(4) h2{color:#42c7d8}.home-card:nth-child(5) h2{color:#8aff8a}.home-card:nth-child(6) h2{color:#ffb5d0}.home-card:nth-child(7) h2{color:#d7e7ff}
.ticker{height:47px;overflow:hidden}.ticker-track{display:grid;gap:5px;animation:roll 10s linear infinite}.ticker-line{display:grid;grid-template-columns:18px minmax(0,1fr) auto;gap:5px;align-items:center;color:#d8e4ee;font-size:12px;min-height:21px}.ticker-line span:nth-child(2){white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ticker-rank{color:var(--accent);font-weight:900}.ticker-val{color:var(--good);font-weight:800;font-size:11px;white-space:nowrap}@keyframes roll{0%,20%{transform:translateY(0)}28%,48%{transform:translateY(-26px)}56%,76%{transform:translateY(-52px)}84%,96%{transform:translateY(-78px)}100%{transform:translateY(0)}}.hint{font-size:11px;color:var(--muted);margin-top:7px}
.macro-chart-grid{display:grid;gap:10px}.macro-chart{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px}.macro-chart-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}.macro-chart-name{font-weight:900}.macro-chart-value{color:#d7e7ff;font-weight:900}.macro-pos{color:#8aff8a}.macro-neg{color:#ff8585}.mini-svg{width:100%;height:108px;margin-top:8px;display:block}.mini-svg .axis{stroke:#263544;stroke-width:1}.mini-svg .line{fill:none;stroke:#7db1ff;stroke-width:3}.mini-svg .area{fill:#1b2d43;opacity:.55}
.panel{display:none;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin:12px 0}.page-mode #homeGrid{display:none}.page-mode #detailPanel{display:block}.page-mode .refresh{display:none}.panel-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}.back{border:1px solid #4f77aa;background:#26384d;color:#d7e7ff;border-radius:10px;width:38px;height:36px;font-size:18px}.panel h2{font-size:18px;margin:0}.list{display:grid;gap:9px}
.row{display:grid;grid-template-columns:34px 1fr auto;gap:8px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px}.rank{font-size:18px;font-weight:900;color:var(--accent)}.name{font-weight:900;font-size:16px}.meta{font-size:12px;color:var(--muted);line-height:1.45;margin-top:3px}.score{text-align:right;color:var(--good);font-weight:900;font-size:14px}.chip{display:inline-block;border:1px solid #4f77aa;border-radius:999px;padding:2px 7px;margin:3px 3px 0 0;color:#d7e7ff;background:#26384d;font-size:11px}.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}.metric{background:#202832;border:1px solid #344151;border-radius:12px;padding:10px}.metric b{display:block;color:#d7e7ff;font-size:18px}.metric span{display:block;color:#9fb0bf;font-size:11px;margin-top:3px}.section-note{background:#0f1720;border:1px solid #263544;border-radius:12px;padding:10px;color:#c7d4e0;font-size:12px;line-height:1.55;margin-bottom:10px}.mini-bars{display:grid;gap:7px;margin-top:8px}.mini-bar{display:grid;grid-template-columns:76px 1fr auto;gap:7px;align-items:center;font-size:12px}.bar-track{height:8px;background:#344151;border-radius:999px;overflow:hidden}.bar-fill{display:block;height:100%;background:#7db1ff}.pos{color:#8aff8a}.neg{color:#ff8585}
.empty{border:1px dashed #3d4a58;border-radius:12px;padding:18px;color:var(--muted);line-height:1.6}.refresh{width:100%;height:44px;border-radius:12px;border:0;background:linear-gradient(135deg,#42c7d8,#6bb8ff);color:#07131a;font-weight:900;margin-top:10px;box-shadow:0 8px 20px rgba(66,199,216,.18)}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:99;display:flex;align-items:flex-end}.modal.hidden{display:none}.sheet{width:100%;max-height:84vh;overflow:auto;background:#111820;border:1px solid #344151;border-radius:18px 18px 0 0;padding:16px}.sheet-head{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #344151;padding-bottom:10px;margin-bottom:10px}.close{border:1px solid #4f77aa;background:#26384d;color:#d7e7ff;border-radius:9px;padding:6px 10px}.news{border-bottom:1px solid #263544;padding:10px 0}.news a{color:#d7e7ff;text-decoration:none;font-weight:800}.news a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <h1>시장 레이더 Mobile</h1>
    <div id="status" class="status">불러오는 중...</div>
    <button class="refresh" onclick="loadHot(true)">오늘 HOT 새로고침</button>
  </div>
  <div id="homeGrid" class="home-grid">
    <div class="home-card"><h2>오늘의 종목 HOT</h2><div id="stockCard"></div></div>
    <div class="home-card"><h2>시장·거시 HOT</h2><div id="macroCard"></div></div>
    <div class="home-card"><h2>보고서</h2><div id="reportCard"></div></div>
    <div class="home-card action"><h2>매크로 그래프</h2><div id="macroMiniCard"></div></div>
    <div class="home-card"><h2>산업수출데이터</h2><div id="industryCard"></div></div>
    <div class="home-card"><h2>테마</h2><div id="themeCard"></div></div>
    <div class="home-card wide"><h2>관심종목</h2><div id="watchCard"></div></div>
  </div>
  <section id="detailPanel" class="panel"><div class="panel-head"><button class="back" onclick="goHome()">‹</button><h2 id="detailTitle">오늘의 종목 HOT 이슈</h2></div><div id="detailList" class="list"></div></section>
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
function num(n){return Number(n||0).toLocaleString()}
function money(n){n=Number(n||0);if(Math.abs(n)>=1000000000000)return (n/1000000000000).toFixed(1)+"조";if(Math.abs(n)>=100000000)return (n/100000000).toFixed(0)+"억";return num(n)}
function pct(n){n=Number(n||0);return `${n>0?"+":""}${n.toFixed(2)}%`}
async function loadHot(force=false){const st=document.getElementById("status");st.textContent="오늘 HOT 계산 중...";try{const r=await fetch(`/api/hot?force=${force?1:0}&ts=${Date.now()}`);const d=await r.json();if(!d.ok)throw new Error(d.error||"로드 실패");DATA=d;render();st.innerHTML=`${esc(d.today)} / 뉴스 ${d.sourceNewsCount}건 / 업데이트 ${esc(d.generatedAt)} / 공유DB ${d.dbShared?"연결":"없음"}`}catch(e){st.innerHTML=`오류: ${esc(e.message)}`}}
function render(){document.body.classList.remove("page-mode");renderHome()}
function ticker(rows,type){if(!rows.length)return "<div class='empty'>데이터 없음</div>";const lines=rows.slice(0,5).map((r,i)=>{const name=type==="stock"?r.stockName:(type==="report"?r.stockName:r.name||r.keyword);const val=type==="stock"||type==="macro"?`뉴스 ${r.newsCount||0}건`:(type==="report"?(r.opinion||r.firm||"리포트"):r.value||"");return `<div class='ticker-line'><span class='ticker-rank'>${i+1}</span><span>${esc(name)}</span><span class='ticker-val'>${esc(val)}</span></div>`}).join("");return `<div class='ticker'><div class='ticker-track'>${lines}${lines}</div></div><div class='hint'>눌러서 자세히 보기</div>`}
function renderHome(){document.getElementById("stockCard").innerHTML=ticker(DATA.stockHot||[],"stock");document.getElementById("macroCard").innerHTML=ticker(DATA.macroHot||[],"macro");document.getElementById("reportCard").innerHTML=ticker(DATA.reports?.items||[],"report");document.getElementById("macroMiniCard").innerHTML="<div class='ticker'><div class='ticker-track'><div class='ticker-line'><span class='ticker-rank'>↗</span><span>나스닥·S&P500·다우</span><span class='ticker-val'>지수</span></div><div class='ticker-line'><span class='ticker-rank'>↗</span><span>달러지수·환율·금리</span><span class='ticker-val'>매크로</span></div><div class='ticker-line'><span class='ticker-rank'>↗</span><span>WTI·금·비트코인</span><span class='ticker-val'>원자재</span></div></div></div><div class='hint'>눌러서 그래프 보기</div>";document.getElementById("industryCard").innerHTML=ticker(DATA.cards?.industry||[],"static");document.getElementById("themeCard").innerHTML=ticker(DATA.cards?.theme||[],"static");document.getElementById("watchCard").innerHTML=ticker(DATA.cards?.watch||[],"static");document.getElementById("stockCard").parentElement.onclick=()=>showDetail("stock");document.getElementById("macroCard").parentElement.onclick=()=>showDetail("macro");document.getElementById("reportCard").parentElement.onclick=()=>showDetail("report");document.getElementById("macroMiniCard").parentElement.onclick=()=>showDetail("macroChart");document.getElementById("industryCard").parentElement.onclick=()=>showDetail("industry");document.getElementById("themeCard").parentElement.onclick=()=>showDetail("theme");document.getElementById("watchCard").parentElement.onclick=()=>showDetail("watch")}
function goHome(){document.body.classList.remove("page-mode");window.scrollTo({top:0,behavior:"smooth"})}
async function showDetail(type){const title={stock:"오늘의 종목 HOT 이슈",macro:"시장·거시 HOT 이슈",macroChart:"매크로 그래프",report:"보고서",industry:"산업수출데이터",theme:"테마",watch:"관심종목"}[type]||"상세";document.getElementById("detailTitle").textContent=title;document.body.classList.add("page-mode");window.scrollTo({top:0,behavior:"smooth"});if(type==="stock")renderRows(DATA.stockHot||[],"stock");else if(type==="macro")renderRows(DATA.macroHot||[],"macro");else if(type==="macroChart")renderMacroCharts();else if(type==="report")await loadReportPage();else if(type==="industry")await loadIndustryPage();else if(type==="theme")await loadThemePage();else renderStaticRows(DATA.cards?.[type]||[],type)}
function renderRows(rows,type){const el=document.getElementById("detailList");if(!rows.length){el.innerHTML="<div class='empty'>표시할 데이터가 없습니다.</div>";return}el.innerHTML=rows.slice(0,15).map((r,i)=>{const name=type==="stock"?r.stockName:r.keyword;const sub=type==="stock"?r.stockCode:(r.sources||[]).slice(0,2).join(", ");const chips=(r.keywords||[]).slice(0,4).map(k=>`<span class='chip'>${esc(k)}</span>`).join("");return `<div class='row' onclick='openModal("${type}",${i})'><div class='rank'>${i+1}</div><div><div class='name'>${esc(name)}</div><div class='meta'>${esc(sub)} / 뉴스 ${Number(r.newsCount||0)}건 / 점수 ${Number(r.score||0).toFixed(0)}<br>${chips}<br>${esc(r.title||"")}</div></div><div class='score'>뉴스 ${Number(r.newsCount||0)}건<br><span class='meta'>${Number(r.score||0).toFixed(0)}</span></div></div>`}).join("")}
function renderReportRows(rows){const el=document.getElementById("detailList");if(!rows.length){el.innerHTML="<div class='empty'>보고서 데이터가 없습니다.</div>";return}el.innerHTML=rows.map((r,i)=>`<div class='row'><div class='rank'>${i+1}</div><div><div class='name'>${esc(r.stockName||"-")}</div><div class='meta'>${esc(r.firm||"")} / ${esc(r.opinion||"")} / 목표가 ${esc(r.targetPrice||"-")}<br>${esc(r.title||"")}</div></div><div class='score'>보고서</div></div>`).join("")}
async function loadReportPage(){const el=document.getElementById("detailList");el.innerHTML="<div class='empty'>보고서 DB를 불러오는 중...</div>";try{const r=await fetch(`/api/research-reports?limit=40&ts=${Date.now()}`);const d=await r.json();if(!d.ok)throw new Error(d.error||"보고서 로드 실패");renderMobileReports(d)}catch(e){el.innerHTML=`<div class='empty'>보고서 오류: ${esc(e.message)}</div>`}}
function renderMobileReports(d){const el=document.getElementById("detailList");const rows=d.reports||[];const meta=d.meta||{};const stocks=new Set(rows.map(r=>r.stock_name).filter(Boolean));const targets=rows.filter(r=>r.target_price);let html=`<div class='section-note'>${esc(meta.start||"-")} ~ ${esc(meta.end||"-")} / 보고서 ${rows.length}건 / 종목 ${stocks.size}개</div><div class='metric-grid'><div class='metric'><b>${rows.length}건</b><span>보고서</span></div><div class='metric'><b>${targets.length}건</b><span>목표가 포함</span></div></div>`;html+=rows.map((r,i)=>{const kws=(r.keywords||[]).slice(0,4).map(k=>`<span class='chip'>${esc(k.keyword)}</span>`).join("");const reason=(r.reasons||[])[0]?.reason_text||r.target_price_reason||r.summary||"";return `<div class='row'><div class='rank'>${i+1}</div><div><div class='name'>${esc(r.stock_name||"-")}</div><div class='meta'>${esc(r.report_date)} / ${esc(r.securities_firm||"")} / ${esc(r.investment_opinion||"")}<br>목표가 ${r.target_price?num(r.target_price)+"원":"-"} / 현재가 ${r.current_price_at_report_date?num(r.current_price_at_report_date)+"원":"-"}<br>${esc(r.title||"")}<br>${kws}<br>${esc(reason).slice(0,120)}</div></div><div class='score'>${r.upside_potential?Number(r.upside_potential).toFixed(1)+"%":"-"}</div></div>`}).join("");el.innerHTML=html}
async function loadIndustryPage(){const el=document.getElementById("detailList");el.innerHTML="<div class='empty'>산업수출데이터를 불러오는 중...</div>";try{const r=await fetch(`/api/export-report?ts=${Date.now()}`);const d=await r.json();if(!d.ok)throw new Error(d.error||"산업수출데이터 로드 실패");renderMobileIndustry(d)}catch(e){el.innerHTML=`<div class='empty'>산업수출데이터 오류: ${esc(e.message)}</div>`}}
function renderMobileIndustry(d){const el=document.getElementById("detailList");const m=d.metrics||{};const items=d.items||[];const max=Math.max(...items.map(x=>Number(x.latestAmount||0)),1);let html=`<div class='section-note'><b>${esc(d.reportMonth||"-")}</b> ${esc(d.headline||"")}</div><div class='metric-grid'><div class='metric'><b>${esc(m.exportAmount||"-")}</b><span>수출 ${esc(m.exportYoY||"")}</span></div><div class='metric'><b>${esc(m.importAmount||"-")}</b><span>수입 ${esc(m.importYoY||"")}</span></div><div class='metric'><b>${esc(m.balance||"-")}</b><span>무역수지</span></div><div class='metric'><b>${items.length}개</b><span>품목</span></div></div>`;html+=`<div class='section-note'>수출액 상위 품목</div><div class='mini-bars'>`+items.slice().sort((a,b)=>Number(b.latestAmount||0)-Number(a.latestAmount||0)).slice(0,10).map(it=>`<div class='mini-bar'><span>${esc(it.name)}</span><div class='bar-track'><span class='bar-fill' style='width:${Math.max(4,Number(it.latestAmount||0)/max*100)}%'></span></div><b>${num(it.latestAmount)}백만$</b></div>`).join("")+`</div>`;html+=items.slice().sort((a,b)=>Number(b.latest||0)-Number(a.latest||0)).slice(0,12).map((it,i)=>`<div class='row'><div class='rank'>${i+1}</div><div><div class='name'>${esc(it.name)}</div><div class='meta'>수출 ${num(it.latestAmount)}백만$ / 3개월 평균 ${pct(it.avg3)}<br>${esc(it.comment||"")}<br>${(it.newsKeywords||[]).slice(0,4).map(k=>`<span class='chip'>${esc(k)}</span>`).join("")}</div></div><div class='score ${Number(it.latest)>=0?"pos":"neg"}'>${pct(it.latest)}</div></div>`).join("");el.innerHTML=html}
async function loadThemePage(){const el=document.getElementById("detailList");el.innerHTML="<div class='empty'>테마 데이터를 불러오는 중...</div>";try{const r=await fetch(`/api/themes?ts=${Date.now()}`);const d=await r.json();if(!d.ok)throw new Error(d.error||"테마 로드 실패");renderMobileThemes(d)}catch(e){el.innerHTML=`<div class='empty'>테마 오류: ${esc(e.message)}</div>`}}
function renderMobileThemes(d){const el=document.getElementById("detailList");const themes=d.themes||[];let html=`<div class='section-note'>${esc(d.start||"-")} ~ ${esc(d.end||"-")} / ${esc(d.provider||"")} 기준 테마 ${themes.length}개</div>`;html+=themes.map((t,i)=>{const stocks=(t.stocks||[]).slice(0,5).map(s=>`<div class='mini-bar'><span>${esc(s.name)}</span><div class='bar-track'><span class='bar-fill' style='width:${Math.max(4,Math.min(100,Math.abs(Number(s.changePct||0))*8))}%'></span></div><b class='${Number(s.changePct)>=0?"pos":"neg"}'>${pct(s.changePct)}</b></div>`).join("");return `<div class='metric'><b>${i+1}. ${esc(t.name)}</b><span>점수 ${Number(t.score||0).toFixed(1)} / 평균 ${pct(t.changePct)} / 외인+기관 ${money(t.netBuyTotal)}</span><div style='margin-top:6px'>${(t.keywords||[]).map(k=>`<span class='chip'>${esc(k)}</span>`).join("")}</div><div class='mini-bars'>${stocks}</div></div>`}).join("");el.innerHTML=html}
function renderStaticRows(rows,type){const el=document.getElementById("detailList");if(!rows.length){el.innerHTML="<div class='empty'>표시할 데이터가 없습니다.</div>";return}el.innerHTML=rows.map((r,i)=>`<div class='row'><div class='rank'>${i+1}</div><div><div class='name'>${esc(r.name)}</div><div class='meta'>${esc(r.value)} / 상세 데이터 연결 예정</div></div><div class='score'>준비중</div></div>`).join("")}
function svgLine(series,pct){if(!series||series.length<2)return "<div class='empty'>그래프 데이터 없음</div>";const w=320,h=108,p=12;const vals=series.map(x=>Number(x.value));const min=Math.min(...vals),max=Math.max(...vals);const span=max-min||1;const pts=series.map((d,i)=>{const x=p+i*(w-p*2)/(series.length-1);const y=p+(max-Number(d.value))/span*(h-p*2);return [x,y]}).map(p=>p.join(",")).join(" ");const area=`${p},${h-p} ${pts} ${w-p},${h-p}`;const color=Number(pct)>=0?"#8aff8a":"#ff8585";const fill=Number(pct)>=0?"#163222":"#3a1d25";return `<svg class='mini-svg' viewBox='0 0 ${w} ${h}' preserveAspectRatio='none'><line class='axis' x1='${p}' y1='${h-p}' x2='${w-p}' y2='${h-p}'></line><polygon class='area' style='fill:${fill}' points='${area}'></polygon><polyline class='line' style='stroke:${color}' points='${pts}'></polyline></svg>`}
function renderMacroCharts(){const el=document.getElementById("detailList");const rows=DATA.macroCharts||[];if(!rows.length){el.innerHTML="<div class='empty'>매크로 그래프 데이터가 없습니다.</div>";return}const grouped={};rows.forEach(r=>{const k=r.category||"매크로";(grouped[k]=grouped[k]||[]).push(r)});el.innerHTML=Object.keys(grouped).map(cat=>`<div class='section-note'><b>${esc(cat)}</b></div><div class='macro-chart-grid'>${grouped[cat].map(r=>{const pct=Number(r.pct);const cls=pct>=0?"macro-pos":"macro-neg";const sign=Number.isFinite(pct)?(pct>0?"+":"")+pct.toFixed(2)+"%":"";return `<div class='macro-chart'><div class='macro-chart-head'><div class='macro-chart-name'>${esc(r.name)}</div><div class='macro-chart-value'>${r.latest==null?"-":Number(r.latest).toLocaleString()}${esc(r.unit||"")} <span class='${cls}'>${sign}</span></div></div>${svgLine(r.series,pct)}</div>`}).join("")}</div>`).join("")}
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
            elif parsed.path == "/api/research-reports":
                qs = parse_qs(parsed.query)
                start = qs.get("start", [""])[0].strip()
                end = qs.get("end", [""])[0].strip()
                q = qs.get("q", [""])[0].strip()
                limit = int(qs.get("limit", ["80"])[0] or 80)
                self.send(200, json.dumps(research_reports_payload(start, end, q, limit), ensure_ascii=False), "application/json; charset=utf-8")
            elif parsed.path == "/api/export-report":
                qs = parse_qs(parsed.query)
                month = qs.get("month", [""])[0].strip()
                self.send(200, json.dumps(industry_payload_from_db(month), ensure_ascii=False), "application/json; charset=utf-8")
            elif parsed.path == "/api/themes":
                qs = parse_qs(parsed.query)
                start = qs.get("start", [""])[0].strip()
                end = qs.get("end", [""])[0].strip()
                self.send(200, json.dumps(theme_dashboard_payload(start, end), ensure_ascii=False), "application/json; charset=utf-8")
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
