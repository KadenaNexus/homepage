// Posting to X (API v2, POST /2/tweets) with OAuth 1.0a user context.
// In dry mode nothing leaves the server: posts are appended to posts.jsonl only.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const ENDPOINT = 'https://api.x.com/2/tweets';

const pct = (s) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);

export function oauthHeader({ method, url, consumerKey, consumerSecret, token, tokenSecret, nonce, timestamp }) {
  const params = {
    oauth_consumer_key: consumerKey,
    oauth_nonce: nonce || crypto.randomBytes(16).toString('hex'),
    oauth_signature_method: 'HMAC-SHA1',
    oauth_timestamp: String(timestamp || Math.floor(Date.now() / 1000)),
    oauth_token: token,
    oauth_version: '1.0',
  };
  // JSON bodies are not part of the OAuth 1.0a signature base string.
  const base = Object.keys(params).sort().map((k) => `${pct(k)}=${pct(params[k])}`).join('&');
  const sigBase = `${method.toUpperCase()}&${pct(url)}&${pct(base)}`;
  const key = `${pct(consumerSecret)}&${pct(tokenSecret)}`;
  params.oauth_signature = crypto.createHmac('sha1', key).update(sigBase).digest('base64');
  return 'OAuth ' + Object.keys(params).sort().map((k) => `${pct(k)}="${pct(params[k])}"`).join(', ');
}

export class XPoster {
  constructor({ mode, keys, dataDir, log = console.log }) {
    this.mode = mode === 'live' ? 'live' : 'dry';
    this.keys = keys;
    this.logFile = path.join(dataDir, 'posts.jsonl');
    this.log = log;
    if (this.mode === 'live' && !(keys.consumerKey && keys.consumerSecret && keys.token && keys.tokenSecret)) {
      throw new Error('POST_MODE=live needs X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN and X_ACCESS_SECRET');
    }
  }

  record(entry) {
    fs.appendFileSync(this.logFile, JSON.stringify(entry) + '\n');
  }

  // Returns { ok, id?, error? }. Never throws.
  async post(text, meta = {}) {
    const at = new Date().toISOString();
    if (this.mode === 'dry') {
      this.record({ at, mode: 'dry', text, ...meta });
      this.log(`[dry post]\n${text}\n`);
      return { ok: true, id: null };
    }
    try {
      const res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: {
          authorization: oauthHeader({ method: 'POST', url: ENDPOINT, consumerKey: this.keys.consumerKey, consumerSecret: this.keys.consumerSecret, token: this.keys.token, tokenSecret: this.keys.tokenSecret }),
          'content-type': 'application/json',
        },
        body: JSON.stringify({ text }),
        signal: AbortSignal.timeout(20000),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const error = `HTTP ${res.status} ${JSON.stringify(body).slice(0, 300)}`;
        this.record({ at, mode: 'live', ok: false, error, text, ...meta });
        return { ok: false, error, status: res.status };
      }
      this.record({ at, mode: 'live', ok: true, id: body.data?.id, text, ...meta });
      return { ok: true, id: body.data?.id };
    } catch (e) {
      this.record({ at, mode: 'live', ok: false, error: e.message, text, ...meta });
      return { ok: false, error: e.message };
    }
  }
}
