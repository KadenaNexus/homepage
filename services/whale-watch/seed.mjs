#!/usr/bin/env node
// One-time seed of the feed with the last N days (default 30), so the page is not
// empty on day one. Finds candidate blocks through the indexer (transfers of the
// largest holders, which include exchange wallets and DEX pools), then reads those
// blocks from the node and runs them through the same code as the live watcher.
// Nothing is posted. Run before the first start: node seed.mjs [days]
import { Watcher, CONFIG, runLimited } from './watcher.mjs';

const days = Number(process.argv[2] || 30);
const since = Date.now() - days * 86400e3;
const w = new Watcher({ ...CONFIG });
w.seeding = true;
await w.refreshPrice(); // seeded amounts get today's USD price

const holders = await w.ix.holdersAbove(CONFIG.moveMin);
console.log(`checking ${holders.length} holders of ${CONFIG.moveMin}+ KDA for ${days} days`);
const blocks = new Map(); // "chain:height" -> true
await runLimited(holders.map(({ account }) => async () => {
  let after = null;
  for (let page = 0; page < 40; page++) {
    const d = await w.ix.q(
      `query($a:String!,$after:String){transfers(accountName:$a,fungibleName:"coin",first:50,after:$after){pageInfo{hasNextPage endCursor} edges{node{amount creationTime block{chainId height}}}}}`,
      { a: account, after },
    );
    let old = false;
    for (const { node } of d.transfers.edges) {
      if (Date.parse(node.creationTime) < since) { old = true; continue; }
      if (Number(node.amount) >= CONFIG.moveMin) blocks.set(`${node.block.chainId}:${node.block.height}`, true);
    }
    if (old || !d.transfers.pageInfo.hasNextPage) break;
    after = d.transfers.pageInfo.endCursor;
  }
}), 6, (e) => console.error('holder skipped:', e.message));

const cut = await w.cw.cut();
const list = [...blocks.keys()].map((k) => k.split(':').map(Number)).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
console.log(`reading ${list.length} blocks from the node`);
const fetched = [];
await runLimited(list.map(([c, h]) => async () => {
  const [b] = await w.cw.blocks(c, h, h, cut[c].hash);
  fetched.push(b);
}), 5, (e) => console.error('block skipped:', e.message));
fetched.sort((a, b) => a.header.creationTime - b.header.creationTime);
for (const b of fetched) w.processBlock(b);
w.fresh = []; // never post seeded history
for (const item of w.feed) w.state.posted[item.id] = 'seed';
await w.checkPlatformShare();
await w.snapshotConcentration();
w.fresh = [];
w.save();
console.log(`feed now holds ${w.feed.length} items`);
