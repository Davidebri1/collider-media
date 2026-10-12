#!/usr/bin/env python3
"""Collider themes: mirror David's link-shared Drive folder 'Collider Themes' into themes.json.

One file = one theme, file name (without extension) = theme name. Songs/ subfolder = shared songs.
No quality caps: native resolution (up to 4K long side) and native frame rate (never resampled),
H.264 CRF 18 preset slow +faststart; HLS (fMP4) when an MP4 would exceed GitHub's 100 MB file limit.
width/height/fps detected with ffprobe. Incremental: ingest/state.json remembers processed Drive ids.
Keyless: reads Drive's public embedded folder view and public download links.
"""
import html, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request, hashlib
FOLDER = os.environ.get('DRIVE_FOLDER', '1DNqeA7tY2XY8Gfs2x0zho1LFj2q7LgY2')
BUDGET = float(os.environ.get('BUDGET_MIN', '50')) * 60
T0 = time.time()
VID = {'mp4','mov','m4v','webm','mkv','avi','gif'}
IMG = {'jpg','jpeg','png','webp','heic','bmp','tif','tiff'}
AUD = {'mp3','m4a','aac','wav','flac','ogg','opus'}
MAXMP4 = 95 * 1024 * 1024

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')

def listing(fid):
    h = get(f'https://drive.google.com/embeddedfolderview?id={fid}')
    out = []
    for m in re.finditer(r'class="flip-entry" id="entry-([\w-]+)".*?<a href="([^"]*)".*?flip-entry-title">([^<]*)</div>.*?flip-entry-last-modified"><div>([^<]*)<', h, re.S):
        fid, href, title, mod = m.group(1), html.unescape(m.group(2)), html.unescape(m.group(3)), m.group(4)
        out.append({'id': fid, 'name': title, 'mod': mod, 'folder': '/folders/' in href})
    return out

def sh(*a): subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
def ext(n): return n.rsplit('.', 1)[-1].lower() if '.' in n else ''
def stem(n): return n.rsplit('.', 1)[0] if '.' in n else n
def slugify(n, fid):
    s = re.sub(r'[^a-z0-9]+', '-', n.lower()).strip('-')[:48] or 'theme'
    return f'{s}-{fid[-6:].lower().replace("_","x")}'

def download(fid, dst):
    sh('curl', '-fsSL', '--retry', '3', '-o', dst,
       f'https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t')

def probe(p):
    j = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', p]))
    v = next((s for s in j['streams'] if s['codec_type'] == 'video'), None)
    a = any(s['codec_type'] == 'audio' for s in j['streams'])
    fps = None
    if v:
        for k in ('avg_frame_rate', 'r_frame_rate'):
            n, _, d = (v.get(k) or '0/0').partition('/')
            if d and float(d) and float(n): fps = round(float(n) / float(d), 3); break
        rot = 0
        for sd in v.get('side_data_list', []) or []:
            rot = int(sd.get('rotation', 0) or 0)
        w, hgt = int(v['width']), int(v['height'])
        if abs(rot) in (90, 270): w, hgt = hgt, w
    else: w = hgt = None
    return {'w': w, 'h': hgt, 'fps': fps, 'audio': a, 'dur': float(j['format'].get('duration') or 0)}

def cap4k():  # keep native, only cap the long side at 3840 (David: "up to 4K"); never touches fps
    return "scale='if(gte(iw,ih),min(3840,iw),-2)':'if(gte(iw,ih),-2,min(3840,ih))':flags=lanczos,format=yuv420p"

def mmss(s): s = int(round(s)); return f'{s//60}:{s%60:02d}'

def process(f, work, outdir):
    src = os.path.join(work, 'src.' + (ext(f['name']) or 'bin'))
    download(f['id'], src)
    p = probe(src)
    shutil.rmtree(outdir, ignore_errors=True); os.makedirs(outdir)
    rel = os.path.relpath(outdir, '.')
    e = ext(f['name']); res = {'probe': p}
    if e in VID and not (e == 'gif' and p['dur'] == 0):
        sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-frames:v', '1', '-vf', cap4k().replace(',format=yuv420p', ''),
           '-c:v', 'libwebp', '-q:v', '92', os.path.join(outdir, 'poster.webp'))
        enc = ['-an', '-vf', cap4k(), '-fps_mode', 'passthrough', '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
               '-profile:v', 'high']
        mp4 = os.path.join(outdir, 'loop.mp4')
        sh('ffmpeg', '-v', 'error', '-y', '-i', src, *enc, '-movflags', '+faststart', mp4)
        if os.path.getsize(mp4) > MAXMP4:
            os.remove(mp4); hd = os.path.join(outdir, 'hls'); os.makedirs(hd)
            sh('ffmpeg', '-v', 'error', '-y', '-i', src, *enc, '-f', 'hls', '-hls_time', '4', '-hls_playlist_type', 'vod',
               '-hls_segment_type', 'fmp4', '-hls_segment_filename', os.path.join(hd, 'seg%04d.m4s'), os.path.join(hd, 'index.m3u8'))
            res['video'] = f'{rel}/hls/index.m3u8'
        else: res['video'] = f'{rel}/loop.mp4'
        if p['audio']:
            sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-vn', '-c:a', 'aac', '-b:a', '256k', os.path.join(outdir, 'song.m4a'))
            res['song'] = {'number': 1, 'title': stem(f['name']), 'duration': mmss(p['dur']), 'mood': '', 'audio': f'{rel}/song.m4a'}
        res['poster'] = f'{rel}/poster.webp'
    elif e in IMG or e == 'gif':
        sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-frames:v', '1', '-vf', cap4k().replace(',format=yuv420p', ''),
           '-c:v', 'libwebp', '-q:v', '95', os.path.join(outdir, 'still.webp'))
        res['still'] = res['poster'] = f'{rel}/still.webp'
    else: return None
    return res

def main():
    cat = json.load(open('themes.json'))
    st = json.load(open('ingest/state.json')) if os.path.exists('ingest/state.json') else {'files': {}, 'songs': {}}
    # Curated names, maintained by build_names.py. The Drive filename is a
    # machine slug, so without this every hand-written name reverts on each run.
    nm = json.load(open('ingest/names.json')) if os.path.exists('ingest/names.json') else {}
    curated = nm.get('names', {}) if isinstance(nm, dict) else {}
    skip = set(nm.get('exclude', []) if isinstance(nm, dict) else [])
    items = listing(FOLDER)
    files = [i for i in items if not i['folder'] and (ext(i['name']) in VID | IMG)]
    # Retired themes stay retired even though the file is still on Drive.
    files = [i for i in files if slugify(stem(i['name']), i['id']) not in skip]
    songs_dir = next((i for i in items if i['folder'] and i['name'].lower() == 'songs'), None)
    songs = [s for s in listing(songs_dir['id']) if not s['folder'] and ext(s['name']) in AUD] if songs_dir else []
    seen = {f['id'] for f in files}; done = pending = failed = 0
    for fid in list(st['files']):
        if fid not in seen:
            shutil.rmtree(f"themes/{st['files'][fid]['slug']}", ignore_errors=True); del st['files'][fid]
    work = tempfile.mkdtemp()
    for f in files:
        old = st['files'].get(f['id'])
        if old and old['mod'] == f['mod'] and old['name'] == f['name'] and old.get('res'): continue
        if time.time() - T0 > BUDGET: pending += 1; continue
        slug = old['slug'] if old else slugify(stem(f['name']), f['id'])
        try:
            r = process(f, work, f'themes/{slug}')
            if r: st['files'][f['id']] = {'name': f['name'], 'mod': f['mod'], 'slug': slug, 'res': r}; done += 1
        except Exception as ex:
            failed += 1; print('FAIL', f['name'], getattr(ex, 'stderr', b'')[-400:] if hasattr(ex, 'stderr') else ex, file=sys.stderr)
        for x in os.listdir(work): os.remove(os.path.join(work, x))
    # shared songs
    sseen = {s['id'] for s in songs}
    for sid in list(st['songs']):
        if sid not in sseen:
            try: os.remove(st['songs'][sid]['audio'])
            except FileNotFoundError: pass
            del st['songs'][sid]
    os.makedirs('tracks/songs', exist_ok=True)
    for s in songs:
        o = st['songs'].get(s['id'])
        if o and o['mod'] == s['mod'] and o['name'] == s['name']: continue
        src = os.path.join(work, 'song.' + ext(s['name'])); download(s['id'], src)
        dst = f"tracks/songs/{slugify(stem(s['name']), s['id'])}.{'mp3' if ext(s['name'])=='mp3' else 'm4a'}"
        if dst.endswith('.mp3'): shutil.copy(src, dst)
        else: sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-vn', '-c:a', 'aac', '-b:a', '256k', dst)
        st['songs'][s['id']] = {'name': s['name'], 'mod': s['mod'], 'audio': dst, 'dur': mmss(probe(dst)['dur'])}
    shared = [{'number': n + 1, 'title': stem(v['name']), 'duration': v['dur'], 'mood': '', 'audio': v['audio']}
              for n, v in enumerate(sorted(st['songs'].values(), key=lambda v: v['name'].lower()))]
    themes = []
    for f in files:  # folder order
        e = st['files'].get(f['id'])
        if not e or not e.get('res'): continue
        r, p = e['res'], e['res']['probe']; live = 'video' in r
        w, h = p['w'], p['h']
        if w and max(w, h) > 3840: k = 3840 / max(w, h); w, h = round(w * k / 2) * 2, round(h * k / 2) * 2
        themes.append({'slug': e['slug'], 'name': curated.get(e['slug']) or stem(e['name']), 'collection': 'Collider Themes', 'creator': 'David Ebri',
            'tier': 'Free Live Loop' if live else 'Free Spatial Canvas', 'premium': False, 'price': None, 'productId': None,
            'poster': r['poster'], 'video': r.get('video'), **({'still': r['still']} if 'still' in r else {}),
            'tracks': [r['song']] if r.get('song') else shared,
            'width': w, 'height': h, 'fps': p['fps'] if live else None, 'driveId': f['id'], 'source': e['name']})
    keep = {t['slug'] for t in themes}
    for d in os.listdir('themes'):
        if d not in keep and d not in {v['slug'] for v in st['files'].values()}: shutil.rmtree(f'themes/{d}')
    cat['themes'] = themes
    if shared: cat['ambientTracks'] = [{'title': t['title'], 'audio': t['audio'], 'art': themes[0]['poster'] if themes else None} for t in shared]
    else: cat['ambientTracks'] = [a for a in cat.get('ambientTracks', []) if os.path.exists(a['audio'])]
    for a in cat['ambientTracks']:
        if a.get('art') and not os.path.exists(a['art']) and themes: a['art'] = themes[0]['poster']
    if isinstance(nm, dict) and nm.get('defaultSlug') in keep: cat['defaultSlug'] = nm['defaultSlug']
    if cat.get('defaultSlug') not in keep and themes: cat['defaultSlug'] = themes[0]['slug']
    cat['generatedBy'] = 'collider-drive-sync'
    new = json.dumps(cat, indent=1, ensure_ascii=False)
    oldcat = open('themes.json').read()
    if new != oldcat or done or failed:
        cat['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()); new = json.dumps(cat, indent=1, ensure_ascii=False)
    open('themes.json', 'w').write(new + '\n')
    os.makedirs('ingest', exist_ok=True); json.dump(st, open('ingest/state.json', 'w'), indent=1)
    summ = f'folder files={len(files)} songs={len(songs)} catalog themes={len(themes)} processed={done} pending={pending} failed={failed}'
    print(summ)
    with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as o:
        o.write(f'message=Collider Drive sync: {summ}\n')
    with open(os.environ.get('GITHUB_STEP_SUMMARY', '/dev/null'), 'a') as o: o.write(summ + '\n')

if __name__ == '__main__': main()
