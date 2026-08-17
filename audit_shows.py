#!/usr/bin/env python3
"""
Audit shows.json against archive.org — finds dead links, missing MP3s, etc.
Run from the dialadead.com directory:
    python3 audit_shows.py
    python3 audit_shows.py --fix   # removes bad shows from shows.json
"""

import json, urllib.request, urllib.error, concurrent.futures, sys, argparse, shutil, time, threading
from datetime import datetime

SHOWS_FILE = 'shows.json'
# BE POLITE. This script used to fire 20 concurrent requests with no delay at
# all, across every show in the file — ~2,000 requests as fast as the network
# allowed. Archive.org rate-limits or blocks an IP that behaves like that, and
# because dialadead.com fetches archive.org *directly from the visitor's
# browser*, a block earned here also breaks the live site for whoever is on
# that connection. That failure looks exactly like a bug in the site (shows
# stop loading, old builds don't help), so it is worth a lot of patience here.
MAX_WORKERS = 4    # concurrent requests
MIN_INTERVAL = 0.25  # seconds between request starts, across all workers
TIMEOUT     = 20   # seconds per request
# archive.org asks that automated clients identify themselves and give a
# contact address, so they can get in touch instead of just blocking.
USER_AGENT  = 'dialadead-audit/2.0 (+https://dialadead.com; hello@neondeadhead.com)'
MAX_RETRIES = 4

_throttle = threading.Lock()
_next_at = [0.0]

def _wait_turn():
    """Global rate limit: no more than one request start per MIN_INTERVAL."""
    with _throttle:
        now = time.monotonic()
        start = max(now, _next_at[0])
        _next_at[0] = start + MIN_INTERVAL
    delay = start - time.monotonic()
    if delay > 0:
        time.sleep(delay)

def check(item):
    date, sid = item
    url = f'https://archive.org/metadata/{sid}'
    for attempt in range(MAX_RETRIES):
        _wait_turn()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                if r.status != 200:
                    return (date, sid, f'HTTP {r.status}')
                data = json.loads(r.read())
                files = data.get('files', [])
                mp3s  = [f for f in files if f['name'].lower().endswith('.mp3')]
                if not files:
                    return (date, sid, 'NO_FILES')
                if not mp3s:
                    return (date, sid, 'NO_MP3S')
                return None
        except urllib.error.HTTPError as e:
            # 429/503 mean "you are going too fast" — back off hard and retry
            # rather than counting the show as dead. Treating throttling as a
            # dead link is how a good show gets pruned out of shows.json.
            if e.code in (429, 503) and attempt < MAX_RETRIES - 1:
                time.sleep(5 * (2 ** attempt))
                continue
            return (date, sid, f'HTTP_{e.code}')
        except urllib.error.URLError as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (2 ** attempt))
                continue
            return (date, sid, f'URL_ERR: {str(e.reason)[:60]}')
        except Exception as e:
            return (date, sid, f'ERROR: {str(e)[:60]}')

def main():
    global MAX_WORKERS, MIN_INTERVAL
    parser = argparse.ArgumentParser()
    parser.add_argument('--fix', action='store_true',
                        help='Remove bad shows from shows.json (backs up original first)')
    parser.add_argument('--workers', type=int, default=MAX_WORKERS,
                        help=f'concurrent requests (default {MAX_WORKERS}; raising this risks a block)')
    parser.add_argument('--interval', type=float, default=MIN_INTERVAL,
                        help=f'minimum seconds between requests (default {MIN_INTERVAL})')
    parser.add_argument('--limit', type=int, default=0,
                        help='audit only the first N shows — use this to spot-check')
    args = parser.parse_args()
    MAX_WORKERS, MIN_INTERVAL = args.workers, args.interval

    shows = json.load(open(SHOWS_FILE))
    ids   = [(date, s['id']) for date, s in shows.items()]
    if args.limit:
        ids = ids[:args.limit]
    total = len(ids)

    rate = MAX_WORKERS / MIN_INTERVAL if MIN_INTERVAL else float('inf')
    print(f'Auditing {total} shows against archive.org...')
    print(f'Workers: {MAX_WORKERS}  Interval: {MIN_INTERVAL}s  Timeout: {TIMEOUT}s')
    print(f'Estimated time: ~{total * MIN_INTERVAL / 60:.0f} min at this rate.')
    print('A full audit is deliberately slow. Archive.org blocks IPs that hammer\n'
          'it, and the live site streams from archive.org in the visitor\'s own\n'
          'browser — so a block earned here also breaks dialadead.com for you.\n')

    bad  = []
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(check, i): i for i in ids}
        for f in concurrent.futures.as_completed(futures):
            done += 1
            if done % 100 == 0:
                pct = done / total * 100
                print(f'  {done}/{total}  ({pct:.0f}%)', flush=True)
            result = f.result()
            if result:
                bad.append(result)

    bad.sort()
    ok = total - len(bad)

    print(f'\n{"="*60}')
    print(f'RESULTS: {ok} OK  |  {len(bad)} PROBLEMS  |  {total} TOTAL')
    print(f'{"="*60}\n')

    if not bad:
        print('All shows look good!')
        return

    # Group by reason
    by_reason = {}
    for date, sid, reason in bad:
        by_reason.setdefault(reason, []).append((date, sid))

    for reason, items in sorted(by_reason.items()):
        print(f'── {reason} ({len(items)}) ──')
        for date, sid in items:
            print(f'  {date}  {sid}')
        print()

    # Write report
    report_file = f'audit_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
    with open(report_file, 'w') as fh:
        fh.write(f'Audit run: {datetime.now().isoformat()}\n')
        fh.write(f'Total: {total}  OK: {ok}  Problems: {len(bad)}\n\n')
        for reason, items in sorted(by_reason.items()):
            fh.write(f'── {reason} ({len(items)}) ──\n')
            for date, sid in items:
                fh.write(f'  {date}  {sid}\n')
            fh.write('\n')
    print(f'Report saved to: {report_file}')

    if args.fix:
        # A throttled run makes healthy shows look dead. Pruning on those
        # results would quietly delete good nights from the index and the
        # damage only shows up later, as shows that "don't exist" any more.
        throttled = [b for b in bad if b[2].startswith(('HTTP_429', 'HTTP_503', 'URL_ERR', 'ERROR'))]
        if throttled and len(throttled) > max(5, 0.1 * total):
            print(f'\nREFUSING TO PRUNE: {len(throttled)} of {len(bad)} failures look like '
                  f'rate limiting or network trouble,\nnot dead recordings. Those shows are '
                  f'probably fine. Wait for the block to lift\n(usually hours), then re-run — '
                  f'lower --workers / raise --interval if it keeps happening.')
            return
        bad_dates = {date for date, sid, reason in bad}
        backup = SHOWS_FILE.replace('.json', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        shutil.copy(SHOWS_FILE, backup)
        print(f'\nBacking up original to: {backup}')
        cleaned = {date: s for date, s in shows.items() if date not in bad_dates}
        with open(SHOWS_FILE, 'w') as fh:
            json.dump(cleaned, fh, indent=2)
        print(f'Removed {len(bad_dates)} bad shows from {SHOWS_FILE}')
        print(f'{len(cleaned)} shows remaining.')
    else:
        print(f'\nRun with --fix to remove bad shows from {SHOWS_FILE}')

if __name__ == '__main__':
    main()
