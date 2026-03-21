"""
Bot Telegram - Gestionnaire d'Accès Multi-Canal
Autonome: fonctionne sur plusieurs canaux simultanément
Assistante IA: répond automatiquement aux utilisateurs
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ChatMemberHandler, ContextTypes, filters
)

from config import (
    BOT_TOKEN, ADMINS, PORT, DATA_FILE, CHECK_INTERVAL,
    GEMINI_API_KEY, GEMINI_API_KEYS, OPENAI_API_KEYS, GROQ_API_KEYS,
    DEEPSEEK_API_KEYS, OCR_SPACE_API_KEY,
    TELETHON_API_ID, TELETHON_API_HASH,
)
import telethon_manager

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Imports IA ────────────────────────────────────────────────
try:
    from google import genai as google_genai
    from google.genai import types as genai_types
except ImportError:
    google_genai = None
    genai_types = None

try:
    import openai as openai_lib
except ImportError:
    openai_lib = None

# ── Fournisseurs IA disponibles ────────────────────────────────
AI_PROVIDERS = [
    {"code": "gemini",   "name": "Google Gemini",    "model": "gemini-2.5-flash-lite"},
    {"code": "openai",   "name": "OpenAI (ChatGPT)", "model": "gpt-4o-mini"},
    {"code": "deepseek", "name": "DeepSeek",         "model": "deepseek-chat",      "base_url": "https://api.deepseek.com"},
    {"code": "groq",     "name": "Groq",             "model": "llama3-8b-8192",     "base_url": "https://api.groq.com/openai/v1"},
]

# Formats de clé attendus par fournisseur
_KEY_PATTERNS = {
    "gemini":   {"prefix": ["AIza"], "min_len": 30,
                 "hint": "commence par `AIza` (ex: `AIzaSyDg0OQ...`)"},
    "openai":   {"prefix": ["sk-"],  "min_len": 20,
                 "hint": "commence par `sk-` (ex: `sk-proj-...`)"},
    "deepseek": {"prefix": ["sk-"],  "min_len": 20,
                 "hint": "commence par `sk-` (ex: `sk-...`)"},
    "groq":     {"prefix": ["gsk_"], "min_len": 20,
                 "hint": "commence par `gsk_` (ex: `gsk_...`)"},
}


def _validate_key_format(provider: str, key: str) -> tuple:
    """Valide le format d'une clé API. Retourne (valide, message_erreur)."""
    key = key.strip()
    pattern = _KEY_PATTERNS.get(provider)
    if not pattern:
        return len(key) >= 10, "Format inconnu"
    if len(key) < pattern["min_len"]:
        return False, f"Clé trop courte. Une clé {provider} {pattern['hint']}."
    if not any(key.startswith(pfx) for pfx in pattern["prefix"]):
        return False, f"Format incorrect. Une clé {provider} {pattern['hint']}."
    return True, ""


def _format_quota_line(label: str, remaining, limit) -> str:
    """Formate une ligne de quota avec barre de progression."""
    try:
        rem = int(remaining)
        lim = int(limit)
        if lim > 0:
            pct = int((rem / lim) * 100)
            filled = int(pct / 10)
            bar = "█" * filled + "░" * (10 - filled)
            return f"{label}: `{rem:,}/{lim:,}` [{bar}] {pct}%"
        return f"{label}: `{rem:,}`"
    except (TypeError, ValueError):
        return f"{label}: `{remaining}`"


async def _test_ai_key(provider: str, key: str) -> tuple:
    """
    Teste une clé API avec un appel minimal et lit les infos de quota en temps réel.
    Retourne (succès, message_statut).

    Pour les fournisseurs OpenAI-compatibles (OpenAI, Groq, DeepSeek) :
      → lit les headers x-ratelimit-* pour afficher le quota en temps réel.
    Pour Gemini :
      → confirme que la clé fonctionne + affiche les tokens utilisés.

    Note : le quota mensuel/billing n'est pas accessible par API
    (uniquement via le dashboard du fournisseur).
    """
    p_info = next((p for p in AI_PROVIDERS if p["code"] == provider), None)
    if not p_info:
        return False, "❌ Fournisseur inconnu"

    try:
        if provider == "gemini":
            if google_genai is None:
                return False, "❌ Bibliothèque Gemini non disponible"
            client = _init_gemini_client(key)
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=p_info["model"],
                    contents=[{"role": "user", "parts": [{"text": "OK"}]}]
                )
            )
            # Lire usage_metadata si disponible
            lines = ["✅ **Clé Gemini valide — quota disponible**\n"]
            try:
                um = resp.usage_metadata
                prompt_tok  = getattr(um, "prompt_token_count", "?")
                cand_tok    = getattr(um, "candidates_token_count", "?")
                total_tok   = getattr(um, "total_token_count", "?")
                lines.append(f"📊 **Tokens ce test :** entrée `{prompt_tok}` + sortie `{cand_tok}` = `{total_tok}` total")
            except Exception:
                pass
            lines.append("\n_ℹ️ Quota mensuel/billing : consultez console.cloud.google.com_")
            return True, "\n".join(lines)

        elif provider in ("openai", "deepseek", "groq"):
            if openai_lib is None:
                return False, "❌ Bibliothèque OpenAI non disponible"
            kwargs = {"api_key": key, "max_retries": 0}
            if "base_url" in p_info:
                kwargs["base_url"] = p_info["base_url"]
            oa_client = openai_lib.AsyncOpenAI(**kwargs)

            # Utiliser with_raw_response pour accéder aux headers HTTP
            raw_resp = await oa_client.with_raw_response.chat.completions.create(
                model=p_info["model"],
                messages=[{"role": "user", "content": "OK"}],
                max_tokens=3
            )
            hdrs = raw_resp.headers
            completion = raw_resp.parse()

            lines = [f"✅ **Clé {p_info['name']} valide — quota disponible**\n"]

            # Requêtes
            rem_req  = hdrs.get("x-ratelimit-remaining-requests")
            lim_req  = hdrs.get("x-ratelimit-limit-requests")
            rst_req  = hdrs.get("x-ratelimit-reset-requests")
            # Tokens
            rem_tok  = hdrs.get("x-ratelimit-remaining-tokens")
            lim_tok  = hdrs.get("x-ratelimit-limit-tokens")
            rst_tok  = hdrs.get("x-ratelimit-reset-tokens")

            if rem_req is not None or lim_req is not None:
                lines.append("📊 **Quota temps réel (fenêtre actuelle) :**")
                if rem_req is not None:
                    lines.append("  " + _format_quota_line("🔢 Requêtes", rem_req, lim_req or "?"))
                if rst_req:
                    lines.append(f"  ⏱ Reset requêtes dans : `{rst_req}`")
                if rem_tok is not None:
                    lines.append("  " + _format_quota_line("🪙 Tokens  ", rem_tok, lim_tok or "?"))
                if rst_tok:
                    lines.append(f"  ⏱ Reset tokens dans   : `{rst_tok}`")
            else:
                lines.append("📊 **Quota :** disponible _(headers non fournis par ce serveur)_")

            # Usage de l'appel test
            try:
                u = completion.usage
                if u:
                    lines.append(f"\n📝 **Tokens ce test :** entrée `{u.prompt_tokens}` + sortie `{u.completion_tokens}` = `{u.total_tokens}`")
            except Exception:
                pass

            pname = p_info["name"]
            dashboards = {
                "openai":   "platform.openai.com/usage",
                "deepseek": "platform.deepseek.com/usage",
                "groq":     "console.groq.com",
            }
            lines.append(f"\n_ℹ️ Quota mensuel/billing : {dashboards.get(provider, 'dashboard du fournisseur')}_")
            return True, "\n".join(lines)

    except Exception as e:
        err_lower = str(e).lower()
        if any(kw in err_lower for kw in ["quota", "rate limit", "429", "resource exhausted",
                                           "too many requests", "exceeded"]):
            return True, "⚠️ Clé valide mais **quota actuellement épuisé** (réessai automatique dans 1h)"
        elif any(kw in err_lower for kw in ["invalid", "unauthorized", "401",
                                             "authentication", "incorrect api key",
                                             "api key not valid", "wrong api key",
                                             "invalid_api_key"]):
            return False, "❌ Clé API **invalide ou incorrecte** — vérifiez la clé dans votre dashboard"
        else:
            return False, f"⚠️ Vérification impossible : `{str(e)[:120]}`"

    return False, "❌ Fournisseur non supporté"

# État saisie de clé API (admin uniquement)
# {user_id: {"provider": "gemini"}}
ai_key_input_state = {}

# État des flux admin interactifs (boutons)
# {user_id: {"action": "grant", "step": "enter_uid", "cid": "...", ...}}
admin_flow_state = {}

# Quota épuisé en mémoire : {("gemini", 0): timestamp_epoch}
ai_quota_exhausted = {}
QUOTA_RESET_SECONDS = 3600  # réessaie après 1 heure

# Client Gemini actif (compatible avec le reste du code)
gemini_client = None


def _load_ai_keys() -> dict:
    """
    Retourne le dict {provider: [key1, key2, ...]} en fusionnant :
      1. Les clés des variables d'environnement (GEMINI_API_KEYS, etc.)
      2. Les clés persistées manuellement dans channels_data.json
    Les doublons sont éliminés ; l'ordre env-vars → JSON est préservé.
    """
    data = load_data()
    saved = data.get("ai_keys", {})

    # Clés env vars par fournisseur
    env_keys = {
        "gemini":   GEMINI_API_KEYS,
        "openai":   OPENAI_API_KEYS,
        "groq":     GROQ_API_KEYS,
        "deepseek": DEEPSEEK_API_KEYS,
    }

    merged = {}
    for provider, env_list in env_keys.items():
        combined = list(env_list)  # priorité env vars
        for k in saved.get(provider, []):
            if k not in combined:
                combined.append(k)
        if combined:
            merged[provider] = combined

    # Fournisseurs ajoutés manuellement (hors des 4 ci-dessus)
    for provider, klist in saved.items():
        if provider not in merged:
            merged[provider] = klist

    return merged


def _save_ai_key(provider: str, key: str):
    """Ajoute ou remplace une clé pour le fournisseur donné."""
    data = load_data()
    ai_keys = data.get("ai_keys", {})
    if provider not in ai_keys:
        ai_keys[provider] = []
    if key not in ai_keys[provider]:
        ai_keys[provider].append(key)
    data["ai_keys"] = ai_keys
    save_data(data)


def _is_quota_ok(provider: str, idx: int) -> bool:
    """Vérifie si la clé n'est pas en quota épuisé."""
    ts = ai_quota_exhausted.get((provider, idx))
    if ts is None:
        return True
    return (datetime.now().timestamp() - ts) > QUOTA_RESET_SECONDS


def _mark_quota_exhausted(provider: str, idx: int):
    """Marque une clé comme quota épuisé."""
    ai_quota_exhausted[(provider, idx)] = datetime.now().timestamp()
    logger.warning(f"⚠️ Quota épuisé pour {provider}[{idx}]")


def _is_quota_error(exc: Exception) -> bool:
    """Détecte une erreur de quota/rate-limit."""
    msg = str(exc).lower()
    quota_keywords = ["quota", "rate limit", "resource exhausted", "429", "too many requests",
                      "exceeded", "limit exceeded", "rateerror"]
    return any(kw in msg for kw in quota_keywords)


def _init_gemini_client(key: str):
    """Crée un client Gemini à partir d'une clé."""
    if google_genai is None:
        return None
    return google_genai.Client(api_key=key)


def _refresh_gemini_client():
    """Met à jour le client Gemini global avec la première clé disponible."""
    global gemini_client
    keys = _load_ai_keys().get("gemini", [])
    for i, k in enumerate(keys):
        if _is_quota_ok("gemini", i):
            gemini_client = _init_gemini_client(k)
            return
    gemini_client = None


# Initialisation au démarrage avec la clé de config.py uniquement
# (_load_ai_keys nécessite load_data défini plus bas — sera chargé au premier appel)
try:
    if GEMINI_API_KEY and google_genai:
        gemini_client = google_genai.Client(api_key=GEMINI_API_KEY)
        logger.info("✅ Assistant IA Gemini initialisé (clé config)")
except Exception as e:
    logger.warning(f"⚠️ Impossible d'initialiser Gemini: {e}")


async def _ai_call_with_fallback(contents: list) -> str:
    """
    Appelle l'IA avec fallback automatique entre fournisseurs et clés.
    Retourne le texte de la réponse, ou None si tout échoue.
    """
    global gemini_client
    all_keys = _load_ai_keys()

    for provider_info in AI_PROVIDERS:
        pcode = provider_info["code"]
        model = provider_info["model"]
        keys = all_keys.get(pcode, [])

        for idx, key in enumerate(keys):
            if not _is_quota_ok(pcode, idx):
                continue

            try:
                if pcode == "gemini":
                    client = _init_gemini_client(key)
                    response = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda c=client, m=model, ct=contents: c.models.generate_content(
                            model=m, contents=ct
                        )
                    )
                    # Mettre à jour le client global si succès
                    gemini_client = client
                    return response.text

                elif pcode in ("openai", "deepseek", "groq") and openai_lib:
                    kwargs = {"api_key": key}
                    if "base_url" in provider_info:
                        kwargs["base_url"] = provider_info["base_url"]
                    oa_client = openai_lib.AsyncOpenAI(**kwargs)
                    # Convertir le format contents Gemini → OpenAI messages
                    messages = []
                    for item in contents:
                        role = "assistant" if item.get("role") == "model" else item.get("role", "user")
                        text = "".join(part.get("text", "") for part in item.get("parts", []))
                        messages.append({"role": role, "content": text})

                    completion = await oa_client.chat.completions.create(
                        model=model,
                        messages=messages
                    )
                    return completion.choices[0].message.content

            except Exception as e:
                if _is_quota_error(e):
                    _mark_quota_exhausted(pcode, idx)
                    logger.warning(f"Quota épuisé {pcode}[{idx}], essai suivant…")
                    continue
                else:
                    logger.error(f"Erreur IA {pcode}[{idx}]: {e}")
                    continue

    return None


async def _notify_admins_quota_exhausted(bot):
    """Notifie les admins que tous les quotas sont épuisés."""
    all_keys = _load_ai_keys()
    providers_info = []
    for p in AI_PROVIDERS:
        keys = all_keys.get(p["code"], [])
        if keys:
            providers_info.append(f"• {p['name']} ({len(keys)} clé(s))")

    providers_str = "\n".join(providers_info) if providers_info else "• Aucune clé configurée"
    msg = (
        "🚨 **Alerte : Quotas IA épuisés**\n\n"
        "Tous les quotas des clés API IA sont épuisés :\n"
        f"{providers_str}\n\n"
        "➡️ Utilisez `/setaikey` pour ajouter de nouvelles clés API.\n"
        "_Les quotas se réinitialisent automatiquement après 1 heure._"
    )
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, msg, parse_mode="Markdown")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════
# CONSTANTES PAIEMENT
# ═══════════════════════════════════════════════════════════════
PRICE_PER_DAY_FCFA = 1000   # 1 000 FCFA = 1 jour (50 USD = 30 000 FCFA = 30 jours)
USD_TO_FCFA = 600            # 1 USD = 600 FCFA
EUR_TO_FCFA = 655            # 1 EUR = 655 FCFA (taux fixe XOF)
GBP_TO_FCFA = 760            # 1 GBP ≈ 760 FCFA
CAD_TO_FCFA = 440            # 1 CAD ≈ 440 FCFA
CHF_TO_FCFA = 660            # 1 CHF ≈ 660 FCFA

# État des utilisateurs en attente d'une capture de paiement
# Nouveau flux: étape 1 = choix du canal, étape 2 = screenshot
# {user_id: {"step": "screenshot", "channel_id": str, "channel_name": str, ...}}
payment_state = {}

# État des demandes de bonus en attente d'approbation admin
# {user_id: {"channel_id": str, "channel_name": str, "user_name": str}}
bonus_state = {}
bonus_msg_state = {}   # {user_id: {"cid": ..., "ch_name": ..., "step": "typing"}}

# Liens d'invitation en attente de confirmation admin
# {(cid, uid_str): invite_link_str}
pending_invites = {}

# Utilisateurs actuellement en mode assistance IA
# {user_id: True}
assistance_mode = {}

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


extra_admins: set = set()  # admins ajoutés dynamiquement (persistés en JSON)


def is_admin(user_id):
    return user_id in ADMINS or user_id in extra_admins


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
            "default_duration_hours": 24,
            "members": {},
            "blocked": {}
        }
    ch = data["channels"][cid]
    if "blocked" not in ch:
        ch["blocked"] = {}
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
        [InlineKeyboardButton("⏱ 24h", callback_data=f"grant_{cid}_{uid}_24"),
         InlineKeyboardButton("⏱ 48h", callback_data=f"grant_{cid}_{uid}_48"),
         InlineKeyboardButton("⏱ 72h", callback_data=f"grant_{cid}_{uid}_72")],
        [InlineKeyboardButton(
            f"⏱ Défaut ({default_hours}h)",
            callback_data=f"grant_{cid}_{uid}_{default_hours}"
        )],
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
- Crypto: BNB (Binance Smart Chain) et TRX (Tron)

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
     → Crypto au choix (propose les deux options) :
       • BNB (Binance Smart Chain) : 0x13108641DcfaBea3b2e8dEd4d35B8f49606f5A17
       • TRX (Tron) : TZ91vunM8NgV6gG6JURe2HeWiMvhWjv8pZ
     → NE JAMAIS montrer le lien MoneyFusion
3. EXCEPTION : Si l'utilisateur demande EXPLICITEMENT la crypto (même en Afrique) → propose les deux adresses :
   • BNB : 0x13108641DcfaBea3b2e8dEd4d35B8f49606f5A17
   • TRX : TZ91vunM8NgV6gG6JURe2HeWiMvhWjv8pZ
4. Ne jamais montrer les deux méthodes (MoneyFusion + crypto) ensemble pour la même région.

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

async def ai_reply(user_id: int, user_message: str, bot=None) -> str:
    """Génère une réponse IA avec fallback automatique entre fournisseurs."""
    all_keys = _load_ai_keys()
    has_any_key = any(all_keys.get(p["code"]) for p in AI_PROVIDERS)

    if not has_any_key:
        return (
            "👋 Bonjour! Je suis le bot de gestion d'accès.\n\n"
            "Contactez un administrateur pour obtenir l'accès aux canaux privés."
        )

    uid = str(user_id)
    history = conversation_history.get(uid, [])

    contents = [
        {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
        {"role": "model", "parts": [{"text": "Bien compris, je suis prêt à aider."}]}
    ]
    contents.extend(history)
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    reply_text = await _ai_call_with_fallback(contents)

    if reply_text is None:
        # Tous les quotas sont épuisés
        if bot:
            asyncio.create_task(_notify_admins_quota_exhausted(bot))
        return (
            "⚠️ Le service IA est temporairement indisponible (quota épuisé).\n"
            "Veuillez contacter un administrateur."
        )

    # Sauvegarder l'historique (max 20 messages)
    history.append({"role": "user", "parts": [{"text": user_message}]})
    history.append({"role": "model", "parts": [{"text": reply_text}]})
    conversation_history[uid] = history[-20:]

    return reply_text


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages texte en chat privé"""
    user = update.effective_user
    if not user:
        return

    text = update.message.text
    if not text:
        return

    # 1. Intercepter l'auth Telethon (admin uniquement)
    if is_admin(user.id) and user.id in telethon_manager.auth_state:
        msg, auth_done = await telethon_manager.process_auth_step(user.id, text)
        await update.message.reply_text(msg, parse_mode="Markdown")
        if auth_done:
            session_str = await telethon_manager.get_session_string()
            await save_telethon_session(session_str, context, user.id)
        return

    # 2. Intercepter la saisie d'une clé API IA (admin uniquement)
    if is_admin(user.id) and user.id in ai_key_input_state:
        state = ai_key_input_state.pop(user.id)
        provider = state["provider"]
        new_key = text.strip()
        provider_name = next((p["name"] for p in AI_PROVIDERS if p["code"] == provider), provider)

        # Validation du format de la clé
        fmt_ok, fmt_err = _validate_key_format(provider, new_key)
        if not fmt_ok:
            await update.message.reply_text(
                f"❌ **Format de clé incorrect**\n\n{fmt_err}\n\n"
                f"Réessayez avec `/setaikey`.",
                parse_mode="Markdown"
            )
            return

        # Informer que la vérification est en cours
        checking_msg = await update.message.reply_text(
            f"🔄 **Vérification de la clé {provider_name}…**\n\nTest du quota en cours, merci de patienter.",
            parse_mode="Markdown"
        )

        # Tester la clé (quota check)
        test_ok, test_status = await _test_ai_key(provider, new_key)

        if not test_ok:
            await checking_msg.edit_text(
                f"❌ **Clé refusée — {provider_name}**\n\n{test_status}\n\n"
                f"Vérifiez votre clé et réessayez avec `/setaikey`.",
                parse_mode="Markdown"
            )
            return

        # Sauvegarder la clé
        _save_ai_key(provider, new_key)

        # Réinitialiser les quotas épuisés pour ce fournisseur
        keys_to_clear = [k for k in ai_quota_exhausted if k[0] == provider]
        for k in keys_to_clear:
            del ai_quota_exhausted[k]

        # Rafraîchir le client Gemini si c'est Gemini
        if provider == "gemini":
            _refresh_gemini_client()

        all_keys = _load_ai_keys()
        nb_keys = len(all_keys.get(provider, []))
        await checking_msg.edit_text(
            f"✅ **Clé {provider_name} ajoutée avec succès!**\n\n"
            f"{test_status}\n"
            f"🔑 {nb_keys} clé(s) configurée(s) pour {provider_name}.\n\n"
            f"L'assistant utilisera automatiquement cette clé avec fallback automatique.",
            parse_mode="Markdown"
        )
        return

    # 3. Intercepter saisie texte du flux admin interactif
    if is_admin(user.id) and user.id in admin_flow_state:
        state = admin_flow_state[user.id]
        raw = text.strip()
        action = state.get("action")
        step   = state.get("step")

        if action == "grant" and step == "enter_uid":
            try:
                uid = str(int(raw))
            except ValueError:
                await update.message.reply_text("❌ ID invalide. Envoyez uniquement l'identifiant numérique Telegram.", parse_mode="Markdown")
                return
            cid = state["cid"]
            ch_name = state.get("ch_name", cid)
            admin_flow_state.pop(user.id, None)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱ 24h", callback_data=f"fl_gr_{cid}_{uid}_24"),
                 InlineKeyboardButton("⏱ 48h", callback_data=f"fl_gr_{cid}_{uid}_48"),
                 InlineKeyboardButton("⏱ 72h", callback_data=f"fl_gr_{cid}_{uid}_72")],
                [InlineKeyboardButton("🔙 Menu principal", callback_data="adm_menu")],
            ])
            await update.message.reply_text(
                f"✅ *Accorder accès — {ch_name}*\n\n👤 Utilisateur: `{uid}`\n\nChoisissez la durée :",
                reply_markup=kb, parse_mode="Markdown"
            )
            return

        elif action == "bonus" and step == "enter_uid":
            try:
                uid = str(int(raw))
            except ValueError:
                await update.message.reply_text("❌ ID invalide. Envoyez uniquement l'identifiant numérique Telegram.", parse_mode="Markdown")
                return
            cid = state["cid"]
            ch_name = state.get("ch_name", cid)
            admin_flow_state.pop(user.id, None)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱ 24h", callback_data=f"fl_bn_{cid}_{uid}_24"),
                 InlineKeyboardButton("⏱ 48h", callback_data=f"fl_bn_{cid}_{uid}_48"),
                 InlineKeyboardButton("⏱ 72h", callback_data=f"fl_bn_{cid}_{uid}_72")],
                [InlineKeyboardButton("🔙 Menu principal", callback_data="adm_menu")],
            ])
            await update.message.reply_text(
                f"🎁 *Bonus — {ch_name}*\n\n👤 Utilisateur: `{uid}`\n\nChoisissez la durée :",
                reply_markup=kb, parse_mode="Markdown"
            )
            return

        elif action == "addadmin" and step == "enter_id":
            try:
                new_id = int(raw)
            except ValueError:
                await update.message.reply_text("❌ ID invalide. Envoyez uniquement l'identifiant numérique.", parse_mode="Markdown")
                return
            admin_flow_state.pop(user.id, None)
            if new_id in extra_admins or new_id in ADMINS:
                await update.message.reply_text(f"ℹ️ L'utilisateur `{new_id}` est déjà administrateur.", parse_mode="Markdown")
                return
            d2 = load_data()
            lst = d2.get("extra_admins", [])
            lst.append(new_id)
            d2["extra_admins"] = lst
            save_data(d2)
            extra_admins.add(new_id)
            await update.message.reply_text(
                f"✅ *Administrateur ajouté!*\n\n🆔 ID: `{new_id}`\n\nIl peut maintenant utiliser toutes les commandes admin.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principal", callback_data="adm_menu")]]),
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(new_id, "✅ *Vous avez été ajouté comme administrateur!*\n\nTapez /start pour voir le menu.", parse_mode="Markdown")
            except Exception:
                pass
            return

        return  # état inconnu, on ignore

    # 4. Intercepter le message de demande de bonus (utilisateur ayant déjà utilisé son bonus)
    if user.id in bonus_msg_state and bonus_msg_state[user.id].get("step") == "typing":
        state = bonus_msg_state.pop(user.id)
        cid = state["cid"]
        ch_name = state["ch_name"]
        msg_text = text.strip()

        if len(msg_text) < 20:
            # Message trop court → redemander
            bonus_msg_state[user.id] = state  # remettre l'état
            await update.message.reply_text(
                "❌ Votre message est trop court.\n\n"
                "Développez votre demande avec des arguments sérieux.\n"
                "_Rédigez un message plus convaincant:_",
                parse_mode="Markdown"
            )
            return

        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username_str = f"@{user.username}" if user.username else "N/A"

        # Confirmer à l'utilisateur
        await update.message.reply_text(
            "✅ *Votre message a été transmis à l'administrateur.*\n\n"
            "Vous serez notifié de la réponse.\n\n"
            "_Conseil: s'il n'y a pas de réponse rapide, l'administrateur a peut-être "
            "jugé votre demande non convaincante. Pensez à souscrire un abonnement via /payer_",
            parse_mode="Markdown"
        )

        # Envoyer aux admins avec boutons d'approbation
        approve_keyboard = [
            [InlineKeyboardButton("✅ Accorder 24h", callback_data=f"bapprove_{user.id}_{cid}_24"),
             InlineKeyboardButton("✅ Accorder 72h", callback_data=f"bapprove_{user.id}_{cid}_72")],
            [InlineKeyboardButton("✅ Accorder 7 jours", callback_data=f"bapprove_{user.id}_{cid}_168"),
             InlineKeyboardButton("✅ Accorder 1 mois", callback_data=f"bapprove_{user.id}_{cid}_720")],
            [InlineKeyboardButton("❌ Refuser", callback_data=f"bdeny_{user.id}_{cid}")],
        ]
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"✉️ *Demande d'accès — Bonus épuisé*\n\n"
                    f"👤 Utilisateur: *{full_name}* ({username_str})\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"📢 Canal: *{ch_name}*\n\n"
                    f"📝 *Message de l'utilisateur:*\n"
                    f"_{msg_text}_\n\n"
                    f"Accordez-vous l'accès?",
                    reply_markup=InlineKeyboardMarkup(approve_keyboard),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Notif bonus_msg à admin {admin_id}: {e}")
        return

    # 5. Si l'utilisateur est en attente d'une capture de paiement, lui rappeler
    if user.id in payment_state and payment_state[user.id].get("step") == "screenshot":
        await update.message.reply_text(
            "📸 Envoyez la **capture d'écran** de votre paiement (une image).",
            parse_mode="Markdown"
        )
        return

    # 4. L'IA ne répond QUE si l'utilisateur est en mode assistance
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

    response = await ai_reply(user.id, text, bot=context.bot)

    # Bouton "Retourner à l'accueil" après chaque réponse
    home_keyboard = [[InlineKeyboardButton("🏠 Retourner à l'accueil", callback_data="home")]]

    await update.message.reply_text(
        response,
        reply_markup=InlineKeyboardMarkup(home_keyboard),
        parse_mode="Markdown"
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
                    [InlineKeyboardButton("⏱ 24h", callback_data=f"setdef_{cid}_24"),
                     InlineKeyboardButton("⏱ 48h", callback_data=f"setdef_{cid}_48")],
                    [InlineKeyboardButton("⏱ 7 jours", callback_data=f"setdef_{cid}_168"),
                     InlineKeyboardButton("⏱ 30 jours", callback_data=f"setdef_{cid}_720")],
                ]
                await context.bot.send_message(
                    admin_id,
                    f"✅ **Bot ajouté au canal!**\n\n"
                    f"📢 **Canal:** {chat.title}\n"
                    f"🆔 **ID:** `{chat.id}`\n\n"
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
        default_hours = ch.get("default_duration_hours", 24)

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

        # Vérifier si c'est un membre payant (déjà enregistré via paiement)
        if uid in ch.get("members", {}):
            # Membre payant — notifier l'admin avec bouton Confirmer pour révoquer le lien
            key = (cid, uid)
            invite_link = pending_invites.get(key, "")
            member_info = ch["members"][uid]
            expires_at = member_info.get("expires_at", 0)
            dur_sec = member_info.get("duration_seconds", 0)
            dur_label = format_duration_label(dur_sec)
            expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M') if expires_at else "?"

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
            # Membre inconnu — demander à l'admin combien de temps accorder
            default_hours = ch.get("default_duration_hours", 24)
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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[0]

    # ── Sélection du fournisseur IA (admin uniquement) ──────────────────
    if action == "aikey":
        user = update.effective_user
        if not is_admin(user.id):
            await query.answer("❌ Accès refusé.", show_alert=True)
            return
        provider_code = "_".join(parts[1:]) if len(parts) > 1 else ""
        if provider_code == "cancel":
            ai_key_input_state.pop(user.id, None)
            await query.edit_message_text("❌ Opération annulée.")
            return
        provider_info = next((p for p in AI_PROVIDERS if p["code"] == provider_code), None)
        if not provider_info:
            await query.edit_message_text("❌ Fournisseur inconnu.")
            return
        ai_key_input_state[user.id] = {"provider": provider_code}
        pattern = _KEY_PATTERNS.get(provider_code, {})
        hint = pattern.get("hint", "clé API valide")
        await query.edit_message_text(
            f"🔑 **{provider_info['name']}**\n\n"
            f"Saisissez votre clé API dans le chat.\n\n"
            f"📋 Format attendu : clé qui {hint}\n\n"
            f"⚠️ La clé sera vérifiée automatiquement avant d'être enregistrée.\n"
            f"Tapez /annuler pour annuler.",
            parse_mode="Markdown"
        )
        return

    # ── Menu administrateur (boutons groupés) ───────────────────────────
    if action == "adm":
        user = update.effective_user
        if not is_admin(user.id):
            await query.answer("❌ Accès refusé.", show_alert=True)
            return

        sub = "_".join(parts[1:]) if len(parts) > 1 else ""
        back_btn = [[InlineKeyboardButton("🔙 Menu principal", callback_data="adm_menu")]]

        if sub == "noop":
            return

        elif sub == "menu":
            data = load_data()
            ai_toggle = data.get("ai_enabled", True)
            await query.edit_message_text(
                _admin_menu_text(ai_toggle),
                reply_markup=_admin_menu_keyboard(ai_toggle),
                parse_mode="Markdown"
            )

        elif sub == "channels":
            data = load_data()
            channels = data.get("channels", {})
            if not channels:
                text = "📢 *Canaux gérés*\n\nAucun canal géré pour l'instant."
            else:
                lines = ["📢 *Canaux gérés:*\n"]
                for cid, ch in channels.items():
                    nb = len(ch.get("members", {}))
                    dur = ch.get("default_duration_hours", 24)
                    lines.append(f"• *{ch.get('name', 'Sans nom')}*\n  ID: `{cid}`\n  👥 {nb} membre(s) | ⏱ Défaut: {dur}h")
                text = "\n".join(lines)
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

        elif sub == "members":
            await query.edit_message_text(
                "👥 *Voir les membres d'un canal*\n\n"
                "Tapez la commande dans le chat :\n"
                "`/members <id_canal>`\n\n"
                "Exemple :\n`/members -1001234567890`",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "extend":
            await query.edit_message_text(
                "⏫ *Rallonger l'accès d'un membre*\n\n"
                "Tapez la commande dans le chat :\n"
                "`/extend <id_canal> <id_user> <heures>`\n\n"
                "Exemple :\n`/extend -1001234567890 987654321 24`",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "grant":
            await query.edit_message_text(
                "✅ *Accorder l'accès à un membre*\n\n"
                "Tapez la commande dans le chat :\n"
                "`/grant <id_canal> <id_user> <heures>`\n\n"
                "Exemple :\n`/grant -1001234567890 987654321 48`",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "remove":
            await query.edit_message_text(
                "❌ *Retirer un membre d'un canal*\n\n"
                "Tapez la commande dans le chat :\n"
                "`/remove <id_canal> <id_user>`\n\n"
                "Exemple :\n`/remove -1001234567890 987654321`",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "unblock":
            await query.edit_message_text(
                "🔓 *Débloquer un membre*\n\n"
                "Tapez la commande dans le chat :\n"
                "`/unblock <id_canal> <id_user>`\n\n"
                "Exemple :\n`/unblock -1001234567890 987654321`",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "setduration":
            await query.edit_message_text(
                "⏱ *Changer la durée par défaut d'un canal*\n\n"
                "Tapez la commande dans le chat :\n"
                "`/setduration <id_canal> <heures>`\n\n"
                "Exemple :\n`/setduration -1001234567890 24`",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "bonus":
            await query.edit_message_text(
                "🎁 *Accorder un accès gratuit (bonus)*\n\n"
                "Tapez la commande dans le chat :\n"
                "`/bonus`\n\n"
                "Le bot vous guidera pour choisir le canal et l'utilisateur.",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "ai_on":
            data = load_data()
            data["ai_enabled"] = True
            save_data(data)
            status = "✅ opérationnel" if gemini_client else "⚠️ activé mais aucune clé configurée"
            await query.edit_message_text(
                f"🤖 *Assistant IA {status}!*\n\nIl répondra automatiquement aux utilisateurs.",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "ai_off":
            data = load_data()
            data["ai_enabled"] = False
            save_data(data)
            await query.edit_message_text(
                "⭕ *Assistant IA désactivé.*\n\nLe bot ne répondra plus automatiquement.",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "setaikey":
            hints = {
                "gemini":   "Format: `AIza...`",
                "openai":   "Format: `sk-...`",
                "deepseek": "Format: `sk-...`",
                "groq":     "Format: `gsk_...`",
            }
            keyboard = []
            for i, p in enumerate(AI_PROVIDERS, start=1):
                keyboard.append([InlineKeyboardButton(f"{i}. {p['name']}", callback_data=f"aikey_{p['code']}")])
            keyboard.append([InlineKeyboardButton("🔙 Menu principal", callback_data="adm_menu")])
            lines = ["🤖 *Configurer une clé API IA*\n", "Choisissez le fournisseur :"]
            for i, p in enumerate(AI_PROVIDERS, start=1):
                h = hints.get(p["code"], "")
                lines.append(f"{i}. *{p['name']}* — {h}")
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif sub == "listaikeys":
            all_keys = _load_ai_keys()
            lines = ["🔑 *Clés API IA configurées:*\n"]
            found_any = False
            for p in AI_PROVIDERS:
                pcode = p["code"]
                keys = all_keys.get(pcode, [])
                if not keys:
                    lines.append(f"*{p['name']}:* _aucune clé_")
                    continue
                found_any = True
                for idx, key in enumerate(keys):
                    masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "***"
                    if _is_quota_ok(pcode, idx):
                        status = "✅ actif"
                    else:
                        ts = ai_quota_exhausted.get((pcode, idx), 0)
                        remaining = max(0, int(QUOTA_RESET_SECONDS - (datetime.now().timestamp() - ts)))
                        status = f"⚠️ épuisé (~{remaining//60}min)"
                    lines.append(f"*{p['name']} [{idx+1}]:* `{masked}` — {status}")
            if not found_any:
                lines.append("\n_Utilisez 🔑 Config clé IA pour ajouter des clés._")
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "checkquota":
            await query.edit_message_text(
                "🔄 *Vérification du quota de toutes les clés…*\n\nMerci de patienter.",
                parse_mode="Markdown"
            )
            all_keys = _load_ai_keys()
            results = []
            for p in AI_PROVIDERS:
                pcode = p["code"]
                keys = all_keys.get(pcode, [])
                if not keys:
                    results.append(f"\n*{p['name']}:* _aucune clé_")
                    continue
                for idx, key in enumerate(keys):
                    masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "***"
                    results.append(f"\n🔑 *{p['name']} [{idx+1}]* (`{masked}`) :")
                    ok, status_text = await _test_ai_key(pcode, key)
                    for line in status_text.split("\n"):
                        if line.strip():
                            results.append(f"  {line}")
            full_msg = "📊 *Rapport de quota IA*\n" + "\n".join(results)
            if len(full_msg) > 4000:
                full_msg = full_msg[:3990] + "\n_(tronqué)_"
            await query.edit_message_text(
                full_msg,
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        elif sub == "admins":
            data = load_data()
            extra = data.get("extra_admins", [])
            lines = ["👑 *Gestion des administrateurs*\n"]
            lines.append("*Super-admins (fixes):*")
            for aid in ADMINS:
                lines.append(f"• `{aid}`")
            if extra:
                lines.append("\n*Admins dynamiques:*")
                for aid in extra:
                    lines.append(f"• `{aid}`")
            else:
                lines.append("\n_Aucun admin dynamique._")
            adm_kb = []
            if user.id in ADMINS:
                adm_kb.append([
                    InlineKeyboardButton("➕ Ajouter admin", callback_data="fl_aa"),
                    InlineKeyboardButton("❌ Retirer admin", callback_data="fl_ra"),
                ])
            adm_kb.extend(back_btn)
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(adm_kb), parse_mode="Markdown"
            )

        elif sub == "help":
            text = (
                "📖 *Aide — Commandes Admin*\n\n"
                "*Canaux:*\n"
                "• `/channels` — Liste des canaux\n"
                "• `/members <id_canal>` — Membres + temps\n"
                "• `/remove <id_canal> <id_user>` — Retirer\n\n"
                "*Durées:*\n"
                "• Boutons: *24h / 48h / 72h / Défaut* (nouveau membre)\n"
                "• `/grant <id_canal> <id_user> <h>` — Accorder\n"
                "• `/extend <id_canal> <id_user> <h>` — Rallonger\n"
                "• `/setduration <id_canal> <h>` — Défaut\n"
                "• `/unblock <id_canal> <id_user>` — Débloquer\n\n"
                "*Administrateurs:*\n"
                "• `/addadmin <id>` — Ajouter un admin\n"
                "• `/removeadmin <id>` — Retirer un admin\n"
                "• `/listadmins` — Voir tous les admins\n\n"
                "*IA:*\n"
                "• `/ai_on` / `/ai_off` — Activer/désactiver\n"
                "• `/setaikey` — Config clé API\n"
                "• `/checkquota` — Vérif. quota\n\n"
                "*Telethon:*\n"
                "• `/connect` — Connecter compte\n"
                "• `/telethon` — Statut\n"
                "• `/scan <id_canal>` — Rescanner\n"
                "• `/disconnect` — Déconnecter"
            )
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )

        return

    # ── Flux interactifs admin (navigation boutons sans commandes) ───────
    if action == "fl":
        user = update.effective_user
        if not is_admin(user.id):
            await query.answer("❌ Accès refusé.", show_alert=True)
            return

        sub = parts[1] if len(parts) > 1 else ""
        params = parts[2:]
        data = load_data()
        channels = data.get("channels", {})
        back_menu = [[InlineKeyboardButton("🔙 Menu principal", callback_data="adm_menu")]]

        def _channel_kbd(action_code: str):
            rows = []
            for cid, ch in channels.items():
                rows.append([InlineKeyboardButton(
                    f"📢 {ch.get('name', cid)}",
                    callback_data=f"fl_{action_code}_{cid}"
                )])
            if not rows:
                return None
            rows.extend(back_menu)
            return InlineKeyboardMarkup(rows)

        def _member_kbd(action_code: str, cid: str, members: dict):
            rows = []
            ct = int(datetime.now().timestamp())
            for uid, info in list(members.items())[:50]:
                exp = info.get("expires_at", 0)
                rem = format_time_remaining(exp - ct) if exp > ct else "Expiré"
                rows.append([InlineKeyboardButton(
                    f"👤 {uid} — {rem}",
                    callback_data=f"fl_{action_code}_{cid}_{uid}"
                )])
            rows.append([InlineKeyboardButton("🔙 Canaux", callback_data=f"fl_{action_code}")])
            rows.extend(back_menu)
            return InlineKeyboardMarkup(rows)

        def _duration_kbd(action_code: str, cid: str, uid: str):
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱ 24h", callback_data=f"fl_{action_code}_{cid}_{uid}_24"),
                 InlineKeyboardButton("⏱ 48h", callback_data=f"fl_{action_code}_{cid}_{uid}_48"),
                 InlineKeyboardButton("⏱ 72h", callback_data=f"fl_{action_code}_{cid}_{uid}_72")],
                [InlineKeyboardButton("🔙 Menu principal", callback_data="adm_menu")],
            ])

        async def _grant_execute(cid, uid, hours, action_label="accordé", bonus=False):
            ch = channels.get(cid, {})
            ct = int(datetime.now().timestamp())
            ds = hours * 3600
            exp = ct + ds
            ch.setdefault("members", {})[uid] = {
                "expires_at": exp, "granted_at": ct, "duration_seconds": ds
            }
            if bonus:
                ch["members"][uid]["bonus"] = True
            ch.setdefault("blocked", {}).pop(uid, None)
            save_data(data)
            dur_lbl = format_duration_label(ds)
            exp_str = datetime.fromtimestamp(exp).strftime('%d/%m/%Y à %H:%M')
            try:
                await context.bot.unban_chat_member(int(cid), int(uid))
            except Exception:
                pass
            invite_link = None
            try:
                inv = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
                invite_link = inv.invite_link
                pending_invites[(cid, uid)] = invite_link
            except Exception as e:
                logger.warning(f"Lien invitation (fl): {e}")
            try:
                icon = "🎁" if bonus else "✅"
                verb = "un accès gratuit" if bonus else "votre accès"
                if invite_link:
                    msg = (f"{icon} *Accès {action_label}!*\n\n"
                           f"📢 Canal: *{ch.get('name', cid)}*\n"
                           f"⏱ Durée: *{dur_lbl}*\n"
                           f"📅 Expire le: {exp_str}\n\n"
                           f"👇 *Cliquez ici pour rejoindre :*\n{invite_link}\n\n"
                           f"⚠️ Lien à usage unique — ne pas partager.")
                else:
                    msg = (f"{icon} *Accès {action_label}!*\n\n"
                           f"📢 Canal: *{ch.get('name', cid)}*\n"
                           f"⏱ Durée: *{dur_lbl}*\n"
                           f"📅 Expire le: {exp_str}")
                await context.bot.send_message(int(uid), msg, parse_mode="Markdown")
            except Exception:
                pass
            return dur_lbl, exp_str, invite_link

        # ── Voir les membres ─────────────────────────────────────────
        if sub == "ms":
            if not params:
                kb = _channel_kbd("ms")
                if not kb:
                    await query.edit_message_text("📢 Aucun canal géré.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text("👥 *Voir les membres — Choisissez un canal :*", reply_markup=kb, parse_mode="Markdown")
            else:
                cid = params[0]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                members = ch.get("members", {})
                ct = int(datetime.now().timestamp())
                if not members:
                    txt = f"📢 *{ch.get('name', cid)}*\n\n_Aucun membre actif._"
                else:
                    lines = [f"📢 *{ch.get('name', cid)}* — {len(members)} membre(s):\n"]
                    for uid, info in members.items():
                        exp = info.get("expires_at", 0)
                        rem = format_time_remaining(exp - ct)
                        lines.append(f"• `{uid}` — ⏱ {rem}")
                    txt = "\n".join(lines)
                await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Canaux", callback_data="fl_ms")],
                    *back_menu
                ]), parse_mode="Markdown")

        # ── Accorder accès ───────────────────────────────────────────
        elif sub == "gr":
            if not params:
                kb = _channel_kbd("gr")
                if not kb:
                    await query.edit_message_text("📢 Aucun canal géré.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text("✅ *Accorder accès — Choisissez un canal :*", reply_markup=kb, parse_mode="Markdown")
            elif len(params) == 1:
                cid = params[0]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                admin_flow_state[user.id] = {"action": "grant", "step": "enter_uid", "cid": cid, "ch_name": ch.get("name", cid)}
                await query.edit_message_text(
                    f"✅ *Accorder accès — {ch.get('name', cid)}*\n\n"
                    f"Envoyez l'*ID Telegram* de l'utilisateur dans le chat.\n\n"
                    f"_(Tapez /annuler pour annuler)_",
                    parse_mode="Markdown"
                )
            elif len(params) == 2:
                cid, uid = params[0], params[1]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text(
                    f"✅ *Accorder accès — {ch.get('name', cid)}*\n\n👤 Utilisateur: `{uid}`\n\nChoisissez la durée :",
                    reply_markup=_duration_kbd("gr", cid, uid), parse_mode="Markdown"
                )
            elif len(params) >= 3:
                cid, uid, h_str = params[0], params[1], params[2]
                hours = int(h_str)
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                dur_lbl, exp_str, inv = await _grant_execute(cid, uid, hours)
                await query.edit_message_text(
                    f"✅ *Accès accordé avec succès!*\n\n"
                    f"📢 Canal: *{ch.get('name', cid)}*\n"
                    f"👤 Utilisateur: `{uid}`\n"
                    f"⏱ Durée: *{dur_lbl}*\n"
                    f"📅 Expire: {exp_str}\n"
                    f"🔗 Lien envoyé: {'✅' if inv else '❌'}",
                    reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                )

        # ── Rallonger l'accès ────────────────────────────────────────
        elif sub == "ex":
            if not params:
                kb = _channel_kbd("ex")
                if not kb:
                    await query.edit_message_text("📢 Aucun canal géré.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text("⏫ *Rallonger — Choisissez un canal :*", reply_markup=kb, parse_mode="Markdown")
            elif len(params) == 1:
                cid = params[0]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                members = ch.get("members", {})
                if not members:
                    await query.edit_message_text(
                        f"📢 *{ch.get('name', cid)}*\n\n_Aucun membre actif._",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Canaux", callback_data="fl_ex")], *back_menu]), parse_mode="Markdown"
                    )
                    return
                await query.edit_message_text(
                    f"⏫ *Rallonger — {ch.get('name', cid)}*\n\nChoisissez un membre :",
                    reply_markup=_member_kbd("ex", cid, members), parse_mode="Markdown"
                )
            elif len(params) == 2:
                cid, uid = params[0], params[1]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                ct = int(datetime.now().timestamp())
                exp = ch.get("members", {}).get(uid, {}).get("expires_at", 0)
                rem = format_time_remaining(exp - ct) if exp > ct else "Expiré"
                await query.edit_message_text(
                    f"⏫ *Rallonger — {ch.get('name', cid)}*\n\n👤 Utilisateur: `{uid}`\n⏳ Temps restant: {rem}\n\nAjoutez combien de temps ?",
                    reply_markup=_duration_kbd("ex", cid, uid), parse_mode="Markdown"
                )
            elif len(params) >= 3:
                cid, uid, h_str = params[0], params[1], params[2]
                hours = int(h_str)
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                ct = int(datetime.now().timestamp())
                member = ch.get("members", {}).get(uid, {})
                cur_exp = member.get("expires_at", ct)
                new_exp = max(cur_exp, ct) + hours * 3600
                if uid in ch.get("members", {}):
                    ch["members"][uid]["expires_at"] = new_exp
                save_data(data)
                exp_str = datetime.fromtimestamp(new_exp).strftime('%d/%m/%Y à %H:%M')
                try:
                    await context.bot.send_message(
                        int(uid),
                        f"✅ *Votre accès a été rallongé!*\n\n📢 Canal: *{ch.get('name', cid)}*\n➕ Ajout: *{hours}h*\n📅 Nouvelle expiration: {exp_str}",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                await query.edit_message_text(
                    f"✅ *Accès rallongé!*\n\n📢 Canal: *{ch.get('name', cid)}*\n👤 Utilisateur: `{uid}`\n➕ Ajout: *{hours}h*\n📅 Nouvelle expiration: {exp_str}",
                    reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                )

        # ── Retirer un membre ────────────────────────────────────────
        elif sub == "rm":
            if not params:
                kb = _channel_kbd("rm")
                if not kb:
                    await query.edit_message_text("📢 Aucun canal géré.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text("❌ *Retirer membre — Choisissez un canal :*", reply_markup=kb, parse_mode="Markdown")
            elif len(params) == 1:
                cid = params[0]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                members = ch.get("members", {})
                if not members:
                    await query.edit_message_text(
                        f"📢 *{ch.get('name', cid)}*\n\n_Aucun membre actif._",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Canaux", callback_data="fl_rm")], *back_menu]), parse_mode="Markdown"
                    )
                    return
                await query.edit_message_text(
                    f"❌ *Retirer — {ch.get('name', cid)}*\n\nChoisissez un membre :",
                    reply_markup=_member_kbd("rm", cid, members), parse_mode="Markdown"
                )
            elif len(params) == 2:
                cid, uid = params[0], params[1]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                try:
                    await context.bot.ban_chat_member(int(cid), int(uid))
                    await context.bot.unban_chat_member(int(cid), int(uid))
                except Exception as e:
                    logger.warning(f"Retrait {uid}: {e}")
                ch.get("members", {}).pop(uid, None)
                save_data(data)
                try:
                    await context.bot.send_message(int(uid), f"⚠️ Vous avez été retiré du canal *{ch.get('name', cid)}*.", parse_mode="Markdown")
                except Exception:
                    pass
                await query.edit_message_text(
                    f"✅ *Membre retiré!*\n\n📢 Canal: *{ch.get('name', cid)}*\n👤 Utilisateur: `{uid}`",
                    reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                )

        # ── Débloquer ────────────────────────────────────────────────
        elif sub == "ub":
            if not params:
                kb = _channel_kbd("ub")
                if not kb:
                    await query.edit_message_text("📢 Aucun canal géré.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text("🔓 *Débloquer — Choisissez un canal :*", reply_markup=kb, parse_mode="Markdown")
            elif len(params) == 1:
                cid = params[0]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                blocked = ch.get("blocked", {})
                if not blocked:
                    await query.edit_message_text(
                        f"📢 *{ch.get('name', cid)}*\n\n_Aucun utilisateur bloqué._",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Canaux", callback_data="fl_ub")], *back_menu]), parse_mode="Markdown"
                    )
                    return
                rows = []
                for uid in list(blocked.keys())[:50]:
                    rows.append([InlineKeyboardButton(f"🚫 {uid}", callback_data=f"fl_ub_{cid}_{uid}")])
                rows.append([InlineKeyboardButton("🔙 Canaux", callback_data="fl_ub")])
                rows.extend(back_menu)
                await query.edit_message_text(
                    f"🔓 *Débloquer — {ch.get('name', cid)}*\n\nChoisissez un utilisateur :",
                    reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown"
                )
            elif len(params) == 2:
                cid, uid = params[0], params[1]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                try:
                    await context.bot.unban_chat_member(int(cid), int(uid))
                except Exception as e:
                    logger.warning(f"Unban {uid}: {e}")
                ch.get("blocked", {}).pop(uid, None)
                save_data(data)
                await query.edit_message_text(
                    f"✅ *Utilisateur débloqué!*\n\n📢 Canal: *{ch.get('name', cid)}*\n👤 ID: `{uid}`",
                    reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                )

        # ── Durée par défaut ─────────────────────────────────────────
        elif sub == "sd":
            if not params:
                kb = _channel_kbd("sd")
                if not kb:
                    await query.edit_message_text("📢 Aucun canal géré.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text("⏱ *Durée défaut — Choisissez un canal :*", reply_markup=kb, parse_mode="Markdown")
            elif len(params) == 1:
                cid = params[0]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                cur = ch.get("default_duration_hours", 24)
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏱ 24h",      callback_data=f"fl_sd_{cid}_24"),
                     InlineKeyboardButton("⏱ 48h",      callback_data=f"fl_sd_{cid}_48"),
                     InlineKeyboardButton("⏱ 72h",      callback_data=f"fl_sd_{cid}_72")],
                    [InlineKeyboardButton("⏱ 1 semaine", callback_data=f"fl_sd_{cid}_168"),
                     InlineKeyboardButton("⏱ 1 mois",   callback_data=f"fl_sd_{cid}_720")],
                    [InlineKeyboardButton("🔙 Canaux", callback_data="fl_sd"), InlineKeyboardButton("🔙 Menu", callback_data="adm_menu")],
                ])
                await query.edit_message_text(
                    f"⏱ *Durée défaut — {ch.get('name', cid)}*\n\nDurée actuelle: *{cur}h*\n\nChoisissez la nouvelle durée :",
                    reply_markup=kb, parse_mode="Markdown"
                )
            elif len(params) == 2:
                cid, h_str = params[0], params[1]
                hours = int(h_str)
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                ch["default_duration_hours"] = hours
                save_data(data)
                await query.edit_message_text(
                    f"✅ *Durée par défaut mise à jour!*\n\n📢 Canal: *{ch.get('name', cid)}*\n⏱ Nouvelle durée: *{hours}h*",
                    reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                )

        # ── Bonus gratuit ────────────────────────────────────────────
        elif sub == "bn":
            if not params:
                kb = _channel_kbd("bn")
                if not kb:
                    await query.edit_message_text("📢 Aucun canal géré.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text("🎁 *Bonus gratuit — Choisissez un canal :*", reply_markup=kb, parse_mode="Markdown")
            elif len(params) == 1:
                cid = params[0]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                admin_flow_state[user.id] = {"action": "bonus", "step": "enter_uid", "cid": cid, "ch_name": ch.get("name", cid)}
                await query.edit_message_text(
                    f"🎁 *Bonus — {ch.get('name', cid)}*\n\n"
                    f"Envoyez l'*ID Telegram* de l'utilisateur dans le chat.\n\n"
                    f"_(Tapez /annuler pour annuler)_",
                    parse_mode="Markdown"
                )
            elif len(params) == 2:
                cid, uid = params[0], params[1]
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                await query.edit_message_text(
                    f"🎁 *Bonus — {ch.get('name', cid)}*\n\n👤 Utilisateur: `{uid}`\n\nChoisissez la durée :",
                    reply_markup=_duration_kbd("bn", cid, uid), parse_mode="Markdown"
                )
            elif len(params) >= 3:
                cid, uid, h_str = params[0], params[1], params[2]
                hours = int(h_str)
                ch = channels.get(cid)
                if not ch:
                    await query.edit_message_text("❌ Canal introuvable.", reply_markup=InlineKeyboardMarkup(back_menu))
                    return
                dur_lbl, exp_str, inv = await _grant_execute(cid, uid, hours, action_label="accordé (bonus)", bonus=True)
                # Marquer le bonus comme utilisé pour cet utilisateur
                data2 = load_data()
                bu = data2.setdefault("bonus_used", [])
                if uid not in [str(x) for x in bu]:
                    bu.append(int(uid))
                    save_data(data2)
                await query.edit_message_text(
                    f"🎁 *Bonus accordé!*\n\n📢 Canal: *{ch.get('name', cid)}*\n👤 Utilisateur: `{uid}`\n⏱ Durée: *{dur_lbl}*\n📅 Expire: {exp_str}\n🔗 Lien envoyé: {'✅' if inv else '❌'}",
                    reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                )

        # ── Ajouter admin ────────────────────────────────────────────
        elif sub == "aa":
            if user.id not in ADMINS:
                await query.answer("❌ Super-admins uniquement.", show_alert=True)
                return
            admin_flow_state[user.id] = {"action": "addadmin", "step": "enter_id"}
            await query.edit_message_text(
                "👑 *Ajouter un administrateur*\n\n"
                "Envoyez l'*ID Telegram* de la personne à promouvoir.\n\n"
                "_(Tapez /annuler pour annuler)_",
                parse_mode="Markdown"
            )

        # ── Retirer admin ────────────────────────────────────────────
        elif sub == "ra":
            if user.id not in ADMINS:
                await query.answer("❌ Super-admins uniquement.", show_alert=True)
                return
            extra_list = list(extra_admins)
            if not params:
                if not extra_list:
                    await query.edit_message_text(
                        "👑 *Admins dynamiques*\n\n_Aucun admin à retirer._",
                        reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                    )
                    return
                rows = [[InlineKeyboardButton(f"❌ Retirer {aid}", callback_data=f"fl_ra_{aid}")] for aid in extra_list]
                rows.extend(back_menu)
                await query.edit_message_text(
                    "👑 *Retirer un admin — Choisissez :*",
                    reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown"
                )
            elif len(params) == 1:
                target_id = int(params[0])
                if target_id in ADMINS:
                    await query.answer("❌ Impossible de retirer un super-admin.", show_alert=True)
                    return
                extra_admins.discard(target_id)
                d2 = load_data()
                lst = d2.get("extra_admins", [])
                if target_id in lst:
                    lst.remove(target_id)
                d2["extra_admins"] = lst
                save_data(d2)
                await query.edit_message_text(
                    f"✅ *Admin retiré.*\n\n🆔 ID: `{target_id}`",
                    reply_markup=InlineKeyboardMarkup(back_menu), parse_mode="Markdown"
                )

        return

    # Accessible à tous les utilisateurs
    if query.data == "assist_start":
        user = update.effective_user
        first_name = user.first_name or "vous"
        # Activer le mode assistance
        assistance_mode[user.id] = True
        # Réinitialiser l'historique pour une nouvelle session
        conversation_history.pop(str(user.id), None)

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
        # Désactiver le mode assistance
        assistance_mode.pop(user.id, None)
        conversation_history.pop(str(user.id), None)

        await query.edit_message_text("✅ Session terminée.")

        # Afficher le menu principal
        user_keyboard = [
            [InlineKeyboardButton("💳 Payer mon abonnement", callback_data="pay_start")],
            [InlineKeyboardButton("🎁 Demander un bonus", callback_data="bonus_start")],
            [InlineKeyboardButton("💬 Assistance", callback_data="assist_start")]
        ]
        await context.bot.send_message(
            user.id,
            f"🏠 **Menu principal**\n\n"
            f"Que souhaitez-vous faire ?\n\n"
            f"• 💳 Payer votre abonnement (**50 USD/mois** ou {PRICE_PER_DAY_FCFA} FCFA/jour)\n"
            f"• 🎁 Demander un accès gratuit (bonus)\n"
            f"• 💬 Contacter l'assistance",
            reply_markup=InlineKeyboardMarkup(user_keyboard),
            parse_mode="Markdown"
        )
        return

    # ── Callbacks accessibles à tous les utilisateurs ─────────────────
    if query.data == "pay_start":
        user = update.effective_user
        data = load_data()
        channels = data.get("channels", {})
        if not channels:
            await query.edit_message_text("ℹ️ Aucun canal disponible pour le moment.\nContactez un administrateur.")
            return
        # Si un seul canal → aller directement à la capture d'écran
        if len(channels) == 1:
            cid = list(channels.keys())[0]
            ch_name = channels[cid].get("name", cid)
            payment_state[user.id] = {"step": "screenshot", "channel_id": cid, "channel_name": ch_name}
            await query.edit_message_text(
                f"💳 **Paiement**\n\n"
                f"📢 Canal: **{ch_name}**\n\n"
                f"📸 Envoyez la **capture d'écran** de votre paiement dans ce chat.\n\n"
                f"Le bot vérifiera automatiquement le montant et activera votre accès immédiatement.\n\n"
                f"💵 Taux: **{PRICE_PER_DAY_FCFA} FCFA = 1 jour** | **50 USD = 1 mois**\n\n"
                f"_Appuyez sur /annuler pour annuler._",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                f"💳 **Paiement — Étape 1/2**\n\n"
                f"Choisissez le **canal** auquel vous souhaitez accéder:",
                reply_markup=_build_payer_channel_keyboard(user.id, channels),
                parse_mode="Markdown"
            )
        return

    if action == "pch":
        payer_uid = int(parts[1])
        cid = "_".join(parts[2:])   # au cas où cid contiendrait un séparateur
        if update.effective_user.id != payer_uid:
            await query.answer("Ce bouton ne vous est pas destiné.", show_alert=True)
            return
        data = load_data()
        if cid not in data.get("channels", {}):
            await query.edit_message_text("❌ Canal introuvable.")
            return
        ch_name = data["channels"][cid].get("name", cid)
        payment_state[payer_uid] = {"step": "screenshot", "channel_id": cid, "channel_name": ch_name}
        await query.edit_message_text(
            f"💳 **Paiement — Étape 2/2**\n\n"
            f"📢 Canal choisi: **{ch_name}**\n\n"
            f"📸 Envoyez maintenant la **capture d'écran** de votre paiement dans ce chat.\n\n"
            f"Le bot vérifiera automatiquement le montant, la devise et que le reçu n'a pas déjà été utilisé, "
            f"puis activera votre accès immédiatement.\n\n"
            f"💵 Taux: **{PRICE_PER_DAY_FCFA} FCFA = 1 jour** | **50 USD = 1 mois**",
            parse_mode="Markdown"
        )
        return

    if action == "paycancel":
        payer_uid = int(parts[1])
        payment_state.pop(payer_uid, None)
        try:
            await query.edit_message_text("❌ Paiement annulé.")
        except Exception:
            pass
        return

    if query.data == "bonus_start":
        user = update.effective_user
        data = load_data()
        channels = data.get("channels", {})
        if not channels:
            await query.edit_message_text("ℹ️ Aucun canal disponible.")
            return

        # ── Vérifier si le bonus a déjà été utilisé ──────────────────
        bonus_used_set = set(str(x) for x in data.get("bonus_used", []))
        if str(user.id) in bonus_used_set:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Payer un abonnement", callback_data="pay_start")],
                [InlineKeyboardButton("✉️ Envoyer un message à l'admin", callback_data=f"bmsg_s_{user.id}")],
                [InlineKeyboardButton("🏠 Menu principal", callback_data="home")],
            ])
            await query.edit_message_text(
                "🚫 *Bonus déjà utilisé*\n\n"
                "Vous avez déjà bénéficié de votre accès gratuit.\n\n"
                "Pour continuer à accéder au canal, vous pouvez :\n"
                "• 💳 Souscrire à un abonnement\n"
                "• ✉️ Envoyer un message convaincant à l'administrateur\n\n"
                "_Notez que l'administrateur n'accepte pas les demandes sans arguments solides._",
                reply_markup=kb,
                parse_mode="Markdown"
            )
            return

        # ── Bonus disponible : choisir le canal ──────────────────────
        keyboard = []
        for cid, ch in channels.items():
            keyboard.append([InlineKeyboardButton(f"📢 {ch.get('name', cid)}", callback_data=f"bch_{user.id}_{cid}")])
        keyboard.append([InlineKeyboardButton("❌ Annuler", callback_data="home")])
        await query.edit_message_text(
            "🎁 *Demande de bonus*\n\nPour quel canal souhaitez-vous demander un accès gratuit?\n\n"
            "_La demande sera envoyée à l'administrateur pour approbation._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # ── Bonus épuisé → sélection canal pour message admin ───────────────
    if action == "bmsg" and len(parts) >= 3 and parts[1] == "s":
        requester_uid = int(parts[2])
        if update.effective_user.id != requester_uid:
            await query.answer("Ce bouton ne vous est pas destiné.", show_alert=True)
            return
        data = load_data()
        channels = data.get("channels", {})
        if not channels:
            await query.edit_message_text("ℹ️ Aucun canal disponible.")
            return
        if len(channels) == 1:
            cid = list(channels.keys())[0]
            ch_name = channels[cid].get("name", cid)
            bonus_msg_state[requester_uid] = {"cid": cid, "ch_name": ch_name, "step": "typing"}
            await query.edit_message_text(
                f"✉️ *Message à l'administrateur*\n\n"
                f"📢 Canal: *{ch_name}*\n\n"
                f"Rédigez ci-dessous votre message de demande d'accès.\n\n"
                f"⚠️ *Conseils importants:*\n"
                f"• Soyez *convaincant* et apportez des arguments solides\n"
                f"• Expliquez *pourquoi* vous méritez cet accès\n"
                f"• Ne dites *jamais* «je n'ai pas d'argent» — ce type de message est systématiquement ignoré\n"
                f"• Sossou Kouamé n'approuve que les messages sérieux avec de vrais arguments\n\n"
                f"_Tapez votre message maintenant:_",
                parse_mode="Markdown"
            )
        else:
            kb = []
            for cid, ch in channels.items():
                kb.append([InlineKeyboardButton(f"📢 {ch.get('name', cid)}", callback_data=f"bmsg_ch_{requester_uid}_{cid}")])
            kb.append([InlineKeyboardButton("❌ Annuler", callback_data="home")])
            await query.edit_message_text(
                "✉️ *Message à l'admin — Choisissez le canal :*",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )
        return

    # ── Bonus épuisé → canal sélectionné → demander le message ─────────
    if action == "bmsg" and len(parts) >= 3 and parts[1] == "ch":
        requester_uid = int(parts[2])
        cid = "_".join(parts[3:])
        if update.effective_user.id != requester_uid:
            await query.answer("Ce bouton ne vous est pas destiné.", show_alert=True)
            return
        data = load_data()
        channels = data.get("channels", {})
        if cid not in channels:
            await query.edit_message_text("❌ Canal introuvable.")
            return
        ch_name = channels[cid].get("name", cid)
        bonus_msg_state[requester_uid] = {"cid": cid, "ch_name": ch_name, "step": "typing"}
        await query.edit_message_text(
            f"✉️ *Message à l'administrateur*\n\n"
            f"📢 Canal: *{ch_name}*\n\n"
            f"Rédigez ci-dessous votre message de demande d'accès.\n\n"
            f"⚠️ *Conseils importants:*\n"
            f"• Soyez *convaincant* et apportez des arguments solides\n"
            f"• Expliquez *pourquoi* vous méritez cet accès\n"
            f"• Ne dites *jamais* «je n'ai pas d'argent» — ce type de message est systématiquement ignoré\n"
            f"• Sossou Kouamé n'approuve que les messages sérieux avec de vrais arguments\n\n"
            f"_Tapez votre message maintenant:_",
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
        approve_keyboard = []
        for h_label, h_val in [("1 jour (24h)", 24), ("3 jours (72h)", 72),
                                 ("7 jours (168h)", 168), ("1 mois (720h)", 720)]:
            approve_keyboard.append([InlineKeyboardButton(
                f"✅ {h_label}", callback_data=f"bapprove_{requester_uid}_{cid}_{h_val}"
            )])
        approve_keyboard.append([InlineKeyboardButton("❌ Refuser", callback_data=f"bdeny_{requester_uid}_{cid}")])

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
        hours = int(parts[3])
        data = load_data()
        if cid not in data.get("channels", {}):
            await query.edit_message_text("❌ Canal introuvable.")
            return
        ch = data["channels"][cid]
        ch_name = ch.get("name", cid)
        current_time = int(datetime.now().timestamp())
        duration_seconds = hours * 3600
        expires_at = current_time + duration_seconds
        ch.setdefault("members", {})[str(requester_uid)] = {
            "expires_at": expires_at,
            "granted_at": current_time,
            "duration_seconds": duration_seconds,
            "bonus": True
        }
        ch.setdefault("blocked", {}).pop(str(requester_uid), None)
        # Marquer le bonus comme utilisé (1 seul bonus par utilisateur)
        bu = data.setdefault("bonus_used", [])
        if str(requester_uid) not in [str(x) for x in bu]:
            bu.append(requester_uid)
        save_data(data)
        try:
            await context.bot.unban_chat_member(int(cid), requester_uid)
        except Exception:
            pass
        bonus_state.pop(requester_uid, None)
        dur_label = format_duration_label(duration_seconds)
        expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M')

        # Générer le lien d'invitation à usage unique
        invite_link = None
        try:
            inv_obj = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
            invite_link = inv_obj.invite_link
            pending_invites[(cid, str(requester_uid))] = invite_link
        except Exception as e:
            logger.warning(f"Lien bonus ({cid}): {e}")

        # Envoyer la notification + lien à l'utilisateur
        try:
            if invite_link:
                await context.bot.send_message(
                    requester_uid,
                    f"🎁 *Accès bonus approuvé!*\n\n"
                    f"📢 Canal: *{ch_name}*\n"
                    f"⏱ Durée: *{dur_label}*\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"👇 *Cliquez ici pour rejoindre le canal:*\n{invite_link}\n\n"
                    f"⚠️ Ce lien est à usage unique — ne le partagez pas.",
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    requester_uid,
                    f"🎁 *Accès bonus approuvé!*\n\n"
                    f"📢 Canal: *{ch_name}*\n"
                    f"⏱ Durée: *{dur_label}*\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"✅ Votre accès est activé.\n"
                    f"_(Lien indisponible — contactez l'admin si nécessaire)_",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.warning(f"Envoi notif bonus user {requester_uid}: {e}")

        admin_name = update.effective_user.first_name or "Admin"
        link_status = "✅ Lien envoyé" if invite_link else "⚠️ Lien non généré"
        await query.edit_message_text(
            f"🎁 *Bonus accordé par {admin_name}*\n\n"
            f"🆔 Utilisateur: `{requester_uid}`\n"
            f"📢 Canal: *{ch_name}*\n"
            f"⏱ Durée: *{dur_label}*\n"
            f"📅 Expire le: {expire_str}\n"
            f"🔗 {link_status}",
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
                f"Pour accéder au canal, effectuez un paiement via /payer",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await query.edit_message_text(
            f"❌ Demande de `{requester_uid}` refusée pour **{ch_name}**.",
            parse_mode="Markdown"
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

    if action == "setdef":
        cid = parts[1]
        hours = int(parts[2])
        data = load_data()
        if cid in data.get("channels", {}):
            data["channels"][cid]["default_duration_hours"] = hours
            ch_name = data["channels"][cid].get("name", cid)
            save_data(data)
            dur = f"{hours//24}j" if hours >= 24 else f"{hours}h"
            await query.edit_message_text(
                f"✅ **Durée par défaut mise à jour!**\n\n"
                f"📢 Canal: {ch_name}\n"
                f"⏱ Durée: {dur}",
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
        invite_link = None
        try:
            await context.bot.unban_chat_member(int(cid), int(uid))
        except Exception:
            pass
        try:
            invite_obj = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
            invite_link = invite_obj.invite_link
            pending_invites[(cid, uid)] = invite_link
        except Exception as e:
            logger.warning(f"Impossible de créer le lien d'invitation (grant) pour {cid}: {e}")
            for admin_id in ADMINS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"⚠️ *Lien d'invitation impossible pour* `{ch.get('name', cid)}`\n\n"
                        f"Le bot n'est pas administrateur de ce canal.\n"
                        f"👤 Utilisateur: `{uid}` doit recevoir son lien manuellement.\n\n"
                        f"➡️ Ajoutez le bot comme admin dans le canal `{ch.get('name', cid)}` puis réessayez.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

        try:
            if invite_link:
                user_msg = (
                    f"✅ **Accès accordé!**\n\n"
                    f"📢 Canal: **{ch['name']}**\n"
                    f"⏱ Durée: **{dur_label}**\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"👇 **Cliquez sur ce lien pour rejoindre le canal :**\n"
                    f"{invite_link}\n\n"
                    f"⚠️ Ce lien est à usage unique — ne le partagez pas."
                )
            else:
                user_msg = (
                    f"✅ **Accès accordé!**\n\n"
                    f"📢 Canal: **{ch['name']}**\n"
                    f"⏱ Durée: **{dur_label}**\n"
                    f"📅 Expire le: {expire_str}\n\n"
                    f"⚠️ Votre accès sera automatiquement retiré à expiration."
                )
            await context.bot.send_message(int(uid), user_msg, parse_mode="Markdown")
        except Exception:
            pass

        await query.edit_message_text(
            f"✅ **Accès accordé!**\n\n"
            f"🆔 Utilisateur: `{uid}`\n"
            f"⏱ Durée: **{dur_label}**\n"
            f"📅 Expire: {expire_str}\n"
            f"🔗 Lien envoyé: {'Oui' if invite_link else 'Non (erreur)'}",
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
        # paychan_{user_id}_{cid}
        payer_uid = int(parts[1])
        cid = parts[2]
        state = payment_state.get(payer_uid, {})

        if state.get("step") != "channel":
            await query.edit_message_text("❌ Session expirée. Recommencez avec /payer")
            return

        hours = state["hours"]
        amount_str = state["amount_str"]
        amount_fcfa = state["amount_fcfa"]
        photo_file_id = state.get("photo_file_id")

        data = load_data()
        if cid not in data.get("channels", {}):
            await query.edit_message_text("❌ Canal introuvable.")
            payment_state.pop(payer_uid, None)
            return

        ch = data["channels"][cid]
        current_time = int(datetime.now().timestamp())
        duration_seconds = hours * 3600
        expires_at = current_time + duration_seconds

        ch.setdefault("members", {})[str(payer_uid)] = {
            "expires_at": expires_at,
            "granted_at": current_time,
            "duration_seconds": duration_seconds
        }
        ch.setdefault("blocked", {}).pop(str(payer_uid), None)
        save_data(data)

        dur_label = format_duration_label(duration_seconds)
        expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M')

        # Débloquer si banni
        try:
            await context.bot.unban_chat_member(int(cid), payer_uid)
        except Exception:
            pass

        # Confirmer à l'utilisateur
        await query.edit_message_text(
            f"🎉 **Accès activé avec succès!**\n\n"
            f"📢 Canal: **{ch['name']}**\n"
            f"💰 Montant payé: **{amount_str}**\n"
            f"⏱ Durée: **{dur_label}**\n"
            f"📅 Expire le: {expire_str}\n\n"
            f"✅ Vous pouvez maintenant rejoindre le canal.",
            parse_mode="Markdown"
        )

        payment_state.pop(payer_uid, None)

        # Notifier les admins
        user = update.effective_user
        if photo_file_id:
            await notify_admins_payment(
                context, user, cid, ch["name"], amount_str, hours, photo_file_id
            )


# ═══════════════════════════════════════════════════════════════
# COMMANDES ADMIN
# ═══════════════════════════════════════════════════════════════

def _admin_menu_keyboard(ai_toggle: bool) -> InlineKeyboardMarkup:
    """Construit le clavier du menu admin avec boutons groupés."""
    ia_lbl = "🔴 Désactiver IA" if ai_toggle else "🟢 Activer IA"
    ia_cb  = "adm_ai_off"      if ai_toggle else "adm_ai_on"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━━ 👥 Gestion Membres ━━━", callback_data="adm_noop")],
        [InlineKeyboardButton("📢 Canaux",         callback_data="adm_channels"),
         InlineKeyboardButton("👥 Membres",        callback_data="fl_ms")],
        [InlineKeyboardButton("✅ Accorder accès", callback_data="fl_gr"),
         InlineKeyboardButton("⏫ Rallonger",      callback_data="fl_ex")],
        [InlineKeyboardButton("❌ Retirer membre", callback_data="fl_rm"),
         InlineKeyboardButton("🔓 Débloquer",      callback_data="fl_ub")],
        [InlineKeyboardButton("━━━ ⚙️ Configuration ━━━",  callback_data="adm_noop")],
        [InlineKeyboardButton("⏱ Durée défaut",   callback_data="fl_sd"),
         InlineKeyboardButton("🎁 Bonus gratuit",  callback_data="fl_bn")],
        [InlineKeyboardButton(ia_lbl,              callback_data=ia_cb),
         InlineKeyboardButton("📊 Vérif. quota",   callback_data="adm_checkquota")],
        [InlineKeyboardButton("🔑 Config clé IA",  callback_data="adm_setaikey"),
         InlineKeyboardButton("📋 Mes clés IA",    callback_data="adm_listaikeys")],
        [InlineKeyboardButton("━━━ 🌐 Général ━━━",        callback_data="adm_noop")],
        [InlineKeyboardButton("👑 Gérer Admins",   callback_data="adm_admins"),
         InlineKeyboardButton("❓ Aide complète",  callback_data="adm_help")],
        [InlineKeyboardButton("💳 Payer",          callback_data="pay_start"),
         InlineKeyboardButton("💬 Assistance",     callback_data="assist_start")],
    ])


def _admin_menu_text(ai_toggle: bool) -> str:
    all_keys = _load_ai_keys()
    has_key = any(all_keys.get(p["code"]) for p in AI_PROVIDERS)
    ia_ok = gemini_client or has_key
    ia_status = "✅ Active" if ia_ok else "❌ Aucune clé"
    ia_state  = "Oui" if ai_toggle else "Non"
    return (
        "👋 *Bienvenue, Administrateur!*\n\n"
        f"🤖 *IA:* {ia_status} | *Activée:* {ia_state}\n\n"
        "_Choisissez une action ci-dessous :_"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_admin(user_id):
        data = load_data()
        ai_toggle = data.get("ai_enabled", True)
        await update.message.reply_text(
            _admin_menu_text(ai_toggle),
            reply_markup=_admin_menu_keyboard(ai_toggle),
            parse_mode="Markdown"
        )
    else:
        user_keyboard = [
            [InlineKeyboardButton("💳 Payer mon abonnement", callback_data="pay_start")],
            [InlineKeyboardButton("🎁 Demander un bonus",    callback_data="bonus_start")],
            [InlineKeyboardButton("💬 Assistance",           callback_data="assist_start")]
        ]
        await update.message.reply_text(
            "👋 *Bienvenue!*\n\n"
            f"• 💳 Abonnement mensuel: *50 USD / mois*\n"
            f"• 💵 Ou: *{PRICE_PER_DAY_FCFA} FCFA / jour*\n"
            f"• 🎁 Vous pouvez demander un accès gratuit (bonus)\n"
            f"• 💬 Contacter l'assistance",
            reply_markup=InlineKeyboardMarkup(user_keyboard),
            parse_mode="Markdown"
        )


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


async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /addadmin <user_id> — ajouter un administrateur (super-admins uniquement)."""
    caller = update.effective_user.id
    if caller not in ADMINS:
        await update.message.reply_text("❌ Seuls les super-administrateurs peuvent ajouter des admins.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/addadmin <user_id>`", parse_mode="Markdown")
        return
    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID invalide. Utilisez un identifiant numérique.")
        return

    data = load_data()
    admins_list = data.get("extra_admins", [])
    if new_admin_id in admins_list or new_admin_id in ADMINS:
        await update.message.reply_text(f"ℹ️ L'utilisateur `{new_admin_id}` est déjà administrateur.", parse_mode="Markdown")
        return
    admins_list.append(new_admin_id)
    data["extra_admins"] = admins_list
    save_data(data)
    extra_admins.add(new_admin_id)
    await update.message.reply_text(
        f"✅ *Administrateur ajouté !*\n\n🆔 ID: `{new_admin_id}`\n\nIl peut maintenant utiliser toutes les commandes admin.",
        parse_mode="Markdown"
    )
    try:
        await context.bot.send_message(
            new_admin_id,
            "✅ *Vous avez été ajouté comme administrateur du bot Baccara!*\n\nTapez /start pour voir le menu.",
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /removeadmin <user_id> — retirer un administrateur (super-admins uniquement)."""
    caller = update.effective_user.id
    if caller not in ADMINS:
        await update.message.reply_text("❌ Seuls les super-administrateurs peuvent retirer des admins.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removeadmin <user_id>`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID invalide. Utilisez un identifiant numérique.")
        return
    if target_id in ADMINS:
        await update.message.reply_text("❌ Impossible de retirer un super-administrateur de base.")
        return

    data = load_data()
    admins_list = data.get("extra_admins", [])
    if target_id not in admins_list:
        await update.message.reply_text(f"ℹ️ L'utilisateur `{target_id}` n'est pas dans la liste des admins.", parse_mode="Markdown")
        return
    admins_list.remove(target_id)
    data["extra_admins"] = admins_list
    save_data(data)
    extra_admins.discard(target_id)
    await update.message.reply_text(
        f"✅ *Administrateur retiré.*\n\n🆔 ID: `{target_id}`",
        parse_mode="Markdown"
    )


async def listadmins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /listadmins — voir tous les administrateurs."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    data = load_data()
    extra = data.get("extra_admins", [])
    lines = ["👑 *Liste des administrateurs:*\n"]
    lines.append("*Super-admins (fixes):*")
    for aid in ADMINS:
        lines.append(f"• `{aid}`")
    if extra:
        lines.append("\n*Admins ajoutés dynamiquement:*")
        for aid in extra:
            lines.append(f"• `{aid}`")
    else:
        lines.append("\n_Aucun admin dynamique ajouté._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def setaikey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /setaikey — choisir le fournisseur IA et saisir la clé API."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    hints = {
        "gemini":   "Format: `AIza...`",
        "openai":   "Format: `sk-...`",
        "deepseek": "Format: `sk-...`",
        "groq":     "Format: `gsk_...`",
    }
    keyboard = []
    for i, p in enumerate(AI_PROVIDERS, start=1):
        keyboard.append([InlineKeyboardButton(
            f"{i}. {p['name']}",
            callback_data=f"aikey_{p['code']}"
        )])
    keyboard.append([InlineKeyboardButton("❌ Annuler", callback_data="aikey_cancel")])

    lines = ["🤖 *Configurer une clé API IA*\n", "Choisissez le fournisseur :"]
    for i, p in enumerate(AI_PROVIDERS, start=1):
        h = hints.get(p["code"], "")
        lines.append(f"{i}. *{p['name']}* — {h}")

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def listaikeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /listaikeys — affiche les clés IA configurées et leur statut."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    all_keys = _load_ai_keys()
    lines = ["🔑 **Clés API IA configurées:**\n"]

    for p in AI_PROVIDERS:
        pcode = p["code"]
        pname = p["name"]
        keys = all_keys.get(pcode, [])
        if not keys:
            lines.append(f"**{pname}:** aucune clé")
            continue
        for idx, key in enumerate(keys):
            masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "***"
            if _is_quota_ok(pcode, idx):
                status = "✅ actif"
            else:
                ts = ai_quota_exhausted.get((pcode, idx), 0)
                remaining = int(QUOTA_RESET_SECONDS - (datetime.now().timestamp() - ts))
                status = f"⚠️ quota épuisé (reset dans ~{remaining//60}min)"
            lines.append(f"**{pname} [{idx+1}]:** `{masked}` — {status}")

    lines.append("\n_Utilisez /setaikey pour ajouter ou /checkquota pour tester en temps réel._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def checkquota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /checkquota — teste toutes les clés configurées et affiche le quota en temps réel."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return

    all_keys = _load_ai_keys()
    has_any = any(all_keys.get(p["code"]) for p in AI_PROVIDERS)
    if not has_any:
        await update.message.reply_text(
            "❌ Aucune clé API configurée.\nUtilisez `/setaikey` pour en ajouter une.",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text(
        "🔄 **Test du quota de toutes les clés…**\n\nMerci de patienter, cela peut prendre quelques secondes.",
        parse_mode="Markdown"
    )

    results = []
    for p in AI_PROVIDERS:
        pcode = p["code"]
        pname = p["name"]
        keys = all_keys.get(pcode, [])
        if not keys:
            results.append(f"**{pname}:** _aucune clé configurée_")
            continue
        for idx, key in enumerate(keys):
            masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "***"
            results.append(f"\n🔑 **{pname} [{idx+1}]** (`{masked}`) :")
            ok, status_text = await _test_ai_key(pcode, key)
            # Indenter chaque ligne du résultat
            for line in status_text.split("\n"):
                if line.strip():
                    results.append(f"  {line}")

    full_msg = "📊 **Rapport de quota IA**\n" + "\n".join(results)

    # Telegram limite les messages à 4096 caractères
    if len(full_msg) > 4000:
        full_msg = full_msg[:3990] + "\n_…(tronqué)_"

    await msg.edit_text(full_msg, parse_mode="Markdown")


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
        default_h = ch.get("default_duration_hours", 24)
        msg += (
            f"📢 **{ch.get('name', cid)}**\n"
            f"   🆔 `{cid}`\n"
            f"   👥 {active} actif(s) | 🔴 {expired} expiré(s)\n"
            f"   ⏱ Défaut: {default_h}h\n\n"
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
            "_Définit la durée par défaut du bouton Défaut._",
            parse_mode="Markdown"
        )
        return

    cid = context.args[0]
    try:
        hours = int(context.args[1])
        if not (1 <= hours <= 750):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Durée invalide. Entrez un nombre entre 1 et 750.")
        return

    data = load_data()
    if cid not in data.get("channels", {}):
        await update.message.reply_text("❌ Canal introuvable.")
        return

    data["channels"][cid]["default_duration_hours"] = hours
    save_data(data)
    await update.message.reply_text(
        f"✅ Durée par défaut mise à jour: **{hours}h** pour **{data['channels'][cid]['name']}**",
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

    try:
        await context.bot.send_message(
            int(uid),
            f"✅ **Accès accordé!**\n\n"
            f"📢 Canal: **{ch['name']}**\n"
            f"⏱ Durée: **{dur_label}**\n"
            f"📅 Expire le: {expire_str}\n\n"
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
        f"📅 Expire: {expire_str}",
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
            await context.bot.unban_chat_member(int(cid), int(uid))
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
        await context.bot.unban_chat_member(int(cid), int(uid))
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
            "• `/payer` — Payer et accéder à un canal\n"
            "• `/bonus` — Demander un accès gratuit\n"
            "• `/start` — Menu principal"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
# SYSTÈME DE PAIEMENT PAR CAPTURE D'ÉCRAN
# ═══════════════════════════════════════════════════════════════

def _parse_amount_robust(value) -> float:
    """Convertit une valeur montant en float, gère virgule européenne et espaces."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    # Format européen: "1 234,56" ou "1.234,56" → enlever séparateurs de milliers
    # Détecter si la virgule est décimale (format européen) ou le point
    s = s.replace(" ", "").replace("\u00a0", "")  # espaces insécables
    if "," in s and "." in s:
        # Ex: "1.234,56" → virgule = décimale
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Ex: "50,00" → virgule = décimale (format français)
        s = s.replace(",", ".")
    # Supprimer tout caractère non numérique sauf le point
    import re as _re
    s = _re.sub(r"[^\d.]", "", s)
    return float(s) if s else 0.0


CURRENCY_TABLE = {
    # Franc CFA et variantes
    "XOF": ("FCFA", 1.0),
    "FCFA": ("FCFA", 1.0),
    "CFA": ("FCFA", 1.0),
    "XAF": ("FCFA", 1.0),
    # Dollar américain
    "USD": ("USD", USD_TO_FCFA),
    "$": ("USD", USD_TO_FCFA),
    "US$": ("USD", USD_TO_FCFA),
    # Euro (France, Europe)
    "EUR": ("EUR", EUR_TO_FCFA),
    "€": ("EUR", EUR_TO_FCFA),
    # Livre sterling
    "GBP": ("GBP", GBP_TO_FCFA),
    "£": ("GBP", GBP_TO_FCFA),
    # Dollar canadien
    "CAD": ("CAD", CAD_TO_FCFA),
    "CA$": ("CAD", CAD_TO_FCFA),
    # Franc suisse
    "CHF": ("CHF", CHF_TO_FCFA),
    # Franc guinéen
    "GNF": ("GNF", 0.1),
    # Franc congolais
    "CDF": ("CDF", 0.0003),
    # Stablecoins (1 USD ≈ 600 FCFA)
    "USDT": ("USDT", USD_TO_FCFA),
    "USDC": ("USDC", USD_TO_FCFA),
    "BUSD": ("BUSD", USD_TO_FCFA),
    "DAI":  ("DAI",  USD_TO_FCFA),
}

# Taux de repli pour les cryptos (mis à jour si CoinGecko répond)
CRYPTO_FALLBACK_FCFA = {
    "BNB":  228000,
    "ETH":  1_200_000,
    "BTC":  48_000_000,
    "TRX":  60,
    "SOL":  90_000,
    "MATIC": 360,
    "ADA":  360,
    "DOGE": 60,
    "XRP":  360,
    "LTC":  30_000,
}

# Map symbole → ID CoinGecko
COINGECKO_IDS = {
    "BNB":  "binancecoin",
    "ETH":  "ethereum",
    "BTC":  "bitcoin",
    "TRX":  "tron",
    "SOL":  "solana",
    "MATIC": "matic-network",
    "ADA":  "cardano",
    "DOGE": "dogecoin",
    "XRP":  "ripple",
    "LTC":  "litecoin",
}

# Cache des prix crypto (symbol → (rate_fcfa, timestamp))
_crypto_cache: dict = {}


async def _get_crypto_rate_fcfa(symbol: str) -> float:
    """Récupère le taux XOF d'une crypto via CoinGecko (cache 30 min)."""
    import time as _time
    import aiohttp as _aiohttp

    symbol = symbol.upper()
    cached = _crypto_cache.get(symbol)
    if cached and _time.time() - cached[1] < 1800:
        return cached[0]

    coin_id = COINGECKO_IDS.get(symbol)
    if not coin_id:
        return float(CRYPTO_FALLBACK_FCFA.get(symbol, 600))

    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        async with _aiohttp.ClientSession() as session:
            async with session.get(url, timeout=_aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json(content_type=None)
        price_usd = float(data[coin_id]["usd"])
        rate = price_usd * USD_TO_FCFA
        _crypto_cache[symbol] = (rate, _time.time())
        logger.info(f"CoinGecko: 1 {symbol} = ${price_usd} = {rate:,.0f} FCFA")
        return rate
    except Exception as e:
        logger.warning(f"CoinGecko erreur pour {symbol}: {e} — fallback utilisé")
        return float(CRYPTO_FALLBACK_FCFA.get(symbol, 600))


OCR_API_KEY = OCR_SPACE_API_KEY or "K86527928888957"


async def _ocr_extract_text(image_bytes: bytes) -> str:
    """Extrait le texte d'une image via l'API OCR.space — multilingue automatique."""
    import base64 as _b64
    import aiohttp as _aiohttp

    b64 = _b64.b64encode(image_bytes).decode()
    payload = {
        "apikey": OCR_API_KEY,
        "language": "auto",
        "isOverlayRequired": "false",
        "base64Image": f"data:image/jpeg;base64,{b64}",
        "OCREngine": "2",
        "scale": "true",
        "detectOrientation": "true"
    }
    url = "https://api.ocr.space/parse/image"
    async with _aiohttp.ClientSession() as session:
        async with session.post(url, data=payload, timeout=_aiohttp.ClientTimeout(total=30)) as resp:
            result = await resp.json(content_type=None)
    if result.get("ParsedResults"):
        return result["ParsedResults"][0].get("ParsedText", "")
    logger.warning(f"OCR.space: pas de résultat — {result.get('ErrorMessage', '')}")
    return ""


_VISION_PROMPT = (
    "You are a payment screenshot analyzer. Analyze this payment/transaction screenshot "
    "and extract the information. The image may be in ANY language (French, English, Russian, "
    "Arabic, Spanish, German, Chinese, Portuguese, Turkish, etc.).\n\n"
    "Return ONLY a valid JSON object with exactly these fields:\n"
    "{\n"
    '  "app": "payment app name (Binance, Wave, PayPal, MoneyFusion, Orange Money, MTN, etc.)",\n'
    '  "montant": 0.04,\n'
    '  "devise": "BNB",\n'
    '  "reference": "unique transaction ID / txid / hash / reference number / invoice number",\n'
    '  "statut": "completed",\n'
    '  "date": "2026-02-20"\n'
    "}\n\n"
    "Extraction rules:\n"
    "- 'montant': positive number only (the sent/paid amount, NOT the fee/commission)\n"
    "- 'devise': currency or crypto symbol (BNB, ETH, TRX, USDT, USDC, USD, EUR, FCFA, XOF, GNF, RUB, etc.)\n"
    "- 'reference': the most unique transaction identifier available "
    "(txid hash / reference UUID / invoice number / order ID). "
    "For crypto: prefer the full txid hash (0x...). "
    "For mobile money: prefer the reference/payment UUID.\n"
    "- 'statut': must be exactly 'completed', 'pending', or 'failed'\n"
    "- 'date': ISO format YYYY-MM-DD if visible, else null\n"
    "- If a field cannot be found, use null\n"
    "- Return ONLY the JSON object. No markdown, no explanation, no code block."
)

# Modèles vision pour chaque fournisseur (compatibles images)
_VISION_MODELS = {
    "gemini":   "gemini-2.0-flash",              # Vision native (gemini-1.5-flash retiré de l'API)
    "openai":   "gpt-4o-mini",                   # Vision via image_url base64
    "groq":     "llama-3.2-11b-vision-preview",  # Vision Llama sur Groq
    # deepseek: pas de vision dans l'API standard → ignoré
}


def _parse_vision_json(raw: str, provider: str) -> dict | None:
    """Parse la réponse JSON d'un modèle vision. Retourne le dict ou None si invalide."""
    import json as _json
    import re as _re
    try:
        raw = raw.strip()
        # Nettoyer les blocs markdown éventuels
        raw = _re.sub(r'^```(?:json)?\s*', '', raw, flags=_re.MULTILINE)
        raw = _re.sub(r'\s*```$', '', raw, flags=_re.MULTILINE)
        raw = raw.strip()
        parsed = _json.loads(raw)
        montant = parsed.get("montant")
        if montant is None or not isinstance(montant, (int, float)) or float(montant) <= 0:
            logger.warning(f"Vision {provider}: montant invalide → {montant}")
            return None
        devise = str(parsed.get("devise") or "XOF").upper().strip()
        reference = str(parsed.get("reference") or "").strip()
        app = str(parsed.get("app") or "Inconnu").strip()
        statut = str(parsed.get("statut") or "unknown").strip()
        date_str = str(parsed.get("date") or "").strip()
        logger.info(f"✅ Vision {provider} OK → {montant} {devise} via {app} ref={reference[:40]}")
        return {
            "app": app,
            "montant": float(montant),
            "devise_raw": devise,
            "reference": reference,
            "statut": statut,
            "date": date_str,
        }
    except Exception as e:
        logger.warning(f"Vision {provider} parse JSON échec: {e} | raw={raw[:100]}")
        return None


async def _ai_analyze_image(image_bytes: bytes) -> dict | None:
    """
    Analyse une image de paiement via TOUS les fournisseurs IA disponibles avec fallback.
    Ordre : Gemini → OpenAI → Groq → (DeepSeek ignoré, pas de vision standard)
    Retourne un dict ou None si tous échouent.
    Gère toutes les langues : français, anglais, russe, arabe, espagnol, allemand, chinois...
    """
    import base64 as _b64
    import asyncio as _asyncio

    b64 = _b64.b64encode(image_bytes).decode()
    all_keys = _load_ai_keys()

    # ── Gemini Vision ───────────────────────────────────────────────────
    gemini_keys = all_keys.get("gemini", [])
    for idx, key in enumerate(gemini_keys):
        if not _is_quota_ok("gemini", idx):
            continue
        if google_genai is None:
            break
        try:
            client = _init_gemini_client(key)
            vision_model = _VISION_MODELS["gemini"]
            contents = [{
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    {"text": _VISION_PROMPT}
                ]
            }]
            loop = _asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda c=client, m=vision_model, ct=contents: c.models.generate_content(
                    model=m, contents=ct
                )
            )
            result = _parse_vision_json(response.text, f"Gemini/{vision_model}")
            if result:
                return result
        except Exception as e:
            if _is_quota_error(e):
                _mark_quota_exhausted("gemini", idx)
                logger.warning(f"Vision Gemini[{idx}] quota épuisé, essai suivant…")
            else:
                logger.warning(f"Vision Gemini[{idx}] erreur: {e}")

    # ── OpenAI Vision (gpt-4o-mini) ─────────────────────────────────────
    openai_keys = all_keys.get("openai", [])
    for idx, key in enumerate(openai_keys):
        if not _is_quota_ok("openai", idx):
            continue
        if openai_lib is None:
            break
        try:
            oa_client = openai_lib.AsyncOpenAI(api_key=key)
            vision_model = _VISION_MODELS["openai"]
            completion = await oa_client.chat.completions.create(
                model=vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
                        {"type": "text", "text": _VISION_PROMPT}
                    ]
                }],
                max_tokens=400
            )
            raw = completion.choices[0].message.content
            result = _parse_vision_json(raw, f"OpenAI/{vision_model}")
            if result:
                return result
        except Exception as e:
            if _is_quota_error(e):
                _mark_quota_exhausted("openai", idx)
                logger.warning(f"Vision OpenAI[{idx}] quota épuisé, essai suivant…")
            else:
                logger.warning(f"Vision OpenAI[{idx}] erreur: {e}")

    # ── Groq Vision (llama-3.2-11b-vision-preview) ──────────────────────
    groq_keys = all_keys.get("groq", [])
    for idx, key in enumerate(groq_keys):
        if not _is_quota_ok("groq", idx):
            continue
        if openai_lib is None:
            break
        try:
            groq_info = next(p for p in AI_PROVIDERS if p["code"] == "groq")
            oa_client = openai_lib.AsyncOpenAI(
                api_key=key,
                base_url=groq_info.get("base_url", "https://api.groq.com/openai/v1")
            )
            vision_model = _VISION_MODELS["groq"]
            completion = await oa_client.chat.completions.create(
                model=vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": _VISION_PROMPT}
                    ]
                }],
                max_tokens=400
            )
            raw = completion.choices[0].message.content
            result = _parse_vision_json(raw, f"Groq/{vision_model}")
            if result:
                return result
        except Exception as e:
            if _is_quota_error(e):
                _mark_quota_exhausted("groq", idx)
                logger.warning(f"Vision Groq[{idx}] quota épuisé, essai suivant…")
            else:
                logger.warning(f"Vision Groq[{idx}] erreur: {e}")

    logger.warning("Vision: tous les fournisseurs ont échoué → secours OCR")
    return None


# Alias de compatibilité (ancienne référence interne)
_gemini_analyze_image = _ai_analyze_image


def _parse_payment_text(text: str) -> dict:
    """Parse le texte OCR pour extraire montant, devise, référence et application."""
    import re as _re

    t = text.upper()

    # ── Nettoyer les lignes cassées (Txid Binance souvent coupé en 2-3 lignes) ──
    # Rejoindre les fragments hexadécimaux consécutifs
    t_joined = _re.sub(r'(0X[0-9A-F]+)\s*\n\s*([0-9A-F]+)', r'\1\2', t)
    if t_joined != t:
        t = t_joined

    # ── Détecter l'application de paiement (multilingue) ───────────────
    app_map = {
        # Crypto exchanges
        "BINANCE": "Binance", "TRUST WALLET": "Trust Wallet", "TRUSTWALLET": "Trust Wallet",
        "COINBASE": "Coinbase", "KUCOIN": "KuCoin", "BYBIT": "Bybit",
        "CRYPTO.COM": "Crypto.com", "METAMASK": "MetaMask", "OKEX": "OKX", "OKX": "OKX",
        "KRAKEN": "Kraken", "GATE.IO": "Gate.io", "HUOBI": "Huobi",
        # Mobile money Afrique
        "WAVE": "Wave", "ORANGE MONEY": "Orange Money", "MTN MONEY": "MTN Money",
        "MONEYFUSION": "MoneyFusion", "MONEY FUSION": "MoneyFusion",
        "MOOV": "Moov Money", "FLOOZ": "Flooz", "AIRTEL": "Airtel Money",
        "TMONEY": "T-Money", "FREE MONEY": "Free Money", "YUP": "Yup",
        "CINETPAY": "CinetPay", "KKIAPAY": "KKiaPay", "FEDAPAY": "FedaPay",
        # International
        "PAYPAL": "PayPal", "REVOLUT": "Revolut", "WISE": "Wise",
        "CASHAPP": "CashApp", "CASH APP": "CashApp", "VENMO": "Venmo",
        "LYDIA": "Lydia", "SUMERIA": "Sumeria", "WESTERN UNION": "Western Union",
        "MONEYGRAM": "MoneyGram", "SKRILL": "Skrill", "NETELLER": "Neteller",
        # Russe / CIS
        "QIWI": "QIWI", "ЮMONEY": "YuMoney", "YUMONEY": "YuMoney",
        "ВЫВОД": "Binance",
    }
    app_name = "Inconnu"
    for kw, name in app_map.items():
        if kw in t:
            app_name = name
            break

    # Liste des symboles crypto supportés
    _CRYPTO = r'(BNB|ETH|BTC|TRX|USDT|USDC|BUSD|DAI|SOL|MATIC|ADA|DOGE|XRP|LTC|TON|AVAX|DOT)'

    # ── Détecter montant + devise ───────────────────────────────────────
    # Mots-clés multilingues pour "montant" (FR/EN/RU/ES/DE/AR/PT/ZH)
    _AMOUNT_KW = (
        r'(?:MONTANT|AMOUNT|СУММА|ИТОГО|TOTAL|SUM|SOMME|MONTO|BETRAG|'
        r'CANTIDAD|IMPORTE|VALOR|IMPORTO|СУММ|كمية|金额|KWOTA)'
    )

    patterns = [
        # ── Crypto : mot-clé + montant + symbole ──
        (_AMOUNT_KW + r'[:\s*]+[-]?(\d+[.,]\d+)\s*' + _CRYPTO, 1, None),
        # Valeur crypto directe (positive ou négative)
        (r'[-]?(\d+[.,]\d{1,8})\s*' + _CRYPTO, 1, None),
        # ── Fiat avec devise explicite ──
        # FCFA/XOF/GNF/CDF — gère séparateurs milliers
        (r'((?:\d{1,3}(?:[\s\xa0,]\d{3})+|\d+)(?:[.,]\d{1,3})?)\s*(FCFA|XOF|GNF|CDF|XAF)', 1, None),
        # Stablecoins
        (r'(\d+[.,]\d{1,4})\s*(USDT|USDC|BUSD|DAI)', 1, None),
        # USD: $50.00 ou 50.00 USD
        (r'\$\s*(\d+[.,]\d{1,2})', 1, 'USD'),
        (r'(\d+[.,]\d{1,2})\s*USD', 1, 'USD'),
        # EUR
        (r'€\s*(\d+[.,]\d{1,2})', 1, 'EUR'),
        (r'(\d+[.,]\d{1,2})\s*EUR', 1, 'EUR'),
        # GBP
        (r'£\s*(\d+[.,]\d{1,2})', 1, 'GBP'),
        (r'(\d+[.,]\d{1,2})\s*GBP', 1, 'GBP'),
        # CAD
        (r'CA\$\s*(\d+[.,]\d{1,2})', 1, 'CAD'),
        (r'(\d+[.,]\d{1,2})\s*CAD', 1, 'CAD'),
        # CHF
        (r'(\d+[.,]\d{1,2})\s*CHF', 1, 'CHF'),
        # RUB (Russian)
        (r'(\d+[.,]\d{1,2})\s*(?:RUB|РУБ|₽)', 1, 'RUB'),
        # TRY (Turkish lira)
        (r'(\d+[.,]\d{1,2})\s*TRY', 1, 'TRY'),
        # ── Fallback mot-clé + nombre ──
        (_AMOUNT_KW + r'[:\s]+(\d+[.,]\d{1,3})', 1, 'XOF'),
        # FCFA seul (nombre avant FCFA sans séparateur milliers)
        (r'(\d{3,}(?:[.,]\d{1,3})?)\s*(FCFA|XOF)', 1, None),
        # Dernier recours : nombre décimal
        (r'(\d+[.,]\d{1,3})', 1, 'XOF'),
    ]

    montant = 0.0
    devise_raw = "XOF"
    for pat, grp, forced_devise in patterns:
        m = _re.search(pat, t)
        if m:
            try:
                raw_num = m.group(grp).replace(' ', '').replace('\xa0', '').replace(',', '.')
                val = float(raw_num)
                if val > 0:
                    montant = val
                    devise_raw = forced_devise if forced_devise else m.group(grp + 1).strip()
                    break
            except (ValueError, IndexError):
                continue

    # ── Détecter la référence / Txid (multilingue) ─────────────────────
    ref_patterns = [
        # Hash crypto complet 0x... (Ethereum/BSC/TRX style) — peut être long
        r'(0[Xx][0-9A-Fa-f]{20,})',
        # Txid après label multilingue (EN/RU/FR/ES/DE)
        r'(?:TXID|TX[\s_]?ID|TRANSACTION[\s_]?(?:ID|HASH)?|HASH|'
        r'ИДЕНТИФИКАТОР|ТРАНСАКЦИЯ|'
        r'REFERENCIA|RÉFÉRENCE?|REFERENCE|'
        r'TRANSAKTION|TRANSAKTIONS[\s_]?ID)'
        r'[\s:]*([0-9A-Z][0-9A-Z\-_]{5,})',
        # UUID format (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) — MoneyFusion, CinetPay, etc.
        r'([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})',
        # Numéro facture / N° / FACT-... / ORDER-...
        r'(?:N[°O][\s.]*(?:FACTURE|FACT)?|FACT(?:URE)?|ORDER[\s_]?(?:ID)?|'
        r'INVOICE[\s_]?(?:NO|ID|#)?|RECHNUNG[\s_]?(?:NR)?)'
        r'[\s:]*([A-Z0-9][A-Z0-9\-_]{4,39})',
        # Référence alphanumérique longue (≥8 chars)
        r'(?:R[ÉE]F(?:ERENCE)?(?:\s+DE\s+PAIEMENT)?|REF)[.:\s]+([A-Z0-9][A-Z0-9\-_]{5,})',
        # ID long purement numérique (≥10 chiffres)
        r'\b([0-9]{10,20})\b',
    ]
    reference = ""
    for rp in ref_patterns:
        rm = _re.search(rp, t)
        if rm:
            candidate = rm.group(1).strip()
            if len(candidate) >= 6:
                reference = candidate
                break

    return {"montant": montant, "devise_raw": devise_raw, "app": app_name, "reference": reference}


async def analyze_payment_screenshot(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Analyse une capture d'écran de paiement.
    Méthode 1 (prioritaire): Gemini Vision — comprend toutes les langues nativement.
    Méthode 2 (secours):     OCR.space + regex multilingue.
    Compatible: Binance, Trust Wallet, PayPal, Wave, Orange Money, MTN, MoneyFusion, etc.
    Devises: BNB, ETH, BTC, TRX, USDT, USDC + USD, EUR, GBP, RUB, FCFA/XOF, GNF, etc.
    """
    import hashlib as _hashlib

    montant = 0.0
    devise_raw = "XOF"
    app_name = "Inconnu"
    reference = ""
    raw_text = ""
    method_used = "?"

    # ══ Méthode 1 : IA Vision (Gemini → OpenAI → Groq, fallback automatique) ═
    ai_result = await _ai_analyze_image(image_bytes)

    if ai_result and ai_result.get("montant", 0) > 0:
        montant = ai_result["montant"]
        devise_raw = ai_result["devise_raw"]
        app_name = ai_result["app"]
        reference = ai_result["reference"]
        method_used = "IA Vision"
        logger.info(f"✅ Analyse IA Vision: {montant} {devise_raw} via {app_name} ref={reference[:40]}")
    else:
        # ══ Méthode 2 : OCR.space + regex (secours) ══════════════════
        logger.info("Gemini Vision indisponible ou échec → secours OCR.space")
        try:
            raw_text = await _ocr_extract_text(image_bytes)
        except Exception as e:
            logger.error(f"OCR.space erreur: {e}")
            return {
                "success": False,
                "details": (
                    "❌ Impossible d'analyser la capture.\n"
                    "Vérifiez que l'image est nette et bien cadrée, puis réessayez."
                )
            }

        if not raw_text.strip():
            return {
                "success": False,
                "details": (
                    "❌ Aucun texte détecté sur la capture.\n"
                    "L'image est peut-être floue, mal cadrée ou trop compressée."
                )
            }

        logger.info(f"OCR extrait: {raw_text[:300]}")
        parsed = _parse_payment_text(raw_text)
        montant = parsed["montant"]
        devise_raw = parsed["devise_raw"]
        app_name = parsed["app"]
        reference = parsed["reference"]
        method_used = "OCR+regex"

        if montant <= 0:
            return {
                "success": False,
                "details": (
                    f"❌ Montant introuvable sur la capture.\n"
                    f"_Texte lu:_ `{raw_text[:200].strip()}`\n\n"
                    "Assurez-vous que le montant est clairement visible."
                )
            }

    # ══ Conversion en FCFA ════════════════════════════════════════════
    _CRYPTO_SYMBOLS = set(CRYPTO_FALLBACK_FCFA.keys()) | {"USDT", "USDC", "BUSD", "DAI", "TON", "AVAX"}

    if devise_raw in _CRYPTO_SYMBOLS:
        rate = await _get_crypto_rate_fcfa(devise_raw)
        devise_label = devise_raw
        amount_fcfa = int(montant * rate)
        crypto_price_str = f"1 {devise_raw} ≈ {rate:,.0f} FCFA"
        amount_str = f"{montant:.6g} {devise_label} → {amount_fcfa:,} FCFA\n💱 _{crypto_price_str}_"
    elif devise_raw in CURRENCY_TABLE:
        devise_label, rate = CURRENCY_TABLE[devise_raw]
        amount_fcfa = int(montant * rate)
        if devise_raw in ("XOF", "FCFA", "CFA", "XAF"):
            devise_label = "FCFA"
            amount_str = f"{amount_fcfa:,} FCFA"
        else:
            amount_str = f"{montant:.2f} {devise_label} → {amount_fcfa:,} FCFA"
    else:
        devise_label = devise_raw
        amount_fcfa = int(montant)
        amount_str = f"{amount_fcfa:,} FCFA"
        logger.warning(f"Devise inconnue '{devise_raw}' → traitée comme FCFA")

    days = amount_fcfa / PRICE_PER_DAY_FCFA
    hours = int(days * 24)

    # ══ Hash anti-doublon ═════════════════════════════════════════════
    hash_input = f"{montant:.6g}|{devise_raw}|{reference}|{app_name}".lower()
    payment_hash = _hashlib.sha256(hash_input.encode()).hexdigest()[:24]

    logger.info(f"💰 Paiement analysé ({method_used}): {amount_str} | hash={payment_hash} | ref={reference[:40]}")

    return {
        "success": True,
        "montant_brut": montant,
        "devise": devise_label,
        "devise_raw": devise_raw,
        "amount_fcfa": amount_fcfa,
        "amount_str": amount_str,
        "days": days,
        "hours": hours,
        "app": app_name,
        "reference": reference,
        "payment_hash": payment_hash,
        "description": f"Paiement de {amount_str} via {app_name}",
        "raw_text": raw_text[:400],
        "method": method_used,
    }


def _build_payer_channel_keyboard(user_id: int, channels: dict) -> InlineKeyboardMarkup:
    """Construit le clavier de sélection de canal pour le paiement."""
    keyboard = []
    for cid, ch in channels.items():
        keyboard.append([InlineKeyboardButton(
            f"📢 {ch.get('name', cid)}",
            callback_data=f"pch_{user_id}_{cid}"
        )])
    keyboard.append([InlineKeyboardButton("❌ Annuler", callback_data=f"paycancel_{user_id}")])
    return InlineKeyboardMarkup(keyboard)


async def payer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /payer — étape 1: choisir le canal (ou direct si 1 seul), puis envoyer la capture"""
    user = update.effective_user
    if not user:
        return

    data = load_data()
    channels = data.get("channels", {})
    if not channels:
        await update.message.reply_text(
            "ℹ️ Aucun canal disponible pour le moment.\nContactez un administrateur."
        )
        return

    if len(channels) == 1:
        cid = list(channels.keys())[0]
        ch_name = channels[cid].get("name", cid)
        payment_state[user.id] = {"step": "screenshot", "channel_id": cid, "channel_name": ch_name}
        await update.message.reply_text(
            f"💳 **Paiement**\n\n"
            f"📢 Canal: **{ch_name}**\n\n"
            f"📸 Envoyez la **capture d'écran** de votre paiement dans ce chat.\n\n"
            f"Le bot vérifiera automatiquement le montant et activera votre accès immédiatement.\n\n"
            f"💵 Taux: **{PRICE_PER_DAY_FCFA} FCFA = 1 jour** | **50 USD = 1 mois**\n\n"
            f"_Tapez /annuler pour annuler._",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"💳 **Paiement — Étape 1/2**\n\n"
            f"Choisissez le **canal** auquel vous souhaitez accéder:",
            reply_markup=_build_payer_channel_keyboard(user.id, channels),
            parse_mode="Markdown"
        )


async def annuler_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /annuler — annule le paiement en cours ou la saisie de clé API"""
    user = update.effective_user
    if not user:
        return
    if user.id in ai_key_input_state:
        ai_key_input_state.pop(user.id)
        await update.message.reply_text("❌ Saisie de clé API annulée.")
    elif user.id in admin_flow_state:
        admin_flow_state.pop(user.id)
        await update.message.reply_text("❌ Opération annulée.")
    elif user.id in bonus_msg_state:
        bonus_msg_state.pop(user.id)
        await update.message.reply_text("❌ Demande de message annulée.")
    elif user.id in payment_state:
        payment_state.pop(user.id)
        await update.message.reply_text("❌ Paiement annulé.")
    else:
        await update.message.reply_text("ℹ️ Aucune opération en cours à annuler.")


async def handle_payment_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Traite la capture d'écran de paiement envoyée par l'utilisateur"""
    user = update.effective_user
    if not user:
        return

    state = payment_state.get(user.id, {})
    if state.get("step") != "screenshot":
        return  # Pas en mode paiement — ignorer

    cid = state.get("channel_id")
    ch_name = state.get("channel_name", "Canal")

    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    await update.message.reply_text(
        f"🔍 Analyse du paiement pour **{ch_name}** en cours...",
        parse_mode="Markdown"
    )

    # Télécharger la photo
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    image_bytes = await photo_file.download_as_bytearray()

    # Analyser avec Gemini Vision
    try:
        result = await analyze_payment_screenshot(bytes(image_bytes))
    except Exception as e:
        error_str = str(e)
        payment_state.pop(user.id, None)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
            await update.message.reply_text(
                "⚠️ **Service temporairement indisponible**\n\n"
                "Le service d'analyse est momentanément saturé. "
                "Veuillez réessayer dans quelques minutes.\n\n"
                "Si le problème persiste, contactez l'administrateur.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "❌ **Erreur lors de l'analyse**\n\n"
                "Une erreur inattendue s'est produite. Veuillez réessayer ou contacter l'administrateur.",
                parse_mode="Markdown"
            )
        logger.error(f"Erreur handle_payment_photo pour user {user.id}: {e}")
        return

    if not result["success"]:
        await update.message.reply_text(
            f"❌ **Impossible de traiter la capture**\n\n"
            f"{result.get('details', 'Montant non détecté.')}\n\n"
            f"Assurez-vous que la capture montre clairement le montant payé et réessayez.",
            parse_mode="Markdown"
        )
        payment_state.pop(user.id, None)
        return

    amount_fcfa = result["amount_fcfa"]
    hours = result["hours"]
    days_text = format_duration_label(hours * 3600)
    payment_hash = result.get("payment_hash", "")
    reference = result.get("reference", "")

    # ── Vérification anti-doublon ──────────────────────────────────────
    data = load_data()
    used_payments = data.setdefault("used_payments", {})
    used_references = data.setdefault("used_references", {})
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    # Chercher le doublon: par hash global OU par référence/txid seule
    prev = None
    dup_reason = ""
    if payment_hash and payment_hash in used_payments:
        prev = used_payments[payment_hash]
        dup_reason = "hash"
    elif reference and reference in used_references:
        prev = used_references[reference]
        dup_reason = f"référence `{reference}`"

    if prev:
        await update.message.reply_text(
            f"🚫 **Reçu déjà utilisé !**\n\n"
            f"Ce reçu de paiement a déjà été enregistré le **{prev.get('date', '?')}**.\n\n"
            f"Si vous pensez qu'il y a une erreur, contactez l'administrateur via /start",
            parse_mode="Markdown"
        )
        payment_state.pop(user.id, None)
        # Notifier l'admin
        for admin_id in ADMINS:
            try:
                await context.bot.send_photo(
                    admin_id,
                    photo=photo.file_id,
                    caption=(
                        f"⚠️ **Tentative de doublon détectée !**\n\n"
                        f"👤 Utilisateur: **{full_name}** (@{user.username or 'N/A'})\n"
                        f"🆔 ID: `{user.id}`\n"
                        f"💰 Montant: {result['amount_str']}\n"
                        f"🔍 Détecté via: {dup_reason}\n"
                        f"📅 Précédent: {prev.get('date', '?')} — user `{prev.get('user_id', '?')}`"
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        return

    # ── Montant insuffisant ────────────────────────────────────────────
    if hours < 1:
        await update.message.reply_text(
            f"⚠️ **Montant insuffisant**\n\n"
            f"💰 Montant détecté: {result['amount_str']}\n"
            f"💵 Minimum requis: **{PRICE_PER_DAY_FCFA} FCFA** (1 jour)\n\n"
            f"Contactez un administrateur si vous pensez qu'il y a une erreur.",
            parse_mode="Markdown"
        )
        payment_state.pop(user.id, None)
        return

    # ── Vérifier que le canal existe toujours ─────────────────────────
    if not cid or cid not in data.get("channels", {}):
        await update.message.reply_text(
            "❌ Canal introuvable. Recommencez avec /payer",
            parse_mode="Markdown"
        )
        payment_state.pop(user.id, None)
        return

    ch = data["channels"][cid]
    current_time = int(datetime.now().timestamp())
    duration_seconds = hours * 3600
    expires_at = current_time + duration_seconds

    # Enregistrer le membre
    ch.setdefault("members", {})[str(user.id)] = {
        "expires_at": expires_at,
        "granted_at": current_time,
        "duration_seconds": duration_seconds
    }
    ch.setdefault("blocked", {}).pop(str(user.id), None)

    # Enregistrer le hash anti-doublon + la référence séparément
    payment_record = {
        "user_id": user.id,
        "date": datetime.now().strftime('%d/%m/%Y %H:%M'),
        "channel": ch_name,
        "amount_str": result["amount_str"],
        "reference": reference
    }
    if payment_hash:
        used_payments[payment_hash] = payment_record
    # Indexer la référence/txid séparément pour détection rapide
    if reference:
        used_references[reference] = payment_record

    save_data(data)

    # Débloquer si banni
    try:
        await context.bot.unban_chat_member(int(cid), user.id)
    except Exception:
        pass

    payment_state.pop(user.id, None)

    expire_str = datetime.fromtimestamp(expires_at).strftime('%d/%m/%Y à %H:%M')
    ref_line = f"🔖 Référence: `{reference}`\n" if reference else ""

    # Générer un lien d'invitation unique (1 seule utilisation)
    invite_link = None
    try:
        invite_obj = await context.bot.create_chat_invite_link(int(cid), member_limit=1)
        invite_link = invite_obj.invite_link
        pending_invites[(cid, str(user.id))] = invite_link
    except Exception as e:
        logger.warning(f"Impossible de créer le lien d'invitation pour {cid}: {e}")
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"⚠️ *Bot non admin dans le canal* `{ch_name}`\n\n"
                    f"Le paiement de @{user.username or user.first_name} (`{user.id}`) a été validé automatiquement "
                    f"mais le lien d'invitation n'a pas pu être généré.\n\n"
                    f"➡️ Ajoutez le bot comme administrateur dans `{ch_name}` (canal `{cid}`) "
                    f"puis envoyez manuellement le lien à l'utilisateur.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    # Confirmer à l'utilisateur avec le lien
    if invite_link:
        await update.message.reply_text(
            f"🎉 **Paiement validé ! Accès activé.**\n\n"
            f"📢 Canal: **{ch_name}**\n"
            f"💰 Montant: **{result['amount_str']}**\n"
            f"⏱ Durée: **{days_text}**\n"
            f"📅 Expire le: {expire_str}\n"
            f"{ref_line}\n"
            f"👇 **Cliquez sur ce lien pour rejoindre le canal:**\n"
            f"{invite_link}\n\n"
            f"⚠️ Ce lien est à usage unique — ne le partagez pas.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"🎉 **Paiement validé ! Accès activé.**\n\n"
            f"📢 Canal: **{ch_name}**\n"
            f"💰 Montant: **{result['amount_str']}**\n"
            f"⏱ Durée: **{days_text}**\n"
            f"📅 Expire le: {expire_str}\n"
            f"{ref_line}\n"
            f"✅ Vous pouvez rejoindre le canal.\n"
            f"_(Lien non disponible — contactez l'admin si nécessaire)_",
            parse_mode="Markdown"
        )

    # Notifier les admins
    await notify_admins_payment(
        context, user, cid, ch_name, result["amount_str"], hours,
        photo.file_id, reference,
        raw_text=result.get("raw_text", ""),
        app_name=result.get("app", ""),
        method=result.get("method", "?")
    )


async def notify_admins_payment(context, user, cid: str, ch_name: str,
                                 amount_str: str, hours: int, photo_file_id: str,
                                 reference: str = "", raw_text: str = "",
                                 app_name: str = "", method: str = "?"):
    """Notifie les admins d'un nouveau paiement validé"""
    dur_label = format_duration_label(hours * 3600)
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else "N/A"

    ref_display = reference[:60] if reference else "—"
    ref_line = f"🔖 Référence: `{ref_display}`\n"
    app_line = f"📱 Application: **{app_name}**\n" if app_name and app_name != "Inconnu" else ""
    method_line = f"🤖 Analysé via: _{method}_\n" if method else ""
    ocr_preview = f"\n📄 _OCR: {raw_text[:120].strip()}_" if raw_text else ""

    caption = (
        f"💳 **Nouveau paiement reçu!**\n\n"
        f"👤 Utilisateur: **{full_name}** ({username})\n"
        f"🆔 ID: `{user.id}`\n"
        f"📢 Canal: **{ch_name}**\n"
        f"💰 Montant: **{amount_str}**\n"
        f"{app_line}"
        f"{ref_line}"
        f"{method_line}"
        f"⏱ Accès accordé: **{dur_label}**\n"
        f"✅ Accès activé automatiquement."
        f"{ocr_preview}"
    )

    for admin_id in ADMINS:
        try:
            await context.bot.send_photo(
                admin_id,
                photo=photo_file_id,
                caption=caption,
                parse_mode="Markdown"
            )
        except Exception as e:
            try:
                await context.bot.send_message(admin_id, caption, parse_mode="Markdown")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
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
                            f"💳 Pour renouveler votre abonnement, contactez notre assistant:\n"
                            f"👉 Appuyez sur /start",
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

async def main():
    logger.info("🤖 Démarrage du bot multi-canal...")

    # Charger les admins dynamiques depuis le fichier de données
    _startup_data = load_data()
    for aid in _startup_data.get("extra_admins", []):
        extra_admins.add(int(aid))
    if extra_admins:
        logger.info(f"👑 {len(extra_admins)} admin(s) dynamique(s) chargé(s)")

    application = Application.builder().token(BOT_TOKEN).build()

    # Commandes
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("channels", channels_command))
    application.add_handler(CommandHandler("members", members_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("setduration", setduration_command))
    application.add_handler(CommandHandler("ai_on", ai_on_command))
    application.add_handler(CommandHandler("ai_off", ai_off_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("payer", payer_command))
    application.add_handler(CommandHandler("annuler", annuler_command))
    application.add_handler(CommandHandler("grant", grant_command))
    application.add_handler(CommandHandler("extend", extend_command))
    application.add_handler(CommandHandler("bonus", bonus_command))
    application.add_handler(CommandHandler("unblock", unblock_command))
    application.add_handler(CommandHandler("connect", connect_command))
    application.add_handler(CommandHandler("disconnect", disconnect_command))
    application.add_handler(CommandHandler("telethon", telethon_status_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("setaikey", setaikey_command))
    application.add_handler(CommandHandler("listaikeys", listaikeys_command))
    application.add_handler(CommandHandler("checkquota", checkquota_command))
    application.add_handler(CommandHandler("addadmin", addadmin_command))
    application.add_handler(CommandHandler("removeadmin", removeadmin_command))
    application.add_handler(CommandHandler("listadmins", listadmins_command))

    # Callbacks boutons
    application.add_handler(CallbackQueryHandler(button_callback))

    # Événements membres du canal
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Captures d'écran de paiement — photos en chat privé
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        handle_payment_photo
    ))

    # Messages utilisateurs (réponse IA) — uniquement dans les chats privés, hors commandes
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_user_message
    ))

    await start_web_server()
    await application.initialize()
    await application.start()
    asyncio.create_task(check_expirations_task(application))

    logger.info("✅ Bot multi-canal démarré avec succès!")

    await application.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
    )

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
