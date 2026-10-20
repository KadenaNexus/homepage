// Minimal Chainweb client: cut, canonical blocks by height range, and /local.
// Tries each node in order, so the Saudi node can be primary with a public fallback.
import { hashBase64Url } from './blake2b.mjs';

const NET = 'mainnet01';

export class Chainweb {
  constructor(urls, { timeoutMs = 30000, log = () => {} } = {}) {
    this.urls = urls.map((u) => u.replace(/\/+$/, ''));
    this.timeoutMs = timeoutMs;
    this.log = log;
  }

  async request(path, init = {}) {
    let lastErr;
    for (const base of this.urls) {
      try {
        const res = await fetch(`${base}/chainweb/0.0/${NET}${path}`, {
          ...init,
          signal: AbortSignal.timeout(this.timeoutMs),
          headers: { 'content-type': 'application/json', ...(init.headers || {}) },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status} ${(await res.text()).slice(0, 160)}`);
        return await res.json();
      } catch (e) {
        lastErr = e;
        this.log(`node ${base}${path.split('?')[0]}: ${e.message}`);
      }
    }
    throw lastErr;
  }

  // { "0": {height, hash}, ... }
  async cut() {
    const d = await this.request('/cut');
    return d.hashes;
  }

  // Canonical blocks of one chain between two heights (inclusive), ascending.
  // Uses the branch endpoint bounded above by the current cut hash, so orphans never appear.
  async blocks(chain, minHeight, maxHeight, upperHash) {
    const out = [];
    let next = null;
    for (let guard = 0; guard < 50; guard++) {
      const q = `minheight=${minHeight}&maxheight=${maxHeight}&limit=100${next ? `&next=${encodeURIComponent(next)}` : ''}`;
      const d = await this.request(`/chain/${chain}/block/branch?${q}`, {
        method: 'POST',
        body: JSON.stringify({ lower: [], upper: [upperHash] }),
      });
      out.push(...d.items);
      if (!d.next) break;
      next = d.next;
    }
    out.sort((a, b) => a.header.height - b.header.height);
    const expected = maxHeight - minHeight + 1;
    if (out.length !== expected) throw new Error(`chain ${chain}: got ${out.length} blocks for ${minHeight}-${maxHeight}`);
    return out;
  }

  async local(chain, code) {
    const cmd = JSON.stringify({
      networkId: NET,
      payload: { exec: { data: {}, code } },
      signers: [],
      meta: { creationTime: Math.floor(Date.now() / 1000) - 60, ttl: 600, gasLimit: 150000, chainId: String(chain), gasPrice: 1e-8, sender: '' },
      nonce: `whale-watch-${Date.now()}-${Math.random()}`,
    });
    const body = JSON.stringify({ hash: hashBase64Url(cmd), sigs: [], cmd });
    const d = await this.request(`/chain/${chain}/pact/api/v1/local?signatureVerification=false&preflight=false`, { method: 'POST', body });
    if (d.result?.status !== 'success') throw new Error(`local on chain ${chain} failed: ${JSON.stringify(d.result?.error || d).slice(0, 200)}`);
    return d.result.data;
  }
}

export function num(x) {
  if (typeof x === 'number') return x;
  if (x && typeof x === 'object' && 'decimal' in x) return Number(x.decimal);
  if (x && typeof x === 'object' && 'int' in x) return Number(x.int);
  return Number(x);
}

export function decodeB64Json(s) {
  return JSON.parse(Buffer.from(s, 'base64url').toString('utf8'));
}
