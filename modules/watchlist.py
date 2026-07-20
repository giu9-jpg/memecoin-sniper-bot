# modules/watchlist.py v1.0
"""
Watchlist / Price Alerts personnalisées

Types d'alertes :
  1. MC_TARGET   → Market cap atteint (ex: 500K, 1M)
  2. PUMP        → % de gain depuis ajout
  3. DROP        → % de perte depuis ajout
  4. PRICE       → Prix cible atteint
  5. VOLUME      → Volume 1h dépassé

Surveille toutes les 2 minutes.
Envoie une alerte Telegram quand condition atteinte.
"""

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("watchlist")


class Watchlist:

    DATA_FILE = "data/watchlist.json"

    # Cycle de vérification
    CHECK_INTERVAL = 120  # 2 minutes

    # Types d'alertes
    ALERT_TYPES = {
        "MC_TARGET":  "🎯 Market Cap atteint",
        "PUMP":       "🚀 Pump détecté",
        "DROP":       "📉 Chute détectée",
        "PRICE":      "💰 Prix atteint",
        "VOLUME":     "📊 Volume dépassé",
    }

    def __init__(self, alert_callback):
        """
        alert_callback : fonction async pour envoyer l'alerte
        """
        self.alert_callback = alert_callback
        self.session = None
        self.running = False

        # Watchlist : {mint: [{type, target, symbol, added_at, entry_data}]}
        self.watches = {}

        # Alertes déjà envoyées (anti-doublon)
        self.triggered = set()

        # Stats
        self.total_watches_added = 0
        self.total_alerts_sent   = 0
        self.total_checks        = 0

        self._load_data()

    async def start(self):
        """Démarre le monitoring"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True

        # Compte les watches actifs
        total_watches = sum(len(w) for w in self.watches.values())

        logger.info(
            f"🔔 Watchlist démarrée "
            f"({total_watches} watches sur {len(self.watches)} tokens)"
        )
        asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        self._save_data()
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🔔 Watchlist arrêtée")

    # ════════════════════════════════════════
    # AJOUT / SUPPRESSION DE WATCHES
    # ════════════════════════════════════════

    async def add_watch(
        self,
        symbol_or_mint: str,
        alert_type: str,
        target: float,
        mint: str = None,
    ) -> dict:
        """
        Ajoute une surveillance.

        Args:
          symbol_or_mint : symbole ou adresse mint
          alert_type     : "MC_TARGET" | "PUMP" | "DROP" | "PRICE" | "VOLUME"
          target         : valeur cible (ex: 500000 pour 500K MC)
          mint           : adresse mint (optionnel si symbol fourni)

        Returns:
          {"success": True/False, "message": "..."}
        """
        try:
            alert_type = alert_type.upper()

            if alert_type not in self.ALERT_TYPES:
                return {
                    "success": False,
                    "message": f"Type inconnu. Types : {list(self.ALERT_TYPES.keys())}"
                }

            # Détermine le mint
            if not mint:
                # Si c'est déjà un mint (44 chars)
                if len(symbol_or_mint) >= 32:
                    mint = symbol_or_mint
                else:
                    # Cherche via DexScreener
                    mint = await self._find_mint_by_symbol(symbol_or_mint)
                    if not mint:
                        return {
                            "success": False,
                            "message": f"Token {symbol_or_mint} non trouvé"
                        }

            # Récupère données actuelles pour référence
            current_data = await self._fetch_token_data(mint)
            if not current_data:
                return {
                    "success": False,
                    "message": "Impossible de récupérer les données du token"
                }

            symbol = current_data.get("symbol", "?")

            # Crée la watch
            watch = {
                "id":            f"{mint}_{alert_type}_{int(time.time())}",
                "mint":          mint,
                "symbol":        symbol,
                "type":          alert_type,
                "target":        target,
                "added_at":      time.time(),
                "added_date":    datetime.now(timezone.utc).isoformat(),
                "entry_price":   current_data.get("price", 0),
                "entry_mc":      current_data.get("market_cap", 0),
                "triggered":     False,
            }

            # Ajoute à la watchlist
            if mint not in self.watches:
                self.watches[mint] = []

            self.watches[mint].append(watch)
            self.total_watches_added += 1
            self._save_data()

            logger.info(
                f"🔔 Watch ajoutée : ${symbol} "
                f"{alert_type}={target}"
            )

            return {
                "success": True,
                "message": f"Surveillance activée pour ${symbol}",
                "watch": watch,
                "current_price": current_data.get("price", 0),
                "current_mc": current_data.get("market_cap", 0),
            }

        except Exception as e:
            logger.error(f"Add watch error : {e}")
            return {"success": False, "message": str(e)}

    def remove_watch(
        self,
        symbol_or_mint: str,
        alert_type: str = None,
    ) -> dict:
        """
        Retire une ou plusieurs watches.

        Args:
          symbol_or_mint : symbole ou mint
          alert_type     : optionnel, si fourni retire seulement ce type

        Returns:
          {"success": True, "removed": count}
        """
        try:
            symbol_upper = symbol_or_mint.upper()
            target_mint = None
            removed = 0

            # Cherche par mint direct
            if symbol_or_mint in self.watches:
                target_mint = symbol_or_mint
            else:
                # Cherche par symbole
                for mint, watches in self.watches.items():
                    for w in watches:
                        if w["symbol"].upper() == symbol_upper:
                            target_mint = mint
                            break
                    if target_mint:
                        break

            if not target_mint:
                return {
                    "success": False,
                    "message": f"Aucune watch trouvée pour {symbol_or_mint}"
                }

            if alert_type:
                # Retire seulement le type spécifié
                alert_type = alert_type.upper()
                before = len(self.watches[target_mint])
                self.watches[target_mint] = [
                    w for w in self.watches[target_mint]
                    if w["type"] != alert_type
                ]
                removed = before - len(self.watches[target_mint])
            else:
                # Retire toutes les watches
                removed = len(self.watches[target_mint])
                del self.watches[target_mint]

            # Nettoie si vide
            if target_mint in self.watches and not self.watches[target_mint]:
                del self.watches[target_mint]

            self._save_data()

            return {
                "success": True,
                "removed": removed,
                "message": f"{removed} watch(s) supprimée(s)"
            }

        except Exception as e:
            logger.error(f"Remove watch error : {e}")
            return {"success": False, "message": str(e)}

    def get_all_watches(self) -> list:
        """Retourne toutes les watches actives (à plat)"""
        all_watches = []
        for mint, watches in self.watches.items():
            for w in watches:
                if not w.get("triggered"):
                    all_watches.append(w)
        return sorted(all_watches, key=lambda x: x["added_at"], reverse=True)

    # ════════════════════════════════════════
    # MONITORING
    # ════════════════════════════════════════

    async def _monitor_loop(self):
        """Boucle principale"""
        while self.running:
            try:
                if self.watches:
                    await self._check_all_watches()
                    self._save_data()
                self.total_checks += 1
            except Exception as e:
                logger.error(f"Watchlist monitor error : {e}")
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _check_all_watches(self):
        """Vérifie toutes les watches en parallèle"""
        # Groupe par mint (une seule API call par token)
        tasks = [
            self._check_token_watches(mint)
            for mint in list(self.watches.keys())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_token_watches(self, mint: str):
        """Vérifie toutes les watches d'un token"""
        try:
            watches = self.watches.get(mint, [])
            active_watches = [w for w in watches if not w.get("triggered")]

            if not active_watches:
                return

            # Récupère données actuelles UNE fois
            current = await self._fetch_token_data(mint)
            if not current:
                return

            for watch in active_watches:
                triggered = self._check_watch_condition(watch, current)
                if triggered:
                    watch["triggered"] = True
                    watch["triggered_at"] = time.time()
                    watch["triggered_data"] = current
                    await self._send_alert(watch, current)

        except Exception as e:
            logger.error(f"Check token watches error : {e}")

    def _check_watch_condition(
        self, watch: dict, current: dict
    ) -> bool:
        """Vérifie si une condition est atteinte"""
        try:
            alert_type = watch["type"]
            target = watch["target"]
            entry_price = watch.get("entry_price", 0)

            if alert_type == "MC_TARGET":
                current_mc = current.get("market_cap", 0)
                return current_mc >= target

            elif alert_type == "PUMP":
                current_price = current.get("price", 0)
                if entry_price > 0 and current_price > 0:
                    change_pct = ((current_price - entry_price) / entry_price) * 100
                    return change_pct >= target
                return False

            elif alert_type == "DROP":
                current_price = current.get("price", 0)
                if entry_price > 0 and current_price > 0:
                    change_pct = ((current_price - entry_price) / entry_price) * 100
                    return change_pct <= -abs(target)
                return False

            elif alert_type == "PRICE":
                current_price = current.get("price", 0)
                # Alerte si prix touche ou dépasse (dans les 2 sens)
                if entry_price > 0:
                    if entry_price < target:
                        return current_price >= target
                    else:
                        return current_price <= target
                return current_price >= target

            elif alert_type == "VOLUME":
                current_vol = current.get("volume_1h", 0)
                return current_vol >= target

            return False

        except Exception as e:
            logger.debug(f"Check condition error : {e}")
            return False

    async def _send_alert(self, watch: dict, current: dict):
        """Envoie une alerte de watch déclenchée"""
        try:
            self.total_alerts_sent += 1

            alert_data = {
                "watch":       watch,
                "current":     current,
                "type":        watch["type"],
                "type_label":  self.ALERT_TYPES.get(watch["type"], "?"),
                "symbol":      watch["symbol"],
                "mint":        watch["mint"],
                "target":      watch["target"],
            }

            logger.info(
                f"🔔 Watch déclenchée : ${watch['symbol']} "
                f"{watch['type']}"
            )

            if self.alert_callback:
                await self.alert_callback(alert_data)

        except Exception as e:
            logger.error(f"Send alert error : {e}")

    # ════════════════════════════════════════
    # HELPERS API
    # ════════════════════════════════════════

    async def _fetch_token_data(self, mint: str) -> dict:
        """Récupère données actuelles d'un token"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pairs = data.get("pairs") or []
            if not pairs:
                return None

            pair = pairs[0]
            base = pair.get("baseToken", {})

            return {
                "symbol":     base.get("symbol", "?"),
                "name":       base.get("name", "?"),
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0) or 0,
                "liquidity":  pair.get("liquidity", {}).get("usd", 0) or 0,
                "volume_1h":  pair.get("volume", {}).get("h1", 0) or 0,
                "volume_24h": pair.get("volume", {}).get("h24", 0) or 0,
                "change_1h":  pair.get("priceChange", {}).get("h1", 0) or 0,
                "change_24h": pair.get("priceChange", {}).get("h24", 0) or 0,
                "dex_url":    pair.get("url", ""),
            }
        except Exception:
            return None

    async def _find_mint_by_symbol(self, symbol: str) -> str:
        """Trouve le mint d'un token par son symbole (Solana)"""
        try:
            # Cherche via DexScreener
            url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pairs = data.get("pairs") or []

            # Filtre Solana + symbole exact
            for p in pairs:
                if p.get("chainId") != "solana":
                    continue
                base_sym = p.get("baseToken", {}).get("symbol", "")
                if base_sym.upper() == symbol.upper():
                    return p.get("baseToken", {}).get("address")

            # Si pas de match exact, prend le premier Solana
            for p in pairs:
                if p.get("chainId") == "solana":
                    return p.get("baseToken", {}).get("address")

            return None

        except Exception:
            return None

    # ════════════════════════════════════════
    # STATS
    # ════════════════════════════════════════

    def get_stats(self) -> dict:
        active = sum(
            len([w for w in ws if not w.get("triggered")])
            for ws in self.watches.values()
        )
        triggered = sum(
            len([w for w in ws if w.get("triggered")])
            for ws in self.watches.values()
        )

        return {
            "active_watches":     active,
            "triggered_watches":  triggered,
            "total_tokens":       len(self.watches),
            "total_added":        self.total_watches_added,
            "total_alerts":       self.total_alerts_sent,
            "total_checks":       self.total_checks,
        }

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        """Charge la watchlist"""
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.watches = data.get("watches", {})
                    self.total_watches_added = data.get("total_added", 0)
                    self.total_alerts_sent = data.get("total_alerts", 0)
                    logger.info(
                        f"🔔 Watchlist chargée : "
                        f"{len(self.watches)} tokens"
                    )
        except Exception as e:
            logger.error(f"Watchlist load error : {e}")

    def _save_data(self):
        """Sauvegarde"""
        try:
            os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "watches":       self.watches,
                    "total_added":   self.total_watches_added,
                    "total_alerts":  self.total_alerts_sent,
                    "saved_at":      datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Watchlist save error : {e}")