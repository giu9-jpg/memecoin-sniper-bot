# modules/admin_security.py — v1.0 CORRIGÉ
# FIX AUDIT : aucun bug critique trouvé, code identique
# Nettoyage mineur : imports inutilisés retirés

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from collections import defaultdict, deque
from utils.logger import get_logger

logger = get_logger("admin_security")


class AdminSecurity:

    DATA_FILE = "data/admin_security.json"

    SENSITIVE_COMMANDS = {
        "/reset",
        "/reset_ml",
        "/reset_portfolio",
        "/reset_bulls",
        "/clear_alerts",
        "/wipe_data",
    }

    RATE_LIMIT_WINDOW    = 60
    RATE_LIMIT_MAX_CMD   = 20
    RATE_LIMIT_MAX_HEAVY = 5

    HEAVY_COMMANDS = {
        "/backtest",
        "/backtest_strategy",
        "/compare_strategies",
        "/bullrun",
        "/candidates",
    }

    BLACKLIST_THRESHOLD  = 50
    BLACKLIST_DURATION   = 3600
    CONFIRMATION_TIMEOUT = 30

    def __init__(self):
        self.main_admin = os.getenv("TELEGRAM_CHAT_ID", "")

        extra = os.getenv("TELEGRAM_ADMINS_EXTRA", "")
        self.extra_admins = [
            a.strip() for a in extra.split(",") if a.strip()
        ]

        self.authorized_admins = set()
        if self.main_admin:
            self.authorized_admins.add(str(self.main_admin))
        for admin in self.extra_admins:
            self.authorized_admins.add(str(admin))

        self.command_history       = defaultdict(lambda: deque(maxlen=100))
        self.pending_confirmations = {}
        self.blacklist             = {}
        self.violations            = defaultdict(int)
        self.command_log           = []
        self.admin_stats           = {}

        self._load_data()

        logger.info(
            f"🔐 AdminSecurity initialisé "
            f"({len(self.authorized_admins)} admin(s))"
        )

    async def start(self):
        logger.info("🔐 AdminSecurity actif")
        asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        self._save_data()
        logger.info("🔐 AdminSecurity arrêté")

    async def _cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(300)
                self._cleanup_expired()
                self._save_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Security cleanup error : {e}")

    def _cleanup_expired(self):
        now = time.time()

        expired = [
            uid for uid, exp in self.blacklist.items()
            if exp < now
        ]
        for uid in expired:
            del self.blacklist[uid]
            self.violations[uid] = 0
            logger.info(f"🔐 Blacklist expirée pour {uid}")

        expired_conf = [
            uid for uid, data in self.pending_confirmations.items()
            if now - data["timestamp"] > self.CONFIRMATION_TIMEOUT
        ]
        for uid in expired_conf:
            del self.pending_confirmations[uid]

        if len(self.command_log) > 500:
            self.command_log = self.command_log[-500:]

    def is_authorized(self, user_id: str) -> bool:
        return str(user_id) in self.authorized_admins

    def is_blacklisted(self, user_id: str) -> bool:
        user_id = str(user_id)
        if user_id in self.blacklist:
            if self.blacklist[user_id] > time.time():
                return True
            else:
                del self.blacklist[user_id]
                return False
        return False

    def get_blacklist_remaining(self, user_id: str) -> int:
        user_id = str(user_id)
        if user_id in self.blacklist:
            remaining = self.blacklist[user_id] - time.time()
            return max(0, int(remaining))
        return 0

    def check_rate_limit(
        self, user_id: str, command: str
    ) -> dict:
        user_id = str(user_id)
        now     = time.time()

        if self.is_blacklisted(user_id):
            remaining = self.get_blacklist_remaining(user_id)
            return {
                "allowed":   False,
                "reason":    f"Blacklisté pour {remaining}s",
                "remaining": 0,
            }

        history = self.command_history[user_id]
        cutoff  = now - self.RATE_LIMIT_WINDOW
        recent  = [ts for ts in history if ts > cutoff]

        heavy_count = sum(
            1 for entry in self.command_log[-50:]
            if entry.get("user_id") == user_id
            and entry.get("command", "") in self.HEAVY_COMMANDS
            and entry.get("timestamp", 0) > cutoff
        )

        if len(recent) >= self.RATE_LIMIT_MAX_CMD:
            self._add_violation(user_id, "rate_limit_general")
            return {
                "allowed":   False,
                "reason":    f"Trop de commandes ({len(recent)}/{self.RATE_LIMIT_MAX_CMD} en 60s)",
                "remaining": 0,
            }

        if command in self.HEAVY_COMMANDS and heavy_count >= self.RATE_LIMIT_MAX_HEAVY:
            self._add_violation(user_id, "rate_limit_heavy")
            return {
                "allowed":   False,
                "reason":    f"Trop de commandes lourdes ({heavy_count}/{self.RATE_LIMIT_MAX_HEAVY} en 60s)",
                "remaining": 0,
            }

        return {
            "allowed":   True,
            "reason":    None,
            "remaining": self.RATE_LIMIT_MAX_CMD - len(recent) - 1,
        }

    def _add_violation(self, user_id: str, reason: str):
        user_id = str(user_id)
        self.violations[user_id] += 1

        logger.warning(
            f"🔐 Violation {reason} : {user_id} "
            f"({self.violations[user_id]}/{self.BLACKLIST_THRESHOLD})"
        )

        if self.violations[user_id] >= self.BLACKLIST_THRESHOLD:
            expiry = time.time() + self.BLACKLIST_DURATION
            self.blacklist[user_id] = expiry
            logger.warning(
                f"🔐 BLACKLIST : {user_id} pendant {self.BLACKLIST_DURATION}s"
            )

    def register_command(
        self,
        user_id: str,
        command: str,
        success: bool = True,
    ):
        user_id = str(user_id)
        now     = time.time()

        self.command_history[user_id].append(now)

        self.command_log.append({
            "user_id":   user_id,
            "command":   command,
            "timestamp": now,
            "date":      datetime.now(timezone.utc).isoformat(),
            "success":   success,
        })

        if user_id not in self.admin_stats:
            self.admin_stats[user_id] = {
                "commands_count": 0,
                "first_seen":     now,
                "last_command":   None,
                "last_time":      0,
            }

        stats = self.admin_stats[user_id]
        stats["commands_count"] += 1
        stats["last_command"]    = command
        stats["last_time"]       = now

    def needs_confirmation(self, command: str) -> bool:
        return command in self.SENSITIVE_COMMANDS

    def request_confirmation(
        self, user_id: str, command: str
    ) -> dict:
        user_id = str(user_id)

        if user_id in self.pending_confirmations:
            pending = self.pending_confirmations[user_id]
            if pending["command"] == command:
                del self.pending_confirmations[user_id]
                logger.info(
                    f"🔐 Confirmation reçue : {user_id} → {command}"
                )
                return {"confirmed": True, "message": "Commande confirmée"}
            del self.pending_confirmations[user_id]

        self.pending_confirmations[user_id] = {
            "command":   command,
            "timestamp": time.time(),
        }

        return {
            "confirmed": False,
            "message": (
                f"🔒 CONFIRMATION REQUISE\n\n"
                f"Cette commande est sensible.\n"
                f"Retape `{command}` dans les {self.CONFIRMATION_TIMEOUT}s "
                f"pour confirmer."
            ),
        }

    def get_stats(self) -> dict:
        return {
            "authorized_admins": len(self.authorized_admins),
            "total_commands":    len(self.command_log),
            "active_users":      len(self.admin_stats),
            "blacklisted":       len(self.blacklist),
            "pending_confirms":  len(self.pending_confirmations),
            "total_violations":  sum(self.violations.values()),
        }

    def get_admin_stats(self, user_id: str = None) -> dict:
        if user_id:
            return self.admin_stats.get(str(user_id), {})
        return dict(self.admin_stats)

    def get_recent_commands(self, limit: int = 20) -> list:
        return list(self.command_log[-limit:])

    def get_authorized_admins(self) -> list:
        return list(self.authorized_admins)

    def add_admin(self, user_id: str) -> bool:
        user_id = str(user_id)
        if user_id not in self.authorized_admins:
            self.authorized_admins.add(user_id)
            logger.info(f"🔐 Admin ajouté : {user_id}")
            return True
        return False

    def remove_admin(self, user_id: str) -> bool:
        user_id = str(user_id)
        if user_id == str(self.main_admin):
            return False
        if user_id in self.authorized_admins:
            self.authorized_admins.remove(user_id)
            logger.info(f"🔐 Admin retiré : {user_id}")
            return True
        return False

    def unblacklist(self, user_id: str) -> bool:
        user_id = str(user_id)
        if user_id in self.blacklist:
            del self.blacklist[user_id]
            self.violations[user_id] = 0
            logger.info(f"🔐 Débloqué manuellement : {user_id}")
            return True
        return False

    def clear_violations(self, user_id: str = None):
        if user_id:
            self.violations[str(user_id)] = 0
        else:
            self.violations.clear()

    def _load_data(self):
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.violations  = defaultdict(int, data.get("violations", {}))
                    self.admin_stats = data.get("admin_stats", {})
                    self.command_log = data.get("command_log", [])[-500:]
                    logger.info(
                        f"🔐 Security data chargée "
                        f"({len(self.admin_stats)} admins historiques)"
                    )
        except Exception as e:
            logger.error(f"Security load error : {e}")

    def _save_data(self):
        try:
            os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "violations":  dict(self.violations),
                    "admin_stats": self.admin_stats,
                    "command_log": self.command_log[-500:],
                    "saved_at":    datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Security save error : {e}")