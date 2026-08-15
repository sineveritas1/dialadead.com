#!/usr/bin/env python3
"""
build_shows.py — regenerate shows.json from the archive.org Grateful Dead collection.

This replaces the old (lost) generate_shows.py. The important difference is *how
it pulls*: instead of querying archive.org date by date, it scrapes the whole
collection once via the scrape API (~18k recordings, ~19 paginated requests),
then decides everything locally. That means:

  * every recording of every night is considered, so the "best" pick is a real
    comparison rather than whatever one search happened to return first;
  * venue/city can be recovered from *any* recording of that night, which fixes
    the "unknown" / "Various - See info file" entries that made the old file
    look broken;
  * non-concerts (interviews, radio spots, studio sessions) and bogus dates
    (gd1967-00-00, gd1966-XX-XX) are rejected instead of being pinned onto a
    real calendar date;
  * it is cheap and repeatable — the raw scrape is cached to disk, so re-running
    with different scoring costs zero requests.

Usage:
    python3 build_shows.py                 # build shows.json (uses cache if fresh)
    python3 build_shows.py --refresh       # force a fresh scrape from archive.org
    python3 build_shows.py --dry-run       # report only, don't write shows.json
    python3 build_shows.py --report-only   # just describe what's in the cache

Output: shows.json  { "YYYY-MM-DD": {id, venue, city, type, [partial]} }
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

COLLECTION = 'GratefulDead'
SHOWS_FILE = 'shows.json'
CACHE_FILE = '.archive_cache.json'
CACHE_MAX_AGE = 24 * 3600          # re-scrape if the cache is older than a day
SCRAPE_URL = 'https://archive.org/services/search/v1/scrape'
FIELDS = 'identifier,date,venue,coverage,title,downloads,avg_rating,source,subject'
PAGE = 1000
TIMEOUT = 60
USER_AGENT = 'dialadead-build/2.0 (+https://dialadead.com)'

# The band's actual performing years. Anything outside this is not a show.
FIRST_YEAR, LAST_YEAR = 1965, 1995

# Recordings that aren't concerts. Matched against identifier + title.
NON_CONCERT = re.compile(
    r'\b(interview|radio[\s._-]?spot|commercial|promo|rehearsal|soundcheck|'
    r'studio[\s._-]?(session|outtake)|outtake|documentary|press[\s._-]?conf)',
    re.I)

# Compilations / unknown-date material masquerading as a dated show.
# Matches gd1966-XX-XX, gd1967-00-00, and partial-unknowns like gd1985-02-00
# (day 00) or gd1968-00-12 (month 00) — none of these are a specific concert.
BOGUS_DATE = re.compile(r'xx[-._]?xx', re.I)
ID_DATE = re.compile(r'\b(?:gd)?(\d{2,4})[-.](\d{2}|xx)[-.](\d{2}|xx)', re.I)

PARTIAL_HINT = re.compile(r'\b(partial|incomplete|fragment|excerpt)\b', re.I)
SET_ONLY_HINT = re.compile(r'\b(set[\s._-]?[123]|s[123])\b(?![\s._-]*t\d)', re.I)

SBD_HINT = re.compile(r'\b(sbd|soundboard|dsbd|fob[\s._-]?sbd)\b', re.I)
MTX_HINT = re.compile(r'\b(mtx|matrix)\b', re.I)
AUD_HINT = re.compile(r'\b(aud|audience)\b', re.I)

JUNK_TEXT = re.compile(
    r'^\s*(unknown|unknown location|various|various artists|n/?a|none|null|'
    r'-+|\?+|see info(\s*file)?|various\s*-\s*see info file)\s*$', re.I)


def log(msg):
    print(msg, flush=True)


def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def scrape_collection():
    """Pull every item in the collection using cursor pagination."""
    items, cursor, page = [], None, 0
    while True:
        params = {'q': f'collection:{COLLECTION}', 'fields': FIELDS, 'count': PAGE}
        if cursor:
            params['cursor'] = cursor
        url = f'{SCRAPE_URL}?{urllib.parse.urlencode(params)}'

        for attempt in range(5):
            try:
                data = fetch_json(url)
                break
            except Exception as e:
                wait = 2 ** attempt
                log(f'   ! {type(e).__name__}: {e} — retrying in {wait}s')
                time.sleep(wait)
        else:
            raise SystemExit('archive.org unreachable after 5 attempts')

        batch = data.get('items', [])
        items.extend(batch)
        page += 1
        total = data.get('total')
        log(f'   page {page}: +{len(batch)}  ({len(items)}'
            + (f'/{total}' if total else '') + ')')

        cursor = data.get('cursor')
        if not cursor or not batch:
            break
        time.sleep(0.3)          # be polite to archive.org
    return items


def load_items(refresh=False):
    if not refresh and os.path.exists(CACHE_FILE):
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < CACHE_MAX_AGE:
            with open(CACHE_FILE) as fh:
                items = json.load(fh)
            log(f'Using cached scrape: {len(items)} recordings '
                f'({age/3600:.1f}h old). --refresh to re-pull.')
            return items
        log(f'Cache is {age/3600:.1f}h old — re-scraping.')
    log(f'Scraping the {COLLECTION} collection from archive.org...')
    items = scrape_collection()
    with open(CACHE_FILE, 'w') as fh:
        json.dump(items, fh)
    log(f'Cached {len(items)} recordings to {CACHE_FILE}')
    return items


def parse_date(raw):
    """archive.org dates look like '1977-05-08T00:00:00Z'. Return YYYY-MM-DD."""
    if not raw:
        return None
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(raw))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if not (FIRST_YEAR <= y <= LAST_YEAR):
        return None
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f'{y:04d}-{mo:02d}-{d:02d}'


def clean_text(value):
    """Return a trimmed string, or '' if it's junk like 'unknown' / 'various'."""
    if value is None:
        return ''
    if isinstance(value, list):
        value = value[0] if value else ''
    s = re.sub(r'\s+', ' ', str(value)).strip().strip(',;|-').strip()
    if not s or JUNK_TEXT.match(s):
        return ''
    # "Unknown Location (possibly Owsley's house)" -> keep the parenthetical hint
    if re.match(r'^unknown\b', s, re.I) and '(' not in s:
        return ''
    return s


def blob(item):
    """Everything we might want to pattern-match on, as one lowercase string."""
    subj = item.get('subject') or []
    if isinstance(subj, str):
        subj = [subj]
    return ' '.join([
        str(item.get('identifier', '')),
        str(item.get('title', '')),
        str(item.get('source', '')),
        ' '.join(str(s) for s in subj),
    ]).lower()


def lineage(item):
    """sbd / mtx / aud.

    The identifier is authoritative: taper naming convention puts the lineage
    right in it, and it is the one field nobody writes prose in. Free-text
    `source` / `title` are only consulted when the identifier says nothing,
    because they contain things like "Audience (was labeled as sbd)" — matching
    that would flip a genuine audience tape to soundboard.
    """
    ident = str(item.get('identifier', ''))
    if MTX_HINT.search(ident):
        return 'mtx'
    if AUD_HINT.search(ident):
        return 'aud'
    if SBD_HINT.search(ident):
        return 'sbd'

    text = blob(item)
    # Ignore self-correcting notes like "was labeled as sbd" / "not sbd".
    text = re.sub(r'\b(was|previously|incorrectly|mis)[\s\w]{0,12}labell?ed[^.;,]*', ' ', text)
    text = re.sub(r'\bnot\s+(a\s+)?(sbd|soundboard|matrix)\b', ' ', text)
    if MTX_HINT.search(text):
        return 'mtx'
    if AUD_HINT.search(text):
        return 'aud'
    if SBD_HINT.search(text):
        return 'sbd'
    return 'aud'


def is_non_concert(item):
    return bool(NON_CONCERT.search(blob(item)))


def has_bogus_date(item):
    """True if the identifier advertises an unknown/placeholder date.

    archive.org still stamps such items with a concrete `date` field (often the
    1st of the month/year), so trusting `date` alone silently pins compilations
    and studio sessions onto real concert nights.
    """
    ident = str(item.get('identifier', ''))
    if BOGUS_DATE.search(ident):
        return True
    m = ID_DATE.search(ident)
    if m:
        _, mo, d = m.groups()
        if mo.lower() == 'xx' or d.lower() == 'xx':
            return True
        if mo == '00' or d == '00':
            return True
    return False


def partial_flag(item):
    text = blob(item)
    if PARTIAL_HINT.search(text):
        return 'partial'
    if SET_ONLY_HINT.search(str(item.get('identifier', ''))):
        m = SET_ONLY_HINT.search(str(item.get('identifier', '')))
        return m.group(1).lower().replace('.', '').replace('_', '').replace('-', '')
    return None


def score(item):
    """Higher is better. Lineage dominates, then popularity, then rating.

    A well-regarded matrix is as good a default as a soundboard, so those sit
    close together and let popularity/rating break the tie; audience tapes are
    only chosen when nothing better exists for that night.
    """
    lin = lineage(item)
    s = {'sbd': 3000, 'mtx': 2900, 'aud': 0}[lin]

    try:
        downloads = int(item.get('downloads') or 0)
    except (TypeError, ValueError):
        downloads = 0
    # Log scale: download counts span ~1e2..1e6 across the collection, so a
    # linear cap would flatten the difference between a well-loved transfer and
    # a merely old one. Log keeps the spread meaningful without swamping lineage.
    s += math.log10(downloads + 10) * 300

    try:
        rating = float(item.get('avg_rating') or 0)
    except (TypeError, ValueError):
        rating = 0.0
    s += rating * 100

    if partial_flag(item):
        s -= 1500                      # a complete AUD beats a partial SBD
    if not clean_text(item.get('venue')):
        s -= 50                        # mild nudge toward well-described items
    return s


def build(items):
    by_date = defaultdict(list)
    rejected = Counter()

    for it in items:
        if is_non_concert(it):
            rejected['non-concert (interview/rehearsal/studio/promo)'] += 1
            continue
        if has_bogus_date(it):
            rejected['bogus date in identifier (XX-XX / 00-00)'] += 1
            continue
        date = parse_date(it.get('date'))
        if not date:
            rejected['missing or out-of-range date'] += 1
            continue
        by_date[date].append(it)

    shows = {}
    stats = Counter()
    for date, recs in by_date.items():
        best = max(recs, key=score)

        # Venue/city: prefer the winner's own metadata, but fall back to the
        # most common non-junk value among *all* recordings of that night.
        venue = clean_text(best.get('venue'))
        city = clean_text(best.get('coverage'))
        if not venue:
            votes = Counter(v for v in (clean_text(r.get('venue')) for r in recs) if v)
            if votes:
                venue = votes.most_common(1)[0][0]
                stats['venue recovered from another recording'] += 1
        if not city:
            votes = Counter(c for c in (clean_text(r.get('coverage')) for r in recs) if c)
            if votes:
                city = votes.most_common(1)[0][0]
                stats['city recovered from another recording'] += 1

        lin = lineage(best)
        entry = {
            'id': best['identifier'],
            'venue': venue,
            'city': city,
            # the UI only distinguishes soundboard-ish from audience
            'type': 'sbd' if lin in ('sbd', 'mtx') else 'aud',
        }
        p = partial_flag(best)
        if p:
            entry['partial'] = p
            stats['marked partial'] += 1
        shows[date] = entry
        stats['dates'] += 1
        stats[f'best pick: {lin}'] += 1

    return dict(sorted(shows.items())), rejected, stats, by_date


def compare(old, new):
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new)
                     if old[k].get('id') != new[k].get('id'))

    def junk_count(d, field):
        return sum(1 for v in d.values() if not str(v.get(field, '')).strip())

    log('\n' + '=' * 62)
    log('COMPARISON WITH EXISTING shows.json')
    log('=' * 62)
    log(f'  dates:            {len(old)}  ->  {len(new)}   ({len(new)-len(old):+d})')
    log(f'  added dates:      {len(added)}')
    log(f'  removed dates:    {len(removed)}')
    log(f'  changed recording:{len(changed)}')
    log(f'  empty venue:      {junk_count(old,"venue")}  ->  {junk_count(new,"venue")}')
    log(f'  empty city:       {junk_count(old,"city")}  ->  {junk_count(new,"city")}')
    if removed:
        log('\n  sample removed (should be non-concerts / bogus dates):')
        for k in removed[:12]:
            log(f'    {k}  {old[k].get("id","")}')
    if added:
        log('\n  sample added:')
        for k in added[:12]:
            log(f'    {k}  {new[k].get("id","")}  {new[k].get("venue","")}')
    return added, removed, changed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--refresh', action='store_true',
                    help='force a fresh scrape instead of using the cache')
    ap.add_argument('--dry-run', action='store_true',
                    help='report what would change but do not write shows.json')
    ap.add_argument('--report-only', action='store_true',
                    help='describe the collection and exit')
    args = ap.parse_args()

    items = load_items(refresh=args.refresh)

    if args.report_only:
        log(f'\n{len(items)} recordings in the {COLLECTION} collection.')
        log(f'  non-concerts:  {sum(1 for i in items if is_non_concert(i))}')
        log(f'  bogus dates:   {sum(1 for i in items if has_bogus_date(i))}')
        lin = Counter(lineage(i) for i in items)
        log(f'  lineage:       {dict(lin)}')
        return

    shows, rejected, stats, by_date = build(items)

    log('\n' + '=' * 62)
    log('BUILD SUMMARY')
    log('=' * 62)
    log(f'  recordings scanned:  {len(items)}')
    for reason, n in rejected.most_common():
        log(f'  rejected: {reason}: {n}')
    log(f'  concert dates built: {len(shows)}')
    for k, v in sorted(stats.items()):
        if k != 'dates':
            log(f'  {k}: {v}')
    multi = sum(1 for d, r in by_date.items() if len(r) > 1)
    log(f'  dates with >1 recording available: {multi}')

    old = {}
    if os.path.exists(SHOWS_FILE):
        with open(SHOWS_FILE) as fh:
            old = json.load(fh)
        compare(old, shows)

    if args.dry_run:
        log('\n--dry-run: shows.json not written.')
        return

    with open(SHOWS_FILE, 'w') as fh:
        json.dump(shows, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    log(f'\nWrote {len(shows)} shows to {SHOWS_FILE}')


if __name__ == '__main__':
    sys.exit(main())
