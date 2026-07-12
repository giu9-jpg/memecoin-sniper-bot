"""
Monitor de nouveaux tokens Solana
Utilise DexScreener — FILTRE STRICT Solana uniquement
"""

import requests
from utils.logger import logger


class PumpFunMonitor:
    def __init__(self):
        self.dexscreener_base = (
            "https://api.dexscreener.com/latest"
        )
        # Endpoint spécifique aux tokens Solana récents
        self.token_profiles_url = (
            "https://api.dexscreener.com"
            "/token-profiles/latest/v1"
        )
        self.token_boosts_url = (
            "https://api.dexscreener.com"
            "/token-boosts/latest/v1"
        )
        self.known_tokens = set()

    def get_trending_tokens(self):
        """
        Récupère les tokens Solana trending
        FILTRE STRICT : Solana uniquement
        """
        try:
            # Utilise l'endpoint des tokens boostés
            # (plus pertinent pour les memecoins récents)
            response = requests.get(
                self.token_boosts_url,
                timeout=10
            )

            if response.status_code != 200:
                logger.error(
                    f"DexScreener boosts erreur : "
                    f"{response.status_code}"
                )
                return self._fallback_search()

            data = response.json()

            # ⚠️ FILTRE STRICT : Solana uniquement
            solana_tokens = [
                t for t in data
                if t.get("chainId") == "solana"
            ]

            logger.info(
                f"📊 {len(solana_tokens)} tokens "
                f"Solana boostés trouvés"
            )

            trending = []
            for token in solana_tokens[:30]:
                contract = token.get("tokenAddress", "")

                # ⚠️ VÉRIFICATION : Pas d'adresse EVM
                if not contract or contract.startswith("0x"):
                    continue

                if contract in self.known_tokens:
                    continue

                self.known_tokens.add(contract)

                trending.append({
                    "name": token.get("description", "")[:50],
                    "symbol": "???",
                    "contract": contract,
                    "chain": "solana",
                })

            return trending

        except Exception as e:
            logger.error(f"DexScreener erreur : {e}")
            return self._fallback_search()

    def _fallback_search(self):
        """
        Méthode de secours : recherche via search API
        avec filtre Solana strict
        """
        try:
            url = (
                f"{self.dexscreener_base}"
                f"/dex/search/?q=SOL"
            )
            response = requests.get(url, timeout=10)
            data = response.json()

            pairs = data.get("pairs", [])

            # ⚠️ TRIPLE FILTRE : Solana uniquement
            solana_pairs = [
                p for p in pairs
                if (
                    p.get("chainId") == "solana"
                    and not p.get(
                        "baseToken", {}
                    ).get("address", "").startswith("0x")
                )
            ]

            logger.info(
                f"📊 Fallback : {len(solana_pairs)} "
                f"paires Solana"
            )

            trending = []
            for pair in solana_pairs[:30]:
                contract = pair.get(
                    "baseToken", {}
                ).get("address", "")

                if not contract or contract in self.known_tokens:
                    continue

                # ⚠️ SÉCURITÉ : Rejette les EVM
                if contract.startswith("0x"):
                    logger.warning(
                        f"⛔ Token EVM détecté et ignoré : "
                        f"{contract}"
                    )
                    continue

                self.known_tokens.add(contract)

                # Filtre âge : moins de 7 jours
                created_at = pair.get("pairCreatedAt", 0)
                if created_at:
                    import time
                    age_hours = (
                        time.time() - created_at / 1000
                    ) / 3600
                    if age_hours > 168:  # 7 jours max
                        continue

                trending.append({
                    "name": pair.get(
                        "baseToken", {}
                    ).get("name", ""),
                    "symbol": pair.get(
                        "baseToken", {}
                    ).get("symbol", ""),
                    "contract": contract,
                    "chain": "solana",
                    "liquidity": float(
                        pair.get("liquidity", {}).get("usd", 0)
                    ),
                    "volume_24h": float(
                        pair.get("volume", {}).get("h24", 0)
                    ),
                })

            return trending

        except Exception as e:
            logger.error(f"Fallback erreur : {e}")
            return []

    def get_graduating_tokens(self):
        """Compatibilité"""
        return self.get_trending_tokens()