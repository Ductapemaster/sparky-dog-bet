"""
import_guests.py — Bulk-load guests into the SQLite database from a CSV file.

Usage:
    source .venv/bin/activate
    python import_guests.py guests.csv

CSV format (header row required):
    name,phone4
    Dan Kouba,1234
    Jane Smith,5678

For each row:
  - If the guest does not exist, they are inserted.
  - If the guest already exists, they are deleted and re-inserted (updating phone4 if changed).
    Any existing bets for that guest are also deleted — run this before the game starts only.

Requires DB_PATH to be set (via .env or environment variable).
"""

import csv
import sys
import os
from dotenv import load_dotenv

load_dotenv()

# Import db after loading .env so DB_PATH is available
from app import db

def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'guests_template.csv'

    if not os.path.exists(csv_path):
        print(f'Error: file not found: {csv_path}')
        sys.exit(1)

    db.init_db()

    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print('No rows found in CSV.')
        sys.exit(0)

    added = updated = skipped = 0

    existing = {g['name']: g for g in db.get_all_guests()}

    for row in rows:
        name   = row.get('name', '').strip()
        phone4 = row.get('phone4', '').strip() or None

        if not name:
            continue

        if name in existing:
            g = existing[name]
            stored_pin = g['phone4'] or None
            if stored_pin == phone4:
                skipped += 1
                continue
            # Data changed — delete and re-insert
            db.delete_guest(g['id'])
            db.add_guest(name, phone4)
            updated += 1
        else:
            db.add_guest(name, phone4)
            added += 1

    print(f'Done. Added: {added}  Updated: {updated}  Skipped (unchanged): {skipped}')
    print(f'Total guests in DB: {len(db.get_all_guests())}')


if __name__ == '__main__':
    main()
