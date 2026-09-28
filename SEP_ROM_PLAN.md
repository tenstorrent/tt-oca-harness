# SEP Boot ROM — plan and progress ledger

Umbrella plan for the SEP boot ROM (`hw/sys/sep/bootrom/prod`). Individual workstreams keep
their own detailed plans; this file is the ROM-level view — what shipped, what is open, and
cross-cutting changes that do not belong to any single workstream.

Untracked by convention, for offline review.

## Workstream plans

| Plan | Scope | State |
|---|---|---|
| `OCA_MANIFEST_PLAN.md` | Replace the Grendel/`TBL1` parser with the OCA Boot Manifest and its validation library | Integrated; ROM links `validators/oca/lib` and supplies platform callbacks |
| `ROM_ENTROPY_BRINGUP_PLAN.md` | ESRC → CSRNG → EDN bring-up owned by BL0 | Implemented, `SEP_ENTROPY_BRINGUP ?= 1` |
| `SEP_ROM_DOC_PLAN.md` | `rom.adoc` specification review and reconciliation | Phases 1–11 closed; six mechanical checks committed |

## Current state

- ROM image: `boot_rom.vmem` **39680 bytes** against a 64 KiB budget (`link/rom.ld`).
- Manifest tooling/library: `tt-oca-manifest` submodule at
  `hw/sys/sep/bootrom/prod/tools/tt-oca-manifest`, branch `main`.
- Specification: `hw/sys/sep/bootrom/prod/doc/rom.adoc`, 94 tagged requirements, last reconciled against
  the implementation 2026-09-03.
- Doc consistency checks: `hw/sys/sep/doc/checks/` — run before publishing any doc change.
  Wiring them into CI is deferred by decision on 2026-09-03.

## Open items

From the `rom.adoc` implementation-status matrix (`<<sec:impl_matrix>>`), which is the
authoritative list — this is a summary, not a second source of truth.

**Gaps**

- Peripheral/bus reset is a stub (`PERIPH_RST_TODO`)
- PMP fence policy; PMP binding/release awaits Smepmp
- Fuse-sense readiness ordering — only the PLL path polls `smc_fuse_sense_done`
- Secure-boot escalation flag (`unauthenticated_flags` bit 0) unimplemented
- Demotion directive: BL2 `VALID` qualifier not preserved (narrowed)
- Payload gap zeroing; stack canary position at hand-off

**Unmerged work**

- Handoff self-check ledger (gate ledger), commit `3de14630f`
- Attestation measurement (soft enrollment)

**Deferred / provisional by design**

- PQC signatures and key slots; multi-signer / co-signer verification
- Payload KDF construction (provisional); measurement encoding (superseded by PCRV)
- ROM key digests are test placeholders — **must be replaced before mask finalization**

---

## Cross-cutting changes

### Submodule switch: tt-boot-manifest → tt-oca-manifest (2026-09-03)

The manifest tooling/library submodule now points at
`git@github.com:tenstorrent/tt-oca-manifest.git`, branch `main` (`171e02fa`), at path
`hw/sys/sep/bootrom/prod/tools/tt-oca-manifest`. The new repo carries only the OCA-related
code and documentation; legacy manifest formats were dropped in the move.

#### The one trap: repo name ≠ Python package name

`tt-oca-manifest/pyproject.toml` renames only the **distribution**
(`name = "tt-oca-manifest"`) and deliberately keeps
`package-dir = {"tt_boot_manifest" = "src"}` so existing
`python -m tt_boot_manifest.pack_images` callers are a drop-in.

So the rename splits cleanly on spelling, and that is the rule the sweep used:

| Spelling | Meaning | Action |
|---|---|---|
| `tt-boot-manifest` (hyphen) | repo / directory name | → `tt-oca-manifest` (41 occurrences) |
| `TT_BOOT_MANIFEST_DIR` | make variable naming the dir | → `TT_OCA_MANIFEST_DIR` (6) |
| `tt_boot_manifest` (underscore) | **Python import package** | **unchanged** — renaming it breaks the build |

`hw/sys/sep/dv/README.md` was correctly left untouched: its only reference is the package
name in an error string. A note now sits above `PACK_RUN` in the bootrom Makefile so nobody
"fixes" the apparent inconsistency later.

#### Verified, not assumed

- **Every layout constant is identical across the move** — `OFF_PAYLOAD_OFFSET` 3748,
  `OFF_CLASSIC_MANIFEST_TRAILER` 3168, signed region 3172, `TOC_ENTRY_SIZE` 276,
  `OFF_TOC_ENTRY_HASH` 80, `LEN_MANIFEST_SECURITY_CONTROL` 2. The Phase 9–11 doc corrections
  therefore still hold; all six checks in `hw/sys/sep/doc/checks/` pass unchanged.
- **ROM builds clean** against the new `validators/oca/lib` (15 `.c` files): 0 errors,
  0 warnings, `boot_rom.vmem` 39680 bytes — comfortably inside the 64 KiB budget.
- **Packer runs**: `make oca-images` exits 0 and produces all 18 SPI preloads.
- **End-to-end layout confirmed against the new producer**: in `oca_secure_boot.bin` the
  primary manifest sits at `0x1000` and the backup at `0x41000`, both magic `OCAC` with the
  `cacacaca` trailer at offset 3168 — independently re-confirming `tbl:flash_layout` and the
  signed-region boundary.
- **VP loader works**: `virtual_platform/tests/bootcode/oca_layout.py` loads
  `src/oca/constants.py` by path from the new submodule with no `cryptography` dependency.
- No CI workflow pins the submodule path, so nothing there needed changing.

#### Gotcha for anyone with an existing build tree

The first build after the switch fails with

```
No rule to make target 'tools/tt-boot-manifest/validators/oca/lib/authorization.c'
```

because the generated `.d` dependency files in `build/oca/` still name the old path.
`make -C hw/sys/sep/bootrom/prod clean` fixes it. Worth mentioning in the PR description —
it looks like a broken submodule and is not.

#### Follow-up, not done here

`virtual_platform/tt-oca-harness-model` (a separate repo) still references
`tt-boot-manifest`, mostly inside the vendored
`sw/sep-vp-tests/fw-tests-from-tt-oca-hw/.../bootcode/` tree, which points at
`fw/deps/tt-boot-manifest` — an old tt-oca-hw-layout internal path that was already dead
here. Its `README.md:702` reference is the live one. Fixing these needs a commit in that
repo.

#### Doc policy note

Per direction on 2026-09-03: the published SEP spec does **not** record this transition.
External readers have no need to know a predecessor repo existed, so the rename was a
straight name swap in `rom.adoc` with no migration history added.
