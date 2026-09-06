# Bookora — Setup & Run Guide

This guide walks you through setting up and running Bookora on your local machine for development and testing.

Bookora is a full-stack cinema ticketing application built with a **Flask** backend, a **MySQL/MariaDB** database, and a **server-rendered** responsive frontend. Authentication uses passwordless **Email-OTP** via SMTP.

---

## 1. Prerequisites

Install and verify these tools before starting:

- **MySQL or MariaDB** (via [XAMPP](https://www.apachefriends.org/) or standalone): Provides the relational database.
- **Python 3.10+** with `pip`: Verify with `python --version` and `pip --version`.
- **Gmail Account with an App Password**: Required for sending login verification OTP emails. Generate a 16-character App Password at [Google Account App Passwords](https://myaccount.google.com/apppasswords) (requires 2-Step Verification enabled).
- **Git**: For source version control.

---

## 2. Project Directory & Repository Setup

Clone the repository and navigate into the project root:

```bash
git clone https://github.com/bjgithub29/Bookora.git
cd Bookora
```

All commands below should be executed from the project root folder.

---

## 3. Local Database Initialization (XAMPP)

1. Open the **XAMPP Control Panel**.
2. Start the **MySQL** module (and optionally **Apache** if you want to use phpMyAdmin).
3. Import the canonical schema:

### Option A: Using Command Line (Recommended)
```bash
# Windows (adjust path if XAMPP is installed elsewhere)
"C:\xampp\mysql\bin\mysql.exe" -u root < database/database_schema.sql

# macOS / Linux / Standalone MySQL
mysql -u root -p < database/database_schema.sql
```

### Option B: Using phpMyAdmin
1. Open `http://localhost/phpmyadmin` in your browser.
2. Click the **Import** tab at the top.
3. Click **Choose File** and select `database/database_schema.sql`.
4. Click **Import / Go**.

> `database/database_schema.sql` automatically creates the `bookora` database if it does not exist, sets up all 9 tables, establishes foreign keys, and seeds the initial Ahmedabad theatres with composite unique constraints (`UNIQUE KEY unique_theatre (name, city)`).

---

## 4. Python Virtual Environment & Dependencies

Create an isolated virtual environment and install the production dependencies:

```bash
# 1. Create virtual environment
python -m venv .venv

# 2. Activate virtual environment
# Windows (Command Prompt / PowerShell):
.\.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

This installs Flask 3.0, mysql-connector-python 8.2, python-dotenv, tzdata (for timezone reliability), and Gunicorn.

---

## 5. Configure Environment Variables (`.env`)

Copy the provided `.env.example` template:

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` in a text editor and configure your environment settings:

### Option A: Local Development (XAMPP MySQL/MariaDB)

```ini
# Generate a secret key: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-random-generated-secret-key
DEBUG=True

# Database (matches standard local XAMPP defaults)
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=bookora

# Email OTP Configuration (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-16-character-app-password
EMAIL_FROM=your-email@gmail.com
```

### Option B: Cloud Production (Aiven MySQL 8.4+)

```ini
SECRET_KEY=your-random-generated-secret-key
DEBUG=False

# Aiven MySQL connection parameters
DB_HOST=bookora-db-your-service.d.aivencloud.com
DB_PORT=15053
DB_USER=avnadmin
DB_PASSWORD=your-production-database-password
DB_NAME=bookora
DB_POOL_SIZE=5

# Database TLS/SSL Configuration (Required)
# Keep DB_SSL_VERIFY_CERT=True in production.
# Option 1 (Environment variable): Set DB_SSL_CA_CERT to the PEM text in your PaaS dashboard
# Option 2 (File path): Point DB_SSL_CA to ca.pem (local) or /etc/secrets/ca.pem (Render Secret Files)
DB_SSL_CA=ca.pem
DB_SSL_VERIFY_CERT=True
```

> **Security & Deployment Notes:**
> - Never commit `.env` or any real passwords to Git. Both `.env` and `*.pem` are excluded by `.gitignore`.
> - The CA certificate (`ca.pem`) must **NEVER** be committed to GitHub.
> - For Render/PaaS deployments, supply the CA certificate either via the `DB_SSL_CA_CERT` environment variable or through Render's **Secret Files** feature (mounted at `/etc/secrets/ca.pem`).

---

## 6. Run the Show-Scheduling Migration

To verify that all show-scheduling schema objects, foreign keys, and unique constraints are fully aligned with the application:

```bash
python database/migrate_show_scheduling.py
```

This script is idempotent and safe to run on an existing database; it creates `show_schedules`, links `shows.schedule_id`, and creates the composite unique constraint `unique_show_instance (movie_id, theatre_id, show_date, show_time)`.

---

## 7. Development Seeding (Controlled Initialization)

To populate movies and initial demo shows in a fresh development database, run the seed scripts in strict order:

```bash
# Step 1: Load movies from movies-data.json
python scripts/seed_movies.py

# Step 2: Create initial schedule rules and generate shows/seats
python scripts/seed_shows.py
```

### Important Seed Principles:
- **Order Matters**: `database/database_schema.sql` $\rightarrow$ `scripts/seed_movies.py` $\rightarrow$ `scripts/seed_shows.py`.
- **Development-Only**: Both `scripts/seed_movies.py` and `scripts/seed_shows.py` contain interactive safety prompts and will refuse to run if existing bookings are detected.
- **Never Run in Production**: These scripts are for local demo bootstrapping only. Production environments rely on `scripts/run_show_maintenance.py` for continuous show generation.

---

## 8. Start the Local Server

Start the Flask development server:

```bash
python app.py
```

The application will start at `http://localhost:5000` (or the port specified by `PORT` in `.env`).

---

## 9. Running the Automated Test Suite

Run the full non-destructive unit test suite:

```bash
python -m unittest discover -s tests -v
# Or run specific test modules:
python -m unittest tests.test_schedule_management tests.test_show_maintenance tests.test_show_availability tests.test_authorization -v
```

### Verified Test Coverage:
- `test_schedule_management`: 23 tests (validation, overlap algorithms, weekday masks)
- `test_show_maintenance`: 12 tests (rolling window generation, idempotency, seat layouts)
- `test_show_availability`: 3 tests (past show filtering, time cutoff enforcement)
- `test_authorization`: 12 tests (session-based authentication, IDOR protection, CSRF/session scoping)
- **Result: 50 tests pass (0 failures, 0 errors)**.

---

## 10. Local vs. Production Overview

| Feature | Local Development | Cloud Production |
| :--- | :--- | :--- |
| **Server Engine** | `python app.py` (Flask built-in server) | `gunicorn -w 4 -b 0.0.0.0:$PORT app:app` |
| **Database** | XAMPP MariaDB (`localhost:3306`, root/no-password) | Managed Cloud Database (MySQL 8.0+ / MariaDB 10.4+) |
| **`DEBUG` Flag** | `True` (allows development fallbacks) | `False` (crashes if required variables/secrets are missing) |
| **Show Generation** | Initial bootstrapping via `scripts/seed_shows.py` | Daily headless cron job via `scripts/run_show_maintenance.py` |
| **Cookies** | Plain HTTP permitted when `DEBUG=True` | Enforced HTTPS-only (`SESSION_COOKIE_SECURE=True`) |

---

## 11. Troubleshooting

- **`Access denied for user 'root'@'localhost'`**:
  Your MySQL root account has a password or `.env` has an incorrect password. For standard XAMPP, `DB_PASSWORD=` should be blank.
- **`Can't connect to MySQL server` / Error 2003**:
  MySQL is not running. Ensure the MySQL module is active in the XAMPP Control Panel.
- **`Unknown database 'bookora'`**:
  You skipped schema initialization. Import `database/database_schema.sql` first.
- **OTP Email Fails or Times Out**:
  Ensure you are using a 16-character Gmail **App Password** (not your Google account password) and that outbound port 587 is not blocked by local firewall software.
- **Port 5000 is in use**:
  Set `PORT=5001` in `.env` and navigate to `http://localhost:5001`.
- **Database Connection Pool Exhaustion**:
  Ensure `DB_POOL_SIZE` is sized properly relative to your database `max_connections`. The default is 5 connections per process.
