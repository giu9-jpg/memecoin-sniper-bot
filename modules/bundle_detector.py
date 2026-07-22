# modules/bundle_detector.py — NOUVEAU
"""
Détecte les bundles (achats coordonnés dans le même slot/block).
Signaux:
- Même wallet qui achète multiple tokens même slot
- Multiple wallets qui achètent même token même slot (coordinated)
- Jito bundle detection (tip accounts)
"""
from collections import defaultdict
from dataclasses import dataclass
import time

@dataclass
class BundleSignal:
    token_mint: str
    slot: int
    buyers: list[str]
    amounts: list[float]
    is_jito: bool
    coordinator: str | None  # wallet qui finance le bundle
    confidence: float

class BundleDetector:
    JITO_TIP_ACCOUNTS = {
        "96gYZGLnJYVFYjzsw5r8w6Y9zGgLwM6cKp8zJZ8vX9K",
        "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
        # ... tous les Jito tip accounts
    }
    
    def __init__(self, grpc_listener, callback):
        self.grpc = grpc_listener
        self.callback = callback
        self.slot_buys = defaultdict(list)  # slot -> [(buyer, token, amount, tx_sig)]
        self.cleanup_task = None
        
    async def start(self):
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def on_transaction(self, tx_data: dict):
        """Appelé pour CHAQUE transaction (via gRC listener)"""
        slot = tx_data.get("slot")
        if not slot:
            return
            
        # Parse swaps/buys
        buys = self._extract_buys(tx_data)
        for buy in buys:
            self.slot_buys[slot].append(buy)
        
        # Analyse bundle sur ce slot
        await self._analyze_slot(slot)
    
    def _extract_buys(self, tx) -> list[dict]:
        # Parse instructions pour trouver swaps (Raydium, Pump.fun, etc.)
        # Retourne [{"buyer": "...", "token": "...", "amount_sol": 0.5, "sig": "..."}]
        return []
    
    async def _analyze_slot(self, slot: int):
        buys = self.slot_buys.get(slot, [])
        if len(buys) < 3:  # minimum pour bundle suspect
            return
        
        # Group by token
        by_token = defaultdict(list)
        for buy in buys:
            by_token[buy["token"]].append(buy)
        
        for token, token_buys in by_token.items():
            if len(token_buys) >= 3:
                # Coordinated buy sur même token
                signal = BundleSignal(
                    token_mint=token,
                    slot=slot,
                    buyers=[b["buyer"] for b in token_buys],
                    amounts=[b["amount_sol"] for b in token_buys],
                    is_jito=any(b.get("jito_tip", False) for b in token_buys),
                    coordinator=self._find_coordinator(token_buys),
                    confidence=min(len(token_buys) / 10.0, 1.0),
                )
                await self.callback(signal)
    
    def _find_coordinator(self, buys) -> str | None:
        # Cherche wallet qui envoie SOL aux buyers juste avant
        # ou wallet commun qui fund les buyers
        return None
    
    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(60)
            cutoff = max(self.slot_buys.keys()) - 100 if self.slot_buys else 0
            for slot in list(self.slot_buys.keys()):
                if slot < cutoff:
                    del self.slot_buys[slot]