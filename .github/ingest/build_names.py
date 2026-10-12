"""Generate ingest/names.json — the curated names drive_sync.py must preserve.

The sync bot derives every theme name from the Drive filename
(`'name': stem(e['name'])`) and then does `cat['themes'] = themes`, which
discards any hand-curated name. That is why 114 curated names kept reverting
to machine slugs.

This writes the curated name for every current theme, keyed by slug (the slug
is stable — the bot reuses it for the same Drive id), plus the slugs to skip
and the default boot wallpaper. drive_sync.py reads it on every run.
"""
import json, os, re, sys

CAT = 'themes.json'
OUT = os.path.join('ingest', 'names.json')

MACHINE = re.compile(r'^(untitled\b|\d{4}-\d{2}-\d{2}|[0-9a-f]{8})', re.I)

cat = json.load(open(CAT, encoding='utf-8'))
names = {}
for t in cat['themes']:
    n = (t.get('name') or '').strip()
    if n and not MACHINE.match(n):
        names[t['slug']] = n

# The anime boot clip is retired. The file is still on Drive, so the bot
# re-adds it every run and resets defaultSlug to it. Exclude by slug
# unconditionally: the local folder is already gone, so isdir would miss it.
RETIRED = ['0251d1e0-16a1-49ad-9807-19d1bceac3e9-1080-hd-nksdeh']
exclude = list(RETIRED)

os.makedirs('ingest', exist_ok=True)
doc = {
    '_comment': 'Curated theme names. drive_sync.py MUST use these instead of the Drive filename.',
    'names': names,
    'exclude': exclude,
    'defaultSlug': cat.get('defaultSlug'),
}
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(doc, f, indent=1, ensure_ascii=False)
    f.write('\n')
print(f'wrote {len(names)} curated names, {len(exclude)} excluded, default={doc["defaultSlug"]}')
