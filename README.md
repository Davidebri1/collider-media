# collider-media

Public media host for the Collider app (GitHub Pages).

- `themes.json` : theme catalog the app loads at runtime (bundled fallback copy ships in the app).
- `themes/<slug>/poster.webp` : poster, about 720px wide.
- `themes/<slug>/loop.mp4` : live wallpaper loop, H.264 720p, faststart, muted (premium packs).
- `themes/<slug>/still.webp` : 1080px still for full-bleed use (free themes).
- `tracks/*.mp3` : ambient tracks for the music drawer.

## Add a theme (no app rebuild)
1. Transcode: poster `ffmpeg -i src.jpg -vf scale=720:-2 -c:v libwebp -q:v 75 poster.webp`;
   loop `ffmpeg -i src.mp4 -an -vf scale=720:-2,format=yuv420p -c:v libx264 -preset slow -crf 26 -movflags +faststart loop.mp4` (keep under 2.5 MB).
2. Put both under `themes/<slug>/`.
3. Add an entry to `themes.json` (slug, name, collection, price, productId, poster, video, tracks). Paths are relative to `baseUrl`.
4. Commit and push. Pages serves it within a few minutes; the app picks it up on next launch.
