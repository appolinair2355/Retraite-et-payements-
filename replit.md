# Sossou Kouamé — Paiement en Ligne

Mobile Money & Crypto payment page powered by the [Money Fusion](https://pay.moneyfusion.net) API.

## Stack

- **Runtime:** Node.js 18
- **Framework:** Express 4
- **Frontend:** Vanilla HTML/CSS/JS (static files served by Express)
- **Payment provider:** Money Fusion

## How to run

```bash
npm start
```

The server starts on port 5000. The workflow **Start application** (`npm start`) is pre-configured.

## Project structure

| File | Purpose |
|------|---------|
| `server.js` | Express backend — proxies requests to Money Fusion API |
| `index.html` | Payment form (Mobile Money & Crypto) |
| `style.css` | Styles |
| `script.js` | Frontend logic |
| `success.html` | Payment success/confirmation page |

## Environment secrets

| Key | Purpose |
|-----|---------|
| `DATABASE_URL` | PostgreSQL connection string (e.g. `postgresql://user:pass@host/db`) |
| `SESSION_SECRET` | Secret used to sign session cookies |
| `MONEY_FUSION_API_KEY` | Money Fusion API key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for notifications |
| `GMAIL_USER` | Gmail address used to send confirmation emails |
| `GMAIL_PASS` | Gmail app password for the above account |
| `ADMIN_EMAIL` | Email address that receives admin/failure alerts |

## API routes

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/create-payment` | Initiate a payment via Money Fusion |
| `GET` | `/api/payment-status/:token` | Check payment status |
| `POST` | `/webhook` | Receive real-time payment notifications |
| `GET` | `/my-ip` | Get server IP (for Money Fusion IP whitelist) |

## Notes

- The API key is read from `process.env.MONEY_FUSION_API_KEY` — never hardcode it.
- The Money Fusion dashboard requires your server's IP to be whitelisted. Visit `/my-ip` to get it.
- `logo-sk.png` is not included in the repo — add it to the project root to display the logo.

## User preferences

<!-- Record any preferences the user explicitly asks to remember here -->
