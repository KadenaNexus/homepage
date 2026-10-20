// Turns a Chainweb block (header + payloadWithOutputs) into the activity the
// watcher cares about: KDA transfers (one record per move, cross-chain paired
// on the source chain), DEX trades, and platform-share events.
import { num, decodeB64Json } from './chainweb.mjs';

const isKda = (ref) => ref && ref.refName && ref.refName.name === 'coin' && !ref.refName.namespace;
const tokenName = (ref) => (ref?.refName ? (ref.refName.namespace ? `${ref.refName.namespace}.` : '') + ref.refName.name : '?');
const eventName = (e) => `${e.module.namespace ? `${e.module.namespace}.` : ''}${e.module.name}.${e.name}`;

// Pool accounts of the Kadena DEXes are principal-like hashes (43 chars, no colon).
export const looksLikePool = (a) => typeof a === 'string' && a.length === 43 && !a.includes(':');

export const DEX_NAMES = {
  'kaddex.exchange': 'Mercatus',
};

export function isPlatformShare(account) {
  return typeof account === 'string' && /^PS_C\d+/.test(account);
}

export function parseBlock(block) {
  const h = block.header;
  const chain = Number(h.chainId);
  const height = h.height;
  const time = Math.floor(h.creationTime / 1000); // microseconds -> ms
  let miner = null;
  try { miner = decodeB64Json(block.payloadWithOutputs.minerData).account; } catch { /* ignore */ }

  const transfers = []; // every KDA transfer (source side), for flows
  const dexTrades = [];
  const platform = [];
  const pools = new Set();

  for (const [, outB64] of block.payloadWithOutputs.transactions) {
    let out;
    try { out = decodeB64Json(outB64); } catch { continue; }
    if (out.result?.status !== 'success') continue;
    const requestKey = out.reqKey;
    const events = (out.events || []).map((e) => ({ name: eventName(e), params: e.params || [] }));
    const swaps = events.filter((e) => /exchange\.SWAP$/.test(e.name));
    // Any DEX pool activity (swaps, liquidity adds/removes all emit <dex>.exchange.UPDATE)
    const updates = events.filter((e) => /exchange\.UPDATE$/.test(e.name));
    const dexTx = swaps.length > 0 || updates.length > 0;

    // gas payer: the KDA transfer to this block's miner (Pact 5 pays gas as a coin.TRANSFER)
    let gasPayer = null;
    for (const e of events) {
      if (e.name === 'coin.TRANSFER' && miner && e.params[1] === miner && e.params[0]) gasPayer = e.params[0];
    }

    let idx = 0;
    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      if (e.name === 'coin.RELEASE_ALLOCATION' && isPlatformShare(e.params[0])) {
        platform.push({ kind: 'release', account: e.params[0], amount: num(e.params[1]), chain, height, time, requestKey });
      }
      if (e.name !== 'coin.TRANSFER') continue;
      const [from, to, amt] = e.params;
      const amount = num(amt);
      if (!from) continue; // coinbase or the landing step of a cross-chain move
      if (miner && to === miner && from === gasPayer && amount < 1) continue; // gas fee
      let receiver = to;
      let toChain = chain;
      if (!to) {
        // cross-chain send: the matching TRANSFER_XCHAIN event names the receiver and target chain
        const x = events.find((x) => x.name === 'coin.TRANSFER_XCHAIN' && x.params[0] === from && Math.abs(num(x.params[2]) - amount) < 1e-9);
        if (!x) continue;
        receiver = x.params[1];
        toChain = Number(x.params[3]);
      }
      const rec = { id: `${requestKey}:${chain}:${idx++}`, requestKey, chain, toChain, height, time, from, to: receiver, amount, dexTx };
      transfers.push(rec);
      if (isPlatformShare(from)) platform.push({ kind: 'transfer', account: from, to: receiver, amount, chain, height, time, requestKey });
    }

    // Liquidity added to or removed from a pool (no swap in the tx): one KDA leg plus the other token.
    if (!swaps.length && updates.length) {
      const moduleName = updates[0].name.replace(/\.UPDATE$/, '');
      for (const t of transfers.filter((t) => t.requestKey === requestKey && t.dexTx)) {
        const add = looksLikePool(t.to) && !looksLikePool(t.from);
        const remove = looksLikePool(t.from) && !looksLikePool(t.to);
        if (!add && !remove) continue;
        const pool = add ? t.to : t.from;
        pools.add(pool);
        const otherEv = events.find((e) => /\.TRANSFER$/.test(e.name) && e.name !== 'coin.TRANSFER' && !/tokens\.TRANSFER$/.test(e.name) && (add ? e.params[1] === pool : e.params[0] === pool));
        dexTrades.push({
          id: `${requestKey}:${chain}:lp`, requestKey, chain, height, time, side: add ? 'add' : 'remove', kda: t.amount,
          other: otherEv ? { token: otherEv.name.replace(/\.TRANSFER$/, ''), amount: num(otherEv.params[2]) } : null,
          trader: add ? t.from : t.to, pool, dex: DEX_NAMES[moduleName] || moduleName.split('.').pop(), module: moduleName, liquidity: true,
        });
      }
    }

    if (swaps.length) {
      for (const s of swaps) for (const a of [s.params[0], s.params[1]]) if (looksLikePool(a)) pools.add(a);
      let sold = 0, bought = 0;
      for (const s of swaps) {
        const [, , aIn, tIn, aOut, tOut] = s.params;
        if (isKda(tIn)) sold += num(aIn);
        if (isKda(tOut)) bought += num(aOut);
      }
      const net = bought - sold;
      const first = swaps[0].params;
      const last = swaps[swaps.length - 1].params;
      const side = net < 0 ? 'sell' : 'buy';
      // the non-KDA side of the trade: what the trader ended up with (sell) or paid (buy)
      const other = side === 'sell'
        ? { token: tokenName(last[5]), amount: num(last[4]) }
        : { token: tokenName(first[3]), amount: num(first[2]) };
      const candidates = [last[1], first[0], gasPayer];
      const trader = candidates.find((a) => a && !looksLikePool(a)) || gasPayer;
      const moduleName = swaps[0].name.replace(/\.SWAP$/, '');
      dexTrades.push({
        id: `${requestKey}:${chain}:dex`, requestKey, chain, height, time, side, kda: Math.abs(net), other, trader,
        dex: DEX_NAMES[moduleName] || moduleName.split('.').pop(), module: moduleName, hops: swaps.length,
        roundTrip: sold > 0 && bought > 0,
      });
    }
  }
  return { chain, height, time, miner, transfers, dexTrades, platform, pools };
}
