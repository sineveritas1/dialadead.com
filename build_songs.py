#!/usr/bin/env python3
"""
build_songs.py — build songs.json, a song-title -> show-dates index.

Why this exists: the archive search could only match venue, city and date,
because shows.json holds no track information. Searching by song needs the
tracklist of every show, and that is one metadata request per show.

It is therefore SLOW ON PURPOSE. 4 workers with 0.25s between request starts,
same pacing as audit_shows.py: archive.org rate-limits clients that go faster,
and a limited IP breaks the live site for whoever is on that connection (see
CLAUDE.md). ~2,000 shows takes roughly 10 minutes. Don't "speed it up".

Output is deliberately compact, because the browser downloads it:
    {"d": ["1965-11-03", ...],            # every date, once
     "s": {"Althea": "1f,2a,3b", ...}}    # song -> base36 indices into d

Usage:
    python3 build_songs.py                 # build songs.json
    python3 build_songs.py --limit 50      # spot-check on 50 shows
"""
import argparse, json, re, sys, threading, time, urllib.error, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

SHOWS_FILE, OUT_FILE = 'shows.json', 'songs.json'
WORKERS, INTERVAL, TIMEOUT, RETRIES = 4, 0.25, 20, 4
UA = 'dialadead-songs/1.0 (+https://dialadead.com; hello@neondeadhead.com)'

_lock = threading.Lock(); _next = [0.0]
def _wait():
    with _lock:
        start = max(time.monotonic(), _next[0]); _next[0] = start + INTERVAL
    d = start - time.monotonic()
    if d > 0: time.sleep(d)

# ── cleanName(), ported from index.html so indexed titles match the setlist ──
CANON_NAMES = ["Truckin'","Sugar Magnolia","Scarlet Begonias","Fire on the Mountain",
 "Casey Jones","Ripple","Friend of the Devil","Uncle John's Band","Playing in the Band",
 "Dark Star","St. Stephen","The Other One","Not Fade Away","Good Lovin'","Bertha",
 "Jack Straw","Tennessee Jed","Ramble On Rose","Brown-Eyed Women","Cumberland Blues",
 "China Cat Sunflower","I Know You Rider","Eyes of the World","Estimated Prophet",
 "Terrapin Station","He's Gone","Wharf Rat","Deal","Loser","Candyman","Sugaree",
 "Mississippi Half-Step","Cassidy","Row Jimmy","Franklin's Tower","The Music Never Stopped",
 "Shakedown Street","Touch of Grey","Throwing Stones","Morning Dew","Around and Around",
 "Johnny B. Goode","U.S. Blues","One More Saturday Night","Turn On Your Love Light",
 "Goin' Down the Road Feeling Bad","El Paso","Me and My Uncle","Big River","Mama Tried",
 "Deep Elem Blues","Cold Rain and Snow","Bird Song","Box of Rain","Attics of My Life",
 "Black Peter","Standing on the Moon","Stella Blue","Comes a Time","Help on the Way",
 "Slipknot!","Weather Report Suite","China Doll","Brokedown Palace","Might as Well",
 "Feel Like a Stranger","Hell in a Bucket","West L.A. Fadeaway","Althea","Alabama Getaway",
 "Samson and Delilah","New Speedway Boogie","Dire Wolf","Cosmic Charlie","The Wheel",
 "Dupree's Diamond Blues","Jack-A-Roe","Peggy-O","Sing Me Back Home","Tomorrow Is Forever",
 "Drums","Space","Birdsong","Playing in the Band Reprise"]
_norm = lambda x: re.sub(r'[^a-z0-9]', '', x.lower())
CANON = {_norm(n): n for n in CANON_NAMES}
CANON.update({
 'gdtrfb':"Goin' Down the Road Feeling Bad", 'goingdowntheroadfeelingbad':"Goin' Down the Road Feeling Bad",
 'nfa':'Not Fade Away','ujb':"Uncle John's Band",'fotm':'Fire on the Mountain',
 'ststephen':'St. Stephen','saintstephen':'St. Stephen','usblues':'U.S. Blues',
 'playin':'Playing in the Band','playinintheband':'Playing in the Band',
 'lovelight':'Turn On Your Love Light','loveligh':'Turn On Your Love Light',
 'goodloving':"Good Lovin'",'theotherone':'The Other One','wheel':'The Wheel',
 'jbgoode':'Johnny B. Goode','chinacat':'China Cat Sunflower','ikyr':'I Know You Rider'})

I = re.I
def clean_name(raw):
    if not raw: return '—'
    s = raw
    s = re.sub(r'\.(mp3|flac|shn|ogg|wav)$', '', s, flags=I)
    s = re.sub(r'[._](64|128|192|256|320)k?b?$', '', s, flags=I)
    s = re.sub(r'_vbr$', '', s, flags=I)
    s = re.sub(r'(\.(sbeok|shnf|shntool|shn|flac\d*|md5|st5|sbd|aud|matrix|vbr))+$', '', s, flags=I)
    s = re.sub(r'^gd\d{2,4}[.\-]\d{2}[.\-]\d{2}(\.[a-z0-9]+)*[\s._\-]*(d\d+)?(s\d+)?t\d+[._\-\s]*', '', s, flags=I)
    s = re.sub(r'^gd[\s._-]*\d{2,4}[.\-\s_]?\d{2}[.\-\s_]?\d{2}[\s._\-]*(?:(?:[ds]\d+)?t?\d{1,3})?[\s._\-]*', '', s, flags=I)
    s = re.sub(r'^grateful[\s._-]*dead[\s\d._-]*(s\d+)?(t\d+)?[\s._-]*(?=[a-zA-Z])', '', s, flags=I)
    s = re.sub(r'^grateful[\s._-]*dead[\s\d._-]+', '', s, flags=I)
    s = re.sub(r'^\.?(d\d+)?(s\d+)?t\d+[._\-\s]*', '', s, flags=I)
    s = re.sub(r'^\d{1,3}[._\-\s]+', '', s)
    s = re.sub(r'\b(sbeok|shnf|shntool|shn|flac\d*|sbd|aud|matrix|remaster(ed)?|stereo|mono|set\d+|disc\d+|d\d+)\b', '', s, flags=I)
    s = re.sub(r'\b\d{4,}\b', ' ', s)
    s = re.sub(r'\s*->\s*', ' > ', s)
    s = re.sub(r'[._\-]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^[^a-zA-Z0-9(]+|[^a-zA-Z0-9\'")]+$', '', s).strip()
    if s and not re.search(r'\s', s) and re.search(r'[a-z][A-Z]', s):
        s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    if s and s == s.lower():
        s = re.sub(r'\b\w', lambda m: m.group(0).upper(), s)
    return CANON.get(_norm(s), s) or '—'

# Not songs — segues, tuning, crowd noise, encore markers.
SKIP = re.compile(r'^(tuning|crowd|banter|intro|outro|applause|encore|silence|'
                  r'untitled|unknown|track ?\d*|jam|—|-)$', I)

def tracks_for(identifier):
    url = f'https://archive.org/metadata/{identifier}'
    for attempt in range(RETRIES):
        _wait()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                meta = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < RETRIES - 1:
                time.sleep(5 * (2 ** attempt)); continue
            return None
        except Exception:
            if attempt < RETRIES - 1:
                time.sleep(2 * (2 ** attempt)); continue
            return None
    else:
        return None
    files = meta.get('files') or []
    mp3s = [f for f in files if f.get('name', '').lower().endswith('.mp3')]
    if not mp3s: return None
    out, seen = [], set()
    for f in mp3s:
        n = clean_name(f.get('title') or f.get('name'))
        if not n or n == '—' or SKIP.match(n): continue
        # A segue title covers several songs — index each of them.
        for part in re.split(r'\s*>\s*', n):
            part = part.strip()
            if not part or SKIP.match(part): continue
            part = CANON.get(_norm(part), part)
            if len(part) > 60: continue
            if part.lower() not in seen:
                seen.add(part.lower()); out.append(part)
    return out

def b36(n):
    if n == 0: return '0'
    d, out = '0123456789abcdefghijklmnopqrstuvwxyz', ''
    while n: n, r = divmod(n, 36); out = d[r] + out
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()
    shows = json.load(open(SHOWS_FILE))
    dates = sorted(shows)
    if args.limit: dates = dates[:args.limit]
    print(f'Indexing songs for {len(dates)} shows '
          f'(~{len(dates)*INTERVAL/60:.0f} min at {WORKERS} workers / {INTERVAL}s).', flush=True)

    idx, done, failed = defaultdict(list), [0], []
    def work(i_date):
        i, date = i_date
        names = tracks_for(shows[date]['id'])
        done[0] += 1
        if done[0] % 200 == 0:
            print(f'  {done[0]}/{len(dates)}', flush=True)
        if names is None: failed.append(date); return
        for n in names: idx[n].append(i)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, enumerate(dates)))

    # Keep songs that appear more than once; one-offs are nearly all junk titles.
    songs = {n: ','.join(b36(i) for i in sorted(set(v)))
             for n, v in sorted(idx.items()) if len(set(v)) > 1}
    json.dump({'d': dates, 's': songs}, open(OUT_FILE, 'w'), ensure_ascii=False, separators=(',', ':'))
    import os
    print(f'\n{len(songs)} songs across {len(dates)} shows -> {OUT_FILE} '
          f'({os.path.getsize(OUT_FILE)/1024:.0f} KB)')
    print(f'failed/no-mp3 shows: {len(failed)}')
    top = sorted(idx.items(), key=lambda kv: -len(set(kv[1])))[:12]
    print('most-played:', ', '.join(f'{n} ({len(set(v))})' for n, v in top))

if __name__ == '__main__':
    sys.exit(main())
