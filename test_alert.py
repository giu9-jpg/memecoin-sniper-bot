# test_alert.py
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from modules.alert_sender import AlertSender

    sender = AlertSender()

    fake_token = {
        "address":            "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        "name":               "TestCoin",
        "symbol":             "TEST",
        "price_usd":          0.000042,
        "market_cap":         85_000,
        "liquidity":          45_000,
        "volume_24h":         120_000,
        "volume_1h":          25_000,
        "volume_5m":          8_000,
        "price_change_5m":    12.5,
        "price_change_1h":    35.2,
        "price_change_6h":    8.1,
        "price_change_24h":   67.3,
        "holders":            342,
        "age_minutes":        23,
        "mint_renounced":     True,
        "lp_locked":          True,
        "freeze_auth":        False,
        "top_10_holders_pct": 28,
        "is_honeypot":        False,
        "vol_acceleration":   2.8,
        "ratio_buy_5m":       3.2,
        "ratio_buy_1h":       2.1,
        "momentum_signal":    "EARLY_PUMP",
        "signal_type":        "GEM_FORTE",
        "has_socials":        True,
        "score":              8.5,
        "score_reasons": [
            "🔥 Très early : 23 min",
            "🚀 EARLY PUMP détecté",
            "🟢 Pression acheteuse FORTE",
        ],
        "whale_count":  1,
        "smart_signals": [
            {
                "type":     "STEALTH_ACCUMULATION",
                "emoji":    "🤫",
                "message":  "ACCUMULATION FURTIVE: vol x2.8",
                "priority": "CRITICAL",
                "bonus":    3.5,
            },
            {
                "type":     "WHALE_ENTRY",
                "emoji":    "🐋",
                "message":  "BALEINE: achats de $3,200",
                "priority": "CRITICAL",
                "bonus":    3.0,
            },
        ],
        "smart_count":  2,
        "has_critical": True,
        "smart_bonus":  3.5,
    }

    print("📤 Envoi du test Telegram...")
    result = await sender.send_alert(fake_token)

    if result:
        print("✅ Alerte envoyée ! Vérifie ton Telegram")
    else:
        print("❌ Échec. Vérifie les credentials dans .env")

    await sender.close()

if __name__ == "__main__":
    asyncio.run(main())