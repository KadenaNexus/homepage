/* Kadena AgentPay AI owner dashboard (devnet demo).
 *
 * Everything runs in this page: it makes an owner key and an agent key, signs
 * Kadena transactions with them, and talks to the demo service on the devnet
 * server. The agent buys from the demo seller over x402.
 *
 * Needs AgentPayCrypto (crypto.js): keyPairFromSeed, randomSeed, sign, hash.
 */
(() => {
  "use strict";
  const C = window.AgentPayCrypto;
  const local = ["127.0.0.1", "localhost"].includes(location.hostname);
  // The service address can be changed only when the page itself runs locally (for tests).
  const API = (local && new URLSearchParams(location.search).get("api")) || "https://devnet.kadena.ws/agentpay";
  const STORE = "agentpay-demo-v1";
  const POLL_MS = local ? 150 : 3000;
  const MODULE_DEFAULT = "free.agentpay";
  const AGENT_CEILING_KDA = 1; // the agent in this page never signs for more than this

  const $ = id => document.getElementById(id);
  const enc = new TextEncoder();
  const hex = bytes => Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  const unhex = text => Uint8Array.from(text.match(/../g), h => parseInt(h, 16));
  const b64url = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const toB64 = obj => btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
  const fromB64 = text => JSON.parse(decodeURIComponent(escape(atob(text))));
  const short = (text, n = 10) => (text.length > 2 * n + 3 ? `${text.slice(0, n)}…${text.slice(-6)}` : text);

  let info = null;
  let state = load();
  let busy = false;

  function load() {
    try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; }
  }
  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch { /* private mode: keep in memory */ }
  }
  const owner = () => C.keyPairFromSeed(unhex(state.ownerSeed));
  const agent = () => C.keyPairFromSeed(unhex(state.agentSeed));
  const ownerAccount = () => "k:" + hex(owner().publicKey);

  // ---- numbers. Amounts are kept as text so nothing is rounded on the way.
  /** "1" -> "1.0", "0.050" -> "0.05". Returns null if it is not a positive amount. */
  function dec(text) {
    const t = String(text).trim();
    if (!/^\d{1,6}(\.\d{1,12})?$/.test(t) || Number(t) <= 0) return null;
    const [whole, fraction = ""] = t.split(".");
    return `${String(Number(whole))}.${fraction.replace(/0+$/, "") || "0"}`;
  }
  /** A number read from the chain: plain, {"decimal": "..."} or {"int": n}. */
  function num(value) {
    if (value && typeof value === "object") return Number(value.decimal ?? value.int ?? NaN);
    return Number(value);
  }
  const show = value => {
    const n = num(value);
    return Number.isFinite(n) ? String(Number(n.toFixed(6))) : "?";
  };
  function atomicToDec(atomic) {
    const padded = atomic.padStart(13, "0");
    const whole = padded.slice(0, -12).replace(/^0+(?=\d)/, "");
    return `${whole}.${padded.slice(-12).replace(/0+$/, "") || "0"}`;
  }

  // ---- Kadena transactions
  const requestKey = cmd => b64url(C.hash(enc.encode(cmd)));
  const signature = (cmd, keys) => hex(C.sign(C.hash(enc.encode(cmd)), keys.secretKey));

  /** JSON for a command. Amounts in `literals` are written by hand so "1.0" stays a decimal. */
  function command(body, literals = {}) {
    let text = JSON.stringify(body);
    for (const [mark, value] of Object.entries(literals)) text = text.split(`"${mark}"`).join(value);
    return text;
  }
  const meta = sender => ({
    chainId: info.chainId, sender, gasLimit: info.gasLimit, gasPrice: info.gasPrice, ttl: 600,
    creationTime: Math.floor(Date.now() / 1000) - 30,
  });

  async function call(path, options = {}) {
    let response;
    try {
      response = await fetch(API + path, options);
    } catch {
      throw new Error("The devnet demo service could not be reached.");
    }
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
    return { response, data };
  }
  async function post(path, body) {
    const { response, data } = await call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error((data && (data.detail || data.error)) || `The demo service answered ${response.status}.`);
    return data;
  }

  /** Read-only call. Returns the value, or null if the chain refused (for example "row not found"). */
  async function read(code) {
    const cmd = command({ networkId: info.network, payload: { exec: { code, data: {} } }, signers: [], meta: { ...meta(""), gasLimit: 15000 }, nonce: `read-${Date.now()}-${Math.random()}` });
    const out = await post("/local?signatureVerification=false", { hash: requestKey(cmd), sigs: [], cmd });
    return out.result && out.result.status === "success" ? out.result.data : null;
  }

  async function waitMined(key, label) {
    const started = Date.now();
    for (;;) {
      const out = await post("/poll", { requestKey: key });
      if (out.mined) {
        const result = out.result.result || {};
        if (result.status === "success") return out.result;
        const message = (result.error && result.error.message) || "The chain refused the transaction.";
        throw new Error(message);
      }
      const seconds = Math.round((Date.now() - started) / 1000);
      if (seconds > 300) throw new Error("No block after 5 minutes. The devnet may be paused.");
      say(`${label} Waiting for a block (${seconds}s)…`);
      await new Promise(r => setTimeout(r, POLL_MS));
    }
  }

  /** One owner transaction, signed by the owner key, which also pays the gas. */
  async function ownerSend(label, code, data = {}, clist = [], literals = {}) {
    const keys = owner();
    const account = ownerAccount();
    const cmd = command({
      networkId: info.network, payload: { exec: { code, data } },
      signers: [{ pubKey: hex(keys.publicKey), clist }], meta: meta(account),
      nonce: `agentpay-app-${Date.now()}`,
    }, literals);
    say(`${label} Sending…`);
    const sent = await post("/send", { hash: requestKey(cmd), sigs: [{ sig: signature(cmd, keys) }], cmd });
    return waitMined(sent.requestKey, label);
  }
  const transferCaps = (from, to) => [{ name: "coin.GAS", args: [] }, { name: "coin.TRANSFER", args: [from, to, "__AMOUNT__"] }];

  // ---- the agent: one x402 purchase
  function buildPayment(offer, memo) {
    const extra = offer.extra;
    const amount = atomicToDec(offer.amount);
    const keys = agent();
    const agentPublicKey = hex(keys.publicKey);
    const code = `(${extra.module}.pay "${state.allowanceId}" "${offer.payTo}" ${amount} "${extra.paymentId}" "${memo}")`;
    const cmd = command({
      networkId: offer.network.split(":")[1],
      payload: { exec: { code, data: {} } },
      signers: [
        { pubKey: extra.feePayer, clist: [{ name: "coin.GAS", args: [] }] },
        { pubKey: agentPublicKey, clist: [{ name: `${extra.module}.PAY`, args: [state.allowanceId, offer.payTo, "__AMOUNT__", extra.paymentId] }] },
      ],
      meta: { chainId: extra.chainId, sender: extra.feePayerAccount, gasLimit: extra.gasLimit, gasPrice: extra.gasPrice, ttl: Math.min(offer.maxTimeoutSeconds || 600, 600), creationTime: Math.floor(Date.now() / 1000) - 30 },
      nonce: `x402-${extra.paymentId}`,
    }, { __AMOUNT__: amount });
    return {
      x402Version: 2, accepted: offer,
      payload: { allowance: state.allowanceId, memo, agentPublicKey, cmd, signature: signature(cmd, keys) },
    };
  }

  async function buy(product) {
    const log = $("log");
    log.replaceChildren();
    const line = (text, kind) => {
      const li = document.createElement("li");
      if (kind) li.className = kind;
      li.textContent = text;
      log.append(li);
      return li;
    };
    const started = Date.now();
    const entry = { time: Date.now(), path: product.path, item: product.description, price: product.priceKda };
    try {
      say(`Agent: asking for "${product.description}"…`);
      line(`1. Agent asks the seller for ${product.path}`);
      const first = await call(product.path);
      if (first.response.status !== 402) throw new Error(`Expected "402 Payment Required", got ${first.response.status}.`);
      const required = fromB64(first.response.headers.get("PAYMENT-REQUIRED"));
      const offer = required.accepts.find(o => o.scheme === "exact" && o.network === info.x402Network && o.asset === "coin");
      if (!offer) throw new Error("The seller did not offer a KDA price this agent can pay.");
      const price = atomicToDec(offer.amount);
      line(`2. Seller answers 402: ${show(price)} KDA to ${short(offer.payTo)}, payment id ${offer.extra.paymentId}`);
      if (Number(price) > AGENT_CEILING_KDA) throw new Error("The price is above this agent's own ceiling, so it did not sign.");
      const payment = buildPayment(offer, "dashboard demo");
      line("3. Agent signs one payment for exactly those terms and asks again");
      say("Agent: payment signed. Waiting for the seller…");
      // The seller may be waiting for a block. Show that in the log itself, with
      // a running count, so the wait is visible where the reader is looking.
      const waiting = line("Waiting for the seller…");
      const waitStart = Date.now();
      const tick = setInterval(() => {
        const s = Math.round((Date.now() - waitStart) / 1000);
        waiting.textContent = s < 3 ? "Waiting for the seller…" : `Waiting for the seller, which is waiting for a block (${s}s)…`;
      }, 1000);
      let second;
      try {
        second = await call(product.path, { headers: { "PAYMENT-SIGNATURE": toB64(payment) } });
      } finally {
        clearInterval(tick);
        waiting.remove();
      }
      const header = second.response.headers.get("PAYMENT-RESPONSE");
      const receipt = header ? fromB64(header) : null;
      const seconds = ((Date.now() - started) / 1000).toFixed(1);
      entry.paymentId = offer.extra.paymentId;
      if (second.response.status === 200 && receipt && receipt.success) {
        const fast = receipt.extra && receipt.extra.settlement === "submitted";
        entry.ok = true; entry.fast = fast; entry.tx = receipt.transaction; entry.seconds = seconds;
        line(fast
          ? `4. Delivered in ${seconds}s, before the block. The payment was sent and is being confirmed.`
          : `4. Paid and delivered in ${seconds}s. The payment is in a block.`, "ok");
        line(`Data received: ${JSON.stringify(second.data)}`, "ok");
        say("");
      } else {
        const reason = (receipt && ((receipt.extra && receipt.extra.detail) || receipt.errorMessage || receipt.errorReason)) || `The seller answered ${second.response.status}.`;
        entry.ok = false; entry.reason = reason;
        line(`4. Refused: ${reason}. Nothing was paid.`, "no");
        say("");
      }
    } catch (err) {
      entry.ok = false; entry.reason = err.message;
      line(`Stopped: ${err.message}`, "no");
      say("");
    }
    state.history = [entry, ...(state.history || [])].slice(0, 30);
    save();
    await refresh();
  }

  // ---- screen
  function say(text, isError = false) {
    const el = $("activity");
    el.textContent = text;
    el.classList.toggle("err", isError);
  }
  function setBusy(on) {
    busy = on;
    document.querySelectorAll(".apd button, .apd input").forEach(el => { if (el.id !== "btn-reset") el.disabled = on; });
  }
  /** Run one action with the buttons locked, and show any error. */
  async function act(work) {
    if (busy) return;
    setBusy(true);
    try {
      await work();
    } catch (err) {
      say(err.message || String(err), true);
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    $("step-owner").hidden = false;
    const hasOwner = Boolean(state.ownerSeed);
    $("btn-owner").hidden = hasOwner;
    $("owner-facts").hidden = !hasOwner;
    $("step-create").hidden = !hasOwner || Boolean(state.allowanceId);
    for (const id of ["panel-allowance", "panel-agent", "panel-history"]) $(id).hidden = !state.allowanceId;
    if (!hasOwner) return;
    $("owner-account").textContent = ownerAccount();
    const balance = await read(`(coin.get-balance "${ownerAccount()}")`);
    $("owner-balance").textContent = balance === null ? "0" : show(balance);
    if (!state.allowanceId) return;

    const id = state.allowanceId;
    const [allowance, vault, left, listOn, approved] = await Promise.all([
      read(`(${info.module}.get-allowance "${id}")`),
      read(`(${info.module}.vault-balance "${id}")`),
      read(`(${info.module}.remaining-today "${id}")`),
      read(`(${info.module}.sellers-only "${id}")`),
      read(`(${info.module}.is-approved-seller "${id}" "${info.seller}")`),
    ]);
    if (allowance === null) {
      // The devnet was restarted, or this browser's allowance is from an older run.
      say("This allowance is no longer on the devnet (it may have been restarted). Press Reset to start again.", true);
      return;
    }
    state.view = { paused: Boolean(allowance.paused), listOn: Boolean(listOn), approved: Boolean(approved), vault: allowance.vault };
    $("allowance-id").textContent = id;
    $("vault-account").textContent = short(String(allowance.vault), 12);
    $("st-vault").textContent = show(vault);
    $("st-left").textContent = show(left);
    $("st-per").textContent = show(allowance["per-payment"]);
    $("st-daily").textContent = show(allowance["daily-cap"]);
    $("st-count").textContent = show(allowance["payment-count"]);
    $("st-list").textContent = state.view.listOn ? (state.view.approved ? "On, demo seller approved" : "On, demo seller not approved") : "Off";
    if (document.activeElement !== $("set-per")) $("set-per").value = show(allowance["per-payment"]);
    if (document.activeElement !== $("set-daily")) $("set-daily").value = show(allowance["daily-cap"]);
    const pill = $("state-pill");
    pill.textContent = state.view.paused ? "Paused" : "Active";
    pill.classList.toggle("paused", state.view.paused);
    $("btn-pause").textContent = state.view.paused ? "Resume payments" : "Pause all payments";
    $("btn-list").textContent = state.view.listOn ? "Turn off approved sellers only" : "Turn on approved sellers only";
    $("btn-approve").textContent = state.view.approved ? "Remove the demo seller" : "Approve the demo seller";
    await renderHistory();
  }

  async function renderHistory() {
    const body = $("history").querySelector("tbody");
    const rows = [];
    for (const entry of state.history || []) {
      let result = entry.ok ? (entry.fast ? "Delivered; confirming" : "Paid") : `Refused: ${entry.reason}`;
      if (entry.ok && !entry.onChain) {
        const receipt = await read(`(${info.module}.get-payment "${state.allowanceId}" "${entry.paymentId}")`);
        if (receipt !== null) { entry.onChain = true; save(); }
      }
      if (entry.ok && entry.onChain) result = `Paid, on chain (${entry.seconds}s${entry.fast ? ", fast delivery" : ""})`;
      const tr = document.createElement("tr");
      for (const [text, cls] of [[new Date(entry.time).toLocaleTimeString(), ""], [entry.item, ""], [`${show(entry.price)} KDA`, ""], [result, entry.ok ? "ok" : "no"]]) {
        const td = document.createElement("td");
        td.textContent = text;
        if (cls) td.className = cls;
        tr.append(td);
      }
      rows.push(tr);
    }
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4; td.textContent = "No purchases yet.";
      tr.append(td); rows.push(tr);
    }
    body.replaceChildren(...rows);
  }

  function renderProducts() {
    $("buys").replaceChildren(...info.products.map(product => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "buy"; button.dataset.path = product.path;
      const name = document.createElement("b"); name.textContent = product.description;
      const price = document.createElement("span"); price.textContent = `Buy for ${show(product.priceKda)} KDA`;
      button.append(name, price);
      button.addEventListener("click", () => act(() => buy(product)));
      return button;
    }));
  }

  // ---- actions
  const amountFrom = (id, what) => {
    const value = dec($(id).value);
    if (!value) throw new Error(`${what} must be a number above zero, for example 0.05.`);
    return value;
  };

  $("btn-owner").addEventListener("click", () => act(async () => {
    state = { ownerSeed: hex(C.randomSeed()), agentSeed: hex(C.randomSeed()), history: [] };
    save();
    say("Creating the owner account and asking the faucet for 2 test KDA…");
    const sent = await post("/faucet", { account: ownerAccount() });
    await waitMined(sent.requestKey, "Faucet:");
    say("");
    await refresh();
  }));

  $("form-create").addEventListener("submit", event => {
    event.preventDefault();
    act(async () => {
      const per = amountFrom("in-per", "The per-payment limit");
      const daily = amountFrom("in-daily", "The daily limit");
      const fund = amountFrom("in-fund", "The vault amount");
      if (Number(daily) < Number(per)) throw new Error("The daily limit cannot be below the per-payment limit.");
      if (Number(fund) > 1.9) throw new Error("The test owner has 2 KDA. Put at most 1.9 in the vault, to leave some for fees.");
      const id = "demo-" + hex(C.randomSeed()).slice(0, 12);
      const account = ownerAccount();
      await ownerSend("Creating the allowance.", `(${info.module}.create-allowance "${id}" "${account}" (read-keyset "agent-ks") ${per} ${daily})`,
        { "agent-ks": { keys: [hex(agent().publicKey)], pred: "keys-all" } });
      state.allowanceId = id;
      save();
      const vault = await read(`(${info.module}.vault-account "${id}")`);
      await ownerSend("Putting KDA in the vault.", `(coin.transfer "${account}" "${vault}" ${fund})`, {}, transferCaps(account, vault), { __AMOUNT__: fund });
      say("");
      await refresh();
    });
  });

  const ownerCall = (label, code) => act(async () => { await ownerSend(label, code); say(""); await refresh(); });
  $("form-limits").addEventListener("submit", event => {
    event.preventDefault();
    act(async () => {
      const per = amountFrom("set-per", "The per-payment limit");
      const daily = amountFrom("set-daily", "The daily limit");
      if (Number(daily) < Number(per)) throw new Error("The daily limit cannot be below the per-payment limit.");
      await ownerSend("Saving the limits.", `(${info.module}.set-limits "${state.allowanceId}" ${per} ${daily})`);
      say("");
      await refresh();
    });
  });
  $("btn-pause").addEventListener("click", () => ownerCall(state.view.paused ? "Resuming payments." : "Pausing payments.",
    `(${info.module}.set-paused "${state.allowanceId}" ${state.view.paused ? "false" : "true"})`));
  $("btn-list").addEventListener("click", () => ownerCall("Changing the approved sellers setting.",
    `(${info.module}.set-sellers-only "${state.allowanceId}" ${state.view.listOn ? "false" : "true"})`));
  $("btn-approve").addEventListener("click", () => ownerCall(state.view.approved ? "Removing the demo seller." : "Approving the demo seller.",
    `(${info.module}.${state.view.approved ? "remove-seller" : "approve-seller"} "${state.allowanceId}" "${info.seller}")`));
  $("btn-withdraw").addEventListener("click", () => act(async () => {
    const amount = amountFrom("move-amount", "The amount");
    await ownerSend("Withdrawing to the owner.", `(${info.module}.withdraw "${state.allowanceId}" ${amount})`);
    say("");
    await refresh();
  }));
  $("btn-add").addEventListener("click", () => act(async () => {
    const amount = amountFrom("move-amount", "The amount");
    const account = ownerAccount();
    await ownerSend("Adding to the vault.", `(coin.transfer "${account}" "${state.view.vault}" ${amount})`, {}, transferCaps(account, state.view.vault), { __AMOUNT__: amount });
    say("");
    await refresh();
  }));
  $("form-move").addEventListener("submit", event => event.preventDefault());
  $("btn-reset").addEventListener("click", () => {
    if (busy) return;
    state = {};
    try { localStorage.removeItem(STORE); } catch { /* nothing stored */ }
    $("log").replaceChildren();
    say("");
    refresh();
  });

  // ---- start
  (async () => {
    try {
      const { response, data } = await call("/info");
      if (!response.ok || !data) throw new Error("no info");
      info = { module: MODULE_DEFAULT, ...data };
      renderProducts();
      await refresh();
    } catch {
      $("offline").hidden = false;
      $("step-owner").hidden = true;
    }
  })();
})();
