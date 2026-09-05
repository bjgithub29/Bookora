"""Command entry point for the deployed daily Bookora show-maintenance job.

Run from the project root after applying the scheduling migration:

    python scripts/run_show_maintenance.py

This command creates missing instances only.  It does not invoke either seed
script and it never deletes historical data.
"""
import os
import sys

# Ensure project root is on sys.path when executed directly
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import mysql.connector
from dotenv import load_dotenv

from services.show_maintenance import maintain_upcoming_shows

load_dotenv(os.path.join(_PROJECT_ROOT, '.env'))


def _required(name):
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f'{name} is required for show maintenance.')
    return value


def db_config():
    """Production-only connection configuration; values are never printed."""
    config = {
        'host': _required('DB_HOST'),
        'port': int(os.getenv('DB_PORT', '3306')),
        'user': _required('DB_USER'),
        'password': os.getenv('DB_PASSWORD', ''),
        'database': _required('DB_NAME'),
        'charset': 'utf8mb4',
    }
    ssl_ca = os.getenv('DB_SSL_CA')
    if ssl_ca:
        config['ssl_ca'] = ssl_ca
        config['ssl_verify_cert'] = os.getenv('DB_SSL_VERIFY_CERT', 'true').lower() in ('1', 'true', 'yes', 'on')
    return config


def main():
    conn = mysql.connector.connect(**db_config())
    cursor = conn.cursor()
    try:
        # A database advisory lock prevents two scheduler invocations from doing
        # needless concurrent work.  Schema uniqueness is still the final guard.
        cursor.execute("SELECT GET_LOCK('bookora_show_maintenance', 0)")
        if cursor.fetchone()[0] != 1:
            print('Show maintenance skipped: another run is already active.')
            return 0
        result = maintain_upcoming_shows(conn)
        print(
            'Show maintenance complete: '
            f"{result['created_shows']} show(s), {result['created_seats']} seat(s) created "
            f"for {result['today']} through {result['horizon']}."
        )
        return 0
    finally:
        try:
            cursor.execute("SELECT RELEASE_LOCK('bookora_show_maintenance')")
            cursor.fetchone()
        except Exception:
            pass
        cursor.close()
        conn.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        # Do not print connector configuration (which could include secrets).
        print(f'Show maintenance failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
