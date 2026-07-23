╔══════════════════════════════════════════════════════════════╗
║         ASSISNT PAYEMENT — DÉPLOIEMENT RENDER.COM           ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ÉTAPES DE DÉPLOIEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Créer un compte sur https://render.com

2. Nouveau service → "Web Service"

3. Choisir "Deploy from a Git repository"
   OU utiliser "Manual Deploy" avec ce ZIP

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
   │ DATABASE_URL        │ URL PostgreSQL de paiement-s-curis     │
   │ PORT                │ 5000                                   │
   └─────────────────────┴────────────────────────────────────────┘

   ⚠️ Toutes les autres valeurs (BOT_TOKEN, clés IA, Telethon)
   sont déjà codées en dur dans config.py — aucune autre
   variable d'environnement n'est nécessaire.

   DATABASE_URL est la seule variable à configurer : c'est
   l'URL de connexion à votre base PostgreSQL sur Render.com
   (le même que celui du site paiement-s-curis.onrender.com).

6. Cliquer "Create Web Service" → Render installe et démarre

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FONCTIONNEMENT DU SYSTÈME DE PAIEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. INSCRIPTION (nouveaux utilisateurs)
   - L'utilisateur envoie /start au bot
   - Le bot demande : prénom, nom, email, mot de passe
   - Un compte est créé dans la base de données PostgreSQL
   - L'email et le mot de passe servent à se connecter sur
     https://paiement-s-curis.onrender.com

2. PAIEMENT
   - L'utilisateur clique "💳 Payer mon abonnement"
   - Le bot affiche le lien vers le site de paiement avec
     ses identifiants de connexion
   - L'utilisateur paie sur le site
   - L'utilisateur revient dans le bot et clique
     "✅ J'ai payé — Vérifier mon accès"
   - Le bot consulte la base de données pour vérifier
     que subscription_expires_at > maintenant
   - Si confirmé : accès accordé au(x) canal(aux) +
     message de remerciement Sossou Kouamé

3. EXPIRATION
   - Le bot vérifie toutes les 30 secondes
   - À expiration : l'utilisateur est retiré du canal
   - Message envoyé pour renouveler via /start

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FONCTIONNALITÉS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Inscription avec email/mot de passe (identique au site)
✅ Vérification paiement via base de données PostgreSQL
✅ Gestion multi-canaux avec accès payants
✅ IA multi-fournisseurs (Gemini, OpenAI, Groq, DeepSeek)
✅ Gestion des membres : accorder, rallonger, retirer, bloquer
✅ Mode d'emploi par canal configurable
✅ Interface admin complète par boutons
✅ Support multilingue (FR, EN, AR, ES, RU, PT, ZH...)
✅ Session Telethon persistante

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDES ADMIN PRINCIPALES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/start        → Menu principal
/grant        → Accorder l'accès à un utilisateur
/extend       → Rallonger l'accès
/remove       → Retirer un membre
/channels     → Voir tous les canaux gérés
/members      → Voir les membres d'un canal
/connect      → Connecter Telethon

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FICHIERS INCLUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main.py              → Code principal du bot
config.py            → Configuration (valeurs codées en dur)
telethon_manager.py  → Gestionnaire session Telethon
requirements.txt     → Dépendances Python
render.yaml          → Configuration Render.com
Procfile             → Commande de démarrage
runtime.txt          → Version Python (3.12)
channels_data.json   → Base de données locale (canaux/membres)
README_DEPLOY.txt    → Ce fichier

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
