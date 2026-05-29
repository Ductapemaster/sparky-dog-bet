"""Generate WebP thumbnails and display versions for all existing gallery images.

Run inside the container after rebuilding:
    docker exec sparky-dog-bet-web-1 python generate_thumbnails.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app.db import (
    _gallery_dir, _thumbs_dir, _thumb_filename, generate_thumbnail,
    _display_dir, _display_filename, generate_display,
)

gallery = _gallery_dir()
images  = sorted(
    f for f in os.listdir(gallery)
    if os.path.isfile(os.path.join(gallery, f))
    and f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
)

print(f"Found {len(images)} images in {gallery}\n")

for filename in images:
    orig_kb    = os.path.getsize(os.path.join(gallery, filename)) // 1024
    thumb_path = os.path.join(_thumbs_dir(),  _thumb_filename(filename))
    disp_path  = os.path.join(_display_dir(), _display_filename(filename))

    if not os.path.exists(thumb_path):
        generate_thumbnail(filename)
        t = f"{os.path.getsize(thumb_path)//1024}KB" if os.path.exists(thumb_path) else "FAIL"
    else:
        t = "exists"

    if not os.path.exists(disp_path):
        generate_display(filename)
        d = f"{os.path.getsize(disp_path)//1024}KB" if os.path.exists(disp_path) else "FAIL"
    else:
        d = "exists"

    print(f"  {filename:<28}  orig:{orig_kb:5d}KB  thumb:{t}  display:{d}")

print("\nDone.")
