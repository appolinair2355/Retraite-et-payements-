"""
Bot Telegram - Gestionnaire d'Accès Multi-Canal
Configuration pour déploiement Render.com (port 10000)
"""

import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8442253971:AAEisYucgZ49Ej2b-mK9_6DhNrqh9WOc_XU")

ADMINS_STR = os.getenv("ADMINS", "8649780855")
ADMINS = [int(x.strip()) for x in ADMINS_STR.split(",") if x.strip()]

PORT = int(os.getenv("PORT", "5000"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCLIkisyBGwLq6GZccGcCijvCFzdzZczsU")

TELETHON_API_ID = int(os.getenv("TELETHON_API_ID", "30696801"))
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "1BJWap1wBuzQ-THnnulo4T9qTz28w5NZDy9FqUpqSjAVGBPhPKHXuLuzTHLaF937hQ1Afh7kb1CTn3TxOUSTkLbnLiE2j8bYCnqlkbR7i-5WWB4JyVHqDti9A7_nnDKSb_nEoqw-WiJxRs0R2LmEI1vVn7e3Y2RaeIZtv9Sq5-AOlu8KPGHDAte1u23cCK6uEe-fNU6ei_i3aXYmeM4Vh2Bbs2ukyt35KHg2tbVoFHlle5NDGOVi-iI99dAA6gBaEe4M2eetklNSQFm0AHY1stLafVpYHqJWLgclUh-PN6nWa-QwIh5_GNI8QQIxW-U0B0YJBCcFSWF7NQPeTTa9nLbFndqCLenQ=")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", ")

DATA_FILE = "channels_data.json"
CHECK_INTERVAL = 60
