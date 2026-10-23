// Text for posts and the page. Pure functions, unit-tested.
// Alerts end with a DenaScan link to the transaction (Naif's choice, Oct 2026: on X's
// pay-per-use API a post with a link costs about $0.20 instead of $0.015). Summaries stay link-free.

export function shortAccount(a) {
  if (!a) return '?';
  if (/^k:[0-9a-f]{64}$/.test(a)) return `k:${a.slice(2, 6)}…${a.slice(-4)}`;
  if (a.length > 16) return `${a.slice(0, 10)}…${a.slice(-4)}`;
  return a;
}

// "Gate"; "CoinEx (likely)" when the label rests on circumstantial evidence;
// "Binance (delisted, likely)" when the exchange no longer trades KDA.
export const nameWithTags = (name, status, likely) => {
  const tags = [status, likely && 'likely'].filter(Boolean);
  return tags.length ? `${name} (${tags.join(', ')})` : name;
};
export function displayName(l) {
  if (!l) return null;
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

export function idleText(days) {
  if (days >= 730) return `${(days / 365).toFixed(1)} years`;
  if (days >= 365) return `${(days / 365).toFixed(1)} year${days >= 548 ? 's' : ''}`;
  return `${days} days`;
}

export function movePost(it, { labelOf, price, thresholds }) {
  const fromL = labelOf(it.from);
  const toL = labelOf(it.to);
  const amt = `${fmtKda(it.amount)} $KDA${fmtUsd(it.amount, price)}`;
  let head;
  const fx = fromL?.type === 'exchange', tx = toL?.type === 'exchange';
  if (fx && tx) head = `${amt} moved from ${displayName(fromL)} to ${displayName(toL)}`;
  else if (fx) head = `${amt} withdrawn from ${displayName(fromL)}`;
  else if (tx) head = `${amt} deposited to ${displayName(toL)}`;
  else head = `${amt} moved`;
  const lines = [];
  if (it.dormantDays) lines.push(`⏰ A wallet idle for ${idleText(it.dormantDays)} just moved`);
  lines.push(`${whales(it.amount, thresholds)} ${head}`, '');
  lines.push(`From: ${who(it.from, labelOf)}`);
  lines.push(`To: ${who(it.to, labelOf)}`);
  if (it.newWhale) lines.push(`🆕 Receiver now holds ${compact(it.newWhale)} KDA`);
  lines.push('', chainText(it), txUrl(it.requestKey));
  return lines.join('\n');
}

// Takes a parsed trade ({ kda, liquidity }) or a stored feed item ({ amount, type: 'liquidity' }).
export function dexPost(it, { labelOf, price, thresholds }) {
  const kda = it.kda ?? it.amount;
  const liquidity = it.liquidity ?? it.type === 'liquidity';
  const sym = it.other ? tokenSymbol(it.other.token) : null;
  const amt = `${fmtKda(kda)} $KDA${fmtUsd(kda, price)}`;
  let head;
  if (liquidity) {
    const plus = it.other ? ` + ${fmtToken(it.other.amount)} ${sym}` : '';
    head = it.side === 'add'
      ? `🌊 ${amt}${plus} put into the ${it.dex} KDA/${sym} pool (liquidity added)`
      : `🌊 ${amt}${plus} taken out of the ${it.dex} KDA/${sym} pool (liquidity removed)`;
  } else {
    const w = kda >= thresholds.huge ? '🚨 ' : '';
    head = it.side === 'sell'
      ? `${w}💱 ${amt} sold for ${fmtToken(it.other.amount)} ${sym} on ${it.dex}`
      : `${w}💱 ${amt} bought with ${fmtToken(it.other.amount)} ${sym} on ${it.dex}`;
  }
  return [head, '', `${liquidity ? 'Wallet' : 'Trader'}: ${who(it.trader, labelOf)}`, '', `Chain ${it.chain}`, txUrl(it.requestKey)].join('\n');
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

// Exchange lines for the daily summary. With a per-exchange breakdown, names the
// busiest exchanges (up to max); without one, gives the totals only.
export function flowLines(flowIn, flowOut, exchanges, max = 3) {
  if (!flowIn && !flowOut) return [];
  const named = (exchanges || []).map(exchangeLine).filter(Boolean);
  if (!named.length || max < 1) return [`Exchanges: ${compact(flowIn)} KDA deposited · ${compact(flowOut)} KDA withdrawn`];
  const lines = ['Exchanges:', ...named.slice(0, max)];
  const rest = named.length - max;
  if (rest > 0) lines.push(`+ ${rest} more ${rest === 1 ? 'exchange' : 'exchanges'}`);
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
  if (w.flowIn || w.flowOut) {
    const net = w.flowIn - w.flowOut;
    lines.push(net === 0 ? 'Exchanges: deposits and withdrawals even'
      : `Exchanges: ${compact(Math.abs(net))} more KDA ${net > 0 ? 'deposited than withdrawn' : 'withdrawn than deposited'}`);
    if (w.exchanges?.length) lines.push(`Busiest: ${w.exchanges.slice(0, 3).map((e) => e.display).join(', ')}`);
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
