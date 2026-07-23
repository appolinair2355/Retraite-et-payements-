"""
Bot Telegram - Gestionnaire d'Accès Multi-Canal
Autonome: fonctionne sur plusieurs canaux simultanément
Assistante IA: répond automatiquement aux utilisateurs
"""

import asyncio
import json
import logging
import os
import re as _re_mod
from datetime import datetime, timedelta, timezone
from aiohttp import web
import asyncpg
import bcrypt as _bcrypt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ChatMemberHandler, ContextTypes, filters
)

from config import BOT_TOKEN, ADMINS, PORT, DATA_FILE, CHECK_INTERVAL, GEMINI_API_KEY, TELETHON_API_ID, TELETHON_API_HASH, DATABASE_URL
import telethon_manager

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# IA Gemini
gemini_client = None
if GEMINI_API_KEY:
    try:
        from google import genai as google_genai
        from google.genai import types as genai_types
        gemini_client = google_genai.Client(api_key=GEMINI_API_KEY)
        logger.info("✅ Assistant IA Gemini initialisé")
    except Exception as e:
        logger.warning(f"⚠️ Impossible d'initialiser Gemini: {e}")

# ═══════════════════════════════════════════════════════════════
# BASE DE DONNÉES POSTGRESQL
# ═══════════════════════════════════════════════════════════════
# DATABASE_URL importé depuis config.py
db_pool = None


async def init_db_pool():
    global db_pool
    if not DATABASE_URL:
        logger.warning("⚠️ DATABASE_URL non configuré — fonctions DB désactivées")
        return
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL, ssl="require", min_size=1, max_size=5, command_timeout=15
        )
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(120) UNIQUE NOT NULL,
                    email VARCHAR(120) UNIQUE,
                    password_hash VARCHAR(256) NOT NULL,
                    first_name TEXT, last_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_approved BOOLEAN DEFAULT FALSE,
                    is_premium BOOLEAN DEFAULT FALSE,
                    subscription_expires_at TIMESTAMPTZ,
                    subscription_duration_minutes INTEGER,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;
                CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_id_uniq
                    ON users(telegram_id) WHERE telegram_id IS NOT NULL;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS plain_password TEXT;
            """)
        logger.info("✅ Connexion PostgreSQL établie")
    except Exception as e:
        logger.error(f"❌ Connexion DB échouée: {e}")
        db_pool = None


async def db_get_user_by_telegram_id(telegram_id: int):
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1", telegram_id
            )
    except Exception as e:
        logger.error(f"DB get_user error: {e}")
        return None


async def db_email_exists(email: str) -> bool:
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1 OR username = $1",
                email.lower().strip(),
            )
            return row is not None
    except Exception as e:
        logger.error(f"DB email_exists error: {e}")
        return False


async def db_register_user(
    telegram_id: int, first_name: str, last_name: str, email: str, plain_password: str
):
    """Crée un compte utilisateur dans la base de données de paiement."""
    if not db_pool:
        return None, "Base de données non disponible"
    email = email.lower().strip()
    try:
        pw_hash = _bcrypt.hashpw(plain_password.encode(), _bcrypt.gensalt()).decode()
        async with db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO users
                        (username, email, password_hash, first_name, last_name,
                         is_approved, telegram_id, plain_password)
                    VALUES ($1,$2,$3,$4,$5,TRUE,$6,$7)
                    RETURNING *
                    """,
                    email, email, pw_hash, first_name, last_name,
                    telegram_id, plain_password,
                )
                return row, None
            except Exception as insert_err:
                err_str = str(insert_err)
                if "23505" in err_str or "unique" in err_str.lower():
                    return None, "email_exists"
                return None, err_str
    except Exception as e:
        logger.error(f"DB register_user error: {e}")
        return None, str(e)


async def db_check_subscription(telegram_id: int):
    """Retourne les infos d'abonnement actif ou None si expiré/inexistant."""
    user = await db_get_user_by_telegram_id(telegram_id)
    if not user:
        return None
    expires_at = user["subscription_expires_at"]
    if not expires_at:
        return None
    now = datetime.now(timezone.utc)
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    if exp > now:
        return {
            "expires_at": exp,
            "duration_minutes": user.get("subscription_duration_minutes") or 0,
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "email": user.get("email") or "",
        }
    return None


async def db_get_user_by_email(email: str):
    """Recherche un utilisateur par email."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1 OR username = $1",
                email.lower().strip(),
            )
    except Exception as e:
        logger.error(f"DB get_user_by_email error: {e}")
        return None


async def db_link_telegram_id(db_user_id: int, telegram_id: int) -> bool:
    """Lie un Telegram ID à un compte existant (délie l'ancien si nécessaire)."""
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET telegram_id = NULL WHERE telegram_id = $1 AND id != $2",
                telegram_id, db_user_id,
            )
            await conn.execute(
                "UPDATE users SET telegram_id = $1 WHERE id = $2",
                telegram_id, db_user_id,
            )
        return True
    except Exception as e:
        logger.error(f"DB link_telegram_id error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# ÉTATS CONVERSATIONNELS
# ═══════════════════════════════════════════════════════════════

# Inscription: {user_id: {"step": "first_name"|"last_name"|"email"|"password"|"confirm", ...}}
reg_state = {}

# Connexion: {user_id: {"step": "email"|"password", "email": str, "db_user_id": int}}
login_state = {}

# IDs Telegram des utilisateurs reconnus admin via la base de données (rempli à la connexion)
db_admin_telegram_ids = set()

# État des demandes de bonus en attente d'approbation admin
# {user_id: {"channel_id": str, "channel_name": str, "user_name": str}}
bonus_state = {}

# Liens d'invitation en attente de confirmation admin
# {(cid, uid_str): invite_link_str}
pending_invites = {}

# Utilisateurs actuellement en mode assistance IA
# {user_id: True}
assistance_mode = {}

# État admin pour les flux de configuration interactive
# {admin_id: {"action": str, ...}}
admin_state = {}

# Fournisseurs IA supportés
AI_PROVIDERS = {
    "gemini":   {"name": "Gemini",   "emoji": "🔵", "default_model": "gemini-2.5-flash-lite"},
    "openai":   {"name": "OpenAI",   "emoji": "🟢", "default_model": "gpt-4o-mini"},
    "groq":     {"name": "Groq",     "emoji": "🟠", "default_model": "llama-3.1-8b-instant"},
    "deepseek": {"name": "DeepSeek", "emoji": "🔷", "default_model": "deepseek-chat"},
}

# Suivi des échecs de clés IA en mémoire
# {(provider, api_key): {"until": timestamp, "reason": "quota"|"invalid"}}
ai_key_failures = {}

# Timestamp de la dernière alerte admin envoyée (évite le spam)
_ai_alert_last_sent = 0
_AI_ALERT_COOLDOWN = 1800  # Envoyer l'alerte au max toutes les 30 minutes

# ═══════════════════════════════════════════════════════════════
# GESTION DES DONNÉES
# ═══════════════════════════════════════════════════════════════

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        data = {"channels": {}, "global_admins": ADMINS, "ai_enabled": True}
        save_data(data)
        return data
    except Exception as e:
        logger.error(f"Erreur load_data: {e}")
        return {"channels": {}, "global_admins": ADMINS, "ai_enabled": True}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def is_admin(user_id):
    return user_id in ADMINS or user_id in db_admin_telegram_ids


def format_time_remaining(seconds):
    if seconds <= 0:
        return "Expiré"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours >= 24:
        days = hours // 24
        rem = hours % 24
        return f"{days}j {rem}h" if rem else f"{days}j"
    elif hours > 0:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


def get_channel_data(data, channel_id):
    cid = str(channel_id)
    if cid not in data["channels"]:
        data["channels"][cid] = {
            "name": f"Canal {cid}",
            "default_duration_seconds": 86400,
            "members": {},
            "blocked": {}
        }
    ch = data["channels"][cid]
    if "blocked" not in ch:
        ch["blocked"] = {}
    # Migration automatique: ancien champ → nouveau champ
    if "default_duration_seconds" not in ch and "default_duration_hours" in ch:
        ch["default_duration_seconds"] = ch["default_duration_hours"] * 3600
    elif "default_duration_seconds" not in ch:
        ch["default_duration_seconds"] = 86400
    return ch


def format_duration_label(total_seconds: int) -> str:
    """Formate une durée en secondes en texte lisible"""
    if total_seconds < 3600:
        m = total_seconds // 60
        return f"{m} minute{'s' if m > 1 else ''}"
    hours = total_seconds // 3600
    if hours >= 24:
        days = hours // 24
        rem = hours % 24
        return f"{days}j {rem}h" if rem else f"{days}j"
    return f"{hours}h"


def member_keyboard(cid: str, uid: str, default_hours: int):
    """Clavier standard pour accorder l'accès à un membre"""
    return [
        [InlineKeyboardButton("⏱ 30min", callback_data=f"grantm_{cid}_{uid}_30"),
         InlineKeyboardButton("⏱ 1h",    callback_data=f"grant_{cid}_{uid}_1"),
         InlineKeyboardButton("⏱ 5h",    callback_data=f"grant_{cid}_{uid}_5")],
        [InlineKeyboardButton("⏱ 24h",   callback_data=f"grant_{cid}_{uid}_24"),
         InlineKeyboardButton("⏱ 48h",   callback_data=f"grant_{cid}_{uid}_48")],
        [InlineKeyboardButton("📅 7 jours",  callback_data=f"grant_{cid}_{uid}_168"),
         InlineKeyboardButton("📅 1 mois",   callback_data=f"grant_{cid}_{uid}_720")],
        [InlineKeyboardButton("❌ Retirer maintenant", callback_data=f"kick_{cid}_{uid}")]
    ]


# ═══════════════════════════════════════════════════════════════
# SERVEUR WEB KEEP-ALIVE
# ═══════════════════════════════════════════════════════════════

async def web_handler(request):
    data = load_data()
    total_members = sum(
        len(ch.get("members", {}))
        for ch in data.get("channels", {}).values()
    )
    channels_count = len(data.get("channels", {}))
    ai_status = "✅ IA active" if data.get("ai_enabled", True) and gemini_client else "⭕ IA inactive"
    return web.Response(
        text=f"🤖 Bot Telegram Multi-Canal | {channels_count} canal(aux) | {total_members} membre(s) | {ai_status}",
        content_type="text/html"
    )


async def start_web_server():
    app = web.Application()
    app.router.add_get('/', web_handler)
    app.router.add_get('/health', lambda request: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Serveur web démarré sur le port {PORT}")


# ═══════════════════════════════════════════════════════════════
# ASSISTANT IA
# ═══════════════════════════════════════════════════════════════

# Historique des conversations par utilisateur
conversation_history = {}

SYSTEM_PROMPT = """Tu es l'assistante virtuelle du développeur Sossou Kouamé Appolinaire.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IDENTITÉ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quand on te demande "qui es-tu ?", réponds :
"Je suis l'assistante du développeur Sossou Kouamé Appolinaire. Je suis là pour vous orienter sur le paiement, expliquer les commandes du bot et répondre à toutes vos questions sur Baccara."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LANGUE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Si la langue de l'utilisateur n'est pas claire, demande-lui dans quelle langue il préfère communiquer.
- Tu peux répondre dans TOUTES les langues du monde : français, anglais, arabe, espagnol, russe, portugais, chinois, etc.
- Adapte-toi toujours à la langue de l'utilisateur.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TARIFS ET ACCÈS AU CANAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABONNEMENT MENSUEL (OFFRE PRINCIPALE) :
- 50 USD = 1 mois complet d'accès (30 jours) — c'est l'offre recommandée
- En FCFA : 50 USD × 600 = 30 000 FCFA pour 1 mois

TARIF JOURNALIER (pour les durées courtes) :
- 1 000 FCFA = 1 jour d'accès au canal privé
- Exemples :
  • 1 000 FCFA → 1 jour
  • 5 000 FCFA → 5 jours
  • 10 000 FCFA → 10 jours
  • 30 000 FCFA → 1 mois (30 jours)

CONVERSIONS (taux automatiques du bot) :
- 1 USD = 600 FCFA (dollar américain)
- 1 EUR = 655 FCFA (euro — France, Europe)
- 1 GBP = 760 FCFA (livre sterling — Royaume-Uni)
- 1 CAD = 440 FCFA (dollar canadien)
- 1 CHF = 660 FCFA (franc suisse)
- 10 GNF = 1 FCFA (franc guinéen)

Exemples USD :
  • 50 USD = 30 000 FCFA → 1 mois (offre principale)
  • 20 USD = 12 000 FCFA → 12 jours
  • 10 USD = 6 000 FCFA → 6 jours
  • 5 USD = 3 000 FCFA → 3 jours

Exemples EUR (France) :
  • 50 EUR = 32 750 FCFA → 32 jours
  • 30 EUR = 19 650 FCFA → 19 jours
  • 10 EUR = 6 550 FCFA → 6 jours

APPLICATIONS DE PAIEMENT RECONNUES PAR LE BOT:
- Europe/France: PayPal, Revolut, Wise, Lydia, Sumeria, virement bancaire
- Afrique de l'Ouest: Wave, Orange Money, MTN Mobile Money, MoneyFusion, Free Money, Moov Money
- USA/International: CashApp, Venmo, Zelle
- Crypto: BNB (Binance)

Quand un utilisateur demande le prix ou l'abonnement mensuel, mets TOUJOURS en avant l'offre à 50 USD/mois comme l'offre principale et la plus avantageuse.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMENT PAYER — ÉTAPES EXACTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Étape 1 : Effectue ton paiement via le moyen selon ton pays (voir section PAIEMENT).
Étape 2 : Appuie sur le bouton 💳 "Payer mon abonnement" dans le bot (ou tape /payer).
Étape 3 : Envoie la capture d'écran de ton paiement dans le chat.
Étape 4 : Le bot analyse automatiquement le montant et la devise.
Étape 5 : Choisis le canal auquel tu veux accéder.
Étape 6 : Ton accès est activé immédiatement pour la durée calculée.
Étape 7 : Tu recevras un message de confirmation avec la date d'expiration.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RÈGLES DE PAIEMENT PAR PAYS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. TOUJOURS demander le pays de l'utilisateur avant de donner un lien de paiement.
2. Selon le pays :
   - AFRIQUE (Côte d'Ivoire, Sénégal, Mali, Burkina Faso, Guinée, Cameroun, Congo, Togo, Bénin, Niger, Mauritanie, Madagascar, Gabon, etc.)
     → Lien MoneyFusion UNIQUEMENT : https://my.moneyfusion.net/69988c55ee1fe6f8b700aa50
     → NE JAMAIS montrer l'adresse crypto
   - HORS AFRIQUE (Europe, Amérique, Asie, Océanie, etc.)
     → Crypto BNB UNIQUEMENT : 0x13108641DcfaBea3b2e8dEd4d35B8f49606f5A17
     → NE JAMAIS montrer le lien MoneyFusion
3. EXCEPTION : Si l'utilisateur demande EXPLICITEMENT la crypto → adresse BNB : 0x13108641DcfaBea3b2e8dEd4d35B8f49606f5A17
4. Ne jamais montrer les deux méthodes ensemble.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXPIRATION ET RENOUVELLEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Quand l'accès expire, l'utilisateur est automatiquement retiré du canal.
- Il reçoit un message l'informant que son accès a expiré.
- S'il tente de rejoindre le canal sans payer → il est automatiquement bloqué.
- Pour renouveler : refaire le processus de paiement normalement (💳 → capture → canal).
- Si bloqué par erreur, contacter l'administrateur.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDES DU BOT (pour les utilisateurs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/start — Affiche le menu principal avec les boutons 💬 Assistance et 💳 Payer
/payer — Lance directement le processus de paiement par capture d'écran

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDES ADMINISTRATEUR (ne partager qu'avec les admins)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/channels — Liste tous les canaux gérés par le bot
/members <id_canal> — Voir les membres actifs d'un canal
/grant <id_canal> <id_user> <heures> — Accorder l'accès manuellement (1h à 750h)
  Exemple : /grant -1001234567890 987654321 48  → 48h d'accès
/remove <id_canal> <id_user> — Retirer manuellement un membre
/unblock <id_canal> <id_user> — Débloquer un utilisateur banni
/setduration <id_canal> <heures> — Changer la durée du bouton "Défaut"
/scan <id_canal> — Rescanner manuellement un canal pour détecter les membres
/ai_on — Activer l'assistant IA
/ai_off — Désactiver l'assistant IA
/connect — Connecter Telethon (compte personnel) pour voir tous les membres
/telethon — Vérifier le statut de la connexion Telethon
/help — Afficher l'aide complète

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FONCTIONNEMENT DU BOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Le bot gère l'accès temporaire à des canaux Telegram privés.
- Quand un utilisateur rejoint un canal, l'admin reçoit une notification avec des boutons pour définir la durée : 2min / 10min / 20min / 30min / Défaut.
- La durée peut aller de 2 minutes à 750 heures (environ 31 jours).
- L'accès est retiré automatiquement à l'expiration, toutes les 30 secondes.
- Le paiement par capture d'écran est analysé automatiquement par l'IA.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOMAINE : BACCARA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Tu es experte du jeu Baccara et peux répondre à toutes les questions sur les règles, stratégies, statistiques, gestion de bankroll, etc.
- Les canaux privés proposent des signaux et analyses pour le Baccara.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STYLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Professionnelle, chaleureuse et précise.
- Utilise des exemples concrets avec chiffres quand l'utilisateur pose des questions sur les tarifs.
- Ne révèle jamais les tokens, clés API ou mots de passe.
- Pour les questions hors sujet, réponds brièvement et redirige.
"""

def get_keys_list(ai_config: dict, provider: str) -> list:
    """Retourne la liste des clés pour un fournisseur (supporte string ou list)"""
    keys_dict = ai_config.get("keys", {})
    val = keys_dict.get(provider)
    if val is None:
        return [GEMINI_API_KEY] if (provider == "gemini" and GEMINI_API_KEY) else []
    if isinstance(val, str):
        return [val] if val else []
    return [k for k in val if k]


def _is_quota_error(error_str: str) -> bool:
    return any(x in error_str for x in ["429", "quota", "rate limit", "exhausted", "resource_exhausted", "too many"])


def _is_invalid_key_error(error_str: str) -> bool:
    return any(x in error_str for x in ["401", "invalid api key", "api key not valid", "unauthorized", "permission_denied", "authentication"])


AI_CALL_TIMEOUT = 25  # secondes max par appel IA


async def _call_ai_provider(provider: str, api_key: str, history: list, user_message: str) -> str:
    """Effectue un appel IA avec une clé spécifique. Lève une exception si échec."""

    async def _do_call():
        if provider == "gemini":
            from google import genai as google_genai
            client = google_genai.Client(api_key=api_key)
            contents = [{"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                        {"role": "model", "parts": [{"text": "Bien compris, je suis prêt à aider."}]}]
            contents.extend(history)
            contents.append({"role": "user", "parts": [{"text": user_message}]})
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=AI_PROVIDERS["gemini"]["default_model"],
                    contents=contents
                )
            )
            return response.text
        else:
            import openai as openai_lib
            base_urls = {
                "openai": None,
                "groq": "https://api.groq.com/openai/v1",
                "deepseek": "https://api.deepseek.com",
            }
            client_kwargs = {"api_key": api_key, "timeout": AI_CALL_TIMEOUT, "max_retries": 0}
            if base_urls.get(provider):
                client_kwargs["base_url"] = base_urls[provider]
            oai_client = openai_lib.AsyncOpenAI(**client_kwargs)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for h in history:
                role = h.get("role", "user")
                content = h.get("parts", [{}])[0].get("text", "")
                if role == "model":
                    role = "assistant"
                messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": user_message})
            response = await oai_client.chat.completions.create(
                model=AI_PROVIDERS[provider]["default_model"],
                messages=messages
            )
            return response.choices[0].message.content

    try:
        return await asyncio.wait_for(_do_call(), timeout=AI_CALL_TIMEOUT)
    except asyncio.TimeoutError:
        raise Exception(f"Timeout: {provider} n'a pas répondu en {AI_CALL_TIMEOUT}s")


async def check_single_ai_key(provider: str, api_key: str) -> tuple:
    """Teste une clé IA. Retourne (succès: bool, message: str)."""
    try:
        result = await _call_ai_provider(provider, api_key, [], "test")
        return True, "✅ Active et fonctionnelle"
    except Exception as e:
        err = str(e).lower()
        if _is_quota_error(err):
            return False, "⚠️ Quota épuisé"
        elif _is_invalid_key_error(err):
            return False, "❌ Clé invalide"
        else:
            short = str(e)[:60]
            return False, f"❌ Erreur: {short}"


async def _notify_admins_keys_exhausted(bot, provider: str, keys: list, current_time: int):
    """Envoie une alerte privée aux admins quand toutes les clés sont épuisées."""
    global _ai_alert_last_sent
    if current_time - _ai_alert_last_sent < _AI_ALERT_COOLDOWN:
        return
    _ai_alert_last_sent = current_time

    pinfo = AI_PROVIDERS.get(provider, {"name": provider, "emoji": "🤖"})
    lines = [
        f"🚨 **ALERTE — Clés IA épuisées**\n",
        f"Fournisseur actif: {pinfo['emoji']} **{pinfo['name']}**",
        f"Toutes les clés sont indisponibles:\n",
    ]
    for i, k in enumerate(keys):
        short = k[:8] + "..." + k[-4:] if len(k) > 14 else k
        failure = ai_key_failures.get((provider, k))
        if failure:
            reason = "Quota épuisé" if failure["reason"] == "quota" else "Clé invalide"
            lines.append(f"  Clé {i+1} (`{short}`): ❌ {reason}")
        else:
            lines.append(f"  Clé {i+1} (`{short}`): ❌ Erreur inconnue")

    lines.append("\n_Ajoutez de nouvelles clés via le panneau admin → ⚙️ Config IA._")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Gérer les clés IA", callback_data="admin_ai_config")]])
    text = "\n".join(lines)

    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"Erreur envoi alerte admin {admin_id}: {e}")


async def _try_provider_keys(provider: str, keys: list, history: list, user_message: str, current_time: int) -> str | None:
    """Essaie toutes les clés d'un fournisseur. Retourne la réponse ou None si toutes échouent."""
    for api_key in keys:
        failure = ai_key_failures.get((provider, api_key))
        if failure and failure["until"] > current_time:
            logger.info(f"[{provider}] Clé #{keys.index(api_key)+1} en cooldown → suivante")
            continue
        try:
            reply_text = await _call_ai_provider(provider, api_key, history, user_message)
            ai_key_failures.pop((provider, api_key), None)
            return reply_text
        except Exception as e:
            err = str(e).lower()
            key_idx = keys.index(api_key) + 1
            if _is_quota_error(err):
                ai_key_failures[(provider, api_key)] = {"until": current_time + 3600, "reason": "quota"}
                logger.warning(f"[{provider}] Clé #{key_idx} quota épuisé → rotation")
            elif _is_invalid_key_error(err):
                ai_key_failures[(provider, api_key)] = {"until": current_time + 86400, "reason": "invalid"}
                logger.warning(f"[{provider}] Clé #{key_idx} invalide → rotation")
            else:
                logger.error(f"[{provider}] Clé #{key_idx} erreur: {e}")
    return None


async def ai_reply(user_id: int, user_message: str, bot=None) -> str:
    """Génère une réponse IA avec rotation automatique des clés et fallback inter-fournisseurs."""
    data = load_data()
    ai_config = data.get("ai_config", {})
    active_provider = ai_config.get("provider", "gemini")
    current_time = int(datetime.now().timestamp())
    uid = str(user_id)
    history = conversation_history.get(uid, [])

    # Ordre de tentative : fournisseur actif en premier, puis les autres
    providers_order = [active_provider] + [p for p in AI_PROVIDERS if p != active_provider]

    for provider in providers_order:
        keys = get_keys_list(ai_config, provider)
        if not keys:
            continue

        reply_text = await _try_provider_keys(provider, keys, history, user_message, current_time)
        if reply_text is not None:
            if provider != active_provider:
                logger.info(f"Fallback utilisé: {provider} (fournisseur principal {active_provider} épuisé)")
            history.append({"role": "user", "parts": [{"text": user_message}]})
            history.append({"role": "model", "parts": [{"text": reply_text}]})
            conversation_history[uid] = history[-20:]
            return reply_text

    # Tous les fournisseurs ont échoué — alerter les admins
    if bot:
        active_keys = get_keys_list(ai_config, active_provider)
        asyncio.create_task(_notify_admins_keys_exhausted(bot, active_provider, active_keys, current_time))

    return "L'assistant est temporairement indisponible. Contactez l'administrateur."


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages texte en chat privé"""
    user = update.effective_user
    if not user:
        return

    text = update.message.text
    if not text:
        return

    # 0a. Intercepter le flux de CONNEXION
    if user.id in login_state:
        state = login_state[user.id]
        step = state.get("step")

        if step == "email":
            login_id = text.strip().lower()
            if not login_id:
                await update.message.reply_text("⚠️ Identifiant invalide. Entrez votre nom d'utilisateur ou votre email:")
                return
            db_user = await db_get_user_by_email(login_id)
            if not db_user:
                login_state.pop(user.id, None)
                await update.message.reply_text(
                    "❌ Aucun compte trouvé avec cet identifiant.\n\n"
                    "Tapez /start pour recommencer.",
                    reply_markup=_auth_keyboard(),
                )
                return
            state["email"] = login_id
            state["db_user_id"] = db_user["id"]
            state["step"] = "password"
            await update.message.reply_text(
                f"✅ Email: `{email}`\n\n🔑 Entrez votre **mot de passe**:",
                parse_mode="Markdown",
            )
            return

        elif step == "password":
            password = text.strip()
            db_user = await db_get_user_by_email(state.get("email", ""))
            if not db_user:
                login_state.pop(user.id, None)
                await update.message.reply_text(
                    "❌ Session expirée. Tapez /start pour recommencer.",
                    reply_markup=_auth_keyboard(),
                )
                return
            pw_hash = db_user.get("password_hash") or ""
            try:
                ok = _bcrypt.checkpw(password.encode(), pw_hash.encode())
            except Exception:
                ok = False
            if not ok:
                await update.message.reply_text(
                    "❌ Mot de passe incorrect.\n\nRéessayez ou tapez /start."
                )
                return
            # Connexion OK — lier le telegram_id
            await db_link_telegram_id(db_user["id"], user.id)
            if db_user.get("is_admin"):
                db_admin_telegram_ids.add(user.id)
            login_state.pop(user.id, None)
            first = db_user.get("first_name") or user.first_name or "vous"
            if is_admin(user.id):
                data = load_data()
                panel_text, panel_kb = build_admin_panel(data)
                await update.message.reply_text(
                    f"🎉 **Connexion réussie! Bienvenue, {first}!**",
                    parse_mode="Markdown",
                )
                await update.message.reply_text(panel_text, reply_markup=panel_kb, parse_mode="Markdown")
            else:
                menu_text, menu_kb = _user_main_menu(first)
                await update.message.reply_text(
                    f"🎉 **Connexion réussie! Bienvenue, {first}!**\n\n" + menu_text.split("**\n\n", 1)[-1],
                    reply_markup=menu_kb,
                    parse_mode="Markdown",
                )
            return
        return  # état inconnu

    # 0b. Intercepter le flux d'INSCRIPTION
    if user.id in reg_state:
        state = reg_state[user.id]
        step = state.get("step")

        if step == "first_name":
            fn = text.strip()
            if len(fn) < 2:
                await update.message.reply_text("⚠️ Prénom trop court. Réessayez:")
                return
            state["first_name"] = fn
            state["step"] = "last_name"
            await update.message.reply_text(
                f"✅ Prénom: **{fn}**\n\n📝 **Étape 2/4** — Quel est votre **nom de famille**?",
                parse_mode="Markdown",
            )
            return

        elif step == "last_name":
            ln = text.strip()
            if len(ln) < 2:
                await update.message.reply_text("⚠️ Nom trop court. Réessayez:")
                return
            state["last_name"] = ln
            state["step"] = "email"
            await update.message.reply_text(
                f"✅ Nom: **{ln}**\n\n"
                "📝 **Étape 3/4** — Entrez votre **adresse email**\n"
                "_(ce sera votre identifiant de connexion sur le site de paiement)_",
                parse_mode="Markdown",
            )
            return

        elif step == "email":
            email = text.strip().lower()
            if not _re_mod.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                await update.message.reply_text("⚠️ Email invalide. Entrez un email valide:")
                return
            if await db_email_exists(email):
                await update.message.reply_text(
                    "⚠️ Cet email est déjà utilisé.\n\nEntrez un autre email ou contactez un administrateur."
                )
                return
            state["email"] = email
            state["step"] = "password"
            await update.message.reply_text(
                f"✅ Email: **{email}**\n\n"
                "📝 **Étape 4/4** — Choisissez un **mot de passe** (minimum 6 caractères):",
                parse_mode="Markdown",
            )
            return

        elif step == "password":
            pw = text.strip()
            if len(pw) < 6:
                await update.message.reply_text("⚠️ Mot de passe trop court (minimum 6 caractères). Réessayez:")
                return
            state["password"] = pw
            state["step"] = "confirm"
            await update.message.reply_text(
                "📝 **Confirmation** — Répétez votre mot de passe:", parse_mode="Markdown"
            )
            return

        elif step == "confirm":
            if text.strip() != state.get("password"):
                await update.message.reply_text(
                    "❌ Les mots de passe ne correspondent pas.\n\nEntrez votre mot de passe à nouveau:"
                )
                state["step"] = "password"
                return
            await update.message.reply_text("⏳ Création de votre compte en cours...")
            row, err = await db_register_user(
                user.id,
                state.get("first_name", ""),
                state.get("last_name", ""),
                state.get("email", ""),
                state.get("password", ""),
            )
            reg_state.pop(user.id, None)
            if err:
                if err == "email_exists":
                    msg = "❌ Cet email est déjà enregistré.\n\nTapez /start pour vous connecter."
                else:
                    logger.error(f"Erreur inscription user {user.id}: {err}")
                    msg = "❌ Une erreur est survenue. Contactez un administrateur.\n\nTapez /start pour recommencer."
                await update.message.reply_text(msg, reply_markup=_auth_keyboard())
                return
            # Inscription réussie — le telegram_id est déjà lié (fait dans db_register_user)
            first = state.get("first_name", "")
            if is_admin(user.id):
                data = load_data()
                panel_text, panel_kb = build_admin_panel(data)
                await update.message.reply_text(
                    f"🎉 **Compte créé! Bienvenue, {first}!**\n\n"
                    f"📧 Email: `{state.get('email', '')}`",
                    parse_mode="Markdown",
                )
                await update.message.reply_text(panel_text, reply_markup=panel_kb, parse_mode="Markdown")
            else:
                menu_text, menu_kb = _user_main_menu(first or user.first_name or "vous")
                await update.message.reply_text(
                    f"🎉 **Compte créé avec succès!**\n\n"
                    f"👤 {state.get('first_name', '')} {state.get('last_name', '')}\n"
                    f"📧 Email: `{state.get('email', '')}`\n\n"
                    f"Vous pouvez dès maintenant payer votre abonnement.",
                    parse_mode="Markdown",
                )
                await update.message.reply_text(menu_text, reply_markup=menu_kb, parse_mode="Markdown")
            return
        return  # état inconnu

    # 0b. Intercepter les états admin (configuration interactive)
    if is_admin(user.id) and user.id in admin_state:
        state = admin_state[user.id]
        action = state.get("action")

        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Retour Admin", callback_data="admin_panel")]])

        if action == "await_ai_key":
            provider = state.get("provider")
            api_key = text.strip()
            data = load_data()
            if "ai_config" not in data:
                data["ai_config"] = {}
            if "keys" not in data["ai_config"]:
                data["ai_config"]["keys"] = {}
            existing = get_keys_list(data["ai_config"], provider)
            if api_key not in existing:
                existing.append(api_key)
            data["ai_config"]["keys"][provider] = existing
            data["ai_config"]["provider"] = provider
            save_data(data)
            admin_state.pop(user.id, None)
            prov_info = AI_PROVIDERS.get(provider, {})
            await update.message.reply_text(
                f"✅ **Clé {prov_info.get('name', provider)} ajoutée!**\n\n"
                f"{prov_info.get('emoji', '🤖')} Fournisseur actif: **{prov_info.get('name', provider)}**\n"
                f"🔑 Total clés: **{len(existing)}**\n\n"
                f"L'assistant IA utilisera maintenant **{prov_info.get('name', provider)}** avec rotation automatique.",
                reply_markup=cancel_kb,
                parse_mode="Markdown"
            )
            return

        elif action == "await_add_ai_key":
            provider = state.get("provider")
            api_key = text.strip()
            data = load_data()
            if "ai_config" not in data:
                data["ai_config"] = {}
            if "keys" not in data["ai_config"]:
                data["ai_config"]["keys"] = {}
            existing = get_keys_list(data["ai_config"], provider)
            if api_key in existing:
                admin_state.pop(user.id, None)
                await update.message.reply_text("⚠️ Cette clé est déjà configurée.", reply_markup=cancel_kb)
                return
            existing.append(api_key)
            data["ai_config"]["keys"][provider] = existing
            save_data(data)
            admin_state.pop(user.id, None)
            prov_info = AI_PROVIDERS.get(provider, {})
            await update.message.reply_text(
                f"✅ **Clé #{len(existing)} ajoutée pour {prov_info.get('name', provider)}!**\n\n"
                f"🔑 Total clés configurées: **{len(existing)}**\n\n"
                f"La rotation automatique est active.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"⚙️ Gérer les clés {prov_info.get('name', provider)}", callback_data=f"admin_ai_keys_{provider}")
                ]]),
                parse_mode="Markdown"
            )
            return

        elif action == "await_renew_ai_key":
            provider = state.get("provider")
            idx = state.get("index", 0)
            new_key = text.strip()
            data = load_data()
            if "ai_config" not in data:
                data["ai_config"] = {}
            existing = get_keys_list(data["ai_config"], provider)
            if new_key in existing:
                admin_state.pop(user.id, None)
                await update.message.reply_text("⚠️ Cette clé est déjà dans la liste.", reply_markup=cancel_kb)
                return
            old_key = existing[idx] if 0 <= idx < len(existing) else None
            if old_key:
                ai_key_failures.pop((provider, old_key), None)
                existing[idx] = new_key
            else:
                existing.append(new_key)
            data["ai_config"].setdefault("keys", {})[provider] = existing
            save_data(data)
            admin_state.pop(user.id, None)
            prov_info = AI_PROVIDERS.get(provider, {})
            await update.message.reply_text(
                f"✅ **Clé {idx+1} renouvelée — {prov_info.get('emoji','🤖')} {prov_info.get('name', provider)}!**\n\n"
                f"L'ancienne clé expirée a été remplacée.\n"
                f"🔑 Total clés: **{len(existing)}**",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"⚙️ Gérer les clés {prov_info.get('name', provider)}", callback_data=f"admin_ai_keys_{provider}")
                ]]),
                parse_mode="Markdown"
            )
            return

        elif action == "await_grant_args":
            args = text.strip().split()
            admin_state.pop(user.id, None)
            context.args = args
            await grant_command(update, context)
            return

        elif action == "await_extend_args":
            args = text.strip().split()
            admin_state.pop(user.id, None)
            context.args = args
            await extend_command(update, context)
            return

        elif action == "await_remove_args":
            args = text.strip().split()
            admin_state.pop(user.id, None)
            context.args = args
            await remove_command(update, context)
            return

        elif action == "await_members_args":
            args = text.strip().split()
            admin_state.pop(user.id, None)
            context.args = args
            await members_command(update, context)
            return

        elif action == "await_setdur_args":
            args = text.strip().split()
            admin_state.pop(user.id, None)
            context.args = args
            await setduration_command(update, context)
            return

        elif action == "await_unblock_args":
            args = text.strip().split()
            admin_state.pop(user.id, None)
            context.args = args
            await unblock_command(update, context)
            return

        elif action == "await_scan_args":
            args = text.strip().split()
            admin_state.pop(user.id, None)
            context.args = args
            await scan_command(update, context)
            return

    # 1. Intercepter l'auth Telethon (admin uniquement)
    if is_admin(user.id) and user.id in telethon_manager.auth_state:
        msg, auth_done = await telethon_manager.process_auth_step(user.id, text)
        await update.message.reply_text(msg, parse_mode="Markdown")
        if auth_done:
            session_str = await telethon_manager.get_session_string()
            await save_telethon_session(session_str, context, user.id)
        return

    # 3. L'IA ne répond QUE si l'utilisateur est en mode assistance
    if user.id not in assistance_mode:
        return  # Ignorer silencieusement — pas de réponse hors mode assistance

    data = load_data()
    if not data.get("ai_enabled", True):
        await update.message.reply_text(
            "L'assistant est temporairement désactivé. Contactez un administrateur."
        )
        return

    # Indiquer que le bot est en train d'écrire
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        response = await ai_reply(user.id, text, bot=context.bot)
    except Exception as e:
        logger.error(f"Erreur inattendue ai_reply pour {user.id}: {e}", exc_info=True)
        response = "L'assistant est temporairement indisponible. Contactez l'administrateur."

    # Bouton "Retourner à l'accueil" après chaque réponse
    home_keyboard = [[InlineKeyboardButton("🏠 Retourner à l'accueil", callback_data="home")]]

    try:
        await update.message.reply_text(
            response,
            reply_markup=InlineKeyboardMarkup(home_keyboard),
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text(
            response,
            reply_markup=InlineKeyboardMarkup(home_keyboard),
            parse_mode=None
        )

    logger.info(f"IA [assistance] répondu à {user.id}: {text[:50]}...")


# ═══════════════════════════════════════════════════════════════
# ÉVÉNEMENTS : BOT AJOUTÉ/RETIRÉ D'UN CANAL
# ═══════════════════════════════════════════════════════════════

async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Déclenché quand le statut du bot change dans un canal/groupe"""
    result = update.my_chat_member
    chat = result.chat
    new_status = result.new_chat_member.status

    if new_status in (ChatMember.ADMINISTRATOR, ChatMember.MEMBER):
        data = load_data()
        cid = str(chat.id)
        ch = get_channel_data(data, chat.id)
        ch["name"] = chat.title or f"Canal {cid}"
        save_data(data)

        logger.info(f"✅ Bot ajouté au canal: {chat.title} ({chat.id})")

        for admin_id in ADMINS:
            try:
                keyboard = [
                    [InlineKeyboardButton("⏱ 30min", callback_data=f"setdef_{cid}_1800"),
                     InlineKeyboardButton("⏱ 1h",    callback_data=f"setdef_{cid}_3600"),
                     InlineKeyboardButton("⏱ 5h",    callback_data=f"setdef_{cid}_18000")],
                    [InlineKeyboardButton("⏱ 24h",   callback_data=f"setdef_{cid}_86400"),
                     InlineKeyboardButton("⏱ 48h",   callback_data=f"setdef_{cid}_172800")],
                    [InlineKeyboardButton("📅 7 jours",  callback_data=f"setdef_{cid}_604800"),
                     InlineKeyboardButton("📅 1 mois",   callback_data=f"setdef_{cid}_2592000")],
                    [InlineKeyboardButton("🏠 Panneau Admin", callback_data="admin_panel")],
                ]
                await context.bot.send_message(
                    admin_id,
                    f"✅ **Nouveau canal détecté!**\n\n"
                    f"📢 **Canal:** {chat.title}\n"
                    f"🆔 **ID:** `{chat.id}`\n\n"
                    f"Le canal a été ajouté automatiquement à la liste.\n"
                    f"⚙️ Choisissez la durée d'accès **par défaut** pour ce canal:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Erreur notif admin {admin_id}: {e}")

        asyncio.create_task(scan_channel_members(context, chat.id, chat.title or cid))

    elif new_status in (ChatMember.LEFT, ChatMember.BANNED):
        data = load_data()
        cid = str(chat.id)
        if cid in data["channels"]:
            del data["channels"][cid]
            save_data(data)

        for admin_id in ADMINS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"⚠️ **Bot retiré du canal**\n\n"
                    f"📢 **Canal:** {chat.title or cid}\n"
                    f"🆔 **ID:** `{chat.id}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Erreur notif admin {admin_id}: {e}")


async def scan_channel_members(context, channel_id, channel_name):
    """Scanne les membres visibles d'un canal et envoie une fiche par membre à l'admin"""
    await asyncio.sleep(3)
    try:
        bot = context.bot
        admins = await bot.get_chat_administrators(channel_id)
        data = load_data()
        cid = str(channel_id)
        ch = get_channel_data(data, channel_id)
        existing_members = set(ch.get("members", {}).keys())
        default_hours = ch.get("default_duration_seconds", 86400)

        # Essayer Telethon en priorité (accès à tous les membres)
        telethon_users = []
        if TELETHON_API_ID and await telethon_manager.is_connected():
            telethon_users = await telethon_manager.get_all_channel_members(channel_id)
            logger.info(f"Telethon: {len(telethon_users)} membres trouvés dans {channel_name}")

        bot_info = await bot.get_me()

        if telethon_users:
            # Utiliser les données Telethon (tous les membres)
            members_found = [
                u for u in telethon_users
                if str(u.id) not in existing_members and u.id != bot_info.id
            ]
            source = "🔵 **Via Telethon** (liste complète des membres)"
        else:
            # Fallback: uniquement les admins via Bot API
            members_found = [
                a.user for a in admins
                if not a.user.is_bot
                and str(a.user.id) not in existing_members
                and a.user.id != bot_info.id
            ]
            source = "🟡 **Via Bot API** (administrateurs uniquement — connectez Telethon avec /connect pour voir tous les membres)"

        # Résumé initial
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🔍 **Scan du canal: {channel_name}**\n\n"
                    f"👥 **{len(members_found)} membre(s) détecté(s)**\n"
                    f"{source}\n\n"
                    + ("Fiches en cours d'envoi..." if members_found else "Aucun nouveau membre à gérer."),
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        # Envoyer une fiche individuelle par membre avec boutons de durée
        for user in members_found:
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            username = f"@{user.username}" if user.username else "N/A"
            uid = str(user.id)

            for admin_id in ADMINS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"👤 **Membre détecté**\n\n"
                        f"📢 **Canal:** {channel_name}\n"
                        f"👤 **Nom:** {full_name}\n"
                        f"📛 **Username:** {username}\n"
                        f"🆔 **ID:** `{user.id}`\n\n"
                        f"⏱ Quelle durée d'accès lui accorder?",
                        reply_markup=InlineKeyboardMarkup(member_keyboard(cid, uid, default_hours)),
                        parse_mode="Markdown"
                    )
                    await asyncio.sleep(0.5)  # Éviter le flood
                except Exception as e:
                    logger.error(f"Erreur fiche membre {uid}: {e}")

    except Exception as e:
        logger.error(f"Erreur scan_channel_members: {e}")


# ═══════════════════════════════════════════════════════════════
# ÉVÉNEMENTS : NOUVEAU MEMBRE DANS UN CANAL
# ═══════════════════════════════════════════════════════════════

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Déclenché quand un membre rejoint/quitte un canal géré"""
    result = update.chat_member
    chat = result.chat
    new_member = result.new_chat_member
    user = new_member.user

    if user.is_bot:
        return

    cid = str(chat.id)
    data = load_data()

    if cid not in data.get("channels", {}):
        return

    if new_member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR):
        uid = str(user.id)
        ch = get_channel_data(data, chat.id)

        # Vérifier si l'utilisateur est bloqué (accès expiré précédemment)
        if uid in ch.get("blocked", {}):
            try:
                await context.bot.ban_chat_member(int(cid), int(uid))
                logger.info(f"Utilisateur bloqué {uid} a tenté de rejoindre {cid} — rejeté")
            except Exception as e:
                logger.error(f"Erreur ban utilisateur bloqué {uid}: {e}")
            try:
                await context.bot.send_message(
                    int(uid),
                    f"🚫 **Accès refusé — {ch['name']}**\n\n"
                    f"Votre accès à ce canal a expiré.\n\n"
                    f"💳 Pour renouveler votre abonnement et accéder à nouveau, "
                    f"contactez notre assistant en appuyant sur /start",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = f"@{user.username}" if user.username else "N/A"

        # ── Message d'accueil envoyé à TOUS les membres qui rejoignent ──
        mode_emploi = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 **MODE D'EMPLOI – BOT DE PRÉDICTION BACCARAT**\n\n"
            f"🎯 **Principe de fonctionnement**\n"
            f"Le bot prédit les cartes suivantes :\n"
            f"♠️ (Pique), ♦️ (Carreau), ♣️ (Trèfle), ❤️ (Cœur).\n\n"
            f"🕹️ **Comment utiliser les prédictions**\n"
            f"▪️ Le bot affiche un numéro de manche en tête.\n"
            f"▪️ Allez sur votre plateforme de jeu (bookmaker), section Baccarat, et trouvez ce numéro.\n"
            f"▪️ Sélectionnez : 👉 « Le joueur reçoit une carte enseigne »\n"
            f"▪️ Choisissez la carte indiquée par le bot.\n\n"
            f"🔁 **En cas d'échec**\n"
            f"👉 Passez immédiatement au numéro suivant (affiché en bas des prédictions) et rejouez.\n\n"
            f"⚠️ **Recommandations stratégiques**\n"
            f"▪️ Attendez une première perte du bot avant de miser (recommandé).\n"
            f"▪️ Les plus confiants peuvent jouer dès la première prédiction.\n"
            f"▪️ Le bot émet 4 prédictions consécutives, puis s'arrête (nouvelle série).\n\n"
            f"💰 **Plan de mise (progression recommandée)**\n"
            f"▪️ 500 FCFA → 1 200 FCFA → 2 500 FCFA\n"
            f"▪️ 5 500 FCFA → 12 000 FCFA → 25 000 FCFA\n"
            f"👉 En cas de gain : revenez à 500 FCFA.\n\n"
            f"🧠 **Conseils essentiels**\n"
            f"▪️ Respectez rigoureusement le plan de mise.\n"
            f"▪️ Max 4 prédictions par jour.\n"
            f"▪️ Ne dépassez pas les 6 niveaux de mise.\n"
            f"▪️ Évitez toute décision impulsive.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💳 **MODE DE PAIEMENT & RENOUVELLEMENT**\n\n"
            f"1️⃣ Tapez /start dans ce bot pour ouvrir le menu principal.\n"
            f"2️⃣ Appuyez sur 💳 **Payer mon abonnement** (ou tapez /payer).\n"
            f"3️⃣ Envoyez une capture d'écran de votre paiement (Wave, Orange Money, PayPal, BNB, etc.).\n"
            f"4️⃣ Le bot analyse automatiquement le montant et calcule votre durée d'accès.\n"
            f"5️⃣ Choisissez le canal souhaité — votre accès est activé immédiatement.\n\n"
            f"🎁 **Demander un accès bonus (gratuit)**\n"
            f"▪️ Tapez /bonus dans ce bot et suivez les instructions.\n"
            f"▪️ La demande est soumise à l'approbation de l'administrateur.\n\n"
            f"💬 **Besoin d'aide ?**\n"
            f"Appuyez sur 💬 **Assistance** dans le menu /start pour discuter avec notre assistante.\n"
            f"❓ Si vous ne comprenez pas quelque chose, écrivez directement à @Kouam2025_bot — elle vous guidera étape par étape.\n\n"
            f"💳 Pour renouveler ou toute question : @Kouam2025_bot"
        )

        # Vérifier si c'est un membre payant (déjà enregistré via paiement)
        if uid in ch.get("members", {}):
            member_info = ch["members"][uid]
            expires_at = member_info.get("expires_at", 0)
            dur_sec = member_info.get("duration_seconds", 0)
            dur_label = format_duration_label(dur_sec)
            expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M') if expires_at else "?"

            try:
                await context.bot.send_message(
                    int(uid),
                    f"🎉 **Bienvenue dans {ch['name']}!**\n\n"
                    f"✅ Votre accès est actif.\n"
                    f"⏱ Durée: **{dur_label}**\n"
                    f"📅 Expire le: **{expire_str}**\n\n"
                    f"⚠️ Votre accès sera automatiquement retiré à expiration.\n\n"
                    + mode_emploi,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Erreur envoi message d'accueil à {uid}: {e}")

            # Notifier l'admin avec bouton Confirmer pour révoquer le lien
            key = (cid, uid)
            invite_link = pending_invites.get(key, "")

            confirm_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Confirmer l'intégration", callback_data=f"cjoin_{uid}_{cid}")
            ]])
            for admin_id in ADMINS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"✅ **Membre intégré: {ch['name']}**\n\n"
                        f"👤 **Nom:** {full_name}\n"
                        f"📛 **Username:** {username}\n"
                        f"🆔 **ID:** `{user.id}`\n"
                        f"⏱ **Durée:** {dur_label}\n"
                        f"📅 **Expire:** {expire_str}\n\n"
                        f"Cliquez sur **Confirmer** pour révoquer le lien d'invitation.",
                        reply_markup=confirm_kb,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Erreur notif admin {admin_id}: {e}")
        else:
            # Membre inconnu — envoyer le message d'accueil puis notifier l'admin
            try:
                await context.bot.send_message(
                    int(uid),
                    f"🎉 **Bienvenue dans {ch['name']}!**\n\n"
                    f"✅ Vous avez bien rejoint le canal.\n\n"
                    + mode_emploi,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Erreur envoi message d'accueil à {uid}: {e}")

            default_hours = ch.get("default_duration_seconds", 86400)
            for admin_id in ADMINS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"🆕 **Nouveau membre dans {ch['name']}**\n\n"
                        f"👤 **Nom:** {full_name}\n"
                        f"📛 **Username:** {username}\n"
                        f"🆔 **ID:** `{user.id}`\n\n"
                        f"⏱ Combien de temps lui accorder?",
                        reply_markup=InlineKeyboardMarkup(member_keyboard(cid, uid, default_hours)),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Erreur notif admin {admin_id}: {e}")

    elif new_member.status in (ChatMember.LEFT, ChatMember.BANNED):
        uid = str(user.id)
        data = load_data()
        if cid in data.get("channels", {}) and uid in data["channels"][cid].get("members", {}):
            del data["channels"][cid]["members"][uid]
            save_data(data)


# ═══════════════════════════════════════════════════════════════
# CALLBACKS (Boutons)
# ═══════════════════════════════════════════════════════════════

def build_admin_panel(data):
    """Construit le panneau admin avec tous les boutons"""
    ai_config = data.get("ai_config", {})
    provider = ai_config.get("provider", "gemini")
    prov_info = AI_PROVIDERS.get(provider, AI_PROVIDERS["gemini"])
    ai_enabled = data.get("ai_enabled", True)
    text = (
        "👋 **Panneau Administrateur**\n\n"
        f"🤖 IA: {prov_info['emoji']} **{prov_info['name']}** | "
        f"{'✅ Activée' if ai_enabled else '⭕ Désactivée'}\n\n"
        "Sélectionnez une action:"
    )
    keyboard = [
        [InlineKeyboardButton("📋 Canaux", callback_data="admin_channels"),
         InlineKeyboardButton("👥 Membres", callback_data="admin_members_ask")],
        [InlineKeyboardButton("✅ Accorder accès", callback_data="admin_grant_ask"),
         InlineKeyboardButton("⏫ Prolonger", callback_data="admin_extend_ask")],
        [InlineKeyboardButton("❌ Retirer membre", callback_data="admin_remove_ask"),
         InlineKeyboardButton("🔓 Débloquer", callback_data="admin_unblock_ask")],
        [InlineKeyboardButton("⏱ Durée défaut", callback_data="admin_setdur_ask"),
         InlineKeyboardButton("🔍 Scanner canal", callback_data="admin_scan_ask")],
        [InlineKeyboardButton("🤖 Activer IA", callback_data="admin_ai_on"),
         InlineKeyboardButton("⭕ Désactiver IA", callback_data="admin_ai_off"),
         InlineKeyboardButton("⚙️ Config IA", callback_data="admin_ai_config")],
        [InlineKeyboardButton("🔌 Connecter Telethon", callback_data="admin_telethon_connect"),
         InlineKeyboardButton("📡 Statut Telethon", callback_data="admin_telethon_status")],
        [InlineKeyboardButton("💳 Payer", callback_data="pay_start"),
         InlineKeyboardButton("🎁 Bonus", callback_data="bonus_start"),
         InlineKeyboardButton("💬 Assistance", callback_data="assist_start")],
        [InlineKeyboardButton("📖 Aide", callback_data="admin_help")],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def build_ai_config_panel(data):
    """Construit le panneau de configuration IA"""
    ai_config = data.get("ai_config", {})
    current_provider = ai_config.get("provider", "gemini")
    lines = ["⚙️ **Configuration de l'Assistant IA**\n"]
    for pid, pinfo in AI_PROVIDERS.items():
        keys = get_keys_list(ai_config, pid)
        n = len(keys)
        if pid == current_provider:
            status = f"✅ **Actif** — {n} clé(s)"
        elif n > 0:
            status = f"🔑 {n} clé(s)"
        else:
            status = "➕ Aucune clé"
        lines.append(f"{pinfo['emoji']} **{pinfo['name']}** — {status}")
    lines.append("\n_Appuyez sur un fournisseur pour gérer ses clés ou l'activer:_")
    keyboard = [
        [InlineKeyboardButton("🔵 Gemini", callback_data="admin_ai_keys_gemini"),
         InlineKeyboardButton("🟢 OpenAI", callback_data="admin_ai_keys_openai")],
        [InlineKeyboardButton("🟠 Groq", callback_data="admin_ai_keys_groq"),
         InlineKeyboardButton("🔷 DeepSeek", callback_data="admin_ai_keys_deepseek")],
        [InlineKeyboardButton("🔍 Tester toutes les clés", callback_data="admin_ai_testall")],
        [InlineKeyboardButton("← Retour", callback_data="admin_panel")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def build_ai_keys_panel(data: dict, provider: str) -> tuple:
    """Construit le panneau de gestion des clés pour un fournisseur."""
    ai_config = data.get("ai_config", {})
    current_provider = ai_config.get("provider", "gemini")
    pinfo = AI_PROVIDERS[provider]
    keys = get_keys_list(ai_config, provider)
    current_time = int(datetime.now().timestamp())

    lines = [f"{pinfo['emoji']} **Clés {pinfo['name']}**\n"]
    if not keys:
        lines.append("_Aucune clé configurée._")
    else:
        for i, k in enumerate(keys):
            short = k[:8] + "..." + k[-4:] if len(k) > 14 else k
            failure = ai_key_failures.get((provider, k))
            if failure and failure["until"] > current_time:
                if failure["reason"] == "quota":
                    status = "⏳ Quota épuisé"
                else:
                    status = "❌ Expirée / Invalide"
            else:
                status = "✅ Active"
            lines.append(f"**Clé {i+1}:** `{short}` — {status}")

    is_active = current_provider == provider
    keyboard = []
    for i, k in enumerate(keys):
        failure = ai_key_failures.get((provider, k))
        is_expired = failure and failure["until"] > current_time
        if is_expired:
            # Clé expirée : proposer Renouveler et Supprimer
            keyboard.append([
                InlineKeyboardButton(f"🔄 Renouveler clé {i+1}", callback_data=f"admin_ai_renew_{provider}_{i}"),
                InlineKeyboardButton(f"🗑", callback_data=f"admin_ai_rmkey_{provider}_{i}"),
            ])
        else:
            # Clé active : juste supprimer
            keyboard.append([
                InlineKeyboardButton(f"🗑 Supprimer clé {i+1}", callback_data=f"admin_ai_rmkey_{provider}_{i}")
            ])
    keyboard.append([InlineKeyboardButton("➕ Ajouter une clé", callback_data=f"admin_ai_addkey_{provider}")])
    if not is_active and keys:
        keyboard.append([InlineKeyboardButton(f"✅ Activer {pinfo['name']}", callback_data=f"admin_ai_activate_{provider}")])
    if keys:
        keyboard.append([InlineKeyboardButton("🔍 Tester les clés", callback_data=f"admin_ai_test_{provider}")])
    keyboard.append([InlineKeyboardButton("← Retour Config IA", callback_data="admin_ai_config")])

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[0]

    # ── INSCRIPTION ────────────────────────────────────────────
    if query.data == "inscription":
        uid = update.effective_user.id
        reg_state[uid] = {"step": "first_name"}
        login_state.pop(uid, None)
        await query.edit_message_text(
            "📝 **Inscription — Étape 1/4**\n\nQuel est votre **prénom**?",
            parse_mode="Markdown",
        )
        return

    # ── CONNEXION ──────────────────────────────────────────────
    if query.data == "connexion":
        uid = update.effective_user.id
        login_state[uid] = {"step": "email"}
        reg_state.pop(uid, None)
        await query.edit_message_text(
            "🔐 **Connexion**\n\nEntrez votre **identifiant** (nom d'utilisateur ou email):",
            parse_mode="Markdown",
        )
        return

    # ── GARDE D'AUTHENTIFICATION ───────────────────────────────
    # Tous les autres callbacks nécessitent d'être connecté
    _db_user = await db_get_user_by_telegram_id(update.effective_user.id)
    if not _db_user:
        try:
            await query.edit_message_text(
                "🔒 **Accès refusé**\n\n"
                "Vous devez vous connecter ou créer un compte pour continuer.",
                reply_markup=_auth_keyboard(),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return
    # ── FIN GARDE ──────────────────────────────────────────────

    if query.data == "assist_start":
        user = update.effective_user
        first_name = user.first_name or "vous"
        # Activer le mode assistance
        assistance_mode[user.id] = True
        # Réinitialiser l'historique pour une nouvelle session
        conversation_history.pop(user.id, None)

        home_keyboard = [[InlineKeyboardButton("🏠 Retourner à l'accueil", callback_data="home")]]
        await query.edit_message_text(
            f"👨‍💻 **Bonjour {first_name}!**\n\n"
            f"Je suis l'assistante du développeur **Sossou Kouamé Appolinaire**.\n"
            f"Je suis là pour vous orienter pour le paiement et répondre à toutes vos questions sur **Baccara** et notre bot. 😊\n\n"
            f"🌍 *In which language would you like to chat?*\n"
            f"🌍 *¿En qué idioma deseas que hablemos?*\n"
            f"🌍 *بأي لغة تريد أن نتحدث؟*\n"
            f"🌍 **Dans quelle langue souhaitez-vous dialoguer ?**",
            reply_markup=InlineKeyboardMarkup(home_keyboard),
            parse_mode="Markdown"
        )
        return

    if query.data == "home":
        user = update.effective_user
        assistance_mode.pop(user.id, None)
        conversation_history.pop(user.id, None)
        admin_state.pop(user.id, None)
        await query.edit_message_text("✅ Session terminée.")
        if is_admin(user.id):
            data = load_data()
            panel_text, panel_kb = build_admin_panel(data)
            await context.bot.send_message(user.id, panel_text, reply_markup=panel_kb, parse_mode="Markdown")
        else:
            first = _db_user.get("first_name") or user.first_name or "vous"
            menu_text, menu_kb = _user_main_menu(first)
            await context.bot.send_message(user.id, menu_text, reply_markup=menu_kb, parse_mode="Markdown")
        return

    # ── Callbacks accessibles à tous les utilisateurs ─────────────────
    if query.data == "my_status":
        user = update.effective_user
        uid_str = str(user.id)
        data = load_data()
        channels = data.get("channels", {})
        current_time = int(datetime.now().timestamp())
        found = False
        lines = [f"📊 **Statut de vos abonnements**\n👤 {user.first_name}\n"]

        for cid, ch in channels.items():
            members = ch.get("members", {})
            if uid_str in members:
                m = members[uid_str]
                expires_at = m.get("expires_at", 0)
                time_left = expires_at - current_time
                dur_total = format_duration_label(m.get("duration_seconds", 0))
                expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M') if expires_at else "?"
                if time_left > 0:
                    remaining = format_time_remaining(time_left)
                    lines.append(
                        f"📢 **{ch.get('name', cid)}**\n"
                        f"   ✅ Accès **ACTIF**\n"
                        f"   ⏳ Temps restant: **{remaining}**\n"
                        f"   📅 Expire le: {expire_str}\n"
                        f"   ⏱ Durée totale: {dur_total}\n"
                    )
                else:
                    lines.append(
                        f"📢 **{ch.get('name', cid)}**\n"
                        f"   🔴 Accès **EXPIRÉ** depuis le {expire_str}\n"
                    )
                found = True

        if not found:
            lines.append("ℹ️ Vous n'avez aucun abonnement enregistré.\n\nAppuyez sur 💳 *Payer mon abonnement* pour souscrire.")

        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu principal", callback_data="back_main")]])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb)
        return

    if query.data == "back_main":
        user = update.effective_user
        admin_state.pop(user.id, None)
        if is_admin(user.id):
            data = load_data()
            panel_text, panel_kb = build_admin_panel(data)
            await query.edit_message_text(panel_text, reply_markup=panel_kb, parse_mode="Markdown")
        else:
            first = _db_user.get("first_name") or user.first_name or "vous"
            menu_text, menu_kb = _user_main_menu(first)
            await query.edit_message_text(menu_text, reply_markup=menu_kb, parse_mode="Markdown")
        return

    if query.data == "pay_start":
        user = update.effective_user
        db_user = await db_get_user_by_telegram_id(user.id)
        if not db_user:
            await query.edit_message_text(
                "❌ Vous devez d'abord créer un compte.\n\nTapez /start pour vous inscrire.",
                parse_mode="Markdown",
            )
            return
        email = db_user.get("email") or "votre email"
        pay_keyboard = [
            [InlineKeyboardButton(
                "🌐 Accéder au site de paiement",
                url="https://paiement-s-curis.onrender.com",
            )],
            [InlineKeyboardButton(
                "✅ J'ai payé — Vérifier mon accès",
                callback_data="check_payment",
            )],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "💳 **Paiement d'abonnement**\n\n"
            "Pour activer votre accès:\n\n"
            "1️⃣ Cliquez sur **\"Accéder au site de paiement\"**\n"
            f"2️⃣ Connectez-vous avec:\n"
            f"   📧 Email: `{email}`\n"
            f"   🔑 Votre mot de passe\n"
            "3️⃣ Effectuez votre paiement\n"
            "4️⃣ Revenez ici et cliquez **\"J'ai payé\"**\n\n"
            "_Votre accès sera activé automatiquement après vérification._",
            reply_markup=InlineKeyboardMarkup(pay_keyboard),
            parse_mode="Markdown",
        )
        return

    if query.data == "check_payment":
        user = update.effective_user
        sub = await db_check_subscription(user.id)
        if not sub:
            pay_keyboard = [
                [InlineKeyboardButton(
                    "🌐 Accéder au site de paiement",
                    url="https://paiement-s-curis.onrender.com",
                )],
                [InlineKeyboardButton("🔄 Vérifier à nouveau", callback_data="check_payment")],
                [InlineKeyboardButton("🏠 Menu principal", callback_data="back_main")],
            ]
            await query.edit_message_text(
                "⏳ **Paiement non encore détecté**\n\n"
                "Votre paiement n'est pas encore enregistré dans notre système.\n\n"
                "• Assurez-vous d'avoir complété le paiement sur le site\n"
                "• Attendez quelques secondes puis cliquez **Vérifier à nouveau**\n\n"
                "_Si le problème persiste, contactez un administrateur._",
                reply_markup=InlineKeyboardMarkup(pay_keyboard),
                parse_mode="Markdown",
            )
            return
        # Paiement confirmé — accorder l'accès
        expires_at = sub["expires_at"]
        duration_min = sub.get("duration_minutes", 0)
        expire_str = expires_at.strftime("%d/%m/%Y à %H:%M")
        expires_ts = int(expires_at.timestamp())
        if duration_min >= 43200:
            dur_label = f"{duration_min // 43200} mois"
        elif duration_min >= 1440:
            dur_label = f"{duration_min // 1440} jour(s)"
        elif duration_min > 0:
            dur_label = f"{duration_min} minute(s)"
        else:
            dur_label = "abonnement actif"

        data = load_data()
        channels = data.get("channels", {})
        uid_str = str(user.id)
        current_time = int(datetime.now().timestamp())

        for cid, ch in channels.items():
            existing = ch.get("members", {}).get(uid_str, {})
            if existing.get("expires_at", 0) >= expires_ts:
                continue
            duration_seconds = max(expires_ts - current_time, 0)
            ch.setdefault("members", {})[uid_str] = {
                "expires_at": expires_ts,
                "granted_at": current_time,
                "duration_seconds": duration_seconds,
            }
            ch.setdefault("blocked", {}).pop(uid_str, None)
            try:
                await context.bot.unban_chat_member(int(cid), user.id, only_if_banned=True)
            except Exception:
                pass
            try:
                invite_obj = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
                invite_link = invite_obj.invite_link
                pending_invites[(cid, uid_str)] = invite_link
                await context.bot.send_message(
                    user.id,
                    f"🎉 **Accès activé — {ch.get('name', cid)}**\n\n"
                    f"👇 Rejoignez le canal:\n{invite_link}\n\n"
                    "⚠️ Lien à usage unique — ne le partagez pas.",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"Lien invite canal {cid}: {e}")

        save_data(data)
        first_name = sub.get("first_name") or user.first_name or "utilisateur"
        last_name = sub.get("last_name") or user.last_name or ""
        await query.edit_message_text(
            "🎉 **Paiement confirmé!**\n\n"
            f"Sossou Kouamé vous remercie pour votre confiance, "
            f"vous avez payé un abonnement de **{dur_label}** "
            f"qui expire le **{expire_str}**.\n\n"
            "✅ Vos accès aux canaux ont été activés.",
            parse_mode="Markdown",
        )
        return

    if query.data == "bonus_start":
        user = update.effective_user
        data = load_data()
        channels = data.get("channels", {})
        if not channels:
            await query.edit_message_text("ℹ️ Aucun canal disponible.")
            return
        keyboard = []
        for cid, ch in channels.items():
            keyboard.append([InlineKeyboardButton(f"📢 {ch.get('name', cid)}", callback_data=f"bch_{user.id}_{cid}")])
        keyboard.append([InlineKeyboardButton("❌ Annuler", callback_data="home")])
        await query.edit_message_text(
            "🎁 **Demande de bonus**\n\nPour quel canal souhaitez-vous demander un accès gratuit?\n\n"
            "_La demande sera envoyée à l'administrateur pour approbation._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    if action == "bch":
        requester_uid = int(parts[1])
        cid = "_".join(parts[2:])
        if update.effective_user.id != requester_uid:
            await query.answer("Ce bouton ne vous est pas destiné.", show_alert=True)
            return
        data = load_data()
        if cid not in data.get("channels", {}):
            await query.edit_message_text("❌ Canal introuvable.")
            return
        ch_name = data["channels"][cid].get("name", cid)
        user = update.effective_user
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username_str = f"@{user.username}" if user.username else "N/A"

        bonus_state[requester_uid] = {"channel_id": cid, "channel_name": ch_name, "user_name": full_name}

        await query.edit_message_text(
            f"⏳ **Demande envoyée!**\n\n"
            f"📢 Canal demandé: **{ch_name}**\n\n"
            f"Votre demande a été transmise à l'administrateur.\n"
            f"Vous serez notifié dès qu'elle sera traitée.",
            parse_mode="Markdown"
        )

        # Notifier les admins avec boutons d'approbation
        approve_keyboard = [
            [
                InlineKeyboardButton("✅ 30min", callback_data=f"bapprove_{requester_uid}_{cid}_1800"),
                InlineKeyboardButton("✅ 1h",    callback_data=f"bapprove_{requester_uid}_{cid}_3600"),
                InlineKeyboardButton("✅ 5h",    callback_data=f"bapprove_{requester_uid}_{cid}_18000"),
            ],
            [
                InlineKeyboardButton("✅ 24h",   callback_data=f"bapprove_{requester_uid}_{cid}_86400"),
                InlineKeyboardButton("✅ 48h",   callback_data=f"bapprove_{requester_uid}_{cid}_172800"),
            ],
            [
                InlineKeyboardButton("✅ 7 jours", callback_data=f"bapprove_{requester_uid}_{cid}_604800"),
                InlineKeyboardButton("✅ 1 mois",  callback_data=f"bapprove_{requester_uid}_{cid}_2592000"),
            ],
            [InlineKeyboardButton("❌ Refuser", callback_data=f"bdeny_{requester_uid}_{cid}")],
        ]

        for admin_id in ADMINS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"🎁 **Demande de bonus reçue!**\n\n"
                    f"👤 Utilisateur: **{full_name}** ({username_str})\n"
                    f"🆔 ID: `{requester_uid}`\n"
                    f"📢 Canal: **{ch_name}**\n\n"
                    f"Choisissez la durée d'accès à accorder:",
                    reply_markup=InlineKeyboardMarkup(approve_keyboard),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Erreur envoi notif bonus à admin {admin_id}: {e}")
        return

    if action == "cjoin":
        # cjoin_{uid}_{cid} — Admin confirme l'intégration et révoque le lien d'invitation
        if not is_admin(update.effective_user.id):
            await query.answer("Réservé à l'administrateur.", show_alert=True)
            return
        uid = parts[1]
        cid = "_".join(parts[2:])
        key = (cid, uid)
        invite_link = pending_invites.pop(key, None)
        revoked = False
        if invite_link:
            try:
                await context.bot.revoke_chat_invite_link(int(cid), invite_link)
                revoked = True
            except Exception as e:
                logger.warning(f"Impossible de révoquer le lien {invite_link}: {e}")
        data = load_data()
        ch_name = data.get("channels", {}).get(cid, {}).get("name", cid)
        admin_name = update.effective_user.first_name or "Admin"
        status_line = "🔒 Lien révoqué." if revoked else "⚠️ Lien déjà expiré ou introuvable."
        await query.edit_message_text(
            f"✅ **Intégration confirmée par {admin_name}**\n\n"
            f"📢 Canal: **{ch_name}**\n"
            f"🆔 Utilisateur: `{uid}`\n"
            f"{status_line}",
            parse_mode="Markdown"
        )
        return

    if action == "bapprove":
        if not is_admin(update.effective_user.id):
            await query.answer("Réservé à l'administrateur.", show_alert=True)
            return
        requester_uid = int(parts[1])
        cid = parts[2]
        duration_seconds = int(parts[3])
        data = load_data()
        if cid not in data.get("channels", {}):
            await query.edit_message_text("❌ Canal introuvable.")
            return
        ch = data["channels"][cid]
        current_time = int(datetime.now().timestamp())
        expires_at = current_time + duration_seconds
        ch.setdefault("members", {})[str(requester_uid)] = {
            "expires_at": expires_at, "granted_at": current_time, "duration_seconds": duration_seconds
        }
        ch.setdefault("blocked", {}).pop(str(requester_uid), None)
        save_data(data)
        try:
            await context.bot.unban_chat_member(int(cid), requester_uid, only_if_banned=True)
        except Exception:
            pass
        bonus_state.pop(requester_uid, None)
        dur_label = format_duration_label(duration_seconds)
        expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M')
        # Générer un lien d'invitation unique pour le bonus
        bonus_invite_link = None
        try:
            invite_obj = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
            bonus_invite_link = invite_obj.invite_link
            pending_invites[(cid, str(requester_uid))] = bonus_invite_link
        except Exception as e:
            logger.warning(f"Impossible de créer le lien bonus pour {cid}: {e}")

        try:
            if bonus_invite_link:
                await context.bot.send_message(
                    requester_uid,
                    f"🎉 **Accès bonus approuvé!**\n\n"
                    f"📢 Canal: **{ch['name']}**\n"
                    f"⏱ Durée: **{dur_label}**\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"👇 **Cliquez sur ce lien pour rejoindre le canal:**\n"
                    f"{bonus_invite_link}\n\n"
                    f"⚠️ Ce lien est à usage unique — ne le partagez pas.\n"
                    f"⚠️ Votre accès sera automatiquement retiré à expiration.",
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    requester_uid,
                    f"🎉 **Accès bonus approuvé!**\n\n"
                    f"📢 Canal: **{ch['name']}**\n"
                    f"⏱ Durée: **{dur_label}**\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"✅ Vous pouvez maintenant rejoindre le canal.\n"
                    f"⚠️ Votre accès sera automatiquement retiré à expiration.",
                    parse_mode="Markdown"
                )
        except Exception:
            pass
        admin_name = update.effective_user.first_name or "Admin"
        await query.edit_message_text(
            f"✅ **Bonus accordé par {admin_name}**\n\n"
            f"🆔 Utilisateur: `{requester_uid}`\n"
            f"📢 Canal: **{ch['name']}**\n"
            f"⏱ Durée: **{dur_label}**\n"
            f"📅 Expire le: {expire_str}",
            parse_mode="Markdown"
        )
        return

    if action == "bdeny":
        if not is_admin(update.effective_user.id):
            await query.answer("Réservé à l'administrateur.", show_alert=True)
            return
        requester_uid = int(parts[1])
        cid = parts[2]
        bonus_state.pop(requester_uid, None)
        data = load_data()
        ch_name = data.get("channels", {}).get(cid, {}).get("name", cid)
        try:
            await context.bot.send_message(
                requester_uid,
                f"❌ **Demande de bonus refusée**\n\n"
                f"📢 Canal: **{ch_name}**\n\n"
                f"Votre demande n'a pas été approuvée.\n"
                f"Pour accéder au canal, payez votre abonnement via /start → 💳 Payer.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.edit_message_text(
            f"❌ Demande de `{requester_uid}` refusée pour **{ch_name}**.",
            parse_mode="Markdown",
        )
        return

    # ── Toutes les actions suivantes sont réservées aux admins ─────────
    if not is_admin(update.effective_user.id):
        user = update.effective_user
        user_keyboard = [
            [InlineKeyboardButton("💳 Payer mon abonnement", callback_data="pay_start")],
            [InlineKeyboardButton("🎁 Demander un bonus", callback_data="bonus_start")],
            [InlineKeyboardButton("💬 Assistance", callback_data="assist_start")]
        ]
        try:
            await query.edit_message_text(
                f"👋 Bonjour **{user.first_name or 'vous'}**!\n\nQue souhaitez-vous faire?",
                reply_markup=InlineKeyboardMarkup(user_keyboard),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # ── Panneau Admin ──────────────────────────────────────────────
    if query.data == "admin_panel":
        data = load_data()
        text, kb = build_admin_panel(data)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    if query.data == "admin_channels":
        data = load_data()
        channels = data.get("channels", {})
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Retour", callback_data="admin_panel")]])
        if not channels:
            await query.edit_message_text("📋 Aucun canal géré.", reply_markup=back_kb)
            return
        current_time = int(datetime.now().timestamp())
        msg = "📋 **Canaux gérés:**\n\n"
        for cid, ch in channels.items():
            members = ch.get("members", {})
            active = sum(1 for m in members.values() if m.get("expires_at", 0) > current_time)
            expired = len(members) - active
            default_secs = ch.get("default_duration_seconds", 86400)
            dur_label = format_duration_label(default_secs)
            msg += (
                f"📢 **{ch.get('name', cid)}**\n"
                f"   🆔 `{cid}`\n"
                f"   👥 {active} actif(s) | 🔴 {expired} expiré(s)\n"
                f"   ⏱ Défaut: {dur_label}\n\n"
            )
        await query.edit_message_text(msg, reply_markup=back_kb, parse_mode="Markdown")
        return

    if query.data == "admin_members_ask":
        admin_state[update.effective_user.id] = {"action": "await_members_args"}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="admin_panel")]])
        await query.edit_message_text(
            "👥 **Voir les membres**\n\nEnvoyez l'**ID du canal**:\n`<id_canal>`\n\nEx: `-1001234567890`",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    if query.data == "admin_grant_ask":
        admin_state[update.effective_user.id] = {"action": "await_grant_args"}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="admin_panel")]])
        await query.edit_message_text(
            "✅ **Accorder accès**\n\nEnvoyez:\n`<id_canal> <id_user> <heures>`\n\nEx: `-1001234567890 987654321 24`",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    if query.data == "admin_extend_ask":
        admin_state[update.effective_user.id] = {"action": "await_extend_args"}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="admin_panel")]])
        await query.edit_message_text(
            "⏫ **Prolonger l'accès**\n\nEnvoyez:\n`<id_canal> <id_user> <heures>`\n\nEx: `-1001234567890 987654321 48`",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    if query.data == "admin_remove_ask":
        admin_state[update.effective_user.id] = {"action": "await_remove_args"}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="admin_panel")]])
        await query.edit_message_text(
            "❌ **Retirer un membre**\n\nEnvoyez:\n`<id_canal> <id_user>`\n\nEx: `-1001234567890 987654321`",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    if query.data == "admin_unblock_ask":
        admin_state[update.effective_user.id] = {"action": "await_unblock_args"}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="admin_panel")]])
        await query.edit_message_text(
            "🔓 **Débloquer un utilisateur**\n\nEnvoyez:\n`<id_canal> <id_user>`\n\nEx: `-1001234567890 987654321`",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    if query.data == "admin_setdur_ask":
        admin_state[update.effective_user.id] = {"action": "await_setdur_args"}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="admin_panel")]])
        await query.edit_message_text(
            "⏱ **Durée par défaut**\n\nEnvoyez:\n`<id_canal> <heures>`\n\nEx: `-1001234567890 24`",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    if query.data == "admin_scan_ask":
        admin_state[update.effective_user.id] = {"action": "await_scan_args"}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="admin_panel")]])
        await query.edit_message_text(
            "🔍 **Scanner un canal**\n\nEnvoyez l'**ID du canal**:\n`<id_canal>`\n\nEx: `-1001234567890`",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    if query.data == "admin_ai_on":
        data = load_data()
        data["ai_enabled"] = True
        save_data(data)
        text, kb = build_admin_panel(data)
        await query.edit_message_text("✅ **Assistant IA activé!**\n\n" + text, reply_markup=kb, parse_mode="Markdown")
        return

    if query.data == "admin_ai_off":
        data = load_data()
        data["ai_enabled"] = False
        save_data(data)
        text, kb = build_admin_panel(data)
        await query.edit_message_text("⭕ **Assistant IA désactivé.**\n\n" + text, reply_markup=kb, parse_mode="Markdown")
        return

    if query.data == "admin_ai_config":
        data = load_data()
        text, kb = build_ai_config_panel(data)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    # Gestion des clés par fournisseur: admin_ai_keys_<provider>
    if action == "admin" and len(parts) >= 4 and parts[1] == "ai" and parts[2] == "keys":
        provider = parts[3]
        if provider not in AI_PROVIDERS:
            await query.answer("Fournisseur inconnu.", show_alert=True)
            return
        data = load_data()
        text, kb = await build_ai_keys_panel(data, provider)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    # Ajouter une clé: admin_ai_addkey_<provider>
    if action == "admin" and len(parts) >= 4 and parts[1] == "ai" and parts[2] == "addkey":
        provider = parts[3]
        if provider not in AI_PROVIDERS:
            await query.answer("Fournisseur inconnu.", show_alert=True)
            return
        pinfo = AI_PROVIDERS[provider]
        admin_state[update.effective_user.id] = {"action": "await_add_ai_key", "provider": provider}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data=f"admin_ai_keys_{provider}")]])
        await query.edit_message_text(
            f"➕ **Ajouter une clé {pinfo['emoji']} {pinfo['name']}**\n\n"
            f"Envoyez votre clé API dans ce chat.\n"
            f"Elle sera ajoutée à la liste — la rotation automatique s'active quand il y a plusieurs clés.\n\n"
            f"⚠️ Ne partagez jamais vos clés API.",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    # Supprimer une clé: admin_ai_rmkey_<provider>_<index>
    if action == "admin" and len(parts) >= 5 and parts[1] == "ai" and parts[2] == "rmkey":
        provider = parts[3]
        idx = int(parts[4])
        if provider not in AI_PROVIDERS:
            await query.answer("Fournisseur inconnu.", show_alert=True)
            return
        data = load_data()
        keys = get_keys_list(data.get("ai_config", {}), provider)
        if 0 <= idx < len(keys):
            removed = keys.pop(idx)
            ai_key_failures.pop((provider, removed), None)
            if "ai_config" not in data:
                data["ai_config"] = {}
            data["ai_config"].setdefault("keys", {})[provider] = keys
            save_data(data)
            await query.answer(f"Clé {idx+1} supprimée.", show_alert=False)
        text, kb = await build_ai_keys_panel(data, provider)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    # Renouveler une clé expirée: admin_ai_renew_<provider>_<index>
    if action == "admin" and len(parts) >= 5 and parts[1] == "ai" and parts[2] == "renew":
        provider = parts[3]
        idx = int(parts[4])
        if provider not in AI_PROVIDERS:
            await query.answer("Fournisseur inconnu.", show_alert=True)
            return
        pinfo = AI_PROVIDERS[provider]
        admin_state[update.effective_user.id] = {"action": "await_renew_ai_key", "provider": provider, "index": idx}
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data=f"admin_ai_keys_{provider}")]])
        await query.edit_message_text(
            f"🔄 **Renouveler la clé {idx+1} — {pinfo['emoji']} {pinfo['name']}**\n\n"
            f"Envoyez la nouvelle clé API dans ce chat.\n"
            f"Elle remplacera l'ancienne clé expirée.\n\n"
            f"⚠️ Ne partagez jamais vos clés API.",
            reply_markup=cancel_kb, parse_mode="Markdown"
        )
        return

    # Activer un fournisseur: admin_ai_activate_<provider>
    if action == "admin" and len(parts) >= 4 and parts[1] == "ai" and parts[2] == "activate":
        provider = parts[3]
        if provider not in AI_PROVIDERS:
            await query.answer("Fournisseur inconnu.", show_alert=True)
            return
        data = load_data()
        if "ai_config" not in data:
            data["ai_config"] = {}
        data["ai_config"]["provider"] = provider
        save_data(data)
        pinfo = AI_PROVIDERS[provider]
        await query.answer(f"{pinfo['emoji']} {pinfo['name']} activé!", show_alert=False)
        text, kb = await build_ai_keys_panel(data, provider)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    # Tester les clés d'un fournisseur: admin_ai_test_<provider>
    if action == "admin" and len(parts) >= 4 and parts[1] == "ai" and parts[2] == "test":
        provider = parts[3]
        if provider not in AI_PROVIDERS:
            await query.answer("Fournisseur inconnu.", show_alert=True)
            return
        data = load_data()
        keys = get_keys_list(data.get("ai_config", {}), provider)
        pinfo = AI_PROVIDERS[provider]
        if not keys:
            await query.answer("Aucune clé configurée.", show_alert=True)
            return
        await query.edit_message_text(f"🔍 Test des clés {pinfo['name']} en cours...", parse_mode="Markdown")
        lines = [f"🔍 **Résultats — {pinfo['emoji']} {pinfo['name']}**\n"]
        for i, k in enumerate(keys):
            short = k[:8] + "..." + k[-4:] if len(k) > 14 else k
            ok, msg = await check_single_ai_key(provider, k)
            if not ok and _is_quota_error(msg.lower()):
                ai_key_failures[(provider, k)] = {"until": int(datetime.now().timestamp()) + 3600, "reason": "quota"}
            elif not ok and _is_invalid_key_error(msg.lower()):
                ai_key_failures[(provider, k)] = {"until": int(datetime.now().timestamp()) + 86400, "reason": "invalid"}
            else:
                ai_key_failures.pop((provider, k), None)
            lines.append(f"**Clé {i+1}** (`{short}`): {msg}")
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"← Retour", callback_data=f"admin_ai_keys_{provider}")]])
        await query.edit_message_text("\n".join(lines), reply_markup=back_kb, parse_mode="Markdown")
        return

    # Tester TOUTES les clés de tous les fournisseurs
    if query.data == "admin_ai_testall":
        data = load_data()
        await query.edit_message_text("🔍 Test de toutes les clés en cours...\n_Cela peut prendre quelques secondes._", parse_mode="Markdown")
        lines = ["🔍 **Rapport de toutes les clés IA**\n"]
        any_key = False
        for pid, pinfo in AI_PROVIDERS.items():
            keys = get_keys_list(data.get("ai_config", {}), pid)
            if not keys:
                continue
            any_key = True
            lines.append(f"\n{pinfo['emoji']} **{pinfo['name']}** ({len(keys)} clé(s)):")
            for i, k in enumerate(keys):
                short = k[:8] + "..." + k[-4:] if len(k) > 14 else k
                ok, msg = await check_single_ai_key(pid, k)
                if not ok and "quota" in msg.lower():
                    ai_key_failures[(pid, k)] = {"until": int(datetime.now().timestamp()) + 3600, "reason": "quota"}
                elif not ok and ("invalide" in msg.lower() or "invalid" in msg.lower()):
                    ai_key_failures[(pid, k)] = {"until": int(datetime.now().timestamp()) + 86400, "reason": "invalid"}
                else:
                    ai_key_failures.pop((pid, k), None)
                lines.append(f"  Clé {i+1} (`{short}`): {msg}")
        if not any_key:
            lines.append("Aucune clé configurée.")
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Retour Config IA", callback_data="admin_ai_config")]])
        await query.edit_message_text("\n".join(lines), reply_markup=back_kb, parse_mode="Markdown")
        return

    if action == "admin" and len(parts) >= 3 and parts[1] == "ai" and parts[2] == "provider":
        provider = parts[3] if len(parts) > 3 else None
        if provider not in AI_PROVIDERS:
            await query.answer("Fournisseur inconnu.", show_alert=True)
            return
        prov_info = AI_PROVIDERS[provider]
        admin_state[update.effective_user.id] = {"action": "await_ai_key", "provider": provider}
        cancel_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Annuler", callback_data="admin_ai_config")]
        ])
        await query.edit_message_text(
            f"🔑 **Configuration {prov_info['emoji']} {prov_info['name']}**\n\n"
            f"Envoyez votre clé API **{prov_info['name']}** dans ce chat.\n\n"
            f"_Cette clé sera sauvegardée et utilisée pour l'assistant IA._\n\n"
            f"⚠️ Ne partagez jamais vos clés API.",
            reply_markup=cancel_kb,
            parse_mode="Markdown"
        )
        return

    if query.data == "admin_telethon_status":
        connected = await telethon_manager.is_connected()
        if connected:
            try:
                client = telethon_manager.get_client()
                me = await client.get_me()
                status_msg = (
                    f"📡 **Statut Telethon**\n\n"
                    f"✅ Connecté: **{me.first_name}** (@{me.username or me.id})\n\n"
                    f"Telethon est opérationnel."
                )
            except Exception:
                status_msg = "✅ **Telethon connecté** (détails indisponibles)"
        else:
            status_msg = (
                "❌ **Telethon non connecté**\n\n"
                "Utilisez le bouton 🔌 Connecter pour l'authentifier."
            )
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Retour", callback_data="admin_panel")]])
        await query.edit_message_text(status_msg, reply_markup=back_kb, parse_mode="Markdown")
        return

    if query.data == "admin_telethon_connect":
        await query.edit_message_text("🔌 Lancement de la connexion Telethon...")
        if not TELETHON_API_ID or not TELETHON_API_HASH:
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Retour", callback_data="admin_panel")]])
            await context.bot.send_message(
                update.effective_user.id,
                "❌ **API Telethon non configurée.**\n\nAjoutez les secrets `TELETHON_API_ID` et `TELETHON_API_HASH`.\n\nObtenez-les sur https://my.telegram.org",
                reply_markup=back_kb, parse_mode="Markdown"
            )
            return
        msg = await telethon_manager.start_auth(update.effective_user.id)
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
        return

    if query.data == "admin_help":
        text = (
            "📖 **Aide — Commandes Admin**\n\n"
            "**Depuis les boutons:**\n"
            "• 📋 **Canaux** — Liste des canaux gérés\n"
            "• 👥 **Membres** — Membres + temps restant (saisir ID canal)\n"
            "• ✅ **Accorder accès** — Donner accès (saisir canal, user, heures)\n"
            "• ⏫ **Prolonger** — Rallonger l'accès existant\n"
            "• ❌ **Retirer** — Retirer un membre\n"
            "• 🔓 **Débloquer** — Débloquer un utilisateur banni\n"
            "• ⏱ **Durée défaut** — Changer la durée par défaut d'un canal\n"
            "• 🔍 **Scanner** — Rescanner un canal\n"
            "• ⚙️ **Config IA** — Choisir le fournisseur IA et configurer la clé API\n"
            "• 🔌 **Telethon** — Connecter votre compte Telegram\n\n"
            "**Fournisseurs IA supportés:**\n"
            "🔵 Gemini | 🟢 OpenAI | 🟠 Groq | 🔷 DeepSeek"
        )
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Retour", callback_data="admin_panel")]])
        await query.edit_message_text(text, reply_markup=back_kb, parse_mode="Markdown")
        return

    if action == "setdef":
        cid = parts[1]
        duration_seconds = int(parts[2])
        data = load_data()
        if cid in data.get("channels", {}):
            data["channels"][cid]["default_duration_seconds"] = duration_seconds
            ch_name = data["channels"][cid].get("name", cid)
            save_data(data)
            dur_label = format_duration_label(duration_seconds)
            await query.edit_message_text(
                f"✅ **Durée par défaut mise à jour!**\n\n"
                f"📢 Canal: {ch_name}\n"
                f"⏱ Durée: {dur_label}",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ Canal introuvable.")

    elif action in ("grant", "grantm"):
        cid = parts[1]
        uid = parts[2]
        val = int(parts[3])
        data = load_data()

        if cid not in data.get("channels", {}):
            await query.edit_message_text("❌ Canal introuvable.")
            return

        ch = data["channels"][cid]
        current_time = int(datetime.now().timestamp())

        # "grant" = heures, "grantm" = minutes
        duration_seconds = val * 60 if action == "grantm" else val * 3600
        expires_at = current_time + duration_seconds

        ch.setdefault("members", {})[uid] = {
            "expires_at": expires_at,
            "granted_at": current_time,
            "duration_seconds": duration_seconds
        }
        # Débloquer l'utilisateur s'il était bloqué
        ch.setdefault("blocked", {}).pop(uid, None)
        save_data(data)

        dur_label = format_duration_label(duration_seconds)
        expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M:%S')

        # Générer un lien d'invitation unique pour l'utilisateur
        grant_invite_link = None
        try:
            invite_obj = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
            grant_invite_link = invite_obj.invite_link
            pending_invites[(cid, uid)] = grant_invite_link
        except Exception as e:
            logger.warning(f"Impossible de créer le lien pour {cid}: {e}")

        try:
            if grant_invite_link:
                await context.bot.send_message(
                    int(uid),
                    f"✅ **Accès accordé!**\n\n"
                    f"📢 Canal: **{ch['name']}**\n"
                    f"⏱ Durée: **{dur_label}**\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"👇 **Cliquez sur ce lien pour rejoindre le canal:**\n"
                    f"{grant_invite_link}\n\n"
                    f"⚠️ Ce lien est à usage unique — ne le partagez pas.\n"
                    f"⚠️ Votre accès sera automatiquement retiré à expiration.",
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    int(uid),
                    f"✅ **Accès accordé!**\n\n"
                    f"📢 Canal: **{ch['name']}**\n"
                    f"⏱ Durée: **{dur_label}**\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"✅ Vous pouvez rejoindre le canal.\n"
                    f"⚠️ Votre accès sera automatiquement retiré à expiration.",
                    parse_mode="Markdown"
                )
        except Exception:
            pass

        await query.edit_message_text(
            f"✅ **Accès accordé!**\n\n"
            f"🆔 Utilisateur: `{uid}`\n"
            f"⏱ Durée: **{dur_label}**\n"
            f"📅 Expire: {expire_str}\n"
            f"🔗 Lien envoyé à l'utilisateur.",
            parse_mode="Markdown"
        )

    elif action == "kick":
        cid = parts[1]
        uid = parts[2]
        data = load_data()

        if cid not in data.get("channels", {}):
            await query.edit_message_text("❌ Canal introuvable.")
            return

        try:
            await context.bot.ban_chat_member(int(cid), int(uid))
            await context.bot.unban_chat_member(int(cid), int(uid))
        except Exception as e:
            logger.warning(f"Impossible de retirer {uid} du canal {cid}: {e}")

        ch = data["channels"][cid]
        ch.get("members", {}).pop(uid, None)
        save_data(data)

        try:
            await context.bot.send_message(
                int(uid),
                f"⚠️ Vous avez été retiré du canal **{ch['name']}**.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        await query.edit_message_text(
            f"✅ Utilisateur `{uid}` retiré du canal {ch['name']}.",
            parse_mode="Markdown"
        )

    elif action == "paychan":
        # Flux obsolète — rediriger vers le nouveau système
        await query.edit_message_text(
            "⚠️ Ce lien est obsolète.\n\nUtilisez le bouton **💳 Payer mon abonnement** depuis /start.",
            parse_mode="Markdown",
        )


# ═══════════════════════════════════════════════════════════════
# COMMANDES ADMIN
# ═══════════════════════════════════════════════════════════════

def _auth_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 S'inscrire", callback_data="inscription"),
        InlineKeyboardButton("🔐 Se connecter", callback_data="connexion"),
    ]])


def _user_main_menu(first_name: str) -> tuple:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Mon statut d'abonnement", callback_data="my_status")],
        [InlineKeyboardButton("💳 Payer mon abonnement", callback_data="pay_start")],
        [InlineKeyboardButton("🎁 Demander un bonus", callback_data="bonus_start")],
        [InlineKeyboardButton("💬 Assistance", callback_data="assist_start")],
    ])
    text = (
        f"👋 **Bonjour {first_name}!**\n\n"
        "• 📊 Vérifier votre durée restante\n"
        "• 💳 Payer votre abonnement\n"
        "• 🎁 Demander un accès gratuit (bonus)\n"
        "• 💬 Contacter l'assistance"
    )
    return text, kb


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Réinitialiser tout flux en cours
    reg_state.pop(user_id, None)
    login_state.pop(user_id, None)

    # Vérifier si déjà connecté (telegram_id lié dans la DB)
    db_user = await db_get_user_by_telegram_id(user_id)
    if db_user:
        first = db_user.get("first_name") or update.effective_user.first_name or "vous"
        if is_admin(user_id):
            data = load_data()
            panel_text, panel_kb = build_admin_panel(data)
            await update.message.reply_text(panel_text, reply_markup=panel_kb, parse_mode="Markdown")
        else:
            menu_text, menu_kb = _user_main_menu(first)
            await update.message.reply_text(menu_text, reply_markup=menu_kb, parse_mode="Markdown")
        return

    # Non connecté — afficher l'écran d'accueil avec inscription/connexion
    await update.message.reply_text(
        "👋 **Bienvenue sur le bot Sossou Kouamé!**\n\n"
        "Pour accéder à nos services, veuillez vous identifier:\n\n"
        "• 📝 **S'inscrire** — Je n'ai pas encore de compte\n"
        "• 🔐 **Se connecter** — J'ai déjà un compte",
        reply_markup=_auth_keyboard(),
        parse_mode="Markdown",
    )


async def statut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Afficher la durée restante d'abonnement pour l'utilisateur"""
    user = update.effective_user
    uid_str = str(user.id)
    data = load_data()
    channels = data.get("channels", {})
    current_time = int(datetime.now().timestamp())
    found = False
    lines = [f"📊 **Statut de vos abonnements**\n👤 {user.first_name}\n"]

    for cid, ch in channels.items():
        members = ch.get("members", {})
        if uid_str in members:
            m = members[uid_str]
            expires_at = m.get("expires_at", 0)
            time_left = expires_at - current_time
            dur_total = format_duration_label(m.get("duration_seconds", 0))
            expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M') if expires_at else "?"
            if time_left > 0:
                remaining = format_time_remaining(time_left)
                lines.append(
                    f"📢 **{ch.get('name', cid)}**\n"
                    f"   ✅ Accès **ACTIF**\n"
                    f"   ⏳ Temps restant: **{remaining}**\n"
                    f"   📅 Expire le: {expire_str}\n"
                    f"   ⏱ Durée totale: {dur_total}\n"
                )
            else:
                lines.append(
                    f"📢 **{ch.get('name', cid)}**\n"
                    f"   🔴 Accès **EXPIRÉ** depuis le {expire_str}\n"
                )
            found = True

    if not found:
        lines.append(
            "ℹ️ Vous n'avez aucun abonnement enregistré.\n\n"
            "Tapez /start pour souscrire ou demander un bonus."
        )

    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Menu principal", callback_data="back_main")
    ]])
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=back_kb)


async def ai_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    data = load_data()
    data["ai_enabled"] = True
    save_data(data)
    status = "✅ opérationnel" if gemini_client else "⚠️ activé mais GEMINI_API_KEY non configuré"
    await update.message.reply_text(f"🤖 **Assistant IA {status}!**\n\nIl répondra automatiquement aux utilisateurs.", parse_mode="Markdown")


async def ai_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    data = load_data()
    data["ai_enabled"] = False
    save_data(data)
    await update.message.reply_text("⭕ **Assistant IA désactivé.**\n\nLe bot ne répondra plus automatiquement.", parse_mode="Markdown")


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    data = load_data()
    channels = data.get("channels", {})

    if not channels:
        await update.message.reply_text(
            "📋 Aucun canal géré.\n\n"
            "➕ Ajoutez le bot comme administrateur d'un canal pour commencer."
        )
        return

    current_time = int(datetime.now().timestamp())
    msg = "📋 **Canaux gérés:**\n\n"

    for cid, ch in channels.items():
        members = ch.get("members", {})
        active = sum(1 for m in members.values() if m.get("expires_at", 0) > current_time)
        expired = len(members) - active
        default_secs = ch.get("default_duration_seconds", ch.get("default_duration_hours", 24) * 3600)
        dur_label = format_duration_label(default_secs)
        msg += (
            f"📢 **{ch.get('name', cid)}**\n"
            f"   🆔 `{cid}`\n"
            f"   👥 {active} actif(s) | 🔴 {expired} expiré(s)\n"
            f"   ⏱ Défaut: {dur_label}\n\n"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")


async def members_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: `/members <id_canal>`", parse_mode="Markdown")
        return

    cid = context.args[0]
    data = load_data()

    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal introuvable.")
        return

    ch = data["channels"][cid]
    members = ch.get("members", {})
    current_time = int(datetime.now().timestamp())

    if not members:
        await update.message.reply_text(f"📋 Aucun membre dans **{ch['name']}**.", parse_mode="Markdown")
        return

    msg = f"📋 **Membres — {ch['name']}**\n\n"
    for uid, m in members.items():
        time_left = m.get("expires_at", 0) - current_time
        status = "🟢" if time_left > 0 else "🔴"
        msg += f"{status} `{uid}` — ⏳ {format_time_remaining(time_left)}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: `/remove <id_canal> <id_user>`", parse_mode="Markdown")
        return

    cid, uid = context.args[0], context.args[1]
    data = load_data()

    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal introuvable.")
        return

    ch = data["channels"][cid]
    try:
        await context.bot.ban_chat_member(int(cid), int(uid))
        await context.bot.unban_chat_member(int(cid), int(uid))
    except Exception as e:
        logger.warning(f"Impossible de retirer {uid}: {e}")

    ch.get("members", {}).pop(uid, None)
    save_data(data)

    try:
        await context.bot.send_message(int(uid), f"⚠️ Votre accès au canal **{ch['name']}** a été révoqué.", parse_mode="Markdown")
    except Exception:
        pass

    await update.message.reply_text(f"✅ Utilisateur `{uid}` retiré de **{ch['name']}**.", parse_mode="Markdown")


async def setduration_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Usage: `/setduration <id_canal> <heures>`\n"
            "Exemple: `/setduration -1001234567890 24`\n"
            "_Définit la durée par défaut (en heures entières, ex: 0.5 pour 30min)._",
            parse_mode="Markdown"
        )
        return

    cid = context.args[0]
    try:
        hours_float = float(context.args[1])
        if not (0.1 <= hours_float <= 750):
            raise ValueError
        duration_seconds = int(hours_float * 3600)
    except ValueError:
        await update.message.reply_text("❌ Durée invalide. Entrez un nombre entre 0.1 et 750 (heures).")
        return

    data = load_data()
    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal introuvable.")
        return

    data["channels"][cid]["default_duration_seconds"] = duration_seconds
    save_data(data)
    dur_label = format_duration_label(duration_seconds)
    await update.message.reply_text(
        f"✅ Durée par défaut mise à jour: **{dur_label}** pour **{data['channels'][cid]['name']}**",
        parse_mode="Markdown"
    )


async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Accorder l'accès par commande — durée en heures (1h à 750h)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ Usage: `/grant <id_canal> <id_user> <heures>`\n"
            "Exemple: `/grant -1001234567890 987654321 48`\n"
            "_Durée: 1h minimum, 750h maximum_",
            parse_mode="Markdown"
        )
        return

    cid = context.args[0]
    uid = context.args[1]
    try:
        hours = int(context.args[2])
        if not (1 <= hours <= 750):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Durée invalide. Entrez un nombre entre 1 et 750.")
        return

    data = load_data()
    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal introuvable.")
        return

    ch = data["channels"][cid]
    current_time = int(datetime.now().timestamp())
    duration_seconds = hours * 3600
    expires_at = current_time + duration_seconds

    ch.setdefault("members", {})[uid] = {
        "expires_at": expires_at,
        "granted_at": current_time,
        "duration_seconds": duration_seconds
    }
    ch.setdefault("blocked", {}).pop(uid, None)
    save_data(data)

    dur_label = format_duration_label(duration_seconds)
    expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M')

    # Générer un lien d'invitation unique
    cmd_invite_link = None
    try:
        invite_obj = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
        cmd_invite_link = invite_obj.invite_link
        pending_invites[(cid, uid)] = cmd_invite_link
    except Exception as e:
        logger.warning(f"Impossible de créer le lien /grant pour {cid}: {e}")

    try:
        if cmd_invite_link:
            await context.bot.send_message(
                int(uid),
                f"✅ **Accès accordé!**\n\n"
                f"📢 Canal: **{ch['name']}**\n"
                f"⏱ Durée: **{dur_label}**\n"
                f"📅 Expire le: {expire_str}\n\n"
                f"👇 **Cliquez sur ce lien pour rejoindre le canal:**\n"
                f"{cmd_invite_link}\n\n"
                f"⚠️ Ce lien est à usage unique — ne le partagez pas.\n"
                f"⚠️ Votre accès sera automatiquement retiré à expiration.",
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                int(uid),
                f"✅ **Accès accordé!**\n\n"
                f"📢 Canal: **{ch['name']}**\n"
                f"⏱ Durée: **{dur_label}**\n"
                f"📅 Expire le: {expire_str}\n\n"
                f"✅ Vous pouvez rejoindre le canal.\n"
                f"⚠️ Votre accès sera automatiquement retiré à expiration.",
                parse_mode="Markdown"
            )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ **Accès accordé par commande!**\n\n"
        f"📢 Canal: {ch['name']}\n"
        f"🆔 Utilisateur: `{uid}`\n"
        f"⏱ Durée: **{dur_label}**\n"
        f"📅 Expire: {expire_str}\n"
        f"🔗 Lien d'invitation envoyé à l'utilisateur.",
        parse_mode="Markdown"
    )


async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Débloquer un utilisateur précédemment bloqué"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Usage: `/unblock <id_canal> <id_user>`",
            parse_mode="Markdown"
        )
        return

    cid = context.args[0]
    uid = context.args[1]
    data = load_data()

    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal introuvable.")
        return

    ch = data["channels"][cid]
    if uid in ch.get("blocked", {}):
        del ch["blocked"][uid]
        # Unban pour lui permettre de rejoindre
        try:
            await context.bot.unban_chat_member(int(cid), int(uid), only_if_banned=True)
        except Exception:
            pass
        save_data(data)
        await update.message.reply_text(
            f"✅ Utilisateur `{uid}` débloqué.\n"
            f"Il peut maintenant rejoindre **{ch['name']}**.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"ℹ️ L'utilisateur `{uid}` n'est pas bloqué.", parse_mode="Markdown")


async def extend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rallonger la durée d'accès d'un membre existant"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ Usage: `/extend <id_canal> <id_user> <heures>`\n"
            "Exemple: `/extend -1001234567890 987654321 24`\n"
            "_Ajoute des heures à l'accès existant d'un membre._",
            parse_mode="Markdown"
        )
        return

    cid = context.args[0]
    uid = context.args[1]
    try:
        extra_hours = int(context.args[2])
        if not (1 <= extra_hours <= 750):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Durée invalide. Entrez un nombre entre 1 et 750.")
        return

    data = load_data()
    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal introuvable.")
        return

    ch = data["channels"][cid]
    members = ch.setdefault("members", {})
    current_time = int(datetime.now().timestamp())

    if uid in members:
        current_expiry = members[uid].get("expires_at", current_time)
        # Si déjà expiré, on part de maintenant; sinon on rallonge depuis l'expiration actuelle
        base_time = max(current_expiry, current_time)
        new_expiry = base_time + (extra_hours * 3600)
        members[uid]["expires_at"] = new_expiry
        members[uid].setdefault("duration_seconds", extra_hours * 3600)
    else:
        # Nouveau membre
        new_expiry = current_time + (extra_hours * 3600)
        members[uid] = {
            "expires_at": new_expiry,
            "granted_at": current_time,
            "duration_seconds": extra_hours * 3600
        }

    ch.setdefault("blocked", {}).pop(uid, None)
    save_data(data)

    expire_str = datetime.fromtimestamp(new_expiry).strftime('%d/%m/%Y à %H:%M')

    try:
        await context.bot.unban_chat_member(int(cid), int(uid), only_if_banned=True)
    except Exception:
        pass

    try:
        await context.bot.send_message(
            int(uid),
            f"✅ **Accès prolongé!**\n\n"
            f"📢 Canal: **{ch['name']}**\n"
            f"➕ **+{extra_hours}h** ajoutées\n"
            f"📅 Nouveau terme: {expire_str}",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ **Accès prolongé de +{extra_hours}h**\n\n"
        f"🆔 Utilisateur: `{uid}`\n"
        f"📢 Canal: **{ch['name']}**\n"
        f"📅 Expire maintenant le: {expire_str}",
        parse_mode="Markdown"
    )


async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /bonus — demander un accès sans paiement (envoi notification admin)"""
    user = update.effective_user
    if not user:
        return

    data = load_data()
    channels = data.get("channels", {})
    if not channels:
        await update.message.reply_text("ℹ️ Aucun canal disponible pour le moment.")
        return

    keyboard = []
    for cid, ch in channels.items():
        keyboard.append([InlineKeyboardButton(
            f"📢 {ch.get('name', cid)}",
            callback_data=f"bch_{user.id}_{cid}"
        )])
    keyboard.append([InlineKeyboardButton("❌ Annuler", callback_data="home")])

    await update.message.reply_text(
        "🎁 **Demande de bonus**\n\n"
        "Pour quel canal souhaitez-vous demander un accès gratuit?\n\n"
        "_Votre demande sera envoyée à l'administrateur pour approbation._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        text = (
            "📖 **Aide — Commandes Admin**\n\n"
            "**Canaux:**\n"
            "• `/channels` — Liste des canaux gérés\n"
            "• `/members <id_canal>` — Membres + temps restant\n"
            "• `/remove <id_canal> <id_user>` — Retirer un membre\n\n"
            "**Durées d'accès:**\n"
            "• **Boutons** (nouveau membre): 2min / 10min / 20min / 30min / Défaut\n"
            "• `/grant <id_canal> <id_user> <heures>` — Accorder 1h à 750h\n"
            "• `/extend <id_canal> <id_user> <heures>` — **Rallonger** l'accès existant\n"
            "• `/setduration <id_canal> <heures>` — Durée du bouton Défaut\n"
            "• `/unblock <id_canal> <id_user>` — Débloquer un banni\n"
            "• `/bonus` — Accorder accès gratuit (envoie notif à vous-même)\n\n"
            "**Paiements:**\n"
            "• Anti-doublon automatique (hash du reçu vérifié)\n"
            "• Références de transaction extraites et stockées\n\n"
            "**Expiration:**\n"
            "• Retrait immédiat à expiration\n"
            "• Retour tenté → blocage auto + message\n\n"
            "**Assistant IA:**\n"
            "• `/ai_on` / `/ai_off` — Activer/désactiver\n\n"
            "**Telethon:**\n"
            "• `/connect [+numéro]` — Connecter compte Telegram\n"
            "• `/telethon` — Statut connexion\n"
            "• `/scan <id_canal>` — Rescanner un canal\n"
            "• `/disconnect` — Déconnecter"
        )
    else:
        text = (
            "📖 **Aide**\n\n"
            "• `/start` — Menu principal et paiement\n"
            "• `/bonus` — Demander un accès gratuit\n"
            "• `/statut` — Voir votre abonnement"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
# COMMANDES PAIEMENT
# ═══════════════════════════════════════════════════════════════

async def payer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /payer — redirige vers le menu de paiement"""
    user = update.effective_user
    if not user:
        return
    db_user = await db_get_user_by_telegram_id(user.id)
    if not db_user:
        await update.message.reply_text(
            "❌ Vous devez d'abord créer un compte.\n\nTapez /start pour vous inscrire.",
            parse_mode="Markdown",
        )
        return
    email = db_user.get("email") or "votre email"
    pay_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🌐 Accéder au site de paiement",
            url="https://paiement-s-curis.onrender.com",
        )],
        [InlineKeyboardButton(
            "✅ J'ai payé — Vérifier mon accès",
            callback_data="check_payment",
        )],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="back_main")],
    ])
    await update.message.reply_text(
        "💳 **Paiement d'abonnement**\n\n"
        "1️⃣ Cliquez sur **\"Accéder au site de paiement\"**\n"
        f"2️⃣ Connectez-vous avec votre email: `{email}`\n"
        "3️⃣ Effectuez votre paiement\n"
        "4️⃣ Cliquez **\"J'ai payé\"** pour activer l'accès\n\n"
        "_Votre accès sera activé automatiquement après vérification._",
        reply_markup=pay_keyboard,
        parse_mode="Markdown",
    )


async def annuler_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /annuler"""
    user = update.effective_user
    if not user:
        return
    reg_state.pop(user.id, None)
    login_state.pop(user.id, None)
    await update.message.reply_text(
        "✅ Opération annulée. Tapez /start pour recommencer.",
        reply_markup=_auth_keyboard(),
    )


# COMMANDES TELETHON (Compte utilisateur personnel)
# ═══════════════════════════════════════════════════════════════

async def save_telethon_session(session_str: str, context, admin_id: int):
    """Sauvegarde la session Telethon dans un fichier et notifie l'admin"""
    # Sauvegarder dans un fichier local pour persistance
    try:
        with open("telethon_session.txt", "w") as f:
            f.write(session_str)
        logger.info("Session Telethon sauvegardée dans telethon_session.txt")
    except Exception as e:
        logger.error(f"Erreur sauvegarde session: {e}")

    # Message partie 1: confirmation
    await context.bot.send_message(
        admin_id,
        f"✅ **Connexion Telethon réussie et session sauvegardée!**\n\n"
        f"La session est stockée localement dans `telethon_session.txt`.\n\n"
        f"📋 **Pour utiliser sur Render.com** → voir message suivant:",
        parse_mode="Markdown"
    )

    # Message partie 2: la session string brute (pour copier-coller)
    await context.bot.send_message(
        admin_id,
        f"🔑 **Votre TELETHON\\_SESSION:**\n\n"
        f"`{session_str}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **Sur Render.com:**\n"
        f"1. Dashboard → votre service → **Environment**\n"
        f"2. Cliquez **Add Environment Variable**\n"
        f"3. Key: `TELETHON_SESSION`\n"
        f"4. Value: collez la chaîne ci-dessus\n"
        f"5. **Save Changes** → redéployez\n\n"
        f"📌 **Sur Replit:**\n"
        f"Secrets → `TELETHON_SESSION` → collez la chaîne\n\n"
        f"⚠️ Ne partagez jamais cette session — elle donne accès à votre compte.",
        parse_mode="Markdown"
    )


async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lance l'authentification Telethon"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if not TELETHON_API_ID or not TELETHON_API_HASH:
        await update.message.reply_text(
            "❌ **API Telethon non configurée.**\n\n"
            "Ajoutez ces secrets dans Replit:\n"
            "• `TELETHON_API_ID` — votre API ID\n"
            "• `TELETHON_API_HASH` — votre API Hash\n\n"
            "Obtenez-les sur https://my.telegram.org",
            parse_mode="Markdown"
        )
        return

    uid = update.effective_user.id
    # Si le numéro est passé directement en argument (ex: /connect +22507XXXXXXXX)
    if context.args:
        phone_arg = context.args[0].strip()
        # Démarrer l'auth et passer directement à l'étape numéro
        init_msg = await telethon_manager.start_auth(uid)
        if "Déjà connecté" in init_msg:
            await update.message.reply_text(init_msg, parse_mode="Markdown")
            return
        # Traiter le numéro immédiatement
        msg, done = await telethon_manager.process_auth_step(uid, phone_arg)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        msg = await telethon_manager.start_auth(uid)
        await update.message.reply_text(msg, parse_mode="Markdown")


async def disconnect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Déconnecte le client Telethon"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    try:
        client = telethon_manager.get_client()
        if client.is_connected():
            await client.disconnect()
        telethon_manager.telethon_client = None
        await update.message.reply_text("✅ Telethon déconnecté.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {e}")


async def telethon_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche le statut de la connexion Telethon"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if not TELETHON_API_ID:
        await update.message.reply_text(
            "⚠️ `TELETHON_API_ID` non configuré.",
            parse_mode="Markdown"
        )
        return

    connected = await telethon_manager.is_connected()
    if connected:
        client = telethon_manager.get_client()
        me = await client.get_me()
        await update.message.reply_text(
            f"✅ **Telethon connecté**\n\n"
            f"👤 Compte: **{me.first_name}** (@{me.username or me.id})\n"
            f"📡 Accès complet aux membres des canaux activé.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🔴 **Telethon non connecté**\n\n"
            "Utilisez /connect pour vous authentifier.",
            parse_mode="Markdown"
        )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force un scan Telethon d'un canal"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Usage: `/scan <id_canal>`",
            parse_mode="Markdown"
        )
        return

    cid = context.args[0]
    data = load_data()
    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal inconnu. Ajoutez d'abord le bot au canal.")
        return

    ch = data["channels"][cid]
    channel_name = ch.get("name", cid)

    await update.message.reply_text(
        f"🔍 Scan du canal **{channel_name}** en cours...",
        parse_mode="Markdown"
    )

    asyncio.create_task(scan_channel_members(context, int(cid), channel_name))


# ═══════════════════════════════════════════════════════════════
# TÂCHE DE VÉRIFICATION DES EXPIRATIONS
# ═══════════════════════════════════════════════════════════════

async def check_expirations_task(application: Application):
    while True:
        try:
            data = load_data()
            current_time = int(datetime.now().timestamp())
            changed = False

            for cid, ch in data.get("channels", {}).items():
                to_remove = [
                    uid for uid, m in ch.get("members", {}).items()
                    if m.get("expires_at", 0) <= current_time
                ]

                for uid in to_remove:
                    # Ban sans unban = retrait immédiat + blocage
                    try:
                        await application.bot.ban_chat_member(int(cid), int(uid))
                        logger.info(f"✅ Membre {uid} expiré — banni du canal {cid}")
                    except Exception as e:
                        logger.error(f"Erreur ban {uid} canal {cid}: {e}")

                    # Ajouter à la liste des bloqués
                    ch.setdefault("blocked", {})[uid] = {
                        "blocked_at": current_time
                    }

                    # Message de paiement envoyé à l'utilisateur
                    try:
                        await application.bot.send_message(
                            int(uid),
                            f"⏰ **Accès expiré — {ch['name']}**\n\n"
                            f"Votre accès à ce canal a expiré et vous avez été retiré.\n\n"
                            f"🚫 Toute tentative de retour sera automatiquement bloquée.\n\n"
                            f"💳 Pour renouveler, tapez /start et cliquez sur 💳 Payer mon abonnement.",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

                    del ch["members"][uid]
                    changed = True

            if changed:
                save_data(data)

        except Exception as e:
            logger.error(f"Erreur check_expirations: {e}")

        await asyncio.sleep(30)  # Vérification toutes les 30 secondes


# ═══════════════════════════════════════════════════════════════
# FONCTION PRINCIPALE
# ═══════════════════════════════════════════════════════════════

async def startup_channel_scan(bot):
    """Au démarrage, vérifie et met à jour la liste des canaux déjà enregistrés."""
    data = load_data()
    channels = data.get("channels", {})
    if not channels:
        logger.info("🔍 Démarrage: aucun canal enregistré.")
        return

    to_remove = []
    updated = False
    for cid, ch in list(channels.items()):
        try:
            chat = await bot.get_chat(int(cid))
            new_name = chat.title or ch.get("name", f"Canal {cid}")
            if ch.get("name") != new_name:
                ch["name"] = new_name
                updated = True
            member = await bot.get_chat_member(int(cid), bot.id)
            if member.status in (ChatMember.LEFT, ChatMember.BANNED):
                to_remove.append(cid)
                logger.warning(f"⚠️ Canal {cid} retiré (bot exclu ou banni).")
            else:
                logger.info(f"✅ Canal actif: {ch['name']} ({cid})")
        except Exception as e:
            logger.warning(f"Canal {cid} inaccessible au démarrage: {e}")

    for cid in to_remove:
        del data["channels"][cid]

    if to_remove or updated:
        save_data(data)

    active = len(channels) - len(to_remove)
    logger.info(f"🔍 Scan démarrage terminé: {active} canal(aux) actif(s) sur {len(channels)} enregistré(s).")


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Capture toutes les exceptions non gérées des handlers.
    Nettoie admin_state pour éviter que l'admin reste bloqué."""
    logger.error("Exception non gérée dans un handler:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_user:
        uid = update.effective_user.id
        if uid in admin_state:
            admin_state.pop(uid, None)
            logger.warning(f"admin_state nettoyé pour {uid} suite à une erreur")
        try:
            msg = update.message or (update.callback_query and update.callback_query.message)
            if msg:
                await msg.reply_text(
                    "❌ Une erreur est survenue. L'état a été réinitialisé. Tapez /start pour recommencer.",
                    parse_mode=None
                )
        except Exception:
            pass


async def main():
    logger.info("🤖 Démarrage du bot multi-canal...")

    application = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()

    application.add_error_handler(global_error_handler)

    # Seule commande disponible: /start (ouvre le menu principal pour tout le monde)
    # Toutes les actions admin passent par les boutons inline
    application.add_handler(CommandHandler("start", start_command))

    # Callbacks boutons
    application.add_handler(CallbackQueryHandler(button_callback))

    # Événements membres du canal
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Messages utilisateurs (réponse IA, saisies admin, inscription) — uniquement chats privés
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_user_message
    ))

    await init_db_pool()
    await start_web_server()
    await application.initialize()
    await application.start()

    # Scan automatique des canaux déjà enregistrés au démarrage
    asyncio.create_task(startup_channel_scan(application.bot))

    asyncio.create_task(check_expirations_task(application))

    logger.info("✅ Bot multi-canal démarré avec succès!")

    # Supprime un éventuel webhook actif : sinon start_polling plante avec une erreur
    # "Conflict: can't use getUpdates while a webhook is set" et le bot ne répond plus du tout.
    await application.bot.delete_webhook(drop_pending_updates=True)

    await application.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
    )

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
