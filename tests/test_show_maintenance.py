"""Unit tests for the production-safe show-window generator.

These use a small transactional MySQL stand-in, so they prove the generation
algorithm without connecting to a developer's XAMPP or any hosted database.
"""
import copy
import unittest
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from services.show_maintenance import (
    BUSINESS_TIMEZONE,
    SEAT_ROWS,
    SHOW_WINDOW_DAYS,
    maintain_upcoming_shows,
)


class FakeMaintenanceCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []
        self.lastrowid = 0
        self.rowcount = 0

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.split())
        if normalized.startswith('SELECT id, movie_id, theatre_id'):
            horizon, today = params
            self.rows = [
                row for row in self.conn.schedules
                if row['is_active'] and row['start_date'] <= horizon
                and (row['end_date'] is None or row['end_date'] >= today)
            ]
            self.rowcount = len(self.rows)
            return
        if normalized.startswith('INSERT INTO shows'):
            movie_id, theatre_id, show_date, show_time, schedule_id = params
            key = (movie_id, theatre_id, show_date, show_time)
            existing = self.conn.shows.get(key)
            if existing is None:
                self.lastrowid = self.conn.next_show_id
                self.conn.next_show_id += 1
                self.conn.shows[key] = {'id': self.lastrowid, 'schedule_id': schedule_id}
                self.rowcount = 1
            else:
                self.lastrowid = existing['id']
                # COALESCE(schedule_id, VALUES(schedule_id)): only set if currently None
                if existing['schedule_id'] is None:
                    existing['schedule_id'] = schedule_id
                self.rowcount = 0
            return
        raise AssertionError(f'Unexpected SQL: {normalized}')

    def executemany(self, sql, values):
        if self.conn.fail_seats:
            raise RuntimeError('simulated seat insertion failure')
        added = 0
        for show_id, label, price in values:
            key = (show_id, label)
            if key not in self.conn.seats:
                self.conn.seats[key] = {
                    'price': price,
                    'is_booked': False,
                    'booked_by': None,
                }
                added += 1
        self.rowcount = added

    def fetchall(self):
        return copy.deepcopy(self.rows)

    def close(self):
        pass


class FakeMaintenanceConnection:
    def __init__(self, schedules, bookings=None):
        self.schedules = schedules
        self.shows = {}
        self.seats = {}
        self.bookings = bookings or {99: {'show_id': 7, 'status': 'CONFIRMED'}}
        self.next_show_id = 1
        self.fail_seats = False
        self.in_transaction = False
        self._snapshot = None

    def cursor(self, **_kwargs):
        return FakeMaintenanceCursor(self)

    def start_transaction(self):
        if self.in_transaction:
            raise RuntimeError('Transaction already in progress')
        self.in_transaction = True
        self._snapshot = copy.deepcopy((self.shows, self.seats, self.bookings, self.next_show_id))

    def commit(self):
        self.in_transaction = False
        self._snapshot = None

    def rollback(self):
        self.in_transaction = False
        if self._snapshot is not None:
            self.shows, self.seats, self.bookings, self.next_show_id = copy.deepcopy(self._snapshot)
            self._snapshot = None


def schedule(*, id=1, active=True, start_date=date(2026, 9, 1), end_date=None, days='1111111',
             movie_id=10, theatre_id=20, show_time=time(19, 0)):
    return {
        'id': id, 'movie_id': movie_id, 'theatre_id': theatre_id, 'show_time': show_time,
        'start_date': start_date, 'end_date': end_date,
        'days_of_week': days, 'is_active': active,
    }


class ShowMaintenanceTests(unittest.TestCase):
    TODAY = date(2026, 9, 5)

    def test_full_window_creates_nothing_on_second_run(self):
        conn = FakeMaintenanceConnection([schedule()])
        first = maintain_upcoming_shows(conn, now=self.TODAY)
        second = maintain_upcoming_shows(conn, now=self.TODAY)
        self.assertEqual(first['created_shows'], 7)
        self.assertEqual(first['created_seats'], 7 * len(SEAT_ROWS))
        self.assertEqual(second['created_shows'], 0)
        self.assertEqual(second['created_seats'], 0)

    def test_duplicate_show_prevention_does_not_create_duplicate_rows(self):
        # Pre-seed day 1 show instance
        conn = FakeMaintenanceConnection([schedule()])
        show_key = (10, 20, self.TODAY, time(19, 0))
        conn.shows[show_key] = {'id': 50, 'schedule_id': 1}
        conn.next_show_id = 51

        result = maintain_upcoming_shows(conn, now=self.TODAY)
        # 6 new shows created; the existing 1 is reused without duplicating
        self.assertEqual(result['created_shows'], 6)
        self.assertEqual(conn.shows[show_key]['id'], 50)
        self.assertEqual(len(conn.shows), 7)

    def test_duplicate_seat_prevention_preserves_booked_seats(self):
        conn = FakeMaintenanceConnection([schedule()])
        show_key = (10, 20, self.TODAY, time(19, 0))
        conn.shows[show_key] = {'id': 50, 'schedule_id': 1}
        conn.next_show_id = 51

        # Pre-populate seats for show 50, with seat A1 already booked
        for label, price in SEAT_ROWS:
            conn.seats[(50, label)] = {
                'price': price,
                'is_booked': (label == 'A1'),
                'booked_by': 777 if label == 'A1' else None,
            }

        result = maintain_upcoming_shows(conn, now=self.TODAY)
        # Seats for show 50 are skipped (0 created for show 50; 6 * 120 for the other 6 shows)
        self.assertEqual(result['created_seats'], 6 * len(SEAT_ROWS))
        # Booked seat state must be completely preserved
        self.assertTrue(conn.seats[(50, 'A1')]['is_booked'])
        self.assertEqual(conn.seats[(50, 'A1')]['booked_by'], 777)

    def test_schedule_ownership_provenance_preserved(self):
        # Show was originally generated by Schedule 1
        conn = FakeMaintenanceConnection([])
        show_key = (10, 20, self.TODAY, time(19, 0))
        conn.shows[show_key] = {'id': 50, 'schedule_id': 1}

        # Schedule 1 is now inactive, Schedule 2 is the replacement
        sched2 = schedule(id=2, start_date=self.TODAY, end_date=self.TODAY + timedelta(days=6))
        conn.schedules = [sched2]

        maintain_upcoming_shows(conn, now=self.TODAY)
        # Schedule ID on show 50 MUST remain 1 due to COALESCE(schedule_id, VALUES(schedule_id))
        self.assertEqual(conn.shows[show_key]['schedule_id'], 1)

    def test_legacy_null_schedule_id_is_claimed_by_matching_schedule(self):
        # Legacy show had schedule_id = None
        conn = FakeMaintenanceConnection([schedule(id=9)])
        show_key = (10, 20, self.TODAY, time(19, 0))
        conn.shows[show_key] = {'id': 50, 'schedule_id': None}

        maintain_upcoming_shows(conn, now=self.TODAY)
        # COALESCE(NULL, 9) links the legacy show to the active schedule
        self.assertEqual(conn.shows[show_key]['schedule_id'], 9)

    def test_missing_last_day_is_the_only_instance_created(self):
        conn = FakeMaintenanceConnection([schedule()])
        maintain_upcoming_shows(conn, now=self.TODAY, window_days=6)
        result = maintain_upcoming_shows(conn, now=self.TODAY, window_days=7)
        self.assertEqual(result['created_shows'], 1)
        self.assertEqual(result['created_seats'], len(SEAT_ROWS))

    def test_existing_bookings_are_not_modified(self):
        bookings = {77: {'show_id': 999, 'status': 'CONFIRMED', 'seat_ids': '[1, 2]'}}
        conn = FakeMaintenanceConnection([schedule()], bookings=bookings)
        before = copy.deepcopy(conn.bookings)
        maintain_upcoming_shows(conn, now=self.TODAY)
        self.assertEqual(conn.bookings, before)

    def test_inactive_or_finished_schedule_generates_nothing(self):
        conn = FakeMaintenanceConnection([
            schedule(active=False),
            schedule(end_date=date(2026, 9, 4)),
        ])
        result = maintain_upcoming_shows(conn, now=self.TODAY)
        self.assertEqual(result['active_schedules'], 0)
        self.assertEqual(result['created_shows'], 0)
        self.assertEqual(result['created_seats'], 0)

    def test_weekday_rule_is_respected(self):
        # Saturday 2026-09-05 through Friday: only the Monday bit is enabled.
        conn = FakeMaintenanceConnection([schedule(days='1000000')])
        result = maintain_upcoming_shows(conn, now=self.TODAY)
        self.assertEqual(result['created_shows'], 1)

    def test_seat_failure_rolls_back_created_show_and_seats(self):
        conn = FakeMaintenanceConnection([schedule()])
        conn.fail_seats = True
        with self.assertRaisesRegex(RuntimeError, 'seat insertion'):
            maintain_upcoming_shows(conn, now=self.TODAY)
        self.assertEqual(conn.shows, {})
        self.assertEqual(conn.seats, {})

    def test_disabling_a_schedule_preserves_existing_generated_shows(self):
        old = schedule(id=1, end_date=date(2026, 9, 7))
        replacement = schedule(id=2, start_date=date(2026, 9, 8), end_date=date(2026, 9, 20))
        conn = FakeMaintenanceConnection([old, replacement])

        maintain_upcoming_shows(conn, now=self.TODAY)
        generated_before_deactivation = copy.deepcopy(conn.shows)
        old['is_active'] = False
        maintain_upcoming_shows(conn, now=date(2026, 9, 8))

        self.assertTrue(generated_before_deactivation)
        self.assertTrue(all(key in conn.shows for key in generated_before_deactivation))

    def test_rolling_window_maintains_today_plus_six_days_asia_kolkata(self):
        # Timezone-aware timestamp: 2026-09-05 23:30 in Asia/Kolkata
        aware_now = datetime(2026, 9, 5, 23, 30, tzinfo=ZoneInfo('Asia/Kolkata'))
        conn = FakeMaintenanceConnection([schedule(start_date=date(2026, 9, 1))])
        res = maintain_upcoming_shows(conn, now=aware_now, window_days=SHOW_WINDOW_DAYS)

        self.assertEqual(res['today'], date(2026, 9, 5))
        self.assertEqual(res['horizon'], date(2026, 9, 11))
        self.assertEqual((res['horizon'] - res['today']).days, 6)
        self.assertEqual(res['created_shows'], 7)


if __name__ == '__main__':
    unittest.main(verbosity=2)
