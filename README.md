# Bookora — Movie Ticket Booking Platform

> A full-stack movie ticketing web application featuring passwordless email-OTP authentication, transactional seat reservations with row-level locking, server-authoritative pricing, and an automated rolling 7-day show schedule generation engine.

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-3.0-000000?logo=flask&logoColor=white">
  <img alt="MySQL" src="https://img.shields.io/badge/MySQL-MariaDB-4479A1?logo=mysql&logoColor=white">
  <img alt="Gunicorn" src="https://img.shields.io/badge/Gunicorn-23.0-499848?logo=gunicorn&logoColor=white">
  <img alt="Bootstrap" src="https://img.shields.io/badge/Bootstrap-5.3-7952B3?logo=bootstrap&logoColor=white">
</p>

---

## 1. Overview

**Bookora** is a production-hardened cinema ticketing platform built with Python, Flask, and MySQL/MariaDB. Users authenticate without passwords using time-limited, rate-limited email one-time passwords (OTPs). The application provides an interactive, responsive movie discovery experience: browsing now-showing films, exploring theatre showtimes, selecting seats on an auditorium map with tiered pricing, and completing bookings securely. The backend maintains strict server-side ownership of user identity, prices all transactions directly from database records, prevents concurrency race conditions using transactional row locks, and automatically generates future show instances across a 7-day rolling window.

---

## 2. Core Features

- **Movie Discovery & Catalog**: Browse now-showing titles complete with posters, banners, trailers, certification, duration, genre, and cast details.
- **Theatre & Showtime Browsing**: View movie listings across venues with dynamic date selection and automatic filtering of past/started shows.
- **Passwordless Email-OTP Authentication**: Frictionless login via 6-digit cryptographic OTPs dispatched over SMTP, backed by brute-force protections, cooldown intervals, and server-side verification proofs.
- **Secure Server-Side Sessions**: Cryptographically signed session cookies (`HttpOnly`, `SameSite=Lax`, `Secure` in production) ensure identity is never client-injected.
- **Interactive Auditorium Seat Selection**: Real-time seat availability map with tiered pricing (Regular, Premium, VIP) and visual states for available, selected, and reserved seats.
- **Transactional Booking Engine**: Atomic seat reservations using `SELECT ... FOR UPDATE` row locks to eliminate double-booking race conditions.
- **Booking Management & Cancellations**: View confirmed bookings and execute owner-scoped cancellations that safely return seats to available inventory.
- **Saved Movies (Bookmarks)**: Save favorite movies to personal watchlists with database-level uniqueness.
- **User Profile Management**: Manage contact details and personal profile attributes.
- **Responsive Web Design**: Unified breakpoint ladder providing touch-friendly, accessible layouts on mobile phones, tablets, and desktops.
- **Recurring Show Schedules**: Operator-managed schedule rules (`show_schedules`) defining movie, theatre, showtime, date ranges, and weekday bitmasks.
- **Rolling 7-Day Show Maintenance**: Idempotent maintenance engine maintaining a continuous window of `today + next 6 days` show instances and seat layouts.

---

## 3. Technical Stack

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend Framework** | Python 3.10+ / [Flask 3.0](https://flask.palletsprojects.com/) | Core application routing, REST API, and server-side rendering |
| **WSGI Production Server** | [Gunicorn 23.0](https://gunicorn.org/) | Pre-fork worker WSGI HTTP server (`Procfile` entrypoint) |
| **Database** | MySQL 8.0+ / MariaDB 10.4+ | Relational schema, transactional row locking, and foreign key integrity |
| **DB Driver & Pooling** | `mysql-connector-python 8.2` | Connection pooling (`MySQLConnectionPool`) and buffered cursors |
| **Template Engine** | Jinja2 | Server-rendered HTML pages |
| **Frontend** | Vanilla JavaScript (ES6+), HTML5, CSS3 | Clean, framework-free client logic using relative `fetch()` requests |
| **UI Components & Icons** | Bootstrap 5.3, Font Awesome 6 | Responsive grid, interactive modals, and iconography |
| **Timezone Management** | `tzdata 2025.2` / `zoneinfo` | Explicit `Asia/Kolkata` cinema business clock calculations |
| **Configuration** | `python-dotenv 1.0` | Environment variable isolation |
| **Testing** | Python standard library `unittest` | Automated unit test suite (50 verified passing tests) |

---

## 4. Architecture Overview

Bookora follows a clean, single-origin three-tier architecture:

```text
┌──────────────────────────────────────────────────────────┐
│                      Client Browser                      │
│      Vanilla JS + HTML5 + CSS3 + Bootstrap 5.3 Modals    │
│      All requests use same-origin relative paths (/api)  │
└────────────────────────────┬─────────────────────────────┘
                             │  HTTP / HTTPS
                             ▼
┌──────────────────────────────────────────────────────────┐
│                   Flask Application                      │
│  - Signed Session Cookie Validation                      │
│  - Route Controllers & Error Handlers                    │
│  - REST API Endpoints (/api/...)                         │
│  - Connection Pool Management (MySQLConnectionPool)      │
│  - Scheduling Domain Logic & Validators                  │
└────────────────────────────┬─────────────────────────────┘
                             │  TCP (Optional TLS/SSL)
                             ▼
┌──────────────────────────────────────────────────────────┐
│              Relational Database (MySQL / MariaDB)       │
│  - 9 Structured Tables with Foreign Keys & Unique Keys   │
│  - Atomic Transactions with `FOR UPDATE` Seat Locks      │
│  - Recurring Schedule Rules (show_schedules)             │
│  - Generated Show & Seat Instances                       │
└──────────────────────────────────────────────────────────┘
```

### Production Architecture
In a cloud deployment:
1. **Web Traffic**: Client requests terminate at a secure reverse proxy/load balancer over HTTPS and are forwarded to the **Gunicorn** WSGI process cluster.
2. **Database**: Connections are routed to a **managed cloud relational database** (MySQL 8.0+ / MariaDB 10.4+) over encrypted TLS/SSL.
3. **Show Maintenance**: An automated **cloud scheduler / cron worker** runs headless maintenance daily (`python scripts/run_show_maintenance.py`), keeping the rolling 7-day show window up to date independently of user web requests.

---

## 5. Security & Authorization

Bookora enforces defensive security principles across all layers:

- **Server-Authoritative Identity**: The server extracts the acting user strictly from `session['user_id']` via `@login_required` and `get_current_user()`. Client-supplied user IDs in query parameters or request bodies are completely ignored.
- **IDOR Protection**: Bookings, cancellations, profile edits, and saved movies are strictly filtered by the authenticated user's session identifier.
- **Server-Side Pricing**: The backend calculates total booking amounts by querying seat prices directly from `seats.price`. Any client-submitted price in the payload is ignored.
- **Concurrency & Race Condition Prevention**: Booking creation begins an explicit database transaction and applies `SELECT ... FOR UPDATE` to lock requested seats, preventing simultaneous double-booking.
- **Cryptographic OTP Session Proofs**: Profile completion (`POST /api/complete-profile`) requires a signed server-side verification proof generated during `POST /api/verify-otp`. An attacker cannot register an unverified email or forge identities.
- **Multi-Layered Rate Limiting & Cooldown**:
  - Per-IP and per-identifier sliding window limits for OTP dispatch and verification.
  - Cluster-wide 45-second resend cooldown anchored on `otp_verification.created_at` in MySQL.
  - Brute-force lockout: 5 failed verification attempts invalidate the code in the database.
- **Secure Cookie Configuration**: Session cookies are configured with `HttpOnly=True`, `SameSite=Lax`, and `Secure=True` in production (`not DEBUG`).
- **Generic Production Error Responses**: Unhandled exceptions are logged server-side with full tracebacks, while clients receive sanitized generic messages (`{"success": false, "message": "Something went wrong. Please try again."}`).
- **No Root File Leak**: Dangerous root catch-all routes are eliminated. Sensitive files (`.env`, `.git`, application source, SQL backups) cannot be read via HTTP.

---

## 6. Show Scheduling Architecture

Future shows are governed by an operator-managed source of truth:

```text
show_schedules (Operator recurring rules)
       │
       ▼
show_maintenance (Engine runs via scripts/run_show_maintenance.py)
       │
       ▼
shows (Dated instances for today through today + 6 days)
       │
       ▼
seats (120 seats per show: Rows A-J, Columns 1-12)
       │
       ▼
bookings (Customer purchases tied to show and seat IDs)
```

### Key Principles:
- **Rolling Window**: Calculates `today` through `today + 6 days` in `Asia/Kolkata` time, ensuring timezone independence from the host server.
- **Idempotency & Duplicate Prevention**: Uniqueness is enforced by database constraints:
  - `shows`: Composite unique key `(movie_id, theatre_id, show_date, show_time)`
  - `seats`: Composite unique key `(show_id, seat_label)`
- **Historical Preservation**: Past shows and booked seats are preserved permanently for accounting and audit integrity.
- **Role of Seed Scripts**: `scripts/seed_movies.py` and `scripts/seed_shows.py` are destructive development/demo initialization tools with interactive safety gates. They are **not** used for daily production show generation; production relies on `scripts/run_show_maintenance.py`.

---

## 7. Testing

The repository includes a comprehensive unit test suite covering domain logic, schedule overlap algorithms, rolling window generation, show availability, and authorization boundaries:

```bash
python -m unittest discover -s tests -v
# Or run specific test modules:
python -m unittest tests.test_schedule_management tests.test_show_maintenance tests.test_show_availability tests.test_authorization -v
```

### Verified Test Results:
- **`test_schedule_management`**: 23 tests passing (field validation, weekday bitmasks, range overlaps, deactivation).
- **`test_show_maintenance`**: 12 tests passing (rolling window generation, idempotency, seat creation, legacy show claiming).
- **`test_show_availability`**: 3 tests passing (server-side started show cutoff, seat selection availability).
- **`test_authorization`**: 12 tests passing (login enforcement, session scoping, IDOR protection, logout cleanup).
- **Total**: **50 tests passing (0 failures, 0 errors)**.

---

## 8. Project Structure

```text
Bookora/
├── app.py                          # Flask backend: routing, REST API, auth & connection pool
├── requirements.txt                # Production Python dependencies
├── Procfile                        # Gunicorn start command for PaaS / container deployments
├── .env.example                    # Environment variable template with documentation
├── .gitignore                      # Git exclusion rules for backups, .venv, and secrets
├── README.md                       # Comprehensive platform documentation (this file)
├── SETUP.md                        # Step-by-step local setup and troubleshooting guide
├── movies-data.json                # Seed movie catalog (titles, descriptions, cast, posters)
│
├── database/                       # Database schema definition and migration scripts
│   ├── database_schema.sql         # Canonical DDL: tables, indexes, constraints, and venue seed
│   └── migrate_show_scheduling.py  # Idempotent release migration script for schema updates
│
├── services/                       # Core domain business logic and background engines
│   ├── __init__.py                 # Services package initialization
│   ├── schedule_management.py     # Schedule rule validation, overlap prevention & transactions
│   └── show_maintenance.py         # Rolling-window maintenance engine for shows and seats
│
├── scripts/                        # Operational CLIs, scheduled jobs, and demo seeders
│   ├── run_show_maintenance.py     # Headless CLI entrypoint for daily scheduled maintenance
│   ├── seed_common.py              # Shared database connection helper & destructive action safety gates
│   ├── seed_movies.py              # Development script to load movies from JSON
│   └── seed_shows.py               # Development script to seed demo schedule rules and shows
│
├── tests/                          # Automated unit test suites (50 tests passing)
│   ├── __init__.py                 # Tests package initialization
│   ├── test_authorization.py       # IDOR and session authorization tests
│   ├── test_schedule_management.py # Schedule rule validation & overlap tests
│   ├── test_show_maintenance.py    # Rolling-window show & seat generation tests
│   └── test_show_availability.py   # Show cutoff & time filtering tests
│
├── docs/                           # Technical operations and runbooks
│   └── SHOW_SCHEDULING_OPERATIONS.md # Operator and cloud scheduler runbook
│
├── templates/                      # Jinja2 HTML templates
│   ├── index.html                  # Home discovery page with carousel and movie rows
│   ├── movie-details.html          # Individual movie metadata, cast, and trailer
│   ├── shows.html                  # Venue showtime picker and date filtering
│   ├── seat-selection.html         # Interactive auditorium seat map and checkout modal
│   ├── my-bookings.html            # User booking history and cancellation interface
│   ├── saved-movies.html           # User bookmarked movies list
│   └── profile.html                # User profile settings
│
└── static/                         # Static web assets
    ├── banners/                    # Movie hero banner images
    ├── posters/                    # Movie card poster images
    ├── *.css                       # Page-specific responsive stylesheets
    └── *.js                        # Page-specific frontend client scripts
```

---

## 9. Local Setup Summary

Detailed step-by-step local instructions are provided in **[SETUP.md](SETUP.md)**. Summary of quick start commands:

```bash
# 1. Start MySQL (e.g. via XAMPP)
# 2. Initialize canonical database schema
mysql -u root < database/database_schema.sql

# 3. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
.\.venv\Scripts\activate        # Windows

# 4. Install production dependencies
pip install -r requirements.txt

# 5. Configure environment variables
copy .env.example .env          # Windows (cp .env.example .env on Linux/macOS)
# Edit .env with your SECRET_KEY, DB settings, and Gmail App Password

# 6. Run initial dev seeds (Order: schema -> movies -> shows)
python scripts/seed_movies.py
python scripts/seed_shows.py

# 7. Start the development server
python app.py                   # Accessible at http://localhost:5000
```

---

## 10. Deployment Architecture

- **Local vs. Production**: Local development utilizes XAMPP MariaDB on `localhost:3306` with `DEBUG=True`. Production requires `DEBUG=False`, an external managed relational database (MySQL 8.0+ or MariaDB 10.4+), and a random, high-entropy `SECRET_KEY`.
- **WSGI Runner**: Managed hosting environments execute the command defined in `Procfile`:
  ```bash
  gunicorn -w 4 -b 0.0.0.0:$PORT app:app
  ```
- **Database Release Step**: During release deployment, run:
  ```bash
  python database/migrate_show_scheduling.py
  ```
  This applies missing scheduling tables, indexes, and constraints idempotently.
- **Daily Automated Scheduler**: Configure the platform's scheduler (e.g., cron job or worker service) to run once daily shortly after midnight IST (`18:35 UTC`):
  ```bash
  python scripts/run_show_maintenance.py
  ```
  See **[docs/SHOW_SCHEDULING_OPERATIONS.md](docs/SHOW_SCHEDULING_OPERATIONS.md)** for operational runbook details.

---

## 11. Environment Variables Reference

Production environments require configuration via environment variables. Full details and descriptions are documented in **[.env.example](.env.example)**.

| Variable Name | Status | Description |
| :--- | :---: | :--- |
| `SECRET_KEY` | **Required** | High-entropy random secret key for signing session cookies |
| `DEBUG` | **Required** | Must be set to `False` in production |
| `DB_HOST` | **Required** | Hostname of the relational database |
| `DB_PORT` | Optional | Database port (defaults to `3306`) |
| `DB_USER` | **Required** | Database username |
| `DB_PASSWORD` | **Required** | Database password |
| `DB_NAME` | **Required** | Database schema name (`bookora`) |
| `DB_SSL_CA` | Optional | Path to provider CA bundle for encrypted DB connections |
| `DB_POOL_SIZE` | Optional | Connection pool size per Gunicorn worker (defaults to `5`) |
| `EMAIL_HOST` | Optional | SMTP host (defaults to `smtp.gmail.com`) |
| `EMAIL_PORT` | Optional | SMTP port (defaults to `587`) |
| `EMAIL_USER` | **Required** | SMTP authentication username / Gmail address |
| `EMAIL_PASSWORD` | **Required** | SMTP authentication password / Gmail App Password |
| `EMAIL_FROM` | Optional | Outgoing sender email address (defaults to `EMAIL_USER`) |
| `SESSION_COOKIE_SECURE`| Optional | Enforces HTTPS-only cookies (defaults to `True` when `DEBUG=False`) |
| `TRUST_PROXY_HEADERS` | Optional | Set to `True` when running behind a cloud reverse proxy |

---

## 12. Credits & Portfolio Information

Designed and engineered by **Bhavya Jain** as a portfolio project demonstrating production-grade software engineering, database design, concurrent transactions, and full-stack development.

- GitHub: [@bjgithub29](https://github.com/bjgithub29)
- Repository: [Bookora](https://github.com/bjgithub29/Bookora)

---
<sub>This project is developed for educational and portfolio demonstration purposes. Movie posters, banners, and titles belong to their respective copyright holders.</sub>
