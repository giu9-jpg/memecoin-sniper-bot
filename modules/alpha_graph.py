# modules/alpha_graph.py — NOUVEAU
"""
Construit un graphe d'influence on-chain:
- Wallets qui achètent ENSEMBLE régulièrement
- Wallets qui copient d'autres wallets (lead/lag)
- Clusters de "smart money" vs "dumb money"
- Score de crédibilité par wallet
"""
import networkx as nx
from collections import defaultdict
import json

class AlphaGraph:
    def __init__(self, min_co_occurrences=5, min_lead_lag_correlation=0.7):
        self.graph = nx.DiGraph()
        self.wallet_stats = defaultdict(lambda: {
            "buys": 0, "wins": 0, "total_roi": 0.0,
            "followers": set(), "following": set(),
            "cluster": None, "credibility": 0.0
        })
        self.min_co = min_co_occurrences
        self.min_corr = min_lead_lag_correlation
        self.co_buy_matrix = defaultdict(lambda: defaultdict(int))
        
    async def record_buy(self, wallet: str, token: str, timestamp: int, price: float):
        """Appelé pour CHAQUE achat détecté (alpha wallets + nouveaux)"""
        # Co-occurrence tracking
        recent_buyers = self._get_recent_buyers(token, timestamp, window=300)  # 5min
        for other in recent_buyers:
            if other != wallet:
                self.co_buy_matrix[wallet][other] += 1
                self.co_buy_matrix[other][wallet] += 1
        
        # Lead/lag detection
        await self._update_lead_lag(wallet, token, timestamp)
    
    def _get_recent_buyers(self, token, timestamp, window):
        # À implémenter avec index temps-réel
        return []
    
    async def _update_lead_lag(self, wallet, token, timestamp):
        # Détecte si wallet A achète systématiquement AVANT wallet B
        # Correlation sur 20+ tokens communs
        pass
    
    def compute_credibility(self):
        """PageRank-style sur le graphe de co-buy + lead/lag + win rate"""
        for wallet, stats in self.wallet_stats.items():
            # Facteurs:
            # - Win rate historique
            # - Average ROI
            # - Centralité dans graphe (suivi par d'autres)
            # - Lead score (achète avant les autres)
            # - Cluster quality (son cluster a quel WR?)
            pass
    
    def get_top_alpha(self, limit=50) -> list[dict]:
        """Retourne les wallets Tier 0 actuels"""
        sorted_wallets = sorted(
            self.wallet_stats.items(),
            key=lambda x: x[1]["credibility"],
            reverse=True
        )
        return [
            {"wallet": w, **stats} 
            for w, stats in sorted_wallets[:limit]
        ]
    
    def detect_new_smart_money(self, min_credibility=0.8) -> list[str]:
        """Wallets qui montent en crédibilité récemment"""
        return [
            w for w, s in self.wallet_stats.items()
            if s["credibility"] >= min_credibility and w not in self.known_tier1
        ]