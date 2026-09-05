# Bookora show scheduling operations

## What owns future shows

`show_schedules` is the operator-managed source of truth. A row says that one
movie plays at one existing theatre, at one local India time, over a date range.
`days_of_week` is exactly seven `0`/`1` characters in Monday-to-Sunday order;
for example, `1111111` is daily, `1000000` is Monday-only, and `0000011` is
Saturday/Sunday. Modern MySQL/MariaDB also enforce this with a `CHECK`, but the
application validator is authoritative for older engines that do not enforce
`CHECK` constraints.

`shows` remains the dated customer-facing instance table. Its optional
`schedule_id` records the rule that generated it. `seats` remain per-show rows,
and `bookings.show_id` continues to point to the generated show. There is no
screen table in the current schema, so a show instance is uniquely identified
by `(movie_id, theatre_id, show_date, show_time)`.

There is currently no admin/operator UI. Schedule creation must use the
non-public `services.schedule_management.create_schedule()` helper (as `scripts/seed_shows.py`
does), not a raw `INSERT`. It validates input, locks same-identity writes, and
rejects rules that can claim the same enabled calendar date. An authenticated
admin UI can use that helper later without changing the generator.

For one movie/theatre/show-time identity, active rules may have non-overlapping
date ranges, or may overlap only when their weekday masks have no common enabled
date. An open-ended active rule conflicts with every later rule that shares an
enabled weekday. To replace a rule, end or deactivate the old rule before adding
an overlapping replacement. Deactivation stops future generation only; it never
deletes generated shows, seats, or bookings.

## Safe rolling window

`scripts/run_show_maintenance.py` calls `maintain_upcoming_shows()` for today through
today + 6 calendar days, calculated in `Asia/Kolkata`. It selects only active
rules whose date ranges overlap that window. For each date enabled by a rule it:

1. creates the one missing show instance, or reuses its existing unique row;
2. creates the standard existing Bookora seat layout for that show, or reuses
   its existing unique seat rows;
3. commits all inserts together.

No `DELETE` is present in this command. If seat creation fails, the transaction
rolls back, including a just-created show. A database unique key on the show
identity and the existing `(show_id, seat_label)` unique key make repeat runs
and overlapping runs idempotent. The command also takes a short MySQL advisory
lock to avoid unnecessary overlapping work.

An expired show is retained. `/api/shows` filters it out with a show date/time
comparison in India business time; `/api/seats`, booking and cancellation apply
the same server-side time check. The browser is never trusted to decide whether
booking is still possible.

## One-time migration and production scheduler

Before the first production run, take the provider's normal database backup and
run this once with production database variables configured:

```bash
python database/migrate_show_scheduling.py
```

The migration creates `show_schedules`, adds nullable `shows.schedule_id`, and
adds the schedule foreign key and unique show-instance index. It never deletes
data. If legacy duplicate show instances exist, it stops before adding the
unique index and reports a sample; resolve those deliberately before retrying.
Because MySQL/MariaDB DDL statements commit implicitly, the migration is designed
to be idempotent and safely re-runnable if interrupted or after duplicate cleanup.

Then configure the cloud scheduler, cron, or hosting-provider scheduled job to
run once daily (for example shortly after midnight IST):

```bash
python scripts/run_show_maintenance.py
```

The application process and a personal laptop do not need to be running. The
job needs the same `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`,
and optional TLS settings as the web app. The command requires non-empty values
and does not log them. The web process calculates show availability using
`Asia/Kolkata`; a cloud host may run in UTC because the code does not rely on
the host clock for show business time.

## Seed scripts

`scripts/seed_movies.py` and `scripts/seed_shows.py` are still intentionally destructive
development/demo initializers. They refuse a database containing bookings by
default and require a confirmation for their deletes. `scripts/seed_shows.py` now
creates short-lived demo schedule rules for its initial seven-day window and
uses the same generator to create instances. Neither seed script belongs in a
daily production scheduler.
