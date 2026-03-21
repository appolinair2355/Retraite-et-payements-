═══════════════════════════════════════════════════════════════
   ASSISNT PAYEMENT - Bot Telegram Gestionnaire d'Accès
   Déploiement sur Render.com
═══════════════════════════════════════════════════════════════

ÉTAPES DE DÉPLOIEMENT :
───────────────────────
1. Créez un compte sur render.com
2. "New" → "Web Service" → "Deploy from ZIP file"
3. Uploader ce ZIP
4. Configurer les Variables d'Environnement ci-dessous

VARIABLES D'ENVIRONNEMENT (Render → Environment) :
────────────────────────────────────────────────────
OBLIGATOIRES :
  BOT_TOKEN           = Token de votre bot (depuis @BotFather)
  ADMINS              = Votre ID Telegram (ex: 123456789)
  PORT                = 10000

CLÉS IA (au moins 1 fournisseur) :
  GEMINI_API_KEYS     = clé1,clé2,clé3   (Google AI Studio)
  OPENAI_API_KEYS     = sk-...,sk-...     (platform.openai.com)
  GROQ_API_KEYS       = gsk_...,gsk_...  (console.groq.com)
  DEEPSEEK_API_KEYS   = sk-...,sk-...    (platform.deepseek.com)
  OCR_SPACE_API_KEY   = K...             (ocr.space - optionnel)

TELETHON (optionnel, pour scan membres complet) :
  TELETHON_API_ID     = votre API ID     (my.telegram.org)
  TELETHON_API_HASH   = votre API Hash
  TELETHON_SESSION    = chaîne de session Telethon

FONCTIONNEMENT AU DÉMARRAGE :
──────────────────────────────
- Le bot démarre avec ZÉRO canal configuré
- Ajoutez le bot comme ADMINISTRATEUR dans vos canaux Telegram
- Il détecte automatiquement les canaux où il est admin
- Il notifie les admins et commence à gérer les accès

COMMANDES ADMIN PRINCIPALES :
───────────────────────────────
/start          - Menu principal
/checkquota     - Voir les quotas IA restants
/setaikey       - Ajouter une clé IA
/listaikeys     - Lister les clés IA configurées
/channels       - Voir les canaux gérés

