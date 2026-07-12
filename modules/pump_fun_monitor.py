"""
Multi-Chain Token Monitor
Scanne Solana, Ethereum, Base, BSC, Arbitrum, Polygon
via DexScreener
"""

import requests
from utils.logger import logger


class PumpFunMonitor:
    def __init__(self):
        self.dexscreener_base = (
            "https://api.dexscreener.com/latest"
        )
        self.known_tokens = set()
        
        # Chaînes à scanner
        self.chains = [
            "solana",
            "ethereum",
            "base",
            "bsc",
            "arbitrum",
            "polygon",
        ]

    def get_trending_tokens(self):
        """
        Récupère les tokens trending sur TOUTES les chaînes
        """
        all_tokens = []
        
        for chain in self.chains:
            try:
                tokens = self._get_chain_tokens(chain)
                all_tokens.extend(tokens)
                logger.info(
                    f"  📡 {chain.upper()} : "
                    f"{len(tokens)} tokens détectés"
                )
            except Exception as e:
                logger.error(f"  ❌ {chain} erreur : {e}")
                continue
        
        # Trie par volume (les plus actifs d'abord)
        all_tokens.sort(
            key=lambda x: x.get("volume_24h", 0),
            reverse=True
        )
        
        return all_tokens

    def _get_chain_tokens(self, chain):
        """
        Récupère les tokens d'une chaîne spécifique
        """
        try:
            # Cherche les paires actives sur cette chaîne
            url = (
                f"{self.dexscreener_base}"
                f"/dex/search/?q={chain}"
            )
            response = requests.get(url, timeout=10)
            data = response.json()

            pairs = data.get("pairs", [])
            
            # Filtre par chaîne
            chain_pairs = [
                p for p in pairs 
                if p.get("chainId") == chain
            ]

            tokens = []
            for pair in chain_pairs[:20]:
                contract = pair.get("baseToken", {}).get("address", "")
                
                if not contract or contract in self.known_tokens:
                    continue
                
                self.known_tokens.add(contract)

                tokens.append({
                    "name": pair.get(
                        "baseToken", {}
                    ).get("name", ""),
                    "symbol": pair.get(
                        "baseToken", {}
                    ).get("symbol", ""),
                    "contract": contract,
                    "chain": chain,
                    "liquidity": float(
                        pair.get("liquidity", {}).get("usd", 0)
                    ),
                    "volume_24h": float(
                        pair.get("volume", {}).get("h24", 0)
                    ),
                })

            return tokens

        except Exception as e:
            logger.error(f"DexScreener {chain} erreur : {e}")
            return []

    def get_graduating_tokens(self):
        """Compatibilité"""
        return self.get_trending_tokens()