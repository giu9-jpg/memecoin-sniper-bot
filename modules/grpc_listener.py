# modules/grpc_listener.py — NOUVEAU MODULE CORE
"""
Yellowstone gRPC listener — sub-50ms new pool detection.
Remplace pump_fun_monitor.py + raydium_monitor.py + dex_polling.
"""
import asyncio
import grpc
from typing import Callable, Awaitable
import os

# Yellowstone gRPC proto (generate from https://github.com/rpcpool/yellowstone-grpc)
# pip install yellowstone-grpc-client
from yellowstone_grpc.client import YellowstoneClient
from yellowstone_grpc.proto.geyser_pb2 import (
    SubscribeRequest,
    SubscribeRequestFilterTransactions,
    CommitmentLevel,
)

class GrpcPoolListener:
    """
    Écoute TOUS les nouveaux pools Raydium/Pump.fun/Meteora/Orca en temps réel.
    Filtre side-car: ne garde que les creates de pool avec liquidité > threshold.
    """
    
    PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    RAYDIUM_CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
    RAYDIUM_CLMM = "CAMMCzo5YL8w4Vzw8KJG6UfxQxX4Z7tGqY9Vq8J7KzX"
    METEORA_DLMM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
    ORCA_WHIRLPOOL = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
    
    TARGET_PROGRAMS = [
        PUMP_FUN_PROGRAM,
        RAYDIUM_CPMM,
        RAYDIUM_CLMM,
        METEORA_DLMM,
        ORCA_WHIRLPOOL,
    ]
    
    def __init__(self, callback: Callable[[dict], Awaitable[None]]):
        self.callback = callback
        self.client = None
        self.running = False
        
    async def start(self):
        endpoint = os.getenv("YELLOWSTONE_GRPC_ENDPOINT", "grpc.yellowstone.com:443")
        token = os.getenv("YELLOWSTONE_GRPC_TOKEN")  # ton token Yellowstone/Shyft/Triton
        
        self.client = YellowstoneClient(endpoint, token=token)
        
        # Filtre: transactions qui touchent les programmes cibles
        tx_filter = SubscribeRequestFilterTransactions(
            account_include=[],
            account_exclude=[],
            account_required=self.TARGET_PROGRAMS,
            vote=False,
            failed=False,
        )
        
        request = SubscribeRequest(
            transactions={"pools": tx_filter},
            commitment=CommitmentLevel.PROCESSED,  # LE PLUS RAPIDE
        )
        
        self.running = True
        async for update in self.client.subscribe(request):
            if not self.running:
                break
            await self._process_update(update)
    
    async def _process_update(self, update):
        tx = update.transaction
        if not tx or not tx.transaction:
            return
            
        # Parse logs pour détecter "initialize pool" / "create pool"
        logs = tx.transaction.meta.log_messages or []
        for log in logs:
            if any(kw in log.lower() for kw in ["initialize", "create pool", "initialize2", "createpool"]):
                # Extract pool address, tokens, initial liquidity
                pool_data = self._parse_pool_creation(tx, log)
                if pool_data and pool_data.get("initial_liq_usd", 0) >= 1000:  # threshold min
                    await self.callback(pool_data)
                break
    
    def _parse_pool_creation(self, tx, log) -> dict | None:
        # TODO: parse instruction data pour extraire mint_a, mint_b, liquidity
        # Utilise solders/py-solana pour decode les instructions
        return {
            "pool_address": "...",
            "base_mint": "...",
            "quote_mint": "So11111111111111111111111111111111111111112",
            "initial_liq_usd": 5000,
            "source": "grpc",
            "timestamp": tx.slot,
        }
    
    async def stop(self):
        self.running = False
        if self.client:
            await self.client.close()