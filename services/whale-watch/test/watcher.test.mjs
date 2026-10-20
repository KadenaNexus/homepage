// node --test services/whale-watch/test
// Uses real mainnet blocks saved in test/fixtures (no network needed).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseBlock } from '../lib/parse.mjs';
import { hashBase64Url } from '../lib/blake2b.mjs';
import { oauthHeader } from '../lib/x.mjs';
import * as F from '../lib/format.mjs';
import { Watcher, CONFIG } from '../watcher.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const fixture = (n) => JSON.parse(fs.readFileSync(path.join(HERE, 'fixtures', `${n}.json`), 'utf8'));

test('blake2b-256 matches the reference vectors', () => {
  assert.equal(hashBase64Url(''), 'DldRwCblQ7Loqy6wYJnaodHl30d3j3eH-qtFzfEv46g');
  assert.equal(hashBase64Url('abc'), 'vd2BPGNCOXIxce8_7phXm5SWTjuxyz5CcmLIwGjVIxk');
});

test('plain transfer: 999,745.69 KDA on chain 1 (Sep 27)', () => {
  const p = parseBlock(fixture('1-7266334'));
  const big = p.transfers.filter((t) => t.amount > 100000);
  assert.equal(big.length, 1);
  assert.equal(big[0].from, 'k:0d584a4cbbfd9a4878d816512894e65918e54fae13df39a6f520fc90caea2fb0');
  assert.equal(big[0].to.slice(0, 12), 'k:a143f45049');
  assert.equal(big[0].amount, 999745.69);
  assert.equal(big[0].dexTx, false);
});

test('cross-chain move is paired on the source chain with its real receiver', () => {
  const p = parseBlock(fixture('0-7250270'));
  const x = p.transfers.find((t) => t.amount > 1e6);
  assert.equal(x.toChain, 2);
  assert.equal(x.from, x.to); // a wallet moving its own KDA between chains
});

test('liquidity add and remove are DEX items, not wallet moves', () => {
  const add = parseBlock(fixture('2-7250297'));
  assert.equal(add.transfers.find((t) => t.amount > 500000).dexTx, true);
  const lp = add.dexTrades.find((d) => d.liquidity);
  assert.equal(lp.side, 'add');
  assert.equal(F.tokenSymbol(lp.other.token), 'kb-USDC');
  assert.ok(add.pools.has('-qXygkgY9Y_Ld50QdjBng12LIXRqki4EovuF_OJ6DmA'));
  const rem = parseBlock(fixture('2-7314870'));
  const r = rem.dexTrades.find((d) => d.liquidity);
  assert.equal(r.side, 'remove');
  assert.equal(F.tokenSymbol(r.other.token), 'BRO');
  assert.ok(Math.abs(r.kda - 501772.19) < 0.01);
});

test('gas payments are not counted as transfers', () => {
  const p = parseBlock(fixture('2-7266285'));
  assert.ok(p.transfers.every((t) => t.to !== p.miner || t.amount >= 1));
});

function tmpWatcher(extra = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ww-'));
  const posts = [];
  const poster = { post: async (text, meta) => { posts.push({ text, meta }); return { ok: true, id: String(posts.length) }; } };
  const w = new Watcher({ ...CONFIG, dataDir: path.join(dir, 'd'), publicDir: path.join(dir, 'p'), labelsFile: path.join(dir, 'labels.json'), ...extra }, {
    poster, chainweb: {}, indexer: {}, now: () => Date.parse('2026-09-27T18:00:00Z'),
  });
  return { w, posts, dir };
}

test('watcher: posts the 999,746 move once, with the exchange label, under 280 characters', async () => {
  const { w, posts, dir } = tmpWatcher();
  fs.writeFileSync(path.join(dir, 'labels.json'), JSON.stringify({ accounts: { 'k:0d584a4cbbfd9a4878d816512894e65918e54fae13df39a6f520fc90caea2fb0': { name: 'Example Exchange', type: 'exchange' } } }));
  w.loadLabels();
  w.state.price = 0.0108;
  w.processBlock(fixture('1-7266334'));
  w.processBlock(fixture('1-7266334')); // the same block twice must not duplicate
  assert.equal(w.feed.length, 1);
  await w.postFresh();
  assert.equal(posts.length, 1);
  const t = posts[0].text;
  assert.match(t, /999,746 \$KDA \(~\$10,797\) withdrawn from Example Exchange/);
  assert.match(t, /^🐋🐋 /m);
  assert.match(t, /To: unknown wallet k:a143…/);
  assert.doesNotMatch(t, /https?:|\.ws|\.com/); // no links: plain posts cost $0.015, link posts $0.20
  assert.ok(F.weightedLength(t) <= 280);
  // exchange outflow counted
  const day = w.state.days['2026-09-27'];
  assert.ok(day.flowOut > 999000);
  await w.postFresh();
  assert.equal(posts.length, 1);
});

test('watcher: self cross-chain move and DEX liquidity are not posted as moves', async () => {
  const { w, posts } = tmpWatcher({ postMin: 1e12 });
  w.processBlock(fixture('0-7250270'));
  w.processBlock(fixture('2-7250297'));
  assert.equal(w.feed.filter((f) => f.type === 'move').length, 0);
  assert.equal(w.feed.filter((f) => f.type === 'liquidity').length, 1);
  await w.postFresh();
  assert.equal(posts.length, 0);
});

test('watcher: daily alert cap holds back extra alerts and counts them', async () => {
  const { w, posts } = tmpWatcher({ maxAlertsPerDay: 1 });
  w.processBlock(fixture('1-7266334'));
  w.processBlock(fixture('2-7266285'));
  await w.postFresh();
  assert.equal(posts.length, 1);
  assert.equal(w.day(w.now()).notPosted, 1);
});

test('watcher: old items are never posted (no posting history after downtime)', async () => {
  const { w, posts } = tmpWatcher();
  w.now = () => Date.parse('2026-10-20T08:00:00Z');
  w.processBlock(fixture('1-7266334'));
  await w.postFresh();
  assert.equal(posts.length, 0);
});

test('watcher: relay hop with the same amount is merged into the first alert', async () => {
  const { w, posts } = tmpWatcher();
  w.processBlock(fixture('1-7266334'));
  // synthesize the next hop: receiver passes the same amount on
  const first = w.feed[0];
  w.addItem({ type: 'move', id: 'hop2', time: first.time + 60000, chain: 1, toChain: 1, requestKey: 'abcdefghij', amount: first.amount, from: first.to, to: 'k:' + 'e'.repeat(64), relayOf: first.id });
  await w.postFresh();
  assert.equal(posts.length, 1);
});

test('formats: tiers, dormant line, DEX and platform posts stay short', () => {
  const labelOf = () => null;
  const ctx = { labelOf, price: 0.0107, thresholds: { big: 500000, huge: 1000000 } };
  const base = { chain: 1, toChain: 1, requestKey: 'vWiX6xDWQ7EMcM0YbgKRO1tBXEDRVnNneJkfUXkQ20g', from: 'k:' + 'a'.repeat(64), to: 'k:' + 'b'.repeat(64) };
  assert.match(F.movePost({ ...base, amount: 150000 }, ctx), /^🐋 150,000/);
  assert.match(F.movePost({ ...base, amount: 2500000 }, ctx), /^🚨🐋🐋🐋 2,500,000/);
  const dormant = F.movePost({ ...base, amount: 150000, dormantDays: 900 }, ctx);
  assert.match(dormant, /idle for 2\.5 years/);
  const dex = F.dexPost({ chain: 2, requestKey: base.requestKey, kda: 180000, side: 'sell', other: { token: 'n_e595727b657fbbb3b8e362a05a7bb8d12865c1ff.kb-USDC', amount: 1925.4 }, trader: base.from, dex: 'Mercatus' }, ctx);
  assert.match(dex, /180,000 \$KDA \(~\$1,926\) sold for 1,925 kb-USDC on Mercatus/);
  const ps = F.platformPost({ kind: 'release', account: 'PS_C5_001', amount: 400000, chain: 5, requestKey: base.requestKey, remaining: 86944000 }, ctx);
  assert.match(ps, /3 of the 5 community keys/);
  for (const t of [dormant, dex, ps]) assert.ok(F.weightedLength(t) <= 280, t);
  const daily = F.dailyPost({ day: '2026-10-20', moves: 3, largest: 456638, dex: 1, flowIn: 820000, flowOut: 1100000, platform: 87344000, platformDays: 377, notPosted: 0 });
  assert.match(daily, /Exchange flow: 820K in · 1\.1M out/);
  assert.match(daily, /87\.3M KDA, unmoved for 377 days/);
  const weekly = F.weeklyPost({ from: '2026-10-14', to: '2026-10-20', moves: 9, largest: 999746, conc: { w1m: 43, w100k: 404, top10: 131009517 }, prev: { w1m: 42, w100k: 407 }, flowIn: 1e6, flowOut: 2.2e6 });
  assert.match(weekly, /1M\+ KDA: 43 \(\+1\)/);
  assert.match(weekly, /100K\+ KDA: 404 \(−3\)/);
  assert.match(weekly, /net flow: 1\.2M out/);
});

test('oauth header has the required fields and a stable signature', () => {
  const h = oauthHeader({ method: 'POST', url: 'https://api.x.com/2/tweets', consumerKey: 'ck', consumerSecret: 'cs', token: 'tk', tokenSecret: 'ts', nonce: 'n1', timestamp: 1700000000 });
  assert.match(h, /^OAuth oauth_consumer_key="ck", oauth_nonce="n1", oauth_signature="[^"]+", oauth_signature_method="HMAC-SHA1", oauth_timestamp="1700000000", oauth_token="tk", oauth_version="1.0"$/);
  // independently computed with Python hmac/hashlib for the same inputs
  assert.match(h, /oauth_signature="IkqzcoSodURYDr0EVrc6NxWWJfI%3D"/);
});
