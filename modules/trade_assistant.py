# modules/trade_assistant.py v1.0
"""
Trade Assistant
Aide à l'achat/vente manuel avec confirmation.

Fonctionnalités :
  - Génère les URLs Photon pré-remplies
  - Stocke les achats en attente
  - Confirme l'achat après validation utilisateur
  - Enregistre automatiquement dans portfolio
"""

import asyncio
import aiohttp
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("trade_assistant")


class TradeAssistant:

    # Prix SOL en USD (mis à jour périodiquement)
    SOL_PRICE_USD = 200  # valeur par défaut, updated régulièrement

    def __init__(self, portfolio_tracker, alert_sender, ml_scorer):
        self.portfolio_tracker = portfolio_tracker
        self.alert_sender      = alert_sender
        self.ml_scorer         = ml_scorer

        self.session = None
        self.running = False

        # Achats en attente de confirmation
        # {user_id: {symbol, amount_eur, mint, timestamp}}
        self.pending_buys = {}

        # Stats
        self.total_buys_confirmed = 0
        self.total_buys_cancelled = 0
        self.total_sells          = 0

    async def start(self):
        """Démarre le module"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True

        # Update prix SOL
        await self._update_sol_price()

        logger.info(
            f"💰 TradeAssistant démarré "
            f"(SOL: ${self.SOL_PRICE_USD:.0f})"
        )

        # Démarre la boucle de mise à jour prix SOL
        asyncio.create_task(self._price_update_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("💰 TradeAssistant arrêté")

    # ════════════════════════════════════════
    # UPDATE PRIX SOL
    # ════════════════════════════════════════

    async def _price_update_loop(self):
        """Met à jour le prix SOL toutes les 5 minutes"""
        while self.running:
            await asyncio.sleep(300)
            try:
                await self._update_sol_price()
            except Exception as e:
                logger.debug(f"SOL price update error : {e}")

    async def _update_sol_price(self):
        """Récupère le prix actuel de SOL"""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.SOL_PRICE_USD = data.get("solana", {}).get("usd", 200)
                    logger.debug(f"SOL price updated : ${self.SOL_PRICE_USD:.2f}")
        except Exception:
            pass

    # ════════════════════════════════════════
    # PRÉPARER UN ACHAT
    # ════════════════════════════════════════

    async def prepare_buy(
        self,
        user_id: str,
        symbol: str,
        amount_eur: float,
        mint: str = None,
    ) -> dict:
        """
        Prépare un achat.

        Args:
          user_id    : ID Telegram de l'utilisateur
          symbol     : symbole du token (ex: PEPE)
          amount_eur : montant en euros
          mint       : adresse du token (optionnel)

        Returns:
          {
            "success": True/False,
            "message": "...",
            "photon_url": "...",
            "pending_id": "..."
          }
        """
        try:
            symbol = symbol.upper()

            # Trouve le mint si pas fourni
            if not mint:
                mint = await self._find_mint_by_symbol(symbol)
                if not mint:
                    return {
                        "success": False,
                        "message": f"Token {symbol} introuvable sur Solana"
                    }

            # Récupère les données actuelles
            token_data = await self._fetch_token_data(mint)
            if not token_data:
                return {
                    "success": False,
                    "message": "Impossible de récupérer les données du token"
                }

            # Convertit EUR → SOL
            # 1 EUR ≈ 1.08 USD (approx)
            amount_usd = amount_eur * 1.08
            amount_sol = amount_usd / self.SOL_PRICE_USD

            # Génère l'URL Photon avec montant pré-rempli
            photon_url = self._build_photon_url(mint, amount_sol)

            # Stocke l'achat en attente
            pending_id = f"{user_id}_{mint}_{int(time.time())}"
            self.pending_buys[user_id] = {
                "pending_id":   pending_id,
                "symbol":       symbol,
                "mint":         mint,
                "amount_eur":   amount_eur,
                "amount_sol":   amount_sol,
                "entry_price":  token_data.get("price", 0),
                "entry_mc":     token_data.get("market_cap", 0),
                "entry_liquidity": token_data.get("liquidity", 0),
                "entry_buy_ratio": token_data.get("buy_ratio", 0),
                "entry_volume_1h": token_data.get("volume_1h", 0),
                "timestamp":    time.time(),
                "photon_url":   photon_url,
            }

            logger.info(
                f"💰 Buy prep : ${symbol} = {amount_eur}€ "
                f"({amount_sol:.4f} SOL) pour {user_id}"
            )

            return {
                "success":    True,
                "message":    "Achat préparé",
                "pending_id": pending_id,
                "photon_url": photon_url,
                "symbol":     symbol,
                "amount_eur": amount_eur,
                "amount_sol": amount_sol,
                "price":      token_data.get("price", 0),
                "market_cap": token_data.get("market_cap", 0),
                "liquidity":  token_data.get("liquidity", 0),
                "mint":       mint,
            }

        except Exception as e:
            logger.error(f"Prepare buy error : {e}")
            return {"success": False, "message": str(e)}

    def _build_photon_url(self, mint: str, amount_sol: float) -> str:
        """
        Génère l'URL Photon avec les paramètres pré-remplis.

        Format Photon : https://photon-sol.tinyastro.io/en/lp/{mint}?amount={sol}
        """
        base_url = f"https://photon-sol.tinyastro.io/en/lp/{mint}"

        # Photon accepte le paramètre amount en SOL
        url = f"{base_url}?amount={amount_sol:.6f}"

        return url

    # ════════════════════════════════════════
    # CONFIRMER UN ACHAT
    # ════════════════════════════════════════

    async def confirm_buy(self, user_id: str) -> dict:
        """
        Confirme l'achat en attente (après validation Photon).
        Enregistre dans le portfolio.
        """
        try:
            pending = self.pending_buys.get(user_id)
            if not pending:
                return {
                    "success": False,
                    "message": "Aucun achat en attente"
                }

            # Vérifie que l'achat n'est pas trop vieux (10 min max)
            elapsed = time.time() - pending["timestamp"]
            if elapsed > 600:
                del self.pending_buys[user_id]
                return {
                    "success": False,
                    "message": "Achat expiré (>10 min). Retape /buy"
                }

            # Enregistre dans le portfolio
            result = await self.portfolio_tracker.add_buy(
                symbol=pending["symbol"],
                amount_eur=pending["amount_eur"],
                mint=pending["mint"],
            )

            if not result.get("success"):
                return {
                    "success": False,
                    "message": f"Erreur portfolio : {result.get('error', 'inconnu')}"
                }

            self.total_buys_confirmed += 1

            # Nettoie
            del self.pending_buys[user_id]

            logger.info(
                f"💰 Buy confirmé : ${pending['symbol']} "
                f"= {pending['amount_eur']}€"
            )

            return {
                "success":    True,
                "message":    "Achat confirmé",
                "symbol":     pending["symbol"],
                "amount_eur": pending["amount_eur"],
                "mint":       pending["mint"],
                "entry_price": pending["entry_price"],
            }

        except Exception as e:
            logger.error(f"Confirm buy error : {e}")
            return {"success": False, "message": str(e)}

    async def cancel_buy(self, user_id: str) -> dict:
        """Annule un achat en attente"""
        if user_id in self.pending_buys:
            symbol = self.pending_buys[user_id]["symbol"]
            del self.pending_buys[user_id]
            self.total_buys_cancelled += 1
            return {
                "success": True,
                "message": f"Achat ${symbol} annulé"
            }
        return {
            "success": False,
            "message": "Aucun achat en attente"
        }

    # ════════════════════════════════════════
    # ENREGISTRER UNE VENTE
    # ════════════════════════════════════════

    async def register_sell(
        self,
        symbol: str,
        pnl_pct: float,
    ) -> dict:
        """
        Enregistre une vente manuelle.
        Calcule PnL et met à jour ML.
        """
        try:
            symbol = symbol.upper()

            # Enregistre dans portfolio
            result = await self.portfolio_tracker.add_sell(
                symbol=symbol,
                pnl_pct=pnl_pct,
            )

            if not result.get("success"):
                return {
                    "success": False,
                    "message": result.get("error", "Position introuvable")
                }

            trade = result["trade"]

            # Nourrit le ML
            self.ml_scorer.record_result(
                token_name=symbol,
                is_win=(pnl_pct > 0),
                pnl_pct=pnl_pct,
            )

            self.total_sells += 1

            logger.info(
                f"💰 Sell : ${symbol} PnL {pnl_pct:+.1f}% "
                f"({trade['pnl_eur']:+.2f}€)"
            )

            return {
                "success":    True,
                "message":    "Vente enregistrée",
                "symbol":     symbol,
                "pnl_pct":    pnl_pct,
                "pnl_eur":    trade["pnl_eur"],
                "final_eur":  trade["final_eur"],
                "amount_eur": trade["amount_eur"],
                "duration_min": trade["duration_min"],
            }

        except Exception as e:
            logger.error(f"Register sell error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # HELPERS API
    # ════════════════════════════════════════

    async def _fetch_token_data(self, mint: str) -> dict:
        """Récupère les données actuelles d'un token"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pairs = data.get("pairs") or []
            if not pairs:
                return None

            pair = pairs[0]
            base = pair.get("baseToken", {})

            txns = pair.get("txns", {}) or {}
            buys_1h = txns.get("h1", {}).get("buys", 0) if txns.get("h1") else 0
            sells_1h = txns.get("h1", {}).get("sells", 0) if txns.get("h1") else 0
            txns_1h = buys_1h + sells_1h
            buy_ratio = round(buys_1h / txns_1h * 100, 1) if txns_1h > 0 else 0

            return {
                "symbol":     base.get("symbol", "?"),
                "name":       base.get("name", "?"),
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0) or 0,
                "liquidity":  pair.get("liquidity", {}).get("usd", 0) or 0,
                "volume_1h":  pair.get("volume", {}).get("h1", 0) or 0,
                "volume_24h": pair.get("volume", {}).get("h24", 0) or 0,
                "buy_ratio":  buy_ratio,
                "change_1h":  pair.get("priceChange", {}).get("h1", 0) or 0,
                "change_24h": pair.get("priceChange", {}).get("h24", 0) or 0,
            }
        except Exception:
            return None

    async def _find_mint_by_symbol(self, symbol: str) -> str:
        """Trouve le mint Solana d'un token par son symbole"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pairs = data.get("pairs") or []

            # Match exact symbole + Solana
            for p in pairs:
                if p.get("chainId") != "solana":
                    continue
                base_sym = p.get("baseToken", {}).get("symbol", "")
                if base_sym.upper() == symbol.upper():
                    return p.get("baseToken", {}).get("address")

            # Fallback : premier Solana
            for p in pairs:
                if p.get("chainId") == "solana":
                    return p.get("baseToken", {}).get("address")

            return None

        except Exception:
            return None

    # ════════════════════════════════════════
    # STATS
    # ════════════════════════════════════════

    def get_stats(self) -> dict:
        return {
            "pending_buys":      len(self.pending_buys),
            "buys_confirmed":    self.total_buys_confirmed,
            "buys_cancelled":    self.total_buys_cancelled,
            "sells_registered":  self.total_sells,
            "sol_price_usd":     self.SOL_PRICE_USD,
        }

    def get_pending_buy(self, user_id: str) -> dict:
        """Retourne l'achat en attente d'un user"""
        return self.pending_buys.get(user_id)