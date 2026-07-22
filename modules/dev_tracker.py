# modules/dev_tracker.py — NOUVEAU
"""
Surveille les wallets dev connus + nouveaux deployers.
Détecte : nouveau token créé → alerte AVANT premier achat public.
"""
import asyncio
from collections import defaultdict
from solders.pubkey import Pubkey
from solders.signature import Signature

class DevWalletTracker:
    """
    Track les wallets qui déploient des tokens (Pump.fun, Raydium, etc.)
    Source: 
    - Historical analysis (top devs des 30 derniers jours)
    - Real-time: detecter nouveaux deployers qui ont eu du succès
    """
    
    PUMP_FUN_CREATE_IX = "create"  # discriminator dans logs
    TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    
    def __init__(self, grpc_listener, callback):
        self.grpc = grpc_listener
        self.callback = callback
        self.known_devs = set()  # chargés depuis DB/historique
        self.dev_stats = defaultdict(lambda: {"tokens": 0, "rugs": 0, "avg_roi": 0.0})
        self.new_dev_candidates = {}
        
    async def on_new_pool(self, pool_data: dict):
        """Appelé par grpc_listener pour chaque nouveau pool"""
        dev_wallet = await self._identify_dev(pool_data)
        if not dev_wallet:
            return
            
        # Dev connu avec track record ?
        if dev_wallet in self.known_devs:
            stats = self.dev_stats[dev_wallet]
            if stats["rugs"] / max(stats["tokens"], 1) < 0.3 and stats["avg_roi"] > 2.0:
                await self.callback({
                    "type": "PRO_DEV_LAUNCH",
                    "dev": dev_wallet,
                    "pool": pool_data,
                    "stats": stats,
                    "priority": "CRITICAL",
                })
            return
        
        # Nouveau dev → track son premier token
        self.new_dev_candidates[dev_wallet] = pool_data
        # On attend de voir si ce token rug ou pump
    
    async def _identify_dev(self, pool_data) -> str | None:
        # Pour Pump.fun: le créateur est dans l'instruction create
        # Pour Raydium: le fee payer de la tx create pool
        # À implémenter selon source
        return pool_data.get("creator")
    
    def register_outcome(self, dev: str, token: str, rugged: bool, roi: float):
        """Appelé quand un token finit (rug ou gradue)"""
        if dev in self.new_dev_candidates:
            del self.new_dev_candidates[dev]
        
        stats = self.dev_stats[dev]
        stats["tokens"] += 1
        if rugged:
            stats["rugs"] += 1
        stats["avg_roi"] = (stats["avg_roi"] * (stats["tokens"] - 1) + roi) / stats["tokens"]
        
        # Promote si track record solide
        if stats["tokens"] >= 3 and stats["rugs"] / stats["tokens"] < 0.2:
            self.known_devs.add(dev)
            self._persist_dev(dev, stats)