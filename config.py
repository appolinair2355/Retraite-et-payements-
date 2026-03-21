"""
Bot Telegram - Gestionnaire d'Accès Multi-Canal
Configuration complète pour déploiement Render.com (port 10000)

Variables d'environnement disponibles :
  BOT_TOKEN              - Token du bot Telegram (obligatoire)
  ADMINS                 - IDs admin séparés par virgule (ex: 123456,789012)
  PORT                   - Port web (défaut: 10000)

  -- Clés IA (plusieurs clés séparées par virgule) --
  GEMINI_API_KEYS        - Clé(s) Google Gemini  (ex: AIzaSy...,AIzaSy...)
  OPENAI_API_KEYS        - Clé(s) OpenAI          (ex: sk-...,sk-...)
  GROQ_API_KEYS          - Clé(s) Groq             (ex: gsk_...,gsk_...)
  DEEPSEEK_API_KEYS      - Clé(s) DeepSeek         (ex: sk-...,sk-...)
  OCR_SPACE_API_KEY      - Clé OCR.space (secours vision)

  -- Telethon (optionnel, scan membres complet) --
  TELETHON_API_ID        - ID API Telethon
  TELETHON_API_HASH      - Hash API Telethon
  TELETHON_SESSION       - Chaîne de session Telethon
"""

import os

# ── Telegram ────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMINS_STR = os.getenv("ADMINS", "")
ADMINS = [int(x.strip()) for x in ADMINS_STR.split(",") if x.strip().isdigit()]

PORT = int(os.getenv("PORT", "10000"))

# ── Données persistantes ────────────────────────────────────────
DATA_FILE = "channels_data.json"
CHECK_INTERVAL = 60

# ── Clé Gemini principale (rétrocompat) ────────────────────────
# Accepte GEMINI_API_KEY (ancienne) ou GEMINI_API_KEYS (nouvelle, multi)
def _parse_keys(env_name_plural: str, env_name_single: str = "") -> list:
    """Lit une var d'env contenant 0..N clés séparées par virgule."""
    raw = os.getenv(env_name_plural, "") or os.getenv(env_name_single, "")
    return [k.strip() for k in raw.split(",") if k.strip()]

GEMINI_API_KEYS  = _parse_keys("GEMINI_API_KEYS",   "GEMINI_API_KEY")
OPENAI_API_KEYS  = _parse_keys("OPENAI_API_KEYS",   "OPENAI_API_KEY")
GROQ_API_KEYS    = _parse_keys("GROQ_API_KEYS",     "GROQ_API_KEY")
DEEPSEEK_API_KEYS = _parse_keys("DEEPSEEK_API_KEYS","DEEPSEEK_API_KEY")
OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_API_KEY", "")

# Alias rétrocompat (utilisé dans main.py)
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""

# ── Telethon (optionnel) ────────────────────────────────────────
TELETHON_API_ID   = int(os.getenv("TELETHON_API_ID", "0") or "0")
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "")
TELETHON_SESSION  = os.getenv("TELETHON_SESSION", "")
