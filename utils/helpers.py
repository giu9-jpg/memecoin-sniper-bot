# utils/helpers.py — v1.0
# Fonctions utilitaires partagées entre tous les modules

import re
import time
from typing import Any


# ══════════════════════════════════════════
# FORMATAGE NOMBRES
# ══════════════════════════════════════════

def fmt_number(num: Any, decimals: int = 1) -> str:
    """
    Formate un nombre pour l'affichage.
    85000 → "85K" | 1200000 → "1.2M" | None → "0"
    """
    try:
        n = float(num or 0)
    except (TypeError, ValueError):
        return "0"

    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.{decimals}f}B"
    elif n >= 1_000_000:
        return f"{n / 1_000_000:.{decimals}f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def fmt_price(price: Any, decimals: int = 8) -> str:
    """Formate un prix de token. 0.00000123 → "$0.00000123" """
    try:
        p = float(price or 0)
    except (TypeError, ValueError):
        return "$0"

    if p == 0:
        return "$0"
    elif p >= 1:
        return f"${p:.4f}"
    elif p >= 0.0001:
        return f"${p:.6f}"
    else:
        return f"${p:.{decimals}f}"


def fmt_pct(value: Any, sign: bool = True) -> str:
    """Formate un pourcentage. 12.5 → "+12.5%" | -3.2 → "-3.2%" """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0%"

    if sign and v > 0:
        return f"+{v:.1f}%"
    return f"{v:.1f}%"


def fmt_duration(seconds: float) -> str:
    """Formate une durée en secondes. 65 → "1min" | 3700 → "1h 1min" """
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "0s"

    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}min"
    elif s < 86400:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}min" if m else f"{h}h"
    else:
        d = s // 86400
        h = (s % 86400) // 3600
        return f"{d}j {h}h" if h else f"{d}j"


def fmt_age(age_minutes: float) -> str:
    """Formate l'âge d'un token. 5 → "5min" | 90 → "1.5h" """
    try:
        m = float(age_minutes or 0)
    except (TypeError, ValueError):
        return "?"

    if m < 60:
        return f"{m:.0f}min"
    elif m < 1440:
        return f"{m / 60:.1f}h"
    else:
        return f"{m / 1440:.1f}j"


# ══════════════════════════════════════════
# VALIDATION ADRESSES SOLANA
# ══════════════════════════════════════════

BASE58_CHARS = frozenset(
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    "abcdefghijkmnopqrstuvwxyz"
)


def is_valid_solana_address(address: Any) -> bool:
    """
    Vérifie qu'une adresse est une adresse Solana valide.
    - Non vide, ne commence pas par 0x
    - Longueur 32-44 chars base58
    """
    if not address or not isinstance(address, str):
        return False
    if address.startswith("0x"):
        return False
    if not (32 <= len(address) <= 44):
        return False
    return all(c in BASE58_CHARS for c in address)


def is_stablecoin_or_native(address: str) -> bool:
    """Retourne True si l'adresse est un stablecoin ou SOL natif."""
    KNOWN_STABLE = {
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
        "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E",
    }
    return address in KNOWN_STABLE


# ══════════════════════════════════════════
# MARKDOWN TELEGRAM
# ══════════════════════════════════════════

_MD_SPECIAL = frozenset(r"\_*[]()~`>#+-=|{}.!")


def escape_markdown(text: Any) -> str:
    """
    Échappe les caractères spéciaux pour Telegram MarkdownV2.
    escape_markdown("PEPE-2.0") → "PEPE\\-2\\.0"
    """
    if text is None:
        return ""
    result = ""
    for char in str(text):
        if char in _MD_SPECIAL:
            result += "\\" + char
        else:
            result += char
    return result


def strip_markdown(text: str) -> str:
    """Supprime tous les caractères Markdown d'un texte (fallback)."""
    if not text:
        return ""
    text = re.sub(r'\\([_*\[\]()~`>#\+\-=|{}.!])', r'\1', text)
    text = re.sub(r'[*_`]', '', text)
    return text.strip()


# ══════════════════════════════════════════
# GESTION DU TEMPS
# ══════════════════════════════════════════

def now_ts() -> float:
    """Retourne le timestamp actuel."""
    return time.time()


def is_recent(timestamp: float, max_age_seconds: float) -> bool:
    """Vérifie si un timestamp est récent."""
    return (time.time() - timestamp) <= max_age_seconds


def age_from_ts(timestamp: float) -> float:
    """Retourne l'âge en secondes depuis un timestamp."""
    return time.time() - timestamp


# ══════════════════════════════════════════
# SAFE GETTERS
# ══════════════════════════════════════════

def safe_float(value: Any, default: float = 0.0) -> float:
    """Convertit une valeur en float sans planter."""
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Convertit une valeur en int sans planter."""
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """Convertit une valeur en str sans planter."""
    if value is None:
        return default
    return str(value)


def safe_dict(value: Any) -> dict:
    """Retourne un dict vide si value n'est pas un dict."""
    if isinstance(value, dict):
        return value
    return {}


def safe_list(value: Any) -> list:
    """Retourne une liste vide si value n'est pas une liste."""
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


# ══════════════════════════════════════════
# CALCULS TRADING
# ══════════════════════════════════════════

def calc_multiplier(price_entry: float, price_current: float) -> float:
    """Calcule le multiplicateur entre deux prix."""
    if not price_entry or price_entry <= 0:
        return 0.0
    try:
        return round(float(price_current) / float(price_entry), 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def calc_pnl_eur(amount_eur: float, multiplier: float) -> float:
    """Calcule le P&L en EUR."""
    try:
        return round(
            float(amount_eur) * float(multiplier) - float(amount_eur), 2
        )
    except (TypeError, ValueError):
        return 0.0


def calc_buy_ratio(buys: Any, sells: Any) -> float:
    """Calcule le ratio buys/sells. Protège contre sells=0."""
    try:
        b = float(buys  or 0)
        s = float(sells or 0)
        return round(b / max(s, 1), 2)
    except (TypeError, ValueError):
        return 1.0


def calc_vol_acceleration(
    vol_5m: float, vol_1h: float, vol_24h: float
) -> float:
    """Calcule l'accélération du volume."""
    try:
        v5m  = float(vol_5m  or 0)
        v1h  = float(vol_1h  or 0)
        v24h = float(vol_24h or 0)

        avg_hourly = v24h / 24 if v24h > 0 else 0
        if avg_hourly <= 0:
            return 1.0

        rate_5m = (v5m * 12) / avg_hourly if v5m > 0 else 0
        rate_1h = v1h / avg_hourly if v1h > 0 else 0
        accel   = (rate_5m * 0.6) + (rate_1h * 0.4)
        return round(accel, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0


# ══════════════════════════════════════════
# NETTOYAGE DICTIONNAIRES
# ══════════════════════════════════════════

def trim_dict_by_timestamp(
    d: dict, max_size: int, keep: int, ts_key: str = None
) -> dict:
    """Purge un dictionnaire en gardant les entrées les plus récentes."""
    if len(d) <= max_size:
        return d

    if ts_key is None:
        sorted_items = sorted(
            d.items(), key=lambda x: x[1], reverse=True
        )
    else:
        sorted_items = sorted(
            d.items(),
            key=lambda x: (
                x[1].get(ts_key, 0) if isinstance(x[1], dict) else 0
            ),
            reverse=True,
        )
    return dict(sorted_items[:keep])


def cleanup_old_entries(
    d: dict, max_age_seconds: float, ts_key: str = None
) -> dict:
    """Supprime les entrées plus vieilles que max_age_seconds."""
    now    = time.time()
    cutoff = now - max_age_seconds

    if ts_key is None:
        return {
            k: v for k, v in d.items()
            if isinstance(v, (int, float)) and v > cutoff
        }
    else:
        return {
            k: v for k, v in d.items()
            if isinstance(v, dict) and v.get(ts_key, 0) > cutoff
        }