"""Create a controlled demo schedule and its initial seven days of shows.

This is a DEVELOPMENT / INITIAL-SEEDING TOOL. It deletes demo schedules,
shows, and seats, which can cascade into bookings; seed_common.py blocks that
against a database containing bookings unless explicitly overridden. It is not
the deployed daily scheduler. Production runs scripts/run_show_maintenance.py.
"""
import os
import random
import sys
from datetime import timedelta

# Ensure project root is on sys.path when executed directly
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from scripts import seed_common
except ImportError:
    import seed_common

from services.schedule_management import create_schedule
from services.show_maintenance import SHOW_WINDOW_DAYS, business_now, maintain_upcoming_shows


SHOW_TIMES = ['10:00:00', '13:00:00', '16:00:00', '19:00:00', '22:00:00']


seed_common.print_banner('Bookora demo show + seat generator')
conn = seed_common.connect()
cursor = conn.cursor(dictionary=True, buffered=True)

try:
    cursor.execute("SELECT id, title FROM movies")
    movies = cursor.fetchall()
    cursor.execute("SELECT id, name FROM theatres WHERE city = 'Ahmedabad'")
    theatres = cursor.fetchall()

    print(f"\nMovies: {len(movies)}")
    print(f"Theatres: {len(theatres)}")
    if not movies:
        print("\nNo movies in the database - run `python scripts/seed_movies.py` first.")
        print("Nothing was deleted.")
        sys.exit(1)
    if not theatres:
        print("\nNo Ahmedabad theatres - load database/database_schema.sql first.")
        print("Nothing was deleted.")
        sys.exit(1)

    seed_common.require_destructive_confirmation(
        conn, 'every row in `seats`, `shows` and `show_schedules` (cascades to bookings)'
    )

    # Intentional only for a fresh/local demo. The production maintenance
    # command never executes DELETE and leaves historical rows in place.
    cursor.execute("DELETE FROM seats")
    cursor.execute("DELETE FROM shows")
    cursor.execute("DELETE FROM show_schedules")
    print("\nCleared existing demo schedules, shows and seats.\n")

    today = business_now().date()
    end_date = today + timedelta(days=SHOW_WINDOW_DAYS - 1)
    schedule_count = 0
    for movie in movies:
        # This random selection is a demo convention only. It creates stable
        # source rules once, rather than a different random schedule per date.
        for theatre in random.sample(theatres, min(3, len(theatres))):
            for show_time in random.sample(SHOW_TIMES, min(3, len(SHOW_TIMES))):
                create_schedule(
                    conn,
                    movie_id=movie['id'], theatre_id=theatre['id'], show_time=show_time,
                    start_date=today, end_date=end_date, days_of_week='1111111', is_active=True,
                )
                schedule_count += 1

    result = maintain_upcoming_shows(conn, now=today)
    print(f"Created {schedule_count} demo schedule rule(s)")
    print(f"Generated {result['created_shows']} show(s)")
    print(f"Generated {result['created_seats']} seat(s)")

    cursor.execute("""
        SELECT m.title, COUNT(DISTINCT s.id) AS show_count
        FROM movies m LEFT JOIN shows s ON m.id = s.movie_id
        GROUP BY m.id LIMIT 5
    """)
    print("\nShows per movie (sample):")
    for row in cursor.fetchall():
        print(f"  - {row['title']}: {row['show_count']} shows")
except Exception:
    conn.rollback()
    raise
finally:
    cursor.close()
    conn.close()

print("\nShow demo seeding completed.")
