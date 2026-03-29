"""
sync_breeds.py — Replace the breeds table with the current contents of breeds.txt.
Run once after updating breeds.txt:
    source .venv/bin/activate
    python sync_breeds.py
"""
import os, sqlite3, sys

db_path = os.environ.get('DB_PATH', 'data/sparky.db')
breeds_path = os.path.join(os.path.dirname(__file__), 'breeds.txt')

if not os.path.exists(breeds_path):
    sys.exit(f"breeds.txt not found at {breeds_path}")

with open(breeds_path) as f:
    breeds = [l.strip() for l in f if l.strip() and l.strip().lower() != 'breedname']

conn = sqlite3.connect(db_path)
conn.execute("DELETE FROM breeds")
conn.executemany("INSERT OR IGNORE INTO breeds (breed_name) VALUES (?)", [(b,) for b in breeds])
conn.commit()
conn.close()

print(f"Synced {len(breeds)} breeds from breeds.txt into {db_path}")
