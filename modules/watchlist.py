# modules/watchlist.py — v1.0 CORRIGÉ
# FIX AUDIT :
# - get_stats() retourne les bonnes clés attendues par main.py
#   (active_watches, triggered_watches)
# - remove_watch() retourne dict avec "removed" key
# - Protection session dans update loop

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("watchlist")


class Watchlist:

    DATA_FILE     = "data/watchlist.json"
    CHECK_INTERVAL = 60   # 1 minute

    def __init__(self, alert_callback):
        self.alert_callback = alert_callback
        self.session        = None
        self.running        = False

        # {id: {symbol, mint, type, target, created_at, triggered}}
        self.watches = {}
        self._next_id = 1

        self.total_triggered = 0
        self._load_data()

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True
        logger.info(
            f"🔔 Watchlist démarrée "
            f"({len(self.watches)} watches actives)"
        )
        asyncio.create_task(self._check_loop())

    async def stop(self):
        self.running = False
        self._save_data()
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🔔 Watchlist arrêtée")

    # ════════════════════════════════════════
    # AJOUT / SUPPRESSION
    # ════════════════════════════════════════

    async def add_watch(
        self,
        symbol_or_mint: str,
        alert_type:     str,
        target:         float,
    ) -> dict:
        """
        Ajoute une alerte de surveillance.

        Types supportés : MC_TARGET, PUMP, DROP, PRICE, VOLUME
        """
        try:
            symbol = symbol_or_mint.upper()
            mint   = None

            # Détecter si c'est un mint (longueur > 10 et base58)
            if len(symbol_or_mint) > 10:
                mint   = symbol_or_mint
                symbol = "UNKNOWN"

                # Récupérer le symbole depuis DexScreener
                if self.session and not self.session.closed:
                    data = await self._fetch_token_data(mint)
                    if data:
                        symbol = data.get("symbol", "UNKNOWN").upper()

            watch_id = str(self._next_id)
            self._next_id += 1

            self.watches[watch_id] = {
                "id":         watch_id,
                "symbol":     symbol,
                "mint":       mint or symbol,
                "type":       alert_type.upper(),
                "target":     target,
                "created_at": time.time(),
                "triggered":  False,
                "trigger_count": 0,
            }

            self._save_data()

            logger.info(
                f"🔔 Watch ajoutée : ${symbol} {alert_type} {target}"
            )

            return {"success": True, "watch_id": watch_id, "symbol": symbol}

        except Exception as e:
            logger.error(f"Add watch error : {e}")
            return {"success": False, "message": str(e)}

    def remove_watch(
        self,
        symbol:     str,
        alert_type: str = None,
    ) -> dict:
        """
        Retire une ou plusieurs watches par symbole.
        FIX AUDIT : retourne "removed" pour compatibilité main.py
        """
        symbol  = symbol.upper()
        removed = 0

        to_delete = []
        for watch_id, watch in self.watches.items():
            if watch["symbol"] == symbol:
                if alert_type is None or watch["type"] == alert_type.upper():
                    to_delete.append(watch_id)

        for watch_id in to_delete:
            del self.watches[watch_id]
            removed += 1

        if removed > 0:
            self._save_data()
            return {"success": True, "removed": removed}
        else:
            return {
                "success": False,
                "message": f"Aucune watch trouvée pour ${symbol}",
                "removed": 0,
            }

    # ════════════════════════════════════════
    # BOUCLE DE SURVEILLANCE
    # ════════════════════════════════════════

    async def _check_loop(self):
        while self.running:
            try:
                # FIX : vérifier session avant d'appeler
                if self.session and not self.session.closed:
                    await self._check_all_watches()
            except Exception as e:
                logger.error(f"Watchlist check error : {e}")
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _check_all_watches(self):
        active = [w for w in self.watches.values() if not w.get("triggered")]

        if not active:
            return

        # Grouper par mint pour limiter les appels API
        by_mint = {}
        for watch in active:
            mint = watch["mint"]
            by_mint.setdefault(mint, []).append(watch)

        for mint, watches in by_mint.items():
            try:
                current = await self._fetch_token_data(mint)
                if not current:
                    continue

                for watch in watches:
                    triggered = self._check_condition(watch, current)
                    if triggered:
                        await self._trigger_watch(watch, current)

            except Exception as e:
                logger.debug(f"Watch check error for {mint[:8]}: {e}")

    def _check_condition(self, watch: dict, current: dict) -> bool:
        alert_type = watch["type"]
        target     = watch["target"]

        mc         = current.get("market_cap", 0)
        change_24h = current.get("change_24h", 0)
        price      = current.get("price", 0)
        volume_24h = current.get("volume_24h", 0)

        if alert_type == "MC_TARGET":
            return mc >= target
        elif alert_type == "PUMP":
            return change_24h >= target
        elif alert_type == "DROP":
            return change_24h <= -abs(target)
        elif alert_type == "PRICE":
            return price >= target
        elif alert_type == "VOLUME":
            return volume_24h >= target

        return False

    async def _trigger_watch(self, watch: dict, current: dict):
        try:
            # Marquer comme déclenché (one-shot)
            watch_id = watch["id"]
            if watch_id in self.watches:
                self.watches[watch_id]["triggered"]      = True
                self.watches[watch_id]["trigger_count"] += 1
                self.watches[watch_id]["triggered_at"]   = time.time()

            self.total_triggered += 1
            self._save_data()

            alert_data = {
                "watch":   watch,
                "current": current,
                "symbol":  watch["symbol"],
                "mint":    watch["mint"],
            }

            logger.info(
                f"🔔 WATCH TRIGGERED : ${watch['symbol']} "
                f"{watch['type']} {watch['target']}"
            )

            if self.alert_callback:
                await self.alert_callback(alert_data)

        except Exception as e:
            logger.error(f"Trigger watch error : {e}")

    async def _fetch_token_data(self, mint_or_symbol: str) -> dict | None:
        try:
            # Si c'est un symbole court, cherche par search
            if len(mint_or_symbol) <= 10:
                url = f"https://api.dexscreener.com/latest/dex/search?q={mint_or_symbol}"
            else:
                url = f"https://api.dexscreener.com/latest/dex/tokens/{mint_or_symbol}"

            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pairs = data.get("pairs") or []
            sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
            if not sol_pairs:
                return None

            pair         = sol_pairs[0]
            price_change = pair.get("priceChange", {}) or {}

            return {
                "symbol":     pair.get("baseToken", {}).get("symbol", "?"),
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0) or 0,
                "liquidity":  pair.get("liquidity", {}).get("usd", 0) or 0,
                "volume_24h": pair.get("volume", {}).get("h24", 0) or 0,
                "change_24h": price_change.get("h24", 0) or 0,
            }

        except Exception:
            return None

    # ════════════════════════════════════════
    # GETTERS
    # ════════════════════════════════════════

    def get_all_watches(self) -> list:
        return list(self.watches.values())

    def get_stats(self) -> dict:
        """
        FIX AUDIT : retourne les clés exactes attendues par main.py
          - active_watches
          - triggered_watches
        """
        active    = sum(1 for w in self.watches.values() if not w.get("triggered"))
        triggered = sum(1 for w in self.watches.values() if w.get("triggered"))

        return {
            "active_watches":    active,
            "triggered_watches": triggered,
            "total_watches":     len(self.watches),
            "total_triggered":   self.total_triggered,
        }

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.watches      = data.get("watches", {})
                    self._next_id     = data.get("next_id", 1)
                    self.total_triggered = data.get("total_triggered", 0)
                    logger.info(
                        f"🔔 {len(self.watches)} watches chargées"
                    )
        except Exception as e:
            logger.error(f"Watchlist load error : {e}")

    def _save_data(self):
        try:
            data_dir = os.path.dirname(self.DATA_FILE)
            if data_dir:
                os.makedirs(data_dir, exist_ok=True)

            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "watches":         self.watches,
                    "next_id":         self._next_id,
                    "total_triggered": self.total_triggered,
                    "saved_at":        datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Watchlist save error : {e}")