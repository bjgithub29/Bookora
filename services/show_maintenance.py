"""Production-safe generation of Bookora's rolling show window.

This module deliberately knows nothing about Flask or the deployment platform.
It turns active rows in ``show_schedules`` (the operator-managed source of
truth) into dated ``shows`` instances, plus their per-show seats.  It never
deletes shows, seats, or bookings.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from services.schedule_management import validate_weekday_mask
except ImportError:
    from .schedule_management import validate_weekday_mask


BUSINESS_TIMEZONE_NAME = 'Asia/Kolkata'
BUSINESS_TIMEZONE = ZoneInfo(BUSINESS_TIMEZONE_NAME)
SHOW_WINDOW_DAYS = 7

# This is the existing Bookora seed layout.  Keeping it here means a generated
# show always receives the same seat map as an initially seeded show.
SEAT_PRICES = {
    'A': 150, 'B': 150, 'C': 150,
    'D': 200, 'E': 200, 'F': 200,
    'G': 250, 'H': 250,
    'I': 300, 'J': 300,
}
SEAT_ROWS = tuple(
    (f'{row}{number}', price)
    for row, price in SEAT_PRICES.items()
    for number in range(1, 13)
)


def business_now() -> datetime:
    """Return the current India business time as a timezone-aware datetime."""
    return datetime.now(BUSINESS_TIMEZONE)


def _as_business_date(now: datetime | date | None) -> date:
    if now is None:
        return business_now().date()
    if isinstance(now, datetime):
        if now.tzinfo is not None:
            return now.astimezone(BUSINESS_TIMEZONE).date()
        return now.date()
    return now


def is_scheduled_on(schedule: dict[str, Any], target_date: date) -> bool:
    """Return whether a seven-character Mon-Sun schedule includes a date."""
    days = validate_weekday_mask(schedule['days_of_week'])
    return days[target_date.weekday()] == '1'


def _candidate_dates(schedule: dict[str, Any], today: date, horizon: date):
    start = max(today, schedule['start_date'])
    end_date = schedule.get('end_date')
    end = min(horizon, end_date) if end_date else horizon
    while start <= end:
        if is_scheduled_on(schedule, start):
            yield start
        start += timedelta(days=1)


def maintain_upcoming_shows(conn, now: datetime | date | None = None,
                             window_days: int = SHOW_WINDOW_DAYS) -> dict[str, Any]:
    """Generate only the missing show instances in today through horizon.

    ``conn`` must be a mysql-connector connection.  The function is
    intentionally callable by a cron/worker command and by tests.  One
    transaction covers every show and seat written during a run: a failed seat
    insert rolls back the related show instance too.

    Two layers make repeated or overlapping runs safe:
    * the ``shows`` unique key identifies one movie/theatre/date/time instance;
    * the ``seats`` unique key identifies one label per show.
    """
    if window_days < 1:
        raise ValueError('window_days must be at least 1')

    today = _as_business_date(now)
    horizon = today + timedelta(days=window_days - 1)
    cursor = conn.cursor(dictionary=True, buffered=True)
    created_shows = 0
    created_seats = 0

    try:
        if not getattr(conn, 'in_transaction', False):
            conn.start_transaction()
        cursor.execute(
            """
            SELECT id, movie_id, theatre_id, show_time, start_date, end_date, days_of_week
            FROM show_schedules
            WHERE is_active = TRUE
              AND start_date <= %s
              AND (end_date IS NULL OR end_date >= %s)
            ORDER BY id
            """,
            (horizon, today),
        )
        schedules = cursor.fetchall()

        for schedule in schedules:
            for show_date in _candidate_dates(schedule, today, horizon):
                # LAST_INSERT_ID(id) gives this process the id whether the row
                # was newly inserted or already existed.  COALESCE safely links
                # a legacy matching instance to its schedule without touching
                # any booking or seat data.
                cursor.execute(
                    """
                    INSERT INTO shows
                        (movie_id, theatre_id, show_date, show_time, schedule_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id),
                        schedule_id = COALESCE(schedule_id, VALUES(schedule_id))
                    """,
                    (
                        schedule['movie_id'], schedule['theatre_id'], show_date,
                        schedule['show_time'], schedule['id'],
                    ),
                )
                if cursor.rowcount == 1:
                    created_shows += 1
                show_id = cursor.lastrowid

                # The duplicate-key clause handles only the expected seat-label
                # collision during a concurrent/repeated run. Other database
                # errors still abort the transaction and are rolled back.
                cursor.executemany(
                    """
                    INSERT INTO seats (show_id, seat_label, price, is_booked)
                    VALUES (%s, %s, %s, FALSE)
                    ON DUPLICATE KEY UPDATE id = id
                    """,
                    [(show_id, label, price) for label, price in SEAT_ROWS],
                )
                created_seats += cursor.rowcount

        conn.commit()
        return {
            'today': today,
            'horizon': horizon,
            'active_schedules': len(schedules),
            'created_shows': created_shows,
            'created_seats': created_seats,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
