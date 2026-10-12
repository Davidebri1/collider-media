"""Remove the machine-named default wallpaper and finish the rename pass.

- deletes the theme the catalog boots onto (the UUID-named anime clip)
- points defaultSlug at a curated 4K loop instead
- gives every remaining machine-named track title the curated theme name
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "themes.json"

MACHINE = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-)"
    r"|(?:_\d{3,4}x\d{3,4}$)"
    r"|(?:_medium$)"
    r"|(?:^(?:\d{9,}|video\d+|\d+_[A-Za-z]))",
    re.I,
)

# The theme the app boots onto. Named "Reader by the Window" after the rename,
# but it is a stray source clip, not a curated piece.
DROP_SLUG = "0251d1e0-16a1-49ad-9807-19d1bceac3e9-1080-hd-nksdeh"
NEW_DEFAULT = None  # chosen below from the catalog itself

raw = CATALOG.read_bytes()
data = json.loads(raw.decode("utf-8"))

before = len(data["themes"])
data["themes"] = [t for t in data["themes"] if t["slug"] != DROP_SLUG]
dropped = before - len(data["themes"])

# Pick the new default: the highest-resolution landscape loop whose name is
# already curated. Deterministic, so re-running changes nothing.
candidates = [
    t for t in data["themes"]
    if t.get("video") and not MACHINE.search(t["name"])
]
best = max(candidates, key=lambda t: (min(t.get("width") or 0, t.get("height") or 0), t["width"] * t["height"]))
NEW_DEFAULT = best["slug"]

data["defaultSlug"] = NEW_DEFAULT

# Every track that still carries a machine title borrows its theme's name.
renamed_tracks = 0
for t in data["themes"]:
    for tr in t.get("tracks") or []:
        if MACHINE.search(tr.get("title") or "") or not (tr.get("title") or "").strip():
            tr["title"] = t["name"]
            renamed_tracks += 1

out = json.dumps(data, indent=1, ensure_ascii=False)
# The published file is CRLF; reproduce it byte-for-byte apart from our edits.
if b"\r\n" in raw:
    out = out.replace("\n", "\r\n")

CATALOG.write_bytes(out.encode("utf-8"))

folder = ROOT / "themes" / DROP_SLUG
if folder.exists():
    shutil.rmtree(folder)

print(f"themes before      {before}")
print(f"themes after       {len(data['themes'])}")
print(f"removed            {dropped}  ({DROP_SLUG})")
print(f"folder deleted     {not folder.exists()}")
print(f"new defaultSlug    {NEW_DEFAULT}  ({best['name']}, {best['width']}x{best['height']})")
print(f"track titles fixed {renamed_tracks}")
print(f"machine names left {sum(1 for t in data['themes'] if MACHINE.search(t['name']))}")

# validate
re = json.loads(CATALOG.read_bytes().decode("utf-8"))
missing = [t["slug"] for t in re["themes"] if not (ROOT / t["poster"]).exists()]
missing += [t["slug"] for t in re["themes"] if t.get("video") and not (ROOT / t["video"]).exists()]
print(f"missing assets     {len(missing)}")
if missing:
    print("  " + ", ".join(missing[:10]))
    sys.exit(1)