// Read-only helpers on the public Kadena GraphQL indexer. Used for history the
// node cannot answer quickly: when a wallet was last active, and holder counts.
// Every caller treats a failure here as "unknown" and carries on.

export class Indexer {
  constructor(url, { timeoutMs = 30000 } = {}) {
    this.url = url;
    this.timeoutMs = timeoutMs;
  }

  async q(query, variables = {}) {
    const res = await fetch(this.url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, variables }),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!res.ok) throw new Error(`indexer HTTP ${res.status}`);
    const d = await res.json();
    if (d.errors && !d.data) throw new Error(`indexer: ${JSON.stringify(d.errors).slice(0, 200)}`);
    return d.data;
  }

  // Time (ms) of the account's most recent KDA transfer before `beforeMs`, ignoring
  // `excludeRequestKey`. null when the account has no earlier activity in the indexer.
  async lastActivityBefore(account, beforeMs, excludeRequestKey) {
    let after = null;
    for (let page = 0; page < 6; page++) {
      const d = await this.q(
        `query($a:String!,$after:String){transfers(accountName:$a,fungibleName:"coin",first:50,after:$after){pageInfo{hasNextPage endCursor} edges{node{creationTime requestKey}}}}`,
        { a: account, after },
      );
      for (const { node } of d.transfers.edges) {
        const t = Date.parse(node.creationTime);
        if (node.requestKey === excludeRequestKey) continue;
        if (t < beforeMs - 1000) return t;
      }
      if (!d.transfers.pageInfo.hasNextPage) return null;
      after = d.transfers.pageInfo.endCursor;
    }
    return undefined; // too busy to tell: not dormant
  }

  // Holders with at least `minBalance` KDA, largest first (balances summed across chains).
  async holdersAbove(minBalance, maxPages = 30) {
    const out = [];
    let after = null;
    for (let page = 0; page < maxPages; page++) {
      const d = await this.q(
        `query($after:String){topFungibleAccounts(first:100,fungibleName:"coin",after:$after){pageInfo{hasNextPage endCursor} edges{node{accountName totalBalance}}}}`,
        { after },
      );
      for (const { node } of d.topFungibleAccounts.edges) {
        const b = Number(node.totalBalance);
        if (b < minBalance) return out;
        out.push({ account: node.accountName, balance: b });
      }
      if (!d.topFungibleAccounts.pageInfo.hasNextPage) return out;
      after = d.topFungibleAccounts.pageInfo.endCursor;
    }
    return out;
  }
}
