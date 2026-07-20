# modules/portfolio_tracker.py v1.0
"""
Portfolio Tracker
Suit tes trades manuels et calcule ton PnL réel.

Commandes :
  /buy <symbol> <amount_eur>   → enregistre un achat
  /sell <symbol> [pnl_pct]     → enregistre une vente
  /portfolio                   → voir positions actuelles
  /pnl                         → PnL total (day/week/all)
  /trades                      → historique complet
"""

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

logger = get_logger("portfolio")


class PortfolioTracker:

    DATA_FILE = "data/portfolio.json"

    def __init__(self):
        self.session = None

        # Positions ouvertes : {symbol: {...}}
        self.open_positions = {}

        # Historique complet des trades
        self.trades_history = []

        # Stats
        self.total_invested = 0
        self.total_pnl = 0

        self._load_data()

    async def start(self):
        """Démarre le tracker"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        logger.info(
            f"💼 PortfolioTracker démarré "
            f"({len(self.open_positions)} positions | "
            f"{len(self.trades_history)} trades)"
        )

    async def stop(self):
        """Arrêt propre"""
        self._save_data()
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("💼 PortfolioTracker arrêté")

    # ════════════════════════════════════════
    # ACHAT / VENTE
    # ════════════════════════════════════════

    async def add_buy(
        self,
        symbol: str,
        amount_eur: float,
        mint: str = None,
    ) -> dict:
        """Enregistre un achat"""
        try:
            symbol = symbol.upper()

            # Récupère le prix actuel si mint fourni
            entry_price = 0
            entry_mc = 0
            if mint:
                data = await self._fetch_token_data(mint)
                if data:
                    entry_price = data.get("price", 0)
                    entry_mc = data.get("market_cap", 0)

            position = {
                "symbol":       symbol,
                "mint":         mint or "",
                "amount_eur":   amount_eur,
                "entry_price":  entry_price,
                "entry_mc":     entry_mc,
                "entry_time":   time.time(),
                "entry_date":   datetime.now(timezone.utc).isoformat(),
                "current_price": entry_price,
                "current_pnl":  0,
            }

            self.open_positions[symbol] = position
            self.total_invested += amount_eur

            self._save_data()

            logger.info(
                f"💼 BUY : {symbol} ${amount_eur:.0f}€ "
                f"@ ${entry_price:.8f}"
            )

            return {
                "success": True,
                "position": position,
            }

        except Exception as e:
            logger.error(f"Portfolio buy error : {e}")
            return {"success": False, "error": str(e)}

    async def add_sell(
        self,
        symbol: str,
        pnl_pct: float = None,
    ) -> dict:
        """Enregistre une vente"""
        try:
            symbol = symbol.upper()

            if symbol not in self.open_positions:
                return {
                    "success": False,
                    "error": f"Pas de position ouverte sur {symbol}"
                }

            position = self.open_positions[symbol]

            # Si pnl_pct pas fourni, essaie de le calculer
            if pnl_pct is None and position.get("mint"):
                current_data = await self._fetch_token_data(position["mint"])
                if current_data:
                    entry = position.get("entry_price", 0)
                    current = current_data.get("price", 0)
                    if entry > 0 and current > 0:
                        pnl_pct = ((current - entry) / entry) * 100

            if pnl_pct is None:
                pnl_pct = 0

            # Calcul du PnL en euros
            amount = position["amount_eur"]
            pnl_eur = amount * (pnl_pct / 100)
            final_amount = amount + pnl_eur

            # Enregistrer dans l'historique
            trade = {
                "symbol":     symbol,
                "mint":       position.get("mint", ""),
                "amount_eur": amount,
                "pnl_pct":    pnl_pct,
                "pnl_eur":    pnl_eur,
                "final_eur":  final_amount,
                "entry_time": position["entry_time"],
                "sell_time":  time.time(),
                "sell_date":  datetime.now(timezone.utc).isoformat(),
                "duration_min": (time.time() - position["entry_time"]) / 60,
            }

            self.trades_history.append(trade)
            self.total_pnl += pnl_eur

            # Retirer la position
            del self.open_positions[symbol]

            self._save_data()

            logger.info(
                f"💼 SELL : {symbol} PnL {pnl_pct:+.0f}% "
                f"({pnl_eur:+.2f}€)"
            )

            return {
                "success": True,
                "trade": trade,
            }

        except Exception as e:
            logger.error(f"Portfolio sell error : {e}")
            return {"success": False, "error": str(e)}

    # ════════════════════════════════════════
    # RÉCUPÉRATION DES DONNÉES
    # ════════════════════════════════════════

    async def _fetch_token_data(self, mint: str) -> dict:
        """Récupère le prix actuel d'un token"""
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
            return {
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0) or 0,
                "liquidity":  pair.get("liquidity", {}).get("usd", 0) or 0,
            }
        except Exception:
            return None

    async def update_positions(self):
        """Met à jour les prix actuels de toutes les positions"""
        for symbol, pos in self.open_positions.items():
            mint = pos.get("mint")
            if not mint:
                continue

            data = await self._fetch_token_data(mint)
            if data:
                current_price = data.get("price", 0)
                entry_price = pos.get("entry_price", 0)

                if entry_price > 0 and current_price > 0:
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    pos["current_price"] = current_price
                    pos["current_pnl"] = pnl_pct

    # ════════════════════════════════════════
    # STATISTIQUES
    # ════════════════════════════════════════

    def get_portfolio_summary(self) -> dict:
        """Résumé du portefeuille"""
        total_open_value = 0
        total_open_pnl_eur = 0

        for pos in self.open_positions.values():
            amount = pos["amount_eur"]
            pnl_pct = pos.get("current_pnl", 0)
            total_open_value += amount * (1 + pnl_pct / 100)
            total_open_pnl_eur += amount * (pnl_pct / 100)

        return {
            "open_positions":       len(self.open_positions),
            "total_invested":       self.total_invested,
            "total_pnl":            self.total_pnl,
            "total_open_value":     total_open_value,
            "total_open_pnl_eur":   total_open_pnl_eur,
            "total_trades":         len(self.trades_history),
        }

    def get_pnl_by_period(self) -> dict:
        """PnL par période"""
        now = time.time()
        day_ago = now - 86400
        week_ago = now - (7 * 86400)
        month_ago = now - (30 * 86400)

        pnl_day = 0
        pnl_week = 0
        pnl_month = 0
        pnl_all = 0

        wins_day = 0
        losses_day = 0
        wins_week = 0
        losses_week = 0
        wins_all = 0
        losses_all = 0

        for trade in self.trades_history:
            sell_time = trade.get("sell_time", 0)
            pnl_eur = trade.get("pnl_eur", 0)
            is_win = pnl_eur > 0

            pnl_all += pnl_eur
            if is_win:
                wins_all += 1
            else:
                losses_all += 1

            if sell_time >= day_ago:
                pnl_day += pnl_eur
                if is_win:
                    wins_day += 1
                else:
                    losses_day += 1

            if sell_time >= week_ago:
                pnl_week += pnl_eur
                if is_win:
                    wins_week += 1
                else:
                    losses_week += 1

            if sell_time >= month_ago:
                pnl_month += pnl_eur

        win_rate_all = (
            (wins_all / (wins_all + losses_all) * 100)
            if (wins_all + losses_all) > 0 else 0
        )

        return {
            "pnl_day":       pnl_day,
            "pnl_week":      pnl_week,
            "pnl_month":     pnl_month,
            "pnl_all":       pnl_all,
            "wins_day":      wins_day,
            "losses_day":    losses_day,
            "wins_week":     wins_week,
            "losses_week":   losses_week,
            "wins_all":      wins_all,
            "losses_all":    losses_all,
            "win_rate_all":  win_rate_all,
        }

    def get_top_trades(self, limit: int = 5) -> dict:
        """Top et pire trades"""
        if not self.trades_history:
            return {"top": [], "worst": []}

        sorted_by_pnl = sorted(
            self.trades_history,
            key=lambda x: x.get("pnl_pct", 0),
            reverse=True,
        )

        return {
            "top": sorted_by_pnl[:limit],
            "worst": sorted_by_pnl[-limit:][::-1],
        }

    def get_all_positions(self) -> list:
        """Retourne toutes les positions ouvertes"""
        return list(self.open_positions.values())

    def get_all_trades(self, limit: int = 20) -> list:
        """Retourne les derniers trades"""
        sorted_trades = sorted(
            self.trades_history,
            key=lambda x: x.get("sell_time", 0),
            reverse=True,
        )
        return sorted_trades[:limit]

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        """Charge le portefeuille"""
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.open_positions = data.get("open_positions", {})
                    self.trades_history = data.get("trades_history", [])
                    self.total_invested = data.get("total_invested", 0)
                    self.total_pnl = data.get("total_pnl", 0)
                    logger.info(
                        f"💼 Portfolio chargé : "
                        f"{len(self.open_positions)} positions, "
                        f"{len(self.trades_history)} trades"
                    )
        except Exception as e:
            logger.error(f"Portfolio load error : {e}")

    def _save_data(self):
        """Sauvegarde"""
        try:
            os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "open_positions":  self.open_positions,
                    "trades_history":  self.trades_history,
                    "total_invested":  self.total_invested,
                    "total_pnl":       self.total_pnl,
                    "saved_at":        datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Portfolio save error : {e}")