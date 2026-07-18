#!/usr/bin/env python3
# scripts/reset_performance.py — v1.0
# Remet à zéro l'historique des performances
# Lance : python scripts/reset_performance.py

import os
import sys
import json
import time
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_FILE = "data/performance.json"


def main():
    print("\n🗑️  Reset de l'historique des performances\n" + "═" * 40)

    if not os.path.exists(DB_FILE):
        print("  ℹ️  Fichier inexistant — rien à faire")
        return

    # Affiche les stats actuelles
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  📊 Trades actuels : {len(data)}")
    except Exception as e:
        print(f"  ⚠️  Impossible de lire le fichier : {e}")
        data = {}

    # Confirmation
    response = input("\n  ⚠️  Confirmer le reset ? (oui/non) : ").strip().lower()
    if response not in ("oui", "o", "yes", "y"):
        print("  ❌ Reset annulé")
        return

    # Backup avant reset
    backup = DB_FILE.replace(
        ".json",
        f"_backup_{int(time.time())}.json",
    )
    try:
        shutil.copy2(DB_FILE, backup)
        print(f"  💾 Backup créé : {backup}")
    except Exception as e:
        print(f"  ⚠️  Backup impossible : {e}")

    # Reset
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
        print(f"  ✅ Fichier remis à zéro : {DB_FILE}")
    except Exception as e:
        print(f"  ❌ Erreur reset : {e}")

    print("\n✅ Terminé\n")


if __name__ == "__main__":
    main()