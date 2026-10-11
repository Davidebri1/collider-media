# collider-media

Public media host for the Collider app (GitHub Pages).

- `themes.json` : theme catalog the app loads at runtime (bundled fallback copy ships in the app).
- `themes/<slug>/poster.webp` : poster at the source's full resolution (long side capped at 4K only).
- `themes/<slug>/loop.mp4` : live wallpaper, H.264 CRF 18 preset slow, +faststart, native resolution (up to 4K) and native frame rate (never resampled). Over 95 MB it is published as HLS instead: `themes/<slug>/hls/index.m3u8`.
- `themes/<slug>/still.webp` : full-resolution still (image themes).
- `themes/<slug>/song.m4a` : the video's embedded audio, when it has any (that theme's song).
- Every theme entry carries `width`, `height` and `fps` (ffprobe at ingest) plus its `driveId`.
- `tracks/*.mp3` : ambient tracks for the music drawer.

## Add, replace or remove a theme (no app rebuild, no bot)
Drag files into the Drive folder "Collider Themes" (one file = one theme, file name = theme name; shared songs go in `Songs/`).
The "Collider Drive sync" Action (`.github/workflows/drive-sync.yml`) runs every 20 minutes on GitHub's schedule, and on demand from the Actions tab.
It mirrors the folder exactly: new files are added, changed files re-ingested, deleted files removed. Large batches continue on the next run.
