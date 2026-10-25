#!/usr/bin/env python3
"""
build_pages.py — write the static, crawlable pages search engines index.

Why this exists: the app is one index.html that draws everything with JS, and
every show lives at /?date=YYYY-MM-DD. Google sees the raw HTML first — a date
picker and a footer — and nothing links to the ?date= URLs, so it had nothing
to index. This writes plain HTML that needs no JS to read:

    show/YYYY-MM-DD.html   one page per show in shows.json  -> /show/YYYY-MM-DD
    year/YYYY.html         every show that year, linked     -> /year/YYYY
    pages.css              the one stylesheet they share
    sitemap.xml            the homepage, every year and every show

Cloudflare Pages serves foo.html at /foo, so the links below carry no
extension. Each show page links into the player at /?date=…; the player sets
its canonical back to /show/… so the two don't compete in search results.

Generated, not hand-edited — like shows.json. Re-run after rebuilding
shows.json or songs.json and commit the output. Makes no network requests.

Usage:
    python3 build_pages.py
"""
import html, json, os, shutil
from collections import defaultdict

SITE = 'https://dialadead.com'
LOGO = 'https://res.cloudinary.com/dmbeoutyi/image/upload/v1774666557/Untitled_design_16_v575qu.png'
BRAND = 'https://res.cloudinary.com/dmbeoutyi/image/upload/w_72,h_72,c_fill,f_auto,q_auto/v1774666557/Untitled_design_16_v575qu.png'
ICON = 'https://res.cloudinary.com/dmbeoutyi/image/upload/w_64,h_64,c_fill/v1774666557/Untitled_design_16_v575qu.png'
MONTHS = ['January','February','March','April','May','June','July','August',
          'September','October','November','December']
JUNK = {'', 'unknown', 'various', 'various - see info file', 'unknown, unknown'}

esc = lambda s: html.escape(s or '', quote=True)
def real(s): return s if (s or '').strip().lower() not in JUNK else ''
def long_date(k):
    y, m, d = map(int, k.split('-')); return f'{MONTHS[m-1]} {d}, {y}'
def where(s): return ', '.join(x for x in (real(s.get('venue')), real(s.get('city'))) if x)

CSS = """*{margin:0;padding:0;box-sizing:border-box}
body{background:#050505;color:#ddd;font-family:'Share Tech Mono',monospace;display:flex;justify-content:center;padding:10px;line-height:1.6}
.machine{width:100%;max-width:640px;background:#090909;border:2px solid #2a2a2a;border-radius:16px;padding:18px 16px 24px;box-shadow:0 0 0 1px #333,0 0 40px rgba(255,20,147,.1)}
a{color:#00BFFF;text-decoration:none}a:hover{text-decoration:underline}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:14px;font-family:'Orbitron',monospace;font-weight:900;letter-spacing:4px;color:#39FF14;text-shadow:0 0 10px #39FF1466}
.brand img{width:36px;height:36px}
.crumbs{font-size:12px;color:#888;margin-bottom:12px}
h1{font-family:'Orbitron',monospace;font-size:clamp(18px,5vw,24px);color:#FF1493;text-shadow:0 0 10px #FF149366;letter-spacing:1px;line-height:1.3;margin-bottom:6px}
h2{font-family:'Orbitron',monospace;font-size:13px;color:#39FF14;letter-spacing:2px;margin:20px 0 8px}
.where{color:#00BFFF;font-size:15px}.meta{color:#39FF14cc;font-size:13px;margin-top:2px}
.play{display:inline-block;margin:16px 0 4px;background:#FF1493;color:#fff;font-family:'Orbitron',monospace;font-weight:700;letter-spacing:2px;padding:12px 18px;border-radius:8px;box-shadow:0 0 16px #FF149388}
.play:hover{background:#ff3aac;text-decoration:none}
ul{list-style:none}.songs{columns:2;column-gap:16px;font-size:14px}.songs li{break-inside:avoid}
.shows li{padding:6px 0;border-bottom:1px solid #1a1a1a;font-size:14px}.shows .v{color:#aaa}
.nav{display:flex;justify-content:space-between;gap:10px;margin-top:20px;font-size:13px}
.years{display:flex;flex-wrap:wrap;gap:6px;font-size:13px}.years a{border:1px solid #2a2a2a;border-radius:4px;padding:2px 7px}
p{font-size:14px;margin-top:8px}.foot{margin-top:24px;font-size:12px;color:#888;text-align:center}
@media(max-width:420px){.songs{columns:1}}"""

def page(title, desc, path, body, ld=None):
    url = SITE + path
    lds = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n' if ld else ''
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<link rel="icon" type="image/png" sizes="64x64" href="{ICON}">
<meta name="theme-color" content="#39FF14">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{LOGO}">
<meta property="og:site_name" content="DIAL·A·DEAD">
<meta name="twitter:card" content="summary">
{lds}<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/pages.css">
</head>
<body>
<main class="machine">
<a class="brand" href="/"><img src="{BRAND}" alt="" width="36" height="36">DIAL·A·DEAD</a>
{body}
<div class="foot"><a href="/">DIAL·A·DEAD</a> · Grateful Dead time machine · audio streams free from <a href="https://archive.org/details/GratefulDead">Archive.org</a></div>
</main>
</body>
</html>
"""

def year_links(years, cur=None):
    return '<div class="years">' + ''.join(
        f'<span>{y}</span>' if y == cur else f'<a href="/year/{y}">{y}</a>' for y in years) + '</div>'

def songs_by_date():
    try: s = json.load(open('songs.json'))
    except (OSError, ValueError): return {}
    out = defaultdict(list)
    for song, idx in s['s'].items():
        for i in idx.split(','): out[s['d'][int(i, 36)]].append(song)
    return {k: sorted(v, key=str.lower) for k, v in out.items()}

def show_page(k, s, prev, nxt, songs):
    y = k[:4]; ld_date = long_date(k); w = where(s); sbd = s.get('type') == 'sbd'
    rec = 'Soundboard' if sbd else 'Audience'
    title = f'Grateful Dead {ld_date}' + (f' — {w}' if w else '') + ' | DIAL·A·DEAD'
    desc = (f'Stream the Grateful Dead concert from {ld_date}' + (f' at {w}' if w else '')
            + f'. {rec} recording, free from Archive.org' + (f' — {len(songs)} songs incl. '
            + ', '.join(songs[:3]) if songs else '') + '.')
    body = [f'<div class="crumbs"><a href="/">Home</a> › <a href="/year/{y}">{y}</a> › {esc(ld_date)}</div>',
            f'<h1>Grateful Dead — {esc(ld_date)}</h1>']
    if w: body.append(f'<div class="where">{esc(w)}</div>')
    body.append(f'<div class="meta">{rec} recording · Archive.org</div>')
    body.append(f'<a class="play" href="/?date={k}">▶ PLAY THIS SHOW</a>')
    if songs:
        body.append(f'<h2>SONGS PLAYED · A–Z ({len(songs)})</h2><ul class="songs">'
                    + ''.join(f'<li>{esc(x)}</li>' for x in songs) + '</ul>')
    body.append(f'<p>Every recording Archive.org holds for this night — soundboards, matrixes and '
                f'audience tapes — is selectable in the player. Source: '
                f'<a href="https://archive.org/details/{esc(s["id"])}">{esc(s["id"])}</a>.</p>')
    body.append('<div class="nav">'
                + (f'<a href="/show/{prev}">← {esc(long_date(prev))}</a>' if prev else '<span></span>')
                + (f'<a href="/show/{nxt}">{esc(long_date(nxt))} →</a>' if nxt else '<span></span>') + '</div>')
    ld = {'@context': 'https://schema.org', '@type': 'MusicEvent',
          'name': f'Grateful Dead — {ld_date}', 'startDate': k,
          'eventStatus': 'https://schema.org/EventScheduled',
          'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
          'performer': {'@type': 'MusicGroup', 'name': 'Grateful Dead'},
          'location': {'@type': 'Place', 'name': real(s.get('venue')) or 'Unknown venue',
                       'address': real(s.get('city')) or 'Unknown'},
          'url': f'{SITE}/show/{k}'}
    return page(title, desc, f'/show/{k}', '\n'.join(body), ld)

def year_page(y, keys, shows, years):
    i = years.index(y); prev = years[i-1] if i else None; nxt = years[i+1] if i+1 < len(years) else None
    title = f'Grateful Dead {y} Shows — Stream All {len(keys)} Concerts | DIAL·A·DEAD'
    desc = (f'All {len(keys)} Grateful Dead concerts from {y}, free to stream from Archive.org: '
            f'{", ".join(long_date(k) for k in keys[:3])} and more.')
    items = ''.join(f'<li><a href="/show/{k}">{esc(long_date(k))}</a>'
                    + (f' <span class="v">— {esc(where(shows[k]))}</span>' if where(shows[k]) else '')
                    + '</li>' for k in keys)
    body = (f'<div class="crumbs"><a href="/">Home</a> › {y}</div>'
            f'<h1>Grateful Dead {y} Shows</h1>'
            f'<div class="meta">{len(keys)} shows · tap one to read about it and stream it</div>'
            f'<ul class="shows">{items}</ul>'
            '<div class="nav">'
            + (f'<a href="/year/{prev}">← {prev}</a>' if prev else '<span></span>')
            + (f'<a href="/year/{nxt}">{nxt} →</a>' if nxt else '<span></span>') + '</div>'
            f'<h2>ALL YEARS</h2>{year_links(years, y)}')
    return page(title, desc, f'/year/{y}', body)

def main():
    shows = json.load(open('shows.json')); keys = sorted(shows); songs = songs_by_date()
    by_year = defaultdict(list)
    for k in keys: by_year[k[:4]].append(k)
    years = sorted(by_year)
    with open('pages.css', 'w') as f: f.write(CSS + '\n')
    for d in ('show', 'year'):
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for i, k in enumerate(keys):
        with open(f'show/{k}.html', 'w') as f:
            f.write(show_page(k, shows[k], keys[i-1] if i else None,
                              keys[i+1] if i+1 < len(keys) else None, songs.get(k, [])))
    for y in years:
        with open(f'year/{y}.html', 'w') as f: f.write(year_page(y, by_year[y], shows, years))
    urls = ['/'] + [f'/year/{y}' for y in years] + [f'/show/{k}' for k in keys]
    with open('sitemap.xml', 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + ''.join(f'  <url><loc>{SITE}{u}</loc></url>\n' for u in urls) + '</urlset>\n')
    print(f'wrote {len(keys)} show pages, {len(years)} year pages, sitemap with {len(urls)} URLs')

if __name__ == '__main__':
    main()
