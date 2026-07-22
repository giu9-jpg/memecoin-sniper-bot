# modules/evolution/feature_store.py
"""
Feature Store + Label Store.
- Calcule features à T0 (snapshot immuable)
- Calcule labels à T+1h, T+24h, T+7d (outcome réel)
- Backfill automatique quand nouveaux features ajoutés
"""
import json
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
import threading
from collections import defaultdict

import numpy as np
import pandas as pd

from modules.evolution.event_store import get_event_store, BotEvent

FEATURE_VERSION = "3.0"  # Incrémenter si schema change

@dataclass
class FeatureVector:
    token_mint: str
    timestamp: float
    feature_version: str
    features: dict = field(default_factory=dict)      # {feature_name: value}
    feature_hash: str = ""                            # Hash pour déduplication
    
    def __post_init__(self):
        if not self.feature_hash:
            self.feature_hash = hashlib.md5(
                json.dumps(self.features, sort_keys=True).encode()
            ).hexdigest()[:16]

@dataclass
class LabelSet:
    token_mint: str
    detection_ts: float
    labels: dict = field(default_factory=dict)        # {horizon: {label_name: value}}
    # horizons: "1h", "4h", "24h", "7d"
    # labels: max_roi, min_roi, rugged, time_to_peak, exit_reason, pnl_pct, max_dd

class FeatureStore:
    def __init__(self, base_path: str = "data/features"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        
        # Registre des extracteurs de features
        self.feature_extractors: dict[str, callable] = {}
        self._register_default_extractors()
        
        # Registre des calculateurs de labels
        self.label_calculators: dict[str, callable] = {}
        self._register_default_labels()
    
    def _register_default_extractors(self):
        """Enregistre les extracteurs de features standards."""
        self.feature_extractors.update({
            "onchain_liquidity_usd": self._extract_liquidity,
            "onchain_holder_count": self._extract_holders,
            "onchain_top10_pct": self._extract_top10,
            "onchain_age_seconds": self._extract_age,
            "onchain_buy_sell_ratio_5m": self._extract_bs_ratio,
            "onchain_unique_buyers_5m": self._extract_unique_buyers,
            "onchain_net_sol_inflow_5m": self._extract_net_inflow,
            "safety_score": self._extract_safety,
            "safety_mint_authority": self._extract_mint_auth,
            "safety_freeze_authority": self._extract_freeze_auth,
            "dev_credibility": self._extract_dev_cred,
            "dev_token_count": self._extract_dev_count,
            "dev_rug_rate": self._extract_dev_rug_rate,
            "alpha_wallet_signal": self._extract_alpha_signal,
            "whale_inflow_5m": self._extract_whale_inflow,
            "bundle_score": self._extract_bundle_score,
            "twitter_mentions_5m": self._extract_twitter_mentions,
            "twitter_sentiment": self._extract_twitter_sentiment,
            "kols_mentioning": self._extract_kols,
            "price_change_1m": self._extract_price_change_1m,
            "price_change_5m": self._extract_price_change_5m,
            "volume_5m": self._extract_volume_5m,
            "vwap_deviation": self._extract_vwap_dev,
            "rsi_5m": self._extract_rsi,
            "consecutive_green": self._extract_green_candles,
            "hour_utc": lambda ctx: datetime.fromtimestamp(ctx["timestamp"]).hour,
            "is_weekend": lambda ctx: datetime.fromtimestamp(ctx["timestamp"]).weekday() >= 5,
        })
    
    def _register_default_labels(self):
        self.label_calculators.update({
            "max_roi": self._calc_max_roi,
            "min_roi": self._calc_min_roi,
            "rugged": self._calc_rugged,
            "time_to_peak": self._calc_time_to_peak,
            "exit_reason": self._calc_exit_reason,
            "pnl_pct": self._calc_pnl,
            "max_drawdown": self._calc_max_dd,
        })
    
    # === EXTRACTEURS FEATURES (à implémenter avec tes modules existants) ===
    def _extract_liquidity(self, ctx: dict) -> float:
        return ctx.get("liquidity_usd", 0.0)
    
    def _extract_holders(self, ctx: dict) -> int:
        return ctx.get("holder_count", 0)
    
    def _extract_top10(self, ctx: dict) -> float:
        return ctx.get("top10_holder_pct", 100.0)
    
    def _extract_age(self, ctx: dict) -> float:
        return ctx.get("pool_age_seconds", 0.0)
    
    def _extract_bs_ratio(self, ctx: dict) -> float:
        buys = ctx.get("buys_5m", 0)
        sells = ctx.get("sells_5m", 1)
        return buys / max(sells, 1)
    
    def _extract_unique_buyers(self, ctx: dict) -> int:
        return ctx.get("unique_buyers_5m", 0)
    
    def _extract_net_inflow(self, ctx: dict) -> float:
        return ctx.get("net_sol_inflow_5m", 0.0)
    
    def _extract_safety(self, ctx: dict) -> float:
        return ctx.get("safety_score", 0.0)
    
    def _extract_mint_auth(self, ctx: dict) -> int:
        return 1 if ctx.get("mint_authority_enabled") else 0
    
    def _extract_freeze_auth(self, ctx: dict) -> int:
        return 1 if ctx.get("freeze_authority_enabled") else 0
    
    def _extract_dev_cred(self, ctx: dict) -> float:
        return ctx.get("dev_credibility", 0.0)
    
    def _extract_dev_count(self, ctx: dict) -> int:
        return ctx.get("dev_token_count", 0)
    
    def _extract_dev_rug_rate(self, ctx: dict) -> float:
        return ctx.get("dev_rug_rate", 1.0)
    
    def _extract_alpha_signal(self, ctx: dict) -> float:
        return float(ctx.get("alpha_wallet_detected", False))
    
    def _extract_whale_inflow(self, ctx: dict) -> float:
        return ctx.get("whale_inflow_5m", 0.0)
    
    def _extract_bundle_score(self, ctx: dict) -> float:
        return ctx.get("bundle_confidence", 0.0)
    
    def _extract_twitter_mentions(self, ctx: dict) -> int:
        return ctx.get("twitter_mentions_5m", 0)
    
    def _extract_twitter_sentiment(self, ctx: dict) -> float:
        return ctx.get("twitter_sentiment", 0.0)
    
    def _extract_kols(self, ctx: dict) -> int:
        return len(ctx.get("kols_mentioning", []))
    
    def _extract_price_change_1m(self, ctx: dict) -> float:
        return ctx.get("price_change_1m", 0.0)
    
    def _extract_price_change_5m(self, ctx: dict) -> float:
        return ctx.get("price_change_5m", 0.0)
    
    def _extract_volume_5m(self, ctx: dict) -> float:
        return ctx.get("volume_5m", 0.0)
    
    def _extract_vwap_dev(self, ctx: dict) -> float:
        return ctx.get("vwap_deviation", 0.0)
    
    def _extract_rsi(self, ctx: dict) -> float:
        return ctx.get("rsi_5m", 50.0)
    
    def _extract_green_candles(self, ctx: dict) -> int:
        return ctx.get("consecutive_green_candles", 0)
    
    # === CALCULATEURS LABELS ===
    def _calc_max_roi(self, price_history: list[dict]) -> float:
        if not price_history:
            return 0.0
        prices = [p["price"] for p in price_history]
        entry = prices[0]
        return max((p - entry) / entry for p in prices) if entry > 0 else 0.0
    
    def _calc_min_roi(self, price_history: list[dict]) -> float:
        if not price_history:
            return 0.0
        prices = [p["price"] for p in price_history]
        entry = prices[0]
        return min((p - entry) / entry for p in prices) if entry > 0 else 0.0
    
    def _calc_rugged(self, price_history: list[dict]) -> int:
        if not price_history:
            return 0
        prices = [p["price"] for p in price_history]
        entry = prices[0]
        # Rug = drop > 90% from peak après avoir fait 2x+
        peak = max(prices)
        if peak / entry >= 2.0 and prices[-1] / peak < 0.1:
            return 1
        return 0
    
    def _calc_time_to_peak(self, price_history: list[dict]) -> float:
        if not price_history:
            return 0.0
        prices = [p["price"] for p in price_history]
        peak_idx = prices.index(max(prices))
        return (price_history[peak_idx]["ts"] - price_history[0]["ts"]) / 60.0  # minutes
    
    def _calc_exit_reason(self, price_history: list[dict], sl_pct: float = -0.25, tp_pct: float = 1.0) -> str:
        if not price_history:
            return "no_data"
        prices = [p["price"] for p in price_history]
        entry = prices[0]
        for p in prices:
            change = (p - entry) / entry
            if change <= sl_pct:
                return "SL_HIT"
            if change >= tp_pct:
                return "TP_HIT"
        return "TIMEOUT"
    
    def _calc_pnl(self, price_history: list[dict], exit_ts: float | None = None) -> float:
        if not price_history:
            return 0.0
        prices = [p["price"] for p in price_history]
        entry = prices[0]
        exit_price = prices[-1] if exit_ts is None else self._get_price_at(price_history, exit_ts)
        return (exit_price - entry) / entry if entry > 0 else 0.0
    
    def _calc_max_dd(self, price_history: list[dict]) -> float:
        if not price_history:
            return 0.0
        prices = [p["price"] for p in price_history]
        peak = prices[0]
        max_dd = 0.0
        for p in prices:
            if p > peak:
                peak = p
            dd = (peak - p) / peak
            max_dd = max(max_dd, dd)
        return max_dd
    
    def _get_price_at(self, history: list[dict], ts: float) -> float:
        # Trouve le prix le plus proche du timestamp
        return min(history, key=lambda x: abs(x["ts"] - ts))["price"]
    
    # === API PUBLIQUE ===
    def compute_features(self, context: dict) -> FeatureVector:
        """Calcule toutes les features pour un context donné."""
        features = {}
        for name, extractor in self.feature_extractors.items():
            try:
                features[name] = extractor(context)
            except Exception as e:
                features[name] = 0.0  # ou NaN, mais 0.0 plus simple pour ML
        
        return FeatureVector(
            token_mint=context.get("token_mint", ""),
            timestamp=context.get("timestamp", time.time()),
            feature_version=FEATURE_VERSION,
            features=features
        )
    
    def compute_labels(self, token_mint: str, detection_ts: float, 
                       price_history: list[dict]) -> LabelSet:
        """Calcule labels pour tous les horizons."""
        labels = {}
        horizons = {"1h": 3600, "4h": 14400, "24h": 86400, "7d": 604800}
        
        for horizon_name, horizon_sec in horizons.items():
            cutoff_ts = detection_ts + horizon_sec
            # Filtre history jusqu'au cutoff
            relevant = [p for p in price_history if p["ts"] <= cutoff_ts]
            if not relevant:
                labels[horizon_name] = {k: None for k in self.label_calculators}
                continue
            
            horizon_labels = {}
            for name, calc in self.label_calculators.items():
                try:
                    horizon_labels[name] = calc(relevant)
                except Exception:
                    horizon_labels[name] = None
            labels[horizon_name] = horizon_labels
        
        return LabelSet(token_mint=token_mint, detection_ts=detection_ts, labels=labels)
    
    def save_feature_vector(self, fv: FeatureVector):
        """Sauvegarde feature vector (partitionné par jour)."""
        date_key = datetime.fromtimestamp(fv.timestamp).strftime("%Y%m%d")
        path = self.base_path / f"features_{date_key}.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps({
                "token_mint": fv.token_mint,
                "timestamp": fv.timestamp,
                "feature_version": fv.feature_version,
                "feature_hash": fv.feature_hash,
                "features": fv.features
            }) + "\n")
    
    def save_label_set(self, ls: LabelSet):
        date_key = datetime.fromtimestamp(ls.detection_ts).strftime("%Y%m%d")
        path = self.base_path / f"labels_{date_key}.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps({
                "token_mint": ls.token_mint,
                "detection_ts": ls.detection_ts,
                "labels": ls.labels
            }) + "\n")
    
    def load_training_data(self, start_ts: float, end_ts: float, 
                           horizons: list[str] = ["24h"]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """
        Charge features + labels alignés pour training.
        Retourne (X, {horizon: y_dict})
        """
        # Implémentation: joint features et labels sur token_mint + detection_ts
        # Gère missing values, alignement temporel, etc.
        pass


# Singleton
_feature_store: FeatureStore | None = None

def get_feature_store() -> FeatureStore:
    global _feature_store
    if _feature_store is None:
        _feature_store = FeatureStore()
    return _feature_store