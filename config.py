"""
Bot Telegram - Gestionnaire d'Accès Multi-Canal
Configuration pour déploiement Render.com (port 10000)
"""

import os

# ─── OBLIGATOIRE — À définir dans Render.com > Environment ───────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN est requis. Configurez-le dans les variables d'environnement Render.com.")

# ─── ADMINISTRATEURS ─────────────────────────────────────────────────────────
ADMINS_STR = os.getenv("ADMINS", "1190237801")
ADMINS = [int(x.strip()) for x in ADMINS_STR.split(",") if x.strip()]

# ─── PORT RENDER.COM ─────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "10000"))

# ─── CLÉ IA (non utilisée ici — les clés IA sont configurées via le panneau admin du bot) ──
GEMINI_API_KEY = ""

# ─── TELETHON ─────────────────────────────────────────────────────────────────
TELETHON_API_ID = int(os.getenv("TELETHON_API_ID", "29177661"))
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "a8639172fa8d35dbfd8ea46286d349ab")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "")

# ─── FICHIER DE DONNÉES ───────────────────────────────────────────────────────
DATA_FILE = "channels_data.json"
CHECK_INTERVAL = 60
