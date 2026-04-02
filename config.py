"""
Bot Telegram - Gestionnaire d'Accès Multi-Canal
Configuration pour déploiement Render.com (port 10000)
"""

import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8442253971:AAEisYucgZ49Ej2b-mK9_6DhNrqh9WOc_XU")

ADMINS_STR = os.getenv("ADMINS", "1190237801")
ADMINS = [int(x.strip()) for x in ADMINS_STR.split(",") if x.strip()]

PORT = int(os.getenv("PORT", "5000"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCLIkisyBGwLq6GZccGcCijvCFzdzZczsU")

TELETHON_API_ID = int(os.getenv("TELETHON_API_ID", "29177661"))
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "a8639172fa8d35dbfd8ea46286d349ab")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "1BJWap1wBux_QLE6eCmOvh_-xu9dHUqu-zuZLWoAbVxHHyNt33g6LrBQ5uJzvaB-Pdfi0InFVtgMj94fNHdX2Kdm1GckTVjW4LYfoeMl0WVEYZXK0J1-RpmK2dAgq1DZBfHY5PhnYSj4jmecP6EnbyYKoe-PpJ4vmlzI0QAJo6-tajhYJ_RFH9JAdhjixa1_lHIjJVgZFyvMkYY02aZ4m0Dixt7dWAqg-4wM6NX-b70XAoKAfblX0V_AyP0M7hRf7Qzk8QjPP3xPeT-onO1HAjuubugPCscHp2YdPYMqQegQcb94IlVcLSxALV8k4IFGXdNi-UfCQI1HdyWlapNZxC_GmfnYCeSU=")

DATA_FILE = "channels_data.json"
CHECK_INTERVAL = 60
