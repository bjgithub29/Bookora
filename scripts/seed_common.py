"""
Shared safety helpers for the Bookora seed scripts.

seed_movies.py and seed_shows.py are DEVELOPMENT / INITIAL-SEEDING tools: they
delete whole tables and rebuild demo data. Because `movies` and `shows` cascade
into `bookings`, running either one against a live database destroys real
customer bookings. Everything in this module exists to make that impossible by
accident:

  * connection settings come from the environment (the same variable names
    app.py uses), never from literals in the seed scripts;
  * the target server/database is printed before anything is touched;
  * a database that already contains bookings is refused outright;
  * the DELETEs need the database name typed out to proceed.
"""
import os
import sys

# Reconfigure stdout/stderr before anything prints. Windows consoles default to
# cp1252, which cannot encode the emoji in these scripts' progress output; the
# resulting UnicodeEncodeError used to abort a seed run halfway, after the
# DELETEs and before the commit. errors='replace' degrades a character at worst.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError, OSError):  # pragma: no cover
        pass

# Ensure project root is on sys.path when executed directly
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import mysql.connector
from dotenv import load_dotenv

load_dotenv(os.path.join(_PROJECT_ROOT, '.env'))


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def db_config():
    """Connection settings, read from the same env vars as app.py.

    The localhost/root defaults are a development convenience; a hosted
    database is configured through .env or the platform's environment, so no
    production credential is ever written into a source file.
    """
    config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': int(os.getenv('DB_PORT', '3306')),
        'user': os.getenv('DB_USER', 'root'),
        'password': os.getenv('DB_PASSWORD', ''),
        'database': os.getenv('DB_NAME', 'bookora'),
        'charset': 'utf8mb4',
    }

    ssl_ca = os.getenv('DB_SSL_CA')
    if ssl_ca:
        config['ssl_ca'] = ssl_ca
        config['ssl_verify_cert'] = _env_bool('DB_SSL_VERIFY_CERT', True)
    elif _env_bool('DB_SSL_DISABLED', False):
        config['ssl_disabled'] = True

    return config


def print_banner(title):
    line = '=' * 66
    print(line)
    print(f"  {title}")
    print("  DEVELOPMENT / INITIAL-SEEDING TOOL - it deletes rows.")
    print("  Intended run order:")
    print("    1. database/database_schema.sql   2. scripts/seed_movies.py   3. scripts/seed_shows.py")
    print(line)


def connect():
    """Open the seed connection and show which server it points at.

    Printing the target is the whole point of the confirmation below: the
    password is never printed, but you do need to see which host and database
    you are about to rewrite.
    """
    config = db_config()
    print(f"Target: {config['user']}@{config['host']}:{config['port']}/{config['database']}")
    if 'ssl_ca' in config:
        print("TLS:    enabled (DB_SSL_CA)")
    return mysql.connector.connect(**config)


def count_bookings(conn):
    """Number of rows in `bookings`, or exit with advice if the schema is absent."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM bookings")
        return int(cursor.fetchone()[0])
    except mysql.connector.Error as exc:
        print(f"\n❌ Could not read the bookings table: {getattr(exc, 'msg', exc)}")
        print("   Load database/database_schema.sql into this database first.")
        sys.exit(1)
    finally:
        cursor.close()


def require_destructive_confirmation(conn, what):
    """Gate the DELETEs in the seed scripts. Exits the process if not confirmed.

    A database holding bookings is treated as real data and refused: only
    --force-destroy-bookings overrides that, and it still has to be confirmed
    interactively. --yes skips the typing when there is nothing to lose, so CI
    or a first-time setup script can seed an empty database unattended.
    """
    database = db_config()['database']
    assume_yes = '--yes' in sys.argv or '-y' in sys.argv
    force = '--force-destroy-bookings' in sys.argv

    bookings = count_bookings(conn)
    print(f"\nAbout to delete: {what}")
    print(f"Bookings currently in '{database}': {bookings}")

    if bookings and not force:
        print("\n❌ Refusing to run. This database contains bookings, so it is not an")
        print("   empty development database, and seeding would cascade-delete them.")
        print("   If it really is a throwaway database, re-run with:")
        print("       --force-destroy-bookings")
        print("   (you will still have to confirm interactively).")
        sys.exit(1)

    if bookings:
        print(f"\n⚠️  --force-destroy-bookings will PERMANENTLY DELETE {bookings} booking(s).")
    elif assume_yes:
        print("--yes given and no bookings present - continuing without a prompt.")
        return

    if not sys.stdin or not sys.stdin.isatty():
        print("\n❌ Refusing to run: confirmation is required but stdin is not a terminal.")
        print("   Re-run in a terminal, or pass --yes on an empty database.")
        sys.exit(1)

    try:
        answer = input(f"Type the database name ('{database}') to continue: ").strip()
    except EOFError:
        # Windows reports NUL as a character device, so the isatty() check above
        # can pass even with no real input attached. Refuse cleanly instead of
        # dying with a traceback.
        print("\n❌ Refusing to run: no input available to confirm with.")
        sys.exit(1)
    if answer != database:
        print("❌ Confirmation did not match. Nothing was changed.")
        sys.exit(1)
