// Daily X post: today's transfer-fee table from kadena.ws/research/fees/.
// Reads the published fees.json and card.png, uploads the image and posts once a day.
// POST_MODE=dry (default) prints the post and sends nothing.
import crypto from 'node:crypto';
import { oauthHeader } from '../whale-watch/lib/x.mjs';

const SITE = process.env.FEES_SITE || 'https://kadena.ws/research/fees/';
const mode = process.env.POST_MODE === 'live' ? 'live' : 'dry';
const keys = {
  consumerKey: process.env.X_API_KEY, consumerSecret: process.env.X_API_SECRET,
  token: process.env.X_ACCESS_TOKEN, tokenSecret: process.env.X_ACCESS_SECRET,
};

function usd(v) {
  if (v >= 1) return `$${v.toFixed(2)}`;
  const p = Number(v).toPrecision(2);
  if (!p.includes('e')) return `$${p}`;
  const [m, e] = p.split('e');
  return `$${v.toFixed(-Number(e) + Math.max(0, m.replace('.', '').length - 1))}`;
}

const auth = (method, url) => oauthHeader({ method, url, consumerKey: keys.consumerKey, consumerSecret: keys.consumerSecret, token: keys.token, tokenSecret: keys.tokenSecret });

async function main() {
  const data = await (await fetch(SITE + 'fees.json?ts=' + Date.now())).json();
  const updated = new Date(data.updated);
  const ageH = (Date.now() - updated) / 36e5;
  if (ageH > 30) { console.log(`fees.json is ${ageH.toFixed(0)} h old, not posting`); return; }
  const rows = [...data.chains].sort((a, b) => a.native_usd - b.native_usd);
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));
  const k = by.kadena;
  const rank = rows.indexOf(k) + 1;
  const date = updated.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
  const lead = rank === 1 ? `Kadena is the cheapest of ${rows.length} chains today.` : `Kadena is number ${rank} of ${rows.length} today.`;
  const text = [
    `What one simple transfer costs today (${date}):`, '',
    `Kadena ${usd(k.native_usd)}`,
    `Solana ${usd(by.solana.native_usd)}`,
    `Ethereum ${usd(by.ethereum.native_usd)}`,
    `Bitcoin ${usd(by.bitcoin.native_usd)}`, '',
    `${lead} All chains, method and data:`, SITE,
  ].join('\n');

  const img = Buffer.from(await (await fetch(SITE + 'card.png?ts=' + Date.now())).arrayBuffer());
  if (img.length < 10000) throw new Error('card.png missing or too small');

  if (mode === 'dry') { console.log(`[dry post, image ${img.length} bytes]\n${text}`); return; }
  if (!Object.values(keys).every(Boolean)) throw new Error('live mode needs X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET');

  // 1. upload the image (X API v2 media upload; multipart bodies are not part of the OAuth 1.0a signature)
  const upURL = 'https://api.x.com/2/media/upload';
  const form = new FormData();
  form.append('media', new Blob([img], { type: 'image/png' }), 'fees.png');
  form.append('media_category', 'tweet_image');
  const up = await fetch(upURL, { method: 'POST', headers: { authorization: auth('POST', upURL) }, body: form });
  const upBody = await up.json().catch(() => ({}));
  const mediaId = upBody.data?.id || upBody.media_id_string;
  if (!up.ok || !mediaId) throw new Error(`media upload failed: HTTP ${up.status} ${JSON.stringify(upBody).slice(0, 300)}`);

  // 2. post
  const twURL = 'https://api.x.com/2/tweets';
  const tw = await fetch(twURL, {
    method: 'POST',
    headers: { authorization: auth('POST', twURL), 'content-type': 'application/json' },
    body: JSON.stringify({ text, media: { media_ids: [mediaId] } }),
  });
  const twBody = await tw.json().catch(() => ({}));
  if (!tw.ok) throw new Error(`post failed: HTTP ${tw.status} ${JSON.stringify(twBody).slice(0, 300)}`);
  console.log(`posted https://x.com/i/web/status/${twBody.data?.id}`);
}

main().catch((e) => { console.error(e.message); process.exitCode = 1; });
