# idma (vendored, patched)

Upstream: the [`tenstorrent/tt-iDMA`](https://github.com/tenstorrent/tt-iDMA) fork,
branch `tt/master`, pinned in the root `Bender.yml`. The fork is
[`pulp-platform/iDMA`](https://github.com/pulp-platform/iDMA) `v0.6.5-src` plus TT
commits. One of those commits backports the R-AW channel coupler fixes from upstream
#80 and #204, which are already in v0.7.0; drop it when the fork moves to v0.7.0 or
later.

The `-src` tag ships only the iDMA **source** (templates); its `target/rtl/` is empty
(`.gitignore` only). The sibling `v0.6.5` release does ship a generated `target/rtl`,
but it is a different, generic config — not the bundle TT compiles — so we vendor the
source and keep TT's generated RTL as overlay collateral (see below).

## Layout

- `upstream/` — bender-managed copy of upstream `src/` only.
- `overlay/target/rtl/` — TT-owned generated RTL OCA compiles (`idma_generated.sv`,
  `include/idma/tracer.svh`), produced from the patched templates with a TT generator
  config. No upstream equivalent; committed directly, not touched by `bender vendor init`.
- `overlay/rdl/` — TT-owned register description (`dma_ctrl.rdl`) for the iDMA CSR
  block. Hand-maintained today; future home for RDL exported from the patched
  `idma_reg.hjson.tpl` via `regtool --systemrdl`. Generated C/adoc/html collateral
  stays under `hw/comp/idma_wrapper/data/registers/`.
- `Bender.yml`, `patches/`, this `README.md` — hand-authored at the package root.

## Patches

The TT delta — all in-place edits to upstream files (no new modules) — is applied
as five numbered patches in sorted filename order. Patches 0001 through 0004
establish the backend, frontend, typedef, and midend customizations. Patch 0005
updates templates modified by 0001 and 0002, so it must follow both.

### `patches/0001-tt-idma-backend.patch` — protocol backends + their templates

Channel-field wiring and fixes for the AXI (`idma_axi_{read,write}`), AXI-Stream
(`idma_axis_write`), OBI (`idma_obi_write`), and TileLink (`idma_tilelink_*`)
backends, the channel coupler / dataflow element / error handler, plus the mirrored
`backend/tpl/{idma_backend,idma_legalizer,idma_transport_layer}.sv.tpl` generators.

### `patches/0002-tt-idma-frontend.patch` — desc64 frontend + reg templates

Edits to the `frontend/desc64/*` descriptor engine and the
`frontend/reg/tpl/idma_reg.{hjson,sv}.tpl` register generators.

### `patches/0003-tt-idma-typedef.patch` — shared typedef header

Edits to `src/include/idma/typedef.svh`.

### `patches/0004-tt-idma-midend.patch` — midend

Edits to the `midend/idma_{nd,mp_dist,mp_split}_midend` modules.

### `patches/0005-tt-idma-widths.patch` — generated width conversions

Explicitly sizes backend arithmetic, AXI metadata, register-frontend request
fields, and neutral payload values at their destination widths.

`overlay/target/rtl/idma_generated.sv` is generated from the templates in `upstream/`,
but it cannot be regenerated wholesale: its register frontend and `tracer.svh` were
edited by hand, and its backend modules come from older templates than the ones now in
`upstream/`. Rerunning the generator would undo those edits and pull in unrelated
template changes. To bring one template change into the bundle, run the generator with
and without the change, and apply only the difference between the two outputs to the
committed file.
