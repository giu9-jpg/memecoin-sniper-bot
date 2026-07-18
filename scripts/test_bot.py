#!/usr/bin/env python3
# scripts/test_bot.py — v1.0
# Script de test complet avant lancement du bot
# Lance : python scripts/test_bot.py

import asyncio
import os
import sys

# Ajoute le dossier parent au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from utils.logger import logger


# ══════════════════════════════════════════
# COULEURS CONSOLE
# ══════════════════════════════════════════

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

OK   = f"{GREEN}✅ OK{RESET}"
FAIL = f"{RED}❌ FAIL{RESET}"
WARN = f"{YELLOW}⚠️  WARN{RESET}"


def print_header(title: str):
    print(f"\n{BOLD}{BLUE}{'═'*50}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'═'*50}{RESET}")


def print_result(name: str, ok: bool, detail: str = ""):
    status = OK if ok else FAIL
    detail_str = f"  → {detail}" if detail else ""
    print(f"  {status}  {name}{detail_str}")


# ══════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════

async def test_env():
    """Test des variables d'environnement."""
    print_header("1. Variables d'environnement")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")
    rpc_url   = os.getenv("SOLANA_RPC_URL", "")

    print_result(
        "TELEGRAM_BOT_TOKEN",
        bool(bot_token),
        f"{'***' + bot_token[-10:] if bot_token else 'MANQUANT'}",
    )
    print_result(
        "TELEGRAM_CHAT_ID",
        bool(chat_id),
        f"{chat_id or 'MANQUANT'}",
    )

    has_rpc    = bool(rpc_url)
    has_apikey = "api-key=" in rpc_url if rpc_url else False
    print_result(
        "SOLANA_RPC_URL",
        has_rpc,
        "présent" if has_rpc else "MANQUANT",
    )
    print_result(
        "SOLANA_RPC_URL contient api-key=",
        has_apikey,
        "OK" if has_apikey else "Clé Helius manquante",
    )

    return all([bool(bot_token), bool(chat_id), has_rpc])


async def test_imports():
    """Test que tous les modules s'importent correctement."""
    print_header("2. Imports des modules")

    modules = [
        ("utils.logger",               "logger"),
        ("utils.helpers",              "fmt_number"),
        ("utils.rate_limiter",         "RateLimiter"),
        ("modules.token_analyzer",     "TokenAnalyzer"),
        ("modules.alert_sender",       "AlertSender"),
        ("modules.decision_engine",    "DecisionEngine"),
        ("modules.alpha_tracker",      "AlphaTracker"),
        ("modules.whale_tracker",      "WhaleTracker"),
        ("modules.position_tracker",   "PositionTracker"),
        ("modules.market_context",     "MarketContext"),
        ("modules.performance_tracker","PerformanceTracker"),
        ("modules.early_detector",     "EarlyDetector"),
        ("modules.whale_inflow",       "WhaleInflowTracker"),
        ("modules.twitter_tracker",    "TwitterTracker"),
        ("modules.smart_signals",      "SmartSignalDetector"),
        ("modules.pump_fun_monitor",   "PumpFunMonitor"),
        ("modules.pump_portal_ws",     "PumpPortalWebSocket"),
        ("config.alpha_wallets",       "ALPHA_WALLETS"),
        ("config.alpha_accounts",      "ALPHA_ACCOUNTS"),
        ("config.whales",              "WHALE_WALLETS"),
    ]

    all_ok = True
    for module_path, attr in modules:
        try:
            mod = __import__(module_path, fromlist=[attr])
            getattr(mod, attr)
            print_result(module_path, True)
        except ImportError as e:
            print_result(module_path, False, str(e))
            all_ok = False
        except AttributeError as e:
            print_result(module_path, False, f"attr manquant: {e}")
            all_ok = False
        except Exception as e:
            print_result(module_path, False, str(e))
            all_ok = False

    return all_ok


async def test_config():
    """Test de la configuration."""
    print_header("3. Configuration")

    from config.alpha_wallets import (
        ALPHA_WALLETS,
        get_all_wallets,
        get_wallet_bonus,
        get_copy_threshold,
    )
    from config.alpha_accounts import (
        ALPHA_ACCOUNTS,
        get_all_accounts,
        get_account_tier,
        get_account_bonus,
    )

    # Alpha wallets
    all_wallets = get_all_wallets()
    print_result(
        f"Alpha wallets chargés",
        len(all_wallets) > 0,
        f"{len(all_wallets)} wallets",
    )

    # Test get_wallet_bonus avec liste
    test_wallet = all_wallets[0] if all_wallets else ""
    if test_wallet:
        bonus, msg = get_wallet_bonus([test_wallet])
        print_result(
            "get_wallet_bonus([wallet])",
            isinstance(bonus, float) and isinstance(msg, str),
            f"bonus={bonus} msg='{msg}'",
        )
        bonus2, _ = get_wallet_bonus(test_wallet)
        print_result(
            "get_wallet_bonus(wallet) str",
            isinstance(bonus2, float),
            f"bonus={bonus2}",
        )

    # Test get_copy_threshold
    threshold = get_copy_threshold(test_wallet)
    print_result(
        "get_copy_threshold",
        isinstance(threshold, float),
        f"seuil={threshold}",
    )

    # Alpha accounts Twitter
    all_accounts = get_all_accounts()
    print_result(
        "Alpha accounts Twitter",
        len(all_accounts) > 0,
        f"{len(all_accounts)} comptes",
    )

    tier = get_account_tier("Ansem")
    print_result(
        "get_account_tier('Ansem')",
        tier is not None,
        f"tier={tier}",
    )

    bonus_tw = get_account_bonus("ansem")   # Test insensible à la casse
    print_result(
        "get_account_bonus insensible casse",
        bonus_tw > 0,
        f"bonus={bonus_tw}",
    )

    return True


async def test_helpers():
    """Test des fonctions utilitaires."""
    print_header("4. Utils / Helpers")

    from utils.helpers import (
        fmt_number,
        fmt_price,
        fmt_pct,
        fmt_age,
        is_valid_solana_address,
        escape_markdown,
        calc_multiplier,
        calc_buy_ratio,
        safe_float,
        safe_int,
    )

    tests = [
        ("fmt_number(85000)",      fmt_number(85_000)       == "85K"),
        ("fmt_number(1200000)",    fmt_number(1_200_000)    == "1.2M"),
        ("fmt_number(None)",       fmt_number(None)         == "0"),
        ("fmt_price(0.00000123)",  "$" in fmt_price(0.00000123)),
        ("fmt_pct(12.5)",          fmt_pct(12.5)            == "+12.5%"),
        ("fmt_pct(-3.2)",          fmt_pct(-3.2)            == "-3.2%"),
        ("fmt_age(30)",            fmt_age(30)              == "30min"),
        ("fmt_age(90)",            "h" in fmt_age(90)),
        ("is_valid_solana addr",   is_valid_solana_address(
            "So11111111111111111111111111111111111111112"
        )),
        ("is_valid reject 0x",     not is_valid_solana_address("0xabc")),
        ("is_valid reject empty",  not is_valid_solana_address("")),
        ("escape_markdown(-)",     "\\-" in escape_markdown("a-b")),
        ("escape_markdown(.)",     "\\." in escape_markdown("1.0")),
        ("calc_multiplier",        calc_multiplier(1.0, 3.0) == 3.0),
        ("calc_multiplier 0",      calc_multiplier(0, 1.0)  == 0.0),
        ("calc_buy_ratio",         calc_buy_ratio(30, 10)   == 3.0),
        ("calc_buy_ratio 0 sells", calc_buy_ratio(30, 0)    == 30.0),
        ("safe_float str",         safe_float("12.5")       == 12.5),
        ("safe_float None",        safe_float(None)         == 0.0),
        ("safe_int str",           safe_int("42")           == 42),
    ]

    all_ok = True
    for name, result in tests:
        print_result(name, result)
        if not result:
            all_ok = False

    return all_ok


async def test_market_context():
    """Test du MarketContext."""
    print_header("5. Market Context")

    from modules.market_context import MarketContext

    ctx = MarketContext()
    try:
        await ctx.fetch_market_data()
        sig = ctx.get_market_signal()

        print_result(
            "fetch_market_data()",
            True,
            f"BTC {sig['btc_change_24h']:+.1f}% | "
            f"SOL {sig['sol_change_24h']:+.1f}%",
        )
        print_result(
            "get_market_signal() regime",
            sig["regime"] in ("BULLISH", "NEUTRAL", "BEARISH"),
            sig["regime"],
        )
        print_result(
            "Fear & Greed Index",
            0 <= sig["fear_greed"] <= 100,
            str(sig["fear_greed"]),
        )
        print_result(
            "should_alert présent",
            "should_alert" in sig,
            str(sig["should_alert"]),
        )
        return True
    except Exception as e:
        print_result("Market context", False, str(e))
        return False
    finally:
        await ctx.close()


async def test_dexscreener():
    """Test de l'API DexScreener."""
    print_header("6. DexScreener API")

    from modules.token_analyzer import TokenAnalyzer

    # Token connu : BONK
    TEST_TOKEN = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

    analyzer = TokenAnalyzer()
    try:
        data = await analyzer._get_dexscreener_data(TEST_TOKEN)
        ok   = bool(data and data.get("symbol"))
        print_result(
            "DexScreener API",
            ok,
            f"symbol={data.get('symbol')} "
            f"mc=${data.get('market_cap', 0):,.0f}"
            if ok else "Pas de données",
        )
        return ok
    except Exception as e:
        print_result("DexScreener API", False, str(e))
        return False
    finally:
        await analyzer.close()


async def test_telegram():
    """Test de l'envoi Telegram."""
    print_header("7. Telegram")

    from modules.alert_sender import AlertSender

    sender = AlertSender()
    try:
        # Teste juste la connexion, pas l'envoi réel
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            print_result("Credentials", False, "manquants")
            return False

        print_result("Credentials", True, "présents")

        # Test getMe pour valider le token
        import aiohttp
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                ok     = result.get("ok", False)
                username = result.get(
                    "result", {}
                ).get("username", "?")
                print_result(
                    "Token Telegram valide",
                    ok,
                    f"@{username}" if ok else result.get("description"),
                )
                return ok

    except Exception as e:
        print_result("Telegram", False, str(e))
        return False
    finally:
        await sender.close()


async def test_helius():
    """Test de l'API Helius."""
    print_header("8. Helius API")

    from modules.alpha_tracker import AlphaTracker
    from config.alpha_wallets  import get_all_wallets

    tracker = AlphaTracker()

    if not tracker.api_key:
        print_result(
            "Helius API Key",
            False,
            "SOLANA_RPC_URL ne contient pas api-key=",
        )
        return False

    print_result("Helius API Key", True, f"***{tracker.api_key[-6:]}")

    # Test avec le premier wallet
    wallets = get_all_wallets()
    if not wallets:
        print_result("Alpha wallets", False, "liste vide")
        return False

    try:
        txs = await tracker._check_wallet_transactions(wallets[0])
        print_result(
            "Helius transactions",
            True,
            f"wallet {wallets[0][:8]}... accessible",
        )
        return True
    except Exception as e:
        print_result("Helius transactions", False, str(e))
        return False
    finally:
        await tracker.close()


async def test_performance_tracker():
    """Test du PerformanceTracker."""
    print_header("9. Performance Tracker")

    from modules.performance_tracker import PerformanceTracker

    tracker = PerformanceTracker()

    # Test get_stats vide
    stats = tracker.get_stats()
    print_result(
        "get_stats() retourne dict valide",
        isinstance(stats, dict) and "total_alerts" in stats,
        f"{stats['total_alerts']} alertes",
    )

    # Test get_summary_message
    msg = tracker.get_summary_message()
    print_result(
        "get_summary_message() non vide",
        isinstance(msg, str) and len(msg) > 10,
        f"{len(msg)} chars",
    )

    # Test flush
    try:
        tracker.flush()
        print_result("flush()", True)
    except Exception as e:
        print_result("flush()", False, str(e))

    return True


async def test_nitter():
    """Test de la disponibilité de Nitter."""
    print_header("10. Nitter / Twitter Tracker")

    from modules.twitter_tracker import TwitterTracker

    tracker = TwitterTracker()
    try:
        instance = await tracker.find_working_instance()
        ok       = instance is not None
        print_result(
            "Instance Nitter disponible",
            ok,
            instance or "Aucune disponible",
        )
        return ok
    except Exception as e:
        print_result("Nitter", False, str(e))
        return False
    finally:
        await tracker.close()


# ══════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════

async def main():
    print(f"\n{BOLD}{'='*50}{RESET}")
    print(f"{BOLD}  🤖 MemeSniper v11.3 — Test de démarrage{RESET}")
    print(f"{BOLD}{'='*50}{RESET}")

    results = {}

    # Tests dans l'ordre
    test_funcs = [
        ("Environnement",        test_env),
        ("Imports",              test_imports),
        ("Configuration",        test_config),
        ("Helpers",              test_helpers),
        ("Market Context",       test_market_context),
        ("DexScreener",          test_dexscreener),
        ("Telegram",             test_telegram),
        ("Helius",               test_helius),
        ("Performance Tracker",  test_performance_tracker),
        ("Nitter",               test_nitter),
    ]

    for name, func in test_funcs:
        try:
            results[name] = await func()
        except Exception as e:
            print(f"\n  {RED}💥 Erreur inattendue dans {name}: {e}{RESET}")
            results[name] = False

    # Résumé final
    print_header("RÉSUMÉ FINAL")

    passed  = sum(1 for v in results.values() if v)
    failed  = sum(1 for v in results.values() if not v)
    total   = len(results)

    for name, ok in results.items():
        print_result(name, ok)

    print(f"\n  {BOLD}Score : {passed}/{total}{RESET}")

    if failed == 0:
        print(f"\n  {GREEN}{BOLD}🚀 Tout est OK — Le bot peut démarrer !{RESET}")
        print(f"  {GREEN}Lance : python main.py{RESET}\n")
        return 0
    else:
        critical = not results.get("Environnement") or \
                   not results.get("Imports")        or \
                   not results.get("Telegram")

        if critical:
            print(
                f"\n  {RED}{BOLD}❌ Erreurs critiques détectées.{RESET}"
            )
            print(
                f"  {RED}Corrige les erreurs avant de lancer.{RESET}\n"
            )
            return 1
        else:
            print(
                f"\n  {YELLOW}{BOLD}⚠️  Avertissements ({failed} tests).{RESET}"
            )
            print(
                f"  {YELLOW}Le bot peut démarrer mais certaines "
                f"fonctionnalités seront limitées.{RESET}\n"
            )
            return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)