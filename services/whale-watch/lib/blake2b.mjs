// BLAKE2b with a configurable digest length (RFC 7693). Node's crypto only
// offers BLAKE2b-512, and Chainweb command hashes are BLAKE2b-256, which is a
// different parameter block, not a truncation. Small and dependency-free.

const IV = [
  0xf3bcc908, 0x6a09e667, 0x84caa73b, 0xbb67ae85, 0xfe94f82b, 0x3c6ef372, 0x5f1d36f1, 0xa54ff53a,
  0xade682d1, 0x510e527f, 0x2b3e6c1f, 0x9b05688c, 0xfb41bd6b, 0x1f83d9ab, 0x137e2179, 0x5be0cd19,
];
const SIGMA = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
  [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
  [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
  [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
  [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
  [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
  [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
];

// 64-bit words are stored as (lo, hi) pairs of 32-bit numbers in a Uint32Array.
function add64(v, a, b) {
  const lo = v[a] + v[b];
  let hi = v[a + 1] + v[b + 1];
  if (lo >= 0x100000000) hi++;
  v[a] = lo;
  v[a + 1] = hi;
}
function add64c(v, a, lo0, hi0) {
  const lo = v[a] + lo0;
  let hi = v[a + 1] + hi0;
  if (lo >= 0x100000000) hi++;
  v[a] = lo;
  v[a + 1] = hi;
}
function G(v, m, a, b, c, d, ix, iy) {
  add64(v, a, b);
  add64c(v, a, m[ix], m[ix + 1]);
  let xlo = v[d] ^ v[a], xhi = v[d + 1] ^ v[a + 1];
  v[d] = xhi; v[d + 1] = xlo; // rotr 32
  add64(v, c, d);
  xlo = v[b] ^ v[c]; xhi = v[b + 1] ^ v[c + 1];
  v[b] = (xlo >>> 24) ^ (xhi << 8); v[b + 1] = (xhi >>> 24) ^ (xlo << 8); // rotr 24
  add64(v, a, b);
  add64c(v, a, m[iy], m[iy + 1]);
  xlo = v[d] ^ v[a]; xhi = v[d + 1] ^ v[a + 1];
  v[d] = (xlo >>> 16) ^ (xhi << 16); v[d + 1] = (xhi >>> 16) ^ (xlo << 16); // rotr 16
  add64(v, c, d);
  xlo = v[b] ^ v[c]; xhi = v[b + 1] ^ v[c + 1];
  v[b] = (xhi >>> 31) ^ (xlo << 1); v[b + 1] = (xlo >>> 31) ^ (xhi << 1); // rotr 63
}

function compress(ctx, last) {
  const v = new Uint32Array(32);
  const m = new Uint32Array(32);
  for (let i = 0; i < 16; i++) { v[i] = ctx.h[i]; v[i + 16] = IV[i]; }
  v[24] ^= ctx.t;
  v[25] ^= ctx.t / 0x100000000;
  if (last) { v[28] = ~v[28]; v[29] = ~v[29]; }
  for (let i = 0; i < 32; i++) {
    const j = i * 4;
    m[i] = ctx.b[j] ^ (ctx.b[j + 1] << 8) ^ (ctx.b[j + 2] << 16) ^ (ctx.b[j + 3] << 24);
  }
  for (let r = 0; r < 12; r++) {
    const s = SIGMA[r];
    G(v, m, 0, 8, 16, 24, s[0] * 2, s[1] * 2);
    G(v, m, 2, 10, 18, 26, s[2] * 2, s[3] * 2);
    G(v, m, 4, 12, 20, 28, s[4] * 2, s[5] * 2);
    G(v, m, 6, 14, 22, 30, s[6] * 2, s[7] * 2);
    G(v, m, 0, 10, 20, 30, s[8] * 2, s[9] * 2);
    G(v, m, 2, 12, 22, 24, s[10] * 2, s[11] * 2);
    G(v, m, 4, 14, 16, 26, s[12] * 2, s[13] * 2);
    G(v, m, 6, 8, 18, 28, s[14] * 2, s[15] * 2);
  }
  for (let i = 0; i < 16; i++) ctx.h[i] = ctx.h[i] ^ v[i] ^ v[i + 16];
}

export function blake2b(input, outlen = 32) {
  const data = typeof input === 'string' ? new TextEncoder().encode(input) : input;
  const ctx = { b: new Uint8Array(128), h: new Uint32Array(16), t: 0, c: 0 };
  for (let i = 0; i < 16; i++) ctx.h[i] = IV[i];
  ctx.h[0] ^= 0x01010000 ^ outlen;
  for (let i = 0; i < data.length; i++) {
    if (ctx.c === 128) { ctx.t += ctx.c; compress(ctx, false); ctx.c = 0; }
    ctx.b[ctx.c++] = data[i];
  }
  ctx.t += ctx.c;
  while (ctx.c < 128) ctx.b[ctx.c++] = 0;
  compress(ctx, true);
  const out = new Uint8Array(outlen);
  for (let i = 0; i < outlen; i++) out[i] = ctx.h[i >> 2] >> (8 * (i & 3));
  return out;
}

export function hashBase64Url(str) {
  return Buffer.from(blake2b(str, 32)).toString('base64url');
}
