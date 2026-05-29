"""
db.py — SQLite database layer. Replaces sheets.py.

All data stored in a local SQLite file at the path set by the DB_PATH env var.
Uses Python's built-in sqlite3 — no additional dependencies required.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

_submit_lock = threading.Lock()


def _db_path():
    return os.environ.get('DB_PATH', 'data/sparky.db')


@contextmanager
def _get_db():
    conn = sqlite3.connect(_db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _get_db_exclusive():
    """Open a connection with BEGIN IMMEDIATE, acquiring the write lock before any reads.
    Ensures the check-then-write in submit_bet is atomic across all Gunicorn workers."""
    conn = sqlite3.connect(_db_path(), timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def init_db():
    """Create tables, seed breeds from breeds.txt, insert default config values."""
    path = _db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    with _get_db() as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS guests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                phone4 TEXT,
                has_submitted INTEGER DEFAULT 0,
                submitted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guest_name TEXT NOT NULL,
                breed TEXT NOT NULL,
                percentage INTEGER NOT NULL,
                submitted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS actual_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                breed TEXT NOT NULL UNIQUE,
                actual_percentage REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS breeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                breed_name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS gallery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                caption TEXT,
                sort_order INTEGER DEFAULT 0
            );
        """)

        # Seed default config — INSERT OR IGNORE leaves existing values untouched
        defaults = [
            ('BettingLocked',   'FALSE'),
            ('RequirePin',      'TRUE'),
            ('ResultsRevealed', 'FALSE'),
            ('AdminPassword',   'sparky'),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", defaults
        )

        # Seed breeds from breeds.txt if the table is empty
        count = conn.execute("SELECT COUNT(*) FROM breeds").fetchone()[0]
        if count == 0:
            breeds_path = os.path.join(os.path.dirname(__file__), '..', 'breeds.txt')
            if os.path.exists(breeds_path):
                with open(breeds_path) as f:
                    # Skip the header line ("BreedName")
                    lines = [line.strip() for line in f if line.strip()]
                    breed_names = [l for l in lines if l.lower() != 'breedname']
                conn.executemany(
                    "INSERT OR IGNORE INTO breeds (breed_name) VALUES (?)",
                    [(b,) for b in breed_names]
                )


# ── Config ────────────────────────────────────────────────────

def get_config(key):
    with _get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else None


def set_config(key, value):
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value))
        )


def is_true(val):
    return val is True or str(val).strip().upper() == 'TRUE'


# ── Guests ────────────────────────────────────────────────────

def get_guest_names():
    with _get_db() as conn:
        rows = conn.execute("SELECT name FROM guests ORDER BY name").fetchall()
        return [r['name'] for r in rows]


def verify_guest(name, phone4):
    pin_required = is_true(get_config('RequirePin'))
    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM guests WHERE name = ?", (str(name).strip(),)
        ).fetchone()

    if not row:
        return {'verified': False, 'error': 'Name not found in the guest list. Please check your name or ask the organizers.'}

    if pin_required:
        stored  = str(row['phone4'] or '').strip()
        entered = str(phone4 or '').strip()
        if stored != entered:
            return {'verified': False, 'error': 'PIN does not match. Please double-check the last 4 digits of your phone number.'}

    return {
        'verified':      True,
        'has_submitted': bool(row['has_submitted']),
        'submitted_at':  row['submitted_at'],
    }


def get_all_guests():
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, phone4, has_submitted, submitted_at FROM guests ORDER BY name"
        ).fetchall()
        return [
            {
                'id':            r['id'],
                'name':          r['name'],
                'phone4':        r['phone4'] or '',
                'has_submitted': bool(r['has_submitted']),
                'submitted_at':  r['submitted_at'] or '',
            }
            for r in rows
        ]


# ── Bets ──────────────────────────────────────────────────────

def submit_bet(name, phone4, breeds):
    verification = verify_guest(name, phone4)
    if not verification['verified']:
        return {'success': False, 'error': verification['error']}
    if verification['has_submitted']:
        return {'success': False, 'error': 'You have already placed your bet.'}

    if is_true(get_config('BettingLocked')):
        return {'success': False, 'error': 'Betting is currently locked. Check with the organizers.'}

    if not breeds:
        return {'success': False, 'error': 'Please add at least one breed.'}

    total = sum(int(b['percentage']) for b in breeds)
    if total != 100:
        return {'success': False, 'error': f'Percentages must add up to exactly 100%. Current total: {total}%.'}

    valid_breeds = {b.lower() for b in get_breeds()}
    seen = set()
    for b in breeds:
        key = b['breed'].lower()
        if key not in valid_breeds:
            return {'success': False, 'error': f'"{b["breed"]}" is not a recognized breed. Please select from the list.'}
        if key in seen:
            return {'success': False, 'error': f'"{b["breed"]}" appears more than once. Combine them into one row.'}
        seen.add(key)

    with _submit_lock:
        # BEGIN IMMEDIATE acquires the write lock before reading, making the
        # re-check + write atomic across all Gunicorn workers (not just threads).
        with _get_db_exclusive() as conn:
            row = conn.execute(
                "SELECT has_submitted FROM guests WHERE name = ?", (str(name).strip(),)
            ).fetchone()
            if not row or row['has_submitted']:
                return {'success': False, 'error': 'You have already placed your bet.'}

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for b in breeds:
                conn.execute(
                    "INSERT INTO bets (guest_name, breed, percentage, submitted_at) VALUES (?, ?, ?, ?)",
                    (str(name).strip(), str(b['breed']).strip(), int(b['percentage']), now)
                )
            conn.execute(
                "UPDATE guests SET has_submitted = 1, submitted_at = ? WHERE name = ?",
                (now, str(name).strip())
            )

    return {'success': True, 'submitted_at': now}


def get_bet(name):
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT breed, percentage FROM bets WHERE guest_name = ? ORDER BY percentage DESC",
            (str(name).strip(),)
        ).fetchall()
        return [{'breed': r['breed'], 'percentage': r['percentage']} for r in rows]


# ── Breeds & Gallery ──────────────────────────────────────────

def get_breeds():
    with _get_db() as conn:
        rows = conn.execute("SELECT breed_name FROM breeds ORDER BY breed_name").fetchall()
        return [r['breed_name'] for r in rows]


def get_all_breeds():
    with _get_db() as conn:
        rows = conn.execute("SELECT id, breed_name FROM breeds ORDER BY breed_name").fetchall()
        return [dict(r) for r in rows]


def add_breed(breed_name):
    with _get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO breeds (breed_name) VALUES (?)", (breed_name,))


def update_breed(breed_id, breed_name):
    with _get_db() as conn:
        conn.execute("UPDATE breeds SET breed_name=? WHERE id=?", (breed_name, breed_id))


def delete_breed(breed_id):
    with _get_db() as conn:
        conn.execute("DELETE FROM breeds WHERE id=?", (breed_id,))


def get_gallery_images():
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT file_id FROM gallery ORDER BY sort_order, id"
        ).fetchall()
        return [{'filename': r['file_id']} for r in rows]


# ── Scoring ───────────────────────────────────────────────────

def get_actual_results():
    with _get_db() as conn:
        rows = conn.execute("SELECT breed, actual_percentage FROM actual_results").fetchall()
        return {r['breed']: float(r['actual_percentage']) for r in rows}


# ── Admin: Guests ─────────────────────────────────────────────

def add_guest(name, phone4=None):
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO guests (name, phone4) VALUES (?, ?)",
            (str(name).strip(), str(phone4).strip() if phone4 else None)
        )


def update_guest(guest_id, name, phone4=None):
    with _get_db() as conn:
        conn.execute(
            "UPDATE guests SET name = ?, phone4 = ? WHERE id = ?",
            (str(name).strip(), str(phone4).strip() if phone4 else None, guest_id)
        )


def delete_guest(guest_id):
    with _get_db() as conn:
        row = conn.execute("SELECT name FROM guests WHERE id = ?", (guest_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM bets WHERE guest_name = ?", (row['name'],))
        conn.execute("DELETE FROM guests WHERE id = ?", (guest_id,))


def reset_guest_bet(guest_name):
    """Delete all bet rows for a guest and clear their submission flag so they can re-submit."""
    with _get_db() as conn:
        conn.execute("DELETE FROM bets WHERE guest_name = ?", (str(guest_name).strip(),))
        conn.execute(
            "UPDATE guests SET has_submitted = 0, submitted_at = NULL WHERE name = ?",
            (str(guest_name).strip(),)
        )


# ── Admin: Bets ───────────────────────────────────────────────

def get_all_bets():
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, guest_name, breed, percentage, submitted_at "
            "FROM bets ORDER BY guest_name, percentage DESC"
        ).fetchall()
        return [
            {
                'id':           r['id'],
                'guest_name':   r['guest_name'],
                'breed':        r['breed'],
                'percentage':   r['percentage'],
                'submitted_at': r['submitted_at'] or '',
            }
            for r in rows
        ]


def get_all_bets_for_scoring():
    """Load all bets for submitted guests in one query. Returns {guest_name: [{breed, percentage}]}."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT b.guest_name, b.breed, b.percentage "
            "FROM bets b "
            "JOIN guests g ON g.name = b.guest_name "
            "WHERE g.has_submitted = 1 "
            "ORDER BY b.guest_name, b.percentage DESC"
        ).fetchall()
    bets_by_guest = {}
    for row in rows:
        bets_by_guest.setdefault(row['guest_name'], []).append(
            {'breed': row['breed'], 'percentage': row['percentage']}
        )
    return bets_by_guest


def add_bet_row(guest_name, breed, percentage):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO bets (guest_name, breed, percentage, submitted_at) VALUES (?, ?, ?, ?)",
            (str(guest_name).strip(), str(breed).strip(), int(percentage), now)
        )


def update_bet(bet_id, breed, percentage):
    with _get_db() as conn:
        conn.execute(
            "UPDATE bets SET breed = ?, percentage = ? WHERE id = ?",
            (str(breed).strip(), int(percentage), int(bet_id))
        )


def delete_bet(bet_id):
    with _get_db() as conn:
        conn.execute("DELETE FROM bets WHERE id = ?", (bet_id,))


def wipe_all_bets():
    """Delete every bet and reset all guest submission flags. Intended for testing only."""
    with _get_db() as conn:
        conn.execute("DELETE FROM bets")
        conn.execute("UPDATE guests SET has_submitted = 0, submitted_at = NULL")


# ── Admin: Actual Results ─────────────────────────────────────

def get_all_actual_results():
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, breed, actual_percentage FROM actual_results ORDER BY actual_percentage DESC"
        ).fetchall()
        return [
            {'id': r['id'], 'breed': r['breed'], 'actual_percentage': r['actual_percentage']}
            for r in rows
        ]


def upsert_actual_result(breed, pct):
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO actual_results (breed, actual_percentage) VALUES (?, ?) "
            "ON CONFLICT(breed) DO UPDATE SET actual_percentage = excluded.actual_percentage",
            (str(breed).strip(), float(pct))
        )


def delete_actual_result(result_id):
    with _get_db() as conn:
        conn.execute("DELETE FROM actual_results WHERE id = ?", (result_id,))


# ── Admin: Gallery ────────────────────────────────────────────

def _gallery_dir():
    """Directory where uploaded gallery images are stored."""
    return os.path.join(os.path.dirname(os.path.abspath(_db_path())), 'gallery')


def _thumbs_dir():
    return os.path.join(_gallery_dir(), 'thumbs')


def _display_dir():
    return os.path.join(_gallery_dir(), 'display')


def _thumb_filename(filename):
    return os.path.splitext(filename)[0] + '.webp'

_display_filename = _thumb_filename


def generate_display(filename):
    """Generate a 2048px WebP display version for the lightbox. Silent no-op on failure."""
    try:
        from PIL import Image, ImageOps
        src = os.path.join(_gallery_dir(), filename)
        display = _display_dir()
        os.makedirs(display, exist_ok=True)
        dst = os.path.join(display, _display_filename(filename))
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((2048, 2048), Image.LANCZOS)
            img.save(dst, 'WEBP', quality=85)
    except Exception:
        pass


def generate_thumbnail(filename):
    """Generate a 400px WebP thumbnail for an uploaded gallery image. Silent no-op on failure."""
    try:
        from PIL import Image, ImageOps
        src = os.path.join(_gallery_dir(), filename)
        thumbs = _thumbs_dir()
        os.makedirs(thumbs, exist_ok=True)
        dst = os.path.join(thumbs, _thumb_filename(filename))
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((400, 400), Image.LANCZOS)
            img.save(dst, 'WEBP', quality=75)
    except Exception:
        pass


def get_all_gallery():
    """Full gallery rows including id and sort_order, for admin use."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, file_id, sort_order FROM gallery ORDER BY sort_order, id"
        ).fetchall()
        return [
            {'id': r['id'], 'filename': r['file_id'], 'sort_order': r['sort_order']}
            for r in rows
        ]


def add_gallery_image(filename, sort_order=0):
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO gallery (file_id, sort_order) VALUES (?, ?)",
            (str(filename).strip(), int(sort_order or 0))
        )


def reorder_gallery(id_list):
    with _get_db() as conn:
        for i, img_id in enumerate(id_list):
            conn.execute("UPDATE gallery SET sort_order = ? WHERE id = ?", (i, int(img_id)))


def delete_gallery_image(image_id):
    with _get_db() as conn:
        row = conn.execute("SELECT file_id FROM gallery WHERE id = ?", (image_id,)).fetchone()
        conn.execute("DELETE FROM gallery WHERE id = ?", (image_id,))
    if row:
        path = os.path.join(_gallery_dir(), row['file_id'])
        try:
            os.remove(path)
        except OSError:
            pass
        thumb = os.path.join(_thumbs_dir(), _thumb_filename(row['file_id']))
        try:
            os.remove(thumb)
        except OSError:
            pass
        display = os.path.join(_display_dir(), _display_filename(row['file_id']))
        try:
            os.remove(display)
        except OSError:
            pass
