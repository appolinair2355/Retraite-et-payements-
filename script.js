// ============================================
// SOSSOU KOUAMÉ — Paiement en Ligne
// Frontend appelle le serveur backend, pas Money Fusion directement
// ============================================

// ─── CONFIGURATION ─────────────────────────────────────────────────────────
// L'URL de TON serveur (Render ou local)
const SERVER_URL = window.location.origin; // Auto-detect: https://ton-site.onrender.com ou http://localhost:3000

// ─── TOUS LES PAYS DU MONDE ──────────────────────────────────────────────
const COUNTRIES = {
  "bj": { name: "Bénin", flag: "🇧🇯", code: "+229", currency: "XOF",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "moov", name: "Moov", color: "#FF6600", textColor: "#fff" },
      { key: "celtiis", name: "Celtiis", color: "#00A859", textColor: "#fff" }
    ]
  },
  "ci": { name: "Côte d'Ivoire", flag: "🇨🇮", code: "+225", currency: "XOF",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "moov", name: "Moov", color: "#0066CC", textColor: "#fff" },
      { key: "wave", name: "Wave", color: "#1CE5BD", textColor: "#000" }
    ]
  },
  "bf": { name: "Burkina Faso", flag: "🇧🇫", code: "+226", currency: "XOF",
    networks: [
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "moov", name: "Moov", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "tg": { name: "Togo", flag: "🇹🇬", code: "+228", currency: "XOF",
    networks: [
      { key: "tmoney", name: "T-Money", color: "#0066CC", textColor: "#fff" },
      { key: "moov", name: "Moov", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "sn": { name: "Sénégal", flag: "🇸🇳", code: "+221", currency: "XOF",
    networks: [
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "wave", name: "Wave", color: "#1CE5BD", textColor: "#000" },
      { key: "free", name: "Free", color: "#DA291C", textColor: "#fff" }
    ]
  },
  "ml": { name: "Mali", flag: "🇲🇱", code: "+223", currency: "XOF",
    networks: [
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "moov", name: "Moov", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "gh": { name: "Ghana", flag: "🇬🇭", code: "+233", currency: "GHS",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "airteltigo", name: "AirtelTigo", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "ng": { name: "Nigeria", flag: "🇳🇬", code: "+234", currency: "NGN",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" },
      { key: "glo", name: "Glo", color: "#00A859", textColor: "#fff" },
      { key: "9mobile", name: "9mobile", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "cm": { name: "Cameroun", flag: "🇨🇲", code: "+237", currency: "XAF",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "ga": { name: "Gabon", flag: "🇬🇦", code: "+241", currency: "XAF",
    networks: [
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" }
    ]
  },
  "cg": { name: "Congo", flag: "🇨🇬", code: "+242", currency: "XAF",
    networks: [
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" },
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" }
    ]
  },
  "cd": { name: "RDC", flag: "🇨🇩", code: "+243", currency: "CDF",
    networks: [
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "vodacom", name: "Vodacom", color: "#E60000", textColor: "#fff" }
    ]
  },
  "rw": { name: "Rwanda", flag: "🇷🇼", code: "+250", currency: "RWF",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" }
    ]
  },
  "bi": { name: "Burundi", flag: "🇧🇮", code: "+257", currency: "BIF",
    networks: [
      { key: "lumicash", name: "Lumicash", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "tz": { name: "Tanzanie", flag: "🇹🇿", code: "+255", currency: "TZS",
    networks: [
      { key: "mpesa", name: "M-Pesa", color: "#00A859", textColor: "#fff" },
      { key: "tigopesa", name: "Tigo Pesa", color: "#0066CC", textColor: "#fff" },
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" }
    ]
  },
  "ke": { name: "Kenya", flag: "🇰🇪", code: "+254", currency: "KES",
    networks: [
      { key: "mpesa", name: "M-Pesa", color: "#00A859", textColor: "#fff" },
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" }
    ]
  },
  "ug": { name: "Ouganda", flag: "🇺🇬", code: "+256", currency: "UGX",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" }
    ]
  },
  "et": { name: "Éthiopie", flag: "🇪🇹", code: "+251", currency: "ETB",
    networks: [
      { key: "telebirr", name: "Telebirr", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "za": { name: "Afrique du Sud", flag: "🇿🇦", code: "+27", currency: "ZAR",
    networks: [
      { key: "vodapay", name: "Vodapay", color: "#E60000", textColor: "#fff" }
    ]
  },
  "zm": { name: "Zambie", flag: "🇿🇲", code: "+260", currency: "ZMW",
    networks: [
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" },
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" }
    ]
  },
  "zw": { name: "Zimbabwe", flag: "🇿🇼", code: "+263", currency: "ZWL",
    networks: [
      { key: "ecocash", name: "EcoCash", color: "#00A859", textColor: "#fff" }
    ]
  },
  "mz": { name: "Mozambique", flag: "🇲🇿", code: "+258", currency: "MZN",
    networks: [
      { key: "mpesa", name: "M-Pesa", color: "#00A859", textColor: "#fff" },
      { key: "vodacom", name: "Vodacom", color: "#E60000", textColor: "#fff" }
    ]
  },
  "mg": { name: "Madagascar", flag: "🇲🇬", code: "+261", currency: "MGA",
    networks: [
      { key: "mvola", name: "MVola", color: "#FF6600", textColor: "#fff" },
      { key: "airtel", name: "Airtel", color: "#E60000", textColor: "#fff" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "ma": { name: "Maroc", flag: "🇲🇦", code: "+212", currency: "MAD",
    networks: [
      { key: "inwi", name: "Inwi", color: "#FF6600", textColor: "#fff" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "iam", name: "IAM", color: "#E60000", textColor: "#fff" }
    ]
  },
  "dz": { name: "Algérie", flag: "🇩🇿", code: "+213", currency: "DZD",
    networks: [
      { key: "djezzy", name: "Djezzy", color: "#E60000", textColor: "#fff" },
      { key: "ooredoo", name: "Ooredoo", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "tn": { name: "Tunisie", flag: "🇹🇳", code: "+216", currency: "TND",
    networks: [
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "ooredoo", name: "Ooredoo", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "eg": { name: "Égypte", flag: "🇪🇬", code: "+20", currency: "EGP",
    networks: [
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "etisalat", name: "Etisalat", color: "#00A859", textColor: "#fff" },
      { key: "we", name: "WE", color: "#9B59B6", textColor: "#fff" }
    ]
  },
  "ly": { name: "Libye", flag: "🇱🇾", code: "+218", currency: "LYD",
    networks: [
      { key: "madar", name: "Madar", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "sd": { name: "Soudan", flag: "🇸🇩", code: "+249", currency: "SDG",
    networks: [
      { key: "zain", name: "Zain", color: "#E60000", textColor: "#fff" },
      { key: "mtn", name: "MTN", color: "#FFCC00", textColor: "#000" }
    ]
  },
  "fr": { name: "France", flag: "🇫🇷", code: "+33", currency: "EUR",
    networks: [
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "sfr", name: "SFR", color: "#E60000", textColor: "#fff" },
      { key: "bouygues", name: "Bouygues", color: "#0066CC", textColor: "#fff" },
      { key: "free", name: "Free", color: "#DA291C", textColor: "#fff" }
    ]
  },
  "gb": { name: "Royaume-Uni", flag: "🇬🇧", code: "+44", currency: "GBP",
    networks: [
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "o2", name: "O2", color: "#0066CC", textColor: "#fff" },
      { key: "three", name: "Three", color: "#00A859", textColor: "#fff" },
      { key: "ee", name: "EE", color: "#FFCC00", textColor: "#000" }
    ]
  },
  "de": { name: "Allemagne", flag: "🇩🇪", code: "+49", currency: "EUR",
    networks: [
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "telekom", name: "Telekom", color: "#E60000", textColor: "#fff" },
      { key: "o2", name: "O2", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "es": { name: "Espagne", flag: "🇪🇸", code: "+34", currency: "EUR",
    networks: [
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "movistar", name: "Movistar", color: "#00A859", textColor: "#fff" }
    ]
  },
  "it": { name: "Italie", flag: "🇮🇹", code: "+39", currency: "EUR",
    networks: [
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "tim", name: "TIM", color: "#0066CC", textColor: "#fff" },
      { key: "windtre", name: "WindTre", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "pt": { name: "Portugal", flag: "🇵🇹", code: "+351", currency: "EUR",
    networks: [
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "meo", name: "MEO", color: "#00A859", textColor: "#fff" },
      { key: "nos", name: "NOS", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "nl": { name: "Pays-Bas", flag: "🇳🇱", code: "+31", currency: "EUR",
    networks: [
      { key: "vodafone", name: "Vodafone", color: "#E60000", textColor: "#fff" },
      { key: "kpn", name: "KPN", color: "#0066CC", textColor: "#fff" },
      { key: "tmobile", name: "T-Mobile", color: "#E60000", textColor: "#fff" }
    ]
  },
  "be": { name: "Belgique", flag: "🇧🇪", code: "+32", currency: "EUR",
    networks: [
      { key: "proximus", name: "Proximus", color: "#0066CC", textColor: "#fff" },
      { key: "orange", name: "Orange", color: "#FF6600", textColor: "#fff" },
      { key: "base", name: "Base", color: "#E60000", textColor: "#fff" }
    ]
  },
  "ch": { name: "Suisse", flag: "🇨🇭", code: "+41", currency: "CHF",
    networks: [
      { key: "swisscom", name: "Swisscom", color: "#0066CC", textColor: "#fff" },
      { key: "sunrise", name: "Sunrise", color: "#FF6600", textColor: "#fff" },
      { key: "salt", name: "Salt", color: "#E60000", textColor: "#fff" }
    ]
  },
  "us": { name: "États-Unis", flag: "🇺🇸", code: "+1", currency: "USD",
    networks: [
      { key: "venmo", name: "Venmo", color: "#3D95CE", textColor: "#fff" },
      { key: "cashapp", name: "Cash App", color: "#00D632", textColor: "#000" },
      { key: "zelle", name: "Zelle", color: "#6B1FA9", textColor: "#fff" }
    ]
  },
  "ca": { name: "Canada", flag: "🇨🇦", code: "+1", currency: "CAD",
    networks: [
      { key: "interac", name: "Interac", color: "#FFCC00", textColor: "#000" }
    ]
  },
  "br": { name: "Brésil", flag: "🇧🇷", code: "+55", currency: "BRL",
    networks: [
      { key: "pix", name: "PIX", color: "#00A859", textColor: "#fff" },
      { key: "mercadopago", name: "Mercado Pago", color: "#00A3E0", textColor: "#fff" }
    ]
  },
  "mx": { name: "Mexique", flag: "🇲🇽", code: "+52", currency: "MXN",
    networks: [
      { key: "oxxo", name: "OXXO", color: "#FFCC00", textColor: "#000" },
      { key: "spei", name: "SPEI", color: "#E60000", textColor: "#fff" }
    ]
  },
  "co": { name: "Colombie", flag: "🇨🇴", code: "+57", currency: "COP",
    networks: [
      { key: "nequi", name: "Nequi", color: "#FF6600", textColor: "#fff" },
      { key: "daviplata", name: "Daviplata", color: "#E60000", textColor: "#fff" }
    ]
  },
  "ar": { name: "Argentine", flag: "🇦🇷", code: "+54", currency: "ARS",
    networks: [
      { key: "mercadopago", name: "Mercado Pago", color: "#00A3E0", textColor: "#fff" }
    ]
  },
  "cl": { name: "Chili", flag: "🇨🇱", code: "+56", currency: "CLP",
    networks: [
      { key: "mercadopago", name: "Mercado Pago", color: "#00A3E0", textColor: "#fff" }
    ]
  },
  "pe": { name: "Pérou", flag: "🇵🇪", code: "+51", currency: "PEN",
    networks: [
      { key: "yape", name: "Yape", color: "#6B1FA9", textColor: "#fff" },
      { key: "plin", name: "Plin", color: "#E60000", textColor: "#fff" }
    ]
  },
  "cn": { name: "Chine", flag: "🇨🇳", code: "+86", currency: "CNY",
    networks: [
      { key: "alipay", name: "Alipay", color: "#1677FF", textColor: "#fff" },
      { key: "wechat", name: "WeChat Pay", color: "#07C160", textColor: "#fff" }
    ]
  },
  "in": { name: "Inde", flag: "🇮🇳", code: "+91", currency: "INR",
    networks: [
      { key: "paytm", name: "Paytm", color: "#00BDF2", textColor: "#fff" },
      { key: "phonepe", name: "PhonePe", color: "#6B1FA9", textColor: "#fff" },
      { key: "gpay", name: "Google Pay", color: "#4285F4", textColor: "#fff" },
      { key: "upi", name: "UPI", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "jp": { name: "Japon", flag: "🇯🇵", code: "+81", currency: "JPY",
    networks: [
      { key: "paypay", name: "PayPay", color: "#E60000", textColor: "#fff" },
      { key: "linepay", name: "LINE Pay", color: "#00B900", textColor: "#fff" }
    ]
  },
  "kr": { name: "Corée du Sud", flag: "🇰🇷", code: "+82", currency: "KRW",
    networks: [
      { key: "kakaopay", name: "KakaoPay", color: "#FFCC00", textColor: "#000" },
      { key: "toss", name: "Toss", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "id": { name: "Indonésie", flag: "🇮🇩", code: "+62", currency: "IDR",
    networks: [
      { key: "gopay", name: "GoPay", color: "#00A859", textColor: "#fff" },
      { key: "ovo", name: "OVO", color: "#6B1FA9", textColor: "#fff" },
      { key: "dana", name: "DANA", color: "#00A3E0", textColor: "#fff" }
    ]
  },
  "th": { name: "Thaïlande", flag: "🇹🇭", code: "+66", currency: "THB",
    networks: [
      { key: "promptpay", name: "PromptPay", color: "#0066CC", textColor: "#fff" },
      { key: "truemoney", name: "TrueMoney", color: "#E60000", textColor: "#fff" }
    ]
  },
  "vn": { name: "Vietnam", flag: "🇻🇳", code: "+84", currency: "VND",
    networks: [
      { key: "momo", name: "MoMo", color: "#E60000", textColor: "#fff" },
      { key: "zalopay", name: "ZaloPay", color: "#00A3E0", textColor: "#fff" },
      { key: "viettelpay", name: "ViettelPay", color: "#00A859", textColor: "#fff" }
    ]
  },
  "ph": { name: "Philippines", flag: "🇵🇭", code: "+63", currency: "PHP",
    networks: [
      { key: "gcash", name: "GCash", color: "#0066CC", textColor: "#fff" },
      { key: "maya", name: "Maya", color: "#00A859", textColor: "#fff" },
      { key: "grabpay", name: "GrabPay", color: "#00B140", textColor: "#fff" }
    ]
  },
  "my": { name: "Malaisie", flag: "🇲🇾", code: "+60", currency: "MYR",
    networks: [
      { key: "touchngo", name: "Touch 'n Go", color: "#0066CC", textColor: "#fff" },
      { key: "grabpay", name: "GrabPay", color: "#00B140", textColor: "#fff" }
    ]
  },
  "sg": { name: "Singapour", flag: "🇸🇬", code: "+65", currency: "SGD",
    networks: [
      { key: "paynow", name: "PayNow", color: "#E60000", textColor: "#fff" },
      { key: "grabpay", name: "GrabPay", color: "#00B140", textColor: "#fff" }
    ]
  },
  "ae": { name: "Émirats Arabes Unis", flag: "🇦🇪", code: "+971", currency: "AED",
    networks: [
      { key: "applepay", name: "Apple Pay", color: "#000000", textColor: "#fff" }
    ]
  },
  "sa": { name: "Arabie Saoudite", flag: "🇸🇦", code: "+966", currency: "SAR",
    networks: [
      { key: "stcpay", name: "STC Pay", color: "#E60000", textColor: "#fff" },
      { key: "urpay", name: "Urway", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "qa": { name: "Qatar", flag: "🇶🇦", code: "+974", currency: "QAR",
    networks: [
      { key: "ooredoo", name: "Ooredoo", color: "#FF6600", textColor: "#fff" }
    ]
  },
  "kw": { name: "Koweït", flag: "🇰🇼", code: "+965", currency: "KWD",
    networks: [
      { key: "knet", name: "KNET", color: "#0066CC", textColor: "#fff" }
    ]
  },
  "au": { name: "Australie", flag: "🇦🇺", code: "+61", currency: "AUD",
    networks: [
      { key: "paypal", name: "PayPal", color: "#003087", textColor: "#fff" }
    ]
  },
  "nz": { name: "Nouvelle-Zélande", flag: "🇳🇿", code: "+64", currency: "NZD",
    networks: [
      { key: "paypal", name: "PayPal", color: "#003087", textColor: "#fff" }
    ]
  }
};

// ─── CRYPTO WALLETS ────────────────────────────────────────────────────────
const CRYPTO_WALLETS = [
  { id: "BTC", name: "Bitcoin", symbol: "BTC", icon: "₿", address: "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", min: "0.001 BTC" },
  { id: "ETH", name: "Ethereum", symbol: "ETH", icon: "Ξ", address: "0x71C7656EC7ab88b098defB751B7401B5f6d8976F", min: "0.01 ETH" },
  { id: "USDT_TRC20", name: "Tether (TRC20)", symbol: "USDT", icon: "₮", address: "T9zZ123xABCdef456GHIjkl789mnoPQRst", min: "10 USDT" },
  { id: "USDT_ERC20", name: "Tether (ERC20)", symbol: "USDT", icon: "₮", address: "0x71C7656EC7ab88b098defB751B7401B5f6d8976F", min: "10 USDT" },
  { id: "BNB", name: "BNB Smart Chain", symbol: "BNB", icon: "B", address: "bnb1xy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", min: "0.05 BNB" },
  { id: "SOL", name: "Solana", symbol: "SOL", icon: "S", address: "HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrH", min: "0.5 SOL" }
];

let selectedCountry = null;
let selectedNetwork = null;
let selectedCrypto = null;
let paymentMode = "mobile";

// ─── INITIALISATION ────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initMobileMenu();
  initScrollSpy();
  populateCountries();
  loadHistory();

  document.getElementById("countrySelect").addEventListener("change", onCountryChange);
  document.getElementById("phoneInput").addEventListener("input", checkFormComplete);
  document.getElementById("amountInput").addEventListener("input", checkFormComplete);
  document.getElementById("clientName").addEventListener("input", checkFormComplete);
});

// ─── UI ──────────────────────────────────────────────────────────────────
function initMobileMenu() {
  const btn = document.querySelector('.mobile-menu-btn');
  const menu = document.querySelector('.mobile-menu');
  btn.addEventListener('click', () => menu.classList.toggle('open'));
  document.querySelectorAll('.mobile-nav-link').forEach(link => {
    link.addEventListener('click', () => menu.classList.remove('open'));
  });
}

function initScrollSpy() {
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.nav-link');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id = entry.target.getAttribute('id');
        navLinks.forEach(link => {
          link.classList.toggle('active', link.getAttribute('href') === `#${id}`);
        });
      }
    });
  }, { rootMargin: '-40% 0px -40% 0px' });
  sections.forEach(sec => observer.observe(sec));
}

// ─── PAYMENT MODE ──────────────────────────────────────────────────────────
function selectPaymentMode(mode, element) {
  paymentMode = mode;
  document.querySelectorAll('.payment-mode-card').forEach(c => c.classList.remove('selected'));
  element.classList.add('selected');

  const countryGroup = document.getElementById('countryGroup');
  const networkGroup = document.getElementById('networkGroup');
  const phoneGroup = document.getElementById('phoneGroup');
  const cryptoGroup = document.getElementById('cryptoWalletsGroup');

  if (mode === 'mobile') {
    countryGroup.style.display = 'block';
    cryptoGroup.style.display = 'none';
    if (selectedCountry) {
      networkGroup.style.display = 'block';
      phoneGroup.style.display = 'block';
    }
  } else {
    countryGroup.style.display = 'none';
    networkGroup.style.display = 'none';
    phoneGroup.style.display = 'none';
    cryptoGroup.style.display = 'block';
    renderCryptoWallets();
  }
  checkFormComplete();
}

// ─── PAYS ────────────────────────────────────────────────────────────────
function populateCountries() {
  const select = document.getElementById("countrySelect");
  Object.entries(COUNTRIES).forEach(([key, country]) => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = `${country.flag} ${country.name}`;
    select.appendChild(opt);
  });
}

function onCountryChange(e) {
  const code = e.target.value;
  selectedCountry = COUNTRIES[code];
  if (!selectedCountry) return;

  document.getElementById("countryFlag").textContent = selectedCountry.flag;
  document.getElementById("countryCode").textContent = selectedCountry.code;
  document.getElementById("currencyLabel").textContent = selectedCountry.currency;

  renderNetworks(selectedCountry.networks);
  document.getElementById("networkGroup").style.display = "block";
  document.getElementById("phoneGroup").style.display = "block";
  document.getElementById("amountGroup").style.display = "block";
  document.getElementById("nameGroup").style.display = "block";
  document.getElementById("descGroup").style.display = "block";

  selectedNetwork = null;
  checkFormComplete();
}

function renderNetworks(networks) {
  const grid = document.getElementById("networkGrid");
  grid.innerHTML = "";
  networks.forEach(net => {
    const card = document.createElement("div");
    card.className = "network-card";
    card.dataset.key = net.key;
    card.innerHTML = `
      <div class="network-logo" style="background:${net.color};color:${net.textColor}">
        ${net.name.charAt(0)}
      </div>
      <span class="network-name">${net.name}</span>
    `;
    card.addEventListener("click", () => selectNetwork(net, card));
    grid.appendChild(card);
  });
}

function selectNetwork(network, cardElement) {
  selectedNetwork = network;
  document.querySelectorAll(".network-card").forEach(c => c.classList.remove("selected"));
  cardElement.classList.add("selected");
  checkFormComplete();
}

// ─── CRYPTO ──────────────────────────────────────────────────────────────
function renderCryptoWallets() {
  const grid = document.getElementById("cryptoGrid");
  grid.innerHTML = "";
  CRYPTO_WALLETS.forEach(wallet => {
    const card = document.createElement("div");
    card.className = "crypto-card";
    card.dataset.id = wallet.id;
    card.innerHTML = `
      <div class="crypto-icon">${wallet.icon}</div>
      <div class="crypto-info">
        <div class="crypto-name">${wallet.name}</div>
        <div class="crypto-symbol">${wallet.symbol}</div>
        <div class="crypto-address">${wallet.address}</div>
      </div>
    `;
    card.addEventListener("click", () => selectCrypto(wallet, card));
    grid.appendChild(card);
  });
}

function selectCrypto(wallet, cardElement) {
  selectedCrypto = wallet;
  document.querySelectorAll(".crypto-card").forEach(c => c.classList.remove("selected"));
  cardElement.classList.add("selected");
  document.getElementById("amountGroup").style.display = "block";
  document.getElementById("nameGroup").style.display = "block";
  document.getElementById("descGroup").style.display = "block";
  checkFormComplete();
}

// ─── FORM VALIDATION ─────────────────────────────────────────────────────
function checkFormComplete() {
  const amount = document.getElementById("amountInput").value;
  const name = document.getElementById("clientName").value.trim();
  const btn = document.getElementById("payBtn");

  let isComplete = false;

  if (paymentMode === "mobile") {
    const phone = document.getElementById("phoneInput").value.trim();
    isComplete = selectedNetwork && phone.length >= 8 && amount && parseInt(amount) >= 100 && name;
  } else {
    isComplete = selectedCrypto && amount && parseFloat(amount) > 0 && name;
  }

  btn.style.display = isComplete ? "flex" : "none";
}

// ─── PAIEMENT ────────────────────────────────────────────────────────────
function initiatePayment() {
  const btn = document.getElementById("payBtn");
  const btnText = document.getElementById("btnText");
  const btnLoader = document.getElementById("btnLoader");
  const resultDiv = document.getElementById("result");

  const amount = document.getElementById("amountInput").value;
  const name = document.getElementById("clientName").value.trim();
  const desc = document.getElementById("paymentDesc").value.trim() || "Paiement";

  btn.disabled = true;
  btnText.textContent = "Traitement...";
  btnLoader.classList.remove("hidden");
  resultDiv.classList.add("hidden");

  if (paymentMode === "mobile") {
    payMobileMoney(amount, name, desc);
  } else {
    payCrypto(amount, name, desc);
  }
}

// ─── MOBILE MONEY PAYMENT ────────────────────────────────────────────────
// Le frontend appelle TON SERVEUR, pas Money Fusion directement
function payMobileMoney(amount, name, desc) {
  const phone = document.getElementById("phoneInput").value.trim().replace(/\s/g, "");
  const fullPhone = selectedCountry.code + phone;
  const currency = selectedCountry.currency;

  const paymentData = {
    totalPrice: parseInt(amount),
    article: [{ [desc]: parseInt(amount) }],
    numeroSend: fullPhone,
    nomclient: name,
    return_url: window.location.origin + "/success.html?amount=" + amount + "&currency=" + currency + "&phone=" + encodeURIComponent(fullPhone) + "&name=" + encodeURIComponent(name) + "&network=" + encodeURIComponent(selectedNetwork.name),
  };

  // APPEL VERS TON SERVEUR (pas Money Fusion directement)
  fetch(SERVER_URL + "/api/create-payment", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(paymentData)
  })
  .then(res => res.json())
  .then(data => {
    if (data.statut === true || data.success === true) {
      saveToHistory({
        token: data.token || data.tokenPay,
        date: new Date().toISOString(),
        name: name,
        phone: fullPhone,
        amount: amount,
        currency: currency,
        network: selectedNetwork.name,
        country: selectedCountry.name,
        status: "pending",
        mode: "mobile"
      });

      if (data.url) {
        window.location.href = data.url;
      } else {
        showResult("success", "Paiement initié ! Token: " + (data.token || data.tokenPay));
      }
    } else {
      showResult("error", data.message || data.error || "Erreur lors du paiement");
    }
  })
  .catch(err => {
    console.error(err);
    showResult("error", "Erreur de connexion. Vérifiez que votre serveur est en ligne.");
  })
  .finally(() => {
    resetButton();
  });
}

// ─── CRYPTO PAYMENT ──────────────────────────────────────────────────────
function payCrypto(amount, name, desc) {
  showResult("success", `
    <h4>✅ Paiement Crypto</h4>
    <p>Envoyez <strong>${amount} ${selectedCrypto.symbol}</strong> à l'adresse :</p>
    <div class="token-box" onclick="copyToClipboard(this, '${selectedCrypto.address}')">${selectedCrypto.address}</div>
    <p style="font-size:0.85rem;color:var(--gray-600);">Minimum: ${selectedCrypto.min}</p>
    <p style="margin-top:12px;">Après le transfert, votre paiement sera validé.</p>
  `);

  saveToHistory({
    token: "CRYPTO-" + Date.now(),
    date: new Date().toISOString(),
    name: name,
    phone: selectedCrypto.address,
    amount: amount,
    currency: selectedCrypto.symbol,
    network: selectedCrypto.name,
    country: "Crypto",
    status: "pending",
    mode: "crypto"
  });

  resetButton();
}

// ─── UI HELPERS ──────────────────────────────────────────────────────────
function showResult(type, message) {
  const resultDiv = document.getElementById("result");
  resultDiv.className = "result-container result-" + type;
  resultDiv.innerHTML = message;
  resultDiv.classList.remove("hidden");
}

function resetButton() {
  const btn = document.getElementById("payBtn");
  const btnText = document.getElementById("btnText");
  const btnLoader = document.getElementById("btnLoader");
  btn.disabled = false;
  btnText.textContent = "Payer maintenant";
  btnLoader.classList.add("hidden");
}

function copyToClipboard(el, text) {
  navigator.clipboard.writeText(text).then(() => {
    el.classList.add("copied");
    const original = el.textContent;
    el.textContent = "Copié !";
    setTimeout(() => { el.textContent = original; el.classList.remove("copied"); }, 2000);
  }).catch(() => {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); document.body.removeChild(ta);
  });
}

// ─── HISTORIQUE ──────────────────────────────────────────────────────────
function saveToHistory(tx) {
  let history = JSON.parse(localStorage.getItem("sk_payment_history") || "[]");
  history.unshift(tx);
  localStorage.setItem("sk_payment_history", JSON.stringify(history));
  loadHistory();
}

function loadHistory() {
  const list = document.getElementById("historyList");
  const history = JSON.parse(localStorage.getItem("sk_payment_history") || "[]");

  if (history.length === 0) {
    list.innerHTML = `<div class="history-empty">Aucune transaction pour le moment</div>`;
    return;
  }

  list.innerHTML = history.map(tx => {
    const date = new Date(tx.date);
    const dateStr = date.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
    const timeStr = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    const statusClass = tx.status === "paid" || tx.status === "completed" ? "paid" : tx.status === "pending" ? "pending" : "failed";
    const statusLabel = tx.status === "paid" || tx.status === "completed" ? "Réussi" : tx.status === "pending" ? "En attente" : "Échoué";

    return `
      <div class="history-item">
        <span>${dateStr}<br><small style="color:var(--gray-400)">${timeStr}</small></span>
        <span style="font-family:monospace;font-size:0.75rem;word-break:break-all;">${tx.token.substring(0, 20)}...</span>
        <span>${tx.phone.substring(0, 15)}...</span>
        <span><strong>${tx.amount} ${tx.currency}</strong></span>
        <span><span class="status-dot ${statusClass}"></span>${statusLabel}</span>
      </div>
    `;
  }).join("");
}
