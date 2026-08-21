# tt-oca-harness

Open Chiplet Atlas Harness (OCAH) — the open hardware tree for the OCA design:
RTL, register descriptions, generated collateral, and documentation.

> [!WARNING]
> **Early stage.** This repository is under active development. Structure, interfaces,
> and generated collateral may change without notice, and much of the content here is
> provisional. As the documentation matures, most of the material collected in this
> README will migrate into the user guide and other doc products under [`doc/`](doc/);
> for now this file is the landing place for the essentials.

## Repository layout

| Path | Contents |
|------|----------|
| `hw/common/` | Shared RTL: primitives (`och_prim`, `och_prim_generic`), TL-UL, AXI network/monitor elements, register-flow makefiles. |
| `hw/ip/` | Reusable IP blocks, grouped by family where applicable (e.g. `jtag/`, `uart/`, `cross_trigger/`). |
| `hw/sys/` | Subsystems (`smc`, `sep`, `smu`, `dtp`) that integrate the IP blocks. |
| `hw/top/` | Top-level integration. |
| `doc/` | Documentation products (TRM, Integrator Guide, …); see [Documentation](#documentation). |
| `vendor/` | Third-party IP vendored via Bender; see [Third-party imports](#third-party-vendor-package-imports). |
| `tools/`, `scripts/` | Register-flow, documentation, and container helpers. |

## Documentation

Published docs: [https://tenstorrent.github.io/tt-oca-harness/](https://tenstorrent.github.io/tt-oca-harness/)
(landing page: TRM at `/trm/`, Integrator Guide at `/integrator/`). While Pages
visibility is private, that URL redirects to the repo’s private Pages host;
readers need GitHub access to this repository. CI deploys on pushes to `main`
(see `.github/workflows/doc.yml`). In Settings → Pages, use **Deploy from a
branch** → `gh-pages` → `/ (root)`.

Documentation is authored in AsciiDoc and built with Antora (HTML site) and
asciidoctor-pdf (PDF). The toolchain ships as container images, so no local Node or
Ruby install is required — the recommended entry point is the container wrapper:

```bash
scripts/docker-run.sh doc-html trm    # HTML site → doc/trm/_build/html_antora/
scripts/docker-run.sh doc-pdf  trm    # PDF       → doc/trm/dist/ocah-trm.pdf
```

Documentation builds define the generic AsciiDoc `release` attribute by
default, which omits the TRM's internal revision history from HTML and PDF
output. Disable release mode for internal builds with `OCAH_DOC_RELEASE=0`:

```bash
OCAH_DOC_RELEASE=0 scripts/docker-run.sh doc-html trm
OCAH_DOC_RELEASE=0 scripts/docker-run.sh doc-pdf  trm
```

Use `integrator` in place of `trm` to build the Integrator Guide. The images
(`docker.io/antora/antora`, `docker.io/asciidoctor/docker-asciidoctor`) are pulled once
and cached; override them with `OCAH_DOC_HTML_IMAGE` / `OCAH_DOC_PDF_IMAGE` to point at
an internal registry mirror.

If you already have `npx` and `asciidoctor-pdf` on your `PATH` (e.g. inside the project
container), you can invoke the make targets directly instead:

```bash
make ocah-doc-trm-html
make ocah-doc-trm-pdf
make ocah-doc-integrator-html
make ocah-doc-integrator-pdf
```

To build both HTML products and push them to the `gh-pages` branch (requires `uv`
and push rights; temporary until custom hosting — see `doc/gh-pages.mk`):

```bash
make ocah-doc-deploy-ghpages
```

## Register generation

Register collateral is generated from per-block SystemRDL under `hw/**/<block>/regs/`.
HJSON-backed OpenTitan blocks are first exported to RDL via
`tools/regs/reggen_wrapper.py` using the vendored OpenTitan reggen modules. Run
`make regen-regs` to regenerate; committed generated output always corresponds to the
RDL sources. The flow lives in [`hw/common/regs/`](hw/common/regs/) (discovery,
classification, and rules); a dedicated user-guide page will follow.

## DV firmware

Per-subsystem DV firmware libraries (runtime **drivers**, not tests) are built via
`make dv-fw-libs [TARGET=key_manager|sep|smc]` (alias of `ocah-dv-fw-libs`). Each
subsystem owns a `fw.mk` + `toolchain.mk` under `hw/{ip,sys}/<name>/dv/fw/` and builds
as an independent recursive sub-make so the target CPUs (PicoRV32/KM, VeeR EL2/SEP,
Rocket/SMC) never share ISA/ABI/libc flag state.

The RISC-V toolchain is provided by the project container and selected via
`RISCV_TOOLCHAIN`. The build flow lives in [`hw/common/dv/fw/`](hw/common/dv/fw/).

### SMC DV test firmware

C test images are built via the standard dispatcher:

```bash
scripts/docker-run.sh run make dv-fw-tests TARGET=smc
scripts/docker-run.sh run make dv-fw-tests TARGET=smc TEST=version_id   # one test
```

Each subsystem's tests link against one of that subsystem's **link modes** —
memory targets discovered from `link/modes/*.ld` (e.g. SMC: `sram`, `rom`; SEP:
`tcm`; KM: `vrom`) — and output artifacts fold the mode into their name
(`<test>.<mode>.elf`, e.g. `version_id.sram.elf`). A test uses its subsystem's
default mode unless it overrides `FW_TEST_MODE_<test>`; see
[`hw/common/dv/fw/compile.mk`](hw/common/dv/fw/compile.mk) for the full
mechanism.

Most SMC tests default to `sram` mode. The OCCP master BFM tests
(`occp_sanity`, `occp_master`) are declared `rom`-mode in
[`hw/sys/smc/dv/fw/fw.mk`](hw/sys/smc/dv/fw/fw.mk) because they exercise the
I3C master path and must run from the ROM address space. They link against the
open-source weak `I3C_GetDriverInstance` stub (returns `NULL`) so the build is
self-contained.

### SMC boot ROM

`hw/sys/smc/bootrom/` holds two independent ROM firmware trees:

- [`dummy/`](hw/sys/smc/bootrom/dummy/) — the lightweight DV stub used today. Its
  only job is to boot from the ROM address (`0xc0040000`), write
  `TEST_ROM_PASS` (`0x77777777`) to `scratch_0`, and spin in `wfi` so the
  testbench can load real firmware into SRAM. It builds as one `rom`-mode test
  named `dummy` (source `rom.c`) on top of the same generalized firmware engine
  as the SMC DV tests above, reusing `hw/sys/smc/dv/fw/`'s drivers, toolchain
  settings, and link scripts.
- [`prod/`](hw/sys/smc/bootrom/prod/) — self-contained production boot ROM with
  its own includes and drivers (not shared with `dv/fw/`). It implements the
  OCCP target-side protocol and uses weak stubs so the open tree links cleanly;
  the nonfree drivers override them at link time via `NONFREE_DRIVER_SOURCES`.

Build the dummy ROM with its standalone Makefile:

```bash
# From the repo root (OCAH_ROOT resolved automatically):
scripts/docker-run.sh run make -C hw/sys/smc/bootrom/dummy
```

Outputs land under `hw/sys/smc/bootrom/dummy/build/tests/dummy/` (e.g.
`dummy.rom.elf`, `dummy.rom.bin`, `dummy.rom.hex`, plus `.preload.hex` /
`.spi` variants from the shared SMC post-process step).

Build the production ROM from the same container (self-contained Makefile, not
the shared `compile.mk` engine):

```bash
scripts/docker-run.sh run make -C hw/sys/smc/bootrom/prod
```

## Third-party (vendor) package imports

External IP is materialized under `vendor/` via Bender's `vendor_package` feature. If a
vendored tree is also consumed as a Bender package, the root `dependencies:` entry points
at the local package root under `vendor/`; direct third-party `git:` dependencies are not
used.

### Ground rules

- **Import only what OCAH uses.** Every `vendor_package` entry carries a narrowly scoped
  include/`mapping:` list and uses `exclude_from_upstream:` to document intentionally
  omitted upstream paths. Whole-repository imports are prohibited.
- **Commit vendored sources.** Materialized files under `vendor/` are committed so every
  revision is self-contained and reproducible without network access.
- **Pin every upstream entry.** `rev:` must be a full commit hash or an immutable tag;
  mutable refs such as branch names are prohibited.
- **Resolve vendored packages locally.** Packages with hand-authored manifests under
  `vendor/` are pinned via `Bender.local` so transitive users resolve the committed copy.

### Filesystem layout

Vendored packages preserve upstream GitHub org/repo casing under
`vendor/<GitHubOrg>/<GitHubRepo>/`. Bender materializes selected upstream files into
`upstream/` (wiped and refreshed by `bender vendor init`), then applies local patches.
Patch files live in the sibling `patches/` directory so they survive a refresh:

```
vendor/lowRISC/opentitan/
  patches/
    0001-some_change.patch     ← NNNN-<snake_case>.patch, applied in filename order
  upstream/                    ← target_dir (refreshed by bender vendor init)
    hw/ip/otbn/{data,rtl}/      ← selected register + RTL sources
    util/reggen/                ← selected reggen modules only
```

### Bender.yml `vendor_package` template

```yaml
vendor_package:
  - name: <descriptive-name>
    target_dir: vendor/<GitHubOrg>/<GitHubRepo>/upstream
    upstream: { git: "<upstream-url>", rev: "<full-commit-hash-or-tag>" }
    exclude_from_upstream:
      - "<unused/path/relative/to/upstream/root>"
    mapping:
      - { from: "<upstream/file/or/dir>", to: "<local/file/or/dir>", patch_dir: "<local/patch/scope>" }
    patch_dir: "vendor/<GitHubOrg>/<GitHubRepo>/patches"
```

### Authoring a patch

1. Materialize/refresh the vendor tree: `bender vendor init`
2. Edit files under `vendor/<GitHubOrg>/<GitHubRepo>/upstream/`.
3. Stage: `git add vendor/<GitHubOrg>/<GitHubRepo>/`
4. Generate the patch (Bender prompts for a message): `bender vendor patch`
5. Rename to the numbering convention:
   `mv vendor/.../patches/<auto-name>.patch vendor/.../patches/<NNNN>-<description>.patch`
6. Commit both the patched source and the new `.patch` file.

`bender vendor init` re-fetches the pinned commit, copies the selected files, excludes
`exclude_from_upstream:` paths, and re-applies all patches from `patch_dir` in
lexicographic order.
