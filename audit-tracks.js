// Dial-A-Dead track audit — checks every show in shows.json against Archive.org
// Usage: node audit-tracks.js
// Output: audit-results.json + summary printed to console
//
// Rate-limited to 3 req/sec to be polite to Archive.org

import { readFileSync, writeFileSync } from 'fs';

const THRESHOLD = 10; // flag shows with fewer deduped MP3s than this
const DELAY_MS  = 340; // ~3 req/sec

const shows = JSON.parse(readFileSync('./shows.json', 'utf8'));
const entries = Object.entries(shows); // [[date, {id,venue,city,type}], ...]

function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

function dedupedMp3Count(files){
  const allMp3s = files.filter(f => f.name.toLowerCase().endsWith('.mp3'));
  const seen = new Map();
  for(const f of allMp3s){
    const key = f.original || f.name;
    const cur = seen.get(key);
    if(!cur || /_\d+kb\.mp3$|_vbr\.mp3$/i.test(cur.name)) seen.set(key, f);
  }
  return seen.size;
}

async function checkShow(date, { id, venue, city }){
  try {
    const res = await fetch(`https://archive.org/metadata/${id}`);
    if(!res.ok) return { date, id, venue, city, error: `HTTP ${res.status}`, tracks: null };
    const meta = await res.json();
    const tracks = dedupedMp3Count(meta.files || []);
    return { date, id, venue, city, tracks };
  } catch(e) {
    return { date, id, venue, city, error: e.message, tracks: null };
  }
}

async function run(){
  const total = entries.length;
  const flagged = [];
  const errors  = [];
  let done = 0;

  console.log(`Auditing ${total} shows — estimated ${Math.ceil(total * DELAY_MS / 60000)} min...\n`);

  for(const [date, show] of entries){
    const result = await checkShow(date, show);
    done++;

    if(result.error){
      errors.push(result);
      process.stdout.write(`\r[${done}/${total}] ERROR ${date}`);
    } else if(result.tracks < THRESHOLD){
      flagged.push(result);
      process.stdout.write(`\r[${done}/${total}] LOW(${result.tracks}) ${date} — ${result.venue}`);
    } else {
      process.stdout.write(`\r[${done}/${total}] OK(${result.tracks}) ${date}          `);
    }

    await sleep(DELAY_MS);
  }

  const output = { threshold: THRESHOLD, total, flagged, errors };
  writeFileSync('./audit-results.json', JSON.stringify(output, null, 2));

  console.log(`\n\n=== AUDIT COMPLETE ===`);
  console.log(`Total shows checked : ${total}`);
  console.log(`Low track count (<${THRESHOLD}): ${flagged.length}`);
  console.log(`Errors              : ${errors.length}`);
  console.log(`\nFlagged shows:`);
  for(const s of flagged) console.log(`  ${s.date}  ${s.tracks} tracks  ${s.venue}  ${s.id}`);
  console.log(`\nFull results saved to audit-results.json`);
}

run();
