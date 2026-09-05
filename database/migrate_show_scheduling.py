"""Non-destructive, idempotent migration for Bookora show scheduling.

Back up the production database through its provider before running this once.
The script adds metadata and indexes only; it never deletes or rewrites rows.
It refuses to add the show-instance unique key if existing duplicate instances
would make that unsafe, and reports the duplicates for an operator to resolve.

Note: MySQL and MariaDB DDL statements (CREATE TABLE, ALTER TABLE) execute with
implicit commits and cannot be rolled back atomically. The migration is designed
to be strictly idempotent and safely re-runnable from any intermediate step.
"""
import os
import sys

# Ensure project root is on sys.path when executed directly
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import mysql.connector
from dotenv import load_dotenv

load_dotenv(os.path.join(_PROJECT_ROOT, '.env'))


def _required(name):
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f'{name} is required for this migration.')
    return value


def db_config():
    config = {
        'host': _required('DB_HOST'), 'port': int(os.getenv('DB_PORT', '3306')),
        'user': _required('DB_USER'), 'password': os.getenv('DB_PASSWORD', ''),
        'database': _required('DB_NAME'), 'charset': 'utf8mb4',
    }
    ssl_ca = os.getenv('DB_SSL_CA')
    if ssl_ca:
        config['ssl_ca'] = ssl_ca
        config['ssl_verify_cert'] = os.getenv('DB_SSL_VERIFY_CERT', 'true').lower() in ('1', 'true', 'yes', 'on')
    return config


def _column_exists(cursor, table, column):
    cursor.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (table, column),
    )
    return cursor.fetchone() is not None


def _index_exists(cursor, table, index):
    cursor.execute(
        """SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s""",
        (table, index),
    )
    return cursor.fetchone() is not None


def _foreign_key_exists(cursor, name):
    cursor.execute(
        """SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
           WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = %s
             AND CONSTRAINT_TYPE = 'FOREIGN KEY'""",
        (name,),
    )
    return cursor.fetchone() is not None


def migrate(conn):
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS show_schedules (
                id INT AUTO_INCREMENT PRIMARY KEY,
                movie_id INT NOT NULL,
                theatre_id INT NOT NULL,
                show_time TIME NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NULL,
                days_of_week CHAR(7) NOT NULL DEFAULT '1111111',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_show_schedules_movie FOREIGN KEY (movie_id)
                    REFERENCES movies(id) ON DELETE RESTRICT,
                CONSTRAINT fk_show_schedules_theatre FOREIGN KEY (theatre_id)
                    REFERENCES theatres(id) ON DELETE RESTRICT,
                CONSTRAINT chk_show_schedule_dates CHECK (end_date IS NULL OR end_date >= start_date),
                -- Modern MySQL/MariaDB enforce this. The application helper
                -- still validates explicitly for engines that ignore CHECK.
                CONSTRAINT chk_show_schedule_weekdays CHECK (CHAR_LENGTH(days_of_week) = 7 AND days_of_week REGEXP '^[01]{7}$'),
                INDEX idx_schedule_generation (is_active, start_date, end_date),
                INDEX idx_schedule_identity (movie_id, theatre_id, show_time, is_active),
                INDEX idx_schedule_movie (movie_id),
                INDEX idx_schedule_theatre (theatre_id)
            )
            """
        )
        if not _column_exists(cursor, 'shows', 'schedule_id'):
            cursor.execute('ALTER TABLE shows ADD COLUMN schedule_id INT NULL AFTER theatre_id')

        if not _index_exists(cursor, 'show_schedules', 'idx_schedule_identity'):
            cursor.execute(
                'CREATE INDEX idx_schedule_identity '
                'ON show_schedules (movie_id, theatre_id, show_time, is_active)'
            )

        if not _index_exists(cursor, 'shows', 'unique_show_instance'):
            cursor.execute(
                """SELECT movie_id, theatre_id, show_date, show_time, COUNT(*) AS duplicate_count
                   FROM shows
                   GROUP BY movie_id, theatre_id, show_date, show_time
                   HAVING COUNT(*) > 1
                   LIMIT 5"""
            )
            duplicates = cursor.fetchall()
            if duplicates:
                raise RuntimeError(
                    'Cannot safely add unique_show_instance: duplicate show instances already exist. '
                    f'Resolve them manually first (sample: {duplicates}).'
                )
            cursor.execute(
                'ALTER TABLE shows ADD CONSTRAINT unique_show_instance '
                'UNIQUE (movie_id, theatre_id, show_date, show_time)'
            )
        if not _index_exists(cursor, 'shows', 'idx_schedule_date'):
            cursor.execute('CREATE INDEX idx_schedule_date ON shows (schedule_id, show_date)')
        if not _foreign_key_exists(cursor, 'fk_shows_schedule'):
            cursor.execute(
                'ALTER TABLE shows ADD CONSTRAINT fk_shows_schedule '
                'FOREIGN KEY (schedule_id) REFERENCES show_schedules(id) ON DELETE RESTRICT'
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


if __name__ == '__main__':
    conn = None
    try:
        conn = mysql.connector.connect(**db_config())
        migrate(conn)
        print('Show scheduling migration completed. Existing movies, shows, seats and bookings were preserved.')
    except Exception as exc:
        print(f'Migration failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()
