/* Kadena AgentPay AI owner page.
 *
 * The owner signs with a wallet; this page holds no key. For each change it
 * builds the transaction, shows what it does and what the signature is good
 * for, takes the signature from the wallet, checks it, runs the transaction
 * on a node without sending it, and only then sends it.
 *
 * Needs AgentPayOwner (owner-lib.js) and AGENTPAY_OWNER_CONFIG (config.js).
 * The only things kept in the browser are the account name and the allowance
 * ids last used, so the page can show them again.
 */
(() => {
  "use strict";
  const L = window.AgentPayOwner;
  const $ = id => document.getElementById(id);
  const STORE = "agentpay-owner-v1";
  const POLL_MS = ["127.0.0.1", "localhost"].includes(location.hostname) ? 150 : 4000;
  let config, node, signer = null, wallet = null, allowance = null, view = null, pending = null, busy = false;

  const say = (text, bad = false) => { const s = $("status"); s.textContent = text; s.classList.toggle("bad", bad); };
  const note = (el, text, kind = "") => { el.textContent = text; el.className = `note ${kind}`.trim(); };
  const num = v => (v && typeof v === "object" ? Number(v.decimal ?? v.int ?? NaN) : Number(v));
  const show = v => { const n = num(v); return Number.isFinite(n) ? String(Number(n.toFixed(12))) : "?"; };
  const remember = () => { try { localStorage.setItem(STORE, JSON.stringify({ account: wallet && wallet.manual ? signer.account : "", id: allowance || "", phone: !!(wallet && wallet.phone) })); } catch { /* private mode */ } };
  const remembered = () => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } };
  const setBusy = on => { busy = on; document.querySelectorAll("button").forEach(b => { b.disabled = on && b.id !== "btn-cancel" && !b.classList.contains("live"); }); };

  async function guarded(work) {
    if (busy) return;
    setBusy(true);
    try { await work(); }
    catch (err) { say(err instanceof L.Refused || err instanceof Error ? err.message : "Something went wrong.", true); }
    finally { setBusy(false); }
  }

  // ---- the contract on the chain must be the reviewed one
  async function contractOk() {
    const check = await L.checkContract(config, node, L.reads);
    if (!check.ok) { note($("contract"), check.reason, "bad"); return false; }
    if (check.verified && config.singleNode) note($("contract"), `Test deployment: contract ${config.module} matches the reviewed version (hash ${check.hash}), but only one node was asked. Use small amounts.`, "warn");
    else if (check.verified) note($("contract"), `Contract ${config.module} matches the reviewed version (hash ${check.hash}), confirmed by ${check.answers.filter(a => a.ok).length} node(s).`, "good");
    else note($("contract"), `Test network: the contract ${config.module} (hash ${check.hash}) is not checked against a reviewed version.`, "warn");
    return true;
  }

  // ---- account
  async function useAccount(account, how) {
    const details = await node.read(L.reads.details(account));
    if (!details) throw new L.Refused("This account does not exist on this chain yet. It needs some KDA first, also to pay transaction fees.");
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
    note($("approve-text"), `Approve the request in ${p.wallet}. Check there that it shows the same purposes as listed above.`);
    const open = $("approve-open");
    open.hidden = !p.link;
    if (p.link) { open.href = p.link; open.textContent = `Open ${p.wallet}`; } else open.removeAttribute("href");
  }
  const phoneWallet = () => (phone = phone || L.walletConnect(wcClient, config.networkId, { onUri: showLink, onPending: showApproval }));
  const usePhone = got => useAccount(got.account, { ...phoneWallet(), name: got.wallet, publicKey: got.publicKey, phone: true });
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
  async function refresh() {
    const m = config.module;
    const a = await node.read(L.reads.allowance(m, allowance));
    if (!a) { $("panel").hidden = true; throw new L.Refused(`There is no allowance "${allowance}" on this chain.`); }
    const [balance, remaining, listOn] = await Promise.all([
      node.read(L.reads.vaultBalance(m, allowance)), node.read(L.reads.remaining(m, allowance)), node.read(L.reads.sellersOnly(m, allowance))]);
    view = { owner: a.owner, vault: a.vault, paused: a.paused === true, listOn: listOn === true };
    $("panel-title").textContent = `Allowance "${allowance}"`;
    const facts = [["Owner", a.owner], ["Vault account", a.vault], ["In the vault", `${show(balance)} KDA`],
      ["Per payment", `${show(a["per-payment"])} KDA`], ["Per day (UTC)", `${show(a["daily-cap"])} KDA`], ["Left today", `${show(remaining)} KDA`],
      ["Payments so far", `${show(a["payment-count"])} (${show(a["total-paid"])} KDA)`], ["Status", view.paused ? "Paused: the agent can pay nothing" : "Active"],
      ["Sellers", view.listOn ? "Approved sellers only" : "Any seller"]];
    $("facts").replaceChildren(...facts.flatMap(([k, v]) => { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = k; dd.textContent = v; return [dt, dd]; }));
    const mine = a.owner === signer.account;
    note($("mine"), mine ? "" : "This allowance belongs to another account. The chain will refuse changes signed by yours.", mine ? "" : "warn");
    $("btn-pause").textContent = view.paused ? "Resume payments" : "Pause all payments";
    $("btn-list").textContent = `Approved sellers only: ${view.listOn ? "on" : "off"}`;
    $("panel").hidden = false;
    remember();
  }
  $("form-open").addEventListener("submit", event => {
    event.preventDefault();
    guarded(async () => { allowance = $("in-id").value.trim(); L.reads.allowance(config.module, allowance); await refresh(); say(""); });
  });
  $("btn-refresh").addEventListener("click", () => guarded(async () => { await refresh(); say(""); }));

  // ---- review, sign, check, send
  async function propose(action, after) {
    if (!signer) throw new L.Refused("Connect your account first.");
    if (!(await contractOk())) throw new L.Refused("The contract could not be confirmed. Nothing can be signed.");
    const built = L.buildCommand(config, signer, action);
    pending = { built, after };
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
  const closeReview = () => { pending = null; $("review").hidden = true; };
  $("btn-cancel").addEventListener("click", () => {
    if (awaiting) { awaiting.cancel(); return; }      // waiting for a phone wallet: stop waiting, keep the review open
    if (busy) return;
    closeReview(); say("Cancelled. Nothing was sent.");
  });
  $("btn-copy").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("unsigned").value); say("Copied."); } catch { $("unsigned").select(); } });
  $("btn-sign").addEventListener("click", () => guarded(async () => {
    if (!pending) return;
    const { built, after } = pending;
    say(wallet.manual ? "Checking the signature…" : "Waiting for the wallet…");
    const signed = await wallet.sign(L.crypto, built);            // refused unless it is this exact transaction, signed by the owner
    say("Checking the transaction on a node, without sending it…");
    const dry = await node.dryRun(signed);
    if (!dry.ok) throw new L.Refused(`The chain would refuse this: ${dry.error} Nothing was sent.`);
    const key = await node.send(signed);
    closeReview();
    const started = Date.now();
    for (;;) {
      const out = await node.poll(key);
      if (out) {
        if (!out.ok) throw new L.Refused(`The chain refused the transaction: ${out.error}`);
        break;
      }
      const seconds = Math.round((Date.now() - started) / 1000);
      if (seconds > L.TTL_SECONDS + 60) throw new Error(`No block yet. Transaction ${key} may still be confirmed; press Refresh later.`);
      say(`Sent (${key}). Waiting for a block: ${seconds}s…`);
      await new Promise(r => setTimeout(r, POLL_MS));
    }
    if (after) await after();
    await refresh();
    say(`Done: ${built.title.toLowerCase()}. Transaction ${key}.`);
  }));

  const offer = make => guarded(async () => { const made = await make(); await propose(made.action, made.after); });
  const mine = extra => ({ id: allowance, ...extra });
  $("form-create").addEventListener("submit", event => {
    event.preventDefault();
    offer(() => {
      const id = $("new-id").value.trim();
      return { action: { kind: "create", id, owner: signer.account, agentKey: $("new-agent").value.trim(), perPayment: $("new-per").value, dailyLimit: $("new-daily").value },
               after: () => { allowance = id; $("in-id").value = id; $("new").open = false; } };
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
  $("btn-list").addEventListener("click", () => offer(() => ({ action: mine({ kind: "setSellersOnly", on: !view.listOn }) })));

  // ---- start
  guarded(async () => {
    config = L.checkConfig(window.AGENTPAY_OWNER_CONFIG);
    node = L.connect(config, L.crypto);
    $("net").textContent = `Network ${config.networkId}, chain ${config.chainId}, contract ${config.module}.`;
    const before = remembered();
    if (before.account) $("in-account").value = before.account;
    if (before.id) $("in-id").value = before.id;
    if (!(await contractOk())) { $("step-wallet").hidden = true; say("This page cannot be used right now.", true); return; }
    $("btn-phone").hidden = !config.walletConnectProjectId;
    if (before.phone && config.walletConnectProjectId) {
      // A phone wallet connected on an earlier visit: use it again if the wallet still agrees.
      try { const got = await phoneWallet().restore(); if (got) await usePhone(got); } catch { /* connect again by hand */ }
    }
  });
})();
