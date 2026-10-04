<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SEP boot ROM testlist on the virtual platform

This directory holds the declarative SEP boot ROM testlist. Each testcase is a TOML entry. A
pytest adapter turns it into one `sep-vp` run on the OCA manifest ROM and judges the console
output, the `[SEP_STATUS]` stream, the SPI reads and the terminal verdict against the entry.
The boot images a testcase names are either prebuilt OCA images or images generated from a
small mutation spec.

The hand-written tests (`test_bootcode.py`, `test_bootcode_oca.py`,
`test_bootcode_oca_negative.py`, `test_bootcode_oca_rom_keys.py`, with `shared.py`) are
separate from the testlist and are not described here.

## Quick start

Run these from the repository root on a host with `uv`, CMake and g++ 10 or newer.

```bash
# 1. Fetch the model and tt-oca-manifest submodules
git submodule update --init --recursive

# 2. Build sep-vp; the first run also builds its SystemC, CCI, Boost and OpenSSL dependencies
make -C virtual_platform vp

# 3. Build the boot ROM and the OCA images (see Prerequisites for the toolchain choice)
make -C hw/sys/sep/bootrom/prod toolchain-images
make -C hw/sys/sep/bootrom/prod oca-images decrypt_negative_images

# 4. Create the manifest venv that repack specs use
PLAT=$(python3 -c 'import platform; libc, ver = platform.libc_ver(); p = tuple(int(x) for x in ver.split(".")[:2]) if ver else (0,0); m = platform.machine(); print("" if libc != "glibc" or p >= (2,34) else f"{m}-manylinux_2_28" if p >= (2,28) else f"{m}-manylinux_2_17")')
UV_PROJECT_ENVIRONMENT=$PWD/virtual_platform/local/manifest-venv \
  uv sync --project $PWD --locked --no-default-groups --group manifest ${PLAT:+--python-platform $PLAT}

# 5. Run one testcase, then the whole testlist
cd virtual_platform
uv --project .. run --group vp --locked python3 -m pytest \
  tests/bootcode/test_sep_rom_testlist.py --no-build -rA -k rom_ot_secure_boot_golden
uv --project .. run --group vp --locked python3 -m pytest \
  tests/bootcode/test_sep_rom_testlist.py --no-build -rA
```

Step 5 passes when pytest reports `1 passed` and
`logs/sepvp/rom_ot_secure_boot_golden/sep-vp.log` contains `[VP] SIMULATION OF THE TEST PASSED`.
If `make vp` stops at `check-cxx`, follow the compiler fix it prints. If step 3 prints
`absent locally and in cache; building`, stop it and read the toolchain note under Prerequisites.

## File map

| Path | Role |
|---|---|
| `testlist_loader.py` | Parses and validates the testlist into `RomTestCase`; owns `FAMILY_ORDER`, the allowed fields and every cross-field rule |
| `testlist_adapter.py` | Converts a `RomTestCase` into a `SimConfig`, builds the fuse map, resolves `{measurement_golden}`, runs the case and calls `sepvp.judges.judge` |
| `test_sep_rom_testlist.py` | The pytest entry point; one parametrized case per non-retired testcase |
| `boot_images.py` | Produces the image a testcase names (prebuilt, byte patch, ops or repack), runs `image_asserts`, cuts the SMC SRAM bytes, computes the measurement token |
| `boot_image_mutations.py` | Loads and validates mutation specs; applies byte patches; defines `SEPVP_TESTLIST_DIR` handling |
| `oca_image_ops.py` | Whitelist `OPS` of DV mutation helpers a spec may run, with the re-sign rules |
| `oca_repack.py` | Rebuilds an image from a packer config plus field edits, through the manifest venv |
| `oca_layout.py` | OCA manifest field offsets (`L.C.OFF_*`), loaded from the manifest submodule's constants |
| `dv_env.py` | Loads the SEP DV cocotb helper modules (`sep_payload_mutate`, `sep_manifest_mutate`) without importing cocotb |
| `boot_measurement_golden.py` | Computes the expected `BL0S_BOOT_PCR=` token from the boot-state record |
| `preloaded_test_programs.py`, `warm_handler_stub.S`, `warm_fault_stub.S`, `*_words.py`, `gen_warm_stub.py` | Executable stubs deposited through init writes before the run; `gen_warm_stub.py` regenerates the checked-in words from the `.S` sources |
| `untrusted_signing_key.py`, `keys/` | RSA-3072 signing key whose modulus digest is in no ROM key slot; generated with `openssl genrsa` on first use and git-ignored |
| `testlist_audit.py` | Flags entries that a healthy boot would also satisfy |
| `reference/oca_token_map.md` | Lookup table from legacy tokens and error codes to the OCA ROM; a reference, not a source of expected values |
| `testlist/<family>.toml` | One file per family; the file name must be in `FAMILY_ORDER` and every entry's `family` must equal it |
| `testlist/boot_image_mutations/<image>.toml` | One mutation spec per generated image; the file stem is the image name |
| `test_*.py` for the modules above | Host-only unit tests (`hostonly` marker) |

The family files load in `FAMILY_ORDER`. Every family in that list needs its `.toml`, and a
family `.toml` that is not in that list is an error.

## Testcase schema

A testcase is a `[[testcase]]` table in `testlist/<family>.toml`. An unknown field is an
error. Defaults are in parentheses.

Identity:

- `name`, `family`, `tp_id` (optional). `name` is unique across the whole testlist.
- `classification`: `vp-equivalent`, `partial`, `harness-blocked`, `model-blocked`,
  `rtl-only` or `retired`.
  - `harness-blocked`, `model-blocked` and `rtl-only` need a non-empty `Blocked:` entry in
    `markers`. The adapter skips the case with that text as the reason.
  - `retired` takes only `name`, `family`, `tp_id`, `classification`, `reason` and `markers`.
    It is not run. `reason` is required and is valid only on retired entries.
  - `partial` runs; use `markers` to state what the VP does not prove.
- `markers`: free-text limitations. `pytest_markers`: pytest markers to apply (for example
  `needs_debug`, which `--build-type=release` deselects).

Stimulus:

- `image`: a prebuilt image name (keys of `sepvp.paths.OCA_IMAGE_PATHS`) or a mutation spec
  name. Optional only for entries that need no flash image.
- `base_ini`: `secure` (`fuse_maps/prod_secure.yaml`) or `insecure` (`fuse_maps/test_dev.yaml`).
- `efuse`: fuse-map field overrides on top of `base_ini`; needs `base_ini`. A value is an
  integer, a symbolic name or an array of integers. The placeholder
  `"{untrusted_signing_key_digest}"` expands to the digest of the untrusted key as eight words.
- `boot`: `secondary` (default) or `primary`.
- `rotate_update` (false): reorders the SPI slot attempt; needs `boot = "primary"`.
- `recovery` (false): a primary chiplet waits for the SMC manifest instead of reading SPI;
  needs `boot = "primary"` and excludes `rotate_update`.
- `timeout` (120): seconds, positive.
- `preloaded_test_programs`: names from `PROGRAMS` (`warm_jump`, `warm_jump_relocated`,
  `warm_fault`).
- `init_writes`: `{ address, value }` words written before the first instruction. The address
  is 4-byte aligned and inside a window the model accepts; a write elsewhere is dropped by the
  model, so the loader limits targets to those windows. Cold scratch 0 holds the verdict and is
  excluded. A complete run fails unless the model reports every deposit, preloaded programs
  included.
- `smc_sram_image`, `smc_sram_source = [low, high]`, `smc_sram_offset`,
  `smc_sram_manifest_at`: stage bytes of a prebuilt image into the SMC SRAM window. The four
  fields come together. They need `observation = "complete"` and either `boot = "secondary"` or
  `recovery = true`. The source must be a prebuilt image, not a generated one. The harness
  checks that the staged bytes carry the OCA magic at `smc_sram_manifest_at` and that offset 0
  does not hide a valid manifest when `smc_sram_manifest_at` is not 0.

Judging:

- `observation`: `complete` (default; run to completion, then judge) or `streaming` (expect
  tokens in order while the run is live). `streaming` cannot use `expect_counts`,
  `terminal_token`, `expect_silence`, `expect_status`, `forbid_status`, `spi_reads` or
  `expect_verdict`.
- `expect`: console tokens in order. `forbid`: tokens that must not appear. A token cannot be in
  both.
- `expect_counts`: `{ token = n }` exact occurrence counts.
- `terminal_token`: the last console token.
- `expect_silence`: the forbidden tokens must stay absent. It excludes `expect`, needs `forbid`
  and needs a liveness stimulus (`preloaded_test_programs` or `init_writes`), so a dead run does
  not pass as silent.
- `expect_status`, `forbid_status`: `"SEVERITY 0xCODE"` entries matched against the decoded
  `[SEP_STATUS]` stream. A status cannot be in both.
- `expect_verdict`: `PASSED`, `FAILED` or `none`; required for a complete run. `none` requires
  that the firmware prints no verdict. A `FAILED` verdict from the firmware is an error unless
  the entry declares `FAILED`. Expecting the FAILED verdict token in `expect` requires `expect_verdict = "FAILED"`.
- `spi_reads`: spans `{ name, range = [low, high], exact | min | max }`. At least one count is
  required, names are unique and spans do not overlap. `spi_read_order` lists span names in the
  order of their first read and needs `spi_reads`.

Pre-run image checks (`image_asserts`, needs `image`). Each entry names exactly one mode:

- `{ range = [low, high|"end"], all = <byte> }`: every byte of the range equals the byte.
- `{ range = ..., same_as = "<image>" }`: the range is identical to the same range of a base
  image. Use it to prove that the mutation left a region alone.
- `{ range = ..., same_as = "<image>", xor = <byte> }`: every byte of the range is the base byte
  XOR the non-zero mask. Use it for a byte flip whose result depends on the base image.
- `{ range = ..., differs_from = "<image>" }`: the range differs. This is the negative control of
  `same_as`.
- `{ field = { name = "OFF_...", slot = "primary"|"backup", size = 1|2|4|8, value = <int> } }`:
  a manifest field, named by its `OFF_` symbol (not `OFF_TOC_`), holds the value. A field check
  has no `range`.
- `{ toc_field = { name = "OFF_TOC_ENTRY_...", slot, entry = <index>, size, value } }`: a field
  of a cleartext TOC entry holds the value. The offset is the slot's payload base plus
  `TOC_HEADER_SIZE + entry * TOC_ENTRY_SIZE` plus the field offset, all from the producer
  constants, so the check follows a change of the TOC layout. An encrypted payload, a payload
  without the `PTOC` magic or an entry past `image_count` fails the check. It has no `range`.

A byte patch or an op image can be compared only with the image it edited. A repack can be
compared with any prebuilt image.

Measurement golden:

- `measurement_golden = { slot, lc_state, demotion_decision, secure_boot, sboot_dis }` declares
  the boot state BL0 measures. All five keys are required. `lc_state` is at most 0xF,
  `demotion_decision` at most 0x7, `secure_boot` and `sboot_dis` at most 1.
- `{measurement_golden}` in `expect` or as an `expect_counts` key is replaced by
  `BL0S_BOOT_PCR=<hex>`, computed from the slot's manifest hash in the generated image and the
  declared scalars. The digest is never read from a run. The spec and the placeholder must be
  used together; the entry needs `observation = "complete"`.

Known failures:

- `xfail_reason` must cite a DV B-number (for example `"DV B7: ..."`). `xfail_match` is a
  required regex for the failure the sentinel expects, and it may not match an empty message.
  Verdict, forbidden-status and missing-status failures quote the console or status tail, so
  the regex can require the tokens of the slot the entry targets. The case is a strict xfail on
  `JudgeError`. A different judge failure fails the case, and an output-provenance failure
  fails it as unjudgeable. When the DUT is fixed the case XPASSes and strict mode turns that
  into a failure, which tells you to remove the sentinel. An xfail cannot combine with a
  blocked classification.

## Boot image spec schema

A spec is `testlist/boot_image_mutations/<image>.toml`. Its stem is the image name that a
testcase puts in `image`. It cannot reuse the name of a prebuilt image. It is exactly one of
three kinds. Every no-op edit is an error, so a spec cannot silently reproduce its base.

Byte patch: `base` plus `patch`. A patch edits the packed image and leaves the integrity fields
stale on purpose, so the ROM's integrity checks run. Each `patch` entry names one of:

- `{ fill = [low, high|"end"], value = <byte> }`
- `{ offset = <n>, value | xor = <byte> }`
- `{ offset = <n>, le = <int>, size = 1|2|4|8 }`
- `{ field = "OFF_...", slot = "primary"|"backup", value | xor | le (+ size) }`, an offset
  relative to the named manifest field in the slot. `OFF_TOC_` fields are refused because they
  are relative to the TOC.

Ops: `base` plus `ops = [{ op, slot, args = {...} }]`, then an optional `patch`. An op runs a
DV helper from `oca_image_ops.OPS` on one slot, in order. Rules:

- The op name must be in `OPS` and every argument must be one the op declares. Each op leaves
  the slot's manifest hash consistent, so the ROM reaches the field the op names. To break a
  seal on purpose, add a byte patch after the op.
- Payload ops (`set_toc_*`, `permute_toc_entries`, `set_payload_hashed_length`, `set_bl1_*`,
  `set_encryption_*`, `declare_payload_length`, `set_overlapping_payload_offset`) reseal the slot
  themselves.
- Manifest setters that only rehash (`set_demotion`, `set_lifecycle_states`,
  `set_security_version`, `set_public_key_sel`, `set_public_key_slots`, `set_manifest_version`,
  `set_manifest_length`, `set_signature_type`, `set_secure_boot_enforced`) are re-signed by the
  harness when the slot is signed, so the signature still verifies and the payload seals stay as
  the earlier ops left them. On an unsigned slot nothing is re-signed.
- `set_identity` and `set_lifecycle_constraint` reseal the whole slot, payload seals included.
  Such an op is refused after a payload op on the same slot; run it first.
- `clear_secure_boot` makes the slot validly unsigned. `graft_slot_from` (argument `image`)
  copies a slot from another prebuilt image with that image's own seals. It is refused after any
  op on the same slot; run it first.
- The layout is verified after every op.

Repack: `pack_config = "oca_<name>"` (the stem of `configs/oca_<name>_image.yaml` in the ROM
tree), `set` and optional `pin`, then an optional `patch`. The spec edits the packer inputs, so
hashes and signatures cover the change. A repack carries no `base` or `ops`.

- `set` and `pin` entries are `{ target = "image"|"bundle", slot, path, value }`. `bundle`
  needs `slot` of `primary`, `backup` or `both`; `image` takes no `slot`. `path` is a dotted
  path into the YAML config. A repack needs at least one `set`. A packer field cannot appear
  twice across `set` and `pin`. `combos.<n>.config` is owned by the repack.
- A `pin` does not edit. It asserts that the base config still holds `value`, so the spec fails
  loudly if the packer config drifts.
- Edits go through the ROM tree's `derive_pack_config.py`. It refuses a key the base config does
  not declare; use an op for such a field.
- The placeholders `{untrusted_signing_key}` (key file path) and
  `{untrusted_signing_key_name}` can be used as a `set` value. They select the key described in
  the file map.

Choosing a kind: use a byte patch outside the signed region, a repack for a field the packer
config declares, and an op for a field inside the signed region that the config does not
declare.

## Prerequisites

- The boot ROM ELF and the OCA images. Build them from the repository root:

  ```bash
  make -C hw/sys/sep/bootrom/prod toolchain-images
  make -C hw/sys/sep/bootrom/prod oca-images decrypt_negative_images
  ```

  With `RISCV_TOOLCHAIN` set to a host RISC-V toolchain that provides picolibc, the ROM builds on
  the host. Without it, `toolchain-images` compiles in the OCAH toolchain container through
  `scripts/docker-run.sh`, which builds the image from the Nix flake when none is loaded,
  pullable or cached. That build takes a long time; `scripts/docker.md` describes pulling the
  prebuilt image or using a bubblewrap rootfs instead.

  Without `--no-build`, the `oca_images` fixture builds the images itself. With `--no-build`,
  a missing image skips the cases that read it; the images in `paths.TESTLIST_ONLY_IMAGES` skip
  only testlist entries.
- The `tt-oca-manifest` submodule at `hw/sys/sep/bootrom/prod/tools/tt-oca-manifest`.
- The manifest venv, which repack specs use. `SEPVP_MANIFEST_PYTHON` can point to another
  interpreter that imports `tt_boot_manifest.pack_images` and `ruamel.yaml`. Step 4 of the
  quick start creates the default one; `PLAT` is empty on a host whose glibc is 2.34 or newer.
  Check it with:

  ```bash
  virtual_platform/local/manifest-venv/bin/python -c "import tt_boot_manifest.pack_images, ruamel.yaml; print('ok')"
  ```
- A built `sep-vp` (`make -C virtual_platform vp`), unless the case is host-only.
- `openssl` on `PATH`, for the untrusted key.
- `TMPDIR` set to a roomy scratch directory.

## Run

Run these from `virtual_platform/`, with `<python>` the harness interpreter
(`uv --project <repo root> run --group vp --locked python3`).

```bash
# Host-only unit tests: no sep-vp, firmware or toolchain
make -C virtual_platform vp-test-host
<python> -m pytest tests -m hostonly

# One testcase
<python> -m pytest tests/bootcode/test_sep_rom_testlist.py --no-build -k <name> -rA

# The whole testlist
<python> -m pytest tests/bootcode/test_sep_rom_testlist.py --no-build -rA
```

- `--no-build` uses the existing ROM ELF and images. Drop it to let the fixtures rebuild them.
- `--iss-trace` writes the ISS trace to `<run dir>/veer_trace.log`.
- `--stream` echoes sep-vp output live. `--build-type release` deselects `needs_debug` cases.
- Per-run logs are under `logs/sepvp/<name>/` (`sep-vp.log` holds the console). Read them
  before you rerun.
- Generated images and fuse maps are written to the test's pytest `tmp_path`, so parallel runs
  do not share artifacts.
- Do not run two testlist regressions in the same workspace at the same time: both write
  `logs/sepvp/<name>/`. Use `SEPVP_LOGS_DIR` for a second run.

### Negative controls

Copy the testlist, remove or change the stimulus that decides the outcome, and run the copy.
The case must go red.

```bash
cp -r virtual_platform/tests/bootcode/testlist "$TMPDIR/neg_testlist"
# edit "$TMPDIR/neg_testlist/<family>.toml" or its boot_image_mutations/<image>.toml
SEPVP_TESTLIST_DIR="$TMPDIR/neg_testlist" SEPVP_LOGS_DIR="$TMPDIR/neg_logs" \
  <python> -m pytest tests/bootcode/test_sep_rom_testlist.py --no-build -k <name> -rA
```

`SEPVP_TESTLIST_DIR` replaces the testlist root, specs included. `SEPVP_LOGS_DIR` keeps the
positive run's logs.

### Audit

`testlist_audit.audit(testcase, golden_output)` reports three findings against the output of a
healthy boot (the `rom_ot_secure_boot_golden` entry):

- `insensitive`: the entry expects an error-class token that the golden boot also emits.
- `golden_satisfiable`: a healthy boot satisfies the whole contract and nothing outside the run
  pins the stimulus.
- `shares_golden_stimulus`: the entry boots the golden stimulus and only adds assertions. Only
  the entries in `testlist_audit.SHARES_GOLDEN_STIMULUS` may do so.

## Definition of done for a new entry

A testcase is done when all applicable items are true:

- The ROM symbol that reads the stimulus and decides the outcome is identified in
  `hw/sys/sep/bootrom/prod/src/`, and the expected tokens, error codes and status sequence
  are derived from that source. `reference/oca_token_map.md` is only a lookup.
- The entry agrees with the DV test in `hw/sys/sep/dv/testlists/rom_fw.toml` and
  `hw/sys/sep/dv/cocotb/tests/rom_fw/`. A disagreement is reported with evidence from both
  sides, not resolved inside the entry.
- `expect_verdict` is declared.
- `image_asserts` prove, before the run, that the generated image carries the stimulus (`all`,
  `field`, `toc_field`, `same_as` with `xor`, or `differs_from`) and that untouched regions
  survive (`same_as`).
- A failure entry also forbids the success tokens.
- A failover entry forbids `ERROR 0x0213` and does not forbid every `ERROR`, because a
  rejected slot still emits status ERROR lines when the backup succeeds.
- No token that exists only in the legacy ROM (for example `MANIFEST_HASH_OK`, `SIG_VALID`,
  `CRYPTO_VALIDATE_OK`, `PLD_HASH_OK`, `RSA_VERIFY_START`) and no legacy error code is in
  `expect`. Legacy error numbers collide with different OCA meanings; never copy a literal.
- A negative control was run and went red.
- The targeted pytest case ran with `--no-build`, and `sep-vp.log` shows that the expected
  judgment, and not a wrong-reason pass, produced the result.
- A failure of the DUT is not hidden. Keep the spec-correct expectation as a strict xfail
  sentinel with `xfail_reason` and `xfail_match`, or classify the entry as blocked, after the
  owner decides. Do not weaken an expectation to match the output.
- `markers` state what the VP does not prove for this entry.
