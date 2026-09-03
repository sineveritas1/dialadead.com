# Porting these improvements to another Archive.org concert-streaming site

This describes every substantive change made to a single-page, no-backend web app
that streams a band's live shows directly from the Internet Archive. It is written
to be **band-agnostic** so it can be applied to a sibling site for a different
band. Nothing here assumes a build step, a framework, or a server.

Read **section 0 first.** It is the most valuable thing in this document and it
cost an afternoon to learn.

Throughout: `<COLLECTION>` is the Archive.org collection identifier (e.g. the
value used in `collection:(...)` queries), `<PREFIX>` is the filename prefix
tapers use for that band, and `<FIRST_YEAR>`/`<LAST_YEAR>` are its touring years.

---

## 0. The trap: an Archive.org outage looks exactly like your bug

**This is the single most important item.** An afternoon went into chasing a
"regression" that did not exist.

These sites stream **directly from the visitor's browser to Archive.org**. There
is no backend proxying anything. So *any* Archive.org problem surfaces as **your
site being broken**, and — critically — **rolling your site back does not help.**
That combination reads exactly like a bad release you just shipped.

**Before reading a single line of code when shows stop loading:**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://archive.org/
```

Three external failure modes, which need different responses:

| symptom | meaning | what to do |
|---|---|---|
| `503` from anywhere, incl. their homepage | global outage | wait; fix nothing |
| connections refused / no status at all | worse outage | wait; fix nothing |
| works elsewhere, fails only on your connection | your IP is rate-limited | wait hours; stop hammering |
| works everywhere, fails for one date | genuinely a bad recording, or your bug | now debug |

**They cannot "ban your site."** There is no server, account, or API key of yours
to cut off — every request comes from a visitor's own browser and IP. And a ban
would not take down Archive.org's own homepage.

**Confirm a per-IP limit in ten seconds:** load the site over cellular instead of
wifi. A different IP that works proves it.

Put this at the top of your `CLAUDE.md` / contributor docs. Also see §7, which
makes the app *say* which of these is happening instead of blaming the recording.

### The corollary about verification

Several fixes were "verified" against *replayed* Archive.org responses in a
headless browser, then announced as working, while the live path was never
actually exercised. That over-claiming is what let the confusion run for hours.

Two habits that fixed it:

- **Use per-branch preview deploys.** On Cloudflare Pages every branch gets a URL
  (`https://<branch>.<project>.pages.dev`) automatically. Test on a real phone
  there *before* merging to production. This is free and it removes almost all of
  the risk.
- **Say precisely what you tested.** "Verified against recorded API responses" and
  "verified against the live API" are very different claims.

---

## 1. Data layer: generate your show index from one bulk scrape

**The problem.** A per-date index (`shows.json`: `{"YYYY-MM-DD": {id, venue, city,
type}}`) is what makes the browsable archive, RANDOM, and the fast path on submit
possible. If it is built by querying Archive.org date-by-date, you get whatever
one search happened to return first, plus a pile of `unknown` venues.

**The approach that works** — a generator script (`build_shows.py`):

1. Scrape the **whole collection once** via the scrape API
   (`https://archive.org/services/search/v1/scrape`, cursor-paginated, ~1000 rows
   per request). For a ~18k-recording collection this is about 19 requests.
2. Cache the raw scrape to disk (gitignored). **Re-running with different scoring
   then costs zero requests**, so you can tune freely.
3. Group by date, score every recording of each night, keep the best.

**Scoring** (tune per band — see the warning below):

```
lineage:     soundboard 3000 | matrix 2900 | audience 0
popularity:  log10(downloads) * 300
rating:      avg_rating * 100
penalty:     partial/incomplete recording  -1500
```

Log-scaling downloads matters: counts span ~1e2–1e6, and a linear cap made a
famous 1.45M-download soundboard tie with far lesser transfers. The partial
penalty means a complete audience tape beats a half-missing soundboard.

**Venue/city recovery.** If the winning recording has no venue, take the most
common non-junk value from *any other recording of the same night*. This alone
fixed most `unknown` / `Various - See info file` entries.

### Two traps that will bite you

1. **Read lineage from the `identifier`, not the free-text `source` field.** Some
   items literally say `Audience (was labeled as sbd)`. Substring-matching that
   flips a genuine audience tape to soundboard.
2. **A placeholder date still carries a real-looking `date` field.** Archive.org
   stamps items like `<PREFIX>1966-XX-XX` or `<PREFIX>1985-02-00` with a concrete
   date (often the 1st). Trusting `date` alone pins compilations, interviews,
   radio spots and studio rehearsals onto real concert nights. Parse the
   identifier's own date tokens and reject `XX` / `00` month or day.

Also filter non-concerts by identifier/title: interview, radio spot, promo,
rehearsal, soundcheck, studio session, outtake, documentary, press conference.

### Band-specific warnings

- **Adjust the lineage weights to your collection.** The tiers above assume
  soundboards are actually present. For a band whose soundboards are sold
  commercially rather than hosted on Archive.org, the collection may be almost
  entirely audience recordings — in which case lineage barely discriminates and
  you should lean much harder on rating and downloads. **Check the real
  distribution before trusting the weights** (`--report-only` style flag).
- Set `<FIRST_YEAR>`/`<LAST_YEAR>` to the band's touring years so out-of-range
  dates are rejected.

Give the generator `--report-only`, `--dry-run` and `--refresh` flags, and have
`--dry-run` print added/removed/changed dates against the current file.

---

## 2. Search by song (the one people ask for)

**Why it is hard.** Your show index holds no track data, and Archive.org's bulk
scrape API returns **item-level fields only**. The tracklist of a show is a
separate `metadata` request — one per show, so ~2,000 of them.

**The approach** — a second generator (`build_songs.py`) producing `songs.json`:

- Fetch each show's metadata at **deliberately polite pacing** (4 workers, 0.25s
  between request starts, exponential backoff on 429/503). ~2,000 shows takes
  about ten minutes. **Do not speed this up** — see §0 and §8.
- Extract MP3 track titles and clean them with the *same* cleaner the UI uses
  (§3), so indexed titles match what the setlist displays.
- **Split segues**: a title like `Song A > Song B` should index both.
- Drop non-songs (tuning, crowd, banter, intro, applause, untitled) and titles
  appearing only once — those are almost all junk.

**Keep the file small,** because browsers download it. Store a shared date list
and reference dates by **base36 offsets** into it:

```json
{"d": ["1965-11-03", "..."],
 "s": {"Some Song": "1f,2a,3b"}}
```

That compressed ~36k song/show pairs into **158 KB for 660 songs across 2,036
shows**. A naive `song -> [full date strings]` map is roughly 3x larger.

**Load it lazily** — fetch only on the first search, not at startup. Most visits
never search, so an ordinary visit pays nothing. If the fetch fails, degrade
silently to the existing venue/city/date filter.

**Show why a result matched.** When a show is in the list because of a song, put
that song on the card (in an existing line, not a new one, so cards keep their
height).

---

## 3. Track-name cleaning

Raw Archive.org filenames are hostile: `<PREFIX>82-08-08d1t01`,
`<PREFIX>1982-08-08.sbd.miller.31175.sbeok.d1t01`, `<PREFIX>84-04-30 02 SongName`,
run-together `SongNameLikeThis`, trailing `.sbeok.shnf.shntool.md5` chains.

A `cleanName()` that strips, in order: audio extension → bitrate suffixes →
trailing encoding-tag chains → the full `<PREFIX>date` + disc/track prefix →
bare-track-number variants → the band's full-name prefix → leftover `d1t02`/`t04`
codes → standalone leading track numbers → inline technical tags → long numeric
archive IDs. Then normalise `->` to `>`, convert `._-` to spaces, collapse
whitespace, trim stray punctuation.

Two refinements that matter:

- **Split run-together CamelCase only when there are no spaces already**, so
  `SongNameLikeThis` splits but `Song Name` is untouched.
- **Normalise against a canonical title map**, keyed on a lowercase
  alphanumerics-only version of the name, so `fireonthemountain` and
  `Fire On The Mountain` collapse to one canonical spelling. Include common taper
  abbreviations as extra keys.

**Band-specific:** the `<PREFIX>` regexes and the canonical song list are entirely
band-specific and must be rewritten. Everything else is generic.

**Test it against reality**: pull a few hundred real track titles across many
shows and eyeball the output before and after. A regex that looks right will
happily blank out song names in cases you did not think of.

---

## 4. Playback resilience (this is where the real bugs were)

### 4a. A dropped connection must not cost a track

**The bug.** The error handler only retried a stream that had already played past
`0:01`; anything else was treated as "this file is unplayable" and it advanced.
But mobile connections refuse *every* request for a few seconds at a time — tower
handoff, wifi/LTE switch, a 503 burst. Each refusal ate another track, so the
setlist walked itself several songs deep until the network came back.

Reproduced in a headless browser by refusing the audio host for 6 seconds:
**playback landed on track 9**, burning eight songs.

**The fix.** How far a track got decides nothing — dying at `0:00` is the *common*
dropout, not evidence of a bad file:

- every error **retries the same track** (3 tries, backing off ~0.8/1.6/2.4s) and
  only advances once that track has genuinely refused;
- a run of dead tracks stops after two with a "lost the signal" message instead of
  racing to the end of the show;
- the retry budget is earned back after ~30s of clean playback, the skip counter
  after ~10s, and a deliberate tap always gets a fresh chance.

After: the same 6s outage holds track 1 when the outage fits inside the retry
budget, and costs exactly one skip when it does not.

**Space the retries out.** Re-requesting hard is how a client gets rate-limited,
and a limited IP fails *everything* — including your metadata calls. That is how a
playback problem becomes "nothing loads at all."

### 4b. Two stale events that cause phantom double-skips

Both are easy to miss and both advance a track you did not mean to advance:

- Ignore `error` when `audio.error` is null (a stale event for a source you
  already replaced) **and** when `audio.error.code === 1` (`MEDIA_ERR_ABORTED`,
  i.e. your own `src` swap).
- Ignore `ended` when `readyState === 0` — nothing is loaded, so it cannot
  legitimately have just ended.

### 4c. Do not blank `audio.src` between tracks

Setting `src=''` briefly drops the media session and is the classic cause of
playback stalling after a track or two when backgrounded. Assigning a new `src`
already aborts the previous load.

### 4d. Make PLAY recover from an error state

An audio element sitting on an error has nothing loaded, so calling `play()` does
**literally nothing** and the button looks broken — the only way out is a page
reload. If you show a "hit play to resume" message, make PLAY actually reload the
track and resume from the last known position (track it in `timeupdate`).

*(This one was self-inflicted: the "lost the signal" stop in 4a was shipped
without checking that its own advice worked.)*

---

## 5. Background playback and lockscreen controls (Media Session API)

Set per-track metadata and register handlers:

- `navigator.mediaSession.metadata` per track — **this is what shows the song
  title** in the Android/iOS notification and lockscreen instead of a generic app
  name.
- Handlers for `play`, `pause`, `previoustrack`, `nexttrack`, `seekbackward`,
  `seekforward`, plus `playbackState` and position state.

An active media session also **keeps audio focus**, which (with 4c) is the fix for
playback dying when the screen is off.

### The subtle one: do not scroll the page while it is hidden

Tapping next/prev in the phone's notification shade fires your handlers. If that
code scrolls the tracklist, Android surfaces the browser and snaps the shade shut
— it reads as "the button bounced me out of the panel."

Guard it: if `document.visibilityState !== 'visible'`, set a flag and defer the
scroll to the next `visibilitychange`.

---

## 6. Let listeners pick the recording, and link to what they heard

**Recording picker.** Fetch *every* recording for the loaded date live
(`advancedsearch.php ... date:<key>`), soundboards/matrixes first then by download
count, and offer them in a dropdown that reloads in place. Doing this live rather
than baking it into your index keeps the index small and never stale, and every
source Archive.org has for a night stays selectable.

**Share a song, not just a show.** A per-track share button belongs in the
existing row (next to the download button) so rows keep their height.

**Put the recording in the link.** A track number only means something *against
the recording it was counted in*, and the listener may have switched recordings.
Share `?date=...&track=N&src=<identifier>` and have the loader honour all three.
**Clamp the track index** so a link into a recording that is now shorter starts at
the top rather than failing.

---

## 7. Tell the truth about failures

During an outage the app said **"COULDN'T LOAD THIS RECORDING"** — blaming the
show — and then spent its whole retry and fallback budget re-asking a dead server.
Another path said **"check your connection"**, blaming the listener's phone. Both
wrong, and both sent everyone hunting in the wrong place (§0).

Carry the HTTP status on thrown fetch errors and distinguish three cases:

| condition | message |
|---|---|
| `503` | **ARCHIVE.ORG IS OFFLINE** — down right now, *not this site*. Stop after one request; retrying cannot work. |
| no status at all (refused/timeout) | **CAN'T REACH ARCHIVE.ORG** — may be down, or your connection. |
| a real answer about the item (404 etc.) | **COULDN'T LOAD THIS RECORDING** — try another source. |

**Retry and fall back before showing any error.** A single flaky request used to
dead-end an entire night. Retry the metadata fetch (3x with backoff), then load a
**different recording of the same date** — most dates have several, so a night is
almost never genuinely unavailable.

---

## 8. Maintenance scripts must be polite

An audit script fired **20 concurrent requests with no delay** across ~2,000
shows. That is how you earn a per-IP rate limit — which then breaks the live site
for whoever is on that connection (§0).

Every script that touches Archive.org in bulk should:

- run ~4 workers with a **global** minimum interval (~0.25s) between request
  starts;
- identify itself in the User-Agent with a contact address;
- back off and retry on 429/503 rather than recording a dead link;
- expose `--workers` / `--interval` / `--limit`, and print the expected runtime.

**Critically — refuse `--fix` when the failures look like throttling.** Pruning on
a throttled run silently deletes good shows from your index, and you will not
notice until much later.

---

## 9. Mobile UI fixes (all measured, all cheap)

### 9a. A CSS grid that overflowed by 382px

Show cards in a `grid-template-columns:1fr 1fr` were **395px and 292px wide inside
a 314px container** — massive horizontal scroll, cards cut off, and unequal.

Grid items default to `min-width:auto`, so a long venue name sets the column's
minimum and the `1fr` columns are never `1fr`. The ellipsis those cards already
had could never engage.

```css
.card { min-width: 0; overflow: hidden; }
.card > * { min-width: 0; }
```

Result: 0px overflow at 320/390/430px, both columns identical.

### 9b. Filter buttons: use a grid, not wrapped fixed widths

Fixed-width year buttons wrapped to 5 per row on a 320px phone (7 rows) while
wasting ~30px per row at 390px. `grid-template-columns: repeat(6, 1fr)` fills
whatever width exists: buttons get **bigger** and small phones lose a row.

### 9c. Growing small text without lengthening the page

Move the smallest labels to `clamp(current, Nvw, max)` — unchanged on the
narrowest screens, growing from there, so nothing reflows where space is
tightest. Text inside fixed-height scrollers can grow freely without affecting
page length.

### 9d. Two arrow bugs worth knowing

- `←` and `→` may come from **different fallback fonts** if your display font
  contains neither, giving them different glyph heights — one arrow visibly sits
  higher. Use **one glyph for both** and mirror it.
- Mirror with `transform: scaleX(-1)`, **not** `rotate(180deg)`. A rotation flips
  vertically too, so the glyph lands at its mirrored height inside the line box
  and the offset comes straight back.

**Verify this with pixels, not bounding boxes.** The two boxes were identical the
whole time; only the *ink inside them* differed. Render at 3–4x and compare the
painted rows.

### 9e. `:hover` sticks after a tap on touch devices

A tapped card or row keeps its highlight until you touch something else, and reads
as a stray coloured mark rather than feedback. Wrap tap-target hover rules:

```css
@media (hover: hover) { .card:hover { /* ... */ } }
```

Verify by emulating a touch device (`hover: none`) and checking the computed
border/background does not change when a pointer lands on it.

### 9f. Scroll the container, not the page

To keep the active track visible, scroll the **list element**, not
`scrollIntoView()` — the latter walks up ancestors and can move the document. And
compute the offset with `getBoundingClientRect()` deltas, **not** `offsetTop`:
`offsetTop` is relative to the nearest *positioned* ancestor, so if your scroller
is not positioned you silently include everything above it. That bug scrolled the
list ~205px past the playing track.

---

## 10. Smaller wins worth copying

- **A "TODAY" button** that dials the visitor's **local** calendar date (not UTC).
- **Wildcard dates**: a blank field means "any", so `8 / 16 / (blank)` plays a show
  from that day in any year. Validate only the filled fields, but still reject
  impossible dates (Feb 30) rather than reporting "no concert that night".
- **RANDOM that dials without auto-playing**, leaving the user to press the main
  button, with the button pulsing to show it is armed.
- **Per-show SEO**: every show lives at `?date=YYYY-MM-DD`. Without per-show
  `<title>`, description and canonical, search engines see ~2,000 duplicates of
  the homepage and index none of them. Update them as the show loads.
- **A real `404.html`** so unknown paths return an actual 404 rather than a soft
  200 with the whole app.
- **Clear "no concert on this date" messaging** distinct from "something failed".
- Two themes? Style **both** whenever you add UI.

---

## 11. How to verify changes with no local dev machine

Everything above was verified this way; it needs only a headless browser.

```bash
# 1. syntax-check the inline <script>
python3 - <<'PY'
import re; h=open('index.html').read()
open('/tmp/app.js','w').write(re.search(r'<script>\n.*?</script>', h, re.S).group(0)[8:-9])
PY
node --check /tmp/app.js

# 2. smoke-test that the app initialises
python3 -m http.server 8199 & SRV=$!
"$CHROME" --headless=new --no-sandbox --disable-gpu --virtual-time-budget=6000 \
  --dump-dom http://localhost:8199/index.html | grep -oE '[0-9]+ SHOWS'
kill $SRV
```

For behaviour, drive it with Playwright and **intercept the Archive.org calls** so
you can simulate exact conditions: a 6-second outage, a permanently dead
recording, a 503 page, a refused connection. That is how the skipping bug was
pinned down.

For layout, **measure — do not eyeball**: compare `scrollHeight`, element widths
and overflow before and after, at 320 / 390 / 430px. Several "small" CSS changes
turned out to move the page by tens of pixels.

But remember §0: intercepted responses are not the live path. Use the branch
preview URL on a real phone before you call anything done.

---

## Suggested order of work

1. **§0** — write the outage triage into your contributor docs first.
2. **§8** — make maintenance scripts polite before running any of them.
3. **§1** — regenerate the show index properly (tune scoring for your collection).
4. **§4 + §5** — playback resilience and background playback: the biggest
   real-world quality wins.
5. **§7** — honest failure messages.
6. **§3 → §2** — track-name cleaning, then the song index that depends on it.
7. **§9** — the mobile UI fixes.
8. **§6, §10** — sharing, recording picker, and the smaller features.
