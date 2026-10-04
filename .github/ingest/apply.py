#!/usr/bin/env python3
"""Apply Collider ingest requests (ingest/requests/*.json) to this repo.

Request format:
{
  "id": "20261004T140501Z-1a2b3c",
  "base_themes_sha256": "<sha256 of themes.json the request was built against>",
  "files": [{"path": "themes/<slug>/loop.<hash>.mp4", "sha256": "...", "size": 123,
             "drive_id": "<public Drive file id>", "url": "<optional direct URL>"}],
  "themes_json": "<the complete new themes.json text>"
}
Rules: a published file is never overwritten (same path must have identical bytes); themes.json is only
replaced when every file downloaded and verified and every media ref in it exists; media this job
published earlier and that nothing references any more is removed (ingest/published.json). Media
published by anyone else is never touched.
"""
import glob, hashlib, json, os, re, subprocess, sys, time, urllib.request

ROOT = os.getcwd()
REQ_DIR = os.path.join(ROOT, 'ingest', 'requests')
PUBLISHED = os.path.join(ROOT, 'ingest', 'published.json')
RESULT = os.path.join(ROOT, 'ingest', 'last-result.json')
SAFE_PATH = re.compile(r'^(themes|tracks)/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$')


def out(k, v):
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a') as f:
        f.write(f'{k}={v}\n')


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def bare(ref):
    return ref.split('?', 1)[0].split('#', 1)[0] if isinstance(ref, str) else None


def refs(cat):
    r = []
    for t in cat.get('themes', []):
        for k in ('poster', 'video', 'still', 'preview', 'image'):
            if isinstance(t.get(k), str): r.append(t[k])
        for tr in t.get('tracks') or []:
            for k in ('audio', 'art'):
                if isinstance(tr.get(k), str): r.append(tr[k])
    for a in cat.get('ambientTracks') or []:
        for k in ('audio', 'art'):
            if isinstance(a.get(k), str): r.append(a[k])
    return [bare(x) for x in r if x and not re.match(r'^[a-z]+:', x) and not x.startswith('assets/')]


def download(f, dest):
    urls = [f['url']] if f.get('url') else []
    if f.get('drive_id'):
        urls.append(f"https://drive.usercontent.google.com/download?id={f['drive_id']}&export=download&confirm=t")
    last = None
    for attempt in range(4):
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={'User-Agent': 'collider-ingest/1'})
                with urllib.request.urlopen(req, timeout=120) as r, open(dest + '.part', 'wb') as w:
                    while True:
                        b = r.read(1 << 20)
                        if not b: break
                        w.write(b)
                size, digest = os.path.getsize(dest + '.part'), sha256_file(dest + '.part')
                if size == f['size'] and digest == f['sha256']:
                    os.replace(dest + '.part', dest); return
                last = f'{u}: got {size} bytes sha256 {digest[:12]}, expected {f["size"]} / {f["sha256"][:12]}'
            except Exception as e:
                last = f'{u}: {e}'
            if os.path.exists(dest + '.part'): os.remove(dest + '.part')
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f'download failed for {f["path"]}: {last}')


def _fetch_all(req, written):
    for f in req.get('files') or []:
        p = f['path']
        if not SAFE_PATH.match(p) or '..' in p: raise RuntimeError(f'unsafe path {p!r}')
        dest = os.path.join(ROOT, p)
        if os.path.exists(dest):
            if sha256_file(dest) == f['sha256']: continue          # already published, identical
            raise RuntimeError(f'refusing to overwrite published file {p}')
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        download(f, dest); written.append(p)


def apply(req, published):
    cur = os.path.join(ROOT, 'themes.json')
    base = sha256_file(cur) if os.path.exists(cur) else None
    if req.get('base_themes_sha256') and req['base_themes_sha256'] != base:
        raise RuntimeError('stale request: themes.json changed since it was built; the sync will rebuild it')
    new_text = req['themes_json']
    cat = json.loads(new_text)
    if not cat.get('themes'): raise RuntimeError('refusing an empty catalog')
    written = []
    try:
        _fetch_all(req, written)
    except Exception:
        for p in written: os.remove(os.path.join(ROOT, p))
        raise
    missing = sorted({r for r in refs(cat) if not os.path.exists(os.path.join(ROOT, r))})
    if missing:
        for p in written: os.remove(os.path.join(ROOT, p))
        raise RuntimeError('catalog references missing media: ' + ', '.join(missing[:10]))
    with open(cur, 'w', encoding='utf-8', newline='') as w:
        w.write(new_text)
    published.update(written)
    live = set(refs(cat)); removed = []
    for p in sorted(published):
        if p not in live and os.path.exists(os.path.join(ROOT, p)):
            subprocess.run(['git', 'rm', '-q', '--', p], check=True); removed.append(p)
    published.difference_update(removed)
    return written, removed


def main():
    reqs = sorted(glob.glob(os.path.join(REQ_DIR, '*.json')))
    if not reqs:
        print('no ingest requests'); out('changed', 'false'); return
    published = set(json.load(open(PUBLISHED))) if os.path.exists(PUBLISHED) else set()
    results, rejected, msgs = [], False, []
    for rp in reqs:
        rid = os.path.splitext(os.path.basename(rp))[0]
        try:
            req = json.load(open(rp, encoding='utf-8'))
            written, removed = apply(req, published)
            results.append({'id': req.get('id', rid), 'status': 'applied', 'written': written, 'removed': removed,
                            'themes_sha256': sha256_file(os.path.join(ROOT, 'themes.json'))})
            msgs.append(f'{rid}: +{len(written)} -{len(removed)}')
            print(f'applied {rid}: wrote {written}, removed {removed}')
        except Exception as e:
            rejected = True
            results.append({'id': rid, 'status': 'rejected', 'error': str(e)})
            msgs.append(f'{rid}: rejected'); print(f'REJECTED {rid}: {e}')
        subprocess.run(['git', 'rm', '-q', '--', os.path.relpath(rp, ROOT)], check=True)
    os.makedirs(os.path.dirname(PUBLISHED), exist_ok=True)
    json.dump(sorted(published), open(PUBLISHED, 'w'), indent=1)
    json.dump({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'run': os.environ.get('GITHUB_RUN_ID'),
               'results': results}, open(RESULT, 'w'), indent=1)
    out('changed', 'true'); out('rejected', 'true' if rejected else 'false')
    out('message', ('Collider ingest: ' + '; '.join(msgs))[:200])


if __name__ == '__main__':
    main()
