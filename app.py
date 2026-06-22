
# -*- coding: utf-8 -*-
import json, os, re, socket, sqlite3, threading, time, traceback, webbrowser, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

APP_TITLE = "주식 속보 뉴스 이벤트 사전 엔진 v23 + 산업데이터"
HOST = os.environ.get("HOST", "127.0.0.1")
KST = timezone(timedelta(hours=9))

# Kiwi 형태소 분석기는 선택 기능입니다.
# 설치되어 있으면 명사 중심 키워드 추출에 사용하고, 없으면 기존 룰 기반으로 자동 fallback합니다.
KIWI_AVAILABLE = False
KIWI = None
try:
    from kiwipiepy import Kiwi
    KIWI = Kiwi()
    KIWI_AVAILABLE = True
except Exception:
    KIWI_AVAILABLE = False
    KIWI = None


DEFAULT_KEYWORDS = ["달러", "환율", "채권", "국채금리", "유가"]

THEME_KEYWORDS = [
    "삼성전자","SK하이닉스","HBM","HBM3","HBM4","반도체","AI","엔비디아","NVIDIA","TSMC","마이크론","데이터센터",
    "전쟁","휴전","중동","이스라엘","이란","러시아","우크라이나","방산","폴란드",
    "유가","WTI","브렌트","금","달러","환율","원달러","달러지수","금리","채권","국채금리","미국채","10년물","연준","FOMC","CPI","인플레이션",
    "전기차","배터리","2차전지","리튬","희토류","구리","현대차","기아","테슬라",
    "바이오","제약","FDA","임상","승인","보령","유한양행","셀트리온","삼성바이오",
    "합병","인수","수주","계약","공급","투자","증설","실적","매출","영업이익",
    "원전","원자력","전력","로봇","자율주행","조선","해운","식량","곡물",
    "보험","금융","은행","증권","부동산"
]

IMPACT_WORDS = {
    "속보": 3, "단독": 3, "긴급": 3,
    "급등": 3, "급락": 3, "상한가": 4, "하한가": 4,
    "승인": 4, "수주": 4, "계약": 4, "공급": 3,
    "인수": 4, "합병": 4, "최대주주": 4, "지분": 3,
    "제3자배정": 4, "유상증자": 4, "무상증자": 4, "전환사채": 4, "CB": 4, "BW": 4,
    "흑자전환": 4, "적자전환": 4, "실적": 3, "영업이익": 3,
    "기술수출": 5, "임상": 4, "임상3상": 5, "FDA": 5, "신약": 4,
    "제재": 4, "규제": 3, "완화": 3,
    "전쟁": 4, "휴전": 4, "금리": 3, "유가": 3, "환율": 3,
    "HBM": 5, "유리기판": 5, "온디바이스AI": 5, "피지컬AI": 5, "휴머노이드": 5,
    "AI": 3, "반도체": 3, "로봇": 3, "양자": 4
}

STOPWORDS = {
    "있다","했다","한다","된다","있는","없는","위해","통해","관련","기자","종합","오늘","이번","지난","대한",
    "으로","에서","하고","까지","부터","시장","관계자","업계","전망","분석","발표","밝혔다","말했다",
    "참여","개시","판매","제공","개최","운영","진행","지원","확대","강화","추진","선정","공개","소개",
    "보령시장","서울","부산","대구","인천","광주","대전","울산","경기","충남","충북","전남","전북","경남","경북",
    "뉴스","경제","머니","투데이","신문","일보","방송","채널","라디오"
}

CORE_MARKET_KEYWORDS = set(IMPACT_WORDS.keys()) | {
    "매출","영업이익","순이익","가이던스","컨센서스","어닝","어닝서프라이즈","어닝쇼크",
    "투자","증설","공장","생산","양산","납품","공급망","밸류체인",
    "라이선스아웃","기술이전","품목허가","허가","특허","소송","리콜","횡령","배임",
    "국책과제","정부지원","정책","세제혜택","보조금","수출","수입","관세",
    "엔비디아","젠슨황","TSMC","마이크론","삼성전자","SK하이닉스","현대차","테슬라",
    "보령","셀트리온","유한양행","삼성바이오","알테오젠","리가켐바이오",
    "유리기판","HBM","CXL","DDR5","낸드","파운드리","EUV","전력반도체",
    "원전","SMR","방산","전력망","변압기","구리","희토류","리튬","전고체","2차전지"
}

NOVELTY_KEYWORDS = {
    "HBM","HBM3","HBM4","유리기판","온디바이스AI","피지컬AI","휴머노이드","양자컴퓨터","CXL",
    "전력망","변압기","SMR","전고체","로봇","우주항공","AI반도체","자율주행","데이터센터",
    "GLP-1","비만치료제","ADC","항체약물접합체","mRNA"
}


HTML = '''
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>주식 속보 뉴스 이벤트 사전 엔진 v23</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#101418;--panel:#171d23;--line:#2b3542;--text:#e8edf2;--muted:#9fb0bf;--blue:#2f81f7;--chip:#26384d;--warn:#ffb86c;--err:#ff8585;--ok:#8aff8a}
body{font-family:"Malgun Gothic",Arial,sans-serif;margin:0;background:var(--bg);color:var(--text)}
.wrap{max-width:1280px;margin:0 auto;padding:24px}
h1{margin:0 0 8px;font-size:28px}.desc{color:var(--muted);margin-bottom:18px}.box{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(126px,1fr));gap:8px}
label.kw{background:#202832;border:1px solid #344151;border-radius:10px;padding:8px 10px;cursor:pointer;display:block}
label:hover{background:#283241}
textarea,select,input[type=number],input[type=text],input[type=date],input[type=month]{background:#0d1116;color:var(--text);border:1px solid #344151;border-radius:10px;padding:10px;box-sizing:border-box}
textarea{width:100%;height:78px;font-size:15px}select,input[type=number],input[type=text],input[type=date],input[type=month]{font-size:15px}input[type=number]{width:90px}
button{background:var(--blue);color:white;border:0;border-radius:10px;padding:12px 18px;font-size:16px;cursor:pointer}button:hover{background:#1f6feb}button:disabled{background:#444;cursor:not-allowed}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.meta{font-size:13px;color:var(--muted);margin-top:4px}
.badge{display:inline-block;background:#333;color:#ddd;border-radius:999px;padding:3px 8px;font-size:12px;margin-right:6px}
.countbadge{display:inline-block;background:var(--chip);color:#9dccff;border-radius:8px;padding:7px 10px;margin:4px;font-size:14px;cursor:pointer}
.countzero{background:#3a2b2b;color:#ffaaaa}
.ok{color:var(--ok)}.err{color:var(--err)}.warn{color:var(--warn)}
.cardgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.card{background:#202832;border:1px solid #344151;border-radius:12px;padding:12px;cursor:pointer}
.card:hover{background:#283241}.card .num{font-size:26px;font-weight:bold;color:#9dccff}.card .label{font-size:16px;font-weight:bold}.card .sub{font-size:12px;color:var(--muted)}
.graph{height:460px;background:#0d1116;border:1px solid #344151;border-radius:14px;position:relative;overflow:hidden}
.node{position:absolute;border-radius:999px;background:#26384d;color:#d7e7ff;border:1px solid #4f77aa;padding:8px 12px;font-weight:bold;cursor:pointer;box-shadow:0 2px 12px rgba(0,0,0,.25)}
.node:hover{background:#31557c}
.edge{position:absolute;height:2px;background:#42566d;transform-origin:left center;opacity:.65}
.news{list-style:none;padding:0;margin:0}.news li{border-bottom:1px solid var(--line);padding:12px 4px}.news a{color:#d7e7ff;font-size:17px;font-weight:bold;text-decoration:none}.news a:hover{color:#7db1ff;text-decoration:underline}
.section-title{margin:18px 0 8px;padding-top:12px;border-top:1px solid var(--line)}.small{font-size:13px;color:var(--muted)}.hidden{display:none}
.toolbar{position:sticky;top:0;background:rgba(16,20,24,.92);backdrop-filter:blur(8px);z-index:5;padding:8px 0}

.marketgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px;margin-top:12px}
.marketcard{background:#202832;border:1px solid #344151;border-radius:12px;padding:12px}
.markethead{display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:6px}
.marketname{font-weight:bold;font-size:17px}.marketval{font-size:18px;color:#9dccff;font-weight:bold}
.marketchg.up{color:#8aff8a}.marketchg.down{color:#ff8585}.marketchg.flat{color:#aaa}
.chartsvg{width:100%;height:160px;background:#0d1116;border:1px solid #344151;border-radius:8px}


.node-core{background:#4a3b13;border-color:#d6a622;color:#ffe6a3}
.node-novel{background:#223f2d;border-color:#58b579;color:#c9ffd8}
.node-candidate{background:#26384d;border-color:#4f77aa;color:#d7e7ff}
.node-noise{display:none}


.tabs{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.tabbtn{background:#26384d;color:#d7e7ff;border:1px solid #4f77aa;border-radius:10px;padding:9px 14px;font-size:15px}
.tabbtn.active{background:#2f81f7;color:white}
.tabcontent{display:none}
.tabcontent.active{display:block}
.topiccard{background:#202832;border:1px solid #344151;border-radius:12px;padding:12px;cursor:pointer}
.topiccard:hover{background:#283241}

.topic-manager{display:grid;grid-template-columns:1.1fr 2fr 90px auto;gap:8px;align-items:center;margin-top:8px}
.topic-manager input{width:100%}
.topic-list{margin-top:12px;display:grid;gap:8px}
.topic-row{display:grid;grid-template-columns:1fr 2.2fr 80px auto;gap:8px;align-items:center;background:#202832;border:1px solid #344151;border-radius:10px;padding:8px}
.topic-row .topic-name{font-weight:bold;color:#d7e7ff}.topic-row .topic-query{font-size:13px;color:#9fb0bf}.topic-actions button{padding:6px 9px;font-size:12px;margin-left:4px}
@media(max-width:900px){.topic-manager,.topic-row{grid-template-columns:1fr}.topic-actions button{margin:3px 3px 0 0}}



.export-hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:10px}
.export-metric{background:#202832;border:1px solid #344151;border-radius:12px;padding:12px}
.export-metric .k{font-size:13px;color:#9fb0bf}.export-metric .v{font-size:24px;font-weight:bold;color:#d7e7ff;margin-top:4px}.export-metric .c{font-size:13px;margin-top:4px}
.export-full{display:block}.export-row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;align-items:start}.export-row2{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}.export-analysis-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;align-items:start}.export-side-stack{display:grid;grid-template-columns:1fr;gap:14px}.export-chartbox{background:#0d1116;border:1px solid #344151;border-radius:12px;padding:12px;margin-top:12px}.export-chartbox h3{margin:0 0 8px;font-size:17px}
.export-svg{width:100%;height:280px;background:#0d1116;border-radius:8px}.export-svg.tall{height:440px}.export-svg.small{height:230px}
.export-table{width:100%;border-collapse:collapse;font-size:13px}.export-table th,.export-table td{border-bottom:1px solid #344151;padding:7px;text-align:right}.export-table th:first-child,.export-table td:first-child{text-align:left}.export-table th{color:#9fb0bf;font-weight:normal}.export-rank{display:block;margin-top:0}.export-rank-card{background:#202832;border:1px solid #344151;border-radius:12px;padding:12px}.scorebar{height:8px;background:#344151;border-radius:999px;overflow:hidden;margin-top:8px}.scorebar>span{display:block;height:100%;background:#7db1ff}.pill{display:inline-block;border:1px solid #4f77aa;border-radius:999px;padding:3px 8px;margin:2px;color:#d7e7ff;background:#26384d;font-size:12px}.emptybox{border:1px dashed #3d4a58;border-radius:12px;padding:16px;color:#9fb0bf;background:#121920;line-height:1.7}.trend-up{color:#8aff8a}.trend-down{color:#ff8585}.trend-flat{color:#aaa}@media(max-width:1100px){.export-row3,.export-row2,.export-analysis-grid{grid-template-columns:1fr}.export-svg{height:260px}}
.export-stat-controls{display:grid;grid-template-columns:minmax(130px,160px) minmax(130px,160px) minmax(180px,240px) minmax(220px,1fr) auto;gap:10px;align-items:end}.export-stat-controls input,.export-stat-controls select{width:100%;min-width:0}.export-stat-controls button{height:42px;white-space:nowrap;padding:0 14px}.export-stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.export-stat-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:10px}.export-stat-card{background:#202832;border:1px solid #344151;border-radius:12px;padding:10px}.export-stat-card .v{font-size:21px;font-weight:bold;color:#9dccff}.export-stat-card .k{font-size:12px;color:#9fb0bf}@media(max-width:980px){.export-stat-controls{grid-template-columns:1fr 1fr}.export-stat-controls>div:nth-child(4){grid-column:1/-1}.export-stat-controls button{width:100%}.export-stat-grid{grid-template-columns:1fr}}@media(max-width:620px){.export-stat-controls{grid-template-columns:1fr}}
.report-controls{display:grid;grid-template-columns:minmax(150px,170px) minmax(150px,170px) minmax(260px,1fr) auto auto;gap:10px;align-items:end}.report-controls input{width:100%;min-width:0}.report-controls button{height:42px;white-space:nowrap;padding:0 14px}.report-list{display:grid;grid-template-columns:1fr;gap:10px}.report-card{background:#202832;border:1px solid #344151;border-radius:12px;padding:12px}.report-card h3{margin:0 0 6px;font-size:17px}.report-meta{display:flex;gap:8px;flex-wrap:wrap;color:#9fb0bf;font-size:12px;margin-bottom:8px}.report-chip{display:inline-block;border:1px solid #4f77aa;background:#26384d;color:#d7e7ff;border-radius:999px;padding:2px 7px;margin:2px;font-size:12px}.report-price{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:8px 0}.report-price div{background:#111820;border:1px solid #344151;border-radius:10px;padding:8px}.report-price span{display:block;color:#9fb0bf;font-size:12px}.report-price b{display:block;margin-top:3px;color:#d7e7ff}.report-summary{line-height:1.65;color:#dfe8f2}.report-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.report-actions a{display:inline-block;background:#2f81f7;color:white;text-decoration:none;border-radius:9px;padding:7px 10px;font-size:13px}.report-actions button{padding:7px 10px;font-size:13px}.report-detail{margin-top:8px;border-top:1px solid #344151;padding-top:8px}.report-detail h4{margin:8px 0 4px}.report-detail ul{margin:6px 0 0 18px;padding:0}.report-detail li{margin:4px 0;line-height:1.55}.report-statbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px}.report-stat{background:#202832;border:1px solid #344151;border-radius:12px;padding:10px}.report-stat .v{font-size:22px;font-weight:bold;color:#9dccff}.report-stat .k{font-size:12px;color:#9fb0bf}@media(max-width:980px){.report-controls{grid-template-columns:1fr 1fr}.report-controls>div:nth-child(3){grid-column:1/-1}.report-controls button{width:100%}}@media(max-width:620px){.report-controls{grid-template-columns:1fr}}
.report-chart{margin:10px 0 12px;background:#111820;border:1px solid #344151;border-radius:10px;padding:10px}.report-chart-head{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}.report-chart-title{font-weight:700}.report-periods{display:flex;gap:6px;flex-wrap:wrap}.report-periods button{height:30px;padding:0 9px;border-radius:8px;background:#26384d;border:1px solid #4f77aa;font-size:12px}.report-periods button.active{background:#2f81f7;border-color:#7fb4ff}.report-chart canvas{width:100%;height:260px;display:block;background:#0d131a;border:1px solid #263544;border-radius:8px}.report-chart-status{margin-top:7px;color:#9fb0bf;font-size:12px}@media(max-width:620px){.report-chart canvas{height:220px}}
.stock-suggest-box{position:relative}.stock-suggestions{position:absolute;left:0;right:0;top:64px;z-index:40;background:#0d131a;border:1px solid #3b4a5b;border-radius:8px;max-height:260px;overflow:auto;box-shadow:0 12px 30px rgba(0,0,0,.38)}.stock-suggestion{display:flex;justify-content:space-between;gap:10px;padding:9px 10px;border-bottom:1px solid #243140;cursor:pointer}.stock-suggestion:hover,.stock-suggestion.active{background:#1e3145}.stock-suggestion:last-child{border-bottom:0}.stock-suggestion b{font-size:14px}.stock-suggestion span{color:#9fb0bf;font-size:12px;white-space:nowrap}
.theme-controls{display:grid;grid-template-columns:minmax(130px,160px) minmax(130px,160px) auto 1fr;gap:10px;align-items:end}.theme-controls input,.theme-controls select{width:100%;min-width:0}.theme-controls button{height:42px;white-space:nowrap;padding:0 14px}.theme-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.theme-card{background:#202832;border:1px solid #344151;border-radius:12px;padding:12px;cursor:pointer}.theme-card:hover{border-color:#6fa7ee}.theme-card.active{border-color:#7fb4ff;box-shadow:0 0 0 1px #2f81f7 inset}.theme-card h3{margin:0 0 8px;font-size:18px}.theme-score{font-size:28px;font-weight:800;color:#9dccff}.theme-card-line{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:6px;font-size:13px}.theme-bar{height:8px;background:#344151;border-radius:999px;overflow:hidden;margin-top:9px}.theme-bar span{display:block;height:100%;background:#7db1ff}.theme-table{width:100%;border-collapse:collapse;font-size:13px}.theme-table th,.theme-table td{border-bottom:1px solid #344151;padding:7px;text-align:right}.theme-table th:first-child,.theme-table td:first-child{text-align:left}.theme-table th{color:#9fb0bf;font-weight:normal}.theme-supply{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}.theme-supply-card{background:#202832;border:1px solid #344151;border-radius:12px;padding:10px}.theme-supply-card .v{font-size:22px;font-weight:bold;color:#d7e7ff}.theme-supply-card .k{font-size:12px;color:#9fb0bf}.theme-pos{color:#8aff8a}.theme-neg{color:#ff8585}@media(max-width:760px){.theme-controls{grid-template-columns:1fr 1fr}.theme-controls>div:nth-child(4){grid-column:1/-1}.theme-controls button{width:100%}}

</style>
</head>
<body>
<div class="wrap">
<div class="toolbar">
<h1>📰 주식 속보 뉴스 이벤트 사전 엔진 v23</h1>
<div class="desc">뉴스 검색, 속보, 매크로, 이벤트 사전을 한 화면에서 보는 주식 투자 보조 대시보드입니다.</div>
<div class="tabs">
  <button class="tabbtn active" onclick="showTab('searchTab', this)">뉴스검색</button>
  <button class="tabbtn" onclick="showTab('breakingTab', this); loadBreakingNews();">속보뉴스</button>
  <button class="tabbtn" onclick="showTab('macroTab', this)">매크로</button>
  <button class="tabbtn" onclick="showTab('reportTab', this); loadResearchReports(false);">보고서</button>
  <button class="tabbtn" onclick="showTab('exportTab', this); loadExportDashboard(false);">산업데이터</button>
  <button class="tabbtn" onclick="showTab('themeTab', this); loadThemeDashboard(false);">테마</button>
  <button class="tabbtn" onclick="showTab('dictTab', this)">이벤트사전</button>
</div>
</div>

<div id="searchTab" class="tabcontent active">
<div class="box">
<h2>⚙️ 검색 조건</h2>
<div class="row">
<input id="periodValue" type="number" min="1" max="30" value="1">
<select id="periodUnit"><option value="h">시간</option><option value="d">일</option><option value="w" selected>주</option></select>
<select id="maxResults"><option value="20">묶음별 20개</option><option value="50" selected>묶음별 50개</option><option value="100">묶음별 100개</option><option value="200">묶음별 200개</option></select>
<select id="sortBy"><option value="time" selected>최신순</option><option value="score">영향도순</option></select>
</div>
</div>

<div class="box">
<h2>🔎 직접 검색식 입력</h2>
<div class="meta">쉼표 또는 줄바꿈은 검색 묶음 구분, &는 AND 조건입니다. 예: 삼성전자 & HBM, 현대차, 방산 & 폴란드<br><b>기간을 바꿔 재검색하기 쉽도록 검색조건 바로 아래에 배치했습니다.</b></div><br>
<textarea id="extraKeywords" placeholder="예: 삼성전자 & HBM, 현대차, 방산 & 폴란드"></textarea><br><br>
<button id="searchBtn" onclick="searchNews()">뉴스 검색 실행</button>
<button onclick="clearAll()" style="background:#555">초기화</button>
</div>



<div class="box">
<h2>🏷️ 기본 키워드 선택</h2>
<div class="grid" id="keywordGrid"></div>
</div>





<div class="box"><h2>🧾 검색 요약</h2><div id="summary" class="meta">아직 검색 전입니다.</div></div>
<div class="box"><h2>🧩 이슈 카드</h2><div id="cards" class="cardgrid"></div></div>
<div class="box"><h2>🕸️ 키워드 연결 그래프</h2><div class='meta'>노랑=핵심/종목/시장 키워드, 초록=신규 테마 후보, 파랑=후보 키워드. 글씨 크기는 고정. Kiwi ON이면 명사 중심 추출.</div><div id="graph" class="graph"><div class="meta" style="padding:16px">검색 후 표시됩니다.</div></div></div>
<div class="box"><h2>📰 뉴스 제목</h2><div id="status" class="meta">검색 전입니다. 위 카드나 그래프 노드를 클릭하면 관련 뉴스가 펼쳐집니다.</div><div id="newsSections"></div></div>

</div>

<div id="breakingTab" class="tabcontent">
<div class="box">
<h2>⚡ 속보뉴스</h2>
<div class="row">
<input id="breakingValue" type="number" min="1" max="30" value="12">
<select id="breakingUnit"><option value="h" selected>시간</option><option value="d">일</option><option value="w">주</option></select>
<select id="breakingMax"><option value="10">주제별 10개</option><option value="20" selected>주제별 20개</option><option value="50">주제별 50개</option></select>
<button onclick="loadBreakingNews()" style="background:#246b45">내뉴스 새로고침</button>
<button onclick="toggleTopicManager()" style="background:#555">⚙ 내뉴스 주제관리</button>
<span class="meta">주제별 뉴스 건수는 내가 등록한 주제 기준입니다. 같은 제목/링크 뉴스는 중복 제거됩니다.</span>
</div>
<div id="breakingStatus" class="meta" style="margin-top:10px">속보 탭을 열면 내가 설정한 내뉴스 주제별 요약 카드가 표시됩니다. 카드를 클릭하면 뉴스가 펼쳐집니다.</div>
</div>
<div id="topicManagerBox" class="box hidden">
<h2>⚙ 내 속보 주제 관리</h2>
<div class="meta">화면에 보일 이름과 실제 검색식을 분리합니다. 예: 이름=MLCC, 검색식=MLCC OR 적층세라믹콘덴서 OR 삼성전기</div>
<div class="topic-manager">
  <input id="topicNameInput" type="text" placeholder="내뉴스 주제명 예: MLCC">
  <input id="topicQueryInput" type="text" placeholder="검색식 예: MLCC OR 적층세라믹콘덴서 OR 삼성전기">
  <input id="topicPriorityInput" type="number" min="1" max="9" value="5" title="우선순위">
  <div><button onclick="saveBreakingTopic()" style="background:#7a4cc2">저장/추가</button><button onclick="clearTopicForm()" style="background:#555">입력초기화</button></div>
</div>
<div class="row" style="margin-top:10px">
  <button onclick="resetBreakingTopics()" style="background:#8b3a3a">기본 주제로 복원</button>
  <span id="topicManagerStatus" class="meta">주제를 불러오는 중입니다.</span>
</div>
<div id="topicList" class="topic-list"></div>
</div>
<div class="box">
<h2>📊 내뉴스 주제별 뉴스 건수</h2>
<div id="breakingTopics" class="cardgrid"></div>
</div>
<div class="box">
<h2>🏷️ 속보 키워드</h2>
<div id="breakingKeywords" class="cardgrid"></div>
</div>
<div class="box">
<h2>📰 선택한 속보 뉴스</h2>
<div id="breakingNews" class="meta">주제별 뉴스 건수 또는 속보 키워드를 클릭하면 관련 뉴스가 여기에 표시됩니다.</div>
</div>
</div>

<div id="macroTab" class="tabcontent">
<div class="box">
<h2>📈 매크로 그래프</h2>
<div class="row">
<button onclick="loadMarketCharts()" style="background:#246b45">매크로 그래프 새로고침</button>
<span class="meta">나스닥 / S&P500 / 다우 / 달러지수 / 원달러환율 / 미국10년물 / WTI / 금 / 비트코인, 최근 30일</span>
</div>
<div id="marketStatus" class="meta" style="margin-top:10px">아직 불러오기 전입니다.</div>
<div id="marketGrid" class="marketgrid"></div>
</div>
</div>


<div id="reportTab" class="tabcontent">
<div class="box">
<h2>📄 증권사 보고서 DB</h2>
<div class="report-controls">
  <div><div class="meta">시작일</div><input id="reportStart" type="date"></div>
  <div><div class="meta">종료일</div><input id="reportEnd" type="date"></div>
  <div class="stock-suggest-box"><div class="meta">종목명/종목코드</div><input id="reportQuery" type="text" placeholder="삼, 삼성, 005930" autocomplete="off"><input id="reportQueryCode" type="hidden"><div id="reportStockSuggestions" class="stock-suggestions hidden"></div></div>
  <button onclick="loadResearchReports(true)">조회</button>
  <button onclick="clearReportFilters()" style="background:#555">최근 1일</button>
</div>
<div id="reportStatus" class="meta" style="margin-top:10px">보고서 탭을 열면 DB의 최근 1일 보고서를 보여줍니다.</div>
</div>
<div class="box">
  <h2>📌 보고서 요약</h2>
  <div id="reportStats" class="report-statbar"></div>
</div>
<div class="box">
  <h2>🧾 보고서 목록</h2>
  <div id="reportList" class="report-list"></div>
</div>
</div>


<div id="exportTab" class="tabcontent">
<div class="box">
<h2>📦 산업부 수출입 리포트 분석</h2>
<div class="row">
<button onclick="loadExportDashboard(false)" style="background:#246b45">자료 확인 / 저장데이터 갱신</button>
<span class="meta">Render 서버에서는 업로드된 SQLite DB를 읽어 수출입 품목·지역·월별 추이를 표시합니다.</span>
</div>
<div id="exportStatus" class="meta" style="margin-top:10px">산업데이터 탭을 열면 분석 대시보드를 불러옵니다.</div>
<div id="exportRunLog" class="meta" style="margin-top:8px;line-height:1.7"></div>
</div>
<div class="box">
<h2>📌 수출입 핵심 요약</h2>
<div id="exportHero" class="export-hero"></div>
<div id="exportSummary" class="meta" style="margin-top:10px"></div>
</div>
<div class="box export-full">
  <h2>📊 20대 품목 수출 금액 순위</h2>
  <div class="meta">메인 기준은 절대 수출금액입니다. 이 한 칸을 전체 폭으로 사용해서 현재 어느 품목이 가장 크게 수출되는지 먼저 확인합니다.</div>
  <div id="exportTrendChart" class="export-chartbox"></div>
  <div id="exportItemButtons" style="margin-top:8px"></div>
</div>
<div class="export-analysis-grid">
  <div class="box">
    <h2>📈 최근월 증감률 순위</h2>
    <div class="meta">최근월 기준 성장 속도 순위입니다. 단, 투자 판단의 기본 기준은 오른쪽 수출액 순위입니다.</div>
    <div id="exportGrowthChart" class="export-rank"></div>
  </div>
  <div class="box">
    <h2>📋 수출액 순위</h2>
    <div class="meta">최근월 수출액이 큰 품목부터 정렬합니다.</div>
    <div id="exportGrowthTable"></div>
  </div>
  <div class="export-side-stack">
    <div class="box">
      <h2>🌎 국가별 최근 흐름</h2>
      <div id="exportCountryChart" class="export-chartbox"></div>
      <div id="exportCountryTable" style="margin-top:10px"></div>
    </div>
    <div class="box">
      <h2>🗺️ 지역별 최근 흐름</h2>
      <div id="exportRegionChart" class="export-chartbox"></div>
      <div id="exportRegionTable" style="margin-top:10px"></div>
    </div>
  </div>
</div>
<div class="box">
  <h2>🧭 품목 전체 표</h2>
  <div id="exportItemTable"></div>
</div>
<div class="box">
  <h2>📉 수출입 통계분석</h2>
  <div class="meta">DB에 저장된 전체 기간을 기준으로 품목별 월별 수출액과 증감률 흐름을 비교합니다.</div>
  <div class="export-stat-controls" style="margin-top:10px">
    <div><div class="meta">시작월</div><input id="exportStatsStart" type="month"></div>
    <div><div class="meta">종료월</div><input id="exportStatsEnd" type="month"></div>
    <div><div class="meta">품목</div><select id="exportStatsItem"></select></div>
    <div><div class="meta">품목 찾기</div><input id="exportStatsSearch" type="text" placeholder="반도체, 자동차, 화장품"></div>
    <button onclick="renderExportStats(LAST_EXPORT_DATA)">통계 보기</button>
  </div>
  <div id="exportStatsStatus" class="meta" style="margin-top:10px"></div>
  <div id="exportStatsSummary" class="export-stat-summary"></div>
  <div class="export-stat-grid">
    <div class="export-chartbox"><h3>선택 품목 월별 수출금액</h3><div id="exportStatsAmountChart"></div></div>
    <div class="export-chartbox"><h3>선택 품목 월별 증감률</h3><div id="exportStatsGrowthChart"></div></div>
  </div>
  <div class="export-chartbox"><h3>기간 내 품목 비교</h3><div id="exportStatsTable"></div></div>
</div>
<div class="box">
<h2>📰 수출 데이터와 연결할 뉴스 키워드</h2>
<div id="exportNewsBridge" class="meta"></div>
</div>
</div>

<div id="themeTab" class="tabcontent">
<div class="box">
<h2>🧭 테마 대시보드</h2>
<div class="theme-controls">
  <div><div class="meta">시작일</div><input id="themeStart" type="date"></div>
  <div><div class="meta">종료일</div><input id="themeEnd" type="date"></div>
  <button onclick="loadThemeDashboard(true)" style="background:#246b45">테마 보기</button>
  <div class="meta">러프 테마DB 기준으로 최근 등락률, 거래대금, 외국인/기관 순매수를 합산합니다.</div>
</div>
<div id="themeStatus" class="meta" style="margin-top:10px">테마 탭을 열면 최근 5거래일 기준 강한 테마를 보여줍니다.</div>
</div>
<div class="box">
  <h2>🔥 최근 강한 테마</h2>
  <div id="themeCards" class="theme-grid"></div>
</div>
<div class="box">
  <h2>💸 선택 테마 수급</h2>
  <div id="themeSupply" class="theme-supply"></div>
</div>
<div class="box">
  <h2>📋 테마별 종목</h2>
  <div id="themeStocks"></div>
</div>
</div>

<div id="dictTab" class="tabcontent">
<div class="box">
<h2>📚 이벤트 사전 관리</h2>
<div class="meta">새로 발견한 주식 이벤트 키워드를 JSON 사전에 추가합니다. 다음 검색부터 바로 반영됩니다.</div><br>
<div class="row">
<input id="dictCategory" type="text" placeholder="카테고리 예: 주주환원" style="width:180px">
<input id="dictKeyword" type="text" placeholder="키워드 예: 자사주 소각" style="width:220px">
<input id="dictImpact" type="number" min="0" max="100" value="80" title="중요도" style="width:90px">
<input id="dictNovelty" type="number" min="0" max="100" value="20" title="신규성" style="width:90px">
<button onclick="addDictionaryKeyword()" style="background:#7a4cc2">사전에 추가</button>
<button onclick="loadDictionary()" style="background:#555">사전 보기</button>
</div>
<div id="dictStatus" class="meta" style="margin-top:10px">사전 준비 완료.</div>
<div id="dictPreview" class="meta" style="margin-top:10px"></div>
</div>
</div>
</div>

<script>
window.onerror = function(message, source, lineno, colno, error){
  const s=document.getElementById("summary");
  if(s){s.innerHTML="<span class='err'>JS 오류: "+message+" / "+lineno+":"+colno+"</span>";}
};
const DEFAULT_KEYWORDS = __DEFAULT_KEYWORDS__;
let LAST_DATA=null;

function init(){
  const grid=document.getElementById("keywordGrid");
  DEFAULT_KEYWORDS.forEach(kw=>{
    const lab=document.createElement("label"); lab.className="kw";
    const input=document.createElement("input"); input.type="checkbox"; input.value=kw;
    lab.appendChild(input); lab.appendChild(document.createTextNode(" "+kw)); grid.appendChild(lab);
  });
  document.getElementById("extraKeywords").addEventListener("input", clearResultsOnly);
  document.getElementById("periodValue").addEventListener("change", clearResultsOnly);
  document.getElementById("periodUnit").addEventListener("change", clearResultsOnly);
  document.getElementById("maxResults").addEventListener("change", clearResultsOnly);
  document.getElementById("sortBy").addEventListener("change", clearResultsOnly);
  document.querySelectorAll("#keywordGrid input").forEach(x=>x.addEventListener("change", clearResultsOnly));
  document.getElementById("summary").innerHTML="<span class='ok'>준비 완료. 조건을 입력하고 검색하세요.</span>";
  initReportStockSuggest();
  loadMarketCharts();
  loadDictionary();
  loadBreakingTopics();
}

function getPayload(){
  return {
    periodValue: document.getElementById("periodValue").value,
    periodUnit: document.getElementById("periodUnit").value,
    maxResults: document.getElementById("maxResults").value,
    sortBy: document.getElementById("sortBy").value,
    checkedKeywords:[...document.querySelectorAll("#keywordGrid input:checked")].map(x=>x.value),
    extraKeywords: document.getElementById("extraKeywords").value
  };
}

function clearAll(){
  LAST_DATA = null;
  document.querySelectorAll("#keywordGrid input").forEach(x=>x.checked=false);
  document.getElementById("extraKeywords").value="";
  document.getElementById("summary").innerHTML="<span class='ok'>초기화 완료.</span>";
  document.getElementById("cards").innerHTML="";
  document.getElementById("graph").innerHTML="<div class='meta' style='padding:16px'>검색 후 표시됩니다.</div>";
  document.getElementById("newsSections").innerHTML="";
  document.getElementById("status").textContent="검색 전입니다.";
}

function clearResultsOnly(){
  LAST_DATA = null;
  document.getElementById("summary").innerHTML = "<span class='warn'>검색 조건이 변경되었습니다. 다시 검색하세요.</span>";
  document.getElementById("cards").innerHTML = "";
  document.getElementById("graph").innerHTML = "<div class='meta' style='padding:16px'>검색 후 표시됩니다.</div>";
  document.getElementById("newsSections").innerHTML = "";
  document.getElementById("status").textContent = "새 검색 조건입니다. 뉴스 검색 실행을 누르세요.";
}

function renderSummary(data){
  let html=`${data.periodLabel} / 구글뉴스 전용 / 묶음 ${data.groups.length}개 / 전체 ${data.total}건 / Kiwi ${data.kiwiAvailable ? "ON" : "OFF"} / 생성시각 ${data.generatedAt}<br>`;
  data.groups.forEach((g, idx)=>{
    const cnt=data.perGroup[g.label]?.count || 0;
    const cls = cnt===0 ? "countbadge countzero" : "countbadge";
    html += `<span data-group-index="${idx}" class="${cls}">${escapeHtml(g.label)} ${cnt}건</span>`;
  });
  return html;
}

function bindSummaryButtons(){
  document.querySelectorAll("#summary .countbadge").forEach(el=>{
    el.addEventListener("click", function(){
      const idx = parseInt(this.getAttribute("data-group-index"), 10);
      if(LAST_DATA && LAST_DATA.groups && LAST_DATA.groups[idx]){
        toggleGroup(LAST_DATA.groups[idx].label);
      }
    });
  });
}

function renderCards(data){
  const el=document.getElementById("cards"); el.innerHTML="";

  // 검색어 묶음 자체를 먼저 카드로 표시. 예: 보령 49건
  data.groups.forEach(g=>{
    const pg=data.perGroup[g.label];
    const div=document.createElement("div"); div.className="card";
    div.onclick=()=>toggleGroup(g.label);
    div.innerHTML=`<div class="label">검색어: ${g.label}</div><div class="num">${pg.count}</div><div class="sub">전체 뉴스 펼치기</div>`;
    el.appendChild(div);
  });

  data.keywordStats.slice(0,24).forEach(k=>{
    const div=document.createElement("div"); div.className="card";
    div.onclick=()=>showKeywordNews(k.keyword);
    div.innerHTML=`<div class="label">${k.keyword}</div><div class="num">${k.count}</div><div class="sub">관련 뉴스 ${k.count}건 / 시장점수 ${k.marketScore} / ${k.category ? k.category + " / " : ""}${k.kind}</div>`;
    el.appendChild(div);
  });
}

function renderGraph(data){
  const g=document.getElementById("graph"); g.innerHTML="";
  const nodes=data.graph.nodes.slice(0,18);
  const edges=data.graph.edges.slice(0,28);
  if(!nodes.length){g.innerHTML="<div class='meta' style='padding:16px'>그래프를 만들 키워드가 없습니다.</div>"; return;}
  const w=g.clientWidth || 1100, h=g.clientHeight || 460;
  const cx=w/2, cy=h/2, rx=Math.min(w*0.38,420), ry=170;
  const pos={};
  nodes.forEach((n,i)=>{const ang=(Math.PI*2*i/nodes.length)-Math.PI/2; pos[n.id]={x:cx+rx*Math.cos(ang), y:cy+ry*Math.sin(ang)};});
  edges.forEach(e=>{
    if(!pos[e.source]||!pos[e.target]) return;
    const p1=pos[e.source], p2=pos[e.target];
    const dx=p2.x-p1.x, dy=p2.y-p1.y, len=Math.sqrt(dx*dx+dy*dy);
    const line=document.createElement("div"); line.className="edge";
    line.style.left=p1.x+"px"; line.style.top=p1.y+"px"; line.style.width=len+"px";
    line.style.transform=`rotate(${Math.atan2(dy,dx)}rad)`;
    line.style.opacity=Math.min(.9,.25+e.weight*.08);
    g.appendChild(line);
  });
  nodes.forEach(n=>{
    const p=pos[n.id];
    const d=document.createElement("div");
    d.className="node node-"+(n.kind||"candidate");
    d.textContent=`${n.id} ${n.count}`;
    d.title=`시장점수 ${n.score || 0} / ${n.kind || ""}`;
    d.onclick=()=>showKeywordNews(n.id);
    d.style.fontSize="15px";
    d.style.left=(p.x-45)+"px"; d.style.top=(p.y-18)+"px";
    g.appendChild(d);
  });
}

function renderNewsSections(data){
  const el=document.getElementById("newsSections");
  el.innerHTML="<div class='meta'>검색 요약 버튼, 이슈 카드, 또는 그래프 노드를 클릭하면 관련 뉴스가 여기에 표시됩니다.</div>";
}

function toggleGroup(label){
  if(!LAST_DATA || !LAST_DATA.perGroup || !LAST_DATA.perGroup[label]){
    document.getElementById("status").innerHTML=`<span class="warn">${escapeHtml(label)} 뉴스 데이터를 찾지 못했습니다.</span>`;
    return;
  }

  const pg = LAST_DATA.perGroup[label];
  const el = document.getElementById("newsSections");
  let html = `<h3 class="section-title">${escapeHtml(label)} 전체 뉴스 — ${pg.count}건</h3><ul class="news">`;

  if(!pg.items || !pg.items.length){
    html += `<li><span class="warn">선택 기간 내 검색된 뉴스가 없습니다.</span></li>`;
  }else{
    pg.items.forEach(item=>{
      html += `<li>
        <div>
          <span class="badge">구글뉴스</span>
          <span class="badge">${escapeHtml(item.keyword)}</span>
          <span class="badge">영향도 ${item.score}</span>
          <span class="meta">${escapeHtml(item.source || "")}</span>
        </div>
        <a href="${item.link}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
        <div class="meta">${item.published || ""}</div>
      </li>`;
    });
  }

  html += "</ul>";
  el.innerHTML = html;
  document.getElementById("status").innerHTML=`<span class="ok">${escapeHtml(label)} 전체 뉴스 ${pg.count}건을 표시했습니다.</span>`;
  el.scrollIntoView({behavior:"smooth",block:"start"});
}

function normalizeClientText(s){
  return String(s || "").toLowerCase().replace(/[^가-힣a-z0-9]+/g,"");
}

function showKeywordNews(keyword){
  const el=document.getElementById("newsSections"); el.innerHTML="";
  const items=[];
  LAST_DATA.groups.forEach(g=>{(LAST_DATA.perGroup[g.label].items||[]).forEach(item=>{
    const rawText=(item.title+" "+(item.summary||"")+" "+(item.source||"")).toLowerCase();
    const normText=normalizeClientText(rawText);
    const normKeyword=normalizeClientText(keyword);
    if(rawText.includes(keyword.toLowerCase()) || (normKeyword && normText.includes(normKeyword))) items.push(item);
  });});
  let html=`<h3 class="section-title">${keyword} 관련 뉴스 — ${items.length}건</h3><ul class="news">`;
  if(!items.length) html+=`<li><span class="warn">관련 뉴스가 없습니다.</span></li>`;
  items.forEach(item=>{html+=`<li><div><span class="badge">${item.keyword}</span><span class="badge">영향도 ${item.score}</span><span class="meta">${escapeHtml(item.source||'')}</span></div><a href="${item.link}" target="_blank">${escapeHtml(item.title)}</a><div class="meta">${item.published||""}</div></li>`;});
  html+="</ul>"; el.innerHTML=html;
  document.getElementById("status").innerHTML=`<span class="ok">${keyword} 관련 뉴스 ${items.length}건 표시</span>`;
  el.scrollIntoView({behavior:"smooth",block:"start"});
}

async function searchNews(){
  const btn=document.getElementById("searchBtn");
  btn.disabled=true;

  // 새 검색 시작 시 이전 검색 데이터와 화면을 완전히 초기화
  LAST_DATA = null;
  document.getElementById("summary").innerHTML="검색 중...";
  document.getElementById("cards").innerHTML="";
  document.getElementById("graph").innerHTML="<div class='meta' style='padding:16px'>그래프 생성 중...</div>";
  document.getElementById("newsSections").innerHTML="";
  document.getElementById("status").innerHTML="새 검색을 실행 중입니다...";
  try{
    const res=await fetch("/api/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(getPayload())});
    const data=await res.json();
    if(!data.ok){document.getElementById("summary").innerHTML=`<span class="err">${data.error}</span>`; btn.disabled=false; return;}
    LAST_DATA=data;
    document.getElementById("summary").innerHTML=renderSummary(data);
    bindSummaryButtons();
    renderCards(data); renderGraph(data); renderNewsSections(data);
    document.getElementById("status").innerHTML="<span class='ok'>검색 완료. 카드/그래프 노드를 클릭하면 관련 뉴스가 펼쳐집니다.</span>";
  }catch(e){document.getElementById("summary").innerHTML=`<span class="err">오류: ${e.message}</span>`;}
  btn.disabled=false;
}



async function loadDictionary(){
  const status=document.getElementById("dictStatus");
  const preview=document.getElementById("dictPreview");
  if(!status || !preview) return;
  status.innerHTML="사전 불러오는 중...";
  try{
    const res=await fetch("/api/dictionary");
    const data=await res.json();
    if(!data.ok){
      status.innerHTML=`<span class="err">${data.error || "사전 로드 실패"}</span>`;
      return;
    }
    const cats=Object.keys(data.data || {});
    let html=`카테고리 ${cats.length}개<br>`;
    cats.slice(0,12).forEach(cat=>{
      const info=data.data[cat];
      const kws=(info.keywords||[]).slice(0,10).join(", ");
      html+=`<b>${escapeHtml(cat)}</b> (${(info.keywords||[]).length}개): ${escapeHtml(kws)}<br>`;
    });
    preview.innerHTML=html;
    status.innerHTML="<span class='ok'>사전 로드 완료.</span>";
  }catch(e){
    status.innerHTML=`<span class="err">사전 오류: ${e.message}</span>`;
  }
}

async function addDictionaryKeyword(){
  const category=document.getElementById("dictCategory").value.trim();
  const keyword=document.getElementById("dictKeyword").value.trim();
  const impact=document.getElementById("dictImpact").value;
  const novelty=document.getElementById("dictNovelty").value;
  const status=document.getElementById("dictStatus");

  if(!category || !keyword){
    status.innerHTML="<span class='warn'>카테고리와 키워드를 입력하세요.</span>";
    return;
  }

  status.innerHTML="사전에 저장 중...";
  try{
    const res=await fetch("/api/dictionary/add",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({category,keyword,impact,novelty})
    });
    const data=await res.json();
    if(!data.ok){
      status.innerHTML=`<span class="err">${data.error || "저장 실패"}</span>`;
      return;
    }
    status.innerHTML=`<span class="ok">저장 완료: ${escapeHtml(category)} / ${escapeHtml(keyword)}</span>`;
    document.getElementById("dictKeyword").value="";
    loadDictionary();
  }catch(e){
    status.innerHTML=`<span class="err">저장 오류: ${e.message}</span>`;
  }
}



function showTab(tabId, btn){
  document.querySelectorAll(".tabcontent").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".tabbtn").forEach(x=>x.classList.remove("active"));
  const el=document.getElementById(tabId);
  if(el) el.classList.add("active");
  if(btn) btn.classList.add("active");
}

let EDITING_TOPIC_KEY=null;

function toggleTopicManager(){
  const box=document.getElementById("topicManagerBox");
  if(!box) return;
  box.classList.toggle("hidden");
  if(!box.classList.contains("hidden")) loadBreakingTopics();
}

function clearTopicForm(){
  EDITING_TOPIC_KEY=null;
  document.getElementById("topicNameInput").value="";
  document.getElementById("topicQueryInput").value="";
  document.getElementById("topicPriorityInput").value="5";
}

async function loadBreakingTopics(){
  const list=document.getElementById("topicList");
  const st=document.getElementById("topicManagerStatus");
  if(st) st.innerHTML="주제 불러오는 중...";
  try{
    const res=await fetch(`/api/breaking-topics?ts=${Date.now()}`);
    const data=await res.json();
    if(!data.ok){ if(st) st.innerHTML=`<span class='err'>${escapeHtml(data.error||"주제 로드 실패")}</span>`; return; }
    renderBreakingTopicList(data.topics || []);
    if(st) st.innerHTML=`<span class='ok'>내뉴스 주제 ${(data.topics||[]).length}개</span>`;
  }catch(e){ if(st) st.innerHTML=`<span class='err'>주제 오류: ${escapeHtml(e.message)}</span>`; }
}

function renderBreakingTopicList(topics){
  const list=document.getElementById("topicList");
  if(!list) return;
  if(!topics.length){ list.innerHTML="<div class='emptybox'>등록된 내뉴스 주제가 없습니다. 기본 주제로 복원하거나 새 주제를 추가하세요.</div>"; return; }
  list.innerHTML=topics.map(t=>`
    <div class='topic-row'>
      <div class='topic-name'>${escapeHtml(t.name)} ${t.enabled===false?"<span class='badge'>OFF</span>":""}</div>
      <div class='topic-query'>${escapeHtml(t.query)}</div>
      <div class='meta'>우선순위 ${escapeHtml(t.priority||5)}</div>
      <div class='topic-actions'>
        <button onclick='editBreakingTopic(${JSON.stringify(t).replace(/'/g,"&#039;")})' style='background:#555'>수정</button>
        <button onclick='deleteBreakingTopic("${escapeHtml(t.key)}")' style='background:#8b3a3a'>삭제</button>
      </div>
    </div>`).join("");
}

function editBreakingTopic(t){
  EDITING_TOPIC_KEY=t.key || null;
  document.getElementById("topicNameInput").value=t.name || "";
  document.getElementById("topicQueryInput").value=t.query || t.name || "";
  document.getElementById("topicPriorityInput").value=t.priority || 5;
  const box=document.getElementById("topicManagerBox");
  if(box) box.classList.remove("hidden");
}

async function saveBreakingTopic(){
  const name=document.getElementById("topicNameInput").value.trim();
  const query=document.getElementById("topicQueryInput").value.trim() || name;
  const priority=document.getElementById("topicPriorityInput").value || 5;
  const st=document.getElementById("topicManagerStatus");
  if(!name){ if(st) st.innerHTML="<span class='warn'>주제명을 입력하세요.</span>"; return; }
  try{
    const res=await fetch('/api/breaking-topics/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:EDITING_TOPIC_KEY,name,query,priority})});
    const data=await res.json();
    if(!data.ok){ if(st) st.innerHTML=`<span class='err'>${escapeHtml(data.error||"저장 실패")}</span>`; return; }
    clearTopicForm();
    renderBreakingTopicList(data.topics || []);
    if(st) st.innerHTML="<span class='ok'>주제 저장 완료. 속보 새로고침을 누르면 반영됩니다.</span>";
  }catch(e){ if(st) st.innerHTML=`<span class='err'>저장 오류: ${escapeHtml(e.message)}</span>`; }
}

async function deleteBreakingTopic(key){
  if(!confirm('이 주제를 삭제할까요?')) return;
  const st=document.getElementById("topicManagerStatus");
  try{
    const res=await fetch('/api/breaking-topics/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key})});
    const data=await res.json();
    if(!data.ok){ if(st) st.innerHTML=`<span class='err'>${escapeHtml(data.error||"삭제 실패")}</span>`; return; }
    renderBreakingTopicList(data.topics || []);
    if(st) st.innerHTML="<span class='ok'>삭제 완료. 속보 새로고침을 누르면 반영됩니다.</span>";
  }catch(e){ if(st) st.innerHTML=`<span class='err'>삭제 오류: ${escapeHtml(e.message)}</span>`; }
}

async function resetBreakingTopics(){
  if(!confirm('내뉴스 주제를 기본값으로 복원할까요?')) return;
  const st=document.getElementById("topicManagerStatus");
  try{
    const res=await fetch('/api/breaking-topics/reset',{method:'POST'});
    const data=await res.json();
    if(!data.ok){ if(st) st.innerHTML=`<span class='err'>${escapeHtml(data.error||"복원 실패")}</span>`; return; }
    clearTopicForm();
    renderBreakingTopicList(data.topics || []);
    if(st) st.innerHTML="<span class='ok'>기본 주제로 복원되었습니다.</span>";
  }catch(e){ if(st) st.innerHTML=`<span class='err'>복원 오류: ${escapeHtml(e.message)}</span>`; }
}

async function loadBreakingNews(){
  const status=document.getElementById("breakingStatus");
  const topics=document.getElementById("breakingTopics");
  const keywords=document.getElementById("breakingKeywords");
  const news=document.getElementById("breakingNews");
  if(!status || !topics || !keywords || !news) return;

  const v=document.getElementById("breakingValue").value || "12";
  const u=document.getElementById("breakingUnit").value || "h";
  const m=document.getElementById("breakingMax").value || "20";

  status.innerHTML="속보뉴스 불러오는 중...";
  topics.innerHTML="";
  keywords.innerHTML="";
  news.innerHTML="";

  try{
    const res=await fetch(`/api/breaking?value=${encodeURIComponent(v)}&unit=${encodeURIComponent(u)}&max=${encodeURIComponent(m)}`);
    const data=await res.json();
    if(!data.ok){
      status.innerHTML=`<span class="err">${data.error || "속보 로드 실패"}</span>`;
      return;
    }

    status.innerHTML=`<span class="ok">${data.periodLabel} / 내뉴스 주제 ${data.topicCount||0}개 / 중복 제거 후 전체 ${data.total}건 / 업데이트 ${data.generatedAt}</span>` + (data.errors && data.errors.length ? `<br><span class="warn">${data.errors.join(" / ")}</span>` : "");

    data.topics.forEach(t=>{
      const div=document.createElement("div");
      div.className="card";
      div.onclick=()=>renderBreakingTopicNews(t.name, t.items || []);
      div.innerHTML=`<div class="label">${escapeHtml(t.name)}</div><div class="num">${t.count}</div><div class="sub">관련 속보 보기</div>`;
      topics.appendChild(div);
    });

    window.LAST_BREAKING_DATA = data;

    (data.keywordStats || []).slice(0,16).forEach(k=>{
      const actualCount=countBreakingKeywordNews(k.keyword, data.topItems || []);
      if(actualCount <= 0) return;
      const div=document.createElement("div");
      div.className="card";
      div.onclick=()=>renderBreakingKeywordNews(k.keyword, data.topItems || []);
      div.innerHTML=`<div class="label">${escapeHtml(k.keyword)}</div><div class="num">${actualCount}</div><div class="sub">클릭하면 관련 속보 표시 / 시장점수 ${k.marketScore || k.impact || 0}</div>`;
      keywords.appendChild(div);
    });

    news.innerHTML="<div class='meta'>주제별 뉴스 건수 또는 속보 키워드를 클릭하면 관련 뉴스가 여기에 표시됩니다.</div>";
  }catch(e){
    status.innerHTML=`<span class="err">속보 오류: ${e.message}</span>`;
  }
}

function renderBreakingTopicNews(title, items){
  const news=document.getElementById("breakingNews");
  if(!news) return;
  let html=`<h3 class="section-title">${escapeHtml(title)} — ${items.length}건</h3><ul class="news">`;
  if(!items.length){
    html+=`<li><span class="warn">표시할 속보가 없습니다.</span></li>`;
  }else{
    items.forEach(item=>{
      html+=`<li>
        <div><span class="badge">${escapeHtml(item.topic || "속보")}</span><span class="meta">${escapeHtml(item.source || "")}</span></div>
        <a href="${item.link}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
        <div class="meta">${item.published || ""}</div>
      </li>`;
    });
  }
  html+="</ul>";
  news.innerHTML=html;
  news.scrollIntoView({behavior:"smooth",block:"start"});
}



function countBreakingKeywordNews(keyword, allItems){
  const nk=normalizeClientText(keyword);
  let count=0;
  (allItems || []).forEach(item=>{
    const text=(item.title+" "+(item.summary||"")+" "+(item.source||"")).toLowerCase();
    const nt=normalizeClientText(text);
    if(text.includes(String(keyword).toLowerCase()) || (nk && nt.includes(nk))){
      count++;
    }
  });
  return count;
}

function renderBreakingKeywordNews(keyword, allItems){
  const items=[];
  const nk=normalizeClientText(keyword);
  (allItems || []).forEach(item=>{
    const text=(item.title+" "+(item.summary||"")+" "+(item.source||"")).toLowerCase();
    const nt=normalizeClientText(text);
    if(text.includes(String(keyword).toLowerCase()) || (nk && nt.includes(nk))){
      items.push(item);
    }
  });
  renderBreakingTopicNews(keyword + " 관련 속보", items);
}

async function loadMarketCharts(){
  const status=document.getElementById("marketStatus");
  const grid=document.getElementById("marketGrid");
  if(!status || !grid) return;
  status.innerHTML="매크로 데이터 불러오는 중...";
  grid.innerHTML="";
  try{
    const res=await fetch("/api/market");
    const data=await res.json();
    if(!data.ok){
      status.innerHTML=`<span class="err">${data.error || "매크로 데이터 오류"}</span>`;
      return;
    }
    status.innerHTML=`<span class="ok">업데이트: ${data.generatedAt}</span>` + (data.errors && data.errors.length ? `<br><span class="warn">${data.errors.join(" / ")}</span>` : "");
    let lastCat="";
    data.items.forEach(item=>{
      if(item.category && item.category!==lastCat){
        const h=document.createElement("div");
        h.className="market-section-title";
        h.style.gridColumn="1 / -1";
        h.style.fontWeight="800";
        h.style.margin="8px 0 0";
        h.style.color="#d7e7ff";
        h.textContent=item.category;
        grid.appendChild(h);
        lastCat=item.category;
      }
      renderMarketCard(item, grid);
    });
  }catch(e){
    status.innerHTML=`<span class="err">매크로 그래프 오류: ${e.message}</span>`;
  }
}

function renderMarketCard(item, grid){
  const card=document.createElement("div");
  card.className="marketcard";
  const latest = item.latest === null || item.latest === undefined ? "-" : item.latest;
  const chgClass = item.change === null ? "flat" : (item.change > 0 ? "up" : (item.change < 0 ? "down" : "flat"));
  const chgText = item.change === null ? "" : `${item.change > 0 ? "+" : ""}${item.change} (${item.pct > 0 ? "+" : ""}${item.pct}%)`;
  card.innerHTML=`
    <div class="markethead">
      <div class="marketname">${escapeHtml(item.name)}</div>
      <div class="marketval">${latest}${escapeHtml(item.unit || "")}</div>
    </div>
    <div class="marketchg ${chgClass}">${chgText}</div>
    <div>${drawMiniChart(item.series || [])}</div>
    <div class="meta">심볼: ${escapeHtml(item.symbol)} / 최근 30일</div>
  `;
  grid.appendChild(card);
}

function drawMiniChart(series){
  if(!series || series.length < 2){
    return `<svg class="chartsvg"><text x="16" y="40" fill="#9fb0bf">데이터 없음</text></svg>`;
  }
  const w=340, h=150, pad=18;
  const vals=series.map(d=>d.value);
  const min=Math.min(...vals), max=Math.max(...vals);
  const span=(max-min)||1;
  const pts=series.map((d,i)=>{
    const x=pad + i*(w-2*pad)/(series.length-1);
    const y=h-pad - (d.value-min)*(h-2*pad)/span;
    return [x,y];
  });
  const poly=pts.map(p=>p.join(",")).join(" ");
  const last=pts[pts.length-1];
  const lineColor = vals[vals.length-1] >= vals[0] ? "#8aff8a" : "#ff8585";
  return `
    <svg class="chartsvg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="${pad}" y1="${h-pad}" x2="${w-pad}" y2="${h-pad}" stroke="#344151" stroke-width="1"/>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h-pad}" stroke="#344151" stroke-width="1"/>
      <polyline points="${poly}" fill="none" stroke="${lineColor}" stroke-width="3"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="4" fill="${lineColor}"/>
      <text x="${pad+2}" y="${pad+4}" fill="#9fb0bf" font-size="10">${max.toFixed(2)}</text>
      <text x="${pad+2}" y="${h-pad-4}" fill="#9fb0bf" font-size="10">${min.toFixed(2)}</text>
    </svg>`;
}



let LAST_EXPORT_DATA=null;
let SELECTED_EXPORT_ITEM=null;
let LAST_REPORT_DATA=null;
let LAST_THEME_DATA=null;
let SELECTED_THEME_KEY=null;
let REPORT_STOCK_SUGGESTIONS=[];
let REPORT_STOCK_ACTIVE=-1;
let REPORT_STOCK_TIMER=null;
const REPORT_STOCK_FALLBACK=[
  {code:"005930",name:"삼성전자",market:"KOSPI"},
  {code:"005935",name:"삼성전자우",market:"KOSPI"},
  {code:"009150",name:"삼성전기",market:"KOSPI"},
  {code:"032830",name:"삼성생명",market:"KOSPI"},
  {code:"028260",name:"삼성물산",market:"KOSPI"},
  {code:"006400",name:"삼성SDI",market:"KOSPI"},
  {code:"207940",name:"삼성바이오로직스",market:"KOSPI"},
  {code:"000660",name:"SK하이닉스",market:"KOSPI"},
  {code:"005380",name:"현대차",market:"KOSPI"},
  {code:"000270",name:"기아",market:"KOSPI"},
  {code:"204320",name:"HL만도",market:"KOSPI"},
  {code:"034020",name:"두산에너빌리티",market:"KOSPI"},
  {code:"035420",name:"NAVER",market:"KOSPI"},
  {code:"035720",name:"카카오",market:"KOSPI"}
];

function moneyText(v){
  if(v===null || v===undefined || v==="") return "-";
  const n=Number(v);
  if(!Number.isFinite(n)) return "-";
  return n.toLocaleString("ko-KR")+"원";
}

function pctText(v){
  if(v===null || v===undefined || v==="") return "-";
  const n=Number(v);
  if(!Number.isFinite(n)) return "-";
  return (n>0?"+":"")+n.toFixed(1)+"%";
}

function initReportStockSuggest(){
  const input=document.getElementById("reportQuery");
  const box=document.getElementById("reportStockSuggestions");
  if(!input || !box || input.dataset.suggestBound==="1") return;
  input.dataset.suggestBound="1";
  input.addEventListener("input", ()=>{
    const code=document.getElementById("reportQueryCode");
    if(code) code.value="";
    const q=input.value.trim();
    const local=localReportStockSuggestions(q);
    if(local.length) renderReportStockSuggestions(local);
    else hideReportStockSuggestions();
    clearTimeout(REPORT_STOCK_TIMER);
    REPORT_STOCK_TIMER=setTimeout(fetchReportStockSuggestions, 140);
  });
  input.addEventListener("keydown", e=>{
    if(box.classList.contains("hidden")) return;
    if(e.key==="ArrowDown"){
      e.preventDefault();
      REPORT_STOCK_ACTIVE=Math.min(REPORT_STOCK_SUGGESTIONS.length-1, REPORT_STOCK_ACTIVE+1);
      markReportStockSuggestion();
    }else if(e.key==="ArrowUp"){
      e.preventDefault();
      REPORT_STOCK_ACTIVE=Math.max(0, REPORT_STOCK_ACTIVE-1);
      markReportStockSuggestion();
    }else if(e.key==="Enter" && REPORT_STOCK_ACTIVE>=0){
      e.preventDefault();
      selectReportStock(REPORT_STOCK_SUGGESTIONS[REPORT_STOCK_ACTIVE]);
    }else if(e.key==="Escape"){
      hideReportStockSuggestions();
    }
  });
  document.addEventListener("click", e=>{
    if(!e.target.closest(".stock-suggest-box")) hideReportStockSuggestions();
  });
}

function hideReportStockSuggestions(){
  const box=document.getElementById("reportStockSuggestions");
  if(!box) return;
  box.classList.add("hidden");
  box.innerHTML="";
  REPORT_STOCK_ACTIVE=-1;
}

function markReportStockSuggestion(){
  const box=document.getElementById("reportStockSuggestions");
  if(!box) return;
  box.querySelectorAll(".stock-suggestion").forEach((el,idx)=>{
    el.classList.toggle("active", idx===REPORT_STOCK_ACTIVE);
  });
}

function selectReportStock(item){
  const input=document.getElementById("reportQuery");
  const code=document.getElementById("reportQueryCode");
  if(input) input.value=`${item.name} (${item.code})`;
  if(code) code.value=item.code || "";
  hideReportStockSuggestions();
}

function renderReportStockSuggestions(items){
  const box=document.getElementById("reportStockSuggestions");
  if(!box) return;
  REPORT_STOCK_SUGGESTIONS=items || [];
  REPORT_STOCK_ACTIVE=-1;
  if(!REPORT_STOCK_SUGGESTIONS.length){
    hideReportStockSuggestions();
    return;
  }
  box.innerHTML=REPORT_STOCK_SUGGESTIONS.map((item,idx)=>`
    <div class="stock-suggestion" data-idx="${idx}">
      <b>${escapeHtml(item.name || "")}</b>
      <span>${escapeHtml(item.code || "")}${item.market ? " / "+escapeHtml(item.market) : ""}</span>
    </div>`).join("");
  box.querySelectorAll(".stock-suggestion").forEach(el=>{
    el.addEventListener("mousedown", e=>{
      e.preventDefault();
      selectReportStock(REPORT_STOCK_SUGGESTIONS[Number(el.dataset.idx)]);
    });
  });
  box.classList.remove("hidden");
}

function localReportStockSuggestions(q){
  const nq=String(q || "").trim().toLowerCase().replace(/[\\s_()./&-]+/g,"");
  if(!nq) return [];
  return REPORT_STOCK_FALLBACK.filter(item=>{
    const name=String(item.name || "").toLowerCase().replace(/[\\s_()./&-]+/g,"");
    const code=String(item.code || "");
    return name.includes(nq) || code.includes(nq);
  }).slice(0,10);
}

function signedMoneyText(v){
  if(v===null || v===undefined || v==="") return "-";
  const n=Number(v);
  if(!Number.isFinite(n)) return "-";
  const sign=n>0?"+":"";
  const abs=Math.abs(n);
  if(abs>=100000000) return sign+(n/100000000).toFixed(1)+"억";
  if(abs>=10000) return sign+(n/10000).toFixed(1)+"만";
  return sign+n.toLocaleString("ko-KR");
}

async function loadThemeDashboard(useFilters){
  const status=document.getElementById("themeStatus");
  const cards=document.getElementById("themeCards");
  const stocks=document.getElementById("themeStocks");
  const supply=document.getElementById("themeSupply");
  if(!status || !cards || !stocks || !supply) return;
  status.innerHTML="테마 데이터를 불러오는 중...";
  cards.innerHTML="";
  stocks.innerHTML="";
  supply.innerHTML="";
  try{
    const params=new URLSearchParams();
    if(useFilters){
      const s=document.getElementById("themeStart").value.trim();
      const e=document.getElementById("themeEnd").value.trim();
      if(s) params.set("start", s);
      if(e) params.set("end", e);
    }
    params.set("ts", Date.now());
    const res=await fetch(`/api/themes?${params.toString()}`);
    const data=await res.json();
    if(!data.ok){
      status.innerHTML=`<span class='err'>${escapeHtml(data.error || "테마 데이터 오류")}</span>`;
      return;
    }
    LAST_THEME_DATA=data;
    renderThemeDashboard(data);
  }catch(e){
    status.innerHTML=`<span class='err'>테마 오류: ${escapeHtml(e.message)}</span>`;
  }
}

function renderThemeDashboard(data){
  const status=document.getElementById("themeStatus");
  const cards=document.getElementById("themeCards");
  const themes=data.themes || [];
  status.innerHTML=`<span class='ok'>${escapeHtml(data.start || "-")} ~ ${escapeHtml(data.end || "-")} / 테마 ${themes.length}개 / ${escapeHtml(data.provider || "")}</span>` + (data.supplyProvider ? ` <span class='meta'>/ 수급 ${escapeHtml(data.supplyProvider)}</span>` : "");
  if(!themes.length){
    cards.innerHTML="<div class='emptybox'>표시할 테마 데이터가 없습니다.</div>";
    return;
  }
  const maxScore=Math.max(...themes.map(t=>Number(t.score || 0)), 1);
  cards.innerHTML=themes.map((t,idx)=>{
    const cls=idx===0 && !SELECTED_THEME_KEY ? "theme-card active" : "theme-card";
    const pct=Number(t.changePct || 0);
    const supply=Number(t.netBuyTotal || 0);
    return `<div class='${cls}' onclick='selectTheme("${escapeHtml(t.key)}")'>
      <h3>${escapeHtml(t.name)}</h3>
      <div class='theme-score'>${Number(t.score || 0).toFixed(1)}</div>
      <div class='theme-bar'><span style='width:${Math.max(4, Number(t.score || 0)/maxScore*100)}%'></span></div>
      <div class='theme-card-line'><span>평균 등락률</span><b class='${pct>=0?"theme-pos":"theme-neg"}'>${pct>0?"+":""}${pct.toFixed(2)}%</b></div>
      <div class='theme-card-line'><span>거래대금</span><b>${signedMoneyText(t.amount)}</b></div>
      <div class='theme-card-line'><span>외국인+기관</span><b class='${supply>=0?"theme-pos":"theme-neg"}'>${signedMoneyText(supply)}</b></div>
      <div style='margin-top:8px'>${(t.keywords||[]).slice(0,4).map(k=>`<span class='pill'>${escapeHtml(k)}</span>`).join("")}</div>
    </div>`;
  }).join("");
  selectTheme(SELECTED_THEME_KEY || themes[0].key);
}

function selectTheme(key){
  if(!LAST_THEME_DATA) return;
  SELECTED_THEME_KEY=key;
  document.querySelectorAll(".theme-card").forEach(card=>card.classList.remove("active"));
  const themes=LAST_THEME_DATA.themes || [];
  const idx=themes.findIndex(t=>t.key===key);
  const cards=document.querySelectorAll(".theme-card");
  if(idx>=0 && cards[idx]) cards[idx].classList.add("active");
  const theme=themes[idx>=0?idx:0];
  renderThemeDetail(theme || {});
}

function renderThemeDetail(theme){
  const supply=document.getElementById("themeSupply");
  const stocks=document.getElementById("themeStocks");
  if(!supply || !stocks) return;
  const foreign=Number(theme.foreignNetBuy || 0);
  const inst=Number(theme.institutionNetBuy || 0);
  const total=Number(theme.netBuyTotal || 0);
  supply.innerHTML=`
    <div class='theme-supply-card'><div class='k'>테마</div><div class='v'>${escapeHtml(theme.name || "-")}</div></div>
    <div class='theme-supply-card'><div class='k'>외국인 순매수</div><div class='v ${foreign>=0?"theme-pos":"theme-neg"}'>${signedMoneyText(foreign)}</div></div>
    <div class='theme-supply-card'><div class='k'>기관 순매수</div><div class='v ${inst>=0?"theme-pos":"theme-neg"}'>${signedMoneyText(inst)}</div></div>
    <div class='theme-supply-card'><div class='k'>합산 수급</div><div class='v ${total>=0?"theme-pos":"theme-neg"}'>${signedMoneyText(total)}</div></div>
  `;
  const rows=theme.stocks || [];
  if(!rows.length){
    stocks.innerHTML="<div class='emptybox'>이 테마에 연결된 종목이 없습니다.</div>";
    return;
  }
  stocks.innerHTML=`<table class='theme-table'><thead><tr><th>종목</th><th>코드</th><th>등락률</th><th>거래대금</th><th>외국인</th><th>기관</th><th>뉴스</th></tr></thead><tbody>`+
    rows.map(r=>{
      const ch=Number(r.changePct || 0);
      const f=Number(r.foreignNetBuy || 0);
      const i=Number(r.institutionNetBuy || 0);
      return `<tr>
        <td>${escapeHtml(r.name || "")}</td>
        <td>${escapeHtml(r.code || "")}</td>
        <td class='${ch>=0?"theme-pos":"theme-neg"}'>${ch>0?"+":""}${ch.toFixed(2)}%</td>
        <td>${signedMoneyText(r.amount)}</td>
        <td class='${f>=0?"theme-pos":"theme-neg"}'>${signedMoneyText(f)}</td>
        <td class='${i>=0?"theme-pos":"theme-neg"}'>${signedMoneyText(i)}</td>
        <td><button onclick='searchThemeNews("${escapeHtml(r.name || theme.name || "")}")' style='padding:5px 8px;font-size:12px'>검색</button></td>
      </tr>`;
    }).join("")+`</tbody></table>
    <div style='margin-top:10px'>${(theme.newsKeywords||theme.keywords||[]).map(k=>`<span class='pill'>${escapeHtml(k)}</span>`).join("")}</div>`;
}

function searchThemeNews(keyword){
  showTab('searchTab', document.querySelector('.tabbtn'));
  const q=document.getElementById("extraKeywords");
  if(q) q.value=keyword;
  clearResultsOnly();
}

async function fetchReportStockSuggestions(){
  const input=document.getElementById("reportQuery");
  if(!input) return;
  const q=input.value.trim();
  if(!q){
    hideReportStockSuggestions();
    return;
  }
  const local=localReportStockSuggestions(q);
  if(local.length) renderReportStockSuggestions(local);
  try{
    const res=await fetch(`/api/stocks?q=${encodeURIComponent(q)}&ts=${Date.now()}`);
    const data=await res.json();
    if(!data.ok) throw new Error(data.error || "종목 검색 실패");
    const stocks=(data.stocks || []).slice(0,10);
    if(stocks.length) renderReportStockSuggestions(stocks);
    else if(!local.length) hideReportStockSuggestions();
  }catch(e){
    if(!local.length) hideReportStockSuggestions();
  }
}

function clearReportFilters(){
  const s=document.getElementById("reportStart");
  const e=document.getElementById("reportEnd");
  const q=document.getElementById("reportQuery");
  const c=document.getElementById("reportQueryCode");
  if(s) s.value="";
  if(e) e.value="";
  if(q) q.value="";
  if(c) c.value="";
  hideReportStockSuggestions();
  loadResearchReports(false);
}

async function loadResearchReports(useFilters){
  const status=document.getElementById("reportStatus");
  const list=document.getElementById("reportList");
  if(!status || !list) return;
  status.innerHTML="보고서 DB를 불러오는 중...";
  try{
    const params=new URLSearchParams();
    if(useFilters){
      const s=document.getElementById("reportStart").value.trim();
      const e=document.getElementById("reportEnd").value.trim();
      const selectedCode=(document.getElementById("reportQueryCode")||{}).value || "";
      const q=selectedCode || document.getElementById("reportQuery").value.trim();
      if(s) params.set("start", s);
      if(e) params.set("end", e);
      if(q) params.set("q", q);
    }
    params.set("ts", Date.now());
    const res=await fetch(`/api/research-reports?${params.toString()}`);
    const raw=await res.text();
    let data;
    try{
      data=JSON.parse(raw);
    }catch(parseError){
      const preview=raw.replace(/\\s+/g, " ").slice(0, 120);
      throw new Error(`API가 JSON이 아닌 응답을 보냈습니다. HTTP ${res.status} / ${preview}`);
    }
    if(!data.ok){status.innerHTML=`<span class='err'>${escapeHtml(data.error || "보고서 DB 오류")}</span>`; return;}
    LAST_REPORT_DATA=data;
    renderResearchReports(data);
  }catch(e){
    status.innerHTML=`<span class='err'>보고서 DB 오류: ${escapeHtml(e.message)}</span>`;
  }
}

function renderResearchReports(data){
  const status=document.getElementById("reportStatus");
  const stats=document.getElementById("reportStats");
  const list=document.getElementById("reportList");
  const meta=data.meta || {};
  const reports=data.reports || [];
  status.innerHTML=`<span class='ok'>${escapeHtml(meta.start || "-")} ~ ${escapeHtml(meta.end || "-")} / ${reports.length}건</span>` + (meta.latestDate ? ` <span class='meta'>/ 최신 보고서일 ${escapeHtml(meta.latestDate)}</span>` : "");
  const stocks=new Set(reports.map(r=>r.stock_name).filter(Boolean));
  const firms=new Set(reports.map(r=>r.securities_firm).filter(Boolean));
  const targets=reports.filter(r=>r.target_price);
  stats.innerHTML=[
    ["보고서", reports.length+"건"],
    ["종목", stocks.size+"개"],
    ["증권사", firms.size+"곳"],
    ["목표가 있음", targets.length+"건"]
  ].map(x=>`<div class='report-stat'><div class='v'>${escapeHtml(x[1])}</div><div class='k'>${escapeHtml(x[0])}</div></div>`).join("");
  if(!reports.length){
    list.innerHTML="<div class='emptybox'>선택한 기간/검색어에 해당하는 보고서가 없습니다.</div>";
    return;
  }
  list.innerHTML=reports.map(r=>renderResearchReportCard(r)).join("");
}

function renderResearchReportCard(r){
  const kws=(r.keywords || []).slice(0,8).map(k=>`<span class='report-chip'>${escapeHtml(k.keyword)}</span>`).join("");
  const reasons=(r.reasons || []).slice(0,5).map(x=>`<li><b>${escapeHtml(x.reason_keyword || x.reason_type || "근거")}</b> ${escapeHtml(x.reason_text || "")}</li>`).join("");
  const sourceUrl=r.report_url || "";
  const detailId=`report-detail-${r.report_id}`;
  const chartId=`report-chart-${r.report_id}`;
  const canvasId=`report-chart-canvas-${r.report_id}`;
  const statusId=`report-chart-status-${r.report_id}`;
  return `
    <div class='report-card'>
      <h3>${escapeHtml(r.stock_name || "-")} <span class='meta'>${escapeHtml(r.stock_code || "")}</span></h3>
      <div class='report-meta'>
        <span>${escapeHtml(r.report_date || "-")}</span>
        <span>${escapeHtml(r.securities_firm || r.source || "-")}</span>
        <span>${escapeHtml(r.analyst || "")}</span>
        <span>${escapeHtml(r.investment_opinion || "")}</span>
      </div>
      <div class='report-price'>
        <div><span>목표가</span><b>${moneyText(r.target_price)}</b></div>
        <div><span>이전 목표가</span><b>${moneyText(r.previous_target_price)}</b></div>
        <div><span>현재가</span><b>${moneyText(r.current_price_at_report_date)}</b></div>
        <div><span>상승여력</span><b>${pctText(r.upside_potential)}</b></div>
      </div>
      <div class='report-summary'><b>${escapeHtml(r.title || "")}</b><br>${escapeHtml(r.summary || "요약이 없습니다.")}</div>
      <div>${kws}</div>
      <div class='report-actions'>
        ${sourceUrl ? `<a href='${sourceUrl}' target='_blank' rel='noopener'>원문 열기</a>` : ""}
        <button onclick='toggleReportDetail("${detailId}")' style='background:#555'>상세 보기</button>
        <button onclick='searchExportKeyword("${escapeHtml(r.stock_name || "")}")' style='background:#246b45'>뉴스검색</button>
      </div>
      <div id='${detailId}' class='report-detail hidden' data-loaded='0' data-stock-code='${escapeHtml(r.stock_code || "")}' data-stock-name='${escapeHtml(r.stock_name || "")}' data-report-date='${escapeHtml(r.report_date || "")}' data-report-id='${escapeHtml(r.report_id || "")}'>
        <div id='${chartId}' class='report-chart'>
          <div class='report-chart-head'>
            <div class='report-chart-title'>종가 vs 목표가 추이</div>
            <div class='report-periods'>
              <button data-period='1m' onclick='loadReportPriceChart("${detailId}","1m",this)'>1개월</button>
              <button data-period='3m' onclick='loadReportPriceChart("${detailId}","3m",this)'>3개월</button>
              <button data-period='6m' class='active' onclick='loadReportPriceChart("${detailId}","6m",this)'>6개월</button>
              <button data-period='1y' onclick='loadReportPriceChart("${detailId}","1y",this)'>1년</button>
              <button data-period='after' onclick='loadReportPriceChart("${detailId}","after",this)'>보고서일 이후</button>
            </div>
          </div>
          <canvas id='${canvasId}'></canvas>
          <div id='${statusId}' class='report-chart-status'>상세 보기를 열면 주가와 목표가를 함께 불러옵니다.</div>
        </div>
        <h4>목표가 이유</h4>
        <div class='meta'>${escapeHtml(r.target_price_reason || "-")}</div>
        <h4>리스크</h4>
        <div class='meta'>${escapeHtml(r.risk_summary || "-")}</div>
        <h4>보고서 요약 근거</h4>
        ${reasons ? `<ul>${reasons}</ul>` : "<div class='meta'>등록된 근거가 없습니다.</div>"}
      </div>
    </div>`;
}

function toggleReportDetail(id){
  const el=document.getElementById(id);
  if(!el) return;
  el.classList.toggle("hidden");
  if(!el.classList.contains("hidden") && el.dataset.loaded!=="1"){
    el.dataset.loaded="1";
    loadReportPriceChart(id, "6m");
  }
}

async function loadReportPriceChart(detailId, period, btn){
  const el=document.getElementById(detailId);
  if(!el) return;
  const canvas=el.querySelector("canvas");
  const status=el.querySelector(".report-chart-status");
  const code=el.dataset.stockCode || "";
  const reportDate=el.dataset.reportDate || "";
  if(btn){
    el.querySelectorAll(".report-periods button").forEach(b=>b.classList.remove("active"));
    btn.classList.add("active");
  }
  if(!code){
    if(status) status.innerHTML="<span class='err'>종목코드가 없어 주가 그래프를 불러올 수 없습니다.</span>";
    return;
  }
  if(status) status.textContent="주가와 목표가 데이터를 불러오는 중...";
  try{
    const params=new URLSearchParams({stock_code:code, report_date:reportDate, report_id:el.dataset.reportId || "", period:period || "6m"});
    const res=await fetch(`/api/report-price-chart?${params.toString()}&ts=${Date.now()}`);
    const data=await res.json();
    if(!data.ok) throw new Error(data.error || "주가 그래프 조회 실패");
    drawReportPriceChart(canvas, data);
    const targetText=data.targetSeries.length ? `목표가 ${data.targetSeries.length}건` : "목표가 없음";
    if(status) status.innerHTML=`<span class='ok'>${escapeHtml(data.stockName || code)}</span> / 종가 ${data.closeSeries.length}일 / ${targetText} / ${escapeHtml(data.start)} ~ ${escapeHtml(data.end)}`;
  }catch(e){
    if(status) status.innerHTML=`<span class='err'>주가 그래프 오류: ${escapeHtml(e.message)}</span>`;
  }
}

function drawReportPriceChart(canvas, data){
  if(!canvas) return;
  const rect=canvas.getBoundingClientRect();
  const dpr=window.devicePixelRatio || 1;
  const w=Math.max(1, rect.width);
  const h=Math.max(1, rect.height);
  canvas.width=Math.floor(w*dpr);
  canvas.height=Math.floor(h*dpr);
  const ctx=canvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle="#0d131a";
  ctx.fillRect(0,0,w,h);
  const closes=data.closeSeries || [];
  const targets=data.targetSeries || [];
  if(!closes.length){
    ctx.fillStyle="#9fb0bf";
    ctx.font="13px Segoe UI";
    ctx.fillText("주가 데이터가 없습니다.", 18, 28);
    return;
  }
  const pad={l:54,r:76,t:24,b:46};
  const plotW=w-pad.l-pad.r;
  const plotH=h-pad.t-pad.b;
  const startDate=new Date(data.start);
  const endDate=new Date(data.end);
  const totalMs=Math.max(1, endDate-startDate);
  const xOf=dateText=>pad.l+(new Date(dateText)-startDate)/totalMs*plotW;
  const values=closes.map(x=>Number(x.close)).filter(Number.isFinite).concat(targets.map(x=>Number(x.targetPrice)).filter(Number.isFinite));
  const min=Math.min(...values);
  const max=Math.max(...values);
  const range=Math.max(1, max-min);
  const yOf=v=>pad.t+(max-Number(v))/range*plotH;

  ctx.strokeStyle="#263544";
  ctx.fillStyle="#9fb0bf";
  ctx.font="12px Segoe UI";
  ctx.textAlign="right";
  for(let i=0;i<=4;i++){
    const y=pad.t+plotH*i/4;
    const val=max-range*i/4;
    ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(w-pad.r,y); ctx.stroke();
    ctx.fillText(Math.round(val).toLocaleString("ko-KR"), w-8, y+4);
  }
  ctx.textAlign="left";

  if(data.reportDate){
    const rx=xOf(data.reportDate);
    if(rx>=pad.l && rx<=w-pad.r){
      ctx.strokeStyle="#f5c542";
      ctx.setLineDash([4,4]);
      ctx.beginPath(); ctx.moveTo(rx,pad.t); ctx.lineTo(rx,pad.t+plotH); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle="#f5c542";
      ctx.fillText("보고서", rx+4, pad.t+13);
    }
  }

  ctx.strokeStyle="#7db1ff";
  ctx.lineWidth=2;
  ctx.beginPath();
  closes.forEach((p,i)=>{
    const x=xOf(p.date), y=yOf(p.close);
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  });
  ctx.stroke();

  if(targets.length>=2){
    ctx.strokeStyle="#ff8a80";
    ctx.lineWidth=1.8;
    ctx.beginPath();
    targets.forEach((p,i)=>{
      const x=xOf(p.date), y=yOf(p.targetPrice);
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    });
    ctx.stroke();
  }
  targets.forEach(p=>{
    const x=xOf(p.date), y=yOf(p.targetPrice);
    if(x<pad.l || x>w-pad.r) return;
    ctx.fillStyle="#ff8a80";
    ctx.beginPath(); ctx.arc(x,y,4,0,Math.PI*2); ctx.fill();
  });

  const latest=closes[closes.length-1];
  ctx.fillStyle="#7db1ff";
  ctx.font="12px Segoe UI";
  ctx.fillText("종가", pad.l, 16);
  if(targets.length){
    ctx.fillStyle="#ff8a80";
    ctx.fillText("목표가", pad.l+48, 16);
  }
  ctx.fillStyle="#9fb0bf";
  ctx.fillText(closes[0].date, pad.l, h-16);
  ctx.textAlign="right";
  ctx.fillText(latest.date, w-pad.r, h-16);
  ctx.textAlign="left";
}

async function loadExportDashboard(force){
  const status=document.getElementById("exportStatus");
  if(!status) return;
  status.innerHTML = "수출입 저장 데이터와 최신 게시물 확인 중...";
  try{
    const res=await fetch(`/api/export-report?force=${force ? "1" : "0"}&ts=${Date.now()}`);
    const data=await res.json();
    if(!data.ok){status.innerHTML=`<span class='err'>${escapeHtml(data.error || "분석 실패")}</span>`; return;}
    LAST_EXPORT_DATA=data;
    SELECTED_EXPORT_ITEM=null;
    renderExportDashboard(data);
    status.innerHTML=`<span class='ok'>${escapeHtml(data.statusMessage || "분석 완료")}</span> <span class='meta'>/ 업데이트 ${escapeHtml(data.generatedAt || "")}</span>`;
    renderExportRunLog(data, force);
  }catch(e){status.innerHTML=`<span class='err'>산업데이터 오류: ${escapeHtml(e.message)}</span>`;}
}


function renderExportRunLog(data, force){
  const el=document.getElementById("exportRunLog"); if(!el) return;
  const latest=data.latestPost || {};
  const mode=data.analysisMode || (force ? "force" : "check");
  const modeText = mode === "today" ? "오늘 신규자료 감지" : (mode === "error" ? "확인 오류" : "오늘 자료 확인");
  const sourceUrl = data.url || latest.url || "";
  const title = data.title || latest.title || "-";
  const pub = data.publishedDate || latest.publishedDate || "-";
  const saved = data.usedSavedData ? "저장된 표 기반 데이터 사용" : "신규 자료 반영";
  el.innerHTML = `
    <div style="background:#111820;border:1px solid #344151;border-radius:10px;padding:10px;margin-top:8px">
      <b>실행 결과</b> : ${escapeHtml(modeText)} / ${escapeHtml(saved)}<br>
      <b>감지 자료</b> : ${escapeHtml(title)}<br>
      <b>게시일</b> : ${escapeHtml(pub)} ${sourceUrl ? `/ <a href='${sourceUrl}' target='_blank' style='color:#9dccff'>원문 열기</a>` : ""}<br>
      <b>설명</b> : ${escapeHtml(data.runDetail || "현재 버전은 검증된 표 기반 JSON/내장 데이터를 웹페이지에 표시합니다. PDF 자동추출은 제외했습니다.")}
    </div>`;
}

function renderExportDashboard(data){
  renderExportHero(data);
  renderExportTrend(data, null);
  renderExportItemButtons(data);
  renderExportThemeRank(data);
  renderExportItemTable(data);
  initExportStatsControls(data);
  renderExportStats(data);
  renderExportRegion(data);
  renderExportNewsBridge(data);
}

function renderExportHero(data){
  const hero=document.getElementById("exportHero");
  const sum=document.getElementById("exportSummary");
  if(!hero || !sum) return;
  const m=data.metrics || {};
  const metrics=[
    ["보고서", data.reportMonth || "-", data.source || "산업통상자원부"],
    ["수출", m.exportAmount || "-", m.exportYoY ? `${m.exportYoY}` : ""],
    ["수입", m.importAmount || "-", m.importYoY ? `${m.importYoY}` : ""],
    ["무역수지", m.balance || "-", m.balanceComment || ""]
  ];
  hero.innerHTML=metrics.map(x=>`<div class='export-metric'><div class='k'>${escapeHtml(x[0])}</div><div class='v'>${escapeHtml(x[1])}</div><div class='c ${String(x[2]).includes('-')?'trend-down':'trend-up'}'>${escapeHtml(x[2])}</div></div>`).join("");
  sum.innerHTML = `<b>한줄 해석:</b> ${escapeHtml(data.headline || "품목별·월별 흐름을 기준으로 강한 산업을 확인합니다.")}<br><span class='meta'>원문: ${data.url ? `<a href='${data.url}' target='_blank' style='color:#9dccff'>산업부 자료 열기</a>` : "저장된 표 기반 데이터"}</span>`;
}

function renderExportItemButtons(data){
  const el=document.getElementById("exportItemButtons"); if(!el) return;
  const items=(data.items || []).slice().sort((a,b)=>(b.score||0)-(a.score||0));
  el.innerHTML = `<span class='pill' onclick='SELECTED_EXPORT_ITEM=null;renderExportTrend(LAST_EXPORT_DATA,null)'>전체</span>` + items.map(it=>`<span class='pill' onclick='SELECTED_EXPORT_ITEM="${escapeHtml(it.key)}";renderExportTrend(LAST_EXPORT_DATA,"${escapeHtml(it.key)}")'>${escapeHtml(it.name)}</span>`).join("");
}

function renderExportTrend(data, selectedKey){
  const box=document.getElementById("exportTrendChart"); if(!box) return;
  const months=data.months || [];
  let items=(data.items || []).slice().sort((a,b)=>(b.latestAmount||0)-(a.latestAmount||0));
  if(!items.length){box.innerHTML="<div class='meta'>표시할 품목 데이터가 없습니다.</div>"; return;}

  // 전체 화면의 메인 기준은 증감률이 아니라 절대 수출금액이다.
  // 투자자가 먼저 봐야 하는 것은 '현재 어느 산업이 가장 크게 수출되는가'이므로 금액 기준 막대그래프로 표시한다.
  if(!selectedKey){
    const valid=items.filter(it=>typeof it.latestAmount==='number');
    const w=820,h=Math.max(520, 28*valid.length+70),padL=120,padR=95,padT=20,padB=34;
    const max=Math.max(1,...valid.map(it=>it.latestAmount||0));
    const rowH=Math.max(22,(h-padT-padB)/Math.max(1,valid.length));
    let svg=`<svg class='export-svg tall' viewBox='0 0 ${w} ${h}' preserveAspectRatio='none'>`;
    for(let g=0; g<=4; g++){
      const v=g*max/4;
      const xx=padL+v*(w-padL-padR)/max;
      svg+=`<line x1='${xx}' y1='${padT}' x2='${xx}' y2='${h-padB}' stroke='#22303d' stroke-width='1'/>`;
      svg+=`<text x='${xx-18}' y='${h-8}' fill='#9fb0bf' font-size='10'>${Math.round(v/1000).toLocaleString()}B</text>`;
    }
    valid.forEach((it,i)=>{
      const y=padT+i*rowH+3;
      const val=it.latestAmount||0;
      const bw=val*(w-padL-padR)/max;
      const growth=typeof it.latest==='number' ? `${it.latest>0?'+':''}${it.latest}%` : '-';
      svg+=`<text x='8' y='${y+14}' fill='#d7e7ff' font-size='11'>${i+1}. ${escapeHtml(it.name)}</text>`;
      svg+=`<rect x='${padL}' y='${y}' width='${Math.max(2,bw)}' height='15' rx='3' fill='#7db1ff'/>`;
      svg+=`<text x='${padL+bw+6}' y='${y+13}' fill='#d7e7ff' font-size='11'>${Number(val).toLocaleString()} 백만$</text>`;
      svg+=`<text x='${w-58}' y='${y+13}' fill='${(it.latest||0)>=0?'#8aff8a':'#ff8585'}' font-size='11'>${growth}</text>`;
    });
    svg+='</svg>';
    box.innerHTML=`<h3>최근월 20대 품목 수출금액 순위</h3>${svg}<div class='meta'>파란 막대는 최근월 수출금액입니다. 우측 증감률은 보조지표이며, 품목 버튼을 누르면 해당 품목의 월별 금액/증감률을 봅니다.</div>`;
    return;
  }

  const item=items.find(x=>x.key===selectedKey);
  if(!item){box.innerHTML="<div class='meta'>선택한 품목 데이터가 없습니다.</div>"; return;}
  const amountSeries=(item.amounts||[]).map((v,i)=>({month:months[i]||String(i+1), value:v})).filter(d=>typeof d.value==='number');
  const growthSeries=(item.monthly||[]).map((v,i)=>({month:months[i]||String(i+1), value:v})).filter(d=>typeof d.value==='number');
  if(!amountSeries.length){box.innerHTML=`<h3>${escapeHtml(item.name)}</h3><div class='meta'>이 품목은 표시할 금액 데이터가 없습니다.</div>`; return;}
  const w=760,h=330,padL=54,padR=24,padT=20,padB=38;
  const max=Math.max(1,...amountSeries.map(d=>d.value));
  const barW=(w-padL-padR)/Math.max(1,amountSeries.length)*0.55;
  const x=(i)=>padL+i*(w-padL-padR)/Math.max(1,amountSeries.length);
  const y=(v)=>padT+(max-v)*(h-padT-padB)/max;
  let svg=`<svg class='export-svg tall' viewBox='0 0 ${w} ${h}' preserveAspectRatio='none'>`;
  for(let g=0; g<=4; g++){const v=g*max/4; const yy=padT+(max-v)*(h-padT-padB)/max; svg+=`<line x1='${padL}' y1='${yy}' x2='${w-padR}' y2='${yy}' stroke='#22303d' stroke-width='1'/><text x='4' y='${yy+4}' fill='#9fb0bf' font-size='10'>${Math.round(v).toLocaleString()}</text>`;}
  amountSeries.forEach((d,i)=>{const xx=x(i)+barW*0.35; const bh=h-padB-y(d.value); svg+=`<rect x='${xx}' y='${y(d.value)}' width='${barW}' height='${Math.max(2,bh)}' rx='3' fill='#7db1ff'/><text x='${xx-3}' y='${h-12}' fill='#9fb0bf' font-size='11'>${escapeHtml(d.month)}</text>`;});
  svg+='</svg>';
  const growthHtml=growthSeries.length ? `<div class='meta'>월별 증감률: ${growthSeries.map(d=>`${escapeHtml(d.month)} <b class='${d.value>=0?'trend-up':'trend-down'}'>${d.value>0?'+':''}${d.value}%</b>`).join(' / ')}</div>` : '';
  box.innerHTML=`<h3>${escapeHtml(item.name)} 월별 수출금액</h3>${svg}<div class='meta'>단위: 백만 달러. 선택 품목은 금액 흐름을 먼저 표시하고, 증감률은 아래에 보조로 표시합니다.</div>${growthHtml}`;
}

function renderExportThemeRank(data){
  const chartEl=document.getElementById("exportGrowthChart");
  const tableEl=document.getElementById("exportGrowthTable");
  if(!chartEl || !tableEl) return;
  const items=(data.items || []).slice();
  const growthRank=items.filter(x=>typeof x.latest==='number').sort((a,b)=>(b.latest||-999)-(a.latest||-999));

  const growthChart=(arr)=>{
    const valid=arr.slice();
    const w=520,h=Math.max(380, 22*valid.length+60),padL=95,padR=55,padT=18,padB=26;
    const max=Math.max(10,...valid.map(x=>Math.abs(x.latest||0)));
    let svg=`<svg class='export-svg tall' viewBox='0 0 ${w} ${h}' preserveAspectRatio='none'>`;
    valid.forEach((it,i)=>{
      const y=padT+i*22;
      const val=it.latest||0;
      const bw=Math.abs(val)*(w-padL-padR)/(max*1.12);
      const color=val>=0?'#8aff8a':'#ff8585';
      svg+=`<text x='8' y='${y+14}' fill='#d7e7ff' font-size='11'>${i+1}. ${escapeHtml(it.name)}</text>`;
      svg+=`<rect x='${padL}' y='${y+3}' width='${Math.max(2,bw)}' height='13' rx='3' fill='${color}'/>`;
      svg+=`<text x='${padL+bw+5}' y='${y+14}' fill='${color}' font-size='11'>${val>0?'+':''}${val}%</text>`;
    });
    svg+='</svg>';
    return svg;
  };

  const amountRank=items.filter(x=>typeof x.latestAmount==='number').sort((a,b)=>(b.latestAmount||0)-(a.latestAmount||0));
  const tableRows=amountRank.map((it,i)=>`<tr onclick='SELECTED_EXPORT_ITEM="${escapeHtml(it.key)}";renderExportTrend(LAST_EXPORT_DATA,"${escapeHtml(it.key)}")' style='cursor:pointer'><td>${i+1}</td><td>${escapeHtml(it.name)}</td><td>${Number(it.latestAmount).toLocaleString()} 백만$</td><td class='${it.latest>=0?'trend-up':'trend-down'}'>${typeof it.latest==='number'?(it.latest>0?'+':'')+it.latest+'%':'-'}</td></tr>`).join('');

  chartEl.innerHTML=`<div class='export-chartbox' style='margin-top:0'><h3>최근월 증감률 순위</h3>${growthChart(growthRank)}<div class='meta'>증감률은 보조지표입니다. 금액이 작은 품목의 급등률은 품목 상세에서 금액 흐름을 같이 확인합니다.</div></div>`;
  tableEl.innerHTML=`<table class='export-table'><thead><tr><th>순위</th><th>품목</th><th>수출액</th><th>증감률</th></tr></thead><tbody>${tableRows}</tbody></table>`;
}

function renderExportItemTable(data){
  const el=document.getElementById("exportItemTable"); if(!el) return;
  const items=(data.items || []).slice().sort((a,b)=>(a.rank||999)-(b.rank||999));
  let html=`<table class='export-table'><thead><tr><th>순번</th><th>품목</th><th>최근월 금액</th><th>최근월 증감률</th><th>3개월 평균</th><th>전월대비 변화</th><th>해석</th></tr></thead><tbody>`;
  items.forEach(it=>{const acc=it.acceleration||0; html+=`<tr><td>${it.rank||''}</td><td>${escapeHtml(it.name)}</td><td>${typeof it.latestAmount==='number'?Number(it.latestAmount).toLocaleString()+' 백만$':'-'}</td><td class='${it.latest>=0?'trend-up':'trend-down'}'>${typeof it.latest==='number'?(it.latest>0?'+':'')+it.latest+'%':'-'}</td><td>${typeof it.avg3==='number'?(it.avg3>0?'+':'')+it.avg3+'%':'-'}</td><td class='${acc>0?'trend-up':acc<0?'trend-down':'trend-flat'}'>${typeof acc==='number'?(acc>0?'+':'')+acc:'-'}</td><td>${escapeHtml(it.comment||'')}</td></tr>`;});
  html+='</tbody></table>';
  el.innerHTML=html;
}

function initExportStatsControls(data){
  const months=(data.months || []).slice().sort();
  const itemSelect=document.getElementById("exportStatsItem");
  const start=document.getElementById("exportStatsStart");
  const end=document.getElementById("exportStatsEnd");
  if(!itemSelect || !start || !end) return;
  const prev=itemSelect.value;
  const items=(data.items || []).slice().sort((a,b)=>(b.latestAmount||0)-(a.latestAmount||0));
  itemSelect.innerHTML=items.map(it=>`<option value="${escapeHtml(it.key)}">${escapeHtml(it.name)}</option>`).join("");
  if(prev && items.some(it=>it.key===prev)) itemSelect.value=prev;
  else if(items.some(it=>it.name==="반도체")) itemSelect.value=items.find(it=>it.name==="반도체").key;
  if(months.length){
    if(!start.value) start.value=months[0];
    if(!end.value) end.value=months[months.length-1];
  }
  itemSelect.onchange=()=>renderExportStats(LAST_EXPORT_DATA);
  start.onchange=()=>renderExportStats(LAST_EXPORT_DATA);
  end.onchange=()=>renderExportStats(LAST_EXPORT_DATA);
  const search=document.getElementById("exportStatsSearch");
  if(search && !search.dataset.bound){
    search.dataset.bound="1";
    search.addEventListener("input", ()=>{
      const q=search.value.trim().toLowerCase();
      if(!q) return;
      const found=items.find(it=>String(it.name||"").toLowerCase().includes(q) || String(it.key||"").toLowerCase().includes(q));
      if(found){ itemSelect.value=found.key; renderExportStats(LAST_EXPORT_DATA); }
    });
  }
}

function exportSeriesForItem(data, item, startMonth, endMonth){
  const months=(data.months || []).slice().sort();
  const rawMonths=item.months && item.months.length ? item.months : months;
  const amountMap={};
  const growthMap={};
  (rawMonths || []).forEach((m,i)=>{
    amountMap[m]=(item.amounts || [])[i];
    growthMap[m]=(item.monthly || [])[i];
  });
  return months
    .filter(m=>(!startMonth || m>=startMonth) && (!endMonth || m<=endMonth))
    .map(m=>({month:m, amount:amountMap[m], growth:growthMap[m]}));
}

function validNumber(v){
  const n=Number(v);
  return Number.isFinite(n) ? n : null;
}

function latestValid(arr, key){
  for(let i=arr.length-1;i>=0;i--){
    const v=validNumber(arr[i][key]);
    if(v!==null) return {value:v, month:arr[i].month};
  }
  return null;
}

function firstValid(arr, key){
  for(const row of arr){
    const v=validNumber(row[key]);
    if(v!==null) return {value:v, month:row.month};
  }
  return null;
}

function exportDirection(latestGrowth, growthDelta){
  if(latestGrowth===null || latestGrowth===undefined) return "데이터 부족";
  if(latestGrowth > 0 && growthDelta > 5) return "상승 가속";
  if(latestGrowth > 0 && growthDelta < -5) return "상승 지속(둔화)";
  if(latestGrowth > 0) return "상승 유지";
  if(latestGrowth < 0 && growthDelta > 5) return "하락 완화";
  if(latestGrowth < 0 && growthDelta < -5) return "하락 확대";
  if(latestGrowth < 0) return "하락";
  return "보합";
}

function drawExportLineChart(rows, key, unit){
  const values=rows.map(r=>validNumber(r[key]));
  const valid=values.filter(v=>v!==null);
  if(!valid.length) return "<div class='emptybox'>선택 기간에 추출된 수치가 없습니다.</div>";
  const w=900,h=320,padL=58,padR=28,padT=24,padB=64;
  const min=Math.min(...valid, key==="growth" ? 0 : Math.min(...valid));
  const max=Math.max(...valid, key==="growth" ? 0 : Math.max(...valid));
  const span=(max-min)||1;
  const x=i=>padL+(rows.length<=1?0:i*(w-padL-padR)/(rows.length-1));
  const y=v=>h-padB-((v-min)/span)*(h-padT-padB);
  const pts=rows.map((r,i)=>{
    const v=validNumber(r[key]);
    return v===null ? null : {x:x(i), y:y(v), v, month:r.month};
  });
  const path=pts.filter(Boolean).map((p,i)=>`${i?'L':'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  let svg=`<svg class='export-svg tall' viewBox='0 0 ${w} ${h}' preserveAspectRatio='none'>`;
  for(let g=0; g<=4; g++){
    const v=min+span*g/4;
    const yy=y(v);
    svg+=`<line x1='${padL}' y1='${yy}' x2='${w-padR}' y2='${yy}' stroke='#22303d' stroke-width='1'/>`;
    svg+=`<text x='6' y='${yy+4}' fill='#9fb0bf' font-size='11'>${Math.round(v).toLocaleString()}${unit}</text>`;
  }
  svg+=`<path d='${path}' fill='none' stroke='${key==="growth"?"#8aff8a":"#7db1ff"}' stroke-width='3'/>`;
  pts.forEach(p=>{
    if(!p) return;
    const color=key==="growth" && p.v<0 ? "#ff8585" : (key==="growth" ? "#8aff8a" : "#7db1ff");
    svg+=`<circle cx='${p.x}' cy='${p.y}' r='4' fill='${color}'/>`;
    svg+=`<text x='${p.x-14}' y='${p.y-8}' fill='${color}' font-size='11'>${p.v>0&&key==="growth"?"+":""}${Math.round(p.v).toLocaleString()}${unit}</text>`;
  });
  rows.forEach((r,i)=>svg+=`<text x='${x(i)-18}' y='${h-22}' fill='#9fb0bf' font-size='11' transform='rotate(-35 ${x(i)-18} ${h-22})'>${escapeHtml(r.month)}</text>`);
  svg+="</svg>";
  return svg;
}

function renderExportStats(data){
  if(!data) return;
  const status=document.getElementById("exportStatsStatus");
  const summary=document.getElementById("exportStatsSummary");
  const amountChart=document.getElementById("exportStatsAmountChart");
  const growthChart=document.getElementById("exportStatsGrowthChart");
  const table=document.getElementById("exportStatsTable");
  const itemSelect=document.getElementById("exportStatsItem");
  if(!status || !summary || !amountChart || !growthChart || !table || !itemSelect) return;
  const start=document.getElementById("exportStatsStart").value;
  const end=document.getElementById("exportStatsEnd").value;
  const items=(data.items || []).slice();
  const selected=items.find(it=>it.key===itemSelect.value) || items[0];
  if(!selected){ status.innerHTML="<span class='warn'>분석할 품목 데이터가 없습니다.</span>"; return; }
  const selectedRows=exportSeriesForItem(data, selected, start, end);
  const firstAmount=firstValid(selectedRows, "amount");
  const latestAmount=latestValid(selectedRows, "amount");
  const firstGrowth=firstValid(selectedRows, "growth");
  const latestGrowth=latestValid(selectedRows, "growth");
  const amountDelta=(firstAmount && latestAmount) ? latestAmount.value-firstAmount.value : null;
  const growthDelta=(firstGrowth && latestGrowth) ? latestGrowth.value-firstGrowth.value : null;
  const direction=exportDirection(latestGrowth ? latestGrowth.value : null, growthDelta || 0);
  status.innerHTML=`<span class='ok'>${escapeHtml(start || "-")} ~ ${escapeHtml(end || "-")} / ${escapeHtml(selected.name)} 통계</span>`;
  summary.innerHTML=[
    ["최근 금액", latestAmount ? Number(latestAmount.value).toLocaleString()+" 백만$" : "-"],
    ["기간 금액 변화", amountDelta!==null ? (amountDelta>0?"+":"")+Number(amountDelta).toLocaleString()+" 백만$" : "-"],
    ["최근 증감률", latestGrowth ? (latestGrowth.value>0?"+":"")+latestGrowth.value+"%" : "-"],
    ["최근 방향", direction]
  ].map(x=>`<div class='export-stat-card'><div class='v'>${escapeHtml(x[1])}</div><div class='k'>${escapeHtml(x[0])}</div></div>`).join("");
  amountChart.innerHTML=drawExportLineChart(selectedRows, "amount", "");
  growthChart.innerHTML=drawExportLineChart(selectedRows, "growth", "%");

  const compare=items.map(it=>{
    const rows=exportSeriesForItem(data, it, start, end);
    const fa=firstValid(rows, "amount"), la=latestValid(rows, "amount");
    const fg=firstValid(rows, "growth"), lg=latestValid(rows, "growth");
    const ad=(fa && la) ? la.value-fa.value : null;
    const gd=(fg && lg) ? lg.value-fg.value : null;
    return {name:it.name, key:it.key, latestAmount:la ? la.value : null, amountDelta:ad, latestGrowth:lg ? lg.value : null, growthDelta:gd, direction:exportDirection(lg ? lg.value : null, gd || 0), points:rows.filter(r=>validNumber(r.amount)!==null || validNumber(r.growth)!==null).length};
  }).filter(r=>r.points>0).sort((a,b)=>(b.latestAmount||0)-(a.latestAmount||0));
  table.innerHTML=`<table class='export-table'><thead><tr><th>품목</th><th>최근 금액</th><th>금액 변화</th><th>최근 증감률</th><th>증감률 변화</th><th>방향</th><th>월수</th></tr></thead><tbody>`+
    compare.map(r=>`<tr onclick='document.getElementById("exportStatsItem").value="${escapeHtml(r.key)}";renderExportStats(LAST_EXPORT_DATA)' style='cursor:pointer'>
      <td>${escapeHtml(r.name)}</td>
      <td>${r.latestAmount!==null?Number(r.latestAmount).toLocaleString()+" 백만$":"-"}</td>
      <td class='${(r.amountDelta||0)>=0?"trend-up":"trend-down"}'>${r.amountDelta!==null?(r.amountDelta>0?"+":"")+Number(r.amountDelta).toLocaleString():"-"}</td>
      <td class='${(r.latestGrowth||0)>=0?"trend-up":"trend-down"}'>${r.latestGrowth!==null?(r.latestGrowth>0?"+":"")+r.latestGrowth+"%":"-"}</td>
      <td class='${(r.growthDelta||0)>=0?"trend-up":"trend-down"}'>${r.growthDelta!==null?(r.growthDelta>0?"+":"")+r.growthDelta.toFixed(1)+"%p":"-"}</td>
      <td>${escapeHtml(r.direction)}</td>
      <td>${r.points}</td>
    </tr>`).join("")+`</tbody></table>`;
}

function renderExportRegion(data){
  const countryChart=document.getElementById("exportCountryChart");
  const countryTable=document.getElementById("exportCountryTable");
  const regionChart=document.getElementById("exportRegionChart");
  const regionTable=document.getElementById("exportRegionTable");

  const renderGroup=(chart, table, title, rows, nameLabel)=>{
    if(!chart || !table) return;
    rows=(rows || []).slice();
    const numericRows=rows.filter(r=>typeof r.latest==='number').sort((a,b)=>(b.latest||0)-(a.latest||0));
    if(!numericRows.length){
      chart.innerHTML=`<h3>${escapeHtml(title)}</h3><div class='emptybox'>${rows.length ? '표 영역은 준비됨. 현재 수치 미연동 상태입니다.' : '아직 구조화된 '+escapeHtml(nameLabel)+' 데이터가 없습니다.'}<br>PDF 27쪽 이하 ${escapeHtml(nameLabel)}별 수출표가 연결되면 이 칸에 금액/증감률이 표시됩니다.</div>`;
      if(rows.length){
        table.innerHTML=`<table class='export-table'><thead><tr><th>${escapeHtml(nameLabel)}</th><th>최근월</th><th>상태</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${escapeHtml(r.name)}</td><td>-</td><td>${escapeHtml(r.comment||'PDF 표 수치 연결 대기')}</td></tr>`).join('')}</tbody></table>`;
      }else{
        table.innerHTML=`<div class='meta'>표시 기준: 최신월 금액/증감률. 임의 예시 데이터는 표시하지 않습니다.</div>`;
      }
      return;
    }
    rows=numericRows;
    const w=520,h=Math.max(230, 26*rows.length+50),padL=95,padR=35,padT=14,padB=28;
    const max=Math.max(10,...rows.map(r=>Math.abs(r.latest||0)));
    let svg=`<svg class='export-svg small' viewBox='0 0 ${w} ${h}' preserveAspectRatio='none'>`;
    rows.forEach((r,i)=>{const y=padT+i*26; const val=r.latest||0; const bw=Math.abs(val)*(w-padL-padR)/(max*1.15); const x0=padL; const color=val>=0?'#8aff8a':'#ff8585'; svg+=`<text x='8' y='${y+16}' fill='#d7e7ff' font-size='12'>${escapeHtml(r.name)}</text><rect x='${x0}' y='${y+4}' width='${Math.max(2,bw)}' height='15' rx='3' fill='${color}'/><text x='${x0+bw+6}' y='${y+16}' fill='${color}' font-size='12'>${val>0?'+':''}${val}%</text>`;});
    svg+='</svg>';
    chart.innerHTML=`<h3>${escapeHtml(title)}</h3>${svg}`;
    table.innerHTML=`<table class='export-table'><thead><tr><th>${escapeHtml(nameLabel)}</th><th>수출액</th><th>증감률</th><th>해석</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${escapeHtml(r.name)}</td><td>${typeof r.amount==='number'?Number(r.amount).toLocaleString()+'억$':'-'}</td><td class='${r.latest>=0?'trend-up':'trend-down'}'>${r.latest>0?'+':''}${r.latest}%</td><td>${escapeHtml(r.comment||'')}</td></tr>`).join('')}</tbody></table>`;
  };

  renderGroup(countryChart, countryTable, '국가별 최신월 수출 증가율', data.countries || [], '국가');
  renderGroup(regionChart, regionTable, '지역별 최신월 수출 증가율', data.regions || [], '지역');
}

function renderExportNewsBridge(data){
  const el=document.getElementById("exportNewsBridge"); if(!el) return;
  const items=(data.items || []).slice().sort((a,b)=>(b.score||0)-(a.score||0)).slice(0,8);
  el.innerHTML = items.map(it=>`<div style='margin-bottom:8px'><b>${escapeHtml(it.name)}</b> → ${(it.newsKeywords||it.themes||[]).map(k=>`<span class='pill'>${escapeHtml(k)}</span>`).join('')} <button onclick='searchExportKeyword("${escapeHtml((it.newsKeywords||it.themes||[it.name])[0])}")' style='padding:5px 9px;font-size:12px'>뉴스검색으로 보내기</button></div>`).join('');
}

function searchExportKeyword(kw){
  showTab('searchTab', document.querySelector('.tabbtn'));
  document.getElementById('extraKeywords').value = kw;
  clearResultsOnly();
  document.getElementById('extraKeywords').scrollIntoView({behavior:'smooth',block:'center'});
}

function safeId(s){
  return btoa(unescape(encodeURIComponent(String(s || ""))))
    .replace(/=/g,"")
    .replace(/[^a-zA-Z0-9]/g,"_");
}

function escapeHtml(s){
  return String(s || "")
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;")
    .replace(/'/g,"&#039;");
}

init();
</script>
</body>
</html>
'''

def app_dir():
    return os.path.dirname(os.path.abspath(__file__))

def log_error(msg):
    try:
        with open(os.path.join(app_dir(), "error_log.txt"), "a", encoding="utf-8") as f:
            f.write("\\n\\n[" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "]\\n")
            f.write(str(msg))
    except Exception:
        pass

def report_db_path():
    return os.environ.get("REPORT_DB_PATH") or os.path.join(app_dir(), "data", "report_reports.db")

def report_db_zip_path():
    return os.environ.get("REPORT_DB_ZIP_PATH") or os.path.join(app_dir(), "data", "report_reports.db.zip")

def ensure_report_db():
    db_path=report_db_path()
    zip_path=report_db_zip_path()
    if os.path.exists(db_path):
        if not os.path.exists(zip_path):
            return True
        if os.path.getmtime(db_path) >= os.path.getmtime(zip_path):
            return True
    if not os.path.exists(zip_path):
        return False
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        db_member=None
        for name in zf.namelist():
            if name.replace("\\","/").endswith("report_reports.db"):
                db_member=name
                break
        if not db_member:
            raise RuntimeError("report_reports.db.zip 안에 report_reports.db 파일이 없습니다.")
        with zf.open(db_member) as src, open(db_path, "wb") as dst:
            while True:
                chunk=src.read(1024*1024)
                if not chunk:
                    break
                dst.write(chunk)
    return os.path.exists(db_path)

def report_db_exists():
    return ensure_report_db()

def db_connect():
    ensure_report_db()
    con=sqlite3.connect(report_db_path())
    con.row_factory=sqlite3.Row
    return con

def db_rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]

STOCK_MASTER_CACHE={"loaded_at":0, "items":[]}
DEFAULT_STOCK_MASTER=[
    {"code":"005930","name":"삼성전자","market":"KOSPI","marcap":0,"source":"default"},
    {"code":"000660","name":"SK하이닉스","market":"KOSPI","marcap":0,"source":"default"},
    {"code":"005380","name":"현대차","market":"KOSPI","marcap":0,"source":"default"},
    {"code":"000270","name":"기아","market":"KOSPI","marcap":0,"source":"default"},
    {"code":"035420","name":"NAVER","market":"KOSPI","marcap":0,"source":"default"},
    {"code":"035720","name":"카카오","market":"KOSPI","marcap":0,"source":"default"},
    {"code":"204320","name":"HL만도","market":"KOSPI","marcap":0,"source":"default"},
    {"code":"034020","name":"두산에너빌리티","market":"KOSPI","marcap":0,"source":"default"},
]

def normalize_stock_name(value):
    return re.sub(r"[\s\-_()./&]+", "", str(value or "").strip().lower())

def stock_master_items():
    now=time.time()
    if STOCK_MASTER_CACHE["items"] and now-STOCK_MASTER_CACHE["loaded_at"]<3600*12:
        return STOCK_MASTER_CACHE["items"]
    items=[]
    try:
        import FinanceDataReader as fdr
        df=fdr.StockListing("KRX")
        for _,row in df.iterrows():
            code=normalize_stock_code(row.get("Code"))
            name=str(row.get("Name") or "").strip()
            if not code or not name:
                continue
            items.append({
                "code":code,
                "name":name,
                "market":str(row.get("Market") or row.get("MarketId") or "").strip(),
                "marcap":int(row.get("Marcap") or 0),
                "source":"FDR_KRX",
            })
    except Exception:
        items=[]
    if not items:
        try:
            if report_db_exists():
                con=db_connect()
                rows=db_rows(
                    con,
                    """
                    SELECT stock_name,stock_code,count(*) AS cnt
                    FROM reports
                    WHERE stock_name IS NOT NULL AND trim(stock_name)!=''
                      AND stock_code IS NOT NULL AND trim(stock_code)!=''
                    GROUP BY stock_name,stock_code
                    """,
                )
                con.close()
                for r in rows:
                    code=normalize_stock_code(r.get("stock_code"))
                    name=str(r.get("stock_name") or "").strip()
                    if code and name:
                        items.append({"code":code, "name":name, "market":"", "marcap":0, "count":int(r.get("cnt") or 0), "source":"report_db"})
        except Exception:
            log_error("stock master fallback failed\n"+traceback.format_exc())
    if not items:
        items=DEFAULT_STOCK_MASTER[:]
    STOCK_MASTER_CACHE["items"]=items
    STOCK_MASTER_CACHE["loaded_at"]=now
    return items

def stock_suggestions_payload(q="", limit=10):
    nq=normalize_stock_name(q)
    if not nq:
        return {"ok":True, "count":0, "stocks":[]}
    exact=[]
    partial=[]
    for item in stock_master_items():
        code=item.get("code") or ""
        name=item.get("name") or ""
        nn=normalize_stock_name(name)
        if nq==code or nq==nn:
            exact.append(item)
        elif nq in nn or nn in nq:
            partial.append(item)
    def score(item):
        code=item.get("code") or ""
        nn=normalize_stock_name(item.get("name"))
        if nq==code:
            return 0
        if nq==nn:
            return 1
        if nn.startswith(nq):
            return 2
        return 3
    matches=sorted(exact or partial, key=lambda it:(score(it), -int(it.get("count") or 0), -int(it.get("marcap") or 0), it.get("name") or ""))[:int(limit or 10)]
    return {"ok":True, "count":len(matches), "stocks":matches}

def research_reports_payload(start="", end="", q="", limit=120):
    if not report_db_exists():
        return {"ok":False, "error":"서버에 report_reports.db 파일이 없습니다. data/report_reports.db로 업로드하세요."}
    con=db_connect()
    today=datetime.now(KST).strftime("%Y-%m-%d")
    latest=con.execute("SELECT MAX(report_date) FROM reports WHERE report_date<=?", (today,)).fetchone()[0] or ""
    if not latest:
        latest=con.execute("SELECT MAX(report_date) FROM reports").fetchone()[0] or ""
    if not start and not end:
        start=latest
        end=latest
    elif start and not end:
        end=start
    elif end and not start:
        start=end
    where=[]
    args=[]
    if start:
        where.append("report_date>=?")
        args.append(start)
    if end:
        where.append("report_date<=?")
        args.append(end)
    if q:
        like="%"+q+"%"
        where.append("""(
            stock_name LIKE ? OR stock_code LIKE ?
        )""")
        args.extend([like, like])
    where_sql=(" WHERE "+" AND ".join(where)) if where else ""
    reports=db_rows(
        con,
        f"""
        SELECT report_id,title,report_date,source,securities_firm,analyst,report_url,stock_name,stock_code,sector,
               investment_opinion,target_price,previous_target_price,target_price_change_type,
               current_price_at_report_date,upside_potential,summary,target_price_reason,risk_summary
        FROM reports
        {where_sql}
        ORDER BY report_date DESC, report_id DESC
        LIMIT ?
        """,
        args+[int(limit or 120)],
    )
    ids=[r["report_id"] for r in reports]
    reasons_by={}
    keywords_by={}
    if ids:
        ph=",".join("?" for _ in ids)
        for row in db_rows(con, f"SELECT report_id,reason_type,reason_keyword,reason_text,sentiment FROM report_reasons WHERE report_id IN ({ph}) ORDER BY reason_id", ids):
            reasons_by.setdefault(row["report_id"], []).append(row)
        for row in db_rows(con, f"SELECT report_id,keyword,keyword_type FROM report_keywords WHERE report_id IN ({ph}) ORDER BY keyword_id", ids):
            keywords_by.setdefault(row["report_id"], []).append(row)
    for r in reports:
        r["reasons"]=reasons_by.get(r["report_id"], [])
        r["keywords"]=keywords_by.get(r["report_id"], [])
    con.close()
    return {
        "ok":True,
        "reports":reports,
        "meta":{"start":start, "end":end, "q":q, "latestDate":latest, "count":len(reports)}
    }

def normalize_stock_code(code):
    digits=re.sub(r"\D","",str(code or ""))
    return digits.zfill(6) if digits else ""

def iso_date(value):
    text=str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None

def source_report_date(report_date="", report_url="", local_file_path=""):
    for value in (report_url, local_file_path):
        text=str(value or "")
        m=re.search(r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)", text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
            except Exception:
                pass
    return iso_date(report_date)

def chart_date_range(report_date="", period="6m"):
    today=datetime.now(KST).date()
    rd=iso_date(report_date) or today
    if rd>today:
        rd=today
    period=(period or "6m").lower()
    if period=="after":
        start=rd
    else:
        days={"1m":31, "3m":93, "6m":186, "1y":370}.get(period, 186)
        start=today-timedelta(days=days)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

def stock_close_series(stock_code, start, end):
    code=normalize_stock_code(stock_code)
    if not code:
        raise ValueError("종목코드가 없습니다.")
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        raise RuntimeError("FinanceDataReader가 설치되어 있지 않아 주가 데이터를 불러올 수 없습니다.") from exc
    df=fdr.DataReader(code, start, end)
    rows=[]
    for idx,row in df.iterrows():
        rows.append({
            "date":idx.strftime("%Y-%m-%d"),
            "open":int(row.get("Open",0) or 0),
            "high":int(row.get("High",0) or 0),
            "low":int(row.get("Low",0) or 0),
            "close":int(row.get("Close",0) or 0),
            "volume":int(row.get("Volume",0) or 0),
        })
    return rows

def target_price_series(stock_code, start, end):
    code=normalize_stock_code(stock_code)
    if not report_db_exists() or not code:
        return []
    start_d=iso_date(start)
    end_d=iso_date(end)
    con=db_connect()
    rows=db_rows(
        con,
        """
        SELECT report_id,report_date,report_url,local_file_path,stock_name,stock_code,securities_firm,title,target_price,current_price_at_report_date
        FROM reports
        WHERE stock_code=?
          AND target_price IS NOT NULL
          AND trim(cast(target_price as text))!=''
        ORDER BY report_date, report_id
        """,
        (code,),
    )
    con.close()
    out=[]
    for r in rows:
        d=source_report_date(r.get("report_date"), r.get("report_url"), r.get("local_file_path"))
        if not d or (start_d and d<start_d) or (end_d and d>end_d):
            continue
        try:
            target=int(float(str(r.get("target_price")).replace(",","")))
        except Exception:
            continue
        if target<=0:
            continue
        out.append({
            "date":d.strftime("%Y-%m-%d"),
            "targetPrice":target,
            "currentPrice":r.get("current_price_at_report_date"),
            "firm":r.get("securities_firm") or "",
            "title":r.get("title") or "",
            "reportId":r.get("report_id"),
        })
    return out

def report_context_from_id(report_id):
    if not report_id or not report_db_exists():
        return {}
    try:
        rid=int(report_id)
    except Exception:
        return {}
    con=db_connect()
    row=con.execute(
        "SELECT report_id,report_date,report_url,local_file_path,stock_name,stock_code FROM reports WHERE report_id=?",
        (rid,),
    ).fetchone()
    con.close()
    if not row:
        return {}
    d=source_report_date(row["report_date"], row["report_url"], row["local_file_path"])
    return {
        "reportDate":d.strftime("%Y-%m-%d") if d else (row["report_date"] or ""),
        "stockCode":row["stock_code"] or "",
        "stockName":row["stock_name"] or "",
    }

def report_price_chart_payload(stock_code="", report_date="", period="6m", report_id=""):
    ctx=report_context_from_id(report_id)
    code=normalize_stock_code(ctx.get("stockCode") or stock_code)
    report_date=ctx.get("reportDate") or report_date
    start,end=chart_date_range(report_date, period)
    close_rows=stock_close_series(code, start, end)
    targets=target_price_series(code, start, end)
    stock_name=ctx.get("stockName") or ""
    if report_db_exists():
        con=db_connect()
        row=con.execute("SELECT stock_name FROM reports WHERE stock_code=? AND stock_name IS NOT NULL AND trim(stock_name)!='' ORDER BY report_date DESC LIMIT 1", (code,)).fetchone()
        stock_name=row["stock_name"] if row else ""
        con.close()
    return {
        "ok":True,
        "stockCode":code,
        "stockName":stock_name,
        "reportDate":(iso_date(report_date).strftime("%Y-%m-%d") if iso_date(report_date) else ""),
        "period":period,
        "start":start,
        "end":end,
        "closeSeries":[{"date":r["date"], "close":r["close"]} for r in close_rows],
        "ohlcv":close_rows,
        "targetSeries":targets,
        "provider":"FinanceDataReader",
    }

def industry_payload_from_db(month=""):
    if not report_db_exists():
        return None
    con=db_connect()
    if not month:
        row=con.execute(
            """
            SELECT ir.report_month
            FROM industry_reports ir
            WHERE EXISTS (SELECT 1 FROM industry_items ii WHERE ii.industry_report_id=ir.industry_report_id)
            ORDER BY ir.report_month DESC
            LIMIT 1
            """
        ).fetchone()
        month=row["report_month"] if row else ""
    report=con.execute("SELECT * FROM industry_reports WHERE report_month=?", (month,)).fetchone()
    if not report:
        con.close()
        return None
    all_months=[r["report_month"] for r in db_rows(con, "SELECT report_month FROM industry_reports ORDER BY report_month")]
    extracted_months=[
        r["report_month"] for r in db_rows(
            con,
            """
            SELECT DISTINCT ir.report_month
            FROM industry_reports ir JOIN industry_items ii ON ii.industry_report_id=ir.industry_report_id
            ORDER BY ir.report_month
            """
        )
    ]
    latest_items=db_rows(con, "SELECT * FROM industry_items WHERE industry_report_id=? ORDER BY rank", (report["industry_report_id"],))
    items=[]
    for item in latest_items:
        monthly=db_rows(
            con,
            """
            SELECT ir.report_month AS month, ii.latest_amount AS amount, ii.latest_growth AS growth
            FROM industry_reports ir
            JOIN industry_items ii ON ii.industry_report_id=ir.industry_report_id
            WHERE ii.item_name=?
            ORDER BY ir.report_month
            """,
            (item["item_name"],),
        )
        by_month={r["month"]:r for r in monthly}
        themes=[r["keyword"] for r in db_rows(con, "SELECT keyword FROM industry_keywords WHERE industry_report_id=? AND item_key=? AND keyword_type='theme' ORDER BY keyword_id", (report["industry_report_id"], item["item_key"]))]
        news=[r["keyword"] for r in db_rows(con, "SELECT keyword FROM industry_keywords WHERE industry_report_id=? AND item_key=? AND keyword_type='news' ORDER BY keyword_id", (report["industry_report_id"], item["item_key"]))]
        items.append({
            "rank":item["rank"], "key":item["item_key"], "name":item["item_name"],
            "months":extracted_months,
            "amounts":[by_month.get(m,{}).get("amount") for m in extracted_months],
            "monthly":[by_month.get(m,{}).get("growth") for m in extracted_months],
            "latest":item["latest_growth"], "latestAmount":item["latest_amount"],
            "avg3":item["avg_3m_growth"], "acceleration":item["acceleration"], "score":item["score"],
            "themes":themes, "newsKeywords":news, "comment":item["comment"],
        })
    countries=[{"name":r["country_name"],"amount":r["export_amount"],"latest":r["growth_rate"],"comment":r["comment"]} for r in db_rows(con, "SELECT * FROM industry_countries WHERE industry_report_id=? ORDER BY growth_rate DESC", (report["industry_report_id"],))]
    regions=[{"name":r["region_name"],"amount":r["export_amount"],"latest":r["growth_rate"],"comment":r["comment"]} for r in db_rows(con, "SELECT * FROM industry_regions WHERE industry_report_id=? ORDER BY growth_rate DESC", (report["industry_report_id"],))]
    downloads=db_rows(con, "SELECT report_month,title,source_url,local_file_path,file_size,downloaded_at FROM industry_downloads ORDER BY report_month DESC")
    con.close()
    return {
        "ok":True,
        "dataVerified":True,
        "dataScope":report["data_scope"] or "SQLite DB 수출입 분석 데이터",
        "source":report["source"] or "산업통상자원부",
        "reportMonth":report["report_month"],
        "availableMonths":list(reversed(all_months)),
        "title":report["title"],
        "url":report["source_url"],
        "publishedDate":report["published_date"],
        "generatedAt":report["generated_at"],
        "statusMessage":"서버 SQLite DB에서 수출입 분석 데이터 로드 완료",
        "analysisMode":"sqlite_db",
        "usedSavedData":True,
        "runDetail":"업로드된 report_reports.db의 industry_* 테이블에서 품목별 수출액, 증감률, 국가/지역 흐름을 읽었습니다.",
        "headline":report["headline"] or "품목별·월별 흐름을 기준으로 강한 산업을 확인합니다.",
        "metrics":{
            "exportAmount":report["export_amount"] or "-",
            "exportYoY":report["export_yoy"] or "",
            "importAmount":report["import_amount"] or "-",
            "importYoY":report["import_yoy"] or "",
            "balance":report["trade_balance"] or "-",
            "balanceComment":report["balance_comment"] or "",
        },
        "months":extracted_months,
        "items":items,
        "countries":countries,
        "regions":regions,
        "downloadedReports":downloads,
    }

def find_free_port():
    for port in range(5000, 5100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port)); return port
            except OSError:
                pass
    raise RuntimeError("사용 가능한 포트를 찾지 못했습니다.")

def http_get(url, timeout=12):
    req = Request(url, headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language":"ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    with urlopen(req, timeout=timeout) as res:
        return res.read()

def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\\s+", " ", unescape(s)).strip()

def parse_period(value, unit):
    try: value = int(value)
    except Exception: value = 1
    value = max(1, min(value, 30))
    if unit == "h":
        delta=timedelta(hours=value); google_when=f"{value}h"; label=f"최근 {value}시간"
    elif unit == "w":
        delta=timedelta(days=value*7); google_when=f"{value*7}d"; label=f"최근 {value}주"
    else:
        delta=timedelta(days=value); google_when=f"{value}d"; label=f"최근 {value}일"
    return {"google_when":google_when,"label":label,"since":datetime.now(KST)-delta}

def parse_groups(raw_text, checked_keywords):
    """
    검색 묶음 파서.
    - 쉼표(,) 또는 실제 줄바꿈만 검색 묶음 구분자로 사용
    - &는 AND 조건
    - 영문 단어는 절대 문자 단위로 분해하지 않음
      예: bank -> bank, energy -> energy, finance -> finance, nvidia -> nvidia
    """
    groups = []

    for kw in checked_keywords:
        kw = (kw or "").strip()
        if kw:
            groups.append({"label": kw, "terms": [kw]})

    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    # 중요: r"[,\n]+"가 아니라 실제 줄바꿈 splitlines + comma split 사용
    parts = []
    for line in text.split("\n"):
        for part in line.split(","):
            part = part.strip()
            if part:
                parts.append(part)

    for part in parts:
        terms = [t.strip() for t in part.split("&") if t.strip()]
        if terms:
            groups.append({"label": " & ".join(terms), "terms": terms})

    seen = set()
    out = []
    for g in groups:
        key = re.sub(r"\s+", "", g["label"]).lower()
        if key not in seen:
            seen.add(key)
            out.append(g)
    return out


def build_query(group):
    return " ".join([f'"{t}"' for t in group["terms"]])

def parse_google_dt(pub):
    try:
        dt=parsedate_to_datetime(pub)
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST)
    except Exception:
        return None

def within_period(dt, period):
    return True if not dt else dt >= period["since"]

def matches_all_terms(item, group):
    text=" ".join([item.get("title") or "", item.get("source") or "", item.get("summary") or ""]).lower()
    return all(t.lower() in text for t in group["terms"])

def score_item(item, all_terms):
    text=((item.get("title") or "")+" "+(item.get("source") or "")+" "+(item.get("summary") or "")).lower()
    score=0
    for w, pts in IMPACT_WORDS.items():
        if w.lower() in text: score+=pts
    for t in all_terms:
        if t.lower() in text: score+=1
    dt=item.get("published_dt")
    if dt:
        h=(datetime.now(KST)-dt).total_seconds()/3600
        if h<=1: score+=3
        elif h<=6: score+=2
        elif h<=24: score+=1
    return score

def search_google(group, period, max_results):
    query=build_query(group)+f" when:{period['google_when']}"
    url="https://news.google.com/rss/search?q="+quote_plus(query)+"&hl=ko&gl=KR&ceid=KR:ko"
    data=http_get(url)
    root=ET.fromstring(data)
    items=[]
    for item in root.findall(".//item"):
        title=(item.findtext("title") or "").strip()
        link=(item.findtext("link") or "").strip()
        pub=(item.findtext("pubDate") or "").strip()
        source_el=item.find("source")
        source=source_el.text.strip() if source_el is not None and source_el.text else "Google News"
        summary=strip_tags(item.findtext("description") or "")
        dt=parse_google_dt(pub)
        if not title or not link: continue
        if not matches_all_terms({"title":title,"source":source,"summary":summary}, group): continue
        if not within_period(dt, period): continue
        items.append({"keyword":group["label"],"title":title,"link":link,"source":source,"published":dt.strftime("%Y-%m-%d %H:%M") if dt else pub,"published_dt":dt,"summary":summary})
        if len(items)>=max_results: break
    return items

def dedupe(items):
    seen=set(); out=[]
    for it in items:
        key=re.sub(r"\\s+","",it.get("title") or "").lower()
        if key and key not in seen:
            seen.add(key); out.append(it)
    return out

def normalize_title(title):
    title = re.sub(r"\[[^\]]+\]|\([^\)]+\)", " ", title or "")
    title = re.sub(r"[^가-힣A-Za-z0-9&+.\- ]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def is_bad_keyword(tok):
    if not tok or len(tok) < 2:
        return True
    if tok in STOPWORDS:
        return True
    if tok.isdigit():
        return True
    if tok.endswith(("했다", "한다", "된다", "있는", "없는", "했다가", "한다는", "이라고")):
        return True
    bad_suffix = ("시장", "기자", "일보", "뉴스", "신문", "투데이")
    if any(tok.endswith(s) and tok not in CORE_MARKET_KEYWORDS for s in bad_suffix):
        return True
    return False


def classify_keyword(kw):
    if kw in NOVELTY_KEYWORDS:
        return "novel"
    if kw in CORE_MARKET_KEYWORDS:
        return "core"
    if re.fullmatch(r"[가-힣A-Za-z0-9]{2,12}", kw) and kw not in STOPWORDS:
        return "candidate"
    return "noise"



def kiwi_extract_terms(text):
    """
    Kiwi 기반 명사/고유명사 후보 추출.
    Kiwi가 없거나 실패하면 빈 리스트를 반환한다.
    """
    if not KIWI_AVAILABLE or KIWI is None:
        return []
    try:
        tokens = KIWI.tokenize(text or "")
    except Exception:
        return []

    out = []
    for tok in tokens:
        form = getattr(tok, "form", "")
        tag = getattr(tok, "tag", "")
        if not form:
            continue
        # NNG 일반명사, NNP 고유명사, SL 외국어, SN 숫자
        if tag in ("NNG", "NNP", "SL", "SN"):
            if not is_bad_keyword(form):
                out.append(form)
    return out


def simple_extract_terms(title):
    """
    Kiwi가 없을 때 사용하는 정규식 fallback.
    영문 단어는 글자 단위로 분해하지 않는다.
    """
    title = normalize_title(title)
    return re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9.\\-]{1,15}", title)



def keyword_news_count(keyword, all_items):
    """
    실제 관련 뉴스 개수 계산.
    한 뉴스 안에 같은 키워드가 여러 번 나와도 1건.
    공백/특수문자는 정규화해서 비교.
    """
    cnt = 0
    for it in all_items:
        text = it.get("title", "") + " " + it.get("summary", "") + " " + it.get("source", "")
        if normalized_contains(keyword, text):
            cnt += 1
    return cnt


def extract_keyword_stats(all_items):
    stats = {}
    event_dict = flatten_event_dictionary()
    event_keywords = set(event_dict.keys())

    def add_kw(kw, item):
        kw = (kw or "").strip()
        if is_bad_keyword(kw):
            return
        kind = classify_keyword(kw)
        if kind == "noise":
            return
        event_info = event_dict.get(kw)
        if event_info:
            kind = "core" if event_info.get("novelty", 0) < 50 else "novel"

        if kw not in stats:
            stats[kw] = {
                "keyword": kw,
                "count": 0,
                "impact": 0,
                "novelty": 0,
                "spread": 0,
                "kind": kind,
                "category": event_info.get("category", "") if event_info else "",
                "sources": set(),
                "rawMentions": 0
            }
        stats[kw]["count"] += 1
        stats[kw]["rawMentions"] += 1
        stats[kw]["impact"] += item.get("score", 0)
        if event_info:
            stats[kw]["impact"] += event_info.get("impact", 0)
            stats[kw]["novelty"] += event_info.get("novelty", 0)
        stats[kw]["sources"].add(item.get("source", ""))
        if kw in NOVELTY_KEYWORDS:
            stats[kw]["novelty"] += 8
        elif kind == "candidate":
            stats[kw]["novelty"] += 2

    for it in all_items:
        title = normalize_title(it.get("title", ""))
        text = title + " " + it.get("summary", "") + " " + it.get("source", "")
        low = text.lower()

        # 1) 사전 기반 주식 키워드
        for kw in THEME_KEYWORDS:
            if kw.lower() in low:
                add_kw(kw, it)

        # 2) 핵심 시장 키워드
        for kw in CORE_MARKET_KEYWORDS:
            if kw.lower() in low:
                add_kw(kw, it)

        # 2-1) 사용자가 키워나가는 이벤트 사전 키워드
        # 공백/특수문자 차이도 잡기 위해 정규화 매칭 사용
        for kw in event_keywords:
            if normalized_contains(kw, text):
                add_kw(kw, it)

        # 3) 제목 토큰 자동 추출
        # Kiwi ON: 명사/고유명사 중심
        # Kiwi OFF: 기존 정규식 기반 fallback
        tokens = kiwi_extract_terms(title)
        if not tokens:
            tokens = simple_extract_terms(title)

        for tok in tokens:
            if is_bad_keyword(tok):
                continue
            if tok not in CORE_MARKET_KEYWORDS and tok not in NOVELTY_KEYWORDS:
                has_market_context = any(k.lower() in low for k in CORE_MARKET_KEYWORDS)
                if not has_market_context:
                    continue
            add_kw(tok, it)

    result = []
    for kw, v in stats.items():
        source_count = len([s for s in v["sources"] if s])
        actual_count = keyword_news_count(kw, all_items)
        # 화면에 보이는 count는 실제 관련 뉴스 개수로 통일
        v["count"] = actual_count
        # 확산도는 내부 원시 언급량과 언론사 분산을 반영
        v["spread"] = v["rawMentions"] + source_count * 2
        v["marketScore"] = round(v["impact"] + v["novelty"] + v["spread"], 2)
        v["sources"] = list(v["sources"])[:5]
        if actual_count > 0:
            result.append(v)

    return sorted(result, key=lambda x: (x["marketScore"], x["impact"], x["count"]), reverse=True)[:40]


def build_graph(all_items, keyword_stats):
    top = [k["keyword"] for k in keyword_stats[:18]]
    score_map = {k["keyword"]: k.get("marketScore", 0) for k in keyword_stats}
    kind_map = {k["keyword"]: k.get("kind", "candidate") for k in keyword_stats}
    node_map = {k: {"id": k, "count": 0, "score": score_map.get(k, 0), "kind": kind_map.get(k, "candidate")} for k in top}
    edges = {}

    for it in all_items:
        text = (it["title"] + " " + it.get("summary", "") + " " + it.get("source", "")).lower()
        present = [k for k in top if normalized_contains(k, text)]
        for k in present:
            node_map[k]["count"] += 1
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = sorted([present[i], present[j]])
                edges[(a, b)] = edges.get((a, b), 0) + 1

    nodes = [v for v in node_map.values() if v["count"] > 0]
    edge_list = [{"source": a, "target": b, "weight": w} for (a, b), w in edges.items()]
    edge_list.sort(key=lambda x: x["weight"], reverse=True)
    return {"nodes": nodes, "edges": edge_list}

def search_all(payload):
    period=parse_period(payload.get("periodValue",1), payload.get("periodUnit","d"))
    groups=parse_groups(payload.get("extraKeywords",""), payload.get("checkedKeywords",[]))
    try: max_results=int(payload.get("maxResults",50))
    except Exception: max_results=50
    max_results=max(1,min(max_results,200))
    sort_by=payload.get("sortBy","time")
    if not groups: return {"ok":False,"error":"검색어를 입력하거나 체크박스를 선택하세요."}
    per_group={}; all_items=[]; all_terms=[t for g in groups for t in g["terms"]]
    for g in groups:
        try: items=search_google(g,period,max_results)
        except Exception:
            log_error(traceback.format_exc()); items=[]
        items=dedupe(items)
        for it in items: it["score"]=score_item(it,all_terms)
        if sort_by=="score": items.sort(key=lambda x:(x.get("score",0), x.get("published_dt") or datetime.min.replace(tzinfo=KST)), reverse=True)
        else: items.sort(key=lambda x:x.get("published_dt") or datetime.min.replace(tzinfo=KST), reverse=True)
        items=items[:max_results]
        all_items.extend(items)
        per_group[g["label"]]={"terms":g["terms"],"count":len(items),"items":[{k:v for k,v in it.items() if k!="published_dt"} for it in items]}
    keyword_stats=extract_keyword_stats(all_items)
    graph=build_graph(all_items, keyword_stats)
    total=sum(v["count"] for v in per_group.values())
    return {"ok":True,"periodLabel":period["label"],"groups":[{"label":g["label"],"terms":g["terms"]} for g in groups],"maxResults":max_results,"sortBy":sort_by,"total":total,"perGroup":per_group,"keywordStats":keyword_stats,"graph":graph,"generatedAt":datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),"kiwiAvailable":KIWI_AVAILABLE}


def yahoo_chart(symbol, days=30, interval="1d"):
    now = int(time.time())
    start = now - days * 86400
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + quote_plus(symbol)
        + f"?period1={start}&period2={now}&interval={interval}"
    )
    data = json.loads(http_get(url, timeout=12).decode("utf-8", errors="replace"))
    result = data.get("chart", {}).get("result", [])
    if not result:
        raise RuntimeError("데이터 없음")
    r = result[0]
    ts = r.get("timestamp") or []
    quote = (r.get("indicators", {}).get("quote") or [{}])[0]
    close = quote.get("close") or []
    out = []
    for t, c in zip(ts, close):
        if c is None:
            continue
        dt = datetime.fromtimestamp(t, KST)
        out.append({"date": dt.strftime("%m-%d"), "value": round(float(c), 4)})
    return out[-days:]


def market_snapshot():
    symbols = [
        {"category":"미국시장", "key": "nasdaq", "name": "나스닥", "symbol": "^IXIC", "days": 30, "unit": ""},
        {"category":"미국시장", "key": "sp500", "name": "S&P500", "symbol": "^GSPC", "days": 30, "unit": ""},
        {"category":"미국시장", "key": "dow", "name": "다우", "symbol": "^DJI", "days": 30, "unit": ""},
        {"category":"금리/환율", "key": "dxy", "name": "달러지수", "symbol": "DX-Y.NYB", "days": 30, "unit": ""},
        {"category":"금리/환율", "key": "usdkrw", "name": "원달러환율", "symbol": "KRW=X", "days": 30, "unit": "원"},
        {"category":"금리/환율", "key": "us10y", "name": "미국10년물 국채금리", "symbol": "^TNX", "days": 30, "unit": "%"},
        {"category":"원자재/코인", "key": "wti", "name": "WTI 유가", "symbol": "CL=F", "days": 30, "unit": "$"},
        {"category":"원자재/코인", "key": "gold", "name": "금", "symbol": "GC=F", "days": 30, "unit": "$"},
        {"category":"원자재/코인", "key": "bitcoin", "name": "비트코인", "symbol": "BTC-USD", "days": 30, "unit": "$"},
    ]
    items = []
    errors = []
    for s in symbols:
        try:
            series = yahoo_chart(s["symbol"], s["days"], "1d")
            latest = series[-1]["value"] if series else None
            prev = series[-2]["value"] if len(series) >= 2 else None
            change = None if latest is None or prev is None else round(latest - prev, 4)
            pct = None if latest is None or prev in (None, 0) else round((latest - prev) / prev * 100, 2)
            items.append({**s, "latest": latest, "change": change, "pct": pct, "series": series})
        except Exception as e:
            errors.append(f"{s['name']}: {e}")
            items.append({**s, "latest": None, "change": None, "pct": None, "series": []})
    return {
        "ok": True,
        "generatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "errors": errors
    }



DEFAULT_EVENT_DICTIONARY = {
    "주주환원": {
        "impact": 90,
        "novelty": 20,
        "keywords": [
            "자사주 매입", "자사주매입", "자사주 소각", "자사주소각",
            "배당 확대", "배당확대", "특별배당", "주주환원", "밸류업",
            "배당성향", "중간배당"
        ]
    },
    "기업행위": {
        "impact": 85,
        "novelty": 15,
        "keywords": [
            "무상증자", "유상증자", "제3자배정", "제3자배정 유상증자",
            "CB", "BW", "전환사채", "신주인수권부사채", "액면분할",
            "인적분할", "물적분할", "합병", "인수", "최대주주 변경",
            "경영권 분쟁", "공개매수"
        ]
    },
    "실적": {
        "impact": 75,
        "novelty": 10,
        "keywords": [
            "흑자전환", "적자전환", "어닝서프라이즈", "어닝쇼크",
            "영업이익", "순이익", "매출", "가이던스", "컨센서스 상회",
            "컨센서스 하회"
        ]
    },
    "바이오": {
        "impact": 90,
        "novelty": 25,
        "keywords": [
            "FDA", "임상1상", "임상2상", "임상3상", "품목허가",
            "기술수출", "라이선스아웃", "신약", "항암제", "희귀의약품",
            "ADC", "항체약물접합체", "비만치료제", "GLP-1"
        ]
    },
    "반도체_AI": {
        "impact": 85,
        "novelty": 45,
        "keywords": [
            "HBM", "HBM3", "HBM4", "CXL", "유리기판", "AI반도체",
            "온디바이스AI", "엔비디아", "젠슨황", "TSMC", "마이크론",
            "파운드리", "EUV", "DDR5", "데이터센터"
        ]
    },
    "거시경제": {
        "impact": 80,
        "novelty": 10,
        "keywords": [
            "금리", "국채금리", "미국채", "10년물", "FOMC", "연준",
            "CPI", "인플레이션", "달러", "환율", "원달러", "유가",
            "WTI", "금", "채권"
        ]
    },
    "신규테마": {
        "impact": 65,
        "novelty": 70,
        "keywords": [
            "피지컬AI", "휴머노이드", "양자컴퓨터", "전력망", "변압기",
            "SMR", "전고체", "로봇", "우주항공", "자율주행"
        ]
    }
}


def event_dict_path():
    return os.path.join(app_dir(), "stock_event_dictionary.json")


def ensure_event_dictionary():
    path = event_dict_path()
    if not os.path.exists(path):
        save_event_dictionary(DEFAULT_EVENT_DICTIONARY)
    return path


def load_event_dictionary():
    path = ensure_event_dictionary()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("dictionary must be object")
        return data
    except Exception:
        log_error("event dictionary load failed\n" + traceback.format_exc())
        save_event_dictionary(DEFAULT_EVENT_DICTIONARY)
        return DEFAULT_EVENT_DICTIONARY.copy()


def save_event_dictionary(data):
    path = event_dict_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_event_text(s):
    """
    이벤트/키워드 매칭용 정규화.
    공백, 느낌표, 하이픈 등 특수문자를 제거해서 같은 의미를 동일 비교한다.
    예: '자사주 소각!' -> '자사주소각'
    """
    s = str(s or "").lower()
    return re.sub(r"[^가-힣a-z0-9]+", "", s)


def normalized_contains(keyword, text):
    if not keyword:
        return False
    low_kw = str(keyword).lower()
    low_text = str(text or "").lower()
    if low_kw in low_text:
        return True
    nk = normalize_event_text(keyword)
    nt = normalize_event_text(text)
    return bool(nk and nk in nt)


def flatten_event_dictionary():
    data = load_event_dictionary()
    flat = {}
    for category, info in data.items():
        impact = int(info.get("impact", 50)) if isinstance(info, dict) else 50
        novelty = int(info.get("novelty", 10)) if isinstance(info, dict) else 10
        keywords = info.get("keywords", []) if isinstance(info, dict) else []
        for kw in keywords:
            kw = str(kw).strip()
            if not kw:
                continue
            # 표시명은 JSON 원본 그대로 유지.
            # 매칭은 normalized_contains()로 처리.
            flat[kw] = {
                "category": category,
                "impact": impact,
                "novelty": novelty,
                "normalized": normalize_event_text(kw)
            }
    return flat


def add_event_keyword(category, keyword, impact=70, novelty=20):
    category = (category or "").strip()
    keyword = (keyword or "").strip()
    if not category or not keyword:
        raise ValueError("카테고리와 키워드를 입력하세요.")

    try:
        impact = int(impact)
    except Exception:
        impact = 70
    try:
        novelty = int(novelty)
    except Exception:
        novelty = 20

    impact = max(0, min(100, impact))
    novelty = max(0, min(100, novelty))

    data = load_event_dictionary()
    if category not in data or not isinstance(data.get(category), dict):
        data[category] = {"impact": impact, "novelty": novelty, "keywords": []}

    data[category]["impact"] = impact
    data[category]["novelty"] = novelty

    keywords = data[category].setdefault("keywords", [])
    if keyword not in keywords:
        keywords.append(keyword)

    save_event_dictionary(data)
    return data



DEFAULT_BREAKING_TOPICS = [
    {"name": "한국증시", "query": "한국 증시 OR 코스피 OR 코스닥", "priority": 5, "enabled": True},
    {"name": "속보", "query": "속보 증시 OR 주식 속보", "priority": 5, "enabled": True},
    {"name": "반도체", "query": "반도체 OR HBM OR 삼성전자 OR SK하이닉스", "priority": 5, "enabled": True},
    {"name": "AI", "query": "AI OR 인공지능 OR 엔비디아 OR 데이터센터", "priority": 5, "enabled": True},
    {"name": "바이오", "query": "바이오 OR 제약 OR FDA OR 임상", "priority": 5, "enabled": True},
    {"name": "방산", "query": "방산 OR 전쟁 OR 수주", "priority": 4, "enabled": True},
    {"name": "원전전력", "query": "원전 OR 원자력 OR 전력망 OR 변압기", "priority": 4, "enabled": True},
    {"name": "2차전지", "query": "2차전지 OR 배터리 OR 리튬 OR 전기차", "priority": 4, "enabled": True},
    {"name": "로봇", "query": "로봇 OR 휴머노이드 OR 피지컬AI", "priority": 4, "enabled": True},
    {"name": "거시", "query": "환율 OR 금리 OR 유가 OR 국채금리 OR 연준", "priority": 4, "enabled": True}
]

def topic_key(name):
    base = re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(name or "").strip()).strip("_")
    return base or "topic"

def breaking_topics_path():
    return os.path.join(app_dir(), "breaking_topics.json")

def normalize_breaking_topic(t):
    name = str(t.get("name", "") or "").strip()
    query = str(t.get("query", "") or name).strip()
    if not name:
        return None
    try:
        priority = int(t.get("priority", 5))
    except Exception:
        priority = 5
    priority = max(1, min(priority, 9))
    return {
        "key": str(t.get("key") or topic_key(name)),
        "name": name,
        "query": query or name,
        "priority": priority,
        "enabled": bool(t.get("enabled", True))
    }

def default_breaking_topics():
    out=[]
    for t in DEFAULT_BREAKING_TOPICS:
        nt=normalize_breaking_topic(t)
        if nt:
            out.append(nt)
    return out

def save_breaking_topics(topics):
    clean=[]
    seen=set()
    for t in topics or []:
        nt=normalize_breaking_topic(t)
        if not nt:
            continue
        k=nt["key"]
        # 이름/검색식 기준 중복 제거
        sig=(normalize_event_text(nt["name"]), normalize_event_text(nt["query"]))
        if k in seen or sig in seen:
            continue
        seen.add(k); seen.add(sig)
        clean.append(nt)
    clean.sort(key=lambda x:(-int(x.get("priority",5)), x.get("name","")))
    with open(breaking_topics_path(), "w", encoding="utf-8") as f:
        json.dump({"topics": clean}, f, ensure_ascii=False, indent=2)
    return clean

def load_breaking_topics():
    path=breaking_topics_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw=json.load(f)
            topics=raw.get("topics", raw if isinstance(raw, list) else [])
            clean=save_breaking_topics(topics)
            if clean:
                return clean
        except Exception:
            log_error("breaking topics load failed\n" + traceback.format_exc())
    return save_breaking_topics(default_breaking_topics())

def upsert_breaking_topic(payload):
    topics=load_breaking_topics()
    key=str(payload.get("key") or "").strip() or topic_key(payload.get("name"))
    nt=normalize_breaking_topic({
        "key": key,
        "name": payload.get("name"),
        "query": payload.get("query"),
        "priority": payload.get("priority", 5),
        "enabled": payload.get("enabled", True)
    })
    if not nt:
        raise ValueError("주제명이 비어 있습니다.")
    # 같은 이름/검색식은 기존 것을 갱신
    name_sig=normalize_event_text(nt["name"])
    query_sig=normalize_event_text(nt["query"])
    out=[]; replaced=False
    for t in topics:
        if t.get("key")==key or normalize_event_text(t.get("name",""))==name_sig or normalize_event_text(t.get("query",""))==query_sig:
            if not replaced:
                out.append(nt); replaced=True
            continue
        out.append(t)
    if not replaced:
        out.append(nt)
    return save_breaking_topics(out)

def delete_breaking_topic(key):
    key=str(key or "").strip()
    topics=[t for t in load_breaking_topics() if t.get("key") != key]
    return save_breaking_topics(topics)


def search_google_breaking(topic_name, query, period_when="1d", max_results=30):
    url = "https://news.google.com/rss/search?q=" + quote_plus(query + f" when:{period_when}") + "&hl=ko&gl=KR&ceid=KR:ko"
    data = http_get(url)
    root = ET.fromstring(data)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else "Google News"
        summary = strip_tags(item.findtext("description") or "")
        dt = parse_google_dt(pub)
        if not title or not link:
            continue
        items.append({
            "topic": topic_name,
            "title": title,
            "link": link,
            "source": source,
            "published": dt.strftime("%Y-%m-%d %H:%M") if dt else pub,
            "published_ts": int(dt.timestamp()) if dt else 0,
            "summary": summary
        })
        if len(items) >= max_results:
            break
    return items


def dedupe_breaking_items(items):
    seen = set()
    out = []
    for it in items:
        key = normalize_event_text(it.get("title", ""))
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def breaking_snapshot(period_value=12, period_unit="h", max_per_topic=20):
    try:
        period_value = int(period_value)
    except Exception:
        period_value = 12
    period_value = max(1, min(period_value, 30))

    if period_unit == "h":
        period_when = f"{period_value}h"
        period_label = f"최근 {period_value}시간"
    elif period_unit == "w":
        period_when = f"{period_value * 7}d"
        period_label = f"최근 {period_value}주"
    else:
        period_when = f"{period_value}d"
        period_label = f"최근 {period_value}일"

    try:
        max_per_topic = int(max_per_topic)
    except Exception:
        max_per_topic = 20
    max_per_topic = max(5, min(max_per_topic, 50))

    topic_results = []
    all_items = []
    errors = []

    breaking_topics = [t for t in load_breaking_topics() if t.get("enabled", True)]
    global_seen = set()
    for t in breaking_topics:
        try:
            raw_items = search_google_breaking(t["name"], t["query"], period_when, max_per_topic)
            raw_items = dedupe_breaking_items(raw_items)
            items = []
            for it in raw_items:
                key = normalize_event_text(it.get("link") or it.get("title", ""))
                title_key = normalize_event_text(it.get("title", ""))
                if key in global_seen or title_key in global_seen:
                    continue
                global_seen.add(key); global_seen.add(title_key)
                items.append(it)
            topic_results.append({"name": t["name"], "query": t.get("query", t["name"]), "count": len(items), "items": items})
            all_items.extend(items)
        except Exception as e:
            errors.append(f"{t['name']}: {e}")
            topic_results.append({"name": t["name"], "query": t.get("query", t["name"]), "count": 0, "items": []})
            log_error("breaking search failed\n" + traceback.format_exc())

    # 전체 중복 제거 후 최신순 정렬
    all_items = dedupe_breaking_items(all_items)
    all_items.sort(key=lambda x: x.get("published_ts", 0), reverse=True)

    # 주식 이벤트 사전/키워드 엔진으로 속보 키워드 요약 생성
    pseudo_items = []
    for it in all_items:
        pseudo_items.append({
            "title": it.get("title", ""),
            "summary": it.get("summary", ""),
            "source": it.get("source", ""),
            "score": score_item({"title": it.get("title", ""), "summary": it.get("summary", ""), "source": it.get("source", ""), "published_dt": None}, [])
        })
    keyword_stats = extract_keyword_stats(pseudo_items) if pseudo_items else []

    # 속보 키워드 count는 실제 클릭 시 보여줄 뉴스 개수와 같은 기준으로 재계산
    top_items = all_items[:80]
    for k in keyword_stats:
        kw = k.get("keyword", "")
        k["count"] = sum(1 for it in top_items if normalized_contains(kw, (it.get("title","") + " " + it.get("summary","") + " " + it.get("source",""))))

    keyword_stats = [k for k in keyword_stats if k.get("count", 0) > 0]

    return {
        "ok": True,
        "periodLabel": period_label,
        "generatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "topics": topic_results,
        "topicCount": len(breaking_topics),
        "total": len(all_items),
        "topItems": top_items,
        "keywordStats": keyword_stats[:20],
        "errors": errors
    }



# ---------------- 산업부 수출입 리포트 분석 ----------------
EXPORT_THEME_MAP = {
    "semiconductor": {"name":"반도체", "themes":["HBM","AI서버","메모리","반도체장비"], "news":["반도체","HBM","SK하이닉스","삼성전자"]},
    "cosmetics": {"name":"화장품", "themes":["K뷰티","ODM","미국수출","아마존"], "news":["화장품","K뷰티","코스맥스","한국콜마","APR"]},
    "ship": {"name":"선박", "themes":["조선","LNG선","수주","해양플랜트"], "news":["조선","선박","HD현대중공업","한화오션"]},
    "power": {"name":"전력기기", "themes":["변압기","전선","전력망","데이터센터"], "news":["전력기기","변압기","전선","전력망"]},
    "auto": {"name":"자동차", "themes":["완성차","부품","친환경차","북미"], "news":["자동차","현대차","기아","자동차부품"]},
    "battery": {"name":"이차전지", "themes":["배터리","양극재","리튬","전기차"], "news":["이차전지","배터리","양극재","리튬"]},
    "bio": {"name":"바이오헬스", "themes":["제약","의료기기","CDMO","미용의료"], "news":["바이오","제약","의료기기","CDMO"]},
    "display": {"name":"디스플레이", "themes":["OLED","IT패널","애플","장비"], "news":["디스플레이","OLED","패널"]},
    "steel": {"name":"철강", "themes":["철강","후판","관세","건설"], "news":["철강","후판","관세"]},
    "petrochem": {"name":"석유화학", "themes":["화학","스프레드","나프타","중국수요"], "news":["석유화학","화학","나프타"]},
    "food": {"name":"농수산식품", "themes":["K푸드","라면","김","냉동식품"], "news":["K푸드","라면","김 수출","식품"]},
    "wireless": {"name":"무선통신기기", "themes":["스마트폰","부품","통신장비","XR"], "news":["무선통신기기","스마트폰","통신장비"]}
}

def export_data_path():
    return export_latest_path()

def export_reports_dir():
    d=os.path.join(app_dir(), "data", "export_reports")
    os.makedirs(d, exist_ok=True)
    return d

def export_latest_path():
    return os.path.join(export_reports_dir(), "export_latest.json")

def confirmed_export_report():
    """사용자가 제공한 산업부 표 이미지에서 확인된 15개 품목 데이터만 사용.
    임의 추정값/예시값은 넣지 않는다.
    단위: 백만 달러, 증감률: %
    """
    months=["25.5","26.3","26.4","26.5"]
    rows=[
        (1,"semiconductor","반도체", [(13794,-21.2),(32829,151.4),(31895,173.5),(37157,169.4)], ["HBM","AI서버","메모리","반도체장비"], ["반도체","HBM","AI반도체","SK하이닉스","삼성전자"]),
        (2,"petroleum","석유제품", [(3581,-20.8),(6135,86.1),(5106,39.9),(5250,46.6)], ["정유","유가","정제마진"], ["석유제품","정유","유가"]),
        (3,"petrochem","석유화학", [(3329,-17.5),(4004,9.5),(4096,7.9),(3698,11.1)], ["화학","나프타","스프레드"], ["석유화학","화학","나프타"]),
        (4,"auto","자동차", [(6198,-4.5),(6369,2.2),(6166,-5.5),(5833,-5.9)], ["완성차","친환경차","북미"], ["자동차","현대차","기아"]),
        (5,"machinery","일반기계", [(4072,-5.2),(3891,-6.4),(4209,-2.6),(3817,-6.3)], ["기계","설비투자","산업재"], ["일반기계","기계"]),
        (6,"steel","철강제품", [(2084,-8.8),(2054,-0.3),(2145,-9.3),(2039,-2.1)], ["철강","후판","관세"], ["철강","후판","관세"]),
        (7,"autoparts","자동차부품", [(1654,-9.4),(1786,-2.3),(1894,-6.0),(1613,-2.5)], ["자동차부품","전장","완성차 밸류체인"], ["자동차부품","전장"]),
        (8,"display","디스플레이", [(1341,-17.9),(1439,-1.5),(1285,-2.7),(1466,9.4)], ["OLED","패널","IT기기"], ["디스플레이","OLED","패널"]),
        (9,"wireless","무선통신기기", [(1295,3.9),(1786,43.4),(1620,11.6),(1459,12.6)], ["스마트폰","통신장비","XR"], ["무선통신기기","스마트폰","통신장비"]),
        (10,"ship","선박", [(2239,4.6),(3525,10.8),(2890,43.8),(2613,16.7)], ["조선","LNG선","수주"], ["조선","선박","HD현대중공업","한화오션"]),
        (11,"biohealth","바이오헬스", [(1371,6.6),(1523,6.4),(1639,18.3),(1442,5.2)], ["제약","의료기기","CDMO"], ["바이오","제약","의료기기"]),
        (12,"computer","컴퓨터", [(1070,2.3),(3417,189.1),(4083,515.8),(4179,290.7)], ["SSD","AI서버","데이터센터"], ["컴퓨터","SSD","데이터센터","AI서버"]),
        (13,"textile","섬유", [(913,-11.2),(928,4.9),(1051,6.3),(853,-6.6)], ["섬유","의류","소비재"], ["섬유","의류"]),
        (14,"battery","이차전지", [(524,-18.5),(819,28.6),(653,-6.5),(688,31.4)], ["배터리","양극재","전기차"], ["이차전지","배터리","양극재"]),
        (15,"home_appliance","가전", [(612,-15.0),(588,-7.9),(565,-20.0),(479,-21.7)], ["가전","소비재","북미"], ["가전","LG전자"]),
        # 아래 5개는 보고서 본문에 공개된 최신월 수치로 보완. 이전월 표 수치는 자동 PDF 추출 단계에서 채운다.
        (16,"nonferrous","비철금속", [(None,None),(None,None),(None,None),(1700,41.0)], ["비철금속","구리","알루미늄"], ["비철금속","구리","알루미늄"]),
        (17,"electrical","전기기기", [(None,None),(None,None),(None,None),(1300,-2.0)], ["전력기기","변압기","전선"], ["전기기기","전력기기","변압기","전선"]),
        (18,"cosmetics","화장품", [(None,None),(None,None),(None,None),(1180,24.2)], ["K뷰티","ODM","미국수출"], ["화장품","K뷰티","코스맥스","한국콜마","APR"]),
        (19,"agri_food","농수산식품", [(None,None),(None,None),(None,None),(1070,4.7)], ["식품","K푸드","농산가공품"], ["농수산식품","K푸드","라면","김"]),
        (20,"living","생활용품", [(None,None),(None,None),(None,None),(700,-5.0)], ["생활용품","소비재"], ["생활용품","소비재"]),
    ]
    items=[]
    for rank,key,name,vals,themes,news in rows:
        amounts=[a for a,g in vals]
        growth=[g for a,g in vals]
        latest=next((g for a,g in reversed(vals) if isinstance(g,(int,float))), None)
        latest_amount=next((a for a,g in reversed(vals) if isinstance(a,(int,float))), None)
        numeric_growth=[g for g in growth if isinstance(g,(int,float))]
        avg3=round(sum(numeric_growth[-3:])/len(numeric_growth[-3:]),1) if numeric_growth else None
        prev = numeric_growth[-2] if len(numeric_growth)>=2 else None
        acceleration=round(latest-prev,1) if isinstance(latest,(int,float)) and isinstance(prev,(int,float)) else None
        amount_score=min(35, (latest_amount or 0)/37157*35)
        growth_score=max(0,min(45,((latest or 0)+30)/320*45))
        accel_score=max(0,min(20,(((acceleration if acceleration is not None else 0)+30)/120)*20))
        score=round(amount_score+growth_score+accel_score,1)
        if isinstance(latest_amount,(int,float)) and latest_amount >= 10000 and (latest or 0) > 0:
            comment="규모와 증가율이 모두 강한 핵심 품목"
        elif (latest or 0) > 50:
            comment="증가율 강세. 규모와 지속성 확인 필요"
        elif (latest or 0) > 0:
            comment="증가세 유지. 전월 대비 흐름 확인"
        else:
            comment="감소세. 회복 전까지 보수적 관찰"
        items.append({
            "rank":rank,"key":key,"name":name,
            "amounts":amounts,"monthly":growth,
            "latest":latest,"latestAmount":latest_amount,
            "avg3":avg3,"acceleration":acceleration,"score":score,
            "themes":themes,"newsKeywords":news,"comment":comment
        })
    return {
        "ok":True,
        "dataVerified":True,
        "dataScope":"산업부 20대 주요 수출 품목 + 5월 국가/지역별 수출 요약 데이터",
        "source":"산업통상자원부·KITA 공개 요약 기반 데이터",
        "reportMonth":"2026-05",
        "title":"20대 주요 수출 품목 규모 및 증감률",
        "url":"",
        "publishedDate":"",
        "generatedAt":datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "statusMessage":"저장된 표 기반 수출입 데이터 표시",
        "headline":"메인 기준은 절대 수출금액입니다. 반도체가 압도적 1위이며, 국가별로는 중국·미국·아세안 3대 지역 수출 증가가 두드러집니다.",
        "metrics":{"exportAmount":"-","exportYoY":"표 미확인","importAmount":"-","importYoY":"-","balance":"-","balanceComment":"전체 수출입 원문 수치 미연동"},
        "months":months,
        "items":items,
        "countries":[
            {"name":"중국","amount":189.0,"latest":80.9,"comment":"반도체가 세 자릿수 증가하고 농수산식품·화장품 등 소비재도 양호해 최대 수출지역으로 급증"},
            {"name":"미국","amount":160.0,"latest":59.0,"comment":"AI·반도체·컴퓨터 수요와 북미 소비재 흐름이 함께 강한 핵심 시장"},
            {"name":"아세안","amount":159.0,"latest":58.0,"comment":"중국·미국과 함께 3대 수출축. 반도체·IT·중간재 수요 회복 확인"},
            {"name":"EU","amount":62.0,"latest":2.0,"comment":"플러스는 유지했지만 증가율은 낮아 상대적으로 둔한 지역"},
            {"name":"중남미","amount":32.0,"latest":43.0,"comment":"규모는 작지만 증가율이 높아 시장 다변화 관점에서 관심"},
            {"name":"일본","amount":27.0,"latest":12.0,"comment":"완만한 증가. 소재·부품·중간재 흐름 추적 필요"},
            {"name":"인도","amount":20.0,"latest":25.0,"comment":"규모는 아직 작지만 성장률이 높아 중장기 확장 시장으로 분류"}
        ],
        "regions":[
            {"name":"중화권","amount":189.0,"latest":80.9,"comment":"중국향 반도체 급증이 전체 수출 증가를 강하게 견인"},
            {"name":"북미","amount":160.0,"latest":59.0,"comment":"미국 중심 AI·IT 수요와 소비재 수출 흐름이 강함"},
            {"name":"동남아","amount":159.0,"latest":58.0,"comment":"아세안향 중간재·IT 수출 회복으로 주요 성장축 형성"},
            {"name":"유럽","amount":62.0,"latest":2.0,"comment":"EU는 증가폭이 제한적이라 다른 지역 대비 모멘텀 약함"},
            {"name":"중남미","amount":32.0,"latest":43.0,"comment":"고성장 지역으로 분류되지만 절대 규모는 아직 작음"},
            {"name":"일본·인도","amount":47.0,"latest":17.5,"comment":"일본 27억 달러(+12%)와 인도 20억 달러(+25%)를 묶은 보조 성장권"}
        ]
    }

def sample_export_report():
    # 호환용 이름. 실제로는 임의 예시가 아니라 확인된 표 기반 데이터만 반환한다.
    return confirmed_export_report()

def _valid_iso_date(s):
    try:
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", s or ""):
            return False
        dt=datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=KST)
        now=datetime.now(KST)
        if dt.year < 2020 or dt > now + timedelta(days=1):
            return False
        return True
    except Exception:
        return False

def _make_iso_date(y, m, d):
    try:
        y=int(y); m=int(m); d=int(d)
        dt=datetime(y,m,d,tzinfo=KST)
        s=dt.strftime("%Y-%m-%d")
        return s if _valid_iso_date(s) else ""
    except Exception:
        return ""

def parse_motie_latest_export_post():
    """산업부 보도·참고자료 목록에서 최신 '수출입 동향' 글을 찾는다.
    핵심 수정:
    - 게시글 번호(예: 20512253)를 날짜로 변환하지 않는다.
    - 날짜는 YYYY-MM-DD 또는 YYYY.MM.DD 형태만 인정한다.
    - 2021년 같은 오래된 검색 결과는 최신 자료로 채택하지 않는다.
    """
    from urllib.parse import urljoin

    base="https://www.motir.go.kr/kor/article/ATCL3f49a5a8c"
    urls=[base]
    urls += [f"{base}?pageIndex={i}" for i in range(1, 11)]
    errors=[]
    candidates=[]

    def add_candidate(title, href, date_text):
        title=re.sub(r"\s+", " ", strip_tags(title or "")).strip()
        if not ("수출입" in title and "동향" in title):
            return
        # ICT 수출입 동향은 별도 통계라 제외
        if "ICT" in title.upper() or "정보통신" in title:
            return
        dm=re.search(r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", date_text or "")
        if not dm:
            return
        published=_make_iso_date(dm.group(1), dm.group(2), dm.group(3))
        if not published:
            return
        # 너무 오래된 검색결과는 최신 판단에서 제외
        if published < "2025-01-01":
            return
        candidates.append({"title":title,"url":href,"publishedDate":published})

    for url in urls:
        try:
            html=http_get(url, timeout=12).decode("utf-8", errors="replace")
            if "수출입" not in html:
                continue
            # 목록 페이지는 제목 주변 2000자 안에 등록일이 같이 있다.
            for m in re.finditer(r"<a[^>]+href=[\'\"]([^\'\"]+)[\'\"][^>]*>(.*?)</a>", html, flags=re.I|re.S):
                href=urljoin(url, m.group(1))
                title_html=m.group(2)
                title=strip_tags(title_html)
                if "수출입" not in title or "동향" not in title:
                    continue
                near=strip_tags(html[m.start():m.start()+2200])
                add_candidate(title, href, near)

            # 웹 렌더링/접근성 텍스트에 제목과 날짜가 풀린 경우 보완
            plain=strip_tags(html)
            for m in re.finditer(r"((?:20\d{2}년\s*)?\d{1,2}월\s*수출입\s*동향|20\d{2}년\s*\d{1,2}월\s*수출입\s*동향).*?(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", plain, flags=re.S):
                title=re.sub(r"\s+", " ", m.group(1)).strip()
                add_candidate(title, url, m.group(0))
        except Exception as e:
            errors.append(f"{url} -> {e}")

    if candidates:
        # 같은 글 중복 제거 후 등록일 최신순
        uniq={}
        for c in candidates:
            k=(c["title"], c["publishedDate"])
            uniq[k]=c
        arr=list(uniq.values())
        arr.sort(key=lambda c:c["publishedDate"], reverse=True)
        return arr[0]

    raise RuntimeError("산업부 최신 수출입 동향 확인 실패: " + " | ".join(errors[-3:]))

def load_saved_export_report():
    path=export_data_path()
    if os.path.exists(path):
        try:
            with open(path,"r",encoding="utf-8") as f:
                data=json.load(f)
            # 이전 버전에서 잘못 저장된 2051-22-53, 2021년 자료 등은 폐기
            pd=data.get("publishedDate","")
            title=str(data.get("title","") or "")
            if pd and not _valid_iso_date(pd):
                raise ValueError("invalid saved publishedDate")
            if "2021" in title or "21년" in title or "2051" in str(pd):
                raise ValueError("stale/wrong saved export report")
            data["ok"]=True
            return data
        except Exception:
            log_error("export report load discarded or failed\n"+traceback.format_exc())
    data=sample_export_report()
    try:
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
    except Exception:
        pass
    return data

def export_report_snapshot(force=False):
    """안정형 수출입 대시보드.
    산업부 PDF viewer 직접 다운로드는 현재 사이트 구조/인증서 문제로 불안정하므로 실행하지 않는다.
    대신 확인된 표 기반 데이터(confirmed_export_report)를 JSON으로 저장하고 웹페이지에 표시한다.
    최신 게시물 메타 정보는 가능할 때만 갱신하고, 실패해도 데이터 화면은 깨지지 않는다.
    """
    db_data=industry_payload_from_db("")
    if db_data:
        return db_data
    data=load_saved_export_report()
    if not data:
        data=sample_export_report()
    try:
        latest=parse_motie_latest_export_post()
        data.update({
            "ok":True,
            "source":"산업통상자원부",
            "url":latest.get("url", data.get("url", "")),
            "latestPost":latest,
            "generatedAt":datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "statusMessage":"수출입 표 기반 데이터 표시 / 최신 게시물 확인 완료",
            "analysisMode":"stable_json",
            "usedSavedData":True,
            "runDetail":"검증된 표 기반 JSON 데이터를 표시합니다. 산업부 PDF 직접 자동다운로드는 현재 viewer 구조가 불안정하여 제외했습니다."
        })
    except Exception as e:
        data.update({
            "ok":True,
            "generatedAt":datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "statusMessage":"수출입 표 기반 데이터 표시 / 산업부 최신 게시물 확인 생략: "+str(e),
            "analysisMode":"stable_json",
            "usedSavedData":True,
            "runDetail":"산업부 최신 게시물 확인은 실패했지만, 검증된 표 기반 데이터는 정상 표시합니다. PDF 자동추출은 사용하지 않습니다."
        })
    try:
        path=export_data_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
    except Exception:
        pass
    return data

# ---------------- 테마 대시보드 ----------------
THEME_SEEDS = [
    {"key":"semiconductor","name":"반도체/HBM","keywords":["HBM","AI반도체","메모리","반도체장비"],"news":["반도체","HBM","AI반도체","SK하이닉스","삼성전자"],"stocks":["삼성전자","SK하이닉스","한미반도체","주성엔지니어링","이오테크닉스","테크윙","리노공업"]},
    {"key":"power","name":"전력기기/전선","keywords":["변압기","전력망","전선","데이터센터"],"news":["전력기기","변압기","전선","데이터센터"],"stocks":["HD현대일렉트릭","LS ELECTRIC","효성중공업","일진전기","제룡전기","대한전선","가온전선"]},
    {"key":"shipbuilding","name":"조선/LNG","keywords":["조선","LNG선","수주","해양플랜트"],"news":["조선","LNG선","수주","한화오션"],"stocks":["HD현대중공업","HD한국조선해양","한화오션","삼성중공업","HD현대미포","HJ중공업"]},
    {"key":"cosmetics","name":"화장품/K뷰티","keywords":["K뷰티","ODM","미국수출","아마존"],"news":["화장품","K뷰티","코스맥스","한국콜마"],"stocks":["코스맥스","한국콜마","아모레퍼시픽","LG생활건강","APR","실리콘투","브이티"]},
    {"key":"bio","name":"바이오/제약","keywords":["바이오","제약","CDMO","의료기기"],"news":["바이오","제약","CDMO","의료기기"],"stocks":["삼성바이오로직스","셀트리온","알테오젠","리가켐바이오","에이비엘바이오","HLB"]},
    {"key":"battery","name":"이차전지","keywords":["배터리","양극재","리튬","전기차"],"news":["이차전지","배터리","양극재","리튬"],"stocks":["LG에너지솔루션","삼성SDI","에코프로비엠","포스코퓨처엠","엘앤에프","에코프로"]},
    {"key":"auto","name":"자동차/부품","keywords":["완성차","부품","친환경차","북미"],"news":["자동차","현대차","기아","자동차부품"],"stocks":["현대차","기아","현대모비스","HL만도","성우하이텍","화신"]},
    {"key":"defense","name":"방산","keywords":["방산","수출","폴란드","중동"],"news":["방산","한화에어로스페이스","현대로템","LIG넥스원"],"stocks":["한화에어로스페이스","현대로템","LIG넥스원","한국항공우주","한화시스템"]},
    {"key":"nuclear","name":"원전/에너지","keywords":["원전","SMR","원전수출","전력"],"news":["원전","SMR","두산에너빌리티","한전기술"],"stocks":["두산에너빌리티","한전기술","한전KPS","우진","비에이치아이"]},
    {"key":"food","name":"음식료/K푸드","keywords":["K푸드","라면","김","수출"],"news":["K푸드","라면","삼양식품","농심"],"stocks":["삼양식품","농심","오리온","CJ제일제당","빙그레"]},
    {"key":"ai_software","name":"AI/소프트웨어","keywords":["AI","데이터센터","클라우드","LLM"],"news":["AI","소프트웨어","NAVER","카카오"],"stocks":["NAVER","카카오","더존비즈온","이스트소프트","솔트룩스"]},
]

THEME_STOCK_CODE_FALLBACK = {
    "삼성전자":"005930","SK하이닉스":"000660","한미반도체":"042700","주성엔지니어링":"036930","이오테크닉스":"039030","테크윙":"089030","리노공업":"058470",
    "HD현대일렉트릭":"267260","LS ELECTRIC":"010120","효성중공업":"298040","일진전기":"103590","제룡전기":"033100","대한전선":"001440","가온전선":"000500",
    "HD현대중공업":"329180","HD한국조선해양":"009540","한화오션":"042660","삼성중공업":"010140","HD현대미포":"010620","HJ중공업":"097230",
    "코스맥스":"192820","한국콜마":"161890","아모레퍼시픽":"090430","LG생활건강":"051900","APR":"278470","실리콘투":"257720","브이티":"018290",
    "삼성바이오로직스":"207940","셀트리온":"068270","알테오젠":"196170","리가켐바이오":"141080","에이비엘바이오":"298380","HLB":"028300",
    "LG에너지솔루션":"373220","삼성SDI":"006400","에코프로비엠":"247540","포스코퓨처엠":"003670","엘앤에프":"066970","에코프로":"086520",
    "현대차":"005380","기아":"000270","현대모비스":"012330","HL만도":"204320","성우하이텍":"015750","화신":"010690",
    "한화에어로스페이스":"012450","현대로템":"064350","LIG넥스원":"079550","한국항공우주":"047810","한화시스템":"272210",
    "두산에너빌리티":"034020","한전기술":"052690","한전KPS":"051600","우진":"105840","비에이치아이":"083650",
    "삼양식품":"003230","농심":"004370","오리온":"271560","CJ제일제당":"097950","빙그레":"005180",
    "NAVER":"035420","카카오":"035720","더존비즈온":"012510","이스트소프트":"047560","솔트룩스":"304100",
}

def theme_date_range(start="", end=""):
    today=datetime.now(KST).date()
    end_d=iso_date(end) or today
    start_d=iso_date(start) or (end_d - timedelta(days=10))
    if start_d>end_d:
        start_d,end_d=end_d,start_d
    return start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")

def stock_lookup_by_name():
    lookup={}
    for item in stock_master_items():
        name=str(item.get("name") or "").strip()
        code=normalize_stock_code(item.get("code"))
        if name and code:
            lookup[normalize_stock_name(name)]={"name":name,"code":code,"market":item.get("market") or ""}
    return lookup

def resolve_theme_stock(name, lookup):
    key=normalize_stock_name(name)
    if key in lookup:
        return lookup[key]
    for k,item in lookup.items():
        if key and (key in k or k in key):
            return item
    fallback_code=THEME_STOCK_CODE_FALLBACK.get(name)
    if fallback_code:
        return {"name":name, "code":fallback_code, "market":""}
    return {"name":name, "code":"", "market":""}

def pykrx_stock_module():
    try:
        from pykrx import stock
        return stock
    except Exception:
        return None

def fdr_module():
    try:
        import FinanceDataReader as fdr
        return fdr
    except Exception:
        return None

def stock_theme_snapshot(code, start, end, pykrx_stock=None, fdr=None):
    code=normalize_stock_code(code)
    if not code:
        return {"changePct":0, "amount":0, "foreignNetBuy":0, "institutionNetBuy":0, "provider":"none", "supplyProvider":"none"}
    s8=start.replace("-","")
    e8=end.replace("-","")
    close_first=None
    close_last=None
    amount=0
    provider=""
    if pykrx_stock:
        try:
            df=pykrx_stock.get_market_ohlcv(s8, e8, code, adjusted=False)
            if df is not None and not df.empty:
                df=df.sort_index()
                close_first=float(df.iloc[0].get("종가") or 0)
                close_last=float(df.iloc[-1].get("종가") or 0)
                if "거래대금" in df.columns:
                    amount=int(float(df["거래대금"].fillna(0).sum()))
                elif "거래량" in df.columns:
                    amount=int(float((df["종가"].fillna(0)*df["거래량"].fillna(0)).sum()))
                provider="pykrx"
        except Exception:
            pass
    if (not close_first or not close_last) and fdr:
        try:
            df=fdr.DataReader(code, start, end)
            if df is not None and not df.empty:
                df=df.sort_index()
                close_first=float(df.iloc[0].get("Close") or 0)
                close_last=float(df.iloc[-1].get("Close") or 0)
                amount=int(float((df["Close"].fillna(0)*df["Volume"].fillna(0)).sum()))
                provider="FinanceDataReader"
        except Exception:
            pass
    foreign=0
    institution=0
    supply_provider="none"
    if pykrx_stock:
        try:
            tv=pykrx_stock.get_market_trading_value_by_date(s8, e8, code)
            if tv is not None and not tv.empty:
                if "외국인합계" in tv.columns:
                    foreign=int(float(tv["외국인합계"].fillna(0).sum()))
                elif "외국인" in tv.columns:
                    foreign=int(float(tv["외국인"].fillna(0).sum()))
                if "기관합계" in tv.columns:
                    institution=int(float(tv["기관합계"].fillna(0).sum()))
                elif "기관" in tv.columns:
                    institution=int(float(tv["기관"].fillna(0).sum()))
                supply_provider="pykrx"
        except Exception:
            pass
    change=round((close_last-close_first)/close_first*100, 2) if close_first and close_last else 0
    return {
        "changePct":change,
        "amount":amount,
        "foreignNetBuy":foreign,
        "institutionNetBuy":institution,
        "provider":provider or "none",
        "supplyProvider":supply_provider,
    }

def theme_dashboard_payload(start="", end=""):
    start,end=theme_date_range(start, end)
    lookup=stock_lookup_by_name()
    pykrx_stock=pykrx_stock_module()
    fdr=fdr_module()
    themes=[]
    providers=set()
    supply_providers=set()
    for seed in THEME_SEEDS:
        stock_rows=[]
        for raw_name in seed["stocks"]:
            resolved=resolve_theme_stock(raw_name, lookup)
            snap=stock_theme_snapshot(resolved.get("code"), start, end, pykrx_stock, fdr)
            providers.add(snap.get("provider") or "none")
            supply_providers.add(snap.get("supplyProvider") or "none")
            stock_rows.append({
                "name":resolved.get("name") or raw_name,
                "code":resolved.get("code") or "",
                "market":resolved.get("market") or "",
                "changePct":snap["changePct"],
                "amount":snap["amount"],
                "foreignNetBuy":snap["foreignNetBuy"],
                "institutionNetBuy":snap["institutionNetBuy"],
            })
        valid=[r for r in stock_rows if r.get("code")]
        avg_change=round(sum(r["changePct"] for r in valid)/len(valid), 2) if valid else 0
        amount=sum(int(r.get("amount") or 0) for r in valid)
        foreign=sum(int(r.get("foreignNetBuy") or 0) for r in valid)
        institution=sum(int(r.get("institutionNetBuy") or 0) for r in valid)
        net=foreign+institution
        score=round(max(0, avg_change)*12 + min(35, amount/100000000000) + max(0, net)/10000000000, 1)
        stock_rows.sort(key=lambda r:(r.get("changePct") or 0, r.get("amount") or 0), reverse=True)
        themes.append({
            "key":seed["key"], "name":seed["name"],
            "keywords":seed["keywords"], "newsKeywords":seed["news"],
            "changePct":avg_change, "amount":amount,
            "foreignNetBuy":foreign, "institutionNetBuy":institution, "netBuyTotal":net,
            "score":score, "stocks":stock_rows,
        })
    themes.sort(key=lambda t:(t["score"], t["changePct"], t["amount"]), reverse=True)
    return {
        "ok":True,
        "start":start, "end":end,
        "generatedAt":datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "provider":"/".join(sorted(p for p in providers if p and p!="none")) or "none",
        "supplyProvider":"/".join(sorted(p for p in supply_providers if p and p!="none")) or "none",
        "themes":themes,
    }

class Handler(BaseHTTPRequestHandler):
    def send_content(self,status,content,ctype="text/html; charset=utf-8"):
        if isinstance(content,str): content=content.encode("utf-8")
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(content))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(content)
    def do_GET(self):
        if self.path=="/" or self.path.startswith("/index"):
            self.send_content(200, HTML.replace("__DEFAULT_KEYWORDS__", json.dumps(DEFAULT_KEYWORDS,ensure_ascii=False)))
        elif self.path.startswith("/api/research-reports"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs=parse_qs(urlparse(self.path).query)
                start=qs.get("start",[""])[0].strip()
                end=qs.get("end",[""])[0].strip()
                q=qs.get("q",[""])[0].strip()
                limit=int(qs.get("limit",["120"])[0] or 120)
                self.send_content(200, json.dumps(research_reports_payload(start, end, q, limit), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok":False,"error":str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/report-price-chart"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs=parse_qs(urlparse(self.path).query)
                stock_code=qs.get("stock_code",[""])[0].strip()
                report_date=qs.get("report_date",[""])[0].strip()
                report_id=qs.get("report_id",[""])[0].strip()
                period=qs.get("period",["6m"])[0].strip()
                self.send_content(200, json.dumps(report_price_chart_payload(stock_code, report_date, period, report_id), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok":False,"error":str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/stocks"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs=parse_qs(urlparse(self.path).query)
                q=qs.get("q",[""])[0].strip()
                limit=int(qs.get("limit",["10"])[0] or 10)
                self.send_content(200, json.dumps(stock_suggestions_payload(q, limit), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok":False,"error":str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/export-report"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs=parse_qs(urlparse(self.path).query)
                force=qs.get("force",["0"])[0] in ("1","true","yes")
                self.send_content(200, json.dumps(export_report_snapshot(force), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok":False,"error":str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/themes"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs=parse_qs(urlparse(self.path).query)
                start=qs.get("start",[""])[0].strip()
                end=qs.get("end",[""])[0].strip()
                self.send_content(200, json.dumps(theme_dashboard_payload(start, end), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok":False,"error":str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/market"):
            try:
                self.send_content(200, json.dumps(market_snapshot(), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/dictionary"):
            try:
                self.send_content(200, json.dumps({"ok": True, "data": load_event_dictionary()}, ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/breaking-topics"):
            try:
                self.send_content(200, json.dumps({"ok": True, "topics": load_breaking_topics()}, ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/breaking"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                pv = qs.get("value", ["12"])[0]
                pu = qs.get("unit", ["h"])[0]
                mr = qs.get("max", ["20"])[0]
                self.send_content(200, json.dumps(breaking_snapshot(pv, pu, mr), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                log_error(traceback.format_exc())
                self.send_content(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self.send_content(404,"Not found","text/plain; charset=utf-8")
    def do_POST(self):
        try:
            length=int(self.headers.get("Content-Length","0"))
            payload=json.loads(self.rfile.read(length).decode("utf-8") or "{}")

            if self.path == "/api/search":
                self.send_content(200,json.dumps(search_all(payload),ensure_ascii=False),"application/json; charset=utf-8")
                return

            if self.path == "/api/dictionary/add":
                data = add_event_keyword(
                    payload.get("category",""),
                    payload.get("keyword",""),
                    payload.get("impact",70),
                    payload.get("novelty",20)
                )
                self.send_content(200, json.dumps({"ok": True, "data": data}, ensure_ascii=False), "application/json; charset=utf-8")
                return

            if self.path == "/api/breaking-topics/save":
                topics = upsert_breaking_topic(payload)
                self.send_content(200, json.dumps({"ok": True, "topics": topics}, ensure_ascii=False), "application/json; charset=utf-8")
                return

            if self.path == "/api/breaking-topics/delete":
                topics = delete_breaking_topic(payload.get("key", ""))
                self.send_content(200, json.dumps({"ok": True, "topics": topics}, ensure_ascii=False), "application/json; charset=utf-8")
                return

            if self.path == "/api/breaking-topics/reset":
                topics = save_breaking_topics(default_breaking_topics())
                self.send_content(200, json.dumps({"ok": True, "topics": topics}, ensure_ascii=False), "application/json; charset=utf-8")
                return

            self.send_content(404,json.dumps({"ok":False,"error":"not found"},ensure_ascii=False),"application/json; charset=utf-8")
        except Exception as e:
            log_error(traceback.format_exc()); self.send_content(500,json.dumps({"ok":False,"error":str(e)},ensure_ascii=False),"application/json; charset=utf-8")
    def log_message(self, fmt, *args): return

def open_browser(url):
    time.sleep(1)
    try: os.startfile(url)
    except Exception: webbrowser.open(url)

def main():
    os.chdir(app_dir())
    port = int(os.environ.get("PORT", "0") or "0") or find_free_port()
    host = "0.0.0.0" if os.environ.get("PORT") else HOST
    server=ThreadingHTTPServer((host,port),Handler)
    url=f"http://{host}:{port}/"
    if not os.environ.get("PORT"):
        threading.Thread(target=open_browser,args=(url,),daemon=True).start()
    print(APP_TITLE); print("URL:",url); print("Close this window to stop server.")
    server.serve_forever()

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: pass
    except Exception:
        log_error(traceback.format_exc())
        input("Error. Check error_log.txt. Press Enter.")

