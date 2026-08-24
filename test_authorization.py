"""
Authorization / IDOR regression tests for Bookora.

These tests verify the server-side session authentication and — most importantly —
that every user-owned endpoint derives the acting user from the signed session
cookie, NEVER from a client-supplied user_id (body, query string, or URL path).
That is the fix for the IDOR where GET /api/bookings?user_id=2 could be changed to
?user_id=1 to read another user's data.

The database layer (app.get_db) is mocked, so these tests require Flask but do
NOT need a running MySQL server. Each test drives a real Flask request through
the real route + login_required decorator, then asserts which user id the SQL
was actually bound to.

Run from the project root:

    python -m unittest test_authorization -v
    # or, if you use pytest:
    pytest test_authorization.py -v
"""
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from decimal import Decimal

import app as bookora


class FakeCursor:
    """
    Minimal MySQL-cursor stand-in. It records every (sql, params) pair passed to
    execute() and returns canned rows chosen by inspecting the SQL text — enough
    to exercise the authorization logic without a real database.
    """

    def __init__(self, dictionary=False):
        self.dictionary = dictionary
        self.lastrowid = 4242
        self.calls = []          # [(sql, params), ...]
        self._last_sql = ""
        self._last_params = ()

    def execute(self, sql, params=()):
        self._last_sql = sql
        self._last_params = tuple(params) if params else ()
        self.calls.append((sql, self._last_params))

    def fetchone(self):
        sql = self._last_sql
        params = self._last_params
        # update_profile's "is a phone already set?" probe (select phone only).
        if "SELECT phone FROM users" in sql:
            return {'phone': None}
        # get_current_user() + profile final re-fetch — the session user exists.
        if "FROM users WHERE id" in sql:
            uid = params[0] if params else None
            return {'id': uid, 'name': 'Test User',
                    'email': 'user%s@example.com' % uid, 'phone': None}
        # create_booking show-timing lookup — a show safely in the future.
        if "FROM shows WHERE id" in sql:
            return {'show_date': date.today() + timedelta(days=2),
                    'show_time': timedelta(hours=19)}
        # check-saved uses a non-dictionary cursor: result[0]
        if "COUNT(*)" in sql:
            return (0,)
        # cancel-booking ownership probe — pretend no match (endpoint 404s);
        # the test asserts on the bound PARAMS, not the outcome.
        if "FROM bookings" in sql and "WHERE b.id" in sql:
            return None
        return None

    def fetchall(self):
        sql = self._last_sql
        params = self._last_params
        # create_booking seat lock: params == (show_id, *seat_ids)
        if "FOR UPDATE" in sql:
            seat_ids = params[1:]
            return [{'id': sid, 'price': Decimal('100.00'), 'is_booked': 0}
                    for sid in seat_ids]
        # bookings list / saved-movies list, etc.
        return []

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.cursors = []

    def cursor(self, dictionary=False):
        c = FakeCursor(dictionary=dictionary)
        self.cursors.append(c)
        return c

    def start_transaction(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        bookora.app.config['TESTING'] = True
        self.client = bookora.app.test_client()
        self._patcher = patch.object(bookora, 'get_db')
        self.mock_get_db = self._patcher.start()
        self.conn = FakeConn()
        self.mock_get_db.return_value = self.conn

    def tearDown(self):
        self._patcher.stop()

    # ---- helpers -----------------------------------------------------------

    def login_as(self, user_id):
        """Seed a signed session cookie for the given user id."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id

    def recorded(self):
        """All (sql, params) executed across every cursor opened this request."""
        out = []
        for c in self.conn.cursors:
            out.extend(c.calls)
        return out

    def params_where(self, predicate):
        return [p for (sql, p) in self.recorded() if predicate(sql)]

    # ---- 1. Unauthenticated requests are rejected with 401 -----------------

    def test_bookings_requires_auth(self):
        self.assertEqual(self.client.get('/api/bookings').status_code, 401)

    def test_create_booking_requires_auth(self):
        resp = self.client.post('/api/create-booking',
                                 json={'show_id': 1, 'seat_ids': [1]})
        self.assertEqual(resp.status_code, 401)

    def test_cancel_booking_requires_auth(self):
        resp = self.client.post('/api/cancel-booking', json={'booking_id': 1})
        self.assertEqual(resp.status_code, 401)

    def test_profile_update_requires_auth(self):
        resp = self.client.put('/api/profile/update', json={'name': 'X'})
        self.assertEqual(resp.status_code, 401)

    def test_saved_movies_requires_auth(self):
        self.assertEqual(self.client.get('/api/saved-movies').status_code, 401)

    # ---- 2 & 3. Bookings are scoped to the SESSION user, not ?user_id= -----

    def test_bookings_ignores_query_user_id_uses_session_user2(self):
        """IDOR fix: logged in as 2, ?user_id=1 must still query user 2."""
        self.login_as(2)
        resp = self.client.get('/api/bookings?user_id=1')  # attacker tampering
        self.assertEqual(resp.status_code, 200)
        q = self.params_where(lambda s: "FROM bookings b" in s)
        self.assertTrue(q, "bookings query never ran")
        self.assertEqual(q[0][0], 2, "bookings must be filtered by session user (2)")

    def test_bookings_user1_scoped_to_user1(self):
        self.login_as(1)
        resp = self.client.get('/api/bookings?user_id=2')  # attacker tampering
        self.assertEqual(resp.status_code, 200)
        q = self.params_where(lambda s: "FROM bookings b" in s)
        self.assertEqual(q[0][0], 1, "bookings must be filtered by session user (1)")

    # ---- 4. Cancel binds the ownership check to the session user -----------

    def test_cancel_uses_session_user_not_body(self):
        self.login_as(2)
        self.client.post('/api/cancel-booking',
                         json={'booking_id': 55, 'user_id': 1})  # injected user_id
        own = self.params_where(lambda s: "WHERE b.id" in s)
        self.assertTrue(own, "ownership lookup never ran")
        self.assertEqual(own[0], (55, 2),
                         "cancel must check ownership against session user (2)")

    # ---- 5. Profile update binds to the session user ----------------------

    def test_profile_update_uses_session_user_not_body(self):
        self.login_as(2)
        resp = self.client.put('/api/profile/update',
                               json={'name': 'Attacker', 'user_id': 1})
        self.assertEqual(resp.status_code, 200)
        upd = self.params_where(lambda s: s.strip().startswith("UPDATE users"))
        self.assertTrue(upd, "profile UPDATE never ran")
        self.assertEqual(upd[0][-1], 2, "profile update must target session user (2)")

    # ---- 6. Saved movies scoped to the session user -----------------------

    def test_saved_movies_uses_session_user(self):
        self.login_as(2)
        resp = self.client.get('/api/saved-movies')
        self.assertEqual(resp.status_code, 200)
        q = self.params_where(lambda s: "FROM movies m" in s and "saved_movies" in s)
        self.assertTrue(q, "saved-movies query never ran")
        self.assertEqual(q[0][0], 2)

    # ---- 7. Create-booking records the SESSION user as owner --------------

    def test_create_booking_owner_is_session_user_not_body(self):
        self.login_as(2)
        resp = self.client.post('/api/create-booking',
                                json={'user_id': 1, 'show_id': 9, 'seat_ids': [10, 11]})
        self.assertEqual(resp.status_code, 200)
        ins = self.params_where(lambda s: "INSERT INTO bookings" in s)
        self.assertTrue(ins, "booking INSERT never ran")
        self.assertEqual(ins[0][0], 2, "booking must be owned by session user (2)")
        seats = self.params_where(lambda s: s.strip().startswith("UPDATE seats"))
        self.assertTrue(seats, "seat UPDATE never ran")
        self.assertEqual(seats[0][0], 2, "seats must be booked_by session user (2)")

    # ---- Logout clears the server-side session ----------------------------

    def test_logout_clears_session(self):
        self.login_as(2)
        self.assertEqual(self.client.post('/api/logout').status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn('user_id', sess)


if __name__ == '__main__':
    unittest.main(verbosity=2)
