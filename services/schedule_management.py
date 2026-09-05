"""Validated, non-public writes for Bookora show schedule rules.

There is intentionally no HTTP endpoint in this module.  Seed tooling and a
future authenticated operator UI can use these functions; direct SQL writers
must apply the same rules described in docs/SHOW_SCHEDULING_OPERATIONS.md.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable


class ScheduleValidationError(ValueError):
    """A schedule field is malformed or violates the date-range rules."""


class ScheduleOverlapError(ScheduleValidationError):
    """Two active rules could generate the same show instance."""


class ScheduleWriteBusyError(RuntimeError):
    """Another controlled write for the same schedule identity is in progress."""


WEEKDAY_MASK_LENGTH = 7  # Monday through Sunday; preserved from Phase 1.
SCHEDULE_LOCK_TIMEOUT_SECONDS = 10


def _scalar(row: Any) -> Any:
    """Read the one value returned by a normal or dictionary cursor."""
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def validate_weekday_mask(value: Any) -> str:
    """Return a valid Mon-Sun mask or raise a clear validation error."""
    if not isinstance(value, str) or len(value) != WEEKDAY_MASK_LENGTH:
        raise ScheduleValidationError(
            'days_of_week must be exactly seven characters ordered Monday through Sunday.'
        )
    if set(value) - {'0', '1'}:
        raise ScheduleValidationError('days_of_week may contain only 0 and 1.')
    return value


def _normalise_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ScheduleValidationError(f'{field_name} must be a calendar date.')


def normalise_show_time(value: Any) -> time:
    """Accept a normal SQL/JSON time value and return a canonical time object."""
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        if seconds < 0 or seconds >= 24 * 60 * 60:
            raise ScheduleValidationError('show_time must be within one calendar day.')
        return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if isinstance(value, str):
        for pattern in ('%H:%M:%S', '%H:%M'):
            try:
                return datetime.strptime(value, pattern).time()
            except ValueError:
                pass
    raise ScheduleValidationError('show_time must use HH:MM or HH:MM:SS.')


def validate_schedule_fields(*, movie_id: Any, theatre_id: Any, show_time: Any,
                             start_date: Any, end_date: Any, days_of_week: Any,
                             is_active: Any = True) -> dict[str, Any]:
    """Validate and normalize every operator-supplied schedule field."""
    if not isinstance(movie_id, int) or movie_id <= 0:
        raise ScheduleValidationError('movie_id must be a positive integer.')
    if not isinstance(theatre_id, int) or theatre_id <= 0:
        raise ScheduleValidationError('theatre_id must be a positive integer.')
    if not isinstance(is_active, bool):
        raise ScheduleValidationError('is_active must be true or false.')

    normalized_start = _normalise_date(start_date, 'start_date')
    normalized_end = None if end_date is None else _normalise_date(end_date, 'end_date')
    if normalized_end is not None and normalized_end < normalized_start:
        raise ScheduleValidationError('end_date cannot be before start_date.')

    return {
        'movie_id': movie_id,
        'theatre_id': theatre_id,
        'show_time': normalise_show_time(show_time),
        'start_date': normalized_start,
        'end_date': normalized_end,
        'days_of_week': validate_weekday_mask(days_of_week),
        'is_active': is_active,
    }


def _common_enabled_weekdays(first_mask: str, second_mask: str) -> set[int]:
    return {
        weekday for weekday, (first, second) in enumerate(zip(first_mask, second_mask))
        if first == '1' and second == '1'
    }


def schedules_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Whether two active rules can claim the same calendar date.

    The caller may compare any two rules; different movie/theatre/time identities
    never conflict.  For matching identities, ranges must intersect *and* both
    masks must enable at least one common date in that intersection.
    """
    if not first['is_active'] or not second['is_active']:
        return False
    if (
        first['movie_id'] != second['movie_id']
        or first['theatre_id'] != second['theatre_id']
        or normalise_show_time(first['show_time']) != normalise_show_time(second['show_time'])
    ):
        return False

    first_mask = validate_weekday_mask(first['days_of_week'])
    second_mask = validate_weekday_mask(second['days_of_week'])
    common_weekdays = _common_enabled_weekdays(first_mask, second_mask)
    if not common_weekdays:
        return False

    start = max(_normalise_date(first['start_date'], 'start_date'),
                _normalise_date(second['start_date'], 'start_date'))
    first_end = first.get('end_date')
    second_end = second.get('end_date')
    end_candidates = [
        _normalise_date(value, 'end_date')
        for value in (first_end, second_end)
        if value is not None
    ]
    end = min(end_candidates) if end_candidates else None
    if end is not None and end < start:
        return False

    # An unbounded intersection, or any seven consecutive dates, necessarily
    # includes every weekday at least once.
    if end is None or (end - start).days >= WEEKDAY_MASK_LENGTH - 1:
        return True

    candidate = start
    while candidate <= end:
        if candidate.weekday() in common_weekdays:
            return True
        candidate += timedelta(days=1)
    return False


def ensure_no_schedule_overlap(candidate: dict[str, Any],
                               existing_schedules: Iterable[dict[str, Any]]) -> None:
    """Raise when an active candidate conflicts with any active existing rule."""
    for existing in existing_schedules:
        if schedules_overlap(candidate, existing):
            raise ScheduleOverlapError(
                'An active schedule already claims at least one enabled date for '
                'this movie, theatre and show time. End/deactivate it first, or '
                'choose a non-overlapping date range or weekday mask.'
            )


def _schedule_lock_name(movie_id: int, theatre_id: int, show_time: time) -> str:
    # MySQL named locks are capped at 64 characters. Hashing prevents an
    # arbitrary operator-supplied value from changing lock scope or length.
    identity = f'{movie_id}:{theatre_id}:{show_time.isoformat()}'
    return 'bookora_schedule_' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:40]


def create_schedule(conn, **schedule_fields: Any) -> int:
    """Insert one validated, non-overlapping schedule in a transaction.

    A MySQL advisory lock serializes same movie/theatre/time writes, preventing
    two operators from both passing the overlap query and inserting conflicting
    rules.  This is the supported write path for seed tooling and any future
    authenticated operator feature.
    """
    candidate = validate_schedule_fields(**schedule_fields)
    cursor = conn.cursor(dictionary=True, buffered=True)
    lock_name = _schedule_lock_name(
        candidate['movie_id'], candidate['theatre_id'], candidate['show_time']
    )
    acquired_lock = False
    try:
        cursor.execute('SELECT GET_LOCK(%s, %s)', (lock_name, SCHEDULE_LOCK_TIMEOUT_SECONDS))
        acquired_lock = _scalar(cursor.fetchone()) == 1
        if not acquired_lock:
            raise ScheduleWriteBusyError('Another schedule change for this show time is in progress.')

        if not getattr(conn, 'in_transaction', False):
            conn.start_transaction()
        cursor.execute(
            """
            SELECT id, movie_id, theatre_id, show_time, start_date, end_date, days_of_week, is_active
            FROM show_schedules
            WHERE movie_id = %s AND theatre_id = %s AND show_time = %s AND is_active = TRUE
            FOR UPDATE
            """,
            (candidate['movie_id'], candidate['theatre_id'], candidate['show_time']),
        )
        ensure_no_schedule_overlap(candidate, cursor.fetchall())
        cursor.execute(
            """
            INSERT INTO show_schedules
                (movie_id, theatre_id, show_time, start_date, end_date, days_of_week, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                candidate['movie_id'], candidate['theatre_id'], candidate['show_time'],
                candidate['start_date'], candidate['end_date'], candidate['days_of_week'],
                candidate['is_active'],
            ),
        )
        schedule_id = cursor.lastrowid
        conn.commit()
        return schedule_id
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if acquired_lock:
            try:
                cursor.execute('SELECT RELEASE_LOCK(%s)', (lock_name,))
                cursor.fetchone()
            except Exception:
                pass
        cursor.close()


def deactivate_schedule(conn, schedule_id: int) -> None:
    """Stop future generation without deleting an existing schedule or show."""
    if not isinstance(schedule_id, int) or schedule_id <= 0:
        raise ScheduleValidationError('schedule_id must be a positive integer.')
    cursor = conn.cursor(buffered=True)
    try:
        if not getattr(conn, 'in_transaction', False):
            conn.start_transaction()
        cursor.execute('UPDATE show_schedules SET is_active = FALSE WHERE id = %s', (schedule_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
