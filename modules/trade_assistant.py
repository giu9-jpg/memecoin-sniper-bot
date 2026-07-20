# modules/trade_assistant.py — v1.1
# ═══════════════════════════════════════════════
# v1.1 CHANGEMENTS :
# + register_pending()           — appelé par alert_sender à chaque alerte
# + confirm_buy_from_callback()  — appelé par callback_handler (bouton ✅)
#
# HÉRITÉ v1.0 :
# + prepare_buy()       — commande /buy SYMBOL AMOUNT
# + confirm_buy()       — commande /confirm
# + cancel_buy()        — commande /cancel
# + register_sell()     — commande /sold SYMBOL PCT
# + get_pending_buy()   — commande /confirm
# + get_stats()         — /status, health check
# + Prix SOL temps réel (CoinGecko, maj 5min)
# + URL Photon pré-remplie avec montant SOL
# ═══════════════════════════════════════════════

import asyncio
import aiohttp
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("trade_assistant")


class TradeAssistant:

    # Prix SOL en USD (mis à jour toutes les 5 min)
    SOL_PRICE_USD = 200

    def __init__(self, portfolio_tracker, alert_sender, ml_scorer):
        self.portfolio_tracker = portfolio_tracker
        self.alert_sender      = alert_sender
        self.ml_scorer         = ml_scorer

        self.session = None
        self.running = False

        # Achats en attente de confirmation
        # Deux types de clés :
        #   user_id → achat via /buy (commande manuelle)
        #   mint    → achat via bouton inline (depuis alerte)
        self.pending_buys = {}

        # Stats
        self.total_buys_confirmed = 0
        self.total_buys_cancelled = 0
        self.total_sells          = 0

    # ════════════════════════════════════════
    # START / STOP
    # ════════════════════════════════════════

    async def start(self):
        """Démarre le module."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True

        await self._update_sol_price()

        logger.info(
            f"💰 TradeAssistant v1.1 démarré "
            f"(SOL: ${self.SOL_PRICE_USD:.0f})"
        )

        asyncio.create_task(self._price_update_loop())

    async def stop(self):
        """Arrêt propre."""
        self.running = False
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("💰 TradeAssistant arrêté")

    # ════════════════════════════════════════
    # PRIX SOL
    # ════════════════════════════════════════

    async def _price_update_loop(self):
        """Met à jour le prix SOL toutes les 5 minutes."""
        while self.running:
            await asyncio.sleep(300)
            try:
                await self._update_sol_price()
            except Exception as e:
                logger.debug(f"SOL price update error : {e}")

    async def _update_sol_price(self):
        """Récupère le prix actuel de SOL via CoinGecko."""
        try:
            url = (
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=solana&vs_currencies=usd"
            )
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data.get("solana", {}).get("usd", 200)
                    self.SOL_PRICE_USD = price
                    logger.debug(f"SOL price updated : ${self.SOL_PRICE_USD:.2f}")
        except Exception:
            pass

    # ════════════════════════════════════════
    # REGISTER PENDING — appelé par alert_sender
    # ════════════════════════════════════════

    def register_pending(
        self,
        mint:       str,
        symbol:     str,
        score:      float,
        tier:       str,
        amount:     float,
        market_cap: float,
        price:      float,
        alert_data: dict = None,
    ):
        """
        Enregistre un token en pending depuis une alerte automatique.

        Appelé par alert_sender.send_alert() à chaque alerte envoyée.
        Stocké sous la clé MINT (pas user_id) pour que
        callback_handler puisse retrouver le trade via le bouton inline.

        Différence avec prepare_buy() :
          register_pending → depuis alerte automatique (bouton inline)
          prepare_buy      → depuis commande /buy manuelle
        """
        amount_sol = (amount * 1.08) / max(self.SOL_PRICE_USD, 1)

        self.pending_buys[mint] = {
            "pending_id":      f"alert_{mint}_{int(time.time())}",
            "symbol":          symbol,
            "mint":            mint,
            "amount_eur":      amount,
            "amount_sol":      amount_sol,
            "entry_price":     price,
            "entry_mc":        market_cap,
            "entry_liquidity": 0,
            "entry_buy_ratio": 0,
            "entry_volume_1h": 0,
            "timestamp":       time.time(),
            "photon_url":      self._build_photon_url(mint, amount_sol),
            "score":           score,
            "tier":            tier,
            "alert_data":      alert_data or {},
            "source":          "alert",
        }
        logger.info(
            f"💰 Pending alert: ${symbol} {amount}€ "
            f"({mint[:8]}...) score={score}"
        )

    # ════════════════════════════════════════
    # CONFIRM BUY FROM CALLBACK — bouton ✅
    # ════════════════════════════════════════

    async def confirm_buy_from_callback(
        self,
        mint:   str,
        amount: float,
    ) -> dict:
        """
        Confirme un achat depuis le bouton inline ✅ J'ai acheté.

        Appelé par callback_handler._handle_bought().
        Cherche dans pending_buys par mint.

        Différence avec confirm_buy(user_id) :
          confirm_buy_from_callback → bouton inline (mint comme clé)
          confirm_buy               → commande /confirm (user_id comme clé)
        """
        try:
            # Cherche par mint exact
            pending = self.pending_buys.get(mint)

            # Fallback : cherche dans les valeurs
            if not pending:
                for key, p in list(self.pending_buys.items()):
                    if p.get("mint") == mint:
                        pending = p
                        break

            if not pending:
                return {
                    "success": False,
                    "message": (
                        f"Alerte introuvable pour ce token.\n"
                        f"Elle a peut-être expiré ou déjà confirmée."
                    )
                }

            # Mise à jour du montant réel investi
            pending["amount_eur"] = amount
            pending["amount_sol"] = (amount * 1.08) / max(self.SOL_PRICE_USD, 1)

            # Enregistre dans portfolio_tracker
            result = await self.portfolio_tracker.add_buy(
                symbol=pending["symbol"],
                amount_eur=amount,
                mint=mint,
            )

            if not result.get("success"):
                return {
                    "success": False,
                    "message": (
                        f"Erreur portfolio : "
                        f"{result.get('error', 'inconnu')}"
                    )
                }

            self.total_buys_confirmed += 1

            # Nettoyer le pending
            self.pending_buys.pop(mint, None)

            logger.info(
                f"💰 Buy callback confirmé : "
                f"${pending['symbol']} = {amount}€ "
                f"(score: {pending.get('score', '?')}, "
                f"tier: {pending.get('tier', '?')})"
            )

            return {
                "success":     True,
                "message":     "Achat confirmé",
                "symbol":      pending["symbol"],
                "amount_eur":  amount,
                "mint":        mint,
                "entry_price": pending.get("entry_price", 0),
                "score":       pending.get("score", 0),
                "tier":        pending.get("tier", "NORMAL"),
                "market_cap":  pending.get("entry_mc", 0),
            }

        except Exception as e:
            logger.error(f"confirm_buy_from_callback error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # PREPARE BUY — commande /buy
    # ════════════════════════════════════════

    async def prepare_buy(
        self,
        user_id:    str,
        symbol:     str,
        amount_eur: float,
        mint:       str = None,
    ) -> dict:
        """
        Prépare un achat depuis la commande /buy SYMBOL AMOUNT.

        Stocke sous la clé user_id dans pending_buys.
        L'utilisateur doit ensuite taper /confirm.
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

            # Récupère les données actuelles du token
            token_data = await self._fetch_token_data(mint)
            if not token_data:
                return {
                    "success": False,
                    "message": "Impossible de récupérer les données du token"
                }

            # Convertit EUR → SOL (1 EUR ≈ 1.08 USD)
            amount_usd = amount_eur * 1.08
            amount_sol = amount_usd / max(self.SOL_PRICE_USD, 1)

            photon_url = self._build_photon_url(mint, amount_sol)

            # Stocke sous user_id (clé commande /buy)
            pending_id = f"{user_id}_{mint}_{int(time.time())}"
            self.pending_buys[user_id] = {
                "pending_id":      pending_id,
                "symbol":          symbol,
                "mint":            mint,
                "amount_eur":      amount_eur,
                "amount_sol":      amount_sol,
                "entry_price":     token_data.get("price", 0),
                "entry_mc":        token_data.get("market_cap", 0),
                "entry_liquidity": token_data.get("liquidity", 0),
                "entry_buy_ratio": token_data.get("buy_ratio", 0),
                "entry_volume_1h": token_data.get("volume_1h", 0),
                "timestamp":       time.time(),
                "photon_url":      photon_url,
                "score":           0,
                "tier":            "MANUAL",
                "source":          "command",
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

    # ════════════════════════════════════════
    # CONFIRM BUY — commande /confirm
    # ════════════════════════════════════════

    async def confirm_buy(self, user_id: str) -> dict:
        """
        Confirme l'achat en attente depuis /confirm.
        Cherche dans pending_buys par user_id.
        """
        try:
            pending = self.pending_buys.get(user_id)
            if not pending:
                return {
                    "success": False,
                    "message": "Aucun achat en attente"
                }

            # Vérifie expiration (10 min max)
            elapsed = time.time() - pending["timestamp"]
            if elapsed > 600:
                del self.pending_buys[user_id]
                return {
                    "success": False,
                    "message": "Achat expiré (>10 min). Retape /buy"
                }

            # Enregistre dans portfolio
            result = await self.portfolio_tracker.add_buy(
                symbol=pending["symbol"],
                amount_eur=pending["amount_eur"],
                mint=pending["mint"],
            )

            if not result.get("success"):
                return {
                    "success": False,
                    "message": (
                        f"Erreur portfolio : "
                        f"{result.get('error', 'inconnu')}"
                    )
                }

            self.total_buys_confirmed += 1
            del self.pending_buys[user_id]

            logger.info(
                f"💰 Buy confirmé : ${pending['symbol']} "
                f"= {pending['amount_eur']}€"
            )

            return {
                "success":     True,
                "message":     "Achat confirmé",
                "symbol":      pending["symbol"],
                "amount_eur":  pending["amount_eur"],
                "mint":        pending["mint"],
                "entry_price": pending["entry_price"],
            }

        except Exception as e:
            logger.error(f"Confirm buy error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # CANCEL BUY — commande /cancel
    # ════════════════════════════════════════

    async def cancel_buy(self, user_id: str) -> dict:
        """Annule un achat en attente (commande /cancel)."""
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
    # REGISTER SELL — commande /sold
    # ════════════════════════════════════════

    async def register_sell(
        self,
        symbol:  str,
        pnl_pct: float,
    ) -> dict:
        """
        Enregistre une vente manuelle via /sold SYMBOL PCT.
        Met à jour portfolio + ML automatiquement.
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

            # Nourrit le ML automatiquement
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
                "success":      True,
                "message":      "Vente enregistrée",
                "symbol":       symbol,
                "pnl_pct":      pnl_pct,
                "pnl_eur":      trade["pnl_eur"],
                "final_eur":    trade["final_eur"],
                "amount_eur":   trade["amount_eur"],
                "duration_min": trade["duration_min"],
            }

        except Exception as e:
            logger.error(f"Register sell error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # HELPERS API
    # ════════════════════════════════════════

    def _build_photon_url(self, mint: str, amount_sol: float) -> str:
        """Génère l'URL Photon avec montant SOL pré-rempli."""
        return (
            f"https://photon-sol.tinyastro.io/en/lp/{mint}"
            f"?amount={amount_sol:.6f}"
        )

    async def _fetch_token_data(self, mint: str) -> dict | None:
        """Récupère les données actuelles d'un token via DexScreener."""
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

            txns     = pair.get("txns", {}) or {}
            h1       = txns.get("h1", {}) or {}
            buys_1h  = h1.get("buys", 0)
            sells_1h = h1.get("sells", 0)
            txns_1h  = buys_1h + sells_1h
            buy_ratio = (
                round(buys_1h / txns_1h * 100, 1)
                if txns_1h > 0 else 0
            )

            return {
                "symbol":     base.get("symbol", "?"),
                "name":       base.get("name", "?"),
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": (
                    pair.get("marketCap", 0)
                    or pair.get("fdv", 0)
                    or 0
                ),
                "liquidity":  (
                    pair.get("liquidity", {}).get("usd", 0) or 0
                ),
                "volume_1h":  (
                    pair.get("volume", {}).get("h1", 0) or 0
                ),
                "volume_24h": (
                    pair.get("volume", {}).get("h24", 0) or 0
                ),
                "buy_ratio":  buy_ratio,
                "change_1h":  (
                    pair.get("priceChange", {}).get("h1", 0) or 0
                ),
                "change_24h": (
                    pair.get("priceChange", {}).get("h24", 0) or 0
                ),
            }
        except Exception:
            return None

    async def _find_mint_by_symbol(self, symbol: str) -> str | None:
        """Trouve l'adresse mint d'un token par son symbole (DexScreener)."""
        try:
            url = (
                f"https://api.dexscreener.com/latest/dex/search"
                f"?q={symbol}"
            )
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

            # Fallback : premier token Solana trouvé
            for p in pairs:
                if p.get("chainId") == "solana":
                    return p.get("baseToken", {}).get("address")

            return None

        except Exception:
            return None

    # ════════════════════════════════════════
    # STATS & GETTERS
    # ════════════════════════════════════════

    def get_stats(self) -> dict:
        """Retourne les stats pour /status et health check."""
        return {
            "pending_buys":     len(self.pending_buys),
            "buys_confirmed":   self.total_buys_confirmed,
            "buys_cancelled":   self.total_buys_cancelled,
            "sells_registered": self.total_sells,
            "sol_price_usd":    self.SOL_PRICE_USD,
        }

    def get_pending_buy(self, user_id: str) -> dict | None:
        """Retourne l'achat en attente d'un user (pour /confirm)."""
        return self.pending_buys.get(user_id)