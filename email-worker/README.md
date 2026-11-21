# dialadead.com email (Cloudflare Email Routing + Email Worker)

This handles **inbound** mail: `hello@dialadead.com` and similar addresses get forwarded to your
real inbox. There's no mailbox to host. Cloudflare takes the message and `worker.js` decides
where it goes, or bounces it.

```
sender ──MX──▶ Cloudflare Email Routing ──catch-all──▶ worker.js ──forward──▶ your Gmail
                                                           └──setReject──▶ bounce (unknown address / blocked sender)
```

## 1. Turn on Email Routing (dashboard, about 2 min)
1. Cloudflare dashboard → **dialadead.com** → **Email** → **Email Routing** → **Get started / Enable**.
2. Let it **add the DNS records** it offers. They are three `MX` records
   (`route1/2/3.mx.cloudflare.net`), an SPF `TXT` (`v=spf1 include:_spf.mx.cloudflare.net ~all`)
   and a DKIM `TXT` at `cf2024-1._domainkey`. The domain has no MX records yet, so nothing conflicts.
   The existing `google-site-verification` TXT stays as it is.
3. **Destination addresses** → add your Gmail and click the verification link Cloudflare sends.
   Forwarding to an unverified address fails.

## 2. Deploy the worker
**Option A, dashboard:** Email Routing → **Email Workers** → **Create** → paste `worker.js` → Deploy.
(The dashboard editor accepts the ES-module file as is.)

**Option B, CLI:**
```bash
cd email-worker
npx wrangler login
npx wrangler deploy
```

## 3. Set the variables
Workers & Pages → `dialadead-email` → **Settings → Variables and Secrets**:

| name | example | notes |
|---|---|---|
| `FORWARD_TO` | `you@gmail.com` | **required.** Comma-separate several. Each must be verified (step 1.3). Use type *Secret* so it isn't shown. |
| `ACCEPT` | `hello,info,contact,booking` | Addresses that go to `FORWARD_TO`. Default: `hello,info,contact,admin,postmaster,abuse,webmaster` |
| `ALIASES` | `{"booking":"other@gmail.com"}` | Sends an address somewhere other than `FORWARD_TO`. |
| `CATCH_ALL` | `true` | Accepts *any* address. It's off by default because a catch-all draws spam. |
| `BLOCK` | `@spamdomain.biz,jerk@x.com` | Senders to bounce. |

`hello+anything@` is delivered as `hello@`, which is handy for sign-ups. Addresses aren't kept in
`wrangler.toml` or `worker.js` because Pages serves the repo root publicly (`_redirects` also
redirects `/email-worker/*` away).

## 4. Route mail to the worker
Email Routing → **Routing rules** → **Catch-all address** → Action **Send to a Worker** →
`dialadead-email` → **Enable**. You don't need per-address rules because the worker handles that.

## 5. Add DMARC (recommended)
DNS → add `TXT` `_dmarc` → `v=DMARC1; p=none; rua=mailto:hello@dialadead.com`
Once reports look clean, tighten it to `p=quarantine`.

## 6. Test
Send mail from a *different* account (Gmail hides mail you send to yourself) to `hello@dialadead.com`,
and to a bogus address, which should bounce. Logs: Workers → `dialadead-email` → **Logs**.
Code check: `node email-worker/test.mjs`.

## Replying *as* hello@dialadead.com
Email Routing only receives mail. To send from the domain in Gmail (**Settings → Accounts →
Send mail as**), Gmail needs an SMTP server that is allowed to send for `dialadead.com`. Use any
transactional provider with SMTP and a free tier (Resend, Brevo, SMTP2GO and others), or Cloudflare's own
Email Service where your account has it. Verify the domain with the provider, add the DNS records it
gives you, and **merge its SPF include into the same SPF record**, e.g.
`v=spf1 include:_spf.mx.cloudflare.net include:<provider> ~all`, since a domain may have only one SPF record.
