"""
Generate show schedules for all movies across Ahmedabad theatres
Creates realistic show times for the next 7 days
"""
import mysql.connector
from datetime import datetime, timedelta

# Database connection
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='bookora'
)
cursor = conn.cursor(dictionary=True)

# Show times per day
SHOW_TIMES = ['10:00:00', '13:00:00', '16:00:00', '19:00:00', '22:00:00']

# Get all movies
cursor.execute("SELECT id, title FROM movies")
movies = cursor.fetchall()

# Get all theatres in Ahmedabad
cursor.execute("SELECT id, name FROM theatres WHERE city = 'Ahmedabad'")
theatres = cursor.fetchall()

print(f"📽️  Movies: {len(movies)}")
print(f"🏛️  Theatres: {len(theatres)}")

# Clear existing shows and seats
cursor.execute("DELETE FROM seats")
cursor.execute("DELETE FROM shows")
print("🗑️  Cleared existing shows and seats\n")

# Generate shows for next 7 days
today = datetime.now().date()
show_count = 0
seat_count = 0

for day_offset in range(7):
    show_date = today + timedelta(days=day_offset)
    
    for movie in movies:
        # Each movie shows in 2-3 random theatres per day
        import random
        selected_theatres = random.sample(theatres, min(3, len(theatres)))
        
        for theatre in selected_theatres:
            # Each theatre shows 2-3 showtimes per movie per day
            selected_times = random.sample(SHOW_TIMES, min(3, len(SHOW_TIMES)))
            
            for show_time in selected_times:
                # Insert show
                cursor.execute("""
                    INSERT INTO shows (movie_id, theatre_id, show_date, show_time)
                    VALUES (%s, %s, %s, %s)
                """, (movie['id'], theatre['id'], show_date, show_time))
                
                show_id = cursor.lastrowid
                show_count += 1
                
                # Generate seats for this show
                # Standard layout: Rows A-J, Seats 1-12
                seat_prices = {
                    'A': 150, 'B': 150, 'C': 150,  # Front - cheaper
                    'D': 200, 'E': 200, 'F': 200,  # Middle - regular
                    'G': 250, 'H': 250,             # Back - premium
                    'I': 300, 'J': 300              # VIP - most expensive
                }
                
                for row in seat_prices.keys():
                    for seat_num in range(1, 13):  # 12 seats per row
                        seat_label = f"{row}{seat_num}"
                        price = seat_prices[row]

                        # All seats start available; bookings are created via the app
                        is_booked = False

                        cursor.execute("""
                            INSERT INTO seats (show_id, seat_label, price, is_booked)
                            VALUES (%s, %s, %s, %s)
                        """, (show_id, seat_label, price, is_booked))
                        
                        seat_count += 1

conn.commit()

print(f"✅ Generated {show_count} shows")
print(f"✅ Generated {seat_count} seats")

# Show summary
cursor.execute("""
    SELECT 
        m.title,
        COUNT(DISTINCT s.id) as show_count
    FROM movies m
    LEFT JOIN shows s ON m.id = s.movie_id
    GROUP BY m.id
    LIMIT 5
""")

print("\n📊 Shows per movie (sample):")
for row in cursor.fetchall():
    print(f"   - {row['title']}: {row['show_count']} shows")

cursor.close()
conn.close()

print("\n✅ Show generation completed!")
