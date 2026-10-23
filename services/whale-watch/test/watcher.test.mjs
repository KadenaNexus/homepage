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
  assert.match(t, /\nhttps:\/\/denascan\.com\/transactions\/[A-Za-z0-9_-]{43}$/); // alerts end with the DenaScan tx link
  assert.equal((t.match(/https?:/g) || []).length, 1);
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
  assert.match(daily, /Exchanges: 820K KDA deposited · 1\.1M KDA withdrawn/);
  assert.match(daily, /87\.3M KDA, unmoved for 377 days/);
  assert.doesNotMatch(daily, /https?:/); // summaries stay link-free ($0.015)
  const weekly = F.weeklyPost({ from: '2026-10-14', to: '2026-10-20', moves: 9, largest: 999746, conc: { w1m: 43, w100k: 404, top10: 131009517 }, prev: { w1m: 42, w100k: 407 }, flowIn: 1e6, flowOut: 2.2e6 });
  assert.match(weekly, /1M\+ KDA: 43 \(\+1\)/);
  assert.match(weekly, /100K\+ KDA: 404 \(−3\)/);
  assert.match(weekly, /Exchanges: 1\.2M more KDA withdrawn than deposited/);
  // with a per-exchange breakdown the summaries name the exchanges
  const ex = [
    { display: 'Gate', in: 15000, out: 80000 },
    { display: 'Binance', in: 7000, out: 0 },
    { display: 'Bybit (likely)', in: 0, out: 400 },
    { display: 'KuCoin', in: 38, out: 0 },
  ];
  const named = F.dailyPost({ day: '2026-10-21', moves: 0, flowIn: 22038, flowOut: 80400, exchanges: ex, platform: 87344000, platformDays: 377 });
  assert.match(named, /Exchanges:\nGate: 15K KDA deposited · 80K withdrawn\nBinance: 7K KDA deposited\nBybit \(likely\): 400 KDA withdrawn\n\+ 1 more exchange/);
  assert.ok(F.weightedLength(named) <= 280, named);
  const busy = F.dailyPost({ day: '2026-10-21', moves: 4, largest: 1234567, dex: 2, notPosted: 3, flowIn: 1e6, flowOut: 1e6,
    exchanges: ['Binance.US (likely)', 'Coinmetro (likely)', 'TradeOgre (likely)', 'KuCoin (likely)'].map((display) => ({ display, in: 123456, out: 654321 })), platform: 87344000, platformDays: 377 });
  assert.ok(F.weightedLength(busy) <= 280, busy);
  assert.match(F.weeklyPost({ from: '2026-10-14', to: '2026-10-20', moves: 0, flowIn: 1, flowOut: 2, exchanges: ex }), /Busiest: Gate, Binance, Bybit \(likely\)/);
});

test('oauth header has the required fields and a stable signature', () => {
  const h = oauthHeader({ method: 'POST', url: 'https://api.x.com/2/tweets', consumerKey: 'ck', consumerSecret: 'cs', token: 'tk', tokenSecret: 'ts', nonce: 'n1', timestamp: 1700000000 });
  assert.match(h, /^OAuth oauth_consumer_key="ck", oauth_nonce="n1", oauth_signature="[^"]+", oauth_signature_method="HMAC-SHA1", oauth_timestamp="1700000000", oauth_token="tk", oauth_version="1.0"$/);
  // independently computed with Python hmac/hashlib for the same inputs
  assert.match(h, /oauth_signature="IkqzcoSodURYDr0EVrc6NxWWJfI%3D"/);
});

test('likely labels say so, exchange-to-exchange moves name both, sweeps inside one exchange are not posted', async () => {
  const { w, posts, dir } = tmpWatcher();
  const A = 'k:0d584a4cbbfd9a4878d816512894e65918e54fae13df39a6f520fc90caea2fb0';
  const B = 'k:a143f4504985' + '0'.repeat(52);
  fs.writeFileSync(path.join(dir, 'labels.json'), JSON.stringify({ accounts: {
    [A]: { name: 'Gate', type: 'exchange', confidence: 'confirmed', source: 'x' },
    'k:a143f45049850d6ae3a5e0d3dd02c0ea9b9a1f6b58c8bd29a8e8aa9cdb8d6f43': { name: 'CoinEx', type: 'exchange', confidence: 'likely', source: 'x' },
  } }));
  w.loadLabels();
  w.processBlock(fixture('1-7266334'));
  const item = w.feed[0];
  assert.equal(item.fromLabel, 'Gate');
  // pretend the receiver is the likely-CoinEx wallet
  item.to = 'k:a143f45049850d6ae3a5e0d3dd02c0ea9b9a1f6b58c8bd29a8e8aa9cdb8d6f43';
  const text = F.movePost(item, { labelOf: w.labelOf, price: 0.0108, thresholds: { big: 5e5, huge: 1e6 } });
  assert.match(text, /moved from Gate to CoinEx \(likely\)/);
  // a sweep between two wallets of the same exchange: kept on the page, never posted, not counted
  w.addItem({ type: 'move', id: 'sweep', time: item.time + 1000, chain: 1, toChain: 0, requestKey: 'sweepsweep', amount: 300000, from: B, to: A, internal: true });
  await w.postFresh();
  assert.equal(posts.length, 1);
  assert.equal(w.state.posted.sweep, 'internal');
  assert.equal(w.day(item.time).moves, 1);
  assert.deepEqual(w.publish() ?? null, null);
  const stats = JSON.parse(fs.readFileSync(path.join(w.cfg.publicDir, 'stats.json'), 'utf8'));
  assert.ok(stats.labelledExchanges.includes('CoinEx (likely)') && stats.labelledExchanges.includes('Gate'));
});

test('nothing is posted when the state cannot be stored first (no double posts)', async () => {
  const { w, posts, dir } = tmpWatcher({ checkpointCmd: 'exit 3' });
  w.processBlock(fixture('1-7266334'));
  await assert.rejects(() => w.postFresh());
  assert.equal(posts.length, 0);
  const ok = tmpWatcher({ checkpointCmd: `touch ${JSON.stringify(path.join(dir, 'synced'))}` });
  ok.w.processBlock(fixture('1-7266334'));
  await ok.w.postFresh();
  assert.equal(ok.posts.length, 1);
  assert.ok(fs.existsSync(path.join(dir, 'synced')));
});

test('label changes reach items already in the feed', () => {
  const { w, dir } = tmpWatcher();
  w.processBlock(fixture('1-7266334'));
  assert.equal(w.feed[0].fromLabel, null);
  fs.writeFileSync(path.join(dir, 'labels.json'), JSON.stringify({ accounts: { 'k:0d584a4cbbfd9a4878d816512894e65918e54fae13df39a6f520fc90caea2fb0': { name: 'Gate', type: 'exchange', confidence: 'confirmed', source: 'x' } } }));
  w.loadLabels();
  w.publish();
  const feed = JSON.parse(fs.readFileSync(path.join(w.cfg.publicDir, 'feed.json'), 'utf8'));
  assert.equal(feed.items[0].fromLabel, 'Gate');
});

test('names carry delisted / closed and likely tags', () => {
  assert.equal(F.displayName({ name: 'Binance', status: 'delisted', confidence: 'likely' }), 'Binance (delisted, likely)');
  assert.equal(F.displayName({ name: 'Gate', confidence: 'confirmed' }), 'Gate');
  assert.equal(F.displayName({ name: 'TradeOgre', status: 'closed', confidence: 'confirmed' }), 'TradeOgre (closed)');
  const labels = JSON.parse(fs.readFileSync(new URL('../labels.json', import.meta.url), 'utf8')).accounts;
  const ex = Object.values(labels).filter((l) => l.type === 'exchange');
  assert.deepEqual([...new Set(ex.filter((l) => l.confidence === 'confirmed').map((l) => l.name))], ['Gate']);
  for (const n of ['Binance', 'Binance.US', 'KuCoin', 'OKX', 'MEXC', 'Bybit', 'Coinmetro']) assert.ok(ex.filter((l) => l.name === n).every((l) => l.status === 'delisted'), n);
  for (const n of ['CoinEx', 'TradeOgre']) assert.ok(ex.filter((l) => l.name === n).every((l) => l.status === 'closed'), n);
});

test('watcher: DEX and pool alerts post with the real KDA amount and one cashtag', async () => {
  const { w, posts } = tmpWatcher();
  w.processBlock(fixture('2-7314870')); // 501,772 KDA taken out of the Mercatus KDA/BRO pool
  const lp = w.feed.find((f) => f.type === 'liquidity');
  assert.ok(lp, 'liquidity item');
  w.now = () => lp.time + 60000;
  w.fresh = [...w.feed];
  // a DEX sale stored the way the watcher stores it (amount, not kda)
  w.addItem({ type: 'dex', id: 'sale1', time: lp.time, chain: 2, height: 1, requestKey: 'pNCPDjedezU3_wwfpw2fwZHUY3tnAnAAAAAAAAAAAAA', amount: 475868, side: 'sell', other: { token: 'n_e595727b657fbbb3b8e362a05a7bb8d12865c1ff.kb-USDC', amount: 3307.39 }, trader: 'k:' + 'c'.repeat(64), dex: 'Mercatus' });
  await w.postFresh();
  const texts = posts.map((p) => p.text);
  const pool = texts.find((t) => /pool/.test(t)), sale = texts.find((t) => /sold for/.test(t));
  assert.match(pool, /501,772 \$KDA .*taken out of the Mercatus KDA\/BRO pool \(liquidity removed\)/);
  assert.match(sale, /^💱 475,868 \$KDA( \(~\$[\d,]+\))? sold for 3,307 kb-USDC on Mercatus/);
  for (const t of texts) assert.equal(F.postProblem(t), null, t);
});

test('postProblem catches what X rejects', () => {
  assert.equal(F.postProblem('💱 NaN $KDA (~$NaN) sold'), 'broken value in text');
  assert.equal(F.postProblem('$KDA and $BRO'), 'more than one cashtag');
  assert.equal(F.postProblem('🐋 100,000 $KDA (~$1,060) moved'), null);
});
