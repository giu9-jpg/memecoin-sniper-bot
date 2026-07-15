# modules/auto_trader.py
# Achète et vend automatiquement via Jupiter DEX

import aiohttp
import base64
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

class AutoTrader:
    
    def __init__(self):
        self.wallet    = Keypair.from_base58_string(os.getenv("WALLET_PRIVATE_KEY"))
        self.rpc       = AsyncClient(os.getenv("SOLANA_RPC_URL"))
        self.jupiter   = "https://quote-api.jup.ag/v6"
    
    async def buy_token(self, token_address: str, amount_sol: float):
        """Achète un token via Jupiter."""
        # 1. Get quote
        quote = await self._get_quote(
            input_mint  = "So11111111111111111111111111111111111111112",
            output_mint = token_address,
            amount      = int(amount_sol * 1e9)
        )
        # 2. Swap
        await self._execute_swap(quote)
    
    async def sell_token(self, token_address: str, pct: int = 100):
        """Vend X% d'un token."""
        balance = await self._get_token_balance(token_address)
        amount  = int(balance * pct / 100)
        
        quote = await self._get_quote(
            input_mint  = token_address,
            output_mint = "So11111111111111111111111111111111111111112",
            amount      = amount
        )
        await self._execute_swap(quote)