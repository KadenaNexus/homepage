// Fetches each site twice (30 s apart) before calling it down, so a single slow
// response does not raise an alarm. One issue per site, labelled "uptime".
const SITES = [
  ['kadena.ws', 'https://kadena.ws/'],
  ['Network Monitor', 'https://nodes.kadena.ws/'],
  ['P2P Marketplace', 'https://marketplace.kadena.ws/'],
  ['Earn', 'https://earn.kadena.ws/'],
  ['Adoption Index', 'https://adoption.kadena.ws/'],
  ['Quantum-Safe Kadena', 'https://quantum.kadena.ws/'],
  ['Kadena Devs', 'https://kadenadevs.kadena.ws/'],
  ['Kadena Garden', 'https://mine.kadena.ws/'],
];
const LABEL = 'uptime';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function probe(url) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 20000);
  try {
    const res = await fetch(url, { redirect: 'follow', signal: ctl.signal, headers: { 'user-agent': 'kadena-nexus-uptime' } });
    return { ok: res.status < 500 && res.status !== 404, detail: `HTTP ${res.status}` };
  } catch (e) {
    return { ok: false, detail: e.name === 'AbortError' ? 'timeout after 20 s' : (e.cause?.code || e.message) };
  } finally {
    clearTimeout(t);
  }
}

module.exports = async ({ github, context, core }) => {
  const { owner, repo } = context.repo;
  const results = [];
  for (const [name, url] of SITES) {
    let r = await probe(url);
    if (!r.ok) { await sleep(30000); r = await probe(url); }
    results.push({ name, url, ...r });
  }
  const open = await github.paginate(github.rest.issues.listForRepo, { owner, repo, state: 'open', labels: LABEL, per_page: 100 });
  const now = new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  let failures = 0;
  for (const r of results) {
    const title = `Down: ${r.name} (${r.url})`;
    const existing = open.find((i) => i.title === title);
    if (!r.ok) {
      failures++;
      if (existing) {
        await github.rest.issues.createComment({ owner, repo, issue_number: existing.number, body: `Still down at ${now}: ${r.detail}` });
      } else {
        await github.rest.issues.create({ owner, repo, title, labels: [LABEL],
          body: `${r.url} failed two checks 30 s apart at ${now}: **${r.detail}**.\n\nThis issue closes itself when the site answers again. Check nginx, the process manager (pm2) and the certificate on the server.` });
      }
      core.error(`${r.name} is down: ${r.detail}`);
    } else if (existing) {
      await github.rest.issues.createComment({ owner, repo, issue_number: existing.number, body: `Back up at ${now} (${r.detail}).` });
      await github.rest.issues.update({ owner, repo, issue_number: existing.number, state: 'closed' });
    }
    core.info(`${r.ok ? 'OK  ' : 'DOWN'} ${r.name} ${r.detail}`);
  }
  if (failures) core.setFailed(`${failures} site(s) down`);
};
