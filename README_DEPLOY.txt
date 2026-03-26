╔══════════════════════════════════════════════════════════════════╗
║          BACCARAT BOT — PACK DÉPLOIEMENT RENDER.COM              ║
╚══════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ÉTAPES DE DÉPLOIEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Créer un compte sur https://render.com

2. Nouveau service → "Web Service"

3. Cliquer "Deploy from a Git repository"
   OU utiliser "Manual Deploy" avec ce ZIP (option "Upload ZIP")

4. Paramètres du service :
   ┌─────────────────┬────────────────────────────────┐
   │ Champ           │ Valeur                         │
   ├─────────────────┼────────────────────────────────┤
   │ Name            │ baccarat-bot (ou votre choix)  │
   │ Runtime         │ Python 3                       │
   │ Build Command   │ pip install -r requirements.txt│
   │ Start Command   │ python main.py                 │
   │ Plan            │ Free (suffisant pour démarrer) │
   └─────────────────┴────────────────────────────────┘

5. Variables d'environnement (onglet "Environment") :
   ┌──────────────────┬──────────────────────────────────────────┐
   │ Clé              │ Valeur                                   │
   ├──────────────────┼──────────────────────────────────────────┤
   │ BOT_TOKEN        │ Votre token BotFather (OBLIGATOIRE)      │
   │ ADMINS           │ Votre ID Telegram (ex: 1190237801)       │
   │ PORT             │ 10000                                    │
   │ TELETHON_API_ID  │ Votre API ID Telethon                    │
   │ TELETHON_API_HASH│ Votre API Hash Telethon                  │
   │ TELETHON_SESSION │ Votre session string Telethon            │
   └──────────────────┴──────────────────────────────────────────┘

   ⚠️  BOT_TOKEN est la seule variable OBLIGATOIRE au démarrage.
       Les clés IA (Gemini, Groq, OpenAI, DeepSeek) sont ajoutées
       directement par l'administrateur via le panneau admin du bot
       (pas besoin de variables d'environnement pour les clés IA).

6. Cliquer "Create Web Service" → Render installe et démarre le bot.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Le bot écoute sur le port 10000 (configuré dans config.py).
Render détecte automatiquement ce port via la variable PORT.
Health check disponible sur : GET /

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APRÈS LE DÉMARRAGE — CONFIGURATION IA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Les clés IA se configurent depuis le bot, sans toucher au serveur :

1. Ouvrir le bot Telegram → /start
2. Panneau Admin → ⚙️ Config IA
3. Choisir un fournisseur (Gemini, Groq, OpenAI ou DeepSeek)
4. Cliquer ➕ Ajouter une clé → envoyer la clé dans le chat
5. Répéter pour ajouter plusieurs clés (rotation automatique)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FONCTIONNALITÉS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Gestion multi-canaux avec accès payants
✅ Détection automatique des canaux (ajouter le bot = détection immédiate)
✅ Scan des canaux au démarrage (validation automatique)
✅ IA multi-fournisseurs : Gemini, OpenAI, Groq, DeepSeek
   - Rotation automatique des clés en cas de quota épuisé
   - Fallback inter-fournisseurs automatique
   - Plusieurs clés par fournisseur, configurables via le bot
✅ Alertes admin en privé si toutes les clés IA sont épuisées
✅ Interface 100% boutons (aucune commande à taper côté admin)
✅ Gestion des membres : accorder, rallonger, retirer, bloquer
✅ Support multilingue (FR, EN, AR, ES, PT, ZH...)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PERSISTANCE DES DONNÉES SUR RENDER (plan gratuit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  Le plan Free de Render redémarre le service régulièrement.
    Les données (membres, canaux, clés IA) sont dans channels_data.json.
    Pour éviter toute perte, il est recommandé de :
    - Passer au plan Starter ($7/mois) avec un Persistent Disk
    - OU sauvegarder régulièrement channels_data.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FICHIERS INCLUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main.py              → Code principal du bot
config.py            → Configuration (port 10000, env vars Render)
telethon_manager.py  → Gestionnaire session Telethon
requirements.txt     → Dépendances Python
render.yaml          → Configuration Render.com (auto-déployable)
Procfile             → Commande de démarrage
runtime.txt          → Version Python (3.11.9)
channels_data.json   → Base de données vide (propre)
README_DEPLOY.txt    → Ce fichier

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
