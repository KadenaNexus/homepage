/* Kadena AgentPay AI owner page.
 *
 * The owner signs with a wallet; this page holds no key. For each change it
 * builds the transaction, shows what it does and what the signature is good
 * for, takes the signature from the wallet, checks it, runs the transaction
 * on a node without sending it, and only then sends it.
 *
 * Needs AgentPayOwner (owner-lib.js) and AGENTPAY_OWNER_CONFIG (config.js).
 * Kept in the browser, and nothing else: the account name and allowance id
 * last used (so the page can show them again), the id of the phone wallet
 * connection, and, while a transaction is on its way, its public transaction
 * id (so that after a lost reply or a reload the page finds it again instead
 * of sending a second one).
 */
(() => {
  "use strict";
  const L = window.AgentPayOwner;
  const $ = id => document.getElementById(id);
  const STORE = "agentpay-owner-v1", SENT = "agentpay-owner-sent-v1";
  const POLL_MS = ["127.0.0.1", "localhost"].includes(location.hostname) ? 150 : 4000;
  let config, node, signer = null, wallet = null, allowance = null, view = null, pending = null, busy = false;

  const say = (text, bad = false) => { const s = $("status"); s.textContent = text; s.classList.toggle("bad", bad); };
  const note = (el, text, kind = "") => { el.textContent = text; el.className = `note ${kind}`.trim(); };
  // A value the node did not give is never shown as a number: null is not 0.
  const num = v => (v && typeof v === "object" ? Number(v.decimal ?? v.int ?? NaN) : typeof v === "number" || (typeof v === "string" && v.trim() !== "") ? Number(v) : NaN);
  const show = v => { const n = num(v); return Number.isFinite(n) ? String(Number(n.toFixed(12))) : "unavailable"; };
  const kda = v => (show(v) === "unavailable" ? "unavailable" : `${show(v)} KDA`);
  const missing = error => /not found|no value found/i.test(error || "");
  const remember = () => { try { localStorage.setItem(STORE, JSON.stringify({ account: wallet && wallet.manual ? signer.account : "", id: allowance || "", phone: !!(wallet && wallet.phone), topic: (wallet && wallet.topic) || "" })); } catch { /* private mode */ } };
  const remembered = () => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } };
  // A button marked "locked" stays off whatever else happens (its current value is not known).
  const setBusy = on => { busy = on; document.querySelectorAll("button").forEach(b => { b.disabled = b.classList.contains("locked") || (on && b.id !== "btn-cancel" && !b.classList.contains("live")); }); };
  const lock = (button, on) => { button.classList.toggle("locked", on); button.disabled = on || (busy && !button.classList.contains("live")); };

  async function guarded(work) {
    if (busy) return;
    setBusy(true);
    try { await work(); }
    catch (err) { say(err instanceof L.Refused || err instanceof Error ? err.message : "Something went wrong.", true); }
    finally { setBusy(false); }
  }

  // ---- the contract on the chain must be the reviewed one
  // Returns the hash every listed node reports, or null when it is not confirmed.
  async function contractOk() {
    const check = await L.checkContract(config, node, L.reads);
    if (!check.ok) { note($("contract"), check.reason, "bad"); return null; }
    if (check.verified && config.singleNode) note($("contract"), `Test deployment: contract ${config.module} matches the reviewed version (hash ${check.hash}), but only one node was asked. Use small amounts.`, "warn");
    else if (check.verified) note($("contract"), `Contract ${config.module} matches the reviewed version (hash ${check.hash}), confirmed by ${check.answers.filter(a => a.ok).length} node(s).`, "good");
    else note($("contract"), `Test network: the contract ${config.module} (hash ${check.hash}) is not checked against a reviewed version.`, "warn");
    return check.hash;
  }

  // ---- transactions on their way
  // Before a transaction is sent, its public id is written down here. It is
  // crossed off when a block confirms or refuses it, or when it is too old to
  // be accepted any more. Until then no new change is built for that account:
  // a reply lost on the way, a closed tab or a second tab must never lead to
  // the same KDA being moved twice.
  let sentHere = [];
  const sentRead = () => { try { const list = JSON.parse(localStorage.getItem(SENT)); return Array.isArray(list) ? list.filter(r => r && typeof r.key === "string") : []; } catch { return sentHere; } };
  const sentWrite = list => { sentHere = list; try { list.length ? localStorage.setItem(SENT, JSON.stringify(list)) : localStorage.removeItem(SENT); } catch { /* kept for this visit only */ } };
  const sentDrop = key => sentWrite(sentRead().filter(r => r.key !== key));
  /** Asks the chain about every transaction written down. Returns those still open. */
  async function reconcile() {
    const open = [], settled = [];
    for (const record of sentRead()) {
      let out;
      try { out = await node.poll(record.key); } catch { open.push(record); continue; }      // no answer: still unknown
      if (out) { sentDrop(record.key); settled.push(out.ok ? `Confirmed: ${record.title} (transaction ${record.key}).` : `Refused by the chain: ${record.title} (transaction ${record.key}): ${out.error}`); continue; }
      if (Date.now() / 1000 > record.expires + 90) { sentDrop(record.key); settled.push(`Not confirmed, and now too old to be: ${record.title} (transaction ${record.key}). Nothing changed.`); continue; }
      open.push(record);
    }
    showSent(open, settled);
    return open;
  }
  function showSent(open, settled = []) {
    const lines = open.map(r => {
      const minutes = Math.max(1, Math.ceil((r.expires + 90 - Date.now() / 1000) / 60));
      return `Sent earlier and not confirmed yet: ${r.title}, allowance "${r.id}" (transaction ${r.key}). New changes for this account wait until it is confirmed or expires, at most ${minutes} more minute(s), so that nothing is done twice.`;
    });
    note($("sent"), [...settled, ...lines].join(" "), open.length ? "warn" : settled.length ? "good" : "");
    $("btn-check-sent").hidden = !open.length;
  }
  const mineOpen = open => open.filter(r => signer && r.account === signer.account);
  async function nothingOnItsWay() {
    const open = mineOpen(await reconcile());
    if (open.length) throw new L.Refused(`A transaction sent earlier (${open[0].title}, transaction ${open[0].key}) is not confirmed yet. Wait for it, then try again. Nothing new was sent.`);
  }
  $("btn-check-sent").addEventListener("click", () => guarded(async () => { const open = await reconcile(); if (!open.length && allowance) await refresh(); say(open.length ? "Still waiting for a block." : ""); }));
  window.addEventListener("storage", event => { if (event.key === SENT) showSent(sentRead()); });   // another tab sent something

  // ---- account
  async function useAccount(account, how) {
    const asked = await node.ask(L.reads.details(account));
    if (!asked.ok && !missing(asked.error)) throw new Error(`The account could not be read from the node (${asked.error}). Try again.`);
    const details = asked.ok ? asked.data : null;
    if (!details) throw new L.Refused(`This account has no KDA on chain ${config.chainId} yet. On Kadena every chain keeps its own balance. Send a little KDA to this account on chain ${config.chainId} (1 KDA is plenty for fees), then connect again.`);
    const key = L.singleKeyOf(details);
    if (how.publicKey && how.publicKey !== key) throw new L.Refused("The wallet's key is not the key that controls this account on the chain.");
    signer = { account, publicKey: key };
    wallet = how;
    $("who").textContent = `${account}, balance ${show(details.balance)} KDA, signing with ${how.name}.`;
    $("btn-ecko").hidden = $("btn-manual").hidden = $("btn-phone").hidden = true;
    $("form-manual").hidden = true;
    $("btn-leave").hidden = false;
    $("step-allowance").hidden = false;
    remember();
    say("");
  }
  $("btn-ecko").addEventListener("click", () => guarded(async () => {
    const adapter = L.ecko(window.kadena);
    if (!adapter.available()) throw new L.Refused("eckoWALLET was not found in this browser. Install it, or use \"Sign elsewhere and paste\".");
    say("Waiting for the wallet…");
    const got = await adapter.account(config.networkId);
    await useAccount(got.account, { ...adapter, publicKey: got.publicKey });
  }));
  $("btn-manual").addEventListener("click", () => { $("form-manual").hidden = false; $("in-account").focus(); });

  // ---- phone wallets over WalletConnect. Its client is loaded only when asked for.
  let wcLoading = null, phone = null, linkShown = "", awaiting = null;
  const loadWalletConnect = () => {
    if (!wcLoading) {
      wcLoading = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "walletconnect.js";
        script.onload = () => (window.AgentPayWC ? resolve(window.AgentPayWC) : reject(new Error("The phone wallet connection could not be loaded.")));
        script.onerror = () => reject(new Error("The phone wallet connection could not be loaded."));
        document.head.append(script);
      });
      wcLoading.catch(() => { wcLoading = null; });
    }
    return wcLoading;
  };
  const wcClient = async () => (await loadWalletConnect()).client(config.walletConnectProjectId, {
    name: "Kadena AgentPay AI", description: "Owner page: set and control an AI agent's spending allowance in KDA.",
    url: location.origin, icons: [`${location.origin}/favicon.ico`] });
  function showLink(uri) {
    linkShown = uri || "";
    $("phone").hidden = !uri;
    if (!uri) return;
    const cells = window.AgentPayWC.qr(uri), canvas = $("qr"), quiet = 4;
    const size = Math.floor(canvas.width / (cells.length + 2 * quiet));
    const g = canvas.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, canvas.width, canvas.height);
    g.fillStyle = "#000";
    const offset = Math.floor((canvas.width - size * cells.length) / 2);
    cells.forEach((row, y) => row.forEach((dark, x) => { if (dark) g.fillRect(offset + x * size, offset + y * size, size, size); }));
  }
  function showApproval(p) {
    awaiting = p;
    $("approve").hidden = !p;
    if (!p) return;
    const linx = /linx/i.test(p.wallet) ? " In Linx, open the Data tab to see the full request." : "";
    note($("approve-text"), `Approve the request in ${p.wallet}. Check there that it shows the same purposes as listed above.${linx}`);
    const open = $("approve-open");
    open.hidden = !p.link;
    if (p.link) { open.href = p.link; open.textContent = `Open ${p.wallet}`; } else open.removeAttribute("href");
  }
  const phoneWallet = () => (phone = phone || L.walletConnect(wcClient, config.networkId, { onUri: showLink, onPending: showApproval }));
  const usePhone = got => useAccount(got.account, { ...phoneWallet(), name: got.wallet, publicKey: got.publicKey, phone: true, topic: got.topic });
  $("btn-phone").addEventListener("click", () => guarded(async () => {
    say("Preparing the connection…");
    await loadWalletConnect();
    const waiting = phoneWallet().account();
    say("Waiting for your wallet to approve the connection…");
    await usePhone(await waiting);
  }));
  $("btn-stop").addEventListener("click", () => { if (phone) phone.cancelConnect(); });
  $("btn-copy-link").addEventListener("click", async () => { try { await navigator.clipboard.writeText(linkShown); say("Link copied. Paste it into your wallet's WalletConnect screen."); } catch { say("Copying is not allowed here. Scan the code instead.", true); } });
  $("btn-again").addEventListener("click", () => { if (awaiting) { awaiting.resend(); say("Request sent again. Approve it once in your wallet."); } });
  $("form-manual").addEventListener("submit", event => {
    event.preventDefault();
    guarded(() => useAccount($("in-account").value.trim(), { ...L.manual(() => Promise.resolve($("pasted").value)), manual: true }));
  });
  $("btn-leave").addEventListener("click", async () => {
    try { localStorage.removeItem(STORE); } catch { /* nothing stored */ }
    if (wallet && wallet.phone) { try { await wallet.disconnect(); } catch { /* the wallet ends it on its side */ } }
    location.reload();
  });

  // ---- allowance
  // `target` becomes the open allowance only when it was read in full. A
  // failed read never leaves the page showing one allowance while its buttons
  // act on another.
  function closePanel() {
    allowance = null; view = null;
    $("panel").hidden = true;
    closeReview();
  }
  async function refresh(target = allowance) {
    const m = config.module;
    const got = await node.ask(L.reads.allowance(m, target));
    if (!got.ok || !got.data) {
      if (target !== allowance || (!got.ok && missing(got.error))) closePanel();
      if (!got.ok && !missing(got.error)) throw new Error(`Allowance "${target}" could not be read from the node (${got.error}). Try again.`);
      throw new L.Refused(`There is no allowance "${target}" on this chain.`);
    }
    const a = got.data;
    const [balance, remaining, list] = await Promise.all([
      node.ask(L.reads.vaultBalance(m, target)), node.ask(L.reads.remaining(m, target)), node.ask(L.reads.sellersOnly(m, target))]);
    // What the node did not answer is shown as unavailable, never as 0 or "off".
    const listKnown = list.ok && typeof list.data === "boolean";
    const inVault = balance.ok ? balance.data : null, left = remaining.ok ? remaining.data : null;
    allowance = target;
    view = { id: target, owner: a.owner, vault: a.vault, paused: a.paused === true, listOn: listKnown ? list.data : null };
    $("panel-title").textContent = `Allowance "${target}"`;
    const facts = [["Owner", a.owner], ["Vault account", a.vault], ["In the vault", kda(inVault)],
      ["Per payment", kda(a["per-payment"])], ["Per day (UTC)", kda(a["daily-cap"])], ["Left today", kda(left)],
      ["Payments so far", `${show(a["payment-count"])} (${kda(a["total-paid"])})`], ["Status", view.paused ? "Paused: the agent can pay nothing" : "Active"],
      ["Sellers", !listKnown ? "Unavailable: the node did not answer" : view.listOn ? "Approved sellers only" : "Any seller"]];
    $("facts").replaceChildren(...facts.flatMap(([k, v]) => { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = k; dd.textContent = v; return [dt, dd]; }));
    // The four numbers an owner looks at first.
    const tiles = [["In the vault", inVault], ["Left today", left], ["Per payment", a["per-payment"]], ["Per day (UTC)", a["daily-cap"]]];
    $("tiles").replaceChildren(...tiles.map(([label, value]) => {
      const tile = document.createElement("div"), l = document.createElement("span"), v = document.createElement("strong"), u = document.createElement("small");
      const known = show(value) !== "unavailable";
      tile.className = "tile"; l.textContent = label; v.textContent = known ? `${show(value)} ` : "unavailable"; u.textContent = known ? "KDA" : ""; v.append(u); tile.append(l, v);
      return tile;
    }));
    $("pill").textContent = view.paused ? "Paused" : "Active";
    $("pill").className = `pill ${view.paused ? "off" : "on"}`;
    const mine = a.owner === signer.account;
    note($("mine"), mine ? "" : "This allowance belongs to another account. The chain will refuse changes signed by yours.", mine ? "" : "warn");
    $("btn-pause").textContent = view.paused ? "Resume payments" : "Pause all payments";
    $("btn-list").textContent = `Approved sellers only: ${!listKnown ? "unavailable" : view.listOn ? "on" : "off"}`;
    lock($("btn-list"), !listKnown);          // not switched while its current value is unknown
    $("panel").hidden = false;
    remember();
  }
  $("form-open").addEventListener("submit", event => {
    event.preventDefault();
    guarded(async () => {
      const wanted = $("in-id").value.trim();
      L.reads.allowance(config.module, wanted);
      if (wanted !== allowance) closePanel();          // the old allowance is put away before the new one is read
      await refresh(wanted);
      say("");
    });
  });
  $("btn-refresh").addEventListener("click", () => guarded(async () => { await refresh(); say(""); }));
  $("btn-copy-id").addEventListener("click", async () => { try { await navigator.clipboard.writeText(allowance || ""); say("Allowance id copied. Keep it: you need it to open this allowance again."); } catch { say(`Allowance id: ${allowance}`); } });

  // ---- review, sign, check, send
  async function propose(action, after) {
    if (!signer) throw new L.Refused("Connect your account first.");
    await nothingOnItsWay();
    const hash = await contractOk();
    if (!hash) throw new L.Refused("The contract could not be confirmed. Nothing can be signed.");
    // The transaction is tied to this version of the contract: the chain runs it against no other.
    const built = L.buildCommand(config, signer, action, { moduleHash: hash });
    pending = { built, after, action };
    $("review-title").textContent = `Review: ${built.title}`;
    const li = text => { const el = document.createElement("li"); el.textContent = text; return el; };
    $("review-lines").replaceChildren(...built.lines.map(li));
    $("review-caps").replaceChildren(...built.caps.map(cap => li(`${cap.name} ${cap.args.join(" ")}`.trim() + (cap.name === "coin.GAS" ? "  (pay the transaction fee)" : ""))));
    $("review-gas").textContent = `Fee: at most ${built.maxGasKda} KDA, paid by ${signer.account}. Network ${built.networkId}, chain ${built.chainId}. Valid for ${L.TTL_SECONDS / 60} minutes.`;
    $("review-code").textContent = built.code;
    $("review-cmd").textContent = built.cmd;
    $("review-paste").hidden = !wallet.manual;
    $("unsigned").value = wallet.manual ? L.unsignedForm(L.crypto, built) : "";
    $("pasted").value = "";
    $("btn-sign").textContent = wallet.manual ? "Check signature and send" : "Sign with wallet";
    $("review").hidden = false;
    $("review").scrollIntoView({ block: "nearest" });
    say("Nothing is sent until you sign.");
  }
  function closeReview() { pending = null; $("review").hidden = true; }
  $("btn-cancel").addEventListener("click", () => {
    if (awaiting) { awaiting.cancel(); return; }      // waiting for a phone wallet: stop waiting, keep the review open
    if (busy) return;
    closeReview(); say("Cancelled. Nothing was sent.");
  });
  $("btn-copy").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("unsigned").value); say("Copied."); } catch { $("unsigned").select(); } });
  $("btn-sign").addEventListener("click", () => guarded(async () => {
    if (!pending) return;
    const { built, after, action } = pending;
    say(wallet.manual ? "Checking the signature…" : "Waiting for the wallet…");
    await nothingOnItsWay();
    const signed = await wallet.sign(L.crypto, built);            // refused unless it is this exact transaction, signed by the owner
    say("Checking the transaction on a node, without sending it…");
    // The contract is checked once more: signing can take minutes. (The
    // transaction itself also fails on any other version of the contract.)
    if ((await contractOk()) !== built.moduleHash) throw new L.Refused("The contract changed while you were signing. Nothing was sent. Start again and review it against the contract as it is now.");
    const dry = await node.dryRun(signed);
    if (!dry.ok) throw new L.Refused(`The chain would refuse this: ${dry.error} Nothing was sent.`);
    await nothingOnItsWay();                                       // another tab may have sent something meanwhile
    const key = signed.hash;
    sentWrite([...sentRead(), { key, title: built.title, kind: built.kind, id: action.id, account: signer.account, expires: built.expires }]);
    showSent(sentRead());
    try { await node.send(signed); }
    catch (err) {
      // Not knowing is not the same as not sent. The transaction stays written down and is looked for.
      closeReview();
      throw new L.Refused(`The node did not confirm that it received the transaction (${err.message}). It may still have arrived. This page keeps looking for transaction ${key}; press "Check again" in a moment. Nothing new can be sent until it is confirmed or expires.`);
    }
    closeReview();
    const started = Date.now();
    for (;;) {
      let out = null;
      try { out = await node.poll(key); } catch { /* the node did not answer; ask again */ }
      if (out) {
        sentDrop(key); showSent(sentRead());
        if (!out.ok) throw new L.Refused(`The chain refused the transaction: ${out.error}`);
        break;
      }
      const seconds = Math.round((Date.now() - started) / 1000);
      if (seconds > L.TTL_SECONDS + 60) throw new Error(`No block yet. Transaction ${key} may still be confirmed; press "Check again" later.`);
      say(`Sent. Waiting for a block, which usually takes under a minute: ${seconds}s… (transaction ${key})`);
      await new Promise(r => setTimeout(r, POLL_MS));
    }
    if (after) await after();
    await refresh();
    say(`Done: ${built.title.toLowerCase()}, allowance "${action.id}". Transaction ${key}.${built.kind === "create" ? " Keep the allowance id: you need it to open this allowance again." : ""}`);
  }));

  const offer = make => guarded(async () => { const made = await make(); await propose(made.action, made.after); });
  // An action is for the allowance on screen: the id comes from the view that was read, not from a text field.
  const mine = extra => { if (!view || view.id !== allowance) throw new L.Refused("Open an allowance first."); return { id: view.id, ...extra }; };
  $("form-create").addEventListener("submit", event => {
    event.preventDefault();
    offer(() => {
      const id = $("new-id").value.trim();
      return { action: { kind: "create", id, owner: signer.account, agentKey: $("new-agent").value.trim(), perPayment: $("new-per").value, dailyLimit: $("new-daily").value },
               after: async () => { $("in-id").value = id; $("new").open = false; closePanel(); await refresh(id); } };
    });
  });
  $("btn-pause").addEventListener("click", () => offer(() => ({ action: mine({ kind: "setPaused", paused: !view.paused }) })));
  $("btn-fund").addEventListener("click", () => offer(() => ({ action: mine({ kind: "fund", owner: signer.account, vault: view.vault, amount: $("move-amount").value }) })));
  $("btn-withdraw").addEventListener("click", () => offer(() => ({ action: mine({ kind: "withdraw", amount: $("move-amount").value }) })));
  $("form-move").addEventListener("submit", event => event.preventDefault());
  $("form-limits").addEventListener("submit", event => { event.preventDefault(); offer(() => ({ action: mine({ kind: "setLimits", perPayment: $("set-per").value, dailyLimit: $("set-daily").value }) })); });
  $("form-agent").addEventListener("submit", event => { event.preventDefault(); offer(() => ({ action: mine({ kind: "rotateAgent", agentKey: $("set-agent").value.trim() }) })); });
  $("form-seller").addEventListener("submit", event => event.preventDefault());
  $("btn-approve").addEventListener("click", () => offer(() => ({ action: mine({ kind: "approveSeller", payee: $("seller").value.trim() }) })));
  $("btn-remove").addEventListener("click", () => offer(() => ({ action: mine({ kind: "removeSeller", payee: $("seller").value.trim() }) })));
  $("btn-list").addEventListener("click", () => offer(() => { if (!view || view.listOn === null) throw new L.Refused("The current setting could not be read. Press Refresh first."); return { action: mine({ kind: "setSellersOnly", on: !view.listOn }) }; }));

  // ---- start
  guarded(async () => {
    config = L.checkConfig(window.AGENTPAY_OWNER_CONFIG);
    node = L.connect(config, L.crypto);
    $("net").textContent = `Network ${config.networkId}, chain ${config.chainId}, contract ${config.module}.`;
    $("net-chip").textContent = `${config.networkId} · chain ${config.chainId}`;
    const before = remembered();
    if (before.account) $("in-account").value = before.account;
    if (before.id) $("in-id").value = before.id;
    if (!(await contractOk())) { $("step-wallet").hidden = true; say("This page cannot be used right now.", true); return; }
    await reconcile();                       // a transaction sent on an earlier visit is looked for first
    $("btn-phone").hidden = !config.walletConnectProjectId;
    if (before.phone && config.walletConnectProjectId) {
      // A phone wallet connected on an earlier visit: use it again if the wallet still agrees.
      try { const got = await phoneWallet().restore(before.topic || undefined); if (got) await usePhone(got); } catch { /* connect again by hand */ }
    }
  });
})();
