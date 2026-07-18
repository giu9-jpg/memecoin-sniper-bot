# modules/ml_scorer.py v1.0
"""
Score ML léger basé sur les patterns historiques
Apprend automatiquement de tes retours (wins/losses)
Nécessite 10+ trades pour être efficace
Plus tu l'utilises, plus il s'améliore
"""

import json
import os
import time
from utils.logger import get_logger

logger = get_logger("ml_scorer")

ML_FILE     = "data/ml_patterns.json"
MIN_SAMPLES = 5


class MLScorer:

    def __init__(self):
        self.data = self._load()
        self.weights = {
            "holder_bucket":     1.2,
            "liquidity_bucket":  1.5,
            "mc_bucket":         1.0,
            "age_bucket":        1.3,
            "has_alpha_wallet":  2.0,
            "has_twitter":       1.5,
            "whale_inflow":      1.3,
            "top_holder_bucket": -1.0,
            "hour_bucket":       0.4,
            "safety_bucket":     1.8,
        }
        logger.info(
            f"🧠 MLScorer chargé | "
            f"{len(self.data.get('trades', []))} trades en mémoire"
        )

    # ════════════════════════════════════════
    # CHARGEMENT / SAUVEGARDE
    # ════════════════════════════════════════

    def _load(self) -> dict:
        if os.path.exists(ML_FILE):
            try:
                with open(ML_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"ML load error: {e}")
        return {"trades": [], "win_rates": {}}

    def _save(self):
        try:
            os.makedirs("data", exist_ok=True)
            with open(ML_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"ML save error: {e}")

    # ════════════════════════════════════════
    # FEATURE EXTRACTION
    # ════════════════════════════════════════

    def extract_features(
        self,
        token_data: dict,
        analysis:   dict = None,
        safety:     dict = None
    ) -> dict:
        """
        Transforme les données d'un token en features ML.
        Chaque feature est un bucket (catégorie).
        """
        analysis = analysis or {}
        safety   = safety or {}

        mc      = token_data.get("market_cap", 0) or 0
        liq     = token_data.get("liquidity", 0) or 0
        holders = token_data.get("holders", 0) or 0
        age     = token_data.get("age_minutes", 999) or 999
        top1    = analysis.get("top_holder_pct", 0) or 0
        s_score = safety.get("score", 10)

        hour = time.localtime().tm_hour

        return {
            "holder_bucket":     self._b(holders, [20, 50, 100, 500]),
            "liquidity_bucket":  self._b(liq,    [1000, 5000, 20000, 100000]),
            "mc_bucket":         self._b(mc,     [10000, 50000, 200000, 1000000]),
            "age_bucket":        self._b(age,    [2, 5, 15, 60]),
            "has_alpha_wallet":  str(bool(analysis.get("alpha_wallet_list"))),
            "has_twitter":       str(bool(analysis.get("twitter_mentions"))),
            "whale_inflow":      str(bool(analysis.get("whale_inflow_detected"))),
            "top_holder_bucket": self._b(top1,  [10, 20, 30, 50]),
            "hour_bucket":       self._b(hour,  [6, 12, 18, 22]),
            "safety_bucket":     self._b(s_score, [4, 6, 8, 9]),
        }

    # ════════════════════════════════════════
    # SCORING
    # ════════════════════════════════════════

    def get_ml_bonus(self, features: dict) -> float:
        """
        Retourne un bonus entre -1.5 et +1.5.
        Basé sur les win rates historiques.
        0.0 si pas assez de données.
        """
        trades = self.data.get("trades", [])

        if len(trades) < MIN_SAMPLES:
            return 0.0

        win_rates = self.data.get("win_rates", {})
        total_bonus = 0.0
        counted = 0

        for feat_name, feat_val in features.items():
            key   = f"{feat_name}:{feat_val}"
            stats = win_rates.get(key, {})
            n     = stats.get("total", 0)

            if n < 3:
                continue

            wr     = stats.get("wins", 0) / n
            weight = self.weights.get(feat_name, 1.0)

            bonus = (wr - 0.5) * 2.0 * weight
            total_bonus += bonus
            counted += 1

        if counted == 0:
            return 0.0

        result = max(-1.5, min(1.5, total_bonus / counted))
        logger.debug(
            f"🧠 ML bonus: {result:+.2f} "
            f"({counted} features, {len(trades)} trades)"
        )
        return result

    # ════════════════════════════════════════
    # APPRENTISSAGE
    # ════════════════════════════════════════

    def record_result(
        self,
        token_name: str,
        is_win:     bool,
        pnl_pct:    float,
        features:   dict = None
    ):
        """
        Enregistre le résultat d'un trade.
        Appelé via /win ou /loss dans Telegram.
        """
        if features is None:
            features = {}

        trade = {
            "token_name": token_name,
            "is_win":     is_win,
            "pnl_pct":    round(pnl_pct, 2),
            "features":   features,
            "timestamp":  time.time(),
        }
        self.data.setdefault("trades", []).append(trade)

        # Mettre à jour les win rates
        win_rates = self.data.setdefault("win_rates", {})
        for feat_name, feat_val in features.items():
            key = f"{feat_name}:{feat_val}"
            wr  = win_rates.setdefault(key, {"wins": 0, "total": 0})
            wr["total"] += 1
            if is_win:
                wr["wins"] += 1

        # Garder max 1000 trades
        if len(self.data["trades"]) > 1000:
            self.data["trades"] = self.data["trades"][-1000:]

        self._save()

        icon = "✅" if is_win else "❌"
        logger.info(
            f"{icon} ML enregistré | {token_name} | "
            f"PnL: {pnl_pct:+.1f}% | "
            f"Total: {len(self.data['trades'])} trades"
        )

    def get_stats(self) -> dict:
        """Statistiques du modèle ML"""
        trades = self.data.get("trades", [])
        if not trades:
            return {
                "trades": 0, "ready": False,
                "message": f"Besoin de {MIN_SAMPLES} trades"
            }

        wins    = [t for t in trades if t.get("is_win")]
        losses  = len(trades) - len(wins)
        avg_pnl = sum(t.get("pnl_pct", 0) for t in trades) / len(trades)

        return {
            "trades":   len(trades),
            "wins":     len(wins),
            "losses":   losses,
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "avg_pnl":  round(avg_pnl, 1),
            "ready":    len(trades) >= MIN_SAMPLES,
            "features": len(self.data.get("win_rates", {})),
        }

    def _b(self, value: float, thresholds: list) -> str:
        """Convertit une valeur en bucket"""
        for t in thresholds:
            if value < t:
                return f"<{t}"
        return f">={thresholds[-1]}"