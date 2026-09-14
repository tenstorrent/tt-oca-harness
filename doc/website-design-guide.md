# OCAH Documentation Website — Design & Maintenance Reference

This document describes how the OCAH documentation website is built, styled, and structured, for anyone maintaining or extending it. 
It complements the contributor-facing guide (`documentation.adoc`), which covers writing and building content.
This document covers the site itself: layout, styling, navigation, and the underlying design decisions.

---

## Architecture Overview

The site is built with [Antora](https://antora.org), a static site generator for multi-component AsciiDoc documentation. It publishes **one combined site** covering a landing page and five books ("components," in Antora's terminology):

| Section | Antora component name | Has a PDF? |
|---|---|---|
| Home (landing page) | `ocah-home` | No  |
| Technical Reference Manual | `ocah-docs` | Yes |
| Integrator Guide | `ocah-integrator-guide` | Yes |
| Programmer's Guide | `ocah-programmer-guide` | Yes |
| Application Notes | `ocah-appnotes` | Yes |
| Getting Started Guide | `ocah-starting` | Yes |

**Home is the site's entry point.** `antora-playbook.yml`'s `site.start_page` points at `ocah-home::index.adoc`. 
Home is genuinely separate front-matter content (feature overview, motivation, use cases, licensing) rather than a book, and is structured as independent linked pages rather than a book-style `include::` chain.

All six components are built in a single Antora invocation, driven by one playbook at the repository root: `antora-playbook.yml`. 
This is what makes cross-book navigation and the book/version switcher panel work natively — Antora is aware of every component at once, 
rather than the site being stitched together from separately-built pieces.

Each component also has its own standalone playbook (`antora-<name>-playbook.yml`) for building just that one component in isolation 
during content development, and its own `doc.mk` build fragment. The combined playbook is what actually gets published; the standalone 
ones are a convenience for iterating on a single component without a full site build.

PDF output is entirely separate from the HTML build — it uses `asciidoctor-pdf` directly against each component's `src/` tree, with no Antora involvement. HTML and PDF share the same underlying `.adoc` source files but are assembled independently.

Deployment is via GitHub Actions (`.github/workflows/doc.yml`), which builds and publishes to the `gh-pages` branch on every push to `main`.
### Every component stages its own full copy of the shared hardware documentation

This is the single most important architectural fact for anyone editing content under `hw/`.

`doc/stage-docs.sh` runs once per component during its build `-setup` step. 
For **every** component — including Home and the Getting Started Guide, neither of which has any content directly about SEP, SMC, DTP, or the IP catalog — it stages five Antora modules: 
- `ROOT` (that component's own pages) 
- `smc`, `sep`, `dtp`
- `ip` (a full, independent copy of the shared hardware documentation from `hw/sys/{smc,sep,dtp}/doc` and every `hw/ip/*/doc`, plus vendor overlay register partials).

Practically, this means:
- Editing a file under `hw/sys/smc/doc/` or `hw/ip/*/doc/` affects **every** component's build, not just whichever book you think of as "the SMC book" or "the peripherals book" — there isn't one; the same source is duplicated six times over.
- The same peripheral or subsystem page can be reached at a different URL under each component's own namespace (e.g. a page might appear under both `/ocah-docs/latest/ip/...` and `/ocah-home/latest/ip/...`), since each component's copy is genuinely independent, not a shared reference.
- A full site rebuild is required to see a hardware-doc change reflected everywhere; rebuilding a single component's own standalone playbook only refreshes that one component's copy.
- This is a deliberate, working design but it is a real build-time and output-size cost worth being aware of.
### Register-table and shared-content includes are staged the same way

Two specific patterns rely on this staging mechanism and are worth knowing separately:

- **Register tables.** PeakRDL-generated register documentation is staged as matched pairs, wired into content via the dual-backend `ifdef::backend-html5[]`/`ifdef::backend-pdf[]` pattern described later.
  - an `.html` partial (for Antora/HTML)
  - a corresponding `.adoc` partial (for the direct PDF build) with the same basename
- **Port declaration tables.** A small number of subsystem port-declaration tables (`hw/sys/{smc,sep,dtp,smu}/doc/port_table.adoc`) are staged specifically into the `ROOT` module's `partials/hw/<system>/doc/` path, for the Integrator Guide to reference directly.

---
## Page Anatomy

Every page on the site is assembled from the stock Antora default UI theme, with a set of deliberate overrides layered on top. The override mechanism is Antora's `ui.supplemental_files` feature: any file placed under `doc/ui-supplemental/`, at the same relative path as a file inside the UI theme bundle, replaces that file when the site is built. This is how every customization described below is applied, without maintaining a fork of the underlying theme.
### Top navbar

Controlled by `doc/ui-supplemental/partials/header-content.hbs`, a full override of the theme's default header partial.

The navbar contains:
- The OCA logo and site title, in-flow (not centered — centering caused overlap with the menus at narrower widths). **The logo is the site's link back to Home**.
- A search box.
- Three dropdown menus: 
  - **Guides** links to each book's home page — Getting Started, TRM, Integrator Guide, Programmer's Guide, Application Notes, in that order 
  - **Downloads** PDF downloads for every book that has one — all five except Home
  - **Datasheets** per-subsystem datasheet PDFs, kept as a separate menu from Downloads for clarity, since combining them read as cluttered.
- A Tenstorrent logo linking to tenstorrent.com.

The Guides/Downloads/Datasheets menus are static, hand-written link lists rather than dynamically generated from Antora's component catalog. 
This is a deliberate choice: dynamic generation would require relying on Handlebars helpers not verified to exist in the exact UI bundle version in use, 
and a static list is more robust at the cost of one extra line to add whenever a new book or download is introduced.

All navbar links use `{{{siteRootPath}}}` (Antora's built-in "path back to the site root" variable) rather than absolute or component-relative paths, 
since the site is one combined build — every page can reach any other page via a path relative to the shared root.

**CAUTION - if adding new menu items**
The stock theme has a blanket CSS rule hiding unrecognized `.navbar-item` elements (originally meant to hide unused demo content). 
Any new navbar item — including new dropdown menus — needs an explicit exception added to this rule's `:not(...)` list in `extra.css`, or it will render invisible despite being present in the HTML. 

### Left sidebar (page navigation)

This is Antora's native, content-driven navigation tree — generated automatically from each component's `nav.adoc` file (e.g. `doc/trm/modules/ROOT/nav.adoc`) and the heading structure of the pages it references. 

For the book components, this is deliberately kept **flat, at chapter level only** — no deep per-section sub-entries. 
This matches the single-file PDF's own chapter structure and avoids the numbering/duplication problems that arise if HTML and PDF chapter structures diverge.

Getting Started's `nav.adoc` groups its eight sub-pages into two labeled sections rather than a flat list, since Getting Started's content is two audiences' worth of material.
The matching PDF structure achieves the same visual grouping via two `== ` group headings with `leveloffset=+1` applied to the includes underneath each, so the included 
pages nest correctly one level below the group heading rather than becoming siblings of it.

Below the navigation tree sits a collapsible panel (`.nav-panel-explore`, toggled via the `.context-bar` strip) — Antora's native book/version switcher. 
It lists every component known to the combined playbook automatically, including Home; adding a new component to `content.sources` is the only thing needed to make it appear here, no additional code.

### Right-hand contents panel

This is Antora's automatic per-page table of contents, generated from the current page's own heading structure. 
It is not manually maintained and has received no customization beyond basic color/typography styling to match the rest of the site.

Antora numbers sections **per page**, not per site. 
Since chapters are deliberately kept as single assembled pages (matching the PDF), this doesn't cause numbering gaps within a chapter
but numbering does restart at 1 for each separate top-level chapter (e.g. the Architecture chapter and a following chapter each start their own numbering), 
which differs from the PDF's continuous numbering across the whole document. 
This has been accepted as a reasonable trade-off since resolving it would mean merging chapters into ever-longer single pages. 
Home deliberately opts out of section numbering altogether (no `sectnums` attribute set in `doc/home/antora.yml`).

### Footer

Controlled by `doc/ui-supplemental/partials/footer-content.hbs`. 
Contains a short OCA/Tenstorrent message, the Tenstorrent logo linking out, and the MPL-2.0 license attribution for the underlying Antora UI theme, 
kept as de-emphasized fine print rather than removed (a licensing compliance requirement, not a stylistic choice).

This same file is also where the site's two custom `<script>` tags are loaded, at the very end of the body (after the footer markup, so anything they need to find in the DOM already exists by the time they run):
- `js/keyboard-shortcuts.js` — keyboard-navigation shortcuts for the site.
- `js/a11y-patches.js` — runtime accessibility patches for gaps in the stock theme's markup that can't be fixed with CSS alone.

---

## Styling and Overrides to the Native Antora Theme

All custom CSS lives in `doc/ui-supplemental/css/`, in these files, each linked explicitly from `doc/ui-supplemental/partials/head.hbs`:

- **`extra.css`** — the primary stylesheet: color palette, typography, navbar/sidebar/footer/switcher styling, mobile fixes, the dashboard mockup, 
accessibility color-contrast overrides, and general table-width handling.
- **`image-zoom.css`** — a zoom-in cursor and slight hover-dim on inline document images.

There is no `@import` between these files or any other stylesheet — every stylesheet the site depends on (`site.css` from the theme itself, 
`extra.css`, `image-zoom.css`) is linked explicitly and individually from `head.hbs`. 
Explicit links make every active stylesheet visible directly in the page source.

### Color palette

Defined as CSS custom properties at the top of `extra.css`, sourced from openchipletatlas.org's own site:

| Variable                | Hex       | Role                                                                                                                             |
| ----------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `--oca-green`           | `#103525` | Primary dark green — sidebar, headings, footer                                                                                   |
| `--oca-cream`           | `#EEEAE0` | Navbar/table header background                                                                                                   |
| `--oca-cream-light`     | `#F8F4EB` | Lighter alternate background                                                                                                     |
| `--oca-gold`            | `#F6BC42` | Hover/accent states                                                                                                              |
| `--oca-gold-accessible` | `#937027` | Darkened variant of `--oca-gold` for use as text/link color on light backgrounds — gold itself fails contrast as foreground text |
| `--oca-orange`          | `#F6931E` | Button/pill accents (switcher panel, version badges)                                                                             |
| `--oca-text`            | `#484848` | Body text                                                                                                                        |

### Typography

Three variables (`--oca-font-display`, `--oca-font-body`, `--oca-font-mono`), each a font stack, with the real Tenstorrent/OCA brand fonts now integrated (not a placeholder):

| Variable             | Fonts                                                                                        | Used for          |
| -------------------- | -------------------------------------------------------------------------------------------- | ----------------- |
| `--oca-font-display` | Degular Display (Light 300 / Medium 500), falling back to Georgia/Iowan Old Style/serif      | Headings          |
| `--oca-font-body`    | Neue Haas Unica Pro (Regular 400 / Medium 500), falling back to system sans-serif            | Body text, navbar |
| `--oca-font-mono`    | Berkeley Mono (Regular/Bold, both with an Oblique variant), falling back to system monospace | Code blocks       |

Font files are staged under `doc/ui-supplemental/fonts/` and declared via `@font-face` at the top of `extra.css`, each with `font-display: swap` 
so text renders immediately in a fallback font while the real one downloads. 

### What's overridden from the stock theme, and why

- **Navbar background, item colors, dropdown behavior** — recolored to the OCA palette; dropdown open/close behavior is made explicit in CSS (rather than relying on the theme's own hover CSS) for reliability.
- **Left sidebar and switcher panel** — recolored dark green with white text; the switcher panel itself is styled as a cream card with a green border for contrast against the dark sidebar.
- **Headings, body text, links, code blocks** — recolored/re-fonted to match the palette, scoped to `.doc` (Antora's content wrapper class) so the change only applies to actual document content, not UI chrome.
- **Footer** — recolored dark green, matching the navbar/sidebar treatment, with a grid layout that keeps the message block centered while pinning the OCA logo to the left edge.
- **Mobile navbar** .
- **Register tables (bit-layout)** — the PDF register generator (PeakRDL) emits its own hardcoded styling (a blue header, grey background) embedded directly in each generated table's HTML. 
This is overridden in `extra.css` using `!important`, since the embedded style is equal CSS specificity and appears later in the page than the linked stylesheet, and would otherwise win the cascade tie.
- **`%autowidth` prose tables (general).** - Asciidoctor's `%autowidth` attribute sizes a table to its content's natural, unwrapped width with no maximum, which is fine for short-content tables but lets a table with long unwrapped cells overflow past the sidebar. A specific update rule applies to **every** `%autowidth` table site-wide.
- **Dashboard mockup tables** — styled to match the site's OCA typography/header treatment, but deliberately keep plain red/yellow/green status coloring rather than forcing the brand palette onto pass/fail indicators, since clarity of that signal matters more than brand consistency here.
- **Accessibility color-contrast overrides** — three stock theme/library colors that measured below WCAG AA's 4.5:1 minimum against their background, overridden to darker equivalents that stay close to the original hue: the "Edit this Page" toolbar link, and two `highlight.js` syntax-token colors (`.hljs-comment`/`.hljs-quote`, and `.hljs-built_in`).
- **`.nav-item-toggle` minimum size** — set to `min-width`/`min-height: 24px`, since the stock element rendered slightly under the WCAG 2.5.8 minimum touch-target size. Uses `min-*` rather than a fixed size, so it only enlarges the box where it currently falls short, without otherwise touching the element's position or background-image sizing.

---

## Mobile Support

The site uses the Antora default theme's built-in responsive breakpoint (collapsing the navbar into a hamburger menu below approximately 1024px width) rather than a custom responsive implementation. 
Targeted fixes sit on top of the stock behavior, all in `extra.css`:

- The hamburger icon itself is recolored to the site's dark text color, since the theme's default icon color has poor contrast against the cream navbar background.
- The expanded mobile menu panel is explicitly set to the cream background color — the theme's `.navbar-menu` element has its own background property, separate from the main navbar's, 
which the general navbar recoloring doesn't reach on its own.
- The Tenstorrent logo link is given a top border and centered alignment specifically at mobile widths, so it reads as a separate element from the Guides/Downloads/Datasheets list above it rather than blending into it.
- The `.nav-item-toggle` minimum touch-target size is a mobile/touch usability fix as much as an accessibility one, though it applies at all viewport widths, not only narrow ones.

No changes have been made to the right-hand contents panel or left sidebar's mobile behavior — both use the theme's stock responsive handling.

---

## Search

Site-wide search is provided by [`@antora/lunr-extension`](https://gitlab.com/antora/antora-lunr-extension), Antora's official (though still pre-1.0) search extension, 
using [Lunr.js](https://lunrjs.com) for client-side full-text search with no server component.

**How it's wired in:**
- The extension package is added to the Antora invocation used for the combined build (`doc/doc.mk`'s shared `OCAH_ANTORA` variable, and the equivalent Docker-based local build path in `scripts/docker-run.sh`).
- It's registered in `antora-playbook.yml` under `antora.extensions`.
- The build is run with the environment variable `SITE_SEARCH_PROVIDER=lunr` set — this is what causes the search box to actually appear in the navbar; 
the box's HTML is already present in the stock theme, conditionally shown based on this variable, and needed no changes.
- This is only enabled for the **combined** build. The standalone per-component playbooks don't register the extension, so `SITE_SEARCH_PROVIDER` is deliberately not set globally,

**A patched file:** `doc/ui-supplemental/js/search-ui.js` overrides a file that ships inside the `@antora/lunr-extension` package itself (not the Antora UI theme), 
using the same `supplemental_files` mechanism described in Section 3. 
The patch adds a defensive sort of the search index's internal data structure immediately before it's loaded, working around a data-ordering issue in the extension 
that could otherwise cause the search index to fail to load entirely. 
If a future version of the extension resolves this at the source, this override could potentially be removed.

Since search indexes content across all six components in one combined build, adding a new component to `content.sources` extends search coverage automatically — no separate search configuration is needed per component.

---

## Accessibility

Two mechanisms work together: CSS color-contrast overrides for anything static, and a small runtime JavaScript patch for markup gaps in the stock theme that can't be fixed with CSS alone.

### CSS contrast overrides

The "Edit this Page" link color, `.hljs-comment`/`.hljs-quote`, and `.hljs-built_in` are all 
darkened from their stock values, each verified to clear the WCAG AA 4.5:1 contrast minimum against the code-block/page background while staying close to the original hue.

### Runtime patches (`doc/ui-supplemental/js/a11y-patches.js`)

Loaded from `footer-content.hbs`, after the footer markup. 
It patches three specific gaps in the stock theme's own markup, none of which are fixable by CSS alone since they're missing semantics, not just missing color:

- **The toolbar's home-link icon** (`.home-link`) and **the sidebar's section expand/collapse toggle** (`.nav-item-toggle`) both render as background-image-only elements 
with no text content and no accessible name at all in the stock theme. 
The script adds an `aria-label` to each, but only if one isn't already present (checking `aria-label`, `aria-labelledby`, `title`, and visible text content first), 
so it's safe to run even if a future theme update adds real labels itself.
- **Horizontally-scrolling code blocks** need to be in the keyboard tab order so keyboard users can actually scroll them (this is `axe-core`'s `scrollable-region-focusable` rule). 
The script checks each code block's actual `scrollWidth` vs. `clientWidth` and only adds `tabindex="0"` to ones that are genuinely overflowing — not every code block, since most aren't wide enough to need it.
- **That overflow check runs twice**, not once: an initial pass on `DOMContentLoaded`, and a second pass once `document.fonts.ready` resolves. 
This is because the custom monospace font (Berkeley Mono, loaded with `font-display: swap`) can change a code block's rendered width after the page has already loaded, 
once the real font replaces the fallback.

---

## Key Design Decisions

A summary of the decisions that shape the site's structure:

- **One combined Antora build, not separate builds per component.** 
Chosen so the site itself is a fully native, cross-linked Antora experience.
- **A dedicated Home landing page, structurally separate from the books, and the site's actual entry point.** 
Home covers feature overview, motivation, use cases, and licensing — content a book-per-subsystem structure has nowhere natural to put. 
It's built as independent linked pages (each page an `xref:`-connected sibling, not part of an `include::` chain the way every book's chapters are),
which is linked to having no PDF: producing one would mean either restructuring it to look like a book (defeating the point of keeping it lightweight) 
or accepting a much messier build with parallel HTML/PDF content branches for every page.
- **The site logo, not a dropdown entry, is Home's only navigation path.**
Consistent with treating Home as the site's front door rather than "one more item in a list."
- **"Null builder" placeholder components.**
Components without real content yet are still built as full, real Antora components with placeholder content, 
appearing correctly in navigation and the switcher panel, rather than being hidden until content exists. This means the site's navigation always reflects its intended final shape.
- **Static, hand-written navbar dropdown menus**
not dynamically generated from the component catalog — favors robustness over the small ongoing cost of adding one line per new book/download.
- **Flat, chapter-level-only left navigation for the books**
matching the PDF's own chapter structure, rather than deep per-section navigation entries — avoids numbering/duplication issues between HTML and PDF. 
Getting Started's two-section grouping is a deliberate exception.
- **Per-page (not per-site) section numbering is accepted as-is.** 
A genuine Antora limitation, not something to "fix" by merging content into longer pages.
- **Every component stages its own full copy of the shared hardware documentation**
rather than one shared component every book references. 
A deliberate trade of build-time/output-size cost for build simplicity and per-component independence).
- **Two distinct table-styling rules for two distinct table categories**
Bit-layout register tables need a fixed width and no wrapping to stay meaningful; 
Long-content prose tables need full width and forced wrapping to avoid overflowing. 
Conflating the two would break one or the other.
- **Register/status table coloring stays semantic (red/yellow/green), not brand-colored**
on the dashboard mockup and similar status displays — legibility of the pass/fail signal takes priority over brand consistency in this one case.
- **Missing PDFs degrade gracefully, not fatally.**
The staging step that copies each component's PDF into the deployed site's downloads area checks for the file's existence first; 
a missing PDF produces a build-time warning and is skipped, rather than failing the entire site build.
- **No CSS `@import` chains** 
Every stylesheet is linked explicitly, to keep it visible and avoid silent link failures.

---

## Authoring Conventions for Shared HTML/PDF Content

**CAUTION - if adding new files**
This matters for anyone editing subsystem/hardware documentation content (under `hw/`), not just site infrastructure, since getting it wrong silently breaks one output format while the other keeps working.

Subsystem documentation files are shared source for both the website (via Antora) and the downloadable PDFs (via direct `asciidoctor-pdf`), 
but the two tools resolve `include::` directives differently, so a single include statement cannot always serve both:

- **Antora-only syntax** (`include::<module>:<path>[]` resource-ID references, and `partial$`-prefixed paths) is understood only by Antora. 
Plain `asciidoctor-pdf` has no concept of Antora's modules and will fail to resolve these at all.
- **Plain relative filesystem paths** (e.g. `../../../ip/some_ip/doc/index.adoc`) work correctly for the direct PDF build, 
but do not reliably resolve the same way when the same file is staged into Antora's virtual module structure for the HTML build — 
particularly when the target is a full **page** (a chapter document) in a different module. 
Plain relative paths generally do work correctly for same-directory includes and for referencing register-content **partials** within the same module.

The established pattern where a chapter needs to pull in content from a different module for both outputs is:

```asciidoc
ifdef::backend-html5[]
include::<module>:<relative-path>[leveloffset=0]
endif::backend-html5[]
ifdef::backend-pdf[]
include::<matching-raw-relative-path>[leveloffset=0]
endif::backend-pdf[]
```

Both branches should resolve to the same actual content, via the mechanism appropriate to each backend. 
When editing a file using this pattern, **both branches need updating together** — a change applied to only one backend's branch will silently diverge from the other. 
When adding a *new* cross-module reference, use this same dual-backend structure from the start, rather than a single unconditional include, even if it currently only 
needs to work for one backend — Antora resource-ID syntax used unconditionally will break the PDF build outright, since plain Asciidoctor cannot interpret it at all.

Register tables specifically follow a recognizable variant of this same pattern: the `backend-html5` branch includes an `.html` partial (usually wrapped in a `++++` passthrough block), 
the paired `backend-pdf` branch includes an `.adoc` partial with the **same basename**. 
This is also the pattern that the `collect_doc.py` tool (below) uses to distinguish an auto-generated register table from genuine hand-authored content.

---

## Locating a Book's Scattered Source Files (`collect_doc.py`)

A direct consequence of the architecture is that 
a single component's actual content is spread across its own `doc/<component>/src/` tree, the shared `hw/sys/*/doc` and `hw/ip/*/doc` trees, 
generated register partials under `regs/gen/adoc`, and occasionally vendor overlay register directories — none of it in one place, 
and the include chain connecting it all isn't obvious from any single file. 
`collect_doc.py` exists to make this concrete for a given component: point it at that component's top-level `index.adoc`, and it recursively 
follows the include chain (and, optionally, image references) to assemble a flat mirror of every real file involved, preserving each file's original repo-relative path.

**What it follows:** only the `ifdef::backend-pdf[]` branch of any conditional include, since that branch always resolves to a real, direct filesystem path — 
the `ifdef::backend-html5[]` branch is skipped entirely, including any Antora resource-ID includes inside it (`partial$...`, `component:module`-style paths), 
which aren't real filesystem paths outside an actual Antora build. Includes that aren't wrapped in any backend conditional at all are always followed.

**Usage:**
```bash
python3 collect_doc.py --start doc/trm/src/index.adoc --target /tmp/trm-mirror
```
`--repo-root` is auto-detected by walking upward from the start file looking for `.git`, or can be passed explicitly. 
The `--start` path can be a real filesystem path or a repo-root-relative one.

**Two opt-in flags, both off by default:**
- `--images` — also copies image files referenced via `image::`/`image:` macros, resolved against the nearest `:imagesdir:` attribute declared earlier 
in the include chain (AsciiDoc's `:imagesdir:` is a document-wide attribute, not a per-file one — a file can reference an image without ever declaring 
`:imagesdir:` itself, relying entirely on an ancestor file having set it).
- `--no-tables` — excludes auto-generated register-table includes, detected via the html5/pdf same-basename pairing. 
Reports a single count of how many were excluded, not a per-file list.

**Known limitations, worth knowing before relying on it for something load-bearing:**
- It follows `include::` and `image::`/`image:` only — not `xref:` links. In practice this shouldn't miss real content.
- `:imagesdir:` tracking assumes the attribute is set once and doesn't change mid-document.
- The register-table detection heuristic is specific to the exact html5/pdf same-basename pairing convention described above.
