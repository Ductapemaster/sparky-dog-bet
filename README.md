# Sparky's DNA Bet

## Tech Stack

- **Python 3.11** / **Flask 3.0** — web framework with Jinja2 templating
- **SQLite** — database via Python's stdlib `sqlite3` (no ORM)
- **Gunicorn** — WSGI server (4 workers, 60s timeout)
- **Docker** + **Docker Compose** — containerized deployment; SQLite file and gallery images persist via a bind mount at `./data` → `/app/data`

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

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask session secret |
| `DB_PATH` | Path to SQLite file (default: `data/sparky.db`) |
