#!/usr/bin/env node
// Kadena Whale Watch: reads every block on all 20 Kadena chains, finds large KDA
// moves, DEX trades, platform-share movements and exchange flows, writes the
// data for kadena.ws/whales, and posts alerts plus a daily summary to X.
//
//   node watcher.mjs                 run forever (systemd)
//   node watcher.mjs --once          catch up once and exit
//   node watcher.mjs --backfill-hours 6 --once   start 6 hours back (testing)
//
// Configuration comes from the environment; see README.md.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { Chainweb, num } from './lib/chainweb.mjs';
import { parseBlock, isPlatformShare } from './lib/parse.mjs';
import { Indexer } from './lib/indexer.mjs';
import { XPoster } from './lib/x.mjs';
import * as F from './lib/format.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const env = process.env;
const argv = process.argv.slice(2);
const arg = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };

export const CONFIG = {
  nodes: (env.NODE_URLS || 'https://api.chainweb-community.org').split(',').map((s) => s.trim()).filter(Boolean),
  indexer: env.INDEXER_URL || 'https://graphql.chaddex.com/graphql',
  dataDir: env.DATA_DIR || path.join(HERE, 'data'),
  publicDir: env.PUBLIC_DIR || path.join(HERE, 'public-data'),
  labelsFile: env.LABELS_FILE || path.join(HERE, 'labels.json'),
  moveMin: Number(env.MOVE_MIN || 100000),
  postMin: Number(env.POST_MIN || 100000),
  big: Number(env.BIG_MIN || 500000),
  huge: Number(env.HUGE_MIN || 1000000),
  whaleLine: Number(env.WHALE_LINE || 1000000),
  dormantDays: Number(env.DORMANT_DAYS || 365),
  confirmations: Number(env.CONFIRMATIONS || 6),
  pollSeconds: Number(env.POLL_SECONDS || 30),
  maxBlocksPerLoop: Number(env.MAX_BLOCKS_PER_LOOP || 300),
  postMode: env.POST_MODE || 'dry',
  // Optional shell command run after every save that must succeed before anything is posted
  // (GitHub Actions uses it to copy state to the server first, so a failed run never double-posts).
  checkpointCmd: env.CHECKPOINT_CMD || '',
  maxAlertsPerDay: Number(env.MAX_ALERTS_PER_DAY || 6),
  freshMinutes: Number(env.FRESH_MINUTES || 180),
  summaryHour: Number(env.SUMMARY_HOUR || 21), // local time (Riyadh)
  weeklyDay: Number(env.WEEKLY_DAY || 5), // 0 Sunday … 5 Friday
  tzOffsetHours: Number(env.TZ_OFFSET_HOURS || 3), // Riyadh, no daylight saving
  platformLastMove: env.PLATFORM_LAST_MOVE || '2025-10-09T00:00:00Z',
  feedDays: Number(env.FEED_DAYS || 90),
  priceModule: env.PRICE_PAIR || 'n_e595727b657fbbb3b8e362a05a7bb8d12865c1ff.kb-USDC',
};

const log = (...a) => console.log(new Date().toISOString(), ...a);

// ---------- storage ----------
function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return fallback; }
}
function writeJson(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(data));
  fs.renameSync(tmp, file);
}

export function newState() {
  return {
    version: 1, heights: {}, pools: [], price: null, priceAt: 0,
    platform: { total: null, perChain: {}, checkedAt: 0, lastMoveAt: null },
    days: {}, hours: {}, conc: {}, posted: {}, alertsByDay: {},
    lastDaily: '', lastWeekly: '', lastConcDay: '',
  };
}

// ---------- the watcher ----------
export class Watcher {
  constructor(cfg, deps = {}) {
    this.cfg = cfg;
    fs.mkdirSync(cfg.dataDir, { recursive: true });
    this.stateFile = path.join(cfg.dataDir, 'state.json');
    this.feedFile = path.join(cfg.dataDir, 'feed.json');
    this.state = { ...newState(), ...readJson(this.stateFile, {}) };
    if (!this.state.platform.lastMoveAt) this.state.platform.lastMoveAt = cfg.platformLastMove;
    this.feed = readJson(this.feedFile, []);
    this.pools = new Set(this.state.pools);
    this.loadLabels();
    this.cw = deps.chainweb || new Chainweb(cfg.nodes, { log });
    this.ix = deps.indexer || new Indexer(cfg.indexer);
    this.x = deps.poster || new XPoster({
      mode: cfg.postMode, dataDir: cfg.dataDir, log,
      keys: { consumerKey: env.X_API_KEY, consumerSecret: env.X_API_SECRET, token: env.X_ACCESS_TOKEN, tokenSecret: env.X_ACCESS_SECRET },
    });
    this.now = deps.now || (() => Date.now());
    this.fresh = [];
  }

  loadLabels() {
    const raw = readJson(this.cfg.labelsFile, { accounts: {} });
    this.labels = raw.accounts || {};
    if (this.pools) for (const [a, l] of Object.entries(this.labels)) if (l.type === 'dex') this.pools.add(a);
    this.labelsMtime = fs.existsSync(this.cfg.labelsFile) ? fs.statSync(this.cfg.labelsFile).mtimeMs : 0;
  }

  labelOf = (a) => {
    if (!a) return null;
    if (this.labels[a]) return this.labels[a];
    if (this.pools.has(a)) return { name: 'a DEX pool', type: 'dex' };
    if (isPlatformShare(a)) return { name: `platform share ${a}`, type: 'platform' };
    return null;
  };

  // An exchange counts as confirmed when any of its wallets is confirmed; it shows
  // "delisted" or "closed" when its labels say it no longer trades KDA.
  exchangeStatus(name) {
    return Object.values(this.labels).find((l) => l.type === 'exchange' && l.name === name && l.status)?.status || null;
  }

  exchangeDisplay(name) {
    const ls = Object.values(this.labels).filter((l) => l.type === 'exchange' && l.name === name);
    return F.nameWithTags(name, ls.find((l) => l.status)?.status, !ls.some((l) => l.confidence !== 'likely'));
  }

  localDay(ms) { return new Date(ms + this.cfg.tzOffsetHours * 3600e3).toISOString().slice(0, 10); }
  hourKey(ms) { return new Date(ms).toISOString().slice(0, 13); }
  day(ms) {
    const k = this.localDay(ms);
    return (this.state.days[k] ||= { moves: 0, largest: 0, dex: 0, flowIn: 0, flowOut: 0, flows: {} });
  }

  // ---- block processing ----
  processBlock(block) {
    const p = parseBlock(block);
    for (const a of p.pools) this.pools.add(a);
    const t = this.cfg.moveMin;
    for (const tr of p.transfers) {
      if (!this.seeding) this.countFlow(tr); // a seed reads only selected blocks, so flows would be partial
      if (tr.dexTx || tr.amount < t) continue;
      if (tr.from === tr.to) continue; // same wallet moving between its own chains
      if (this.pools.has(tr.from) || this.pools.has(tr.to)) continue; // handled as a DEX item
      const fl = this.labelOf(tr.from), tl = this.labelOf(tr.to);
      const internal = fl?.type === 'exchange' && tl?.type === 'exchange' && fl.name === tl.name; // e.g. a deposit sweep
      const item = { type: 'move', id: tr.id, time: tr.time, chain: tr.chain, toChain: tr.toChain, height: tr.height, requestKey: tr.requestKey, amount: tr.amount, from: tr.from, to: tr.to };
      // A relay hop: the same amount passed straight on from the wallet that just received it.
      const prev = this.feed.find((f) => f.type === 'move' && f.to === tr.from && Math.abs(f.amount - tr.amount) <= f.amount * 0.005 && tr.time - f.time >= 0 && tr.time - f.time < 12 * 3600e3);
      if (internal) item.internal = true;
      if (prev) { item.relayOf = prev.id; item.via = tr.from; item.origin = prev.relayOf ? prev.origin : prev.from; if (tr.to === prev.from) item.returned = true; }
      this.addItem(item);
    }
    for (const d of p.dexTrades) {
      if (d.kda < t) continue;
      this.addItem({ type: d.liquidity ? 'liquidity' : 'dex', id: d.id, time: d.time, chain: d.chain, height: d.height, requestKey: d.requestKey, amount: d.kda, side: d.side, other: d.other, trader: d.trader, dex: d.dex, hops: d.hops });
    }
    for (const e of p.platform) {
      this.addItem({ type: 'platform', id: `${e.requestKey}:${e.chain}:ps:${e.account}`, time: e.time, chain: e.chain, height: e.height, requestKey: e.requestKey, amount: e.amount, kind: e.kind, account: e.account, to: e.to });
      this.state.platform.lastMoveAt = new Date(e.time).toISOString();
    }
    return p;
  }

  countFlow(tr) {
    const fl = this.labelOf(tr.from), tl = this.labelOf(tr.to);
    const fx = fl?.type === 'exchange' ? fl.name : null;
    const tx = tl?.type === 'exchange' ? tl.name : null;
    if (!fx && !tx) return;
    if (fx && tx && fx === tx) return; // internal shuffle
    const d = this.day(tr.time);
    const h = (this.state.hours[this.hourKey(tr.time)] ||= { in: 0, out: 0, ex: {} });
    h.ex ||= {}; // hours recorded before per-exchange counts existed have none
    if (tx) { d.flowIn += tr.amount; h.in += tr.amount; (d.flows[tx] ||= { in: 0, out: 0 }).in += tr.amount; (h.ex[tx] ||= { in: 0, out: 0 }).in += tr.amount; }
    if (fx) { d.flowOut += tr.amount; h.out += tr.amount; (d.flows[fx] ||= { in: 0, out: 0 }).out += tr.amount; (h.ex[fx] ||= { in: 0, out: 0 }).out += tr.amount; }
  }

  addItem(item) {
    if (this.feed.some((f) => f.id === item.id)) return;
    item.usd = this.state.price ? Math.round(item.amount * this.state.price) : null;
    if (item.from) item.fromLabel = F.displayName(this.labelOf(item.from));
    if (item.to) item.toLabel = F.displayName(this.labelOf(item.to));
    if (item.trader) item.traderLabel = F.displayName(this.labelOf(item.trader));
    const d = this.day(item.time);
    if (item.type === 'move' && !item.relayOf && !item.internal) { d.moves++; d.largest = Math.max(d.largest, item.amount); }
    if (item.type === 'dex' || item.type === 'liquidity') d.dex++;
    this.feed.unshift(item);
    this.fresh.push(item);
  }

  async catchUp() {
    const cut = await this.cw.cut();
    const chains = Object.keys(cut).map(Number).sort((a, b) => a - b);
    let processed = 0;
    const work = chains.map((c) => async () => {
      const target = Math.min(cut[c].height - this.cfg.confirmations, this.cfg.stopHeight ?? Infinity);
      let from = this.state.heights[c] != null ? this.state.heights[c] + 1 : target;
      const until = Math.min(target, from + this.cfg.maxBlocksPerLoop - 1);
      while (from <= until) {
        const to = Math.min(until, from + 99);
        const blocks = await this.cw.blocks(c, from, to, cut[c].hash);
        for (const b of blocks) { this.processBlock(b); processed++; }
        this.state.heights[c] = to;
        from = to + 1;
      }
    });
    await runLimited(work, 5, (e) => log('chain error:', e.message));
    this.state.lagBlocks = Math.max(...chains.map((c) => cut[c].height - (this.state.heights[c] ?? cut[c].height)));
    this.state.cutHeight = Math.max(...chains.map((c) => cut[c].height));
    return processed;
  }

  // ---- enrichment of fresh items ----
  isFresh(item) { return item.time >= this.now() - this.cfg.freshMinutes * 60e3; }

  async enrich(item) {
    if (item.type !== 'move' || !this.isFresh(item)) return;
    const fromL = this.labelOf(item.from);
    if (!fromL) {
      try {
        const last = await this.ix.lastActivityBefore(item.from, item.time, item.requestKey);
        if (last) {
          const days = Math.floor((item.time - last) / 86400e3);
          if (days >= this.cfg.dormantDays) { item.dormantDays = days; item.lastActive = last; }
        }
      } catch (e) { log('dormant check skipped:', e.message); }
    }
    if (!this.labelOf(item.to)) {
      try {
        const bal = await this.totalBalance(item.to);
        if (bal >= this.cfg.whaleLine && bal - item.amount < this.cfg.whaleLine) item.newWhale = bal;
      } catch (e) { log('balance check skipped:', e.message); }
    }
  }

  async totalBalance(account) {
    const q = `(try 0.0 (coin.get-balance ${JSON.stringify(account)}))`;
    const vals = await Promise.all(Array.from({ length: 20 }, (_, c) => this.cw.local(c, q).then(num)));
    return vals.reduce((a, b) => a + b, 0);
  }

  // ---- posting ----
  async postFresh() {
    const t = { big: this.cfg.big, huge: this.cfg.huge };
    const ctx = { labelOf: this.labelOf, price: this.state.price, thresholds: t };
    // oldest first so a burst posts in chain order
    for (const item of this.fresh.sort((a, b) => a.time - b.time)) {
      if (this.state.posted[item.id] || !this.isFresh(item)) continue;
      const platform = item.type === 'platform';
      if (!platform && item.amount < this.cfg.postMin) continue;
      if (item.relayOf) { this.state.posted[item.id] = 'relay'; continue; } // the first hop was the alert
      if (item.internal) { this.state.posted[item.id] = 'internal'; continue; } // an exchange moving its own KDA
      const dayKey = this.localDay(this.now());
      const sent = this.state.alertsByDay[dayKey] || 0;
      if (!platform && sent >= this.cfg.maxAlertsPerDay) { this.day(this.now()).notPosted = (this.day(this.now()).notPosted || 0) + 1; this.state.posted[item.id] = 'capped'; continue; }
      const text = item.type === 'move' ? F.movePost(item, ctx)
        : platform ? F.platformPost({ ...item, remaining: this.state.platform.total }, ctx)
          : F.dexPost(item, ctx);
      const problem = F.postProblem(text);
      if (problem) { this.state.posted[item.id] = 'bad-text'; log(`not posted (${problem}):`, text); continue; } // X would reject it, or a number is broken
      this.state.posted[item.id] = 'pending';
      this.checkpoint(); // throws if the state could not be stored: then nothing is posted
      const r = await this.x.post(text, { kind: item.type, item: item.id });
      this.state.posted[item.id] = r.ok ? (r.id || 'dry') : 'failed';
      item.posted = r.ok;
      if (r.ok && !platform) this.state.alertsByDay[dayKey] = sent + 1;
      if (!r.ok) log('post failed:', r.error);
    }
    this.fresh = [];
  }

  // ---- periodic tasks ----
  async refreshPrice() {
    if (this.now() - this.state.priceAt < 10 * 60e3) return;
    try {
      const pair = await this.cw.local(2, `(kaddex.exchange.get-pair coin ${this.cfg.priceModule})`);
      const kda = num(pair.leg0.reserve), usdc = num(pair.leg1.reserve);
      if (kda > 0 && usdc > 0) { this.state.price = usdc / kda; this.state.priceAt = this.now(); }
    } catch (e) { log('price skipped:', e.message); }
  }

  async checkPlatformShare() {
    if (this.now() - this.state.platform.checkedAt < 60 * 60e3) return;
    const code = `(fold (+) 0.0 (map (lambda (k) (let ((r (read coin.allocation-table k))) (if (at 'redeemed r) 0.0 (at 'balance r)))) (filter (lambda (k) (= "PS_" (take 3 k))) (keys coin.allocation-table))))`;
    try {
      const per = {};
      for (let c = 0; c < 10; c++) per[c] = num(await this.cw.local(c, code));
      const total = Object.values(per).reduce((a, b) => a + b, 0);
      const prev = this.state.platform.total;
      if (prev != null && total < prev - 1e-6) {
        for (let c = 0; c < 10; c++) {
          const drop = (this.state.platform.perChain[c] ?? per[c]) - per[c];
          if (drop > 1e-6 && !this.feed.some((f) => f.type === 'platform' && f.chain === c && this.now() - f.time < 2 * 3600e3)) {
            this.addItem({ type: 'platform', id: `ps-drop:${c}:${this.now()}`, time: this.now(), chain: c, amount: drop, kind: 'drop' });
          }
        }
        this.state.platform.lastMoveAt = new Date(this.now()).toISOString();
      }
      Object.assign(this.state.platform, { total, perChain: per, checkedAt: this.now() });
    } catch (e) { log('platform check skipped:', e.message); }
  }

  async snapshotConcentration() {
    const day = new Date(this.now()).toISOString().slice(0, 10); // UTC day
    if (this.state.lastConcDay === day) return;
    try {
      const holders = await this.ix.holdersAbove(100000);
      const bal = holders.map((h) => h.balance);
      this.state.conc[day] = {
        w100k: bal.length,
        w1m: bal.filter((b) => b >= 1e6).length,
        w10m: bal.filter((b) => b >= 1e7).length,
        top10: Math.round(bal.slice(0, 10).reduce((a, b) => a + b, 0)),
        top100: Math.round(bal.slice(0, 100).reduce((a, b) => a + b, 0)),
      };
      this.state.lastConcDay = day;
    } catch (e) { log('concentration skipped:', e.message); }
  }

  windowStats(hours) {
    const since = this.now() - hours * 3600e3;
    const items = this.feed.filter((f) => f.time >= since);
    const moves = items.filter((f) => f.type === 'move' && !f.relayOf && !f.internal);
    let flowIn = 0, flowOut = 0, complete = true;
    const byEx = {};
    for (const [k, v] of Object.entries(this.state.hours)) {
      if (Date.parse(`${k}:00:00Z`) < since - 3600e3 + 1) continue;
      flowIn += v.in; flowOut += v.out;
      if (!v.ex) { complete = false; continue; }
      for (const [name, f] of Object.entries(v.ex)) {
        const e = (byEx[name] ||= { in: 0, out: 0 });
        e.in += f.in; e.out += f.out;
      }
    }
    // Name exchanges only when every hour in the window has its breakdown, so the names add up to the totals.
    const exchanges = complete
      ? Object.entries(byEx).map(([name, f]) => ({ name, display: this.exchangeDisplay(name), status: this.exchangeStatus(name), in: f.in, out: f.out })).sort((a, b) => (b.in + b.out) - (a.in + a.out))
      : null;
    return { moves: moves.length, largest: Math.max(0, ...moves.map((m) => m.amount)), dex: items.filter((f) => f.type === 'dex' || f.type === 'liquidity').length, flowIn, flowOut, exchanges };
  }

  async scheduledPosts() {
    const local = new Date(this.now() + this.cfg.tzOffsetHours * 3600e3);
    const dayKey = local.toISOString().slice(0, 10);
    if (local.getUTCHours() < this.cfg.summaryHour) return;
    const weekly = local.getUTCDay() === this.cfg.weeklyDay;
    if (weekly && this.state.lastWeekly !== dayKey) {
      const w = this.windowStats(24 * 7);
      const concDays = Object.keys(this.state.conc).sort();
      const latest = concDays.at(-1);
      const weekAgo = concDays.filter((d) => d <= new Date(this.now() - 7 * 86400e3).toISOString().slice(0, 10)).at(-1);
      const text = F.weeklyPost({ ...w, from: this.localDay(this.now() - 6 * 86400e3), to: dayKey, conc: latest ? this.state.conc[latest] : null, prev: weekAgo ? this.state.conc[weekAgo] : null });
      this.state.lastWeekly = dayKey;
      this.state.lastDaily = dayKey; // the weekly digest replaces that day's summary
      this.checkpoint();
      const r = await this.x.post(text, { kind: 'weekly' });
      if (!r.ok) log('weekly post failed:', r.error);
      return;
    }
    if (this.state.lastDaily === dayKey) return;
    const s = this.windowStats(24);
    const p = this.state.platform;
    const text = F.dailyPost({
      ...s, day: dayKey, notPosted: this.state.days[dayKey]?.notPosted || 0,
      platform: p.total, platformDays: Math.floor((this.now() - Date.parse(p.lastMoveAt)) / 86400e3),
    });
    this.state.lastDaily = dayKey;
    this.checkpoint();
    const r = await this.x.post(text, { kind: 'daily' });
    if (!r.ok) log('daily post failed:', r.error);
  }

  // ---- outputs ----
  prune() {
    const cutoff = this.now() - this.cfg.feedDays * 86400e3;
    this.feed = this.feed.filter((f) => f.time >= cutoff).sort((a, b) => b.time - a.time);
    const dayCut = this.localDay(cutoff);
    for (const k of Object.keys(this.state.days)) if (k < dayCut) delete this.state.days[k];
    for (const k of Object.keys(this.state.conc)) if (k < dayCut) delete this.state.conc[k];
    for (const k of Object.keys(this.state.alertsByDay)) if (k < dayCut) delete this.state.alertsByDay[k];
    const hourCut = this.hourKey(this.now() - 9 * 86400e3);
    for (const k of Object.keys(this.state.hours)) if (k < hourCut) delete this.state.hours[k];
    const keep = new Set(this.feed.map((f) => f.id));
    for (const k of Object.keys(this.state.posted)) if (!keep.has(k)) delete this.state.posted[k];
  }

  // Save, then run the checkpoint command (if any). Throws when the command fails.
  checkpoint() {
    this.save();
    if (this.cfg.checkpointCmd) execFileSync('bash', ['-c', this.cfg.checkpointCmd], { stdio: 'inherit', timeout: 120000 });
  }

  trimPostLog(maxLines = 1000) {
    const f = path.join(this.cfg.dataDir, 'posts.jsonl');
    if (!fs.existsSync(f)) return;
    const lines = fs.readFileSync(f, 'utf8').split('\n').filter(Boolean);
    if (lines.length > maxLines) fs.writeFileSync(f, lines.slice(-maxLines).join('\n') + '\n');
  }

  save() {
    this.trimPostLog();
    this.prune();
    this.state.pools = [...this.pools];
    writeJson(this.stateFile, this.state);
    writeJson(this.feedFile, this.feed);
    this.publish();
  }

  // Labels change over time (new evidence, corrections), so names on stored items are refreshed on every publish.
  relabel() {
    for (const it of this.feed) {
      if (it.from) it.fromLabel = F.displayName(this.labelOf(it.from));
      if (it.to) it.toLabel = F.displayName(this.labelOf(it.to));
      if (it.trader) it.traderLabel = F.displayName(this.labelOf(it.trader));
      if (it.type === 'move') {
        const fl = this.labelOf(it.from), tl = this.labelOf(it.to);
        if (fl?.type === 'exchange' && tl?.type === 'exchange' && fl.name === tl.name) it.internal = true;
      }
    }
  }

  publish() {
    this.relabel();
    const now = this.now();
    const days = Object.entries(this.state.days).sort().map(([day, d]) => ({ day, moves: d.moves, largest: Math.round(d.largest), dex: d.dex, flowIn: Math.round(d.flowIn), flowOut: Math.round(d.flowOut) }));
    const exchanges = {};
    const since30 = this.localDay(now - 30 * 86400e3);
    for (const [day, d] of Object.entries(this.state.days)) {
      if (day < since30) continue;
      for (const [name, f] of Object.entries(d.flows)) {
        const e = (exchanges[name] ||= { in: 0, out: 0 });
        e.in += f.in; e.out += f.out;
      }
    }
    const p = this.state.platform;
    writeJson(path.join(this.cfg.publicDir, 'feed.json'), {
      updated: new Date(now).toISOString(),
      items: this.feed.slice(0, 400).map(({ posted, ...rest }) => ({ ...rest, posted: Boolean(this.state.posted[rest.id] && !['capped', 'failed', 'pending', 'relay', 'seed', 'internal'].includes(this.state.posted[rest.id])) })),
    });
    writeJson(path.join(this.cfg.publicDir, 'stats.json'), {
      updated: new Date(now).toISOString(),
      price: this.state.price,
      thresholds: { move: this.cfg.moveMin, post: this.cfg.postMin },
      days,
      exchanges: Object.entries(exchanges).map(([name, f]) => ({ name, display: this.exchangeDisplay(name), in: Math.round(f.in), out: Math.round(f.out) })).sort((a, b) => (b.in + b.out) - (a.in + a.out)),
      labelledExchanges: [...new Set(Object.values(this.labels).filter((l) => l.type === 'exchange').map((l) => F.displayName(l)))],
      exchangeList: [...new Set(Object.values(this.labels).filter((l) => l.type === 'exchange').map((l) => l.name))].map((n) => this.exchangeDisplay(n)).sort(),
      concentration: Object.entries(this.state.conc).sort().map(([day, c]) => ({ day, ...c })),
      platform: p.total == null ? null : { total: Math.round(p.total), perChain: p.perChain, lastMoveAt: p.lastMoveAt, checkedAt: new Date(p.checkedAt).toISOString() },
    });
    writeJson(path.join(this.cfg.publicDir, 'status.json'), {
      updated: new Date(now).toISOString(), lagBlocks: this.state.lagBlocks ?? null, cutHeight: this.state.cutHeight ?? null, postMode: this.cfg.postMode,
    });
  }

  async tick() {
    if (fs.existsSync(this.cfg.labelsFile) && fs.statSync(this.cfg.labelsFile).mtimeMs !== this.labelsMtime) this.loadLabels();
    await this.refreshPrice();
    const n = await this.catchUp();
    for (const item of this.fresh) await this.enrich(item);
    await this.checkPlatformShare();
    await this.postFresh();
    await this.snapshotConcentration();
    await this.scheduledPosts();
    this.checkpoint();
    return n;
  }
}

export async function runLimited(tasks, limit, onError) {
  let i = 0;
  const workers = Array.from({ length: Math.min(limit, tasks.length) }, async () => {
    while (i < tasks.length) {
      const task = tasks[i++];
      try { await task(); } catch (e) { onError(e); }
    }
  });
  await Promise.all(workers);
}

async function main() {
  const cfg = { ...CONFIG };
  const w = new Watcher(cfg);
  const back = Number(arg('--backfill-hours') || 0);
  if (back > 0 && !Object.keys(w.state.heights).length) {
    const cut = await w.cw.cut();
    for (const [c, v] of Object.entries(cut)) w.state.heights[c] = v.height - cfg.confirmations - Math.round(back * 120);
    cfg.maxBlocksPerLoop = Math.max(cfg.maxBlocksPerLoop, Math.round(back * 120) + 50);
  }
  // Replay a fixed height range (testing): --start-height H --stop-height H2 --once
  const startH = Number(arg('--start-height') || 0);
  if (startH) {
    cfg.stopHeight = Number(arg('--stop-height'));
    for (let c = 0; c < 20; c++) w.state.heights[c] = startH - 1;
    cfg.maxBlocksPerLoop = cfg.stopHeight - startH + 1;
  }
  log(`whale-watch starting: post mode ${cfg.postMode}, nodes ${cfg.nodes.join(', ')}`);
  let stop = false;
  for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { stop = true; });
  do {
    const started = Date.now();
    try {
      const n = await w.tick();
      if (n) log(`processed ${n} blocks, lag ${w.state.lagBlocks}, feed ${w.feed.length}`);
    } catch (e) {
      log('tick failed:', e.message);
      if (argv.includes('--once')) process.exitCode = 1;
    }
    if (argv.includes('--once')) break;
    const wait = Math.max(1000, cfg.pollSeconds * 1000 - (Date.now() - started));
    for (let t = 0; t < wait && !stop; t += 1000) await new Promise((r) => setTimeout(r, 1000));
  } while (!stop);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch((e) => { log('fatal:', e); process.exit(1); });
}
