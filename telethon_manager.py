"""
Gestionnaire Telethon - Connexion au compte Telegram personnel
Permet de voir tous les membres d'un canal
"""

import logging
import os
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch

logger = logging.getLogger(__name__)

try:
    from config import TELETHON_API_ID as _CFG_API_ID, TELETHON_API_HASH as _CFG_API_HASH, TELETHON_SESSION as _CFG_SESSION
except ImportError:
    _CFG_API_ID, _CFG_API_HASH, _CFG_SESSION = 0, "", ""

API_ID = int(os.getenv("TELETHON_API_ID", str(_CFG_API_ID)))
API_HASH = os.getenv("TELETHON_API_HASH", _CFG_API_HASH)

def _load_session_string() -> str:
    """
    Charge la session Telethon depuis (par ordre de priorité) :
      1. Variable d'environnement TELETHON_SESSION
      2. config.py (TELETHON_SESSION)
      3. channels_data.json  ← persistance sur Render.com
      4. telethon_session.txt (fallback local)
    """
    s = os.getenv("TELETHON_SESSION", "") or _CFG_SESSION
    if s:
        return s
    # Lecture dans channels_data.json pour survivre aux redémarrages Render
    try:
        import json as _json
        with open("channels_data.json", "r", encoding="utf-8") as f:
            data = _json.load(f)
        s = data.get("telethon_session", "")
        if s:
            return s
    except Exception:
        pass
    try:
        with open("telethon_session.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

SESSION_STRING = _load_session_string()

# Client Telethon global
telethon_client: TelegramClient = None


def get_client() -> TelegramClient:
    """Retourne ou crée le client Telethon"""
    global telethon_client
    if telethon_client is None:
        session_str = _load_session_string()
        session = StringSession(session_str) if session_str else StringSession()
        telethon_client = TelegramClient(session, API_ID, API_HASH)
    return telethon_client


async def is_connected() -> bool:
    """Vérifie si le client est connecté"""
    try:
        client = get_client()
        if not client.is_connected():
            await client.connect()
        return await client.is_user_authorized()
    except Exception as e:
        logger.error(f"Erreur is_connected: {e}")
        return False


async def get_session_string() -> str:
    """Retourne la session string pour la sauvegarder"""
    client = get_client()
    return client.session.save()


async def get_all_channel_members(channel_id: int) -> list:
    """Récupère tous les membres d'un canal via Telethon"""
    try:
        client = get_client()
        if not client.is_connected():
            await client.connect()

        if not await client.is_user_authorized():
            logger.warning("Telethon non authentifié")
            return []

        all_participants = []
        offset = 0
        limit = 100

        while True:
            participants = await client(GetParticipantsRequest(
                channel=channel_id,
                filter=ChannelParticipantsSearch(""),
                offset=offset,
                limit=limit,
                hash=0
            ))

            if not participants.users:
                break

            all_participants.extend(participants.users)
            offset += len(participants.users)

            if offset >= participants.count:
                break

        # Filtrer les bots
        return [u for u in all_participants if not u.bot]

    except Exception as e:
        logger.error(f"Erreur get_all_channel_members: {e}")
        return []


# État d'authentification en cours
auth_state = {}  # {user_id: {"step": "phone"|"code"|"2fa", "phone": str}}


async def start_auth(user_id: int) -> str:
    """Démarre le processus d'authentification"""
    try:
        client = get_client()
        if not client.is_connected():
            await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            return f"✅ Déjà connecté en tant que **{me.first_name}** (@{me.username or me.id})"

        auth_state[user_id] = {"step": "phone"}
        return "📱 Entrez votre **numéro de téléphone** Telegram (format international, ex: +22507XXXXXXXX):"

    except Exception as e:
        logger.error(f"Erreur start_auth: {e}")
        return f"❌ Erreur: {e}"


async def process_auth_step(user_id: int, text: str) -> tuple[str, bool]:
    """
    Traite une étape d'authentification.
    Retourne (message, auth_complete)
    """
    state = auth_state.get(user_id, {})
    step = state.get("step")
    client = get_client()

    if not client.is_connected():
        await client.connect()

    try:
        if step == "phone":
            phone = text.strip()
            state["phone"] = phone
            await client.send_code_request(phone)
            state["step"] = "code"
            auth_state[user_id] = state
            return (
                f"📨 Code de vérification envoyé à **{phone}**.\n\n"
                f"⚠️ Tapez `aa` suivi de votre code Telegram (sans espace).\n"
                f"Exemple: si le code est `12345` → envoyez `aa12345`",
                False
            )

        elif step == "code":
            raw = text.strip()
            # Exiger le préfixe "aa"
            if not raw.lower().startswith("aa"):
                return (
                    "⚠️ Format incorrect.\n\n"
                    "Tapez `aa` devant votre code. Exemple: `aa12345`",
                    False
                )
            code = raw[2:].strip().replace(" ", "")
            phone = state.get("phone")
            try:
                await client.sign_in(phone, code)
                me = await client.get_me()
                del auth_state[user_id]
                return (
                    f"✅ **Connexion réussie!**\n\n"
                    f"👤 Connecté: **{me.first_name}** (@{me.username or me.id})",
                    True
                )
            except Exception as e:
                if "two-steps" in str(e).lower() or "password" in str(e).lower():
                    state["step"] = "2fa"
                    auth_state[user_id] = state
                    return (
                        "🔐 Votre compte a la **vérification 2 étapes** activée.\n\n"
                        "Tapez `aa` suivi de votre mot de passe 2FA.\n"
                        "Exemple: `aaMonMotDePasse`",
                        False
                    )
                raise e

        elif step == "2fa":
            raw = text.strip()
            if not raw.lower().startswith("aa"):
                return (
                    "⚠️ Format incorrect.\n\n"
                    "Tapez `aa` devant votre mot de passe 2FA. Exemple: `aaMonMotDePasse`",
                    False
                )
            password = raw[2:]
            await client.sign_in(password=password)
            me = await client.get_me()
            del auth_state[user_id]
            return (
                f"✅ **Connexion réussie avec 2FA!**\n\n"
                f"👤 Connecté: **{me.first_name}** (@{me.username or me.id})",
                True
            )

    except Exception as e:
        logger.error(f"Erreur auth step {step}: {e}")
        auth_state.pop(user_id, None)
        return (f"❌ Erreur d'authentification: {e}\n\nRecommencez avec /connect", False)

    return ("❌ Étape inconnue. Recommencez avec /connect", False)
