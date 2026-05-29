# Sparky's DNA Bet

## Tech Stack

- **Python 3.11** / **Flask 3.0** — web framework with Jinja2 templating
- **SQLite** — database via Python's stdlib `sqlite3` (no ORM)
- **Gunicorn + gevent** — WSGI server, 2 workers × 100 connections (non-blocking I/O)
- **Pillow** — WebP thumbnail and display image generation
- **Docker** + **Docker Compose** — containerized deployment; SQLite file and gallery images persist via a named volume mounted at `/app/data`
- **Cloudflare Tunnel** — exposes the app publicly via `sparky.koubalabs.com`; gallery image routes are edge-cached for 24 hours

## Project Structure

```
app/
  __init__.py       # app factory, calls db.init_db() on startup
  db.py             # all database access (SQLite)
  routes.py         # all Flask routes
  scoring.py        # TVD scoring algorithm
  templates/        # Jinja2 HTML templates (extend base.html)
  static/
    style.css       # all CSS — mobile-first, single stylesheet
wsgi.py             # gunicorn entry point
import_guests.py    # standalone CSV import script
Dockerfile
docker-compose.yml
requirements.txt    # Flask, gunicorn, python-dotenv
```

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY
python wsgi.py         # http://localhost:8000
```

## Production

```bash
docker compose up -d --build
```

The container binds to host port `9999` (mapped to gunicorn on `8000`). The `./data` directory is bind-mounted into the container at `/app/data` — the database and uploaded gallery images live there and persist across rebuilds. Copy this folder when migrating to a new machine.

### Gallery image pipeline

Uploaded images are stored as originals in `data/gallery/`. Two derived sizes are generated automatically on upload (and cleaned up on delete):

| Path | Size | Format | Use |
|------|------|--------|-----|
| `data/gallery/thumbs/{name}.webp` | 400px | WebP q75 | Gallery grid |
| `data/gallery/display/{name}.webp` | 2048px | WebP q85 | Lightbox |

Routes `/gallery-thumb/<filename>` and `/gallery-img/<filename>` serve the derived files (falling back to the original if a derived file is missing). Both routes set `Cache-Control: public, max-age=86400` and are edge-cached by Cloudflare.

To backfill derived images for existing uploads (safe to re-run — skips existing files):

```bash
docker exec sparky-dog-bet-web-1 python generate_thumbnails.py
```

### Cloudflare

The app is publicly accessible at `https://sparky.koubalabs.com` via a Cloudflare Tunnel (`cloudflared` container on the host). A Cloudflare Cache Rule caches all `/gallery-thumb/*` and `/gallery-img/*` responses at the edge for 24 hours, so concurrent guests at the wedding hit CF's CDN rather than the home server.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask session secret |
| `DB_PATH` | Path to SQLite file (default: `data/sparky.db`) |
