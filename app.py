"""
Flask Backend for Bookora - Clean Database-Driven API
Rebuilt booking system using MySQL only
"""
from flask import Flask, render_template, request, jsonify, send_from_directory, session, g
from flask_cors import CORS
import mysql.connector
from datetime import datetime, timedelta, date
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import json
from functools import wraps
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')
# Restrict CORS to the app's own local origins and allow credentials so the
# session cookie is honored on same-origin API calls (no wildcard-with-credentials).
CORS(app, supports_credentials=True, origins=[
    "http://localhost:5000",
    "http://127.0.0.1:5000",
])

# Application configuration (loaded from environment; safe defaults for local dev)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

# Secure signed-cookie session configuration.
# Flask signs the session cookie with SECRET_KEY, so the client cannot forge or
# alter the authenticated user id — the server is the source of truth for identity.
app.config['SESSION_COOKIE_HTTPONLY'] = True   # JS cannot read the session cookie (mitigates XSS token theft)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # cookie not sent on cross-site requests (mitigates CSRF)
# Only send the cookie over HTTPS in production. Controlled by env so local HTTP dev still works.
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() in ('true', '1', 'yes')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Email configuration
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_FROM = os.getenv('EMAIL_FROM', EMAIL_USER)

# Database connection helper
def get_db():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'bookora')
    )

# Phone number normalization helper
def normalize_phone(phone):
    """
    Normalize phone number to 10-digit format (no +91 prefix)
    Returns normalized phone or None if invalid
    """
    if not phone:
        return None
    
    # Convert to string and remove all whitespace
    phone = str(phone).strip().replace(' ', '').replace('-', '')
    
    # Remove +91 prefix if present
    if phone.startswith('+91'):
        phone = phone[3:]
    elif phone.startswith('91') and len(phone) == 12:
        phone = phone[2:]
    
    # Validate it's exactly 10 digits
    if len(phone) == 10 and phone.isdigit():
        return phone
    
    return None

# ============================================
# AUTHENTICATION HELPERS (server-side session)
# ============================================

def get_current_user():
    """
    Return the currently authenticated user based on the server-side session.

    Identity comes from session['user_id'], which is set only after a successful
    OTP verification / profile completion. The signed session cookie cannot be
    forged or altered by the client, so the server — not the request body/query —
    decides who the user is. Returns the user dict, or None if there is no valid
    session or the referenced user no longer exists.
    """
    # Resolve at most once per request.
    if 'current_user' in g:
        return g.current_user

    user_id = session.get('user_id')
    if not user_id:
        g.current_user = None
        return None

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, name, email, phone FROM users WHERE id = %s",
            (user_id,)
        )
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    # Session points at a user that no longer exists — clear the stale session.
    if not user:
        session.pop('user_id', None)

    g.current_user = user
    return user


def login_required(view):
    """
    Decorator that rejects unauthenticated requests with HTTP 401 and otherwise
    exposes the authenticated user as g.current_user to the wrapped view.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'message': 'Authentication required'}), 401
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped

# ============================================
# MOVIE APIs
# ============================================

@app.route('/api/movies/slug/<slug>', methods=['GET'])
def get_movie_by_slug(slug):
    """Get movie details by slug"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM movies WHERE slug = %s", (slug,))
        movie = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not movie:
            return jsonify({'success': False, 'message': 'Movie not found'}), 404
        
        return jsonify({'success': True, 'movie': movie}), 200
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/movies', methods=['GET'])
def get_all_movies():
    """Get all movies"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM movies WHERE status = 'now_showing' ORDER BY title")
        movies = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'movies': movies, 'count': len(movies)}), 200
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# SHOWS APIs
# ============================================

@app.route('/api/shows', methods=['GET'])
def get_shows():
    """Get shows for a movie on a specific date - accepts slug or movie_id"""
    try:
        # Accept either slug or movie_id
        slug = request.args.get('slug')
        movie_id = request.args.get('movie_id')
        date = request.args.get('date')
        
        if not date:
            return jsonify({'success': False, 'message': 'date parameter required'}), 400
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Resolve slug to movie_id if slug provided
        if slug and not movie_id:
            cursor.execute("SELECT id, title FROM movies WHERE slug = %s", (slug,))
            movie = cursor.fetchone()
            
            if not movie:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': f'Movie not found for slug: {slug}'}), 404
            
            movie_id = movie['id']
        
        if not movie_id:
            return jsonify({'success': False, 'message': 'slug or movie_id required'}), 400
        
        # Get shows with theatre information
        query = """
            SELECT 
                s.id as show_id,
                s.show_time,
                t.id as theatre_id,
                t.name as theatre_name,
                t.address as theatre_address,
                (SELECT COUNT(*) FROM seats WHERE show_id = s.id AND is_booked = 0) as available_seats,
                (SELECT COUNT(*) FROM seats WHERE show_id = s.id) as total_seats
            FROM shows s
            JOIN theatres t ON s.theatre_id = t.id
            WHERE s.movie_id = %s AND s.show_date = %s
            ORDER BY t.name, s.show_time
        """
        
        cursor.execute(query, (movie_id, date))
        shows = cursor.fetchall()
        
        # Group by theatre
        theatres = {}
        for show in shows:
            theatre_id = show['theatre_id']
            if theatre_id not in theatres:
                theatres[theatre_id] = {
                    'id': theatre_id,
                    'name': show['theatre_name'],
                    'address': show['theatre_address'],
                    'shows': []
                }
            
            occupancy_pct = ((show['total_seats'] - show['available_seats']) / show['total_seats'] * 100) if show['total_seats'] > 0 else 0
            
            # FIX: MySQL TIME columns are returned as timedelta objects
            # Convert timedelta to HH:MM string format
            show_time = show['show_time']
            if isinstance(show_time, timedelta):
                total_seconds = int(show_time.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                time_str = f"{hours:02d}:{minutes:02d}"
            else:
                # Fallback for datetime.time objects
                time_str = show_time.strftime('%H:%M')
            
            theatres[theatre_id]['shows'].append({
                'show_id': show['show_id'],
                'time': time_str,
                'available_seats': show['available_seats'],
                'occupancy': round(occupancy_pct, 1),
                'show_date': date  # Pass show_date for frontend validation
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'theatres': list(theatres.values())
        }), 200
        
    except Exception as e:
        print(f"❌ ERROR in /api/shows: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# SEATS APIs
# ============================================

@app.route('/api/seats/<int:show_id>', methods=['GET'])
def get_seats(show_id):
    """Get all seats for a show"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Get show details
        cursor.execute("""
            SELECT s.*, m.title as movie_title, t.name as theatre_name, t.address as theatre_address
            FROM shows s
            JOIN movies m ON s.movie_id = m.id
            JOIN theatres t ON s.theatre_id = t.id
            WHERE s.id = %s
        """, (show_id,))
        
        show = cursor.fetchone()
        
        if not show:
            return jsonify({'success': False, 'message': 'Show not found'}), 404
        
        # Check if show has already started (server-side validation)
        show_date = show['show_date']
        show_time = show['show_time']
        
        # Convert show_time (timedelta or time) to datetime
        if isinstance(show_time, timedelta):
            total_seconds = int(show_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            show_datetime = datetime.combine(show_date, datetime.min.time().replace(hour=hours, minute=minutes))
        else:
            show_datetime = datetime.combine(show_date, show_time)
        
        current_datetime = datetime.now()
        
        if current_datetime >= show_datetime:
            cursor.close()
            conn.close()
            return jsonify({
                'success': False, 
                'message': 'This show has already started and is no longer available for booking.'
            }), 400
        
        # Get seats
        cursor.execute("""
            SELECT id, seat_label, price, is_booked
            FROM seats
            WHERE show_id = %s
            ORDER BY seat_label
        """, (show_id,))
        
        seats = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # FIX: Handle timedelta for show_time (MySQL TIME columns)
        show_time = show['show_time']
        if isinstance(show_time, timedelta):
            total_seconds = int(show_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours:02d}:{minutes:02d}"
        else:
            time_str = show_time.strftime('%H:%M')
        
        return jsonify({
            'success': True,
            'show': {
                'id': show['id'],
                'movie_title': show['movie_title'],
                'theatre_name': show['theatre_name'],
                'theatre_address': show['theatre_address'],
                'show_date': show['show_date'].strftime('%Y-%m-%d'),
                'show_time': time_str
            },
            'seats': seats
        }), 200
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# AUTHENTICATION APIs
# ============================================

def send_email_otp(email, otp):
    """Send OTP email using SMTP - optimized for speed"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Your Bookora Verification Code'
        msg['From'] = EMAIL_FROM
        msg['To'] = email
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Inter', Arial, sans-serif; margin: 0; padding: 0; background-color: #FAF9F8; }}
                .container {{ max-width: 600px; margin: 40px auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(42, 37, 32, 0.08); }}
                .header {{ background: linear-gradient(135deg, #D4A59A 0%, #C89B8E 100%); padding: 40px 30px; text-align: center; }}
                .header h1 {{ color: white; margin: 0; font-size: 32px; font-weight: 600; letter-spacing: 1px; }}
                .content {{ padding: 40px 30px; }}
                .otp-box {{ background: #FAF9F8; border: 2px dashed #D4A59A; border-radius: 8px; padding: 30px; text-align: center; margin: 30px 0; }}
                .otp-code {{ font-size: 42px; font-weight: 700; color: #D4A59A; letter-spacing: 12px; margin: 0; }}
                .message {{ color: #2A2520; font-size: 16px; line-height: 1.6; margin: 20px 0; }}
                .footer {{ background: #FAF9F8; padding: 20px 30px; text-align: center; color: #8B7E74; font-size: 13px; }}
                .brand {{ color: #D4A59A; font-weight: 600; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎬 BOOKORA</h1>
                </div>
                <div class="content">
                    <p class="message">Hello!</p>
                    <p class="message">Your One-Time Password (OTP) to verify your account is:</p>
                    <div class="otp-box">
                        <p class="otp-code">{otp}</p>
                    </div>
                    <p class="message">This code is valid for <strong>10 minutes</strong>. Please do not share it with anyone.</p>
                    <p class="message">If you didn't request this code, please ignore this email.</p>
                </div>
                <div class="footer">
                    <p>© 2026 <span class="brand">Bookora</span> | Your Premium Movie Booking Experience</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        # Optimized timeout - 5 seconds max for faster response
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=5) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ OTP email sent to {email}")
        return True
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False

@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    """Send OTP to email and store in database"""
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400
        
        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        
        # Calculate expiry (10 minutes from now)
        expires_at = datetime.now() + timedelta(minutes=10)
        
        # Store OTP in database
        conn = get_db()
        cursor = conn.cursor()
        
        # Delete any existing OTPs for this email
        cursor.execute("DELETE FROM otp_verification WHERE identifier = %s", (email,))
        
        # Insert new OTP
        cursor.execute("""
            INSERT INTO otp_verification (identifier, otp, expires_at)
            VALUES (%s, %s, %s)
        """, (email, otp, expires_at))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # Send email
        if send_email_otp(email, otp):
            return jsonify({
                'success': True,
                'message': 'OTP sent successfully to your email'
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to send email. Please try again.'
            }), 500
        
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP and check if user exists"""
    try:
        data = request.get_json()
        identifier = data.get('email') or data.get('phone')
        otp = data.get('otp')
        contact_type = data.get('type', 'email')  # 'email' or 'phone'
        
        # Normalize phone identifier if it's a phone type
        if contact_type == 'phone' and identifier:
            normalized_phone = normalize_phone(identifier)
            if normalized_phone:
                identifier = normalized_phone
        
        if not identifier or not otp:
            return jsonify({'success': False, 'message': 'Identifier and OTP are required'}), 400
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Check OTP in database
        cursor.execute("""
            SELECT * FROM otp_verification 
            WHERE identifier = %s AND otp = %s AND expires_at > NOW()
        """, (identifier, otp))
        
        otp_record = cursor.fetchone()
        
        if not otp_record:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Invalid or expired OTP'}), 400
        
        # Delete used OTP
        cursor.execute("DELETE FROM otp_verification WHERE id = %s", (otp_record['id'],))
        conn.commit()
        
        # Check if user exists
        if contact_type == 'email':
            cursor.execute("SELECT * FROM users WHERE email = %s", (identifier,))
        else:
            cursor.execute("SELECT * FROM users WHERE phone = %s", (identifier,))
        
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if user:
            # User exists — establish the authenticated server-side session.
            # From here on the server derives identity from session['user_id'];
            # the client no longer needs to (and must not) supply its own user_id.
            session.permanent = True
            session['user_id'] = user['id']
            return jsonify({
                'success': True,
                'message': 'OTP verified successfully',
                'userExists': True,
                'user': {
                    'id': user['id'],
                    'name': user['name'],
                    'email': user['email'],
                    'phone': user['phone']
                }
            }), 200
        else:
            # New user - needs profile completion
            return jsonify({
                'success': True,
                'message': 'OTP verified successfully',
                'userExists': False,
                'identifier': identifier,
                'type': contact_type
            }), 200
            
    except Exception as e:
        print(f"Error verifying OTP: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/complete-profile', methods=['POST'])
def complete_profile():
    """Complete user profile after OTP verification"""
    try:
        data = request.get_json()
        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')
        primary_contact = data.get('primaryContact')  # 'email' or 'phone'
        
        # ONLY name is required - mobile and email are optional
        if not name:
            return jsonify({'success': False, 'message': 'Name is required'}), 400
        
        # Validate name format (letters and spaces only, 2-50 characters)
        import re
        name_pattern = r'^[A-Za-z][A-Za-z ]{1,49}$'
        if not re.match(name_pattern, name):
            return jsonify({'success': False, 'message': 'Invalid name format.'}), 400
        
        # Normalize phone number if provided
        if phone:
            normalized_phone = normalize_phone(phone)
            if not normalized_phone:
                return jsonify({'success': False, 'message': 'Invalid phone number format'}), 400
            phone = normalized_phone
        
        # Ensure at least one contact method exists (from OTP verification)
        if not email and not phone:
            return jsonify({'success': False, 'message': 'At least email or phone is required'}), 400
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Check for duplicate phone number
        if phone:
            cursor.execute("SELECT id FROM users WHERE phone = %s", (phone,))
            existing_user = cursor.fetchone()
            if existing_user:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'This mobile number is already registered with another account.'}), 400
        
        # Check for duplicate email
        if email:
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            existing_user = cursor.fetchone()
            if existing_user:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'This email is already registered with another account.'}), 400
        
        # Insert new user
        cursor.execute("""
            INSERT INTO users (name, email, phone, primary_contact_type)
            VALUES (%s, %s, %s, %s)
        """, (name, email, phone, primary_contact))
        
        user_id = cursor.lastrowid
        conn.commit()
        
        # Fetch created user
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()

        # New account created via a verified OTP flow — establish the session so
        # the server (not the client) tracks this authenticated user going forward.
        session.permanent = True
        session['user_id'] = user['id']

        return jsonify({
            'success': True,
            'message': 'Profile completed successfully',
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email'],
                'phone': user['phone']
            }
        }), 200
        
    except Exception as e:
        print(f"Error completing profile: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """Clear the authenticated server-side session (server-side sign-out)."""
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

# ============================================
# SAVED MOVIES APIs
# ============================================

@app.route('/api/saved-movies', methods=['GET'])
@login_required
def get_saved_movies():
    """Get all saved movies for the authenticated user"""
    try:
        user_id = g.current_user['id']
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT m.* FROM movies m
            INNER JOIN saved_movies sm ON m.id = sm.movie_id
            WHERE sm.user_id = %s
            ORDER BY sm.created_at DESC
        """, (user_id,))
        
        saved_movies = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'movies': saved_movies}), 200
    except Exception as e:
        print(f"Error fetching saved movies: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/save-movie', methods=['POST'])
@login_required
def save_movie():
    """Save a movie for the authenticated user"""
    try:
        data = request.get_json()
        user_id = g.current_user['id']
        movie_id = data.get('movie_id')

        if not movie_id:
            return jsonify({'success': False, 'message': 'Movie ID required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Insert; a duplicate (already saved) is fine and treated as success
        try:
            cursor.execute("""
                INSERT INTO saved_movies (user_id, movie_id)
                VALUES (%s, %s)
            """, (user_id, movie_id))
            conn.commit()
        except mysql.connector.IntegrityError:
            # Movie already saved for this user (UNIQUE constraint) - idempotent, ignore
            conn.rollback()
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Movie saved successfully'}), 200
    except Exception as e:
        print(f"Error saving movie: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/unsave-movie', methods=['POST'])
@login_required
def unsave_movie():
    """Remove a saved movie for the authenticated user"""
    try:
        data = request.get_json()
        user_id = g.current_user['id']
        movie_id = data.get('movie_id')

        if not movie_id:
            return jsonify({'success': False, 'message': 'Movie ID required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM saved_movies
            WHERE user_id = %s AND movie_id = %s
        """, (user_id, movie_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Movie unsaved successfully'}), 200
    except Exception as e:
        print(f"Error unsaving movie: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/check-saved/<int:movie_id>', methods=['GET'])
@login_required
def check_saved(movie_id):
    """Check if a movie is saved by the authenticated user"""
    try:
        user_id = g.current_user['id']
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) as count FROM saved_movies
            WHERE user_id = %s AND movie_id = %s
        """, (user_id, movie_id))
        
        result = cursor.fetchone()
        is_saved = result[0] > 0
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'is_saved': is_saved}), 200
    except Exception as e:
        print(f"Error checking saved status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# PAGE ROUTES (before catch-all)
# ============================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/movie/<slug>')
def movie_details(slug):
    return render_template('movie-details.html')

@app.route('/shows/<slug>')
def shows_page(slug):
    return render_template('shows.html')

@app.route('/seats/<int:show_id>')
def seats_page(show_id):
    return render_template('seat-selection.html')

@app.route('/profile')
def profile_page():
    return render_template('profile.html')

@app.route('/my-bookings')
def my_bookings_page():
    return render_template('my-bookings.html')

@app.route('/saved-movies')
def saved_movies_page():
    return render_template('saved-movies.html')

# ============================================
# PROFILE APIs
# ============================================

@app.route('/api/profile/update', methods=['PUT'])
@login_required
def update_profile():
    """Update the authenticated user's profile (name, and phone if currently NULL)"""
    try:
        data = request.json
        user_id = g.current_user['id']
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip() if 'phone' in data else None

        if not name:
            return jsonify({'success': False, 'message': 'Name is required'}), 400
        
        # Validate name format (letters and spaces only, 2-50 characters)
        import re
        name_pattern = r'^[A-Za-z][A-Za-z ]{1,49}$'
        if not re.match(name_pattern, name):
            return jsonify({'success': False, 'message': 'Invalid name format.'}), 400
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Normalize phone number if provided
        if phone:
            normalized_phone = normalize_phone(phone)
            if not normalized_phone:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'Invalid phone number format. Please enter a valid 10-digit mobile number.'}), 400
            phone = normalized_phone
        
        # Check current phone value
        cursor.execute("SELECT phone FROM users WHERE id = %s", (user_id,))
        current_user = cursor.fetchone()
        
        if not current_user:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Update name (always allowed)
        # Update phone ONLY if current phone is NULL and new phone is provided
        if phone and current_user['phone'] is None:
            # Check if phone number already exists in database
            cursor.execute("SELECT id FROM users WHERE phone = %s AND id != %s", (phone, user_id))
            existing_user = cursor.fetchone()
            if existing_user:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'This mobile number is already registered with another account.'}), 400
            
            # Allow adding phone number (one-time only)
            cursor.execute(
                "UPDATE users SET name = %s, phone = %s WHERE id = %s",
                (name, phone, user_id)
            )
        elif phone and current_user['phone'] is not None:
            # Reject attempt to change existing phone number
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Phone number cannot be changed once set'}), 400
        else:
            # Only update name
            cursor.execute(
                "UPDATE users SET name = %s WHERE id = %s",
                (name, user_id)
            )
        
        conn.commit()
        
        # Fetch updated user data
        cursor.execute("SELECT id, name, email, phone FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if user:
            return jsonify({'success': True, 'user': user})
        else:
            return jsonify({'success': False, 'message': 'User not found'}), 404
            
    except Exception as e:
        print(f"Error updating profile: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# BOOKINGS APIs
# ============================================

@app.route('/api/bookings', methods=['GET'])
@login_required
def get_user_bookings():
    """Get all bookings for the authenticated user.

    Identity is taken from the server-side session, NOT from the request. Any
    ?user_id= supplied by the client is ignored, which closes the IDOR where a
    user could read another user's bookings by changing the query parameter.
    """
    try:
        user_id = g.current_user['id']

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Get bookings with show and movie details
        query = """
            SELECT 
                b.id as booking_id,
                b.seat_ids,
                b.total_price,
                b.status,
                b.booking_date,
                s.id as show_id,
                s.show_date,
                s.show_time,
                m.id as movie_id,
                m.title as movie_title,
                m.poster_url,
                m.duration,
                m.certification,
                t.name as theatre_name,
                t.address as theatre_address
            FROM bookings b
            JOIN shows s ON b.show_id = s.id
            JOIN movies m ON s.movie_id = m.id
            JOIN theatres t ON s.theatre_id = t.id
            WHERE b.user_id = %s
            ORDER BY b.booking_date DESC
        """
        
        cursor.execute(query, (user_id,))
        bookings = cursor.fetchall()
        
        # Process seat_ids JSON and convert dates/times to strings
        for booking in bookings:
            seat_ids = json.loads(booking['seat_ids'])
            booking['seat_ids'] = seat_ids
            
            # Fetch seat details (labels, types, prices) for this booking
            if seat_ids:
                placeholders = ','.join(['%s'] * len(seat_ids))
                seat_query = f"""
                    SELECT id, seat_label, price
                    FROM seats
                    WHERE id IN ({placeholders})
                """
                cursor.execute(seat_query, tuple(seat_ids))
                seat_details = cursor.fetchall()
                
                # Convert Decimal prices to float for JSON serialization
                for seat in seat_details:
                    if 'price' in seat:
                        seat['price'] = float(seat['price'])
                
                booking['seat_details'] = seat_details
            else:
                booking['seat_details'] = []
            
            # Convert date to string
            if isinstance(booking.get('show_date'), date):
                booking['show_date'] = booking['show_date'].strftime('%Y-%m-%d')
            
            # Convert time (timedelta) to string
            if isinstance(booking.get('show_time'), timedelta):
                total_seconds = int(booking['show_time'].total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                booking['show_time'] = f"{hours:02d}:{minutes:02d}:00"
            
            # Convert booking_date to string
            if isinstance(booking.get('booking_date'), date):
                booking['booking_date'] = booking['booking_date'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(booking['booking_date'], 'strftime') else str(booking['booking_date'])
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'bookings': bookings})
        
    except Exception as e:
        print(f"Error fetching bookings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/cancel-booking', methods=['POST'])
@login_required
def cancel_booking():
    """Cancel a booking and release seats (only the owner's own booking)."""
    try:
        data = request.json
        booking_id = data.get('booking_id')
        user_id = g.current_user['id']

        if not booking_id:
            return jsonify({'success': False, 'message': 'Booking ID required'}), 400
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Verify booking belongs to user and is confirmed
        cursor.execute("""
            SELECT b.*, s.show_date, s.show_time 
            FROM bookings b
            JOIN shows s ON b.show_id = s.id
            WHERE b.id = %s AND b.user_id = %s AND b.status = 'CONFIRMED'
        """, (booking_id, user_id))
        
        booking = cursor.fetchone()
        
        if not booking:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Booking not found or already cancelled'}), 404
        
        # Check if show is in the future
        show_datetime = datetime.combine(booking['show_date'], 
                                        datetime.strptime(str(booking['show_time']), '%H:%M:%S').time())
        
        if show_datetime <= datetime.now():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Cannot cancel past bookings'}), 400
        
        # Update booking status to CANCELLED
        cursor.execute("UPDATE bookings SET status = 'CANCELLED' WHERE id = %s", (booking_id,))
        
        # Release seats - update seats to available
        seat_ids = json.loads(booking['seat_ids'])

        for seat_id in seat_ids:
            cursor.execute(
                "UPDATE seats SET is_booked = FALSE, booked_by = NULL, booked_at = NULL WHERE id = %s",
                (seat_id,)
            )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Booking cancelled successfully'})
        
    except Exception as e:
        print(f"Error cancelling booking: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/create-booking', methods=['POST'])
@login_required
def create_booking():
    """Create a new booking with server-side price calculation and row locking."""
    conn = None
    cursor = None
    try:
        data = request.json or {}
        user_id = g.current_user['id']
        show_id = data.get('show_id')
        seat_ids = data.get('seat_ids', [])
        # NOTE: any client-supplied total_price is intentionally ignored.
        # The price is always calculated on the server from the seats table.
        # user_id also comes from the session, never from the request body.

        if not show_id or not seat_ids:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400

        # Validate and de-duplicate seat ids (must be integers)
        try:
            seat_ids = [int(s) for s in seat_ids]
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Invalid seat selection'}), 400
        seat_ids = list(dict.fromkeys(seat_ids))  # de-dupe, preserve order
        if not seat_ids:
            return jsonify({'success': False, 'message': 'No seats selected'}), 400

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Run the whole booking as a single transaction so the availability
        # check and the seat update are atomic (prevents double-booking).
        conn.start_transaction()

        # NOTE: the user's existence is already guaranteed by get_current_user()
        # (login_required), so no separate user lookup is needed here.

        # Get show details to validate timing
        cursor.execute("SELECT show_date, show_time FROM shows WHERE id = %s", (show_id,))
        show = cursor.fetchone()
        if not show:
            conn.rollback()
            return jsonify({'success': False, 'message': 'Show not found'}), 404

        # Reject bookings for shows that have already started (server-side)
        show_date = show['show_date']
        show_time = show['show_time']
        if isinstance(show_time, timedelta):
            total_seconds = int(show_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            show_datetime = datetime.combine(
                show_date, datetime.min.time().replace(hour=hours, minute=minutes)
            )
        else:
            show_datetime = datetime.combine(show_date, show_time)

        if datetime.now() >= show_datetime:
            conn.rollback()
            return jsonify({
                'success': False,
                'message': 'This show has already started and is no longer available for booking.'
            }), 400

        # Lock the requested seats FOR UPDATE so concurrent requests cannot
        # grab the same seats between the availability check and the update.
        placeholders = ','.join(['%s'] * len(seat_ids))
        cursor.execute(
            f"""SELECT id, price, is_booked
                FROM seats
                WHERE show_id = %s AND id IN ({placeholders})
                FOR UPDATE""",
            (show_id, *seat_ids)
        )
        rows = cursor.fetchall()

        # Every requested seat must exist and belong to this show
        found_ids = {row['id'] for row in rows}
        missing = [s for s in seat_ids if s not in found_ids]
        if missing:
            conn.rollback()
            return jsonify({
                'success': False,
                'message': f'Seat(s) not available for this show: {missing}'
            }), 404

        # None of the requested seats may already be booked
        already_booked = [row['id'] for row in rows if row['is_booked']]
        if already_booked:
            conn.rollback()
            return jsonify({
                'success': False,
                'message': f'Seat(s) already booked: {already_booked}'
            }), 409

        # Authoritative price: sum of the seat prices straight from the database
        total_price = sum(row['price'] for row in rows)

        # Mark the seats as booked and record who booked them and when
        cursor.execute(
            f"""UPDATE seats
                SET is_booked = TRUE, booked_by = %s, booked_at = NOW()
                WHERE show_id = %s AND id IN ({placeholders})""",
            (user_id, show_id, *seat_ids)
        )

        # Create the booking using the server-calculated price
        cursor.execute(
            """INSERT INTO bookings (user_id, show_id, seat_ids, total_price, status)
               VALUES (%s, %s, %s, %s, 'CONFIRMED')""",
            (user_id, show_id, json.dumps(seat_ids), total_price)
        )
        booking_id = cursor.lastrowid

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Booking confirmed successfully',
            'booking_id': booking_id,
            'total_price': float(total_price)
        })

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"Error creating booking: {e}")
        return jsonify({'success': False, 'message': 'Could not complete booking. Please try again.'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ============================================
# STATIC FILE SERVING (last - catch-all)
# ============================================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve files from static folder"""
    return send_from_directory('static', filename)

@app.route('/<path:filename>')
def serve_root_files(filename):
    """Serve CSS/JS files from root"""
    # Only serve actual files, not routes
    if '.' in filename and os.path.isfile(filename):
        return send_from_directory('.', filename)
    return "File not found", 404

# Favicon route to prevent 404 errors
@app.route('/favicon.ico')
def favicon():
    return '', 204  # No Content response

if __name__ == '__main__':
    print("🚀 Starting Bookora Server...")
    print("📍 Database: MySQL (bookora)")
    print("🎬 Movie system: Active")
    print("🎫 Booking system: Database-driven")
    app.run(debug=DEBUG, port=int(os.getenv('PORT', 5000)))
