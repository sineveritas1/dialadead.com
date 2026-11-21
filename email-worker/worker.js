// DIAL·A·DEAD inbound mail — Cloudflare Email Worker.
// Email Routing hands every message for *@dialadead.com to email() below
// (catch-all → this worker). No addresses live in this file: the repo root is
// served publicly by Pages, so destinations come from dashboard variables.
//
//   FORWARD_TO  required  default destination(s), comma-separated. Each must be
//                         a VERIFIED destination address in Email Routing.
//   ALIASES     optional  JSON {"local-part": "dest[,dest]"} for per-address routing,
//                         e.g. {"booking":"me@example.com"}. Local parts not listed fall
//                         to FORWARD_TO when CATCH_ALL is "true", else bounce.
//   ACCEPT      optional  extra local parts accepted (→ FORWARD_TO) when CATCH_ALL is off.
//                         Default: hello,info,contact,admin,postmaster,abuse,webmaster
//   CATCH_ALL   optional  "true" to accept any local part. Default "false".
//   BLOCK       optional  comma-separated senders to bounce: "spam@x.com" or "@x.com".
const DEF_ACCEPT='hello,info,contact,admin,postmaster,abuse,webmaster';
const list=s=>(s||'').split(',').map(x=>x.trim().toLowerCase()).filter(Boolean);
const json=s=>{try{return s?JSON.parse(s):{}}catch(e){console.log('ALIASES is not valid JSON');return {}}};

export function route(to,from,env){
  const [lp0,dom]=to.toLowerCase().split('@'), lp=lp0.split('+')[0]; // hello+x@ → hello@
  const f=from.toLowerCase(), fd='@'+f.split('@')[1];
  if(list(env.BLOCK).some(b=>b===f||b===fd)) return {reject:'Message rejected.'};
  const al=Object.fromEntries(Object.entries(json(env.ALIASES)).map(([k,v])=>[k.toLowerCase(),v]));
  if(al[lp]) return {lp,dest:list(al[lp])};
  const ok=env.CATCH_ALL==='true'||list(env.ACCEPT||DEF_ACCEPT).includes(lp);
  if(!ok) return {reject:`No such address: ${lp}@${dom}`};
  const dest=list(env.FORWARD_TO);
  return dest.length?{lp,dest}:{reject:'Mailbox temporarily unavailable.'};
}

export default {
  async email(message,env){
    const r=route(message.to,message.from,env);
    if(r.reject){console.log('reject',message.from,'->',message.to,r.reject);return message.setReject(r.reject);}
    const h=new Headers({'X-DialADead-Alias':r.lp});
    // Forward to every destination; one failing (e.g. unverified) must not drop the rest.
    const res=await Promise.allSettled(r.dest.map(d=>message.forward(d,h)));
    const bad=res.filter(x=>x.status==='rejected');
    bad.forEach(x=>console.log('forward failed:',x.reason&&x.reason.message));
    if(bad.length===res.length) message.setReject('Mailbox temporarily unavailable.');
  }
};
