# tt-oca

This is a **_interim private_** TT repository while we populate it with the OCA design and refine
it. This repository will be converted to open source in Q3 2026 when it is ready.

---

## Third-party (vendor) package imports

External IP and third-party source files are materialized in this repository via Bender's
`vendor_package` feature. If a vendored tree is also consumed as a Bender package, the root
`dependencies:` entry must point at the local package root under `vendor/`; do not add direct
third-party `git:` dependencies.

### Ground rules

- **Import only what OCAH uses.** Every `vendor_package` entry must carry a narrowly scoped
  `mapping:` list and should use `exclude_from_upstream:` to document intentionally omitted
  upstream directories or files. Whole-repository imports are prohibited.
- **Commit vendored sources.** The materialized files under `vendor/` are committed to this
  repository so that every revision is fully self-contained and reproducible without network
  access.
- **Pin every upstream entry.** The `rev:` field must be a full commit hash or an immutable tag
  (e.g. a release tag). Mutable refs such as branch names are prohibited.
- **Resolve vendored packages locally.** Packages with hand-authored manifests under `vendor/`
  should be pinned with `Bender.local` overrides so transitive users resolve to the committed
  local copy.

### Filesystem layout

Vendored packages preserve the upstream GitHub organization and repository casing under
`vendor/<GitHubOrg>/<GitHubRepo>/`. Bender materializes the selected upstream files into
`upstream/`, then applies local patches there. Patch files live in the sibling `patches/`
directory so they are not removed when `bender vendor init` refreshes the target directory.

Example:

```
vendor/
  lowRISC/
    opentitan/
      patches/
        0001-some_change.patch
      upstream/             ← target_dir (wiped and refreshed by bender vendor init)
        hw/ip/otbn/data/    ← selected register source files
        hw/ip/otbn/rtl/     ← selected OTBN RTL source files
        util/reggen/        ← selected OpenTitan reggen modules only
        util/design/mubi/   ← selected OpenTitan mubi helper used by reggen
```

### Patch files

Local modifications to vendored sources are maintained as patch files so they survive a
`bender vendor init` refresh.

**Patch location:**

```
vendor/<GitHubOrg>/<GitHubRepo>/patches/<NUMBER>-<PATCH_NAME>.patch
```

- `<NUMBER>` is a **4-digit zero-padded** integer (`0001`, `0002`, …). Bender applies patches
  in lexicographic filename order, so the number prefix controls application order.
- `<PATCH_NAME>` is a short, snake_case description of the logical change set (a single patch
  file may touch multiple source files).

Example:

```
vendor/lowRISC/opentitan/patches/0001-some_change.patch
vendor/lowRISC/opentitan/patches/0002-some_later_change.patch
```

### Bender.yml `vendor_package` conventions

Each entry must follow this template:

```yaml
vendor_package:
  - name: <descriptive-name>
    target_dir: vendor/<GitHubOrg>/<GitHubRepo>/upstream
    upstream: { git: "<upstream-url>", rev: "<full-commit-hash-or-tag>" }
    exclude_from_upstream:
      - "<unused/path/relative/to/upstream/root>"
    mapping:
      - { from: "<upstream/file/or/dir>", to: "<local/file/or/dir>", patch_dir: "<local/patch/scope>" }
      # add only files and directories actually consumed by OCAH
    patch_dir: "vendor/<GitHubOrg>/<GitHubRepo>/patches/"
```

### Authoring a new patch

1. Materialise (or refresh) the vendor tree:
   ```
   bender vendor init
   ```
2. Edit the files under `vendor/<GitHubOrg>/<GitHubRepo>/upstream/` as needed.
3. Stage the changes:
   ```
   git add vendor/<GitHubOrg>/<GitHubRepo>/
   ```
4. Generate a patch (Bender will prompt for a commit message):
   ```
   bender vendor patch
   ```
   Bender writes the patch into `patch_dir` with an auto-generated name.
5. Rename the patch to follow the numbering convention:
   ```
   mv vendor/.../patches/<auto-name>.patch vendor/.../patches/<NNNN>-<description>.patch
   git add vendor/.../patches/
   ```
6. Commit both the patched source and the new `.patch` file.

### Refreshing / re-initialising a vendor tree

```
bender vendor init
```

This re-fetches the upstream commit, copies the files selected by `mapping:`, excludes any paths
listed in `exclude_from_upstream:`, and re-applies all patches from `patch_dir` in lexicographic
order.

---

## Register Generation

OCAH register collateral is generated from per-block SystemRDL files under
`hw/ip/<block>/regs/`. HJSON-backed OpenTitan register blocks are first exported to RDL using
`tools/regs/reggen_wrapper.py` and the directly vendored OpenTitan reggen modules under
`vendor/lowRISC/opentitan/upstream/util/`. See [`doc/user_guide/regs.adoc`](doc/user_guide/regs.adoc)
for the `make regen-regs` targets, generated output layout, and firmware/DV header conventions.

---

## DV Firmware

Per-subsystem DV firmware (the runtime **drivers** ported from `tt-oca-hw`, not the tests) is
built via `make dv-fw [TARGET=key_manager|sep|smc]`. Each subsystem owns a `fw.mk` + `toolchain.mk` under
`hw/{ip,sys}/<name>/dv/fw/` and is built as an independent recursive sub-make so the three target
CPUs (PicoRV32/KM, VeeR EL2/SEP, Rocket/SMC) never share ISA/ABI/libc flag state. The RISC-V
toolchain (including picolibc for SEP) is provided by the project Docker image and selected via
`RISCV_TOOLCHAIN` (empty by default; no site-local paths committed). See
[`doc/dv-firmware.md`](doc/dv-firmware.md) for the build-flow architecture, the toolchain
contract, the ported driver sets + provenance, and the deferred register-header reconciliation.

---

## Example: OpenTitan Register Sources

OpenTitan register descriptions are vendored as inputs for OCAH register-generation flows.
For OTBN, the RTL source subtree, `otbn.hjson`, and the minimum OpenTitan reggen Python modules
needed to export SystemRDL are imported. DV collateral, assembler, simulator, and unrelated
utilities are intentionally excluded.

**Bender.yml entry:**

```yaml
vendor_package:
  - name: opentitan
    target_dir: vendor/lowRISC/opentitan/upstream
    upstream: { git: "git@github.com:lowRISC/opentitan.git", rev: "bbe4dbf28bbfe815dcd11d723dc3e38635b46704" }
    exclude_from_upstream:
      - "hw/ip/otbn/dv"
      - "hw/ip/otbn/util"
      - "util/regtool.py"
    mapping:
      - { from: "hw/ip/otbn/data/otbn.hjson", to: "hw/ip/otbn/data/otbn.hjson", patch_dir: "hw/ip/otbn/data" }
      - { from: "hw/ip/otbn/rtl", to: "hw/ip/otbn/rtl", patch_dir: "hw/ip/otbn/rtl" }
      - { from: "util/reggen/ip_block.py", to: "util/reggen/ip_block.py", patch_dir: "util/reggen" }
      # Additional minimal reggen dependencies are mapped in Bender.yml.
    patch_dir: "vendor/lowRISC/opentitan/patches"
```

**Applied patches:**

| File | Description |
|---|---|
| `vendor/lowRISC/opentitan/patches/0001-otbn_sram_ext.patch` | Replaces `prim_ram_1p_scr` with `prim_ram_1p_scr_ext` in `otbn.sv` to expose external SRAM interfaces (`imem_sram_req_o`, `dmem_sram_req_o`, …) required by the OCAH crypto PKA integration. |

**Materialise:**

```
bender vendor init
```
