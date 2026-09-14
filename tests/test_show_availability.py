"""Server-side show-expiration tests without a MySQL server."""
import unittest
from datetime import date, datetime, time
from unittest.mock import patch

import app as bookora


class FakeCursor:
    def __init__(self, movie=None, show=None, shows=None, seats=None):
        self.movie = movie
        self.show = show
        self.shows = shows or []
        self.seats = seats or []
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))

    def fetchone(self):
        if self.calls and 'FROM movies' in self.calls[-1][0]:
            return self.movie
        return self.show

    def fetchall(self):
        # /api/shows has no show-detail SELECT; /api/seats has one before seats.
        if self.calls and 'FROM shows s' in self.calls[-1][0]:
            return self.shows
        if self.calls and 'FROM seats' in self.calls[-1][0]:
            return self.seats
        return []

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self, **_kwargs):
        return self.cursor_instance

    def close(self):
        pass


class ShowAvailabilityTests(unittest.TestCase):
    def setUp(self):
        bookora.app.config['TESTING'] = True
        self.client = bookora.app.test_client()

    def test_show_list_filters_started_instances_in_sql(self):
        cursor = FakeCursor(shows=[{
            'show_id': 4, 'show_time': time(21, 0), 'theatre_id': 2,
            'theatre_name': 'Demo', 'theatre_address': 'Ahmedabad',
            'available_seats': 120, 'total_seats': 120,
        }])
        now = datetime(2026, 9, 5, 20, 0)
        with patch.object(bookora, 'get_db', return_value=FakeConnection(cursor)), \
             patch.object(bookora, 'business_now_naive', return_value=now):
            response = self.client.get('/api/shows?movie_id=1&date=2026-09-05')

        self.assertEqual(response.status_code, 200)
        sql, params = cursor.calls[0]
        self.assertIn('TIMESTAMP(s.show_date, s.show_time) > %s', sql)
        self.assertEqual(params, ('1', date(2026, 9, 5), now))
        self.assertEqual(response.get_json()['theatres'][0]['shows'][0]['show_id'], 4)

    def test_movie_with_no_shows_returns_empty_theatres(self):
        cursor = FakeCursor(shows=[])
        now = datetime(2026, 9, 15, 10, 0)
        with patch.object(bookora, 'get_db', return_value=FakeConnection(cursor)), \
             patch.object(bookora, 'business_now_naive', return_value=now):
            response = self.client.get('/api/shows?movie_id=8&date=2026-09-15')

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['theatres'], [])

    def test_slug_resolution_and_theatre_grouping(self):
        cursor = FakeCursor(
            movie={'id': 8, 'title': 'Kesari Chapter 2'},
            shows=[
                {
                    'show_id': 101, 'show_time': time(10, 0), 'theatre_id': 5,
                    'theatre_name': 'City Gold', 'theatre_address': 'Ashram Road',
                    'available_seats': 100, 'total_seats': 120,
                },
                {
                    'show_id': 102, 'show_time': time(14, 0), 'theatre_id': 5,
                    'theatre_name': 'City Gold', 'theatre_address': 'Ashram Road',
                    'available_seats': 120, 'total_seats': 120,
                },
                {
                    'show_id': 201, 'show_time': time(19, 0), 'theatre_id': 8,
                    'theatre_name': 'INOX', 'theatre_address': 'SG Highway',
                    'available_seats': 80, 'total_seats': 120,
                },
            ]
        )
        now = datetime(2026, 9, 15, 8, 0)
        with patch.object(bookora, 'get_db', return_value=FakeConnection(cursor)), \
             patch.object(bookora, 'business_now_naive', return_value=now):
            response = self.client.get('/api/shows?slug=kesari_chapter_2&date=2026-09-15')

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['theatres']), 2)
        # City Gold has 2 shows, INOX has 1 show
        city_gold = next(t for t in data['theatres'] if t['id'] == 5)
        self.assertEqual(len(city_gold['shows']), 2)
        self.assertEqual(city_gold['shows'][0]['time'], '10:00')
        self.assertAlmostEqual(city_gold['shows'][0]['occupancy'], 16.7, places=1)

    def test_invalid_or_missing_date_rejected(self):
        response = self.client.get('/api/shows?movie_id=8')
        self.assertEqual(response.status_code, 400)
        self.assertIn('date parameter required', response.get_json()['message'])

        response2 = self.client.get('/api/shows?movie_id=8&date=invalid-date')
        self.assertEqual(response2.status_code, 400)
        self.assertIn('date must use YYYY-MM-DD', response2.get_json()['message'])

    def test_started_show_cannot_open_seat_selection(self):
        cursor = FakeCursor(show={
            'id': 4, 'show_date': date(2026, 9, 5), 'show_time': time(19, 0),
            'movie_title': 'Demo', 'theatre_name': 'Demo', 'theatre_address': 'Ahmedabad',
        })
        with patch.object(bookora, 'get_db', return_value=FakeConnection(cursor)), \
             patch.object(bookora, 'business_now_naive', return_value=datetime(2026, 9, 5, 19, 0)):
            response = self.client.get('/api/seats/4')
        self.assertEqual(response.status_code, 400)
        self.assertIn('no longer available', response.get_json()['message'])
        self.assertEqual(len(cursor.calls), 1, 'expired shows must not query seats')

    def test_future_show_remains_available(self):
        cursor = FakeCursor(
            show={
                'id': 4, 'show_date': date(2026, 9, 5), 'show_time': time(19, 0),
                'movie_title': 'Demo', 'theatre_name': 'Demo', 'theatre_address': 'Ahmedabad',
            },
            seats=[{'id': 1, 'seat_label': 'A1', 'price': 150, 'is_booked': False}],
        )
        with patch.object(bookora, 'get_db', return_value=FakeConnection(cursor)), \
             patch.object(bookora, 'business_now_naive', return_value=datetime(2026, 9, 5, 18, 59)):
            response = self.client.get('/api/seats/4')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['seats'][0]['seat_label'], 'A1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
