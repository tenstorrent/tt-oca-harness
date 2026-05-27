# tt-oca

This is a **_interim private_** TT repository while we populate it with the OCA design and refine
it. This repository will be converted to open source in Q3 2026 when it is ready.

---

## Third-party (vendor) package imports

All external IP and third-party source files are pulled into this repository exclusively via
Bender's `vendor_package` feature. The standard Bender `dependencies:` block is intentionally
absent from this repository; do not add `dependencies:` entries for third-party packages.

### Ground rules

- **Import only what OCAH uses.** Every `vendor_package` entry must carry a narrowly scoped
  `include_from_upstream:` list (and `exclude_from_upstream:` where helpful). Whole-repository
  imports are prohibited.
- **Commit vendored sources.** The materialized files under `vendor/` are committed to this
  repository so that every revision is fully self-contained and reproducible without network
  access.
- **One upstream commit pin per entry.** The `rev:` field must be a full commit hash (not a
  branch or tag) so the import is deterministic.

### Filesystem layout

```
vendor/<VENDOR_NAME>/<REPOSITORY_NAME>/<IMPORTED_FILE_HIER>
```

`<VENDOR_NAME>` is the upstream organisation or owner exactly as it appears on the hosting
service (case-preserving, e.g. `lowRISC`). `<REPOSITORY_NAME>` is the upstream repository name
(e.g. `opentitan`). The file hierarchy beneath that mirrors the subtrees requested in
`include_from_upstream` verbatim.

Example:

```
vendor/
  lowRISC/
    opentitan/             ← target_dir (wiped and refreshed by bender vendor init)
      hw/ip/otbn/rtl/      ← from include_from_upstream: "hw/ip/otbn/rtl"
      hw/ip/otbn/data/
      hw/ip/otbn/dv/tracer/
      hw/ip/otbn/util/
  patches/                 ← patch files live here, outside any target_dir
    lowRISC/
      opentitan/
        0001-otbn_sram_ext.patch
```

### Patch files

Local modifications to vendored sources are maintained as patch files so they survive a
`bender vendor init` refresh.

**Patch location:**

```
vendor/patches/<VENDOR_NAME>/<REPOSITORY_NAME>/<NUMBER>-<PATCH_NAME>.patch
```

- `<NUMBER>` is a **4-digit zero-padded** integer (`0001`, `0002`, …). Bender applies patches
  in lexicographic filename order, so the number prefix controls application order.
- `<PATCH_NAME>` is a short, snake_case description of the logical change set (a single patch
  file may touch multiple source files).

Example:

```
vendor/patches/lowRISC/opentitan/0001-otbn_sram_ext.patch
vendor/patches/lowRISC/opentitan/0002-some_later_change.patch
```

### Bender.yml `vendor_package` conventions

Each entry must follow this template:

```yaml
vendor_package:
  - name: <descriptive-name>
    target_dir: vendor/<VENDOR_NAME>/<REPOSITORY_NAME>
    upstream: { git: "<upstream-url>", rev: "<full-commit-hash>" }
    include_from_upstream:
      - "<path/relative/to/upstream/root>"
      # add only the subtrees actually consumed by OCAH
    patch_dir: "vendor/patches/<VENDOR_NAME>/<REPOSITORY_NAME>/"
```

### Authoring a new patch

1. Materialise (or refresh) the vendor tree:
   ```
   bender vendor init
   ```
2. Edit the files under `vendor/<VENDOR_NAME>/<REPOSITORY_NAME>/` as needed.
3. Stage the changes:
   ```
   git add vendor/<VENDOR_NAME>/<REPOSITORY_NAME>/
   ```
4. Generate a patch (Bender will prompt for a commit message):
   ```
   bender vendor patch
   ```
   Bender writes the patch into `patch_dir` with an auto-generated name.
5. Rename the patch to follow the numbering convention:
   ```
   mv vendor/patches/.../<auto-name>.patch vendor/patches/.../<NNNN>-<description>.patch
   git add vendor/patches/...
   ```
6. Commit both the patched source and the new `.patch` file.

### Refreshing / re-initialising a vendor tree

```
bender vendor init
```

This re-fetches the upstream commit, copies the `include_from_upstream` subtrees, and re-applies
all patches from `patch_dir` in lexicographic order.

---

## Example: OpenTitan OTBN

The OpenTitan [OTBN](https://opentitan.org/book/hw/ip/otbn/) (Big Number Accelerator) is the
first vendored import. It is used by OCAH's crypto subsystem.

**Bender.yml entry:**

```yaml
vendor_package:
  - name: opentitan
    target_dir: vendor/lowRISC/opentitan
    upstream: { git: "git@github.com:lowRISC/opentitan.git", rev: "bbe4dbf28bbfe815dcd11d723dc3e38635b46704" }
    include_from_upstream:
      - "hw/ip/otbn/rtl"
      - "hw/ip/otbn/data"
      - "hw/ip/otbn/dv/tracer"
      - "hw/ip/otbn/util"
    patch_dir: "vendor/patches/lowRISC/opentitan/"
```

**Applied patches:**

| File | Description |
|---|---|
| `vendor/patches/lowRISC/opentitan/0001-otbn_sram_ext.patch` | Replaces `prim_ram_1p_scr` with `prim_ram_1p_scr_ext` in `otbn.sv` to expose external SRAM interfaces (`imem_sram_req_o`, `dmem_sram_req_o`, …) required by the OCAH crypto PKA integration. |

**Materialise:**

```
bender vendor init
```
