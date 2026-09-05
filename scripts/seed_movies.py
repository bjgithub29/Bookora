"""
Seed movies from movies-data.json into MySQL database
Converts string IDs to slugs and properly formats data

DEVELOPMENT / INITIAL-SEEDING TOOL. This deletes every row in `movies`, which
cascades into shows, seats and bookings, so seed_common.py refuses to run
against a database that already contains bookings.

Usage:
    python scripts/seed_movies.py                           # asks for confirmation
    python scripts/seed_movies.py --yes                     # unattended, empty database only
    python scripts/seed_movies.py --force-destroy-bookings  # allows a database with bookings
"""
import json
import os
import sys

# Ensure project root is on sys.path when executed directly
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from scripts import seed_common
except ImportError:
    import seed_common

seed_common.print_banner('Bookora movie seeder')

# Load movies from JSON before touching the database: a missing or empty file
# should not cost you the movies table.
json_path = os.path.join(_PROJECT_ROOT, 'movies-data.json')
with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)
    movies = data.get('movies', [])

print(f"\n📥 Found {len(movies)} movies in JSON file")

if not movies:
    print("❌ movies-data.json contains no movies - leaving the database untouched.")
    sys.exit(1)

conn = seed_common.connect()
cursor = conn.cursor()

try:
    seed_common.require_destructive_confirmation(
        conn, 'every row in `movies` (cascades to shows, seats and bookings)'
    )

    # Clear existing movies
    cursor.execute("DELETE FROM movies")
    print("\n🗑️  Cleared existing movies\n")

    inserted = 0
    failed = 0

    # Insert each movie
    for movie in movies:
        try:
            sql = """
            INSERT INTO movies (slug, title, description, poster_url, banner_url, duration,
                              language, genre, release_date, status, certification, director, cast, trailer_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            # Use existing ID as slug
            slug = movie.get('id', '').lower().replace(' ', '_')

            values = (
                slug,
                movie.get('title'),
                movie.get('description', ''),
                f"/static/posters/{movie.get('poster', '')}" if movie.get('poster') else '',
                f"/static/banners/{movie.get('banner', '')}" if movie.get('banner') else '',
                movie.get('duration', 120),
                ', '.join(movie.get('language', [])) if isinstance(movie.get('language'), list) else movie.get('language', ''),
                ', '.join(movie.get('genre', [])) if isinstance(movie.get('genre'), list) else movie.get('genre', ''),
                movie.get('releaseDate', '2026-01-01'),
                movie.get('status', 'now_showing'),
                movie.get('rating', 'U/A'),
                movie.get('director', ''),
                ', '.join(movie.get('cast', [])) if isinstance(movie.get('cast'), list) else movie.get('cast', ''),
                movie.get('trailer', '')
            )

            cursor.execute(sql, values)

        except Exception as e:
            # The insert is what can fail; keep the reporting outside the guarded
            # block so a printing problem is never reported as an insert error.
            failed += 1
            print(f"❌ Error inserting {movie.get('title')}: {e}")
            continue

        inserted += 1
        print(f"✅ Inserted: {movie.get('title')} (slug: {slug})")

    conn.commit()

    # Verify
    cursor.execute("SELECT COUNT(*) FROM movies")
    count = cursor.fetchone()[0]
    print(f"\n📊 Total movies in database: {count}")

    cursor.execute("SELECT id, slug, title FROM movies LIMIT 5")
    movies_in_db = cursor.fetchall()
    print("\n🎬 Sample movies:")
    for movie in movies_in_db:
        print(f"   - [ID: {movie[0]}] {movie[2]} (slug: {movie[1]})")

except Exception:
    conn.rollback()
    raise
finally:
    cursor.close()
    conn.close()

if failed:
    print(f"\n⚠️  Seeding finished with {failed} failed insert(s), {inserted} succeeded.")
    print("   Next step: python scripts/seed_shows.py")
    sys.exit(1)

print(f"\n✅ Seeding completed! ({inserted} movies)")
print("   Next step: python scripts/seed_shows.py")
