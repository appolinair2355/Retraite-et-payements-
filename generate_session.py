"""
Génère une session Telethon et l'envoie dans votre chat Telegram privé.

Usage (dans le Shell Replit) :
    python generate_session.py

Étapes :
  1. Entrez votre numéro de téléphone  (+225XXXXXXXXXX)
  2. Telegram vous envoie un code de vérification
  3. Tapez le code avec le préfixe "aa"  →  ex : aa12345
  4. La session est affichée dans le Shell ET envoyée dans votre chat Telegram
"""

import asyncio
import os
import sys

import httpx
from telethon import TelegramClient
from telethon.sessions import StringSession

# ── Récupérer les variables depuis config.py ──────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import TELETHON_API_ID, TELETHON_API_HASH, BOT_TOKEN, ADMINS


async def send_to_telegram(session_str: str):
    """Envoie la session dans le chat privé du premier admin."""
    if not ADMINS or not BOT_TOKEN:
        return
    admin_id = ADMINS[0]
    text = (
        "🔑 *Session Telethon générée avec succès*\n\n"
        "Copiez cette chaîne et utilisez-la comme variable d'environnement "
        "`TELETHON_SESSION` sur Render.com ou dans votre `.env` :\n\n"
        f"`{session_str}`\n\n"
        "⚠️ *Ne partagez jamais cette chaîne avec personne.*"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": admin_id, "text": text, "parse_mode": "Markdown"},
            )
            if r.status_code == 200:
                print(f"✅ Session envoyée dans votre chat Telegram (ID: {admin_id})")
            else:
                print(f"⚠️  Envoi Telegram échoué ({r.status_code}): {r.text}")
    except Exception as e:
        print(f"⚠️  Erreur envoi Telegram: {e}")


async def main():
    print()
    print("═" * 62)
    print("   GÉNÉRATEUR DE SESSION TELETHON")
    print("═" * 62)
    print()

    phone = input("📱 Numéro de téléphone (avec indicatif, ex: +22500000000): ").strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    client = TelegramClient(StringSession(), TELETHON_API_ID, TELETHON_API_HASH)
    await client.connect()

    print(f"\n⏳ Envoi du code de vérification à {phone} …")
    try:
        await client.send_code_request(phone)
    except Exception as e:
        print(f"❌ Impossible d'envoyer le code : {e}")
        await client.disconnect()
        return

    print("\n📨 Un code vient d'arriver dans votre application Telegram.")
    print("   Entrez-le ici avec le préfixe  'aa'  (exemple : aa12345)")
    raw = input("🔑 Code : ").strip()

    if not raw.lower().startswith("aa"):
        print("❌ Le code doit commencer par 'aa'  (exemple : aa12345). Abandonné.")
        await client.disconnect()
        return

    code = raw[2:].strip()  # supprimer le préfixe "aa"

    try:
        await client.sign_in(phone, code)
    except Exception as e:
        err = str(e).lower()
        if "two-step" in err or "password" in err or "2fa" in err:
            pwd = input("🔐 2FA activé — entrez votre mot de passe Telegram : ").strip()
            try:
                await client.sign_in(password=pwd)
            except Exception as e2:
                print(f"❌ Erreur 2FA : {e2}")
                await client.disconnect()
                return
        else:
            print(f"❌ Erreur de connexion : {e}")
            await client.disconnect()
            return

    session_str = client.session.save()
    await client.disconnect()

    print()
    print("═" * 62)
    print("✅  SESSION GÉNÉRÉE AVEC SUCCÈS")
    print("═" * 62)
    print()
    print(session_str)
    print()
    print("═" * 62)
    print("Copiez la chaîne ci-dessus dans la variable TELETHON_SESSION")
    print("sur Render.com (ou dans vos secrets Replit).")
    print("═" * 62)
    print()

    # Envoyer également dans le chat Telegram
    await send_to_telegram(session_str)
    print()


asyncio.run(main())
