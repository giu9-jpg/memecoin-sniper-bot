"""
Module de suivi des baleines
Vérifie si des wallets Smart Money détiennent le token
"""

import requests
import os
from dotenv import load_dotenv
from utils.logger import logger
from config.settings import KNOWN_WHALE_WALLETS

load_dotenv()


class WhaleTracker:
    def __init__(self):
        self.helius_rpc = os.getenv("SOLANA_RPC_URL")
        self.known_whales = KNOWN_WHALE_WALLETS

        logger.info(
            f"🐋 WhaleTracker initialisé — "
            f"{len(self.known_whales)} wallets surveillés"
        )

    def check_whale_activity(self, contract_address):
        """Vérifie si des baleines détiennent ce token"""
        whale_buyers = []

        for whale in self.known_whales:
            try:
                result = self._check_wallet_holds_token(
                    whale["address"],
                    contract_address
                )
                if result["holds"]:
                    whale_buyers.append({
                        **whale,
                        "balance": result["balance"],
                        "balance_usd": result.get(
                            "balance_usd", 0
                        ),
                    })
                    logger.info(
                        f"🐋 BALEINE DÉTECTÉE : "
                        f"{whale['name']} tient ce token !"
                    )
            except Exception as e:
                logger.error(
                    f"Whale check erreur ({whale['name']}) : {e}"
                )

        score_bonus = min(len(whale_buyers) * 1.5, 3.0)

        return {
            "whale_count": len(whale_buyers),
            "whales": whale_buyers,
            "is_smart_money_signal": len(whale_buyers) >= 1,
            "score_bonus": score_bonus,
            "whale_names": [
                w["name"] for w in whale_buyers
            ],
        }

    def _check_wallet_holds_token(self, wallet, token):
        """
        Vérifie via RPC Solana si un wallet détient un token
        Retourne le solde si trouvé
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    wallet,
                    {"mint": token},
                    {"encoding": "jsonParsed"}
                ]
            }
            response = requests.post(
                self.helius_rpc,
                json=payload,
                timeout=10
            )
            result = response.json()
            accounts = (
                result.get("result", {}).get("value", [])
            )

            if not accounts:
                return {"holds": False, "balance": 0}

            # Récupère le solde
            balance = 0
            for account in accounts:
                parsed = (
                    account.get("account", {})
                    .get("data", {})
                    .get("parsed", {})
                    .get("info", {})
                    .get("tokenAmount", {})
                )
                balance += float(
                    parsed.get("uiAmount", 0) or 0
                )

            return {
                "holds": balance > 0,
                "balance": round(balance, 2)
            }

        except Exception as e:
            logger.error(f"RPC erreur : {e}")
            return {"holds": False, "balance": 0}

    def get_recent_whale_buys(self, limit=5):
        """
        Récupère les dernières transactions des baleines
        (pour le rapport de démarrage)
        """
        recent = []
        for whale in self.known_whales[:3]:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [
                        whale["address"],
                        {"limit": limit}
                    ]
                }
                response = requests.post(
                    self.helius_rpc,
                    json=payload,
                    timeout=10
                )
                result = response.json()
                sigs = result.get(
                    "result", []
                )
                if sigs:
                    recent.append({
                        "whale": whale["name"],
                        "tx_count": len(sigs),
                        "last_activity": sigs[0].get(
                            "blockTime", 0
                        ),
                    })
            except Exception as e:
                logger.error(
                    f"Recent buys erreur ({whale['name']}): {e}"
                )

        return recent