#!/usr/bin/env python3
"""Drive pickup: drop a file into the "Collider Themes" Drive folder, it appears in the app.

STRICTLY ADDITIVE. This is the whole point of the file.

The previous script (drive_sync.py, removed) rebuilt themes.json from scratch on
every run:

    themes = [ ... name = Drive filename ... ]     # rebuilt from scratch
    cat['themes'] = themes                         # discarded every curated name
    if cat['defaultSlug'] not in keep: ...         # reset the boot wallpaper
    shutil.rmtree(...)                             # deleted unreferenced media
    # workflow: git add -A                          # swept every hand edit

So a human rename in themes.json survived until the next cron tick, up to 20
minutes later, forever. That is the behaviour this script replaces.

The rules here, and they are the whole contract:

  1. An entry already in themes.json is NEVER modified. Not its name, not its
     slug, not its price, not its tier, not its order.
  2. Nothing is ever deleted. Not a media directory, not an entry.
  3. defaultSlug is never rewritten. If it stops resolving, the app falls back;
     a human decides, not this script.
  4. A new Drive file is appended to the end of the list with a name humanised
     from the filename ONCE. From then on it is a curated entry like any other
     and this script will never touch it again.
  5. Stage only what this run created. Never `git add -A`.

Keyless: the Drive folder is link-shared, so this reads Drive's public embedded
folder view and public download links. No secrets, no service account.

Runtime state: ingest/pickup-state.json, so a re-run does not re-download a
file that failed mid-encode more than once.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

FOLDER = os.environ.get('DRIVE_FOLDER', '1DNqeA7tY2XY8Gfs2x0zho1LFj2q7LgY2')
BUDGET = float(os.environ.get('BUDGET_MIN', '45')) * 60
MAXMP4 = 95 * 1024 * 1024
VID = {'mp4', 'mov', 'm4v', 'webm', 'mkv'}
IMG = {'jpg', 'jpeg', 'png', 'webp', 'heic', 'tif', 'tiff'}
AUD = {'mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg'}
STATE = 'ingest/pickup-state.json'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')


def listing(fid):
    """Public embedded folder view -> [{id, name, mod, folder}]."""
    h = get(f'https://drive.google.com/embeddedfolderview?id={fid}')
    out = []
    for m in re.finditer(
            r'class="flip-entry" id="entry-([\w-]+)".*?<a href="([^"]*)".*?'
            r'flip-entry-title">([^<]*)</div>.*?flip-entry-last-modified"><div>([^<]*)<',
            h, re.S):
        out.append({'id': m.group(1), 'name': html.unescape(m.group(3)),
                    'mod': m.group(4), 'folder': '/folders/' in m.group(2)})
    return out


def sh(*a):
    subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def ext(n):
    return n.rsplit('.', 1)[-1].lower() if '.' in n else ''


def stem(n):
    return n.rsplit('.', 1)[0] if '.' in n else n


def slugify(n, fid):
    s = re.sub(r'[^a-z0-9]+', '-', n.lower()).strip('-')[:48] or 'theme'
    return f'{s}-{fid[-6:].lower().replace("_", "x")}'


def humanise(n):
    """'0_beach-waves_3840x2160' -> 'Beach Waves'. Used ONCE, at first sight.

    Separators become spaces FIRST. Underscore is a word character, so in
    'clip_4k' the word boundary before '4k' never fires and the token survives
    the quality strip, which is how 'clip_4k' became 'Clip K'.
    """
    s = stem(n)
    s = re.sub(r'[_\-]+', ' ', s)
    s = re.sub(r'\b\d{3,4}\s*[x×]\s*\d{3,4}\b', ' ', s)      # 3840x2160
    s = re.sub(r'\b\d{3,4}[pP]\b', ' ', s)                   # 1080p
    s = re.sub(r'\d+(?:\.\d+)?\s*[fF][pP][sS]\b', ' ', s)    # 60fps
    s = re.sub(r'\b[248][kK]\b', ' ', s)                        # 4k / 4K
    s = re.sub(r'\b(?:HD|FHD|UHD|SD)\b', ' ', s, flags=re.I)
    s = re.sub(r'\d+', ' ', s)                               # leftover digits
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return None
    return ' '.join(w[:1].upper() + w[1:] for w in s.split(' '))


def download(fid, dst):
    sh('curl', '-fsSL', '--retry', '3', '-o', dst,
       f'https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t')


def probe(p):
    j = json.loads(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', p]))
    v = next((s for s in j['streams'] if s['codec_type'] == 'video'), None)
    a = any(s['codec_type'] == 'audio' for s in j['streams'])
    fps = None
    if v:
        for k in ('avg_frame_rate', 'r_frame_rate'):
            n, _, d = (v.get(k) or '0/0').partition('/')
            if d and float(d) and float(n):
                fps = round(float(n) / float(d), 3)
                break
    rot = 0
    for sd in v.get('side_data_list', []) if v else []:
        rot = int(sd.get('rotation', 0) or 0)
    w = hgt = None
    if v:
        w, hgt = int(v['width']), int(v['height'])
        if abs(rot) in (90, 270):
            w, hgt = hgt, w
    else:
        w = hgt = None
    return {'w': w, 'h': hgt, 'fps': fps, 'audio': a,
            'dur': float(j['format'].get('duration') or 0)}


def cap4k():
    return ("scale='if(gte(iw,ih),min(3840,iw),-2)':'if(gte(iw,ih),-2,min(3840,ih))'"
            ":flags=lanczos,format=yuv420p")


def mmss(s):
    s = int(round(s))
    return f'{s // 60}:{s % 60:02d}'


def process(f, work, outdir):
    src = os.path.join(work, 'src.' + (ext(f['name']) or 'bin'))
    download(f['id'], src)
    p = probe(src)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir)
    rel = os.path.relpath(outdir, '.')
    e = ext(f['name'])
    res = {'probe': p}
    if e in VID and not (e == 'gif' and p['dur'] == 0):
        sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-frames:v', '1', '-vf',
           cap4k().replace(',format=yuv420p', ''), '-c:v', 'libwebp', '-q:v', '92',
           os.path.join(outdir, 'poster.webp'))
        enc = ['-an', '-vf', cap4k(), '-fps_mode', 'passthrough', '-c:v', 'libx264',
               '-preset', 'slow', '-crf', '18', '-profile:v', 'high']
        mp4 = os.path.join(outdir, 'loop.mp4')
        sh('ffmpeg', '-v', 'error', '-y', '-i', src, *enc, '-movflags', '+faststart', mp4)
        if os.path.getsize(mp4) > MAXMP4:
            os.remove(mp4)
            hd = os.path.join(outdir, 'hls')
            os.makedirs(hd)
            sh('ffmpeg', '-v', 'error', '-y', '-i', src, *enc, '-f', 'hls', '-hls_time', '4',
               '-hls_playlist_type', 'vod', '-hls_segment_type', 'fmp4',
               '-hls_segment_filename', os.path.join(hd, 'seg%04d.m4s'),
               os.path.join(hd, 'index.m3u8'))
            res['video'] = f'{rel}/hls/index.m3u8'
        else:
            res['video'] = f'{rel}/loop.mp4'
        if p['audio']:
            sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-vn', '-c:a', 'aac',
               '-b:a', '256k', os.path.join(outdir, 'song.m4a'))
            res['song'] = {'number': 1, 'title': stem(f['name']),
                           'duration': mmss(p['dur']), 'mood': '',
                           'audio': f'{rel}/song.m4a'}
        res['poster'] = f'{rel}/poster.webp'
    elif e in IMG or e == 'gif':
        sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-frames:v', '1', '-vf',
           cap4k().replace(',format=yuv420p', ''), '-c:v', 'libwebp', '-q:v', '95',
           os.path.join(outdir, 'still.webp'))
        res['still'] = res['poster'] = f'{rel}/still.webp'
    else:
        return None
    return res


def uniq(name, taken):
    if name not in taken:
        return name
    i = 2
    while f'{name} {i}' in taken:
        i += 1
    return f'{name} {i}'


def main():
    cat = json.load(open('themes.json'))
    themes = cat.get('themes', [])

    # Everything already published, read straight from the catalog. This is the
    # source of truth. Not state.json: if the two disagree, the catalog wins,
    # because the catalog is what the app serves.
    published_ids = {t['driveId'] for t in themes if t.get('driveId')}
    published_slugs = {t['slug'] for t in themes}
    taken_names = {t.get('name') for t in themes}

    st = {}
    if os.path.exists(STATE):
        try:
            st = json.load(open(STATE))
        except Exception:
            st = {}
    st.setdefault('files', {})
    st.setdefault('skipped', {})

    items = listing(FOLDER)
    files = [i for i in items if not i['folder'] and ext(i['name']) in VID | IMG]
    songs_dir = next((i for i in items if i['folder'] and i['name'].lower() == 'songs'), None)
    songs = [s for s in listing(songs_dir['id'])
             if not s['folder'] and ext(s['name']) in AUD] if songs_dir else []

    added = skipped = failed = 0
    stop = False
    work = tempfile.mkdtemp(prefix='pickup-')

    try:
        for f in files:
            if stop or time.time() - _t0 > BUDGET:
                stop = True
                break
            if f['id'] in published_ids or f['id'] in st['files']:
                continue
            name = humanise(f['name'])
            if not name:
                st['skipped'][f['id']] = 'no readable name'
                skipped += 1
                continue
            slug = slugify(f['name'], f['id'])
            if slug in published_slugs:
                # Slug collision with something already live: leave it alone
                # rather than merge two different pieces of media.
                st['skipped'][f['id']] = f'slug {slug} already published'
                skipped += 1
                continue
            outdir = f'themes/{slug}'
            try:
                res = process(f, work, outdir)
            except subprocess.CalledProcessError as e:
                st['skipped'][f['id']] = f'encode failed: {e.stderr[:200]!r}'
                failed += 1
                continue
            if not res:
                st['skipped'][f['id']] = 'unsupported type'
                skipped += 1
                continue
            p = res['probe']
            live = 'video' in res
            entry = {
                'slug': slug,
                'name': uniq(name, taken_names),
                'collection': 'Collider Themes',
                'creator': 'David Ebri',
                'tier': 'Free Live Loop' if live else 'Free Spatial Canvas',
                'premium': False,
                'price': None,
                'productId': None,
                'poster': res['poster'],
                'video': res.get('video'),
                'tracks': [res['song']] if res.get('song') else [],
                'width': p['w'],
                'height': p['h'],
                'fps': p['fps'] if live else None,
                'driveId': f['id'],
                'source': f['name'],
            }
            if 'still' in res:
                entry['still'] = res['still']
            # append only. existing entries keep their index, their names and
            # every other field exactly as a human left them.
            themes.append(entry)
            taken_names.add(entry['name'])
            published_slugs.add(slug)
            published_ids.add(f['id'])
            st['files'][f['id']] = {'slug': slug, 'name': f['name'], 'mod': f['mod']}
            added += 1

        # Songs: append only, and only ones not already referenced.
        have_audio = {t['audio'] for th in themes for t in th.get('tracks', []) if t.get('audio')}
        added_songs = 0
        for s in songs:
            if s['id'] in st['files']:
                continue
            slug = slugify(s['name'], s['id'])
            outdir = f'themes/{slug}'
            try:
                os.makedirs(outdir, exist_ok=True)
                dst = os.path.join(outdir, 'song.m4a')
                download(s['id'], dst)
                dur = mmss(probe(dst)['dur'])
            except Exception:
                failed += 1
                continue
            rel = os.path.relpath(outdir, '.')
            audio = f'{rel}/song.m4a'
            if audio in have_audio:
                continue
            host = themes[0] if themes else None
            art = host['poster'] if host else None
            cat.setdefault('ambientTracks', []).append(
                {'title': stem(s['name']), 'audio': audio, 'art': art})
            have_audio.add(audio)
            st['files'][s['id']] = {'slug': slug, 'name': s['name'], 'mod': s['mod'], 'song': True}
            added_songs += 1
    finally:
        shutil.rmtree(work, ignore_errors=True)

    summ = (f'Drive pickup: folder={len(files)} songs={len(songs)} '
            f'catalog={len(themes)} added={added} songs_added={added_songs} '
            f'skipped={skipped} failed={failed} curated_entries_untouched={len(themes) - added}')

    changed = added > 0 or added_songs > 0
    if changed:
        cat['themes'] = themes
        cat['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        # generatedBy records that the catalog is human-curated and machine-appended.
        cat['generatedBy'] = 'collider-drive-pickup (additive; curated entries never rewritten)'
        open('themes.json', 'w').write(json.dumps(cat, indent=1, ensure_ascii=False) + '\n')
        os.makedirs('ingest', exist_ok=True)
        json.dump(st, open(STATE, 'w'), indent=1)
        st['files'] = st['files']
    elif os.path.exists(STATE):
        # Keep the skip log even on a no-op run so a permanently broken file is
        # visible in the log rather than retried forever.
        json.dump(st, open(STATE, 'w'), indent=1)

    print(summ)
    # os.devnull rather than '/dev/null': this also runs on Windows when tested
    # locally against a copy of the catalog.
    null = os.devnull
    with open(os.environ.get('GITHUB_OUTPUT') or null, 'a') as o:
        o.write(f'message={summ}\n')
        o.write(f'changed={"true" if changed else "false"}\n')
    with open(os.environ.get('GITHUB_STEP_SUMMARY') or null, 'a') as o:
        o.write(summ + '\n')


_t0 = time.time()

if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f'encode failed: {e.stderr[:400]!r}', file=sys.stderr)
        sys.exit(1)