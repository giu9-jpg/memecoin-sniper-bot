#!/usr/bin/env python3
# scripts/check_wallets.py — v1.0
# Vérifie les alpha wallets et leur activité récente
# Lance : python scripts/check_wallets.py

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from utils.logger import logger
from config.alpha_wallets import ALPHA_WALLETS, get_wallet_info


async def check_wallet_activity(wallet: str, api_key: str) -> dict:
    """Vérifie l'activité récente d'un wallet."""
    import aiohttp

    result = {
        "wallet":     wallet,
        "accessible": False,
        "tx_count":   0,
        "last_tx_ts": 0,
        "error":      None,
    }

    try:
        url    = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": api_key, "limit": 5, "type": "SWAP"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    txs = await resp.json()
                    if isinstance(txs, list):
                        result["accessible"] = True
                        result["tx_count"]   = len(txs)
                        if txs:
                            result["last_tx_ts"] = txs[0].get(
                                "timestamp", 0
                            )
                elif resp.status == 429:
                    result["error"] = "Rate limit"
                else:
                    result["error"] = f"Status {resp.status}"

    except Exception as e:
        result["error"] = str(e)

    return result


async def main():
    rpc_url = os.getenv("SOLANA_RPC_URL", "")
    api_key = (
        rpc_url.split("api-key=")[-1]
        if "api-key=" in rpc_url else ""
    )

    if not api_key:
        print("❌ SOLANA_RPC_URL sans api-key= — impossible de vérifier")
        return

    print("\n🐋 Vérification des alpha wallets\n" + "═" * 50)

    now = time.time()

    for tier, wallets in ALPHA_WALLETS.items():
        print(f"\n📊 {tier} ({len(wallets)} wallets)")
        print("─" * 40)

        for wallet in wallets:
            info   = get_wallet_info(wallet)
            result = await check_wallet_activity(wallet, api_key)

            # Formate l'âge de la dernière tx
            if result["last_tx_ts"]:
                age_h = (now - result["last_tx_ts"]) / 3600
                last  = f"{age_h:.1f}h ago"
            else:
                last = "Jamais"

            status = "✅" if result["accessible"] else "❌"
            error  = f" ({result['error']})" if result["error"] else ""

            print(
                f"  {status} {wallet[:12]}... | "
                f"tier:{info['tier']} | "
                f"bonus:+{info['bonus']} | "
                f"seuil:{info['threshold']} | "
                f"txs:{result['tx_count']} | "
                f"last:{last}{error}"
            )

            # Rate limiting
            await asyncio.sleep(0.5)

    print("\n✅ Vérification terminée\n")


if __name__ == "__main__":
    asyncio.run(main())