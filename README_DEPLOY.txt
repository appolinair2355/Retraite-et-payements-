╔══════════════════════════════════════════════════════════════╗
║         ASSISNT PAYEMENT — DÉPLOIEMENT RENDER.COM           ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ÉTAPES DE DÉPLOIEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Créer un compte sur https://render.com

2. Nouveau service → "Web Service"

3. Choisir "Deploy from a Git repository"
   OU utiliser "Manual Deploy" avec ce ZIP (option "Upload")

4. Paramètres du service :
   - Name      : assisnt-payement (ou votre choix)
   - Runtime   : Python 3
   - Build Cmd : pip install -r requirements.txt
   - Start Cmd : python main.py
   - Plan      : Free (suffisant pour démarrer)

5. Variables d'environnement à configurer (onglet "Environment") :

   ┌─────────────────────┬────────────────────────────────────────┐
   │ Clé                 │ Valeur                                 │
   ├─────────────────────┼────────────────────────────────────────┤
   │ BOT_TOKEN           │ Votre token BotFather                  │
   │ ADMINS              │ Votre ID Telegram (ex: 1190237801)     │
   │ PORT                │ 10000                                  │
   │ GEMINI_API_KEYS     │ Vos clés Gemini (séparées par virgule) │
   │ OPENAI_API_KEYS     │ Vos clés OpenAI (optionnel)            │
   │ GROQ_API_KEYS       │ Vos clés Groq (optionnel)              │
   │ DEEPSEEK_API_KEYS   │ Vos clés DeepSeek (optionnel)         │
   │ OCR_SPACE_API_KEY   │ Votre clé OCR.space (optionnel)        │
   │ TELETHON_API_ID     │ Votre API ID Telethon                  │
   │ TELETHON_API_HASH   │ Votre API Hash Telethon                │
   │ TELETHON_SESSION    │ Votre session string Telethon          │
   └─────────────────────┴────────────────────────────────────────┘

6. Cliquer "Create Web Service" → Render installe et démarre

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PORT — IMPORTANT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Le bot écoute sur le port 10000 (déjà configuré dans render.yaml
et dans config.py). Render détecte automatiquement ce port.
Le health check est disponible sur /health.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FONCTIONNALITÉS INCLUSES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Gestion multi-canaux avec accès payants
✅ IA multi-fournisseurs (Gemini, OpenAI, Groq, DeepSeek)
   avec fallback automatique en cas de quota épuisé
✅ Analyse de captures de paiement par vision IA
✅ Gestion des membres : accorder, rallonger, retirer, bloquer
✅ Mode d'emploi par canal :
   - Admin configure via bouton "📖 Mode d'emploi" ou /setmode
   - Envoi automatique dans le canal + DM quand un membre rejoint
   - L'assistante IA répond aux questions sur le mode d'emploi
✅ Persistance de session Telethon via channels_data.json
✅ Interface admin complète par boutons
✅ Support multilingue (FR, EN, AR, ES, RU, PT, ZH...)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDES ADMIN PRINCIPALES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/start        → Menu principal
/setmode      → Configurer le mode d'emploi d'un canal
/setaikey     → Ajouter/modifier une clé IA
/listaikeys   → Voir les clés IA configurées
/checkquota   → Tester les quotas de toutes les clés
/grant        → Accorder l'accès à un utilisateur
/extend       → Rallonger l'accès
/remove       → Retirer un membre
/unblock      → Débloquer un utilisateur
/channels     → Voir tous les canaux gérés
/members      → Voir les membres d'un canal
/addadmin     → Ajouter un administrateur
/connect      → Connecter Telethon (session active)
/annuler      → Annuler l'opération en cours

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PERSISTANCE DES DONNÉES SUR RENDER (plan gratuit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ Le plan Free de Render redémarre le service régulièrement.
   Les données sont stockées dans channels_data.json (en mémoire).
   Pour éviter toute perte, il est recommandé de :
   - Passer au plan Starter ($7/mois) avec un Persistent Disk
   - OU sauvegarder régulièrement channels_data.json

La session Telethon est automatiquement sauvegardée dans
channels_data.json ET dans la variable TELETHON_SESSION.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FICHIERS INCLUS DANS CE PACK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main.py              → Code principal du bot (4600+ lignes)
config.py            → Configuration centralisée
telethon_manager.py  → Gestionnaire session Telethon
requirements.txt     → Dépendances Python
render.yaml          → Configuration Render.com (auto-déployable)
Procfile             → Commande de démarrage
runtime.txt          → Version Python (3.11.9)
channels_data.json   → Base de données (vide au départ)
README_DEPLOY.txt    → Ce fichier

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
