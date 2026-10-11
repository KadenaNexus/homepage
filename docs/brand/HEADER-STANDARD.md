# Kadena Nexus site header standard

Every Kadena Nexus product site (every `*.kadena.ws` subdomain) opens with the same brand bar, so visitors always know the site belongs to Kadena Nexus and can get back to kadena.ws in one click. The homepage (kadena.ws) is the parent and is the only exception.

Reference implementations: [nodes.kadena.ws](https://github.com/KadenaNexus/network-monitor/blob/main/client/index.html) and [kadenadevs.kadena.ws](https://github.com/KadenaNexus/devs-site/blob/main/static-site/index.html).

## The rules

1. **Left side, in this order:** the Kadena Nexus mark (32 px wide), the product name, a thin vertical divider, then the text link **Part of Kadena Nexus** pointing to `https://kadena.ws/`.
2. **Product name** is always the full name: Kadena Network Monitor, Kadena P2P Marketplace, Kadena Earn, Kadena Adoption Index, Quantum-Safe Kadena, Kadena Devs, Kadena Garden, ChainProof, Kadena AgentPay AI, KadenaTrace, Kadena Privacy. Display font (Bricolage Grotesque) 700, 1.1 rem.
3. **"Part of Kadena Nexus"**: body font (Instrument Sans), 0.85 rem, muted color (`--mist`), no underline, 1 rem left padding with a 1 px left border in the line color. Exactly this wording; never "Part of the Kadena Nexus Ecosystem" or similar.
4. **Right side:** the site's own navigation and actions (theme toggle, wallet, sign-in). Free per site.
5. **Mobile (under 900 px):** the "Part of Kadena Nexus" link may hide to save space, but then the footer must carry it (rule 6).
6. **Footer** always includes "Part of Kadena Nexus" linking to `https://kadena.ws/`, and a link to `https://github.com/KadenaNexus` for public products.
7. **Page title:** `<Product name> | Kadena Nexus` (for example `Kadena Earn | Kadena Nexus`). The browser tab and link previews then show the parent brand too.
8. **Favicon:** the Kadena Nexus mark (`nexus-mark.png` in this folder), unless the product has an approved mark of its own.
9. **Colors:** use the shared tokens (teal `#1C637B`, orange `#E2710A`, ink/sand/mist/line); dark mode follows `prefers-color-scheme` plus a toggle.

A new product is not ready to launch until it meets rules 1, 6 and 7.

## Drop-in HTML and CSS

```html
<header class="nx-top">
  <div class="nx-wrap">
    <a class="nx-brand" href="/">
      <img src="/nexus-mark.png" width="32" alt="">
      <span>Kadena Earn</span>
    </a>
    <a class="nx-part" href="https://kadena.ws/">Part of Kadena Nexus</a>
    <!-- site navigation goes here -->
  </div>
</header>
```

```css
.nx-wrap{display:flex;align-items:center;gap:1rem;max-width:72rem;margin:0 auto;padding:.9rem 1.25rem}
.nx-brand{display:flex;align-items:center;gap:.6rem;text-decoration:none;font:700 1.1rem/1 "Bricolage Grotesque",system-ui,sans-serif;color:var(--sand,#123A48);white-space:nowrap;min-width:0}
.nx-brand img{width:32px;height:auto}
.nx-part{font:400 .85rem/1 "Instrument Sans",system-ui,sans-serif;color:var(--mist,#4F6B76);text-decoration:none;padding-left:1rem;border-left:1px solid var(--line,#D6E0E4);white-space:nowrap}
.nx-part:hover{color:var(--sand,#123A48)}
@media (max-width:900px){.nx-part{display:none}}
```

## React / Next.js

```tsx
export function NexusBrand({ name }: { name: string }) {
  return (
    <>
      <a className="nx-brand" href="/">
        <img src="/nexus-mark.png" width={32} alt="" />
        <span>{name}</span>
      </a>
      <a className="nx-part" href="https://kadena.ws/">Part of Kadena Nexus</a>
    </>
  );
}
```

## Status (Oct 2026)

| Site | Brand bar | Footer link | Title |
|---|---|---|---|
| nodes.kadena.ws | yes | yes | yes |
| kadenadevs.kadena.ws | yes | yes | yes |
| marketplace.kadena.ws | in the restyle (branch nexus-restyle) | in the restyle | yes |
| earn.kadena.ws | pull request open | pull request open | pull request open |
| adoption.kadena.ws | pull request open | pull request open | pull request open |
| quantum.kadena.ws | issue open (source not yet in GitHub) | | |
