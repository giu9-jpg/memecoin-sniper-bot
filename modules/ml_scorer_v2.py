# modules/ml_scorer_v2.py — ÉVOLUTION
"""
Ensemble model: XGBoost + LightGBM + Neural Net
Features: on-chain + social + technical + macro
Target: P(5x dans 24h) / P(rug dans 1h)
"""
import numpy as np
import xgboost as xgb
import lightgbm as lgb
from sklearn.ensemble import VotingClassifier
import joblib

class MLScorerV2:
    FEATURE_GROUPS = {
        "onchain": [
            "dev_credibility", "dev_token_count", "dev_rug_rate", "dev_avg_roi",
            "bundle_score", "co_buy_cluster_strength", "alpha_wallet_signal",
            "whale_inflow_5m", "whale_inflow_1h", "holder_distribution_gini",
            "top10_holder_pct", "liquidity_usd", "liq_to_mc_ratio",
            "pool_age_seconds", "transaction_count_5m", "buy_sell_ratio_5m",
            "unique_buyers_5m", "net_sol_inflow_5m",
        ],
        "social": [
            "twitter_mentions_5m", "twitter_sentiment", "kols_mentioning",
            "telegram_members_growth", "discord_activity",
            "website_quality_score", "social_links_completeness",
        ],
        "technical": [
            "price_change_1m", "price_change_5m", "price_change_15m",
            "volume_1m", "volume_5m", "volume_15m",
            "vwap_deviation", "rsi_5m", "macd_signal",
            "consecutive_green_candles", "pullback_depth",
        ],
        "macro": [
            "sol_price_change_1h", "sol_volume_change_1h",
            "btc_dominance", "fear_greed_index",
            "hour_utc", "is_weekend", "major_news_flag",
        ],
    }
    
    def __init__(self):
        self.models = {}
        self.scaler = None
        self.feature_names = []
        for group in self.FEATURE_GROUPS.values():
            self.feature_names.extend(group)
    
    def train(self, X, y_5x, y_rug):
        # Train 3 models per target
        for target_name, y in [("5x", y_5x), ("rug", y_rug)]:
            xgb_model = xgb.XGBClassifier(
                n_estimators=500, max_depth=6, learning_rate=0.01,
                subsample=0.8, colsample_bytree=0.8, random_state=42
            )
            lgb_model = lgb.LGBMClassifier(
                n_estimators=500, max_depth=6, learning_rate=0.01,
                subsample=0.8, colsample_bytree=0.8, random_state=42
            )
            # Neural net simple
            from sklearn.neural_network import MLPClassifier
            nn_model = MLPClassifier(
                hidden_layer_sizes=(128, 64, 32), 
                early_stopping=True, random_state=42
            )
            
            ensemble = VotingClassifier([
                ("xgb", xgb_model), ("lgb", lgb_model), ("nn", nn_model)
            ], voting="soft", weights=[2, 2, 1])
            
            ensemble.fit(X, y)
            self.models[target_name] = ensemble
    
    def predict_proba(self, features: dict) -> dict:
        X = np.array([[features.get(f, 0) for f in self.feature_names]])
        return {
            "p_5x": self.models["5x"].predict_proba(X)[0][1],
            "p_rug": self.models["rug"].predict_proba(X)[0][1],
        }
    
    def get_conviction_score(self, features: dict) -> float:
        """Score 0-10 combinant P(5x) et 1-P(rug)"""
        probs = self.predict_proba(features)
        return round(10 * (0.7 * probs["p_5x"] + 0.3 * (1 - probs["p_rug"])), 1)