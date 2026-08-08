# modules/simulator.py — v1.2 RISK-GUARD
# ═══════════════════════════════════════════════
# Paper trading uniquement.
#
# Améliorations :
# + Check plus fréquent configurable
# + Stop-loss plus réactif
# + Emergency exit si prix/liquidité disparaît
# + Trailing stop pour protéger les pumps
# + Persistance DATA_DIR compatible Railway Volume

from __future__ import annotations

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("simulator")


def _env_float(
    name: str,
    default: float,
) -> float:
    try:
        return float(
            str(
                os.getenv(name, str(default))
            ).replace(",", ".")
        )
    except Exception:
        return float(default)


def _env_int(
    name: str,
    default: int,
) -> int:
    try:
        return int(
            float(
                str(
                    os.getenv(name, str(default))
                ).replace(",", ".")
            )
        )
    except Exception:
        return int(default)


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


class Simulator:
    DATA_FILE = str(_data_dir() / "simulations.json")

    SIMULATED_AMOUNT_EUR = _env_float(
        "SIM_AMOUNT_EUR",
        10.0,
    )

    # Plus réactif que 120s pour limiter les -80/-100 en paper.
    CHECK_INTERVAL = max(
        15,
        _env_int("SIM_CHECK_INTERVAL", 30),
    )

    SIM_SL_PCT = _env_float(
        "SIM_SL_PCT",
        -25.0,
    )

    SIM_TP_PCT = _env_float(
        "SIM_TP_PCT",
        100.0,
    )

    SIM_MAX_AGE_HOURS = _env_float(
        "SIM_MAX_AGE_HOURS",
        18.0,
    )

    # Risk Guard
    SIM_EMERGENCY_NO_PRICE_MISSES = max(
        1,
        _env_int("SIM_NO_PRICE_MISSES", 2),
    )

    SIM_NO_PRICE_EXIT_PCT = _env_float(
        "SIM_NO_PRICE_EXIT_PCT",
        -35.0,
    )

    SIM_MIN_LIQUIDITY_EXIT = _env_float(
        "SIM_MIN_LIQUIDITY_EXIT",
        1000.0,
    )

    SIM_LIQUIDITY_DROP_EXIT_PCT = _env_float(
        "SIM_LIQ_DROP_EXIT_PCT",
        -40.0,
    )

    SIM_EARLY_SL_MINUTES = _env_float(
        "SIM_EARLY_SL_MINUTES",
        10.0,
    )

    SIM_EARLY_SL_PCT = _env_float(
        "SIM_EARLY_SL_PCT",
        -18.0,
    )

    SIM_TRAILING_ACTIVATE_PCT = _env_float(
        "SIM_TRAILING_ACTIVATE_PCT",
        50.0,
    )

    SIM_TRAILING_GIVEBACK_PCT = _env_float(
        "SIM_TRAILING_GIVEBACK_PCT",
        45.0,
    )

    def __init__(
        self,
        ml_scorer=None,
    ):
        self.ml_scorer = ml_scorer
        self.session: aiohttp.ClientSession | None = None
        self.running = False

        self.open_positions: dict[str, dict] = {}
        self.simulations_history: list[dict] = []

        self.total_simulated = 0
        self.total_closed = 0
        self.total_pnl_eur = 0.0

        self._load_data()

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )

        self.running = True

        zombies = await self._cleanup_zombies()

        logger.info(
            f"🎮 Simulator v1.2 démarré "
            f"({len(self.open_positions)} pos ouvertes | "
            f"{len(self.simulations_history)} historique | "
            f"SL:{self.SIM_SL_PCT}% TP:+{self.SIM_TP_PCT}% | "
            f"check:{self.CHECK_INTERVAL}s | "
            f"max:{self.SIM_MAX_AGE_HOURS}h)"
        )

        if zombies > 0:
            logger.info(f"🎮 {zombies} positions zombies nettoyées")

        asyncio.create_task(self._check_loop())

    async def stop(self):
        self.running = False
        self._save_data()

        if self.session and not self.session.closed:
            await self.session.close()

        logger.info("🎮 Simulator arrêté")

    # ════════════════════════════════════════
    # SIMULER UN ACHAT
    # ════════════════════════════════════════

    async def simulate_buy(
        self,
        mint: str,
        symbol: str,
        alert_data: dict | None = None,
    ) -> dict:
        try:
            if mint in self.open_positions:
                return {
                    "success": False,
                    "message": "Déjà en position",
                }

            data = await self._fetch_price(mint)

            if not data or data.get("price", 0) <= 0:
                return {
                    "success": False,
                    "message": "Prix indisponible",
                }

            entry_price = float(data["price"])
            alert_data = alert_data or {}

            simulation = {
                "id": f"sim_{int(time.time())}_{mint[:8]}",
                "mint": mint,
                "symbol": symbol,
                "amount_eur": self.SIMULATED_AMOUNT_EUR,

                "entry_price": entry_price,
                "entry_mc": data.get("market_cap", 0),
                "entry_liquidity": data.get("liquidity", 0),

                "entry_time": time.time(),
                "entry_date": datetime.now(timezone.utc).isoformat(),

                "max_gain_pct": 0.0,
                "min_loss_pct": 0.0,
                "current_pnl": 0.0,
                "current_price": entry_price,
                "last_liquidity": data.get("liquidity", 0),
                "no_price_misses": 0,

                "closed": False,

                "alert_score": alert_data.get("score", 0),
                "alert_tier": alert_data.get("tier", "?"),
                "alert_source": alert_data.get("source", "?"),
            }

            self.open_positions[mint] = simulation
            self.total_simulated += 1

            self._save_data()

            logger.info(
                f"🎮 SIM BUY : ${symbol} @ ${entry_price:.8f} "
                f"({self.SIMULATED_AMOUNT_EUR}€)"
            )

            return {
                "success": True,
                "simulation": simulation,
            }

        except Exception as exc:
            logger.error(f"Simulate buy error : {exc}")

            return {
                "success": False,
                "message": str(exc),
            }

    # ════════════════════════════════════════
    # SIMULER UNE VENTE
    # ════════════════════════════════════════

    async def simulate_sell(
        self,
        mint: str,
        reason: str = "sell_signal",
        forced_pnl_pct: float | None = None,
    ) -> dict:
        try:
            if mint not in self.open_positions:
                return {
                    "success": False,
                    "message": "Pas de position",
                }

            pos = self.open_positions[mint]

            data = await self._fetch_price(mint)

            entry_price = float(
                pos.get("entry_price", 0) or 0
            )

            if forced_pnl_pct is not None:
                pnl_pct = float(forced_pnl_pct)
                exit_price = entry_price * max(
                    0.0,
                    1.0 + pnl_pct / 100.0,
                )

            elif data and data.get("price", 0) > 0:
                exit_price = float(data["price"])

                if entry_price > 0:
                    pnl_pct = (
                        (exit_price - entry_price)
                        / entry_price
                    ) * 100
                else:
                    pnl_pct = -100.0

            else:
                # Si le prix a disparu, on ne laisse pas une perte zombie optimiste.
                pnl_pct = min(
                    float(pos.get("current_pnl", 0) or 0),
                    self.SIM_NO_PRICE_EXIT_PCT,
                )

                exit_price = entry_price * max(
                    0.0,
                    1.0 + pnl_pct / 100.0,
                )

            amount_eur = float(
                pos.get(
                    "amount_eur",
                    self.SIMULATED_AMOUNT_EUR,
                )
            )

            pnl_eur = amount_eur * (pnl_pct / 100)
            final_eur = amount_eur + pnl_eur

            pos.update(
                {
                    "exit_price": exit_price,
                    "exit_time": time.time(),
                    "exit_date": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_eur": round(pnl_eur, 2),
                    "final_eur": round(final_eur, 2),
                    "duration_min": round(
                        (
                            time.time()
                            - float(
                                pos.get(
                                    "entry_time",
                                    time.time(),
                                )
                            )
                        )
                        / 60,
                        1,
                    ),
                    "closed": True,
                    "exit_reason": reason,
                    "exit_mc": (
                        data.get("market_cap", 0)
                        if data
                        else 0
                    ),
                    "exit_liquidity": (
                        data.get("liquidity", 0)
                        if data
                        else 0
                    ),
                }
            )

            self.simulations_history.append(pos.copy())

            del self.open_positions[mint]

            self.total_closed += 1
            self.total_pnl_eur += pnl_eur

            # Nourrir le ML historique existant
            if self.ml_scorer:
                try:
                    self.ml_scorer.record_result(
                        token_name=pos["symbol"],
                        is_win=(pnl_pct > 0),
                        pnl_pct=pnl_pct,
                    )

                except Exception as exc:
                    logger.debug(f"ML record error : {exc}")

            self._save_data()

            emoji = "🟢" if pnl_pct > 0 else "🔴"

            logger.info(
                f"🎮 SIM SELL {emoji} : ${pos['symbol']} "
                f"PnL {pnl_pct:+.1f}% ({pnl_eur:+.2f}€) "
                f"reason={reason}"
            )

            return {
                "success": True,
                "simulation": pos,
                "pnl_pct": pnl_pct,
                "pnl_eur": pnl_eur,
                "final_eur": final_eur,
                "duration_min": pos["duration_min"],
            }

        except Exception as exc:
            logger.error(f"Simulate sell error : {exc}")

            return {
                "success": False,
                "message": str(exc),
            }

    # ════════════════════════════════════════
    # BOUCLE DE MISE À JOUR
    # ════════════════════════════════════════

    async def _check_loop(self):
        while self.running:
            try:
                if self.open_positions:
                    await self._update_and_check_positions()

            except Exception as exc:
                logger.error(f"Simulator loop error : {exc}")

            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _update_and_check_positions(self):
        for mint in list(self.open_positions.keys()):
            if mint not in self.open_positions:
                continue

            pos = self.open_positions[mint]

            try:
                data = await self._fetch_price(mint)

                entry_price = float(
                    pos.get("entry_price", 0) or 0
                )

                pnl_pct = float(
                    pos.get("current_pnl", 0) or 0
                )

                if data and data.get("price", 0) > 0:
                    current_price = float(data["price"])

                    if entry_price > 0:
                        pnl_pct = (
                            (current_price - entry_price)
                            / entry_price
                        ) * 100
                    else:
                        pnl_pct = -100.0

                    pos["current_pnl"] = round(pnl_pct, 2)
                    pos["current_price"] = current_price
                    pos["last_liquidity"] = data.get(
                        "liquidity",
                        pos.get("last_liquidity", 0),
                    )
                    pos["no_price_misses"] = 0

                    if pnl_pct > float(
                        pos.get("max_gain_pct", 0) or 0
                    ):
                        pos["max_gain_pct"] = round(pnl_pct, 2)

                    if pnl_pct < float(
                        pos.get("min_loss_pct", 0) or 0
                    ):
                        pos["min_loss_pct"] = round(pnl_pct, 2)

                else:
                    pos["no_price_misses"] = int(
                        pos.get("no_price_misses", 0) or 0
                    ) + 1

                    if (
                        pos["no_price_misses"]
                        >= self.SIM_EMERGENCY_NO_PRICE_MISSES
                    ):
                        logger.info(
                            f"🎮 🚨 SIM NO PRICE : "
                            f"${pos['symbol']} "
                            f"misses={pos['no_price_misses']}"
                        )

                        await self.simulate_sell(
                            mint,
                            reason="sim_no_price_emergency",
                            forced_pnl_pct=min(
                                pnl_pct,
                                self.SIM_NO_PRICE_EXIT_PCT,
                            ),
                        )

                        continue

                age_min = (
                    time.time()
                    - float(pos.get("entry_time", time.time()))
                ) / 60

                max_gain = float(
                    pos.get("max_gain_pct", 0) or 0
                )

                liquidity = float(
                    pos.get("last_liquidity", 0) or 0
                )

                # Emergency exit si liquidité quasi morte
                if (
                    liquidity <= self.SIM_MIN_LIQUIDITY_EXIT
                    and age_min > 2
                ):
                    logger.info(
                        f"🎮 🚨 SIM LIQ EXIT : "
                        f"${pos['symbol']} "
                        f"liq=${liquidity:,.0f}"
                    )

                    await self.simulate_sell(
                        mint,
                        reason="sim_liquidity_emergency",
                        forced_pnl_pct=min(
                            pnl_pct,
                            self.SIM_LIQUIDITY_DROP_EXIT_PCT,
                        ),
                    )

                    continue

                # Early stop-loss pour éviter les rugs rapides
                if (
                    age_min <= self.SIM_EARLY_SL_MINUTES
                    and pnl_pct <= self.SIM_EARLY_SL_PCT
                ):
                    logger.info(
                        f"🎮 ⚡ SIM EARLY SL : "
                        f"${pos['symbol']} "
                        f"PnL {pnl_pct:+.1f}%"
                    )

                    await self.simulate_sell(
                        mint,
                        reason="sim_early_stop_loss",
                    )

                    continue

                # Stop-loss standard
                if pnl_pct <= self.SIM_SL_PCT:
                    logger.info(
                        f"🎮 🛑 SIM SL : ${pos['symbol']} "
                        f"PnL {pnl_pct:+.1f}% ≤ "
                        f"{self.SIM_SL_PCT}%"
                    )

                    await self.simulate_sell(
                        mint,
                        reason="sim_stop_loss",
                    )

                    continue

                # Trailing stop : protège un pump déjà monté
                if (
                    max_gain >= self.SIM_TRAILING_ACTIVATE_PCT
                    and (
                        max_gain - pnl_pct
                    ) >= self.SIM_TRAILING_GIVEBACK_PCT
                ):
                    logger.info(
                        f"🎮 🧲 SIM TRAILING : "
                        f"${pos['symbol']} "
                        f"max {max_gain:+.1f}% "
                        f"now {pnl_pct:+.1f}%"
                    )

                    await self.simulate_sell(
                        mint,
                        reason="sim_trailing_stop",
                    )

                    continue

                # Take profit
                if pnl_pct >= self.SIM_TP_PCT:
                    logger.info(
                        f"🎮 🎯 SIM TP : ${pos['symbol']} "
                        f"PnL {pnl_pct:+.1f}% ≥ "
                        f"+{self.SIM_TP_PCT}%"
                    )

                    await self.simulate_sell(
                        mint,
                        reason="sim_take_profit",
                    )

                    continue

                # Timeout
                age_hours = age_min / 60

                if age_hours >= self.SIM_MAX_AGE_HOURS:
                    logger.info(
                        f"🎮 ⏰ SIM TIMEOUT : ${pos['symbol']} "
                        f"après {age_hours:.1f}h "
                        f"PnL {pnl_pct:+.1f}%"
                    )

                    await self.simulate_sell(
                        mint,
                        reason="sim_timeout",
                    )

                    continue

            except Exception as exc:
                logger.debug(
                    f"Sim check error {mint[:8]}: {exc}"
                )

            # Rate limiting entre appels API
            await asyncio.sleep(0.5)

        self._save_data()

    async def _cleanup_zombies(self) -> int:
        zombies_closed = 0

        for mint in list(self.open_positions.keys()):
            pos = self.open_positions[mint]

            age_hours = (
                time.time()
                - float(pos.get("entry_time", 0) or 0)
            ) / 3600

            if age_hours > max(
                self.SIM_MAX_AGE_HOURS * 1.5,
                24,
            ):
                await self.simulate_sell(
                    mint,
                    reason="zombie_cleanup",
                    forced_pnl_pct=min(
                        float(
                            pos.get("current_pnl", -100)
                            or -100
                        ),
                        -50.0,
                    ),
                )

                zombies_closed += 1

        return zombies_closed

    # ════════════════════════════════════════
    # API
    # ════════════════════════════════════════

    async def _fetch_price(
        self,
        mint: str,
    ) -> dict | None:
        try:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10)
                )

            url = (
                "https://api.dexscreener.com/latest/dex/tokens/"
                f"{mint}"
            )

            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                pairs = data.get("pairs") or []

                if not pairs:
                    return None

                # Choisit la paire la plus liquide
                pair = max(
                    pairs,
                    key=lambda p: float(
                        (p.get("liquidity") or {}).get(
                            "usd",
                            0,
                        )
                        or 0
                    ),
                )

                return {
                    "price": float(
                        pair.get("priceUsd", 0) or 0
                    ),
                    "market_cap": float(
                        pair.get("marketCap", 0)
                        or pair.get("fdv", 0)
                        or 0
                    ),
                    "liquidity": float(
                        (pair.get("liquidity") or {}).get(
                            "usd",
                            0,
                        )
                        or 0
                    ),
                }

        except Exception:
            return None

    # ════════════════════════════════════════
    # STATISTIQUES
    # ════════════════════════════════════════

    def get_stats(self) -> dict:
        closed = [
            sim
            for sim in self.simulations_history
            if sim.get("closed")
        ]

        wins = [
            sim
            for sim in closed
            if float(sim.get("pnl_pct", 0) or 0) > 0
        ]

        losses = [
            sim
            for sim in closed
            if float(sim.get("pnl_pct", 0) or 0) <= 0
        ]

        big_losses = [
            sim
            for sim in closed
            if float(sim.get("pnl_pct", 0) or 0) <= -30
        ]

        total_invested = (
            len(closed)
            * self.SIMULATED_AMOUNT_EUR
        )

        total_pnl = sum(
            float(sim.get("pnl_eur", 0) or 0)
            for sim in closed
        )

        roi = (
            total_pnl / total_invested * 100
            if total_invested > 0
            else 0
        )

        win_rate = (
            len(wins) / len(closed) * 100
            if closed
            else 0
        )

        now = time.time()
        day_ago = now - 86400
        week_ago = now - (7 * 86400)

        pnl_day = sum(
            float(sim.get("pnl_eur", 0) or 0)
            for sim in closed
            if float(sim.get("exit_time", 0) or 0) >= day_ago
        )

        pnl_week = sum(
            float(sim.get("pnl_eur", 0) or 0)
            for sim in closed
            if float(sim.get("exit_time", 0) or 0) >= week_ago
        )

        best_trade = (
            max(
                closed,
                key=lambda x: float(
                    x.get("pnl_pct", 0) or 0
                ),
            )
            if closed
            else None
        )

        worst_trade = (
            min(
                closed,
                key=lambda x: float(
                    x.get("pnl_pct", 0) or 0
                ),
            )
            if closed
            else None
        )

        avg_duration = (
            sum(
                float(sim.get("duration_min", 0) or 0)
                for sim in closed
            )
            / len(closed)
            if closed
            else 0
        )

        by_reason: dict[str, dict[str, Any]] = {}

        for sim in closed:
            reason = sim.get("exit_reason", "unknown")

            by_reason.setdefault(
                reason,
                {
                    "count": 0,
                    "pnl": 0.0,
                },
            )

            by_reason[reason]["count"] += 1
            by_reason[reason]["pnl"] += float(
                sim.get("pnl_eur", 0) or 0
            )

        for value in by_reason.values():
            value["pnl"] = round(value["pnl"], 2)

        return {
            "total_simulated": self.total_simulated,
            "open_positions": len(self.open_positions),
            "closed_positions": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "big_losses": len(big_losses),
            "win_rate": round(win_rate, 1),
            "total_invested": round(total_invested, 2),
            "total_pnl": round(total_pnl, 2),
            "roi_pct": round(roi, 1),
            "pnl_day": round(pnl_day, 2),
            "pnl_week": round(pnl_week, 2),
            "avg_duration_min": round(avg_duration, 1),
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "by_reason": by_reason,
            "settings": {
                "check_interval": self.CHECK_INTERVAL,
                "sl_pct": self.SIM_SL_PCT,
                "tp_pct": self.SIM_TP_PCT,
                "max_age_hours": self.SIM_MAX_AGE_HOURS,
            },
        }

    def get_open_positions(self) -> list:
        return list(self.open_positions.values())

    def get_recent_trades(
        self,
        limit: int = 15,
    ) -> list:
        closed = [
            sim
            for sim in self.simulations_history
            if sim.get("closed")
        ]

        return sorted(
            closed,
            key=lambda x: float(
                x.get("exit_time", 0) or 0
            ),
            reverse=True,
        )[:limit]

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        try:
            if os.path.exists(self.DATA_FILE):
                with open(
                    self.DATA_FILE,
                    "r",
                    encoding="utf-8",
                ) as f:
                    data = json.load(f)

                self.open_positions = data.get(
                    "open_positions",
                    {},
                )

                self.simulations_history = data.get(
                    "history",
                    [],
                )

                self.total_simulated = data.get(
                    "total_simulated",
                    0,
                )

                self.total_closed = data.get(
                    "total_closed",
                    0,
                )

                self.total_pnl_eur = data.get(
                    "total_pnl_eur",
                    0,
                )

                logger.info(
                    f"🎮 Simulations chargées : "
                    f"{len(self.open_positions)} ouvertes, "
                    f"{len(self.simulations_history)} historique"
                )

        except Exception as exc:
            logger.error(f"Simulator load error : {exc}")

    def _save_data(self):
        try:
            data_dir = os.path.dirname(self.DATA_FILE)

            if data_dir:
                os.makedirs(data_dir, exist_ok=True)

            with open(
                self.DATA_FILE,
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    {
                        "open_positions": self.open_positions,
                        "history": self.simulations_history,
                        "total_simulated": self.total_simulated,
                        "total_closed": self.total_closed,
                        "total_pnl_eur": self.total_pnl_eur,
                        "saved_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

        except Exception as exc:
            logger.error(f"Simulator save error : {exc}")

    def reset(self) -> int:
        count = (
            len(self.simulations_history)
            + len(self.open_positions)
        )

        self.open_positions = {}
        self.simulations_history = []
        self.total_simulated = 0
        self.total_closed = 0
        self.total_pnl_eur = 0

        self._save_data()

        return count