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
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "1BJWap1sBu0iZ5dHCi4009vVdtCKekCTR88PA4Uy1nUKmr09kn7Sb6Aj5L8O2OQveSdEP6EUrgA58wjkAToV_D-uSQ7jZwicevyvSPcrNObl7WVI9Qgc88-0DBz6hu4GLqtJDwWqtDSSaxi_Zla7d__GrtsYOHqpmoZso_w0UtlHE6Hr51T8ayci9cJcmR0lL8A2QB3RINBcD_DfWnj2Q4dxG0UGMLWY1sLrszQ8u3P4i-pS2WjyaVXg9kd9xn92r9zcNRF-NMaSKmelujL_L7ux4X1YzAudYvpWBCOG-G8ckkBguLthtIjuEE_U8mc9ntfzKw4W6OFgEafJNr1hTdgndf4YxWoM=")

DATA_FILE = "channels_data.json"
CHECK_INTERVAL = 60
