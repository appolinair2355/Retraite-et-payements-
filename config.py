"""
Bot Telegram - Gestionnaire d'Accès Multi-Canal
Configuration pour déploiement Render.com (port 10000)
"""

import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "7573497633:AAHk9K15yTCiJP-zruJrc9v8eK8I9XhjyH4")

ADMINS_STR = os.getenv("ADMINS", "1190237801")
ADMINS = [int(x.strip()) for x in ADMINS_STR.split(",") if x.strip()]

PORT = int(os.getenv("PORT", "5000"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

TELETHON_API_ID = int(os.getenv("TELETHON_API_ID", "29177661"))
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "a8639172fa8d35dbfd8ea46286d349ab")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "1BJWap1wBu1ij6TcbL6NW6QAR7uMH1fTgRzZgsMI2moX1EvaccZNTmBi5bhHw8pm6yNGnMvb2Z693jqSTJ52Ey_tu895jjnf5jaJ1HYBSRNgov9-POC1upn6xEbRJJxY80s_Ey96ebqmcCbedx-0rZg4Gn9cSCzpECIOkvAf1DPU1OalZAY2OpaiBUSE3MqzBl03nEs7BmJj9lRG3KZRzCH6vv9jX4KvsKkpcN1bYpCiL20VaVKOs9PgUfn4ZzL8QpNqEjY0sKw7AAX0m859midTEIgyOXftKu3pFBpA7-aveZxmLgHrnLo0mxnpyIWVHPCXGDjG-Yc2qpbB8rHDqp6w_wK2kuZ4=")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bonjour_user:WzeZsFKlKWU180iOFxngBEaThdG1kKUR@dpg-d962464s728c73e8p250-a.oregon-postgres.render.com/bonjour")

DATA_FILE = "channels_data.json"
CHECK_INTERVAL = 60
