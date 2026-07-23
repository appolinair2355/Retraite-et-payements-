"""
Crée (ou met à jour) le compte administrateur dans la base de données.

Usage:
    python seed_admin.py

Le compte créé :
    Identifiant : sossoukouam
    Mot de passe : arrow2026
"""
import asyncio
import asyncpg
import bcrypt
import os
import sys

DATABASE_URL = os.getenv("DATABASE_URL", "")

ADMIN_USERNAME  = "sossoukouam"
ADMIN_PASSWORD  = "arrow2026"
ADMIN_FIRST     = "Sossou"
ADMIN_LAST      = "Kouamé"


async def main():
    if not DATABASE_URL:
        print("❌ DATABASE_URL non défini. Assurez-vous que le secret est configuré.")
        sys.exit(1)

    print("⏳ Connexion à la base de données...")
    pool = await asyncpg.create_pool(DATABASE_URL, ssl="require", min_size=1, max_size=2)

    async with pool.acquire() as conn:
        # Créer la table si absente
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(120) UNIQUE NOT NULL,
                email    VARCHAR(120) UNIQUE,
                password_hash VARCHAR(256) NOT NULL,
                first_name TEXT,
                last_name  TEXT,
                is_admin    BOOLEAN DEFAULT FALSE,
                is_approved BOOLEAN DEFAULT FALSE,
                is_premium  BOOLEAN DEFAULT FALSE,
                subscription_expires_at    TIMESTAMPTZ,
                subscription_duration_minutes INTEGER,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS plain_password TEXT;
            CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_id_uniq
                ON users(telegram_id) WHERE telegram_id IS NOT NULL;
        """)

        pw_hash = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()

        row = await conn.fetchrow("""
            INSERT INTO users
                (username, email, password_hash, first_name, last_name,
                 is_admin, is_approved, plain_password)
            VALUES ($1, $2, $3, $4, $5, TRUE, TRUE, $6)
            ON CONFLICT (username) DO UPDATE
                SET password_hash  = EXCLUDED.password_hash,
                    plain_password = EXCLUDED.plain_password,
                    is_admin       = TRUE,
                    is_approved    = TRUE,
                    first_name     = EXCLUDED.first_name,
                    last_name      = EXCLUDED.last_name
            RETURNING id, username, is_admin
        """, ADMIN_USERNAME, ADMIN_USERNAME, pw_hash,
             ADMIN_FIRST, ADMIN_LAST, ADMIN_PASSWORD)

        print("═" * 50)
        print("✅  Compte administrateur créé / mis à jour")
        print(f"   ID DB     : {row['id']}")
        print(f"   Identifiant: {row['username']}")
        print(f"   Mot de passe: {ADMIN_PASSWORD}")
        print(f"   is_admin  : {row['is_admin']}")
        print("═" * 50)
        print()
        print("Étapes suivantes :")
        print("  1. Ouvrez le bot Telegram → /start")
        print("  2. Cliquez sur 🔐 Se connecter")
        print("  3. Identifiant : sossoukouam")
        print("  4. Mot de passe : arrow2026")
        print("  → Vous verrez le panneau d'administration")

    await pool.close()


asyncio.run(main())
