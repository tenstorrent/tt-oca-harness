# Split the SEP ROM/DV/doc work from the VP work and stage it for main

Untracked by convention, for offline review. Plan written 2026-09-03/04; outcomes are appended at
the end as the work lands.

## Context

`tt-oca-harness` branch `inmcm/integrate_oca_boot_manifest` (local only, tip `e9ccbffd7`) carries
22 linear commits on top of `d14133828`, which is exactly the tip of
`origin/feature/sep_virtual_platform` (PR #1444 merge). Those 22 commits hold the OCA boot
manifest integration, the in-ROM entropy bring-up, the ROM specification, and the
tt-oca-manifest submodule switch, interleaved with virtual-platform (VP) test/runner work.
Most are `WIP PHASE X` commits and three of them mix `virtual_platform/` and `hw/sys/sep/` changes.

Wanted:

1. A cleaned feature-work branch with the **same final tree** but a readable log: VP and
   ROM/DV/doc changes in separate commits, 3-6 sentence messages. It will reach
   `feature/sep_virtual_platform` via PR (the feature branch itself is never rewritten).
   `inmcm/integrate_oca_boot_manifest` itself is left untouched as the backup.
2. A new branch off `origin/main` holding only the ROM + DV + doc commits, ready to push and
   PR into `main`. Nothing under `virtual_platform/`, nothing that needs it.

## Ground truth established during exploration

- **Shared history stops at `d14133828`.** Everything above it is local. The 22 commits are
  bisect-clean linear history (no merges), so the rewrite is a straight re-parenting.
- **No hard VP coupling.** No build rule, import, include or test config under `hw/sys/sep/`
  references `virtual_platform/`. Only comments/docstrings and one line of spec prose
  (`hw/sys/sep/bootrom/prod/doc/rom.adoc:80-83` names `virtual_platform/Makefile`).
- **Mixed commits:** `98a06be38` (Phase 4, also moves the tt-oca-harness-model pin to `619079d4`),
  `4cdc1527b` (Phase 5), `968b6502c` (VP fix + ROM one-liner + pin bump). Everything else is
  already one side or the other (`597a47ebe` is VP-only: six lines of `virtual_platform/Makefile`).
  `.gitmodules`, `.gitignore` edits belong to the non-VP side.
- **origin/main moved 57 commits** past the feature branch's merge-base (`99bb553c2`), including
  `hw/sys/sep: Add AXI isolation and reset sequencing for SEP crypto modules (#1253)` and
  `hw/entropy_source: Route the post-BIW health-test count_err (#1512)`, which sit directly under
  the ROM's new entropy bring-up. Files changed on both sides: `.gitignore`,
  `hw/sys/sep/doc/crypto.adoc`, `hw/sys/sep/doc/memory_map.adoc`,
  `hw/sys/sep/dv/docs/SEP_TB_ARCH.adoc`, `hw/sys/sep/dv/tb/tb_top.sv` (our hunk is comment-only).
- **The already-pushed VP port series also changed non-VP files** (`99bb553c2..d14133828`):
  `hw/sys/sep/bootrom/prod/Makefile` (+36: `-MMD -MP` header deps from `fc138d10b`, portable
  `SHELL := /usr/bin/env` + `.SHELLFLAGS` from `b0851d802`, uv-less packer fallback from
  `3fbf72e14`/`faa9dbff3`), `hw/common/dv/fw/compile.mk`, `hw/ip/key_manager/dv/tb/Makefile`,
  `scripts/docker-run.sh`, `tools/docker/*`, `ocah.mk`, `AGENTS.md`, `pyproject.toml`, `uv.lock`,
  `.github/workflows/vp.yml`, `.gitmodules`. Only the bootrom Makefile hunks are needed on main
  (our later Makefile commits build on them).
- **Submodules.** origin/main still has `tools/tt-boot-manifest` at `b2d628fa` (same as the first
  bump's parent, so the pin bumps cherry-pick cleanly). Our branch ends with `tools/tt-oca-manifest`
  at `171e02fa` (on tt-oca-manifest `origin/main`, good). The VP model pin is `416200e9`, which is
  tt-oca-harness-model `origin/main` (uprev commit `e9ccbffd7`, 2026-09-04, VP-only); the
  intermediate pin `619079d4` set in Phase 4 is also on model main, so every pin in the history
  is reachable.
- **CI on main:** `lint-python` (ruff, `select = E,F,I`) gates PRs; `ruff check` on our changed
  SEP Python files reports **37 findings** (`doc/checks/check_tables.py` and `check_xrefs.py`
  one-liner style E701/E702/E401/E741/F401, I001 import order in three cocotb tests, unused
  `cocotb` import in `sep_esrc_noise.py`). Sim CI runs only `no_cpu`/smoke for SEP: **the ROM DV
  tests are never run by CI**, so local VCS runs are the only evidence.
- **Policy violation to fix before main:** five of six `hw/sys/sep/doc/checks/*.py` hardcode
  `pathlib.Path('/localdev/cmccoy/dev/tt-oca-harness')` (personal absolute path; the open-repo
  rule forbids internal paths). `check_reg_addresses.py` already does it right with
  `Path(__file__).resolve().parents[5]`.
- **Stale comment:** bootrom Makefile says entropy bring-up is "Off by default" above
  `SEP_ENTROPY_BRINGUP ?= 1`.
- **Repo merge settings:** main PRs land squash-merged with `COMMIT_MESSAGES` as the body, so the
  per-commit messages below become the squash body verbatim (merge-commit is also allowed).
- **Environment for verification:** no simulator on PATH; DV runs via `source nonfree/setup_env.sh`
  (VCS) with the cocotb-1.9 `venv/bin/python` at repo root, one `--items` per invocation
  (Xcelium is broken here). ROM firmware builds need picolibc, so the bwrap rootfs path
  (`OCAH_TOOLCHAIN_ROOTFS=/localdev/cmccoy/ocah-toolchain-rootfs`) is used; `oca-images` runs
  natively with uv. `asciidoctor` is at `~/bin`. `ruff` is on PATH; codespell/yamllint are not.

## Decisions (confirmed with the user 2026-09-03)

- Fixups (doc-check root path + ruff findings, stale comments) go on **both** branches as two new
  commits on top of the verified tree-identical rewrite.
- **All seven** ROM DV tests run under VCS on the merge branch.
- **Push nothing.** Both branches stay local; the report ends with the exact push / `gh pr create`
  commands and a drafted PR body (kept in this file).
- **The tt-oca-manifest submodule switch goes to main.** Commit A22 (`treewide: Switch manifest
  tooling to the tt-oca-manifest submodule`) is part of the merge-branch content, together with
  the two intermediate tt-boot-manifest pin bumps that precede it (A01, A03, A08). The merge
  branch's final state therefore has `hw/sys/sep/bootrom/prod/tools/tt-oca-manifest` at
  `171e02fa` (tt-oca-manifest `main`), no tt-boot-manifest submodule, and a `.gitmodules` with
  only the tt-oca-manifest stanza. Every ROM build, DV run and doc check on the merge branch
  exercises the new submodule.
- **`inmcm/integrate_oca_boot_manifest` is not rewritten.** It stays exactly where it is as the
  backup; the cleaned history goes on a **new** branch, `inmcm/integrate_oca_boot_manifest_clean`
  (rename with `git branch -m` if a different name is preferred). Save this as a feedback memory
  during execution: never rewrite an existing branch, build the cleaned one beside it.

## Assumptions (stated, not re-asked)

- Merge branch name: `inmcm/sep_rom_oca_manifest`, in a sibling worktree
  `/localdev/cmccoy/dev/tt-oca-harness-main` (the main checkout keeps the VP submodule).
- Granularity: keep the existing commit boundaries (one commit per phase) and split only along the
  VP / non-VP line. Do **not** further split ROM vs DV halves (a ROM fix and the DV test that found
  it stay together). One fold only: the pin bump `2983a16bb` into Phase 0+1 (adjacent, no-op alone).
  Subject convention follows main: `rom/sep:`, `dv/sep:`, `doc/sep:`, `sep:`, `treewide:`; VP
  commits use `vp:`.
- Two **new** small commits go on top of the cleaned branch (after the tree-identity check), so
  both branches get them: the doc-check path/lint fix and the stale-comment/import-order fixes.
  These are the only content changes; everything else is byte-identical to today's tip.
- Excluded from main on purpose: `hw/common/dv/fw/compile.mk` prefix handling, key_manager
  Makefile shell fix, `scripts/docker-run.sh` fixes, container consolidation, `ocah.mk` include,
  `pyproject.toml`/`uv.lock` vp group, `vp.yml`, `AGENTS.md` VP text, `.gitignore`
  `och_sep_ss.log`. All VP-motivated; none needed by ROM/DV/doc.
- VP mentions in ROM/DV comments stay as they are (harmless; the VP lands later via PR #1028).
  Only the `rom.adoc` prose that names `virtual_platform/Makefile` is generalised, on both branches.
- This file is the offline-review copy of the plan (memory convention); outcomes are appended below
  as the work lands.

---

## Part A. Build `inmcm/integrate_oca_boot_manifest_clean` from `inmcm/integrate_oca_boot_manifest`

### Mechanics

Tree-based with `commit-tree`, no working tree or index involvement, so submodule gitlinks are
never re-staged from disk (git is 2.26.2 here: no `--update-refs`, no `--trailer`; a
`rebase -i` + `exec` split would go through the working tree, where `tools/tt-oca-manifest` is
populated and an empty `tools/tt-boot-manifest` dir lingers). A temp-index `git rm --cached`
approach was rejected: `rm` runs the `.gitmodules` staleness check against the cwd's file and dies.
Since `virtual_platform` is one top-level tree entry, swap it with `mktree`:

```bash
nonvp_tree() {  # $1 = old commit C, $2 = current new tip N
  local vp; vp=$(git rev-parse "$2:virtual_platform")
  git ls-tree "$1" | awk -F'\t' -v vp="$vp" \
    '$2=="virtual_platform"{print "040000 tree " vp "\tvirtual_platform"; next}{print}' | git mktree
}
N=$(git rev-parse d14133828)
for C in $(git rev-list --reverse d14133828..e9ccbffd7); do
  s=$(git rev-parse --short $C); [ $s = 2983a16bb ] && continue        # folded into 94ef1d835
  export GIT_AUTHOR_NAME=... GIT_AUTHOR_EMAIL=... GIT_AUTHOR_DATE=...  # copied from C
  case $s in
    98a06be38|4cdc1527b|968b6502c)   # mixed: non-VP half, then VP half
      t=$(nonvp_tree $C $N); n1=$(git commit-tree $t -p $N -F msgs/$s.nonvp); purity $N $n1
      n2=$(git commit-tree $C^{tree} -p $n1 -F msgs/$s.vp);              purity $n1 $n2; N=$n2;;
    *)  n=$(git commit-tree $C^{tree} -p $N -F msgs/$s);                purity $N $n;   N=$n;;
  esac
  [ "$(git rev-parse $N^{tree})" = "$(git rev-parse $C^{tree})" ] || { echo "tree drift at $s"; exit 1; }
done
```

`purity A B` asserts the diff A..B is non-empty and either entirely under `virtual_platform/` or
entirely outside it. The per-step tree-equality check makes the final byte-identity check
redundant but it is run anyway. Author name/email/date copied from the old commit; committer is
me. New messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`
(059e70c25 keeps its existing message verbatim). Script and message files live in
`$CLAUDE_JOB_DIR/tmp/rewrite/`. Then:

```bash
git diff --quiet e9ccbffd7 $N                                  # must be empty
git branch inmcm/integrate_oca_boot_manifest_clean $N          # new branch; the old one is untouched
git checkout inmcm/integrate_oca_boot_manifest_clean           # identical tree: no file changes
git status --short                                             # clean apart from the untracked plan files
```

Then A25/A26 are made as ordinary working-tree commits on the new branch.
`inmcm/integrate_oca_boot_manifest` keeps pointing at `e9ccbffd7` throughout.

### Commit map (old → new). VP = `virtual_platform/` only

| # | Old | New subject |
|---|---|---|
| A01 | 2983a16bb + 94ef1d835 | `rom/sep: Link the OCA validator library and pack OCA test images` |
| A02 | 0b80e3d5b | `rom/sep: Add the SEP platform callbacks for the OCA validator` |
| A03 | 1cdcbb29c | `rom/sep: Replace the Grendel manifest parser with the OCA boot flow` |
| A04 | 98a06be38 (non-VP) | `rom/sep: Add AES-256-CBC decryption, PKCS#7 and the OCA payload KDF` |
| A05 | 98a06be38 (VP) | `vp: Provision CLASS_KEY for encrypted boot and uprev the harness model` |
| A06 | 4cdc1527b (non-VP) | `rom/sep: Fix key-slot numbering and report per-slot boot status` |
| A07 | 4cdc1527b (VP) | `vp: Add OCA boot coverage and an eFuse map drift guard` |
| A08 | 968b6502c (non-VP) | `rom/sep: Map the OCA signature-class refusal to a status code` |
| A09 | 968b6502c (VP) | `vp: Expect the library's signature-class refusal for unsigned images` |
| A10 | 0ded1d367 | `dv/sep: Repoint ROM boot tests at OCA images and fix SBOOT state` |
| A11 | dd3bd4a5e | `dv/sep: Add encrypted, OTP-key and tamper ROM boot tests` |
| A12 | 88fa042f8 | `rom/sep: Rename the ROM key slots and consolidate the test signing keys` |
| A13 | 5b8efbce4 | `vp: Add per-slot ROM key use, revoke and isolate coverage` |
| A14 | 31e8ba1b6 | `rom/sep: Drop the Grendel image build targets and configs` |
| A15 | 8dad35d86 | `vp: Drop the Grendel signed-image target and fixture` |
| A16 | 0a215cd7e | `doc/sep: Add the SEP boot ROM specification and wire it into the book` |
| A17 | 4b59a4437 | `rom/sep: Bring up the entropy chain in the ROM before OTBN and AES` |
| A18 | 597a47ebe | `vp: Fingerprint status-table contents in the VP config signature` |
| A19 | 059e70c25 | (unchanged) `doc/sep: Resolve three open questions in the SEP ROM specification` |
| A20 | 56b8b89a9 | `doc/sep: Add mechanical consistency checks and fix what they found` |
| A21 | fd96f3340 | `dv/sep: Correct the entropy comments in the secure-boot test and testlist` |
| A22 | 410a95e22 | `treewide: Switch manifest tooling to the tt-oca-manifest submodule` |
| A23 | 7887de3eb | `vp: Point manifest tooling paths at tt-oca-manifest` |
| A24 | e9ccbffd7 | `vp: Uprev tt-oca-harness-model to main for the entropy-source fixes` |
| A25 | new | `doc/sep: Anchor the doc checks on the repo root and make them lint-clean` |
| A26 | new | `sep: Fix stale comments and import order flagged by review and ruff` |

Non-VP set (cherry-picked to main): A01-A04, A06, A08, A10-A12, A14, A16-A17, A19-A22, A25-A26 (18).

### Draft messages (bodies; each ends with the Co-Authored-By trailer)

**A01** Uprev the tt-boot-manifest submodule to d17b8fa3, which ships the freestanding OCA
validation library under validators/oca/lib, and compile that library into the boot ROM. The
objects go into their own build/oca/ subdirectory because the library carries its own
lifecycle.c that would otherwise overwrite the ROM's, and they join OBJS so they inherit the flag
stamp and header dependency tracking. The OCA_SUPPORT_CLASSIC/PQC and OCA_TOC_MAX_IMAGES gates go
into both CFLAGS and BUILD_FLAGS so a gate change forces a rebuild, and the build fails with a
clear error when the submodule is not checked out. A new oca-images target packs the first two OCA
test images (non-secure and RSA-3072 signed) from configs that pin the timestamp for
byte-deterministic output; the DV compile step runs it and lists the images as outputs. Nothing
calls the library yet, so ROM behaviour is unchanged.

**A02** Add sep_oca_callbacks(), the platform callback table the OCA validation library drives,
as a thin adapter over drivers the ROM already has: sha256(), rsa_3072_verify(), lc_read_state()
and the eFuse shadow reads. The set_* entries stay NULL by design so the ROM never burns fuses.
The table encodes the contracts from the library's INTEGRATION.md: boolean reporters return the
oca_secure_bool_t sentinels, OCA_HW_UNAVAILABLE is a hard failure, and OCA_LIFECYCLE_UNKNOWN is
written before any early return. plat_verify_signature() accepts RAW RSA-3072 only and requires
the key's public exponent to be exactly 0x00010001, because the OTBN application is the fixed-F4
modexp and would otherwise silently verify an e=3 key against 65537. Nothing calls the table
yet, so the ROM image is unchanged.

**A03** Delete manifest_load.c, manifest_crypto.c and their headers and reimplement the boot flow
in oca_boot.c as the library's staged sequence: peek the manifest, copy it into SEP SRAM,
validate, resolve payload encryption, locate and copy the payload, then check it in place. Slot
rotation, the SMC handshake and manifest_src_read() are unchanged, and authentication always runs
over the SRAM copy rather than the storage medium. The submodule moves to 54c7cf37 for the
is_key_authorized callback, which anchors trust in the ROM key digests before revocation and
signature checks so an attacker-supplied key that signs its own manifest is refused by the
library rather than by convention. rom_handoff.c finds BL1 by its 16-byte TOC type string
instead of assuming entry 0, and rom_main.c reads demotion from the manifest's demotion_control
field. Failures report the library verdict verbatim as 0x000300xx so a console log identifies the
exact rejection, and new *_image.yaml configs place the packed bundle at both manifest slots
because a bare bundle at offset 0 is not bootable.

**A04** Make encrypted OCA payloads boot. aes128cbc_decrypt() becomes aes_cbc_decrypt() taking the
key width, writing all eight KEY_SHARE0 words and the one-hot KEY_LEN encoding, and rejecting
unknown widths instead of letting the hardware default to AES-256; aes_pkcs7_strip() removes
padding in constant time with respect to the pad value. kdf.c is rewritten to the OCA/Key Manager
192-byte derivation block (header, "KM_CLASS_BL" label, kdf_input, entropy) in place of the old
41-byte encoding. plat_decrypt_payload() resolves secret_select against the CLASS_KEY eFuse bank,
decrypts in place, and refuses an all-zero bank as NO_PROVISIONED_SECRET rather than deriving a
key that fails later as a hash mismatch. Two latent HMAC driver bugs, unreachable until now, are
fixed: CFG.key_length was never set, so every HMAC returned 0xFFFFFFFF, and the key was packed
little-endian into big-endian KEY registers. New oca_encrypted_boot_{test,image}.yaml configs pack
the encrypted test image.

**A05** Add the oca_encrypted fuse map, which provisions the CLASS_KEY bank the ROM's OCA KDF
derives the payload key from, so the encrypted-boot image can run on the virtual platform. Move
the tt-oca-harness-model pin to 619079d4, which carries the eFuse offset and re-sync fixes, the
SMC-SRAM backdoor and the entropy_src model work the OCA test suites depend on. This is the VP
half of the AES-256/KDF change; the fuse map's CLASS_KEY words must match the key
oca_encrypted_boot_test.yaml encrypts with.

**A06** public_key_select_classic and CHIPLET_PUBK_REVOKE share one slot numbering (bits 0-7 ROM
classical keys, 8-15 ROM PQC keys, 16 and up the OTP banks), but the ROM mapped bits 6-9 to the
OTP banks, so authorization and revocation named different keys and the OTP anchor was
unreachable. Fix the mapping and refuse PQC and reserved slots explicitly. A per-slot failure is
now a WARN carrying the exact library verdict and only the final failure is an ERROR, so a boot
recovered from the backup slot no longer looks like a failure; MANIFEST_PRIMARY/BACKUP is keyed on
the slot rather than the retry counter, and rom_err_fail() no longer truncates 0x0003xxxx verdicts
into the SEP_MSG space. Distinct console markers (PUBK_NO_SIGNATURE, PUBK_ALGO_UNSUPPORTED, ...)
separate the causes the library folds into one callback result. The Makefile's image list becomes
one OCA_IMAGES variable with a single pattern rule, and nine new config pairs cover AES-128, DER
keys, ECDSA, identity constraints, multi-image TOCs, no-BL1, OTP-anchored keys, PQC and SIP keys.

**A07** Replace the Grendel-era negative tests with OCA suites: about fourteen positive cases in
test_bootcode_oca.py (signed, encrypted, AES-128, DER, ECDSA refusal, identity match, multi-image,
no-BL1, OTP key, PQC, SIP key, SMC-SRAM path) and nine negative cases in
test_bootcode_oca_negative.py (tampering, revocation, wrong key, identity mismatch, version
rollback). oca_layout.py reads manifest offsets from the producer's constants.py by path so the
tests cannot drift from the packer. The sepvp runner gains SimConfig.smc_sram_image, an oca_images
session fixture that builds and checks every image, fuse-map helpers and a repo-wide
otbn.algorithm_type = rsa_3072 default; eight new fuse maps provision the OTP key, SIP key,
identity and revocation scenarios. test_efuse_map_drift.py compares the model's eFuse header
against the generated sep_addr.h so a model that falls behind the RDL fails loudly instead of
reading the wrong bank.

**A08** Uprev tt-boot-manifest to f2929195, where the validator refuses an unsigned manifest on a
secure-boot part before any key callback runs and reports OCA_FAIL_SIGNATURE_CLASS_CONTROL (0x24).
Map that verdict to SEP_MSG_MANIFEST_SECURE_BOOT so the case is reported as a secure-boot refusal
rather than degrading to the generic MANIFEST_LOAD_FAILED. The observable marker changes:
PUBK_NO_SIGNATURE is no longer printed for this case because is_key_authorized is never reached.

**A09** The uprevved validator refuses an unsigned manifest on a secure-boot part inside the
library, before the ROM's key callback runs. Retarget the unsigned-on-secure test to assert
MANIFEST_ERR=0x00030024 and the MANIFEST_SECURE_BOOT status instead of the PUBK_NO_SIGNATURE
marker, pinning the exact code so an unrelated error cannot satisfy the test.

**A10** The four existing ROM DV tests still fed Grendel images to the OCA-only ROM and failed
with OCA_FAIL_MAGIC on both slots. Point them at oca_non_secure_boot.bin and oca_secure_boot.bin
and replace the console markers that died with manifest_crypto.c (MANIFEST_HASH_OK, PLD_HASH_OK,
RSA_VERIFY_START, SIG_VALID, CRYPTO_VALIDATE_OK) with MANIFEST_OK, PAYLOAD_OK, PUBK_AUTHORIZED,
RSA_EXEC and RSA_VERIFY_OK. A new oca_smc_mem.hex target rebases the combined image, not the bare
bundle, so the manifest lands at the SMC responder's MANIFEST_ADDR of 0x1000; sep_sim_cfg.toml
builds it and rom_fw.toml loads it. Simulation exposed a ROM bug the VP suite could not:
bl0_state.secure_boot was never written after the boot-flow rewrite, so a verified boot printed
SBOOT_OFF and told BL1 it was unverified. It is now copied from the validation context, and the
ROM prints PAYLOAD_OK so the payload check leaves console evidence.

**A11** Add three OCA DV tests: an AES-256-CBC encrypted payload keyed from CLASS_KEY, a
signature anchored on CHIPLET_PUBK_HASH0 instead of a ROM digest, and a negative test with a byte
flipped in the signed region of both slots. The scoreboard gains expect_fw_pass because a refused
boot still asserts fw_done through rom_err_fail(), so the gate is fw_pass with the PC-advance
check separating a deliberate refusal from a crash. Two real bugs fell out: aes_init() had no
call site, so the AES engine sat in reset and wait_idle() burned its full timeout (it is now
called from plat_decrypt_payload()), and the +sep_crypto_edn_force shortcut granted only OTBN's
EDN clients while AES is client 0, so tb_top.sv extends the grant. aes_driver.c prints
AES_IDLE_TIMEOUT with the status word so a dead engine and a stuck one are distinguishable. The
DMA boot test promotes make_efuse_image() and max_run_cycles to class data so the new tests can
override them.

**A12** Rename the six ROM root-key slots from dev0/dev1/prod0-3 to rom_key0-5. The old names
implied a trust distinction the ROM does not make: all six resolve through
public_key_select_classic bits 7:0, the same numbering CHIPLET_PUBK_REVOKE uses. Move the test
keys out of the manifest submodule into bootrom/prod/tests/signing_keys/ with a distinct RSA key
per slot plus the P-256 key, and add five per-slot signed images so an off-by-one in slot
resolution can no longer match a digest by accident. key_digests.c is regenerated, which changes
the slot 0 digest, so the DV OTP-anchor test's CHIPLET_PUBK_HASH0 words are re-derived.
generate_key_digests.py emits SPDX headers and derives the slot names from the slot count. The VP
fuse maps that hardcode the slot 0 digest are updated in the following commit.

**A13** Update the four committed fuse maps to the new slot 0 digest from the key consolidation,
re-flipping the LSB in oca_otp_key_wrong.yaml so it still differs in exactly one bit. Add
test_bootcode_oca_rom_keys.py, which for each of the six slots checks that its image authorizes
(PUBK_AUTHORIZED before RSA_VERIFY_OK), that revoking it via CHIPLET_PUBK_REVOKE bit N yields
SEP_MSG_REVOKED_KEY after authorization, and that revoking the other five leaves slot N bootable,
which is the check that pins the bit numbering. Revocation fuse maps are generated into tmp_path
instead of committed. test_digest_table_pins_six_slots parses key_digests.c for six distinct
non-NULL digests to guard the premise, paths.OCA_ROM_KEY_IMAGES maps slots to images, and the
oca_images fixture covers the five new per-slot images.

**A14** Nothing parses the Grendel format any more, so remove its build path: the pack-images and
secure_boot_spi targets, their variables, and the non_secure_boot_test.yaml and
secure_boot_test.yaml configs. The default target is now toolchain-images plus oca-images, and
SEP_SIGNING_KEY survives only as the guard for the OCA recipe. All three c_build blocks in
sep_sim_cfg.toml drop the Grendel targets and outputs (smc_mem.hex, non_secure_boot.bin,
secure_boot.bin), so a stale Grendel artifact can no longer satisfy a stage check. Purely
subtractive; the OCA images and rules are untouched. The virtual platform's boot-secure-image
target depended on secure_boot_spi and is removed in the following commit.

**A15** Remove the boot-secure-image target and SECURE_BOOT_PRELOAD from virtual_platform/Makefile,
and paths.SECURE_BOOT_PRELOAD and the secure_boot_preload fixture from the pytest plugin; all
three pointed at the secure_boot_spi target and build/secure_boot.spi_preload artifact the ROM
build no longer produces. Rename pack-images to oca-images in two docstrings and correct the
OCA_ROM_KEY_IMAGES comment to say ROM key 0 rather than the submodule's dev0 key. No test
referenced the fixture, so nothing is left dangling.

**A16** Add rom.adoc, the SEP boot ROM specification (tagged SEP-ROM-* requirements, the
security-check inventory, boot-stage to status-code traceability and the implementation-status
matrix), and include it from index.adoc so it renders as part of the SEP chapter. Its two
unresolvable includes are gone: the settings template is dropped and the status-code registry is
generated in-repo by gen_status_table.py from bootrom/prod/include/status_values.h, the header the
ROM compiles against, into gen/status_values.adoc. cpu.adoc's BL0 section shrinks to a summary
that names rom.adoc as normative, removing a duplicate flow that described verifying BL1 with a
key carried in the manifest itself. lifecycle_controller.adoc gains an implementation-status note
that the multi-owner REQUIRED_SIGNERS/REQUIRED_ALGS model is not implemented, and doc_render/ is
gitignored for local asciidoctor output.

**A17** The ROM now brings the ESRC -> CSRNG -> EDN chain up itself instead of relying on the DV
+sep_crypto_edn_force grant, which bypassed the chain and violated the EDN req/ack data-hold
protocol once assertions were enabled under VCS. sep_entropy.c implements the documented sequence
(configure with generators off, enable the ring oscillators and poll MAIN_SM_STATUS.BOOT_PHASE_DONE,
enable EDN and wait for the Instantiate ack), pulses TRNG_SW_RST_N, and applies FIPS_LOCK and
EXT_TRNG_SRC_SEL_LOCK with read-back verification; each lock can be deferred to BL1 with
SEP_ENTROPY_DEFER_*_LOCK. Bring-up is lazy and idempotent, invoked from the two crypto callbacks,
so an unsigned boot pays nothing, and a failure is terminal (SEP_MSG_ENTROPY_INIT_FAILED) rather
than surfacing later as a bogus signature error; the external TRNG is left as a weak-symbol seam.
DV switches the three crypto tests to +esrc_noise_force, which drives only the decorrelator noise
inputs because ring oscillators do not oscillate in simulation, adds the sep_esrc_noise.py driver,
and drops the AES EDN force from tb_top.sv. All seven ROM tests pass with the real handshakes.

**A18** VP_CONFIG_SIG covered the path of STATUS_VALUES_PATH, not its contents, so adding a
SEP_MSG_* code left the configure-baked status decoder stale and new codes printed as
SEP_MSG_UNKNOWN. Mix a cksum of the file into the signature so the two codes the entropy bring-up
adds force a reconfigure. This was a latent bug against the signature's stated intent; the entropy
work merely surfaced it.

**A20** Add six scripts under doc/checks/ that cross-reference the specification against generated
headers, the RDL and the manifest producer's constants: anchor resolution, table cell counts,
manifest offsets, register addresses, error-code names and bare identifiers. Each found a real
defect. The eFuse address table was shifted by four bytes by the LOCKS_SPARE insertion, so the
documented BL1_VERSION address was CHIPLET_PUBK_REVOKE's; stale PUBLIC_KEY_0/1 rows are replaced
by the five current OTP banks. Manifest offsets are corrected to the current producer, including
the signed region growing from [0,3145) to [0,3172) and manifest_security_control widening to two
bytes. A new entropy section specifies the ROM's bring-up (SEP-ROM-ENT-010 to -050), the SEP_MSG
code table anchor is fixed in the generator, a dead xref in memory_map.adoc is retargeted, and
personal branch names are replaced with commit hashes.

**A21** Both files still described the retired whole-chain grant ("the boot flow does not bring up
entropy_source/CSRNG/EDN") while annotating an argument that had already become
+esrc_noise_force. Rewrite the comments to say the ROM brings the chain up itself and the plusarg
forces only the decorrelator noise input, with the health tests, CSRNG, EDN and command handshakes
real. Comment-only; nothing rebuilds.

**A22** Replace the tt-boot-manifest submodule with tt-oca-manifest (171e02fa, branch main) at
hw/sys/sep/bootrom/prod/tools/tt-oca-manifest; the new repo carries only the OCA producer,
validator library and documentation. TT_BOOT_MANIFEST_DIR becomes TT_OCA_MANIFEST_DIR and drives
OCA_LIB_DIR, the uv packer invocation, the no-uv PYTHONPATH shim and both missing-submodule
errors; the doc checks, DV config, testlist and docs follow the rename. Upstream renamed only the
distribution and kept the tt_boot_manifest Python package name, so the python -m
tt_boot_manifest.pack_images invocation is unchanged and a Makefile note says why. Layout constants
are identical across the move, so no manifest offsets change. An existing build tree needs one
make clean, because the generated .d files still name the old path.

**A23** oca_layout.py loads the producer's constants.py by path at runtime; move that path to
tools/tt-oca-manifest so the VP bootcode tests do not fail with FileNotFoundError after the
submodule switch. The remaining edits are Makefile notes, the pytest skip message and docstrings
that named the old submodule.

**A24** Move the tt-oca-harness-model pin from 619079d4 to 416200e9, the model's current main,
which carries the entropy_src and EDN fixes the ROM's in-ROM bring-up needs (MAIN_SM_STATUS,
FIPS_LOCK, the CSRNG command-header clen parse and the CMD_RDY/FSM agreement) plus the
memory-safety audit merged since. Every pin this branch has carried is now an ancestor of model
main. VP-only; the ROM, DV and docs are untouched.

**A25** (new content) Five of the six doc consistency checks hardcoded an absolute personal
checkout path as the repo root, which fails in any other checkout and violates the open-repo rule
against internal paths. Derive the root from the script's own location as check_reg_addresses.py
already does, and update checks/README.md accordingly. Expand the one-statement-per-line style in
check_tables.py and check_xrefs.py and drop the unused import so `ruff check` (the CI lint-python
gate: E, F, I) passes on the doc tree. Behaviour of the checks is unchanged.

**A26** (new content) The boot ROM Makefile said the entropy bring-up was off by default above a
line that sets SEP_ENTROPY_BRINGUP ?= 1; make the comment match. Sort the import blocks in the
three OCA cocotb tests and drop the unused cocotb import in sep_esrc_noise.py so CI's ruff gate
passes. Generalise the one rom.adoc sentence (and the gen_status_table.py docstring) that named
virtual_platform/Makefile, so the published specification does not point at a path that need not
exist in every checkout; the statement that the VP's decoder reads the same header stays.

### Part A verification

1. `git diff --quiet inmcm/integrate_oca_boot_manifest <A24>` (before A25/A26) → empty.
   Print `git log --oneline d14133828..inmcm/integrate_oca_boot_manifest_clean`.
2. Purity script over the new commits: each touches only `virtual_platform/**` or nothing under it.
3. `git rev-parse inmcm/integrate_oca_boot_manifest` still `e9ccbffd7`; `git submodule status`
   unchanged; `git status` clean apart from the untracked plan files.
4. After A25/A26: run the six doc checks from the main checkout (they now resolve the root themselves)
   and `ruff check` on the changed SEP Python files → clean. Optional: `make -C virtual_platform vp-test`
   (tree unchanged for the VP; skip unless time allows).

---

## Part B. Merge branch `inmcm/sep_rom_oca_manifest` off `origin/main`

### Setup

```bash
git fetch origin
git worktree add --no-track -b inmcm/sep_rom_oca_manifest /localdev/cmccoy/dev/tt-oca-harness-main origin/main
cd /localdev/cmccoy/dev/tt-oca-harness-main
ln -s /localdev/cmccoy/dev/tt-oca-harness/nonfree nonfree     # gitignored; VCS env
ln -s /localdev/cmccoy/dev/tt-oca-harness/venv venv           # gitignored; cocotb-1.9 for VCS
```

### Commits, in order

**Pre-commits: bring `hw/sys/sep/bootrom/prod/Makefile` to the feature branch's blob (`75c763e2`).**
origin/main's Makefile equals `fc138d10b^`'s; four VP-series commits changed it afterwards and ten
of the eighteen cherry-picks edit inside those hunks (six conflict hunks in A22 alone otherwise).
Each is applied as a Makefile-only slice with `git show <c> -- hw/sys/sep/bootrom/prod/Makefile |
git apply --index --3way`:

1. `fc138d10b` in full (`git cherry-pick`): `-MMD -MP` header dependency tracking. Message kept.
2. `3fbf72e14` + `faa9dbff3` Makefile slices as one commit, author Calvin, new message
   `rom/sep: Let the manifest packer run without uv when its deps are importable`
   (PACK_RUN symlink shim fallback, ensure-pack-deps accepts importable deps, comment names
   `ocah-toolchain`).
3. `b0851d802` Makefile slice, `git commit -C b0851d802` (Daniel Green's message and authorship
   verbatim; drops its `virtual_platform/Makefile` and `hw/ip/key_manager` hunks).

Assert `git rev-parse HEAD:hw/sys/sep/bootrom/prod/Makefile` = `75c763e2` before continuing.

**Then** `git cherry-pick` the 18 non-VP commits A01-A04, A06, A08, A10-A12, A14, A16-A17,
A19-A22, A25-A26, one at a time, no `-x` (source hashes are local-only). Author name/email/date
are preserved by cherry-pick; trailers survive untouched.

Expected conflicts (from `git merge-tree` dry runs) and resolutions:
- **`.gitmodules` (A22):** whole-file conflict. main has only the tt-boot-manifest stanza; ours
  removes it and keeps the tt-oca-harness-model stanza. Resolve to **only** the tt-oca-manifest
  stanza (`path`, `url = git@github.com:tenstorrent/tt-oca-manifest.git`, `branch = main`). The
  gitlink delete/add themselves are clean; an uninitialised gitlink is just an empty dir.
- **`.gitignore` (A16):** one hunk at EOF vs main's edits; keep both, add only `doc_render/`.
- **`hw/sys/sep/dv/tb/tb_top.sv` (A17):** probably one hunk (our comment rewrite of the
  `+sep_crypto_edn_force` block sits near main's edits); keep both sides' intent.
- `crypto.adoc`, `memory_map.adoc`, `SEP_TB_ARCH.adoc`: merge clean per dry run.
- Gitlink bumps (A01, A03, A08) are clean because main's pin `b2d628fa` is the first bump's parent.
  If one does conflict: `git update-index --cacheinfo 160000,<sha>,hw/sys/sep/bootrom/prod/tools/tt-boot-manifest`
  (never `git add` the empty dir), then `git cherry-pick --continue`.
- Anything else gets resolved by hand and noted in this file.

Then, for build/test, populate the submodule without hitting the network:

```bash
git submodule update --init --reference /localdev/cmccoy/dev/tt-oca-harness/.git/modules/hw/sys/sep/bootrom/prod/tools/tt-oca-manifest \
  hw/sys/sep/bootrom/prod/tools/tt-oca-manifest
```
(In a linked worktree this clones into `.git/worktrees/<id>/modules/`; a later
`git worktree remove` needs `--force`.)

### Part B verification

1. **Content check.** For every file in `git diff --name-only d14133828 <A26> -- . ':!virtual_platform'`
   plus `hw/sys/sep/bootrom/prod/Makefile`: `git diff --quiet <A26> <merge-tip> -- <file>` must hold
   for all files main did not touch; for the five shared files, `git diff <A26> <merge-tip> -- <file>`
   must show only main's own hunks (`.gitmodules` additionally lacks the model stanza by design).
   `git diff --stat origin/main <merge-tip>` must list nothing under `virtual_platform/`,
   `tools/docker`, `scripts/`, `.github/`, `ocah.mk`, `pyproject.toml`, `uv.lock`, `AGENTS.md`.
2. `grep -rn 'virtual_platform\|sepvp\|tt-oca-harness-model' hw/sys/sep .gitmodules` → only
   comments/docstrings (list them in the report).
3. `ruff check $(git diff --name-only origin/main -- '*.py')` → clean (CI lint-python gate).
   `git show origin/main:.github/workflows/lint.yml` lists codespell/yamllint too; run
   `uvx codespell`/`uvx yamllint` on changed files if the tools can be fetched, else note CI covers it.
4. **ROM builds** (all three variants + images), same commands the DV c_build stage uses:
   ```bash
   export OCAH_TOOLCHAIN_ROOTFS=/localdev/cmccoy/ocah-toolchain-rootfs
   env -u RISCV_TOOLCHAIN -u RISCV_PREFIX ./scripts/docker-run.sh run-here \
     make -C hw/sys/sep/bootrom/prod NONFREE_ROOT= NONFREE_BOOTCODE_SOURCES= SEP_ENTROPY_BRINGUP=1 \
       toolchain-images ot-toolchain-images ot-pio-toolchain-images
   make -C hw/sys/sep/bootrom/prod NONFREE_ROOT= NONFREE_BOOTCODE_SOURCES= oca-images
   ```
   Expect 0 warnings, `boot_rom.vmem` ≈ 39680 B (64 KiB budget), 18 SPI preloads.
5. **Doc checks:** `for f in hw/sys/sep/doc/checks/check_*.py; do python3 "$f"; done` in the worktree
   (proves the root-anchoring fix); the four gate-worthy ones exit 0. `~/bin/asciidoctor` render of
   `hw/sys/sep/bootrom/prod/doc/rom.adoc` → no errors beyond the Antora-only `partial$` includes.
6. **DV under VCS** (the only place the ROM tests run; main's crypto AXI isolation and
   entropy_source changes have never been exercised with this ROM):
   ```bash
   source nonfree/setup_env.sh
   for t in sep_rom_non_secure_boot_test sep_rom_ot_dma_boot_test sep_rom_ot_pio_boot_test \
            sep_rom_ot_secure_boot_test sep_rom_oca_encrypted_boot_test \
            sep_rom_oca_otp_key_boot_test sep_rom_oca_tamper_test; do
     python3 tools/dv/run_dv.py --dut sep --items $t --tool vcs \
       --stage flist --stage c_compile --stage hdl_compile --stage sim
   done
   ```
   Run in the background (≈1-2 h wall clock). Zero `SyncReqAckDataHold*` hits. If a test fails
   because main's DV environment changed under it, fix it in a separate `dv/sep:` commit on the merge
   branch, report it, and flag it for the feature branch's next uprev; do not paper over it.
7. Record all results in this file and in the PR body draft.

### Hand-off (no push; user decision)

Nothing is pushed. This file gets a drafted PR body for the main PR (title
`rom/sep: Boot from the OCA manifest, bring up entropy in ROM, publish the ROM spec`; sections:
summary; ROM / DV / docs; deliberately excluded (VP, container consolidation, docker-run.sh fixes,
compile.mk); verification table (7 DV results, ROM size, doc checks, ruff); reviewer notes
(`make clean` once after the submodule swap; each commit builds; squash body = concatenated
messages, merge-commit also allowed). The final report lists the exact commands:

```bash
git push -u origin inmcm/sep_rom_oca_manifest             && gh pr create --base main --draft ...
git push -u origin inmcm/integrate_oca_boot_manifest_clean && gh pr create --base feature/sep_virtual_platform --draft ...
```

## Follow-ups (out of scope, to list in the report)

- `scripts/docker-run.sh` fixes (`9bd282114`: docker-only abort, ensure_image inspect,
  bwrap `--die-with-parent`) and the `compile.mk` prefix acceptance are real but VP-adjacent; they
  deserve their own small PR to main.
- `sep_sim_cfg.toml` `[c_build.boot_rom*]` outputs list only two of the 13 packed OCA images.
- Stale wording: bootrom Makefile `$(OCA_BINS)` guard and `rom_fw.toml` still say "dev0 key".
- Intermediate tt-boot-manifest pins (d17b8fa3, 54c7cf37, f2929195) may not be fetchable from the
  tt-boot-manifest remote any more; bisecting through A01-A21 would need them. Final state is
  unaffected.
- Stale worktree `.claude/worktrees/doc-open-questions` (branch `inmcm/doc-open-questions`, 15
  commits on the old base); PR #1028 (`feature/sep_virtual_platform` → main, WIP) is the eventual
  VP landing.
- Memory: record the branch layout (backup `inmcm/integrate_oca_boot_manifest`, cleaned
  `inmcm/integrate_oca_boot_manifest_clean`, VP-less `inmcm/sep_rom_oca_manifest`; feature branch
  only via PR; main squash-merges) and the feedback "never rewrite an existing branch, build the
  cleaned one beside it" in `/home/cmccoy/.claude/projects/-localdev-cmccoy-dev/memory/`.

---

## Outcomes

(appended as the work lands)

## Outcomes

Executed 2026-09-04. Nothing was pushed. Both branches are local; the push and
`gh pr create` commands are at the end of this section.

### Result

| Branch | Tip | Commits | Base |
|---|---|---|---|
| `inmcm/integrate_oca_boot_manifest` (backup, untouched) | `e9ccbffd7` | 22 | `d14133828` |
| `inmcm/integrate_oca_boot_manifest_clean` | `f14dcbbc4` | 27 | `d14133828` |
| `inmcm/sep_rom_oca_manifest` (worktree `../tt-oca-harness-main`) | see below | 22 | `origin/main` `c44999f9d` |

### Part A — the cleaned feature branch

The `commit-tree` rewrite ran exactly as designed. 22 old commits became 24 new
ones (`2983a16bb` folded into A01; `98a06be38`, `4cdc1527b` and `968b6502c` each
split into a non-VP and a VP half), and every step asserted both invariants:

- **Tree equality per step.** After each old commit's pair of new commits, the new
  tip's tree equals the old commit's tree. `git diff --quiet e9ccbffd7 0960d2908`
  (A24, before the fixups) is empty — the branch reproduces today's tree byte for byte.
- **Purity per commit.** Each of the 24 commits touches either only
  `virtual_platform/**` or nothing under it — never both, never nothing.
  16 are non-VP and 8 are VP (A05, A07, A09, A13, A15, A18, A23, A24). With
  A25–A27 that makes 19 non-VP commits, 18 of which go to main (A27 was added
  after the cherry-picks and is applied separately, below).
- Author name/email/date copied from each old commit (all Calvin McCoy);
  committer is the executing session. A19 (`059e70c25`) kept its message verbatim.
- The backup branch still points at `e9ccbffd7`; `git submodule status` is
  unchanged (`tt-oca-manifest` `171e02fa`, `tt-oca-harness-model` `416200e9`);
  the working tree was never touched by the rewrite.

Script and message files: `$CLAUDE_JOB_DIR/tmp/rewrite/` (`rewrite.sh`,
`write_msgs.sh`, `msgs/`, `map.txt`).

**Trailer.** The plan called for `Co-Authored-By: Claude Fable 5.1`; the session that
executed it was Opus 5 (1M context), so that is what the new messages carry — matching
the one pre-existing trailer in the series (on `059e70c25`). The `rom/sep: Let the
manifest packer run without uv…` pre-commit on the merge branch keeps
`Claude Fable 5`, the session that wrote the code it slices.

### Part A fixups — and a third commit the plan did not foresee

A25 and A26 landed as planned, but three checks the plan had not enumerated turned
out to gate or comment on a PR, so A25/A26 grew and a third commit was needed.

**A25 `doc/sep: Anchor the doc checks on the repo root and make them lint-clean`.**
The five hardcoded `/localdev/cmccoy/dev/tt-oca-harness` roots now derive from
`__file__` the way `check_reg_addresses.py` already did. Beyond the plan: CI's
`lint-python` job runs **two** gates, `ruff check` *and* `ruff format --check`
(`make ocah-format-python-check`), and all six scripts failed the formatter. The
commit therefore also expands the one-statement-per-line style across all six
(not just `check_tables.py`/`check_xrefs.py`), renames the ambiguous `l`, drops the
unused `sys` import, removes a dead `for … : pass` loop and a walrus that bound a
flags constant nothing read, and runs `ruff format`. Verified behaviour-preserving:
the five path-independent scripts print byte-identical output before and after,
and `check_reg_addresses.py` still reports RDL, header and docs in agreement.

**A26 `sep: Fix stale comments and import order flagged by review and ruff`.**
As planned (Makefile "Off by default" comment, the `virtual_platform/Makefile`
mention in `rom.adoc` and `gen_status_table.py`, import order in the three OCA
cocotb tests, the unused `cocotb` import in `sep_esrc_noise.py`), plus one change
the plan excluded: **`pyproject.toml`'s ruff `extend-exclude` still named
`tools/tt-boot-manifest`**, a path A22 deleted. That dropped 45 vendored producer
and validator sources under `tools/tt-oca-manifest` into both ruff gates —
invisible in CI, which does not check the submodule out, but not to a local
`make ocah-lint-python`. Repointing the exclude is a one-line change and is the
only reason `ruff format --check` over `tools scripts hw .github` is clean on the
merge branch (`45 files would be reformatted` if you check that tree directly).

**A27 `sep: Add the missing SPDX headers and clean up the new sources` (new).**
`.github/workflows/spdx.yml` runs espressif's `check-copyright` on every push and
pull request and **gates on it**. It requires both `SPDX-License-Identifier` and
`SPDX-FileCopyrightText`; a licence line alone is not enough. Fourteen files this
branch adds failed it — the four OCA C/H sources (licence line only), the six
doc-check scripts and `gen_status_table.py` (nothing), and the three OCA cocotb
tests (missing the copyright line). Reproduced locally with the action's own
`merge_config.py` plus `check-copyright --dry-run`; after the commit the probe
reports `Successfully processed 94 files`. The packer configs (`.yaml`), the test
signing keys (`.pem`) and the generated `gen/status_values.adoc` are types the
checker skips. The same commit strips the 13 trailing-whitespace lines the branch
introduced (`git diff --check` is clean again, so the repo's pre-commit whitespace
hook accepts the tree) and fixes three comment defects: `implments`, a run-together
`kdf_inputand`, and `a intialization` plus two sentences missing full stops.
Headers, comments and whitespace only — no statement of code is touched.

*Caution when reproducing the SPDX probe:* `check-copyright` rewrites files that
lack a trailing newline **even under `--dry-run`**. Running it over `.` touched three
files in the `tt-oca-manifest` submodule and three in the `nonfree` companion
checkout (adding a final newline); all six were reverted. Pass an explicit file list
and check `git status` afterwards.

### Part B — the main-bound branch

`origin/main` had moved further than the plan recorded: 74 commits past the
merge-base `99bb553c2` (the plan said 57), tip `c44999f9d`. The extra commits
brought two more shared files into the overlap (`cpu.adoc`,
`lifecycle_controller.adoc`), both only touched by
`treewide: Fix the pre-rebrand OCH acronym to OCAH … (#1517)`.

**Makefile pre-commits.** `origin/main`'s `bootrom/prod/Makefile` was still exactly
`fc138d10b^`'s blob (`2ff015c3`), as predicted. Three commits bring it to the
feature branch's `75c763e2`:

1. `fc138d10b` cherry-picked whole (it only touches that Makefile), message kept.
2. `3fbf72e14` + `faa9dbff3` Makefile slices as one commit, authored to Calvin,
   new subject `rom/sep: Let the manifest packer run without uv when its deps are
   importable`. (`faa9dbff3`'s half of that slice is only the
   `ocah-vp-toolchain` -> `ocah-toolchain` rename in two comments.)
3. `b0851d802` Makefile slice, committed with `-C b0851d802` so Daniel Green keeps
   authorship and his message; its `virtual_platform/` and `hw/ip/key_manager`
   hunks are dropped.

The three patches touch disjoint regions, so applying them in this order rather
than chronologically still lands on `75c763e2` — asserted before continuing.

**Cherry-picks.** All 18 applied; three conflicted, each resolved as the plan
anticipated:

- **A03** — `UD` on `manifest.h` and `manifest_load.c`: main had edited both, ours
  deletes them. Main's edit was the OCH -> OCAH prose rename and nothing else, so
  the deletions were taken.
- **A14** — same shape on `non_secure_boot_test.yaml` and `secure_boot_test.yaml`;
  same rename, deletions taken.
- **A16** — `.gitignore`, a whole-tail conflict because main's file has no trailing
  newline. Resolved to main's content plus the `doc_render/` stanza only; the
  VP-motivated `och_sep_ss.log` stanza was deliberately not carried across.
- **A22** — `.gitmodules`, resolved to the single `tt-oca-manifest` stanza. The
  gitlink delete/add themselves were clean, as were the three tt-boot-manifest pin
  bumps (main's pin is the first bump's parent).

Nothing else conflicted.

**Content check.** Of the 102 non-VP files the cleaned branch touches, 93 are
byte-identical between the cleaned feature branch (at A26) and the merge branch.
The nine that differ do so only by main's own changes, verified by comparing the
two diffs line for line:

| File | Why it differs |
|---|---|
| `hw/sys/sep/doc/cpu.adoc` | main's OCH -> OCAH rename — **identical** to main's own hunk |
| `hw/sys/sep/doc/crypto.adoc` | main's AXI4/fabric rewrite — **identical** |
| `hw/sys/sep/doc/lifecycle_controller.adoc` | OCH -> OCAH — **identical** |
| `hw/sys/sep/doc/memory_map.adoc` | OCH -> OCAH — **identical** |
| `hw/sys/sep/dv/docs/SEP_TB_ARCH.adoc` | main's own edits — **identical** |
| `hw/sys/sep/dv/tb/tb_top.sv` | main's crypto AXI-isolation work — **identical** |
| `pyproject.toml` | main keeps the mypy/codespell config and the deps the VP series removed — **identical** to main's own hunk apart from the A26 exclude rename |
| `.gitmodules` | no `tt-oca-harness-model` stanza, by design |
| `.gitignore` | main's `/nonfree` rewording, and no `och_sep_ss.log` stanza, by design |

`git diff --name-only origin/main HEAD` touches **only** `hw/sys/**` (99 files),
`.gitignore`, `.gitmodules` and the one `pyproject.toml` line. Nothing under
`virtual_platform/`, `tools/docker/`, `scripts/`, `.github/`, `ocah.mk`, `uv.lock`,
`AGENTS.md`, `hw/common/dv/fw/compile.mk` or `hw/ip/key_manager/`.

**VP references left in the SEP tree** (five, all comments/docstrings, harmless):

```
hw/sys/sep/bootrom/prod/configs/oca_encrypted_boot_test.yaml:4
hw/sys/sep/bootrom/prod/configs/oca_aes128_boot_test.yaml:4
hw/sys/sep/bootrom/prod/configs/oca_otp_key_boot_test.yaml:17
hw/sys/sep/dv/cocotb/tests/cpu/sep_rom_oca_encrypted_boot_test.py:37
hw/sys/sep/dv/cocotb/tests/cpu/sep_rom_oca_otp_key_boot_test.py:27
```

The first two name `virtual_platform/tests/fuse_maps/oca_class_key.yaml`, which does
not exist on either branch — the map is `oca_encrypted.yaml`. Listed as a follow-up
rather than fixed, since the plan keeps VP mentions as they are.

No `tt-boot-manifest` or `TT_BOOT_MANIFEST_DIR` reference survives outside the VP
files that stay behind.

### Part B verification results

| Check | Result |
|---|---|
| `ruff check` over `tools scripts hw .github` (pinned 0.16.5) | clean |
| `ruff format --check` over the same | clean, 1211 files |
| SPDX (`check-copyright` with `.github/spdx_ignore.yaml`) | clean after A27 — `Successfully processed 94 files` |
| `git diff --check origin/main HEAD` | clean |
| ROM build, 3 variants + `oca-images` | exit 0; **39680 / 42328 / 41504 B** of a 64 KiB budget; 18 SPI preloads |
| ROM build warnings | none from ROM C sources (6 pre-existing: OTBN `_start`, `bl1_pass_test` RWX LOAD) |
| Doc checks, run from `cwd=/tmp` | 6/6 exit 0; the four gate-worthy ones substantively clean |
| `asciidoctor rom.adoc` | 0 warnings, 406 KB HTML |
| codespell (report-only) | 2 left: a `.pem` base64 false positive and `unparseable` |
| clang-format (report-only) | **263 violations** in branch-touched files vs 1 in untouched — see follow-ups |
| ROM DV under VCS | **7 of 7 PASS** on `origin/main` `20db9df9e`, no workaround |

### The DV blocker: `sep_rom_ot_secure_boot_test`

| Test | Status | Elapsed | `SyncReqAckDataHold` |
|---|---|---|---|
| `sep_rom_non_secure_boot_test` | PASS | 516 s | 0 |
| `sep_rom_ot_dma_boot_test` | PASS | 580 s | 0 |
| `sep_rom_ot_pio_boot_test` | PASS | 747 s | 0 |
| `sep_rom_ot_secure_boot_test` | **stalled, killed at 85 min** | — | 0 |
| `sep_rom_oca_encrypted_boot_test` | not reached | — | — |
| `sep_rom_oca_otp_key_boot_test` | not reached | — | — |
| `sep_rom_oca_tamper_test` | not reached | — | — |

The three tests that do no asymmetric crypto pass. The first one that does stalls, and
it stalls at a very specific place:

```
5590450.00ns  ROM> PUBK_AUTHORIZED
5614770.00ns  boot progress cyc=350000 retired=62350 pcs=3176 last_pc=0x100478a4
              <nothing further for 65 minutes; simv at 99% CPU; log file byte-frozen>
```

`PUBK_AUTHORIZED` is printed immediately before `plat_verify_signature()`, which is the
first call site of `ENTROPY_PREREQ()` — `plat_sha256()` deliberately does not confirm
entropy. So the stall begins exactly where the ROM's in-ROM entropy bring-up first runs.

The known-good comparison is `20260901_183341__vcs__sep_rom_ot_secure_boot_test` in the
main checkout: same test, same marker at 5590418 ns and `cyc=350000` at 5614770 ns — then
it carried straight on through `RSA_EXEC` (10843202 ns) and `RSA_VERIFY_OK` (15518594 ns)
to completion at cycle 1128384, **1439 s wall, 12555 ns/s**. Our run matched it to within
32 ns and then produced nothing for 65 minutes: a slowdown of at least 56x, or a frozen
simulation. From outside the two are indistinguishable, because `simv` burns 99% CPU either
way and the cocotb progress line only prints every 50000 cycles.

Two things make this worth taking seriously rather than waiting out:

- **The baseline is a valid control: it already had the in-ROM bring-up.** The commit
  `4b59a4437` is dated 2026-09-02 and the run dir 2026-09-01, which at first looked like
  the baseline predated the work — it does not. The 09-01 run's `boot_rom.vmem` is
  byte-identical to both of today's (md5 `be3c850d36e4`), carries the same five entropy
  symbols, drives the same `sep_esrc_noise.py` decorrelator noise, and printed
  `ROM> ENTROPY_OK` at 7869570 ns. The bring-up was in the working tree before it was
  committed. So A17's "All seven ROM tests pass with the real handshakes" *is* backed by
  local evidence, and the same ROM that passes on the pre-main-uprev RTL is the one that
  stalls now.
- **main has moved under the entropy source.** Between the merge-base and `c44999f9d`:
  `hw/entropy_source: Route the post-BIW health-test count_err into es_cntr_err (#1512)`,
  `hw/entropy_source: Reuse shared primitive cells (#1526)` and
  `hw/sys/sep: Add AXI isolation and reset sequencing for SEP crypto modules (#1253)`.
  The plan flagged exactly this combination as never having been exercised together.

The ROM cannot spin forever — `sep_entropy.c`'s waits are bounded
(`SEP_ENTROPY_SEED_TIMEOUT` 2,000,000 and `SEP_ENTROPY_CMD_TIMEOUT` 1,000,000 iterations)
and would print `ESRC_BOOT_PHASE_TIMEOUT=` or `EDN_INSTANTIATE_TIMEOUT=`. But at the
baseline rate of ~785 cycles/s, 2M poll iterations is on the order of seven hours, so a
hardware hang would not self-report inside a usable window either.

**Isolation run.** To separate "main's RTL changes" from "the entropy bring-up itself", the
same test is running against the cleaned feature branch's tree (`f14dcbbc4`, detached, in
`../tt-oca-harness-isolate`), which has the bring-up but none of main's entropy-source or
crypto-AXI work. Only `scripts/docker-run.sh` is taken from `origin/main` there, because the
feature branch's copy probes the extracted rootfs for a `g++` that neither rootfs on this box
has, so `c_compile` cannot otherwise run. Result recorded below.

### A27 on the merge branch

`f14dcbbc4` cherry-picked cleanly; merge branch tip is now **`6de88ea9d`, 22 commits on
`origin/main`**. Re-verified afterwards:

- SPDX probe over the 94 changed files: `Successfully processed 94 files`.
- `git diff --check origin/main HEAD`: clean.
- `ruff check` and `ruff format --check` over `tools scripts hw .github`: clean.
- Content check unchanged at 93 of 102 non-VP files byte-identical, the same nine
  differing only by main's own hunks.
- **`make clean` + full rebuild of all three ROM variants: `boot_rom.vmem` byte-identical
  to the pre-A27 build in every one** (39680 / 42328 / 41504 B). A27 is provably
  comment-, header- and whitespace-only, so the three DV passes recorded above describe
  exactly this binary.

### Root cause: `#1526` turned the entropy ring oscillator into a zero-delay loop

The isolation run settles it. Same ROM binary (`boot_rom.vmem` md5 `be3c850d36e4` in all
three runs, and identical `oca_secure_boot.bin` / `oca_smc_mem.hex`), different RTL:

| Marker | baseline 09-01 | isolation (feature tree, today) | merge branch (main's RTL) |
|---|---|---|---|
| `PUBK_AUTHORIZED` | 5590418 ns | 5590418 ns | 5590450 ns |
| `cyc=400000` | 6414770 ns, retired=71094 | 6414770 ns, retired=71094 | never reached |
| `ROM> ENTROPY_OK` | 7869570 ns | 7869570 ns | never reached |
| `ROM> RSA_EXEC` | 10843202 ns | 10843202 ns | never reached |
| `ROM> RSA_VERIFY_OK` | 15518594 ns | 15518962 ns (+368) | never reached |
| completion | cycle 1128384 | cycle 1128407 | never reached |
| verdict | PASS (1439 s) | **PASS** (1738 s) | killed at 85 min |

The isolation run reproduces the passing baseline exactly through `RSA_EXEC` and passes.
The small tail drift (+368 ns, 23 cycles) is OTBN reseeding URND off EDN, whose timing
depends on the entropy chain's state; it is not a behavioural difference. **The branch is
not at fault; main's RTL is.**

The mechanism, from the elaboration logs of both runs:

1. The SEP ROM boot tests elaborate the **real** `hw/ip/entropy_source/rtl/entropy_ring_oscillator.sv`.
   `sep_sim_cfg.toml`'s `[build].stubs` lists `hw/sys/sep/dv/shims/analog/entropy_ring_oscillator.sv`,
   but neither that shim nor `shims/prim/prim_sync2.sv` is parsed in either run — the only
   shim VCS parses is `abr_wrapper_key_reg_stub.sv`. The `[build].stubs` overrides are inert
   for the `rom_boot` target. (Latent, and harmless while the cells had delays.)
2. Before `cb9ff2f5b` (`hw/entropy_source: Reuse shared primitive cells (#1526)`), that
   module's ring was built from `hw/ip/entropy_source/rtl/gcells.sv`, whose cells each carry
   a transport delay: `assign #1 z_o = ...` in `gbuff`, `gnand2` and `gmux2`. The ring
   oscillates with a finite period — slow to simulate, but it simulates.
3. `#1526` deleted `gcells.sv` and rebound the ring to the canonical primitives
   `prim_clock_nand2`, `prim_stdbuf` and `prim_stdmux2`. All three are plain zero-delay
   continuous assignments (`assign o_Y = i_A;` and friends) in
   `hw/common/och_prim_generic/rtl/`.
4. A ring of zero-delay assignments is a **zero-delay combinational loop**. While
   `enable_i` is low the NAND breaks it. The instant the ROM's entropy bring-up asserts it,
   VCS iterates the loop forever inside one timestep: simulated time stops, the process
   pegs a core, and the cocotb log goes silent — which is exactly the observed signature,
   at exactly the observed moment.

`gcells.sv` is present in the isolation run's `bender.f` (line 776) and absent from the
merge branch's, which is the whole difference.

`#1526` merged 2026-09-04 09:39 PDT, hours before this work. It will wedge **any** SEP
simulation that enables the entropy ring oscillators, not just this branch — this branch is
simply the first thing that turns them on. Worth checking whether the `entropy_source`
block-level TB (`dv/tb/tb_ring_oscillator.v`, which instantiates the same module through
`entropy_noise_source`) is affected too, and whether it runs in CI at all.

**Two independent fixes, and they belong to different owners:**

- **main / `#1526`'s author (the real fix).** Give the ring's cells a simulation delay
  again — either restore `#1` to the `prim_*` wrappers under a simulation guard, or give
  `entropy_ring_oscillator` its own delay-bearing path. Without this, the entropy source
  cannot be simulated at all.
- **This branch (optional workaround).** Make `[build].stubs` actually reach the `rom_boot`
  target so `shims/analog/entropy_ring_oscillator.sv` shadows the real module. The shim
  exists precisely for this ("event-driven simulation can spend unbounded time scheduling
  that analog oscillation"), the ROM tests already drive the decorrelator input explicitly
  with `+esrc_noise_force`, and the baseline shows the RO's output is not otherwise needed.
  This would also make the tests substantially faster. It masks a genuine main bug, though,
  so it should not go in without the main-side fix being raised first — **left for the user
  to decide; not done.**

**DV status as it stands:** 3 of 7 pass on the merge branch; the remaining four cannot run
until one of the two fixes lands. All seven passed on the pre-`#1526` RTL, and the
isolation run re-confirms that with today's exact ROM.

### Follow-ups (not done, in priority order)

1. ~~Raise `#1526` with the entropy-source owners.~~ **Done and fixed** — filed, and
   resolved on main by `20db9df9e` (`hw/entropy_source: Restore ring oscillator simulation
   delay (#1559)`). Nothing outstanding.
2. ~~`[build].stubs` is inert for the `rom_boot` target.~~ **Withdrawn — this was a
   misdiagnosis on my part, and there is no defect.** Both stubs are Verilator-targeted by
   design: `shims/prim/prim_sync2.sv` remaps ports that only the public Verilator primitive
   library exposes differently ("Compatibility OVERRIDE stub ... during public Verilator
   builds"), and `shims/analog/entropy_ring_oscillator.sv` supplies a defined idle value
   under Verilator, which ignores the `#1` stage delays the ring needs to oscillate. Under
   VCS the real modules elaborate and simulate correctly, so the runner's rule -- drop any
   stub whose basename is still in the bender filelist, because a stub that has lagged the
   real port list would bind silently and fail elaboration -- is doing the right thing.
   Forcing these to bind under VCS would *lower* fidelity, swapping a working synchronizer
   and a working oscillator for stand-ins. What was actually wrong is the `[build].stubs`
   comment, which stated the Verilator-only placement as if it were universal; that is what
   sent me down this path, and it is fixed by `dv/sep: Say which simulator the SEP stubs
   actually override`.
3. ~~`clang-format` on the new ROM sources.~~ **Done** — see the clang-format section below.
4. **Stale VP fuse-map name.** `oca_encrypted_boot_test.yaml:4` and
   `oca_aes128_boot_test.yaml:4` name
   `virtual_platform/tests/fuse_maps/oca_class_key.yaml`; the map is `oca_encrypted.yaml`.
   One-line comment fix, belongs on both branches.
5. **codespell noise** (report-only): `tests/signing_keys/*.pem:24 oNd ==> one, and` is a
   base64 false positive — add `*.pem` to `[tool.codespell] skip` in main's
   `pyproject.toml`. `rom.adoc:2654 unparseable ==> unparsable` is a dictionary
   preference. Neither can be fixed identically on both branches: the VP-portability
   series removed the whole `[tool.codespell]` section from the feature branch's
   `pyproject.toml`.
6. **`.github/spdx_ignore.yaml` ignores `build/` but not `build_ot/` or `build_ot_pio/`.**
   Harmless in CI, which never builds, but a local `check-copyright .` after a ROM build
   flags the generated `bl0_version.h` in both.
7. ~~`sep_sim_cfg.toml` `[c_build.boot_rom_ot]` guards only two of the four OCA images the
   DV suite loads.~~ **Done** — `ad958e10d` / `9e26e57f3`; see the section below.
   (Restated 2026-09-05; the earlier "two of 13" was wrong on both counts.)
   `outputs` is the contract that makes `--stage sim` fail with "firmware outputs missing"
   rather than simulate a stale or absent image. `oca-images` packs **17** images into the
   shared `build/`, but DV loads only four of them: `oca_non_secure_boot.bin` and
   `oca_secure_boot.bin` (both declared), plus **`oca_encrypted_boot.bin` and
   `oca_otp_key_boot.bin`, which are not** — so a silent packer failure or a stale artifact
   for either would slip past the stage check into
   `sep_rom_oca_encrypted_boot_test` / `sep_rom_oca_otp_key_boot_test`.
   `[c_build.boot_rom]` and `[c_build.boot_rom_ot_pio]` declare no OCA `.bin` at all, though
   both also run `oca-images`.
   The fix is two lines, not thirteen: the other 13 images have zero references under
   `hw/sys/sep/dv` and are consumed only by the VP suite (`aes128`, `sip_key`, `identity`,
   `pqc`, `ecdsa`, `der`, `multi_image`, `no_bl1`, and `rom_key1-5` via
   `paths.OCA_ROM_KEY_IMAGES`), so declaring them on the main-bound branch would add noise,
   not safety.
8. Stale wording: the bootrom Makefile `$(OCA_BINS)` guard and `rom_fw.toml` still say
   "dev0 key" after the `rom_key0-5` rename.
9. **`tt-boot-manifest` `54c7cf37`** (the pin commits A03-A07 carry) is on no branch or tag
   in that repo. `git fetch origin 54c7cf37a3b039c085228aafbad546ca9c88e6b0` still serves
   it, and `d17b8fa3`/`f2929195` are both ancestors of its `main`, so bisecting works
   today — but a remote GC would break A03-A07. The branch tip and the squash-merged
   result reference `tt-oca-manifest` only, so this affects per-commit review, not the merge.
10. Stale worktree `.claude/worktrees/doc-open-questions` (branch `inmcm/doc-open-questions`,
    15 commits on the old base). PR #1028 (`feature/sep_virtual_platform` -> main, WIP) is
    the eventual VP landing.
11. `scripts/docker-run.sh` fixes (`9bd282114`) and the `compile.mk` prefix acceptance are
    real but VP-adjacent; they deserve their own small PR to main. Related: the feature
    branch's `docker-run.sh` probes an extracted rootfs for `usr/bin/g++`, which neither
    rootfs on this box has, so ROM builds and DV `c_compile` fail there until that probe is
    relaxed to what the requested build actually needs.

### Hand-off — nothing was pushed

Both branches are local.

```bash
# 1. main-bound: ROM + DV + docs, no virtual platform  (22 commits)
cd /localdev/cmccoy/dev/tt-oca-harness-main
git push -u origin inmcm/sep_rom_oca_manifest
gh pr create --draft --base main --head inmcm/sep_rom_oca_manifest \
  --title 'rom/sep: Boot from the OCA manifest, bring up entropy in ROM, publish the ROM spec'

# 2. feature-branch-bound: the same work plus the virtual platform  (27 commits)
cd /localdev/cmccoy/dev/tt-oca-harness
git push -u origin inmcm/integrate_oca_boot_manifest_clean
gh pr create --draft --base feature/sep_virtual_platform \
  --head inmcm/integrate_oca_boot_manifest_clean \
  --title 'sep: OCA manifest boot, in-ROM entropy bring-up, ROM specification, and VP coverage'
```

`inmcm/integrate_oca_boot_manifest` is the backup and should stay local until both PRs land.

Scratch worktrees, when finished with (the submodule was cloned into
`.git/worktrees/<id>/modules/`, so `--force` is needed):

```bash
cd /localdev/cmccoy/dev/tt-oca-harness
git worktree remove --force ../tt-oca-harness-main      # only after the main PR lands
```

`../tt-oca-harness-isolate` was the diagnostic worktree for the entropy stall; it has been
removed now that the fix has landed and been verified.

---

### PR body draft — `inmcm/sep_rom_oca_manifest` -> `main`

**Title:** `rom/sep: Boot from the OCA manifest, bring up entropy in ROM, publish the ROM spec`

---

The SEP boot ROM stops parsing the Grendel manifest format and boots through the
OCA validation library instead; it brings the entropy chain up itself rather than
relying on a DV shortcut; and the ROM finally has a written specification in the
TRM, with mechanical checks that keep it honest. The manifest tooling moves from
the `tt-boot-manifest` submodule to `tt-oca-manifest`.

The 22 commits are ordered so each one is reviewable on its own: three Makefile
pre-commits, then the 19 ROM/DV/doc commits. `main` squash-merges, so the squash
body is the concatenation of the commit messages. Verification below is of the
branch tip; individual commits were not built.

#### ROM

- The Grendel parser (`manifest_load.c`, `manifest_crypto.c`) is gone. `oca_boot.c`
  drives the library's staged sequence — peek, copy to SEP SRAM, validate, resolve
  encryption, locate and copy payload, check in place — and always authenticates the
  SRAM copy, never the storage medium. Library verdicts are reported verbatim as
  `0x000300xx`, so a console log names the exact rejection.
- `oca_platform.c` is the platform callback table: a thin adapter over `sha256()`,
  `rsa_3072_verify()`, `lc_read_state()` and the eFuse shadow reads. Every `set_*`
  entry is NULL by design, so the ROM never burns fuses. `plat_verify_signature()`
  requires the key's public exponent to be exactly `0x00010001`, because the OTBN
  application is the fixed-F4 modexp and would otherwise silently verify an `e=3`
  key against 65537.
- Encrypted payloads boot: AES-256-CBC with the one-hot `KEY_LEN` encoding and all
  eight `KEY_SHARE0` words, constant-time PKCS#7 stripping, and the OCA/Key Manager
  192-byte KDF block. Two latent HMAC driver bugs that were unreachable until now
  are fixed — `CFG.key_length` was never set (every HMAC returned `0xFFFFFFFF`) and
  the key was packed little-endian into big-endian `KEY` registers.
- Key-slot numbering is corrected: `public_key_select_classic` and
  `CHIPLET_PUBK_REVOKE` share one numbering (bits 0-7 ROM classical, 8-15 ROM PQC,
  16+ OTP banks); the ROM had mapped bits 6-9 to the OTP banks, so authorization and
  revocation named different keys and the OTP anchor was unreachable.
- The six ROM root-key slots are renamed `rom_key0-5` and the test keys move out of
  the manifest submodule into `bootrom/prod/tests/signing_keys/`, one distinct RSA
  key per slot, so an off-by-one in slot resolution can no longer match a digest by
  accident.
- The ROM brings ESRC -> CSRNG -> EDN up itself (`sep_entropy.c`), lazily and
  idempotently from the two crypto callbacks, so an unsigned boot pays nothing. It
  replaces the DV `+sep_crypto_edn_force` grant, which bypassed the chain and
  violated the EDN req/ack data-hold protocol once assertions were enabled.
  `FIPS_LOCK` and `EXT_TRNG_SRC_SEL_LOCK` are applied with read-back verification
  and can each be deferred to BL1.

#### DV

- The four existing ROM boot tests are repointed at OCA images (they were feeding
  Grendel images to an OCA-only ROM and failing with `OCA_FAIL_MAGIC` on both
  slots). Simulation exposed a ROM bug the VP suite could not: `bl0_state.secure_boot`
  was never written after the boot-flow rewrite, so a verified boot printed
  `SBOOT_OFF` and told BL1 it was unverified.
- Three new tests: an AES-256-CBC encrypted payload keyed from `CLASS_KEY`, a
  signature anchored on `CHIPLET_PUBK_HASH0` instead of a ROM digest, and a tamper
  test with a byte flipped in the signed region of both slots. The scoreboard gains
  `expect_fw_pass`, because a refused boot still asserts `fw_done` through
  `rom_err_fail()`.
- Two more real bugs fell out: `aes_init()` had no call site (the AES engine sat in
  reset and `wait_idle()` burned its full timeout), and `+sep_crypto_edn_force`
  granted only OTBN's EDN clients while AES is client 0.

#### Docs

- `rom.adoc`: the SEP boot ROM specification — tagged `SEP-ROM-*` requirements, the
  security-check inventory, boot-stage to status-code traceability, and the
  implementation-status matrix. The status-code registry is generated in-repo from
  `status_values.h`, the header the ROM compiles against.
- `doc/checks/`: six scripts cross-referencing the spec against generated headers,
  the RDL and the manifest producer's constants. Each found a real defect — most
  importantly the eFuse address table, shifted four bytes by the `LOCKS_SPARE`
  insertion, so the documented `BL1_VERSION` address was `CHIPLET_PUBK_REVOKE`'s.

#### Deliberately not in this PR

The SEP virtual platform and everything that exists only to serve it: the whole of
`virtual_platform/`, the container consolidation under `tools/docker/`, the
`scripts/docker-run.sh` fixes, `hw/common/dv/fw/compile.mk` prefix handling, the
`ocah.mk` include, the `pyproject.toml` `vp` dependency group, `.github/workflows/vp.yml`
and the `AGENTS.md` VP text. Those land through PR #1028. Five comments and
docstrings under `hw/sys/sep/` still mention VP fuse-map paths; they are harmless
and become accurate when the VP lands.

The three commits at the base of this branch bring `bootrom/prod/Makefile` up to the
state the ROM work was developed against — header dependency tracking, a uv-less
packer fallback, and a portable `SHELL`. They are slices of VP-series commits that
have not reached `main` yet; taking only the boot-ROM hunks keeps the later commits
conflict-free.

#### Reviewer notes

- **`make clean` once** in `hw/sys/sep/bootrom/prod` after the submodule swap: the
  generated `.d` files still name `tools/tt-boot-manifest`.
- `git submodule update --init hw/sys/sep/bootrom/prod/tools/tt-oca-manifest` is
  needed to build the images.
- The ROM DV tests are not run by CI — the PR gate runs `items: smoke` for SEP and the
  nightly/weekly regression tiers run `items: no_cpu`, none of which exercise the ROM — so
  local VCS runs are the only evidence. **All seven pass** against `origin/main`
  `20db9df9e` (515-1858 s each, zero `SyncReqAckDataHold` hits).
- **Checking out an intermediate commit** between the OCA library link and the
  submodule switch needs `tt-boot-manifest` at `54c7cf37`, which is on no branch or
  tag in that repo. `git fetch origin 54c7cf37a3b039c085228aafbad546ca9c88e6b0`
  still serves it, but a remote GC would not. The branch tip does not reference
  `tt-boot-manifest` at all, so the squash-merged result is unaffected.

### Status of the entropy blocker (RESOLVED — kept for the record)

The bug report (`ENTROPY_RO_BUG_REPORT.md`) has been filed against the entropy source and a
fix PR is in flight. Until it merges, the ROM DV suite runs on the merge branch only because
of the shim workaround.

**When the fix lands on main, the workaround should be removed.** It is the tip commit of
both branches, so it drops cleanly:

| Branch | Workaround commit |
|---|---|
| `inmcm/integrate_oca_boot_manifest_clean` | `5753379c7` (tip; branch goes 28 -> 27 commits) |
| `inmcm/sep_rom_oca_manifest` | `6dcba0f46` (tip; branch goes 23 -> 22 commits) |

Removal procedure:

1. `git fetch origin` and rebase/verify the merge branch onto the new `origin/main`.
2. Drop the workaround on both branches (`git reset --hard HEAD~1` while it is still the
   tip, or `git revert` if further commits have landed on top).
3. Confirm the real module is back in the bender flist and the shim is filtered out again:
   `grep -c "rtl/entropy_ring_oscillator.sv" hw/sys/sep/dv/build/sep_bender.f` should be 1,
   and `sep_dut_compile.f` should no longer list `shims/analog/entropy_ring_oscillator.sv`.
4. Re-run all seven ROM DV tests under VCS. They must pass **without** the shim; if any
   hangs between `ROM> PUBK_AUTHORIZED` and `ROM> ENTROPY_OK` again, the upstream fix is
   incomplete — say so rather than reinstating the workaround.
5. Delete `ENTROPY_RO_BUG_REPORT.md` and this section once both branches are clean.

If the fix has not merged by the time the PRs go up, the workaround commit stays and its
message already explains why; flag it in the PR description so a reviewer does not take it
for a permanent change.

### ROM DV: all seven pass with the workaround

Re-run on the merge branch at `6dcba0f46` (i.e. with `dv/sep: Bind the ring-oscillator
shim...`), 2026-09-04 16:31-19:01:

| Test | Status | Elapsed | `SyncReqAckDataHold` |
|---|---|---|---|
| `sep_rom_non_secure_boot_test` | PASS | 475.1 s | 0 |
| `sep_rom_ot_dma_boot_test` | PASS | 580.8 s | 0 |
| `sep_rom_ot_pio_boot_test` | PASS | 873.6 s | 0 |
| `sep_rom_ot_secure_boot_test` | PASS | 2098.6 s | 0 |
| `sep_rom_oca_encrypted_boot_test` | PASS | 1696.7 s | 0 |
| `sep_rom_oca_otp_key_boot_test` | PASS | 1513.0 s | 0 |
| `sep_rom_oca_tamper_test` | PASS | 1773.5 s | 0 |

**7/7, zero `SyncReqAckDataHold` hits.** The four tests that previously could not run — every
one that performs asymmetric crypto and therefore enables the entropy chain — now complete.
`sep_rom_ot_secure_boot_test`, which hung for 85 minutes and had to be killed, passes in
35 minutes.

This also confirms the diagnosis from the other side: with the ring oscillator shimmed out,
main's RTL runs the ROM's entropy bring-up correctly (`ROM> ENTROPY_OK` at 7869714 ns).
The ring was the only thing broken; nothing else in main's entropy-source or crypto-AXI work
is implicated.

Note on runtime: the crypto tests take 25-35 minutes against the ~24-minute pre-`#1526`
baseline. The shim removes an oscillator from the schedule, so they were expected to get
faster, not slower; these runs shared the machine with other work, so the comparison is not
clean. Not investigated — the tests complete and pass, which is what the gate needs.

---

## Resolution: the entropy fix landed, workaround removed, 7/7 green

`20db9df9e` — *hw/entropy_source: Restore ring oscillator simulation delay (#1559)* — landed
on main. It adds `entropy_ring_stage_wrappers.sv`: three wrappers private to entropy_source,
each around one unmodified `prim_*` instance, adding `assign #1 o_Y = y_cell;` under
`` `ifndef SYNTHESIS ``. Synthesis and every other `prim_clock_nand2` / `prim_stdbuf` /
`prim_stdmux2` consumer see the ordinary zero-delay cell; only the ring's own instances gain
the delay. It also adds `dv/tb/tb_ring_smoke.sv`, which requires oscillator edges to advance
simulated time — the regression that keeps this from recurring.

**Actions taken:**

- Dropped `dv/sep: Bind the ring-oscillator shim...` from both branches (it was the tip of
  each): feature branch 28 -> 27 commits (`f14dcbbc4`), merge branch 23 -> 22.
- Rebased the merge branch onto the new `origin/main` `20db9df9e`. All 22 commits replayed
  **with no conflicts**, including across `#1478` (SEP straps removal), the likeliest to
  collide. New tip `51a41b388`.
- `ENTROPY_RO_BUG_REPORT.md` deleted — filed and fixed.

**Re-verified on the rebased branch:**

- Flist back to the unshimmed state: real `entropy_ring_oscillator.sv` parsed (1), new
  `entropy_ring_stage_wrappers.sv` parsed (1), **zero** shim files, `gcells.sv` gone.
- Content check 91 of 102 non-VP files byte-identical to the feature branch; all 11 that
  differ — now including `sep_sim_cfg.toml` and `rom_fw.toml`, which main touched — carry
  only main's own hunks, verified line for line.
- `ruff check` and `ruff format --check` clean (1211 files); `git diff --check` clean;
  SPDX `Successfully processed 94 files`; ROM `c_compile` 19.7 s.
- Diff vs `origin/main` still touches only `hw/sys/**`, `.gitignore`, `.gitmodules` and the
  one `pyproject.toml` line.

**ROM DV, all seven, real ring oscillator, no workaround:**

| Test | Status | Elapsed | `SyncReqAckDataHold` |
|---|---|---|---|
| `sep_rom_non_secure_boot_test` | PASS | 514.7 s | 0 |
| `sep_rom_ot_dma_boot_test` | PASS | 639.9 s | 0 |
| `sep_rom_ot_pio_boot_test` | PASS | 825.0 s | 0 |
| `sep_rom_ot_secure_boot_test` | PASS | 1724.0 s | 0 |
| `sep_rom_oca_encrypted_boot_test` | PASS | 1857.6 s | 0 |
| `sep_rom_oca_otp_key_boot_test` | PASS | 1651.1 s | 0 |
| `sep_rom_oca_tamper_test` | PASS | 1849.8 s | 0 |

The secure-boot test now tracks the original pre-`#1526` baseline to well under a
microsecond (`PUBK_AUTHORIZED` 5589826 vs 5590418 ns, `ENTROPY_OK` 7869090 vs 7869570,
`RSA_EXEC` 10842722 vs 10843202, `RSA_VERIFY_OK` 15518482 vs 15518594, completion at cycle
1128371 vs 1128384), which is the entropy chain behaving exactly as it did before the
regression.

One earlier speculation is retired: removing the oscillator was expected to make the tests
faster, and it did not — the unshimmed run is *faster* (1724 s vs 2099 s for secure boot).
Machine load explains more of the variance than the shim ever did.

**Final state: both branches green on every gate, nothing pushed.**

---

## clang-format cleanup (2026-09-05)

`rom/sep: Format the new boot ROM sources with the tree's clang-format` —
`b18f6afec` on the feature branch (28 commits), `40ad781d1` on the merge branch
(23 commits).

**All 263 violations were ours.** Measured per file with
`git show origin/main:<f> | clang-format --assume-filename=<f> --dry-run --Werror`, so the
tree's `.clang-format` resolves for both sides: main's version of every one of these files
reports **0** violations. (An earlier measurement that piped main's copy through a temp
directory inflated the counts badly, because `-style=file` then resolved a different
config; `--assume-filename` is the right tool.)

| File | main | ours |
|---|---|---|
| `oca_platform.c` | 0 | 71 |
| `oca_boot.c` | 0 | 66 |
| `sep_entropy.c` | 0 | 32 |
| `key_digests.c` | 0 | 30 |
| `kdf.c` | 0 | 28 |
| `oca_boot.h` | 0 | 12 |
| `rom_handoff.c` | 0 | 10 |
| `aes_driver.c` | 0 | 7 |
| `kdf.h` | 0 | 3 |
| `hmac_sha256.c` | 0 | 2 |
| `boot_flash.h` | 0 | 2 |
| **total** | **0** | **263** |

**The generated file was fixed at the source.** `key_digests.c` is emitted by
`generate_key_digests.py`, so formatting the file alone would be reverted by the next run.
Two emitter changes make its output clang-format-clean instead: 16 digest bytes per line
rather than 8 (4 indent + 16 x `"0xXX, "` is 99 columns, inside the `ColumnLimit` of 100;
at 8 per line clang-format repacks the array), and table entries emitted as
`{.digest = X}, // slot N` rather than `{ .digest = X },  // slot N`. Regenerating now
reproduces the committed file byte-for-byte, and the 768-character digest byte sequence is
unchanged.

**Proof it changed nothing.** Two independent checks:

- Stripping all whitespace leaves every one of the eleven C/H files' token streams
  byte-identical to before the reformat.
- A `make clean` plus full rebuild of all three ROM variants produces `boot_rom.vmem`
  byte-identical to the pre-format build (39680 / 42328 / 41504 B, md5 `1744c799ec1f` /
  `d2847d617add` / `a5bbaa2f7ebb`), with no warnings from ROM sources.

Because the binary is identical and the RTL unchanged, the 7/7 DV results above carry over
unchanged; the suite was not re-run.

**Gates after the reformat, both branches:** clang-format 0 violations, `ruff check` and
`ruff format --check` clean, `git diff --check` clean, SPDX `Successfully processed 94
files`, six doc checks exit 0, content check still 91 of 102 files identical between
branches with the same eleven differing only by main's own hunks, and the diff against
`origin/main` still confined to `hw/sys/**` plus `.gitignore`, `.gitmodules` and the one
`pyproject.toml` line.

## Stubs follow-up: withdrawn, comment fixed instead (2026-09-05)

`dv/sep: Say which simulator the SEP stubs actually override` — `9efa3a9e0` on the feature
branch (29 commits), `bf26d92a5` on the merge branch (24 commits). Comment only.

Investigating follow-up #2 showed there was nothing to fix in the build: both
`[build].stubs` entries are Verilator-only by design and correctly inert under VCS. The
defect was the comment above them, which described the Verilator placement ("listed ahead of
the bender filelist so -Wno-MODDUP first definition wins selects them") as though it applied
to every tool. It now states the per-tool rule, says the two stubs are Verilator-only in
effect, and points at `exclude_files` as the way to bind one under VCS — which is what the
`abr_wrapper_key_reg` stub already does.

Verified after the change: the flist is untouched — the real `entropy_ring_oscillator.sv`
and `prim_sync2.sv` are both in `sep_bender.f`, and the only shim in the compile list is
`abr_wrapper_key_reg_stub.sv`, which comes from `[build].sources` and whose real counterpart
is excluded. `ruff` clean, `git diff --check` clean, content check still 91 of 102 identical.

Standing lesson, worth keeping: **the elaboration log, not the config file, settles which
definition a run used.** `grep "Parsing design file"` on `stages/hdl_compile/logs/` is the
authority.

## c_build outputs guard (2026-09-05)

`dv/sep: Guard the encrypted and OTP-key OCA images in the c_build outputs` —
`ad958e10d` on the feature branch (30 commits), `9e26e57f3` on the merge branch
(25 commits).

Added `oca_encrypted_boot.bin` and `oca_otp_key_boot.bin` to
`[c_build.boot_rom_ot].outputs`, bringing the guard to all four OCA images the ROM tests
load. The other thirteen `oca-images` products stay undeclared, with a note saying why: they
have no consumer under `hw/sys/sep/dv` and belong to the VP suite, so listing them would gate
the stage on artifacts none of its tests open.

**Verified by making the guard fail.** Same command, same deleted image, config before and
after the commit:

| | result |
|---|---|
| before (`HEAD~1` config) | no missing-outputs error; sim stage started and ran 5.9 s before failing inside the simulation |
| after | `error firmware outputs missing for 'sep_rom_oca_encrypted_boot_test'; run c_compile first: .../build/oca_encrypted_boot.bin`, stage ERROR in **0.2 s** |

With the image restored the stage passes again and the simulation launches normally.
`outputs` is checked rather than produced, so no build or simulation behaviour changes and
the 7/7 DV results stand.

Two process notes from doing this, both my own errors, recorded so they are not repeated:
`pkill -f <pattern>` matches the very shell running it and kills the rest of the command —
including the cleanup lines after it, which left the config and a deleted image in place
until a follow-up check caught it. Use `pgrep` to collect PIDs and `kill` them by number.
And a `--stage sim` run that passes the guard launches a real ~30-minute simulation; cap it
or expect to kill it.

---

## Review fixups (2026-09-05)

Four commits from manual review, each on both branches.

| Commit | feature | merge |
|---|---|---|
| `rom/sep: Derive the manifest slot offsets from a stated slot size` | `3abef7188` | `2dd9d997c` |
| `dv/sep: Guard the encrypted and OTP-key OCA images in the c_build outputs` | `ad958e10d` | `9e26e57f3` |
| `rom/sep: Bounds-check every storage read before it is issued` | `322304170` | `5d113434a` |
| `treewide: Drop the Grendel and OCA-migration narrative from SEP sources` | `8f8c34d21` | `5adc5206f` |

**Slot geometry.** `BOOT_SLOT_SIZE` / `BOOT_SLOT_MANIFEST_OFFSET` now derive
`PRIMARY_MANIFEST_OFFSET` and `BACKUP_MANIFEST_OFFSET` (values unchanged: 0x1000, 0x41000).
Two `_Static_assert`s replace prose: a slot cannot exceed SEP SRAM, since the ROM stages
manifest+payload there, which is where the historical 0x40000 came from; and the manifest
must sit inside its own slot. Verified the assertion fires when the knob is pushed past SRAM.

**The dead security gate.** Investigating why the geometry change left the binary
byte-identical turned up that `boot_flash_bounds_ok()` **had no caller** — despite
`[SEP-ROM-SPI-010]` naming it and the boot-flow diagram placing it ahead of the read with
"disagreement => reject". A comment in `sep_ot_spi.c` even referred to "the caller's
boot_flash_bounds_ok". It is now called from `manifest_src_read()`, which every storage read
funnels through (peek, body, payload), so a fourth read cannot skip it.

What it adds is a bound on the read **source**. The destination was already checked by
`ot_spi_dst_valid()`, and the library bounds where the payload may be *located* — but the
region handed to the library is the whole flash on the OpenTitan path (`region_base` 0,
`region_limit` `SEP_SPI_MAX_SIZE`), so nothing confined a read to the slot being tried.
`payload_offset` lives in the manifest's unsigned tail and is attacker-controlled even on a
validly signed manifest, so that is the gap closed. Refusals report
`OCA_BOOT_ERR_READ_OUT_OF_BOUNDS` (0x00030106) and print `FLASH_READ_OOB`, distinct from a
transport failure. Checked all 17 packed images place manifest and payload inside their slot
window before running anything.

**Grendel sweep.** 14 sites across 11 files. Two were not merely stale but wrong: the DMA
boot test claimed the Grendel images "are still built for other consumers" (A14 deleted
those targets), and `rom_fw.toml` attributed enforcement to `secure_boot_enabled()`, a
function that went with the old loader. Left alone: `secure_boot_enabled` where it names a
live library field or SEP_MSG code, the `+sep_crypto_edn_force` note (that plusarg still
exists), and "legacy"/"replaces" wording predating this work.

### Verification

ROM binaries grew by the gate: 39816 / 42760 / 41936 B against 39680 / 42328 / 41504 before
(+136 Cadence, +432 OpenTitan), all well inside the 64 KiB budget, no warnings from ROM
sources. The growth is itself the evidence the gate is no longer dead code.

**ROM DV, all seven, run against the merge branch tip `5adc5206f`:**

| Test | Status | Elapsed | `SyncReqAckDataHold` | `FLASH_READ_OOB` |
|---|---|---|---|---|
| `sep_rom_non_secure_boot_test` | PASS | 422.2 s | 0 | 0 |
| `sep_rom_ot_dma_boot_test` | PASS | 566.3 s | 0 | 0 |
| `sep_rom_ot_pio_boot_test` | PASS | 711.8 s | 0 | 0 |
| `sep_rom_ot_secure_boot_test` | PASS | 1544.0 s | 0 | 0 |
| `sep_rom_oca_encrypted_boot_test` | PASS | 1620.5 s | 0 | 0 |
| `sep_rom_oca_otp_key_boot_test` | PASS | 1502.5 s | 0 | 0 |
| `sep_rom_oca_tamper_test` | PASS | 1671.7 s | 0 | 0 |

Zero `FLASH_READ_OOB` matters as much as the passes: the gate is live in the binary and
refused nothing, so every legitimate read clears it. The reads themselves are confirmed by
`OCA_BODY=0x00001000`, `MANIFEST_OK`, `PAYLOAD_OK` and `RSA_VERIFY_OK` in the log.

Cross-branch check after all four: 91 of 102 non-VP files identical, the same eleven
differing only by main's own hunks.
