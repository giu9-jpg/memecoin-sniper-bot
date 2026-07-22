# modules/jito_executor.py — NOUVEAU (optionnel, pour plus tard)
"""
Exécution via Jito bundles pour:
- Atomicité (buy + SL dans même bundle)
- Priority fee optimal
- Protection contre sandwich
- Tip Jito pour inclusion garantie
"""
import asyncio
import json
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from solders.message import MessageV0
import aiohttp

class JitoExecutor:
    JITO_BLOCK_ENGINE = "https://mainnet.block-engine.jito.wtf"
    BUNDLE_TIP_LAMPORTS = 100_000  # 0.0001 SOL tip
    
    def __init__(self, keypair: Keypair, rpc_url: str):
        self.keypair = keypair
        self.rpc_url = rpc_url
        self.session = None
    
    async def buy_with_sl_bundle(
        self, 
        token_mint: str, 
        amount_sol: float, 
        sl_percent: float = 25,
        priority_fee_microlamports: int = 50_000
    ) -> dict:
        """
        Crée un bundle Jito avec:
        1. Swap SOL -> Token (Jupiter/Raydium)
        2. Place ordre limite SL (via Meteora DLMM ou Jupiter DCA)
        3. Tip Jito
        """
        # 1. Get quote Jupiter
        quote = await self._jupiter_quote("So11111111111111111111111111111111111111112", token_mint, amount_sol)
        
        # 2. Build swap tx
        swap_tx = await self._jupiter_swap_tx(quote)
        
        # 3. Build SL tx (limit order sur Meteora DLMM ou Jupiter)
        sl_price = quote["out_amount"] * (100 - sl_percent) / 100
        sl_tx = await self._build_sl_tx(token_mint, quote["out_amount"], sl_price)
        
        # 4. Build tip tx
        tip_tx = self._build_tip_tx()
        
        # 5. Sign all
        bundle_txs = [swap_tx, sl_tx, tip_tx]
        signed = [self._sign_tx(tx) for tx in bundle_txs]
        
        # 6. Send bundle
        result = await self._send_bundle(signed)
        return result
    
    async def _send_bundle(self, signed_txs: list[VersionedTransaction]) -> dict:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [
                    [tx.to_bytes() for tx in signed_txs],
                    {"encoding": "base64"}
                ]
            }
            async with session.post(f"{self.JITO_BLOCK_ENGINE}/api/v1/bundles", json=payload) as resp:
                return await resp.json()