# config/whales.py — v2.0 FIXED
"""
Whales - v2.0
Wallets de baleines Solana à surveiller
"""

WHALE_WALLETS = [
    {
        "address":       "7xuqfpLnqpFkkBCNfKzGFBrG3k3T8YBCZ8aN2KoQHmV",
        "label":         "Whale Alpha 1",
        "tier":          1,
        "min_trade_usd": 5_000,
        "active":        True,
    },
    {
        "address":       "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        "label":         "Whale Alpha 2",
        "tier":          1,
        "min_trade_usd": 5_000,
        "active":        True,
    },
    {
        "address":       "5tzFkiKscXHK5ZXCGbGuFhKEKriECpDSZrnvVMQmtXrg",
        "label":         "Whale Beta 1",
        "tier":          2,
        "min_trade_usd": 2_000,
        "active":        True,
    },
    {
        "address":       "3uW4MAfRaKMCnXo4RoW9R3p4CsSGGPjHAfyWJMNcqTtb",
        "label":         "Whale Beta 2",
        "tier":          2,
        "min_trade_usd": 2_000,
        "active":        True,
    },
    {
        "address":       "BxmAHFCbHCbdMBHbDsKGnqmFhGm3JMq3eFg7Lhbz4mS",
        "label":         "Whale Gamma 1",
        "tier":          3,
        "min_trade_usd": 1_000,
        "active":        True,
    },
]

_ADDRESS_INDEX: dict[str, dict] = {
    w["address"]: w for w in WHALE_WALLETS
}


def get_active_wallets() -> list:
    """Retourne les adresses des baleines actives."""
    return [
        w["address"] for w in WHALE_WALLETS
        if w.get("active", True)
    ]


def get_whale_by_address(address: str) -> dict | None:
    """Retourne les infos d'une baleine par adresse."""
    return _ADDRESS_INDEX.get(address)


def get_whales_by_tier(tier: int) -> list:
    """Retourne les baleines d'un tier donné."""
    return [
        w for w in WHALE_WALLETS
        if w.get("tier") == tier and w.get("active", True)
    ]


def get_min_trade_usd(address: str) -> float:
    """Retourne le montant minimum en USD pour une baleine."""
    whale = get_whale_by_address(address)
    if whale is None:
        return 1_000.0
    return float(whale.get("min_trade_usd", 1_000))


def add_whale(
    address: str,
    label: str = "Unknown Whale",
    tier: int = 3,
    min_trade_usd: float = 1_000,
) -> bool:
    """Ajoute dynamiquement une baleine. Retourne True si ajoutée."""
    if address in _ADDRESS_INDEX:
        return False
    whale = {
        "address":       address,
        "label":         label,
        "tier":          tier,
        "min_trade_usd": min_trade_usd,
        "active":        True,
    }
    WHALE_WALLETS.append(whale)
    _ADDRESS_INDEX[address] = whale
    return True