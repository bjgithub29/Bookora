"""
Seed movies from movies-data.json into MySQL database
Converts string IDs to slugs and properly formats data
"""
import mysql.connector
import json
from datetime import datetime

# Database connection
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='bookora'
)
cursor = conn.cursor()

# Load movies from JSON
with open('movies-data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    movies = data.get('movies', [])

print(f"📥 Found {len(movies)} movies in JSON file\n")

# Clear existing movies
cursor.execute("DELETE FROM movies")
print("🗑️  Cleared existing movies\n")

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
        print(f"✅ Inserted: {movie.get('title')} (slug: {slug})")
        
    except Exception as e:
        print(f"❌ Error inserting {movie.get('title')}: {e}")

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

cursor.close()
conn.close()

print("\n✅ Seeding completed!")
