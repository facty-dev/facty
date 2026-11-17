# ADR-0011 — Web UI stack: Svelte 5 + Vite compiled to a static app, served by `facty serve`

**Date:** 2026-11-17
**Status:** proposed
**Related:** [ADR-0010](0010-triadic-runtime-parity.md) (Web UI is the primary demo
surface; UI is a pure client — "no logic lives in the UI"),
[ADR-0005](0005-cleanroom-stack-replaces-poc.md) (one SmolVM image, egress allow-list),
[USE-CASE-DOC-ASSEMBLY.md](../USE-CASE-DOC-ASSEMBLY.md) (the UI surfaces to build:
intent box, wizard/chat, Proven/Open/Anomalies bullseye, hypothesis graph,
proof tree, packet preview).
Research log: [docs/research/deps-log.md](../research/deps-log.md) (Web UI stack entry, 2026-11-17).

## What problem are we solving?

Slice 1 step 4 needs a Web UI that demos Facty to non-developers (lawyers,
journalists, claims people) and stays a *thin rendering layer* over committed
TerminusDB state. The stack must survive the SmolVM runtime constraints, not just
the demo.

## What constraints do we have?

- **Runtime egress is an allow-list** (api.mistral.ai, registry.npmjs.org,
  api.uprelic.com). No CDN at runtime → **every JS byte must be baked into the
  OCI image at build time**; build-time egress is the host's (Dockerfile), so
  `npm ci` happens in a Docker **builder stage** only.
- **No logic in the UI** (ADR-0010): the UI calls `facty serve` JSON ops + TDB
  reads and renders the result; the verdict path never touches it.
- **Parity**: CLI ↔ Web UI both clients of `facty serve`; the UI must not
  invent a second op set.
- **Surfaces required** (USE-CASE-DOC-ASSEMBLY.md): questionnaire wizard + chat
  (switchable per turn), live SSE-driven bullseye (Proven/Open/Anomalies),
  hypothesis graph (status colors, `prunedBy`, score-sized nodes), proof-tree
  panel, turn timeline, assembled-packet preview with print-to-PDF.
- **Licensing/ethos**: permissively licensed, open-source deps only; the project
  avoids US-closed-model lock-in, so no vendor SDKs.
- **Image size & auditability**: the runtime image should stay lean and the UI
  code reviewable in git (source, not just a bundle).

## Decision drivers

1. Zero runtime egress / baked static assets (hard constraint).
2. Live-updating viz (SSE → reactive re-render) with minimal hand-rolled code.
3. Maintainability for a Python shop (SFCs vs hand-rolled DOM).
4. Payload size (hypothesis graphs are tens of nodes — no heavy graph engine).
5. License hygiene.

## Considered options

Facts verified against primary sources 2026-11-17 (npm registry metadata +
official docs; details in deps-log):

| Option | Build | Runtime payload | Live viz fit | License | Verdict |
|---|---|---|---|---|---|
| **Svelte 5 + Vite → static dist** | `vite build` in Docker builder stage (node 22; vite 8 needs node ^20.19/22.12+) | compiled app only (framework is compile-time; svelte 5.57.3 itself is dev-only) + d3-force 53KB + marked 592KB unpacked | runes (`$state`/`$derived`/`$effect`) make SSE-driven state trivial | MIT | **chosen** |
| Vanilla ES modules, no build | none | hand-written JS + vendored libs | hand-rolled reactivity | n/a | fallback if build step ever hurts |
| React 19 + Vite | same builder stage | react-dom 7.9MB unpacked (~130KB gz) + app | hooks, fine but more boilerplate | MIT | viable, heavier, rejected for a thin client |
| htmx 2 server-rendered by `facty serve` | none | htmx ~14KB min.gz (0BSD), SSE via `hx-ext="sse"`/`sse-connect` | SSE swaps are attribute-driven, but the live graph/bullseye would need server-generated SVG | 0BSD | good for pure forms; rejected for the live graph |
| Lit web components | optional | ~5KB runtime + components | reactive properties | BSD-3 | middle ground; less panel ecosystem |

Graph library sub-decision: **d3-force 3.0.1 (ISC, 53KB)** rendered to hand-rolled
SVG — hypothesis graphs are tens of nodes, a force layout is plenty. Rejected:
cytoscape 3.35.0 (MIT but 5.7MB unpacked — overkill), elkjs 0.12.1 (8MB **and**
EPL-2.0 OR GPL-3.0 — license friction with our Apache-2.0 project).

## Decision

**Svelte 5 (SFCs, runes, plain JS) + Vite 8, compiled at image build to
`web/dist/`, served as static files by `facty serve` (stdlib `http.server`)
under `/`; app code lives in `web/src/` in git. Deps pinned by a committed
`package-lock.json` (`npm ci` in the builder stage). Runtime image gets only
`web/dist/` — no node, no npm, no runtime egress beyond the allow-list.**

- Hypothesis graph + bullseye: SVG, layout via `d3-force`.
- Packet preview: `marked` (MIT) rendering the committed `AssembledDocument`
  Markdown; PDF via browser print (demo), real renderer later.
- Dockerfile becomes multi-stage: `FROM node:22-bookworm AS ui-builder` →
  `npm ci && vite build`; final stage `COPY --from=ui-builder /ui/dist ./web/dist`.
- Vite config: `base: "./"` (relative assets — the UI must serve under whatever
  prefix `facty serve` uses, per vite.dev/guide/build.html).

## Component layer & app shell (survey 2026-11-17, deps-log)

Most-starred + actively maintained Svelte-native options (GitHub stars /
last push / license, all checked 2026-11-17):

| Candidate | Stars | Last push | License | Svelte 5 | Verdict |
|---|---|---|---|---|---|
| **shadcn-svelte** (huntabyte) on **bits-ui** | 9.3k / 3.7k | 2026-11-16/17 | MIT | yes (bits-ui v2.21 peers svelte 5) | **chosen** |
| Skeleton v4 (skeletonlabs) | 6.1k | 2026-11-17 | MIT | yes (Tailwind v4) | optional theming layer |
| flowbite-svelte | 2.8k | 2026-06-27 | MIT | partial | rejected: stale, and Skeleton docs warn against mixing |
| svelteui, sveltestrap, attractions | 1.4k/1.3k/deprecated | — | — | legacy | rejected |
| Svelvet (node graphs) | 2.8k | 2025-02-13 | MIT | no recent | rejected: stale — keep d3-force SVG |

App shells: **no well-maintained Svelte-native admin shell exists**
(flowbite-svelte-admin-dashboard 512★ stale 2025-11; CMSaasStarter 2.4k★ but
Supabase/Stripe-coupled; notus-svelte, salvia-kit stale). The portable
most-starred pattern source for shells is **shadcn-svelte's Blocks library**
(sidebar app-shell blocks, dashboard blocks) — copy-paste source we own and
extend. Cross-framework giants (AdminLTE 45.7k★, ngx-admin 25.7k★,
next-shadcn-dashboard-starter 7.3k★) are pattern references only.

Decision: **component layer = shadcn-svelte** (CLI `npx shadcn-svelte add …`
copies component source into `web/src/lib/components/ui/` — we own the code,
no registry lock-in) on bits-ui + **Tailwind CSS v4** (`@tailwindcss/vite`
4.3.5, peers vite ^8) + `tw-animate-css` + `clsx` + `tailwind-merge`, all MIT.
Notably its component set maps 1:1 onto our panels: **Sidebar** (app shell),
**Command** (palette), **Data Table**, **Field/Forms** (questionnaire),
**Questionnaire**, **Trace** (proof trees), AI Elements **Chat** (chat mode),
**Sonner** (toasts). Graph stays d3-force → SVG; packet stays `marked`.

**Theming (Skeleton v4 presets in concert with bits-ui):** Skeleton ships 24
preset themes as plain CSS (`@import "@skeletonlabs/skeleton/themes/{name}"`),
each defining light+dark variants of Tailwind v4's `--color-*` scale plus
spacing/radius/typography tokens under `[data-theme="{name}"]` on `<html>` —
so bits-ui/shadcn-svelte components pick the palette up automatically; map
Skeleton's `--color-primary-*`/`--color-surface-*` onto shadcn's
`--primary`/`--background` vars in our global CSS to theme the shadcn
components too. A theme switcher = flipping the `data-theme` attribute.
Register only the themes we ship (each adds CSS bundle bytes). **Default preset:
`wintry`** (PO pick 2026-11-17 — cold indigo-violet primary `oklch(62.31% 0.19
259.81deg)`, cool near-white surfaces, deep navy dark mode; fits the detective
brand), with `terminus`/`sahara`/`cerberus` as alternates behind the same
`data-theme` switcher. Custom Facty brand theme later via the
themes.skeleton.dev generator; tweakcn (shadcn-native editor) as the
alternative. Fonts via Fontsource, baked at build. Details: deps-log 2026-11-17.

## Consequences

- Positive: smallest honest runtime (static files only), fully offline in the
  VM, reactive SSE viz with little code, UI logic reviewable as Svelte source,
  all deps MIT/ISC/0BSD.
- Costs accepted: a build step in the Dockerfile and a pinned node toolchain in
  the builder stage; Svelte is a new tool for a Python shop (small learning
  curve, single-file components); bundle output in `web/dist` is gitignored and
  rebuilt, source is the source of truth.
- Rejected explicitly: SvelteKit (we already have a backend — `facty serve` —
  and ADR-0010 forbids logic in the UI), CDN links (runtime egress), elkjs
  (license), cytoscape (size).
- Re-evaluate when: the UI needs SSR/SEO (not a Facty use case — operators are
  authenticated humans), or graphs grow to thousands of nodes (then canvas/
  WebGL, e.g. reagraph-class libs).
