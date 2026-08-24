# Bookora — Setup & Run Guide

How to get Bookora running on your own machine, in order. Follow the steps top to bottom the first time.

Bookora is a Flask + MySQL movie‑ticket booking app. MySQL is provided by **XAMPP**, the backend is **Flask (Python)**, and the frontend is server‑rendered HTML/CSS/JS. Email‑OTP login uses **Gmail SMTP**.

---

## 0. Prerequisites

Install these once before you start:

- **XAMPP** — gives you MySQL (the database) and phpMyAdmin (a web UI to run SQL). Download: https://www.apachefriends.org
- **Python 3.10+** with `pip` — check with `python --version` and `pip --version`
- **A Gmail account with an App Password** — required so the app can send login OTP emails. Create one at https://myaccount.google.com/apppasswords (this is a 16‑character app password, **not** your normal Gmail password). You need 2‑Step Verification enabled on the Google account first.

> On Windows, if `python` doesn't work, try `py` instead (e.g. `py app.py`).

---

## 1. Open the project folder

Clone the repository (or download and unzip it), then open a terminal (Command Prompt / PowerShell) **in the project root** — the folder that contains `app.py`, `requirements.txt`, and `database_schema.sql`.

```bash
git clone https://github.com/bjgithub29/Bookora.git
cd Bookora
```

All commands below are run from this folder.

---

## 2. Start XAMPP (MySQL + Apache)

1. Open the **XAMPP Control Panel**.
2. Click **Start** on **MySQL**.
3. Click **Start** on **Apache** (needed only so you can use phpMyAdmin in the next step).

Leave XAMPP running the whole time you use the app — the Flask backend talks to this MySQL server.

---

## 3. Create the database and tables (run the SQL file)

This step creates the `bookora` database, all the tables, and seeds the four Ahmedabad theatres. You only need to do it **once** (or again if you want to reset the schema).

**Option A — phpMyAdmin (easiest):**

1. Open http://localhost/phpmyadmin in your browser.
2. Click the **Import** tab at the top.
3. Click **Choose File** and select `database_schema.sql` from the project folder.
4. Scroll down and click **Import / Go**.

You should see a success message, and a **`bookora`** database will appear in the left sidebar with the tables `movies`, `theatres`, `shows`, `seats`, `users`, `otp_verification`, `saved_movies`, and `bookings`.

**Option B — command line (if you prefer):**

```bash
"C:\xampp\mysql\bin\mysql.exe" -u root < database_schema.sql
```

> The SQL file already does `CREATE DATABASE IF NOT EXISTS bookora;` — you do **not** need to create the database by hand first.

---

## 4. Install the Python dependencies

Optional but recommended — create a virtual environment so packages stay isolated:

```bash
python -m venv venv
venv\Scripts\activate
```

Then install the requirements:

```bash
pip install -r requirements.txt
```

This installs Flask, flask‑cors, mysql‑connector‑python, and python‑dotenv.

---

## 5. Configure your environment (`.env`)

The app reads its secrets and settings from a `.env` file. Copy the provided template and fill in your values:

```bash
copy .env.example .env
```

Open the new `.env` file and set:

- **`EMAIL_USER`** — your Gmail address
- **`EMAIL_PASSWORD`** — your Gmail **App Password** (16 characters, no spaces)
- **`EMAIL_FROM`** — usually the same Gmail address
- **`SECRET_KEY`** — any long random string (generate one with `python -c "import secrets; print(secrets.token_hex(32))"`)
- **`DB_*`** — leave as the defaults (`DB_HOST=localhost`, `DB_USER=root`, `DB_PASSWORD=` empty, `DB_NAME=bookora`) — these match a standard XAMPP install.
- **`DEBUG`** — set to `True` for local development, `False` otherwise.

> ⚠️ The email settings are **required** for login. Without a valid Gmail App Password, the app can't send OTP codes and you won't be able to log in.
>
> ⚠️ Never commit `.env` to git — it holds real secrets. It's already git‑ignored.

---

## 6. Seed the movies

Loads the movies from `movies-data.json` into the `movies` table.

```bash
python seed_movies.py
```

You should see a list of inserted movies and a total count at the end.

---

## 7. Seed the shows and seats

Generates showtimes for the next 7 days across the theatres, and creates all the seats (rows A–J, 12 seats each, all available).

```bash
python seed_shows.py
```

> **Order matters:** run `seed_movies.py` *before* `seed_shows.py`. Shows are generated for existing movies and theatres, so the movies must already be in the database (and the theatres came from step 3). Running shows first will produce no shows.

---

## 8. Run the app

```bash
python app.py
```

You'll see Flask start up and report that it's running on `http://127.0.0.1:5000`.

---

## 9. Open it in your browser

Go to:

```
http://localhost:5000
```

Then walk through the flow: **Home → pick a movie → Shows → choose date/time → select seats → log in with Email OTP → confirm booking → My Bookings → (cancel if you want) → Profile / Saved Movies.**

When logging in, enter your email, check your inbox (and spam) for the 6‑digit OTP, and complete your profile the first time.

---

## Quick reference (after first‑time setup)

Once everything is installed and seeded, a normal start is just:

```bash
# 1. Start MySQL in the XAMPP Control Panel, then:
cd bookora
venv\Scripts\activate        # if you made a virtual environment
python app.py                # then open http://localhost:5000
```

To reset the show schedule with fresh dates later, re‑run `python seed_shows.py`.

---

## Troubleshooting

**`No module named 'flask'`** — Dependencies aren't installed (or your virtual environment isn't activated). Run `venv\Scripts\activate` then `pip install -r requirements.txt`.

**`Access denied for user 'root'@'localhost'`** — Your MySQL root user has a password but `.env` expects none (or vice‑versa). On a default XAMPP install the root password is empty, so `DB_PASSWORD=` should be blank. Match `.env` to your actual MySQL setup.

**`Can't connect to MySQL server` / `2003`** — MySQL isn't running. Start it in the XAMPP Control Panel. If the port is taken, another MySQL/service may be using port 3306.

**`Unknown database 'bookora'`** — You skipped step 3. Import `database_schema.sql` first.

**No shows or seats appear in the app** — You ran the seeds out of order or not at all. Run `seed_movies.py`, then `seed_shows.py`.

**OTP email never arrives** — `EMAIL_USER`/`EMAIL_PASSWORD` are missing or wrong in `.env`. Use a Gmail **App Password**, not your login password, and check the spam folder.

**`Port 5000 is in use`** — Something else is using the port. Add a line like `PORT=5001` to `.env` and open `http://localhost:5001` instead.

**Re‑running seeds wiped my data** — That's expected: `seed_movies.py` clears the movies table and `seed_shows.py` clears shows and seats before regenerating. Only re‑run them when you want a fresh dataset.

---

## What each piece does

| File | Purpose |
| --- | --- |
| `app.py` | The Flask backend — all routes and API endpoints |
| `database_schema.sql` | Creates the `bookora` database, tables, and seeds theatres |
| `movies-data.json` | Source movie data read by the movie seeder |
| `seed_movies.py` | Loads movies into the database |
| `seed_shows.py` | Generates 7 days of shows + all seats |
| `.env.example` | Template for your local `.env` (copy and fill in) |
| `requirements.txt` | Python dependencies |
| `templates/` | HTML pages | 
| `static/` | CSS, JavaScript, images |
