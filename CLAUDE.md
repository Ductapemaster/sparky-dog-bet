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
| GET | `/about` | About Sparky page with photo gallery |
| GET | `/leaderboard` | Public leaderboard (placeholder until results revealed) |
| GET | `/gallery-thumb/<filename>` | Serve 400px WebP thumbnail from `data/gallery/thumbs/` (fallback: original) |
| GET | `/gallery-img/<filename>` | Serve 2048px WebP display image from `data/gallery/display/` (fallback: original) |
| GET | `/bet` | Bet flow (identity lookup → form → submitted view) |
| POST | `/bet/verify` | Verify guest identity, set session |
| POST | `/bet/submit` | Submit bet |
| GET | `/admin` | Admin dashboard (session-gated) |
| POST | `/admin/login` | Admin login |
| POST | `/admin/toggle/<key>` | Toggle `BettingLocked` or `ResultsRevealed` |
| POST | `/admin/logout` | Admin logout |
| POST | `/admin/guests/add` | Add a guest |
| POST | `/admin/guests/<id>/edit` | Edit guest name/phone4 |
| POST | `/admin/guests/<id>/delete` | Delete guest (also deletes their bets) |
| POST | `/admin/guests/<id>/reset-bet` | Clear a guest's bet so they can re-submit |
| POST | `/admin/bets/add` | Add a bet row for a guest |
| POST | `/admin/bets/<id>/edit` | Edit a single bet row (breed/percentage) |
| POST | `/admin/bets/<id>/delete` | Delete a single bet row |
| POST | `/admin/wipe-all-bets` | Delete ALL bets and reset all guests (testing only) |
| POST | `/admin/breeds/add` | Add a breed to the dropdown list |
| POST | `/admin/breeds/<id>/edit` | Edit a breed name |
| POST | `/admin/breeds/<id>/delete` | Delete a breed |
| POST | `/admin/actual/add` | Add/upsert an actual DNA result |
| POST | `/admin/actual/<id>/edit` | Edit an actual DNA result |
| POST | `/admin/actual/<id>/delete` | Delete an actual DNA result |
| POST | `/admin/gallery/upload` | Upload a gallery photo (stored in `data/gallery/`) |
| POST | `/admin/gallery/reorder` | Reorder gallery images (accepts JSON `{order: [ids]}`) |
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
| `gallery` | id, file_id (stores filename), sort_order |

Config keys: `AdminPassword`, `BettingLocked`, `RequirePin`, `ResultsRevealed`

Database is created and seeded automatically on startup via `db.init_db()`:
- Breeds seeded from `breeds.txt` (AKC list, ~224 breeds) on first run only
- Config keys seeded with safe defaults on first run only
- Default admin password is `sparky` — change immediately via the `config` table

## Gallery Images

Images are uploaded via the admin panel and stored at `data/gallery/` (inside the Docker
volume, so they persist across rebuilds). Supported formats: jpg, jpeg, png, gif, webp.
Order is set via drag-and-drop in the admin Gallery tab.

On upload, two derived sizes are generated automatically via `db.generate_thumbnail()` and
`db.generate_display()`. Deleting a photo also removes both derived files.

| Path | Max dimension | Format | Quality | Route | Use |
|------|--------------|--------|---------|-------|-----|
| `data/gallery/thumbs/{stem}.webp` | 400px | WebP | 75 | `/gallery-thumb/` | Gallery grid |
| `data/gallery/display/{stem}.webp` | 2048px | WebP | 85 | `/gallery-img/` | Lightbox |
| `data/gallery/{original}` | — | original | — | fallback only | Never served directly |

Both routes set `Cache-Control: public, max-age=86400` and fall back to the original if the
derived file doesn't exist. The gallery template uses `src` → thumbnail and `data-full` →
display URL; the lightbox reads `img.dataset.full` on click.

To backfill derived images for existing uploads (idempotent — skips files that already exist):
```bash
docker exec sparky-dog-bet-web-1 python generate_thumbnails.py
```

## Admin Panel

Five-tab layout at `/admin`: **Overview**, **Guests**, **Bets**, **Results**, **Gallery**

- **Overview** — stats (submitted/total/remaining), game controls (lock betting, reveal
  results), leaderboard with expandable rows, guest submission status
- **Guests** — CRUD for guest names and phone4 PINs
- **Bets** — collapsible per-guest groups; add/edit/delete individual bet rows; per-guest
  wipe; Danger Zone (wipe all bets)
- **Results** — add/edit/delete actual DNA result rows (breed + percentage)
- **Gallery** — upload photos; drag-and-drop to reorder; delete

Tab state is preserved across POST-redirects via `sessionStorage`. Admin forms submit via
background `fetch` (AJAX) without a full page reload, except file uploads.

To reset a guest's bet (let them re-submit): Bets tab → guest group → wipe button (yellow).
This deletes their bet rows and clears `has_submitted`.

Guests can also self-edit their bet without admin help: the submitted ("Bet Placed")
view shows an **Edit My Bet** button (hidden once betting is locked or results are
revealed) linking to `/bet?edit=1`, which re-renders the form pre-filled with their
current rows. Submitting in edit mode posts a hidden `editing=1` flag; `bet_submit`
calls `db.submit_bet(..., replace=True)`, which deletes the old rows and re-inserts,
refreshing `submitted_at` to the edit time (so an edit counts as a fresh entry for
tie-breaks). The `BettingLocked` check inside `submit_bet` enforces the edit window.

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
Range 0–100. Lower = better. Unguessed breeds are penalized (treated as 0% guess).
Ties broken by earlier `submitted_at` timestamp. Score kept to 1 decimal place.

## Key Conventions

- `db.is_true(val)` normalises boolean config values
- `_submit_lock` (threading.Lock) + `_get_db_exclusive()` (BEGIN IMMEDIATE) together prevent double-submission: the lock guards same-process threads; BEGIN IMMEDIATE makes the re-check + write atomic across all Gunicorn workers
- `db._gallery_dir()` returns the gallery image directory (`data/gallery/` by default)
- `db._thumbs_dir()` / `db._display_dir()` — derived image subdirectories
- `db._thumb_filename(f)` / `db._display_filename(f)` — converts any filename to `{stem}.webp`
- `db.generate_thumbnail(f)` / `db.generate_display(f)` — silent no-op on failure (won't crash upload if Pillow fails)
- Config booleans toggle via `admin_toggle/<key>` — reads current, flips it, writes back
- Guest name lookup uses a typeahead `<input list="...">` (not a `<select>`)
- PIN (phone4) is always required at login — `RequirePin` config key is not exposed in UI
- The `×` remove button on breed rows is hidden when only one row remains
- `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` are set once in `init_db()` and persist in the DB file — not set on every connection

## Development Workflow

```bash
# First time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SECRET_KEY

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
- Container binds to host port **9999** → gunicorn on 8000
- **Cloudflare Tunnel**: a `cloudflared` container on the host routes `sparky.koubalabs.com`
  → `http://localhost:9999`. Configured via Cloudflare Zero Trust dashboard (token-based,
  no local ingress config file).
- **Cloudflare Cache Rule**: zone `koubalabs.com` has a cache rule matching
  `(starts_with(http.request.uri.path, "/gallery-thumb/")) or (starts_with(http.request.uri.path, "/gallery-img/"))`
  → Eligible for cache, Edge TTL override 1 day. Verify with:
  ```bash
  curl -sI https://sparky.koubalabs.com/gallery-thumb/Bowtie.webp | grep cf-cache-status
  # → HIT on second request
  ```
- **Gunicorn**: gevent worker class, 2 workers, 100 connections each, 60s timeout.
  Switching from 4 sync workers to 2 gevent workers handles concurrent image requests
  without blocking — less critical now that images are edge-cached, but still improves
  non-image route concurrency.

## Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask session signing key — generate a long random string |
| `DB_PATH` | No | Path to SQLite file (default: `data/sparky.db`) |

`.env` is gitignored. Copy `.env.example` and fill in `SECRET_KEY` before first run.
