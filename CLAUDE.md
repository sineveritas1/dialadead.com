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
| `songs.json`     | Song-title index: `{ "d": [dates...], "s": { "Althea": "1f,2a,..." } }` — values are base36 offsets into `d`. Powers **search by song**. Fetched lazily, only on the first archive search. |
| `build_shows.py`  | **Regenerates `shows.json`** from Archive.org. See below. Not part of the served site. |
| `build_songs.py` | **Regenerates `songs.json`.** One metadata request per show (~2,000), so it is rate-limited to 4 workers / 0.25s and takes ~10 minutes. Not part of the served site. |
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

## Searching by song — `songs.json` / `build_songs.py`

`shows.json` holds no track data, so song search needs a second index. Archive.org's
scrape API returns item-level fields only, so the tracklist of each show costs one
`metadata` request — ~2,000 of them. `build_songs.py` does that at the same polite
pacing as `audit_shows.py` (4 workers, 0.25s apart, backoff on 429/503) and takes
about ten minutes. **Don't raise the concurrency** — see the rate-limit note below.

```bash
python3 build_songs.py --limit 20   # spot-check
python3 build_songs.py              # full rebuild (~10 min)
```

It reuses `cleanName()` (ported to Python) so indexed titles match what the setlist
displays, splits segues (`Scarlet > Fire` indexes both), drops non-songs (tuning,
crowd, banter) and songs appearing only once — those are nearly all junk titles.
Dates are stored as base36 offsets into a shared date list, which keeps ~36k
song/show pairs down to ~158 KB for 660 songs.

The browser fetches it **only on the first search**, so it costs nothing on a normal
visit, and if the fetch fails, search silently falls back to venue/city/date.

## Regenerating `shows.json` — `build_shows.py`

`shows.json` is **generated, not hand-edited.** The original generator was lost;
`build_shows.py` replaces it.

```bash
python3 build_shows.py --report-only   # describe the collection, change nothing
python3 build_shows.py --dry-run       # show what would change
python3 build_shows.py                 # write shows.json
python3 build_shows.py --refresh       # force a fresh scrape (cache is 24h)
```

**How it pulls** matters. It does *not* query Archive.org date by date. It
scrapes the whole `GratefulDead` collection once (~18.3k recordings, ~19
cursor-paginated requests) into `.archive_cache.json` (gitignored, ~8 MB), then
decides everything locally. Consequences:

- Every recording of a night is compared, so "best" is a real ranking rather
  than whatever one search happened to return first.
- Venue/city can be **recovered from another recording of the same night**, which
  is what fixed most of the old `unknown` / `Various - See info file` entries.
- Re-running with different scoring costs **zero** requests — tune and re-run freely.

**Scoring** (`score()`): lineage dominates (`sbd` 3000, `mtx` 2900, `aud` 0),
then `log10(downloads) * 300`, then `avg_rating * 100`; partial recordings take
a 1500 penalty so a complete audience tape beats a half-missing soundboard.
Log-scaling downloads matters — counts span ~1e2–1e6, and a linear cap made the
legendary 1.45M-download Cornell soundboard tie with far lesser transfers.

**Two traps, both already handled — don't regress them:**

1. **Lineage must be read from the `identifier`, not the free-text `source`.**
   Some items say `Audience (was labeled as sbd)`; substring-matching that flips
   a genuine audience tape to soundboard.
2. **A placeholder date still carries a real-looking `date` field.** Archive.org
   stamps `gd1966-XX-XX` / `gd1985-02-00` items with a concrete date (often the
   1st), so trusting `date` alone pins compilations, interviews, radio spots and
   studio rehearsals onto real concert nights. `has_bogus_date()` reads the
   identifier's own date tokens and rejects `XX`/`00` month or day.

Rehearsals/interviews/outtakes are dropped via `NON_CONCERT`. Verify changes
with `--dry-run` before writing; the comparison block reports added/removed/
changed dates against the current file.

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

### "The site stopped loading shows" — CHECK ARCHIVE.ORG FIRST

**Do this before reading a single line of code:**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://archive.org/
```

`503` means Archive.org is **globally offline** and there is nothing to fix here.
They serve a "Internet Archive services are temporarily offline" page. It happens,
and it takes every Dead-streaming site down with it.

This matters because the app streams from Archive.org **directly in the visitor's
browser** — there is no backend proxying anything. Any Archive.org problem
surfaces as *this* site being broken, and **rolling the site back does not help**,
which reads exactly like a code regression you just shipped. On 2026-08-16 that
cost an afternoon: three releases and a production rollback chasing a phantom,
while Archive.org was simply down.

Distinguish the two external failure modes:

| check | meaning |
|---|---|
| `archive.org` returns 503 from anywhere | global outage — wait it out, fix nothing |
| works elsewhere, fails only on your connection | your IP is rate-limited — see below |
| works everywhere, fails for one date | genuinely a bad recording / a real bug |

Archive.org **cannot "ban the site"**: there is no server, account or API key of
ours for them to cut off. Requests come from each visitor's own IP. Per-IP rate
limiting is the only block that realistically applies, and it is temporary
(usually hours). Confirm it in ten seconds by loading the site over cellular
instead of wifi — a different IP that works proves it.

Running `audit_shows.py` or `build_shows.py --refresh` is how you earn one, since
they make thousands of requests. `audit_shows.py` now rate-limits itself (4
workers, 0.25s between requests, backoff on 429/503) and refuses `--fix` when
failures look like throttling — pruning a throttled run deletes good shows from
`shows.json`. Don't raise `--workers` to "speed it up"; use `--limit` to
spot-check instead.

### Other

- Cloudflare rewrites the served HTML on the fly (it obfuscates the `mailto:`
  email and injects an `email-decode` script). Do **not** copy the *served* HTML
  back into the repo verbatim — you'd bake in Cloudflare artifacts. Edit the
  source here.
- **Every branch gets a Cloudflare preview URL** (`https://<branch>.gratefuldead.pages.dev`),
  posted by the Pages bot on the PR. Test changes there on a real phone before
  merging to `main` — much better than shipping to production to find out.
- Archive.org occasionally rate-limits or times out; all fetches use
  `fetchWithTimeout` and degrade gracefully.
