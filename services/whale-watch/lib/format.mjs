// Text for posts and the page. Pure functions, unit-tested.
// Alerts end with a DenaScan link to the transaction (Naif's choice, Oct 2026: on X's
// pay-per-use API a post with a link costs about $0.20 instead of $0.015). Summaries stay link-free.

export function shortAccount(a) {
  if (!a) return '?';
  if (/^k:[0-9a-f]{64}$/.test(a)) return `k:${a.slice(2, 6)}…${a.slice(-4)}`;
  if (a.length > 16) return `${a.slice(0, 10)}…${a.slice(-4)}`;
  return a;
}

// Public names. Only exchanges tied to their wallets by the exchange itself (confirmed;
// today that is Gate) are named. Every other exchange wallet shows as "Other exchange"
// (Naif, Oct 24, 2026); labels.json keeps the likely name and its evidence for us.
export const OTHER_EXCHANGE = 'Other exchange';
export const OTHER_EXCHANGES = 'Other exchanges';
export const isNamed = (l) => !(l?.type === 'exchange' && l.confidence !== 'confirmed');
export const nameWithTags = (name, status, likely) => {
  const tags = [status, likely && 'likely'].filter(Boolean);
  return tags.length ? `${name} (${tags.join(', ')})` : name;
};
export function displayName(l) {
  if (!l) return null;
  if (!isNamed(l)) return OTHER_EXCHANGE;
  return nameWithTags(l.name, l.status, l.confidence === 'likely');
}

export function who(account, labelOf) {
  const l = labelOf(account);
  return l ? displayName(l) : `unknown wallet ${shortAccount(account)}`;
}

export function fmtKda(n) {
  return Math.round(n).toLocaleString('en-US');
}

export function compact(n) {
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 1 : 2).replace(/\.?0+$/, '')}M`;
  if (a >= 1e3) return `${Math.round(n / 1e3)}K`;
  return `${Math.round(n)}`;
}

export function fmtUsd(kda, price) {
  if (!price) return '';
  const v = kda * price;
  return ` (~$${v >= 1000 ? Math.round(v).toLocaleString('en-US') : v.toFixed(0)})`;
}

export function tokenSymbol(token) {
  if (!token) return '?';
  const last = token.split('.').pop();
  if (last === 'coin') return 'KDA';
  if (/^[a-z]+$/.test(last)) return last.toUpperCase(); // bro -> BRO, flux -> FLUX
  return last; // kb-USDC
}

export function fmtToken(amount) {
  if (amount >= 100) return Math.round(amount).toLocaleString('en-US');
  if (amount >= 1) return amount.toFixed(2);
  return amount.toPrecision(3);
}

export function whales(amount, t) {
  if (amount >= t.huge) return '🚨🐋🐋🐋';
  if (amount >= t.big) return '🐋🐋';
  return '🐋';
}

export const txUrl = (rk) => `https://denascan.com/transactions/${encodeURIComponent(rk)}`;
const chainText = (it) => (it.toChain != null && it.toChain !== it.chain ? `Chain ${it.chain} → ${it.toChain}` : `Chain ${it.chain}`);

// How long a wallet sat unused, in plain words: "over a year", "over 3 years", "200 days".
export function idleText(days) {
  if (days >= 730) return `over ${Math.floor(days / 365)} years`;
  if (days >= 365) return 'over a year';
  return `${days} days`;
}

// "Oct 22, 2025"
export const dateText = (ms) => {
  const d = new Date(ms);
  return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
};

// "⏰ Dormant wallet woke up: no transactions for over a year (last active Oct 22, 2025)"
export function dormantLine(it) {
  const last = it.lastActive ?? (it.time != null ? it.time - it.dormantDays * 86400e3 : null);
  return `⏰ Dormant wallet woke up: no transactions for ${idleText(it.dormantDays)}${last != null ? ` (last active ${dateText(last)})` : ''}`;
}

// One plain line saying what an exchange move means. Exchanges that no longer trade
// KDA get their own wording, so nobody reads a deposit there as selling pressure.
export function exchangeNote(fromL, toL) {
  const fx = fromL?.type === 'exchange', tx = toL?.type === 'exchange';
  const gone = (l) => (l.status ? 'an exchange that no longer trades KDA' : null);
  if (fx && tx) return '🔁 Moved between two exchanges';
  if (tx) return gone(toL) ? `📥 Sent to ${gone(toL)}` : '📥 Exchange deposit: KDA sent to an exchange can be sold there';
  if (fx) return gone(fromL) ? `📤 Leaving ${gone(fromL)}` : "📤 Exchange withdrawal: KDA taken off an exchange, usually into the owner's own wallet";
  return null;
}

export const newWhaleLine = (n, detail = true) => `🆕 New whale: the receiver now holds ${compact(n)} KDA${detail ? ' (under 1M before this move)' : ''}`;

// Fits a post into X's 280 by dropping the optional explanation lines, least important first.
function fit(build, optional) {
  let keep = [...optional];
  for (;;) {
    const text = build(new Set(keep));
    if (weightedLength(text) <= 280 || !keep.length) return text;
    keep = keep.slice(0, -1);
  }
}

export function movePost(it, { labelOf, price, thresholds }) {
  const fromL = labelOf(it.from);
  const toL = labelOf(it.to);
  const amt = `${fmtKda(it.amount)} $KDA${fmtUsd(it.amount, price)}`;
  let head;
  const fx = fromL?.type === 'exchange', tx = toL?.type === 'exchange';
  const exName = (l) => (isNamed(l) ? displayName(l) : 'an exchange');
  if (fx && tx) head = !isNamed(fromL) && !isNamed(toL) ? `${amt} moved between two exchanges` : `${amt} moved from ${exName(fromL)} to ${exName(toL)}`;
  else if (fx) head = `${amt} withdrawn from ${exName(fromL)}`;
  else if (tx) head = `${amt} deposited to ${exName(toL)}`;
  else head = `${amt} moved`;
  const note = exchangeNote(fromL, toL);
  return fit((keep) => {
    const lines = [];
    if (it.dormantDays) lines.push(keep.has('dormantDate') ? dormantLine(it) : dormantLine({ dormantDays: it.dormantDays }));
    lines.push(`${whales(it.amount, thresholds)} ${head}`);
    if (note && keep.has('note')) lines.push(note);
    const body = [];
    if (!(fx && tx)) body.push(`From: ${who(it.from, labelOf)}`, `To: ${who(it.to, labelOf)}`); // the headline already names both exchanges
    if (it.newWhale) body.push(newWhaleLine(it.newWhale, keep.has('whaleDetail')));
    if (body.length) lines.push('', ...body);
    lines.push('', chainText(it), txUrl(it.requestKey));
    return lines.join('\n');
  }, ['note', 'whaleDetail', 'dormantDate']);
}

const isStable = (sym) => /USD/i.test(sym || '');
const fmtPrice = (p) => `$${p >= 0.1 ? p.toFixed(3) : p.toPrecision(2)}`;

// For trades against a dollar stablecoin: the price the trader actually got, against the
// market (pool) price, e.g. "📉 About $0.0070 per KDA, 35% below the market price".
export function tradePriceLine(it, price) {
  const kda = it.kda ?? it.amount;
  const sym = it.other ? tokenSymbol(it.other.token) : null;
  if (!price || !kda || !it.other || !isStable(sym)) return null;
  const got = it.other.amount / kda;
  const diff = Math.round((got / price - 1) * 100);
  if (Math.abs(diff) < 3) return `About ${fmtPrice(got)} per KDA, close to the market price`;
  return `${diff < 0 ? '📉' : '📈'} About ${fmtPrice(got)} per KDA, ${Math.abs(diff)}% ${diff < 0 ? 'below' : 'above'} the market price`;
}

// Takes a parsed trade ({ kda, liquidity }) or a stored feed item ({ amount, type: 'liquidity' }).
export function dexPost(it, { labelOf, price, thresholds }) {
  const kda = it.kda ?? it.amount;
  const liquidity = it.liquidity ?? it.type === 'liquidity';
  const sym = it.other ? tokenSymbol(it.other.token) : null;
  const amt = `${fmtKda(kda)} $KDA${fmtUsd(kda, price)}`;
  let head, note;
  if (liquidity) {
    const plus = it.other ? ` + ${fmtToken(it.other.amount)} ${sym}` : '';
    head = it.side === 'add'
      ? `🌊 ${amt}${plus} put into the ${it.dex} KDA/${sym} pool`
      : `🌊 ${amt}${plus} taken out of the ${it.dex} KDA/${sym} pool`;
    note = it.side === 'add'
      ? 'Liquidity added, not a purchase: the wallet put both tokens into the pool so others can trade against it'
      : 'Liquidity removed, not a sale: the wallet took its share of both tokens back out of the pool';
  } else {
    const w = kda >= thresholds.huge ? '🚨 ' : '';
    head = it.side === 'sell'
      ? `${w}💱 ${amt} sold on ${it.dex} for ${fmtToken(it.other.amount)} ${sym}`
      : `${w}💱 ${amt} bought on ${it.dex} with ${fmtToken(it.other.amount)} ${sym}`;
    note = tradePriceLine({ ...it, kda }, price);
  }
  return fit((keep) => [head, ...(note && keep.has('note') ? [note] : []), '', `${liquidity ? 'Wallet' : 'Trader'}: ${who(it.trader, labelOf)}`, '', `Chain ${it.chain}`, txUrl(it.requestKey)].join('\n'), ['note']);
}

export function platformPost(it, { price }) {
  const what = it.kind === 'release'
    ? `${fmtKda(it.amount)} $KDA${fmtUsd(it.amount, price)} of the frozen Kadena platform share was released from allocation ${it.account}`
    : it.kind === 'transfer'
      ? `${fmtKda(it.amount)} $KDA${fmtUsd(it.amount, price)} moved out of platform-share account ${it.account} to ${shortAccount(it.to)}`
      : `The frozen Kadena platform share dropped by ${fmtKda(it.amount)} $KDA${fmtUsd(it.amount, price)}`;
  const lines = [`🚨 Platform share moved`, '', what, '', 'Moving it needs 3 of the 5 community keys.'];
  if (it.remaining != null) lines.push(`Still frozen: ${compact(it.remaining)} KDA`);
  lines.push('', `Chain ${it.chain}`);
  if (it.requestKey) lines.push(txUrl(it.requestKey));
  return lines.join('\n');
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const dayLabel = (iso) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${Number(iso.slice(8, 10))}`;

// One exchange's 24h activity, e.g. "Gate: 15K KDA deposited · 80K withdrawn".
export function exchangeLine(e) {
  const parts = [];
  if (Math.round(e.in) > 0) parts.push(`${compact(e.in)} KDA deposited`);
  if (Math.round(e.out) > 0) parts.push(`${compact(e.out)} ${parts.length ? '' : 'KDA '}withdrawn`);
  return parts.length ? `${e.display}: ${parts.join(' · ')}` : null;
}

// Exchange lines for the daily summary: named (confirmed) exchanges one per line, busiest
// first (up to max), then everything else as one "Other exchanges" line. Without a
// breakdown: the totals only.
export function flowLines(flowIn, flowOut, exchanges, max = 3) {
  if (!flowIn && !flowOut) return [];
  const ex = exchanges || [];
  const named = ex.filter((e) => !e.other).map(exchangeLine).filter(Boolean);
  const other = exchangeLine({ display: OTHER_EXCHANGES, in: ex.filter((e) => e.other).reduce((a, e) => a + e.in, 0), out: ex.filter((e) => e.other).reduce((a, e) => a + e.out, 0) });
  if ((!named.length && !other) || max < 1) return [`Exchanges: ${compact(flowIn)} KDA deposited · ${compact(flowOut)} KDA withdrawn`];
  const lines = ['Exchanges:', ...named.slice(0, max)];
  const rest = named.length - max;
  if (rest > 0) lines.push(`+ ${rest} more ${rest === 1 ? 'exchange' : 'exchanges'}`);
  if (other) lines.push(other);
  return lines;
}

export function dailyPost(s) {
  // Name as many exchanges as fit in one post (X allows 280).
  for (let max = 3; ; max--) {
    const lines = [`📊 Kadena whale summary · ${dayLabel(s.day)}`, ''];
    if (s.moves) lines.push(`100K+ KDA moves: ${s.moves} (largest ${fmtKda(s.largest)})`);
    else lines.push('No moves of 100K+ KDA in the last 24h');
    if (s.dex) lines.push(`DEX trades and pool moves 100K+: ${s.dex}`);
    lines.push(...flowLines(s.flowIn, s.flowOut, s.exchanges, max));
    if (s.notPosted) lines.push(`(${s.notPosted} more ${s.notPosted === 1 ? 'move' : 'moves'} not posted today)`);
    if (s.platform != null) lines.push(`Platform share: ${compact(s.platform)} KDA, unmoved for ${s.platformDays} days`);
    const text = lines.join('\n');
    if (max <= 0 || weightedLength(text) <= 280) return text;
  }
}

const delta = (now, before) => (before == null ? '' : ` (${now - before >= 0 ? '+' : '−'}${Math.abs(now - before)})`);

export function weeklyPost(w) {
  const lines = [`🗓 Kadena whale week · ${dayLabel(w.from)}–${dayLabel(w.to)}`, ''];
  lines.push(w.moves ? `100K+ moves: ${w.moves} · largest ${fmtKda(w.largest)} KDA` : 'No moves of 100K+ KDA this week');
  if (w.conc) {
    lines.push(`Wallets holding 1M+ KDA: ${w.conc.w1m}${delta(w.conc.w1m, w.prev?.w1m)}`);
    lines.push(`Wallets holding 100K+ KDA: ${w.conc.w100k}${delta(w.conc.w100k, w.prev?.w100k)}`);
    lines.push(`Top 10 wallets hold ${compact(w.conc.top10)} KDA`);
  }
  // with a breakdown, only named (confirmed) exchanges count toward the net flow
  const live = w.exchanges?.filter((e) => !e.other);
  const fIn = live ? live.reduce((a, e) => a + e.in, 0) : w.flowIn, fOut = live ? live.reduce((a, e) => a + e.out, 0) : w.flowOut;
  if (Math.round(fIn) || Math.round(fOut)) {
    const net = fIn - fOut;
    lines.push(net === 0 ? 'Exchanges: deposits and withdrawals even'
      : `Exchanges: ${compact(Math.abs(net))} more KDA ${net > 0 ? 'deposited than withdrawn' : 'withdrawn than deposited'}`);
    if (live && live.length > 1) lines.push(`Busiest: ${live.slice(0, 3).map((e) => e.display).join(', ')}`);
  }
  return lines.join('\n');
}

// X counts characters with some characters (emoji) weighted 2; stay well under 280.
export function weightedLength(text) {
  let n = 0;
  const plain = text.replace(/https?:\/\/\S+/g, () => { n += 23; return ''; }); // X counts every link as 23
  for (const ch of plain) n += ch.codePointAt(0) > 0x10ff ? 2 : 1;
  return n;
}

// A post X would reject or that shows a broken number: more than one cashtag
// (X allows one), or NaN / undefined / null in the text.
export function postProblem(text) {
  if (/\b(NaN|undefined|null)\b/.test(text)) return 'broken value in text';
  if ((text.match(/\$[A-Za-z][A-Za-z0-9_]*/g) || []).length > 1) return 'more than one cashtag';
  return null;
}
