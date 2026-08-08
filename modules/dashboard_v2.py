# modules/dashboard_v2.py — v14.1-EVOLUTION
"""
Dashboard v14.1 compatible Railway/local.

Améliorations :
- Titre MemeSniper v14.1-EVOLUTION
- Sections Overview / Evolution / Risk / Simulator
- Event Store / Feature Store / Auto-ML / Strategy / Drift Guard
- Performance Analyzer winners/losers
- Paper Trading Only / Auto Buy OFF
- Compatible Railway avec DASHBOARD_HOST / DASHBOARD_PORT / PORT
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from utils.logger import get_logger


logger = get_logger("dashboard_v2")


HTML_V2 = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MemeSniper v14.1-EVOLUTION</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Courier New',monospace;background:#070707;color:#d0d0d0}
.header{background:#101010;padding:14px 20px;border-bottom:2px solid #00ff41;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10}
h1{color:#00ff41;font-size:1.25rem}
.dot{width:10px;height:10px;background:#00ff41;border-radius:50%;animation:blink 1s infinite}
@keyframes blink{50%{opacity:.25}}
.badge{font-size:.75rem;padding:3px 9px;border-radius:12px;border:1px solid #00ff41;color:#00ff41;background:#062006}
.badge.red{border-color:#ff4444;color:#ff4444;background:#220606}
.spacer{flex:1}
.muted{color:#666}
.tabs{display:flex;border-bottom:1px solid #1e1e1e;background:#0d0d0d;overflow-x:auto}
.tab{padding:12px 20px;cursor:pointer;color:#777;border-bottom:2px solid transparent;white-space:nowrap}
.tab.active{color:#00ff41;border-color:#00ff41}
.content{display:none;padding:14px}
.content.active{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px}
.card{background:#111;border:1px solid #202020;border-radius:8px;padding:14px}
.full{grid-column:1/-1}
.title{color:#ff7a00;font-weight:bold;font-size:.86rem;letter-spacing:.04em;text-transform:uppercase;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #202020}
.row{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid #171717;font-size:.86rem}
.row:last-child{border:0}
.lbl{color:#666}
.val{font-weight:bold;text-align:right}
.g{color:#00ff41}
.r{color:#ff4444}
.y{color:#ffcc00}
.o{color:#ff8800}
.b{color:#00aaff}
.gr{color:#777}
.big{font-size:2rem;text-align:center;font-weight:bold;margin:10px 0}
.feed{height:260px;overflow:auto;background:#080808;border-radius:6px;padding:8px}
.line{font-size:.8rem;color:#aaa;border-bottom:1px solid #151515;padding:4px 0}
.time{color:#444;margin-right:8px}
.pill{display:inline-block;padding:2px 7px;border-radius:999px;background:#181818;border:1px solid #333;font-size:.75rem}
.table{width:100%;border-collapse:collapse;font-size:.82rem}
.table th,.table td{padding:7px;border-bottom:1px solid #1b1b1b;text-align:left}
.table th{color:#ff7a00}
.table td:last-child{text-align:right}
.warn{border-color:#553500;background:#180f00}
.danger{border-color:#5a1111;background:#180707}
.small{font-size:.78rem;color:#777;line-height:1.45}
</style>
</head>
<body>

<div class="header">
  <div class="dot"></div>
  <h1>MemeSniper v14.1-EVOLUTION</h1>
  <span id="live" class="badge">LIVE</span>
  <span class="badge">PAPER ONLY</span>
  <span class="badge red">AUTO BUY OFF</span>
  <div class="spacer"></div>
  <span id="uptime" class="muted">--</span>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab(event, 'overview')">📊 Overview</div>
  <div class="tab" onclick="switchTab(event, 'evolution')">🧬 Evolution</div>
  <div class="tab" onclick="switchTab(event, 'risk')">🛡️ Risk</div>
  <div class="tab" onclick="switchTab(event, 'trades')">🎮 Simulator</div>
</div>

<div id="overview" class="content active">
  <div class="grid">

    <div class="card">
      <div class="title">🤖 Bot</div>
      <div class="row"><span class="lbl">État</span><span id="state" class="val g">--</span></div>
      <div class="row"><span class="lbl">Uptime</span><span id="up2" class="val gr">--</span></div>
      <div class="row"><span class="lbl">Alertes</span><span id="alerts" class="val y">0</span></div>
      <div class="row"><span class="lbl">Alertes/h</span><span id="alerts_hour" class="val">0</span></div>
      <div class="row"><span class="lbl">Analyses</span><span id="analyzed" class="val gr">0</span></div>
      <div class="row"><span class="lbl">En cours</span><span id="processing" class="val gr">0</span></div>
      <div class="row"><span class="lbl">WebSocket</span><span id="ws" class="val">--</span></div>
    </div>

    <div class="card">
      <div class="title">🌍 Marché</div>
      <div class="row"><span class="lbl">BTC 24h</span><span id="btc" class="val">--</span></div>
      <div class="row"><span class="lbl">SOL 24h</span><span id="sol" class="val">--</span></div>
      <div class="row"><span class="lbl">Fear Greed</span><span id="fg" class="val">--</span></div>
      <div class="row"><span class="lbl">Régime</span><span id="regime" class="val">--</span></div>
      <div class="row"><span class="lbl">Score min</span><span id="minscore" class="val y">--</span></div>
    </div>

    <div class="card">
      <div class="title">🛡️ Sécurité</div>
      <div class="row"><span class="lbl">Tokens checkés</span><span id="s_total" class="val">0</span></div>
      <div class="row"><span class="lbl">Bloqués</span><span id="s_blocked" class="val r">0</span></div>
      <div class="row"><span class="lbl">Honeypots</span><span id="s_honey" class="val r">0</span></div>
      <div class="row"><span class="lbl">Liq faible</span><span id="s_liq" class="val o">0</span></div>
      <div class="row"><span class="lbl">Taux blocage</span><span id="s_rate" class="val">0%</span></div>
    </div>

    <div class="card">
      <div class="title">🎯 Modules</div>
      <div class="row"><span class="lbl">Bulls</span><span id="bulls" class="val g">0</span></div>
      <div class="row"><span class="lbl">Momentum</span><span id="momentum" class="val o">0</span></div>
      <div class="row"><span class="lbl">Positions</span><span id="positions" class="val y">0</span></div>
      <div class="row"><span class="lbl">Wallets</span><span id="wallets" class="val b">0</span></div>
      <div class="row"><span class="lbl">Candidats</span><span id="candidates" class="val g">0</span></div>
      <div class="row"><span class="lbl">ML trades</span><span id="ml" class="val b">0</span></div>
    </div>

    <div class="card full">
      <div class="title">📡 Live Feed</div>
      <div id="feed" class="feed">
        <div class="line"><span class="time">--:--:--</span>Connexion...</div>
      </div>
    </div>

  </div>
</div>

<div id="evolution" class="content">
  <div class="grid">

    <div class="card">
      <div class="title">🧬 Orchestrator</div>
      <div class="row"><span class="lbl">Auto-Evolution</span><span id="ev_enabled" class="val g">--</span></div>
      <div class="row"><span class="lbl">Event Store</span><span id="ev_events" class="val">0</span></div>
      <div class="row"><span class="lbl">Events 24h</span><span id="ev_events_24h" class="val">0</span></div>
      <div class="row"><span class="lbl">DB</span><span id="ev_db" class="val gr">--</span></div>
      <div class="row"><span class="lbl">Feature Store</span><span id="ev_features" class="val">0</span></div>
    </div>

    <div class="card">
      <div class="title">🤖 Auto-ML</div>
      <div class="row"><span class="lbl">Mode</span><span id="ml_mode" class="val">--</span></div>
      <div class="row"><span class="lbl">Model loaded</span><span id="ml_loaded" class="val">--</span></div>
      <div class="row"><span class="lbl">Fallback</span><span id="ml_fallback" class="val y">--</span></div>
    </div>

    <div class="card">
      <div class="title">📈 Strategy Optimizer</div>
      <div class="row"><span class="lbl">Threshold</span><span id="st_threshold" class="val y">--</span></div>
      <div class="row"><span class="lbl">Samples</span><span id="st_samples" class="val">--</span></div>
      <div class="row"><span class="lbl">Objectif</span><span id="st_obj" class="val">--</span></div>
      <div class="row"><span class="lbl">Last opt</span><span id="st_last" class="val gr">--</span></div>
    </div>

    <div class="card">
      <div class="title">🛡️ Drift Guard</div>
      <div class="row"><span class="lbl">Status</span><span id="dr_status" class="val">--</span></div>
      <div class="row"><span class="lbl">Score drift</span><span id="dr_score" class="val">--</span></div>
      <div class="row"><span class="lbl">Trading paused</span><span id="dr_pause" class="val">false</span></div>
      <div class="row"><span class="lbl">Evol paused</span><span id="dr_epause" class="val">false</span></div>
      <div class="row"><span class="lbl">Last check</span><span id="dr_last" class="val gr">--</span></div>
    </div>

  </div>
</div>

<div id="risk" class="content">
  <div class="grid">

    <div class="card">
      <div class="title">⚙️ Réglages Risk</div>
      <div class="row"><span class="lbl">Max alertes/h</span><span id="cfg_maxh" class="val y">--</span></div>
      <div class="row"><span class="lbl">SIM check</span><span id="sim_check" class="val">--</span></div>
      <div class="row"><span class="lbl">SIM SL</span><span id="sim_sl" class="val r">--</span></div>
      <div class="row"><span class="lbl">SIM TP</span><span id="sim_tp" class="val g">--</span></div>
      <div class="row"><span class="lbl">Max age</span><span id="sim_max_age" class="val">--</span></div>
    </div>

    <div class="card">
      <div class="title">📊 Performance Analyzer</div>
      <div class="row"><span class="lbl">Closed</span><span id="pa_closed" class="val">0</span></div>
      <div class="row"><span class="lbl">WR</span><span id="pa_wr" class="val">0%</span></div>
      <div class="row"><span class="lbl">ROI</span><span id="pa_roi" class="val">0%</span></div>
      <div class="row"><span class="lbl">Big losses</span><span id="pa_big" class="val r">0</span></div>
      <div class="row"><span class="lbl">Rug-like</span><span id="pa_rugs" class="val r">0</span></div>
    </div>

    <div class="card full">
      <div class="title">✅ Recommandations</div>
      <div id="reco" class="feed"></div>
    </div>

  </div>
</div>

<div id="trades" class="content">
  <div class="grid">

    <div class="card">
      <div class="title">🎮 Simulator</div>
      <div class="big" id="sim_roi">0%</div>
      <div class="row"><span class="lbl">Simulés</span><span id="sim_total" class="val">0</span></div>
      <div class="row"><span class="lbl">Ouverts</span><span id="sim_open" class="val y">0</span></div>
      <div class="row"><span class="lbl">Fermés</span><span id="sim_closed" class="val">0</span></div>
      <div class="row"><span class="lbl">Wins/Losses</span><span id="sim_wl" class="val">0/0</span></div>
      <div class="row"><span class="lbl">Win rate</span><span id="sim_wr" class="val">0%</span></div>
      <div class="row"><span class="lbl">PnL</span><span id="sim_pnl" class="val">0€</span></div>
      <div class="row"><span class="lbl">Aujourd'hui</span><span id="sim_day" class="val">0€</span></div>
      <div class="row"><span class="lbl">7 jours</span><span id="sim_week" class="val">0€</span></div>
    </div>

    <div class="card">
      <div class="title">🏆 Best / Worst</div>
      <div class="row"><span class="lbl">Best</span><span id="best_trade" class="val g">--</span></div>
      <div class="row"><span class="lbl">Worst</span><span id="worst_trade" class="val r">--</span></div>
      <div class="row"><span class="lbl">Big losses</span><span id="sim_big_losses" class="val r">0</span></div>
      <div class="row"><span class="lbl">Durée moy</span><span id="sim_avg_duration" class="val">--</span></div>
    </div>

    <div class="card full">
      <div class="title">📋 Derniers trades</div>
      <table class="table">
        <thead>
          <tr>
            <th>Token</th>
            <th>Tier</th>
            <th>Reason</th>
            <th>PnL</th>
          </tr>
        </thead>
        <tbody id="trades_body"></tbody>
      </table>
    </div>

  </div>
</div>

<script>
let ws = null;
let reconnTimer = null;

function switchTab(ev, id){
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
  if(ev && ev.target) ev.target.classList.add('active');
  const el = document.getElementById(id);
  if(el) el.classList.add('active');
}

function $(id){
  return document.getElementById(id);
}

function set(id, value, cls){
  const el = $(id);
  if(!el) return;
  el.textContent = (value === undefined || value === null || value === '') ? '--' : value;
  if(cls) el.className = 'val ' + cls;
}

function pct(value){
  if(value === undefined || value === null || isNaN(Number(value))) return '--';
  const n = Number(value);
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
}

function clsNum(value){
  return Number(value || 0) >= 0 ? 'g' : 'r';
}

function euro(value){
  const n = Number(value || 0);
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '€';
}

function duration(sec){
  sec = Number(sec || 0);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return h + 'h ' + m + 'm ' + s + 's';
}

function shortDate(value){
  if(!value) return '--';
  try{
    return String(value).replace('T', ' ').slice(0, 19);
  }catch(e){
    return '--';
  }
}

function addFeed(msg){
  const f = $('feed');
  if(!f) return;
  const d = document.createElement('div');
  d.className = 'line';
  d.innerHTML = '<span class="time">' + new Date().toLocaleTimeString('fr-FR') + '</span>' + String(msg);
  f.prepend(d);
  while(f.children.length > 120) f.removeChild(f.lastChild);
}

function renderRecommendations(list){
  const reco = $('reco');
  if(!reco) return;
  reco.innerHTML = '';
  if(!list || !list.length){
    const div = document.createElement('div');
    div.className = 'line';
    div.textContent = 'Aucune recommandation pour le moment.';
    reco.appendChild(div);
    return;
  }
  list.forEach(x => {
    const div = document.createElement('div');
    div.className = 'line';
    div.textContent = '• ' + x;
    reco.appendChild(div);
  });
}

function tradeLabel(t){
  if(!t) return '--';
  const sym = t.symbol || '?';
  const pnl = Number(t.pnl_pct || 0);
  return '$' + sym + ' ' + pct(pnl);
}

function updateTrades(trades){
  const body = $('trades_body');
  if(!body) return;
  body.innerHTML = '';
  (trades || []).forEach(t => {
    const tr = document.createElement('tr');
    const p = Number(t.pnl_pct || 0);
    tr.innerHTML =
      '<td>$' + (t.symbol || '?') + '</td>' +
      '<td>' + (t.alert_tier || '?') + '</td>' +
      '<td>' + (t.exit_reason || '') + '</td>' +
      '<td class="' + clsNum(p) + '">' + pct(p) + '</td>';
    body.appendChild(tr);
  });
}

function update(d){
  d = d || {};

  const up = d.uptime || 0;
  $('uptime').textContent = 'Uptime: ' + duration(up);
  set('up2', duration(up), 'gr');

  set('state', d.paused ? 'Pause' : 'Actif', d.paused ? 'r' : 'g');
  set('alerts', d.alerts_sent || 0, 'y');
  set('alerts_hour', d.alerts_per_hour || 0, (d.alerts_per_hour || 0) > 10 ? 'o' : 'g');
  set('analyzed', d.tokens_analyzed || 0, 'gr');
  set('processing', d.processing || 0, 'gr');
  set('ws', d.ws_active ? 'Actif' : 'Off', d.ws_active ? 'g' : 'r');

  const m = d.market || {};
  set('btc', pct(m.btc_24h), clsNum(m.btc_24h || 0));
  set('sol', pct(m.sol_24h), clsNum(m.sol_24h || 0));
  set('fg', m.fear_greed);
  set('regime', m.regime);
  set('minscore', d.config ? d.config.min_score : '--', 'y');
  set('cfg_maxh', d.config ? d.config.max_alerts_per_hour : '--', 'y');

  const s = d.safety || {};
  set('s_total', s.total || 0);
  set('s_blocked', s.blocked || 0, 'r');
  set('s_honey', s.honey || 0, 'r');
  set('s_liq', s.liq || 0, 'o');
  set('s_rate', ((s.blocked || 0) / Math.max(s.total || 0, 1) * 100).toFixed(0) + '%');

  set('bulls', d.bulls_count || 0, 'g');
  set('momentum', d.momentum_alerts || 0, 'o');
  set('positions', d.positions_open || 0, 'y');
  set('wallets', d.wallets_tracked || 0, 'b');
  set('candidates', d.wallet_candidates || 0, 'g');
  set('ml', d.ml_trades || 0, 'b');

  const ev = d.evolution || {};
  set('ev_enabled', ev.enabled ? 'ACTIF' : 'OFF', ev.enabled ? 'g' : 'r');
  set('ev_events', ev.event_store ? ev.event_store.total_events || 0 : 0);
  set('ev_events_24h', ev.event_store ? ev.event_store.events_24h || 0 : 0);
  set('ev_db', ev.event_store ? ev.event_store.db_path || '--' : '--', 'gr');
  set('ev_features', ev.feature_store ? ev.feature_store.features_loaded || 0 : 0);

  const am = ev.auto_ml || {};
  set('ml_mode', am.mode || (am.last_metrics ? am.last_metrics.status : 'heuristic'), 'y');
  set('ml_loaded', am.model_loaded ? 'true' : 'false', am.model_loaded ? 'g' : 'gr');
  set('ml_fallback', am.fallback_available ? 'yes' : 'no', 'y');

  const st = ev.strategy || {};
  set('st_threshold', Number(st.alert_threshold || 0).toFixed(2), 'y');
  set('st_samples', st.samples_used || 0);
  set('st_obj', Number(st.objective_score || 0).toFixed(2));
  set('st_last', shortDate(st.last_optimized_at), 'gr');

  const dr = ev.drift_guard || {};
  set('dr_status', dr.status || 'unknown', dr.status === 'stable' ? 'g' : 'o');
  set('dr_score', Number(dr.last_drift_score || 0).toFixed(2));
  set('dr_pause', dr.trading_paused ? 'true' : 'false', dr.trading_paused ? 'r' : 'g');
  set('dr_epause', dr.auto_evolution_paused ? 'true' : 'false', dr.auto_evolution_paused ? 'r' : 'g');
  set('dr_last', shortDate(dr.last_check_at), 'gr');

  const sim = d.simulator || {};
  set('sim_total', sim.total_simulated || 0);
  set('sim_open', sim.open_positions || 0, 'y');
  set('sim_closed', sim.closed_positions || 0);
  set('sim_wl', (sim.wins || 0) + '/' + (sim.losses || 0));
  set('sim_wr', (sim.win_rate || 0) + '%', (sim.win_rate || 0) >= 40 ? 'g' : 'o');
  set('sim_pnl', euro(sim.total_pnl), clsNum(sim.total_pnl || 0));
  set('sim_day', euro(sim.pnl_day), clsNum(sim.pnl_day || 0));
  set('sim_week', euro(sim.pnl_week), clsNum(sim.pnl_week || 0));
  set('sim_roi', pct(sim.roi_pct), clsNum(sim.roi_pct || 0));

  const simRoi = $('sim_roi');
  if(simRoi) simRoi.className = 'big ' + clsNum(sim.roi_pct || 0);

  set('sim_check', sim.settings ? (sim.settings.check_interval || '--') + 's' : '--');
  set('sim_sl', sim.settings ? (sim.settings.sl_pct || '--') + '%' : '--', 'r');
  set('sim_tp', sim.settings ? '+' + (sim.settings.tp_pct || '--') + '%' : '--', 'g');
  set('sim_max_age', sim.settings ? (sim.settings.max_age_hours || '--') + 'h' : '--');

  set('best_trade', tradeLabel(sim.best_trade), 'g');
  set('worst_trade', tradeLabel(sim.worst_trade), 'r');
  set('sim_big_losses', sim.big_losses || 0, (sim.big_losses || 0) > 0 ? 'r' : 'g');
  set('sim_avg_duration', (sim.avg_duration_min || 0).toFixed(0) + 'min');

  const pa = (d.performance_analyzer && d.performance_analyzer.summary) ? d.performance_analyzer.summary : {};
  set('pa_closed', pa.closed || 0);
  set('pa_wr', (pa.win_rate || 0) + '%', (pa.win_rate || 0) >= 40 ? 'g' : 'o');
  set('pa_roi', pct(pa.roi_pct || 0), clsNum(pa.roi_pct || 0));
  set('pa_big', pa.big_losses || 0, (pa.big_losses || 0) > 0 ? 'r' : 'g');
  set('pa_rugs', pa.rug_like_losses || 0, (pa.rug_like_losses || 0) > 0 ? 'r' : 'g');

  renderRecommendations(d.performance_analyzer ? d.performance_analyzer.recommendations || [] : []);
  updateTrades(d.recent_trades || []);

  if(d.events && d.events.length){
    d.events.forEach(addFeed);
  }
}

function connect(){
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');

  ws.onopen = () => {
    $('live').textContent = 'LIVE';
    $('live').className = 'badge';
    addFeed('Connecté au dashboard v14.1');
    clearTimeout(reconnTimer);
  };

  ws.onmessage = e => {
    try{
      update(JSON.parse(e.data));
    }catch(err){
      console.error(err);
    }
  };

  ws.onclose = () => {
    $('live').textContent = 'OFF';
    $('live').className = 'badge red';
    addFeed('Connexion perdue - reconnexion dans 3s...');
    reconnTimer = setTimeout(connect, 3000);
  };

  ws.onerror = () => {
    try{ ws.close(); }catch(e){}
  };
}

connect();
</script>
</body>
</html>"""


class DashboardServerV2:
    def __init__(self, bot, host: str = "0.0.0.0", port: int = 8080):
        self.bot = bot
        self.port = int(
            os.environ.get("PORT")
            or os.environ.get("DASHBOARD_PORT")
            or port
        )
        self.host = os.environ.get("DASHBOARD_HOST", host)

        self.app = FastAPI(
            title="MemeSniper v14.1-EVOLUTION Dashboard",
            docs_url=None,
            redoc_url=None,
        )

        self._clients: list[WebSocket] = []
        self._events: list[str] = []
        self.safety_stats = {
            "total": 0,
            "blocked": 0,
            "honey": 0,
            "liq": 0,
        }

        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return HTML_V2

        @app.get("/health")
        async def health():
            return JSONResponse(
                {
                    "status": "ok",
                    "service": "MemeSniper v14.1-EVOLUTION",
                    "uptime": time.time()
                    - getattr(self.bot, "start_time", time.time()),
                    "paper_trading_only": True,
                    "auto_trading": False,
                }
            )

        @app.get("/api/status")
        async def api_status():
            return JSONResponse(self._collect())

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

    def _safe_call(self, fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    def _collect(self) -> Dict[str, Any]:
        bot = self.bot
        uptime = time.time() - getattr(bot, "start_time", time.time())

        # Market
        market = {}
        try:
            market = bot.market_context.get_market_signal()
        except Exception:
            market = {}

        # Portfolio
        portfolio = {}
        pnl_periods = {}
        try:
            if hasattr(bot, "portfolio_tracker"):
                portfolio = bot.portfolio_tracker.get_portfolio_summary()
                pnl_periods = bot.portfolio_tracker.get_pnl_by_period()
        except Exception:
            pass

        # Sell stats
        sell_stats = {}
        try:
            if hasattr(bot, "sell_generator"):
                sell_stats = bot.sell_generator.get_stats()
        except Exception:
            pass

        # Wallet discovery
        wallet_stats = {}
        try:
            if hasattr(bot, "wallet_discovery"):
                wallet_stats = bot.wallet_discovery.get_stats()
        except Exception:
            pass

        # ML stats
        ml_stats = {}
        try:
            if hasattr(bot, "ml_scorer"):
                ml_stats = bot.ml_scorer.get_stats()
        except Exception:
            pass

        # Optimizer stats
        opt_stats = {}
        try:
            if hasattr(bot, "auto_optimizer"):
                opt_stats = bot.auto_optimizer.get_stats()
        except Exception:
            pass

        # Simulator stats
        sim_stats = {}
        recent_trades = []
        try:
            if hasattr(bot, "simulator"):
                sim_stats = bot.simulator.get_stats()
                recent_trades = bot.simulator.get_recent_trades(15)
        except Exception:
            pass

        # Evolution
        evolution: Dict[str, Any] = {
            "enabled": bool(getattr(bot, "_evolution_started", False))
        }

        try:
            if hasattr(bot, "event_store") and bot.event_store is not None:
                if hasattr(bot.event_store, "get_status"):
                    evolution["event_store"] = bot.event_store.get_status()
                else:
                    evolution["event_store"] = {}
        except Exception:
            evolution["event_store"] = {}

        try:
            if hasattr(bot, "feature_store") and bot.feature_store is not None:
                if hasattr(bot.feature_store, "get_status"):
                    evolution["feature_store"] = bot.feature_store.get_status()
                else:
                    evolution["feature_store"] = {}
        except Exception:
            evolution["feature_store"] = {}

        try:
            if hasattr(bot, "auto_ml") and bot.auto_ml is not None:
                if hasattr(bot.auto_ml, "get_status"):
                    evolution["auto_ml"] = bot.auto_ml.get_status()
                else:
                    evolution["auto_ml"] = {}
        except Exception:
            evolution["auto_ml"] = {}

        try:
            if hasattr(bot, "strategy_optimizer") and bot.strategy_optimizer is not None:
                if hasattr(bot.strategy_optimizer, "get_current_strategy"):
                    evolution["strategy"] = bot.strategy_optimizer.get_current_strategy()
                else:
                    evolution["strategy"] = {}
        except Exception:
            evolution["strategy"] = {}

        try:
            if hasattr(bot, "drift_guard") and bot.drift_guard is not None:
                if hasattr(bot.drift_guard, "get_status"):
                    evolution["drift_guard"] = bot.drift_guard.get_status()
                else:
                    evolution["drift_guard"] = {}
        except Exception:
            evolution["drift_guard"] = {}

        # Performance Analyzer
        perf_status = {}
        try:
            from modules.evolution.performance_analyzer import (
                get_performance_analyzer,
            )

            perf_status = get_performance_analyzer().get_status()
        except Exception:
            perf_status = {}

        alerts_sent = getattr(bot, "alerts_sent", 0)
        alerts_per_hour = round(alerts_sent / max(uptime / 3600, 1 / 60), 2)

        # Bulls
        bulls_count = 0
        bulls_scans = 0
        try:
            if hasattr(bot, "bull_analyzer"):
                bulls_count = len(getattr(bot.bull_analyzer, "bulls", []) or [])
                bulls_scans = getattr(bot.bull_analyzer, "tokens_scanned", 0)
        except Exception:
            pass

        return {
            "version": "14.1-EVOLUTION",
            "uptime": uptime,
            "paused": getattr(bot, "paused", False),
            "alerts_sent": alerts_sent,
            "alerts_per_hour": alerts_per_hour,
            "sell_alerts": getattr(bot, "sell_alerts_sent", 0),
            "tokens_analyzed": getattr(bot, "tokens_analyzed", 0),
            "processing": len(getattr(bot, "processing_tokens", set())),
            "ws_active": getattr(bot, "ws_active", False),
            "copy_trades": getattr(bot, "copy_trades", 0),
            "twitter_signals": getattr(bot, "twitter_signals", 0),
            "raydium_tokens": getattr(bot, "raydium_tokens", 0),
            "momentum_alerts": getattr(bot, "momentum_alerts", 0),
            "market": {
                "btc_24h": market.get("btc_change_24h"),
                "sol_24h": market.get("sol_change_24h"),
                "fear_greed": market.get("fear_greed"),
                "regime": market.get("regime", "?"),
            },
            "config": {
                "min_score": getattr(
                    getattr(bot, "config", None), "min_score", None
                ),
                "max_alerts_per_hour": getattr(
                    getattr(bot, "config", None), "max_alerts_per_hour", None
                ),
            },
            "safety": self.safety_stats,
            "portfolio": portfolio,
            "pnl_periods": pnl_periods,
            "bulls_count": bulls_count,
            "bulls_scans": bulls_scans,
            "wallets_tracked": wallet_stats.get("wallets_tracked", 0),
            "wallet_candidates": wallet_stats.get("candidates_ready", 0),
            "positions_open": sell_stats.get("positions_open", 0),
            "ml_trades": ml_stats.get("trades", 0),
            "optimizations": opt_stats.get("total_optimizations", 0),
            "simulator": sim_stats,
            "recent_trades": recent_trades,
            "evolution": evolution,
            "performance_analyzer": perf_status,
            "events": list(self._events),
            "paper_trading_only": True,
            "auto_trading": False,
        }

    def add_event(self, msg: str):
        self._events.append(str(msg))

        if len(self._events) > 100:
            self._events = self._events[-100:]

    def record_safety(self, result: dict):
        self.safety_stats["total"] += 1

        if not result.get("safe"):
            self.safety_stats["blocked"] += 1

            reasons = " ".join(
                result.get("reasons", []) + result.get("warnings", [])
            )
            low = reasons.lower()

            if "honeypot" in low:
                self.safety_stats["honey"] += 1

            if "liquid" in low or "liq" in low:
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

        logger.info(
            f"📊 Dashboard v14.1 → http://{self.host}:{self.port}"
        )

        await server.serve()

    async def stop(self):
        logger.info("📊 Dashboard v14.1 arrêté")