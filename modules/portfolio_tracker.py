# modules/portfolio_tracker.py — v1.0 CORRIGÉ
# FIX AUDIT :
# - add_trade() ajouté (appelé par callback_handler)
# - Protection session None dans update_positions
# - os.makedirs protégé

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("portfolio")


class PortfolioTracker:

    DATA_FILE = "data/portfolio.json"

    def __init__(self):
        self.session        = None
        self.open_positions = {}
        self.trades_history = []
        self.total_invested = 0
        self.total_pnl      = 0
        self._load_data()

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        logger.info(
            f"💼 PortfolioTracker démarré "
            f"({len(self.open_positions)} positions | "
            f"{len(self.trades_history)} trades)"
        )

    async def stop(self):
        self._save_data()
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("💼 PortfolioTracker arrêté")

    # ════════════════════════════════════════
    # ADD TRADE — appelé par callback_handler
    # FIX AUDIT : méthode manquante ajoutée
    # ════════════════════════════════════════

    def add_trade(
        self,
        symbol: str,
        mint:   str,
        amount: float,
        price:  float = 0,
        score:  float = 0,
        tier:   str   = "NORMAL",
    ):
        """
        Enregistre un achat depuis le bouton inline ✅.
        Appelé par callback_handler._handle_bought().
        Stocke dans open_positions directement (sync).
        """
        symbol = symbol.upper()

        position = {
            "symbol":        symbol,
            "mint":          mint or "",
            "amount_eur":    amount,
            "entry_price":   price,
            "entry_mc":      0,
            "entry_time":    time.time(),
            "entry_date":    datetime.now(timezone.utc).isoformat(),
            "current_price": price,
            "current_pnl":   0,
            "score":         score,
            "tier":          tier,
            "source":        "inline_button",
        }

        self.open_positions[symbol] = position
        self.total_invested        += amount
        self._save_data()

        logger.info(
            f"💼 Trade ajouté (inline) : {symbol} {amount}€ "
            f"score={score} tier={tier}"
        )

    # ════════════════════════════════════════
    # ACHAT / VENTE
    # ════════════════════════════════════════

    async def add_buy(
        self,
        symbol:     str,
        amount_eur: float,
        mint:       str = None,
    ) -> dict:
        try:
            symbol = symbol.upper()

            entry_price = 0
            entry_mc    = 0

            if mint and self.session and not self.session.closed:
                data = await self._fetch_token_data(mint)
                if data:
                    entry_price = data.get("price", 0)
                    entry_mc    = data.get("market_cap", 0)

            position = {
                "symbol":        symbol,
                "mint":          mint or "",
                "amount_eur":    amount_eur,
                "entry_price":   entry_price,
                "entry_mc":      entry_mc,
                "entry_time":    time.time(),
                "entry_date":    datetime.now(timezone.utc).isoformat(),
                "current_price": entry_price,
                "current_pnl":   0,
                "score":         0,
                "tier":          "MANUAL",
                "source":        "command",
            }

            self.open_positions[symbol] = position
            self.total_invested        += amount_eur
            self._save_data()

            logger.info(
                f"💼 BUY : {symbol} ${amount_eur:.0f}€ "
                f"@ ${entry_price:.8f}"
            )

            return {"success": True, "position": position}

        except Exception as e:
            logger.error(f"Portfolio buy error : {e}")
            return {"success": False, "error": str(e)}

    async def add_sell(
        self,
        symbol:  str,
        pnl_pct: float = None,
    ) -> dict:
        try:
            symbol = symbol.upper()

            if symbol not in self.open_positions:
                return {
                    "success": False,
                    "error":   f"Pas de position ouverte sur {symbol}"
                }

            position = self.open_positions[symbol]

            if pnl_pct is None:
                pnl_pct = 0

            amount    = position["amount_eur"]
            pnl_eur   = amount * (pnl_pct / 100)
            final_amt = amount + pnl_eur

            trade = {
                "symbol":       symbol,
                "mint":         position.get("mint", ""),
                "amount_eur":   amount,
                "pnl_pct":      pnl_pct,
                "pnl_eur":      round(pnl_eur, 2),
                "final_eur":    round(final_amt, 2),
                "entry_time":   position["entry_time"],
                "sell_time":    time.time(),
                "sell_date":    datetime.now(timezone.utc).isoformat(),
                "duration_min": (time.time() - position["entry_time"]) / 60,
                "score":        position.get("score", 0),
                "tier":         position.get("tier", "NORMAL"),
            }

            self.trades_history.append(trade)
            self.total_pnl += pnl_eur

            del self.open_positions[symbol]
            self._save_data()

            logger.info(
                f"💼 SELL : {symbol} PnL {pnl_pct:+.0f}% "
                f"({pnl_eur:+.2f}€)"
            )

            return {"success": True, "trade": trade}

        except Exception as e:
            logger.error(f"Portfolio sell error : {e}")
            return {"success": False, "error": str(e)}

    # ════════════════════════════════════════
    # UPDATE POSITIONS
    # ════════════════════════════════════════

    async def update_positions(self):
        """Met à jour les prix actuels."""
        # FIX : vérifier session avant d'appeler
        if not self.session or self.session.closed:
            return

        for symbol, pos in self.open_positions.items():
            mint = pos.get("mint")
            if not mint:
                continue
            try:
                data = await self._fetch_token_data(mint)
                if data:
                    current_price = data.get("price", 0)
                    entry_price   = pos.get("entry_price", 0)
                    if entry_price > 0 and current_price > 0:
                        pnl_pct            = ((current_price - entry_price) / entry_price) * 100
                        pos["current_price"] = current_price
                        pos["current_pnl"]   = pnl_pct
            except Exception:
                pass

    # ════════════════════════════════════════
    # API
    # ════════════════════════════════════════

    async def _fetch_token_data(self, mint: str) -> dict | None:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data  = await resp.json()
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

    # ════════════════════════════════════════
    # STATISTIQUES
    # ════════════════════════════════════════

    def get_portfolio_summary(self) -> dict:
        total_open_value   = 0
        total_open_pnl_eur = 0

        for pos in self.open_positions.values():
            amount  = pos["amount_eur"]
            pnl_pct = pos.get("current_pnl", 0)
            total_open_value   += amount * (1 + pnl_pct / 100)
            total_open_pnl_eur += amount * (pnl_pct / 100)

        return {
            "open_positions":     len(self.open_positions),
            "total_invested":     self.total_invested,
            "total_pnl":          self.total_pnl,
            "total_open_value":   total_open_value,
            "total_open_pnl_eur": total_open_pnl_eur,
            "total_trades":       len(self.trades_history),
        }

    def get_pnl_by_period(self) -> dict:
        now       = time.time()
        day_ago   = now - 86400
        week_ago  = now - (7 * 86400)
        month_ago = now - (30 * 86400)

        pnl_day   = pnl_week = pnl_month = pnl_all = 0
        wins_day  = losses_day = wins_week = losses_week = 0
        wins_all  = losses_all = 0

        for trade in self.trades_history:
            sell_time = trade.get("sell_time", 0)
            pnl_eur   = trade.get("pnl_eur", 0)
            is_win    = pnl_eur > 0

            pnl_all += pnl_eur
            if is_win:
                wins_all += 1
            else:
                losses_all += 1

            if sell_time >= day_ago:
                pnl_day += pnl_eur
                wins_day   += 1 if is_win else 0
                losses_day += 0 if is_win else 1

            if sell_time >= week_ago:
                pnl_week += pnl_eur
                wins_week   += 1 if is_win else 0
                losses_week += 0 if is_win else 1

            if sell_time >= month_ago:
                pnl_month += pnl_eur

        total = wins_all + losses_all
        win_rate_all = (wins_all / total * 100) if total > 0 else 0

        return {
            "pnl_day":      pnl_day,
            "pnl_week":     pnl_week,
            "pnl_month":    pnl_month,
            "pnl_all":      pnl_all,
            "wins_day":     wins_day,
            "losses_day":   losses_day,
            "wins_week":    wins_week,
            "losses_week":  losses_week,
            "wins_all":     wins_all,
            "losses_all":   losses_all,
            "win_rate_all": round(win_rate_all, 1),
        }

    def get_all_positions(self) -> list:
        return list(self.open_positions.values())

    def get_all_trades(self, limit: int = 20) -> list:
        return sorted(
            self.trades_history,
            key=lambda x: x.get("sell_time", 0),
            reverse=True,
        )[:limit]

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.open_positions = data.get("open_positions", {})
                    self.trades_history = data.get("trades_history", [])
                    self.total_invested = data.get("total_invested", 0)
                    self.total_pnl      = data.get("total_pnl", 0)
                    logger.info(
                        f"💼 Portfolio chargé : "
                        f"{len(self.open_positions)} positions, "
                        f"{len(self.trades_history)} trades"
                    )
        except Exception as e:
            logger.error(f"Portfolio load error : {e}")

    def _save_data(self):
        try:
            # FIX : protection dirname vide
            data_dir = os.path.dirname(self.DATA_FILE)
            if data_dir:
                os.makedirs(data_dir, exist_ok=True)

            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "open_positions": self.open_positions,
                    "trades_history": self.trades_history,
                    "total_invested": self.total_invested,
                    "total_pnl":      self.total_pnl,
                    "saved_at":       datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Portfolio save error : {e}")