# modules/sell_signal_generator.py v1.1
"""
Sell Signal Generator v1.1
Fix : Cooldown 15 min entre alertes du même token
Fix : Auto-close positions à -70% (tokens morts)
"""

import asyncio
import aiohttp
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("sell_signal")


class SellSignalGenerator:

    TP_LEVELS = [
        {"pct": 50,  "sell_pct": 25,  "label": "TP1"},
        {"pct": 100, "sell_pct": 25,  "label": "TP2"},
        {"pct": 200, "sell_pct": 25,  "label": "TP3"},
        {"pct": 500, "sell_pct": 25,  "label": "TP4"},
    ]

    SL_PCT = -25
    BUY_RATIO_DROP_THRESHOLD = 20
    VOLUME_DROP_THRESHOLD    = 50
    NEGATIVE_5M_THRESHOLD    = -10
    CHECK_INTERVAL           = 60

    # v1.1 : Cooldown pour éviter le spam
    ALERT_COOLDOWN           = 900   # 15 minutes
    AUTO_CLOSE_PNL           = -70   # Ferme auto si PnL < -70%

    def __init__(self, alert_callback):
        self.alert_callback = alert_callback
        self.session        = None
        self.running        = False
        self.positions = {}
        self.total_signals = 0
        self.tp_hits       = 0
        self.sl_hits       = 0
        self.dump_saves    = 0

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True
        logger.info(
            f"💰 SellSignalGenerator v1.1 démarré "
            f"(cooldown: {self.ALERT_COOLDOWN}s, "
            f"auto-close: {self.AUTO_CLOSE_PNL}%)"
        )
        asyncio.create_task(self._monitor_loop())

    async def stop(self):
        self.running = False
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("💰 SellSignalGenerator arrêté")

    def add_position(
        self,
        mint: str,
        symbol: str,
        entry_price: float,
        entry_mc: float,
        entry_liquidity: float,
        entry_buy_ratio: float,
        entry_volume_1h: float,
        source: str = "manual",
    ):
        self.positions[mint] = {
            "mint":            mint,
            "symbol":          symbol,
            "entry_price":     entry_price,
            "entry_mc":        entry_mc,
            "entry_liquidity": entry_liquidity,
            "entry_buy_ratio": entry_buy_ratio,
            "entry_volume_1h": entry_volume_1h,
            "entry_time":      time.time(),
            "source":          source,
            "tp_triggered":    [],
            "sl_triggered":    False,
            "max_gain":        0,
            "last_pnl":        0,
            "last_alert_time": 0,  # v1.1
            "snapshots":       [],
        }

        logger.info(
            f"💰 Position ajoutée : ${symbol} "
            f"@ ${entry_price:.8f} | MC ${entry_mc/1000:.0f}K"
        )

    def remove_position(self, mint: str):
        if mint in self.positions:
            pos = self.positions[mint]
            logger.info(f"💰 Position fermée : ${pos['symbol']}")
            del self.positions[mint]

    def get_positions_count(self) -> int:
        return len(self.positions)

    def get_positions(self) -> dict:
        return self.positions.copy()

    async def _monitor_loop(self):
        while self.running:
            try:
                if self.positions:
                    await self._check_all_positions()
            except Exception as e:
                logger.error(f"SellSignal loop error : {e}")
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _check_all_positions(self):
        tasks = [
            self._check_position(mint)
            for mint in list(self.positions.keys())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_position(self, mint: str):
        try:
            pos = self.positions.get(mint)
            if not pos:
                return

            # v1.1 : Auto-close si le token est mort
            if pos.get("last_pnl", 0) < self.AUTO_CLOSE_PNL:
                logger.info(
                    f"💰 Auto-close ${pos['symbol']} : "
                    f"PnL {pos['last_pnl']:.0f}% (token mort)"
                )
                del self.positions[mint]
                return

            current = await self._fetch_token_data(mint)
            if not current:
                return

            entry_price = pos["entry_price"]
            current_price = current.get("price", 0)

            if entry_price == 0 or current_price == 0:
                return

            pnl_pct = ((current_price - entry_price) / entry_price) * 100

            # v1.1 : Mémoriser dernier PnL
            pos["last_pnl"] = pnl_pct

            if pnl_pct > pos["max_gain"]:
                pos["max_gain"] = pnl_pct

            snapshot = {
                "time":       time.time(),
                "price":      current_price,
                "pnl_pct":    pnl_pct,
                "buy_ratio":  current.get("buy_ratio", 0),
                "volume_1h":  current.get("volume_1h", 0),
                "change_5m":  current.get("change_5m", 0),
            }
            pos["snapshots"].append(snapshot)

            if len(pos["snapshots"]) > 20:
                pos["snapshots"] = pos["snapshots"][-20:]

            signals = self._detect_signals(pos, current, pnl_pct)

            if signals:
                await self._trigger_alert(pos, current, pnl_pct, signals)

        except Exception as e:
            logger.error(f"Check position error : {e}")

    async def _fetch_token_data(self, mint: str) -> dict:
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
            price_usd  = float(pair.get("priceUsd", 0) or 0)
            liquidity  = pair.get("liquidity", {}).get("usd", 0) or 0
            volume_1h  = pair.get("volume", {}).get("h1", 0) or 0
            volume_24h = pair.get("volume", {}).get("h24", 0) or 0
            mc         = pair.get("marketCap", 0) or pair.get("fdv", 0) or 0

            price_change = pair.get("priceChange", {}) or {}
            change_5m  = price_change.get("m5", 0) or 0
            change_1h  = price_change.get("h1", 0) or 0

            txns = pair.get("txns", {}) or {}
            buys_1h  = txns.get("h1", {}).get("buys", 0) if txns.get("h1") else 0
            sells_1h = txns.get("h1", {}).get("sells", 0) if txns.get("h1") else 0
            txns_1h  = buys_1h + sells_1h
            buy_ratio = round(buys_1h / txns_1h * 100, 1) if txns_1h > 0 else 0

            return {
                "price":      price_usd,
                "liquidity":  liquidity,
                "volume_1h":  volume_1h,
                "volume_24h": volume_24h,
                "market_cap": mc,
                "change_5m":  change_5m,
                "change_1h":  change_1h,
                "buy_ratio":  buy_ratio,
                "buys_1h":    buys_1h,
                "sells_1h":   sells_1h,
            }

        except Exception as e:
            logger.debug(f"Fetch token data error : {e}")
            return None

    def _detect_signals(
        self,
        pos: dict,
        current: dict,
        pnl_pct: float,
    ) -> list:
        signals = []

        # TAKE PROFIT
        for tp in self.TP_LEVELS:
            label = tp["label"]
            if label in pos["tp_triggered"]:
                continue

            if pnl_pct >= tp["pct"]:
                signals.append({
                    "type":     "TP",
                    "label":    label,
                    "severity": "SUCCESS",
                    "message":  f"🎯 {label} atteint : +{tp['pct']}%",
                    "action":   f"Vendre {tp['sell_pct']}%",
                    "priority": 8,
                })
                pos["tp_triggered"].append(label)
                self.tp_hits += 1
                break

        # STOP LOSS
        if not pos["sl_triggered"] and pnl_pct <= self.SL_PCT:
            signals.append({
                "type":     "SL",
                "severity": "DANGER",
                "message":  f"🛑 STOP LOSS : {pnl_pct:.0f}%",
                "action":   "VENDRE 100% MAINTENANT",
                "priority": 10,
            })
            pos["sl_triggered"] = True
            self.sl_hits += 1

        # BUY RATIO CHUTE
        entry_br = pos["entry_buy_ratio"]
        current_br = current.get("buy_ratio", 0)

        if entry_br > 0:
            br_drop = entry_br - current_br
            if br_drop >= self.BUY_RATIO_DROP_THRESHOLD:
                signals.append({
                    "type":     "BUY_RATIO_DROP",
                    "severity": "WARNING",
                    "message":  f"📉 Buy ratio : {entry_br:.0f}% → {current_br:.0f}%",
                    "action":   "Considérer vendre 50%",
                    "priority": 7,
                })

        # VOLUME S'ÉCROULE
        entry_vol = pos["entry_volume_1h"]
        current_vol = current.get("volume_1h", 0)

        if entry_vol > 10_000 and current_vol > 0:
            vol_drop_pct = ((entry_vol - current_vol) / entry_vol) * 100
            if vol_drop_pct >= self.VOLUME_DROP_THRESHOLD:
                signals.append({
                    "type":     "VOLUME_DROP",
                    "severity": "WARNING",
                    "message":  f"📊 Volume 1h chute : -{vol_drop_pct:.0f}%",
                    "action":   "Momentum s'essouffle",
                    "priority": 6,
                })

        # 5min NÉGATIF
        change_5m = current.get("change_5m", 0)
        if change_5m <= self.NEGATIVE_5M_THRESHOLD:
            signals.append({
                "type":     "NEGATIVE_5M",
                "severity": "WARNING",
                "message":  f"⚠️ 5min négatif : {change_5m:.1f}%",
                "action":   "Dump possible en cours",
                "priority": 7,
            })

        # PERTE APRÈS GAIN
        max_gain = pos["max_gain"]
        if max_gain > 50 and pnl_pct < (max_gain - 30):
            signals.append({
                "type":     "PROFIT_LOST",
                "severity": "WARNING",
                "message":  f"⚠️ Perd les profits : max +{max_gain:.0f}% → +{pnl_pct:.0f}%",
                "action":   "Sécuriser les gains restants",
                "priority": 8,
            })

        # MOMENTUM CASSÉ
        snapshots = pos.get("snapshots", [])
        if len(snapshots) >= 3:
            last_3 = snapshots[-3:]
            all_negative = all(s.get("change_5m", 0) < 0 for s in last_3)
            if all_negative:
                signals.append({
                    "type":     "MOMENTUM_BROKEN",
                    "severity": "WARNING",
                    "message":  "⚠️ Momentum cassé : 3x 5min négatifs",
                    "action":   "Sortir maintenant",
                    "priority": 8,
                })

        return signals

    async def _trigger_alert(
        self,
        pos: dict,
        current: dict,
        pnl_pct: float,
        signals: list,
    ):
        """Déclenche une alerte de vente"""
        try:
            # v1.1 : COOLDOWN pour éviter le spam
            now = time.time()
            last_alert = pos.get("last_alert_time", 0)

            # Sauf si SL déclenché (urgence), on respecte le cooldown
            has_sl = any(s["type"] == "SL" for s in signals)
            if not has_sl:
                elapsed = now - last_alert
                if elapsed < self.ALERT_COOLDOWN:
                    logger.debug(
                        f"💰 Cooldown ${pos['symbol']} : "
                        f"{int(self.ALERT_COOLDOWN - elapsed)}s restant"
                    )
                    return

            pos["last_alert_time"] = now

            confidence = min(100, sum(s["priority"] for s in signals) * 10)
            top_signal = max(signals, key=lambda x: x["priority"])
            recommended_action = top_signal["action"]

            if has_sl:
                confidence = 100

            signal_data = {
                "mint":               pos["mint"],
                "symbol":             pos["symbol"],
                "entry_price":        pos["entry_price"],
                "current_price":      current["price"],
                "pnl_pct":            pnl_pct,
                "max_gain":           pos["max_gain"],
                "entry_time":         pos["entry_time"],
                "elapsed_min":        (time.time() - pos["entry_time"]) / 60,
                "signals":            signals,
                "top_signal":         top_signal,
                "recommended_action": recommended_action,
                "confidence":         confidence,
                "current_mc":         current.get("market_cap", 0),
                "current_liquidity":  current.get("liquidity", 0),
                "current_buy_ratio":  current.get("buy_ratio", 0),
            }

            self.total_signals += 1

            if any(s["type"] in ("BUY_RATIO_DROP", "VOLUME_DROP",
                                 "MOMENTUM_BROKEN") for s in signals):
                self.dump_saves += 1

            if self.alert_callback:
                await self.alert_callback(signal_data)

            logger.info(
                f"💰 SELL SIGNAL ${pos['symbol']} : "
                f"PnL {pnl_pct:+.0f}% | "
                f"Confiance: {confidence} | "
                f"{len(signals)} signaux"
            )

        except Exception as e:
            logger.error(f"Trigger alert error : {e}")

    def get_stats(self) -> dict:
        return {
            "positions_open": len(self.positions),
            "total_signals":  self.total_signals,
            "tp_hits":        self.tp_hits,
            "sl_hits":        self.sl_hits,
            "dump_saves":     self.dump_saves,
        }