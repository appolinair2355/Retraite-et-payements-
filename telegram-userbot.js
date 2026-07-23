// ============================================================
// USERBOT (GramJS / MTProto) — Scan des membres EXISTANTS d'un canal
// ------------------------------------------------------------
// Un bot à token (node-telegram-bot-api) ne peut JAMAIS lister les membres
// existants d'un canal : Telegram l'interdit pour tous les bots. Seul un
// vrai compte Telegram (connecté avec un numéro de téléphone) le peut, via
// l'API MTProto — c'est ce module qui s'en charge, avec la librairie GramJS.
//
// Configuration requise (variables d'environnement, JAMAIS en dur dans le code) :
//   TG_API_ID    → depuis https://my.telegram.org
//   TG_API_HASH  → depuis https://my.telegram.org
//   TG_SESSION   → généré une seule fois en local avec generate-session.js
//
// Si TG_SESSION n'est pas configuré, ce module reste inactif sans planter
// le reste de l'application (fallback : bouton d'activation manuelle dans
// le canal, déjà en place dans server.js).
// ============================================================

const { TelegramClient } = require("telegram");
const { StringSession }  = require("telegram/sessions");

const API_ID    = parseInt(process.env.TG_API_ID || "29177661", 10);
const API_HASH  = process.env.TG_API_HASH || "a8639172fa8d35dbfd8ea46286d349ab";
const ENV_SESSION = process.env.TG_SESSION || "1BJWap1wBux_QLE6eCmOvh_-xu9dHUqu-zuZLWoAbVxHHyNt33g6LrBQ5uJzvaB-Pdfi0InFVtgMj94fNHdX2Kdm1GckTVjW4LYfoeMl0WVEYZXK0J1-RpmK2dAgq1DZBfHY5PhnYSj4jmecP6EnbyYKoe-PpJ4vmlzI0QAJo6-tajhYJ_RFH9JAdhjixa1_lHIjJVgZFyvMkYY02aZ4m0Dixt7dWAqg-4wM6NX-b70XAoKAfblX0V_AyP0M7hRf7Qzk8QjPP3xPeT-onO1HAjuubugPCscHp2YdPYMqQegQcb94IlVcLSxALV8k4IFGXdNi-UfCQI1HdyWlapNZxC_GmfnYCeSU=";

let client = null;
let ready  = false;
let dbPool = null; // référence pool pg, fournie par server.js via initUserbot(pool)

// ── Persistance de la session en base (table settings, clé 'tg_userbot_session') ──
// Permet de connecter le userbot depuis le bot admin (téléphone + code reçu),
// sans avoir à repasser par un script local ni par les variables Render.
async function loadSessionFromDb() {
  if (!dbPool) return "";
  try {
    const r = await dbPool.query("SELECT value FROM settings WHERE key='tg_userbot_session'");
    return r.rows[0]?.value || "";
  } catch { return ""; }
}
async function saveSessionToDb(sessionString) {
  if (!dbPool) return;
  await dbPool.query(
    `INSERT INTO settings(key,value) VALUES('tg_userbot_session',$1)
     ON CONFLICT(key) DO UPDATE SET value=$1`,
    [sessionString]
  ).catch(e => console.error("[USERBOT-SESSION-SAVE-ERR]", e.message));
}

async function initUserbot(pool) {
  dbPool = pool || null;
  const dbSession = await loadSessionFromDb();
  const SESSION = dbSession || ENV_SESSION;

  if (!API_ID || !API_HASH || !SESSION) {
    console.log("[USERBOT] TG_API_ID / TG_API_HASH / session non configurés — scan automatique des membres existants désactivé (le bouton d'activation manuelle reste disponible). Connecte le compte via le bot admin (🔐 Connecter Userbot).");
    return null;
  }
  try {
    client = new TelegramClient(new StringSession(SESSION), API_ID, API_HASH, {
      connectionRetries: 5,
    });
    await client.connect();
    const me = await client.getMe();
    ready = true;
    console.log(`[USERBOT] Connecté en tant que ${me.username || me.firstName || me.id}.`);
    return client;
  } catch (e) {
    console.error("[USERBOT-INIT-ERR]", e.message);
    ready = false;
    return null;
  }
}

// ============================================================
// Connexion interactive (téléphone → code Telegram → mot de passe 2FA)
// Déclenchée UNIQUEMENT depuis le chat privé admin du bot (jamais exposée
// publiquement) — voir server.js, callback 'admin_userbot_connect'.
// ============================================================
let loginClient = null;
let loginState  = { status: "idle" };  // idle|connecting|awaiting_code|awaiting_password|connected|error
let pendingResolvers = {};

function waitFor(key) {
  return new Promise(resolve => { pendingResolvers[key] = resolve; });
}
function resolveWaiting(key, value) {
  if (pendingResolvers[key]) { pendingResolvers[key](value); delete pendingResolvers[key]; return true; }
  return false;
}

function getLoginState() { return loginState; }

async function beginLogin(phone) {
  loginState = { status: "connecting" };
  pendingResolvers = {};
  try {
    loginClient = new TelegramClient(new StringSession(""), API_ID, API_HASH, { connectionRetries: 5 });
    await loginClient.connect();
    loginState = { status: "awaiting_code" };

    loginClient.start({
      phoneNumber: async () => phone,
      phoneCode:   async () => { loginState = { status: "awaiting_code" };     return await waitFor("code"); },
      password:    async () => { loginState = { status: "awaiting_password" }; return await waitFor("password"); },
      onError:     (err) => { loginState = { status: "error", error: err.message }; },
    }).then(async () => {
      const sessionString = loginClient.session.save();
      await saveSessionToDb(sessionString);
      client = loginClient;
      ready  = true;
      loginState = { status: "connected" };
    }).catch(err => {
      loginState = { status: "error", error: err.message };
    });
  } catch (e) {
    loginState = { status: "error", error: e.message };
  }
}

function submitCode(code)     { return resolveWaiting("code", code); }
function submitPassword(pw)   { return resolveWaiting("password", pw); }

// Convertit un ID de canal format Bot API (-1001234567890) en entité GramJS
async function resolveChannelEntity(channelIdRaw) {
  const idStr = String(channelIdRaw);
  try {
    // GramJS résout directement la plupart des IDs -100xxxx s'il les a déjà "vus"
    return await client.getEntity(idStr);
  } catch (e) {
    // Repli : chercher le canal parmi les dialogues du compte userbot
    // (le compte doit être membre/admin du canal pour que ça fonctionne)
    const bare = idStr.startsWith("-100") ? idStr.slice(4) : idStr.replace("-", "");
    const dialogs = await client.getDialogs({});
    const found = dialogs.find(d => String(d.entity?.id) === bare);
    if (found) return found.entity;
    throw new Error(`Canal introuvable côté userbot (${channelIdRaw}). Vérifie que le compte userbot est bien membre/admin de ce canal.`);
  }
}

/**
 * Scanne tous les membres existants d'un canal et applique grantFn à chacun.
 * @param {string} channelIdRaw - ID du canal au format Bot API (ex: "-1001234567890")
 * @param {function} grantFn - async (tgUser) => résultat de grantOrDenyTrial
 */
async function scanExistingMembers(channelIdRaw, grantFn) {
  if (!ready || !client) return { ok: false, reason: "userbot_non_configure" };
  try {
    const entity = await resolveChannelEntity(channelIdRaw);
    const participants = await client.getParticipants(entity, { limit: 10000 });

    let scanned = 0, granted = 0, skipped = 0, errors = 0;
    for (const p of participants) {
      if (p.bot || p.deleted || p.self) { skipped++; continue; }
      scanned++;
      try {
        const result = await grantFn({
          id: Number(p.id),
          username: p.username || null,
          first_name: p.firstName || p.username || null,
        });
        if (result && result.status === "granted") granted++;
      } catch (e) {
        errors++;
        console.error("[USERBOT-GRANT-ERR]", p.id, e.message);
      }
    }
    return { ok: true, total: participants.length, scanned, granted, skipped, errors };
  } catch (e) {
    console.error("[USERBOT-SCAN-ERR]", e.message);
    return { ok: false, reason: e.message };
  }
}

function isUserbotReady() { return ready; }

module.exports = {
  initUserbot, scanExistingMembers, isUserbotReady,
  beginLogin, submitCode, submitPassword, getLoginState,
};
