# modules/dashboard_v2.py v2.0
"""
Dashboard v2 avec graphiques Chart.js
- Courbe alertes par heure
- Courbe tokens analysés
- Heatmap bulls détectés
- Top tokens
- PnL portfolio
"""

import asyncio
import os
import time
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from utils.logger import get_logger

logger = get_logger("dashboard_v2")


HTML_V2 = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MemeSniper v13 Dashboard Pro</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Courier New',monospace;background:#0a0a0a;color:#ccc;padding:0}
.header{background:#111;padding:14px 20px;border-bottom:2px solid #00ff41;
        display:flex;align-items:center;gap:12px;flex-wrap:wrap;position:sticky;top:0;z-index:100}
.header h1{color:#00ff41;font-size:1.3em;font-weight:bold}
.dot{width:10px;height:10px;background:#00ff41;border-radius:50%;
     flex-shrink:0;animation:blink 1s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.ws-badge{font-size:.75em;padding:2px 8px;border-radius:10px;
          background:#0a2a0a;color:#00ff41;border:1px solid #00ff41}
.ws-badge.err{background:#2a0a0a;color:#ff4444;border-color:#ff4444}
.uptime{margin-left:auto;color:#555;font-size:.8em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
      gap:14px;padding:14px}
.card{background:#111;border:1px solid #1e1e1e;border-radius:8px;padding:14px}
.card-title{color:#ff6600;font-size:.85em;font-weight:bold;text-transform:uppercase;
            letter-spacing:.05em;margin-bottom:10px;padding-bottom:8px;
            border-bottom:1px solid #1e1e1e}
.row{display:flex;justify-content:space-between;align-items:center;
     padding:5px 0;border-bottom:1px solid #141414;font-size:.82em}
.row:last-child{border:none}
.lbl{color:#555}
.val{font-weight:bold;text-align:right}
.g{color:#00ff41}.r{color:#ff4444}.o{color:#ff8800}
.y{color:#ffcc00}.gr{color:#666}.b{color:#00aaff}
.full{grid-column:1/-1}
.wide{grid-column:span 2}
.chart-container{position:relative;height:200px;margin-top:8px}
.feed-wrap{background:#080808;border-radius:6px;padding:8px;
           height:250px;overflow-y:auto;margin-top:6px}
.feed-line{padding:3px 0;border-bottom:1px solid #111;
           font-size:.78em;color:#777;display:flex;gap:8px}
.feed-time{color:#333;flex-shrink:0}
.section-title{color:#444;font-size:.75em;text-transform:uppercase;
               letter-spacing:.1em;margin:10px 0 4px}
.stat-big{font-size:2em;font-weight:bold;text-align:center;margin:10px 0}
.tabs{display:flex;gap:0;margin-bottom:14px;border-bottom:1px solid #1e1e1e}
.tab{padding:10px 20px;cursor:pointer;color:#666;font-size:.85em;
     border-bottom:2px solid transparent;transition:all .2s}
.tab.active{color:#00ff41;border-bottom-color:#00ff41}
.tab-content{display:none}
.tab-content.active{display:block}
</style>
</head>
<body>

<div class="header">
  <div class="dot"></div>
  <h1>MemeSniper v13 PRO</h1>
  <span class="ws-badge" id="ws-badge">LIVE</span>
  <span class="uptime" id="uptime-txt">--</span>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('overview')">📊 Overview</div>
  <div class="tab" onclick="switchTab('charts')">📈 Charts</div>
  <div class="tab" onclick="switchTab('portfolio')">💼 Portfolio</div>
  <div class="tab" onclick="switchTab('bulls')">🎯 Bulls</div>
</div>

<!-- TAB OVERVIEW -->
<div class="tab-content active" id="tab-overview">
<div class="grid">

  <div class="card">
    <div class="card-title">🤖 Bot</div>
    <div class="row"><span class="lbl">État</span><span class="val" id="b-state">--</span></div>
    <div class="row"><span class="lbl">Uptime</span><span class="val gr" id="b-up">--</span></div>
    <div class="row"><span class="lbl">Alertes</span><span class="val y" id="b-alerts">0</span></div>
    <div class="row"><span class="lbl">Sell alerts</span><span class="val b" id="b-sells">0</span></div>
    <div class="row"><span class="lbl">Analyses</span><span class="val gr" id="b-analyzed">0</span></div>
    <div class="row"><span class="lbl">En cours</span><span class="val gr" id="b-proc">0</span></div>
    <div class="row"><span class="lbl">WebSocket</span><span class="val" id="b-ws">--</span></div>
  </div>

  <div class="card">
    <div class="card-title">🌍 Marché</div>
    <div class="row"><span class="lbl">BTC 24h</span><span class="val" id="m-btc">--</span></div>
    <div class="row"><span class="lbl">SOL 24h</span><span class="val" id="m-sol">--</span></div>
    <div class="row"><span class="lbl">Fear Greed</span><span class="val" id="m-fg">--</span></div>
    <div class="row"><span class="lbl">Régime</span><span class="val" id="m-mood">--</span></div>
    <div class="row"><span class="lbl">Score min</span><span class="val y" id="m-minscore">7.5</span></div>
  </div>

  <div class="card">
    <div class="card-title">🛡️ Sécurité</div>
    <div class="row"><span class="lbl">Tokens checkés</span><span class="val" id="s-total">0</span></div>
    <div class="row"><span class="lbl">Bloqués</span><span class="val r" id="s-blocked">0</span></div>
    <div class="row"><span class="lbl">Honeypots</span><span class="val r" id="s-honey">0</span></div>
    <div class="row"><span class="lbl">Liq faible</span><span class="val o" id="s-liq">0</span></div>
    <div class="row"><span class="lbl">Taux blocage</span><span class="val" id="s-rate">0%</span></div>
  </div>

  <div class="card">
    <div class="card-title">🎯 Modules v13</div>
    <div class="row"><span class="lbl">Bulls</span><span class="val g" id="mod-bulls">0</span></div>
    <div class="row"><span class="lbl">Momentum</span><span class="val o" id="mod-momentum">0</span></div>
    <div class="row"><span class="lbl">Positions</span><span class="val y" id="mod-positions">0</span></div>
    <div class="row"><span class="lbl">Wallets trackés</span><span class="val b" id="mod-wallets">0</span></div>
    <div class="row"><span class="lbl">Candidats</span><span class="val g" id="mod-candidates">0</span></div>
    <div class="row"><span class="lbl">Optimisations</span><span class="val y" id="mod-opts">0</span></div>
    <div class="row"><span class="lbl">ML trades</span><span class="val b" id="mod-ml">0</span></div>
  </div>

  <div class="card full">
    <div class="card-title">📡 Live Feed <span style="font-size:.75em;color:#444;font-weight:normal;margin-left:8px">(temps réel)</span></div>
    <div class="feed-wrap" id="feed">
      <div class="feed-line"><span class="feed-time">--:--:--</span><span>En attente...</span></div>
    </div>
  </div>

</div>
</div>

<!-- TAB CHARTS -->
<div class="tab-content" id="tab-charts">
<div class="grid">

  <div class="card wide">
    <div class="card-title">📈 Tokens analysés (dernières 24h)</div>
    <div class="chart-container"><canvas id="chart-analyzed"></canvas></div>
  </div>

  <div class="card wide">
    <div class="card-title">🚨 Alertes envoyées (dernières 24h)</div>
    <div class="chart-container"><canvas id="chart-alerts"></canvas></div>
  </div>

  <div class="card">
    <div class="card-title">🛡️ Répartition Safety</div>
    <div class="chart-container"><canvas id="chart-safety"></canvas></div>
  </div>

  <div class="card">
    <div class="card-title">🔥 Sources détection</div>
    <div class="chart-container"><canvas id="chart-sources"></canvas></div>
  </div>

</div>
</div>

<!-- TAB PORTFOLIO -->
<div class="tab-content" id="tab-portfolio">
<div class="grid">

  <div class="card">
    <div class="card-title">💼 Portefeuille</div>
    <div class="stat-big g" id="p-value">0€</div>
    <div class="row"><span class="lbl">Investi total</span><span class="val" id="p-invested">0€</span></div>
    <div class="row"><span class="lbl">PnL réalisé</span><span class="val" id="p-realized">0€</span></div>
    <div class="row"><span class="lbl">PnL non-réalisé</span><span class="val" id="p-unrealized">0€</span></div>
    <div class="row"><span class="lbl">Positions ouvertes</span><span class="val y" id="p-open">0</span></div>
    <div class="row"><span class="lbl">Trades totaux</span><span class="val gr" id="p-trades">0</span></div>
  </div>

  <div class="card">
    <div class="card-title">📊 PnL par période</div>
    <div class="row"><span class="lbl">Aujourd'hui</span><span class="val" id="pnl-day">0€</span></div>
    <div class="row"><span class="lbl">7 jours</span><span class="val" id="pnl-week">0€</span></div>
    <div class="row"><span class="lbl">30 jours</span><span class="val" id="pnl-month">0€</span></div>
    <div class="row"><span class="lbl">All-time</span><span class="val" id="pnl-all">0€</span></div>
    <div class="row"><span class="lbl">Win rate</span><span class="val" id="pnl-wr">0%</span></div>
  </div>

  <div class="card wide">
    <div class="card-title">📈 Évolution PnL</div>
    <div class="chart-container"><canvas id="chart-pnl"></canvas></div>
  </div>

</div>
</div>

<!-- TAB BULLS -->
<div class="tab-content" id="tab-bulls">
<div class="grid">

  <div class="card">
    <div class="card-title">🎯 Bull Analyzer</div>
    <div class="stat-big g" id="ba-total">0</div>
    <div class="row"><span class="lbl">Bulls détectés (7j)</span><span class="val" id="ba-7d">0</span></div>
    <div class="row"><span class="lbl">Gain moyen</span><span class="val g" id="ba-avg">0%</span></div>
    <div class="row"><span class="lbl">Scans effectués</span><span class="val gr" id="ba-scans">0</span></div>
  </div>

  <div class="card">
    <div class="card-title">🔍 Wallet Discovery</div>
    <div class="stat-big b" id="wd-wallets">0</div>
    <div class="row"><span class="lbl">Wallets trackés</span><span class="val" id="wd-tracked">0</span></div>
    <div class="row"><span class="lbl">Bulls analysés</span><span class="val" id="wd-bulls">0</span></div>
    <div class="row"><span class="lbl">Candidats prêts</span><span class="val g" id="wd-candidates">0</span></div>
  </div>

  <div class="card wide">
    <div class="card-title">⏰ Heatmap - Heures des bulls (UTC)</div>
    <div class="chart-container"><canvas id="chart-heatmap"></canvas></div>
  </div>

</div>
</div>

<script>
let ws, reconnTimer;
let charts = {};

// Historique pour les graphiques
let historyAnalyzed = [];
let historyAlerts = [];
let historyTime = [];

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + tab).classList.add('active');

  // Init charts si nécessaire
  setTimeout(() => initCharts(), 50);
}

function initCharts() {
  // Chart Analyzed
  if (!charts.analyzed && document.getElementById('chart-analyzed')) {
    charts.analyzed = new Chart(document.getElementById('chart-analyzed'), {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Analyses/min',
          data: [],
          borderColor: '#00ff41',
          backgroundColor: 'rgba(0,255,65,0.1)',
          tension: 0.3,
          fill: true,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#666' } } },
        scales: {
          x: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' } },
          y: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' } }
        }
      }
    });
  }

  if (!charts.alerts && document.getElementById('chart-alerts')) {
    charts.alerts = new Chart(document.getElementById('chart-alerts'), {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'Alertes',
          data: [],
          backgroundColor: '#ffcc00',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#666' } } },
        scales: {
          x: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' } },
          y: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' }, beginAtZero: true }
        }
      }
    });
  }

  if (!charts.safety && document.getElementById('chart-safety')) {
    charts.safety = new Chart(document.getElementById('chart-safety'), {
      type: 'doughnut',
      data: {
        labels: ['OK', 'Bloqués'],
        datasets: [{
          data: [0, 0],
          backgroundColor: ['#00ff41', '#ff4444'],
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#666' } } }
      }
    });
  }

  if (!charts.sources && document.getElementById('chart-sources')) {
    charts.sources = new Chart(document.getElementById('chart-sources'), {
      type: 'polarArea',
      data: {
        labels: ['Pump.fun', 'Copy', 'Twitter', 'Whales', 'Raydium'],
        datasets: [{
          data: [0, 0, 0, 0, 0],
          backgroundColor: [
            'rgba(0,255,65,0.6)',
            'rgba(255,204,0,0.6)',
            'rgba(0,170,255,0.6)',
            'rgba(255,136,0,0.6)',
            'rgba(255,68,68,0.6)',
          ],
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#666' } } }
      }
    });
  }

  if (!charts.pnl && document.getElementById('chart-pnl')) {
    charts.pnl = new Chart(document.getElementById('chart-pnl'), {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'PnL cumulé (€)',
          data: [],
          borderColor: '#00aaff',
          backgroundColor: 'rgba(0,170,255,0.1)',
          tension: 0.3,
          fill: true,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#666' } } },
        scales: {
          x: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' } },
          y: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' } }
        }
      }
    });
  }

  if (!charts.heatmap && document.getElementById('chart-heatmap')) {
    charts.heatmap = new Chart(document.getElementById('chart-heatmap'), {
      type: 'bar',
      data: {
        labels: Array.from({length:24},(_,i)=>i+'h'),
        datasets: [{
          label: 'Bulls par heure',
          data: Array(24).fill(0),
          backgroundColor: '#ff6600',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#666' } } },
        scales: {
          x: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' } },
          y: { ticks: { color: '#555' }, grid: { color: '#1e1e1e' }, beginAtZero: true }
        }
      }
    });
  }
}

function connect(){
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');
  ws.onopen = () => {
    document.getElementById('ws-badge').className = 'ws-badge';
    document.getElementById('ws-badge').textContent = 'LIVE';
    addFeed('Connecté au dashboard');
    clearTimeout(reconnTimer);
    initCharts();
  };
  ws.onmessage = (e) => {
    try { render(JSON.parse(e.data)); } catch(err) { console.error(err); }
  };
  ws.onclose = () => {
    document.getElementById('ws-badge').className = 'ws-badge err';
    document.getElementById('ws-badge').textContent = 'OFFLINE';
    addFeed('Connexion perdue - reconnexion dans 5s...');
    reconnTimer = setTimeout(connect, 5000);
  };
  ws.onerror = () => ws.close();
}

function render(d){
  // Overview
  const up = d.uptime || 0;
  const h = Math.floor(up/3600), m = Math.floor((up%3600)/60), s = Math.floor(up%60);
  const upStr = h+'h '+m+'m '+s+'s';
  set('b-up', upStr);
  set('uptime-txt', 'Uptime: '+upStr);

  const running = !d.paused;
  setC('b-state', running ? 'Actif' : 'PAUSE', running ? 'val g' : 'val o');
  set('b-alerts', d.alerts_sent || 0);
  set('b-sells', d.sell_alerts || 0);
  set('b-analyzed', d.tokens_analyzed || 0);
  set('b-proc', d.processing || 0);
  setC('b-ws', d.ws_active ? 'Actif' : 'Inactif', d.ws_active ? 'val g' : 'val r');

  // Marché
  const mkt = d.market || {};
  setChg('m-btc', mkt.btc_24h);
  setChg('m-sol', mkt.sol_24h);
  set('m-fg', mkt.fear_greed || '--');
  set('m-mood', mkt.regime || '--');

  // Safety
  const saf = d.safety || {};
  set('s-total', saf.total || 0);
  set('s-blocked', saf.blocked || 0);
  set('s-honey', saf.honey || 0);
  set('s-liq', saf.liq || 0);
  const rate = saf.total > 0 ? ((saf.blocked/saf.total)*100).toFixed(0)+'%' : '0%';
  set('s-rate', rate);

  // Modules v13
  set('mod-bulls', d.bulls_count || 0);
  set('mod-momentum', d.momentum_alerts || 0);
  set('mod-positions', d.positions_open || 0);
  set('mod-wallets', d.wallets_tracked || 0);
  set('mod-candidates', d.wallet_candidates || 0);
  set('mod-opts', d.optimizations || 0);
  set('mod-ml', d.ml_trades || 0);

  // Portfolio
  const port = d.portfolio || {};
  const totVal = (port.total_open_value || 0) + (port.total_pnl || 0);
  set('p-value', totVal.toFixed(0) + '€');
  set('p-invested', (port.total_invested || 0).toFixed(0) + '€');
  const realized = port.total_pnl || 0;
  const unrealized = port.total_open_pnl_eur || 0;
  setC('p-realized', (realized >= 0 ? '+' : '') + realized.toFixed(0) + '€',
       realized >= 0 ? 'val g' : 'val r');
  setC('p-unrealized', (unrealized >= 0 ? '+' : '') + unrealized.toFixed(0) + '€',
       unrealized >= 0 ? 'val g' : 'val r');
  set('p-open', port.open_positions || 0);
  set('p-trades', port.total_trades || 0);

  // PnL par période
  const pnl = d.pnl_periods || {};
  setC('pnl-day', (pnl.pnl_day >= 0 ? '+' : '') + (pnl.pnl_day || 0).toFixed(0) + '€',
       (pnl.pnl_day || 0) >= 0 ? 'val g' : 'val r');
  setC('pnl-week', (pnl.pnl_week >= 0 ? '+' : '') + (pnl.pnl_week || 0).toFixed(0) + '€',
       (pnl.pnl_week || 0) >= 0 ? 'val g' : 'val r');
  setC('pnl-month', (pnl.pnl_month >= 0 ? '+' : '') + (pnl.pnl_month || 0).toFixed(0) + '€',
       (pnl.pnl_month || 0) >= 0 ? 'val g' : 'val r');
  setC('pnl-all', (pnl.pnl_all >= 0 ? '+' : '') + (pnl.pnl_all || 0).toFixed(0) + '€',
       (pnl.pnl_all || 0) >= 0 ? 'val g' : 'val r');
  set('pnl-wr', (pnl.win_rate_all || 0).toFixed(0) + '%');

  // Bulls tab
  const ba = d.bull_analyzer || {};
  set('ba-total', ba.total || 0);
  set('ba-7d', ba.total || 0);
  set('ba-avg', '+' + (ba.avg_gain || 0).toFixed(0) + '%');
  set('ba-scans', d.bulls_scans || 0);

  const wd = d.wallet_discovery || {};
  set('wd-wallets', wd.wallets_tracked || 0);
  set('wd-tracked', wd.wallets_tracked || 0);
  set('wd-bulls', wd.bulls_analyzed || 0);
  set('wd-candidates', wd.candidates_ready || 0);

  // Update charts
  updateCharts(d);

  // Events
  if(d.events && d.events.length){
    d.events.forEach(ev => addFeed(ev));
  }
}

function updateCharts(d) {
  const now = new Date().toLocaleTimeString('fr-FR');

  // Historique analyses
  historyTime.push(now);
  historyAnalyzed.push(d.tokens_analyzed || 0);
  historyAlerts.push(d.alerts_sent || 0);

  if (historyTime.length > 20) {
    historyTime.shift();
    historyAnalyzed.shift();
    historyAlerts.shift();
  }

  if (charts.analyzed) {
    charts.analyzed.data.labels = historyTime;
    charts.analyzed.data.datasets[0].data = historyAnalyzed;
    charts.analyzed.update('none');
  }

  if (charts.alerts) {
    charts.alerts.data.labels = historyTime;
    charts.alerts.data.datasets[0].data = historyAlerts;
    charts.alerts.update('none');
  }

  if (charts.safety) {
    const saf = d.safety || {};
    const ok = (saf.total || 0) - (saf.blocked || 0);
    charts.safety.data.datasets[0].data = [ok, saf.blocked || 0];
    charts.safety.update('none');
  }

  if (charts.sources) {
    charts.sources.data.datasets[0].data = [
      d.tokens_analyzed || 0,
      d.copy_trades || 0,
      d.twitter_signals || 0,
      0,  // whales
      d.raydium_tokens || 0,
    ];
    charts.sources.update('none');
  }

  if (charts.heatmap && d.bull_hours) {
    const hourData = Array(24).fill(0);
    Object.entries(d.bull_hours).forEach(([h, count]) => {
      hourData[parseInt(h)] = count;
    });
    charts.heatmap.data.datasets[0].data = hourData;
    charts.heatmap.update('none');
  }
}

function set(id, val){
  const el = document.getElementById(id);
  if(el) el.textContent = val;
}
function setC(id, val, cls){
  const el = document.getElementById(id);
  if(!el) return;
  el.textContent = val;
  el.className = cls || 'val';
}
function setChg(id, val){
  const el = document.getElementById(id);
  if(!el) return;
  if(val === undefined || val === null){ el.textContent = '--'; return; }
  el.textContent = (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
  el.className = 'val ' + (val >= 0 ? 'g' : 'r');
}
function addFeed(msg){
  const feed = document.getElementById('feed');
  if(!feed) return;
  const now = new Date().toLocaleTimeString('fr-FR');
  const line = document.createElement('div');
  line.className = 'feed-line';
  line.innerHTML = '<span class="feed-time">' + now + '</span><span>' + msg + '</span>';
  feed.prepend(line);
  while(feed.children.length > 100) feed.removeChild(feed.lastChild);
}

connect();
setTimeout(initCharts, 500);
</script>
</body>
</html>"""


class DashboardServerV2:

    def __init__(self, bot, host="0.0.0.0", port=8080):
        self.bot = bot
        self.port = int(
            os.environ.get("PORT") or
            os.environ.get("DASHBOARD_PORT") or
            port
        )
        self.host = os.environ.get("DASHBOARD_HOST", host)

        self.app = FastAPI(title="MemeSniper Dashboard v2", docs_url=None)
        self._clients = []
        self._events = []
        self.safety_stats = {
            "total": 0, "blocked": 0, "honey": 0, "liq": 0
        }
        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return HTML_V2

        @app.get("/health")
        async def health():
            return {
                "status": "ok",
                "service": "MemeSniper v13.0",
                "uptime": time.time() - getattr(self.bot, 'start_time', time.time()),
            }

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            self._clients.append(ws)
            try:
                while True:
                    data = self._collect()
                    await ws.send_json(data)
                    self._events.clear()
                    await asyncio.sleep(3)
            except (WebSocketDisconnect, Exception):
                pass
            finally:
                if ws in self._clients:
                    self._clients.remove(ws)

    def _collect(self):
        """Collecte toutes les données du bot"""
        bot = self.bot
        uptime = time.time() - getattr(bot, 'start_time', time.time())

        # Market
        market = {}
        try:
            sig = bot.market_context.get_market_signal()
            market = {
                "btc_24h": sig.get("btc_change_24h"),
                "sol_24h": sig.get("sol_change_24h"),
                "fear_greed": sig.get("fear_greed"),
                "regime": sig.get("regime", "?"),
            }
        except Exception:
            pass

        # Portfolio
        portfolio = {}
        pnl_periods = {}
        try:
            if hasattr(bot, 'portfolio_tracker'):
                portfolio = bot.portfolio_tracker.get_portfolio_summary()
                pnl_periods = bot.portfolio_tracker.get_pnl_by_period()
        except Exception:
            pass

        # Bull analyzer
        bull_analyzer = {}
        bull_hours = {}
        try:
            if hasattr(bot, 'bull_analyzer'):
                stats = bot.bull_analyzer.get_stats(days=7)
                bull_analyzer = {
                    "total": stats.get("total", 0),
                    "avg_gain": stats.get("avg_gain", 0),
                }
                if stats.get("hours"):
                    for h, c in stats["hours"]:
                        bull_hours[h] = c
        except Exception:
            pass

        # Wallet discovery
        wallet_discovery = {}
        try:
            if hasattr(bot, 'wallet_discovery'):
                wallet_discovery = bot.wallet_discovery.get_stats()
        except Exception:
            pass

        # Sell generator
        sell_stats = {}
        try:
            if hasattr(bot, 'sell_generator'):
                sell_stats = bot.sell_generator.get_stats()
        except Exception:
            pass

        # ML
        ml_trades = 0
        try:
            if hasattr(bot, 'ml_scorer'):
                ml_trades = bot.ml_scorer.get_stats().get('trades', 0)
        except Exception:
            pass

        # Optimizer
        optimizations = 0
        try:
            if hasattr(bot, 'auto_optimizer'):
                optimizations = bot.auto_optimizer.get_stats().get('total_optimizations', 0)
        except Exception:
            pass

        # Bulls count
        bulls_count = 0
        bulls_scans = 0
        try:
            if hasattr(bot, 'bull_analyzer'):
                bulls_count = len(bot.bull_analyzer.bulls)
                bulls_scans = bot.bull_analyzer.tokens_scanned
        except Exception:
            pass

        return {
            "uptime": uptime,
            "paused": getattr(bot, 'paused', False),
            "alerts_sent": getattr(bot, 'alerts_sent', 0),
            "sell_alerts": getattr(bot, 'sell_alerts_sent', 0),
            "tokens_analyzed": getattr(bot, 'tokens_analyzed', 0),
            "processing": len(getattr(bot, 'processing_tokens', set())),
            "ws_active": getattr(bot, 'ws_active', False),
            "copy_trades": getattr(bot, 'copy_trades', 0),
            "twitter_signals": getattr(bot, 'twitter_signals', 0),
            "raydium_tokens": getattr(bot, 'raydium_tokens', 0),
            "momentum_alerts": getattr(bot, 'momentum_alerts', 0),
            "market": market,
            "safety": self.safety_stats,
            "portfolio": portfolio,
            "pnl_periods": pnl_periods,
            "bull_analyzer": bull_analyzer,
            "bull_hours": bull_hours,
            "wallet_discovery": wallet_discovery,
            "bulls_count": bulls_count,
            "bulls_scans": bulls_scans,
            "wallets_tracked": wallet_discovery.get("wallets_tracked", 0),
            "wallet_candidates": wallet_discovery.get("candidates_ready", 0),
            "positions_open": sell_stats.get("positions_open", 0),
            "ml_trades": ml_trades,
            "optimizations": optimizations,
            "events": list(self._events),
        }

    def add_event(self, msg):
        self._events.append(msg)
        if len(self._events) > 30:
            self._events.pop(0)

    def record_safety(self, result):
        self.safety_stats["total"] += 1
        if not result.get("safe"):
            self.safety_stats["blocked"] += 1
            reasons = " ".join(result.get("reasons", []))
            if "honeypot" in reasons.lower():
                self.safety_stats["honey"] += 1
            if "liquidit" in reasons.lower():
                self.safety_stats["liq"] += 1

    async def start(self):
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="error",
            access_log=False,
        )
        server = uvicorn.Server(config)
        logger.info(f"📊 Dashboard v2 → http://{self.host}:{self.port}")
        await server.serve()

    async def stop(self):
        logger.info("📊 Dashboard v2 arrêté")