require("dotenv").config();

// ============================================================
// SOSSOU KOUAMÉ — Serveur Express complet
// Login + Dashboard + Paiement Money Fusion + Crypto + BDD Render
// ============================================================

const express    = require("express");
const path       = require("path");
const { Pool }   = require("pg");
const bcrypt     = require("bcrypt");
const session    = require("express-session");
const pgSession  = require("connect-pg-simple")(session);
const nodemailer = require("nodemailer");
const {
  initUserbot, scanExistingMembers, isUserbotReady,
  beginLogin, submitCode, submitPassword, getLoginState,
} = require("./telegram-userbot");

const app  = express();
const PORT = process.env.PORT || 10000;

// ─── URL DU SITE (pour les boutons Telegram / emails) ─────────────────────
const SITE_URL = process.env.SITE_URL || 'https://solarium-1-rj14.onrender.com';
const PAYMENT_URL = process.env.PAYMENT_URL || 'https://paiement-s-curis.onrender.com';

// ─── BASE DE DONNÉES ──────────────────────────────────────────────────────
// ⚠️ Toujours fournir DATABASE_URL (ou DB_URL) en variable d'environnement sur Render.
const DB_URL = process.env.DATABASE_URL || process.env.DB_URL || 'postgresql://bonjour_user:WzeZsFKlKWU180iOFxngBEaThdG1kKUR@dpg-d962464s728c73e8p250-a.oregon-postgres.render.com/bonjour';
if (!DB_URL) {
  console.error('[FATAL] Aucune variable DATABASE_URL / DB_URL définie. Configurez-la dans Render → Environment.');
}
const pool = new Pool({
  connectionString: DB_URL,
  ssl: { rejectUnauthorized: false },
  max: 5,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 10000,
});

// ─── EMAIL (nodemailer / Gmail) ───────────────────────────────────────────
const GMAIL_USER  = process.env.GMAIL_USER  || 'sossoukouam@gmail.com';
const GMAIL_PASS  = process.env.GMAIL_PASS  || 'gcwbgdpqntabwlud';
const ADMIN_EMAIL = process.env.ADMIN_EMAIL || GMAIL_USER;

const gmailTransport = nodemailer.createTransport({
  service: "gmail",
  auth: { user: GMAIL_USER, pass: GMAIL_PASS },
});

async function sendPaymentEmail(userId, details) {
  if (!GMAIL_USER || !GMAIL_PASS) return;
  try {
    const r = await pool.query(
      "SELECT username, first_name, last_name, email FROM users WHERE id = $1",
      [userId]
    );
    if (!r.rows.length) return;
    const u = r.rows[0];
    const toEmail = u.email || `${u.username}@gmail.com`;
    const name = [u.first_name, u.last_name].filter(Boolean).join(" ") || u.username;
    const subject = `✅ Paiement confirmé — ${details.label}`;
    const html = `
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;background:#0a0f1e;color:#fff;border-radius:12px;overflow:hidden">
  <div style="background:linear-gradient(135deg,#F0C040,#C9A030);padding:28px 32px;text-align:center">
    <h1 style="margin:0;font-size:1.4rem;color:#000">Sossou Kouamé Shopping Boutique</h1>
  </div>
  <div style="padding:32px">
    <h2 style="color:#F0C040;margin-top:0">Bonjour ${name} 👋</h2>
    <p style="color:rgba(255,255,255,0.8);font-size:1rem;line-height:1.6">
      Votre paiement a bien été <strong style="color:#10B981">confirmé et validé</strong>.<br>
      Merci pour votre confiance !
    </p>
    <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(240,192,64,0.3);border-radius:10px;padding:20px;margin:20px 0">
      <table style="width:100%;border-collapse:collapse;font-size:.92rem">
        <tr><td style="color:rgba(255,255,255,0.5);padding:6px 0">Service</td><td style="color:#fff;font-weight:700;text-align:right">${details.label}</td></tr>
        ${details.amount ? `<tr><td style="color:rgba(255,255,255,0.5);padding:6px 0">Montant</td><td style="color:#F0C040;font-weight:700;text-align:right">${details.amount}</td></tr>` : ""}
        ${details.duration ? `<tr><td style="color:rgba(255,255,255,0.5);padding:6px 0">Durée</td><td style="color:#fff;text-align:right">${details.duration}</td></tr>` : ""}
        <tr><td style="color:rgba(255,255,255,0.5);padding:6px 0">Statut</td><td style="color:#10B981;font-weight:700;text-align:right">✓ Validé</td></tr>
      </table>
    </div>
    <p style="color:rgba(255,255,255,0.6);font-size:.88rem">
      Pour toute question, répondez à cet email ou contactez-nous directement.
    </p>
    <div style="text-align:center;margin-top:24px">
      <span style="color:#F0C040;font-size:.8rem">© 2026 Sossou Kouamé Shopping Boutique</span>
    </div>
  </div>
</div>`;
    await gmailTransport.sendMail({
      from: `"Sossou Kouamé" <${GMAIL_USER}>`,
      to: toEmail,
      subject,
      html,
    });
    console.log("[EMAIL] Envoyé à", toEmail);
  } catch (e) {
    console.error("[EMAIL-ERR]", e.message);
  }
}

// ─── MONEY FUSION ─────────────────────────────────────────────────────────
const CONFIG = {
  API_URL:    process.env.MONEY_FUSION_API_URL || "https://pay.moneyfusion.net/Paiements_m/7da7654df194be93/pay/",
  STATUS_URL: "https://pay.moneyfusion.net/paiementNotif",
  API_KEY:    process.env.MONEY_FUSION_API_KEY || "",
};

// ─── PLANS D'ABONNEMENT (lus depuis la BDD en temps réel) ────────────────
const DEFAULT_PLANS = [
  { id: "1j",  label: "1 Jour",    duration_minutes:  1440, amount_usd:  1.08, price_xof:   656, price_eur:  1 },
  { id: "15j", label: "15 Jours",  duration_minutes: 21600, amount_usd: 12.96, price_xof:  7872, price_eur: 12 },
  { id: "30j", label: "30 Jours",  duration_minutes: 43200, amount_usd: 32.40, price_xof: 19680, price_eur: 30 },
];

// ─── INITIALISATION DES TABLES AU DÉMARRAGE ──────────────────────────────
async function initDB() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(80) UNIQUE NOT NULL,
        email VARCHAR(120),
        password_hash VARCHAR(256) NOT NULL,
        first_name TEXT, last_name TEXT,
        is_admin BOOLEAN DEFAULT FALSE,
        is_approved BOOLEAN DEFAULT TRUE,
        is_premium BOOLEAN DEFAULT FALSE,
        is_pro BOOLEAN DEFAULT FALSE,
        is_banned BOOLEAN DEFAULT FALSE,
        account_type TEXT DEFAULT 'Standard',
        plain_password TEXT,
        telegram_id TEXT,
        subscription_expires_at TIMESTAMPTZ,
        subscription_duration_minutes INTEGER,
        last_seen TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
      );
      ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT TRUE;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id TEXT;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS plain_password TEXT;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS account_type TEXT DEFAULT 'Standard';
      ALTER TABLE users ADD COLUMN IF NOT EXISTS is_pro BOOLEAN DEFAULT FALSE;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT;
      ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_code TEXT;

      CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS payment_requests (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        plan_id TEXT NOT NULL,
        plan_label TEXT,
        amount_usd NUMERIC(10,2) NOT NULL,
        duration_minutes INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        payment_method TEXT DEFAULT 'mobile_money',
        transaction_id TEXT,
        admin_note TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
      );
      ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS payment_method TEXT DEFAULT 'mobile_money';
      ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS transaction_id TEXT;
      ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS phone_number TEXT;

      CREATE TABLE IF NOT EXISTS telegram_config (
        id SERIAL PRIMARY KEY,
        channel_id TEXT NOT NULL UNIQUE,
        channel_name TEXT,
        enabled BOOLEAN DEFAULT TRUE,
        channel_invite_link TEXT,
        default_duration_days INTEGER DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT NOW()
      );
      ALTER TABLE telegram_config ADD COLUMN IF NOT EXISTS channel_name TEXT;
      ALTER TABLE telegram_config ADD COLUMN IF NOT EXISTS channel_invite_link TEXT;
      ALTER TABLE telegram_config ADD COLUMN IF NOT EXISTS default_duration_days INTEGER DEFAULT 0;

      CREATE TABLE IF NOT EXISTS telegram_visitors (
        telegram_id BIGINT PRIMARY KEY,
        tg_username TEXT,
        tg_first_name TEXT,
        seen_at TIMESTAMPTZ DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS user_strategy_visible (
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        strategy_id TEXT NOT NULL,
        PRIMARY KEY(user_id, strategy_id)
      );

      CREATE TABLE IF NOT EXISTS strategy_ideas (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        is_paid BOOLEAN DEFAULT FALSE,
        price_usd NUMERIC(10,2) DEFAULT 0,
        enabled BOOLEAN DEFAULT TRUE,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
      );
      ALTER TABLE strategy_ideas ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;

      CREATE TABLE IF NOT EXISTS strategy_channel_routes (
        strategy TEXT NOT NULL,
        channel_id INTEGER REFERENCES telegram_config(id) ON DELETE CASCADE,
        PRIMARY KEY (strategy, channel_id)
      );

      CREATE TABLE IF NOT EXISTS predictions (
        id SERIAL PRIMARY KEY,
        strategy TEXT NOT NULL,
        game_number INTEGER,
        predicted_suit TEXT,
        status VARCHAR(20) DEFAULT 'en_cours',
        created_at TIMESTAMPTZ DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS support_packs (
        id SERIAL PRIMARY KEY,
        amount_usd NUMERIC(10,2) NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        enabled BOOLEAN DEFAULT TRUE,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
      );
      INSERT INTO support_packs (amount_usd, label, sort_order) VALUES
        (200,'☕ Café — 200 FCFA',1),(500,'🍕 Pizza — 500 FCFA',2),
        (1000,'🎮 Joueur — 1 000 FCFA',3),(2000,'⭐ Supporter — 2 000 FCFA',4),
        (5000,'💪 Solide — 5 000 FCFA',5),(10000,'🔥 Motivé — 10 000 FCFA',6)
      ON CONFLICT DO NOTHING;

      CREATE TABLE IF NOT EXISTS support_purchases (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        pack_id INTEGER REFERENCES support_packs(id) ON DELETE SET NULL,
        amount_usd NUMERIC(10,2) NOT NULL,
        status TEXT DEFAULT 'awaiting_screenshot',
        created_at TIMESTAMPTZ DEFAULT NOW()
      );

      -- Accès temporaire canal pour membres non encore liés
      CREATE TABLE IF NOT EXISTS channel_temp_access (
        telegram_id BIGINT NOT NULL,
        channel_id TEXT NOT NULL,
        tg_username TEXT,
        tg_first_name TEXT,
        granted_at TIMESTAMPTZ DEFAULT NOW(),
        expires_at TIMESTAMPTZ NOT NULL,
        kicked BOOLEAN DEFAULT FALSE,
        PRIMARY KEY (telegram_id, channel_id)
      );
    `);

    // ── Migration : passage d'une clé simple (telegram_id) à une clé composite
    // (telegram_id, channel_id) — nécessaire pour qu'un même membre puisse avoir
    // un essai/abonnement indépendant sur PLUSIEURS canaux en parallèle.
    await pool.query(`
      DO $mig$
      BEGIN
        IF EXISTS (
          SELECT 1 FROM pg_constraint
          WHERE conrelid = 'channel_temp_access'::regclass
            AND contype = 'p'
            AND array_length(conkey,1) = 1
        ) THEN
          ALTER TABLE channel_temp_access DROP CONSTRAINT channel_temp_access_pkey;
          ALTER TABLE channel_temp_access ADD PRIMARY KEY (telegram_id, channel_id);
        END IF;
      END
      $mig$;
    `).catch(e => console.error('[MIGRATION-CTA-PK]', e.message));

    // Compte administrateur (créé une seule fois — n'écrase JAMAIS un mot de
    // passe existant, pour que le changement de mot de passe depuis le
    // panneau admin ne soit pas effacé à chaque redémarrage du serveur).
    const bcryptLib = require('bcrypt');
    const ADMIN_USERNAME      = process.env.ADMIN_USERNAME || 'sossoukouam';
    const ADMIN_INITIAL_PASS  = process.env.ADMIN_PASSWORD || null;
    const existingAdmin = await pool.query("SELECT id FROM users WHERE username=$1", [ADMIN_USERNAME]);
    if (!existingAdmin.rows.length) {
      // Premier démarrage : si aucun ADMIN_PASSWORD n'est fourni, on en
      // génère un aléatoire et on l'affiche UNE SEULE FOIS dans les logs
      // Render, pour éviter tout mot de passe par défaut connu à l'avance.
      const crypto = require('crypto');
      const generated = ADMIN_INITIAL_PASS || crypto.randomBytes(9).toString('base64').replace(/[^a-zA-Z0-9]/g,'').slice(0,12);
      const h = await bcryptLib.hash(generated, 10);
      await pool.query(
        `INSERT INTO users (username, email, password_hash, is_admin, is_approved, account_type)
         VALUES ($1,$2,$3,TRUE,TRUE,'Admin')`,
        [ADMIN_USERNAME, ADMIN_EMAIL || null, h]
      );
      if (!ADMIN_INITIAL_PASS) {
        console.log('========================================');
        console.log(`✅ Compte admin créé : ${ADMIN_USERNAME}`);
        console.log(`🔑 Mot de passe généré (à changer ensuite) : ${generated}`);
        console.log('========================================');
      } else {
        console.log(`✅ Compte admin créé : ${ADMIN_USERNAME} (mot de passe défini via ADMIN_PASSWORD)`);
      }
    }
    console.log('✅ Base de données initialisée');
  } catch(e) {
    console.error('[INIT-DB]', e.message);
  }
}
// initDB() est appelé dans app.listen pour garantir l'ordre correct.

async function getPlans() {
  try {
    const r = await pool.query("SELECT value FROM settings WHERE key = 'subscription_plans'");
    if (r.rows.length > 0) return JSON.parse(r.rows[0].value);
  } catch (e) { console.error("[PLANS-DB]", e.message); }
  return DEFAULT_PLANS;
}


// ─── PALIERS DE SOUTIEN (lus depuis support_packs en temps réel) ─────────
async function getSupportTiers() {
  try {
    const r = await pool.query(
      "SELECT id, label, amount_usd FROM support_packs WHERE enabled = true ORDER BY sort_order ASC NULLS LAST, id ASC"
    );
    // La colonne amount_usd contient les montants en XOF (FCFA)
    return r.rows.map(row => ({
      id:        `sup_${row.id}`,
      label:     row.label,
      price_xof: Number(row.amount_usd),
    }));
  } catch (e) {
    console.error("[SUPPORT-TIERS-DB]", e.message);
    return [];
  }
}

// ─── PRIX DES STRATÉGIES (lus depuis settings en temps réel) ─────────────
async function getStrategyPrices() {
  try {
    const r = await pool.query("SELECT value FROM settings WHERE key = 'strategy_prices'");
    if (r.rows.length > 0) return JSON.parse(r.rows[0].value);
  } catch (e) { console.error("[STRAT-PRICES-DB]", e.message); }
  return { default_combo: 15000, default_standard: 10000 };
}

// ─── WALLETS CRYPTO ───────────────────────────────────────────────────────
const CRYPTO_WALLETS = [
  { id: "USDT_TRC20", name: "Tether TRC20", symbol: "USDT", icon: "₮", network: "TRON",     address: "T9zZ123xABCdef456GHIjkl789mnoPQRst", min: "10 USDT" },
  { id: "USDT_ERC20", name: "Tether ERC20", symbol: "USDT", icon: "₮", network: "Ethereum", address: "0x71C7656EC7ab88b098defB751B7401B5f6d8976F", min: "10 USDT" },
  { id: "BTC",        name: "Bitcoin",      symbol: "BTC",  icon: "₿", network: "Bitcoin",  address: "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", min: "0.001 BTC" },
  { id: "ETH",        name: "Ethereum",     symbol: "ETH",  icon: "Ξ", network: "Ethereum", address: "0x71C7656EC7ab88b098defB751B7401B5f6d8976F", min: "0.01 ETH" },
];

// ─── TAUX DE CHANGE TEMPS RÉEL (cache 1h) ────────────────────────────────
let _rateCache = { data: null, ts: 0 };
async function getExchangeRates() {
  const now = Date.now();
  if (_rateCache.data && now - _rateCache.ts < 3_600_000) return _rateCache.data;
  try {
    const [fiatRes, cryptoRes] = await Promise.all([
      fetch("https://open.er-api.com/v6/latest/USD"),
      fetch("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"),
    ]);
    const fiat   = await fiatRes.json();
    const crypto = await cryptoRes.json();
    const data = {
      usd_to_xof: Math.round(fiat.rates?.XOF  || 656),
      usd_to_eur: parseFloat((fiat.rates?.EUR  || 0.93).toFixed(4)),
      btc_usd:    Math.round(crypto.bitcoin?.usd  || 60000),
      eth_usd:    Math.round(crypto.ethereum?.usd || 3000),
      updated_at: new Date().toISOString(),
    };
    _rateCache = { data, ts: now };
    console.log("[RATES]", JSON.stringify(data));
    return data;
  } catch (e) {
    console.error("[RATES-ERR]", e.message);
    const fallback = { usd_to_xof: 656, usd_to_eur: 0.93, btc_usd: 60000, eth_usd: 3000 };
    if (!_rateCache.data) _rateCache = { data: fallback, ts: now - 3_500_000 };
    return _rateCache.data;
  }
}

// ─── MIDDLEWARE ───────────────────────────────────────────────────────────
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
const SESSION_COOKIE_NAME = 'sk.sid';
app.set('trust proxy', 1); // Render est derrière un proxy HTTPS
app.use(session({
  store: new pgSession({ pool, tableName: 'user_sessions', createTableIfMissing: true }),
  name: SESSION_COOKIE_NAME,
  secret: process.env.SESSION_SECRET || 'sk_sossou2026_xK9mP2qLvR8nTwYjZdAcBe',
  resave: false,
  saveUninitialized: false,
  rolling: true,
  cookie: {
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 30 * 24 * 60 * 60 * 1000 // 30 jours, prolongée à chaque requête (rolling)
  }
}));
app.use((req, res, next) => {
  res.header("Access-Control-Allow-Origin", "*");
  res.header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.header("Access-Control-Allow-Headers", "Content-Type, Authorization");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

// ─── AUTH MIDDLEWARE ──────────────────────────────────────────────────────
function requireAuth(req, res, next) {
  if (!req.session.userId) return res.status(401).json({ error: "Non authentifié" });
  next();
}


async function requireAdmin(req, res, next) {
  if (!req.session.userId) return res.status(401).json({ error: "Non authentifié" });
  try {
    const r = await pool.query("SELECT is_admin FROM users WHERE id = $1", [req.session.userId]);
    if (r.rows.length === 0 || !r.rows[0].is_admin) {
      return res.status(403).json({ error: "Accès réservé à l'administrateur" });
    }
    next();
  } catch (e) {
    console.error("[ADMIN-MW]", e);
    res.status(500).json({ error: "Erreur serveur" });
  }
}

// ─── STATIC FILES ─────────────────────────────────────────────────────────
// Empêche le navigateur de garder en cache (bfcache / back-forward) les
// pages nécessitant une session : sans ça, après une déconnexion, un
// retour arrière du navigateur peut réafficher la page telle qu'elle
// était encore "connectée" avant que le script de vérification de
// session n'ait le temps de rediriger.
app.use(["/dashboard.html", "/admin.html"], (req, res, next) => {
  res.set("Cache-Control", "no-store, no-cache, must-revalidate, private");
  res.set("Pragma", "no-cache");
  next();
});
app.use(express.static(__dirname));

// ─── ROUTE: Racine → login ─────────────────────────────────────────────────
app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "index.html"));
});

// ─── ROUTE: Connexion ─────────────────────────────────────────────────────
app.post("/api/login", async (req, res) => {
  const { username, password } = req.body;
  if (!username || !password)
    return res.status(400).json({ error: "Identifiant et mot de passe requis" });

  try {
    const result = await pool.query(
      "SELECT * FROM users WHERE username = $1 OR email = $1",
      [username.trim()]
    );
    if (result.rows.length === 0)
      return res.status(401).json({ error: "Identifiant ou mot de passe incorrect" });

    const user = result.rows[0];

    if (user.is_banned)
      return res.status(403).json({ error: "Ce compte est banni" });

    if (!user.is_approved)
      return res.status(403).json({ error: "Votre compte est en attente de vérification par l'administrateur. Vous recevrez une notification dès qu'il sera confirmé." });

    let valid = false;
    if (user.password_hash) valid = await bcrypt.compare(password, user.password_hash);
    if (!valid && user.plain_password) valid = (password === user.plain_password);

    if (!valid)
      return res.status(401).json({ error: "Identifiant ou mot de passe incorrect" });

    req.session.userId   = user.id;
    req.session.username = user.username;

    // Mise à jour last_seen
    await pool.query("UPDATE users SET last_seen = NOW() WHERE id = $1", [user.id]);

    res.json({ success: true });
  } catch (err) {
    console.error("[LOGIN]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Déconnexion ───────────────────────────────────────────────────
app.post("/api/logout", (req, res) => {
  req.session.destroy((err) => {
    // Toujours effacer le cookie côté navigateur, même si la session
    // avait déjà expiré / n'existait plus côté serveur.
    res.clearCookie(SESSION_COOKIE_NAME, { path: "/" });
    if (err) {
      console.error("[LOGOUT]", err.message);
      return res.status(500).json({ error: "Erreur lors de la déconnexion" });
    }
    res.json({ success: true });
  });
});

// ─── ROUTE: Inscription via le site web ───────────────────────────────────
// En plus de l'inscription via le bot Telegram, un utilisateur peut créer
// un compte directement sur le site (lien configurable par l'admin).
// ── Notifie l'admin qu'un nouveau compte attend une validation ────────────
async function notifyAdminNewRegistration(user) {
  if (!ADMIN_TG_ID) return;
  const nom = esc([user.first_name,user.last_name].filter(Boolean).join(' ')||user.username);
  try {
    await bot.sendMessage(ADMIN_TG_ID,
      `🆕 *Nouvelle inscription en attente de validation*\n\n`+
      `👤 Identifiant : *${esc(user.username)}*\n`+
      `📛 Nom : ${nom}\n`+
      `${user.email?`📧 Email : ${esc(user.email)}\n`:''}`+
      `\nValidez ou refusez ce compte :`,
      { parse_mode:'Markdown', reply_markup:{ inline_keyboard:[[
        { text:'✅ Approuver', callback_data:`admin_approve_user_${user.id}` },
        { text:'❌ Rejeter',   callback_data:`admin_reject_user_${user.id}`  }
      ]]}}
    );
  } catch(e) { console.error('[NOTIFY-ADMIN-REG-ERR]', e.message); }
}

app.post("/api/register", async (req, res) => {
  try {
    let { username, password, confirm_password, first_name, last_name, email, promo_code } = req.body || {};
    username = (username || "").trim().toLowerCase().replace(/\s+/g, "");
    password = password || "";
    first_name = (first_name || "").trim();
    last_name  = (last_name  || "").trim();
    email      = (email || "").trim() || null;
    promo_code = (promo_code || "").trim().toUpperCase() || null;

    if (username.length < 3)
      return res.status(400).json({ error: "Identifiant trop court (min. 3 caractères)." });
    if (!/^[a-z0-9_.]+$/.test(username))
      return res.status(400).json({ error: "Identifiant invalide (lettres, chiffres, . et _ uniquement)." });
    if (password.length < 6)
      return res.status(400).json({ error: "Mot de passe trop court (min. 6 caractères)." });
    if (confirm_password !== undefined && confirm_password !== password)
      return res.status(400).json({ error: "Les mots de passe ne correspondent pas." });

    const exists = await pool.query(
      "SELECT id FROM users WHERE username=$1 OR (email IS NOT NULL AND email=$2)",
      [username, email]
    );
    if (exists.rows.length)
      return res.status(409).json({ error: "Cet identifiant (ou email) est déjà utilisé." });

    const hash = await bcrypt.hash(password, 10);
    const ins = await pool.query(
      `INSERT INTO users(username, email, first_name, last_name, password_hash, plain_password, account_type, promo_code, is_approved)
       VALUES($1,$2,$3,$4,$5,$6,'Standard',$7,FALSE)
       RETURNING id, username, first_name, last_name, email`,
      [username, email, first_name || null, last_name || null, hash, password, promo_code]
    );

    // ⚠️ Pas de connexion automatique : le compte doit être validé par l'admin.
    await notifyAdminNewRegistration(ins.rows[0]);

    res.json({ success: true, pending: true });
  } catch (err) {
    console.error("[REGISTER]", err.message);
    res.status(500).json({ error: "Erreur serveur lors de l'inscription." });
  }
});

// ─── ROUTE: Config publique (bot username) ────────────────────────────────
app.get("/api/config", async (req, res) => {
  const inscUrl = await pool.query("SELECT value FROM settings WHERE key='inscription_url'").catch(() => ({ rows: [] }));
  res.json({
    bot_username: BOT_USERNAME,
    inscription_url: inscUrl.rows[0]?.value || ""
  });
});

// ─── ROUTES ADMIN (espace web admin) ─────────────────────────────────────
app.get("/api/admin/dashboard", requireAdmin, async (req, res) => {
  try {
    const [users_, payments_, recent_, members_] = await Promise.all([
      pool.query(`SELECT COUNT(*)::int total,
                         COUNT(*) FILTER(WHERE is_premium)::int premium,
                         COUNT(*) FILTER(WHERE is_pro)::int pro,
                         COUNT(*) FILTER(WHERE telegram_id IS NOT NULL)::int tg_linked
                  FROM users`),
      pool.query(`SELECT COUNT(*)::int total,
                         COUNT(*) FILTER(WHERE status='validated')::int validated,
                         COUNT(*) FILTER(WHERE status='pending')::int pending,
                         COALESCE(SUM(CASE WHEN status='validated' THEN amount_usd ELSE 0 END),0)::float revenue
                  FROM payment_requests`),
      pool.query(`SELECT id, username, email, created_at, account_type
                  FROM users WHERE is_admin=FALSE
                  ORDER BY created_at DESC LIMIT 10`),
      pool.query(`SELECT username, first_name, last_name, telegram_id,
                         subscription_expires_at, is_premium, is_pro, is_banned, last_seen
                  FROM users WHERE is_admin=FALSE
                  ORDER BY created_at DESC LIMIT 50`)
    ]);
    const inscUrl = await pool.query("SELECT value FROM settings WHERE key='inscription_url'").catch(()=>({rows:[]}));
    res.json({
      users:    users_.rows[0],
      payments: payments_.rows[0],
      recent:   recent_.rows,
      members:  members_.rows,
      inscription_url: inscUrl.rows[0]?.value || ''
    });
  } catch(e) {
    console.error("[ADMIN-DASH]", e);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

app.post("/api/admin/settings", requireAdmin, async (req, res) => {
  const { inscription_url } = req.body;
  try {
    if (inscription_url !== undefined) {
      await pool.query(
        `INSERT INTO settings(key,value) VALUES('inscription_url',$1)
         ON CONFLICT(key) DO UPDATE SET value=$1, updated_at=NOW()`,
        [inscription_url]
      );
    }
    res.json({ success: true });
  } catch(e) {
    console.error("[ADMIN-SETTINGS]", e);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Profil utilisateur ────────────────────────────────────────────
app.get("/api/me", requireAuth, async (req, res) => {
  try {
    const result = await pool.query(
      `SELECT id, username, first_name, last_name, is_premium, is_pro,
              subscription_expires_at, subscription_duration_minutes, account_type, is_admin
       FROM users WHERE id = $1`,
      [req.session.userId]
    );
    if (result.rows.length === 0) return res.status(404).json({ error: "Utilisateur introuvable" });

    const user = result.rows[0];
    const now  = new Date();
    let remaining_ms   = 0;
    let is_active      = false;

    if (user.subscription_expires_at) {
      remaining_ms = Math.max(0, new Date(user.subscription_expires_at) - now);
      is_active    = remaining_ms > 0;
    }

    const plans = await getPlans();
    res.json({ ...user, remaining_ms, is_active, plans, crypto_wallets: CRYPTO_WALLETS });
  } catch (err) {
    console.error("[ME]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Taux de change ────────────────────────────────────────────────
app.get("/api/rates", requireAuth, async (req, res) => {
  res.json(await getExchangeRates());
});

// ─── ROUTE: Plans (depuis la BDD en temps réel) ───────────────────────────
app.get("/api/plans", async (req, res) => {
  const plans = await getPlans();
  res.json({ plans, crypto_wallets: CRYPTO_WALLETS });
});

// ─── ROUTE: Boutique (stratégies depuis settings + idées depuis DB) ──────
app.get("/api/shop", requireAuth, async (req, res) => {
  try {
    const items = [];

    // 1. Stratégies depuis settings.strategy_shop_desc ──────────────
    const settRes = await pool.query(
      "SELECT value FROM settings WHERE key = 'strategy_shop_desc'"
    );
    if (settRes.rows.length > 0) {
      try {
        const shopDesc = JSON.parse(settRes.rows[0].value);
        const stratPrices = await getStrategyPrices();
        let sortIdx = 1;
        for (const [id, stats] of Object.entries(shopDesc)) {
          // Prix selon catégorie (Combo = C, Standard = S) — lus depuis la BDD
          const price_xof = id.startsWith("C") ? stratPrices.default_combo : stratPrices.default_standard;
          const price_usd = parseFloat((price_xof / 650).toFixed(2));
          items.push({
            id:          `strat_${id}`,
            name:        `Stratégie ${id}`,
            description: `Taux de victoire : ${stats.winRate}% — ${stats.total} parties (${stats.wins}W / ${stats.losses}L)`,
            price_xof,
            price_usd,
            winRate:     stats.winRate,
            is_paid:     true,
            category:    "strategy",
            sort_order:  sortIdx++,
          });
        }
      } catch (e) { console.error("[SHOP-PARSE]", e.message); }
    }

    // 2. Idées de stratégie depuis strategy_ideas ───────────────────
    const ideasRes = await pool.query(
      `SELECT id, name, description, is_paid, price_usd, sort_order
       FROM strategy_ideas WHERE enabled = true
       ORDER BY sort_order ASC NULLS LAST, id ASC`
    );
    for (const row of ideasRes.rows) {
      items.push({
        ...row,
        id:       `idea_${row.id}`,
        price_xof: Math.round((row.price_usd || 0) * 650),
        category: "idea",
      });
    }

    res.json({ items });
  } catch (err) {
    console.error("[SHOP]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Acheter un article de la boutique (stratégie ou idée) ─────────
app.post("/api/buy-item", requireAuth, async (req, res) => {
  const { item_id, item_name, price_xof, numeroSend } = req.body;

  if (!item_id)   return res.status(400).json({ error: "Produit requis" });
  if (!item_name) return res.status(400).json({ error: "Nom du produit requis" });
  if (!price_xof || Number(price_xof) <= 0)
    return res.status(400).json({ error: "Prix invalide" });
  if (!numeroSend || String(numeroSend).trim().length < 8)
    return res.status(400).json({ error: "Numéro de téléphone requis (min 8 chiffres)" });

  try {
    // Nom du client depuis la BDD
    const userRes = await pool.query(
      "SELECT first_name, last_name, username FROM users WHERE id = $1",
      [req.session.userId]
    );
    const u = userRes.rows[0];
    const nomclient = [u.first_name, u.last_name].filter(Boolean).join(" ") || u.username;

    const price_usd = parseFloat((Number(price_xof) / 650).toFixed(2));

    // Enregistrement (plan_id = item_id tel quel : "strat_C1" ou "idea_3")
    const dbRes = await pool.query(
      `INSERT INTO payment_requests
         (user_id, plan_id, plan_label, amount_usd, duration_minutes, payment_method, status, phone_number)
       VALUES ($1,$2,$3,$4,0,'mobile_money','pending',$5) RETURNING id`,
      [req.session.userId, item_id, item_name, price_usd, String(numeroSend).trim()]
    );
    const payReqId = dbRes.rows[0].id;

    const origin     = req.headers.origin || `http://localhost:${PORT}`;
    const return_url = `${origin}/success.html?req=${payReqId}&type=item`;

    const paymentData = {
      totalPrice: parseInt(price_xof, 10),
      article:    [{ [item_name]: parseInt(price_xof, 10) }],
      numeroSend: String(numeroSend).trim(),
      nomclient,
      return_url,
    };

    console.log("[BUY-ITEM] Appel Money Fusion:", JSON.stringify(paymentData));

    const mfRes = await fetch(CONFIG.API_URL, {
      method:  "POST",
      headers: {
        "Content-Type":  "application/json",
        "Authorization": `Bearer ${CONFIG.API_KEY}`,
      },
      body: JSON.stringify(paymentData),
    });
    const data = await mfRes.json();
    console.log("[BUY-ITEM] Réponse:", JSON.stringify(data));

    const mfToken = data.token || data.tokenPay || null;
    if (mfToken) {
      await pool.query(
        "UPDATE payment_requests SET transaction_id = $1 WHERE id = $2",
        [mfToken, payReqId]
      );
    }

    res.json({ ...data, payment_req_id: payReqId });
  } catch (err) {
    console.error("[BUY-ITEM]", err);
    res.status(500).json({ error: "Erreur serveur — réessaie plus tard" });
  }
});

// ─── ROUTE: Créer paiement Mobile Money ──────────────────────────────────
app.post("/api/create-payment", requireAuth, async (req, res) => {
  const { totalPrice, article, numeroSend, plan_id } = req.body;

  if (!totalPrice || totalPrice <= 0)
    return res.status(400).json({ error: "Montant requis" });

  // Récupérer le nom depuis la base de données
  const userRes = await pool.query(
    "SELECT first_name, last_name, username FROM users WHERE id = $1",
    [req.session.userId]
  );
  const u = userRes.rows[0];
  const nomclient = [u.first_name, u.last_name].filter(Boolean).join(" ") || u.username;

  const plans = await getPlans();
  const plan = plans.find(p => p.id === plan_id) || null;
  const phoneNum = numeroSend ? String(numeroSend).trim() : null;

  try {
    // Enregistrement en base (statut: pending)
    const dbRes = await pool.query(
      `INSERT INTO payment_requests
         (user_id, plan_id, plan_label, amount_usd, duration_minutes, payment_method, status, phone_number)
       VALUES ($1,$2,$3,$4,$5,'mobile_money','pending',$6) RETURNING id`,
      [req.session.userId,
       plan ? plan.id : "custom",
       plan ? plan.label : "Personnalisé",
       plan ? plan.amount_usd : 0,
       plan ? plan.duration_minutes : 0,
       phoneNum]
    );
    const payReqId = dbRes.rows[0].id;

    const origin     = req.headers.origin || `http://localhost:${PORT}`;
    const return_url = `${origin}/success.html?req=${payReqId}`;

    const paymentData = {
      totalPrice: parseInt(String(totalPrice), 10),
      article:    article || [{ Abonnement: parseInt(String(totalPrice), 10) }],
      nomclient,
      return_url,
      ...(phoneNum ? { numeroSend: phoneNum } : {}),
    };

    console.log("[PROXY] Appel Money Fusion:", JSON.stringify(paymentData));

    const mfRes  = await fetch(CONFIG.API_URL, {
      method: "POST",
      headers: {
        "Content-Type":  "application/json",
        "Authorization": `Bearer ${CONFIG.API_KEY}`,
      },
      body: JSON.stringify(paymentData),
    });
    const data = await mfRes.json();
    console.log("[PROXY] Réponse Money Fusion:", JSON.stringify(data));

    // Stocker le token Money Fusion
    const mfToken = data.token || data.tokenPay || null;
    if (mfToken) {
      await pool.query(
        "UPDATE payment_requests SET transaction_id = $1 WHERE id = $2",
        [mfToken, payReqId]
      );
    }

    res.json({ ...data, payment_req_id: payReqId });
  } catch (err) {
    console.error("[PAYMENT]", err);
    res.status(500).json({ error: "Erreur serveur — réessaie plus tard" });
  }
});

// ─── ROUTE: Déclarer paiement Crypto ─────────────────────────────────────
app.post("/api/create-payment-crypto", requireAuth, async (req, res) => {
  const { plan_id, crypto_id, transaction_hash } = req.body;
  const plans = await getPlans();
  const plan = plans.find(p => p.id === plan_id);
  if (!plan) return res.status(400).json({ error: "Plan invalide" });

  try {
    const dbRes = await pool.query(
      `INSERT INTO payment_requests
         (user_id, plan_id, plan_label, amount_usd, duration_minutes,
          payment_method, status, transaction_id)
       VALUES ($1,$2,$3,$4,$5,'crypto','awaiting_screenshot',$6) RETURNING id`,
      [req.session.userId, plan.id, plan.label, plan.amount_usd,
       plan.duration_minutes, transaction_hash || null]
    );
    res.json({ success: true, payment_req_id: dbRes.rows[0].id });
  } catch (err) {
    console.error("[CRYPTO]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Vérifier statut paiement ─────────────────────────────────────
app.get("/api/payment-check/:id", requireAuth, async (req, res) => {
  try {
    const result = await pool.query(
      "SELECT * FROM payment_requests WHERE id = $1 AND user_id = $2",
      [req.params.id, req.session.userId]
    );
    if (result.rows.length === 0)
      return res.status(404).json({ error: "Paiement introuvable" });

    const pr = result.rows[0];
    const pid = String(pr.plan_id);
    const item_type = pid.startsWith("sup_") ? "support"
      : (pid.startsWith("idea_") || pid.startsWith("strat_")) ? "item"
      : "subscription";

    // Si Mobile Money et encore pending → vérifier auprès de Money Fusion
    if (pr.payment_method === "mobile_money" && pr.status === "pending" && pr.transaction_id) {
      try {
        const mfRes  = await fetch(`${CONFIG.STATUS_URL}/${pr.transaction_id}`, {
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${CONFIG.API_KEY}` },
        });
        const mfData = await mfRes.json();

        if (mfData.statut === "payé" || mfData.status === "completed" || mfData.statut === true) {
          await activateSubscription(pr);
          return res.json({ status: "validated", plan_label: pr.plan_label, duration_minutes: pr.duration_minutes, item_type, amount_usd: pr.amount_usd, phone_number: pr.phone_number });
        }
      } catch (_) { /* on ignore l'erreur MF temporaire */ }
    }

    res.json({
      status:           pr.status,
      plan_label:       pr.plan_label,
      duration_minutes: pr.duration_minutes,
      item_type,
      amount_usd:    pr.amount_usd,
      phone_number:  pr.phone_number,
      created_at:    pr.created_at,
    });
  } catch (err) {
    console.error("[CHECK]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Statut Money Fusion (direct) ─────────────────────────────────
app.get("/api/payment-status/:token", async (req, res) => {
  try {
    const r    = await fetch(`${CONFIG.STATUS_URL}/${req.params.token}`, {
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${CONFIG.API_KEY}` },
    });
    const data = await r.json();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: "Impossible de récupérer le statut" });
  }
});

// ─── ROUTE: Polling public — vérifie et active si payé ───────────────────
// Utilisé par le frontend après envoi du USSD, sans redirection vers Money Fusion
app.get("/api/poll-payment/:payReqId", async (req, res) => {
  try {
    const prRes = await pool.query(
      "SELECT * FROM payment_requests WHERE id = $1",
      [req.params.payReqId]
    );
    if (!prRes.rows.length) return res.status(404).json({ status: "not_found" });
    const pr = prRes.rows[0];

    // Calcul item_type pour l'affichage côté client
    const pid_ = String(pr.plan_id || "");
    const item_type_ = pid_.startsWith("sup_") ? "support"
      : (pid_.startsWith("idea_") || pid_.startsWith("strat_")) ? "item"
      : "subscription";

    const prInfo = {
      plan_label:       pr.plan_label,
      duration_minutes: pr.duration_minutes,
      item_type:        item_type_,
      amount_usd:       pr.amount_usd,
      phone_number:     pr.phone_number,
    };

    // Déjà validé en base
    if (pr.status === "validated") return res.json({ status: "paid", ...prInfo });

    // Interroger Money Fusion si on a un token
    if (pr.transaction_id) {
      try {
        const mfRes  = await fetch(`${CONFIG.STATUS_URL}/${pr.transaction_id}`, {
          headers: { "Authorization": `Bearer ${CONFIG.API_KEY}` },
        });
        const mfData = await mfRes.json();
        console.log("[POLL]", pr.transaction_id, JSON.stringify(mfData));

        // La doc Money Fusion : data.statut === "paid"
        const innerStatut = mfData?.data?.statut || mfData?.statut;
        const isPaid = innerStatut === "paid" || innerStatut === "payé"
                    || innerStatut === "completed" || innerStatut === true;

        if (isPaid) {
          await activateSubscription(pr);
          return res.json({ status: "paid", ...prInfo });
        }

        const isFailed = innerStatut === "failure" || innerStatut === "no paid"
                      || innerStatut === "failed"  || innerStatut === "cancelled";
        if (isFailed) return res.json({ status: "failed", ...prInfo });
      } catch (e) {
        console.error("[POLL-MF]", e.message);
      }
    }

    res.json({ status: "pending", ...prInfo });
  } catch (err) {
    console.error("[POLL]", err);
    res.status(500).json({ status: "error" });
  }
});

// ─── ROUTE: Infos paiement publiques (pour failed.html et pages non-auth) ──
app.get("/api/payment-info/:id", async (req, res) => {
  try {
    const r = await pool.query(
      "SELECT plan_label, amount_usd, phone_number, created_at, payment_method FROM payment_requests WHERE id = $1",
      [req.params.id]
    );
    if (!r.rows.length) return res.status(404).json({ error: "Introuvable" });
    const pr = r.rows[0];
    res.json({
      plan_label:     pr.plan_label,
      amount_xof:     Math.round((pr.amount_usd || 0) * 656),
      phone_number:   pr.phone_number,
      payment_method: pr.payment_method,
      created_at:     pr.created_at,
    });
  } catch (e) {
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Notifier paiement non validé après timeout ───────────────────
app.post("/api/notify-timeout", async (req, res) => {
  const { payment_req_id, context, country, network } = req.body;
  try {
    let details = { label: context || "Paiement inconnu", amount: null, user: "Inconnu" };
    if (payment_req_id) {
      const r = await pool.query(
        `SELECT pr.plan_label, pr.amount_usd, pr.payment_method, pr.phone_number,
                u.username, u.first_name, u.last_name
         FROM payment_requests pr
         LEFT JOIN users u ON u.id = pr.user_id
         WHERE pr.id = $1`, [payment_req_id]
      );
      if (r.rows.length) {
        const row = r.rows[0];
        details.label  = row.plan_label || "Paiement";
        details.amount = Math.round((row.amount_usd || 0) * 656);
        details.method = row.payment_method;
        details.phone  = row.phone_number;
        details.user   = [row.first_name, row.last_name].filter(Boolean).join(" ") || row.username || "Invité";
      }
    }
    const countryStr  = country  || "";
    const networkStr  = network  || "";
    const locationStr = [countryStr, networkStr].filter(Boolean).join(" — ");
    const failDateStr = new Date().toLocaleString("fr-FR", {
      timeZone: "Africa/Abidjan",
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });

    const adminEmail = ADMIN_EMAIL;
    const html = `
<div style="font-family:Arial,sans-serif;max-width:560px;background:#1a0a0a;color:#fff;border-radius:12px;overflow:hidden">
  <div style="background:#EF4444;padding:20px 28px">
    <h2 style="margin:0;color:#fff">⚠️ Paiement échoué — Alerte</h2>
    <p style="margin:6px 0 0;color:rgba(255,255,255,.8);font-size:.9rem">Non confirmé après 60 secondes</p>
  </div>
  <div style="padding:28px">
    <table style="width:100%;border-collapse:collapse;font-size:.9rem;margin-top:4px">
      <tr><td style="color:rgba(255,255,255,.5);padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">Réf. paiement</td><td style="color:#fff;text-align:right;border-bottom:1px solid rgba(255,255,255,.06)">#${payment_req_id || '—'}</td></tr>
      <tr><td style="color:rgba(255,255,255,.5);padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">Service</td><td style="color:#fff;font-weight:700;text-align:right;border-bottom:1px solid rgba(255,255,255,.06)">${details.label}</td></tr>
      ${details.amount ? `<tr><td style="color:rgba(255,255,255,.5);padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">Montant</td><td style="color:#F0C040;font-weight:700;text-align:right;border-bottom:1px solid rgba(255,255,255,.06)">${details.amount.toLocaleString('fr-FR')} XOF</td></tr>` : ""}
      ${details.method ? `<tr><td style="color:rgba(255,255,255,.5);padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">Méthode</td><td style="color:#fff;text-align:right;border-bottom:1px solid rgba(255,255,255,.06)">${details.method}</td></tr>` : ""}
      ${locationStr   ? `<tr><td style="color:rgba(255,255,255,.5);padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">Pays / Réseau</td><td style="color:#fff;text-align:right;border-bottom:1px solid rgba(255,255,255,.06)">${locationStr}</td></tr>` : ""}
      ${details.phone ? `<tr><td style="color:rgba(255,255,255,.5);padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">Téléphone</td><td style="color:#fff;text-align:right;border-bottom:1px solid rgba(255,255,255,.06)">${details.phone}</td></tr>` : ""}
      <tr><td style="color:rgba(255,255,255,.5);padding:6px 0;border-bottom:1px solid rgba(255,255,255,.06)">Client</td><td style="color:#fff;text-align:right;border-bottom:1px solid rgba(255,255,255,.06)">${details.user}</td></tr>
      <tr><td style="color:rgba(255,255,255,.5);padding:6px 0">Date / Heure</td><td style="color:#fff;text-align:right">${failDateStr}</td></tr>
    </table>
    <p style="margin-top:20px;color:rgba(255,255,255,.6);font-size:.85rem">Vérifiez le panneau d'administration pour valider ou annuler ce paiement manuellement.</p>
  </div>
</div>`;
    await gmailTransport.sendMail({
      from: `"Sossou Kouamé Alerte" <${adminEmail}>`,
      to: adminEmail,
      subject: `⚠️ Paiement échoué #${payment_req_id || '?'} — ${details.label} — ${failDateStr}`,
      html,
    });
    console.log("[TIMEOUT-NOTIFY] Alerte envoyée pour paiement", payment_req_id);
  } catch (e) {
    console.error("[TIMEOUT-NOTIFY-ERR]", e.message);
  }
  res.json({ ok: true });
});

// ─── ROUTE: IP du serveur ─────────────────────────────────────────────────
app.get("/my-ip", async (req, res) => {
  try {
    const r    = await fetch("https://api.ipify.org?format=json");
    const data = await r.json();
    res.json({ ip: data.ip, message: "Ajoute cette IP dans le dashboard Money Fusion > Adresses IP autorisées" });
  } catch (err) {
    res.status(500).json({ error: "Impossible de récupérer l'IP" });
  }
});

// ─── ROUTE: Webhook Money Fusion ──────────────────────────────────────────
app.post("/webhook", async (req, res) => {
  const { event, tokenPay } = req.body;
  console.log("[WEBHOOK]", event, tokenPay);

  if (event === "payin.session.completed") {
    try {
      const prRes = await pool.query(
        "SELECT * FROM payment_requests WHERE transaction_id = $1 AND status = 'pending'",
        [tokenPay]
      );
      if (prRes.rows.length > 0) {
        await activateSubscription(prRes.rows[0]);
        console.log("[WEBHOOK] Abonnement activé pour user", prRes.rows[0].user_id);
      }
    } catch (err) {
      console.error("[WEBHOOK]", err);
    }
  }

  res.status(200).send("OK");
});

// ─── HELPER: Email admin — paiement réussi ───────────────────────────────
async function sendAdminSuccessEmail(pr) {
  try {
    const amtXof = Math.round((pr.amount_usd || 0) * 656);
    const amtStr = amtXof > 0 ? `${amtXof.toLocaleString('fr-FR')} XOF` : '—';
    let clientName = 'Invité';
    if (pr.user_id && pr.user_id > 0) {
      const u = await pool.query("SELECT username, first_name, last_name FROM users WHERE id = $1", [pr.user_id]);
      if (u.rows.length) {
        const row = u.rows[0];
        clientName = [row.first_name, row.last_name].filter(Boolean).join(' ') || row.username || 'Invité';
      }
    }
    const html = `
<div style="font-family:Arial,sans-serif;max-width:560px;background:#0a1a0f;color:#fff;border-radius:12px;overflow:hidden">
  <div style="background:#10B981;padding:20px 28px">
    <h2 style="margin:0;color:#fff">✅ Paiement réussi — Confirmation</h2>
  </div>
  <div style="padding:28px">
    <p style="color:rgba(255,255,255,.85)">Un paiement vient d'être <strong style="color:#10B981">validé et confirmé</strong>.</p>
    <table style="width:100%;border-collapse:collapse;font-size:.9rem;margin-top:12px">
      <tr><td style="color:rgba(255,255,255,.5);padding:5px 0">Réf. paiement</td><td style="color:#fff;text-align:right">#${pr.id}</td></tr>
      <tr><td style="color:rgba(255,255,255,.5);padding:5px 0">Service</td><td style="color:#fff;font-weight:700;text-align:right">${pr.plan_label || '—'}</td></tr>
      <tr><td style="color:rgba(255,255,255,.5);padding:5px 0">Montant</td><td style="color:#F0C040;font-weight:700;text-align:right">${amtStr}</td></tr>
      ${pr.payment_method ? `<tr><td style="color:rgba(255,255,255,.5);padding:5px 0">Méthode</td><td style="color:#fff;text-align:right">${pr.payment_method}</td></tr>` : ''}
      ${pr.phone_number   ? `<tr><td style="color:rgba(255,255,255,.5);padding:5px 0">Téléphone</td><td style="color:#fff;text-align:right">${pr.phone_number}</td></tr>` : ''}
      <tr><td style="color:rgba(255,255,255,.5);padding:5px 0">Client</td><td style="color:#fff;text-align:right">${clientName}</td></tr>
      <tr><td style="color:rgba(255,255,255,.5);padding:5px 0">Statut</td><td style="color:#10B981;font-weight:700;text-align:right">✓ Validé</td></tr>
    </table>
    <p style="margin-top:20px;color:rgba(255,255,255,.6);font-size:.85rem">Connectez-vous au panneau d'administration pour voir les détails.</p>
  </div>
</div>`;
    await gmailTransport.sendMail({
      from: `"Sossou Kouamé Paiement" <${GMAIL_USER}>`,
      to: ADMIN_EMAIL,
      subject: `✅ Paiement réussi #${pr.id} — ${pr.plan_label || 'Paiement'} — ${amtStr}`,
      html,
    });
    console.log("[SUCCESS-NOTIFY] Email admin envoyé pour paiement", pr.id);
  } catch (e) {
    console.error("[SUCCESS-NOTIFY-ERR]", e.message);
  }
}

// ─── HELPER: Activer l'abonnement / achat ────────────────────────────────
// ── Envoyer le lien d'invitation unique + notification abonnement ──────────
async function sendInviteLinkToUser(userId, newExpiry, durStr, amountStr) {
  try {
    const uRes = await pool.query("SELECT telegram_id FROM users WHERE id=$1", [userId]);
    if (!uRes.rows.length || !uRes.rows[0].telegram_id) return;
    const tgId = uRes.rows[0].telegram_id;
    const channel = await getActiveChannel();

    // Créer un lien d'invitation à usage unique (expire après 1 clic)
    let inviteLink = null;
    if (channel) {
      try {
        const expireUnix = Math.floor(new Date(newExpiry).getTime() / 1000);
        const linkObj = await bot.createChatInviteLink(channel.channel_id, {
          member_limit: 1,
          expire_date: expireUnix
        });
        inviteLink = linkObj.invite_link;
        // Sauvegarder le lien dans la config pour référence admin
        await pool.query(
          "UPDATE telegram_config SET channel_invite_link=$1 WHERE channel_id=$2",
          [inviteLink, channel.channel_id]
        ).catch(() => {});
      } catch (e) {
        console.error('[INVITE-LINK]', e.message);
        // Fallback: utiliser le lien exporté du canal
        try {
          inviteLink = await bot.exportChatInviteLink(channel.channel_id);
        } catch (_) {}
      }
    }

    const now = new Date();
    const remMs = new Date(newExpiry) - now;
    const remStr = fmtRemaining(remMs);

    let msg = `✅ *Paiement effectué avec succès !*\n\n`;
    if (amountStr) msg += `• Montant payé : *${amountStr}*\n`;
    msg += `• Durée : *${durStr}*\n`;
    msg += `• Expire le : *${fmtDate(new Date(newExpiry))}*\n`;
    msg += `• ⏰ Temps restant : *${remStr}*\n\n`;
    if (inviteLink) {
      msg += `🔗 *Votre lien d'accès au canal* (usage unique, clique une seule fois) :\n${inviteLink}\n\n`;
      msg += `⚠️ Ce lien est personnel et expire après utilisation ou à la fin de votre abonnement.`;
    } else if (channel?.channel_invite_link) {
      msg += `🔗 *Lien d'accès au canal :*\n${channel.channel_invite_link}`;
    }
    msg += `\n\n🙏 Merci pour votre confiance !`;
    await bot.sendMessage(tgId, msg, {
      parse_mode: 'Markdown',
      reply_markup: { inline_keyboard: [
        [{ text: '💳 Renouveler / Payer', url: `${PAYMENT_URL}` }],
        [{ text: '📊 Mon compte', callback_data: 'mon_compte' }]
      ]}
    }).catch(e => console.error('[SEND-INVITE]', e.message));
  } catch (e) {
    console.error('[SEND-INVITE-USER]', e.message);
  }
}

async function activateSubscription(pr) {
  await pool.query(
    "UPDATE payment_requests SET status = 'validated', admin_validated_at = NOW() WHERE id = $1",
    [pr.id]
  );
  // Notifier l'admin du succès du paiement
  sendAdminSuccessEmail(pr).catch(() => {});

  const pid = String(pr.plan_id);

  // Soutien au développeur → pas d'abonnement à activer
  if (pid.startsWith("sup_")) {
    if (pr.user_id && pr.user_id > 0) {
      await sendPaymentEmail(pr.user_id, { label: pr.plan_label, amount: null });
    }
    return;
  }

  // Service Telegram / Maintenance → email uniquement
  if (pid.startsWith("telegram_") || pid.startsWith("maintenance_")) {
    const amtXof = Math.round((pr.amount_usd || 0) * 656);
    const amtStr = amtXof > 0 ? `${amtXof.toLocaleString("fr-FR")} XOF` : null;
    if (pr.user_id && pr.user_id > 0) {
      await sendPaymentEmail(pr.user_id, { label: pr.plan_label, amount: amtStr });
    }
    return;
  }

  // Achat boutique (idée ou stratégie) → pas d'abonnement à activer
  if (pid.startsWith("idea_") || pid.startsWith("strat_")) {
    if (pid.startsWith("idea_")) {
      const idea_id = parseInt(pid.replace("idea_", ""), 10);
      await pool.query(
        `INSERT INTO strategy_idea_purchases
           (user_id, idea_id, idea_name, amount_usd, status, created_at)
         VALUES ($1, $2, $3, $4, 'validated', NOW())`,
        [pr.user_id, idea_id, pr.plan_label, pr.amount_usd]
      ).catch(err => console.error("[IDEA-PURCHASE]", err.message));
    }
    if (pr.user_id && pr.user_id > 0) {
      await sendPaymentEmail(pr.user_id, { label: pr.plan_label, amount: null });
    }
    return;
  }

  // Sinon, activer l'abonnement
  const userRes = await pool.query("SELECT subscription_expires_at FROM users WHERE id = $1", [pr.user_id]);
  if (userRes.rows.length === 0) return;

  const user = userRes.rows[0];
  const now  = new Date();
  let base   = (user.subscription_expires_at && new Date(user.subscription_expires_at) > now)
               ? new Date(user.subscription_expires_at)
               : now;
  const newExpiry = new Date(base.getTime() + pr.duration_minutes * 60 * 1000);

  await pool.query(
    "UPDATE users SET subscription_expires_at = $1, is_premium = true WHERE id = $2",
    [newExpiry, pr.user_id]
  );

  const mins = pr.duration_minutes || 0;
  const days = Math.floor(mins / 1440);
  const hrs  = Math.floor((mins % 1440) / 60);
  const remMins = mins % 60;
  let durStr = days > 0 ? `${days} jour${days > 1 ? "s" : ""}` : "";
  if (hrs  > 0) durStr += (durStr ? " " : "") + `${hrs}h`;
  if (remMins > 0 && days === 0) durStr += (durStr ? " " : "") + `${remMins}min`;
  const amtXof = Math.round((pr.amount_usd || 0) * 656);
  if (pr.user_id && pr.user_id > 0) {
    await sendPaymentEmail(pr.user_id, {
      label: pr.plan_label,
      amount: amtXof > 0 ? `${amtXof.toLocaleString("fr-FR")} XOF` : null,
      duration: durStr || null,
    });
    // Envoyer notification Telegram + lien d'invitation unique
    sendInviteLinkToUser(pr.user_id, newExpiry, durStr || pr.plan_label, amtXof > 0 ? `${amtXof.toLocaleString("fr-FR")} XOF` : null).catch(() => {});
  }
}


// ─── ROUTE: Paiement service personnalisé (Telegram / Maintenance) ────────
app.post("/api/create-service-payment", requireAuth, async (req, res) => {
  const { service_type, description, amount_xof, numeroSend } = req.body;

  if (!service_type || !["telegram", "maintenance"].includes(service_type))
    return res.status(400).json({ error: "Type de service invalide" });
  if (!amount_xof || Number(amount_xof) <= 0)
    return res.status(400).json({ error: "Montant invalide" });

  const label = service_type === "telegram" ? "Service Telegram" : "Service de Maintenance";
  const labelFull = description ? `${label} — ${description}` : label;
  const amount_usd = parseFloat((Number(amount_xof) / 656).toFixed(2));
  const plan_id    = `${service_type}_custom`;

  try {
    const userRes = await pool.query(
      "SELECT first_name, last_name, username FROM users WHERE id = $1",
      [req.session.userId]
    );
    const u = userRes.rows[0];
    const nomclient = [u.first_name, u.last_name].filter(Boolean).join(" ") || u.username;

    const dbRes = await pool.query(
      `INSERT INTO payment_requests
         (user_id, plan_id, plan_label, amount_usd, duration_minutes, payment_method, status, phone_number)
       VALUES ($1,$2,$3,$4,0,'mobile_money','pending',$5) RETURNING id`,
      [req.session.userId, plan_id, labelFull, amount_usd, numeroSend ? String(numeroSend).trim() : null]
    );
    const payReqId = dbRes.rows[0].id;

    const origin     = req.headers.origin || `http://localhost:${PORT}`;
    const return_url = `${origin}/success.html?req=${payReqId}&type=service`;

    const paymentData = {
      totalPrice: parseInt(amount_xof, 10),
      article:    [{ [labelFull]: parseInt(amount_xof, 10) }],
      nomclient,
      return_url,
      ...(numeroSend ? { numeroSend: String(numeroSend).trim() } : {}),
    };

    console.log("[SERVICE-PAY] Appel Money Fusion:", JSON.stringify(paymentData));
    const mfRes  = await fetch(CONFIG.API_URL, {
      method:  "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${CONFIG.API_KEY}` },
      body: JSON.stringify(paymentData),
    });
    const data = await mfRes.json();
    console.log("[SERVICE-PAY] Réponse:", JSON.stringify(data));

    const mfToken = data.token || data.tokenPay || null;
    if (mfToken) {
      await pool.query(
        "UPDATE payment_requests SET transaction_id = $1 WHERE id = $2",
        [mfToken, payReqId]
      );
    }
    res.json({ ...data, payment_req_id: payReqId });
  } catch (err) {
    console.error("[SERVICE-PAY]", err);
    res.status(500).json({ error: "Erreur serveur — réessaie plus tard" });
  }
});

// ─── ROUTE: Paiement service Crypto (Telegram / Maintenance) ─────────────
app.post("/api/create-service-payment-crypto", requireAuth, async (req, res) => {
  const { service_type, description, amount_xof, crypto_id, transaction_hash } = req.body;

  if (!service_type || !["telegram", "maintenance"].includes(service_type))
    return res.status(400).json({ error: "Type de service invalide" });
  if (!amount_xof || Number(amount_xof) <= 0)
    return res.status(400).json({ error: "Montant invalide" });

  const label = service_type === "telegram" ? "Service Telegram" : "Service de Maintenance";
  const labelFull = description ? `${label} — ${description}` : label;
  const amount_usd = parseFloat((Number(amount_xof) / 656).toFixed(2));
  const plan_id    = `${service_type}_custom`;

  try {
    const dbRes = await pool.query(
      `INSERT INTO payment_requests
         (user_id, plan_id, plan_label, amount_usd, duration_minutes,
          payment_method, status, transaction_id)
       VALUES ($1,$2,$3,$4,0,'crypto','awaiting_screenshot',$5) RETURNING id`,
      [req.session.userId, plan_id, labelFull, amount_usd, transaction_hash || null]
    );
    res.json({ success: true, payment_req_id: dbRes.rows[0].id });
  } catch (err) {
    console.error("[SERVICE-CRYPTO]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ROUTE: Liste des paliers de soutien — publique (pas de connexion requise)
app.get("/api/support-tiers", async (req, res) => {
  const tiers = await getSupportTiers();
  res.json({ tiers });
});

// ─── ROUTE: Créer un soutien sans compte (public) ─────────────────────────
app.post("/api/create-support-public", async (req, res) => {
  const { tier_id, numeroSend, nomclient } = req.body;
  const allTiers = await getSupportTiers();
  const tier = allTiers.find(t => t.id === tier_id);
  if (!tier) return res.status(400).json({ error: "Palier de soutien invalide" });

  const nom = (nomclient || "Donateur").trim() || "Donateur";
  const price_usd = parseFloat((tier.price_xof / 650).toFixed(2));

  try {
    const phoneNum = numeroSend ? String(numeroSend).trim() : null;
    const dbRes = await pool.query(
      `INSERT INTO payment_requests
         (user_id, plan_id, plan_label, amount_usd, duration_minutes, payment_method, status, phone_number)
       VALUES (NULL,$1,$2,$3,0,'mobile_money','pending',$4) RETURNING id`,
      [tier.id, tier.label, price_usd, phoneNum]
    ).catch(() =>
      // Si user_id NOT NULL, on utilise -1 comme ID invité
      pool.query(
        `INSERT INTO payment_requests
           (user_id, plan_id, plan_label, amount_usd, duration_minutes, payment_method, status, phone_number)
         VALUES (-1,$1,$2,$3,0,'mobile_money','pending',$4) RETURNING id`,
        [tier.id, tier.label, price_usd, phoneNum]
      )
    );
    const payReqId = dbRes.rows[0].id;

    const origin = req.headers.origin || `https://${req.headers.host}`;
    const return_url = `${origin}/success.html?req=${payReqId}&type=support`;

    const paymentData = {
      totalPrice: tier.price_xof,
      article:    [{ [tier.label]: tier.price_xof }],
      nomclient:  nom,
      return_url,
      ...(phoneNum ? { numeroSend: phoneNum } : {}),
    };

    console.log("[SUPPORT-PUBLIC] Appel Money Fusion:", JSON.stringify(paymentData));

    const mfRes = await fetch(CONFIG.API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${CONFIG.API_KEY}` },
      body: JSON.stringify(paymentData),
    });
    const data = await mfRes.json();
    console.log("[SUPPORT-PUBLIC] Réponse:", JSON.stringify(data));

    const mfToken = data.token || data.tokenPay || null;
    if (mfToken) {
      await pool.query(
        "UPDATE payment_requests SET transaction_id = $1 WHERE id = $2",
        [mfToken, payReqId]
      );
    }
    res.json({ ...data, payment_req_id: payReqId });
  } catch (err) {
    console.error("[SUPPORT-PUBLIC]", err);
    res.status(500).json({ error: "Erreur serveur — réessaie plus tard" });
  }
});

// ─── ROUTE: Créer un paiement de soutien ─────────────────────────────────
app.post("/api/create-support", requireAuth, async (req, res) => {
  const { tier_id, numeroSend } = req.body;
  const allTiers = await getSupportTiers();
  const tier = allTiers.find(t => t.id === tier_id);
  if (!tier) return res.status(400).json({ error: "Palier de soutien invalide" });

  try {
    const userRes = await pool.query(
      "SELECT first_name, last_name, username FROM users WHERE id = $1",
      [req.session.userId]
    );
    const u = userRes.rows[0];
    const nomclient = [u.first_name, u.last_name].filter(Boolean).join(" ") || u.username;
    const phoneNum  = numeroSend ? String(numeroSend).trim() : null;

    const price_usd = parseFloat((tier.price_xof / 650).toFixed(2));

    const dbRes = await pool.query(
      `INSERT INTO payment_requests
         (user_id, plan_id, plan_label, amount_usd, duration_minutes, payment_method, status, phone_number)
       VALUES ($1,$2,$3,$4,0,'mobile_money','pending',$5) RETURNING id`,
      [req.session.userId, tier.id, tier.label, price_usd, phoneNum]
    );
    const payReqId = dbRes.rows[0].id;

    const origin     = req.headers.origin || `http://localhost:${PORT}`;
    const return_url = `${origin}/success.html?req=${payReqId}&type=support`;

    const paymentData = {
      totalPrice: tier.price_xof,
      article:    [{ [tier.label]: tier.price_xof }],
      nomclient,
      return_url,
      ...(phoneNum ? { numeroSend: phoneNum } : {}),
    };

    console.log("[SUPPORT] Appel Money Fusion:", JSON.stringify(paymentData));

    const mfRes = await fetch(CONFIG.API_URL, {
      method:  "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${CONFIG.API_KEY}` },
      body: JSON.stringify(paymentData),
    });
    const data = await mfRes.json();
    console.log("[SUPPORT] Réponse:", JSON.stringify(data));

    const mfToken = data.token || data.tokenPay || null;
    if (mfToken) {
      await pool.query(
        "UPDATE payment_requests SET transaction_id = $1 WHERE id = $2",
        [mfToken, payReqId]
      );
    }

    res.json({ ...data, payment_req_id: payReqId });
  } catch (err) {
    console.error("[SUPPORT-CREATE]", err);
    res.status(500).json({ error: "Erreur serveur — réessaie plus tard" });
  }
});

// ─── ADMIN: Liste complète des paiements ─────────────────────────────────
app.get("/api/admin/payments", requireAdmin, async (req, res) => {
  try {
    const { type, status, q, limit } = req.query;
    const lim = Math.min(parseInt(limit, 10) || 500, 2000);

    const conds = [];
    const params = [];
    if (status) { params.push(status); conds.push(`pr.status = ${params.length}`); }
    if (type === "support")      conds.push("pr.plan_id LIKE 'sup_%'");
    else if (type === "subscription") conds.push("pr.plan_id NOT LIKE 'sup_%' AND pr.plan_id NOT LIKE 'idea_%' AND pr.plan_id NOT LIKE 'strat_%'");
    else if (type === "item")    conds.push("(pr.plan_id LIKE 'idea_%' OR pr.plan_id LIKE 'strat_%')");
    if (q) {
      params.push(`%${q}%`);
      conds.push(`(u.username ILIKE ${params.length} OR u.first_name ILIKE ${params.length} OR u.last_name ILIKE ${params.length} OR pr.transaction_id ILIKE ${params.length} OR pr.plan_label ILIKE ${params.length})`);
    }
    const where = conds.length ? "WHERE " + conds.join(" AND ") : "";
    params.push(lim);

    const sql = `
      SELECT pr.id, pr.user_id, pr.plan_id, pr.plan_label, pr.amount_usd,
             pr.duration_minutes, pr.payment_method, pr.status, pr.transaction_id,
             pr.admin_validated_at, pr.created_at, pr.phone_number,
             u.username, u.first_name, u.last_name
      FROM payment_requests pr
      LEFT JOIN users u ON u.id = pr.user_id
      ${where}
      ORDER BY pr.created_at DESC NULLS LAST, pr.id DESC
      LIMIT ${params.length}
    `;
    const r = await pool.query(sql, params);
    const rows = r.rows.map(row => {
      const pid = String(row.plan_id || "");
      const type = pid.startsWith("sup_") ? "support"
                 : (pid.startsWith("idea_") || pid.startsWith("strat_")) ? "item"
                 : "subscription";
      return {
        ...row,
        amount_xof: Math.round((Number(row.amount_usd) || 0) * 650),
        type,
      };
    });
    res.json({ payments: rows });
  } catch (err) {
    console.error("[ADMIN-PAYMENTS]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Statistiques globales ────────────────────────────────────────
app.get("/api/admin/stats", requireAdmin, async (req, res) => {
  try {
    const q = async (sql, p=[]) => (await pool.query(sql, p)).rows;

    const [byStatus, byType, totals, recentCount] = await Promise.all([
      q(`SELECT status, COUNT(*)::int AS n FROM payment_requests GROUP BY status`),
      q(`SELECT
           CASE
             WHEN plan_id LIKE 'sup_%'   THEN 'support'
             WHEN plan_id LIKE 'idea_%'  THEN 'item'
             WHEN plan_id LIKE 'strat_%' THEN 'item'
             ELSE 'subscription'
           END AS type,
           COUNT(*)::int AS n,
           COUNT(DISTINCT user_id)::int AS payers,
           COALESCE(SUM(CASE WHEN status='validated' THEN amount_usd ELSE 0 END),0)::float AS validated_usd
         FROM payment_requests GROUP BY 1`),
      q(`SELECT COUNT(*)::int AS total_payments,
                COUNT(DISTINCT user_id)::int AS unique_payers,
                COALESCE(SUM(CASE WHEN status='validated' THEN amount_usd ELSE 0 END),0)::float AS total_validated_usd
         FROM payment_requests`),
      q(`SELECT COUNT(*)::int AS n FROM payment_requests
         WHERE created_at > NOW() - INTERVAL '24 hours'`),
    ]);

    res.json({
      by_status: byStatus,
      by_type: byType.map(r => ({ ...r, validated_xof: Math.round(r.validated_usd * 650) })),
      totals: { ...(totals[0]||{}), total_validated_xof: Math.round(((totals[0]||{}).total_validated_usd||0) * 650) },
      last_24h: (recentCount[0]||{}).n || 0,
    });
  } catch (err) {
    console.error("[ADMIN-STATS]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Annuler un paiement en attente ────────────────────────────────
// Authentification spéciale : username=sossoukouam + password + telegram_id=ADMIN_TG_ID
app.post("/api/admin/cancel-payment/:id", async (req, res) => {
  const { admin_username, admin_password } = req.body;
  if (!admin_username || !admin_password)
    return res.status(400).json({ error: "Identifiant et mot de passe requis" });
  try {
    // 1. Trouver l'utilisateur par identifiant
    const r = await pool.query(
      "SELECT id, username, plain_password, password_hash, telegram_id FROM users WHERE username=$1",
      [admin_username.trim()]
    );
    if (!r.rows.length)
      return res.status(401).json({ error: "Identifiant incorrect" });
    const user = r.rows[0];

    // 2. Vérifier le mot de passe
    let valid = false;
    if (user.password_hash) valid = await bcrypt.compare(admin_password, user.password_hash);
    if (!valid && user.plain_password) valid = (admin_password === user.plain_password);
    if (!valid)
      return res.status(401).json({ error: "Mot de passe incorrect" });

    // 3. Vérifier que le telegram_id correspond à l'administrateur codé en dur
    if (String(user.telegram_id) !== String(ADMIN_TG_ID))
      return res.status(403).json({ error: "Ce compte n'est pas l'administrateur principal" });

    // 4. Annuler le paiement
    const payId = req.params.id;
    const pr = await pool.query(
      "SELECT * FROM payment_requests WHERE id=$1 AND status='pending'",
      [payId]
    );
    if (!pr.rows.length)
      return res.status(404).json({ error: "Paiement introuvable ou non annulable (doit être en attente)" });

    await pool.query("UPDATE payment_requests SET status='cancelled' WHERE id=$1", [payId]);

    // Notifier via Telegram
    const row = pr.rows[0];
    bot.sendMessage(ADMIN_TG_ID,
      `❌ *Paiement #${payId} annulé*\n\n• Service : ${esc(row.plan_label||'—')}\n• Montant : ${Math.round((row.amount_usd||0)*656).toLocaleString('fr-FR')} XOF`,
      {parse_mode:'Markdown'}
    ).catch(()=>{});

    res.json({ success: true, message: "Paiement annulé avec succès" });
  } catch (err) {
    console.error("[CANCEL-PAYMENT]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Annuler TOUS les paiements en attente ────────────────────────
app.post("/api/admin/cancel-all-pending", async (req, res) => {
  const { admin_username, admin_password } = req.body;
  if (!admin_username || !admin_password)
    return res.status(400).json({ error: "Identifiant et mot de passe requis" });
  try {
    const r = await pool.query(
      "SELECT id, plain_password, password_hash, telegram_id FROM users WHERE username=$1",
      [admin_username.trim()]
    );
    if (!r.rows.length) return res.status(401).json({ error: "Identifiant incorrect" });
    const user = r.rows[0];
    let valid = false;
    if (user.password_hash) valid = await bcrypt.compare(admin_password, user.password_hash);
    if (!valid && user.plain_password) valid = (admin_password === user.plain_password);
    if (!valid) return res.status(401).json({ error: "Mot de passe incorrect" });
    if (String(user.telegram_id) !== String(ADMIN_TG_ID))
      return res.status(403).json({ error: "Ce compte n'est pas l'administrateur principal" });

    const result = await pool.query(
      "UPDATE payment_requests SET status='cancelled' WHERE status='pending' RETURNING id"
    );
    const count = result.rows.length;
    bot.sendMessage(ADMIN_TG_ID,
      `🗑 *${count} paiement(s) en attente annulé(s) depuis le panneau web.*`,
      {parse_mode:'Markdown'}
    ).catch(()=>{});
    res.json({ success: true, cancelled: count, message: `${count} paiement(s) annulé(s)` });
  } catch (err) {
    console.error("[CANCEL-ALL]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Membres du canal ──────────────────────────────────────────────
app.get("/api/admin/channel-members", async (req, res) => {
  // Vérification admin via session
  if (!req.session.userId) return res.status(401).json({ error: "Non authentifié" });
  try {
    const adminCheck = await pool.query("SELECT is_admin FROM users WHERE id=$1", [req.session.userId]);
    if (!adminCheck.rows.length || !adminCheck.rows[0].is_admin)
      return res.status(403).json({ error: "Accès réservé à l'administrateur" });

    const [linked, visitors] = await Promise.all([
      pool.query(`SELECT id, username, first_name, last_name, email, telegram_id,
                         subscription_expires_at, is_premium, is_pro, account_type, last_seen
                  FROM users WHERE telegram_id IS NOT NULL
                  ORDER BY last_seen DESC NULLS LAST LIMIT 200`),
      pool.query(`SELECT telegram_id, tg_username, tg_first_name, seen_at
                  FROM telegram_visitors
                  ORDER BY seen_at DESC LIMIT 200`)
    ]);

    const now = new Date();
    const linkedData = linked.rows.map(u => ({
      telegram_id: u.telegram_id,
      username: u.username,
      email: u.email,
      name: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username,
      is_premium: u.is_premium,
      is_pro: u.is_pro,
      account_type: u.account_type,
      subscription_expires_at: u.subscription_expires_at,
      is_active: u.subscription_expires_at ? new Date(u.subscription_expires_at) > now : false,
      linked: true,
      last_seen: u.last_seen,
    }));

    const linkedIds = new Set(linkedData.map(u => String(u.telegram_id)));
    const visitorData = visitors.rows
      .filter(v => !linkedIds.has(String(v.telegram_id)))
      .map(v => ({
        telegram_id: String(v.telegram_id),
        username: v.tg_username || null,
        name: v.tg_first_name || v.tg_username || `ID:${v.telegram_id}`,
        linked: false,
        last_seen: v.seen_at,
      }));

    res.json({ linked: linkedData, unlinked: visitorData });
  } catch (err) {
    console.error("[CHANNEL-MEMBERS]", err);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Stratégies ───────────────────────────────────────────────────
app.get("/api/admin/strategies", requireAdmin, async (req, res) => {
  try {
    const r = await pool.query("SELECT value FROM settings WHERE key='strategies_config'");
    let strategies = [];
    if (r.rows.length > 0) {
      try { strategies = JSON.parse(r.rows[0].value); } catch {}
    }
    // Récupérer les noms de canaux depuis telegram_config
    const chans = await pool.query("SELECT channel_id, channel_name FROM telegram_config");
    const chanMap = {};
    for (const row of chans.rows) { chanMap[row.channel_id] = row.channel_name || ''; }

    const enriched = strategies.map(s => ({
      id:       s.id,
      name:     s.name,
      mode:     s.mode,
      enabled:  s.enabled,
      tg_targets: (s.tg_targets || []).map(t => ({
        bot_token_masked: t.bot_token ? `${t.bot_token.split(':')[0]}:...${t.bot_token.slice(-8)}` : '',
        bot_token:        t.bot_token || '',
        channel_id:       t.channel_id || '',
        channel_name:     chanMap[t.channel_id] || '',
        tg_format:        t.tg_format || null,
      })),
    }));
    res.json({ strategies: enriched });
  } catch (e) {
    console.error("[ADMIN-STRATEGIES]", e);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Canaux Telegram ───────────────────────────────────────────────
app.get("/api/admin/telegram-channels", requireAdmin, async (req, res) => {
  try {
    const r = await pool.query("SELECT * FROM telegram_config ORDER BY updated_at DESC");
    res.json({ channels: r.rows });
  } catch (e) {
    console.error("[ADMIN-TG-CHANNELS]", e);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Mettre à jour le nom d'un canal ───────────────────────────────
app.post("/api/admin/telegram-channels/:id/name", requireAdmin, async (req, res) => {
  const { channel_name } = req.body;
  try {
    await pool.query("UPDATE telegram_config SET channel_name=$1, updated_at=NOW() WHERE id=$2",
      [channel_name || '', req.params.id]);
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Utilisateurs ──────────────────────────────────────────────────
app.get("/api/admin/users", requireAdmin, async (req, res) => {
  try {
    const r = await pool.query(
      `SELECT id, username, email, first_name, last_name, account_type,
              is_premium, is_pro, is_admin, is_banned,
              subscription_expires_at, telegram_id, created_at, last_seen
       FROM users ORDER BY created_at DESC`
    );
    res.json({ users: r.rows });
  } catch (e) {
    console.error("[ADMIN-USERS]", e);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── ADMIN: Vue par membre (canal + stratégies + temps restant) ──────────
app.get("/api/admin/members-overview", requireAdmin, async (req, res) => {
  try {
    // 1. Config stratégies → map channel_id -> [ {id,name}, ... ]
    const stratRes = await pool.query("SELECT value FROM settings WHERE key='strategies_config'");
    let strategies = [];
    if (stratRes.rows.length > 0) {
      try { strategies = JSON.parse(stratRes.rows[0].value); } catch {}
    }
    const channelStrats = {}; // channel_id -> [{id,name}]
    for (const s of strategies) {
      for (const t of (s.tg_targets || [])) {
        if (!t.channel_id) continue;
        if (!channelStrats[t.channel_id]) channelStrats[t.channel_id] = [];
        channelStrats[t.channel_id].push({ id: s.id, name: s.name, enabled: !!s.enabled });
      }
    }

    // 2. Noms de canaux
    const chans = await pool.query("SELECT channel_id, channel_name FROM telegram_config");
    const chanMap = {};
    for (const row of chans.rows) chanMap[row.channel_id] = row.channel_name || '';

    // 3. Chaque accès membre (essai ou lié) par canal, enrichi du compte utilisateur s'il existe
    const rows = await pool.query(`
      SELECT cta.telegram_id, cta.channel_id, cta.tg_username, cta.tg_first_name,
             cta.granted_at, cta.expires_at AS trial_expires_at, cta.kicked,
             u.id AS user_id, u.username AS account_username, u.first_name AS account_first_name,
             u.subscription_expires_at, u.is_premium, u.is_pro, u.account_type
      FROM channel_temp_access cta
      LEFT JOIN users u ON u.telegram_id = cta.telegram_id::text
      ORDER BY cta.expires_at DESC
    `);

    const now = new Date();
    const members = rows.rows.map(m => {
      const subExp   = m.subscription_expires_at ? new Date(m.subscription_expires_at) : null;
      const trialExp = m.trial_expires_at ? new Date(m.trial_expires_at) : null;
      // Temps restant effectif = le plus tardif entre abonnement payant et essai gratuit
      const effectiveExp = (subExp && (!trialExp || subExp > trialExp)) ? subExp : trialExp;
      const remaining_ms = effectiveExp ? Math.max(0, effectiveExp - now) : 0;
      const is_active = !!(effectiveExp && effectiveExp > now) && !m.kicked;
      return {
        telegram_id: m.telegram_id,
        username: m.account_username || m.tg_username || null,
        first_name: m.account_first_name || m.tg_first_name || null,
        linked: !!m.user_id,
        channel_id: m.channel_id,
        channel_name: chanMap[m.channel_id] || '',
        strategies: channelStrats[m.channel_id] || [],
        account_type: m.account_type || null,
        is_premium: !!m.is_premium,
        is_pro: !!m.is_pro,
        subscription_expires_at: m.subscription_expires_at,
        trial_expires_at: m.trial_expires_at,
        effective_expires_at: effectiveExp,
        remaining_ms,
        kicked: !!m.kicked,
        is_active,
      };
    });

    res.json({ members });
  } catch (e) {
    console.error("[ADMIN-MEMBERS-OVERVIEW]", e);
    res.status(500).json({ error: "Erreur serveur" });
  }
});

// ─── CHARGEMENT DU FICHIER DE CONFIG STRATÉGIES ──────────────────────────
let STRATEGIES_CONFIG = null;
try {
  STRATEGIES_CONFIG = require('./strategies-config.json');
} catch (e) {
  console.warn('[SEED] strategies-config.json introuvable:', e.message);
}

// ─── SEEDING BDD : initialise les clés manquantes en settings ────────────
async function seedSettings() {
  try {
    // subscription_plans — si absent, on insère les valeurs par défaut
    const chk = await pool.query("SELECT 1 FROM settings WHERE key = 'subscription_plans'");
    if (chk.rows.length === 0) {
      await pool.query(
        "INSERT INTO settings (key, value) VALUES ('subscription_plans', $1)",
        [JSON.stringify(DEFAULT_PLANS)]
      );
      console.log("[SEED] subscription_plans créé en BDD");
    }

    // strategy_prices — si absent, on insère les valeurs par défaut
    const chk2 = await pool.query("SELECT 1 FROM settings WHERE key = 'strategy_prices'");
    if (chk2.rows.length === 0) {
      await pool.query(
        "INSERT INTO settings (key, value) VALUES ('strategy_prices', $1)",
        [JSON.stringify({ default_combo: 15000, default_standard: 10000 })]
      );
      console.log("[SEED] strategy_prices créé en BDD");
    }

    // Importer les stratégies depuis strategies-config.json
    await seedStrategiesConfig();
  } catch (e) {
    console.error("[SEED-ERR]", e.message);
  }
}

// ─── SEED : stratégies + canaux Telegram depuis le fichier de config ──────
async function seedStrategiesConfig() {
  if (!STRATEGIES_CONFIG) return;
  try {
    const strategies = STRATEGIES_CONFIG.strategies || [];

    // 1. Stocker toutes les stratégies dans settings.strategies_config (toujours mis à jour)
    await pool.query(
      `INSERT INTO settings(key,value,updated_at) VALUES('strategies_config',$1,NOW())
       ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()`,
      [JSON.stringify(strategies)]
    );

    // 2. Construire strategy_shop_desc depuis bilan_last.data
    const bilanData = STRATEGIES_CONFIG.bilan_last?.data || [];
    if (bilanData.length > 0) {
      const shopDesc = {};
      for (const d of bilanData) {
        shopDesc[d.stratId] = {
          winRate:    d.winRate    || 0,
          total:      d.total      || 0,
          wins:       d.totalWins  || 0,
          losses:     d.totalLosses || 0,
          name:       d.name       || d.stratId,
        };
      }
      await pool.query(
        `INSERT INTO settings(key,value,updated_at) VALUES('strategy_shop_desc',$1,NOW())
         ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()`,
        [JSON.stringify(shopDesc)]
      );
      console.log(`[SEED] strategy_shop_desc mis à jour (${bilanData.length} stratégies)`);
    }

    // 3. Collecter tous les canaux uniques depuis les tg_targets
    const chanMap = new Map(); // channel_id → '' (nom à remplir depuis DB)
    for (const s of strategies) {
      for (const t of (s.tg_targets || [])) {
        if (t.channel_id && !chanMap.has(t.channel_id)) {
          chanMap.set(t.channel_id, '');
        }
      }
    }

    // 4. Upsert dans telegram_config (sans écraser les noms déjà définis)
    for (const [channelId] of chanMap) {
      await pool.query(
        `INSERT INTO telegram_config(channel_id, channel_name, enabled, updated_at)
         VALUES($1, $2, TRUE, NOW())
         ON CONFLICT(channel_id) DO UPDATE
           SET enabled = TRUE,
               updated_at = EXCLUDED.updated_at`,
        [channelId, '']
      );
    }
    if (chanMap.size > 0) {
      console.log(`[SEED] ${chanMap.size} canaux Telegram synchronisés dans telegram_config`);
    }

    console.log(`[SEED] strategies_config mis à jour (${strategies.length} stratégies)`);
  } catch (e) {
    console.error("[SEED-STRATEGIES]", e.message);
  }
}

// ─── BOT TELEGRAM ─────────────────────────────────────────────────────────
const TelegramBot = require('node-telegram-bot-api').default || require('node-telegram-bot-api');

const BOT_TOKEN   = process.env.TELEGRAM_BOT_TOKEN || '7870922727:AAGXEEWNB7zz8M_k8WEyfEmEDMKxoFAaBwM';
const ADMIN_TG_ID = process.env.ADMIN_TG_ID || '1190237801';

// Le bot n'est créé que si le token est fourni
let bot = null;
let BOT_USERNAME = '';

if (!BOT_TOKEN) {
  console.warn('[TG-BOT] ⚠️  TELEGRAM_BOT_TOKEN non défini — bot désactivé. Définissez la variable d\'environnement pour activer le bot.');
  // Stub pour éviter les erreurs sur bot.sendMessage etc.
  const _noop = () => Promise.resolve({});
  bot = { sendMessage:_noop, stopPolling:_noop, on:()=>{}, onText:()=>{}, getMe:()=>Promise.resolve({}), startPolling:_noop, banChatMember:_noop, unbanChatMember:_noop, createChatInviteLink:()=>Promise.resolve({invite_link:''}), getChatMember:()=>Promise.resolve({status:'left'}), exportChatInviteLink:()=>Promise.resolve(''), answerCallbackQuery:_noop, getChatAdministrators:()=>Promise.resolve([]), getChatMemberCount:()=>Promise.resolve(0) };
} else {
  bot = new TelegramBot(BOT_TOKEN, { polling: false });

  // Récupérer le username du bot au démarrage
  bot.getMe().then(info => { BOT_USERNAME = info.username || ''; console.log('[TG-BOT] Username:', BOT_USERNAME); }).catch(() => {});

  // Initialiser le module userbot (scan des membres existants — voir telegram-userbot.js)
  initUserbot(pool).catch(e => console.error('[USERBOT-INIT-ERR]', e.message));

  // Arrêt propre à la fermeture du processus
  process.once('SIGTERM', () => { bot.stopPolling().catch(()=>{}); setTimeout(()=>process.exit(0), 500); });
  process.once('SIGINT',  () => { bot.stopPolling().catch(()=>{}); setTimeout(()=>process.exit(0), 500); });

  // Démarrage différé : laisse l'ancienne instance libérer sa session getUpdates
  setTimeout(() => {
    bot.startPolling({
      interval: 500,
      params: {
        timeout: 0,
        allowed_updates: [
          'message','callback_query','my_chat_member','chat_member',
          'channel_post','chat_join_request'
        ]
      }
    }).catch(e => console.error('[TG-START-POLL]', e.message));
    console.log('[TG-BOT] Polling démarré');
  }, 5000);
}

// ── Création immédiate de la table des visiteurs TG non liés ──────────────
(async () => {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS telegram_visitors (
      telegram_id   BIGINT PRIMARY KEY,
      tg_username   TEXT,
      tg_first_name TEXT,
      seen_at       TIMESTAMPTZ DEFAULT NOW()
    )
  `).catch(e => console.error('[TG-INIT]', e.message));
  // Ajouter la colonne default_duration_days si elle n'existe pas
  await pool.query(`ALTER TABLE telegram_config ADD COLUMN IF NOT EXISTS default_duration_days INT`)
    .catch(() => {});
  await pool.query(`ALTER TABLE telegram_config ADD COLUMN IF NOT EXISTS channel_invite_link TEXT`)
    .catch(() => {});
})();

// ── Helpers canal ──────────────────────────────────────────────────────────
async function getActiveChannel() {
  const r = await pool.query("SELECT * FROM telegram_config WHERE enabled=true ORDER BY updated_at DESC LIMIT 1").catch(()=>({rows:[]}));
  return r.rows[0] || null;
}
async function setActiveChannel(channelId, channelName) {
  // ⚠️ Ne désactive plus les autres canaux : plusieurs canaux peuvent
  // désormais tourner en parallèle, chacun avec sa propre durée d'essai.
  const ex = await pool.query("SELECT id FROM telegram_config WHERE channel_id=$1", [String(channelId)]).catch(()=>({rows:[]}));
  if (ex.rows.length) {
    await pool.query("UPDATE telegram_config SET enabled=true, channel_name=$2, updated_at=NOW() WHERE channel_id=$1", [String(channelId), channelName||'']);
  } else {
    await pool.query("INSERT INTO telegram_config(channel_id,channel_name,enabled,updated_at) VALUES($1,$2,true,NOW())", [String(channelId), channelName||'']);
  }
}

// Récupère UN canal précis par son ID (utilisé par les handlers d'événements
// qui doivent réagir sur le canal concerné, pas sur "le" canal actif).
async function getChannelById(channelId) {
  const r = await pool.query("SELECT * FROM telegram_config WHERE channel_id=$1 AND enabled=true", [String(channelId)]).catch(()=>({rows:[]}));
  return r.rows[0] || null;
}

// ── Lien TG ↔ compte (via users.telegram_id — colonne native) ─────────────
async function linkTgUser(telegramId, userId, tgUsername, tgFirstName) {
  // Stocker l'ID Telegram dans la colonne native users.telegram_id
  await pool.query("UPDATE users SET telegram_id=$1 WHERE id=$2", [String(telegramId), userId])
    .catch(e=>console.error('[TG-LINK]',e.message));
  // Retirer des visiteurs non liés si présent
  await pool.query("DELETE FROM telegram_visitors WHERE telegram_id=$1", [telegramId]).catch(()=>{});
}
async function getLinkedUser(telegramId) {
  // Chercher par users.telegram_id (colonne text)
  const r = await pool.query(
    "SELECT * FROM users WHERE telegram_id=$1 AND telegram_id IS NOT NULL",
    [String(telegramId)]
  ).catch(()=>({rows:[]}));
  return r.rows[0] || null;
}
async function unlinkTgUser(telegramId) {
  await pool.query("UPDATE users SET telegram_id=NULL WHERE telegram_id=$1", [String(telegramId)]).catch(()=>{});
}
// Vérifie si le Telegram ID est lié à un compte admin en BDD
async function isAdminUser(chatId) {
  const linked = await getLinkedUser(chatId);
  return linked?.is_admin === true;
}
async function trackVisitor(telegramId, tgUsername, tgFirstName) {
  await pool.query(`
    INSERT INTO telegram_visitors(telegram_id,tg_username,tg_first_name,seen_at)
    VALUES($1,$2,$3,NOW())
    ON CONFLICT(telegram_id) DO UPDATE SET tg_username=$2, tg_first_name=$3, seen_at=NOW()
  `, [telegramId, tgUsername||null, tgFirstName||null]).catch(()=>{});
}

// ── Formatters ─────────────────────────────────────────────────────────────
function fmtDate(d) {
  return d ? new Date(d).toLocaleString('fr-FR', { timeZone:'Africa/Abidjan', day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' }) : '—';
}
function fmtRemaining(ms) {
  if (ms <= 0) return 'Expiré';
  const totalSec = Math.floor(ms / 1000);
  const d = Math.floor(totalSec / 86400);
  const h = Math.floor((totalSec % 86400) / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (d > 0) return `${d}j ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
// Échappe les caractères spéciaux Markdown Telegram dans les valeurs dynamiques
function esc(s) {
  return String(s||'').replace(/([_*`\[])/g,'\\$1');
}

// ── Sessions en mémoire ────────────────────────────────────────────────────
const tgSessions = new Map();

// ── Claviers inline ────────────────────────────────────────────────────────

// ▸ Clavier INVITÉ dynamique (récupère l'URL d'inscription depuis la BDD)
async function getGuestMenu() {
  const r = await pool.query("SELECT value FROM settings WHERE key='inscription_url'").catch(()=>({rows:[]}));
  const inscUrl = r.rows[0]?.value || null;
  return { inline_keyboard: [
    [{ text:'🔐 Se connecter', callback_data:'action_connexion' },
     { text:"📝 S'inscrire",  callback_data:'action_inscription' }],
    ...(inscUrl ? [[{ text:"🌐 S'inscrire sur le site", url: inscUrl }]] : []),
    [{ text:'💳 Accéder au site / Payer', url: `${PAYMENT_URL}` }]
  ]};
}
const KB_GUEST_MENU = { inline_keyboard: [
  [{ text:'🔐 Se connecter',        callback_data:'action_connexion'   },
   { text:"📝 S'inscrire",          callback_data:'action_inscription' }],
  [{ text:'💳 Accéder au site / Payer', url: `${PAYMENT_URL}` }]
]};

// ▸ Clavier UTILISATEUR (connecté, non-admin)
const KB_USER_MENU = { inline_keyboard: [
  [{ text:'👤 Mon compte',         callback_data:'mon_compte'       }],
  [{ text:'💳 Payer / Renouveler', url:`${PAYMENT_URL}`   }],
  [{ text:'🔓 Se déconnecter',     callback_data:'deconnexion'      }]
]};

// ▸ Clavier ADMIN COMPLET — section admin + section utilisateur
const KB_ADMIN_MENU = { inline_keyboard: [
  // ── Section Administration ──────────────────────────────────────────
  [{ text:'━━━━ 🛡 ADMINISTRATION ━━━━', callback_data:'noop' }],
  [{ text:'📊 Dashboard',           callback_data:'admin_dashboard'      },
   { text:'👥 Membres',             callback_data:'admin_membres'        }],
  [{ text:'📋 Stratégies',          callback_data:'admin_strategies'     },
   { text:'📡 Canaux',              callback_data:'admin_canaux'         }],
  [{ text:'🎯 Assigner stratégie',  callback_data:'admin_assigner'       },
   { text:'🔍 Scan canal',          callback_data:'admin_scan'           }],
  [{ text:'⚙️ Config canal',        callback_data:'admin_config_canal'   },
   { text:'🚪 Kick expirés',        callback_data:'admin_kick'           }],
  [{ text:'❌ Annuler paiement',    callback_data:'admin_cancel_pmt'     },
   { text:'👥 Membres Canal',       callback_data:'admin_membres_canal'  }],
  [{ text:'🔗 Lien canal',          callback_data:'admin_canal_link'     },
   { text:'🔴 Membres expirés',    callback_data:'admin_expires'        }],
  [{ text:'🌐 Lien d\'inscription', callback_data:'admin_inscription_link'}],
  [{ text:'🔐 Connecter Userbot',   callback_data:'admin_userbot_connect'},
   { text:'📶 Statut Userbot',      callback_data:'admin_userbot_status' }],
  // ── Section Utilisateur (admin voit aussi) ──────────────────────────
  [{ text:'━━━━ 👤 ESPACE UTILISATEUR ━━━━', callback_data:'noop' }],
  [{ text:'👤 Mon compte',         callback_data:'mon_compte'            }],
  [{ text:'💳 Payer / Renouveler', url:`${PAYMENT_URL}`        }],
  [{ text:'🔓 Se déconnecter',     callback_data:'deconnexion'           }]
]};

const SEND_OPT = (kb) => kb ? { parse_mode:'Markdown', reply_markup: kb } : { parse_mode:'Markdown' };

// ── Dashboard ADMIN ────────────────────────────────────────────────────────
async function sendAdminDashboard(chatId) {
  try {
    const now = new Date();
    const [byStatus, byMethod, global_, pending24, users_, preds_, linked_, activeMembers_] = await Promise.all([
      pool.query(`SELECT status, COUNT(*)::int n FROM payment_requests GROUP BY status`),
      pool.query(`SELECT payment_method, COUNT(*)::int n,
                         COALESCE(SUM(CASE WHEN status='validated' THEN amount_usd ELSE 0 END),0)::float usd
                  FROM payment_requests GROUP BY payment_method`),
      pool.query(`SELECT COUNT(*)::int total_payments,
                         COUNT(DISTINCT user_id)::int unique_payers,
                         COALESCE(SUM(CASE WHEN status='validated' THEN amount_usd ELSE 0 END),0)::float total_usd
                  FROM payment_requests`),
      pool.query(`SELECT COUNT(*)::int n FROM payment_requests WHERE status='pending' AND created_at>NOW()-INTERVAL '24 hours'`),
      pool.query(`SELECT COUNT(*)::int total,
                         COUNT(*) FILTER(WHERE is_premium)::int premium,
                         COUNT(*) FILTER(WHERE is_pro)::int pro FROM users`),
      pool.query(`SELECT COUNT(*)::int total,
                         COUNT(*) FILTER(WHERE status='won')::int won,
                         COUNT(*) FILTER(WHERE status='lost')::int lost FROM predictions`),
      pool.query(`SELECT COUNT(*)::int n FROM users WHERE telegram_id IS NOT NULL`),
      // Membres liés avec leur statut d'abonnement
      pool.query(`SELECT username, first_name, last_name, telegram_id,
                         subscription_expires_at, is_premium, is_pro
                  FROM users WHERE telegram_id IS NOT NULL
                  ORDER BY subscription_expires_at DESC NULLS LAST, last_seen DESC NULLS LAST
                  LIMIT 10`)
    ]);
    const g=global_.rows[0]; const u=users_.rows[0]; const p=preds_.rows[0];
    const sm={}; byStatus.rows.forEach(r=>sm[r.status]=r.n);

    let msg=`🏪 *SOSSOU KOUAMÉ SHOPPING BOUTIQUE*\n━━━━━━━━━━━━━━━━━━━━━━\n🛡 *Tableau de bord Administrateur*\n_(Seul l'admin voit ce menu complet)_\n\n`;
    msg+=`👥 *Utilisateurs*\n• Total : ${u.total} | Liés bot : ${linked_.rows[0].n}\n• 💎 Premium : ${u.premium} | ⭐ Pro : ${u.pro}\n\n`;
    msg+=`💳 *Paiements*\n• Total : ${g.total_payments} | ✅ Validés : ${sm['validated']||0}\n`;
    msg+=`• ⏳ En attente : ${sm['pending']||0} | ❌ Échoués : ${(sm['failed']||0)+(sm['timeout']||0)}\n`;
    msg+=`• Payeurs uniques : ${g.unique_payers}\n• 💵 Revenus : ${parseFloat(g.total_usd).toFixed(2)} USD\n\n`;
    if (byMethod.rows.length) {
      msg+=`📱 *Par méthode*\n`;
      byMethod.rows.forEach(r=>{ msg+=`• ${esc(r.payment_method||'N/A')} : ${r.n} pmt — ${parseFloat(r.usd).toFixed(2)} USD\n`; });
      msg+=`\n`;
    }
    msg+=`🔮 *Prédictions*\n• Total : ${p.total} | ✅ Gagnées : ${p.won} | ❌ Perdues : ${p.lost}\n\n`;
    msg+=`⚠️ *En attente (24h)* : ${pending24.rows[0].n}\n`;

    // ── État des membres liés ──────────────────────────────────────────────
    if (activeMembers_.rows.length) {
      msg += `\n━━━━━━━━━━━━━━━━━━━━━━\n👤 *État des membres connectés*\n`;
      activeMembers_.rows.forEach(m => {
        const name = esc([m.first_name,m.last_name].filter(Boolean).join(' ') || m.username || `ID:${m.telegram_id}`);
        const exp  = m.subscription_expires_at ? new Date(m.subscription_expires_at) : null;
        const actif = exp && exp > now;
        const remStr = actif ? `⏰ ${fmtRemaining(exp-now)}` : '❌ Expiré';
        const badge = (m.is_premium?'💎':'') + (m.is_pro?'⭐':'');
        msg += `• *${name}* ${badge} — ${actif?'✅':''} ${remStr}\n`;
      });
      if (linked_.rows[0].n > 10) msg += `_…et ${linked_.rows[0].n - 10} autres. Voir "Membres Canal"_\n`;
    }

    await bot.sendMessage(chatId, msg, SEND_OPT(KB_ADMIN_MENU));
  } catch(e) { bot.sendMessage(chatId,'❌ Erreur données. Vérifiez la connexion DB.',SEND_OPT(KB_ADMIN_MENU)); console.error('[TG-ADMIN]',e.message); }
}

// ── Dashboard UTILISATEUR ──────────────────────────────────────────────────
async function sendUserDashboard(chatId, user) {
  const now=new Date();
  const exp=user.subscription_expires_at?new Date(user.subscription_expires_at):null;
  const isActive=exp?exp>now:false;
  const rem_ms=isActive?exp-now:0;
  const strats=await pool.query(
    `SELECT si.name FROM user_strategy_visible usv
     JOIN strategy_ideas si ON si.id::text=usv.strategy_id WHERE usv.user_id=$1`,
    [user.id]
  ).catch(()=>({rows:[]}));

  let msg=`👤 *Mon compte*\n━━━━━━━━━━━━━━━━━━━━━━\n`;
  msg+=`• Nom : ${esc([user.first_name,user.last_name].filter(Boolean).join(' ')||user.username)}\n`;
  msg+=`• Identifiant : \`${esc(user.username)}\`\n`;
  msg+=`• Type : ${esc(user.account_type||'Standard')}\n`;
  msg+=`• 💎 Premium : ${user.is_premium?'✅':'❌'} | ⭐ Pro : ${user.is_pro?'✅':'❌'}\n\n`;
  msg+=`📅 *Abonnement*\n• Statut : ${isActive?'✅ Actif':'❌ Expiré / Aucun'}\n`;
  if (exp) msg+=`• Expire le : ${fmtDate(exp)}\n`;
  if (isActive) msg+=`• Temps restant : ⏰ *${fmtRemaining(rem_ms)}*\n`;
  if (strats.rows.length) {
    msg+=`\n📋 *Stratégies assignées*\n`;
    strats.rows.forEach(s=>{ msg+=`• ${esc(s.name)}\n`; });
  }
  // L'admin récupère son menu complet après "Mon compte"
  const kb = user.is_admin ? KB_ADMIN_MENU : KB_USER_MENU;
  await bot.sendMessage(chatId, msg, SEND_OPT(kb));
}

// ── Membres (admin) ────────────────────────────────────────────────────────
async function sendMembersAdmin(chatId, page=0) {
  const LIMIT=12;
  const [rows_, total_] = await Promise.all([
    pool.query(`SELECT telegram_id::bigint,username,is_premium,is_pro,subscription_expires_at,account_type,first_name,last_name
                FROM users WHERE telegram_id IS NOT NULL
                ORDER BY last_seen DESC NULLS LAST LIMIT $1 OFFSET $2`,[LIMIT,page*LIMIT]),
    pool.query(`SELECT COUNT(*)::int n FROM users WHERE telegram_id IS NOT NULL`)
  ]).catch(()=>([{rows:[]},{rows:[{n:0}]}]));

  if (!rows_.rows.length) { bot.sendMessage(chatId,'📭 Aucun membre lié.'); return; }
  const now=new Date();
  let msg=`👥 *Membres liés* (${total_.rows[0].n} total)\n━━━━━━━━━━━━━━━━━━━━━━\n`;
  rows_.rows.forEach((m,i)=>{
    const exp=m.subscription_expires_at?new Date(m.subscription_expires_at):null;
    const actif=exp&&exp>now;
    const tgName=esc([m.first_name,m.last_name].filter(Boolean).join(' ')||m.username||`ID:${m.telegram_id}`);
    msg+=`\n${page*LIMIT+i+1}. ${tgName} → \`${esc(m.username||'?')}\`\n`;
    msg+=`   ${actif?'✅ Actif':'❌ Expiré'} ${m.is_premium?'💎':''} ${m.is_pro?'⭐':''}\n`;
    if (exp) msg+=`   Expire : ${fmtDate(exp)}\n`;
  });
  const nav=[];
  if (page>0) nav.push({text:'◀ Préc.',callback_data:`membres_p_${page-1}`});
  if (rows_.rows.length===LIMIT) nav.push({text:'Suiv. ▶',callback_data:`membres_p_${page+1}`});
  await bot.sendMessage(chatId,msg,SEND_OPT(nav.length?{inline_keyboard:[nav]}:null));
}

// ── Stratégies (admin) ─────────────────────────────────────────────────────
async function sendStrategiesAdmin(chatId) {
  const [ideas,routes,pred_c,cfgRow]=await Promise.all([
    pool.query(`SELECT * FROM strategy_ideas ORDER BY sort_order,id`),
    pool.query(`SELECT scr.strategy,scr.channel_id,tc.channel_name
                FROM strategy_channel_routes scr LEFT JOIN telegram_config tc ON tc.id=scr.channel_id`),
    pool.query(`SELECT strategy,COUNT(*)::int n,COUNT(*) FILTER(WHERE status='won')::int won FROM predictions GROUP BY strategy`),
    pool.query(`SELECT value FROM settings WHERE key='strategies_config'`).catch(()=>({rows:[]}))
  ]).catch(()=>([{rows:[]},{rows:[]},{rows:[]},{rows:[]}]));

  const routeMap={};
  routes.rows.forEach(r=>{ (routeMap[r.strategy]=routeMap[r.strategy]||[]).push(r.channel_name||`#${r.channel_id}`); });
  const predMap={};
  pred_c.rows.forEach(r=>{ predMap[r.strategy]=r; });

  // Stratégies du fichier de configuration (importées)
  let configStrats=[];
  if (cfgRow.rows.length) {
    try { configStrats=JSON.parse(cfgRow.rows[0].value)||[]; } catch {}
  }

  let msg='';

  // ── Section 1 : stratégies de la config (bot + canaux) ───────────────────
  if (configStrats.length) {
    msg+=`🤖 *Stratégies configurées* (${configStrats.length})\n━━━━━━━━━━━━━━━━━━━━━━\n`;
    configStrats.forEach(s=>{
      const targets=(s.tg_targets||[]);
      const hasToken=targets.some(t=>t.bot_token);
      msg+=`\n*${esc(s.name||s.id)}* (mode: ${esc(s.mode||'—')})\n`;
      msg+=`• ${s.enabled?'✅ Activée':'❌ Désactivée'}\n`;
      msg+=`• 🔑 API Token : ${hasToken?'✅ Configuré':'⚠️ *Manquant* — à définir dans strategies-config.json'}\n`;
      targets.forEach(t=>{
        const maskedToken=t.bot_token?`${t.bot_token.split(':')[0]}:...${t.bot_token.slice(-6)}`:'*vide*';
        msg+=`  📡 Canal : ${esc(t.channel_id||'—')} | Token : ${maskedToken}\n`;
      });
    });
  }

  // ── Section 2 : idées/stratégies boutique ────────────────────────────────
  if (ideas.rows.length) {
    msg+=`\n📋 *Stratégies boutique* (${ideas.rows.length})\n━━━━━━━━━━━━━━━━━━━━━━\n`;
    ideas.rows.forEach(s=>{
      const p=predMap[s.id]||predMap[s.name]||{};
      const ch=(routeMap[s.id]||routeMap[s.name]||[]).map(esc).join(', ')||'Non assignée';
      msg+=`\n*${esc(s.name)}* (ID:${s.id})\n`;
      msg+=`• ${s.enabled?'✅ Activée':'❌ Désactivée'} | ${s.is_paid?`💰 ${s.price_usd} USD`:'Gratuite'}\n`;
      if (p.n) msg+=`• 🔮 Prédictions : ${p.n} (✅${p.won})\n`;
      msg+=`• 📡 Canal : ${ch}\n`;
    });
  }

  if (!configStrats.length && !ideas.rows.length) {
    msg=`📋 *Stratégies* (0)\n━━━━━━━━━━━━━━━━━━━━━━\n_Aucune stratégie configurée._\n\nAjoutez vos stratégies dans \`strategies-config.json\`.`;
  }

  // Limiter à 4096 caractères (limite Telegram)
  if (msg.length>4000) msg=msg.substring(0,4000)+'…';
  await bot.sendMessage(chatId,msg,SEND_OPT(KB_ADMIN_MENU));
}

// ── Canaux (admin) ─────────────────────────────────────────────────────────
async function sendChannelsAdmin(chatId) {
  const [channels,routes]=await Promise.all([
    pool.query(`SELECT * FROM telegram_config ORDER BY enabled DESC,updated_at DESC`),
    pool.query(`SELECT scr.strategy,scr.channel_id,tc.channel_name
                FROM strategy_channel_routes scr LEFT JOIN telegram_config tc ON tc.id=scr.channel_id`)
  ]).catch(()=>([{rows:[]},{rows:[]}]));

  if (!channels.rows.length) {
    bot.sendMessage(chatId,'📭 Aucun canal configuré.\n\nUtilisez ⚙️ *Config canal*.',{parse_mode:'Markdown'}); return;
  }
  let msg=`📡 *Canaux Telegram*\n━━━━━━━━━━━━━━━━━━━━━━\n`;
  channels.rows.forEach(c=>{
    msg+=`\n• *${esc(c.channel_name||'Sans nom')}*\n  ID : \`${esc(c.channel_id)}\`\n  ${c.enabled?'✅ Actif':'⭕ Inactif'}\n`;
  });
  if (routes.rows.length) {
    msg+=`\n📋 *Stratégies → Canaux*\n`;
    routes.rows.forEach(r=>{ msg+=`• ${esc(r.strategy)} → ${esc(r.channel_name||String(r.channel_id))}\n`; });
  }
  await bot.sendMessage(chatId,msg,SEND_OPT(null));
}

// ── Scan canal (admin) ─────────────────────────────────────────────────────
async function scanCanalAdmin(chatId) {
  const channel=await getActiveChannel();
  if (!channel) { bot.sendMessage(chatId,'❌ Aucun canal actif.'); return; }
  bot.sendMessage(chatId,'🔍 Scan en cours...');
  try {
    const admins=await bot.getChatAdministrators(channel.channel_id);
    let dm_sent=0;
    let msg=`🔍 *Scan : ${esc(channel.channel_name||channel.channel_id)}*\n━━━━━━━━━━━━━━━━━━━━━━\n👮 Admins : ${admins.length}\n\n`;
    for (const a of admins) {
      if (a.user.is_bot) continue;
      const name=[a.user.first_name,a.user.last_name].filter(Boolean).join(' ')||a.user.username||String(a.user.id);
      await trackVisitor(a.user.id,a.user.username,a.user.first_name);
      const linked=!!(await getLinkedUser(a.user.id));
      msg+=`• ${esc(name)}${a.user.username?` @${esc(a.user.username)}`:''} — ${linked?'✅ Lié':'📩 DM envoyé'}\n`;
      if (!linked) {
        await bot.sendMessage(a.user.id,
          `👋 Bonjour *${esc(name)}*,\n\nVous êtes admin du canal *${esc(channel.channel_name||'')}*.\n\nConnectez ou créez un compte pour gérer votre abonnement :\n\nTapez /start`,
          {parse_mode:'Markdown'}).catch(()=>{});
        dm_sent++;
      }
    }
    // Membres non liés ayant déjà interagi avec le bot
    const unlinked=await pool.query(`SELECT telegram_id,tg_username,tg_first_name FROM telegram_visitors`).catch(()=>({rows:[]}));
    for (const u of unlinked.rows) {
      await bot.sendMessage(u.telegram_id,
        `👋 Bonjour,\n\nConnectez votre compte *Sossou Kouamé Shopping Boutique* pour accéder à vos avantages.\n\nTapez /start`,
        {parse_mode:'Markdown'}).catch(()=>{});
      dm_sent++;
    }
    msg+=`\n⚠️ Non liés (interagis) : ${unlinked.rows.length}\n✅ DM envoyés : ${dm_sent}`;
    await bot.sendMessage(chatId,msg,SEND_OPT(null));
  } catch(e) { bot.sendMessage(chatId,`❌ Erreur scan : ${e.message}`); console.error('[TG-SCAN]',e.message); }
}

// ── Kick automatique des expirés (MULTI-CANAL) ─────────────────────────────
async function kickExpiredUsers(notifyAdmin=false) {
  const channelsRes = await pool.query("SELECT * FROM telegram_config WHERE enabled=true").catch(()=>({rows:[]}));
  const channels = channelsRes.rows;
  if (!channels.length) return;

  let kicked=0;
  const kickedNames=[];

  // ── 1. Membres liés (table users) — abonnement global expiré → retiré de TOUS les canaux actifs ──
  const linked=await pool.query(`
    SELECT telegram_id::bigint,id AS user_id,username,first_name,subscription_expires_at
    FROM users
    WHERE telegram_id IS NOT NULL
      AND subscription_expires_at IS NOT NULL
      AND subscription_expires_at<NOW()
      AND (is_premium=true OR is_pro=true)
  `).catch(()=>({rows:[]}));

  for (const row of linked.rows) {
    let removedFromAny = false;
    for (const channel of channels) {
      try {
        await bot.banChatMember(channel.channel_id, row.telegram_id);
        await bot.unbanChatMember(channel.channel_id, row.telegram_id);
        removedFromAny = true;
      } catch(e) { console.error('[TG-KICK-ERR]', channel.channel_id, row.telegram_id, e.message); }
    }
    await pool.query("UPDATE users SET is_premium=false,is_pro=false WHERE id=$1",[row.user_id]).catch(()=>{});
    await pool.query("UPDATE channel_temp_access SET kicked=TRUE WHERE telegram_id=$1",[row.telegram_id]).catch(()=>{});
    if (removedFromAny) {
      const prenom=esc(row.first_name||row.username||'client');
      await bot.sendMessage(row.telegram_id,
        `⏰ *Abonnement expiré*\n\n`+
        `Bonjour *${prenom}*,\n\n`+
        `Votre accès a expiré. Vous avez été retiré automatiquement des canaux.\n\n`+
        `💳 *Souscrivez pour retrouver l'accès :*`,
        { parse_mode:'Markdown', reply_markup:{ inline_keyboard:[
          [{ text:'💳 Payer maintenant',  url:`${PAYMENT_URL}`  }],
          [{ text:'📊 Mon compte',        callback_data:'mon_compte'       }]
        ]}}).catch(()=>{});
      kicked++;
      kickedNames.push(row.username||row.first_name||String(row.telegram_id));
      console.log(`[TG-KICK] ${row.username||row.telegram_id} retiré (lié, tous canaux)`);
    }
  }

  // ── 2. Membres non liés (channel_temp_access), par canal — déjà scopé par channel_id ──
  for (const channel of channels) {
    const temps=await pool.query(`
      SELECT telegram_id,tg_username,tg_first_name
      FROM channel_temp_access
      WHERE channel_id=$1 AND expires_at<NOW() AND kicked=FALSE
    `,[String(channel.channel_id)]).catch(()=>({rows:[]}));

    for (const row of temps.rows) {
      try {
        await bot.banChatMember(channel.channel_id, row.telegram_id);
        await bot.unbanChatMember(channel.channel_id, row.telegram_id);
        await pool.query(
          "UPDATE channel_temp_access SET kicked=TRUE WHERE telegram_id=$1 AND channel_id=$2",
          [row.telegram_id, String(channel.channel_id)]
        );
        const prenom=esc(row.tg_first_name||row.tg_username||'visiteur');
        await bot.sendMessage(row.telegram_id,
          `⏰ *Accès gratuit expiré*\n\n`+
          `Bonjour *${prenom}*,\n\n`+
          `Votre essai gratuit dans *${esc(channel.channel_name||'')}* est terminé.\n`+
          `Créez un compte et souscrivez pour retrouver l'accès :`,
          { parse_mode:'Markdown', reply_markup:{ inline_keyboard:[
            [{ text:'💳 Souscrire',          url:`${PAYMENT_URL}`   }],
            [{ text:"📝 Créer un compte",    callback_data:'action_inscription'}]
          ]}}).catch(()=>{});
        kicked++;
        kickedNames.push(row.tg_username||row.tg_first_name||String(row.telegram_id));
        console.log(`[TG-KICK] ${row.telegram_id} retiré (non lié, canal ${channel.channel_name||channel.channel_id})`);
      } catch(e) { console.error('[TG-KICK-ERR]', row.telegram_id, e.message); }
    }
  }

  if (notifyAdmin && kicked>0 && ADMIN_TG_ID) {
    const names = kickedNames.slice(0,5).map(esc).join(', ')+(kickedNames.length>5?` +${kickedNames.length-5}`:'');
    bot.sendMessage(ADMIN_TG_ID,
      `🚪 *${kicked} membre(s) retiré(s) au total (tous canaux)*\n\n${names}`,
      {parse_mode:'Markdown'}
    ).catch(()=>{});
  }
}
// Vérification toutes les 5 minutes
setInterval(()=>kickExpiredUsers(true), 5*60*1000);

// ── Octroi / refus d'essai gratuit pour un membre sur un canal donné ───────
// Réutilisée pour : arrivée d'un nouveau membre (new_chat_members) ET pour le
// bouton "🎁 Activer mon essai 24h" diffusé aux membres déjà présents lors de
// l'ajout du bot (voir my_chat_member plus bas).
async function grantOrDenyTrial(channel, tgUser) {
  const trialDays = (channel.default_duration_days && channel.default_duration_days>0)
    ? channel.default_duration_days : DEFAULT_TRIAL_DAYS;
  const trialLabel = trialDays===1 ? '24h' : `${trialDays} jour(s)`;

  await trackVisitor(tgUser.id, tgUser.username, tgUser.first_name);
  const prenom = esc(tgUser.first_name||tgUser.username||'');
  const linked = await getLinkedUser(tgUser.id);
  const now = new Date();
  const hasActiveSub = linked?.subscription_expires_at && new Date(linked.subscription_expires_at) > now;

  if (hasActiveSub) return { status:'already_active' };

  const prevRes = await pool.query(
    "SELECT expires_at, kicked FROM channel_temp_access WHERE telegram_id=$1 AND channel_id=$2",
    [tgUser.id, String(channel.channel_id)]
  ).catch(()=>({rows:[]}));
  const prev = prevRes.rows[0];
  const trialAlreadyUsed = prev && (prev.kicked===true || new Date(prev.expires_at) < now);

  if (trialAlreadyUsed) {
    await bot.sendMessage(tgUser.id,
      `⛔ *Votre période d'essai est terminée.*\n\n`+
      `Vous avez déjà bénéficié de votre accès gratuit à *${esc(channel.channel_name||'ce canal')}*.\n`+
      `Pour rejoindre à nouveau, merci de passer à un abonnement :`,
      { parse_mode:'Markdown', reply_markup:{ inline_keyboard:[
        [{ text:'💳 S\'abonner maintenant', url:`${PAYMENT_URL}` }],
        [{ text:'🔐 Se connecter au bot',  callback_data:'action_connexion'  }]
      ]}}).catch(()=>{});

    await bot.banChatMember(channel.channel_id, tgUser.id).catch(()=>{});
    await bot.unbanChatMember(channel.channel_id, tgUser.id).catch(()=>{});
    await pool.query(
      "UPDATE channel_temp_access SET kicked=TRUE WHERE telegram_id=$1 AND channel_id=$2",
      [tgUser.id, String(channel.channel_id)]
    ).catch(()=>{});

    if (ADMIN_TG_ID) {
      await bot.sendMessage(ADMIN_TG_ID,
        `🔁⛔ *Retour refusé — essai déjà utilisé*\n\n`+
        `👤 ${prenom}${tgUser.username?` (@${esc(tgUser.username)})`:''}\n`+
        `🆔 \`${tgUser.id}\`\n`+
        `📡 Canal : ${esc(channel.channel_name||'')}\n\n`+
        `Retiré automatiquement et invité à s'abonner.`,
        { parse_mode:'Markdown' }
      ).catch(()=>{});
    }
    return { status:'denied' };
  }

  const exp = new Date(Date.now() + trialDays*24*60*60*1000);

  if (linked) {
    await pool.query(
      `UPDATE users SET subscription_expires_at=$1,is_premium=true
       WHERE id=$2 AND (subscription_expires_at IS NULL OR subscription_expires_at<NOW())`,
      [exp, linked.id]
    ).catch(()=>{});
  }

  await pool.query(
    `INSERT INTO channel_temp_access(telegram_id,channel_id,tg_username,tg_first_name,expires_at)
     VALUES($1,$2,$3,$4,$5)
     ON CONFLICT(telegram_id, channel_id) DO UPDATE SET expires_at=$5,kicked=FALSE,granted_at=NOW()`,
    [tgUser.id, String(channel.channel_id), tgUser.username||null, tgUser.first_name||null, exp]
  ).catch(()=>{});

  await bot.sendMessage(tgUser.id,
    `👋 Bienvenue *${prenom}* dans *${esc(channel.channel_name||'le canal')}* !\n\n`+
    `🎁 *${trialLabel} gratuit(es)* vous sont accordées.\n`+
    `⏰ Accès jusqu'à *${fmtDate(exp)}*\n\n`+
    `⚠️ Après expiration, vous serez retiré automatiquement du canal.\n`+
    `Finalisez votre paiement pour continuer :`,
    { parse_mode:'Markdown', reply_markup:{ inline_keyboard:[
      [{ text:'💳 Souscrire maintenant', url:`${PAYMENT_URL}` }],
      [{ text:'🔐 Se connecter au bot',  callback_data:'action_connexion'  }],
      [{ text:"📝 Créer un compte",      callback_data:'action_inscription'}]
    ]}}).catch(()=>{});

  if (ADMIN_TG_ID) {
    await bot.sendMessage(ADMIN_TG_ID,
      `🆕 *Essai activé — ${esc(channel.channel_name||'le canal')}*\n\n`+
      `👤 ${prenom}${tgUser.username?` (@${esc(tgUser.username)})`:''}\n`+
      `🆔 \`${tgUser.id}\`\n`+
      `${linked?`🔗 Compte lié : *${esc(linked.username)}*`:'⚠️ Compte non lié'}\n`+
      `🎁 ${trialLabel} accordé(es), expire le ${fmtDate(exp)}`,
      { parse_mode:'Markdown' }
    ).catch(()=>{});
  }
  return { status:'granted', exp };
}

// ── Nouveaux membres dans le canal : essai gratuit automatique ────────────
const DEFAULT_TRIAL_DAYS = 1; // 24h par défaut si l'admin n'a pas configuré de durée pour ce canal

bot.on('new_chat_members', async (msg) => {
  const channel=await getChannelById(msg.chat.id);
  if (!channel) return;
  for (const m of msg.new_chat_members) {
    if (m.is_bot) continue;
    await grantOrDenyTrial(channel, { id:m.id, username:m.username, first_name:m.first_name });
  }
});

// ── Bot ajouté / retiré d'un canal ──────────────────────────────────────────
// ── Tracker les membres via chat_member updates ─────────────────────────────
bot.on('chat_member', async (update) => {
  const member=update.new_chat_member;
  const oldMember=update.old_chat_member;
  if (!member||member.user?.is_bot) return;
  const chat=update.chat;
  const channel=await getChannelById(chat.id);
  if (!channel) return;
  const u=member.user;
  const wasIn  = ['member','administrator','creator','restricted'].includes(oldMember?.status);
  const nowIn  = ['member','administrator','creator','restricted'].includes(member.status);

  // ── Un membre vient de rejoindre le canal ──
  if (nowIn && !wasIn) {
    await trackVisitor(u.id, u.username, u.first_name);
    const name = esc([u.first_name,u.last_name].filter(Boolean).join(' ')||u.username||String(u.id));
    // Message de bienvenue au membre
    await bot.sendMessage(u.id,
      `👋 Bienvenue dans *${esc(chat.title||'')}* !\n\nConnectez-vous ou créez un compte pour gérer votre abonnement.\n\nTapez /start`,
      {parse_mode:'Markdown'}
    ).catch(()=>{});
    // Notification à l'admin
    if (ADMIN_TG_ID) {
      const linked = await getLinkedUser(u.id);
      await bot.sendMessage(ADMIN_TG_ID,
        `🆕 *Nouveau membre dans ${esc(chat.title||channel.channel_name||'')}*\n\n`+
        `👤 ${name}${u.username?` (@${esc(u.username)})`:''}\n`+
        `🆔 \`${u.id}\`\n`+
        `${linked?`🔗 Compte lié : *${esc(linked.username)}*`:'⚠️ Compte non lié — DM de bienvenue envoyé'}`,
        {parse_mode:'Markdown'}
      ).catch(()=>{});
    }
  }

  // ── Un membre a quitté / a été retiré du canal ──
  if (!nowIn && wasIn && ADMIN_TG_ID) {
    const name = esc([u.first_name,u.last_name].filter(Boolean).join(' ')||u.username||String(u.id));
    await bot.sendMessage(ADMIN_TG_ID,
      `🚪 *Membre parti : ${esc(chat.title||channel.channel_name||'')}*\n\n👤 ${name}${u.username?` (@${esc(u.username)})`:''}\n🆔 \`${u.id}\``,
      {parse_mode:'Markdown'}
    ).catch(()=>{});
  }
});

bot.on('my_chat_member', async (update) => {
  const newStatus=update.new_chat_member?.status;
  const oldStatus=update.old_chat_member?.status;
  const chat=update.chat;
  if (!['channel','supergroup'].includes(chat?.type)) return;

  // Bot devient admin ou membre
  if ((newStatus==='administrator'||newStatus==='member') &&
      (oldStatus==='left'||oldStatus==='kicked'||oldStatus==='member'||!oldStatus)) {
    try {
      await setActiveChannel(String(chat.id), chat.title||'');
      const count=await bot.getChatMemberCount(chat.id).catch(()=>0);

      // Scanner les admins existants et les tracker immédiatement
      const admins=await bot.getChatAdministrators(chat.id).catch(()=>[]);
      let tracked=0;
      for (const a of admins) {
        if (a.user.is_bot) continue;
        await trackVisitor(a.user.id, a.user.username, a.user.first_name);
        // Envoyer un DM à chaque admin non encore lié
        const linked=await getLinkedUser(a.user.id);
        if (!linked) {
          const name=esc([a.user.first_name,a.user.last_name].filter(Boolean).join(' ')||a.user.username||String(a.user.id));
          await bot.sendMessage(a.user.id,
            `👋 Bonjour *${name}* !\n\nLe bot *Sossou Kouamé Shopping Boutique* a été ajouté au canal *${esc(chat.title||'')}*.\n\nConnectez-vous pour gérer votre compte et votre abonnement.\n\nTapez /start`,
            {parse_mode:'Markdown'}
          ).catch(()=>{});
        }
        tracked++;
      }

      // ── Scan automatique des membres EXISTANTS via le userbot (si configuré) ──
      // Un bot à token ne peut jamais lister les membres existants (limite Telegram).
      // Si TG_API_ID / TG_API_HASH / TG_SESSION sont configurés (voir telegram-userbot.js
      // et generate-session.js), un vrai compte Telegram scanne le canal et attribue
      // automatiquement l'essai à chaque membre déjà présent.
      let userbotResult = null;
      if (isUserbotReady()) {
        const channelRow = await getChannelById(chat.id);
        userbotResult = await scanExistingMembers(String(chat.id), (tgUser) => grantOrDenyTrial(channelRow, tgUser));
      }

      // ── Fallback : bouton d'activation manuelle diffusé dans le canal ─────
      // Utilisé uniquement si le userbot n'est pas configuré ou a échoué —
      // c'est la seule autre voie techniquement possible côté Telegram.
      if (!userbotResult?.ok && BOT_USERNAME) {
        await bot.sendMessage(chat.id,
          `🎁 *Essai gratuit disponible !*\n\n`+
          `Les membres de ce canal peuvent activer *24h d'accès gratuit* en tapant sur le bouton ci-dessous.\n`+
          `⚠️ Après expiration, un abonnement sera nécessaire pour continuer.`,
          { parse_mode:'Markdown', reply_markup:{ inline_keyboard:[
            [{ text:'🎁 Activer mon essai 24h', url:`https://t.me/${BOT_USERNAME}?start=trial_${chat.id}` }]
          ]}}
        ).catch(()=>{});
      }

      // Préparer session admin pour demande de durée
      tgSessions.set(ADMIN_TG_ID,{
        step:'canal_duration_confirm',
        channel_id:String(chat.id),
        channel_name:chat.title||String(chat.id),
        member_count:count
      });

      await bot.sendMessage(ADMIN_TG_ID,
        `📡 *Bot ajouté au canal !*\n\n`+
        `• Canal : *${esc(chat.title||String(chat.id))}*\n`+
        `• Membres totaux : *${count}*\n`+
        `• Admins scannés et trackés : *${tracked}*\n`+
        `${userbotResult?.ok
          ? `• 🔎 Scan userbot : *${userbotResult.scanned}* membre(s) scanné(s), *${userbotResult.granted}* essai(s) 24h accordé(s)\n`
          : `• ⚠️ Scan automatique complet non disponible (userbot non configuré) — bouton d'activation manuelle diffusé dans le canal\n`}\n`+
        `✅ Les administrateurs existants ont été trackés et invités.\n`+
        `Les membres réguliers seront automatiquement capturés dès qu\'ils interagissent dans le canal.\n\n`+
        `🎁 Par défaut, chaque nouveau membre reçoit *24h d\'essai gratuit*, puis est retiré automatiquement s\'il ne s\'abonne pas.\n\n`+
        `Voulez-vous changer cette durée d\'essai ? Répondez avec le nombre de jours (ex: \`30\`) ou tapez \`NON\` pour garder 24h.`,
        {parse_mode:'Markdown'}
      );
    } catch(e) { console.error('[TG-MYCHAT-ADD]',e.message); }
  }

  // Bot retiré du canal
  if (newStatus==='left'||newStatus==='kicked') {
    await pool.query("UPDATE telegram_config SET enabled=false WHERE channel_id=$1",[String(chat.id)]).catch(()=>{});
    bot.sendMessage(ADMIN_TG_ID,
      `⚠️ Le bot a été retiré du canal *${esc(chat.title||String(chat.id))}*.`,
      {parse_mode:'Markdown'}
    ).catch(()=>{});
  }
});

// ── Résout le canal ciblé par une commande admin manuelle ──────────────────
// Si un channel_id est fourni en dernier argument, on l'utilise ; sinon, s'il
// n'y a qu'un seul canal actif, on le prend par défaut ; sinon on demande de préciser.
async function resolveCommandChannel(explicitId) {
  if (explicitId) return await getChannelById(explicitId);
  const all = await pool.query("SELECT * FROM telegram_config WHERE enabled=true").catch(()=>({rows:[]}));
  if (all.rows.length === 1) return all.rows[0];
  return { _ambiguous: true, list: all.rows };
}

// ── /grant <telegram_id> <jours> [channel_id] — accorder un accès ──────────
bot.onText(/\/grant\s+(\d+)\s+(\d+)(?:\s+(-?\d+))?/, async (msg, match) => {
  if (!(await isAdminUser(msg.chat.id))) return;
  const [, tgId, days, chanId] = match;
  const channel = await resolveCommandChannel(chanId);
  if (!channel || channel._ambiguous) {
    const list = channel?.list?.map(c=>`\`${c.channel_id}\` — ${esc(c.channel_name||'')}`).join('\n') || '';
    bot.sendMessage(msg.chat.id, `⚠️ Précise le canal : \`/grant ${tgId} ${days} <channel_id>\`\n\n${list}`, {parse_mode:'Markdown'}); return;
  }
  const exp = new Date(Date.now() + parseInt(days,10)*24*60*60*1000);
  await pool.query(
    `INSERT INTO channel_temp_access(telegram_id,channel_id,expires_at) VALUES($1,$2,$3)
     ON CONFLICT(telegram_id, channel_id) DO UPDATE SET expires_at=$3,kicked=FALSE`,
    [tgId, String(channel.channel_id), exp]
  ).catch(()=>{});
  const linked = await getLinkedUser(tgId);
  if (linked) {
    await pool.query(`UPDATE users SET subscription_expires_at=$1,is_premium=true WHERE id=$2`,[exp, linked.id]).catch(()=>{});
  }
  await bot.sendMessage(tgId, `🎁 Un accès de *${days} jour(s)* vous a été accordé pour *${esc(channel.channel_name||'')}*, valable jusqu'au ${fmtDate(exp)}.`, {parse_mode:'Markdown'}).catch(()=>{});
  bot.sendMessage(msg.chat.id, `✅ Accès de ${days}j accordé à \`${tgId}\` sur *${esc(channel.channel_name||'')}*.`, {parse_mode:'Markdown'});
});

// ── /extend <telegram_id> <jours> [channel_id] — prolonger l'accès existant ──
bot.onText(/\/extend\s+(\d+)\s+(\d+)(?:\s+(-?\d+))?/, async (msg, match) => {
  if (!(await isAdminUser(msg.chat.id))) return;
  const [, tgId, days, chanId] = match;
  const channel = await resolveCommandChannel(chanId);
  if (!channel || channel._ambiguous) {
    const list = channel?.list?.map(c=>`\`${c.channel_id}\` — ${esc(c.channel_name||'')}`).join('\n') || '';
    bot.sendMessage(msg.chat.id, `⚠️ Précise le canal : \`/extend ${tgId} ${days} <channel_id>\`\n\n${list}`, {parse_mode:'Markdown'}); return;
  }
  const cur = await pool.query("SELECT expires_at FROM channel_temp_access WHERE telegram_id=$1 AND channel_id=$2",[tgId,String(channel.channel_id)]).catch(()=>({rows:[]}));
  const base = (cur.rows[0]?.expires_at && new Date(cur.rows[0].expires_at) > new Date()) ? new Date(cur.rows[0].expires_at) : new Date();
  const exp = new Date(base.getTime() + parseInt(days,10)*24*60*60*1000);
  await pool.query(
    `INSERT INTO channel_temp_access(telegram_id,channel_id,expires_at) VALUES($1,$2,$3)
     ON CONFLICT(telegram_id, channel_id) DO UPDATE SET expires_at=$3,kicked=FALSE`,
    [tgId, String(channel.channel_id), exp]
  ).catch(()=>{});
  const linked = await getLinkedUser(tgId);
  if (linked) await pool.query(`UPDATE users SET subscription_expires_at=$1,is_premium=true WHERE id=$2`,[exp, linked.id]).catch(()=>{});
  await bot.sendMessage(tgId, `⏰ Votre accès à *${esc(channel.channel_name||'')}* a été prolongé jusqu'au ${fmtDate(exp)}.`, {parse_mode:'Markdown'}).catch(()=>{});
  bot.sendMessage(msg.chat.id, `✅ Accès prolongé de ${days}j pour \`${tgId}\` — expire le ${fmtDate(exp)}.`, {parse_mode:'Markdown'});
});

// ── /bonus <telegram_id> <heures> [channel_id] — ajouter un bonus de X heures ──
bot.onText(/\/bonus\s+(\d+)\s+(\d+)(?:\s+(-?\d+))?/, async (msg, match) => {
  if (!(await isAdminUser(msg.chat.id))) return;
  const [, tgId, hours, chanId] = match;
  const channel = await resolveCommandChannel(chanId);
  if (!channel || channel._ambiguous) {
    const list = channel?.list?.map(c=>`\`${c.channel_id}\` — ${esc(c.channel_name||'')}`).join('\n') || '';
    bot.sendMessage(msg.chat.id, `⚠️ Précise le canal : \`/bonus ${tgId} ${hours} <channel_id>\`\n\n${list}`, {parse_mode:'Markdown'}); return;
  }
  const cur = await pool.query("SELECT expires_at FROM channel_temp_access WHERE telegram_id=$1 AND channel_id=$2",[tgId,String(channel.channel_id)]).catch(()=>({rows:[]}));
  const base = (cur.rows[0]?.expires_at && new Date(cur.rows[0].expires_at) > new Date()) ? new Date(cur.rows[0].expires_at) : new Date();
  const exp = new Date(base.getTime() + parseInt(hours,10)*60*60*1000);
  await pool.query(
    `INSERT INTO channel_temp_access(telegram_id,channel_id,expires_at) VALUES($1,$2,$3)
     ON CONFLICT(telegram_id, channel_id) DO UPDATE SET expires_at=$3,kicked=FALSE`,
    [tgId, String(channel.channel_id), exp]
  ).catch(()=>{});
  await bot.sendMessage(tgId, `🎁 Bonus de *${hours}h* ajouté sur *${esc(channel.channel_name||'')}* ! Nouvel accès jusqu'au ${fmtDate(exp)}.`, {parse_mode:'Markdown'}).catch(()=>{});
  bot.sendMessage(msg.chat.id, `✅ Bonus de ${hours}h ajouté à \`${tgId}\`.`, {parse_mode:'Markdown'});
});

// ── /unblock <telegram_id> [channel_id] — permettre de rejoindre à nouveau ──
bot.onText(/\/unblock\s+(\d+)(?:\s+(-?\d+))?/, async (msg, match) => {
  if (!(await isAdminUser(msg.chat.id))) return;
  const [, tgId, chanId] = match;
  const channel = await resolveCommandChannel(chanId);
  if (!channel || channel._ambiguous) {
    const list = channel?.list?.map(c=>`\`${c.channel_id}\` — ${esc(c.channel_name||'')}`).join('\n') || '';
    bot.sendMessage(msg.chat.id, `⚠️ Précise le canal : \`/unblock ${tgId} <channel_id>\`\n\n${list}`, {parse_mode:'Markdown'}); return;
  }
  await pool.query("DELETE FROM channel_temp_access WHERE telegram_id=$1 AND channel_id=$2",[tgId, String(channel.channel_id)]).catch(()=>{});
  bot.sendMessage(msg.chat.id, `✅ \`${tgId}\` débloqué sur *${esc(channel.channel_name||'')}* — il peut refaire un essai gratuit.`, {parse_mode:'Markdown'});
});

// ── /remove <telegram_id> [channel_id] — retirer immédiatement du canal ────
bot.onText(/\/remove\s+(\d+)(?:\s+(-?\d+))?/, async (msg, match) => {
  if (!(await isAdminUser(msg.chat.id))) return;
  const [, tgId, chanId] = match;
  const channel = await resolveCommandChannel(chanId);
  if (!channel || channel._ambiguous) {
    const list = channel?.list?.map(c=>`\`${c.channel_id}\` — ${esc(c.channel_name||'')}`).join('\n') || '';
    bot.sendMessage(msg.chat.id, `⚠️ Précise le canal : \`/remove ${tgId} <channel_id>\`\n\n${list}`, {parse_mode:'Markdown'}); return;
  }
  await bot.banChatMember(channel.channel_id, tgId).catch(()=>{});
  await bot.unbanChatMember(channel.channel_id, tgId).catch(()=>{});
  await pool.query("UPDATE channel_temp_access SET kicked=TRUE WHERE telegram_id=$1 AND channel_id=$2",[tgId, String(channel.channel_id)]).catch(()=>{});
  await bot.sendMessage(tgId, `⛔ Vous avez été retiré de *${esc(channel.channel_name||'')}* par l'administrateur.`, {parse_mode:'Markdown'}).catch(()=>{});
  bot.sendMessage(msg.chat.id, `✅ \`${tgId}\` retiré de *${esc(channel.channel_name||'')}*.`, {parse_mode:'Markdown'});
});

// ── /start ─────────────────────────────────────────────────────────────────
bot.onText(/\/start(?:\s+(.+))?/, async (msg, match) => {
  const chatId=msg.chat.id;
  const payload=(match && match[1]||'').trim();

  // ── Deep-link "🎁 Activer mon essai 24h" tapé depuis le canal ──────────
  if (payload.startsWith('trial_')) {
    const channelId = payload.slice('trial_'.length);
    const channel = await pool.query(
      "SELECT * FROM telegram_config WHERE channel_id=$1", [channelId]
    ).then(r=>r.rows[0]).catch(()=>null);
    if (channel) {
      await grantOrDenyTrial(channel, { id:chatId, username:msg.from?.username, first_name:msg.from?.first_name });
      return;
    }
  }

  tgSessions.delete(chatId);
  const linked=await getLinkedUser(chatId);
  if (linked) {
    if (linked.is_admin) { await sendAdminDashboard(chatId); return; }
    await sendUserDashboard(chatId,linked); return;
  }
  // Non connecté — menu invité
  await trackVisitor(chatId,msg.from?.username,msg.from?.first_name);
  await bot.sendMessage(chatId,
    `👋 Bienvenue sur *Sossou Kouamé Shopping Boutique*\n\nConnectez-vous ou créez un compte pour accéder à vos services.`,
    SEND_OPT(KB_GUEST_MENU));
});

// ── Callback query (boutons inline) ────────────────────────────────────────
bot.on('callback_query', async (query) => {
  const chatId=query.message.chat.id;
  const data=query.data;
  await bot.answerCallbackQuery(query.id).catch(()=>{});

  // ── Bouton section-titre (sans action) ──
  if (data==='noop') return;

  // ── Déconnexion (admin ET utilisateur) — géré AVANT le bloc admin ──────
  if (data==='deconnexion') {
    await unlinkTgUser(chatId);
    const guestMenu = await getGuestMenu();
    bot.sendMessage(chatId,'✅ Déconnecté.\n\nTapez /start pour vous reconnecter.', { parse_mode:'Markdown', reply_markup: guestMenu }); return;
  }

  // ── ADMIN ──
  const _isAdmin = await isAdminUser(chatId);
  if (_isAdmin) {
    if (data==='admin_dashboard')    { await sendAdminDashboard(chatId); return; }
    if (data==='admin_membres')      { await sendMembersAdmin(chatId,0); return; }
    if (data==='admin_strategies')   { await sendStrategiesAdmin(chatId); return; }
    if (data==='admin_canaux')       { await sendChannelsAdmin(chatId); return; }
    if (data==='admin_scan')         { await scanCanalAdmin(chatId); return; }
    if (data.startsWith('admin_approve_user_')) {
      const userId = data.replace('admin_approve_user_','');
      const u = await pool.query("SELECT * FROM users WHERE id=$1",[userId]).then(r=>r.rows[0]).catch(()=>null);
      if (!u) { bot.sendMessage(chatId,'⚠️ Compte introuvable (déjà traité ?).'); return; }
      await pool.query("UPDATE users SET is_approved=true WHERE id=$1",[userId]).catch(()=>{});
      const nom = esc([u.first_name,u.last_name].filter(Boolean).join(' ')||u.username);
      if (u.telegram_id) {
        await bot.sendMessage(u.telegram_id,
          `✅ *Compte confirmé !*\n\nBonjour ${nom}, votre compte a été validé par l'administrateur.\nVous pouvez maintenant vous connecter.`,
          {parse_mode:'Markdown'}
        ).catch(()=>{});
      }
      if (u.email && GMAIL_USER && GMAIL_PASS) {
        await gmailTransport.sendMail({
          from:`"Sossou Kouamé" <${GMAIL_USER}>`, to:u.email,
          subject:'✅ Votre compte a été confirmé',
          html:`<p>Bonjour ${nom},</p><p>Votre compte <strong>${esc(u.username)}</strong> a été validé par l'administrateur.</p><p>Vous pouvez maintenant vous connecter sur le site.</p>`
        }).catch(()=>{});
      }
      bot.sendMessage(chatId, `✅ Compte \`${esc(u.username)}\` approuvé et notifié.`, {parse_mode:'Markdown'});
      return;
    }
    if (data.startsWith('admin_reject_user_')) {
      const userId = data.replace('admin_reject_user_','');
      const u = await pool.query("SELECT * FROM users WHERE id=$1",[userId]).then(r=>r.rows[0]).catch(()=>null);
      if (!u) { bot.sendMessage(chatId,'⚠️ Compte introuvable (déjà traité ?).'); return; }
      await pool.query("DELETE FROM users WHERE id=$1",[userId]).catch(()=>{});
      bot.sendMessage(chatId, `❌ Compte \`${esc(u.username)}\` rejeté et supprimé.`, {parse_mode:'Markdown'});
      return;
    }
    if (data==='admin_userbot_connect') {
      if (isUserbotReady()) {
        bot.sendMessage(chatId,'✅ Le userbot est déjà connecté et actif. Utilise « 📶 Statut Userbot » pour vérifier, ou reconnecte un autre compte si besoin en renvoyant un numéro.'); 
      }
      tgSessions.set(chatId,{step:'userbot_phone'});
      bot.sendMessage(chatId,
        `🔐 *Connexion du compte userbot*\n\n`+
        `Ce compte Telegram (pas le bot) doit être *administrateur* des canaux à scanner.\n\n`+
        `Envoie son numéro de téléphone avec l'indicatif (ex: \`+22995501564\`) :`,
        {parse_mode:'Markdown'}
      );
      return;
    }
    if (data==='admin_userbot_status') {
      const st = getLoginState();
      const readyNow = isUserbotReady();
      const labels = {idle:'inactif',connecting:'connexion en cours…',awaiting_code:'attente du code',awaiting_password:'attente du mot de passe 2FA',connected:'connecté',error:`erreur : ${st.error||''}`};
      bot.sendMessage(chatId,
        readyNow
          ? '✅ *Userbot connecté et actif.*\nLe scan automatique des membres existants fonctionne.'
          : `ℹ️ *Userbot non actif.*\nÉtat de la dernière tentative : ${labels[st.status]||st.status}\n\nUtilise « 🔐 Connecter Userbot » pour (re)lancer la connexion.`,
        {parse_mode:'Markdown'}
      );
      return;
    }
    if (data==='admin_kick') {
      await kickExpiredUsers(false);
      bot.sendMessage(chatId,'✅ Vérification expirés effectuée.'); return;
    }
    if (data.startsWith('membres_p_')) {
      await sendMembersAdmin(chatId,parseInt(data.replace('membres_p_',''))); return;
    }
    if (data==='admin_config_canal') {
      tgSessions.set(chatId,{step:'config_canal_id'});
      bot.sendMessage(chatId,'⚙️ Entrez l\'*ID du canal* (ex: -1001234567890) :',{parse_mode:'Markdown'}); return;
    }
    if (data==='admin_assigner') {
      const members=await pool.query(
        `SELECT telegram_id::bigint,username,first_name,last_name FROM users WHERE telegram_id IS NOT NULL ORDER BY username LIMIT 25`
      ).catch(()=>({rows:[]}));
      if (!members.rows.length) { bot.sendMessage(chatId,'📭 Aucun membre lié.'); return; }
      const btns=members.rows.map(m=>[{text:esc([m.first_name,m.last_name].filter(Boolean).join(' ')||m.username),callback_data:`asgn_u_${m.telegram_id}`}]);
      btns.push([{text:'❌ Annuler',callback_data:'cancel'}]);
      bot.sendMessage(chatId,'🎯 *Choisir un membre :*',SEND_OPT({inline_keyboard:btns})); return;
    }
    if (data.startsWith('asgn_u_')) {
      const tgId=parseInt(data.replace('asgn_u_',''));
      const strategies=await pool.query(`SELECT * FROM strategy_ideas WHERE enabled=true ORDER BY sort_order,id`).catch(()=>({rows:[]}));
      if (!strategies.rows.length) { bot.sendMessage(chatId,'📭 Aucune stratégie disponible.'); return; }
      tgSessions.set(chatId,{step:'assign_strategy',target_tg_id:tgId});
      const btns=strategies.rows.map(s=>[{text:s.name,callback_data:`asgn_s_${s.id}`}]);
      btns.push([{text:'❌ Annuler',callback_data:'cancel'}]);
      bot.sendMessage(chatId,'📋 *Choisir une stratégie :*',SEND_OPT({inline_keyboard:btns})); return;
    }
    if (data.startsWith('asgn_s_')) {
      const stratId=data.replace('asgn_s_','');
      const sess=tgSessions.get(chatId);
      if (!sess||sess.step!=='assign_strategy') return;
      tgSessions.delete(chatId);
      const userRow=await pool.query("SELECT id FROM users WHERE telegram_id=$1::text",[String(sess.target_tg_id)]).catch(()=>({rows:[]}));
      if (!userRow.rows.length) { bot.sendMessage(chatId,'❌ Membre introuvable.'); return; }
      const userId=userRow.rows[0].id;
      await pool.query(`INSERT INTO user_strategy_visible(user_id,strategy_id) VALUES($1,$2) ON CONFLICT DO NOTHING`,[userId,String(stratId)]).catch(()=>{});
      const [strat_,user__]=await Promise.all([
        pool.query("SELECT name FROM strategy_ideas WHERE id=$1",[stratId]),
        pool.query("SELECT username FROM users WHERE id=$1",[userId])
      ]).catch(()=>([{rows:[{}]},{rows:[{}]}]));
      const stratName=strat_.rows[0]?.name||stratId;
      const uname=user__.rows[0]?.username||userId;
      bot.sendMessage(chatId,`✅ Stratégie *${stratName}* assignée à *${uname}*`,{parse_mode:'Markdown'});
      bot.sendMessage(sess.target_tg_id,
        `🎯 *Nouvelle stratégie disponible !*\n\nLa stratégie *${stratName}* vous a été attribuée.\n\nTapez /start pour voir votre compte.`,
        {parse_mode:'Markdown'}).catch(()=>{});
      return;
    }
    // ── Membres expirés (accorder abonnement gratuit) ──────────────────────
    if (data==='admin_expires') {
      const now=new Date();
      // Membres liés expirés
      const [linkedExp, tempExp] = await Promise.all([
        pool.query(`
          SELECT telegram_id::bigint,username,first_name,last_name,subscription_expires_at
          FROM users
          WHERE telegram_id IS NOT NULL
            AND (subscription_expires_at IS NULL OR subscription_expires_at<NOW())
          ORDER BY subscription_expires_at DESC NULLS LAST LIMIT 25
        `).catch(()=>({rows:[]})),
        pool.query(`
          SELECT telegram_id,tg_username,tg_first_name,expires_at
          FROM channel_temp_access
          WHERE expires_at<NOW() AND kicked=TRUE
          ORDER BY expires_at DESC LIMIT 10
        `).catch(()=>({rows:[]}))
      ]);

      const total = linkedExp.rows.length + tempExp.rows.length;
      if (!total) {
        await bot.sendMessage(chatId,
          `✅ *Aucun membre expiré pour l'instant.*\n\nTous les membres actifs sont dans le canal.`,
          SEND_OPT(KB_ADMIN_MENU)); return;
      }

      let msg=`🔴 *Membres expirés* (${total})\n━━━━━━━━━━━━━━━━━━━━━━\n\n`;
      msg+=`Sélectionnez un membre pour lui accorder du temps gratuit :\n`;

      const btns=[];
      for (const m of linkedExp.rows) {
        const name=[m.first_name,m.last_name].filter(Boolean).join(' ')||m.username||`TG:${m.telegram_id}`;
        const label=(name.length>22?name.substring(0,20)+'…':name);
        const since=m.subscription_expires_at?`exp. ${fmtDate(m.subscription_expires_at)}`:'Jamais abonné';
        btns.push([{text:`🔴 ${label} — ${since}`, callback_data:`grant_free_${m.telegram_id}`}]);
      }
      for (const m of tempExp.rows) {
        const name=m.tg_first_name||m.tg_username||`TG:${m.telegram_id}`;
        const label=(name.length>22?name.substring(0,20)+'…':name);
        btns.push([{text:`⚫ ${label} — visiteur`, callback_data:`grant_free_${m.telegram_id}`}]);
      }
      btns.push([{text:'🔙 Menu admin',callback_data:'cancel'}]);
      await bot.sendMessage(chatId, msg, SEND_OPT({inline_keyboard:btns})); return;
    }

    // ── Accorder abonnement gratuit à un membre expiré ─────────────────────
    if (data.startsWith('grant_free_')) {
      const tgId=data.replace('grant_free_','');
      // Chercher le nom (lié ou non lié)
      const lk=await pool.query(
        `SELECT id,username,first_name,last_name FROM users WHERE telegram_id=$1`,[tgId]
      ).catch(()=>({rows:[]}));
      const tv=await pool.query(
        `SELECT tg_username,tg_first_name FROM channel_temp_access WHERE telegram_id=$1`,[tgId]
      ).catch(()=>({rows:[]}));
      const name=(lk.rows.length
        ? ([lk.rows[0].first_name,lk.rows[0].last_name].filter(Boolean).join(' ')||lk.rows[0].username)
        : (tv.rows[0]?.tg_first_name||tv.rows[0]?.tg_username)
      )||`ID:${tgId}`;
      tgSessions.set(chatId,{step:'grant_free_time', target_tg_id:tgId, target_name:name});
      await bot.sendMessage(chatId,
        `🎁 *Accorder du temps gratuit à ${esc(name)}*\n\n`+
        `Entrez la durée à accorder :\n`+
        `• \`5h\` = 5 heures\n`+
        `• \`30m\` ou \`30min\` = 30 minutes\n`+
        `• \`2j\` ou \`2d\` = 2 jours\n`+
        `• \`90\` = 90 minutes (nombre seul = minutes)\n\n`+
        `L'accès sera accordé *en plus* de toute durée restante.`,
        SEND_OPT({inline_keyboard:[[{text:'❌ Annuler',callback_data:'cancel'}]]})); return;
    }
    if (data==='cancel') { tgSessions.delete(chatId); bot.sendMessage(chatId,'❌ Annulé.',SEND_OPT(KB_ADMIN_MENU)); return; }

    // ── Annuler un paiement en attente ──
    if (data==='admin_cancel_pmt') {
      const pending=await pool.query(
        `SELECT pr.id,pr.plan_label,pr.amount_usd,u.username,u.first_name,u.last_name
         FROM payment_requests pr
         LEFT JOIN users u ON u.id=pr.user_id
         WHERE pr.status='pending'
         ORDER BY pr.created_at DESC LIMIT 20`
      ).catch(()=>({rows:[]}));
      if (!pending.rows.length) {
        bot.sendMessage(chatId,'✅ Aucun paiement en attente à annuler.',SEND_OPT(KB_ADMIN_MENU)); return;
      }
      // Proposer : Effacer 1 ou Effacer tout
      const btns=[
        [{ text:`🗑 Effacer TOUT (${pending.rows.length} en attente)`, callback_data:'cancel_pmt_all' }],
        ...pending.rows.map(p=>{
          const amt=Math.round((p.amount_usd||0)*656).toLocaleString('fr-FR');
          const who=esc([p.first_name,p.last_name].filter(Boolean).join(' ')||p.username||'?');
          return [{text:`❌ #${p.id} — ${esc(p.plan_label||'?')} (${amt} XOF) — ${who}`, callback_data:`cancel_pmt_${p.id}`}];
        }),
        [{text:'🔙 Fermer',callback_data:'cancel'}]
      ];
      bot.sendMessage(chatId,
        `❌ *Annuler un paiement en attente*\n━━━━━━━━━━━━━━━━━━━━━━\n`+
        `${pending.rows.length} paiement(s) en attente\n\nChoisissez :`,
        SEND_OPT({inline_keyboard:btns})
      ); return;
    }
    // Effacer TOUT
    if (data==='cancel_pmt_all') {
      const r=await pool.query("SELECT COUNT(*)::int n FROM payment_requests WHERE status='pending'").catch(()=>({rows:[{n:0}]}));
      const n=r.rows[0].n;
      if (!n) { bot.sendMessage(chatId,'✅ Aucun paiement en attente.',SEND_OPT(KB_ADMIN_MENU)); return; }
      await pool.query("UPDATE payment_requests SET status='cancelled' WHERE status='pending'");
      bot.sendMessage(chatId,
        `✅ *${n} paiement(s) en attente annulé(s)*\n\nTous les paiements pending ont été effacés.`,
        SEND_OPT(KB_ADMIN_MENU)
      ); return;
    }
    // Effacer 1
    if (data.startsWith('cancel_pmt_')) {
      const payId=parseInt(data.replace('cancel_pmt_',''));
      const pr=await pool.query("SELECT * FROM payment_requests WHERE id=$1 AND status='pending'",[payId]).catch(()=>({rows:[]}));
      if (!pr.rows.length) { bot.sendMessage(chatId,'❌ Paiement introuvable ou déjà traité.',SEND_OPT(KB_ADMIN_MENU)); return; }
      await pool.query("UPDATE payment_requests SET status='cancelled' WHERE id=$1",[payId]);
      const row=pr.rows[0];
      const amt=Math.round((row.amount_usd||0)*656).toLocaleString('fr-FR');
      bot.sendMessage(chatId,
        `✅ *Paiement #${payId} annulé*\n\n• Service : ${esc(row.plan_label||'—')}\n• Montant : ${amt} XOF`,
        SEND_OPT(KB_ADMIN_MENU)
      ); return;
    }

    // ── Membres canal ──
    if (data==='admin_membres_canal' || data.startsWith('admin_membres_canal_p')) {
      const page = data.startsWith('admin_membres_canal_p') ? parseInt(data.split('_p')[1]||'0') : 0;
      const PER_PAGE = 8;
      const [linked, visitors, channel] = await Promise.all([
        pool.query(`SELECT telegram_id::bigint,username,first_name,last_name,subscription_expires_at,is_premium,is_pro
                    FROM users WHERE telegram_id IS NOT NULL
                    ORDER BY subscription_expires_at DESC NULLS LAST, last_seen DESC NULLS LAST`).catch(()=>({rows:[]})),
        pool.query(`SELECT telegram_id,tg_username,tg_first_name FROM telegram_visitors ORDER BY seen_at DESC LIMIT 10`).catch(()=>({rows:[]})),
        getActiveChannel()
      ]);
      const now = new Date();
      const slice = linked.rows.slice(page*PER_PAGE, (page+1)*PER_PAGE);
      const totalPages = Math.ceil(linked.rows.length / PER_PAGE) || 1;

      let msg = `👥 *Membres du Canal*`;
      if (channel) msg += ` — *${esc(channel.channel_name||channel.channel_id)}*`;
      msg += `\n━━━━━━━━━━━━━━━━━━━━━━\n`;
      msg += `Total liés : *${linked.rows.length}* | Page ${page+1}/${totalPages}\n\n`;

      const memberBtns = [];
      slice.forEach((m, i) => {
        const exp = m.subscription_expires_at ? new Date(m.subscription_expires_at) : null;
        const actif = exp && exp > now;
        const remMs = actif ? exp - now : 0;
        const remStr = actif ? fmtRemaining(remMs) : 'Expiré';
        const name = [m.first_name,m.last_name].filter(Boolean).join(' ') || m.username || `ID:${m.telegram_id}`;
        const nameEsc = esc(name);
        const icon = actif ? '✅' : '❌';
        msg += `${page*PER_PAGE+i+1}. *${nameEsc}* ${m.is_premium?'💎':''}\n`;
        msg += `   ${icon} ⏰ *${remStr}*\n`;
        if (m.username) msg += `   @${esc(m.username)}\n`;
        msg += '\n';
        // Bouton pour cliquer sur ce membre et définir son temps
        const label = name.length > 20 ? name.substring(0,18)+'…' : name;
        memberBtns.push([{ text: `⏱ ${label} — ${remStr}`, callback_data: `set_time_${m.telegram_id}` }]);
      });

      if (visitors.rows.length && page === 0) {
        msg += `📩 *Non liés (interagis)* : ${visitors.rows.length}\n`;
      }

      // Pagination + boutons membres
      const navBtns = [];
      if (page > 0)              navBtns.push({ text:'◀ Préc', callback_data:`admin_membres_canal_p${page-1}` });
      if (page+1 < totalPages)   navBtns.push({ text:'Suiv ▶', callback_data:`admin_membres_canal_p${page+1}` });
      const keyboard = { inline_keyboard: [
        ...memberBtns,
        ...(navBtns.length ? [navBtns] : []),
        [{ text:'🔙 Menu admin', callback_data:'cancel' }]
      ]};
      await bot.sendMessage(chatId, msg, SEND_OPT(keyboard)); return;
    }

    // ── Clic sur un membre → définir son temps ──
    if (data.startsWith('set_time_')) {
      const tgId = data.replace('set_time_','');
      const mRes = await pool.query(
        `SELECT id,username,first_name,last_name,subscription_expires_at FROM users WHERE telegram_id=$1`,
        [tgId]
      ).catch(()=>({rows:[]}));
      if (!mRes.rows.length) { bot.sendMessage(chatId,'❌ Membre introuvable.',SEND_OPT(KB_ADMIN_MENU)); return; }
      const m = mRes.rows[0];
      const name = [m.first_name,m.last_name].filter(Boolean).join(' ') || m.username || `ID:${tgId}`;
      const exp = m.subscription_expires_at ? new Date(m.subscription_expires_at) : null;
      const now = new Date();
      const actif = exp && exp > now;
      const remStr = actif ? fmtRemaining(exp-now) : 'Expiré';
      tgSessions.set(chatId, { step:'set_member_time', target_tg_id: tgId, target_user_id: m.id, target_name: name });
      await bot.sendMessage(chatId,
        `⏱ *Définir la durée pour ${esc(name)}*\n\n`+
        `• Statut actuel : ${actif?'✅ Actif':'❌ Expiré'} — *${remStr}*\n\n`+
        `Entrez la durée à *définir* (remplace l'actuelle) :\n`+
        `• \`30\` ou \`30j\` = 30 jours\n`+
        `• \`24h\` = 24 heures\n`+
        `• \`90m\` = 90 minutes\n`+
        `• \`0\` = retirer du canal immédiatement\n`+
        `• \`+7j\` = ajouter 7 jours à l'abonnement actuel`,
        SEND_OPT({inline_keyboard:[[{text:'❌ Annuler',callback_data:'cancel'}]]})
      ); return;
    }

    // ── Lien canal ──
    if (data==='admin_canal_link') {
      const channel = await getActiveChannel();
      if (!channel) { bot.sendMessage(chatId,'❌ Aucun canal actif.',SEND_OPT(KB_ADMIN_MENU)); return; }
      let msg = `🔗 *Lien d'accès au canal*\n━━━━━━━━━━━━━━━━━━━━━━\n`;
      msg += `• Canal : *${esc(channel.channel_name||channel.channel_id)}*\n`;
      if (channel.channel_invite_link) {
        msg += `• Lien actuel :\n${channel.channel_invite_link}\n\n`;
      } else {
        msg += `• Aucun lien configuré\n\n`;
      }
      msg += `Choisissez une option :`;
      const kb = { inline_keyboard: [
        [{ text:'🤖 Générer lien automatique (1 usage)', callback_data:'canal_link_auto' }],
        [{ text:'✏️ Saisir un lien manuellement', callback_data:'canal_link_manual' }],
        [{ text:'🔙 Menu admin', callback_data:'cancel' }]
      ]};
      await bot.sendMessage(chatId, msg, SEND_OPT(kb)); return;
    }

    if (data==='canal_link_auto') {
      const channel = await getActiveChannel();
      if (!channel) { bot.sendMessage(chatId,'❌ Aucun canal actif.',SEND_OPT(KB_ADMIN_MENU)); return; }
      try {
        const linkObj = await bot.createChatInviteLink(channel.channel_id, { member_limit: 1 });
        await pool.query("UPDATE telegram_config SET channel_invite_link=$1 WHERE channel_id=$2",
          [linkObj.invite_link, channel.channel_id]);
        bot.sendMessage(chatId,
          `✅ *Lien généré (usage unique) :*\n\n${linkObj.invite_link}\n\n⚠️ Ce lien expire après 1 clic. Un nouveau sera créé pour chaque nouvel abonné.`,
          SEND_OPT(KB_ADMIN_MENU));
      } catch(e) {
        bot.sendMessage(chatId,`❌ Erreur lors de la génération du lien : ${e.message}`,SEND_OPT(KB_ADMIN_MENU));
      }
      return;
    }

    if (data==='canal_link_manual') {
      tgSessions.set(chatId,{ step:'config_canal_link' });
      bot.sendMessage(chatId,
        `✏️ *Saisir le lien du canal*\n\nCollez le lien d'invitation Telegram (ex: https://t.me/+xxxxx) :`,
        SEND_OPT({inline_keyboard:[[{text:'❌ Annuler',callback_data:'cancel'}]]})
      ); return;
    }

    // ── Lien d'inscription (admin configure l'URL du site d'inscription) ──
    if (data==='admin_inscription_link') {
      const cur = await pool.query("SELECT value FROM settings WHERE key='inscription_url'").catch(()=>({rows:[]}));
      const curUrl = cur.rows[0]?.value || 'Non défini';
      tgSessions.set(chatId,{ step:'set_inscription_link' });
      await bot.sendMessage(chatId,
        `🌐 *Lien d'inscription du site*\n━━━━━━━━━━━━━━━━━━━━━━\n`+
        `Actuel : ${curUrl}\n\n`+
        `Entrez le nouveau lien d'inscription (URL complète) :\n`+
        `_Ex: https://sossou-kouame-paiement.onrender.com/#register_`,
        SEND_OPT({inline_keyboard:[[{text:'❌ Annuler',callback_data:'cancel'}]]})
      ); return;
    }
  }

  // ── Confirmation inscription ──
  if (data==='reg_confirm_yes') {
    const sess=tgSessions.get(chatId);
    if (!sess||sess.step!=='reg_final_confirm') return;
    tgSessions.delete(chatId);
    try {
      const exists=await pool.query("SELECT id FROM users WHERE username=$1",[sess.username]);
      if (exists.rows.length) { bot.sendMessage(chatId,'⚠️ Identifiant déjà pris. Tapez /start pour réessayer.'); return; }
      const hash=await bcrypt.hash(sess.password,10);
      const ins=await pool.query(
        `INSERT INTO users(username,first_name,last_name,password_hash,plain_password,account_type,promo_code,is_approved)
         VALUES($1,$2,$3,$4,$5,$6,$7,FALSE)
         RETURNING id,username,first_name,last_name,email,is_premium,is_pro,is_admin,subscription_expires_at,account_type`,
        [sess.username, sess.first_name||null, sess.last_name||null, hash, sess.password,
         sess.account_type||'Standard', sess.promo_code||null]
      );
      const newUser=ins.rows[0];
      await linkTgUser(chatId,newUser.id,query.from?.username,query.from?.first_name);
      // ⚠️ Pas d'accès immédiat : le compte doit être validé par l'admin.
      await notifyAdminNewRegistration(newUser);
      await bot.sendMessage(chatId,
        `✅ *Compte créé !*\n\n`+
        `Votre compte *${esc(newUser.username)}* a été enregistré dans la base de données.\n\n`+
        `⏳ Veuillez patienter pour la vérification de l'administrateur. Dès que votre compte sera confirmé, vous recevrez une notification pour vous connecter.`,
        {parse_mode:'Markdown'}
      );
    } catch(e) { bot.sendMessage(chatId,'❌ Erreur création compte. Réessayez.'); console.error('[TG-REG]',e.message); }
    return;
  }
  // ── Sauter le code promo lors de l'inscription ──
  if (data==='reg_skip_promo') {
    const sess=tgSessions.get(chatId);
    if (!sess||sess.step!=='reg_promo') return;
    tgSessions.set(chatId,{...sess,step:'reg_name',promo_code:null});
    bot.sendMessage(chatId,'👤 Entrez votre *prénom et nom* (ex: Jean Dupont) :',{parse_mode:'Markdown'}); return;
  }
  // ── Choix du type de compte lors de l'inscription ──
  if (data==='reg_type_Standard'||data==='reg_type_Pro') {
    const sess=tgSessions.get(chatId);
    if (!sess||sess.step!=='reg_account_type') return;
    const account_type=data==='reg_type_Standard'?'Standard':'Pro';
    tgSessions.set(chatId,{...sess,step:'reg_password',account_type});
    bot.sendMessage(chatId,`✅ Type : *${account_type}*\n\n🔑 Choisissez un *mot de passe* (min. 6 caractères) :`,{parse_mode:'Markdown'}); return;
  }

  // ── Menu utilisateur ──
  if (data==='mon_compte') {
    const linked=await getLinkedUser(chatId);
    if (linked) await sendUserDashboard(chatId,linked);
    else bot.sendMessage(chatId,'❌ Non connecté. Tapez /start');
    return;
  }
  if (data==='action_connexion') {
    tgSessions.set(chatId,{step:'login_username'});
    bot.sendMessage(chatId,'🔐 Entrez votre *identifiant* :',{parse_mode:'Markdown'}); return;
  }
  if (data==='action_inscription') {
    // Vérifier si un lien d'inscription est configuré par l'admin
    const inscR = await pool.query("SELECT value FROM settings WHERE key='inscription_url'").catch(()=>({rows:[]}));
    const inscUrl = inscR.rows[0]?.value || null;
    if (inscUrl) {
      await bot.sendMessage(chatId,
        `📝 *Inscription*\n\nCréez votre compte directement sur notre site :`,
        { parse_mode:'Markdown', reply_markup:{ inline_keyboard:[
          [{ text:"🌐 S'inscrire sur le site", url: inscUrl }],
          [{ text:'🔐 Déjà inscrit ? Se connecter', callback_data:'action_connexion' }]
        ]}}
      );
    } else {
      // Fallback : inscription via le bot Telegram
      tgSessions.set(chatId,{step:'reg_username'});
      bot.sendMessage(chatId,'📝 *Inscription*\n\nChoisissez un *identifiant* (sans espaces) :',{parse_mode:'Markdown'});
    }
    return;
  }
  if (data==='cancel') { tgSessions.delete(chatId); bot.sendMessage(chatId,'❌ Annulé.'); return; }
});

// ── Messages texte (tous les flux) ────────────────────────────────────────
bot.on('message', async (msg) => {
  const chatId=msg.chat.id;
  const text=(msg.text||'').trim();
  if (!text||text.startsWith('/')) return;
  const sess=tgSessions.get(chatId);
  if (!sess) return;

  // Calcul une seule fois du statut admin
  const _isAdmin = await isAdminUser(chatId);

  // ── Connexion userbot : étape 1/3 — téléphone ──────────────────────────────
  if (_isAdmin && sess.step==='userbot_phone') {
    if (!text.startsWith('+') || text.length<8) {
      bot.sendMessage(chatId,'⚠️ Format invalide. Envoie le numéro avec l\'indicatif, ex: `+22995501564` :',{parse_mode:'Markdown'}); return;
    }
    await beginLogin(text);
    tgSessions.set(chatId,{step:'userbot_await_code'});
    bot.sendMessage(chatId,
      `📨 Code envoyé par Telegram sur ce numéro.\n\n`+
      `Tape ici le code reçu (ne le communique à personne d'autre) :`
    );
    return;
  }

  // ── Connexion userbot : étape 2/3 — code reçu ──────────────────────────────
  if (_isAdmin && sess.step==='userbot_await_code') {
    submitCode(text.replace(/\s/g,''));
    bot.sendMessage(chatId,'⏳ Vérification du code…');
    setTimeout(async () => {
      const st = getLoginState();
      if (st.status==='awaiting_password') {
        tgSessions.set(chatId,{step:'userbot_await_password'});
        bot.sendMessage(chatId,'🔒 Ce compte a une double authentification. Envoie le *mot de passe 2FA* :',{parse_mode:'Markdown'});
      } else if (st.status==='connected') {
        tgSessions.delete(chatId);
        bot.sendMessage(chatId,'✅ *Userbot connecté avec succès !*\n\nLe scan automatique des membres existants est maintenant actif dès qu\'un canal est ajouté.',SEND_OPT(KB_ADMIN_MENU));
      } else if (st.status==='error') {
        tgSessions.delete(chatId);
        bot.sendMessage(chatId,`❌ Échec de connexion : ${esc(st.error||'code invalide')}.\n\nRéessaie via « 🔐 Connecter Userbot ».`,SEND_OPT(KB_ADMIN_MENU));
      } else {
        bot.sendMessage(chatId,'⏳ Toujours en cours… réessaie dans quelques secondes ou renvoie le code.');
      }
    }, 2500);
    return;
  }

  // ── Connexion userbot : étape 3/3 — mot de passe 2FA (si activé) ───────────
  if (_isAdmin && sess.step==='userbot_await_password') {
    submitPassword(text);
    bot.sendMessage(chatId,'⏳ Vérification du mot de passe…');
    setTimeout(async () => {
      const st = getLoginState();
      if (st.status==='connected') {
        tgSessions.delete(chatId);
        bot.sendMessage(chatId,'✅ *Userbot connecté avec succès !*\n\nLe scan automatique des membres existants est maintenant actif dès qu\'un canal est ajouté.',SEND_OPT(KB_ADMIN_MENU));
      } else if (st.status==='error') {
        tgSessions.delete(chatId);
        bot.sendMessage(chatId,`❌ Échec de connexion : ${esc(st.error||'mot de passe invalide')}.\n\nRéessaie via « 🔐 Connecter Userbot ».`,SEND_OPT(KB_ADMIN_MENU));
      } else {
        bot.sendMessage(chatId,'⏳ Toujours en cours… réessaie dans quelques secondes.');
      }
    }, 2500);
    return;
  }

  // Réponse durée canal (admin) ─────────────────────────────────────────────
  if (_isAdmin && sess.step==='canal_duration_confirm') {
    if (text.toUpperCase()==='NON') {
      tgSessions.delete(chatId);
      bot.sendMessage(chatId,'✅ Durée d\'essai conservée : 24h par défaut pour les nouveaux membres.',SEND_OPT(KB_ADMIN_MENU)); return;
    }
    const days=parseInt(text,10);
    if (isNaN(days)||days<=0) {
      bot.sendMessage(chatId,'⚠️ Durée invalide. Entrez le nombre de jours (ex: 30) ou NON :'); return;
    }
    const exp=new Date(Date.now()+days*24*60*60*1000);
    // Stocker la durée par défaut dans la config du canal
    await pool.query(
      "UPDATE telegram_config SET default_duration_days=$1 WHERE channel_id=$2",
      [days,sess.channel_id]
    ).catch(e=>console.error('[DURATION-SAVE]',e.message));
    tgSessions.delete(chatId);
    bot.sendMessage(chatId,
      `✅ *Durée automatique configurée !*\n\n`+
      `• Canal : *${esc(sess.channel_name)}*\n`+
      `• Durée accordée aux nouveaux membres : *${days} jour(s)*\n\n`+
      `Chaque nouveau membre rejoignant le canal recevra automatiquement ${days} jour(s) d'abonnement.`,
      SEND_OPT(KB_ADMIN_MENU)
    ); return;
  }

  // ── Définir le temps d'un membre (admin) ─────────────────────────────────
  if (_isAdmin && sess.step==='set_member_time') {
    const raw = text.trim().toLowerCase();
    const tgId = sess.target_tg_id;
    const userId = sess.target_user_id;
    const name = sess.target_name;
    tgSessions.delete(chatId);

    // Retirer immédiatement
    if (raw==='0') {
      const now = new Date(Date.now() - 1000);
      await pool.query("UPDATE users SET subscription_expires_at=$1,is_premium=false,is_pro=false WHERE id=$2",[now,userId]);
      const channel = await getActiveChannel();
      if (channel) {
        await bot.banChatMember(channel.channel_id, tgId).catch(()=>{});
        await bot.unbanChatMember(channel.channel_id, tgId).catch(()=>{});
        await bot.sendMessage(tgId,
          `⚠️ *Votre abonnement a expiré.*\n\nContactez l'administrateur pour renouveler.`,
          {parse_mode:'Markdown'}
        ).catch(()=>{});
      }
      bot.sendMessage(chatId,`✅ *${esc(name)}* retiré du canal.`,SEND_OPT(KB_ADMIN_MENU)); return;
    }

    // Parser la durée : +7j, 30, 30j, 24h, 90m
    let isAdditive = raw.startsWith('+');
    const clean = raw.replace(/^\+/,'');
    let totalMs = 0;
    const mMatch = clean.match(/^(\d+(?:\.\d+)?)\s*m(?:in)?$/);
    const hMatch = clean.match(/^(\d+(?:\.\d+)?)\s*h$/);
    const dMatch = clean.match(/^(\d+(?:\.\d+)?)\s*j?$/);
    if (mMatch)       totalMs = parseFloat(mMatch[1]) * 60 * 1000;
    else if (hMatch)  totalMs = parseFloat(hMatch[1]) * 3600 * 1000;
    else if (dMatch)  totalMs = parseFloat(dMatch[1]) * 86400 * 1000;
    else { bot.sendMessage(chatId,'⚠️ Format invalide. Ex: 30j, 24h, 90m, +7j'); return; }

    if (totalMs <= 0) { bot.sendMessage(chatId,'⚠️ Durée invalide.'); return; }

    const mRes = await pool.query("SELECT subscription_expires_at FROM users WHERE id=$1",[userId]).catch(()=>({rows:[]}));
    const now = new Date();
    let base = now;
    if (isAdditive) {
      const curExp = mRes.rows[0]?.subscription_expires_at;
      if (curExp && new Date(curExp) > now) base = new Date(curExp);
    }
    const newExpiry = new Date(base.getTime() + totalMs);

    await pool.query("UPDATE users SET subscription_expires_at=$1,is_premium=true WHERE id=$2",[newExpiry,userId]);

    const durStr = isAdditive
      ? `+${raw.replace(/^\+/,'')}`
      : raw.replace(/^(\d+)j?$/, (_, n) => `${n} jour${n>1?'s':''}`).replace(/^(\d+)h$/, '$1 heure(s)').replace(/^(\d+)m$/, '$1 minute(s)');
    const remStr = fmtRemaining(newExpiry - now);

    // Envoyer lien d'invitation au membre
    sendInviteLinkToUser(userId, newExpiry, durStr).catch(()=>{});

    bot.sendMessage(chatId,
      `✅ *Durée mise à jour pour ${esc(name)}*\n\n`+
      `• Durée : *${durStr}*\n`+
      `• Expire le : *${fmtDate(newExpiry)}*\n`+
      `• Temps restant : *${remStr}*\n\n`+
      `Un lien d'invitation a été envoyé au membre.`,
      SEND_OPT(KB_ADMIN_MENU)
    ); return;
  }

  // ── Accorder temps gratuit à un membre expiré (admin) ────────────────────
  if (_isAdmin && sess.step==='grant_free_time') {
    const raw=text.trim().toLowerCase();
    const tgId=sess.target_tg_id;
    const name=sess.target_name;
    tgSessions.delete(chatId);

    // Parser la durée : 5h, 30m, 30min, 2j, 2d, 90 (minutes par défaut)
    let totalMs=0;
    const mMatch=raw.match(/^(\d+(?:\.\d+)?)\s*(?:m|min|mins|minutes?)$/);
    const hMatch=raw.match(/^(\d+(?:\.\d+)?)\s*(?:h|hr|heure?s?)$/);
    const dMatch=raw.match(/^(\d+(?:\.\d+)?)\s*(?:j|d|jours?|days?)$/);
    const numOnly=raw.match(/^(\d+(?:\.\d+)?)$/);
    if      (mMatch) totalMs=parseFloat(mMatch[1])*60*1000;
    else if (hMatch) totalMs=parseFloat(hMatch[1])*3600*1000;
    else if (dMatch) totalMs=parseFloat(dMatch[1])*86400*1000;
    else if (numOnly) totalMs=parseFloat(numOnly[1])*60*1000; // nombre seul = minutes
    else { bot.sendMessage(chatId,'⚠️ Format invalide.\n\nEx: `5h`, `30m`, `2j`, `90`',{parse_mode:'Markdown'}); return; }

    if (totalMs<=0) { bot.sendMessage(chatId,'⚠️ Durée invalide.'); return; }

    const channel=await getActiveChannel();
    const now=new Date();
    const newExpiry=new Date(now.getTime()+totalMs);
    const durStr=raw;

    // Chercher si membre lié ou non
    const lk=await pool.query(
      `SELECT id,username,first_name FROM users WHERE telegram_id=$1`,[tgId]
    ).catch(()=>({rows:[]}));

    if (lk.rows.length) {
      // Membre lié → mettre à jour users
      await pool.query(
        `UPDATE users SET subscription_expires_at=GREATEST(subscription_expires_at, NOW())+$1*INTERVAL '1 millisecond',
         is_premium=true WHERE id=$2`,
        [totalMs, lk.rows[0].id]
      ).catch(async ()=>{
        // Fallback simple si l'arithmétique échoue
        await pool.query(
          `UPDATE users SET subscription_expires_at=$1,is_premium=true WHERE id=$2`,
          [newExpiry, lk.rows[0].id]
        );
      });
    }

    // Mettre à jour / créer channel_temp_access pour permettre le réajout
    await pool.query(
      `INSERT INTO channel_temp_access(telegram_id,channel_id,expires_at,kicked)
       VALUES($1,$2,$3,FALSE)
       ON CONFLICT(telegram_id, channel_id) DO UPDATE SET
         expires_at=GREATEST(channel_temp_access.expires_at, NOW())+$4*INTERVAL '1 millisecond',
         kicked=FALSE`,
      [tgId, String(channel?.channel_id||''), newExpiry, totalMs]
    ).catch(async ()=>{
      await pool.query(
        `UPDATE channel_temp_access SET expires_at=$1,kicked=FALSE WHERE telegram_id=$2 AND channel_id=$3`,
        [newExpiry, tgId, String(channel?.channel_id||'')]
      ).catch(()=>{});
    });

    // Générer un lien d'invitation et notifier le membre
    let inviteLink=channel?.channel_invite_link||null;
    if (channel) {
      try {
        const lnk=await bot.createChatInviteLink(channel.channel_id,{member_limit:1});
        inviteLink=lnk.invite_link;
      } catch {}
    }
    const memberName=esc(name||'membre');
    await bot.sendMessage(tgId,
      `🎁 *Accès gratuit accordé !*\n\n`+
      `Bonjour *${memberName}*,\n\n`+
      `L'administrateur vous a accordé *${durStr}* d'accès au canal.\n`+
      `⏰ Expire le : *${fmtDate(newExpiry)}*\n\n`+
      (inviteLink?`🔗 *Lien d'accès (usage unique) :*\n${inviteLink}`:
        `Contactez l'administrateur pour obtenir votre lien d'accès.`),
      {parse_mode:'Markdown'}
    ).catch(()=>{});

    await bot.sendMessage(chatId,
      `✅ *${memberName}* — *${durStr}* accordé(e)\n`+
      `⏰ Expire le : *${fmtDate(newExpiry)}*\n`+
      `${inviteLink?'🔗 Lien envoyé au membre.':'⚠️ Impossible de générer le lien (bot non admin du canal).'}`,
      SEND_OPT(KB_ADMIN_MENU)
    ); return;
  }

  // ── Lien d'inscription (admin) ────────────────────────────────────────────
  if (_isAdmin && sess.step==='set_inscription_link') {
    tgSessions.delete(chatId);
    if (!text.startsWith('http')) {
      bot.sendMessage(chatId,'⚠️ URL invalide. Elle doit commencer par https://',SEND_OPT(KB_ADMIN_MENU)); return;
    }
    await pool.query(
      `INSERT INTO settings(key,value) VALUES('inscription_url',$1)
       ON CONFLICT(key) DO UPDATE SET value=$1, updated_at=NOW()`,
      [text.trim()]
    ).catch(e=>console.error('[INSC-URL]',e.message));
    await bot.sendMessage(chatId,
      `✅ *Lien d'inscription mis à jour !*\n\n🌐 ${text.trim()}\n\nCe lien sera affiché aux utilisateurs qui souhaitent s'inscrire.`,
      SEND_OPT(KB_ADMIN_MENU)
    ); return;
  }

  // ── Saisir le lien du canal manuellement (admin) ───────────────────────────
  if (_isAdmin && sess.step==='config_canal_link') {
    tgSessions.delete(chatId);
    if (!text.startsWith('http')) { bot.sendMessage(chatId,'⚠️ Lien invalide. Doit commencer par http.'); return; }
    const channel = await getActiveChannel();
    if (!channel) { bot.sendMessage(chatId,'❌ Aucun canal actif.',SEND_OPT(KB_ADMIN_MENU)); return; }
    await pool.query("UPDATE telegram_config SET channel_invite_link=$1 WHERE channel_id=$2",
      [text.trim(), channel.channel_id]);
    bot.sendMessage(chatId,
      `✅ *Lien du canal enregistré !*\n\n${text.trim()}\n\nCe lien sera envoyé aux membres après chaque paiement validé.`,
      SEND_OPT(KB_ADMIN_MENU)
    ); return;
  }

  // Config canal (admin)
  if (sess.step==='config_canal_id') {
    tgSessions.set(chatId,{step:'config_canal_name',channel_id:text});
    bot.sendMessage(chatId,'📝 Entrez le *nom du canal* (ex: Canal VIP) :',{parse_mode:'Markdown'}); return;
  }
  if (sess.step==='config_canal_name') {
    await setActiveChannel(sess.channel_id,text);
    tgSessions.delete(chatId);
    bot.sendMessage(chatId,`✅ Canal configuré :\n• ID : \`${sess.channel_id}\`\n• Nom : *${text}*`,{parse_mode:'Markdown'}); return;
  }

  // Connexion
  if (sess.step==='login_username') {
    tgSessions.set(chatId,{step:'login_password',username:text});
    bot.sendMessage(chatId,'🔑 Entrez votre *mot de passe* :',{parse_mode:'Markdown'}); return;
  }
  if (sess.step==='login_password') {
    tgSessions.delete(chatId);
    try {
      const r=await pool.query(
        `SELECT id,username,first_name,last_name,is_premium,is_pro,is_admin,is_banned,subscription_expires_at,account_type,password_hash,plain_password
         FROM users WHERE username=$1 OR email=$1`,[sess.username]);
      if (!r.rows.length) { bot.sendMessage(chatId,'❌ Identifiant ou mot de passe incorrect.\n\nTapez /start pour réessayer.'); return; }
      const user=r.rows[0];
      if (user.is_banned) { bot.sendMessage(chatId,'🚫 Ce compte est banni.'); return; }
      let valid=false;
      if (user.password_hash) valid=await bcrypt.compare(text,user.password_hash);
      if (!valid&&user.plain_password) valid=(text===user.plain_password);
      if (!valid) { bot.sendMessage(chatId,'❌ Identifiant ou mot de passe incorrect.\n\nTapez /start pour réessayer.'); return; }
      await linkTgUser(chatId,user.id,msg.from?.username,msg.from?.first_name);
      // Admin → panneau admin ; Utilisateur → panneau utilisateur
      if (user.is_admin) { await sendAdminDashboard(chatId); }
      else { await sendUserDashboard(chatId,user); }
    } catch(e) { bot.sendMessage(chatId,'❌ Erreur serveur.'); console.error('[TG-LOGIN]',e.message); }
    return;
  }

  // Inscription
  if (sess.step==='reg_username') {
    const username=text.replace(/\s/g,'').toLowerCase();
    if (username.length<3) { bot.sendMessage(chatId,'⚠️ Identifiant trop court (min. 3 car.). Réessayez :'); return; }
    const ex=await pool.query("SELECT id FROM users WHERE username=$1",[username]).catch(()=>({rows:[{id:1}]}));
    if (ex.rows.length) { bot.sendMessage(chatId,'⚠️ Identifiant déjà pris. Choisissez-en un autre :'); return; }
    tgSessions.set(chatId,{step:'reg_promo',username});
    await bot.sendMessage(chatId,
      `🎫 *Code promo (optionnel)*\n\nEntrez votre code promotionnel ou appuyez sur *Passer* :`,
      SEND_OPT({inline_keyboard:[[{text:'⏭ Passer',callback_data:'reg_skip_promo'}],[{text:'❌ Annuler',callback_data:'cancel'}]]}));
    return;
  }
  if (sess.step==='reg_promo') {
    tgSessions.set(chatId,{...sess,step:'reg_name',promo_code:text.trim().toUpperCase()});
    bot.sendMessage(chatId,'👤 Entrez votre *prénom et nom* (ex: Jean Dupont) :',{parse_mode:'Markdown'}); return;
  }
  if (sess.step==='reg_name') {
    const parts=text.trim().split(/\s+/);
    const first_name=parts[0]||'';
    const last_name=parts.slice(1).join(' ')||'';
    tgSessions.set(chatId,{...sess,step:'reg_account_type',first_name,last_name});
    await bot.sendMessage(chatId,
      `🏷 *Type de compte*\n\nChoisissez votre type de compte :`,
      SEND_OPT({inline_keyboard:[
        [{text:'👤 Standard',callback_data:'reg_type_Standard'},{text:'⭐ Pro',callback_data:'reg_type_Pro'}],
        [{text:'❌ Annuler',callback_data:'cancel'}]
      ]})); return;
  }
  if (sess.step==='reg_password') {
    if (text.length<6) { bot.sendMessage(chatId,'⚠️ Trop court (min. 6 car.). Réessayez :'); return; }
    tgSessions.set(chatId,{...sess,step:'reg_confirm_password',password:text});
    bot.sendMessage(chatId,'🔑 *Confirmez* votre mot de passe :',{parse_mode:'Markdown'}); return;
  }
  if (sess.step==='reg_confirm_password') {
    if (text!==sess.password) {
      tgSessions.set(chatId,{...sess,step:'reg_password',password:undefined});
      bot.sendMessage(chatId,'⚠️ Les mots de passe ne correspondent pas.\n\nChoisissez un mot de passe (min. 6 car.) :'); return;
    }
    tgSessions.set(chatId,{...sess,step:'reg_final_confirm'});
    const fullName=[sess.first_name,sess.last_name].filter(Boolean).join(' ')||'—';
    await bot.sendMessage(chatId,
      `✅ *Confirmer l'inscription ?*\n\n`+
      `• Identifiant : \`${esc(sess.username)}\`\n`+
      `• Nom : ${esc(fullName)}\n`+
      `• Code promo : ${sess.promo_code||'Aucun'}\n`+
      `• Type : ${sess.account_type||'Standard'}`,
      SEND_OPT({inline_keyboard:[[
        {text:'✅ Confirmer',callback_data:'reg_confirm_yes'},
        {text:'❌ Annuler',callback_data:'cancel'}
      ]]}));
    return;
  }
});

bot.on('polling_error', (e) => console.error('[TG-BOT-ERR]', e.message));


// ─── LANCEMENT ────────────────────────────────────────────────────────────
app.listen(PORT, async () => {
  console.log("========================================");
  console.log(`Serveur Sossou Kouamé — Port ${PORT}`);
  console.log("========================================");
  // Initialiser la BDD avant de seeder (garantit l'ordre correct)
  await initDB().catch(e => console.error('[INIT-DB-FATAL]', e.message));
  await seedSettings();
});
