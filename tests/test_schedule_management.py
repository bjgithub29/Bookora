"""Validation and transactional tests for controlled show-schedule writes."""
import copy
import unittest
from datetime import date, datetime, time, timedelta

from services.schedule_management import (
    ScheduleOverlapError,
    ScheduleValidationError,
    ScheduleWriteBusyError,
    create_schedule,
    deactivate_schedule,
    ensure_no_schedule_overlap,
    normalise_show_time,
    schedules_overlap,
    validate_schedule_fields,
    validate_weekday_mask,
)


def schedule(*, start=date(2026, 9, 5), end=date(2026, 9, 10),
             days='1111111', active=True, movie_id=1, theatre_id=2, show_time='10:00'):
    return validate_schedule_fields(
        movie_id=movie_id, theatre_id=theatre_id, show_time=show_time,
        start_date=start, end_date=end, days_of_week=days, is_active=active,
    )


class WeekdayMaskValidationTests(unittest.TestCase):
    def test_valid_seven_character_masks_are_accepted(self):
        for valid in ('1111111', '1000000', '0100000', '0000011', '0000001', '0101010'):
            with self.subTest(valid=valid):
                self.assertEqual(validate_weekday_mask(valid), valid)

    def test_invalid_masks_are_rejected(self):
        for invalid in ('111111', '11111111', '11111a1', '1111121', ' 111111', '', None, 1111111):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ScheduleValidationError):
                    validate_weekday_mask(invalid)


class FieldValidationTests(unittest.TestCase):
    def test_date_fields_accept_dates_datetimes_and_iso_strings(self):
        fields = validate_schedule_fields(
            movie_id=1, theatre_id=2, show_time='10:00',
            start_date='2026-09-05', end_date=datetime(2026, 9, 10, 14, 30),
            days_of_week='1111111', is_active=True,
        )
        self.assertEqual(fields['start_date'], date(2026, 9, 5))
        self.assertEqual(fields['end_date'], date(2026, 9, 10))

    def test_end_date_before_start_date_is_rejected(self):
        with self.assertRaisesRegex(ScheduleValidationError, 'end_date cannot be before start_date'):
            validate_schedule_fields(
                movie_id=1, theatre_id=2, show_time='10:00',
                start_date=date(2026, 9, 10), end_date=date(2026, 9, 5),
                days_of_week='1111111',
            )

    def test_invalid_identifiers_are_rejected(self):
        for bad_id in (0, -1, 'one', None):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ScheduleValidationError):
                    validate_schedule_fields(
                        movie_id=bad_id, theatre_id=2, show_time='10:00',
                        start_date=date(2026, 9, 5), end_date=None, days_of_week='1111111',
                    )
                with self.assertRaises(ScheduleValidationError):
                    validate_schedule_fields(
                        movie_id=1, theatre_id=bad_id, show_time='10:00',
                        start_date=date(2026, 9, 5), end_date=None, days_of_week='1111111',
                    )

    def test_show_time_normalisation(self):
        self.assertEqual(normalise_show_time('10:00'), time(10, 0))
        self.assertEqual(normalise_show_time('14:30:00'), time(14, 30))
        self.assertEqual(normalise_show_time(time(18, 0)), time(18, 0))
        self.assertEqual(normalise_show_time(timedelta(hours=20, minutes=15)), time(20, 15))
        for invalid in ('25:00', 'invalid', None, timedelta(days=2)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ScheduleValidationError):
                    normalise_show_time(invalid)


class ScheduleOverlapTests(unittest.TestCase):
    def test_non_overlapping_replacement_is_allowed(self):
        old = schedule(start=date(2026, 9, 5), end=date(2026, 9, 10))
        replacement = schedule(start=date(2026, 9, 11), end=date(2026, 9, 20))
        self.assertFalse(schedules_overlap(old, replacement))
        ensure_no_schedule_overlap(replacement, [old])

    def test_non_overlapping_date_ranges_with_gap_are_allowed(self):
        old = schedule(start=date(2026, 9, 5), end=date(2026, 9, 10))
        replacement = schedule(start=date(2026, 9, 15), end=date(2026, 9, 25))
        self.assertFalse(schedules_overlap(old, replacement))
        ensure_no_schedule_overlap(replacement, [old])

    def test_different_movies_never_overlap(self):
        a = schedule(movie_id=1, theatre_id=1, show_time='10:00')
        b = schedule(movie_id=2, theatre_id=1, show_time='10:00')
        self.assertFalse(schedules_overlap(a, b))

    def test_different_theatres_never_overlap(self):
        a = schedule(movie_id=1, theatre_id=1, show_time='10:00')
        b = schedule(movie_id=1, theatre_id=2, show_time='10:00')
        self.assertFalse(schedules_overlap(a, b))

    def test_different_show_times_never_overlap(self):
        a = schedule(movie_id=1, theatre_id=1, show_time='10:00')
        b = schedule(movie_id=1, theatre_id=1, show_time='13:00')
        self.assertFalse(schedules_overlap(a, b))

    def test_overlapping_active_ranges_are_rejected(self):
        old = schedule(start=date(2026, 9, 5), end=date(2026, 9, 15))
        replacement = schedule(start=date(2026, 9, 10), end=date(2026, 9, 20))
        self.assertTrue(schedules_overlap(old, replacement))
        with self.assertRaises(ScheduleOverlapError):
            ensure_no_schedule_overlap(replacement, [old])

    def test_open_ended_schedule_conflicts_with_later_active_rule(self):
        old = schedule(start=date(2026, 9, 5), end=None)
        replacement = schedule(start=date(2026, 10, 1), end=date(2026, 10, 20))
        self.assertTrue(schedules_overlap(old, replacement))
        with self.assertRaises(ScheduleOverlapError):
            ensure_no_schedule_overlap(replacement, [old])

    def test_two_open_ended_schedules_conflict(self):
        old = schedule(start=date(2026, 9, 5), end=None)
        replacement = schedule(start=date(2026, 10, 1), end=None)
        self.assertTrue(schedules_overlap(old, replacement))

    def test_open_ended_schedules_with_disjoint_weekdays_do_not_conflict(self):
        mon = schedule(start=date(2026, 9, 5), end=None, days='1000000')
        tue = schedule(start=date(2026, 9, 5), end=None, days='0100000')
        self.assertFalse(schedules_overlap(mon, tue))
        ensure_no_schedule_overlap(tue, [mon])

    def test_inactive_schedule_does_not_block_replacement(self):
        old = schedule(active=False)
        replacement = schedule()
        self.assertFalse(schedules_overlap(old, replacement))
        ensure_no_schedule_overlap(replacement, [old])

    def test_candidate_inactive_schedule_does_not_conflict(self):
        active_existing = schedule(active=True)
        inactive_candidate = schedule(active=False)
        self.assertFalse(schedules_overlap(inactive_candidate, active_existing))
        ensure_no_schedule_overlap(inactive_candidate, [active_existing])

    def test_weekday_masks_only_conflict_on_a_shared_enabled_date(self):
        # 2026-09-05 is Saturday and 2026-09-06 is Sunday: these overlap in
        # range but claim different weekdays, so both rules are valid.
        saturday = schedule(start=date(2026, 9, 5), end=date(2026, 9, 6), days='0000010')
        sunday = schedule(start=date(2026, 9, 5), end=date(2026, 9, 6), days='0000001')
        self.assertFalse(schedules_overlap(saturday, sunday))

        monday_a = schedule(start=date(2026, 9, 5), end=date(2026, 9, 8), days='1000000')
        monday_b = schedule(start=date(2026, 9, 7), end=date(2026, 9, 14), days='1000000')
        self.assertTrue(schedules_overlap(monday_a, monday_b))


class FakeScheduleCursor:
    def __init__(self, conn):
        self.conn = conn
        self.lastrowid = 0
        self.rowcount = 0
        self._fetched = None

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.split())
        if 'GET_LOCK' in normalized:
            self._fetched = (1 if not self.conn.lock_busy else 0,)
            return
        if 'RELEASE_LOCK' in normalized:
            self._fetched = (1,)
            return
        if 'SELECT id, movie_id, theatre_id, show_time, start_date, end_date, days_of_week, is_active' in normalized:
            movie_id, theatre_id, show_time = params
            matching = [
                row for row in self.conn.schedules
                if row['movie_id'] == movie_id
                and row['theatre_id'] == theatre_id
                and row['show_time'] == show_time
                and row['is_active']
            ]
            self._fetched = matching
            return
        if normalized.startswith('INSERT INTO show_schedules'):
            movie_id, theatre_id, show_time, start_date, end_date, days_of_week, is_active = params
            self.lastrowid = self.conn.next_id
            self.conn.next_id += 1
            new_row = {
                'id': self.lastrowid,
                'movie_id': movie_id,
                'theatre_id': theatre_id,
                'show_time': show_time,
                'start_date': start_date,
                'end_date': end_date,
                'days_of_week': days_of_week,
                'is_active': is_active,
            }
            self.conn.schedules.append(new_row)
            self.rowcount = 1
            return
        if normalized.startswith('UPDATE show_schedules SET is_active = FALSE'):
            sched_id = params[0]
            found = False
            for row in self.conn.schedules:
                if row['id'] == sched_id:
                    row['is_active'] = False
                    found = True
            self.rowcount = 1 if found else 0
            return
        raise AssertionError(f'Unexpected SQL: {normalized}')

    def fetchone(self):
        return self._fetched

    def fetchall(self):
        return list(self._fetched)

    def close(self):
        pass


class FakeScheduleConnection:
    def __init__(self, schedules=None, lock_busy=False):
        self.schedules = schedules or []
        self.lock_busy = lock_busy
        self.next_id = 100
        self.in_transaction = False
        self._snapshot = None

    def cursor(self, **_kwargs):
        return FakeScheduleCursor(self)

    def start_transaction(self):
        if self.in_transaction:
            raise RuntimeError('Transaction already in progress')
        self.in_transaction = True
        self._snapshot = copy.deepcopy(self.schedules)

    def commit(self):
        self.in_transaction = False
        self._snapshot = None

    def rollback(self):
        self.in_transaction = False
        if self._snapshot is not None:
            self.schedules = copy.deepcopy(self._snapshot)
            self._snapshot = None


class ScheduleTransactionTests(unittest.TestCase):
    def test_create_schedule_persists_valid_rule(self):
        conn = FakeScheduleConnection()
        schedule_id = create_schedule(
            conn, movie_id=1, theatre_id=2, show_time='10:00',
            start_date=date(2026, 9, 5), end_date=date(2026, 9, 10),
            days_of_week='1111111', is_active=True,
        )
        self.assertEqual(schedule_id, 100)
        self.assertEqual(len(conn.schedules), 1)
        self.assertEqual(conn.schedules[0]['id'], 100)
        self.assertTrue(conn.schedules[0]['is_active'])

    def test_create_schedule_fails_when_lock_is_busy(self):
        conn = FakeScheduleConnection(lock_busy=True)
        with self.assertRaises(ScheduleWriteBusyError):
            create_schedule(
                conn, movie_id=1, theatre_id=2, show_time='10:00',
                start_date=date(2026, 9, 5), end_date=date(2026, 9, 10),
                days_of_week='1111111',
            )
        self.assertEqual(len(conn.schedules), 0)

    def test_create_schedule_rejects_overlapping_active_rule_and_rolls_back(self):
        existing = {
            'id': 1, 'movie_id': 1, 'theatre_id': 2, 'show_time': time(10, 0),
            'start_date': date(2026, 9, 5), 'end_date': date(2026, 9, 15),
            'days_of_week': '1111111', 'is_active': True,
        }
        conn = FakeScheduleConnection([existing])
        with self.assertRaises(ScheduleOverlapError):
            create_schedule(
                conn, movie_id=1, theatre_id=2, show_time='10:00',
                start_date=date(2026, 9, 10), end_date=date(2026, 9, 20),
                days_of_week='1111111',
            )
        self.assertEqual(len(conn.schedules), 1)
        self.assertFalse(conn.in_transaction)

    def test_deactivate_and_replace_schedule_succeeds(self):
        existing = {
            'id': 1, 'movie_id': 1, 'theatre_id': 2, 'show_time': time(10, 0),
            'start_date': date(2026, 9, 5), 'end_date': date(2026, 9, 15),
            'days_of_week': '1111111', 'is_active': True,
        }
        conn = FakeScheduleConnection([existing])
        deactivate_schedule(conn, 1)
        self.assertFalse(conn.schedules[0]['is_active'])

        # Now creating an overlapping replacement on the same identity must succeed
        new_id = create_schedule(
            conn, movie_id=1, theatre_id=2, show_time='10:00',
            start_date=date(2026, 9, 10), end_date=date(2026, 9, 20),
            days_of_week='1111111',
        )
        self.assertEqual(new_id, 100)
        self.assertEqual(len(conn.schedules), 2)
        self.assertFalse(conn.schedules[0]['is_active'])
        self.assertTrue(conn.schedules[1]['is_active'])

    def test_deactivate_schedule_validates_id(self):
        conn = FakeScheduleConnection()
        for bad_id in (0, -5, 'ten', None):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ScheduleValidationError):
                    deactivate_schedule(conn, bad_id)


if __name__ == '__main__':
    unittest.main(verbosity=2)
