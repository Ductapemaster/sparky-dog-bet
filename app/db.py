"""
db.py — SQLite database layer. Replaces sheets.py.

All data stored in a local SQLite file at the path set by the DB_PATH env var.
Uses Python's built-in sqlite3 — no additional dependencies required.
"""

import os
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

_submit_lock = threading.Lock()

# Sparky's actual-results sets, reseeded into the DB on every init_db. 'fake' is placeholder
# data for testing the reveal/leaderboard flow without spoiling. 'real' is Sparky's
# CONFIDENTIAL DNA breakdown — it must never be committed (the repo is public), so it is
# loaded at runtime from a gitignored file (data/real_results.json, same {breed: pct} shape)
# via _result_sets(). Without that file the 'real' set stays empty: a fresh checkout runs the
# full app in test mode but can't reveal Sparky's real results. The admin only toggles which
# set is active (config ActiveResultSet) — values are not edited in-app. See SPARKY_DNA_RESULTS.md
# (also gitignored) for the real numbers and the reveal-day procedure. All breed names must
# exist in breeds.txt.
RESULT_SETS = {
    'fake': {
        'Dalmatian': 50,
        'Chihuahua': 23,
        'Siberian Husky': 15,
        'Poodle (Standard)': 12,
    },
    'real': {},
}


def _result_sets():
    """RESULT_SETS with the confidential 'real' set merged in from the gitignored
    data/real_results.json if it exists. Kept out of source so it never reaches the
    public repo; the live deploy supplies the file alongside the DB."""
    sets = {name: dict(pcts) for name, pcts in RESULT_SETS.items()}
    real_path = os.path.join(os.path.dirname(_db_path()) or '.', 'real_results.json')
    try:
        with open(real_path) as f:
            real = json.load(f)
        if isinstance(real, dict) and real:
            sets['real'] = {str(b): float(p) for b, p in real.items()}
    except (OSError, ValueError):
        pass
    return sets


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
                breed TEXT NOT NULL,
                actual_percentage REAL NOT NULL,
                result_set TEXT NOT NULL DEFAULT 'real',
                UNIQUE(breed, result_set)
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

        # Migration: add precomputed score/rank columns to guests if missing. These are
        # filled by recompute_scores() so the bet page can read a guest's standing with a
        # single lookup instead of recomputing the whole leaderboard on every view.
        guest_cols = {r['name'] for r in conn.execute("PRAGMA table_info(guests)").fetchall()}
        if 'score' not in guest_cols:
            conn.execute("ALTER TABLE guests ADD COLUMN score REAL")
        if 'rank' not in guest_cols:
            conn.execute("ALTER TABLE guests ADD COLUMN rank INTEGER")

        # Migration: older DBs have actual_results keyed UNIQUE(breed) with no result_set
        # column. Results are now code-defined (see RESULT_SETS below) and reseeded on every
        # boot, so any existing rows are reproducible — drop and recreate with the new schema.
        actual_cols = {r['name'] for r in conn.execute("PRAGMA table_info(actual_results)").fetchall()}
        if 'result_set' not in actual_cols:
            conn.executescript("""
                DROP TABLE IF EXISTS actual_results;
                CREATE TABLE actual_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    breed TEXT NOT NULL,
                    actual_percentage REAL NOT NULL,
                    result_set TEXT NOT NULL DEFAULT 'real',
                    UNIQUE(breed, result_set)
                );
            """)

        # Seed default config — INSERT OR IGNORE leaves existing values untouched
        defaults = [
            ('BettingLocked',   'FALSE'),
            ('RequirePin',      'TRUE'),
            ('ResultsRevealed', 'FALSE'),
            ('AdminPassword',   'sparky'),
            ('BettingStartTime', ''),
            ('BettingDeadline', ''),
            ('VenmoUsername',   'Dan-Kouba'),
            ('ActiveResultSet', 'fake'),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", defaults
        )

        # Reseed the actual-results sets so the DB always matches the code-defined sets
        # ('real' merged in from the gitignored file, see _result_sets). Results are no longer
        # edited in-app (the admin only toggles which set is active). An empty set is skipped
        # rather than reseeded, so a deploy missing data/real_results.json never wipes real
        # results already in the DB — to change a value, edit the source/file and redeploy.
        for set_name, breeds_pct in _result_sets().items():
            if not breeds_pct:
                continue
            conn.execute("DELETE FROM actual_results WHERE result_set = ?", (set_name,))
            conn.executemany(
                "INSERT INTO actual_results (breed, actual_percentage, result_set) VALUES (?, ?, ?)",
                [(breed, float(pct), set_name) for breed, pct in breeds_pct.items()]
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

    # Backfill precomputed standings for the current state (e.g. if results are already
    # revealed at deploy time) so the bet page can read them immediately after this deploy.
    if is_true(get_config('ResultsRevealed')):
        recompute_scores()


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


# ── Betting deadline / lock ───────────────────────────────────

DEADLINE_FMT = '%Y-%m-%d %H:%M'


def get_deadline():
    """Parse the BettingDeadline config into a naive local datetime, or None."""
    raw = (get_config('BettingDeadline') or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, DEADLINE_FMT)
    except ValueError:
        return None


def get_start_time():
    """Parse the BettingStartTime config into a naive local datetime, or None."""
    raw = (get_config('BettingStartTime') or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, DEADLINE_FMT)
    except ValueError:
        return None


def deadline_display():
    """Human-friendly deadline string (e.g. 'Sat, Jun 13 at 5:00 PM'), or None."""
    dt = get_deadline()
    if not dt:
        return None
    # %-d / %-I strip leading zeros on Linux (glibc).
    return dt.strftime('%a, %b %-d at %-I:%M %p')


def start_display():
    """Human-friendly betting-open string (e.g. 'Sat, Jun 13 at 5:00 PM'), or None."""
    dt = get_start_time()
    if not dt:
        return None
    return dt.strftime('%a, %b %-d at %-I:%M %p')


def betting_phase():
    """Single source of truth for the betting timeline: 'pre', 'open', or 'closed'.

    Closed if results are revealed (we always lock before revealing, so a reveal forces
    closed), manually locked, or past the auto-lock deadline. Pre if a start time is set
    and we haven't reached it yet. Otherwise open.
    """
    if is_true(get_config('ResultsRevealed')):
        return 'closed'
    if is_true(get_config('BettingLocked')):
        return 'closed'
    deadline = get_deadline()
    if deadline is not None and datetime.now() >= deadline:
        return 'closed'
    start = get_start_time()
    if start is not None and datetime.now() < start:
        return 'pre'
    return 'open'


def betting_is_locked():
    """Whether betting submissions are blocked — true unless we're in the open phase
    (covers both 'pre' = not opened yet and 'closed'). Drives the nav lock icon too."""
    return betting_phase() != 'open'


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
            "SELECT id, name, phone4, has_submitted, submitted_at FROM guests "
            "ORDER BY has_submitted ASC, name"
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

def submit_bet(name, phone4, breeds, replace=False):
    verification = verify_guest(name, phone4)
    if not verification['verified']:
        return {'success': False, 'error': verification['error']}
    if verification['has_submitted'] and not replace:
        return {'success': False, 'error': 'You have already placed your bet.'}

    phase = betting_phase()
    if phase != 'open':
        if phase == 'pre':
            opens = start_display()
            msg = f"Betting hasn't opened yet — opens {opens}." if opens else "Betting hasn't opened yet."
            return {'success': False, 'error': msg}
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
            if not row:
                return {'success': False, 'error': 'You have already placed your bet.'}
            if row['has_submitted']:
                if not replace:
                    return {'success': False, 'error': 'You have already placed your bet.'}
                # Editing an existing bet — clear the old rows before re-inserting.
                conn.execute("DELETE FROM bets WHERE guest_name = ?", (str(name).strip(),))

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
        row = conn.execute("SELECT breed_name FROM breeds WHERE id=?", (breed_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Breed not found.'}
        old_name = row['breed_name']
        if old_name == breed_name:
            return {'success': True}
        clash = conn.execute(
            "SELECT 1 FROM breeds WHERE breed_name=? AND id<>?", (breed_name, breed_id)
        ).fetchone()
        if clash:
            return {'success': False, 'error': f'"{breed_name}" already exists.'}
        conn.execute("UPDATE breeds SET breed_name=? WHERE id=?", (breed_name, breed_id))
        conn.execute("UPDATE bets SET breed=? WHERE breed=?", (breed_name, old_name))
        conn.execute("UPDATE actual_results SET breed=? WHERE breed=?", (breed_name, old_name))
        return {'success': True}


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

def get_active_result_set():
    """Which results set is live for scoring/display: 'fake' (test mode) or 'real'."""
    return (get_config('ActiveResultSet') or 'fake').strip()


def get_actual_results():
    """The active set's breed→percentage map. Drives scoring, the leaderboard, and the
    bet 'How You Did' view — all read whichever set the admin has toggled active."""
    active = get_active_result_set()
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT breed, actual_percentage FROM actual_results WHERE result_set = ?",
            (active,)
        ).fetchall()
        return {r['breed']: float(r['actual_percentage']) for r in rows}


def recompute_scores():
    """Compute and persist each submitted guest's TVD score and rank into the guests table.

    Called whenever the actual results change or results are revealed. Scores are a pure
    function of (bets, actual results) and both are frozen once results are revealed (revealing
    auto-locks betting), so materializing them lets the bet page read a standing with one lookup.
    Uses the same TVD formula as scoring.get_leaderboard (Σ|guess−actual|/2, sort by score then
    submission time); keep the two in sync.
    """
    actual = get_actual_results()
    with _get_db() as conn:
        # Clear first so guests with no score (or no longer submitted) end up NULL.
        conn.execute("UPDATE guests SET score = NULL, rank = NULL")
        if not actual:
            return

        bets_by_guest = {}
        for r in conn.execute(
            "SELECT b.guest_name, b.breed, b.percentage FROM bets b "
            "JOIN guests g ON g.name = b.guest_name WHERE g.has_submitted = 1"
        ).fetchall():
            bets_by_guest.setdefault(r['guest_name'], {})[r['breed']] = float(r['percentage'])

        submitted = conn.execute(
            "SELECT name, submitted_at FROM guests WHERE has_submitted = 1"
        ).fetchall()

        scored = []
        for g in submitted:
            guess = bets_by_guest.get(g['name'], {})
            breeds = set(actual) | set(guess)
            score = round(sum(abs(actual.get(b, 0.0) - guess.get(b, 0.0)) for b in breeds) / 2, 1)
            scored.append((score, g['submitted_at'] or '', g['name']))

        scored.sort(key=lambda x: (x[0], x[1]))
        for i, (score, _submitted_at, name) in enumerate(scored, start=1):
            conn.execute(
                "UPDATE guests SET score = ?, rank = ? WHERE name = ?", (score, i, name)
            )


def get_guest_score_rank(name):
    """Return {'score', 'rank', 'total'} for a submitted, scored guest, or None.

    Reads the precomputed columns (see recompute_scores) — no leaderboard computation.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT score, rank FROM guests WHERE name = ? AND has_submitted = 1",
            (str(name).strip(),)
        ).fetchone()
        total = conn.execute(
            "SELECT COUNT(*) FROM guests WHERE has_submitted = 1 AND score IS NOT NULL"
        ).fetchone()[0]
    if not row or row['score'] is None:
        return None
    return {'score': row['score'], 'rank': row['rank'], 'total': total}


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


# ── Admin: Actual Results (read-only — values are code-seeded, see RESULT_SETS) ──

def get_results_by_set():
    """All result sets grouped for the admin read-only display:
    {set_name: [{'breed', 'actual_percentage'}, ...]} sorted by percentage desc."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT breed, actual_percentage, result_set FROM actual_results "
            "ORDER BY result_set, actual_percentage DESC"
        ).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r['result_set'], []).append(
            {'breed': r['breed'], 'actual_percentage': r['actual_percentage']}
        )
    return grouped


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
