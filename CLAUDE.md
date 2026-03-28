# Sparky's DNA Bet — Claude Project Guide

## What This Is

A wedding welcome party game. Guests bet $1 on the breed breakdown of rescue dog Sparky,
scored against his real DNA test results. Hosted on Dan's home server via Docker.

## Architecture

**Stack**: Python/Flask + Jinja2 templates + SQLite + Docker

- `app/db.py` — all database reads/writes (SQLite via stdlib `sqlite3`)
- `app/scoring.py` — TVD scoring algorithm
- `app/routes.py` — all Flask routes
- `app/templates/` — Jinja2 templates (extend `base.html`)
- `app/static/style.css` — all CSS (mobile-first, sage green theme)
- `wsgi.py` — gunicorn entry point
- `Dockerfile` + `docker-compose.yml` — production deployment
- `import_guests.py` — standalone script to bulk-load guests from CSV
- `guests_template.csv` — CSV template for guest import

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Home page |
| GET | `/gallery` | Photo gallery |
| GET | `/about` | About page |
| GET | `/gallery-img/<filename>` | Serve uploaded gallery image from `data/gallery/` |
| GET | `/bet` | Bet form (lookup → form → submitted view) |
| POST | `/bet/verify` | Verify guest identity, set session |
| POST | `/bet/submit` | Submit bet |
| GET | `/admin` | Admin dashboard (session-gated, two tabs: Overview / Data) |
| POST | `/admin/login` | Admin login |
| POST | `/admin/toggle/<key>` | Toggle BettingLocked / ResultsRevealed / RequirePin |
| POST | `/admin/logout` | Admin logout |
| POST | `/admin/guests/add` | Add a guest |
| POST | `/admin/guests/<id>/edit` | Edit guest name/phone4 |
| POST | `/admin/guests/<id>/delete` | Delete guest (also deletes their bets) |
| POST | `/admin/guests/<id>/reset-bet` | Clear a guest's bet so they can re-submit |
| POST | `/admin/bets/<id>/delete` | Delete a single bet row |
| POST | `/admin/wipe-all-bets` | Delete ALL bets and reset all guests (testing only) |
| POST | `/admin/actual/add` | Add/upsert an actual DNA result |
| POST | `/admin/actual/<id>/edit` | Edit an actual DNA result |
| POST | `/admin/actual/<id>/delete` | Delete an actual DNA result |
| POST | `/admin/gallery/upload` | Upload a gallery photo (stored in `data/gallery/`) |
| POST | `/admin/gallery/<id>/edit` | Edit gallery photo caption/sort order |
| POST | `/admin/gallery/<id>/delete` | Delete gallery photo (removes file from disk too) |

## Database

SQLite file at `DB_PATH` (default `data/sparky.db`). Tables:

| Table | Columns |
|-------|---------|
| `guests` | id, name, phone4, has_submitted, submitted_at |
| `bets` | id, guest_name, breed, percentage, submitted_at |
| `actual_results` | id, breed, actual_percentage |
| `breeds` | id, breed_name |
| `config` | key, value |
| `gallery` | id, file_id (stores filename), caption, sort_order |

Config keys: `AdminPassword`, `BettingLocked`, `RequirePin`, `ResultsRevealed`

Database is created and seeded automatically on startup via `db.init_db()`:
- Breeds seeded from `breeds.txt` (AKC list, ~224 breeds) on first run only
- Config keys seeded with safe defaults on first run only
- Default admin password is `sparky` — change immediately via the `config` table

## Gallery Images

Images are uploaded via the admin panel and stored at `data/gallery/` (inside the Docker
volume, so they persist across rebuilds). Served at `/gallery-img/<filename>`. Deleting a
photo from the admin also removes the file from disk. Supported formats: jpg, jpeg, png,
gif, webp.

## Admin Panel

Two-tab layout at `/admin`:
- **Overview** — stats (submitted/total/remaining), game controls (lock betting, reveal
  results, require PIN), leaderboard, guest submission status
- **Data** — full CRUD for guests, bets, actual results, gallery; Danger Zone (wipe all bets)

Nav shows an "Admin" badge, "Overview"/"Data" tabs, and a "Sign Out" button. Tab state is
preserved across POST-redirects via `sessionStorage`.

To reset a guest's bet (let them re-submit): Guests table → Reset Bet button. This deletes
their bet rows and clears `has_submitted`.

## Session

- `session['guest']` — set after `/bet/verify`
  - Keys: `name`, `phone4`, `verified`, `has_submitted`, `submitted_at`
  - On `/bet` load, if session says `has_submitted=True` but no bet rows exist in DB,
    the session is auto-corrected (handles stale cookies from prior app versions)
- `session['admin_auth']` — set to `True` after successful admin login

## Scoring Algorithm

**Total Variation Distance (TVD)** in `app/scoring.py`:
```
Score = Σ |guess_breed_i% - actual_breed_i%| / 2
```
Range 0–100. Lower = better. Ties broken by `submitted_at` timestamp.

## Key Conventions

- `db.is_true(val)` normalises boolean config values
- `_submit_lock` (threading.Lock) in `db.py` prevents race conditions on double-tap submissions
- `db._gallery_dir()` returns the gallery image directory (`data/gallery/` by default)
- Config booleans toggle via `admin_toggle/<key>` — reads current, flips it, writes back
- Guest name lookup uses a typeahead `<input list="...">` (not a dropdown select)
- The `×` remove button on breed rows is hidden when only one row exists

## Development Workflow

```bash
# First time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY

# Load guests (before the game)
python import_guests.py guests.csv

# Run locally
python wsgi.py         # http://localhost:8000 with debug mode

# Production (Docker)
docker compose up -d --build

# View logs
docker compose logs -f web
```

## Deployment & Connectivity

- DB and gallery images persist via a named Docker volume (`sparky_db` → `/app/data`)
- **Tailscale Funnel**: expose port 9999 via Tailscale for HTTPS without Caddy
- No Google credentials needed — Sheets integration has been removed entirely

## What Needs Content

- `app/templates/home.html` — replace `[Partner's Name]`
- `app/templates/about.html` — replace all `[TODO]` placeholders
- `guests.csv` → run `import_guests.py` to load real guest list before the party
- Upload gallery photos via `/admin` → Data tab → Gallery Photos
- Enter actual DNA results via `/admin` → Data tab → Actual DNA Results (after the reveal)
