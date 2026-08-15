# DIAL·A·DEAD

**A neon time machine for Deadheads.** Dial in any date from 1965–1995 and the
Grateful Dead show from that night plays — streamed straight from the
[Archive.org](https://archive.org/details/GratefulDead) live-music collection.
Free, no account, no ads.

### [▶ Open dialadead.com](https://dialadead.com)

## Features

- **Dial a date** — type MM / DD / YYYY and hit ENGAGE.
- **Every recording** — pick from all soundboards, matrixes, and audience tapes
  Archive.org has for that night, in a dropdown.
- **Lockscreen playback** — the current song title shows in your phone's
  notification/lockscreen, and playback keeps going with the screen off.
- **Browse & search** the full ~2,000-show archive by year, venue, or city.
- **Save favorites**, jump to the previous/next show, and download a single
  track or a whole show as a ZIP.
- **RANDOM** — feeling lucky? Let it pick a night for you.
- Installable as a PWA. Neon or black-and-white "purist" theme.

## Tech

One self-contained `index.html` — hand-written HTML/CSS/vanilla JS, no build
step. `shows.json` is the show index; everything else is fetched live from
Archive.org. Hosted on Cloudflare Pages.

See [`CLAUDE.md`](./CLAUDE.md) for architecture, conventions, and deployment.

Feedback welcome → hello@neondeadhead.com · [neondeadhead.com](https://neondeadhead.com)
