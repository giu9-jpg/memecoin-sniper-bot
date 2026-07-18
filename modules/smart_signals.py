# modules/smart_signals.py — v3.0 FIXED
# FIX : protection contre division par zéro partout
# FIX : analyze_all_signals() retourne dict complet même si erreur
# FIX : historique des tokens limité en mémoire
# FIX : seuils plus réalistes

import time
from utils.logger import logger


# ══════════════════════════════════════════
# CONFIGURATION DES SIGNAUX
# ══════════════════════════════════════════
SIGNAL_CONFIG = {
    "volume_spike": {
        "threshold": 3.0,
        "bonus":     1.5,
        "critical":  False,
        "emoji":     "📈",
    },
    "buy_pressure": {
        "threshold": 3.0,
        "bonus":     1.5,
        "critical":  False,
        "emoji":     "🟢",
    },
    "low_mc_high_vol": {
        "threshold": 0,
        "bonus":     2.0,
        "critical":  True,
        "emoji":     "💎",
    },
    "momentum_building": {
        "threshold": 0,
        "bonus":     1.5,
        "critical":  False,
        "emoji":     "🚀",
    },
    "stealth_accumulation": {
        "threshold": 0,
        "bonus":     2.0,
        "critical":  True,
        "emoji":     "🎯",
    },
    "liquidity_growth": {
        "threshold": 0,
        "bonus":     1.0,
        "critical":  False,
        "emoji":     "💧",
    },
    "holder_velocity": {
        "threshold": 0,
        "bonus":     1.5,
        "critical":  False,
        "emoji":     "👥",
    },
}

MAX_HISTORY_TOKENS = 300   # Tokens max en mémoire


class SmartSignalDetector:

    def __init__(self):
        # Historique pour détecter les changements
        # {token_address: {metric: valeur_précédente}}
        self.token_history: dict[str, dict] = {}
        self.history_timestamps: dict[str, float] = {}

    # ═══════════════════════════════════════════════════
    # ANALYSE PRINCIPALE
    # ═══════════════════════════════════════════════════

    async def analyze_all_signals(
        self,
        token_address: str,
        current_data:  dict,
    ) -> dict:
        """
        Analyse tous les smart signals pour un token.
        FIX : retourne toujours un dict complet.
        FIX : ne plante pas si les données sont incomplètes.
        """
        signals      = []
        total_bonus  = 0.0
        has_critical = False

        try:
            # ── Extraction sécurisée des données ──────
            price        = float(current_data.get("price_usd",       0) or 0)
            market_cap   = float(current_data.get("market_cap",      0) or 0)
            liquidity    = float(current_data.get("liquidity",       0) or 0)
            volume_1h    = float(current_data.get("volume_1h",       0) or 0)
            volume_5m    = float(current_data.get("volume_5m",       0) or 0)
            holders      = int(current_data.get("holders",           0) or 0)
            score        = float(current_data.get("score",           5) or 5)
            vol_accel    = float(current_data.get("vol_acceleration", 1) or 1)
            ratio_buy_5m = float(current_data.get("ratio_buy_5m",    1) or 1)
            price_1h     = float(current_data.get("price_change_1h", 0) or 0)

            txns_5m  = current_data.get("txns_5m",  {}) or {}
            txns_1h  = current_data.get("txns_1h",  {}) or {}
            buys_5m  = int(txns_5m.get("buys",  0) or 0)
            sells_5m = int(txns_5m.get("sells", 0) or 0)
            buys_1h  = int(txns_1h.get("buys",  0) or 0)
            sells_1h = int(txns_1h.get("sells", 0) or 0)

            # Historique précédent
            prev = self.token_history.get(token_address, {})

            # ── SIGNAL 1 : Volume Spike ────────────────
            sig = self._check_volume_spike(
                volume_5m, volume_1h, vol_accel
            )
            if sig:
                signals.append(sig)

            # ── SIGNAL 2 : Buy Pressure ────────────────
            sig = self._check_buy_pressure(
                buys_5m, sells_5m, buys_1h, sells_1h, ratio_buy_5m
            )
            if sig:
                signals.append(sig)

            # ── SIGNAL 3 : Low MC / High Volume ───────
            sig = self._check_low_mc_high_vol(
                market_cap, volume_1h, liquidity
            )
            if sig:
                signals.append(sig)

            # ── SIGNAL 4 : Momentum Building ──────────
            sig = self._check_momentum_building(
                price_1h, vol_accel, ratio_buy_5m, score
            )
            if sig:
                signals.append(sig)

            # ── SIGNAL 5 : Stealth Accumulation ───────
            sig = self._check_stealth_accumulation(
                price_1h, volume_1h, buys_1h, sells_1h, prev
            )
            if sig:
                signals.append(sig)

            # ── SIGNAL 6 : Liquidity Growth ───────────
            sig = self._check_liquidity_growth(
                liquidity, market_cap, prev
            )
            if sig:
                signals.append(sig)

            # ── SIGNAL 7 : Holder Velocity ────────────
            sig = self._check_holder_velocity(
                holders, prev
            )
            if sig:
                signals.append(sig)

            # ── Calcul total ──────────────────────────
            for s in signals:
                total_bonus  += s.get("bonus", 0)
                if s.get("critical"):
                    has_critical = True

            # Cap du bonus
            total_bonus = min(total_bonus, 5.0)

            # ── Mise à jour historique ─────────────────
            self._update_history(
                token_address, {
                    "price":     price,
                    "volume_1h": volume_1h,
                    "liquidity": liquidity,
                    "holders":   holders,
                }
            )

        except Exception as e:
            logger.error(
                f"[SMART] Erreur analyze {token_address[:8]}: {e}"
            )

        return {
            "signals":      signals,
            "total_bonus":  round(total_bonus, 2),
            "signal_count": len(signals),
            "has_critical": has_critical,
        }

    # ═══════════════════════════════════════════════════
    # DÉTECTEURS INDIVIDUELS
    # ═══════════════════════════════════════════════════

    def _check_volume_spike(
        self,
        volume_5m: float,
        volume_1h: float,
        vol_accel: float,
    ) -> dict | None:
        """
        Détecte une explosion de volume.
        FIX : protection division par zéro.
        """
        try:
            if volume_1h <= 0:
                return None

            # Ratio volume 5m vs moyenne 5m de la 1h
            avg_5m_in_1h = volume_1h / 12
            if avg_5m_in_1h <= 0:
                return None

            ratio = volume_5m / avg_5m_in_1h

            if ratio >= 5.0 or vol_accel >= 4.0:
                return {
                    "name":     "volume_spike",
                    "emoji":    "📈",
                    "message":  f"Volume SPIKE x{ratio:.1f} (accel x{vol_accel:.1f})",
                    "bonus":    2.0,
                    "critical": False,
                }
            elif ratio >= 3.0 or vol_accel >= 3.0:
                return {
                    "name":     "volume_spike",
                    "emoji":    "📈",
                    "message":  f"Volume fort x{ratio:.1f}",
                    "bonus":    1.5,
                    "critical": False,
                }
            elif ratio >= 2.0:
                return {
                    "name":     "volume_spike",
                    "emoji":    "📊",
                    "message":  f"Volume hausse x{ratio:.1f}",
                    "bonus":    0.5,
                    "critical": False,
                }
        except Exception:
            pass
        return None

    def _check_buy_pressure(
        self,
        buys_5m:     int,
        sells_5m:    int,
        buys_1h:     int,
        sells_1h:    int,
        ratio_buy_5m: float,
    ) -> dict | None:
        """Détecte une forte pression acheteuse."""
        try:
            # FIX : évite division par zéro
            ratio_1h = buys_1h / max(sells_1h, 1)

            # Signal très fort : beaucoup d'achats, peu de ventes
            if buys_5m >= 20 and sells_5m == 0:
                return {
                    "name":     "buy_pressure",
                    "emoji":    "🟢",
                    "message":  f"{buys_5m} buys / 0 sells (5m) 🔥",
                    "bonus":    2.5,
                    "critical": True,
                }
            if ratio_buy_5m >= 5.0 and ratio_1h >= 3.0:
                return {
                    "name":     "buy_pressure",
                    "emoji":    "🟢",
                    "message":  f"Pression EXTRÊME 5m:{ratio_buy_5m:.1f}x 1h:{ratio_1h:.1f}x",
                    "bonus":    2.0,
                    "critical": True,
                }
            if ratio_buy_5m >= 3.0 and ratio_1h >= 2.0:
                return {
                    "name":     "buy_pressure",
                    "emoji":    "🟢",
                    "message":  f"Forte pression 5m:{ratio_buy_5m:.1f}x 1h:{ratio_1h:.1f}x",
                    "bonus":    1.5,
                    "critical": False,
                }
            if ratio_buy_5m >= 3.0:
                return {
                    "name":     "buy_pressure",
                    "emoji":    "🟢",
                    "message":  f"Buy pressure 5m:{ratio_buy_5m:.1f}x",
                    "bonus":    1.0,
                    "critical": False,
                }
        except Exception:
            pass
        return None

    def _check_low_mc_high_vol(
        self,
        market_cap: float,
        volume_1h:  float,
        liquidity:  float,
    ) -> dict | None:
        """
        Détecte un faible MC avec volume élevé.
        FIX : ratios protégés contre division par zéro.
        """
        try:
            if market_cap <= 0 or volume_1h <= 0:
                return None

            # Ratio volume/MC : si > 50% → très actif pour sa taille
            vol_mc_ratio = volume_1h / market_cap

            if market_cap < 100_000 and vol_mc_ratio > 1.0:
                return {
                    "name":     "low_mc_high_vol",
                    "emoji":    "💎",
                    "message":  (
                        f"MC ultra low (${market_cap/1000:.0f}K) "
                        f"+ vol {vol_mc_ratio:.1f}x MC"
                    ),
                    "bonus":    2.5,
                    "critical": True,
                }
            elif market_cap < 300_000 and vol_mc_ratio > 0.5:
                return {
                    "name":     "low_mc_high_vol",
                    "emoji":    "💎",
                    "message":  (
                        f"Low MC (${market_cap/1000:.0f}K) "
                        f"+ vol fort"
                    ),
                    "bonus":    1.5,
                    "critical": False,
                }
        except Exception:
            pass
        return None

    def _check_momentum_building(
        self,
        price_1h:    float,
        vol_accel:   float,
        ratio_buy:   float,
        score:       float,
    ) -> dict | None:
        """Détecte un momentum en construction."""
        try:
            # Momentum fort : prix + volume + buy pressure
            if (
                price_1h > 10
                and vol_accel >= 2.0
                and ratio_buy >= 2.0
            ):
                return {
                    "name":     "momentum_building",
                    "emoji":    "🚀",
                    "message":  (
                        f"Momentum FORT "
                        f"+{price_1h:.0f}% | "
                        f"vol x{vol_accel:.1f} | "
                        f"buy {ratio_buy:.1f}x"
                    ),
                    "bonus":    2.0,
                    "critical": True,
                }
            # Momentum modéré
            elif (
                price_1h > 5
                and vol_accel >= 1.5
                and ratio_buy >= 1.5
            ):
                return {
                    "name":     "momentum_building",
                    "emoji":    "🚀",
                    "message":  f"Momentum OK +{price_1h:.0f}%",
                    "bonus":    1.0,
                    "critical": False,
                }
        except Exception:
            pass
        return None

    def _check_stealth_accumulation(
        self,
        price_1h:  float,
        volume_1h: float,
        buys_1h:   int,
        sells_1h:  int,
        prev:      dict,
    ) -> dict | None:
        """
        Détecte une accumulation discrète.
        FIX : utilise l'historique si disponible.
        """
        try:
            if volume_1h <= 0 or buys_1h <= 0:
                return None

            # Prix stable + volume élevé + plus d'achats que ventes
            price_stable = abs(price_1h) < 5
            more_buys    = buys_1h > sells_1h * 1.5
            vol_decent   = volume_1h > 5_000

            if price_stable and more_buys and vol_decent:
                # Compare avec historique
                prev_vol = float(prev.get("volume_1h", 0) or 0)
                if prev_vol > 0:
                    vol_growth = volume_1h / prev_vol
                    if vol_growth >= 1.5:
                        return {
                            "name":     "stealth_accumulation",
                            "emoji":    "🎯",
                            "message":  (
                                f"ACCUMULATION discrète "
                                f"({buys_1h}b/{sells_1h}s | "
                                f"vol +{(vol_growth-1)*100:.0f}%)"
                            ),
                            "bonus":    2.0,
                            "critical": True,
                        }
                # Sans historique
                if more_buys and vol_decent:
                    return {
                        "name":     "stealth_accumulation",
                        "emoji":    "🎯",
                        "message":  (
                            f"Accumulation possible "
                            f"({buys_1h}b/{sells_1h}s)"
                        ),
                        "bonus":    1.0,
                        "critical": False,
                    }
        except Exception:
            pass
        return None

    def _check_liquidity_growth(
        self,
        liquidity:  float,
        market_cap: float,
        prev:       dict,
    ) -> dict | None:
        """Détecte une croissance de liquidité."""
        try:
            if liquidity <= 0:
                return None

            prev_liq = float(prev.get("liquidity", 0) or 0)

            # Croissance significative depuis dernier check
            if prev_liq > 0:
                growth = (liquidity - prev_liq) / prev_liq
                if growth >= 0.5:
                    return {
                        "name":     "liquidity_growth",
                        "emoji":    "💧",
                        "message":  (
                            f"Liq +{growth*100:.0f}% "
                            f"→ ${liquidity/1000:.0f}K"
                        ),
                        "bonus":    1.0,
                        "critical": False,
                    }

            # Ratio liq/MC élevé
            if market_cap > 0:
                liq_ratio = liquidity / market_cap
                if liq_ratio >= 0.3:
                    return {
                        "name":     "liquidity_growth",
                        "emoji":    "💧",
                        "message":  (
                            f"Liq solide "
                            f"({liq_ratio*100:.0f}% du MC)"
                        ),
                        "bonus":    0.5,
                        "critical": False,
                    }
        except Exception:
            pass
        return None

    def _check_holder_velocity(
        self,
        holders: int,
        prev:    dict,
    ) -> dict | None:
        """Détecte une croissance rapide des holders."""
        try:
            if holders <= 0:
                return None

            prev_holders = int(prev.get("holders", 0) or 0)

            if prev_holders <= 0:
                return None

            growth = holders - prev_holders
            if growth <= 0:
                return None

            pct = growth / prev_holders * 100

            if pct >= 50:
                return {
                    "name":     "holder_velocity",
                    "emoji":    "👥",
                    "message":  (
                        f"Holders EXPLOSION "
                        f"+{growth} ({pct:.0f}%)"
                    ),
                    "bonus":    2.0,
                    "critical": True,
                }
            elif pct >= 20:
                return {
                    "name":     "holder_velocity",
                    "emoji":    "👥",
                    "message":  (
                        f"Holders +{growth} ({pct:.0f}%)"
                    ),
                    "bonus":    1.0,
                    "critical": False,
                }
        except Exception:
            pass
        return None

    # ═══════════════════════════════════════════════════
    # HISTORIQUE
    # ═══════════════════════════════════════════════════

    def _update_history(
        self,
        token_address: str,
        data:          dict,
    ):
        """
        Met à jour l'historique d'un token.
        FIX : limite la mémoire à MAX_HISTORY_TOKENS.
        """
        # Nettoyage si trop de tokens
        if len(self.token_history) >= MAX_HISTORY_TOKENS:
            self._cleanup_history()

        self.token_history[token_address]    = data
        self.history_timestamps[token_address] = time.time()

    def _cleanup_history(self):
        """Supprime les tokens les plus vieux de l'historique."""
        now = time.time()

        # Supprime les tokens non vus depuis 1h
        old = [
            addr for addr, ts in self.history_timestamps.items()
            if now - ts > 3600
        ]
        for addr in old:
            self.token_history.pop(addr, None)
            self.history_timestamps.pop(addr, None)

        # Si encore trop, supprime les plus vieux
        if len(self.token_history) >= MAX_HISTORY_TOKENS:
            sorted_by_age = sorted(
                self.history_timestamps.items(),
                key=lambda x: x[1],
            )
            to_remove = sorted_by_age[: len(sorted_by_age) // 2]
            for addr, _ in to_remove:
                self.token_history.pop(addr, None)
                self.history_timestamps.pop(addr, None)

        logger.debug(
            f"[SMART] 🧹 Historique : "
            f"{len(self.token_history)} tokens"
        )