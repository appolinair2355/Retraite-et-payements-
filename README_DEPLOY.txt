═══════════════════════════════════════════════════════════
   ASSISNT PAYEMENT — Bot Telegram Gestionnaire d Acces
   Deploiement Render.com | Port 10000
═══════════════════════════════════════════════════════════

VARIABLES OBLIGATOIRES (Render → Environment) :
  BOT_TOKEN   = Token de votre bot (depuis @BotFather)
  PORT        = 10000

VOTRE ID ADMIN (1190237801) EST DEJA INTEGRE DANS LE CODE.
Vous etes reconnu admin des le premier demarrage sans
avoir a configurer la variable ADMINS.

Pour ajouter d autres admins : utilisez /addadmin dans le bot.

CLES IA (optionnelles, ajoutables via /setaikey apres demarrage) :
  GEMINI_API_KEYS   = cle1,cle2   (Google AI Studio)
  OPENAI_API_KEYS   = sk-...      (platform.openai.com)
  GROQ_API_KEYS     = gsk_...     (console.groq.com)
  DEEPSEEK_API_KEYS = sk-...      (platform.deepseek.com)
  OCR_SPACE_API_KEY = K...        (ocr.space)

TELETHON (optionnel) :
  TELETHON_API_ID   TELETHON_API_HASH   TELETHON_SESSION

FONCTIONNEMENT :
  Le bot demarre avec ZERO canal. Ajoutez-le comme
  ADMINISTRATEUR dans vos canaux Telegram — il les
  detecte automatiquement et commence a gerer les acces.

COMMANDES PRINCIPALES :
  /start        Menu principal
  /checkquota   Quotas IA restants
  /setaikey     Ajouter une cle IA
  /listaikeys   Lister les cles IA
  /addadmin     Ajouter un administrateur
