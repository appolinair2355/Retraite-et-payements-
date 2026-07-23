// ============================================================
// À EXÉCUTER UNE SEULE FOIS, EN LOCAL, SUR TON PROPRE ORDINATEUR.
// NE JAMAIS EXÉCUTER CE SCRIPT SUR RENDER NI LE PARTAGER À QUELQU'UN D'AUTRE.
//
// Ce script connecte ton compte Telegram (numéro de téléphone) via l'API
// officielle MTProto et génère une "session string". Le code de vérification
// Telegram te sera envoyé directement dans ton appli Telegram (ou par SMS) :
// SEUL TOI dois le saisir ici, jamais à personne d'autre, jamais à Claude.
//
// Utilisation :
//   1. npm install telegram
//   2. node generate-session.js
//   3. Réponds aux questions (numéro, code reçu, mot de passe 2FA si tu en as un)
//   4. Copie la valeur affichée à la fin dans la variable d'environnement
//      TG_SESSION sur Render (Dashboard → ton service → Environment)
// ============================================================

const { TelegramClient } = require("telegram");
const { StringSession }  = require("telegram/sessions");
const readline = require("readline");

// Ces deux valeurs viennent de https://my.telegram.org (mêmes valeurs que
// TG_API_ID / TG_API_HASH que tu configureras sur Render).
const API_ID   = parseInt(process.env.TG_API_ID   || "29177661", 10);
const API_HASH = process.env.TG_API_HASH || "a8639172fa8d35dbfd8ea46286d349ab";

function ask(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(resolve => rl.question(question, answer => { rl.close(); resolve(answer.trim()); }));
}

(async () => {
  console.log("=== Connexion à ton compte Telegram (une seule fois) ===\n");
  const client = new TelegramClient(new StringSession(""), API_ID, API_HASH, {
    connectionRetries: 5,
  });

  await client.start({
    phoneNumber: async () => await ask("📱 Ton numéro Telegram, avec indicatif (ex: +22995501564) : "),
    password:    async () => await ask("🔒 Mot de passe 2FA (laisse vide si tu n'en as pas configuré) : "),
    phoneCode:   async () => await ask("💬 Code reçu dans Telegram (ou par SMS) : "),
    onError:     (err) => console.error(err),
  });

  const sessionString = client.session.save();

  console.log("\n✅ Connecté avec succès !\n");
  console.log("Copie EXACTEMENT cette valeur dans la variable d'environnement");
  console.log("TG_SESSION sur Render (Dashboard → ton service → Environment) :\n");
  console.log(sessionString);
  console.log("\n⚠️  Ne partage cette valeur avec PERSONNE (pas même moi) : elle donne un");
  console.log("    accès complet à ton compte Telegram, comme un mot de passe.\n");

  await client.disconnect();
  process.exit(0);
})();
