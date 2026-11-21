// node email-worker/test.mjs — checks routing and forward/reject behaviour with a fake message.
import assert from 'node:assert/strict';
import w,{route} from './worker.js';
const env={FORWARD_TO:'me@example.com, backup@example.com',ALIASES:'{"Booking":"band@example.com"}',BLOCK:'@spam.biz,bad@x.com'};
assert.deepEqual(route('hello@dialadead.com','a@b.com',env),{lp:'hello',dest:['me@example.com','backup@example.com']});
assert.deepEqual(route('Hello+news@DialADead.com','a@b.com',env).lp,'hello');
assert.deepEqual(route('booking@dialadead.com','a@b.com',env).dest,['band@example.com']);
assert.ok(route('random@dialadead.com','a@b.com',env).reject);
assert.equal(route('random@dialadead.com','a@b.com',{...env,CATCH_ALL:'true'}).lp,'random');
assert.ok(route('hello@dialadead.com','x@SPAM.biz',env).reject);
assert.ok(route('hello@dialadead.com','bad@x.com',env).reject);
assert.ok(route('hello@dialadead.com','a@b.com',{}).reject);           // no FORWARD_TO → bounce, don't drop
assert.ok(route('hello@dialadead.com','a@b.com',{...env,ALIASES:'{bad'}).dest); // bad JSON tolerated
const msg=(to,fail=[])=>({to,from:'fan@b.com',fw:[],rej:null,
  async forward(d,h){if(fail.includes(d))throw new Error('unverified '+d);this.fw.push([d,h.get('X-DialADead-Alias')]);},
  setReject(r){this.rej=r;}});
let m=msg('contact@dialadead.com');await w.email(m,env);assert.equal(m.fw.length,2);assert.equal(m.rej,null);
m=msg('contact@dialadead.com',['me@example.com']);await w.email(m,env);assert.equal(m.fw.length,1);assert.equal(m.rej,null);
m=msg('contact@dialadead.com',['me@example.com','backup@example.com']);await w.email(m,env);assert.ok(m.rej);
m=msg('nope@dialadead.com');await w.email(m,env);assert.equal(m.fw.length,0);assert.ok(m.rej);
console.log('ok');
