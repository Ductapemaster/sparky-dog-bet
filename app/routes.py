import os
from itertools import groupby
from flask import Blueprint, render_template, request, session, redirect, url_for, send_from_directory, g
from werkzeug.utils import secure_filename
from . import db, scoring

bp = Blueprint('main', __name__)


@bp.app_context_processor
def inject_nav_status():
    return dict(nav_status=_status())


def _status():
    if 'status' not in g:
        g.status = {
            'locked':      db.is_true(db.get_config('BettingLocked')),
            'require_pin': db.is_true(db.get_config('RequirePin')),
            'revealed':    db.is_true(db.get_config('ResultsRevealed')),
        }
    return g.status


def _require_admin():
    """Return a redirect if not authenticated, else None."""
    if not session.get('admin_auth'):
        return redirect(url_for('main.admin'))
    return None


# ── Gallery image serving ─────────────────────────────────────

@bp.route('/gallery-img/<filename>')
def gallery_img(filename):
    return send_from_directory(db._gallery_dir(), filename, max_age=3600)


# ── Public pages ──────────────────────────────────────────────

@bp.route('/')
def home():
    return render_template('home.html')


@bp.route('/gallery')
def gallery():
    return render_template('gallery.html', images=db.get_gallery_images())


@bp.route('/about')
def about():
    return render_template('about.html', images=db.get_gallery_images())


@bp.route('/leaderboard')
def leaderboard():
    status = _status()
    lb = scoring.get_leaderboard() if status['revealed'] else []
    return render_template('leaderboard.html',
        leaderboard=lb, actual=db.get_actual_results(), status=status)


# ── Bet / My Bet (single page) ────────────────────────────────

@bp.route('/bet')
def bet():
    status = _status()
    guest  = session.get('guest')

    if guest and guest.get('verified'):
        if guest.get('has_submitted'):
            bet_rows = db.get_bet(guest['name'])
            if not bet_rows:
                # No bet rows in DB — session is stale (e.g. from a prior app version).
                # Look up the real state from DB and correct the session.
                fresh = db.get_all_guests()
                db_guest = next((g for g in fresh if g['name'] == guest['name']), None)
                if db_guest and not db_guest['has_submitted']:
                    session['guest'] = {**guest, 'has_submitted': False, 'submitted_at': None}
                    guest = session['guest']
                    # Fall through to locked / form view below
                else:
                    # DB also says submitted (or guest not found) — show empty submitted view
                    return render_template('bet.html',
                        show_submitted=True, guest=guest, bet=[],
                        leaderboard=scoring.get_leaderboard() if status['revealed'] else None,
                        actual_results=db.get_actual_results() if status['revealed'] else None,
                        score=None,
                        status=status)
            else:
                # Normal path — bet rows exist, refresh submitted_at if missing
                if not guest.get('submitted_at'):
                    fresh_g = next(
                        (g for g in db.get_all_guests() if g['name'] == guest['name']), {}
                    )
                    if fresh_g.get('submitted_at'):
                        guest['submitted_at'] = fresh_g['submitted_at']
                        session['guest'] = guest
                return render_template('bet.html',
                    show_submitted=True, guest=guest,
                    bet=bet_rows,
                    leaderboard=scoring.get_leaderboard() if status['revealed'] else None,
                    actual_results=db.get_actual_results() if status['revealed'] else None,
                    score=scoring.calculate_score(guest['name']) if status['revealed'] else None,
                    status=status)
        if status['locked']:
            locked_bet = db.get_bet(guest['name'])
            return render_template('bet.html', locked=True, guest=guest,
                bet=locked_bet,
                leaderboard=scoring.get_leaderboard() if status['revealed'] else None,
                actual_results=db.get_actual_results() if status['revealed'] and locked_bet else None,
                score=scoring.calculate_score(guest['name']) if status['revealed'] and locked_bet else None,
                status=status)
        return render_template('bet.html',
            show_form=True, guest=guest,
            breeds=db.get_breeds(), status=status)

    return render_template('bet.html',
        guest_names=db.get_guest_names(), status=status)


@bp.route('/bet/verify', methods=['POST'])
def bet_verify():
    name   = request.form.get('name', '').strip()
    phone4 = request.form.get('phone4', '').strip()

    result = db.verify_guest(name, phone4)
    if not result['verified']:
        return render_template('bet.html',
            guest_names=db.get_guest_names(),
            status=_status(), error=result['error'], selected_name=name)

    session['guest'] = {
        'name': name, 'phone4': phone4,
        'verified': True, 'has_submitted': result['has_submitted'],
        'submitted_at': result.get('submitted_at'),
    }
    return redirect(url_for('main.bet'))


@bp.route('/bet/submit', methods=['POST'])
def bet_submit():
    guest = session.get('guest')
    if not guest or not guest.get('verified'):
        return redirect(url_for('main.bet'))

    breed_names = request.form.getlist('breed[]')
    percentages = request.form.getlist('percentage[]')
    breeds = [
        {'breed': b.strip(), 'percentage': p}
        for b, p in zip(breed_names, percentages) if b.strip()
    ]

    result = db.submit_bet(guest['name'], guest['phone4'], breeds)
    if not result['success']:
        return render_template('bet.html',
            show_form=True, guest=guest,
            breeds=db.get_breeds(), status=_status(),
            error=result['error'], submitted_breeds=breeds)

    session['guest'] = {**guest, 'has_submitted': True, 'submitted_at': result.get('submitted_at')}
    return redirect(url_for('main.bet'))


# ── Admin ─────────────────────────────────────────────────────

@bp.route('/admin')
def admin():
    if not session.get('admin_auth'):
        return render_template('admin.html', show_login=True)

    status    = _status()
    guests    = db.get_all_guests()
    submitted = sum(1 for g in guests if g['has_submitted'])

    lb = scoring.get_leaderboard()
    actual = db.get_actual_results()

    all_bets_raw = db.get_all_bets()
    guests_by_name = {g['name']: g for g in guests}
    grouped_bets = []
    for guest_name, group in groupby(all_bets_raw, key=lambda b: b['guest_name']):
        bets_list = list(group)
        g_info = guests_by_name.get(guest_name, {})
        grouped_bets.append({
            'guest_name': guest_name,
            'guest_id':   g_info.get('id'),
            'bets':       bets_list,
        })

    return render_template('admin.html',
        status=status, guests=guests,
        submitted=submitted, total=len(guests),
        leaderboard=lb,
        has_actual=bool(actual),
        actual=actual,
        grouped_bets=grouped_bets,
        all_bets=all_bets_raw,
        actual_results=db.get_all_actual_results(),
        gallery=db.get_all_gallery(),
        breeds=db.get_breeds(),
        all_breeds=db.get_all_breeds())


@bp.route('/admin/login', methods=['POST'])
def admin_login():
    if request.form.get('password', '') == str(db.get_config('AdminPassword')):
        session['admin_auth'] = True
        return redirect(url_for('main.admin'))
    return render_template('admin.html', show_login=True, error='Incorrect password.')


@bp.route('/admin/toggle/<key>', methods=['POST'])
def admin_toggle(key):
    if not session.get('admin_auth'):
        return redirect(url_for('main.admin'))
    if key not in {'BettingLocked', 'ResultsRevealed', 'RequirePin'}:
        return redirect(url_for('main.admin'))
    current = db.get_config(key)
    db.set_config(key, not db.is_true(current))
    return redirect(url_for('main.admin'))


@bp.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_auth', None)
    return redirect(url_for('main.admin'))


# ── Admin: Guest CRUD ─────────────────────────────────────────

@bp.route('/admin/guests/add', methods=['POST'])
def admin_guests_add():
    if denied := _require_admin(): return denied
    name   = request.form.get('name', '').strip()
    phone4 = request.form.get('phone4', '').strip() or None
    if name:
        try:
            db.add_guest(name, phone4)
        except Exception:
            pass  # duplicate name — silently ignore
    return redirect(url_for('main.admin'))


@bp.route('/admin/guests/<int:guest_id>/edit', methods=['POST'])
def admin_guests_edit(guest_id):
    if denied := _require_admin(): return denied
    name   = request.form.get('name', '').strip()
    phone4 = request.form.get('phone4', '').strip() or None
    if name:
        db.update_guest(guest_id, name, phone4)
    return redirect(url_for('main.admin'))


@bp.route('/admin/guests/<int:guest_id>/delete', methods=['POST'])
def admin_guests_delete(guest_id):
    if denied := _require_admin(): return denied
    db.delete_guest(guest_id)
    return redirect(url_for('main.admin'))


@bp.route('/admin/guests/<int:guest_id>/reset-bet', methods=['POST'])
def admin_guests_reset_bet(guest_id):
    if denied := _require_admin(): return denied
    guests = db.get_all_guests()
    guest  = next((g for g in guests if g['id'] == guest_id), None)
    if guest:
        db.reset_guest_bet(guest['name'])
    return redirect(url_for('main.admin'))


# ── Admin: Bet CRUD ───────────────────────────────────────────

@bp.route('/admin/bets/add', methods=['POST'])
def admin_bets_add():
    if denied := _require_admin(): return denied
    guest_name = request.form.get('guest_name', '').strip()
    breed      = request.form.get('breed', '').strip()
    pct        = request.form.get('percentage', '').strip()
    if guest_name and breed and pct:
        db.add_bet_row(guest_name, breed, int(float(pct)))
    return redirect(url_for('main.admin'))


@bp.route('/admin/bets/<int:bet_id>/edit', methods=['POST'])
def admin_bets_edit(bet_id):
    if denied := _require_admin(): return denied
    breed = request.form.get('breed', '').strip()
    pct   = request.form.get('percentage', '').strip()
    if breed and pct:
        db.update_bet(bet_id, breed, int(float(pct)))
    return redirect(url_for('main.admin'))


@bp.route('/admin/bets/<int:bet_id>/delete', methods=['POST'])
def admin_bets_delete(bet_id):
    if denied := _require_admin(): return denied
    db.delete_bet(bet_id)
    return redirect(url_for('main.admin'))


@bp.route('/admin/wipe-all-bets', methods=['POST'])
def admin_wipe_all_bets():
    if denied := _require_admin(): return denied
    db.wipe_all_bets()
    return redirect(url_for('main.admin'))


# ── Admin: Breed CRUD ────────────────────────────────────────

@bp.route('/admin/breeds/add', methods=['POST'])
def admin_breeds_add():
    if denied := _require_admin(): return denied
    name = request.form.get('breed_name', '').strip()
    if name:
        db.add_breed(name)
    return redirect(url_for('main.admin'))


@bp.route('/admin/breeds/<int:breed_id>/edit', methods=['POST'])
def admin_breeds_edit(breed_id):
    if denied := _require_admin(): return denied
    name = request.form.get('breed_name', '').strip()
    if name:
        db.update_breed(breed_id, name)
    return redirect(url_for('main.admin'))


@bp.route('/admin/breeds/<int:breed_id>/delete', methods=['POST'])
def admin_breeds_delete(breed_id):
    if denied := _require_admin(): return denied
    db.delete_breed(breed_id)
    return redirect(url_for('main.admin'))


# ── Admin: Actual Results CRUD ────────────────────────────────

@bp.route('/admin/actual/add', methods=['POST'])
def admin_actual_add():
    if denied := _require_admin(): return denied
    breed = request.form.get('breed', '').strip()
    pct   = request.form.get('pct', '').strip()
    if breed and pct:
        try:
            db.upsert_actual_result(breed, int(float(pct)))
        except ValueError:
            pass
    return redirect(url_for('main.admin'))


@bp.route('/admin/actual/<int:result_id>/edit', methods=['POST'])
def admin_actual_edit(result_id):
    if denied := _require_admin(): return denied
    breed = request.form.get('breed', '').strip()
    pct   = request.form.get('pct', '').strip()
    if breed and pct:
        try:
            db.delete_actual_result(result_id)
            db.upsert_actual_result(breed, int(float(pct)))
        except ValueError:
            pass
    return redirect(url_for('main.admin'))


@bp.route('/admin/actual/<int:result_id>/delete', methods=['POST'])
def admin_actual_delete(result_id):
    if denied := _require_admin(): return denied
    db.delete_actual_result(result_id)
    return redirect(url_for('main.admin'))


# ── Admin: Gallery CRUD ───────────────────────────────────────

_ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


@bp.route('/admin/gallery/upload', methods=['POST'])
def admin_gallery_upload():
    if denied := _require_admin(): return denied
    file       = request.files.get('image')

    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext in _ALLOWED_IMAGE_EXTS:
            gallery_dir = db._gallery_dir()
            os.makedirs(gallery_dir, exist_ok=True)
            filename = secure_filename(file.filename)
            # Avoid collisions
            base, ext = os.path.splitext(filename)
            candidate, n = filename, 1
            while os.path.exists(os.path.join(gallery_dir, candidate)):
                candidate = f"{base}_{n}{ext}"
                n += 1
            file.save(os.path.join(gallery_dir, candidate))
            try:
                db.add_gallery_image(candidate)
            except ValueError:
                pass

    return redirect(url_for('main.admin'))


@bp.route('/admin/gallery/reorder', methods=['POST'])
def admin_gallery_reorder():
    if not session.get('admin_auth'):
        return '', 403
    data  = request.get_json(silent=True) or {}
    order = data.get('order', [])
    if order:
        db.reorder_gallery(order)
    return '', 204


@bp.route('/admin/gallery/<int:image_id>/delete', methods=['POST'])
def admin_gallery_delete(image_id):
    if denied := _require_admin(): return denied
    db.delete_gallery_image(image_id)
    return redirect(url_for('main.admin'))
