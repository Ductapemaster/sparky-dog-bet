# Sparky's DNA Bet

## Tech Stack

- **Python 3.11** / **Flask 3.0** — web framework with Jinja2 templating
- **SQLite** — database via Python's stdlib `sqlite3` (no ORM)
- **Gunicorn** — WSGI server (2 workers)
- **Docker** + **Docker Compose** — containerized deployment; SQLite file and gallery images persist via a named volume mounted at `/app/data`

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

The container binds to host port `9999` (mapped to gunicorn on `8000`). The `sparky_db` Docker volume persists the database and uploaded images across rebuilds.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask session secret |
| `DB_PATH` | Path to SQLite file (default: `data/sparky.db`) |
