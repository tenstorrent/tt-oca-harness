# Replace SEP ROM manifest parsing with the OCA Boot Manifest

## Context

The OCAH SEP boot ROM parses a bespoke ("Grendel") manifest format in
`hw/sys/sep/bootrom/prod/src/manifest_load.c`. We are replacing that format with the
**OCA Boot Manifest**, consumed via the C validation library that now ships in the
`tt-boot-manifest` submodule at `hw/sys/sep/bootrom/prod/tools/tt-boot-manifest`
(HEAD `d17b8fa3`).

The boot flow keeps its shape: load a manifest from SPI or SMC SRAM, confirm geometry and
integrity, check chiplet/life-cycle usage constraints, decrypt and security-check the
payload when secure boot is enabled, verify the signature when it is enforced, then load
payloads and start BL1. What changes is the format and the code interpreting it — larger
body, more fields, PQC-capable variants, and AES-256-CBC payload encryption with a new KDF.

Rather than hand-write a parser, the ROM links the library and supplies platform callbacks
binding it to SEP hardware. Development happens on the SEP virtual platform (a full boot
runs in well under a second); DV simulation tests follow to confirm what the VP established.

## Scope decisions (confirmed)

| Decision | Choice |
|---|---|
| Old format | **Replace outright** — delete the Grendel parser |
| Test bundles | **Generated at build time** via bootrom Makefile pack targets |
| PQC | **Parse all variants; verify RSA-3072 only** |
| Load paths | **Both SPI and SMC SRAM** |
| Signing | RSA-3072 dev0 test key, **raw encoding, no DER** |
| `oca_commit_security_state()` | **Skipped** — `set_*` callbacks left NULL, nothing burned |
| Crypto | **Full** — AES-256 + PKCS#7 + OCA KDF |

## What exploration established

**The library is a good fit.** `validators/oca/lib/` (note: moved out from under `tools/` in
commit `1e7a075`) is 14 `.c` files, freestanding — includes only `<stdint.h>`, `<stddef.h>`,
`<stdbool.h>`, zero libc calls, no malloc, no float, no recursion, no global mutable state.
It builds `-ffreestanding -nostdlib -fno-builtin -Os -std=c99`, matching the ROM's flags.
`validators/oca/INTEGRATION.md` is the porting contract and its headings are pinned by a test.

**It never touches storage.** There is no read/copy/DMA callback — every entry point takes a
pointer to memory the caller already filled. The ROM's existing `manifest_src_read()`
(`src/manifest_load.c:105`, already abstracting SPI vs SMC SRAM behind a `from_spi` flag) is
exactly the right shape to keep. Only `oca_peek_manifest()` (20 bytes) may run against
mapped flash.

**PQC verification is out of scope for the library too**, which is why "parse variants, verify
RSA-3072" lines up: with `OCA_SUPPORT_PQC=1` the ROM understands `OCAP` geometry, and a
PQC-variant manifest signed with a *classical* key still verifies (fixture
`pqc_secure_rsa.yaml`). Native PQC signatures return a clean `OCA_FAIL_UNSUPPORTED_VARIANT`.

**Sizes**: classic main body **4096 B**, signed region `[0,3172)`; PQC main body 36864 B,
signed region `[0,5903)`. TOC header 32 B, entries **276 B** (was 216).

The separate verifier blob (`OCA_CLASSIC_VERIFIER_ENTRY_SIZE` 2048 B, PQC 34816 B) is **out
of scope at this stage** — verifier and co-signer entries are a deferred producer feature
(`use_verifier_key` / `verifier_*` / `co_signers` are hard config errors today) and the
library does not verify them. Ignore them when sizing buffers and writing tests.

**ROM budget is the main risk.** `link/rom.ld` gives 64 KiB; ~31 KiB used, so **~34.5 KiB
headroom**. Deleting the Grendel parser frees ~10 KiB; the OCA library is ~2900 lines of C
which at `-Os` on `rv32im` (no compressed instructions) plausibly lands at 12–20 KiB. It
should fit, but it is not comfortable and **must be measured early**.

## Implementation

### Phase 0 — Build integration and size gate (do this first)

Add the library to `hw/sys/sep/bootrom/prod/Makefile` following the existing
`rsa_3072_app_otbn.o` out-of-tree pattern (`Makefile:236-243`): an `OCA_LIB_SRCS`/`OCA_LIB_OBJS`
static pattern rule over `$(TT_BOOT_MANIFEST_DIR)/validators/oca/lib/*.c`, with `-I` on that
directory added to `CFLAGS`. Do **not** use `NONFREE_BOOTCODE_SOURCES` — it has a flat
basename namespace and the library has a `lifecycle.c` that would collide with the ROM's own.

Two things to get right:
- New objects must land in `OBJS` so they inherit `$(OBJS): $(FLAGS_STAMP)` rebuild-on-flag-change
  and `-include $(OBJS:.o=.d)` header deps.
- Add `-DOCA_SUPPORT_CLASSIC=1 -DOCA_SUPPORT_PQC=1 -DOCA_TOC_MAX_IMAGES=<n>` to `BUILD_FLAGS`
  (`Makefile:192-196`), or flag changes silently reuse stale objects.

**Gate:** build a throwaway TU linking the library and check `size`/`nm` before writing any
callbacks. Two specific things to confirm:

> **DONE — both gates passed with room to spare (2026-08-25).**
> - **Size: 11,470 B text**, zero `data`, zero `bss` (`riscv64-unknown-elf-size -t
>   build_ot/oca/*.o`), against **34,520 B headroom** — and that is *before* `--gc-sections`,
>   with ~10 KiB more still to be freed by deleting the Grendel parser. Largest TUs:
>   `payload.o` 4636, `oca_validator.o` 2054, `parser.o` 1224. **No size levers needed** —
>   `OCA_SUPPORT_PQC` stays on, and `OCA_TOC_MAX_IMAGES` was set to 32 anyway as cheap margin.
> - **No libc dependency.** Every undefined symbol is an internal cross-TU reference
>   (`oca_check_*`, `oca_selector_decode`, …); no `memcpy`/`memset`/`memcmp` synthesized, so
>   the planned `src/rom_mem.c` fallback is **not needed**.
> - Full ROM relinks at **31016 bytes — byte-identical to baseline**, confirming the library
>   gc-sections away cleanly while unreferenced.
> - Note: the library needs the **toolchain container** to compile (`--specs=picolibc.specs`);
>   the host RISC-V toolchain has no picolibc. Build via
>   `./scripts/docker-run.sh run-here make -C hw/sys/sep/bootrom/prod ot-toolchain-images`.

1. **Total `.text` fits.** If not, levers in order: `OCA_SUPPORT_PQC=0` (drops `OCAP`
   geometry — costs the "parse all variants" property, so confirm before taking it),
   `OCA_TOC_MAX_IMAGES=32`, then `-march=rv32imc` (recovers ~20–25% but changes the BL1 ABI
   expectation). The 64 KiB linker `LENGTH` is an IFU-decode limit, not physical — raising it
   is an RTL change, not a linker edit.
2. **No synthesized `mem*` calls.** The ROM links `-nostdlib` and today has **zero** undefined
   symbols and no `memcpy`/`memset`/`memcmp` of its own. GCC can synthesize them from struct
   assignment even under `-fno-builtin`. If `nm` shows any, add a minimal `src/rom_mem.c`.

### Phase 1 — Test manifest bundles

Add `configs/oca_unsigned_test.yaml` and `configs/oca_secure_boot_test.yaml`, modelled on
`validators/oca/test/fixtures/configs/basic.yaml` and `secure_rsa.yaml`. Payload stays
`bl1_pass_test` (`$OCH_ROOT/fw/tests/bl1_pass_test/build/bl1_pass_test.bin`) so the existing
`0xA5A55A5A`→`0xCAFEBABE` mailbox PASS gate keeps working in both environments.

Signed config essentials — raw encodings are already the defaults:
```yaml
manifest_format: oca-classic
secure_boot: 1
signature_type: 0x01                 # RSA-3072 PKCS#1 v1.5 / SHA-256
signing_key_file: "tests/signing_keys/rsa_private_key.dev0.pem"
public_key_select_classic: 0x01      # must be non-zero
public_key_encoding: 0x02            # RAW  (0x01 = DER, not wanted)
signature_encoding: 0x02             # RAW
timestamp: <pinned>                  # pin for byte-deterministic builds
```

Add `oca_images` / `oca_secure_boot_spi` targets mirroring the existing `secure_boot_spi`
recipe (`Makefile:361`): `pack_images --out X.bin` then `bin_to_spi_preload.py X.bin
X.spi_preload`. **Both outputs are required** — the VP consumes `.spi_preload`/raw via
`flash_image`, DV consumes `.bin` via `OcahSpiFlash.preload`. Keep `bl1_test` as a
prerequisite.

Also regenerate `src/key_digests.c` slot 0 via `tools/generate_key_digests.py` if the key
changes; it currently pins the dev0 modulus digest.

Then register the new target in `hw/sys/sep/dv/sep_sim_cfg.toml` under `[c_build.boot_rom_ot]`
— both the trailing `make` argv **and** the `outputs` list. The `outputs` check is what makes
`--stage sim` fail loudly instead of simulating a stale image.

> **DONE (2026-08-25).** `configs/oca_non_secure_boot_test.yaml` and
> `configs/oca_secure_boot_test.yaml`; Makefile targets `oca-images`,
> `oca_non_secure_spi`, `oca_secure_boot_spi`, each emitting `.bin` + `.spi_preload`;
> `sep_sim_cfg.toml` argv and `outputs` updated.
>
> Both images pack to **5444 B** (4096 body + 1348 payload), signature over exactly
> **3172 B** = `OCA_CLASSIC_SIGNED_REGION_END`. Independently validated with the library's
> own CLI — both `PASS`, `image[0] type=TT_SEP  BLSTAGE1 load_addr=0x10020000` — and
> confirmed **non-vacuous**: a flipped byte in the signed region gives
> `FAIL: MANIFEST_HASH`, a broken magic gives `FAIL: MAGIC`.
>
> **Gotcha found:** the OCA producer does **not** expand `$OCH_ROOT`/`$ROOT` in config
> paths (`src/oca/payload.py` calls `open(path)` verbatim), unlike the Grendel packer which
> uses `os.path.expandvars`. The configs therefore carry paths relative to
> `hw/sys/sep/bootrom/prod` — correct because `make -C` makes that the recipe's cwd — and
> the recipes drop the `OCH_ROOT=`/`ROOT=` env prefix the Grendel rules use.
>
> Image type follows the spec's TOC convention (`boot-manifest.adoc`, "Payload TOC entry"):
> bytes[15:8] vendor string, bytes[7:0] standard label — hence `"TT_SEP  BLSTAGE1"`.
>
> To build the validator CLI on this box, static OpenSSL needs `-ldl`:
> `make -C validators/oca OPENSSL_CFLAGS="-I<ossl>/include"
> OPENSSL_LIBS="-L<ossl>/lib64 -lssl -lcrypto -ldl -lpthread"`, with
> `<ossl>` = `virtual_platform/local/openssl-3.3.2`.

### Phase 2 — Platform callback layer

New `src/oca_platform.c` + `include/oca_platform.h` exposing one populated
`const oca_callbacks_t *sep_oca_callbacks(void)`. `memset` the struct, assign only what is
wired; NULL is legal and yields `OCA_FAIL_CALLBACK_UNAVAILABLE` at the check that needs it,
never a pass. There is no context pointer — callbacks reach state through file-scope statics.

| Callback | Implementation |
|---|---|
| `sha256` | thin wrap of `sha256()` — `src/hmac_sha256.c:95` |
| `verify_signature` | `rsa_3072_verify()` — `src/rsa_verify.c:126`; accept `primitive_type==0x01` + `encoding==RAW` only, else `OCA_FAIL_SIGNATURE` |
| `decrypt_payload` | new; see Phase 4 |
| `get_identity_bytes` | SMC fuse map reads (`src/manifest_load.c:387,405`) + `SEP_EFUSE_MAP_SEP_{CHIPLET,SIP,SYS}_ID` |
| `get_lifecycle_state` | `lc_read_state()` — `src/lifecycle.c:30`, mapped to `oca_lifecycle_token_t` |
| `get_version` | `BL1_VERSION` fuse bank |
| `is_secure_boot_active` | `lc_state_enforces_secure_boot()` — `src/lifecycle.c:66` |
| `is_secure_boot_disabled` | SBOOT_DIS / `bl0_state.sboot_dis` — `src/rom_main.c:589` |
| `get_root_key_revocation` | `CHIPLET_PUBK_REVOKE`, source of `check_pubkey_revoked()` |
| `get_security_version` | `BL1_VERSION` bank |
| all `set_*` | **NULL** — commit skipped by decision |

Three semantics that are easy to get wrong:
- The two boolean reporters return `oca_secure_bool_t`, a `uint32_t` where
  `OCA_SECURE_FALSE = 0x5A5A5A5A` and `OCA_SECURE_TRUE = 0xA5A5A5A5`. **Never return `1`** —
  it reads as "enforced". Test by equality, never truthiness.
- Fuse reads return `oca_hw_result_t`; **`OCA_HW_UNAVAILABLE` is a hard failure**, not
  "constraint not applicable". Write `OCA_LIFECYCLE_UNKNOWN (0xFF)` rather than leaving an
  output untouched.
- Reporters are consulted ~6× per validation and must be **stable for the whole run** —
  the library re-derives and compares against the context, and disagreement is
  `OCA_FAIL_SECURE_BOOT_STATE_CHANGED`.

> **DONE (2026-08-25).** `include/oca_platform.h` + `src/oca_platform.c`, added to `OBJS`.
> **1024 B**, zero warnings under `-Wall -Wextra -Wconversion -Wshadow`, and its only
> undefined symbols are `sha256`, `rsa_3072_verify`, `lc_read_state`, `lc_state_is_valid`,
> `lc_state_enforces_secure_boot` — i.e. it is pure adapter over drivers the ROM already had.
> ROM still relinks at 31016 B because nothing calls the table until Phase 3.
>
> **Verified the fail-closed returns are safe.** `get_version` returns `OCA_HW_UNAVAILABLE`
> unconditionally and `get_lifecycle_state` does so for PACKAGE/SYSTEM (SEP provisions
> neither). That is only correct because the library gates every one of these on the
> manifest's selector bits: `oca_check_lifecycle` returns `OCA_OK` when
> `sb.lifecycle_*_enabled` is clear, and `oca_version_range_check` returns `OCA_OK` when
> neither min nor max is specified. So an unconstrained manifest never reaches them, and a
> manifest that *does* constrain a level SEP cannot report fails — which is the intended
> direction. Note `oca_lifecycle_check` itself has no such guard, so the gating lives
> entirely in the caller; do not call the inner form directly.
>
> **Exponent check added.** RAW RSA public keys are a 384-byte BE modulus + 4-byte BE
> exponent, but `rsa_3072_verify()` is backed by `MODE_RSA_3072_MODEXP_F4` and never reads
> the key's exponent. Without an explicit check an `e=3` key would be verified against
> 65537 regardless of what it declares — a silent wrong-key accept. `plat_verify_signature`
> rejects any exponent that is not `0x00010001`.
>
> **Mappings worth knowing:** identity banks (`SEP_CHIPLET_ID` / `SEP_SIP_ID` /
> `SEP_SYS_ID`) are 32 B each, exactly OCA's width. `CHIPLET_PUBK_REVOKE` is only **32 bits**
> against OCA's 128-bit revocation bitmap, so the upper bits read as zero (revoking nothing).
> `get_security_version` returns the low 16 B of the 32-byte `BL1_VERSION` bank raw: the
> library's test is `manifest & device == device` (bit-superset) and eFuse bits only go
> 0 → 1, so the fuse image already *is* that monotone bit set — no thermometer-to-count
> conversion belongs there.

**Fix while here:** `validate_signature()` computes fuse-key digest addresses as
`CHIPLET_PUBK_REVOKE_BASE + 0x100`/`+0x120` (`src/manifest_crypto.c:182,186`), which land on
`SPI_PHY_DLL_SLAVE` and mid-`CHIPLET_PUBK_HASH0`. The real banks are `+0x110`/`+0x130`. The
path has never been exercised (only ROM key slot 0 is used in tests). Carry the corrected
addresses into the new revocation callback rather than porting the bug.

### Phase 3 — Boot flow rewrite

Replace `src/manifest_load.c` + `src/manifest_crypto.c` + `include/manifest.h` with a new
`src/oca_boot.c` implementing the **staged flow** in exactly this order (reference
implementation: `validators/oca/test/main.c:312` `validate_from_storage()`):

```
oca_peek_manifest(head,20)      → variant + body size
  copy body into SEP SRAM       ← manifest_src_read(), unchanged
oca_validation_context_init()
oca_validate_manifest()
oca_payload_encryption_info()
oca_locate_payload(bounds)      → addr + span
  copy payload                  ← manifest_src_read(), unchanged
oca_check_payload_at()
oca_toc_info() / oca_toc_image_at()
  (oca_commit_security_state()  — skipped)
```

Keep unchanged: slot rotation and retry (`manifest_load.c:510-601`, `PRIMARY_MANIFEST_OFFSET
0x1000` / `BACKUP_MANIFEST_OFFSET 0x41000`, `rotate_update` XOR of the slot index, SRAM clear
+ `boot_flash_reinit()` between attempts), the SMC-SRAM handshake
(`SMC_SEP_STATUS_MANIFEST_READY` poll), and staging into `SRAM_BASE`.

Note both bodies must stay resident through the payload check, so continue staging in SEP
SRAM (256 KiB) — never on the 128 KiB DCCM stack, especially with a 36 KiB PQC body.

Rework `src/rom_handoff.c` to select BL1 via `oca_toc_image_at()` — TOC entries are now 276 B
with a 16-ASCII-byte `type` field (was a packed `u64`), so `find_toc_entry()` changes shape.

**Status codes:** map `oca_result_t` (0–34) onto `SEP_MSG_*`. Most of the needed codes already
exist in `include/status_values.h` but are **declared and never emitted** today —
`INVALID_MANIFEST_ID 0x06`, `INVALID_MANIFEST_VERSION 0x07`, `INVALID_SIGNATURE 0x0e`,
`REVOKED_KEY 0x0c`, `TOC_ID_INVALID 0x0f`, `DECRYPTION_FAILED 0x1a`, etc. Wiring the OCA
result codes to them is the natural way to close that gap. Keep the 32-bit
`MANIFEST_ERR_0x0003xxxx` sub-error channel for the mailbox.

Caution: `rom_err_fail()` truncates to `& 0xFFFF` for the cold-scratch word
(`src/rom_main.c:166`), so a `MANIFEST_ERR_*` collides with the `SEP_MSG_*` numbering space.
Worth resolving as part of the remap rather than inheriting.

> **DONE (2026-08-25). Boots end-to-end to `SEP_MSG_STARTING_BL1`, signed and unsigned.**
> New `src/oca_boot.c` + `include/oca_boot.h`; `rom_handoff.c` rewritten onto
> `oca_toc_info`/`oca_toc_image_at`; `rom_main.c` reduced (the whole C13.10 crypto block and
> the separate payload-hash step are subsumed by the staged flow). Deleted
> `manifest_load.c`, `manifest_crypto.c`, `manifest.h`, `manifest_crypto.h`.
> **ROM 31016 → 35392 B** (+4376 net; ~30 KiB headroom left).
>
> Error encoding carries the library verdict verbatim: `0x000300xx` is
> `oca_result_t xx`, `0x000301xx` is a failure in this module. Confirmed live —
> a bad signature reported `MANIFEST_ERR=0x0003000e` (`OCA_FAIL_SIGNATURE`).
>
> **SUPERSEDED — the trust anchor moved into the library (see below).** The ROM-side
> `check_root_key_trust()` described next ran *after* `oca_validate_manifest()`, which is the
> wrong order: it verified with a key and then asked whether the key was trustworthy. It has
> been removed in favour of a proper library check. Kept here for the reasoning, which still
> holds.
>
> **Added a root-key trust anchor that the plan did not call for.** The library authenticates
> a manifest against the key the manifest *carries* and separately checks that key slot is
> not revoked — it never checks the key is one the device trusts. There is no callback for a
> root-key hash and the verifier/co-signer chain is on its "Not supported" list, so on the
> library alone **any attacker key that signs its own manifest verifies**. The old ROM closed
> this with `key_digests.c`; `check_root_key_trust()` in `oca_boot.c` preserves that anchor
> unchanged (same table, same generator, same 384-byte modulus digest). It runs *after*
> `oca_validate_manifest()` because the selection bitmap is only trustworthy once the signed
> region holding it is verified. Note `public_key_select_classic` is a 128-bit **bitmap**,
> not the old small index; more than one bit set is refused as ambiguous.
>
> Other fixes folded in: `PRIMARY/BACKUP_MANIFEST_OFFSET` moved to `boot_flash.h` (flash
> layout, not manifest format); dead `lc_state_to_manifest_bit()` removed rather than left as
> a second divergent LC mapping; `key_digests.h` made standalone; the stale
> `// 0x10100000` comment on `SRAM_BASE` corrected to `0x10000000`.
>
> **Phase 1 gap found and fixed:** a bare `oca-classic` pack emits a bundle at offset 0, but
> the ROM reads slots at 0x1000/0x41000. Added `configs/oca_{non_,}secure_boot_image.yaml`
> (`oca-combined`) placing the bundle at both slots; these are the bootable artefacts and
> what `oca-images` now emits (0x50000 bytes). Both slots validate standalone via
> `oca-validate --manifest-addr 0x1000|0x41000`.

### Phase 4 — Crypto extensions

- **`src/aes_driver.c`**: add AES-256 key loading and PKCS#7 unpadding. Keep the AES-128 path
  — the library accepts `0x01` and a PQC fixture uses it. The IP's SIDELOAD bit is currently
  hard-disabled (`aes_driver.c:158`); we continue loading the derived key directly via
  `KEY_SHARE0` as today.

  **AES-256 is confirmed available — the 128-bit limit is driver-only, not hardware:**
  - `hw/sys/sep/regs/blocks/aes/aes.rdl:127` — `KEY_LEN[10:8]` is 3-bit one-hot;
    AES-256 is `3'b100`. Only 192-bit can be compiled out; **AES-256 is the fallback for
    invalid values**, so it is always present.
  - `aes.rdl:36,54` — `KEY_SHARE0[8]` and `KEY_SHARE1[8]`, i.e. 8×32 bits per share: the
    register file already holds a full 256-bit key. Today's `write_key_128()` writes 4 words
    and zero-fills; the change is to write all 8 and set `KEY_LEN = 0x4`.
  - VP model `sep/peripherals/aes/src/aes.cpp:1534-1537` decodes the one-hot field
    (`0x4 → AES_256`, invalid → AES_256, matching the RDL) and `:484` selects
    `EVP_aes_256_cbc()`. So the encrypted-payload path is testable on the VP as-is.
- **`src/kdf.c`**: rewrite for the OCA scheme. The primitive is unchanged (SP 800-108r1
  CTR-HMAC-SHA-256) but the input encoding is entirely different: a **192-byte block** of
  `header(32) ‖ label(32) ‖ context(64) ‖ entropy(64)`, label = ASCII `KM_CLASS_BL` NUL-padded,
  context = the manifest's 64-byte `kdf_input`, entropy = zero. Today's `kdf.c` builds a
  41-byte input and is single-iteration (`out_len <= 32`); AES-256 needs 32 bytes so that
  still holds, but the block construction must be replaced. Reference implementation:
  `validators/oca/test/openssl_crypto.c`; Python side `src/oca/encryption.py:52-130`;
  **validate against `tests/test_oca_kdf_kat.py`**.
- **`decrypt_payload` callback**: resolve `secret_select` (a 1-based *index*, never a secret)
  against the `CLASS_KEY` fuse bank, derive, AES-CBC-decrypt, strip PKCS#7. Decrypt
  **in place** — the library explicitly supports `*out_plaintext` aliasing `in->ciphertext`
  (safe because `iv`/`kdf_input` live in the manifest body, not the payload) and that avoids a
  second payload-sized buffer. Return `OCA_FAIL_NO_PROVISIONED_SECRET` for an unprovisioned
  slot, distinct from `OCA_FAIL_DECRYPT`.

The library verifies `payload_hash` over the ciphertext *before* calling us, and verifies
`payload_hash_chain` plus every TOC entry hash over the plaintext afterwards — so we supply
only the cipher and KDF.

### Phase 5 — VP tests (primary development loop)

Rewrite `virtual_platform/tests/bootcode/test_bootcode_ot_negative.py`. Its whole coupling to
the format is five offset constants plus `_preload_raw()`; import the new offsets from
`tt_boot_manifest.src.oca.constants` (`OFF_BOOT_MANIFEST_MAGIC`, `OFF_PAYLOAD_OFFSET=3748`,
`TOC_ENTRY_SIZE=276`, …) rather than re-hardcoding them.

Re-derive which negative cases work without re-signing: today's trick depends on magic and
payload-location being checked *before* the signature and `payload_offset` living outside the
signed region. In OCA, `payload_offset` @3748 is likewise in the **unsigned tail** — so
`payload_overlap`, `payload_too_large` and `rotate_to_backup` should port directly, while
`hash_tamper` still works by breaking the signed region.

New coverage worth adding: variant dispatch (`OCAC` vs `OCAP`), trailer corruption,
`manifest_length` mismatch, TOC image-count overflow, root-key revocation, security-version
rollback, and an encrypted-payload round trip.

Two gotchas that will cost time if missed:
- **New `SEP_MSG_*` codes need a VP rebuild.** `STATUS_VALUES_PATH` is baked into the decoder
  at CMake time (`SEP_SCRATCH_COLD_STATUS_VALUES_PATH`); without a reconfigure `expect_status`
  sees `SEP_MSG_UNKNOWN`.
- **`SimConfig(otp=...)` currently works by accident.** `efuse_vp.ini` sets a relative
  `fuse_preload_file` that never resolves from the run dir, so the model falls through to
  per-field CCI params. The model takes an image *or* params, never both. Encrypted-payload
  tests need a real `CLASS_KEY`, so add an explicit absolute `fuse_preload_file` override or a
  `_disable_base_fuse_preload()` mirroring the existing `_disable_base_spi_preload()`. Note no
  test passes `otp=` today, so this path is unit-tested but never run end-to-end — expect
  friction. `sepvp/fuses.py` already maps `CLASS_KEY` (8×32-bit LE words) and `lc_state`.

### Phase 6 — DV simulation tests

Mirror the VP cases. `sep_rom_ot_secure_boot_test.py` is the template — 68 lines, subclassing
`sep_rom_ot_dma_boot_test` and overriding only `flash_image`, `required_markers`,
`forbidden_markers`. Add a new module per case under
`hw/sys/sep/dv/cocotb/tests/cpu/`, register `[[tests]]` entries in
`hw/sys/sep/dv/testlists/cpu.toml` (`target = "rom_boot"`,
`firmware = { name = "boot_rom_ot", mode = "boot_rom_ot" }`).

Two asymmetries to plan around:
- **DV asserts on ROM virt-console ASCII markers, not `SEP_STATUS`.** A VP case expecting
  `SEP_MSG_INVALID_MANIFEST_HASH` has no direct DV counterpart — either assert a console
  string or add a status decoder. Keep the ROM's `simputs` markers (`MANIFEST_ERR=`,
  `RSA_VERIFY_OK/FAIL`, `DECRYPT_OK`, …) alive through the rewrite so DV keeps its hooks.
- **There are no manifest-negative DV tests today** (`sep_rom_non_secure_boot_test.py:55`
  says so outright). For negative cases override `run_scenario` to tamper bytes before
  `flash.preload()` — it accepts a bytes-like object, so no temp file is needed.

If a new test needs non-default fuses, also update the registry in
`hw/sys/sep/dv/cocotb/dv_sim_prestage.py`, which must mirror each test's
`select_efuse_image` kwargs exactly (the RTL `$readmemh` fires at t=0, before cocotb runs).

## Verification

Environment on this box: `source /opt/rh/gcc-toolset-11/enable`,
`export OCAH_TOOLCHAIN_ROOTFS=/localdev/cmccoy/ocah-toolchain-rootfs`,
`export PATH=/tools_soc/opensrc/riscv-gnu-toolchain/2025.01.20-rhel-8.10/bin:$PATH`.

1. **Library self-test** (proves the vendored lib and our understanding of it):
   `make -C hw/sys/sep/bootrom/prod/tools/tt-boot-manifest/validators/oca check` —
   expect two `N/N passed` summaries. Also `make ... classic-only` / `pqc-only` for the
   variant gates, and `pytest tests/test_oca_kdf_kat.py` for the KDF KATs.
2. **Size gate**: `make -C hw/sys/sep/bootrom/prod ot-toolchain-images`, then
   `riscv64-unknown-elf-size build_ot/boot_rom.elf` and `nm build_ot/boot_rom.elf | grep " U "`
   (must stay empty). Fail fast here rather than after the callbacks are written.
3. **Image generation**: build the new pack targets and validate the output *independently*
   with the library's own CLI —
   `validators/oca/build/test/oca-validate --manifest build/oca_secure_boot.bin --list-images`
   (exit 0 = PASS). This decouples "is the image right" from "is the ROM right", which is the
   fastest way to bisect a failure.
4. **VP** (the development loop, ~2 min for the full suite):
   `make -C virtual_platform vp && make -C virtual_platform vp-test PYTEST_ARGS="-v"`.
   Single case: `make -C virtual_platform vp-test PYTEST_ARGS="-v -k hash_tamper"`, or drive
   it directly with `python -m sepvp.cli --bin ... --spi ... --until SEP_MSG_STARTING_BL1`.
   Run logs land in `virtual_platform/logs/sepvp/<name>/sep-vp.log`.
5. **Baseline to beat**: the suite was **1 failed, 35 passed, 1 skipped**, the failure being
   `test_ot_manifest_negative[rotate_to_backup]` with `RSA_PKCS1_FAIL`.

   > **ROOT-CAUSED (2026-08-25): it is a VP configuration bug, not a ROM or manifest bug.**
   > The base config sets `och_sep_ss1.otbn.algorithm_type : otbn_loop`, a loop benchmark
   > model. The real modexp model is selected by `"rsa_3072"`
   > (`sep/peripherals/otbn/src/otbn.cpp` `select_algorithm`), so **RSA-3072 verification
   > could never succeed on the VP** — which is why the only test expecting a *successful*
   > signature check was the only one failing. With
   > `extra_ini=[("string","och_sep_ss1.otbn.algorithm_type","rsa_3072")]` the signed OCA
   > image verifies (`RSA_VERIFY_OK`, `PUBK_TRUSTED`) and boots to `SEP_MSG_STARTING_BL1`.
   >
   > Phase 5 must set this for every secure-boot test — either per-test via `extra_ini`, or
   > better, once in the harness so no future signed test silently exercises a stub. Worth
   > raising upstream too: `otbn_loop` is a poor default for a platform whose ROM verifies
   > RSA.
6. **DV** (slow, run last):
   `python3 tools/dv/run_dv.py --dut sep --items sep_rom_ot_secure_boot_test --stage flist
   --stage hdl_compile --stage c_compile --stage sim`, then the `cpu` regression.

## Risks

1. ~~**ROM size.** The dominant risk.~~ **RETIRED** — measured at 11,470 B against 34,520 B
   headroom (Phase 0). Comfortable even before the Grendel parser is deleted.
2. ~~**`OCA_SUPPORT_PQC=0` is the biggest size lever.**~~ **NOT NEEDED** — PQC support stays
   on, so the "parse all variants" property is kept.
3. **I3C is not modelled on `sep-vp`** — it exists only on the SMC/SMU platforms. This does
   not block the agreed scope: from the ROM's side the second source is SMC SRAM, which the
   existing recovery/secondary tests already exercise. But the actual I3C transfer into SMC
   SRAM cannot be integration-tested here.
4. **`e=3` RSA is unsupported by the OTBN app** (`MODE_RSA_3072_MODEXP_F4`, e=65537 only).
   The dev0 key is e=65537, so this is fine — just don't reach for the `e3` fixtures.
   Unlike AES-256, this one is a genuine hardware/app limit, not a driver gap.
5. **Skipping `oca_commit_security_state()` is correct permanently, not just for now.**
   The ROM burns no fuses by design — BL0 validates and records the commit directive in
   `bl0_state`, and SEP BL1 owns the fuse programming. So anti-rollback and revocation are
   checked by BL0 and advanced by BL1; there is nothing to follow up on the ROM side.

---

## Phase 3b — ROOT-key authorization, done properly in the library (2026-08-26)

The Phase 3 trust anchor was in the wrong place and the wrong order: a ROM-side check that
ran *after* `oca_validate_manifest()`, i.e. verify with the key, then ask whether the key was
trustworthy. Replaced with a first-class library check.

**Library** (`tt-boot-manifest`, branch `cmccoy/root_key_authorization`, commit `54c7cf3`):

- New callback `oca_result_t (*is_key_authorized)(const oca_crypto_blob_t *public_key,
  const uint8_t select[16])`. The decision is the Consumer's — the anchor may be a key in
  mask ROM, a digest in OTP, or a store the format cannot describe — so the library supplies
  the key plus the selection bitmap and holds no opinion. NULL **fails closed**.
- New `oca_check_root_key_authorized()` (`lib/authorization.c`) and result code
  `OCA_FAIL_ROOT_KEY_UNAUTHORIZED = 35`.
- Composed **first of the key checks**, which is the order asked for:

      determine_secure_boot  ->  check_root_key_authorized
                             ->  check_root_key_revocation
                             ->  check_security_version
                             ->  check_signature  ->  (recheck security_version)

  Authorization precedes revocation because the questions narrow in that order — *ever
  trusted*, then *still trusted*. A key can be unauthorized with no revocation bit set. It
  also means an unknown key is refused without being used and without paying for a modexp.
- **The ordering is enforced, not documented.** The verdict is recorded in the validation
  context as `secure_boot_key_authorized`, and `oca_check_signature()` refuses a context that
  does not carry it. A hand-composed sequence that skipped authorization now fails rather than
  verifying against a key nothing vouched for — the same pattern the encryption gate already
  uses against the signature record.
- `oca-validate` grows `--root-key-digest HEX64` and `--trust-any-root-key`; the signed
  fixtures carry the latter, since their keys are not what those cases test.
- **221/221 unit tests** (5 new: refused-before-verification with a zero verify-call count,
  authorization-precedes-revocation, missing-callback-fails-closed, signature-refuses-an
  unauthorized-context, no-op-when-secure-boot-off) and **13/13 fixture sweep**. Also passes
  `--reverse`, so the new cases are order-independent.

Two things the change turned up in the existing tests, both worth knowing:

- The unit-test contexts were **positional** initializers, so inserting a field mid-struct
  silently shifted their meanings — `g_authenticated` would have quietly become
  *un*-authenticated. Converted to designated initializers.
- `test_the_determination_costs_one_consultation_per_consumer` hard-codes the number of gated
  consumers and says "if either number changes, a consumer was added". One was; 4 → 5.

**ROM** (`src/oca_platform.c`): `plat_is_key_authorized()` implements both anchor kinds —
`key_digests.c` for ROM slots, OTP banks above them — resolving the 128-bit
`public_key_select` bitmap to a slot and refusing an ambiguous multi-bit selection. Uses the
**corrected** OTP addresses (`CHIPLET_PUBK_HASH0/1`, `SIP_PUBK_HASH0`, `SYS_PUBK_HASH` via
generated symbols) rather than the old `+0x100/+0x120` arithmetic that landed on
`SPI_PHY_DLL_SLAVE`. Two deliberate hardenings over the old ROM: an unprovisioned ROM slot
now authorizes nothing (the old code treated a NULL digest as "skip the check"), and an
all-zero OTP bank is refused so an unburned part cannot match a zero digest.

ROM 35392 → **36144 B**. Both images still boot to `SEP_MSG_STARTING_BL1`, and the log now
shows `PUBK_AUTHORIZED` **before** `RSA_VERIFY_OK` — the ordering is observable.

Local build notes for the library's own suite on this box:
`make -C validators/oca check PYTHON=<uv-wrapper> OPENSSL_CFLAGS=-I<ossl>/include
OPENSSL_LIBS="-L<ossl>/lib64 -lssl -lcrypto -ldl -lpthread"`, where the uv wrapper is
`uv run --no-project --with-editable <submodule> python` (the repo `.venv` has no
`cryptography`) and `<ossl>` is `virtual_platform/local/openssl-3.3.2`.

---

## Phase 4 — AES-256 + PKCS#7 + OCA KDF (2026-08-26)

Done, and an **AES-256-CBC encrypted payload now decrypts on sep-vp and boots to BL1**.
All three images pass: unsigned, RSA-3072 signed, encrypted.

**ROM changes**
- `src/kdf.c` rewritten. `oca_derive_payload_key()` builds the Key Manager's 192-byte block
  (`header(32) ‖ "KM_CLASS_BL"(32) ‖ kdf_input(64) ‖ entropy(64)`) and runs
  `HMAC-SHA256(secret, be16(i) ‖ block ‖ be16(L))`. The PRF is unchanged from the old ROM;
  the *encoding* is completely different — the old one built a 41-byte
  `counter ‖ info(16) ‖ 0x00 ‖ salt(16) ‖ L` from a 32-byte KDF input, so the same material
  derived a different key. Reference: `validators/oca/test/openssl_crypto.c
  derive_payload_key()`.
- `src/aes_driver.c`: `aes128cbc_decrypt()` → `aes_cbc_decrypt(..., key_bytes, ...)` selecting
  the one-hot `KEY_LEN` (128 → 0x1, 256 → 0x4). An unknown width is **rejected**, not defaulted
  to AES-256 the way the hardware would, since silently using a different key length decrypts
  to garbage. Added `aes_pkcs7_strip()`, constant-time in the padding value.
- `oca_platform.c`: `plat_decrypt_payload()` resolves `secret_select` against the `CLASS_KEY`
  bank, derives, decrypts **in place** (the library supports the aliasing; `iv`/`kdf_input`
  live in the manifest body, not the payload), strips padding. An all-zero CLASS_KEY is
  refused as `NO_PROVISIONED_SECRET` rather than deriving a deterministic key and failing
  later with a misleading `PAYLOAD_HASH_CHAIN`.

ROM 36144 → **38928 B** (~26 KiB headroom).

### Three latent bugs this uncovered

The encrypted path is the first code to call `hmac_sha256()` or read a non-zero fuse bank, so
it walked straight into bugs that had never been reachable.

1. **`hmac_sha256()` never set `CFG.key_length`** — required in HMAC mode, and its reset is
   `Key_None`, which the IP explicitly blocks (`hmac.rdl:138-153`), raising `hmac_err` and
   returning `0xFFFFFFFF` digests. Every HMAC operation failed. `sha256()` was unaffected
   because the field is irrelevant unkeyed, which is why nothing noticed.
2. **`hmac_sha256()` wrote the key little-endian.** The KEY registers are big-endian — byte 0
   in `KEY_0[31:24]` — which is what `key_swap = 0` (the reset) selects. Packing them
   little-endian byte-reverses the key within every word and derives an unrelated HMAC.
3. **VP eFuse model offsets were 4 bytes low from `LC_STATE` onward** (missing `LOCKS_SPARE`
   @0x008), so `CLASS_KEY` read back shifted by one word. Fixed on branch
   `cmccoy/efuse_map_offsets`, commit `57892dfe`. Latent because every fuse the existing tests
   read is zero: the ROM reading LC_STATE's real address got the model's SBOOT_DIS, and both
   are 0 on a TEST_DEV part.

**Still stale in the VP eFuse model, and worth its own change:** from `PUBLIC_KEY_0` onward it
is a whole RDL revision behind — generic `RESERVED_0..7` blocks where the RDL defines
`CHIPLET_PUBK_HASH0/1`, `REQUIRED_SIGNERS`, `REQUIRED_ALGS`, the PQC key hashes, and
`SEP_CHIPLET_ID` / `SEP_SIP_ID` / `SEP_SYS_ID`. Those reads land in reserved space and return
zeroes rather than faulting, so **`plat_get_identity_bytes()` and the OTP key-hash slots in
`plat_is_key_authorized()` cannot be exercised on the VP** until it is re-synced. Neither is
reached by the current tests (no manifest constrains identity; only ROM key slot 0 is used).

**New test assets**
- `configs/oca_encrypted_boot_test.yaml` + `oca_encrypted_boot_image.yaml`, AES-256-CBC with
  a pinned IV and KDF input (an absent value is generated per pack and recorded in a side-car
  JSON, which would make every build differ). Makefile target `oca_encrypted_boot_spi`.
- `virtual_platform/tests/fuse_maps/oca_encrypted.yaml` provisions `CLASS_KEY` to match the
  config's `encryption_secret`. Note the word order: `class_key[0]` is bits[31:0], so each
  word is four consecutive secret bytes read little-endian. Get it wrong and the derivation
  still "succeeds" — it just yields a different key and surfaces as `PAYLOAD_HASH_CHAIN`.

This is also the **first end-to-end use of `SimConfig(otp=...)`**, which the plan flagged as
plumbed but never exercised. It works, and still depends on `efuse_vp.ini`'s relative
`fuse_preload_file` failing to open so the per-field params apply — that fragility is
unchanged and still worth fixing.

---

## Phase 5 — VP tests (2026-08-26)

**48 passed, 0 failed, 0 skipped** (~2 min). Baseline at the start of this work was
35 passed / 1 failed / 1 skipped.

**Harness**
- `otbn.algorithm_type = "rsa_3072"` now set once in `SepVpHarness._abs_path_overrides()`
  rather than per test. The ROM links the OTBN RSA app unconditionally, so no sep-vp run of
  this firmware ever wants the loop model. It composes before `SimConfig.overrides()`, so a
  test can still override it via `extra_ini`.
- New session fixture `oca_images` builds `oca-images` and returns
  `{"unsigned", "signed", "encrypted"}`. One fixture, not three: same make target, same
  prerequisites.
- `paths.OCA_{NS,SEC,ENC}_IMAGE`.

**Tests**
- `tests/bootcode/oca_layout.py` — offsets loaded from the producer's own
  `src/oca/constants.py` by file path (the package `__init__` pulls in `cryptography`, which
  the pytest venv has no reason to carry). No offsets are restated in this repo. It also
  **asserts** `payload_offset` is still in the unsigned tail, so the suite fails loudly rather
  than silently weakening if the format moves it.
- `test_bootcode_oca.py` — 5 positive cases. The signed one asserts `PUBK_AUTHORIZED`
  **before** `RSA_VERIFY_OK`, and the ordering is the assertion: `expect()` consumes the
  stream, so swapping the two library checks fails this test.
- `test_bootcode_oca_negative.py` — 9 tamper cases plus rotate-to-backup, device-side
  revocation, and security-version rollback.
- Deleted `test_bootcode_ot_negative.py` (Grendel format) and the permanently-skipped
  `test_full_boot_to_bl1` placeholder, whose stated blocker the OCA positive tests resolve.
- New fuse maps `oca_key_revoked.yaml`, `oca_secver_set.yaml`.

### Three ROM fixes the new tests forced

1. **Recovered slot failures were reported as production `ERROR`.** A primary-slot failure the
   backup recovers from is not a boot failure, but the ROM emitted `ERROR` for it, so a
   successful rotate looked like a failed boot to anything watching the stream. Per-slot
   verdicts are now `WARN`; on exhausting every slot the last verdict is re-reported as
   `ERROR` before `MANIFEST_LOAD_FAILED`, decoded from the `oca_result_t` in the error's low
   byte so nothing extra is tracked.
2. **`MANIFEST_PRIMARY`/`MANIFEST_BACKUP` was keyed on the retry counter, not the slot.** With
   `rotate_update` the ROM read 0x41000 while printing `MANIFEST_PRIMARY`. Pre-existing in the
   Grendel loader; DV asserts on these markers.
3. **`rom_err_fail()` truncated 32-bit subsystem errors into the `SEP_MSG_*` space.**
   `MANIFEST_ERR=0x00030012` surfaced as status `0x0012` = `SEP_MSG_BL1_SIZE_INVALID` on a
   *payload-hash* failure — an actively misleading line in the stream DV asserts on. Now
   suppressed for codes with a subsystem in the upper half; those paths already report a
   specific ERROR, and the full 32-bit code still reaches the mailbox.

### Expectations I got wrong (the ROM was right)

Worth recording, because each is a fact about the check ordering:
- `manifest_length` is checked **before** `manifest_hash` — framing precedes integrity — so a
  bad length reports the length, not the hash it also breaks.
- Retagging a classic body as `OCAP` fails on the **trailer**, not the length: the magic
  selects the variant, then the trailer is sought at the PQC offset with the PQC marker.
- A negative `payload_offset` must be out of region from **both** slots. `-0x10000` is out of
  range from the primary at 0x1000 but resolves to 0x31000 from the backup at 0x41000 — in
  region, so that slot reads real flash and fails the payload hash instead.

### Not covered, and why
- **Identity constraints** (`chiplet_id`/`package_id`/`system_id`): the VP eFuse model still
  has `RESERVED_*` where the RDL defines `SEP_CHIPLET_ID`/`SEP_SIP_ID`/`SEP_SYS_ID`. Reads
  return zeroes rather than faulting, so a negative identity test would *pass for the wrong
  reason* and the accept direction cannot be tested at all. Deliberately not written until the
  model re-sync lands.
- **OTP-anchored key authorization** is testable (the model's `PUBLIC_KEY_0/1`, `SIP_PUBK`,
  `SYS_PUBK` land on the right offsets after the offset fix) but is not yet covered; only the
  ROM-digest slot is exercised.

---

## Phase 5b — OTP-anchored key authorization, and a slot-numbering bug (2026-08-26)

**52 passed, 0 failed** (~2:41). Writing these tests found a real bug in
`plat_is_key_authorized()`.

### The bug: select and revoke disagreed about which key a bit names

`public_key_select_classic` and `CHIPLET_PUBK_REVOKE` index the **same** key entries — the
RDL says so explicitly on that register ("each key entry maps to one bit here"). The
authoritative map:

| Bits | Key |
|---|---|
| 0–7 | ROM chiplet-creator classical (0,1 = dev keys) |
| 8–15 | ROM chiplet-creator PQC |
| 16 / 17 | `CHIPLET_PUBK_HASH0` / `1` |
| 18 / 19 | `CHIPLET_PUBK_PQC_HASH0` / `1` |
| 20 / 21 | `SIP_PUBK_HASH0` / `SIP_PUBK_PQC_HASH0` |
| 22 / 23 | `SYS_PUBK_HASH` / `SYS_PUBK_PQC_HASH` |
| 24 / 25 | `SIP_PUBK_HASH1` / `SIP_PUBK_PQC_HASH1` |
| 31–26 | reserved |

Phase 3b invented its own: `slot >= PUBK_SEL_NUM_ROM_KEYS` (6) meant OTP, so bits 6–9 were
mapped to the four banks. Bits 6–7 are actually ROM *classical* slots and 8–9 ROM *PQC*.
Consequences, both bad:

- A manifest selecting bit 6 would be authorized against `CHIPLET_PUBK_HASH0` while the
  revocation check tested bit 6 — a ROM dev key. **Authorization and revocation would refer
  to different keys, which makes revocation decorative.**
- The real OTP slots (16+) were rejected as unknown, so the OTP anchor path was unreachable.

Fixed: the slot map now follows the RDL, PQC slots are refused outright (nothing here
verifies a PQC signature, so authorizing one hands a key to a verifier that cannot check it),
reserved bits `[31:26]` are refused, and ROM slots beyond `NUM_PUBLIC_KEY_DIGESTS` are treated
as unprovisioned rather than valid. `SIP_PUBK_HASH1` (bit 24) is mapped for silicon
correctness but is **not exercisable on sep-vp** — its bank at 0x260 is in the model's stale
region.

ROM 38976 → **39104 B**.

### Tests
New `configs/oca_otp_key_boot_test.yaml` + `_image.yaml` (`public_key_select_classic: 0x10000`
= bit 16), Makefile target `oca_otp_key_boot_spi`, and three fuse maps. Same dev0 signing key
as the ROM-anchored image, so the anchor's *location* is the only variable.

- `test_otp_anchored_key_boots` — resolves the bank and digests the 384-byte modulus (a
  blob-wide digest would never match).
- `test_otp_anchored_key_wrong_digest_refused` — map identical but for one flipped bit in
  word 0, isolating the comparison from the plumbing.
- `test_otp_anchored_key_unprovisioned_refused` — an erased bank authorizes nothing. The
  state every part ships in, and the one an attacker would most like permissive.
- `test_otp_anchored_key_revocation_uses_the_same_slot_numbering` — provisions the anchor
  **and** revokes slot 16. Expects `REVOKED_KEY`, which also confirms authorization ran first
  and passed. **This is the case that catches a numbering disagreement.**

**Verified the tests actually catch it:** reintroducing the bits-6–9 mapping fails
`test_otp_anchored_key_boots` and the revocation-numbering test (2 failed, 2 passed). The
wrong-digest and unprovisioned cases still pass under the bug, which is why the
revocation-numbering case is the one worth keeping honest.

Digest words for the maps are generated, not hand-written: `word[0]` holds bits[31:0], so each
is four consecutive digest bytes read little-endian. Getting that backwards yields a
mismatched anchor with no hint as to why.

---

## Follow-up: reconcile the boot ROM specification with the implementation

**Not done. Needs its own pass before this work is considered complete.**

This change altered ROM behaviour well beyond swapping the manifest format, and the
specification has not moved with it. The boot sequence lives in
**`hw/sys/sep/doc/cpu.adoc`** (the "Load second stage bootloader firmware BL1" /
"Verify integrity of BL1 firmware image" section, around lines 105-145). Related:
`attack_countermeasures.adoc` and `lifecycle_controller.adoc` also reference the manifest.

`hw/sys/sep/doc/periphs.adoc` is **already correct** on the key-slot bit map (lines 147-149)
and needs nothing — it was the source of truth that revealed the Phase 5b bug.

What the spec currently says versus what the ROM now does:

| Area | `cpu.adoc` today | Implementation |
|---|---|---|
| **Trust anchor** | Absent. Says verify "using its public key also stored in the manifest" — describes exactly the self-signed-verifies gap | `is_key_authorized` against a ROM digest table or an OTP hash bank, **before** any public-key operation. The single most important omission |
| **Key selector numbering** | Not stated | `public_key_select_classic` is a 128-bit bitmap sharing `CHIPLET_PUBK_REVOKE`'s numbering (bits 0–7 ROM classical, 8–15 ROM PQC, 16+ OTP banks). Worth stating in the boot flow, not only on the fuse register |
| **Check order** | Anti-rollback described *after* signature verification | authorization → revocation → anti-rollback → signature → anti-rollback re-check. Rejecting before the modexp is deliberate and is a spec-level property |
| **Revocation** | Not mentioned in the boot sequence | `CHIPLET_PUBK_REVOKE` checked against the manifest's own revoke bitmap, before the signature |
| **Payload encryption** | Only "payload hash/length" | AES-256-CBC (and 128), key derived from `CLASS_KEY` via SP 800-108r1 CTR-HMAC-SHA-256 over the Key Manager's 192-byte block. Unprovisioned `CLASS_KEY` is a distinct refusal, not a decrypt failure |
| **Exponent** | "expected to be a short value such as 2**16+1" | **Requires** exactly 65537 and rejects anything else, because the OTBN app is `MODE_RSA_3072_MODEXP_F4` and never reads the key's exponent. A soft expectation in the spec is a hard constraint in silicon |
| **Key provisioning** | Public key provisioned "into Key Manager via software write port" | Modulus and signature passed straight to the OTBN RSA app. Either the spec is aspirational or the ROM is wrong — **resolve which** |
| **What is hashed** | "hash digest of {BL1 firmware, OTP fuse profile}" | Signed region, payload, `payload_hash_chain`, and every TOC entry hash — all by the OCA library |
| **Demotion** | — | Now one 16-bit `demotion_control` field (VALID/ENABLE per stage) rather than the old selector-bit plus `flag_args` split |
| **Status semantics** | — | A slot failure the backup recovers from is `WARN`; `ERROR` means every slot is gone. `rom_err_fail()` no longer emits truncated subsystem codes into the `SEP_MSG_*` space |
| **PQC** | — | `OCAP` geometry is parsed; PQC signatures and PQC key slots are refused as unsupported rather than silently accepted |
| **Crypto block bring-up** | — | Every crypto IP comes out of hard reset held by `SEP_RESET_CTRL.SW_RESET_N` (defaults to 0) and the ROM must clear its bit before use — `otbn_init()` for RSA, `aes_init()` for decryption. Added after the AES call site was found missing in Phase 6b; worth stating as a required step rather than leaving it to be rediscovered |
| **Entropy prerequisite** | — | **See below — this is a system question, not a doc edit** |

Two of these are worth treating as spec *decisions* rather than documentation edits: the Key
Manager provisioning path (spec and ROM genuinely disagree), and whether requiring e=65537
is the intended long-term constraint or a temporary consequence of the OTBN app build.

### The entropy prerequisite is now a two-block problem (raised by Phase 6b)

The ROM's crypto depends on an entropy chain **nothing in the boot flow brings up**. This was
already an open question for OTBN (`FIXME(SEP-DV)` in `testlists/cpu.toml`, and
`.dv/artifacts/SEP_ROM_SECURE_VS_NONSECURE_BOOT.md`); Phase 6b established it applies to AES
as well:

- **OTBN** parks in `UrndRefresh` until EDN reseeds it, so RSA verification never starts.
- **AES** does not report `STATUS.IDLE` until its masking PRNG is reseeded, so payload
  decryption never starts.

Both are worked around in simulation by `+sep_crypto_edn_force`, which grants the EDN
handshakes directly and is tagged `dv_shortcut` precisely so it cannot be mistaken for
coverage. The real `entropy_source -> CSRNG -> EDN` path is not exercised by any ROM test,
and the ROM contains no code to configure it.

So the question is not "should the spec mention entropy" but **who is responsible for
bringing up DRBG/EDN before the boot ROM runs crypto** — the ROM itself, hardware
auto-init, or an earlier agent.

### Answered: it is firmware's job, and the ROM is the firmware (2026-08-28)

`hw/ip/drbg/doc/architecture.adoc` and the existing DV driver settle this. **Nothing
auto-initializes the chain**, and every stage of it is off at reset:

| Stage | Reset state | Evidence |
|---|---|---|
| Entropy FIFO clock gate | gated off | `SEP_CLOCK_GATE_CTRL` reset `0x001F0021`, needs bit 10 |
| TRNG source select | **`0x3` = external TRNG**, not internal DRBG | `SEP_EXT_TRNG_SRC_SEL` |
| ESRC ring oscillators | generators off | `SEP_ESRC_RING_OSC_ENABLE` |
| CSRNG `CTRL` | MuBi4False — disabled | `csrng_reg_top.sv:596` `RESVAL(4'h9)` |
| EDN `CTRL` | disabled | same MuBi4 convention |

The DRBG doc is explicit that CSRNG "processes firmware-issued commands (instantiate,
reseed, generate, uninstantiate) through TL-UL" and that EDN needs "mode configuration"
before it automates anything. Its registers sit at CSRNG `0x1091_5000` / EDN `0x1091_5800`
behind a 64-bit AXI-Lite lane adapter — reachable from the SEP CPU, i.e. from the ROM.

**A known-good sequence already exists**: `hw/sys/sep/dv/fw/drivers/sep_entropy.h`, ~14 MMIO
writes in three phases (configure with generators off → start generators → settle → enable
EDN last, in that order). Its header states it is "the firmware-replicable equivalent of the
reference UVM bring-up ... **NOT a force**".

Two consequences:

1. **`+sep_crypto_edn_force` is masking a real ROM gap, not a testbench limitation.** The SEP
   boot ROM is the first and only firmware to run before crypto, so if anything is to bring
   the chain up before RSA and AES, it must. It does not. On silicon, secure boot and
   encrypted boot would both stall — OTBN in `UrndRefresh`, AES never reporting `IDLE`.
2. **`+esrc_noise_force` is a much weaker shortcut and would still be needed in sim**, but
   only because ESRC ring oscillators do not self-oscillate in simulation. The
   DRBG/CSRNG/EDN math above it is real. Porting `sep_entropy.h` into the ROM would let the
   ROM tests drop `+sep_crypto_edn_force` for `+esrc_noise_force` and exercise the actual
   entropy path.

One design question remains, and it is a real one rather than a documentation gap:
`EXT_TRNG_SRC_SEL` **resets to external TRNG**, which suggests the intended production
entropy source may not be the internal DRBG at all. That changes which stages the ROM must
program — but not the conclusion, since CSRNG and EDN need firmware enablement on either
path.

**Recommended follow-up (new work, not part of this integration):** add an entropy bring-up
step to the ROM before the first crypto use, modelled on `sep_entropy.h`, and confirm with DE
which TRNG source production intends.

---

## Phase 5c — SMC-SRAM path and identity constraints (2026-08-26)

**56 passed, 0 failed** (~2:54). Both required two more `tt-oca-harness-model` commits.

### SMC-SRAM load path (`ea2a6c98`)

The second in-scope load path had **no positive coverage and no way to get any**: the platform
seeded the SMC→SEP handshake (`MANIFEST_READY`, `MANIFEST_ADDR = 0x2000`) so the ROM would not
hang, but nothing could put a manifest at that address, so the path was only ever exercisable
in its failure direction.

Added `smcSramBackdoorFile` / `smcSramBackdoorOffset`, mirroring `spiBackdoorFile`. The offset
defaults to the same 0x2000 the handshake publishes — staging anywhere else is invisible to
the ROM, which reads `smc_sram_base + scratch[8]`, and two independently-defaulted constants
would drift. Skipped in forward (SMU) mode, where a real SMC owns staging.

Harness: `SimConfig.smc_sram_image`. Note it takes a **bare bundle**, not a combined SPI
image — this path resolves the payload from the manifest's own `payload_offset`, which for a
bundle is exactly `body_size`, so the slot offsets a combined image adds are meaningless here.
New `oca_smc_bundle` make target.

Two tests: secondary chiplet, and the recovery strap on a *primary* part (distinct, because
that part could have booted from SPI — it proves the strap reaches the load-path decision
rather than only being reported).

### eFuse second-half re-sync (`a92d42a6`)

`57892dfe` aligned everything up to `CHIPLET_PUBK_HASH1`; beyond that the model was still a
whole RDL revision behind — eight generic `RESERVED_*` blocks where the RDL defines eighteen
named registers. Replaced with the real set and rebuilt `k_lock_regions` from the RDL's own
write-lock bit positions. **All 50 registers below 0x400 now match the generated header.**

Two things this was hiding:
- `SEP_CHIPLET_ID` / `SEP_SIP_ID` / `SEP_SYS_ID` had no registers and no params, so identity
  constraints were untestable. Reads returned zeroes rather than faulting — so a
  reject-direction test would have passed *for the wrong reason*, which is why none was written.
- Every reserved block's lock bit was invented and collided with a real RDL assignment.

Renames to match the RDL, the old names being actively misleading about which key a bank
holds: `PUBLIC_KEY_0/1` → `CHIPLET_PUBK_HASH0/1`, `SIP_PUBK` → `SIP_PUBK_HASH0`, `SYS_PUBK` →
`SYS_PUBK_HASH`. `sepvp/fuses.py` accepts both spellings so existing TOML keeps working.
`SPARE0..7` are deliberately left out of the lock table: their locks live in `LOCKS_SPARE`,
which the model has no plumbing for, and aiming them at a free `LOCKS` bit is what produced
the collisions being fixed.

### Identity constraint tests
`configs/oca_identity_boot_test.yaml` binds the manifest to `chiplet_id {0: 0xDE, 1: 0xAD}`
(sparse form — unselected bytes are the producer's `0xA5` filler, so the device fuse must read
`DE AD` then thirty `0xA5`). Both directions covered: matching part boots, one-byte-different
part is refused with `INVALID_CHIPLET_ID`. Having the accept direction is the point — a
reject-only test also passes on a device that reports no identity at all.

### Still not covered on the VP
- `SIP_PUBK_HASH1` (key slot 24) now has a register but no test.
- PQC-variant images (`OCAP` geometry with a classical signature), unsupported signature types
  (ECDSA), DER encodings, AES-128 payloads, and multi-image TOCs where BL1 is not first.
  All are reachable — configs and a make target are the only work.

---

## Phase 5d — remaining VP coverage (2026-08-26)

**64 passed, 0 failed** (~2:32). VP coverage is complete for everything reachable without
further model work.

**Makefile made pattern-driven first.** Twelve images with a copy-pasted four-variable block
each was untenable. `OCA_IMAGES` plus a static pattern rule means a new image is one line and
two configs — there is no per-image recipe to copy and get subtly wrong. Removed ~60 lines
while adding seven images.

New images and what each covers:

| Image | Covers |
|---|---|
| `pqc_boot` | OCAP geometry (36864 B body) with a **classical** RSA-3072 signature — the "parse all variants, verify RSA-3072 only" scope in one test |
| `ecdsa_boot` | ECDSA P-256: a legal OCA primitive this ROM cannot verify → clean refusal |
| `der_boot` | DER public key → refused; ROM parses RAW only |
| `aes128_boot` | The AES-128 half of the cipher support |
| `sip_key_boot` | Key slot 24 (`SIP_PUBK_HASH1`) — a second OTP anchor family |
| `multi_image_boot` | Three-image TOC with BL1 **last**; the handoff must search by type, not take index 0 |
| `no_bl1_boot` | Valid manifest with no bootable stage → clean refusal |

Plus `test_unsigned_image_refused_on_a_secure_lifecycle`, needing no new image: a PROD part
refuses an unsigned manifest on the **device's** insistence via `is_secure_boot_active()`.
Every other signed test has the manifest asking for verification, so none of them would notice
if the device's opinion were ignored.

### Diagnosis fix the probing exposed

ECDSA, DER and unsigned-on-PROD all reported the same `SEP_MSG_INVALID_KEY_HASH`. Correct
ordering — authorization refuses the primitive before any crypto — but poor triage, since
"invalid key hash" is the one thing none of them is. The library gives the callback a single
failure code, so the fix is console markers: `PUBK_NO_SIGNATURE`, `PUBK_ALGO_UNSUPPORTED`,
`PUBK_ENCODING_UNSUPPORTED`, `PUBK_FIELD_TOO_SMALL`. The tests assert on those, so the three
cases are distinguishable despite sharing a status code.

Expectations were **probed before being written** this time rather than guessed — the earlier
phases lost a round trip each to reasonable-but-wrong assumptions about check ordering.

ROM 39104 → **39256 B** (~25 KiB headroom).

### VP coverage now
Both load paths (SPI, SMC SRAM); unsigned / signed / encrypted (AES-128 and 256); ROM-anchored
and two OTP-anchored key families; identity constraints both directions; lifecycle-enforced
secure boot; revocation (manifest and device side, and that select/revoke share a numbering);
anti-rollback; variant dispatch; unsupported algorithm and encoding; multi-image and missing-BL1
TOCs; nine framing/geometry tamper cases; slot rotation and backup fallback.

**Not reachable on the VP**: natively PQC-signed manifests (the library implements no PQC
verification, so this is a scope boundary rather than a gap), and `oca_commit_security_state()`
(no OTP programming path in the ROM — a deliberate scope decision).

---

## Phase 5e — model test suite fixed; drift guard added (2026-08-27)

Prompted by asking whether anything in the model repo catches RDL drift.

### Answer: nothing did, and the test suite made it worse

The model has a thorough eFuse suite (2,200 lines, ASAN/coverage modes, **run by CI**), but
`test/inc/efuse_basetest.h` kept its **own hand-copied offset table** — a fourth duplicate
after `efuse_register.h`, the `efuse_base.h` constructors and `efuse.cpp`'s lock table. It had
gone stale unnoticed, still placing `CLASS_KEY` at 0x064. Model and tests were self-consistent
and **jointly wrong**, which is precisely why the original drift survived a suite this large.
Any test reading the model's own header is asking the model whether it agrees with itself.

### My commits had broken it (`34dc7483`)

Confirmed by running it: would not compile, then 22 failing assertions. Not submittable, since
CI runs it. Fixed by deleting the duplicated offsets and deriving everything:

- `.preload` images addressed the array by **literal word index** (LC_STATE word 2,
  TRANSIENT_RMA_EN 4, token digests 9-16 and 17-24) — all a word out, which is what made a
  dozen unrelated *lifecycle* assertions fail with LC_STATE reading 0.
- OTP commands used **literal bit addresses** (LC_STATE 64, its RMA bits 65/66, BL1_VERSION
  34*32, CHIPLET_UID 1600).
- One test programmed "a word nothing else uses" by naming `RESERVED_2`, a block the map no
  longer has.

**And it exposed a real model bug:** `LC_STATE_BIT_POSITION` was a literal 64, justified in its
own comment as *"LOCKS is 64 bits wide and comes first"* — reasoning that overlooks
`LOCKS_SPARE`. With the map corrected that pointed RMA advance gating at `SBOOT_DIS`'s bits, so
a matching RMA token no longer authorised the transition it exists to authorise. A test-suite
fix that turned up a functional defect, which is the argument for not deferring these.

**115/115 unit + 8/8 coverage. VP builds; harness suite 67 passed.**

### The guard: `virtual_platform/tests/test_efuse_map_drift.py`

Compares the model's header against the generated `sep_addr.h`. It lives in **this** repo
because the model repo does not contain the RDL — this is the only place both exist. Three
checks: every RDL register exists in the model, offsets match, and the shadow region is
ascending and starts at 0.

**Verified it catches the real thing** by pointing the submodule back at `57892dfe~1`: 2 of 3
fail, naming the missing registers and every off-by-4. Passes on the current branch.

Worth noting for the PR: even with the model suite green, it still cannot catch RDL drift.
That needs this guard, or the model repo vendoring a generated offset manifest.

### Upstream state
| Repo | Branch | Commits |
|---|---|---|
| `tt-boot-manifest` | `cmccoy/root_key_authorization` | 1 |
| `tt-oca-harness-model` | `cmccoy/efuse_map_offsets` | 4 (3 eFuse + 1 SMC) |

The SMC commit (`ea2a6c98`) is confirmed independent: cherry-picks onto `main` clean, builds,
and both SMC-SRAM boots reach BL1 without any eFuse commit present. So: **eFuse PR** =
`57892dfe` + `a92d42a6` + `34dc7483` (sequential, one PR); **SMC PR** = `ea2a6c98` alone.

---

## Phase 6a — DV repair, validated in simulation (2026-08-27)

**All four DV ROM tests PASS under VCS**, and the VP suite is still 67 passed.

| Test | Sim time | Result |
|---|---|---|
| `sep_rom_ot_secure_boot_test` | 868 s | PASS |
| `sep_rom_ot_dma_boot_test` | 342 s | PASS |
| `sep_rom_ot_pio_boot_test` | 427 s | PASS |
| `sep_rom_non_secure_boot_test` | 243 s | PASS |

### Getting simulation running

`tt-oca-harness-nonfree` supplies the tool env. Notes for anyone repeating this:

- **Xcelium does not work here.** 24.03.003 and 25.03.001 both die in elaboration with
  `XMERROR_7476` / `CUVCGF: Code generation for top.axi_sim_mem:sv failed` — a tool-side
  code-gen failure, not a testbench problem.
- **VCS needs a second venv.** `run_dv.py` uses cocotb's classic make flow for VCS
  (`cocotb.runner` has no VCS backend) and that flow is pinned to cocotb 1.9.x, because
  cocotb 2.0's `load_entry(argv)` signature is incompatible. The repo's `.venv` is
  deliberately on `cocotb>=2.0,<2.1`, so `_vcs_cocotb_python()` looks for a separate
  `venv/bin/python`. Created it (`/venv/` is already gitignored):
  `uv venv venv --python 3.11 && uv pip install --python venv/bin/python 'cocotb>=1.9,<2' 'pyuvm>=3,<4' 'cocotbext-axi>=0.1.24,<0.2' 'cocotbext-jtag>=0.4.0,<0.5'`
- Run: `source nonfree/setup_env.sh`, then
  `python3 tools/dv/run_dv.py --dut sep --items <test> --tool vcs --stage flist --stage
  c_compile --stage hdl_compile --stage sim`. **`--items` does not accumulate** — repeat
  invocations, one test each; a comma list is rejected.

### The regression, confirmed then fixed

Simulation confirmed the prediction before any repair: the ROM read the Grendel image and
reported `MANIFEST_ERR=0x00030002` (`OCA_FAIL_MAGIC`) on **both** slots, then
`MANIFEST_ALL_FAILED`. Four DV tests were feeding a Grendel image to an OCA-only ROM.

Repairs:
- `sep_rom_ot_dma_boot_test`: images → `oca_non_secure_boot.bin` / `oca_secure_boot.bin`.
- `sep_rom_ot_secure_boot_test`: `RSA_VERIFY_START`/`SIG_VALID`/`CRYPTO_VALIDATE_OK` (all from
  the deleted `manifest_crypto.c`) → `PUBK_AUTHORIZED`/`RSA_EXEC`/`RSA_VERIFY_OK`. Docstring
  flow diagram rewritten for the staged sequence. `PUBK_AUTHORIZED` is the one worth having
  beyond the RSA pair: a boot verifying a signature by a key nothing vouched for would print
  `RSA_VERIFY_OK` and not it.
- `sep_rom_non_secure_boot_test`: `MANIFEST_HASH_OK`/`PLD_HASH_OK` → `MANIFEST_OK`/`PAYLOAD_OK`.
- `sep_rom_ot_pio_boot_test`: nothing — it inherits.
- New `oca_smc_mem.hex` (Makefile) for `+sep_smc_mem_hex`, built from the **combined** image,
  not the bundle: the SMC responder publishes `MANIFEST_ADDR = 0x1000`, which is exactly where
  the combined image puts the manifest. Rebasing the bundle would place it at the window base
  and the ROM would read 0x1000 bytes past it.
- `sep_sim_cfg.toml`: `oca-images` added to the non-OT `boot_rom` argv, plus the new output on
  both build targets.

### A real ROM bug the DV suite caught that the VP suite could not

After the images were repointed, the signed test still failed — on a *forbidden* marker:
**the ROM printed `SBOOT_OFF` on a signed boot.**

`bl0_state.secure_boot` was only ever read (`rom_main.c:346`) and never written: the Phase 3
rewrite dropped the assignment, since the library keeps the determination in a validation
context that does not outlive `try_manifest_slot()`. So the flag was permanently false, and a
verified boot reported itself as unverified — visible to BL1, which also reads `bl0_state`.

The VP suite could not have found this. Its signed test asserts `PUBK_AUTHORIZED` and
`RSA_VERIFY_OK` are *present*; nothing asserted `SBOOT_OFF` was *absent*. DV's
`forbidden_markers` mechanism is what caught it — a genuine argument for keeping both suites
with different assertion styles rather than mirroring one in the other.

Fixed by copying `vctx.secure_boot_enabled` into `bl0_state.secure_boot` after validation.
ROM 39256 → **39280 B**.

Also added `PAYLOAD_OK` to the ROM console: DV asserts on console strings, and the payload
check had no console evidence after `PLD_HASH_OK` went away with the Grendel loader.

### Phase 6 remaining
New OCA-specific DV cases (encrypted payload with a CLASS_KEY eFuse image, a tamper negative,
OTP-anchored key) are still to write. Simulation works now, so these can be validated rather
than written blind. Note `dv_sim_prestage.py`'s registry must mirror any test's
`select_efuse_image` kwargs — the RTL `$readmemh` fires at t=0, before cocotb runs.

---

## Phase 6b — New OCA DV tests, and two real bugs they found (2026-08-28)

Three new simulation tests, all validated under VCS. The encrypted case found a
genuine ROM bug and a genuine testbench gap; neither was visible on the VP.

| Test | Sim | What it proves |
|---|---|---|
| `sep_rom_oca_encrypted_boot_test` | 938 s | AES-256-CBC payload decrypted with an OTP-derived key |
| `sep_rom_oca_otp_key_boot_test` | 864 s | RSA verified against a CHIPLET_PUBK_HASH0 anchor, not a ROM digest |
| `sep_rom_oca_tamper_test` | ~1050 s | A tampered manifest is refused in **both** slots |

### Bug 1 (ROM): `aes_init()` was never called

`aes_init()` was defined and declared and had **no call site**. `SEP_RESET_CTRL.SW_RESET_N`
defaults to 0 — every IP held in software reset — so the AES block sat in reset and
`STATUS` read back `0x00000000` forever. `aes_driver.c`'s first `wait_idle()` then burned
its full 1M-iteration timeout.

The parallel was already in the tree and the AES path had simply missed it:
`rsa_verify.c:132` calls `otbn_init()` before driving OTBN, for exactly this reason. Fixed
by calling `aes_init()` in `plat_decrypt_payload()` before the KDF.

Invisible on the VP because the model does not implement the reset gating — the modelled
AES answers whether or not it has been released.

### Bug 2 (DV): AES is EDN client 0 and nothing granted it entropy

With the reset released, `STATUS` became `0x00000000` → still not idle. The AES masking
PRNG wants an EDN reseed before the core reports `IDLE`, and `+sep_crypto_edn_force` only
forced clients [2]/[3] (OTBN RND/URND). AES is client [0] (`sep_crypto.sv`, `aes_wrapper
.edn_req_o`). Extended the shortcut to cover it; `STATUS` went to `0x00000011`
(IDLE | INPUT_READY) and the decryption completed.

KMAC ([1]) deliberately left unforced — nothing in the boot flow uses it. The ROM's KDF
runs on the separate HMAC core, which needs no EDN; that path completed in simulation
before either fix.

The AES KAT tests take the other route (`+esrc_noise_force`, the real entropy chain). Not
available here: it needs software to bring up entropy_source/CSRNG/EDN and the boot ROM has
no such code — the same reason the OTBN shortcut exists.

### Two process notes that cost real time

- **`--rebuild` does not rebuild the DUT.** The cached simv is keyed on the flist, not on
  file contents, so a `tb_top.sv` edit was silently ignored across three full runs
  (`hdl_compile` "PASS" in 1.6 s, and the old `$display` banner still in the log). The EDN
  fix looked ineffective when it had simply never been compiled. `rm -rf
  hw/sys/sep/dv/build/rom_boot/cocotb/vcs/rom_boot/<hash>` is what actually forces it.
  Check a TB change reached the simv by grepping the log for its own banner text.
- **Diagnose with a register read, not a hypothesis.** Printing `AES_STATUS` once turned
  "AES hangs" into two distinct, separately-fixable faults. That print now lives on the
  `wait_idle()` timeout path (`AES_IDLE_TIMEOUT=<status>`), where `0` means nothing is
  answering and non-zero-not-idle means the core is alive and stuck.

### A wrong assumption the tamper test corrected

The scoreboard gate for a refused boot was first written as "`fw_done` must stay low".
That failed the test even though the ROM had behaved perfectly: both slots rejected with
`MANIFEST_ERR=0x0003000d` (`OCA_FAIL_MANIFEST_HASH`, exactly as predicted — the hash is
checked before the signature), then `MANIFEST_ALL_FAILED`, then `rom_err_fail()` reported
the failure through the mailbox. So `fw_done` asserts with `fw_pass` low.

The correct gate is on **`fw_pass`**, not `fw_done`: only BL1 can produce a PASS, so only a
PASS proves the ROM handed over control. The test now also asserts `fw_done` positively —
a refusal nobody is told about would be a worse outcome than one that is.

`SepBootScoreboard.expect_fw_pass` (default True) carries this; `_MIN_DISTINCT_PCS` stays in
force either way, which is what separates a deliberate refusal from a ROM that crashed on
its first instruction.

### Also changed
- `PAYLOAD_OK` added to the shared `required_markers` in `sep_rom_ot_dma_boot_test`, so all
  four inheriting tests now assert the payload was verified rather than merely staged.
- `make_efuse_image()` and `max_run_cycles` promoted to class data on that base, so a
  subclass can provision OTP banks or trim the cycle budget without restating the scenario.

### Phase 6 remaining
Nothing blocking. Optional further negatives now cheap to add on this scaffolding: an
encrypted image on a part with no CLASS_KEY (`DECRYPT_CLASS_KEY_EMPTY`), a revoked root key,
and a security-version rollback — all three already covered on the VP.

### Regression after these changes
The ROM (`aes_init()` call + `AES_IDLE_TIMEOUT` diagnostic), the shared DMA base test, the
boot scoreboard and `tb_top.sv` all changed, so everything downstream was re-run:

- **DV, all 7 ROM tests PASS**: the 4 pre-existing (`sep_rom_ot_secure_boot_test`,
  `sep_rom_non_secure_boot_test`, `sep_rom_ot_dma_boot_test`, `sep_rom_ot_pio_boot_test`)
  plus the 3 new ones.
- **VP, 67 passed** — unchanged.

ROM text 40428 → 40808 B (+380 for the `aes_init()` call site and the timeout diagnostic),
still ~23 KiB under the 64 KiB ceiling.

---

## Phase 7 — per-slot ROM key coverage (2026-08-28)

Prompted by asking how many ROM-embedded root keys we support. **Answer: 6, confirmed**
(`PUBK_SEL_NUM_ROM_KEYS 6`; slots `dev0 dev1 prod0 prod1 prod2 prod3`). The RDL reserves
bits [7:0] for ROM classical keys, so the ROM pins 6 of 8 and slots 6-7 are correctly
refused as `PUBK_SLOT_UNPROVISIONED`.

**The gap was coverage, not capability.** Only slot 0 had a digest; slots 1-5 were NULL and
refused everything, so five of six anchors were untested and there was **no ROM-key
revocation test at all** — the revocation tests added in Phase 5 covered OTP anchors only.

**VP suite 67 → 86 passed** (2:43). 19 new tests, 20 s for the subset — this is the kind of
matrix the VP is for.

### Six distinct keys, deliberately

Generated 5 new RSA-3072 test keys (all e=65537, as the OTBN app requires) in
`hw/sys/sep/bootrom/prod/tests/signing_keys/`, and regenerated `key_digests.c` across all
six slots. Slot 0's digest is byte-identical, so no existing test moved.

Kept out of the submodule on purpose: these are SEP-ROM slot-coverage keys, not producer
fixtures, and putting them in `tt-boot-manifest` would mean another upstream PR for something
only this ROM cares about.

**Each slot is signed by a different key, and that is the whole point.** With one shared key
a slot resolved off-by-one would still find a matching digest, every test below would pass,
and the suite would prove only that *some* digest matched. This is the exact failure the
Phase 5b bug had — authorization and revocation naming different keys.

### Three axes, 6 slots each

`virtual_platform/tests/bootcode/test_bootcode_oca_rom_keys.py`:

- **use** — each digest authorizes its own key, `PUBK_AUTHORIZED` before `RSA_VERIFY_OK`
- **revoke** — `CHIPLET_PUBK_REVOKE` bit N refuses slot N, as `REVOKED_KEY` *after*
  `PUBK_AUTHORIZED` (so "revoked" is distinguishable from "never recognised")
- **isolate** — revoking the five OTHER slots leaves slot N bootable

The **isolate** axis is the one that pins the numbering down. "use" and "revoke" can both
pass on a revocation check that is offset by one, or that ignores the slot index and refuses
on any non-zero bitmap; neither survives a case that revokes five specific bits and requires
the sixth key to still verify.

Revocation fuse maps are generated into `tmp_path` rather than committed as six near-identical
YAMLs — the only thing that varies is one derived integer, and computing it beside the
assertion keeps the slot-to-bit relationship visible. `SimConfig.otp` takes any path.

Plus `test_digest_table_pins_six_slots`, a premise guard: six entries, none NULL, six
*distinct* digests. Without it a slot regressing to NULL or two slots sharing a key would
leave the parametrised tests passing while proving nothing.

### Independent cross-check

The VP tests exercise the ROM. To decouple "is the image right" from "is the ROM right",
each image was also validated by the library's own CLI in storage-image mode against the
digest `key_digests.c` pins for that slot — a different implementation path (OpenSSL, not
OTBN/HMAC):

- all 6 slots **PASS** with their own digest
- all 6 **correctly REJECTED** when paired with a neighbouring slot's digest

That second run is what makes the first meaningful: it proves `--root-key-digest` is enforced
and the six keys really are distinct.

### Coverage still missing on ROM keys
- Slots 6-7 (the two the bitmap defines but the table does not pin) have no explicit
  `PUBK_SLOT_UNPROVISIONED` test. Cheap to add now the scaffolding exists.
- No test signs with key N while selecting slot M. The per-slot boots rule this out
  implicitly — a ROM ignoring the selector would fail 5 of 6 — but an explicit case would
  name the failure directly.
- These six are TEST keys sitting in slots named `prod0..prod3`. Harmless today (`TEST_BUILD`
  is hardcoded to 1 and unused in the source, so there is no production build path yet), but
  a real production build must regenerate `key_digests.c` from real PEMs. Worth a guard once
  a non-test build exists.

### Key naming: slots 0-5, no dev/prod (same day)

The `dev0 dev1 prod0 prod1 prod2 prod3` names were an internal security-policy holdover from
Grendel, and they implied a trust distinction **the ROM does not make**: all six are
ROM-embedded root keys, resolved identically by the same bitmap
(`public_key_select_classic` bits [7:0], which also index `CHIPLET_PUBK_REVOKE`). Renamed to
`rom_key0..rom_key5` — the slot number is the whole identity.

Touched: the six PEMs, `generate_key_digests.py`'s `SLOT_NAMES` (now `range(6)`),
`key_digests.h`, 18 configs (paths, `signing_key_name`, and prose), the Makefile, four VP
fuse maps, the DV OTP-anchor test, and the VP per-slot test (whose `SLOT_KEYS` map became
redundant — ids are now `slot0`..`slot5`).

**Nothing functional moved.** The key material is unchanged, so every digest is byte-identical:
`key_digests.c` differs only in array names, the ROM's `.rodata` is the same, and
`signing_key_name` never reaches the manifest (verified: 0 occurrences in the image, against
2 for `OCAHSEP`). Re-verified anyway — 6/6 slots PASS against their own digest and 6/6
rejected against a neighbour's; **VP 86 passed**.

### Key consolidation (same day)

The five new keys initially left the ROM's test keys split across two directories and two
repos — slot 0 in the `tt-boot-manifest` submodule, slots 1-5 local. Consolidated: a new
`dev0` was generated in `hw/sys/sep/bootrom/prod/tests/signing_keys/`, so **all six ROM test
keys now live in one directory in one repo**. The EC key for the ECDSA-refused image moved
too (P-256, matching the original) — leaving one key behind would have recreated the split
it was the point of removing.

`generate_key_digests.py --keys-dir tests/signing_keys/` now regenerates the whole table
from that one directory, instead of an explicit six-path `--keys` list.

**A new dev0 changes slot 0's digest, and that digest was hardcoded in five places.** Worth
recording because the grep that finds them is not obvious — the digest appears as
little-endian 32-bit fuse words, in both cases, so a case-sensitive search misses the DV
copy:

| Consumer | Form |
|---|---|
| `bootrom/prod/src/key_digests.c` | byte array (regenerated) |
| `virtual_platform/tests/fuse_maps/oca_otp_key.yaml` | LE words, lowercase |
| `virtual_platform/tests/fuse_maps/oca_otp_key_revoked.yaml` | LE words, lowercase |
| `virtual_platform/tests/fuse_maps/oca_sip_key.yaml` | LE words, lowercase |
| `hw/sys/sep/dv/cocotb/.../sep_rom_oca_otp_key_boot_test.py` | LE words, **uppercase** |

All four fuse maps now carry a note saying the digest derives from `key_digests.c` slot 0
and must be re-derived if the key is regenerated, rather than leaving the next person to
discover it from a failing OTP-anchor test.

`oca_otp_key_wrong.yaml` needed more than a substitution. It is built to differ from the
passing map in **exactly one bit** (word 0's LSB), which is what isolates the digest
comparison from everything else. A blind update would have left it holding the entire old
dev0 digest — still a valid refusal, but testing "all eight words differ" instead of the
one-bit case it documents. Rebased onto the new digest with the LSB flipped again.

`SEP_SIGNING_KEY` in the Makefile also moved, and its "it ships in the tt-boot-manifest
submodule" error text was corrected. The legacy Grendel `secure_boot_spi` target needed no
other change: it derives `ROOT=$(dir $(SEP_SIGNING_KEY))/../..` for the `$ROOT` expansion in
its config, and because the local directory keeps the same `tests/signing_keys` suffix, that
derivation still resolves correctly. Verified by building `pack-images secure_boot_spi`.

Re-verified after the swap: **6/6 slots PASS** against their own digest and **6/6 rejected**
against a neighbour's, via the library CLI; **VP 86 passed**.

Re-verified in RTL after the key swap: **all 7 DV ROM tests PASS**. The three that actually
depend on the new keys went first by design — `sep_rom_oca_otp_key_boot_test` (whose
`_CHIPLET_PUBK_HASH0_WORDS` had to be re-derived by hand), `sep_rom_ot_secure_boot_test` and
`sep_rom_oca_encrypted_boot_test` (both verifying against slot 0).

---

## Phase 8 — boot ROM specification pass (2026-08-28)

`hw/sys/sep/doc/cpu.adoc`, the "BL0 Secure Boot and BL1 Execution Unlock" section,
rewritten to match the implementation. The old text described a flow that no longer exists
and, more importantly, described one that would not have been safe: *"verify the BL1
signature ... using its public key also stored in the manifest"* — a self-signed-verifies
gap with no trust anchor anywhere in the sequence.

### What the section now says

Restructured into load / verify-manifest / load-and-verify-payload / select-BL1 / failure,
covering what was previously absent entirely:

- **Root key authorization before any public-key operation** — the selector resolves to one
  slot, the modulus digest is matched against a ROM digest or an OTP hash bank, ambiguous
  or unprovisioned selections are refused, and a signature check reached without it is
  refused. This is the drift that mattered.
- **The selector is a bitmap sharing `CHIPLET_PUBK_REVOKE`'s numbering** — one bit index
  names one key in both the manifest and the revocation fuse.
- **Check order stated explicitly**: authorization → revocation → anti-rollback →
  constraints → signature. Anti-rollback moved ahead of signature verification, where the
  implementation puts it, and the reason is given (do not spend a modexp on a manifest that
  is already superseded).
- **Revocation**, previously unmentioned in the boot sequence.
- **Payload encryption** — AES-256-CBC, key derived by SP 800-108r1 CTR-HMAC-SHA-256 from
  `CLASS_KEY`, integrity checked over ciphertext before and plaintext after, so a wrong-key
  decryption fails the plaintext check rather than executing.
- **Slot rotation**, the staged load (nothing outside the validated body sizes a later
  read), TOC-based BL1 selection, and WARN-per-slot / ERROR-on-exhaustion status semantics.
- **Crypto block bring-up** — `SEP_RESET_CTRL.SW_RESET_N` must be released per block before
  first use. Added after finding `aes_init()` had no call site (Phase 6b).
- A note that PQC variants are parsed but PQC signatures and key slots are refused.

### Recorded as open rather than settled

A new `[[bl0-open-items]]` subsection carries the three items that are design decisions, not
documentation fixes: the **Key Manager provisioning path** (spec and implementation
genuinely disagree), whether the **e=65537 constraint** is permanent, and the **entropy
prerequisite** (blocked on the hardware team).

### A larger gap found in a sibling document

`lifecycle_controller.adoc`'s "Secure-Boot Signing Model" describes a multi-owner scheme —
`REQUIRED_SIGNERS`, `REQUIRED_ALGS`, per-owner co-signatures, and demotion authorization
riding on them. **None of it is implemented.** Neither fuse field is referenced anywhere in
BL0 or the validation library, and although the OCA layout defines verifier-key and
co-signer entries, the library does not verify them.

Added a scoped implementation-status NOTE at the head of that section saying so and pointing
at what BL0 actually enforces (one root key, one signature). Deliberately did **not** rewrite
the model: it reads as intended design, and silently downgrading a spec to match today's
implementation would destroy the record of what was meant.

`attack_countermeasures.adoc` needed nothing — its "Class 2 Asset Manifest" is a different
artifact. `periphs.adoc` was already correct on the key-slot bit map.

### Verification
Docs could not be rendered here (`doc-html` uses the podman path, which is broken on this
box — the toolchain container uses the bwrap backend instead). Structure was checked
statically: no duplicate anchors, no heading-level skips, list nesting continuous and inline
markup balanced across both edited regions.

---

## Phase 9 — ROM specification cleanup, closing out the doc pass (2026-09-02)

The Phase 8 pass rewrote `cpu.adoc` and the `rom.adoc` status matrix, but three things were
left behind. This phase closes all three, and `rom.adoc` **renders clean for the first time**.

### The three answered open questions landed

`inmcm/doc-open-questions` (`57c2d1fe`) was cut from `a271bab2` and never made it onto the
integration branch. Cherry-picked as `d5af9dd3`: the F4 exponent constraint is **permanent**
(SEP-ROM-SB-100), the Key Manager has **no role** in secure-boot verification
(SEP-ROM-SB-110, and the old software-write-port text is explicitly withdrawn), and the
multi-owner signing model is **deferred, not abandoned**. `rom.adoc` carries **no
`*open question*` rows any more** — everything left is a tracked gap or a deliberate
deferral.

### The status matrix and the inline gap admonitions disagreed

The matrix was refreshed in Phase 8; **the `IMPLEMENTATION GAP` admonitions were not**. Five
of them still described pre-migration behaviour the matrix already declared *closed* — one
document contradicting itself, with the admonitions the more prominent half. Each was
re-verified against the code before being rewritten:

| Admonition | Claim | Reality |
|---|---|---|
| Packer backup offset | writes backup at `0x81000` | configs pack `0x41000` — **removed** |
| Secure boot, "four ways" | legacy `public_key_sel`, no manifest revoke, anti-rollback after signature, fuse addresses off by `0x10` | all four fixed; **only** the `unauthenticated_flags` escalation bit remains — narrowed to that |
| Demotion directive | `demotion_control` not parsed | parsed, BL1 `VALID` honoured; **only** BL2 `VALID` is still dropped — narrowed |
| Payload check order | decrypts before any hash, no chain | `oca_check_payload_at()` does ciphertext-first, chain, per-entry hashes — **removed** |
| Retry scope | crypto runs outside the retry loop | `oca_validate_manifest`/`oca_check_payload_at` are inside `try_manifest_slot()` — **removed** |

The `tt-boot-manifest TOC entry layout | *needs re-check*` row was the one the matrix flagged
as unverified. Re-checked, and it found the real bug below.

### `tbl:manifest_fields` was stale from offset 200 onward — including the signed region

The TOC entry table had been corrected in Phase 8; **the manifest field table had not**, and
it was still recorded against the pre-uprev `tt-boot-manifest`. Every offset from
`payload_encryption_control` on was low, by a drift that grows from 1 to 27 bytes:

| Field | Doc said | Actual |
|---|---|---|
| `payload_encryption_control` | 200 | **201** |
| `signature_type_classic` | 2075 | **2092** |
| `public_key_classic` | 2101, 526 B | **2120, 532 B** |
| `payload_hash` | 2748 | **2775** |
| **signed region** | **`[0, 3145)`** | **`[0, 3172)`** |
| `signature_classic` | 3145 | **3172** |
| `manifest_hash` | 3657 | **3684** |
| `unauthenticated_flags` | 3729 | **3756** |

The signed region is the consequential one: it is the exact byte range the RSA signature and
the manifest hash cover, it appeared in **nine** places across prose, two diagrams, the field
table and the security inventory, and anyone implementing a second consumer from this
document would have produced manifests that fail every signature check. Corrected against
`oca_layout_classic.h` / `oca_layout.h` and the producer's `constants.py`, which agree.
`signature_size_classic`, `public_key_size_classic` and `payload_hash_type` were missing
entirely and were added — the library's parser reads the first two.

### Entropy bring-up had no specification at all

`f25d43f0` implemented it and made it the Makefile default, but `rom.adoc` mentioned entropy
**only** in the status matrix, as a `*gap*` saying nothing in the boot flow performs it.
New `<<sec:entropy>>` section: the three-phase sequence (configure with generators off →
start generators and wait for the health test → enable EDN, then Instantiate) and why the
ordering is normative; the TRNG reset *pulse* rather than a release; the two one-way
configuration locks and the window each must land in; and the weak-symbol external-TRNG seam,
including that `EXT_TRNG_SRC_SEL` **resets to external**. Five new requirements
(SEP-ROM-ENT-010…-050). SEP-ROM-ENT-020 records the deliberate choice that a bring-up failure
is device-level and must *not* rotate to the backup slot.

### Verification — it renders now

`asciidoctor` is on this box at `~/bin`, so the Phase 8 note that docs could not be rendered
was wrong. **`rom.adoc` renders with zero errors and zero warnings.** (The full book emits 7
errors, all pre-existing `partial$sep/regs/gen/...` register includes that need the Antora
build; none from `rom.adoc`.)

Also checked mechanically: **all 136 cross-references resolve**, every table is cell-aligned
against its declared `cols`, and all 15 PlantUML blocks balance. Three defects that check
surfaced, all fixed:

- `<<tbl:sep_msg_codes>>` had **never** resolved — `gen_status_table.py` emits the table
  without the anchor `rom.adoc` refers to. Fixed **in the generator**, not the generated
  file, and regenerated (the only diff is the anchor line, confirming the checked-in file
  was current).
- `SEP-ROM-SB-045` was defined but **absent from the requirement index**. Added.
- The index said "All 86 tagged requirements"; there are now **94**. All 94 are defined,
  indexed, and resolve.

The key-authorization diagram was corrected while it was in hand: it showed the
security-version check only *after* signature verification (the ordering error D2 flagged in
the review, which the prose had fixed but the figure had not), and named "2 fuse digests"
where the implementation resolves **5** OTP hash banks.

### What is deliberately still open

Nothing in `rom.adoc` is an unanswered question. Fourteen rows remain non-closed and every
one is either a tracked implementation gap (PMP fence policy, stack canary at hand-off, the
`unauthenticated_flags` escalation bit, BL2 `VALID`, payload gap zeroing, fuse-sense
readiness, peripheral reset stub), work living on a branch (hand-off ledger, attestation
measurement), a placeholder that must be replaced before mask finalization (ROM key digests),
a provisional construction (payload KDF), or a stated deferral (PQC, multi-signer).


---

## Submodule switch: tt-boot-manifest → tt-oca-manifest (2026-09-03)

The tooling/library submodule moved to `tt-oca-manifest`. Every layout constant is unchanged
across the move, so nothing in this plan is invalidated. Details, verification and the
repo-name-vs-Python-package trap are recorded in `SEP_ROM_PLAN.md`.
