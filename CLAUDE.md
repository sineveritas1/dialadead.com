# CLAUDE.md — DIAL·A·DEAD

Guidance for Claude (and humans) working on this repo. Read this first.

## What this is

**DIAL·A·DEAD** (https://dialadead.com) is a single-page web app: a neon
"time machine" for Deadheads. Type a date from 1965–1995, hit ENGAGE, and the
Grateful Dead show from that night streams straight from the
[Archive.org](https://archive.org/details/GratefulDead) live-music collection.
No accounts, no ads, no backend.

There is **no build step and no framework**. The whole app is hand-written
HTML + CSS + vanilla JS. Ship-ready files are served exactly as they sit in the
repo root.

## Files

| File             | Purpose |
|------------------|---------|
| `index.html`     | The entire app — HTML, CSS, and JS are all inline. This is where ~all work happens. |
| `shows.json`     | Index of ~2,075 shows: `{ "YYYY-MM-DD": { id, venue, city, type } }`. One **recommended** recording per date, used for the browsable archive, RANDOM, and the fast path on ENGAGE. |
| `manifest.json`  | PWA manifest (installable app, theme color, icon). |
| `robots.txt` / `sitemap.xml` | SEO. Both point at `https://dialadead.com/`. |
| `_redirects`     | Cloudflare Pages redirect rules (currently maps `/favicon.ico` to the Cloudinary logo). |
| `audit_shows.py` | Maintenance script: checks every `shows.json` entry against Archive.org for dead links / missing MP3s. `python3 audit_shows.py` to report, `--fix` to prune bad shows. Not part of the served site. |
| `Skull.png`      | Fallback icon / social image (the live logo is served from Cloudinary). |
| `README.md`      | Public-facing blurb. |

## Architecture / how it works

- **ENGAGE** builds a date key `YYYY-MM-DD`. If it's in `shows.json`, it loads
  that recording's Archive.org metadata directly; otherwise it does a live
  Archive.org search for that date and picks the best (soundboard-preferred)
  result.
- **Track list** comes from the recording's `metadata` files list: MP3s only,
  de-duplicated by disc/track, low-bitrate variants filtered out.
- **All recordings per date** (the RECORDING dropdown) are fetched *live* from
  Archive.org (`advancedsearch.php … date:<key>`) when a show loads —
  soundboards/matrixes first, then by download count. This is intentional:
  `shows.json` stays small and never goes stale, and every source Archive.org
  has for a night is always selectable. `switchSource()` reloads the chosen
  recording in place.
- **Track names** are cleaned by `cleanName()` (strips `gdYY-MM-DD…`, disc/track
  codes, encoding tags) and then normalized against `SONG_CANON`, a map of
  canonical Grateful Dead song titles, so `fireonthemountain` → `Fire on the
  Mountain`.
- **Playback + background/lockscreen** uses the **Media Session API**
  (`updateMediaSession()` / `setupMediaSession()`): it sets per-track metadata
  (this is what shows the *song title* — not a generic app name — in the
  Android/iOS notification and lockscreen) and registers play/pause/next/prev/
  seek handlers. It's also the fix for playback stalling after a track or two
  when the screen is off: an active media session keeps audio focus, and
  `playTrack()` no longer blanks `audio.src` between tracks.
- **Extras**: favorites (localStorage, max 6), prev/next-show nav, whole-show
  ZIP download (JSZip, lazy-loaded), single-track download, and a black-and-white
  "PURIST" theme toggle.

## Conventions — keep it this way

- **One self-contained `index.html`.** No bundler, no npm deps, no external JS
  except CDN libraries loaded on demand (JSZip). Fonts + logo are the only other
  external assets. Don't introduce a build pipeline.
- Terse, existing-style JS (short names, packed lines). Match what's there.
- `escHtml()` any Archive.org / user-derived string before putting it in the DOM.
- Two themes: neon (default) and `html.purist`. If you add UI, style **both**.

## Testing from a web session (no local dev machine needed)

Syntax-check the inline JS and smoke-test init in the pre-installed Chromium:

```bash
# 1) syntax check the inline <script>
python3 - <<'PY'
import re; h=open('index.html').read()
open('/tmp/app.js','w').write(re.search(r'<script>\nconst MONTHS=.*?</script>',h,re.S).group(0)[8:-9])
PY
node --check /tmp/app.js

# 2) load the page in real Chromium and confirm the archive renders
python3 -m http.server 8199 & SRV=$!; sleep 1
CHROME=$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1)
"$CHROME" --headless=new --no-sandbox --disable-gpu --virtual-time-budget=6000 \
  --dump-dom http://localhost:8199/index.html | grep -oE '[0-9]+ SHOWS'
kill $SRV
```

Expect `2075 SHOWS` (or whatever `shows.json` currently holds).

## Deployment — IMPORTANT

The live site is on **Cloudflare Pages** (project `gratefuldead`, custom domain
`dialadead.com`). It's a static site: **no build command**, output directory is
the repo root.

### Branches — read this before you base any work

**`main` is the source of truth.** Its `index.html` matches what's live byte for
byte. Work from `main`, merge to `main`.

The repo also carries some stale branches from earlier sessions —
`claude/setup-cloudflare-pages-BVuFq` (which was for a long time the repo's
*default* branch despite being far behind `main`), `preview`, and assorted
`claude/*` branches. **Do not base work on them.** If you branch from the wrong
one you'll silently revert SEO tags, the PWA manifest, show-nav, downloads and
more. Always `git fetch origin main` and branch from that; if the GitHub default
branch is anything other than `main`, fix the default rather than following it.

### The golden rule

**This repo is the source of truth. Never hand-edit the live site**, and never
deploy by direct `wrangler pages deploy` upload from a laptop — that's how the
repo/production relationship gets murky in the first place. All changes go
through `index.html` here, then deploy.

### Preferred setup: connect Pages to GitHub (no wrangler, no CLI)

Do this once in the Cloudflare dashboard so every push auto-deploys:

1. Cloudflare Dashboard → **Workers & Pages** → `gratefuldead` → **Settings** →
   **Builds & deployments** → **Connect to Git** (or create a new Pages project
   from this repo if the existing one is upload-only).
2. Repository: `sineveritas1/dialadead.com`.
3. **Production branch:** `main`.
4. **Framework preset:** None. **Build command:** *(leave blank)*.
   **Build output directory:** `/`.
5. Save. From then on, merging to `main` deploys automatically — no local
   machine required.

### Alternative: GitHub Actions → Pages

If you'd rather deploy from CI, add a workflow using `cloudflare/wrangler-action`
with `pages deploy`. That needs two repo secrets — `CLOUDFLARE_API_TOKEN`
(Pages:Edit) and `CLOUDFLARE_ACCOUNT_ID`. The dashboard git integration above is
simpler and needs no secrets, so prefer it unless you specifically want CI.

## Notes / gotchas

- Cloudflare rewrites the served HTML on the fly (it obfuscates the `mailto:`
  email and injects an `email-decode` script). Do **not** copy the *served* HTML
  back into the repo verbatim — you'd bake in Cloudflare artifacts. Edit the
  source here.
- Archive.org occasionally rate-limits or times out; all fetches use
  `fetchWithTimeout` and degrade gracefully.
