
# -*- coding: utf-8 -*-
import json, os, re, socket, threading, time, traceback, webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

APP_TITLE = "주식 속보 뉴스 이벤트 대시보드 v25 Lite Render"
HOST = "127.0.0.1"
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
<title>주식 속보 뉴스 이벤트 대시보드 v25 Lite Render</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#101418;--panel:#171d23;--line:#2b3542;--text:#e8edf2;--muted:#9fb0bf;--blue:#2f81f7;--chip:#26384d;--warn:#ffb86c;--err:#ff8585;--ok:#8aff8a}
body{font-family:"Malgun Gothic",Arial,sans-serif;margin:0;background:var(--bg);color:var(--text)}
.wrap{max-width:1600px;margin:0 auto;padding:24px}
h1{margin:0 0 8px;font-size:28px}.desc{color:var(--muted);margin-bottom:18px}.box{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(126px,1fr));gap:8px}
label.kw{background:#202832;border:1px solid #344151;border-radius:10px;padding:8px 10px;cursor:pointer;display:block}
label:hover{background:#283241}
textarea,select,input[type=number],input[type=text]{background:#0d1116;color:var(--text);border:1px solid #344151;border-radius:10px;padding:10px;box-sizing:border-box}
textarea{width:100%;height:78px;font-size:15px}select,input[type=number],input[type=text]{font-size:15px}input[type=number]{width:90px}
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

</style>
</head>
<body>
<div class="wrap">
<div class="toolbar">
<h1>📰 주식 속보 뉴스 이벤트 대시보드 v25 Lite Render</h1>
<div class="desc">뉴스검색, 속보뉴스, 매크로만 남긴 경량화 버전입니다.</div>
<div class="tabs">
  <button class="tabbtn active" onclick="showTab('searchTab', this)">뉴스검색</button>
  <button class="tabbtn" onclick="showTab('breakingTab', this); loadBreakingNews();">속보뉴스</button>
  <button class="tabbtn" onclick="showTab('macroTab', this)">매크로</button>
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




<div class="box"><h2>🧾 검색 요약</h2><div id="summary" class="meta">아직 검색 전입니다.</div></div>
<div class="box"><h2>🕸️ 키워드 연결 그래프</h2><div class='meta'>노랑=핵심/종목/시장 키워드, 초록=신규 테마 후보, 파랑=후보 키워드. 글씨 크기는 고정. Kiwi ON이면 명사 중심 추출.</div><div id="graph" class="graph"><div class="meta" style="padding:16px">검색 후 표시됩니다.</div></div></div>
<div class="box"><h2>📰 뉴스 제목</h2><div id="status" class="meta">검색 전입니다. 검색 요약이나 그래프 노드를 클릭하면 관련 뉴스가 펼쳐집니다.</div><div id="newsSections"></div></div>

</div>

<div id="breakingTab" class="tabcontent">
<div class="box">
<h2>⚡ 속보뉴스</h2>
<div class="row">
<input id="breakingValue" type="number" min="1" max="30" value="12">
<select id="breakingUnit"><option value="h" selected>시간</option><option value="d">일</option><option value="w">주</option></select>
<select id="breakingMax"><option value="10">주제별 10개</option><option value="20" selected>주제별 20개</option><option value="50">주제별 50개</option></select>
<button onclick="loadBreakingNews()" style="background:#246b45">속보 새로고침</button>
<span class="meta">주제별 뉴스 건수는 미리 정한 검색 묶음별 수집 건수입니다. 시장 강도 판단은 아직 아닙니다.</span>
</div>
<div id="breakingStatus" class="meta" style="margin-top:10px">속보 탭을 열면 요약 카드만 먼저 표시됩니다. 카드를 클릭하면 뉴스가 펼쳐집니다.</div>
</div>
<div class="box">
<h2>📊 주제별 뉴스 건수</h2>
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
<span class="meta">나스닥 / 달러지수 / 원달러환율 / 미국10년물 국채금리 / WTI 유가 / 금, 최근 30일</span>
</div>
<div id="marketStatus" class="meta" style="margin-top:10px">아직 불러오기 전입니다.</div>
<div id="marketGrid" class="marketgrid"></div>
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


async function fetchJson(url, options){
  const res = await fetch(url, options);
  const text = await res.text();
  let data;
  try{
    data = JSON.parse(text);
  }catch(e){
    throw new Error("서버가 JSON이 아닌 응답을 반환했습니다: " + text.slice(0, 200));
  }
  if(!res.ok || data.ok === false){
    throw new Error(data.error || ("HTTP " + res.status));
  }
  return data;
}


function init(){
  document.getElementById("extraKeywords").addEventListener("input", clearResultsOnly);
  document.getElementById("periodValue").addEventListener("change", clearResultsOnly);
  document.getElementById("periodUnit").addEventListener("change", clearResultsOnly);
  document.getElementById("maxResults").addEventListener("change", clearResultsOnly);
  document.getElementById("sortBy").addEventListener("change", clearResultsOnly);
  document.getElementById("summary").innerHTML="<span class='ok'>준비 완료. 조건을 입력하고 검색하세요.</span>";
  loadMarketCharts();
}

function getPayload(){
  return {
    periodValue: document.getElementById("periodValue").value,
    periodUnit: document.getElementById("periodUnit").value,
    maxResults: document.getElementById("maxResults").value,
    sortBy: document.getElementById("sortBy").value,
    checkedKeywords:[],
    extraKeywords: document.getElementById("extraKeywords").value
  };
}

function clearAll(){
  LAST_DATA = null;
  document.getElementById("extraKeywords").value="";
  document.getElementById("summary").innerHTML="<span class='ok'>초기화 완료.</span>";
  document.getElementById("graph").innerHTML="<div class='meta' style='padding:16px'>검색 후 표시됩니다.</div>";
  document.getElementById("newsSections").innerHTML="";
  document.getElementById("status").textContent="검색 전입니다.";
}

function clearResultsOnly(){
  LAST_DATA = null;
  document.getElementById("summary").innerHTML = "<span class='warn'>검색 조건이 변경되었습니다. 다시 검색하세요.</span>";
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
  el.innerHTML="<div class='meta'>검색 요약 버튼 또는 그래프 노드를 클릭하면 관련 뉴스가 여기에 표시됩니다.</div>";
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
  document.getElementById("graph").innerHTML="<div class='meta' style='padding:16px'>그래프 생성 중...</div>";
  document.getElementById("newsSections").innerHTML="";
  document.getElementById("status").innerHTML="새 검색을 실행 중입니다...";
  try{
    const data=await fetchJson("/api/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(getPayload())});
    if(!data.ok){document.getElementById("summary").innerHTML=`<span class="err">${data.error}</span>`; btn.disabled=false; return;}
    LAST_DATA=data;
    document.getElementById("summary").innerHTML=renderSummary(data);
    bindSummaryButtons();
    renderGraph(data); renderNewsSections(data);
    document.getElementById("status").innerHTML="<span class='ok'>검색 완료. 요약 버튼/그래프 노드를 클릭하면 관련 뉴스가 펼쳐집니다.</span>";
  }catch(e){document.getElementById("summary").innerHTML=`<span class="err">오류: ${e.message}</span>`;}
  btn.disabled=false;
}



function showTab(tabId, btn){
  document.querySelectorAll(".tabcontent").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".tabbtn").forEach(x=>x.classList.remove("active"));
  const el=document.getElementById(tabId);
  if(el) el.classList.add("active");
  if(btn) btn.classList.add("active");
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
    const data=await fetchJson(`/api/breaking?value=${encodeURIComponent(v)}&unit=${encodeURIComponent(u)}&max=${encodeURIComponent(m)}`);
    if(!data.ok){
      status.innerHTML=`<span class="err">${data.error || "속보 로드 실패"}</span>`;
      return;
    }

    status.innerHTML=`<span class="ok">${data.periodLabel} / 전체 ${data.total}건 / 업데이트 ${data.generatedAt}</span>` + (data.errors && data.errors.length ? `<br><span class="warn">${data.errors.join(" / ")}</span>` : "");

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
    const data=await fetchJson("/api/market");
    if(!data.ok){
      status.innerHTML=`<span class="err">${data.error || "매크로 데이터 오류"}</span>`;
      return;
    }
    status.innerHTML=`<span class="ok">업데이트: ${data.generatedAt}</span>` + (data.errors && data.errors.length ? `<br><span class="warn">${data.errors.join(" / ")}</span>` : "");
    data.items.forEach(item=>renderMarketCard(item, grid));
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
        {"key": "nasdaq", "name": "나스닥", "symbol": "^IXIC", "days": 30, "unit": ""},
        {"key": "dxy", "name": "달러지수", "symbol": "DX-Y.NYB", "days": 30, "unit": ""},
        {"key": "usdkrw", "name": "원달러환율", "symbol": "KRW=X", "days": 30, "unit": "원"},
        {"key": "us10y", "name": "미국10년물 국채금리", "symbol": "^TNX", "days": 30, "unit": "%"},
        {"key": "wti", "name": "WTI 유가", "symbol": "CL=F", "days": 30, "unit": "$"},
        {"key": "gold", "name": "금", "symbol": "GC=F", "days": 30, "unit": "$"},
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



BREAKING_TOPICS = [
    {"name": "한국증시", "query": "한국 증시 OR 코스피 OR 코스닥"},
    {"name": "속보", "query": "속보 증시 OR 주식 속보"},
    {"name": "반도체", "query": "반도체 OR HBM OR 삼성전자 OR SK하이닉스"},
    {"name": "AI", "query": "AI OR 인공지능 OR 엔비디아 OR 데이터센터"},
    {"name": "바이오", "query": "바이오 OR 제약 OR FDA OR 임상"},
    {"name": "방산", "query": "방산 OR 전쟁 OR 수주"},
    {"name": "원전전력", "query": "원전 OR 원자력 OR 전력망 OR 변압기"},
    {"name": "2차전지", "query": "2차전지 OR 배터리 OR 리튬 OR 전기차"},
    {"name": "로봇", "query": "로봇 OR 휴머노이드 OR 피지컬AI"},
    {"name": "거시", "query": "환율 OR 금리 OR 유가 OR 국채금리 OR 연준"}
]


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

    for t in BREAKING_TOPICS:
        try:
            items = search_google_breaking(t["name"], t["query"], period_when, max_per_topic)
            items = dedupe_breaking_items(items)
            topic_results.append({"name": t["name"], "count": len(items), "items": items})
            all_items.extend(items)
        except Exception as e:
            errors.append(f"{t['name']}: {e}")
            topic_results.append({"name": t["name"], "count": 0, "items": []})
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
        "total": len(all_items),
        "topItems": top_items,
        "keywordStats": keyword_stats[:20],
        "errors": errors
    }


class Handler(BaseHTTPRequestHandler):
    def send_content(self,status,content,ctype="text/html; charset=utf-8"):
        if isinstance(content,str): content=content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(content)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, payload):
        try:
            content = json.dumps(payload, ensure_ascii=False)
        except Exception:
            content = json.dumps({"ok": False, "error": "JSON encode failed"}, ensure_ascii=False)
        self.send_content(status, content, "application/json; charset=utf-8")

    def do_GET(self):
        try:
            if self.path=="/" or self.path.startswith("/index"):
                self.send_content(200, HTML.replace("__DEFAULT_KEYWORDS__", json.dumps(DEFAULT_KEYWORDS,ensure_ascii=False)))
                return

            if self.path.startswith("/api/market"):
                self.send_json(200, market_snapshot())
                return

            if self.path.startswith("/api/dictionary"):
                self.send_json(200, {"ok": True, "data": load_event_dictionary()})
                return

            if self.path.startswith("/api/breaking"):
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                pv = qs.get("value", ["12"])[0]
                pu = qs.get("unit", ["h"])[0]
                mr = qs.get("max", ["20"])[0]
                self.send_json(200, breaking_snapshot(pv, pu, mr))
                return

            self.send_content(404,"Not found","text/plain; charset=utf-8")
        except Exception as e:
            log_error(traceback.format_exc())
            self.send_json(500, {"ok": False, "error": str(e), "trace": traceback.format_exc()})

    def do_POST(self):
        try:
            length=int(self.headers.get("Content-Length","0"))
            payload=json.loads(self.rfile.read(length).decode("utf-8") or "{}")

            if self.path == "/api/search":
                self.send_json(200, search_all(payload))
                return

            if self.path == "/api/dictionary/add":
                data = add_event_keyword(
                    payload.get("category",""),
                    payload.get("keyword",""),
                    payload.get("impact",70),
                    payload.get("novelty",20)
                )
                self.send_json(200, {"ok": True, "data": data})
                return

            self.send_json(404, {"ok":False,"error":"not found","path":self.path})
        except Exception as e:
            log_error(traceback.format_exc())
            self.send_json(500, {"ok":False,"error":str(e), "trace": traceback.format_exc()})

    def log_message(self, fmt, *args): return

def open_browser(url):
    time.sleep(1)
    try: os.startfile(url)
    except Exception: webbrowser.open(url)

def main():
    os.chdir(app_dir())

    if os.environ.get("RENDER") or os.environ.get("PORT"):
        host = "0.0.0.0"
        port = int(os.environ.get("PORT", "10000"))
        open_url = None
    else:
        host = HOST
        port = find_free_port()
        open_url = f"http://{host}:{port}/"

    server=ThreadingHTTPServer((host,port),Handler)
    url=f"http://{host}:{port}/"

    if open_url:
        threading.Thread(target=open_browser,args=(open_url,),daemon=True).start()

    print(APP_TITLE); print("URL:",url); print("Close this window to stop server.")
    server.serve_forever()

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: pass
    except Exception:
        log_error(traceback.format_exc())
        input("Error. Check error_log.txt. Press Enter.")
