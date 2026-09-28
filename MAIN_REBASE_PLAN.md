# Rebase `inmcm/sep_rom_oca_manifest` onto main after PR #1581

Untracked by convention, for offline review. Plan written 2026-09-08; outcomes are appended
at the end as the work lands. Companion to `BRANCH_CLEANUP_PLAN.md` (the ROM/VP split) and
`SEP_ROM_DOC_PLAN.md` (the spec passes).

## Context

`inmcm/sep_rom_oca_manifest` (28 commits, tip `5adc5206f`) carries the SEP ROM / DV / doc half
of the OCA boot-manifest integration, split from the VP work so it can land on `main` by PR.
Its purpose is to **delete the legacy Grendel manifest format** (magic `TBL1`, the 1184-byte
`manifest_t`, `manifest_load.c` / `manifest_crypto.c` / `manifest.h`) and replace it with the
OCA format via the OCA validator library (`oca_boot.c`, `oca_platform.c`). The published SEP
ROM spec already documents that end state — `SEP_ROM_DOC_PLAN.md` Phase 11 records
*"OCA CLASSIC manifest | holds | no `TBL1` in `src/` or `include/`; `manifest.h` deleted."*

The branch was cut from `20db9df9e`. On **2026-09-07** `origin/main` gained `9317673f1`
— *"sep: Harden ROM boot and expand firmware DV coverage (#1581)"* by another engineer
(~22,000 insertions, 190 files). It **hardened the Grendel parser this branch deletes** and
built 61 new ROM DV tests on it, taking `rom_fw.toml` from 7 tests to 68. So the rebase is no
longer mechanical — it must decide, file by file, what of #1581 survives.

`9317673f1` is a **squash** (single parent `6e2d6c10e`): its 14 sub-commits are not separately
cherry-pickable, so every decision is made at file level against the squashed diff.

### Decisions taken

1. **The OCA migration proceeds; Grendel/TBL1 is deleted.** Keep everything in #1581 that
   improves the *non-manifest* ROM; discard what is specific to the Grendel format or
   re-solves a problem this branch already solved.
2. **BL1 placement becomes data-driven: ICCM must work, SRAM stays supported.** Honour the
   TOC entry's `load_addr` and validate against either region, rather than hardcoding one as
   both sides currently do (this branch: SRAM; #1581: ICCM). Mixing the two hardcodings breaks
   warm reset, so this is the reconciliation.
3. **Land via an integration branch**, port the tests there, then one PR to `main`, so `main`
   never carries a red regression in brand-new coverage.
4. **The VP branch is merged, not rebased** — see the VP section.

> **Before anything else:** triaging #1581 turned up **four live defects on this branch** that
> have nothing to do with the rebase, three of them fail-open:
>
> 1. the `init_bl0_state()` wipe leaves **DEMOTE_2 unlocked on a PROD_END part**;
> 2. the **stack-canary check is dead code** — placed, never read;
> 3. **BL1 validity is checked too late to fail over**, so a manifest with no `BLSTAGE1`
>    image kills the boot instead of trying the backup slot;
> 4. **DEMOTE_1 is left unwritten and unlocked** whenever the manifest defers to BL2.
>
> All four are specified with fixes and verification under *Defects this branch shares and must
> fix*. They are worth landing regardless of what happens to the rebase.

### Why this is smaller than it looks

Of #1581's 190 files, only **21** collide. The other ~169 — DV firmware driver headers, the
`spi_ot_*` / fabric / dma clang-format churn, 19 eFuse preload configs, `testlists/all.toml`,
`sep_tb_signal_list.svh`, `sep_public_scope.vlt`, `sep_warm_handler.hex` — are untouched by
this branch and are **carried along for free** by rebasing onto `origin/main`.

Critically, this branch is **byte-identical to the merge-base** for `vector.S`, `rom.ld`,
`bl0_state.h`, `errors.h`, `sep_dma.c`, `sep_smc_interface.h`, `boot_straps.*`, `fuse_lock.c`,
`sep_ot_spi.c` and `rom_mbx.h`. So #1581's largest and highest-value ROM fixes conflict with
nothing and arrive automatically.

## Safety net (already in place)

- `backup/sep_rom_oca_manifest-prerebase-20260908` → `5adc5206f` (local ref, this session)
- `origin/inmcm/sep_rom_oca_manifest` also contains `5adc5206f`
- `rerere.enabled=true`, holding two Makefile resolutions from the aborted first attempt
- Worktree `/localdev/cmccoy/dev/tt-oca-harness-main` is clean at `5adc5206f`; no rebase running

## Highest-value things arriving free from #1581

Worth stating because they are real silicon/firmware bugs this branch does **not** have fixed:

- **`sep_smc_interface.h`: four offsets addressed unmapped space** — scratch base
  `0x10100`→`0x39080`, `DFX_CTRL_STATUS_SMU` `0xF800`→`0xB800`, both fuse-map entries
  `0xB008/0xB028`→`0x7008/0x7028`. Post codes, the virtual console, the manifest-address
  handshake and MBIST publication all went to a hole. DV could not see it because `u_smc_mem`
  was a flat `axi_sim_mem` answering at any address — which #1581 also fixes with a real
  address-decode checker in `tb_top.sv`.
- **`vector.S`**: stack-free `trap_vector_early` (`mtvec` previously pointed at a handler that
  pushes `ra` before `sp` existed → double fault); the MEM_REPAIR/MBIST gate moved ahead of the
  DCCM scrub with a new MBIST arm; warm dispatch moved `warm_scratch[0]` → `cold_scratch[7]`
  (the warm bank's `arst_n` includes `wdt_rst_ni`, so the old slot was cleared by the very
  reset it dispatched — closes BLK-003).
- **`aes_driver.c`: `check_no_alert()`** — a rejected `CTRL_SHADOWED` update leaves the engine
  on its previous configuration while IDLE/INPUT_READY/OUTPUT_VALID all look normal, so the
  old polling could not detect a misconfigured decrypt.
- **`hmac_sha256.c`: `check_no_error()`** — a rejected op leaves `hmac_idle` asserted, so the
  caller reads a stale digest as real.
- **`fuse_lock.c`**: read-lock the three UID fields with the other secrets.
- **`sep_generate_efuse_preload.py` + 19 eFuse TOMLs** — resolve every offset/bitrange from the
  generated register map, so an RDL rename fails loudly instead of staging a plausible image.
  `sep_efuse_lc_prod_class_key.toml` and `chiplet_key{0,1}*.toml` are *exactly* what this
  branch's `sep_rom_oca_{encrypted,otp_key}_boot_test` currently hand-build in Python.

## Defects this branch shares and must fix

Found by triaging #1581 against this branch's code — real, and not cosmetic:

1. **`init_bl0_state()` wipe (security-relevant).** The secure-boot *bypass* #1581 describes
   does **not** exist here: OCA never routes the verdict through `bl0_state`
   (`oca_platform.c:567-577` reads `SBOOT_DIS` and lifecycle live from fuses, and there is no
   `secure_boot_enabled()` on this branch). **But the ordering defect is present** —
   `rom_lifecycle_policy()` records `lc_state` at `lifecycle.c:145`, then `init_bl0_state()`
   at `rom_main.c:574` zeroes the whole struct (`bl0_state.h:92-96`). Since
   `LC_STATE_TEST_DEV == 0x0`, `rom_main.c:365`'s `get_bl0_state()->lc_state` always reads 0,
   so **on a PROD_END part the "never demote, lock both registers" branch never runs and
   DEMOTE_2 is left unlocked**. BL1 also receives a zeroed `lc_state`/`feat_ctrl`.
   *Fix:* take #1581's reordering (move `[C9c]` ahead of `[C6]`) **and** make `rom_main.c:365`
   use the `lc_state` local from `:541`. Do **not** port the `secure_boot_enabled(m, ...)`
   plumbing — it is `manifest_t`-coupled and the problem is already gone architecturally.

   > **TODO — must fix on this branch, independent of the rebase.**
   >
   > This is a live defect on `inmcm/sep_rom_oca_manifest` today, not an artefact of merging
   > #1581. It is worth fixing **on its own commit, first**, so it is reviewable and
   > backportable without the rest of the rebase, and so the diff that closes it is not buried
   > in a 21-file conflict resolution.
   >
   > Apply both halves, as #1581 did — either one closes it, and having both means the
   > correctness no longer depends on call ordering:
   >
   > 1. **Reorder.** Move the `[C9c]` `init_bl0_state()` call from `rom_main.c:574` to just
   >    after `[C5]` PLL init and before `[C6]` `rom_lifecycle_policy()` (`:541`), so the
   >    zeroing happens before any field is recorded. The zeroing itself cannot simply be
   >    dropped: `bl0_state` sits at the top of DCCM, and `vector.S` clamps its scrub to
   >    `__stack_top`, which `link/rom.ld` places below the `bl0_state` reserve — so no
   >    `DCCM_SCRUB_BYTES` value reaches it, and something must establish its ECC.
   > 2. **Stop re-reading the wiped field.** `rom_main.c:365` does
   >    `uint32_t lc_st = get_bl0_state()->lc_state;` and `:367` tests
   >    `if (lc_st == LC_STATE_PROD_END)`. Pass the `lc_state` local from `:541` down instead.
   >    Confirming the field is genuinely dead today: `lc_state` is assigned at `:541` and
   >    `:365` is its **only** consumer anywhere in the file.
   >
   > *Why it matters:* `LC_STATE_TEST_DEV == 0x0` (`include/lifecycle.h:27`), so the wiped
   > field reads back as a plausible TEST_DEV rather than as an obviously-invalid value. On a
   > PROD_END part the "never demote, always lock both registers" branch therefore never
   > executes, `lc_write_demotion_2(false, true)` is never called, and **DEMOTE_2 is left
   > unlocked**. BL1 additionally receives a zeroed `lc_state` and `feat_ctrl_lo`/`feat_ctrl_hi`.
   > It fails open, and it is silent — nothing in the current 7-test ROM DV set covers it.
   >
   > *Verification:* assert `lc_state` is non-zero at the `:365` read on a PROD_END part, and
   > check `lcc_demote_lock_2` is asserted after handoff. #1581's
   > `lcc_demote_lock_{1,2}_probe_o` XMRs and `sep_efuse_lc_prod_end.toml` are exactly the
   > instrumentation and the fuse image this needs — both are in the KEEP set — and its
   > `sep_firmware_demotion_decision_*` PROD_END subset is the natural home for the test,
   > since those rows read none of the three manifest inputs and so port for free.
2. **The stack canary never gets checked.**
   The canary *is* placed — `rom_main.c:592` writes `STACK_CANARY_VALUE` (`0xDEAD5741`) to
   `__stack_bottom`. The check at `:641` reads it back. But `:636` calls
   `rom_manifest_validate_handoff()`, and **every path out of that function ends in a
   `noreturn` call**: `rom_err_fail(mfst_err)` at `:340`, `rom_err_fail(...)` on the fuse-lock
   confirm at `:405`, and `rom_err_fail(ho_err)` at `:414` after `rom_handoff_bl1()` (which
   itself only returns on failure). So control never comes back and `:641` is **dead code**.

   Nothing caught it because `rom_manifest_validate_handoff` is declared plain `static void`
   at `:334` — the file already uses `__attribute__((noreturn))` at `:153`, `:156`, `:160`, so
   the idiom is right there, just not applied here.

   > **TODO — fix.** Two parts:
   >
   > 1. **Move the check to where it can fire, and where it means something.** Not before the
   >    handoff call at `:636` — that would check the canary *before* the deepest stack usage
   >    (RSA-3072 modexp, SHA-256 and AES all run inside `rom_manifest_boot()` at `:337`) and
   >    would be worse than useless. Put it **inside `rom_manifest_validate_handoff()`,
   >    immediately before `rom_handoff_bl1()` at `:412`** — after the crypto has peaked the
   >    stack and after the fuse-secret lock is confirmed, but before control leaves for BL1.
   >    Keep `rom_err_fail(ROM_ERR_STACK_OVERFLOW)` as the action.
   > 2. **Mark `rom_manifest_validate_handoff` `__attribute__((noreturn))`** so that anything
   >    placed after the call site is unreachable by declaration rather than by accident. This
   >    is the part that stops the bug recurring.
   >
   > Also worth taking from #1581: its `rom.ld` gains
   > `ASSERT(__stack_bottom < __stack_top)`, which catches a *silently disabled* canary — the
   > case where the linker layout collapses the guard region and the check passes trivially.
   > Cheap, and it covers the failure mode the C check cannot see.
   >
   > *Verification:* the check must be shown to fire, not merely to compile. Force it — write
   > a wrong value to `__stack_bottom` just before the new check point, confirm
   > `ROM_ERR_STACK_OVERFLOW` is reported and the boot stops, then revert. A canary check that
   > has never been observed failing is indistinguishable from the dead one being replaced.

3. **BL1 validity is checked too late to fail over to the backup slot.**
   Current order inside `rom_manifest_validate_handoff()`: `rom_manifest_boot()` (slot
   rotation + crypto) at `:337` → demotion at `:364-395` → `lock_fuse_secrets()` at `:399` →
   `check_fuse_secrets_locked()` at `:404` → `rom_handoff_bl1()` at `:412`. The BL1 presence
   and placement checks live in `rom_handoff.c:116-145`, i.e. inside that last call.

   So a manifest that passes the whole crypto chain but whose payload has **no
   `"OCAHSEP BLSTAGE1"` image**, or a BL1 whose `load_addr`/`entry_point` is out of range, is
   only discovered at `:412` — by which point demotion has been written and locked and the
   fuse secrets are locked. `rom_err_fail(ho_err)` then ends the boot outright. **The backup
   slot is never tried**, even though it may hold a perfectly good manifest.
   `oca_boot.c:298-302` only catches the degenerate `payload_span == 0` case.

   > **TODO — fix.** Split the handoff work by *when* it must happen:
   >
   > - **Validation moves earlier, per slot.** Call the BL1 lookup
   >   (`oca_toc_image_at()` scanning for the `"OCAHSEP BLSTAGE1"` type string) plus the
   >   `load_addr` region check and `entry_point < length` from **inside
   >   `try_manifest_slot()`** in `oca_boot.c`, so a slot without a loadable BL1 fails *that
   >   slot* and the rotation loop moves to the backup — the same WARN-per-slot,
   >   ERROR-after-all-slots shape the existing per-slot crypto failures already use.
   > - **The copy and the jump stay where they are**, at `[C18]`. This is required, not just
   >   tidy: **[SEP-ROM-MAN-060]** says "the copy shall not be permitted to corrupt the staged
   >   manifest before validation completes (the copy happens strictly after all checks pass,
   >   at hand-off)". Validating early and copying late is exactly what the spec asks for.
   > - Report the per-slot BL1 rejection distinctly from the transport and crypto failures so
   >   a console log says which slot lacked a BL1, reusing the existing
   >   `SEP_MSG_BL1_BAD_ADDR` / `BL1_ADDR_RANGE` vocabulary.
   >
   > **Sequence this together with the BL1→ICCM change** — both edit the same validation in
   > `rom_handoff.c:134-136`, and doing them separately means touching it twice and merging
   > the second against the first.
   >
   > *Verification:* pack an image whose **primary** slot manifest validates but carries no
   > `BLSTAGE1` entry, and a valid backup. The ROM must WARN on the primary, boot from the
   > backup, and reach BL1 — today it dies with the secrets already locked. #1581's
   > `sep_primary_fail_backup_boot_base` (365 L) is precisely this scenario shape and asserts
   > the backup is provably valid first, so port that base and add this as one of its cases.
   > Also confirm `lc_write_demotion` has **not** run when the primary is rejected.

4. **Demotion-lock hole: DEMOTE_1 is left open when the manifest defers to BL2.**
   At `rom_main.c:377-388` the non-PROD_END path is:

   ```
   if (dc & OCA_DEMOTE_BL1_VALID) {  lc_write_demotion(bl1_demote, true);  }
   else                           {  /* "BL2 deferred: do NOT write or lock DEMOTE_1" */  }
   ```

   When `OCA_DEMOTE_BL1_VALID` is clear the register is left **unwritten and unlocked** — so
   any manifest that simply does not assert that bit leaves the BL1 demotion register open for
   later software to set at will. It fails open.

   #1581 narrows the unlocked case to the one situation that actually needs it. Its own comment
   states the defect in the same terms: *"Skipping the write whenever the BL1 selector bit was
   clear left DEMOTE_1 unwritten and unlocked for later software to set at will."*

   > **TODO — fix.** Adopt #1581's policy, which ports directly because the OCA
   > `demotion_control` bits map one-to-one onto the TBL1 fields it reads:
   >
   > | #1581 (TBL1) | this branch (OCA) |
   > |---|---|
   > | `selector_bits & (1 << SELECTOR_BIT_BL1_DEMOTION)` | `dc & OCA_DEMOTE_BL1_VALID` |
   > | `usage_constraints.flags & (1 << ..._BL1_DEMOTION)` | `dc & OCA_DEMOTE_BL1_ENABLE` |
   > | `flag_args & (1 << FLAG_ARGS_BIT_BL2_DEMOTION)` | `dc & OCA_DEMOTE_BL2_ENABLE` |
   >
   > Restructure to decide first, write once, defaulting to *closed*:
   >
   > ```
   > bool demotion_reg = false, lock_demotion = true;      // default: non-demoted + locked
   > if (lc_state == LC_STATE_PROD_END) { lc_write_demotion_2(false, true); }
   > else if (dc & OCA_DEMOTE_BL1_VALID) { demotion_reg = !!(dc & OCA_DEMOTE_BL1_ENABLE); }
   > else if (dc & OCA_DEMOTE_BL2_ENABLE) { lock_demotion = false; }  // ONLY unlocked case
   > // else: fall through on the defaults -> written non-demoted and locked
   > ```
   >
   > `lock_demotion = false` stays legitimate for exactly one reason: BL2 asked for a demotion,
   > so DEMOTE_1 must remain writable for BL2 to apply it. Every other path closes the
   > register. PROD_END additionally locks DEMOTE_2 — the one case where BL0 touches it at all.
   >
   > **Also defer the register write until after the fuse-secret lock**, as #1581 does, moving
   > it from `:377-388` to after `check_fuse_secrets_locked()` at `:404`. Its rationale is
   > sound and format-independent: *"the demotion register is the last fuse state BL0 changes,
   > so any fault while writing it cannot leave the secret fuses readable."* The corollary is a
   > constraint to record — **anything that needs to READ a secret must run before the lock**,
   > which pins where the UID key derivation and the boot measurement can go.
   >
   > *Verification:* per lifecycle state and per `demotion_control` combination, read back
   > DEMOTE_1's value and lock bit. The matrix to assert: PROD_END → non-demoted + locked (and
   > DEMOTE_2 locked); BL1_VALID → manifest's value + locked; BL2_ENABLE only → **unlocked**;
   > neither → non-demoted + **locked** (this is the row that fails today). #1581's
   > `lcc_demote_state_{1,2}_probe_o` and `lcc_demote_lock_{1,2}_probe_o` read it from the real
   > differential outputs rather than the console, and its `sep_firmware_demotion_decision_*`
   > family (8 tests) is built for exactly this — all in the KEEP set.

## Discard from #1581 — already solved here, or format-only

**Discard as duplicate** (verified present on this branch by other means): the HMAC big-endian
KEY packing and `cfg.f.key_length` (this branch's `Key_128`/`Key_256` selection by `key_len` is
strictly better); the empty-ROM-key-slot rejection (`oca_platform.c:407-412`); the
`PUBK_REVOKE` bit map 16/17/20/22/24 (`oca_platform.c:290-302`, plus the PQC banks); digest
fuses addressed by name (`oca_platform.c:317-338`); payload-hash-before-decrypt; per-image
SHA-256 vs TOC entry hash (`oca_boot.c:184`); encrypted-payload-requires-secure-boot
(`oca_boot.c:194`); and the per-slot crypto retry scope.

Note #1581 also "resolve[s] fuse key revocation by the RDL's bit positions" — the same defect
class this branch's spec work already fixed (`SEP_ROM_DOC_PLAN.md` item D1: select bit *N* and
revoke bit *N* name one key, no offset). Reconcile; do not apply twice.

**Discard as format-only:** `manifest_load.c` / `manifest_crypto.c` / `manifest.h` in full, the
three Grendel packer configs, the `encrypted_boot_spi` Makefile target, and #1581's comment
trimming in Makefile regions this branch rewrites anyway.

**Reject in favour of this branch:**
- The `+sep_crypto_edn_force` AES-EDN-force hunk in `tb_top.sv`. This branch deprecates that
  plusarg: the OCA ROM brings up the real ESRC→CSRNG→EDN chain itself, tests use
  `+esrc_noise_force`, and **forcing `edn_ack` violates the EDN req/ack data-hold protocol and
  trips `prim_sync_reqack_data`'s `SyncReqAckDataHold*` assertions** (the DV table in
  `BRANCH_CLEANUP_PLAN.md` records `SyncReqAckDataHold = 0` across all seven runs). Reroute
  `sep_firmware_encrypted_boot_test`'s entropy need to `+esrc_noise_force`.
- The `pack-images secure_boot_spi encrypted_boot_spi` c_build rules and the `smc_mem.hex`
  input declaration in `sep_sim_cfg.toml` — replaced by `oca-images` + `SEP_ENTROPY_BRINGUP=1`.
- Do **not** carry the `DCCM_SCRUB_BYTES=0` override its message advertises (~3.9× DV
  speedup): the squash contains its own reversal, and main's `sep_sim_cfg.toml` now says the
  scrub is *"left at the product default … as it now is in every boot_rom variant"* in three
  places. Take main's final state, not the message. This branch's Makefile still has `?= 0`,
  so adopt main's `0x20000` together with the un-clamped `vector.S` scrub, or the scrub is
  silently disabled.

## The 21-file conflict set

From `git merge-tree $(git merge-base origin/main <branch>) origin/main <branch>` (read-only).

### Changed in both (11)

| File | main | branch | Resolution |
|---|---|---|---|
| `src/rom_main.c` | 666→738 | 655 | **hard, mixed** — take the KEEP regions above; drop the pass-by-value plumbing and the separate `[C13.10]` crypto block |
| `dv/testlists/rom_fw.toml` | 163→**2250** | 240 | **hard** — keep all 68 of main's entries, rewrite this branch's 7 `module = "cpu.…"` keys to `rom_fw.…`, add its 3 OCA tests |
| `dv/tb/tb_top.sv` | 1867→2236 | 1876 | take main's wholesale **except** the AES-EDN hunk; fix the stale `TBL1` comment at `:675` |
| `src/hmac_sha256.c` | 216→272 | 237 | take only `check_no_error()`, the `goto fail` consolidation, the named digest-size constant |
| `src/aes_driver.c` | 193→236 | 277 | re-apply `check_no_alert()` + idle waits onto this branch's `aes_cbc_decrypt(..., key_bytes, ...)` |
| `src/rom_handoff.c` | 140→140 | 175 | **ICCM decision applies** — see below |
| `bootrom/prod/Makefile` | 356→369 | 499 | mechanical; 2 hunks already in rerere. Take `ROM_ICCM_CLEAR_ENABLE`, `DCCM_SCRUB_BYTES=0x20000`, the `SRAM_SCRUB_BYTES` note; drop `encrypted_boot_spi` |
| `dv/sep_sim_cfg.toml` | 528→614 | 549 | keep the `[pass_fail] abr_reg.sv` waiver pair; take this branch's `oca-images` c_build rule |
| `dv/docs/SEP_TB_ARCH.adoc` | untouched by #1581 | — | trivial: one `tt-boot-manifest` → `tt-oca-manifest` line |
| `.gitignore`, `pyproject.toml` | — | — | union both edits (ruff `I001` ignore + submodule rename) |

### Removed in remote (7) — this branch deletes, main modified

`include/manifest.h`, `include/manifest_crypto.h`, `src/manifest_crypto.c`,
`src/manifest_load.c`, `configs/non_secure_boot_test.yaml`, `configs/secure_boot_test.yaml`,
and the `tools/tt-boot-manifest` submodule. Confirm the deletions, and in the same commit
remove what #1581 left depending on them — `configs/encrypted_boot_test.yaml` (new in #1581,
so it is not in this list) and the `encrypted_boot_spi` target.

### Removed in local (3) — #1581 renamed them

`cocotb/tests/cpu/sep_rom_{non_secure,ot_dma,ot_secure}_boot_test.py` →
`cocotb/tests/rom_fw/`. This branch's edits must be redirected to the new paths.

## BL1 placement: data-driven, ICCM **and** SRAM

ICCM must be supported; SRAM stays supported. Honour the TOC entry's `load_addr` as
**[SEP-ROM-MAN-050]** already specifies ("copy it from its staged location to the entry's
`load_addr`") and validate it against either permitted region, rather than hardcoding one.

- `rom_handoff.c`: replace `copy_bl1_to_sram()` (CPU word loop) with `sep_dma_copy()`
  unconditionally. **The LSU cannot store to ICCM at all** — ICCM and DCCM share VeeR region
  `0xC`, so the LSU faults any ICCM address — while the DMA reaches both. One path for both
  destinations is simpler than branching on the region, and #1581 already added the
  `sep_dma_copy()`/`sep_dma_zero()` plumbing. Delete the comment block at `:17-20` claiming
  "no ICCM/DCCM split to honour"; it stops being true once ICCM is a legal target.
- Widen the placement check at `rom_handoff.c:134-136` from
  `contains_range(SRAM_BASE, SRAM_SIZE, …)` to **SRAM ∪ ICCM** (`SEP_IRAM_BASE/SIZE`), keeping
  `entry_point < length`. Reject anything in neither with the existing `BL1_ADDR_RANGE` /
  `SEP_MSG_BL1_BAD_ADDR` path — an out-of-region `load_addr` is attacker-influenced.
- `vector.S`: the warm-handler range check must cover **both** regions. This branch checks
  `[SEP_SRAM_BASE, SEP_BOOT_ROM_BASE)`; #1581 checks ICCM. Taking either alone rejects
  legitimate handler addresses for the other, which is precisely how mixing the two designs
  breaks warm reset — so this must be two range tests, not a swap.
- Adopt `bl0_state.bl1_image_src_addr` so a BL1 running from ICCM can reach its own
  `.rodata`/`.data` load image, which stays in SRAM.
- Take #1581's `bl1_pass_test` relink (`iccm (rx) : ORIGIN = 0xC0000000`, `.data` LMA copied
  down to DCCM by `_start`) — that exercises the ICCM path in DV.
- Point this branch's `oca_*_boot_image.yaml` configs at `load_addr: 0xC0000000` to match, so
  the default DV path is the ICCM one; SRAM remains reachable by config for anything that
  needs it. **This is the payoff of data-driven placement: the region becomes a config
  property, not a ROM rebuild.**
- Take `include/measurement.h` (self-contained; does **not** include `manifest.h`). It needs a
  32-byte digest — `oca_boot.h` exposes no digest accessor, so either add one or SHA-256
  `rom_oca_body()` over `pk.body_size`. **Decide deliberately: the measurement layout is a
  verifier-facing contract.**

### Spec edits in `hw/sys/sep/bootrom/prod/doc/rom.adoc`

This branch is what *adds* the spec, so these are edits to our own new file, not conflicts.
Both regions become legal BL1 targets:

| Line | Change |
|---|---|
| 1536-1538 | **[SEP-ROM-MAN-060]** "shall lie entirely within SEP SRAM" → within **SEP SRAM or ICCM**, `entry_point < length` unchanged |
| 237 | SRAM row: "BL1 executes from here" → "BL1 may execute from here" (keeps manifest/payload staging) |
| 267 | ICCM row: add that it is also a legal BL1 load/execution target |
| 662 | "BL1 … runs from SRAM" → runs from its TOC `load_addr` (SRAM or ICCM) |
| 668 | "The handler must lie in SEP SRAM" → in SEP SRAM or ICCM; `warm_scratch[0]` → `cold_scratch[7]` |
| 751, 870, 874, 2405 | PMP: entries 3 (SRAM) and 5 (ICCM) are both BL1-capable launch regions; the execute-fence release applies to whichever the manifest selected |
| 3030 | requirement-index row "(SRAM bounds, entry < length)" → "(SRAM or ICCM bounds, …)" |

Add a DV case for the negative: a `load_addr` in **neither** region must be refused. #1581's
`sep_bl1_entry_invalid_test` covers an entry point outside the window and is the natural place.

Re-run the mechanical checks in `hw/sys/sep/doc/checks/` afterwards — per
`SEP_ROM_DOC_PLAN.md`, every one of those passes found something a careful read had missed.

## The 68 tests

Measured, not assumed. All 68 use `module = "rom_fw.*"`; 66 build `boot_rom_ot` from
`build_ot/boot_rom.vmem`; the only artifacts named in `args` are ROM `.vmem` builds,
`build/smc_mem.hex`, and the new eFuse TOMLs — **nothing Grendel-specific comes through
`args`**, so the break vector is the Python staging layer.

| | count |
|---|---|
| reach `env/sep_manifest_mutate.py` or `env/sep_payload_mutate.py` (transitive) | **52** |
| independent of the manifest format | **16** |

`sep_manifest_mutate.py` *is* the TBL1 layout: `MANIFEST_MAGIC = b"TBL1"`,
`MANIFEST_SIZE = 1184`, `TBS_LEN = 744`, 11 fixed offsets. 40 of the 52 couple through just
**four shared base classes** — `sep_backup_manifest_fail_base` (428 L),
`sep_primary_fail_backup_boot_base` (365 L), `sep_demotion_decision_base` (785 L),
`sep_chiplet_pubkey_base` (710 L) — which is where the leverage is.

**Nothing in the 68 is a discard on the merits.** No test asserts a property that exists only
because the manifest is TBL1. The assertion layers (ordering chains, exactly-once counts,
forbidden markers) transfer verbatim; only the injection layer needs rewriting.

### Port approach

Port `sep_manifest_mutate.py` to OCA behind the **same function API** — `slot_base`,
`slot_span`, `erase_slot`, `set_security_version`, `set_signature_type`, `set_public_key_sel`,
`corrupt_public_key`, `flip_signature_byte`, `set_life_cycle_states`, `set_usage_flags_bit`,
`rehash`, `verify_layout`, … Every concept has an OCA analogue, so most of the 52 keep working
unchanged. **Import the offsets from the submodule's `src/oca/constants.py`** rather than
hardcoding them (`OFF_SELECTOR_BITS`, `OFF_LIFECYCLE_{CHIPLET,PACKAGE,SYSTEM}_STATES`,
`OFF_DEMOTION_CONTROL`, `OFF_SECURE_BOOT_CONTROL`, `OCAC_MAGIC`, `OCA_CLASSIC_BODY_SIZE`,
`OCA_CLASSIC_SIGNED_REGION_END`): `constants.py` is the stated authority for manifest offsets,
and hardcoding is precisely the drift that Phases 9–11 of the doc plan kept re-fixing.

Watch the semantic widenings: selector bits go u64 → 16 bytes (a 128-bit bitmap, matching
`plat_is_key_authorized`), and one Grendel `life_cycle_states` becomes three OCA fields
(chiplet/package/system).

Salvage before deleting the two modules (~120 lines, zero manifest knowledge):
- `sep_manifest_mutate.py:151-206` — slot geometry (`PRIMARY_MANIFEST_OFFSET = 0x1000`,
  `BACKUP_MANIFEST_OFFSET = 0x41000`, `ERASED_BYTE`). This branch's
  `sep_rom_oca_tamper_test.py:42-43` independently hardcodes the same two offsets.
- `sep_payload_mutate.py:114-185,342` — a stdlib-only PKCS#1-v1.5 sign/verify and PKCS#8 DER
  reader, written because the DV virtualenv has no `cryptography`. Any OCA negative test that
  mutates a signed region needs exactly this.

`sep_spi_slot_evidence.py` (118 L) is only *incidentally* coupled — two symbol references at
`:83` and `:91`. Repoint them and keep the file whole.

**Adopt this branch's `expect_fw_pass` in `sep_boot_scoreboard.py` before porting negative
tests.** #1581 solved the same problem by hand-rolling poll loops in 40 files and bypassing the
scoreboard; the flag lets the ported tests shrink substantially.

## Execution order

Work on an integration branch off `origin/main`, e.g. `inmcm/sep_rom_oca_manifest_int`.

0. **Fix the `init_bl0_state()` wipe on `inmcm/sep_rom_oca_manifest` as it stands**, before
   the rebase — its own commit, both halves (reorder `[C9c]`, and stop `rom_main.c:365`
   re-reading the wiped `lc_state`). Doing it pre-rebase keeps the fix reviewable on a small
   diff and means it survives independently if the rebase is redone. See item 1 above.

   *Sequencing note, because it is a genuine trade-off:* items 1, 2 and 4 all edit
   `rom_main.c`, which is one of the 11 "changed in both" files and the hardest hand-merge in
   the rebase. Fixing them pre-rebase means their hunks have to be re-resolved during it. The
   split below is deliberate — only item 1 pays that cost, because it is the security fix and
   must not be lost if the rebase is restarted. Items 2 and 4 are folded **into** the
   `rom_main.c` resolution instead (step 3), where #1581's own corrected versions sit right
   there in the conflict as the reference implementation, so the same hunks are touched once
   rather than twice.
1. `git rebase origin/main` and resolve the 21 files above. Two Makefile hunks replay from
   rerere. Expect the real work in `rom_main.c`, `rom_fw.toml`, `tb_top.sv`.
2. **The package move as its own commit**: `cpu/sep_rom_*` → `rom_fw/`, add
   `rom_fw/__init__.py`, rewrite `cpu.` → `rom_fw.` imports, move this branch's three
   `sep_rom_oca_*` tests into `rom_fw/`, and rewrite the 7 `module =` keys in its testlist.
   `sep_rom_ot_pio` and `sep_rom_ot_secure` are trivial; `sep_rom_ot_dma_boot_test.py` (R067)
   needs a hand-merge with overlapping hunks — **pick one eFuse hook name: keep
   `build_efuse_image` (40+ #1581 subclasses) over `make_efuse_image` (2 here).**
3. **Close out the remaining shared defects, as part of resolving `rom_main.c`:**
   - **Item 2, canary** — move the check inside `rom_manifest_validate_handoff()` immediately
     before `rom_handoff_bl1()`, and mark that function `noreturn`. Take #1581's
     `ASSERT(__stack_bottom < __stack_top)` in `rom.ld` (arrives with the rebase).
   - **Item 4, demotion** — adopt the decide-first / default-closed structure, with
     `lock_demotion = false` reachable *only* when `OCA_DEMOTE_BL2_ENABLE` is set, and defer
     the register write until after `check_fuse_secrets_locked()`.
   - Re-confirm **item 1** survived the rebase intact (it is in the same function region).

   Then, separately: **item 3, BL1 per-slot validation** — move the BL1 lookup and placement
   check into `try_manifest_slot()` in `oca_boot.c`, leaving the copy and jump at `[C18]`.
   Do this **in the same commit as the BL1→ICCM widening** (step 4), since both rewrite the
   placement check at `rom_handoff.c:134-136`.
4. Apply the BL1→ICCM change and the spec edits together, so code and spec never disagree.
5. Port `sep_manifest_mutate.py` to OCA, then re-green families in this order (cheapest and
   most format-free first): MBIST → warm-reset → SPI detect → failover-SRAM-clear → straps →
   secure-boot decision → BL1 version → chiplet pubkey → OTBN RSA → BL1 image validity →
   encryption → `backup_*`/`primary_*` → demotion (last; three of its four inputs are manifest
   fields, so start with the PROD_END short-circuit rows which read none).
6. One PR to `main`.

## The VP branch — don't rebase it

Proposed: rebase `feature/sep_virtual_platform` onto main, then rebase `_clean` onto the
updated feature branch. Mechanically possible, but the first half is the trap, and the second
half turns out to be unnecessary.

**Measured topology:**

| Branch | State |
|---|---|
| `origin/feature/sep_virtual_platform` | `d14133828` (PR #1444 merge); **42 commits / 4 merges** ahead of `merge-base 99bb553c2`; main is **134** ahead |
| local `feature/sep_virtual_platform` | stale at `efb2a6e77`, 44 behind origin |
| `inmcm/integrate_oca_boot_manifest_clean` | **33 commits, 0 merges**, based exactly on `d14133828` |

**Why not to rebase the feature branch:**

1. **It is shared and must not be rewritten** — the split plan and the standing rule both say
   so. It carries 4 merge commits from PRs #1309 / #1440 / #1444, and PR #1028 is open against
   it. A rebase force-pushes public history and invalidates that PR and everyone's clones.
2. **Its history contains the criss-cross merge.** Both `3992783fd` and `a613783c3` —
   *"[VP] Add the sepvp runner package and pytest harness plugin"* — are in
   `99bb553c2..origin/feature/sep_virtual_platform`. That duplicate pair is the head of **18
   patch-identical commits** (verified by `git patch-id`: 17 of 18 identical, the 18th
   differing only in `uv.lock` regeneration noise). Linearising the feature branch replays all
   18 twice. **This is exactly what the first rebase attempt in this session ran into** — a
   71-command todo with a duplicated 18-commit block, which is why it stalled on a `uv.lock`
   conflict two commits in.

**Merge main into the feature branch instead.** One merge commit, conflicts resolved once, no
force-push, PR #1028 survives, the merge bases stay intact, and the 18 duplicates never
replay because nothing is linearised.

**And `_clean` needs splitting, not rebasing.** Its 33 commits separate perfectly — **8
VP-only, 25 ROM/DV/doc-only, zero mixed** (verified per-commit by path prefix). Once the
ROM/DV/doc work lands on `main` and main is merged into the feature branch, those 25 arrive
from main and `_clean`'s copies become redundant — a wholesale rebase would replay 25 commits
that conflict with or empty against their own content.

So rebuild `_clean` as just its **8 VP-only commits** on the updated feature tip:

`5742e3e22` CLASS_KEY for encrypted boot · `b502c47ad` OCA boot coverage + eFuse map drift
guard · `c79344b1b` signature-class refusal · `308dec0d0` per-slot ROM key use/revoke/isolate
· `da159b3e7` drop the Grendel signed-image fixture · `24019521f` fingerprint status-table
contents · `1ea6abd07` manifest tooling paths → tt-oca-manifest · `0960d2908` uprev
tt-oca-harness-model

That is a small, reviewable PR into the feature branch, and each of those 8 depends on ROM
changes that will already be present via main. Build it beside the original — never rewrite
`_clean` in place.

**Order of operations:**

1. ROM/DV/doc → `main` (the plan above).
2. Merge `origin/main` into `feature/sep_virtual_platform`, resolving VP-vs-main once. All the
   fixups from step 1 — BL1 placement, the `init_bl0_state` reordering, the SMC offsets —
   arrive automatically.
3. Rebuild `_clean`'s 8 VP-only commits on the new feature tip → PR to the feature branch.
4. PR #1028 takes the feature branch to `main` when VP is ready.

If VP is closer to ready than the ROM work, invert 1 and 2: land PR #1028 first, and then
`_clean` rebases onto `main` directly with no feature branch in the middle.

## Verification

- **ROM builds**: `make -C hw/sys/sep/bootrom/prod` for all three variants (Cadence, OT,
  OT-PIO) plus `oca-images`. Watch the size budget — the branch's four review fixups took the
  binaries to 39816 / 42760 / 41936 B against a 64 KiB budget.
- **Prove the ICCM handoff**, don't assume it: the LSU cannot store to ICCM, so a CPU-copy
  regression fails as a bus error → NMI, not a clean miscompare.
- **ROM DV**: `python3 tools/dv/run_dv.py --dut sep --items <test> --tool vcs`. The 16
  format-free tests must be green *before* the port starts — that is the gate that says the
  rebase itself is sound. Then the 52 as they are ported. `sep_scratch_7_test` is a
  **known pre-existing red** on main (#1581 says so); do not chase it.
- Each run is 400–1700 s; budget accordingly and cap `--stage sim` runs.
- **Assert `SyncReqAckDataHold` and `FLASH_READ_OOB` stay at 0** across runs, as the seven-test
  table in `BRANCH_CLEANUP_PLAN.md` does. Zero `FLASH_READ_OOB` matters as much as the passes:
  it shows the bounds gate is live in the binary and refused nothing legitimate.
- **The four defect fixes each need positive evidence, not just a passing regression** — all
  four are fail-open, so a green suite is exactly what they look like today:
  | Defect | Evidence required |
  |---|---|
  | 1 `init_bl0_state` | `lc_state` non-zero at the `:365` read on a PROD_END part; `lcc_demote_lock_2` asserted after handoff |
  | 2 canary | force a wrong value at `__stack_bottom` and observe `ROM_ERR_STACK_OVERFLOW`, then revert |
  | 3 BL1 per-slot | primary with no `BLSTAGE1` + valid backup → WARN on primary, boots from backup, and `lc_write_demotion` did **not** run |
  | 4 demotion | read back DEMOTE_1 value + lock bit across all four rows; the "neither bit set → locked non-demoted" row is the one that fails today |
- **PR gates**: `ruff check` + `ruff format`, and the SPDX block on new files. `codespell` and
  `clang-format` only comment. Also `sep_generate_efuse_preload.py --selftest`, which #1581
  added to `lint.yml`.
- Re-run `hw/sys/sep/doc/checks/` after the spec edits.
- Cross-check the result against the VP branch: `BRANCH_CLEANUP_PLAN.md` tracked "91 of 102
  non-VP files identical". Recompute after the rebase.

## Loose ends worth recording

- **`dv/docs/rom_verdict_scratch0_migration.md` does not exist on main** but is cited by
  `sep_verdict.py:31`, `sep_base_test.py`, `sep_rom_non_secure_boot_test.py` and
  `sep_rom_ot_dma_boot_test.py`. Four dangling references either way.
- Adopting `errors.h`'s `VERDICT_OUT`/`rom_test_fail()` and deleting `rom_mbx.h` is
  all-or-nothing: it touches `rom_main.c:648-649` and `:182` here, plus whatever DV gates on
  the mailbox. Sequence it as one commit.
- #1581 flags two of its own follow-ups: `MBIST_DONE_WAIT_ITERS = 10000` is uncalibrated, and
  `STATUS_RPT` bit 2 is an undeclared use of a reserved bit borrowed from another chip's efuse
  schema. Neither blocks; both should outlive this rebase as issues.
- Unverified and worth confirming before acting: whether the OCA validator library's
  `oca_check_payload_at()` payload hash covers inter-image gap bytes, which decides whether
  #1581's image ordering/overlap checks and gap zeroization are genuinely redundant. The
  library lives in the `tt-oca-manifest` submodule, which is **not checked out** in
  `tt-oca-harness-main` (it is in the sibling `tt-oca-harness` worktree).

---

## Outcomes: defect fixes (2026-09-08)

Three of the four shared defects are fixed and committed on
`inmcm/sep_rom_oca_manifest`, **pre-rebase**, one commit each.

| Commit | Defect |
|---|---|
| `5cfe16b87` | 1 — `init_bl0_state()` wipe |
| `765857c1b` | 2 — dead stack-canary check |
| `3e790f18d` | 4 — DEMOTE_1 left open |

Item 3 (BL1 validity per slot) is still open, deliberately: it is sequenced with the
BL1→ICCM widening, which needs #1581's `sep_dma_copy()`, so it waits for the rebase.
(Since done — see *Outcomes: item 3, and two defects DV found*.)

### Sequencing deviation from the plan above

The plan put items 2 and 4 *inside* the post-rebase `rom_main.c` resolution to avoid
resolving the same hunks twice. They were done pre-rebase instead, because item 1's fix
already touches both regions those items live in (the handoff signature and the [C15]
demotion block), so the marginal conflict cost is close to zero — while the benefit is that
all three fixes are small, independently reviewable, and survive a restarted rebase. Item 3's
sequencing is unchanged.

### ROM size, all three variants, warning-free

| Variant | Before | After | Δ |
|---|---|---|---|
| default (Cadence) | 39816 | 40048 | +232 |
| OT | 42760 | 42984 | +224 |
| OT-PIO | 41936 | 42160 | +224 |

Inside the 64 KiB budget with ~23 KiB spare. The baseline was rebuilt and measured at exactly
39816 B, matching `BRANCH_CLEANUP_PLAN.md`, so the deltas are attributable to these commits
and nothing else drifted.

### What the fixes turned out to be

**Item 2 was worse than "reordering needed".** The canary was *written* all along but never
verified: `0xDEAD5741` appeared nowhere in the pre-change binary in any materialisation,
because the check sat after a call that never returns and GCC stripped it. The fix moves the
check inside `rom_manifest_validate_handoff()`, immediately before `rom_handoff_bl1()` —
after `rom_manifest_boot()`, where the RSA-3072 modexp, SHA-256 and AES actually peak the
stack. Marking that function `noreturn` is the part that stops the defect recurring, and it
also retired the rest of the trailing block: **the ROM has no PASS path of its own.**
`bl1_pass_test` writes the same `MAGIC0` + `PASS` words itself, so `ROM_FW_MAGIC0` /
`ROM_FW_PASS` had no consumer anywhere in the tree. `rom.adoc` had already flagged the dead
check as an implementation gap; that gap now narrows to the stack-top check
(SEP-ROM-HOFF-020), which remains absent.

**Item 4 required a normative spec change, not just a code fix.** SEP-ROM-DEM-030 *mandated*
the fail-open — "If bit 0 is clear, the ROM shall leave `DEMOTE_1` untouched and unlocked".
The requirement was rewritten to the closed default, SEP-ROM-DEM-035 added for the write
ordering, and the requirement index and its "All 94" count updated to 95. Two extra findings
along the way:
- The unlock condition needed `BL2_VALID` **and** `BL2_ENABLE`, not ENABLE alone — otherwise a
  stray ENABLE on a manifest that never stated a BL2 pair still leaves the register open.
  `OCA_DEMOTE_BL2_VALID` already existed in `oca_boot.h`; nothing was reading it.
- The same predicate has to drive the unlock decision *and* `bl0_state.bl2_demotion_decision`,
  or BL1 is told to demote a register the ROM has locked.

The demotion gap admonition **narrows rather than closes**: `bl2_demotion_decision` is a
single bool, so "not specified" and "specified as no demotion" both reach BL1 as `false`.
Closing that needs a two-bit hand-off field and was left alone.

### Verification actually run

- All three ROM variants build warning-free; sizes above.
- Item 2 proved by codegen, not inspection: `lui a4,0xdead5` + `addi` + `bne` to the failure
  path are present in `boot_rom.dis` where the baseline had no reference to the constant at
  all.
- All six doc checks pass (`check_tables` 32/32, `check_reg_addresses` RDL↔header↔docs agree,
  `check_error_codes` all cited codes exist, `check_manifest_offsets` 10/10). Requirement
  anchors and index agree at 95/95. `asciidoctor` renders `rom.adoc` with no new errors.
  The one `check_xrefs` hit is a pre-existing false positive in
  `hw/ip/system_timer_octs/doc/memmap.adoc`, where a C snippet `<<32) | lo;` parses as an xref.
- **Not run: any DV.** The behavioural evidence each fix needs — `lc_state` non-zero at the
  PROD_END read, `lcc_demote_lock_2` asserted, a forced canary failure reporting
  `ROM_ERR_STACK_OVERFLOW`, and the four-row DEMOTE_1 truth table — all wants the eFuse
  preloads and `lcc_demote_*_probe_o` instrumentation that arrive with #1581. That is a real
  gap: these are fail-open defects, so a green suite is what they looked like before. The
  evidence has to be collected after the rebase.

---

## Outcomes: step 1, the rebase (2026-09-08)

**Done.** `inmcm/sep_rom_oca_manifest_int` @ `365d5aaf8` — **31 commits on `origin/main`**
(`2cee2026e`). `inmcm/sep_rom_oca_manifest` (`3e790f18d`) and
`backup/sep_rom_oca_manifest-prerebase-20260908` (`5adc5206f`) are untouched, per the
never-rewrite rule: the integration branch was cut and rebased, not the original.

### The thing worth knowing: #1581 had already fixed three of the four defects

This is the correction to the previous section. Replaying commit 29 revealed that #1581
independently made the **same** `init_bl0_state()` fix — `[C9c]` ahead of `[C6]`, `lc_state`
passed by value — **and more**, adding a `BL0_STATE_ADDR < __stack_top` runtime check for
linker/header constant drift that mine lacked. That commit was **skipped as fully redundant**.
Main had also already fixed the canary reachability and the demotion policy.

So the plan's original sequencing — fold items 2 and 4 into the post-rebase `rom_main.c`
resolution — **was right, and the deviation cost real duplicated work.** The lesson is
narrow and worth keeping: before fixing a defect found by triaging someone else's commit,
check whether that commit already fixes it. The triage said "#1581 KEEP: stack canary check
moved before handoff" and "demotion: lock DEMOTE_1 non-demoted unless BL2 asked" — both were
in the report, and both were read as *main's problem statement* rather than as *main's fix*.

Two pieces of that work did survive on merit:

- **The canary placement is better than main's.** Main checks it in `rom_main` *before*
  calling `rom_manifest_validate_handoff()`, which is before `rom_manifest_boot()` runs — so
  it samples the canary ahead of the RSA-3072 modexp, SHA-256 and AES frames that are where
  the stack actually peaks. The check now lives inside the callee immediately before
  `rom_handoff_bl1()`: after the deep frames, before control leaves. The function is also
  marked `__attribute__((noreturn))`, which main left unmarked — so its "unreachable" comment
  was convention, and is now compiler-enforced.
- **The `BL2_VALID` tightening**, which main does not have: main tests the BL2 ENABLE bit
  alone, so a stray ENABLE on a manifest that never stated a BL2 pair still leaves DEMOTE_1
  unlocked. Plus the whole `rom.adoc` requirement rewrite (DEM-030/-035/-040, index 94→95),
  which has no counterpart on main because main has no such spec.

### Notable resolutions

| File | Decision |
|---|---|
| `manifest_load.c`, `manifest_crypto.c`, `manifest.h` | deletion confirmed; #1581's hardening of them discarded as format-only, its format-independent halves kept elsewhere |
| `rom_main.c` `[C15]` | main's corrected decide-first/deferred-write **structure** kept, field access moved to OCA `demotion_control` |
| `rom_handoff.c` | **merged**: our OCA TOC lookup + main's `sep_dma_copy()` into ICCM and `bl1_image_src_addr`. Taking our SRAM side would have broken warm reset against main's `vector.S`, which range-checks the handler against ICCM |
| BL1 bounds | `OCH_SEP_TOP_SEP_ICCM_BASE_ADDR/_SIZE` from the generated register map, not the hand-written `SEP_IRAM_*` that died with `manifest.h` |
| `hmac_sha256.c` | main's `check_no_error()` + named digest constant; **our** `key_length` selection (Key_128/Key_256 by `key_len`) over main's hardcoded Key_256, and `HMAC_KEY_LENGTH_128` added so neither path uses a bare literal |
| `tb_top.sv` | our AES-EDN hunk (`$urandom()`, fuller rationale) over main's fixed `AesEdnWord`; self-consistent, and the version the later entropy commit edits — that commit then applied cleanly |
| `sep_sim_cfg.toml` | main's internal-path-free `c_compile` commands every time, with our target list (`oca-images`, `SEP_ENTROPY_BRINGUP=1`) grafted on. **Zero internal paths in the result** |
| `sep_sim_cfg.toml` stub comment | our per-tool Verilator/VCS rule, but rewritten: main dropped the `prim_sync2` stub, so our text described a stub that no longer exists |
| `rom_fw.toml` | main's 68 entries taken wholesale, our 3 OCA entries appended, all `module` keys repointed to `rom_fw.` → **71 tests** |
| Grendel targets | `secure_boot_spi`, `encrypted_boot_spi`, `pack-images`, `SMC_MEM_HEX` and `encrypted_boot_test.yaml` all removed — including the config #1581 had just added |
| `toolchain-images` | main's **container-dispatch** version kept (a #1581-era improvement our side would have collapsed back to a direct build) |

The `tests/cpu/` → `tests/rom_fw/` package move had to be replayed by hand on **seven**
commits. `build_efuse_image` (main, 40+ subclasses) won over our `make_efuse_image` (2), and
our three `sep_rom_oca_*` tests moved into `rom_fw/` with imports repointed.

### Deliberately deferred, not dropped

**The `[C15]` boot measurement.** #1581 records a SHA-256 over the manifest hash, LC state,
demotion decision, `secure_boot` and `sboot_dis` — reading the digest from
`manifest_t.manifest_hash`, a field of the deleted format. `oca_boot.h` exposes **no digest
accessor**, and what the measurement commits to is a verifier-facing contract, so it is not
wired to an inline offset inside a conflict resolution. `measurement.h` is still in the tree,
unused, and there is an in-code NOTE at the call site. **This is a #1581 feature currently
absent and it must land before the PR** — it needs a digest accessor on `oca_boot.h` first.

### Two mistakes I made and caught

- A `git add -A` staged a stale `tools/tt-oca-manifest` as an *embedded git repository* and
  some `build_chk/` artifacts. Unstaged; use explicit paths.
- A wholesale-copy helper for the package move clobbered #1581's `verdict_source` and
  `bring_up_cpu_boot` out of `sep_rom_ot_dma_boot_test.py`, and separately moved
  `sep_rom_sanity_test.py`, which main had *not* moved and which `memory.toml` references as
  `cpu.sep_rom_sanity_test`. Both restored from the rebase HEAD and re-applied as deltas; the
  helper is now guarded to the three files main does not also own. Wholesale copy is only safe
  where the other side has no changes.

### Verification

| Check | Result |
|---|---|
| ROM builds, all three variants | clean, **zero compiler warnings** |
| ROM sizes | 41208 / 44144 / 43320 B (default / OT / OT-PIO) — largest has ~21 KiB spare under 64 KiB |
| `make ocah-lint-python` (the CI gate) | **exit 0**, all checks passed |
| `ruff format --check` | 1321 files already formatted |
| `make ocah-lint-toml` | **exit 0** |
| Doc checks (tables, error codes, manifest offsets, reg addresses) | all pass |
| Requirement anchors vs index | 95 / 95 |
| SEP xref breaks | 0 |
| `asciidoctor` render of `rom.adoc` | clean |
| Grendel residue (`manifest_t`/`TBL1`, configs, targets) | none, bar one explanatory comment |
| `rom_fw.toml` | 71 tests, every `module` in the `rom_fw` package |
| #1581 keeps present | SMC offsets, `vector.S` MBIST gate + `trap_vector_early`, `check_no_alert`, `check_no_error`, UID read-locks, `measurement.h`, 19 eFuse TOMLs, `sep_generate_efuse_preload.py`, `sep_dma_zero` |

A **real gap the gates caught**: 34 `oca_*.yaml` configs plus `doc/checks/README.md` and
`doc/gen/status_values.adoc` had no SPDX header, though the Grendel configs they replace all
did. Fixed in `365d5aaf8`.

Also worth noting the ruff count was initially 402 errors — **all** of them inside the stale
`tools/tt-boot-manifest/` directory left on disk by the submodule rename, which is no longer
in `pyproject.toml`'s exclude list because the branch renamed it to `tt-oca-manifest`.
Removing the leftover directory took the gate to zero. A fresh clone will not have it, but
anyone rebasing across that rename locally will.

### Still open before a PR

1. **The 52-test port** (unchanged from the plan): `sep_manifest_mutate.py` → OCA behind the
   same API, offsets from `src/oca/constants.py`.
2. **Item 3, BL1 per-slot validation** — done; see *Outcomes: item 3, and two defects DV found*.
3. **BL1 placement is currently ICCM-only.** The agreed design is data-driven (SRAM ∪ ICCM,
   validated against both, warm-handler range covering both). The rebase resolved to ICCM
   because that is what keeps the tree self-consistent with main's `vector.S`; the widening
   and its spec edits are still to do.
4. **The boot measurement**, above.
5. **No DV has run.** Every behavioural claim for the four defects, and the whole 71-test
   suite, is still unverified by simulation.

---

## Outcomes: the tt-oca-hw measurement patch set (2026-09-08)

Source: `/localdev/cmccoy/dev/tt-oca-hw/sep_rom_migration/`, two never-landed `tt-oca-hw`
branches re-authored against the harness tree, with a 400-line `INTEGRATION.md`. Its §8 is
written for exactly this situation ("If the OCA manifest branch has landed") and its item 3
independently reaches the same conclusion this plan did — the manifest-hash accessor is *"a
design decision about what gets measured, not a mechanical rewrite. Escalate to a human
rather than inventing a substitute."*

**Decisions taken:** the patch's soft-PCR scheme replaces #1581's measurement; scope is the
three `02` patches. Patch `01` (handoff hardening) is **deferred**.

| Commit | What |
|---|---|
| `a633aaa0a` | `02/0001` (partial) — mandatory ROM-hash insert |
| `c6d044a1f` | `02/0002` — `mdseac`/`mscause` in the trap handler |
| `afae4b17b` | `02/0003` — soft measurement enrollment |

Branch is now **34 commits on `origin/main`**, tree clean, `ocah-lint-python` and
`ocah-lint-toml` both exit 0.

### The blocker the plan had parked is closed

`oca_boot.h` exposed no digest accessor, which is why the rebase deferred the measurement.
The answer turned out to be available without inventing anything: the validator library's
`oca_variant.h` exposes `off_manifest_hash`, and `oca_variant_for_body()` returns the
descriptor. So `rom_oca_manifest_hash()` returns the OCA `manifest_hash` field located
through the library's own descriptor — **not** a literal offset, because the field sits
elsewhere in an OCA-PQC body and both offsets move with the format revision.
`oca_check_manifest_hash()` has already validated that field against the body it covers, so
what slot 1 commits to is the digest of what was actually authenticated. (Worth noting the
contrast: the pre-existing `rom_oca_demotion_control()` *does* hardcode `g_body[172]`.)

### Two things found that the INTEGRATION.md could not have known

**#1581 shipped a competing measurement.** Its header-only `rom_record_measurement()` hashed
the same inputs once into `bl0_state.measurement[32]` — no ROM self-verification, no extend
chain, no raw record for BL1. It had **no callers outside its own header**, so the
replacement was clean. `sizeof(struct bl0_state)` 96 → 188, so both reserve constants moved
128 → 256.

**An error-code collision, resolved in the spec's favour.** The spec's registry already
allocates `0xF004` HANDOFF_SELFCHECK, `0xF005` ROM_HASH_MISMATCH, `0xF006`
MEASUREMENT_FAILED — because `rom.adoc` was written against *this* patch set. #1581's
`MEASUREMENT_FAILED = 0xF004` was the odd one out, and its undocumented
`BL0_STATE_OVERLAPS_STACK` was squatting on `0xF005`. Now: ROM_HASH_MISMATCH `0xF005`,
MEASUREMENT_FAILED `0xF006`, BL0_STATE_OVERLAPS_STACK `0xF007` (with a spec row added, it had
none), and `0xF004` left reserved with a comment for the deferred patch 01.

### A genuine requirement conflict, resolved rather than papered over

**SEP-ROM-ATT-030** puts the slot-1 enrollment *before* the fuse-secret locks.
**SEP-ROM-DEM-035** — added earlier in this branch from #1581's rationale — defers the
`DEMOTE_1` write until *after* them. Both cannot hold if the measurement reads the register
back.

Resolved by having the record carry the *decided* values (`demotion_reg`, `lock_demotion`)
rather than a read-back: the decision is exactly what the deferred write applies, so the two
cannot disagree, and the record still reflects what BL0 applied rather than what the manifest
requested. Final order: demotion decision → **slot-1 enrollment** → fuse lock → `[C17]`
confirm → deferred `DEMOTE_1` write → `[C16]` canary → `[C18]` handoff. `rom.adoc` gains a
NOTE on ATT-030 recording the interaction.

### Verification

| Check | Result |
|---|---|
| All three ROM variants | warning-free; 42552 / 45496 / 44672 B, ~20 KiB spare under 64 KiB |
| Measurement symbols linked | `measurement_enroll`, `_rom_hash`, `_boot_state` all present |
| `sizeof(struct bl0_state)` | **188** ≤ 256; `__stack_top` = DCCM top − 256; `__bss_end` well below it |
| **Hashed-region agreement** (§5's silent-breakage invariant) | `__metadata_end` − ROM base = **32644 B** = objcopy extraction, exactly |
| `-MMD -MP` covers the new file | `measurement.d` generated; `rom_main.d` lists `measurement.h` |
| `insert-rom-sha256.py --verify` | exit 0, real hash embedded |
| **Mandatory-insert failure path** | script stubbed to fail → `make` exits 2 and `.DELETE_ON_ERROR` removes the partial ELF |
| Trap CSR reads | both `csrr` present in the `-Os` disassembly |
| Doc checks / anchors / render | all pass; 95/95; `asciidoctor` clean |

`.DELETE_ON_ERROR` was added beyond the patch set. §6.1 flags its absence as pre-existing,
but making the insert mandatory is what turns it into a live hazard: `$(ELF)` is linked then
patched in place, so a failed insert would otherwise leave an unpatched ELF that make treats
as up to date and ships on the next run.

**Not verified: no simulation.** `ROM_HASH_VERIFIED` and `MEAS_BOOT_STATE_OK` are now
required markers in `sep_rom_non_secure_boot_test`, but have never been observed on a real
console run. §7 of the INTEGRATION.md says the same of the original: nothing in that patch
set was ever validated in simulation on this DUT.

### Still open

Patch `01` (handoff hardening, `ROM_ERR_HANDOFF_SELFCHECK_FAILED` = `0xF004`) is deferred.
It closes the spec's own *"Handoff self-check ledger | unmerged"* gap. Its §8 adaptations are
known: re-express the two manifest-locus entries against `rom_oca_body()`, and either mark
`BOOT_GATE_CRYPTO`/`BOOT_GATE_HASH` on `rom_manifest_boot()` success or remove both bits —
never leave a bit in `BOOT_GATE_EXPECT` that nothing sets. Use
`01-handoff-hardening/standalone/` since `02` landed first, and budget for the `-Os`
disassembly check: §5 records that `volatile` alone did **not** keep the two evaluations
distinct in the original, which is why `harden_u32()` exists.

---

## TODO: comment and commit-message trim pass

`AGENTS.md` was updated (2026-09-08) to tighten comment style, and the work on this branch
does not meet it. A pass over the sources and the commit log is needed before the PR.

### The rule

`AGENTS.md` §Comments: write a comment only for what the code cannot say — a constraint, an
ordering that matters, a hardware behaviour a maintainer would otherwise rediscover. Present
tense, stating what is *true of the code*, not an account of what changed. Three kinds are
called out as not worth their space:

- **Narration** — restating the line below it.
- **Breadcrumbs** — why a change was made, what it replaced, which review asked for it. That
  belongs in the commit message, which stays accurate; a comment recording it is wrong after
  the next edit.
- **Justification** — arguing a change is correct addresses a reviewer who is gone once the PR
  merges.

§Names holds identifiers to the same rule: name what exists, not what changed.

### What to fix, concretely

The comments added on this branch are heavy on breadcrumbs and justification, and several
narrate the debugging that produced them. Known sites, worst first:

| File | Problem |
|---|---|
| `src/rom_main.c` `[C9c]` block | Narrates that the zeroing used to run after `[C6]` and what that wiped. Should state only that it must precede every `bl0_state` writer. |
| `src/rom_main.c` `[C15]` demotion | Explains the old fail-open behaviour and argues the new default is right. Should state the policy and the one case that stays unlocked. |
| `src/rom_main.c` `lc_state` param | "deliberately NOT re-read ... turned this into a silent LC_STATE_TEST_DEV" is a breadcrumb. The parameter existing is the fact. |
| `src/rom_main.c` `[C16]` canary | Argues at length why the position is correct. One line on what the position must satisfy is enough. |
| `src/rom_main.c` ICCM clear | Recounts why the flag used to be 0 and how the boot failed. Delete the history; keep the ECC constraint. |
| `src/rom_handoff.c` placement | Argues the check is the right one ("the check that matters, not..."). Keep the two permitted regions and the LSU/DMA constraint. |
| `src/hmac_sha256.c` `fifo_feed` | Justifies the credit scheme with transaction counts and cites the measurement's cost. Keep the FIFO depth source and why the credit is a lower bound; drop the arithmetic. |
| `src/vector.S` warm range | "That coupling is the point, not tidiness" argues to a reviewer. State that it tracks the cold-path policy. |
| `include/measurement.h` | Long preamble on PCRV roadmap and provisional status. Trim to the extend rule and the two slots. |

Also drop remaining references to `#1581`, run numbers, and "previously"/"used to" phrasing in
comments — provenance belongs in the commit message.

### Commit log

The 36 commits on `inmcm/sep_rom_oca_manifest_int` have bodies running 20-50 lines that
narrate the investigation: which DV run exposed what, what was measured, what was predicted
and did not hold. `AGENTS.md` asks for *why*, not the journey.

Rewrite them shorter and higher level: the title form is already right (`scope: Imperative
summary`), so this is a body pass. Keep the constraint or defect being addressed and the
consequence; drop run-by-run narrative, measured deltas that will not age well, and any
account of what was tried first.

The branch is **unpushed**, so this is a `git rebase -i --exec` reword pass over
`origin/main..HEAD`. Do it on the integration branch, which is already the copy —
`inmcm/sep_rom_oca_manifest` stays as the record of how the work actually went, so nothing is
lost by compressing the integration branch's messages.

Sequence this **after** DV is green and before opening the PR: rewording earlier invalidates
nothing but has to be redone for every commit added in the meantime.

---

## Outcomes: item 3, and two defects DV found (2026-09-08, later)

### Run 5's failure was a stale object, not the ROM

Run 5 handed off correctly — `ROM_HASH_VERIFIED`, `MANIFEST_OK`, `PAYLOAD_OK`,
`MEAS_BOOT_STATE_OK`, `DEMOTE_LOCKED`, `FUSE_SECRETS_LOCKED` all present, `0 trap(s)`,
`iccm_act=1` — and then BL1 itself signalled failure from `_start +484` without printing any
of its named `FAIL:*` reasons.

`_start`'s first act is a bare `verify_bl0_state()` before `.data` is copied (so before
`bl1_puts` works), and its failure path is exactly the observed
`sw 0xDEADBEEF -> cold_scratch[0]; wfi`. The cause:

| | timestamp |
|---|---|
| `bootrom/prod/include/bl0_state.h` modified (the measurement commit) | 15:57:29 |
| `dv/fw/tests/bl1_pass_test/build/bl1_pass_test.o` built | 15:31:15 |

`bl1_pass_test/Makefile` had **no header dependency tracking** — no `-MMD`, no `-include`.
The measurement work grew `sizeof(struct bl0_state)` from 96 to 188, which moves
`BL0_STATE_ADDR` (DCCM top − sizeof) from `0xC005FFA0` to `0xC005FF44`. The stale object kept
addressing the old location: confirmed in the disassembly, which referenced `0xC005FFAC`
before the rebuild and `0xC005FF44` after.

This is the hazard `INTEGRATION.md` §3 describes verbatim, and the reason the boot ROM's own
Makefile carries `-MMD -MP`. That fix never reached this Makefile, which reaches into the ROM
tree by relative path (`../../../../bootrom/prod/include/bl0_state.h`) with no `-I`, so the
dependency is invisible to a reader too.

**Fixed** in `sep: track header dependencies in the bl1_pass_test build`. Verified three ways:
the compiled address moved to `0xC005FF44`, the generated `.d` lists `bl0_state.h`, and
touching the header now provokes a rebuild through the real `c_compile` stage.

`bl1_pass_test` is the **only** DV firmware that includes `bl0_state.h`, so the exposure was
one file.

### The ICCM ECC pad rounded the wrong way

Mine, introduced with the partial-clear mode. `pad_start` rounded **up** to the 64-bit ECC
granule:

```c
const uint32_t pad_start = (load_addr + img_length + 7u) & ~7u;   // wrong
```

With a 1708-byte BL1 that yields `0xC00006B0` and leaves `0xC00006AC..0xC00006B0` — four bytes
inside the granule `[0xC00006A8, 0xC00006B0)` — never written, so a sequential fetch that
crosses into it reads uninitialised ECC. It must round **down**, so a granule holding both
image and past-the-end bytes is covered; the copy runs after the pad and restores the image
bytes in it. Now `(load_addr + img_length) & ~7u`.

Not the cause of run 5 (BL1 died 125 cycles after `PRE_JUMP`, executing from `0xC0000000`),
but a real defect on the ICCM path.

### Item 3 — BL1 per-slot validation: done, and it turns out to be required

`rom_handoff.c`'s locate-and-validate is now a single static `bl1_locate(bl1, in_iccm,
report)` — find the TOC entry, check placement against SRAM ∪ ICCM with the
`BL1_SRAM_EXEC_ENABLE` gate, `entry_point < length`, non-zero length. Two callers:

- `rom_bl1_check()` (new, declared in `oca_boot.h`) runs it inside `try_manifest_slot()` right
  after `g_body`/`g_payload` are staged, and clears them again on rejection. `rom_manifest_boot()`
  runs at `rom_main.c:391`, before the `[C15]` fuse-secret lock, so a primary slot whose BL1
  is missing or unplaceable now fails over to the backup instead of ending the boot with
  secrets already locked.
- `rom_handoff_bl1()` runs it again at `[C18]` and uses the result to copy and jump. It
  re-validates rather than trusting the per-slot call, so the function that owns the copy does
  not depend on a caller having checked.

`report` gates only the informational output (`LOAD=`, `LEN=`, `ENTRY=`, `BL1_DST=`,
`SEP_MSG_BL1_FOUND`), so a successful boot still prints the placement once. Rejection markers
always print — a rejected slot's reason is the diagnostic.

**#1581 already requires this.** `sep_bl1_image_invalid_base.check_defect_attribution()`
asserts the defect marker appears **at least twice** — once before the backup read and once
after — because both slots carry the defect:

> Requiring one occurrence on each side of the backup read is what distinguishes them.

With the check only at `[C18]`, the marker can appear exactly **once**, after both slots have
been read, so `sep_bl1_entry_invalid_test` (TP053-E) and its siblings could not have passed on
this branch. Item 3 is a gate for that family, not a tidiness fix. The check order the base
class assumes — containment first, then entry point — is what `bl1_locate` already does.

Cost: **+160 bytes** (42848 → 43008 B on the Cadence variant, 65536 B budget). Measured by
A/B build against HEAD, not estimated; `bl1_locate` stays a single out-of-line function
(0x284 bytes) with `rom_bl1_check` a 40-byte wrapper, so nothing was duplicated by inlining.

The 24-line justification comment that stood over the placement check was rewritten down to
seven while the block was being moved — one of the sites listed in the trim pass below, now
closed.

### Noted for the 52-test port, not fixed here

`sep_bl1_entry_invalid_test.sibling_markers` names `IMAGE_LEN_ZERO` and `IMAGE_LEN_ALIGN` for
the size rejections, where this ROM prints `BL1_SIZE`. Harmless for that test — a marker that
is never printed cannot appear — but the size-invalid tests in the same family will assert on
names this ROM does not emit. Reconcile the marker vocabulary when porting that family, and
decide it once: either the ROM adopts `IMAGE_LEN_*` or the tests adopt `BL1_SIZE`.

### `+sep_crypto_edn_force`: 25 testlist entries still to migrate

The plan called for rerouting `sep_firmware_encrypted_boot_test`; the real scope is wider.
After the rebase, **27** `rom_fw.toml` entries passed `+sep_crypto_edn_force` and 47 comment
lines referred to it, while `tb_top.sv` — correctly — carries only the OTBN RND/URND clients
(2 and 3). #1581's client-0 (AES) extension was rejected as planned, which makes two claims in
the testlist false on this branch:

* `sep_firmware_encrypted_boot_test`: *"+sep_crypto_edn_force covers OTBN (RSA) and AES
  (decrypt)"* — it does not; AES is not forced here. It also cited `make encrypted_boot_spi`,
  a target this branch deleted.
* `sep_firmware_enforced_secure_boot_flow_test`: *"the ROM brings up no entropy chain"* — this
  branch's ROM does, in `src/sep_entropy.c`.

Both are runnable before the mutation port, so both were rerouted to `+esrc_noise_force` and
their comments corrected. `sep_rom_ot_secure_boot_test` already runs a full RSA-3072 modexp on
OTBN with only `+esrc_noise_force`, which is the evidence that the reroute is sufficient
rather than merely tidier.

The remaining **25** are all inside the 52-test mutation port, so they cannot run yet and are
best migrated with their families rather than in a separate sweep — the port rewrites those
blocks anyway. Two things to carry into that work:

1. Reroute the arg, and fix the comment in the same edit. Many read "No `+sep_crypto_edn_force`:
   revocation precedes the signature step, so OTBN is never driven" — that reasoning is about
   whether the test needs entropy at all and stays valid; only the plusarg name changes.
2. `tb_top.sv`'s block is now worded as "prefer `+esrc_noise_force` … entries still passing it
   are being migrated". When the last entry moves, delete the force outright — the block itself
   says it is a candidate for deletion.

## The 52-test port: the finding that shapes it (2026-09-08)

Before writing any of the OCA mutation layer, the field offsets were checked against each
format's signed region. The result changes the port strategy, so it is recorded before the
code.

**In Grendel, `flag_args` is unsigned. In OCA, the same controls are signed.**

| field | Grendel offset | | OCA offset | |
|---|---|---|---|---|
| BL2 demotion + secure boot | `flag_args` 1168 | **outside** TBS (744) | `demotion_control` 172, `secure_boot_control` 182 | **inside** signed region (3172) |
| security version | 162 | inside | 2042 | inside |
| signature type | 165 | inside | 2092 | inside |
| public key select | 166 | inside | 2104 | inside |
| signature | 744 | outside | 3172 | outside |
| manifest hash | 1128 | outside | 3684 | outside |

Two consequences, in order of importance.

**1. This is a real security improvement, and it should be said out loud.** Under Grendel, BL2
demotion and the secure-boot flag were *outside* the hashed region: an attacker holding a
validly signed manifest could flip either one and the ROM would accept it, because the hash
covers only [0, 744) and the signature covers only the hash. Under OCA both are authenticated.
The ROM code already assumes the OCA behaviour — `rom_oca_demotion_control()` reads the
staged, verified body — so nothing needs fixing; but the migration closes a hole rather than
merely changing a layout, and that belongs in the PR description.

**2. `set_flag_args_bit()` cannot keep its Grendel cost model.** 11 call sites across 4 files
use `FLAG_ARGS_BIT_BL2_DEMOTION` and 11 more across 3 use `FLAG_ARGS_BIT_SECURE_BOOT`, and
they rely on mutating the bits while the manifest is still *accepted* — free under Grendel,
impossible under OCA without re-signing. So each such test needs one of:

* **Pack-time configuration** (preferred where the test only needs a manifest that *has* a
  given policy). This branch already carries 16 `configs/oca_*_boot_test.yaml`, so "a manifest
  requesting BL2 demotion" becomes a config, not a byte mutation — and it is then a signed,
  coherent manifest, which is what the ROM will actually meet in the field.
* **Rehash and re-sign** (needed only where the test's point is that a *tampered* value is
  refused). This is what makes `sep_payload_mutate.py:114-185,342`'s stdlib PKCS#1-v1.5 signer
  and PKCS#8 DER reader worth salvaging — the plan already flagged them, and this is the
  concrete reason: the DV virtualenv has no `cryptography`, and OCA needs a signature over a
  region that mutation now invalidates.

The demotion family was already sequenced last in the port order. This is why: three of its
four inputs are manifest fields, and under OCA all three are signed. Start with the PROD_END
short-circuit rows, which read none of them.

### Mechanics settled while checking

* Slot geometry is unchanged — `oca_non_secure_boot.bin` (327680 B) carries `OCAC` at both
  `0x1000` and `0x41000`, so `PRIMARY_MANIFEST_OFFSET` / `BACKUP_MANIFEST_OFFSET` port as-is.
  `sep_rom_oca_tamper_test.py:42-43` can drop its private copies.
* The structural mapping is clean: `[signed region][signature][manifest_hash]` in both formats.
  `TBS_LEN 744 → OCA_CLASSIC_SIGNED_REGION_END 3172`; `OFF_SIGNATURE 744 → 3172`;
  `OFF_MANIFEST_HASH 1128 → 3684`; `MANIFEST_SIZE 1184 → OCA_CLASSIC_BODY_SIZE 4096`.
  3172 + 512 = 3684 and 3684 + 64 = 3748, so the fields abut exactly as the constants claim.
* Field-width widenings to carry: `selector_bits` u64 → 16 bytes; `public_key_sel` u64 → 16
  bytes; `security_version` → 16 bytes; signature field 384 B → 512 B with the true length in
  `signature_size_classic`; digests sit in 64-byte fields with the SHA-256 in the low 32 and
  the rest zero. One Grendel `life_cycle_states` becomes three OCA fields (chiplet 136,
  package 140, system 144).
* **API surface is 51 names, not 65.** Measured across the test tree: 14 of the module's
  public names have no caller (`MANIFEST_SIZE`, `OFF_PUBLIC_KEY`, `PUBLIC_KEY_LEN`,
  `tbs_hash`, `public_key`, `SIG_TYPE_ECC_P_256`, `SHIPPED_*`, …). Port the 51 and drop the
  rest rather than carrying dead offsets — the module's own header warns that an unused offset
  "would be an unverified number that reads as authoritative".
* `oca` is **not importable** from the DV virtualenv. The module must put
  `hw/sys/sep/bootrom/prod/tools/tt-oca-manifest/src` on `sys.path` and import
  `oca.constants`, following the existing precedent in `env/sep_reg_meta.py:51-52`. It must
  **fail loudly** if that import does not resolve: a silent fallback to literal offsets is the
  exact drift the doc plan kept re-fixing.
* Verify offline with a `--selftest` against the real packed images in
  `bootrom/prod/build/oca_*.bin`, as `sep_generate_efuse_preload.py --selftest` does. That
  checks the layout and every mutator without needing the simulator.

### Key selection: the last design unknown, now resolved

Grendel's `public_key_sel` is a u16 `{index:4, selection:3, rsvd:9}`. OCA's
`public_key_select_classic` is a **128-bit bitmap** with exactly one bit set —
`plat_is_key_authorized()` refuses two set bits with `PUBK_SEL_AMBIGUOUS` rather than picking.
The bit numbering is not the ROM's invention: it is `CHIPLET_PUBK_REVOKE`'s own map in
`sep_efuse_map.rdl`, so authorize-slot-N and revoke-slot-N name the same key.

| bits | anchor | Grendel equivalent |
|---|---|---|
| [7:0] | ROM chiplet-creator classical keys (0,1 = dev keys) | `PUBK_SEL_ROM_KEY` + index |
| [15:8] | ROM PQC keys — refused, nothing here verifies PQC | — |
| 16, 17 | `CHIPLET_PUBK_HASH0` / `1` | `PUBK_SEL_FUSE_KEY_0` / `_1` |
| 20, 22, 24 | `SIP_PUBK_HASH0`, `SYS_PUBK_HASH`, `SIP_PUBK_HASH1` | none |

So `set_public_key_sel(selection=, index=)` ports to "set exactly one bit": `index` for
`PUBK_SEL_ROM_KEY`, else `16 + (selection - 1)`. `PUBK_SEL_NUM_ROM_KEYS = 6` stays the ROM
key-table bound — bits 6 and 7 exist in the bitmap but no digest is provisioned, which is the
empty-slot rejection at `oca_platform.c:407-412`, so 6 remains the boundary value a bounds
test should use.

**`get_public_key_sel()` needs a call-site decision, not a mapping.** It returned Grendel's
packed u16; the natural OCA return is the resolved slot number (0–25), which is what the ROM
computes and what a test wants to assert on. 12 call sites across 9 files compare its result,
so the return semantics have to be settled against those call sites rather than chosen here.
Same shape of question for `set_flag_args_bit()` (see the signed-region finding above). These
two are the reason the port is best done family-by-family alongside the tests that consume it,
in the order the execution plan already gives, rather than as one module rewrite up front.

**Settled and safe to write now** (validated against real packed bytes, no call-site
dependency): slot geometry, `OCAC` magic, `verify_layout`, `rehash`, `erase_slot`,
`slot_is_erased`, `slot_span`, and the signed-region boundary. Verified across all 16
`build/oca_*.bin`: `manifest_hash == SHA256(body[0:3172])` holds for every image and both
slots, the hash sits in the low 32 bytes of a 64-byte field with a zero tail, and
`signature_type_classic`/`signature_size_classic` read 1/384 on the RSA images, 5/64 on
`oca_ecdsa_boot.bin` and 0/0 on `oca_non_secure_boot.bin`. Note OCA's ECDSA-P256 type is
**5**, not Grendel's `SIG_TYPE_ECC_P_256 = 2`.

Also: OCA has **no BL1-demotion selector bit**. Grendel gated demotion behind
`selector_bits[17]` plus `usage_constraints.flags[0]`; OCA has a standalone `demotion_control`
u16 whose bits 0..3 are BL1_VALID / BL1_ENABLE / BL2_VALID / BL2_ENABLE — matching
`oca_boot.h`'s `OCA_DEMOTE_*` exactly. So the 12 uses of `SELECTOR_BIT_BL1_DEMOTION` and 12 of
`USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION` collapse to two bits in one field, which is simpler
than the Grendel split rather than harder.

### The three build flags: non-default branches compile-checked

The flags added for this work (`BL1_SRAM_EXEC_ENABLE`, `ROM_ICCM_CLEAR_ENABLE`,
`ROM_ICCM_CLEAR_FULL`) all ship at one value, so the other branch of each `#if` was never
compiled. Built each non-default setting: `BL1_SRAM_EXEC_ENABLE=0`, `ROM_ICCM_CLEAR_FULL=1`,
`ROM_ICCM_CLEAR_ENABLE=0` — **all three link with zero errors and zero warnings.**

The SRAM lockdown was checked at the instruction level rather than the source level:
`vector.o` built with `BL1_SRAM_EXEC_ENABLE=0` contains **no reference to the SRAM bound**
(`0x10000000`), so the warm-handler range test is genuinely compiled out rather than present
and unreachable. That is the property an adopter locking the ROM down is buying.

The rebuild stamp covers this correctly: `Makefile:325`'s `$(OBJS): $(FLAGS_STAMP)` applies to
every object including `vector.o` (which has its own rule at :337 for
`-x assembler-with-cpp`), so a flag change rebuilds the assembly too. Confirmed by watching
`build/.build_flags` flip and `vector.o` rebuild with it. Worth stating because the same
Makefile's comment explains it was added after exactly this class of silent staleness — and
because `bl1_pass_test`'s Makefile had no equivalent, which is what run 5 tripped over.

The tree is left in the shipping configuration (`BL1_SRAM_EXEC=1 ICCM_FULL=0`).

## gate16: the one failure, and what it was really about (2026-09-08)

`sep_firmware_encrypted_boot_test` failed at **1.8 s** — before simulating —
`FileNotFoundError: build/encrypted_boot.bin`. The plan predicted this class of breakage
("remove what #1581 left depending on them … the `encrypted_boot_spi` target") but the scope
was wider than one config.

**Five DV files referenced the three deleted Grendel images.** The `.hex` names that a naive
sweep also flags (`sep_itcm.hex`, `sep_dtcm.hex`, `sep_efuse.hex`) are per-run generated
artifacts and are fine; the real set is:

| image | referenced by |
|---|---|
| `secure_boot.bin` | `sep_backup_manifest_fail_base.py`, `sep_firmware_encrypted_boot_test.py` |
| `non_secure_boot.bin` | `sep_spi_not_detected_terminal_test.py` |
| `encrypted_boot.bin` | `sep_decryption_failure_terminal_test.py`, `sep_firmware_encrypted_boot_test.py` |

Each has an OCA counterpart with the same two-slot geometry, so for three of them the fix is a
rename to `oca_<name>.bin`. Worth noting `sep_backup_manifest_fail_base` is one of the four
base classes carrying 40 of the 52 tests, so that one reference was blocking a whole family
for a reason that had nothing to do with the mutation layer.

### The encrypted test was Grendel-coupled at the marker level, not the image level

Repointing its image would not have helped. It required six markers and **five do not exist in
this ROM** — `RSA_VERIFY_START`, `SIG_VALID`, `CRYPTO_VALIDATE_OK`, `PLD_HASH_OK`,
`DECRYPT_START` were `manifest_crypto.c` console strings. Only `DECRYPT_OK` survives. Its
CLASS_KEY was the Grendel packer's derivation (`9BA9BD53…`) where the OCA image uses sequential
`00 01 … 1F`. And `sep_rom_ot_secure_boot_test` — which the branch's
`sep_rom_oca_encrypted_boot_test` subclasses — *is* `sep_rom_ot_dma_boot_test` with tighter
assertions, so the two tests share a transport as well as a stimulus. It has no subclasses.

So it was folded in rather than repaired, after salvaging the part that transfers: its
**forbidden**-marker set. 11 of its 13 forbidden markers are emitted by this ROM, and the
HMAC/SHA rejection family is the observable side of the `check_no_error()` fix taken from
#1581 — an operation the IP refuses to start leaves `hmac_idle` asserted, which a completion
poll reads as success, so without those markers a garbage digest (hence a garbage AES key)
reaches decryption looking like a clean run. Those, plus `AES_INIT_BUSY` and `MANIFEST_ERR=`,
are now on the OCA test. The two it dropped, `AES_INIT_FAIL` and `PLD_HASH_MISMATCH`, have no
emitter in this ROM and would have been unverified constants reading as authoritative — the
thing `sep_manifest_mutate`'s own header warns against.

**Method note for the rest of the port:** "does this ROM emit this marker?" is a one-line grep
against `bootrom/prod/src/` and it settled both the required- and forbidden-marker questions
here faster than reading either test. Run it per family before porting assertions, because a
required marker that no longer exists fails the test for a reason unrelated to what it checks.

### Gate list correction

`sep_firmware_encrypted_boot_test` was misclassified as format-free: it does not import
`sep_manifest_mutate`, which is how it got into the 16, but its image, class key and five of
its markers were all Grendel. **The import graph is not a sufficient test for format
coupling** — artifacts and console strings couple too. The remaining 15 of the 16 were
correctly classified.

## The mutation foundation exists: `env/sep_oca_mutate.py` (2026-09-08)

Written as a **new** module beside `sep_manifest_mutate.py` rather than replacing it. Replacing
it in place would break the imports that currently work (`sep_backup_manifest_fail_base` and
friends import names that have no OCA port yet); side-by-side lets families migrate one at a
time and the Grendel module be deleted when the last one moves.

Scope is deliberately the part with no call-site dependency: slot geometry (`slot_base`,
`slot_span`), variant resolution, `verify_layout`, `rehash`, `erase_slot`, `slot_is_erased`,
`signature_type`/`signature_size`, `describe`. The accessors that need a call-site decision
(`get_public_key_sel`'s return type, `set_flag_args_bit`'s cost model) are deliberately absent
rather than guessed.

`python3 env/sep_oca_mutate.py` self-checks against every packed image: **17 images, 16
classic + 1 PQC, 0 failures.** It verifies both slots' layout, that `rehash` is a no-op on an
unmutated image and detects then repairs a signed-region mutation, and that erase/`is_erased`
round-trips. It covers `signature_type` 1 (RSA-3072), 5 (ECDSA-P256) and 0 (unsigned).

Two things it found that the offset analysis had not:

**1. `from oca import constants` cannot work in the DV virtualenv.** `oca/__init__.py` imports
`entry` → `encryption` → `cryptography`, which is absent — the same gap that made
`sep_payload_mutate`'s stdlib PKCS#1 signer necessary in the first place. `constants.py` itself
imports only `collections` and `enum`, so the module loads it **by file path** through
`importlib.util.spec_from_file_location`. That keeps the packer as the authority without
dragging in the packer's dependency tree, and it is the pattern the rest of the port should
use. A load failure raises; there is no literal fallback.

**2. There is a PQC image in the build set.** `oca_pqc_boot.bin` carries `OCAP`, a 36864-byte
body with its signed region ending at 5903 — the ROM is built `OCA_SUPPORT_PQC=1`. A
classic-only mutation layer would have written classic offsets into a PQC body and still looked
like it worked. So geometry is resolved from the magic through the packer's own
`CLASSIC_VARIANT`/`PQC_VARIANT` table (mirroring the ROM's `oca_variant_for_body()`), and
field-level access refuses `OCAP` explicitly: `constants.py` says per-field PQC offsets arrive
"with the validator's PQC support", so deriving them from the trailer shift would be precisely
the hardcoding this module avoids. The C mirror does carry them (`oca_variant.h`'s
`off_manifest_hash`, which `rom_oca_manifest_hash()` uses), so the Python side is the one that
has to wait.

And one bug the selftest caught immediately, worth recording because the shape recurs:
making `slot_span()` consult the variant table broke `slot_is_erased()`, which asks for a span
*after* the magic has been erased. A span is geometry and must answer without a valid
manifest, so it now falls back to the smallest known body size as the floor. Any helper that
erasure calls has the same constraint.

## A spec defect DV found: SBOOT_DIS does not outrank a signed request (2026-09-08)

The last gate failure was worth the 2400 s it took. `sep_firmware_device_cntl_non_secure_boot_flow_test`
booted PROD with `SBOOT_DIS = 1` and the ROM **verified the signature anyway**. That is not a
bug — it is the validator's designed precedence, and it means the requirement this branch
published was wrong.

`validators/oca/lib/secure_boot.c` decides by precedence, not by weighing equal inputs:

1. the **signed** `secure_boot_control` bit 0 — *checked first*, "an image built to be verified
   can only ever boot verified. Nothing a device reports downgrades it";
2. the device disable (`SBOOT_DIS`, lifecycle) — reached only if the manifest is silent;
3. the device's own enforcement view — fail-safe to ENFORCED on an unintelligible answer.

**SEP-ROM-SB-040 said the fuse "shall disable secure boot regardless of the other inputs"**,
and the truth table carried two `SBOOT_DIS = 1 | — | — | off` rows. The requirement conflated
two different things: the *unauthenticated* escalation flag, which indeed must not override a
fused control, and the *signed* `secure_boot_control`, which does. Its own closing sentence —
"an unauthenticated manifest flag shall not override a fused control" — is about the flag, and
is still true; the error was extending it to the signed field.

Measured, not assumed: `secure_boot_control` is `0x03` in **every** signed image this tree
packs and `0x00` only in `oca_non_secure_boot.bin`, which is unsigned. So on every signed
image the fuse has no effect, and the test's premise ("SBOOT_DIS makes a signed image boot
unverified") is unreachable by construction.

Fixed: SB-040 now states the precedence, the truth table splits both `SBOOT_DIS = 1` rows by
the signed bit, and the index row follows. `check_tables.py` and `check_xrefs.py` pass. This is
the same defect class as DEM-030 earlier in this branch — a requirement that normatively
mandated the *weaker* of two behaviours the code could have. Worth a standing habit: when a
DV test disagrees with the ROM, check the spec against the code before believing either.

The test now pins the stronger property with the same stimulus, which was already the
strongest form for it: PROD + `SBOOT_DIS = 1` + a signed enforcing image must run the full
RSA-3072 chain, and `SBOOT_OFF` is forbidden. Its name is now slightly off ("non_secure_boot_flow"
describes the old expected outcome, not the flow); left alone to keep the diff reviewable, but
a rename to something like `sep_firmware_signed_request_outranks_sboot_dis_test` would be
honest.

`+esrc_noise_force` and the 14400 s timeout added for it are correct after all: the ROM really
does verify here, so it really does need the noise source and the modexp budget.

### The marker vocabulary is a systemic port blocker

`RSA_VERIFY_START`, `SIG_VALID`, `CRYPTO_VALIDATE_OK`, `PLD_HASH_OK` and `DECRYPT_START` are
Grendel console strings that **this ROM never prints**. They appear across **~26 test files**,
including six base classes: `sep_chiplet_pubkey_base`, `sep_demotion_prod_base`,
`sep_demotion_prod_end_base`, `sep_primary_fail_backup_boot_base`,
`sep_pubkey_rom_revoked_base`, `sep_pubkey_rom_revoked_primary_base`, plus
`sep_bl1_image_invalid_base`. The OCA equivalents are `PUBK_AUTHORIZED`, `RSA_EXEC`,
`RSA_VERIFY_OK`, with `MANIFEST_OK`/`PAYLOAD_OK` already inherited from
`sep_rom_ot_dma_boot_test`.

Two cautions for the port:

* **Direction matters.** In `enforced_secure_boot_flow` these were *required*; in
  `device_cntl_non_secure_boot_flow` they were *forbidden*. A blind rename would have turned
  a vacuous negative assertion into a failing one, or vice versa. Read each use.
* `CRYPTO_VALIDATE_OK` has no single OCA analogue. In `sep_bl1_image_invalid_base` it is a
  per-slot **count** assertion ("printed once per slot whose crypto chain passed"), which maps
  to `RSA_VERIFY_OK` per slot; elsewhere its role is already covered by the inherited
  `MANIFEST_OK`/`PAYLOAD_OK`. Decide per use, not per name.

A forbidden marker the ROM cannot print is worse than useless: it passes for free and reads as
coverage. That is the same hazard as an unverified offset constant.

## Gate closed: 16/16 (2026-09-09)

`sep_firmware_device_cntl_non_secure_boot_flow_test` PASS, 9349 s — the last one. Against the
14400 s the entry was raised to; the original 7200 s would have failed it, so that change was
load-bearing and not just tidiness.

The property, confirmed in hardware rather than argued from source:

    CHK-SBOOT-STIMULUS: OTP image LC raw=0x1 (PROD), SBOOT_DIS=1
      FUSE: SBOOT_DIS: 1   LC=PROD                    <- stimulus
      PUBK_AUTHORIZED  RSA_EXEC  RSA_VERIFY_OK        <- verified anyway
      SBOOT_OFF occurrences: 0                        <- forbidden marker absent

| | |
|---|---|
| **16 / 16 PASS** | after two fixes |
| `SyncReqAckDataHold` | 0 across the set |
| `FLASH_READ_OOB` | 0 across the set |
| `sep_scratch_7_test` | **passes**, though #1581 calls it a pre-existing red on main |

Neither failure was in the ROM's boot logic, and both were worth their runtime:

1. `sep_firmware_encrypted_boot_test` — required five console strings from the deleted
   `manifest_crypto.c`; folded into `sep_rom_oca_encrypted_boot_test` after salvaging 11 of
   its 13 forbidden markers.
2. `sep_firmware_device_cntl_non_secure_boot_flow_test` — surfaced the `SEP-ROM-SB-040`
   defect above. Spec, truth table and test corrected.

This is the gate the plan set before the mutation port starts ("the 16 format-free tests must
be green *before* the port starts — that is the gate that says the rebase itself is sound").
It is now met, on a 47-commit branch over `origin/main`.

### What the gate actually validated

Worth listing, because these were the open risks and each now has evidence rather than an
argument:

* **ROM self-hash in hardware** — `ROM_HASH_VERIFIED`: the ROM's SHA-256 over `.text` +
  `.metadata` matches the value `insert-rom-sha256.py` embedded at build time.
* **BL1 from ICCM** — `BL1_DST=ICCM`, `BL1_COPIED`, `PRE_JUMP`, then BL1's own `BL0S_OK`. The
  LSU cannot store to ICCM, so a CPU-copy regression would have been a bus error, not a
  miscompare. The DMA path works.
* **The ECC pad rounds down** — `ICCM_PAD=0xc00006a8` for a BL1 ending at `0xC00006AC`, on
  both the non-secure and secure paths.
* **`bl0_state` layout agreement** — BL1 reads the struct at `0xC005FF44`, the 188-byte
  layout's address, and `BL0S_OK` means every field matched. That is the dep-tracking fix
  holding end to end through the real `c_compile` stage.
* **Real entropy under RSA** — `ENTROPY_OK` → `RSA_EXEC` → `RSA_VERIFY_OK` with only
  `+esrc_noise_force`, and `SyncReqAckDataHold` at 0. That is the positive case for rejecting
  `+sep_crypto_edn_force` rather than merely the argument for it.
* **Warm-reset range** — all four warm tests still reject out-of-range handlers after the
  range check was widened to ICCM ∪ SRAM, dispatching via `cold_scratch[7]`.
* **Per-slot BL1 check** — the happy path is undisturbed; the failover behaviour it exists for
  is asserted by `sep_bl1_image_invalid_base`, which is in the mutation port.

### Next

1. Port `sep_manifest_mutate`'s field accessors onto `sep_oca_mutate`, family by family, in
   the execution order above. Traps recorded: marker **direction** (required vs forbidden),
   `CRYPTO_VALIDATE_OK`'s context-dependent mapping, and `set_flag_args_bit`'s cost model now
   that those bits are signed.
2. The comment and commit-message trim pass, now that DV is green — before the PR.
3. An SRAM-linked `bl1_pass_test` variant: `BL1_SRAM_EXEC_ENABLE` is exercised only in the
   negative (compiled out) and by the ICCM path, never by an actual SRAM boot.
4. Then the PR, and the VP branch sequence.

## Does the mutation layer duplicate tt-oca-manifest? (2026-09-09)

Asked during the port, and worth recording because the answer decides how much of
`sep_oca_mutate` should exist at all.

**The submodule is a builder and validator; the mutation layer is a corrupter. Different
axis.** `src/oca/manifest.py` exposes `build_signed_region`, `build_unsigned_tail`,
`compute_manifest_hash`. Its negative tests act at the *config* boundary — e.g.
`test_unsupported_signature_algorithm_rejected` sets a bad `signature_type` and asserts
`pack_oca_bundle` raises `OcaConfigError`. The packer's job is to **refuse** to emit an invalid
manifest, so it cannot produce the stimulus a ROM negative test needs: you cannot get an
unsupported-signature-type image out of it, because the config loader rejects it first. To
learn what the ROM does when such an image is already in flash, the bytes have to be patched
after packing. There is no mutation, tamper or corruption facility anywhere in `src/`,
`tools/` or `tests/`.

So the mutation layer is not redundant. What it owns that the submodule does not: byte-level
field edits on a packed image, slot erasure, and the layout self-check that keeps a
misdirected write from passing as a correct rejection.

**One genuine overlap: `compute_manifest_hash` vs `rehash()`.** The submodule's version is
better — variant-aware, it validates the signed-region length, and it owns the field's
zero-padding convention (64-byte field, digest in the low 32) rather than assuming it.

It is reusable, which was not obvious: the `cryptography` dependency that blocks
`from oca import constants` lives *only* in `__init__.py`'s single line
`from .entry import pack_oca_bundle`. `manifest.py` and `validators.py` import nothing beyond
the stdlib and `.constants`. Registering a bare `oca` package in `sys.modules` and loading the
three modules by path resolves their relative imports without touching `entry`/`encryption`;
verified against `oca_secure_boot.bin`, where `compute_manifest_hash` reproduces the stored
64-byte field exactly.

**TODO:** switch `rehash()` to call `compute_manifest_hash`, and generalise the loader in
`sep_oca_mutate` from "load constants.py standalone" to "load these three modules as a bare
package". That removes the last reimplementation and makes the packer the authority for the
hash field's shape as well as for the offsets.

## Mutation port, increment 1: 5/5 (2026-09-09)

The families that need only slot geometry, the manifest magic and erasure — all already in
`sep_oca_mutate` — migrated by changing one import line each, plus their shared helper
`sep_spi_slot_evidence`. Measuring first is what made this cheap: **7 of the 36** files using
`sep_manifest_mutate` need nothing the foundation lacks.

| test | tool | result |
|---|---|---|
| `sep_spi_detect_success_test` | vcs | PASS |
| `sep_spi_primary_fail_backup_test` | vcs | PASS |
| `sep_rotate_update_set_test` | vcs | PASS after the slot-label fix |
| `sep_spi_not_detected_terminal_test` | vcs | PASS after the status fix |
| `sep_failover_sram_clear_assertion_test` | **verilator** | PASS |

Three failures on the first pass, **none of them in the mutation layer**. The pattern from the
gate held: assertions written against Grendel-era ROM *output*, plus one environmental
mismatch. The layer's own selftest catches its bugs offline, which is where they belong.

### `sep_rotate_update_set_test` forbade the truthful label

It listed `MANIFEST_BACKUP` as `_SECOND_ATTEMPT`, which was only meaningful while the label
followed the retry counter. `oca_boot.c` labels by slot now, and says why: *"labelling by retry
made the marker say PRIMARY while MANIFEST_SRC showed 0x41000."* So the test forbade the label
this branch had deliberately corrected. Now `MANIFEST_BACKUP` is required and
`MANIFEST_PRIMARY` forbidden, which discriminates slightly better — a ROM ignoring the strap
prints both labels *and* a `MANIFEST_ERR=`. Verified: 1 / 0 / 0.

### `sep_spi_not_detected_terminal_test` had two wrong expectations

`STATUS_ENCODE(ERROR, 0x0002)` was derived from the low half of the console error code;
`status_for_result()` maps `OCA_FAIL_MAGIC` to `SEP_MSG_INVALID_MANIFEST_ID`, so a rejected
slot reports `0x0f010006`. The console marker `MANIFEST_ERR=0x00030002` was already right.

The second is **a pre-existing main defect, not a port issue.** Every `report_status` write is
followed by `status_ring_buffer_insert()`, which overwrites `cold_scratch[1]` with
`SEP_MSG_STATUS_REPORTING_INVALID` when the ring descriptor is unusable — and the SEP DV
environment leaves `num_entries` at 0 in all 25 runs checked. So the register's last value is
always that report, and `assert status_seq[-1] == <terminal>` cannot pass on main either.
`status_ring.c` is untouched by this branch and main carries the identical clobber. The test now
filters those writes and asserts on the last *reported* status; staying stopped is separately
covered by `CHK-HANG`.

Also learned: the status sequence is **sampled**, so counts in it are lossy — the run shows
`0xf010006` once though both slots were rejected. Assert presence there and take counts from
the console.

**Worth handing to whoever owns `status_ring.c`:** the invalid-ring report clobbers the very
channel it complements, making `cold_scratch[1]` useless as "the last status" whenever the ring
is unconfigured. Reporting once instead of per-insert keeps the diagnostic without destroying
the signal.

### `sep_failover_sram_clear_assertion_test` was a tool mismatch, not a defect

It reads the SRAM array through `cocotb.top` at `gen_ram_inst[0].u_mem.mem`. That resolves
under Verilator via `sep_public_scope.vlt`; under VCS the walk fails on the generate index and
the test errors in 2.6 s without simulating. **Verilator is this DUT's default tool** — my gate
list ran everything under VCS, which was the error. Under Verilator it passes, resolving the
full path and poisoning all 32768 SRAM words.

The runlib has **no per-test tool key**: `tools` exists but is flow/target-level (per-tool
config tables and a flow's supported-tool list, `config.py:1218`). There is also no
`SIM_NAME`-conditional or skip precedent anywhere in the SEP DV Python, so inventing one in
another engineer's test would be a unilateral new convention. Left as a testlist comment
stating the requirement and why. **A per-test tool constraint is a real gap in the runlib** and
worth raising separately — nothing stops the next person repeating this.

**Second instance of the same lesson:** the import graph does not tell you what a test is
coupled to. The encrypted test was coupled by artifact and console string; this one by
simulator.

## Mutation port, increments 2 and 3

**Key selection and signatures** (12 + 9 + 8 files). `get_public_key_sel` returns the slot
number, not a packed field: every call site compared against a value derived from *Grendel's*
packing, so preserving the type would have fixed nothing, and the slot number is what both the
authorization callback and the revocation bitmap index with. `_REVOKE_BITMAP & (1 << (sel &
0xF))` could not address the OTP slots at bits 16–25; without the mask it can.

`verify_public_key` parses the expected digest from generated `key_digests.c`. The literal in
`sep_manifest_mutate` was **already stale** — `4676d023…` where the generated file has
`a771ca63…`. Anchoring is gated on the same three conditions `plat_is_key_authorized` checks
before comparing a digest (ROM slot, RSA-3072, raw encoding); the selftest caught that gap by
failing on the ECDSA and DER fixtures, whose key fields are not bare moduli, and on the
OTP-anchored images whose digest lives in a fuse.

**Usage constraints.** `selector_bits` is 128 bits; one `life_cycle_states` became three
scoped fields; demotion is a standalone u16 matching `oca_boot.h`'s `OCA_DEMOTE_*`; and
`secure_boot_control` bit 0 is *signed*, so `set_secure_boot_enforced` rehashes. The
secure-boot enforced bit is not in `constants.py`, so it is parsed from the validator's
`oca_layout.h` rather than copied.

**`rehash` now calls the packer's `compute_manifest_hash`.** It writes the whole 64-byte field
rather than the low 32, and `verify_layout` compares the whole field — which catches a dirty
pad the 32-byte compare structurally could not (demonstrated). The loader generalised to load
`constants`, `validators` and `manifest` under a bare `oca` package; the `cryptography`
dependency that blocks a normal import lives solely in the real `__init__`'s single line.

Selftest: **17 images, 16 classic + 1 PQC, 0 failures**, covering every mutator's round trip.

## The Grendel→OCA console marker map (2026-09-09)

Needed by ~26 remaining files, so recorded once here rather than re-derived per family. Every
row was checked by grepping `bootrom/prod/src/` for the string — the one-line method that
settled the earlier cases faster than reading either side.

| Grendel marker | OCA equivalent | note |
|---|---|---|
| `RSA_VERIFY_START` | `RSA_EXEC` | modexp starting |
| `SIG_VALID` | `RSA_VERIFY_OK` | signature verified |
| `PLD_HASH_OK` | `PAYLOAD_OK` | payload hash chain matched |
| `CRYPTO_VALIDATE_OK` | **context-dependent** | no single equivalent — see below |
| `DECRYPT_START` | **none exists** | see below |

`CRYPTO_VALIDATE_OK` meant "this slot's crypto chain passed". Where a test wants that as a
per-slot *count* (`sep_bl1_image_invalid_base` requires it twice, once per slot), use
`RSA_VERIFY_OK`. Where it stands for "the slot was accepted", `MANIFEST_OK` and `PAYLOAD_OK`
already carry it and are inherited from `sep_rom_ot_dma_boot_test` — so the reference usually
just drops.

`DECRYPT_START` has **no OCA counterpart**. The ROM emits `DECRYPT_OK` and the failure arms
(`DECRYPT_CLASS_KEY_EMPTY`, `DECRYPT_NO_SECRET`) but no "starting" marker. Required use should
drop it, since `DECRYPT_OK` implies it started; forbidden use ("decryption never ran") is
carried by the absence of all three.

**Direction is not batch-decidable.** A `forbidden` Grendel marker is *vacuous* on this ROM —
it can never print, so the assertion passes for free and reads as coverage — while a `required`
one is fatal. Those need opposite treatment, and many references are in ordering assertions
(`index_of(_RSA_START)`) rather than in the marker tuples, so a regex sweep misclassifies them.
Read each file. The ordering chains do transfer: `RSA_EXEC` → `RSA_VERIFY_OK` → `MANIFEST_OK`
preserves "verifier driven → signature valid → slot accepted".

### API surface complete; migration is what remains

Measured after the accessor tail landed: **all 36** files that use the Grendel module now have
every name they reference either ported or renamed to a named OCA equivalent — zero missing.
The remaining work is per-file migration, not new accessors.

`sep_backup_manifest_fail_base` migrated first as the biggest lever: **16 files** depend on it,
and it needed only the import swap plus `set_identifier` → `break_magic` (it carries no crypto
markers of its own). Its stale `manifest_load.c` / `validate_manifest_header` /
`manifest.h` citations were repointed to `oca_boot.c` / `oca_peek_manifest` /
`oca_layout.h`.

All 15 of its dependents carry Grendel markers, so the vocabulary — not the mutation layer — is
now the gating item for the rest of the port.

## The backup/primary family is blocked on `sep_payload_mutate` (2026-09-09)

The first fully-ported leaf, `sep_firmware_primary_invalid_signature_test`, failed in 2.3 s
with a **Grendel** assertion — `does not start with b'TBL1' (got b'OCAC')`. The chain:

    sep_primary_fail_backup_boot_base:217  mutate_flash_image
      -> sep_payload_mutate:289            verify_sealed
        -> sep_manifest_mutate:229         verify_layout

`env/sep_payload_mutate.py` is a prerequisite for this whole family, not a peer of it. I had it
in the migration queue but ranked it by its own callers rather than by what depends on it
transitively — the same mistake in miniature as ranking `sep_backup_manifest_fail_base` late.
**Rank the queue by transitive dependents, not by direct imports.**

### Scope

515 lines, 42 public names, **18 used externally**, in two clean halves.

*Transfers unchanged (format-independent, and the salvage the plan already named):*
`load_rsa_private_key`, `sign_pkcs1v15_sha256`, `verify_pkcs1v15_sha256`, `_emsa_pkcs1_v15`,
`_der_len`, `_der_tlv`, `RSA_KEY_BYTES`. A stdlib PKCS#1-v1.5 signer and PKCS#8 DER reader,
written because the DV virtualenv has no `cryptography` — the same gap that forced
`sep_oca_mutate` to load `constants.py` by path.

*Needs porting:*

| name | uses | note |
|---|---|---|
| `verify_sealed` | 15, 9 files | the failing entry point |
| `bl1_field`, `E_TYPE`/`E_OFFSET`/`E_LENGTH`/`E_LOAD_ADDR`/`E_ENTRY_POINT`/`E_HASH` | 10 | TOC entry layout |
| `verify_signing_key`, `reseal` | 8 | re-sign after an in-signed-region mutation |
| `describe_bl1`, `set_bl1_entry_point`, `set_bl1_zero_length`, `payload_base`, `corrupt_ciphertext` | 5 | |
| `MANIFEST_ERR_BL1_BAD_ADDR`, `MANIFEST_ERR_BAD_TOC_ID` | 2 | now derivable via `mm.boot_err()` |

24 names have no external caller and should be dropped rather than ported, same discipline as
the 14 dropped from `sep_manifest_mutate`.

### The TOC layout is the real work

The header offsets happen to agree — magic 0, `payload_length` 8, `image_count` 16, and the
magic is `PTOC` in both, because Grendel had already adopted OCA's payload TOC. **The entry
layout does not:**

| field | Grendel | OCA |
|---|---|---|
| type | 0 | 0 |
| offset | 8 | **20** |
| length | 16 | **28** |
| load_addr | 32 | **52** |
| entry_point | 40 | **60** |
| hash | 56 | **80** |
| entry size | 216 | **272** (144 + 128 description) |

OCA inserts `group` (16), `version` (36), `security_version` (44) and `target_chiplet_id` (68)
that Grendel lacked, and ends with a 128-byte description. All published in `constants.py` as
`OFF_TOC_ENTRY_*`, so the port reads them from there rather than re-deriving.

The manifest-side offsets it also carries (`OFF_PAYLOAD_HASH = 552`, `OFF_PAYLOAD_HASHED_LEN =
584`, `OFF_PAYLOAD_LENGTH = 600`, `OFF_BOOT_PAYLOAD_OFFSET = 1160`, `OFF_USAGE_FLAGS = 92`) are
all Grendel and all have OCA equivalents in `constants.py` (`OFF_PAYLOAD_HASH = 2775`,
`OFF_PAYLOAD_HASHED_LENGTH = 2911`, `OFF_PAYLOAD_LENGTH = 2960`, `OFF_PAYLOAD_OFFSET`,
`OFF_DEMOTION_CONTROL`).

### What is and is not affected

This blocks the inherited backup/primary/chiplet-pubkey/demotion families — the bulk of the 52.
It does **not** affect anything already green: the 16 gate tests and mutation increment 1 (5/5)
do not go through the payload module.

## Demotion family: what changes, and a deliberate coverage decision (2026-09-09)

The demotion decision now reads one signed field, `demotion_control` (u16, offset 172), whose
bits 0..3 are BL1_VALID / BL1_ENABLE / BL2_VALID / BL2_ENABLE. Three things follow for the
11-file family:

1. **Every demotion stimulus costs a re-sign.** The field is inside the signed region, so a
   mutation needs `sep_oca_payload.reseal()` (which works) or a pack-time config. Reseal keeps
   the tests Python-only, which is what the mutation layer is for.
2. **The fail-open is closed.** A manifest that asserts nothing now gets `DEMOTE_1` written
   non-demoted *and locked*, where it used to be left unwritten and unlocked. So the
   "nothing asked" rows expect `DEMOTE_LOCKED`, not `DEMOTE_NOT_LOCKED` — an outcome change,
   not a stimulus change, and the one most likely to read as a regression.
3. **Lifecycle is per identity scope.** SEP reports only the chiplet scope
   (`plat_get_lifecycle_state` returns UNAVAILABLE for package and system), so these tests use
   the chiplet scope and must not select the others: a selected-but-unreportable constraint
   fails the slot under MAN-040.

The assertion layer transfers almost intact, unlike every other family — `BL1_DEMOTE=`,
`BL2_DEMOTE_DEC=`, `DEMOTE: BL2 deferred, unlocked`, `DEMOTE: PROD_END lock`,
`DEMOTE_LOCKED` and `DEMOTE_NOT_LOCKED` are all emitted by the current `[C15]`.

The outcome space is five rows: PROD_END never demotes regardless of manifest content
(DEM-020), and under PROD the four combinations of BL1_VALID/ENABLE and the BL2 pair. All
three PROD_END tests therefore assert the same outcome now; they stay as input coverage but no
longer discriminate.

### Decision: unauthenticated demotion is deferred, and the two tests are KEPT

Two tests, `sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_test` and
`..._prod_sel_bit_set_test`, are premised on an unauthenticated demotion input. There is none
in the current design, so retiring them looked right — and that was wrong. Checking the
outcome table first showed they are the only cover for outcomes **O4** and **O2b**, and O4 is
the only outcome that leaves `DEMOTE_1` unlocked. They are kept, ported on their signed
inputs alone, and both are still in `rom_fw.toml`. Recorded because the retirement was
proposed, agreed and then reversed: check what a test uniquely covers before dropping it, not
after.

The capability is not being dropped, only deferred: `UNAUTH_DEMOTION_TICKET.md` specifies
unauthenticated BL1/BL2 flags gated by new signed allow bits in `demotion_control[5:4]`, with
signed values taking precedence when `VALID` is set. It lands after this branch. The two
retired tests are the natural starting point for that work, so the ticket names the rows to
write first.

## Porting the remaining families (2026-09-09)

The last families were not a marker rename. An audit — every console string the ROM and BL1
can emit, against every string literal in `tests/rom_fw/*.py` reachable from a
required/forbidden/defect-marker assignment — put **30 files** on markers this ROM never
prints. Twelve names mapped one-to-one. The rest named refusals the ROM reports only through
`MANIFEST_ERR=<code>`, and four cases were not vocabulary at all.

### Direction matters, and it is why a regex sweep is not enough

A *forbidden* marker the ROM cannot emit passes for free while reading as coverage. A
*required* one fails every run. So the same stale name is a silent hole in one position and a
hard red in the other, and many references live in ordering or exactly-once assertions rather
than in a marker tuple — where a rename produces a *plausible* assertion that tests nothing.
Each site was read. Three specific traps were hit and are worth recording:

* A blanket citation strip replaced a filename with "the ROM" and ate parts of valid paths,
  producing text like `(1, the ROM)` and `bootrom/prod/src/the ROM`. Repaired by recomputing
  each site from `HEAD` rather than by pattern — the sweep is a pure function, so the correct
  output is derivable, and 77 of 80 sites were fixed mechanically.
* Renaming a value-carrying marker to a valueless one left the format spec behind:
  `f"BAD_SIG_TYPE=0x{v:08x}"` became `f"PUBK_ALGO_UNSUPPORTED{v:08x}"`, which matches nothing.
  Found by AST: any f-string whose literal prefix is a valueless marker but which still
  interpolates. Three more of the same in `rom_fw.toml`.
* `MANIFEST_ERR_KEY_HASH_MISMATCH` was hardcoded to `0x00030016` in one test — the *revoked*
  code. Four docstrings carried codes that no longer exist. Every code is now
  `mm.boot_err(...)`.

### Four ROM-side findings, not DV ones

1. **The ROM echoed neither the key slot nor the revocation bitmap nor the version operands.**
   Five tests assert *which* anchor was consulted or *which* flag word was rejected, and the
   library reports each as one result code. Added `PUBK_SEL=`, `PUBK_REVOKE=`, `FUSE_VER=`,
   `MFST_VER=`. `PUBK_SEL=` sits before the reserved-range refusal so a refused slot is still
   attributed; the version pair is emitted from the security-version callback, the only point
   SEP code holds both sides. No library patch was needed — the validator already calls
   `is_key_authorized` → `get_root_key_revocation` → `get_security_version` →
   `verify_signature`, which is the old console chain exactly.
2. **`BL1_SIZE` was unreachable.** `entry_point >= length` holds for every `entry_point` when
   `length` is zero, so a zero-length BL1 was reported as a bad entry point under the wrong
   code. Length is now checked first.
3. **`+sep_crypto_edn_force` trips a protocol assertion.** Observed, not inferred:
   `sep_firmware_primary_rom_key_valid_test` hit
   `prim_sync_reqack_data.SyncReqAckDataHoldDst2SrcB` at 10232000000 before any ROM output.
   Forcing `edn_ack` violates the req/ack data-hold protocol, as this plan predicted. All 24
   remaining entries moved to `+esrc_noise_force`; the plusarg stays in `tb_top.sv`, off by
   default.
4. **Anti-rollback runs AFTER key authorization**, not before. Two tests asserted the old
   order — one of them asserting `PUBK_SEL=` must *not* precede the failover, which is now
   exactly backwards. They assert the property this ROM actually guarantees: a rolled-back
   manifest never reaches the verifier.

### Semantics that changed under the manifest, not just names

* **`security_version` is a 128-flag bitmap**, rejected when `(device & ~manifest) != 0`.
  `sep_firmware_bl1_ver_test` was built on a popcount model with an eight-word decode claim,
  none of which describes a single 16-byte read. Reworked to the superset rule over the low 16
  bytes the platform reads. The spread preload turns out to suit OCA better than the model it
  was written for: four distinct non-empty words, so omitting any one rejects.
* **The verifier prints two markers, not four.** The OTBN test's per-slot chain collapses to
  `RSA_EXEC → RSA_PKCS1_FAIL`. The engine-failure forbids that separate "rejected" from "never
  ran" are the point of the test and are unchanged.
* **`public_key_select` is a slot bitmap with regions**, and each region refuses differently:
  `[0,6)` provisioned, `[6,7]` unprovisioned, `[8,15]` PQC, `[16,25]` fuse, `[26,31]`
  reserved. Four stimuli no longer meant what they did — three landed in an arm the test also
  forbids:
  * slot 6 is *unprovisioned*, not out of range, so both "index invalid" tests planted a
    stimulus they forbid. Now `OCA_KEY_SLOT_MAX + 1`, which still pins `>` against `>=`
    because slot 25 is a valid fuse key;
  * slot 1 *is* provisioned, so the unpopulated-slot test exercised the digest comparison;
  * a "selection" naming no key source has no analogue — the field has no selection subfield,
    and the helper raises on one. Both selection tests now name two valid slots, which is the
    ambiguity the validator refuses, and assert that **no** slot number is echoed: the refusal
    happens inside the resolution loop, so its absence is the evidence.
  One test computed slot 16 as `(sel & 7) << 4` and was right only by coincidence.
* **Revocation attribution moved.** `KEY_REVOKED idx=<slot>` carried reason and slot together.
  OCA splits them: the reason is the result code, the slot is `PUBK_SEL=`. Both are asserted,
  so nothing is lost — and the ordering chain stays non-degenerate only because the terminal
  marker is the code, not the slot echo.

### Verification

* **The audit re-run reports 0 markers the ROM cannot emit, across all 80 files** — down
  from 30 files. Re-running the same check that found the problem is the only statement worth
  making here; the individual renames are not evidence of anything on their own. (Two hits in
  the first pass were artifacts of the checker itself stripping the leading space from
  `" recovery="` / `" rotate="`, which the ROM emits via `simputsdec24`. The checker was
  wrong, not the tests.)
* `ruff check` and `ruff format` clean across `dv/cocotb/`.
* Both env modules' selftests: 17 images, 16 classic + 1 PQC, 0 failures; 11 sealed, 6
  skipped, 0 failures.
* **All 80 `rom_fw` modules import**, which evaluates every class body — where the marker
  tuples, derived codes and slot constants live. This is what caught the residual undefined
  names a linter pass alone would not have.
* `rom_fw.toml` parses, 70 tests.
* Three ROM variants build: 43424 / 46376 / 45552 B against 64 KiB. The four echoes and the
  BL1 reorder are size-neutral.
* Simulation: batch of four running at the time of writing — the entropy migration cleared
  the `SyncReqAckDataHold` assertion, which is the first thing to confirm.

### Not done, deliberately

* The retired `env/sep_manifest_mutate.py` / `env/sep_payload_mutate.py` are deleted; nothing
  outside the pair referenced them.
* The full `rom_fw` regression has not been run. The entropy migration touches 24 entries and
  changes how each obtains entropy, so it needs a regression run of its own rather than the
  four-test sample this session had time for.

## Library bug: a zero-length TOC entry was accepted (2026-09-09)

Found while making the ROM's `BL1_SIZE` arm reachable, and it is the more
consequential half of that finding. The validation library never rejected a TOC entry whose
`length` is zero, and the spec was **silent** rather than unenforced — so this was a gap in
the format, not just in one implementation.

Why it matters beyond SEP: a zero-length entry declares an image with no content. Its `hash`
is the digest of the empty string, so it authenticates nothing; `entry_point < length` can
never hold, so it can never be legally launched; and it satisfies both the extent bound and
the pairwise overlap test trivially, so no other structural rule catches it. The overlap
comment in `payload.c` even named that as a reason not to worry:

> Zero-length ranges are empty and therefore never overlap.

A Consumer that selects an image by type, loads `length` bytes and jumps to
`load_addr + entry_point` copies nothing and hands control to whatever already occupied
`load_addr`. SEP's ROM happens to carry its own guard; the library certified the manifest as
structurally sound, so any Consumer without that guard inherited the hazard.

**Fixed in the submodule**, on branch `inmcm/reject-zero-length-toc-entry` (`d273df8`):
`validate_toc_structure` rejects it as `OCA_FAIL_PAYLOAD_TOC` (a structural TOC defect needing
no new enumerator), the spec gains the Consumer-rejects / Producer-does-not-emit requirement
with the rationale, the packer refuses to emit one, and the parametrised structural-violation
test gains a `zero_length` case.

### Verification, given the C CLI cannot build here

The repo's C integration tests need OpenSSL 3 (`openssl/core_names.h`); this box has 1.1.1, so
all four parametrisations of that test error out — including the three pre-existing ones. That
is environmental, not a regression. Three other routes were used instead:

* A throwaway harness that `#include`s `payload.c` to reach the static checker: zero-length
  rejected as 21 (`OCA_FAIL_PAYLOAD_TOC`), **one-byte and full-size still accepted**, and the
  misaligned and out-of-bounds cases still rejected. The accept half is the important one — a
  structural rule is easy to make too strict.
* The Python suite: 49 tests in `test_oca_toc.py` + `test_oca_combined.py` pass, so nothing
  legitimately packs a zero-length entry.
* End-to-end through SEP DV, which is the real proof and is what `sep_bl1_size_invalid_test`
  now asserts.

### Consequences taken deliberately

* **The submodule pin is NOT bumped.** The library commit is local and unpushed; moving the
  pin would point the branch at a commit nobody can fetch. The library change needs its own PR
  first, then a pin bump.
* **The ROM keeps its own length check** even though the library now gates first, because the
  ROM must not depend on which library version it links. That makes `BL1_SIZE` unreachable
  from a manifest — so `sep_bl1_size_invalid_test` now *forbids* all three arms of the ROM's
  BL1 check, and their absence is the positive evidence the structural rule ran ahead of
  hand-off. The test's own docstring had already predicted this: it said the gate "cannot be
  reached from a manifest at all".
* **The family base's discriminator changed.** `sep_bl1_image_invalid_base` proved "the defect
  is downstream of the crypto chain" with `PAYLOAD_OK`, which this member no longer reaches —
  its defect is caught *by* the payload validator rather than after it. `MANIFEST_OK` is the
  marker that carries that claim, and it holds for every member.
* **DV can still plant the defect.** The producer guard is in the packer's config path; the DV
  stimulus edits packed bytes. That split is intended: a Producer cannot emit one, and DV can
  still prove the Consumer rejects one.

### A ROM echo that could never fire, caught only by running it

The first hardware run printed `PUBK_SEL=`, `PUBK_REVOKE=` and `FUSE_VER=` — and no
`MFST_VER=`. The echo was guarded on `rom_oca_body()`, which is NULL during validation:
that global deliberately means *the accepted slot's body* and is assigned only after
`PAYLOAD_OK`. Moved to `oca_boot.c`, where the staged body is a local, rather than adding a
staged-body accessor a later reader could mistake for authenticated state. Per slot the order
is now:

```
MANIFEST_SRC= -> OCA_BODY= -> MFST_VER= (claim, at staging) -> PUBK_SEL= ->
PUBK_AUTHORIZED -> PUBK_REVOKE= -> FUSE_VER= (device, at the comparison) ->
RSA_EXEC -> RSA_VERIFY_OK -> MANIFEST_OK -> PAYLOAD_OK
```

Worth recording as a method point: the three echoes that worked and the one that silently did
not were indistinguishable from source review. Only the console proved which.

## Measured RSA test runtime, and what it means for the regression (2026-09-10)

The testlist tells readers to budget "~35-45 minutes" for a two-modexp test. Measured on this
box, every RSA test that has actually completed took **2.4-2.6 hours**:

| test | verdict | sim time | wall |
|---|---|---|---|
| `sep_firmware_device_cntl_non_secure_boot_flow_test` | PASS | 41.5 ms | 9344 s |
| `sep_rom_ot_secure_boot_test` | PASS | 46.7 ms | 8732 s |
| `sep_firmware_enforced_secure_boot_flow_test` | FAIL | 28.5 ms | 8771 s |

`sep_rom_ot_secure_boot_test` is one of the **original nine** `+esrc_noise_force` entries, so
~2.5 h is the established cost of the real ESRC->CSRNG->EDN chain here and **not** a
regression introduced by moving the other 24 entries onto it. OTBN stalls on EDN for URND
reseeds and the live chain has to produce that entropy rather than having it granted.

Two consequences worth planning around:

* **A test sitting at `RSA_EXEC` for two hours is normal, not hung.** Diagnose with CPU time
  (`/proc/<pid>/stat` fields 14+15 -- one core busy is ~100 ticks/s), not with sim-time
  advance: the log only timestamps events, so a quiet modexp looks identical to a hang. Sim
  time is also not a progress measure across runs -- a *failed* run reached 46.7 ms by bailing
  early and then spinning in the failover poll, further than a healthy run's 27 ms of real
  work.
* **A serial full regression is not viable.** ~30 RSA entries x 2.5 h is ~75 h. `run_dv.py`
  takes `--sim-jobs N`; at 8 that is ~10 h, subject to VCS licences and to this being a shared
  box (another user's `sep_efuse_*` runs were live during this session -- check process
  ownership with `stat -c %U /proc/<pid>` before killing anything that matches a grep).

The "35-45 minutes" note was left alone rather than edited: it may be accurate for whatever
machine it was written against, and the measured numbers belong here rather than in a testlist
comment that would then disagree with someone else's environment.
