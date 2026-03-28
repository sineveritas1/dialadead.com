#!/usr/bin/env python3
"""
Audit shows.json against archive.org — finds dead links, missing MP3s, etc.
Run from the dialadead.com directory:
    python3 audit_shows.py
    python3 audit_shows.py --fix   # removes bad shows from shows.json
"""

import json, urllib.request, urllib.error, concurrent.futures, sys, argparse, shutil
from datetime import datetime

SHOWS_FILE = 'shows.json'
MAX_WORKERS = 20   # concurrent requests — lower if archive.org rate-limits you
TIMEOUT     = 15   # seconds per request

def check(item):
    date, sid = item
    url = f'https://archive.org/metadata/{sid}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'dialadead-audit/1.0'})
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
        return (date, sid, f'HTTP_{e.code}')
    except urllib.error.URLError as e:
        return (date, sid, f'URL_ERR: {str(e.reason)[:60]}')
    except Exception as e:
        return (date, sid, f'ERROR: {str(e)[:60]}')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fix', action='store_true',
                        help='Remove bad shows from shows.json (backs up original first)')
    args = parser.parse_args()

    shows = json.load(open(SHOWS_FILE))
    ids   = [(date, s['id']) for date, s in shows.items()]
    total = len(ids)

    print(f'Auditing {total} shows against archive.org...')
    print(f'Workers: {MAX_WORKERS}  Timeout: {TIMEOUT}s\n')

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
