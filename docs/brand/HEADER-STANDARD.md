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
8. **Favicon:** the Kadena Nexus mark (`nexus-mark.png` in this folder), unless the product has an approved mark of its own. Every site ships real icon files, not just an inline image:
   - `favicon.ico` (16, 32 and 48 px), `apple-touch-icon.png` (180 px) and `nexus-mark.png` (or `favicon.svg`) at the site root, and listed in the deploy workflow's `files` so they actually go live.
   - In `<head>`, in this order: `<link rel="icon" href="/favicon.ico" sizes="any">`, `<link rel="apple-touch-icon" href="/apple-touch-icon.png">`, then `<link rel="icon" type="image/png" href="/nexus-mark.png">`.
   - The **last** `rel="icon"` link must be a real file path, never a `data:` URI. Wallets such as eckoWALLET show the icon of the last link when asking to connect, and they cannot load a `data:` URI.
   - Icon files must be served with `Cross-Origin-Resource-Policy: cross-origin`. Without it (helmet's default is `same-origin`) the wallet's connect window shows a broken image. In Express: `app.use(['/favicon.ico','/favicon.svg','/nexus-mark.png','/apple-touch-icon.png'],(req,res,next)=>{res.setHeader('Cross-Origin-Resource-Policy','cross-origin');next();});`. In nginx: `add_header Cross-Origin-Resource-Policy cross-origin;` on those paths.
9. **Colors:** use the shared tokens (teal `#1C637B`, orange `#E2710A`, ink/sand/mist/line); dark mode follows `prefers-color-scheme` plus a toggle.
10. **Nothing overlaps, at any width.** Check the header after signing in (a connected wallet adds a long address) at 1440, 1280, 1024, 900, 870, 768, 390 and 360 px. Nothing may overlap, be pushed off screen, or be cut in half. When space runs out, shrink in this order and stop as soon as it fits:
    1. tighter gaps and padding;
    2. a shorter wallet address (`k:abcd…wxyz`);
    3. shorter nav labels (keep a `data-short` label on each nav item, for example "Leaderboard" becomes "Leaders");
    4. let the nav scroll sideways inside its own box (`overflow-x:auto`), never the whole page.

    Never hide the wallet or the sign-in button to make room; the user must always see that they are connected. The product name may shorten with an ellipsis but the mark and "Kadena Nexus" link stay (the link hides only under rule 5). A script that measures and steps through these levels on resize is fine (Earn's `fitHeader()` in `public/app.js` is the reference); guard it so it also runs in tests without a browser (`window.addEventListener?.(...)`).

A new product is not ready to launch until it meets rules 1, 6, 7, 8 and 10. It must also deploy automatically from GitHub; see [DEPLOY-STANDARD.md](../DEPLOY-STANDARD.md).

## Drop-in HTML and CSS

```html
<header class="nx-top">
  <div class="nx-wrap">
    <a class="nx-brand" href="/">
      <img src="/nexus-mark.png" width="32" alt="">
      <span>Kadena Earn</span>
    </a>
    <a class="nx-part" href="https://kadena.ws/">Part of Kadena Nexus</a>
    <nav class="nx-nav"><!-- site links --></nav>
    <div class="nx-actions"><!-- theme toggle, wallet, sign-in --></div>
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
/* rule 10: never overlap */
.nx-brand span{overflow:hidden;text-overflow:ellipsis}
.nx-nav{display:flex;gap:1rem;min-width:0;overflow-x:auto;scrollbar-width:none}
.nx-nav::-webkit-scrollbar{display:none}
.nx-actions{display:flex;align-items:center;gap:.5rem;flex-shrink:0;margin-left:auto}
```

Put the site's links in `<nav class="nx-nav">` and the theme toggle, wallet and sign-in in `<div class="nx-actions">`, so the actions never get squeezed and the nav is what gives way.

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

## Status (12 Oct 2026)

| Site | Brand bar | Footer link | Title | Icon files (rule 8) |
|---|---|---|---|---|
| nodes.kadena.ws | yes | yes | yes | **no**: inline `data:` icon only, `/favicon.ico` returns 404 (the deploy ships only `index.html`) |
| kadenadevs.kadena.ws | yes | yes | yes | yes |
| marketplace.kadena.ws | yes | yes | yes | partly: `nexus-mark.png` link only; add the `favicon.ico` and `apple-touch-icon` links |
| earn.kadena.ws | yes | yes | yes | yes, including the cross-origin header |
| adoption.kadena.ws | yes | yes | yes | yes (`favicon.svg` last) |
| quantum.kadena.ws | yes | yes | yes | yes |

Rule 10 has been checked on Earn (fixed 12 Oct after the address pushed "Part of Kadena Nexus" off screen). The other sites have no wallet in the header except the Marketplace, which should be checked at the widths above.
