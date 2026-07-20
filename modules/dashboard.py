# modules/dashboard.py v2.0
"""
Dashboard web temps réel
Local  : http://localhost:8080
Railway: https://[ton-url].up.railway.app
Mise à jour automatique toutes les 3 secondes
"""

import asyncio
import os
import time
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from utils.logger import get_logger

logger = get_logger("dashboard")

HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MemeSniper v12 Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Courier New',monospace;background:#0a0a0a;color:#ccc}
.header{background:#111;padding:14px 20px;border-bottom:2px solid #00ff41;
        display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.header h1{color:#00ff41;font-size:1.3em;font-weight:bold}
.dot{width:10px;height:10px;background:#00ff41;border-radius:50%;
     flex-shrink:0;animation:blink 1s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.ws-badge{font-size:.75em;padding:2px 8px;border-radius:10px;
          background:#0a2a0a;color:#00ff41;border:1px solid #00ff41}
.ws-badge.err{background:#2a0a0a;color:#ff4444;border-color:#ff4444}
.uptime{margin-left:auto;color:#555;font-size:.8em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
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
.y{color:#ffcc00}.gr{color:#666}
.full{grid-column:1/-1}
.feed-wrap{background:#080808;border-radius:6px;padding:8px;
           height:200px;overflow-y:auto;margin-top:6px}
.feed-line{padding:3px 0;border-bottom:1px solid #111;
           font-size:.78em;color:#777;display:flex;gap:8px}
.feed-time{color:#333;flex-shrink:0;font-size:.9em}
.section-title{color:#444;font-size:.75em;text-transform:uppercase;
               letter-spacing:.1em;margin:10px 0 4px}
</style>
</head>
<body>

<div class="header">
  <div class="dot"></div>
  <h1>MemeSniper v12.0</h1>
  <span class="ws-badge" id="ws-badge">LIVE</span>
  <span class="uptime" id="uptime-txt">--</span>
</div>

<div class="grid">

  <div class="card">
    <div class="card-title">Bot</div>
    <div class="row"><span class="lbl">Etat</span><span class="val" id="b-state">--</span></div>
    <div class="row"><span class="lbl">Uptime</span><span class="val gr" id="b-up">--</span></div>
    <div class="row"><span class="lbl">Alertes</span><span class="val y" id="b-alerts">0</span></div>
    <div class="row"><span class="lbl">Analyses</span><span class="val gr" id="b-analyzed">0</span></div>
    <div class="row"><span class="lbl">En cours</span><span class="val gr" id="b-proc">0</span></div>
    <div class="row"><span class="lbl">Safety</span><span class="val g">Actif</span></div>
    <div class="row"><span class="lbl">WebSocket</span><span class="val" id="b-ws">--</span></div>
  </div>

  <div class="card">
    <div class="card-title">Marche</div>
    <div class="row"><span class="lbl">BTC 24h</span><span class="val" id="m-btc">--</span></div>
    <div class="row"><span class="lbl">SOL 24h</span><span class="val" id="m-sol">--</span></div>
    <div class="row"><span class="lbl">Fear Greed</span><span class="val" id="m-fg">--</span></div>
    <div class="row"><span class="lbl">Regime</span><span class="val" id="m-mood">--</span></div>
    <div class="row"><span class="lbl">Score min</span><span class="val y" id="m-minscore">7.5</span></div>
  </div>

  <div class="card">
    <div class="card-title">Securite</div>
    <div class="row"><span class="lbl">Tokens checkes</span><span class="val" id="s-total">0</span></div>
    <div class="row"><span class="lbl">Bloques</span><span class="val r" id="s-blocked">0</span></div>
    <div class="row"><span class="lbl">Honeypots</span><span class="val r" id="s-honey">0</span></div>
    <div class="row"><span class="lbl">Liq faible</span><span class="val o" id="s-liq">0</span></div>
    <div class="row"><span class="lbl">Taux blocage</span><span class="val" id="s-rate">0%</span></div>
  </div>

  <div class="card full">
    <div class="card-title">Sources detection</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px">
      <div>
        <div class="section-title">Pump.fun</div>
        <div class="row"><span class="lbl">Tokens</span><span class="val" id="src-pump-n">0</span></div>
      </div>
      <div>
        <div class="section-title">Copy Trading</div>
        <div class="row"><span class="lbl">Signals</span><span class="val" id="src-copy-n">0</span></div>
      </div>
      <div>
        <div class="section-title">Twitter</div>
        <div class="row"><span class="lbl">Mentions</span><span class="val" id="src-tw-n">0</span></div>
      </div>
      <div>
        <div class="section-title">Whales</div>
        <div class="row"><span class="lbl">Signals</span><span class="val" id="src-wh-n">0</span></div>
      </div>
    </div>
  </div>

  <div class="card full">
    <div class="card-title">Live Feed <span style="font-size:.75em;color:#444;font-weight:normal;margin-left:8px">(temps reel)</span></div>
    <div class="feed-wrap" id="feed">
      <div class="feed-line"><span class="feed-time">--:--:--</span><span>En attente...</span></div>
    </div>
  </div>

</div>

<script>
let ws, reconnTimer;

function connect(){
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');
  ws.onopen = () => {
    document.getElementById('ws-badge').className = 'ws-badge';
    document.getElementById('ws-badge').textContent = 'LIVE';
    addFeed('Connecte au dashboard');
    clearTimeout(reconnTimer);
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
  const up = d.uptime || 0;
  const h = Math.floor(up/3600), m = Math.floor((up%3600)/60), s = Math.floor(up%60);
  const upStr = h + 'h ' + m + 'm ' + s + 's';
  set('b-up', upStr);
  set('uptime-txt', 'Uptime: ' + upStr);

  const running = !d.paused;
  setC('b-state', running ? 'Actif' : 'PAUSE', running ? 'val g' : 'val o');
  set('b-alerts', d.alerts_sent || 0);
  set('b-analyzed', d.tokens_analyzed || 0);
  set('b-proc', d.processing || 0);
  setC('b-ws', d.ws_active ? 'Actif' : 'Inactif', d.ws_active ? 'val g' : 'val r');

  const mkt = d.market || {};
  setChg('m-btc', mkt.btc_24h);
  setChg('m-sol', mkt.sol_24h);
  set('m-fg', mkt.fear_greed || '--');
  set('m-mood', mkt.regime || '--');

  const saf = d.safety || {};
  set('s-total', saf.total || 0);
  set('s-blocked', saf.blocked || 0);
  set('s-honey', saf.honey || 0);
  set('s-liq', saf.liq || 0);
  const rate = saf.total > 0 ? ((saf.blocked / saf.total) * 100).toFixed(0) + '%' : '0%';
  set('s-rate', rate);

  set('src-pump-n', d.tokens_analyzed || 0);
  set('src-copy-n', d.copy_trades || 0);
  set('src-tw-n', d.twitter_signals || 0);
  set('src-wh-n', d.whale_signals || 0);

  if(d.events && d.events.length){
    d.events.forEach(ev => addFeed(ev));
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
  el.textContent  = (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
  el.className = 'val ' + (val >= 0 ? 'g' : 'r');
}
function addFeed(msg){
  const feed = document.getElementById('feed');
  const now = new Date().toLocaleTimeString('fr-FR');
  const line = document.createElement('div');
  line.className = 'feed-line';
  line.innerHTML = '<span class="feed-time">' + now + '</span><span>' + msg + '</span>';
  feed.prepend(line);
  while(feed.children.length > 60) feed.removeChild(feed.lastChild);
}

connect();
</script>
</body>
</html>"""


class DashboardServer:

    def __init__(self, bot, host="0.0.0.0", port=8080):
        self.bot = bot
        self.port = int(
            os.environ.get("PORT") or
            os.environ.get("DASHBOARD_PORT") or
            port
        )
        self.host = os.environ.get("DASHBOARD_HOST", host)

        self.app = FastAPI(title="MemeSniper Dashboard", docs_url=None)
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
            return HTML

        @app.get("/health")
        async def health():
            return {
                "status": "ok",
                "service": "MemeSniper v12.0",
                "uptime": time.time() - getattr(self.bot, 'start_time', time.time()),
            }

        @app.get("/api/status")
        async def api_status():
            return self._collect()

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
        bot = self.bot
        uptime = time.time() - getattr(bot, 'start_time', time.time())

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

        return {
            "uptime": uptime,
            "paused": getattr(bot, 'paused', False),
            "alerts_sent": getattr(bot, 'alerts_sent', 0),
            "tokens_analyzed": getattr(bot, 'tokens_analyzed', 0),
            "processing": len(getattr(bot, 'processing_tokens', set())),
            "ws_active": getattr(bot, 'ws_active', False),
            "copy_trades": getattr(bot, 'copy_trades', 0),
            "twitter_signals": getattr(bot, 'twitter_signals', 0),
            "whale_signals": 0,
            "market": market,
            "safety": self.safety_stats,
            "events": list(self._events),
        }

    def add_event(self, msg: str):
        self._events.append(msg)
        if len(self._events) > 30:
            self._events.pop(0)

    def record_safety(self, result: dict):
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
        logger.info(f"📊 Dashboard démarré → http://{self.host}:{self.port}")
        await server.serve()

    async def stop(self):
        logger.info("📊 Dashboard arrêté")