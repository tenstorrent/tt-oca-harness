# SEP Boot ROM — Security and Architecture Audit

| | |
|---|---|
| **Target** | `hw/sys/sep/bootrom/prod/` |
| **PR** | [#1590 `dv/sep: Integrate the SEP ROM OCA manifest`](https://github.com/tenstorrent/tt-oca-harness/pull/1590) — open, CHANGES_REQUESTED |
| **Branch** | `inmcm/sep_rom_oca_manifest_int` (bootrom diff byte-identical to PR head) |
| **Baseline** | `origin/main` |
| **Date** | 2026-09-16 |
| **Auditor** | `embedded-security-auditor` agent |
| **Scope** | 8,648 lines of C/H/S plus `link/rom.ld` and `Makefile`; `doc/rom.adoc` (new, 3,347 lines) and `doc/*.adoc` read for intent; `tools/tt-oca-manifest` treated as an external dependency (interface contract in `validators/oca/lib/oca_validator.h` read, internals not audited). |
| **Method** | Full source read; claims cross-checked against the generated register RDL, the library's header contract, and the pre-existing build artifact `build/boot_rom.elf` (inspected read-only with host `readelf`/`nm`). No build, make target, or simulation was run; no file was modified. |
| **Companion** | Design, reliability, maintainability and CI assessment is a separate `embedded-software-design-reviewer` pass — see `SEP_ROM_DESIGN_REVIEW.md`. |

---

> **Calibration note (added 2026-09-16, after the review ran).** This review was
> commissioned and executed against a masked-ROM / PROD-silicon bar. That is **not** the
> current target. The project is nowhere near tapeout; the near-term deliverable is a
> **BETA release to adopters and customers for hardware evaluation**, where the SEP ROM
> must work in practice and demonstrate secure boot with the new OCA manifest format.
> Hardening of the code and the build is explicitly **not** expected at this stage, and
> the six in-repo ROM signing keys are **demonstration material** — a DEBUG/RELEASE build
> split that forces a rebuild with public key material only, with the private halves held
> outside this repository, is planned.
>
> Read the severities below as "severity if this were the mask candidate", not as BETA
> blockers. **`SEP_ROM_BETA_TRIAGE.md` re-ranks every finding against the BETA target and
> is the list to work from.**

---

## 1. Verdict

**Not secure-correct for a PROD part, and not safe to integrate as-is.** The OCA integration is, on the whole, a genuine improvement in architecture: the ROM stopped hand-parsing an attacker-controlled binary format and now delegates structural parsing, identity/lifecycle constraints, anti-rollback, ordering and the payload hash chain to a library that is verified independently, and the `doc/rom.adoc` specification added by this branch is unusually honest about what is not yet implemented. The blocking issues are not in that architecture; they are at the two ends of it.

Four items block a PROD part. **First (SEC-01), all six ROM root-key digests compiled into the ROM are digests of RSA private keys committed to this repository** — the key-to-digest correspondence was verified by computing SHA-256 over each committed modulus — and `plat_is_key_authorized()` trusts those slots in every lifecycle state with no build-time or lifecycle gate; the branch widens the trusted set from one key (whose private half was in an external submodule) to six (private halves in-tree). **Second (SEC-02), a single skipped store instruction disables RSA signature verification entirely**: the OTBN modexp input and output share one DMEM buffer, `otbn_execute()` never confirms the command was accepted, and if it was not, the "result" that `verify_pkcs1_v15()` examines is the attacker's own signature bytes — so an attacker who authors the signature field as a valid PKCS#1 v1.5 block and glitches one store gets a full secure-boot bypass using only public information. **Third (SEC-03), `plat_is_secure_boot_disabled()` tests the whole `SBOOT_DIS` register for `!= 0`**, but 31 of its 32 bits are hardware-driven reserved bits per the RDL, so any one of them disables secure boot on a PROD part — and because `rom_main.c` masks the same register correctly for `bl0_state`, the boot measurement would attest that secure boot was *not* disabled. This is a direct regression against the deleted `manifest_load.c`, which passed a bit-masked boolean by value. **Fourth (SEC-05/SEC-06), the fault-injection posture does not match the stated attacker model**: `include/harden.h` is used in exactly one file, every verification verdict in the new path is a single non-redundant branch, the secure DMA's hardware range filter is deliberately opened to the entire 32-bit address space, and the PMP fences bind nothing because `PMP_LOCK` defaults to 0 and `mseccfg` is never written.

Separately, and importantly for triage: `doc/rom.adoc`'s implementation-status matrix already declares the PMP gap, the placeholder key digests, the dropped payload-gap zeroization and the missing pre-handoff gate ledger. Those are known. SEC-02, SEC-03, SEC-04, SEC-07, SEC-10, SEC-11 and SEC-25 are not declared anywhere findable in the tree.

---

## 2. Findings

### SEC-01 — All six ROM root-key digests correspond to RSA private keys committed to this repository, trusted in PROD with no gate — **Critical**

`hw/sys/sep/bootrom/prod/src/key_digests.c:10-47`, `hw/sys/sep/bootrom/prod/include/key_digests.h:44-50`, `hw/sys/sep/bootrom/prod/src/oca_platform.c:426-439`, `hw/sys/sep/bootrom/prod/tests/signing_keys/rsa_private_key.rom_key{0..5}.pem`

**This answers the question the audit was asked to verify rather than accept. It is the first of the two possibilities: a PROD-lifecycle part built from this source would trust keys whose private halves are committed to this repository.** The evidence chain:

1. SHA-256 computed over the 384-byte big-endian modulus of each committed PEM. All six match the compiled-in digests byte for byte:

| slot | `sha256(modulus)` computed from the committed PEM | `key_digests.c` |
|---|---|---|
| 0 | `a771ca6337a8f5c21a6ec994647e3aa09cfda7d2037d61bbecdf032b848250f6` | `digest_rom_key0` (L10-13) |
| 1 | `e64dcfb1c53349dc17e6b7a4c82f95e198c7d9ce99d6e482c3c4356586084aaf` | `digest_rom_key1` (L15-18) |
| 2 | `741cfa4fc7bea8208f62de6251fda54c844d91418825b0fc5cd976fa0b30a59f` | `digest_rom_key2` (L20-23) |
| 3 | `621e4531aed65ce219d8f7c2cbdfef8dd972e9088fb6143e239fb20a552a4e55` | `digest_rom_key3` (L25-28) |
| 4 | `b6031c9a5144781a2863fbc82802e49b29ceb3f911965f5125881007782025ae` | `digest_rom_key4` (L30-33) |
| 5 | `635962ef589c6c92d9d5e1d962d31b5a0bc4f099b231d7a9a0480d7d4c3f114c` | `digest_rom_key5` (L35-38) |

2. `nm` on the pre-existing `build/boot_rom.elf` confirms those digests are linked into the ROM image (`digest_rom_key0` at `0x10049170` in `.rodata`, ROM at `0x10040000`), and `public_key_digests` at `0xc0040004`.
3. `plat_is_key_authorized()` (`src/oca_platform.c:426-439`) resolves any `public_key_select_classic` bit in `[5:0]` straight into `public_key_digests[slot]` and accepts the manifest's modulus if its SHA-256 matches. **There is no lifecycle condition anywhere on that path** — no `lc_state` test, no `TEST_DEV`-only restriction. `include/key_digests.h:46-48` states the intent explicitly: "The slot number is the whole identity: the ROM draws no trust distinction between slots when resolving them."
4. The only device-side revocation is `CHIPLET_PUBK_REVOKE[5:0]`, and `src/oca_platform.c:664-668` records that the ROM never advances revocation (`oca_commit_security_state()` is not called, no OTP write driver). An unburned part revokes nothing.
5. Nothing in the build enforces replacement. `Makefile:82` sets `BUILD_TYPE ?= test` and `README.md:145-151` states plainly: "There is no enforced release build mode in the current Makefile." `doc/rom.adoc:3130` declares the row *ROM key digests | placeholder | production digests must land before mask finalization* — a manual, undated, unenforced step in a **mask ROM**.

**Exploitation.** On a PROD or PROD_END part built from this source, with `SBOOT_DIS` clear and `CHIPLET_PUBK_REVOKE` unburned: sign an arbitrary OCA manifest and payload with `tests/signing_keys/rsa_private_key.rom_key0.pem`, set `public_key_select_classic = 0x01`, place the bundle at flash `0x1000`. `plat_is_key_authorized()` returns `OCA_OK`, `plat_verify_signature()` verifies against the attacker's own key, and the ROM copies the attacker's BL1 into ICCM and jumps to it. This is a complete, non-fault-injection secure-boot bypass requiring nothing but a clone of this repository.

**Aggravating factor for remediation.** Roughly twenty DV tests are keyed to these exact digests — `hw/sys/sep/dv/cocotb/env/sep_manifest_mutate.py:924-937` parses `key_digests.c` at runtime, and the `sep_efuse_lc_prod_chiplet_key*.toml` preloads set the chiplet fuse digest equal to `public_key_digests[0]`. Replacing `key_digests.c` with production digests will break the ROM regression, which is a strong structural incentive to defer exactly the step that must not be deferred.

**Fix direction.** Do not ship a mask ROM whose trust anchors are digests of in-repo keys. Either (a) drop the ROM-embedded slots to OTP-only anchoring for PROD/PROD_END and keep the ROM table for TEST_DEV/RMA only, gated on `lc_state` inside `plat_is_key_authorized()`; or (b) make `key_digests.c` a generated-at-build artifact that is *absent* from the tree, with a hard build failure (`#error`) when a release build finds no provisioned digests, and pre-burn `CHIPLET_PUBK_REVOKE[5:0]` on every production part. Either way, decouple DV from the production table (give DV its own build variant with its own digest set) so the production step is not gated on a regression rewrite. The committed private keys should move out of this repository regardless; if they stay, rename the files and the config keys so a reader cannot mistake them for provisioning material, and remove the secret-scanner waiver in favour of an allowlist scoped to a directory whose name says "not a trust anchor".

**On the AES material, which is the other possibility.** `configs/oca_encrypted_boot_test.yaml:33` and `configs/oca_aes128_boot_test.yaml:33` carry `encryption_secret = 000102...1f`, a counting pattern, and the configs themselves state it must match a simulation fuse map (`virtual_platform/tests/fuse_maps/oca_class_key.yaml`). That is genuinely test-only: it corresponds to a `CLASS_KEY` fuse value that only a simulated part has, and a production part burns its own random `CLASS_KEY`. The separation is enforced by fuse provisioning, not by code. The one residual gap is that `plat_decrypt_payload()` (`src/oca_platform.c:234-242`) rejects only an all-zero `CLASS_KEY`; it has no notion of a known-weak value, so a part mistakenly provisioned with the test pattern would derive and decrypt happily. That is Low, not Critical.

---

### SEC-02 — One skipped store turns RSA-3072 verification into a self-check of attacker-supplied bytes — **Critical**

`hw/sys/sep/bootrom/prod/src/otbn_driver.c:118-134`, `hw/sys/sep/bootrom/prod/src/rsa_verify.c:154,162-177`

The OTBN RSA application uses **one DMEM buffer for both operands and result**: `hw/sys/sep/dv/fw/build/otbn/rsa_3072_app/rsa_3072_app_otbn.h:45` puts `inout` at DMEM `0x600`, and `rsa_verify.c` writes the signature there (L154) and reads the modexp result from the same offset (L170).

`otbn_execute()` then does exactly three things: write `CMD = 0xD8`, poll `STATUS == 0` (idle), read `ERR_BITS`. **It never confirms the command was accepted.** `otbn_wait_idle()` (`otbn_driver.c:37-43`) returns `OTBN_OK` the moment `STATUS` reads 0 — which is precisely the state OTBN is in if the command never landed. `ERR_BITS` is then 0, because nothing ran.

**Exploitation (no timing luck required).** The attacker authors the manifest, so they know the SHA-256 of the signed region. They place in the manifest's 384-byte signature field the literal big-endian PKCS#1 v1.5 block the checker expects: `00 01 FF x330 00 || DigestInfo(19) || SHA256(signed_region)`. They select a public key whose modulus hashes to a trusted anchor — a *public* value, so this needs no private key at all (and with SEC-01 unresolved, they have the private key too). Then they glitch the single store at `otbn_driver.c:120` (`mmio_write32(OCH_SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE)`) — the canonical instruction-skip target. OTBN never executes; `inout` still holds `bytes_to_otbn_words(signature)`; `otbn_dmem_read()` hands those words to `verify_pkcs1_v15()`, which compares them against exactly the structure the attacker placed there and returns 0. `plat_verify_signature()` returns `OCA_OK`, the library accepts the manifest, and the ROM boots the attacker's BL1 in PROD. A secondary variant needs no fault at all if the RTL can ever present `STATUS == IDLE` on the first read after the `CMD` write — the same race the HMAC driver's own comment at `src/hmac_sha256.c:67-74` identifies and defends against, left undefended here.

**Fix direction.** Three independent changes, all cheap. (a) Make the output distinct from the input: write the signature to `inout`, then before executing, overwrite the result region with a sentinel that cannot be a valid PKCS#1 block — or better, have the OTBN app write its result to a separate DMEM symbol. (b) Confirm the start: after writing `CMD`, poll for `STATUS != IDLE` with a bounded timeout and fail if the transition is never observed, then poll for idle. (c) Harden the verdict: evaluate `verify_pkcs1_v15()` twice over laundered operands (`harden_u32`) and return a hardened non-boolean sentinel, not `0`/`-1`, all the way up through `plat_verify_signature()`.

---

### SEC-03 — `SBOOT_DIS` tested as a whole word, so any of 31 hardware-driven reserved bits disables secure boot in PROD, invisibly to the boot measurement — **High** (regression)

`hw/sys/sep/bootrom/prod/src/oca_platform.c:605-610`; correct masking at `src/rom_main.c:726-728`; register definition at `hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl:584-597`

```c
static oca_secure_bool_t plat_is_secure_boot_disabled(void) {
    uint32_t sboot_dis = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR);
    return (sboot_dis != 0u) ? OCA_SECURE_TRUE : OCA_SECURE_FALSE;
}
```

The RDL defines `SBOOT_DIS.disable_secure_boot[0:0]` plus `rsvd[31:1]`, and **`rsvd` is `sw = r, hw = rw`** — driven by hardware from the fuse array, not tied off in software. The whole-word `!= 0` test therefore makes 32 bits equivalent to the one chicken bit. `rom_main.c:727` masks the same register correctly with `SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm`, so the two readers of one register disagree.

The library's contract makes the consequence exact. `oca_validator.h:1546-1558` documents the precedence as: manifest `secure_boot_control` bit 0 -> in force; else `is_secure_boot_disabled() == true` -> **not in force**; else `is_secure_boot_active()`. The same header warns at L1092-1098 that when this reporter says disabled, "A manifest with the control bit clear then boots unverified ... anyone able to present such a manifest gets an unverified boot."

**Exploitation.** PROD part. Attacker sets *any single bit* in `SBOOT_DIS[31:1]` — by a partial/stray fuse burn, a differential-decode artefact, or a fault on the shadow register or the fuse-sense path — and presents an unsigned OCA manifest with `secure_boot_control` bit 0 clear at flash `0x1000`. `plat_is_secure_boot_active()` says PROD enforces, but input (2) overrides it: signature, revocation and anti-rollback are all skipped, and the ROM boots the unsigned image. For a fault-injection attacker this is 31x easier than hitting bit 0, and critically **the bit they hit is one nobody checks**: `rom_main.c:728` records `sboot_dis = false` in `bl0_state`, and `src/measurement.c:124` folds that same masked value into the slot-1 boot-state record. The attestation would state that secure boot was not disabled on a boot where it was.

This is a regression. The deleted `secure_boot_enabled()` (`git show origin/main:.../src/manifest_load.c`) took `sboot_dis` as a masked `bool` **argument**, with the comment: "`lc_state` and `sboot_dis` are ARGUMENTS, never re-read from `bl0_state` ... Taking them by value makes this verdict independent of any later reordering."

**No DV coverage.** `hw/sys/sep/dv/tb/efuse_preloads/efuse_configurations/sep_efuse_lc_prod_sboot_dis.toml` sets only `disable_secure_boot = 0x1`. No test asserts that a reserved bit leaves secure boot enforced, so nothing would catch this.

**Fix direction.** Mask to `SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm`, and additionally treat a non-zero `rsvd` field as a fuse-integrity fault (terminal), since on a healthy part it must read zero. Read the fuse once in `rom_main`, and pass the masked hardened value to the callback layer rather than re-reading MMIO inside the callback, so `bl0_state`, the measurement and the policy cannot diverge.

---

### SEC-04 — Secure DMA hardware range filter opened to the entire address space; the software substitute is a single unhardened branch with no timeout — **High**

`hw/sys/sep/bootrom/prod/src/sep_dma.c:73-78, 88-103, 154-171`

```c
void sep_dma_init(void) {
    dma_write(...ENABLED_MEMORY_RANGE_BASE..., 0x00000000u);
    dma_write(...ENABLED_MEMORY_RANGE_LIMIT..., 0xFFFFFFFFu);
    dma_write(...RANGE_VALID..., 0x00000001u);
}
```

The one hardware control that could confine the boot ROM's DMA engine is programmed to permit all 4 GiB. The only remaining confinement is two plain `if (!contains_range_u32(...) && ...) return SEP_MSG_OUT_OF_RANGE_ERROR;` statements (L91-103) — single evaluation, no `harden_u32`, no complement check, no redundancy — even though `include/harden.h` exists for exactly this and `include/boot_flash.h:161-197` demonstrates the pattern.

**Exploitation.** The DMA is the transport for every untrusted byte on the boot path and for the BL1 copy into ICCM, with attacker-influenced `src`, `dst` and `len`. Glitching either of those two branches yields one arbitrary DMA copy with attacker-chosen source and destination — for instance untrusted flash straight into ICCM (bypassing every validation and the `contains_range` placement check in `rom_handoff.c`), or the eFuse shadow window into SMC SRAM, where the SMC can read it, before `lock_fuse_secrets()` runs at `rom_main.c:503`. The hardware gate would have made that fault insufficient on its own; as programmed it contributes nothing.

Additionally, `dma_transfer()`'s completion loop (L156-171) is `for (;;)` with no bound — the comment says "no timeout in the ROM DMA path". A DMA that neither asserts DONE nor ERROR hangs the ROM permanently with no status, and if it happens during an ICCM-destined transfer the `SEP_REGION_SIZE` alias remap (L117-129) is left disabled.

**Fix direction.** Program `ENABLED_MEMORY_RANGE` to the union actually needed, or better, reprogram it per transfer to exactly the destination span and set `RANGE_VALID` before each `GO` — the hardware then enforces what the software intends. Double the software range checks over laundered operands, defaulting to reject on disagreement. Bound the completion poll and fail closed on timeout.

---

### SEC-05 — No fault-injection hardening on any verification verdict in the new OCA path — **High**

`hw/sys/sep/bootrom/prod/src/oca_boot.c:246-250, 280-284, 301-305, 319-324, 345-349, 365-371`; `src/oca_platform.c:495-500`; `src/rom_main.c:507-510, 537-539`; `include/harden.h`

Against the stated attacker model (local glitch capability), every security verdict in the new path is a single `beq`-class branch on a single non-redundant value:

- `if (r != OCA_OK)` after `oca_validate_manifest()` — `oca_boot.c:281`. One skipped branch accepts a manifest that failed authentication.
- `if (r != OCA_OK)` after `oca_check_payload_at()` — `oca_boot.c:346`. One skipped branch accepts an unverified payload.
- `if (diff != 0u)` on the root-key digest comparison — `oca_platform.c:495`.
- `if (!check_fuse_secrets_locked())` — `rom_main.c:507`, a single read and a single `==` on the lock mask.
- `if (*(volatile uint32_t *)__stack_bottom != STACK_CANARY_VALUE)` — `rom_main.c:537`.

`include/harden.h` provides `HARDEN_VAL`/`harden_u32`/`harden_ptr` and is well written. Grepping the tree, it is included by exactly one file — `include/boot_flash.h` — and used only in the `BOOT_SPI_CONTROLLER_OT` branch there (see SEC-09), i.e. **not in the default build at all**. No hardened boolean type is used anywhere; no loop-completion counter is verified on any security loop (`oca_platform.c:399-407`, `437-439`, `492-494`, `measurement.c:99-104`); no branchless critical path exists. `doc/rom.adoc:2540-2563` specifies a pre-handoff "gate ledger" with doubled invariants and an exact tally, and `rom_main.c:176-177` confirms it "has not landed yet."

**Exploitation.** A single instruction skip at `oca_boot.c:281` makes the ROM treat any structurally-parseable manifest as authenticated; execution continues into payload staging, the BL1 placement check, the fuse lock and the handoff with `bl0_state.secure_boot` set from `vctx` (`oca_boot.c:294`), i.e. the device believes it performed a verified boot.

**Fix direction.** Land the gate ledger. In the meantime, apply the minimum that changes the fault cost meaningfully: make each verdict a hardened non-boolean (`0x5AA5`/`0xA55A`-style) carried in a pair with its complement; re-evaluate each `r != OCA_OK` over laundered operands and diverge to `rom_err_fail()` on disagreement; count the checks passed and compare the tally against a constant immediately before `rom_handoff_bl1()`; and re-run `rom_bl1_check()` plus the fuse-lock read-back inside that final gate.

---

### SEC-06 — PMP fences bind nothing in the default build, and SRAM/ICCM are RWX throughout validation — **High** (declared gap)

`hw/sys/sep/bootrom/prod/src/vector.S:352-424`, `Makefile:80-81`, `link/rom.ld:21`

`PMP_LOCK ?= 0` (`Makefile:81`) and `mseccfg` is never written anywhere in the tree (the only hits are in `doc/rom.adoc`). Under base RISC-V PMP, **unlocked entries do not constrain M-mode**, and the SEP ROM runs entirely in M-mode. The seven entries programmed at `vector.S:368-424` therefore have no effect on the ROM whatsoever. Entry 3 marks the untrusted manifest/payload staging SRAM `RWX` (`vector.S:396`, `0x1F`) and entry 5 marks ICCM `RWX`; `link/rom.ld:21` declares DCCM `rwx`. Entry 6 covers `0xC0000000-0xCFFFFFFF` but the actual SMC window is at `0x40000000` (`include/sep_smc_interface.h:29`), and the Cadence XIP aperture at `0x30000000` has no entry at all.

**Credit where due:** `doc/rom.adoc:975-995` states all of this explicitly as an IMPLEMENTATION GAP, including the precise reasons, and `doc/rom.adoc:3064-3073` tracks the ratified Smepmp sequence as "ratified, not implemented". This is a known, documented, unmitigated gap rather than a hidden flaw — which is why it rates High rather than Critical. It still means a PROD part has no execution fencing around attacker-controlled staging memory, and any memory-safety error or fault in the ROM or in the vendored library is directly exploitable as M-mode code execution.

**Fix direction.** Implement the sequence `doc/rom.adoc:907-919` already specifies: `mseccfg.RLB=1` first, all fence rules with `L=1`, SEP SRAM and ICCM `RW-` (no execute) during validation, then `mseccfg.MMWP=1`; release the BL1 region to executable with one locked-rule rewrite at handoff. Fix entry 6's range and add the XIP window before enabling the locks, since `MMWP` turns any ungranted access into a trap.

---

### SEC-07 — `CLASS_KEY` left un-zeroized on the `aes_init()` failure path — **Medium** (regression)

`hw/sys/sep/bootrom/prod/src/oca_platform.c:227-249`

```c
uint8_t secret[OCA_CLASS_KEY_BYTES];
fuse_read_bytes(...CLASS_KEY..., secret, OCA_CLASS_KEY_BYTES);   // L228
...
if (aes_init() != 0) {
    return OCA_FAIL_DECRYPT;     // L247-249: `secret` still holds the raw fuse key
}
```

Every other exit zeroizes (`L240`, `L253`, `L257`, `L265`). This one does not. The deleted `manifest_crypto.c` routed all of these through a single `cleanup:` label that wiped `class_key`, `derived_key`, `info` and `salt` on every path including `aes_init()` failure — so this is a regression introduced by the restructuring.

**Exploitation.** An attacker who can make `aes_init()` fail — hold AES in reset via `SEP_RESET_CTRL`, starve EDN so the masking PRNG never reports idle (`aes_driver.c:190-193`), or glitch the read-back at `aes_driver.c:180-184` — leaves 32 bytes of raw `CLASS_KEY` in the ROM's DCCM stack frame. `lock_fuse_semantics` exists precisely so BL1 cannot read that fuse (`src/fuse_lock.c:28-33`), and DCCM is not scrubbed on the warm-reset path (`vector.S:208-263` jumps before touching DCCM), so a subsequent boot's BL1 can read what the lock was supposed to deny. Combined with SEC-18 (no stack scrub before handoff) the same concern applies to the success path's spills.

**Fix direction.** Restore a single-exit `cleanup:` (or a small RAII-equivalent helper) that wipes `secret` and `key` on every return, and add a compile-time or review-enforced rule that no `return` in this function precedes the wipe.

---

### SEC-08 — The SMC-supplied manifest offset is never bounds-checked, and the comment claiming it is bounded is false — **Medium**

`hw/sys/sep/bootrom/prod/src/oca_boot.c:104-141, 411-419, 437-446`

On the recovery/secondary path the ROM takes a full 32-bit offset from SMC scratch and adds it to the SMC SRAM base with no range test:

```c
offsets[0] = smc_scratch_read(SMC_SCRATCH_MANIFEST_ADDR_IDX);   // L415, unbounded
...
manifest_src = sep_get_smc_sram_base() + offset;                 // L445, wraps
```

`manifest_src_read()` then **explicitly skips its bounds gate** for this path (L119, `if (from_spi)`), justified by the comment at L117-118: "Non-SPI sources (a manifest the SMC staged in its SRAM) are not flash and are bounded by their own region." They are not. The library contract says otherwise: `oca_validator.h:2286-2290` documents `manifest_addr` as merely "Address this manifest was read FROM", used only to compute the manifest span so the payload cannot overlap it — it is never validated against `[region_base, region_limit)`. `region_base`/`region_limit` bound only the *payload* location.

**Mitigating factor, verified:** `sep_dma.c:96-103` does range-check the DMA source against {SPI XIP + SMC SRAM + SEP SRAM}, so this is not an arbitrary-address read. It is still a confinement failure: with `offset = 0xEFFA0000` the "SMC-staged manifest" is read from the untrusted SPI XIP aperture, and with `offset = 0xCFFA0000` from SEP SRAM itself (a self-overlapping DMA onto the staging destination). Since `rom_smc_coordination_probe()` (`rom_main.c:273-276`) already rejects `0xFFFFFFFF`, the loader clearly intends some validation of this value and simply does not do it.

**Fix direction.** Validate `offset` against `[0, SMC_SRAM_SIZE_BYTES - OCA_MANIFEST_PEEK_MIN)` before computing `manifest_src`, and extend `manifest_src_read()`'s gate to cover the non-SPI path by checking `src` against `[region_base, region_limit)` — the values the caller already has in hand. Correct the comment.

---

### SEC-09 — The advertised FI-hardened, slot-confining flash bounds gate does not exist in the default build — **Medium**

`hw/sys/sep/bootrom/prod/include/boot_flash.h:156-206`, `src/oca_boot.c:105-118`, `Makefile:87`

`boot_flash_bounds_ok()` has two bodies. The `BOOT_SPI_CONTROLLER_OT` body (L163-197) is genuinely good: doubled evaluation over `harden_u32`-laundered operands, reject on disagreement, source confined to the specific boot slot and destination confined to SEP SRAM. The `#else` body (L198-205) — taken by the **default** build, since `Makefile:87` sets `BOOT_SPI_CONTROLLER_OT ?= 0` — is a single evaluation that checks only that the source lies somewhere in the 256 MiB XIP aperture. No doubling, no laundering, no slot confinement, and the destination is not checked here at all.

`oca_boot.c:105-118` asserts the opposite on both counts: "It is the only check that the SOURCE stays inside the boot slot being tried ... The gate is fault-injection hardened (doubled, laundered evaluation) and defaults to reject." Neither clause holds for the shipped default. Since `oca_locate_payload()` is also handed the whole aperture as its region on that path (`oca_boot.c:402-403`), **nothing confines a slot's payload to its own slot in the default build** — the primary manifest can name the backup slot's bytes, defeating the independent-second-copy property that `boot_flash.h:28-37` says the two slots exist to provide.

**Fix direction.** Give the Cadence branch the same slot-window test and the same doubled/laundered evaluation as the OT branch — the geometry constants are shared, so it is a small refactor to one common helper — and derive `region_base`/`region_limit` in `rom_manifest_boot()` from the slot being tried rather than from the whole aperture. Then the comment becomes true.

---

### SEC-10 — `sep_dma_zero()` clobbers the first word of the authenticated manifest at handoff — **Medium**

`hw/sys/sep/bootrom/prod/src/sep_dma.c:185-194`, `src/rom_handoff.c:201-223`, `Makefile:78-79`

```c
uint32_t sep_dma_zero(uint32_t dest, size_t len) {
    const uint32_t zero_word = (uint32_t)SEP_EXT_SRAM_BASE;   // == the manifest body
    *(volatile uint32_t *)(uintptr_t)zero_word = 0u;
    return dma_transfer(dest, zero_word, (uint32_t)len, 0);
}
```

The fill source is the first word of SEP SRAM — which is exactly where `try_manifest_slot()` stages the manifest body (`oca_boot.c:234`, `uint8_t *const body = (uint8_t *)SRAM_BASE`). The comment at `sep_dma.c:188-190` defends this with "the word is consumed before any payload is staged there", and that is true of the `[S16]` call site — but false of the ICCM-ECC-pad call site at `rom_handoff.c:216`, which runs at `[S29]`, long after staging and validation. That call site is compiled in by the **default** configuration (`Makefile:78-79`: `ROM_ICCM_CLEAR_ENABLE ?= 1`, `ROM_ICCM_CLEAR_FULL ?= 0`, and the guard at `rom_handoff.c:201` is `#if ROM_ICCM_CLEAR_ENABLE && !ROM_ICCM_CLEAR_FULL`).

**Failure scenario.** Normal successful boot of a BL1 placed in ICCM. At `[S29]` the pad runs, zeroing `body[0..3]` — the OCA magic. `bl0_state.sep_sram_manifest_addr` (`oca_boot.c:373`) then hands BL1 "the validated manifest address" pointing at a body whose magic word is destroyed; `doc/memory-security.adoc:51-53` and `doc/bl1-handoff.adoc:45` both state BL1 consumes that address. Nothing inside the ROM re-reads it after `[S27]`, so this passes DV silently unless BL1 parses the manifest. It also means the artefact the ROM measured at `[S27]` is not the artefact it hands on.

**Fix direction.** Use a dedicated 4-byte zero source that is not inside the staging region — a word in `.data`/DCCM is not a valid DMA source per `sep_dma.c:99-101`, so reserve the *last* word of SEP SRAM, or better, stage the body at `SRAM_BASE + 8` and reserve the first 8 bytes as scratch. Then correct the comment, which is currently load-bearing and wrong.

---

### SEC-11 — The ROM self-measurement covers `.text` only; the trust anchors and the RSA verifier program are unmeasured — **Medium**

`hw/sys/sep/bootrom/prod/src/measurement.c:88-113`, `link/rom.ld:34-45`, `tools/insert-rom-sha256.py:11,38-39`

`measurement_enroll_rom_hash()` hashes `[ROM base, __metadata_end)`. From the pre-existing ELF:

```
__metadata_start = 0x100482c8   __metadata_end = 0x100482c8      # .metadata is EMPTY
.text    0x10040000  size 0x82c8    -> hashed region == .text only
.rodata  0x100482c8  size 0x2718    -> NOT hashed
```

Everything security-relevant that is not an instruction sits in that unmeasured 10 KB: the six root-key digests (`digest_rom_key0` at `0x10049170`), the **OTBN RSA-3072 verification program** (`otbn_rsa_3072_app_imem` at `0x1004922c`, 5,940 bytes), the SHA-256 self-test expected vector, and the `.data` load image — including the initializer for `public_key_digests` (SEC-12). `rom_main.c:701-702` claims the check means "slot 0 measures what is executing rather than what the build claimed"; that is true only of the instruction stream.

`insert-rom-sha256.py:11-13` is also self-contradictory about what it covers ("Hashes only ICCM sections"; "`g_rom_sha256_str` ... in `.rodata` (DCCM)") — neither region is ICCM or DCCM.

**Fix direction.** Extend the hashed region to cover `.rodata` and the `.data` LMA, excluding only the `g_rom_sha256_str` object itself (place it in its own section after the hashed span, which is what the now-empty `.metadata` machinery appears to have been for). Enroll the *computed* digest rather than the parsed embedded one (`measurement.c:112` passes `embedded`), so a glitched compare loop cannot cause slot 0 to attest a hash the ROM did not actually measure.

---

### SEC-12 — The root-of-trust anchor table is a mutable pointer array in DCCM — **Medium**

`hw/sys/sep/bootrom/prod/src/key_digests.c:40`, `include/key_digests.h:50`

`public_key_digests[]` is declared and defined without `const`. Confirmed in the built image: `nm` reports `c0040004 00000018 D public_key_digests` — 24 bytes of function-pointer-like data in `.data`, i.e. in writable DCCM, while the digests it points at are correctly in ROM `.rodata`.

**Exploitation.** A single 32-bit write or fault on `0xC0040004` repoints `public_key_digests[0].digest` at attacker-controlled memory — for example into the staged manifest in SEP SRAM, which the attacker fully controls. `plat_is_key_authorized()` (`oca_platform.c:436-494`) then compares `sha256(attacker_modulus)` against 32 bytes the attacker also supplied, so any key is authorized. Per SEC-11 the measurement would not notice, and per SEC-06 nothing marks DCCM read-only.

**Fix direction.** Make the array `const` so it lands in ROM `.rodata` alongside the digests (drop the pointer indirection entirely and store the 32-byte digests inline in a `const` 2-D array — smaller and unforgeable). Update `tools/generate_key_digests.py:98` to emit `const`. If the indirection must stay, re-derive and re-check the pointer against the ROM address range immediately before use, under `harden_ptr`.

---

### SEC-13 — AES key loaded with `KEY_SHARE1 = 0`, defeating the key registers' Boolean masking — **Medium**

`hw/sys/sep/bootrom/prod/src/aes_driver.c:105-124`

```c
// KEY_SHARE1: all zeros (no masking).
for (uint32_t i = 0; i < 8u; ++i)
    mmio_write32(OCH_SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(0) + (i * 4u), 0u);
```

The OpenTitan AES takes its key as two Boolean shares (`KEY_SHARE0 ^ KEY_SHARE1`) specifically so the key never appears in the clear in any register or on any bus cycle. Writing share 1 as zero puts the full `CLASS_KEY`-derived key in share 0 in the clear, across eight consecutive MMIO stores.

The threat model includes "a local attacker capable of ... observing timing/power". The eight key-load stores are a textbook DPA/SPA target, and they are trivially locatable because the debug console (SEC-20) prints `DECRYPT_OK`/`AES_*` markers around them. The ROM now has a working entropy chain (`src/sep_entropy.c`) and `plat_decrypt_payload()` establishes it before the cipher (`oca_platform.c:201`), so the mask is available at the point it is needed.

**Fix direction.** Draw 32 bytes of randomness from the entropy chain, write `key ^ r` to `KEY_SHARE0` and `r` to `KEY_SHARE1`, and zeroize `r` and the un-split key afterwards. Also verify that `aes_cleanup()`'s `KEY_IV_DATA_IN_CLEAR` actually took, by reading `STATUS` back — currently `aes_driver.c:152-164` fires the trigger and returns without confirmation.

---

### SEC-14 — The BL1 handoff block carries security verdicts with no integrity protection, and the library's hardened boolean is collapsed to a C `bool` at the seam — **Medium**

`hw/sys/sep/bootrom/prod/include/bl0_state.h:64-67, 143-146`, `src/oca_boot.c:294`, `src/rom_main.c:402`

`oca_validator.h:1035-1038` explains why the library uses `oca_secure_bool_t`: "this is a fuse or life-cycle read on a part an attacker may be glitching, and in a `bool` the answer that disables verification is every byte value except one." The ROM then does exactly that:

```c
get_bl0_state()->secure_boot = (vctx.secure_boot_enabled == OCA_SECURE_TRUE);   // oca_boot.c:294
```

`bl0_state.secure_boot` and `.sboot_dis` are 1-byte `bool`s, `.lc_state` a plain `uint32_t`, and `verify_bl0_state()` checks only two magic words and `sizeof` — there is no checksum, complement, or majority vote over any security-relevant field. A single-bit fault anywhere in those bytes changes what BL1 believes about the boot it inherited, and `measurement.c:122-125` copies the same unprotected values into the slot-1 record, so the attestation inherits the corruption rather than detecting it.

**Fix direction.** Store the security verdicts in `bl0_state` as hardened values with complements (`secure_boot` / `secure_boot_inv`), keep `oca_secure_bool_t` rather than narrowing it, and protect the whole struct with a SHA-256 or CRC over its contents that BL1 recomputes — the HMAC engine is already up at that point and `verify_bl0_state()` is the natural place for the check.

---

### SEC-15 — Completion waits accept a stale `idle`; four hardware polls have no timeout — **Medium**

`hw/sys/sep/bootrom/prod/src/hmac_sha256.c:47-65, 92-100, 121-132, 148-155`; `src/sep_dma.c:156-171`; `src/status_ring.c:44-46`; `src/pll_init.c:49-51`

Two distinct problems.

*Stale-idle completion.* `wait_for_completion()` returns success on `STATUS.hmac_idle` as well as on `INTR_STATE.hmac_done`. The file's own comment at L67-74 explains that a rejected operation leaves `hmac_idle` asserted, so the wait "returns success immediately" — it relies on `check_no_error()` to catch that case. But `hmac_idle` is also still asserted in the window between the `hash_process` write and the engine actually starting, in which case the digest registers are read before the digest exists and `check_no_error()` reports nothing wrong. `otbn_wait_idle()` has the same shape (SEC-02). Whether the race is winnable is RTL-dependent and is marked a **hypothesis**; the pattern is unsound regardless, because `hmac_done` is the only signal that distinguishes "finished" from "not started".

*Unbounded polls.* `fifo_feed()` has three `do { } while (fifo_full)` / `while (credit == 0)` spins with no bound (L95-97, L124-132, L150-152) — so a wedged HMAC core hangs the ROM inside `sha256()` even though `wait_for_completion()` itself has a timeout. `dma_transfer()` (SEC-04), `init_status_reporting()` (`status_ring.c:44-46`, comment: "potentially hang forever") and `pll_init()`'s PLL-lock spin (`pll_init.c:49-51`) are likewise unbounded. Each is a fail-stop, so none is a bypass, but each is a silent hang with no status word for post-mortem, reachable by an attacker who can hold a strap or wedge a block.

**Fix direction.** Gate completion on `hmac_done` only, having first confirmed the operation started (poll for `hmac_idle` clear, bounded). Bound every hardware poll and converge failures on `rom_err_fail()` with a distinct status so a hang becomes an attributable error.

---

### SEC-16 — Secure-boot enforcement re-reads the lifecycle fuse without validating it and without cross-checking the validated copy — **Medium**

`hw/sys/sep/bootrom/prod/src/oca_platform.c:600-603`; contrast `src/oca_platform.c:545-548`, `src/lifecycle.c:127-141`

```c
static oca_secure_bool_t plat_is_secure_boot_active(void) {
    uint32_t lc = lc_read_state();
    return lc_state_enforces_secure_boot(lc) ? OCA_SECURE_TRUE : OCA_SECURE_FALSE;
}
```

`plat_get_lifecycle_state()` twenty lines earlier calls `lc_state_is_valid(lc)` and returns `OCA_HW_ERROR` on a bad value. The enforcement reporter does not — and `lc_state_enforces_secure_boot()` (`lifecycle.c:67-71`) returns `false` for every value that is not exactly `PROD` or `PROD_END`. So an invalid or faulted lifecycle read maps to **"secure boot is not enforced"**: fail-open on the single most consequential policy input. It also ignores `bl0_state.lc_state`, the copy that `rom_lifecycle_policy()` already validated at `[S11]`, so the two are never compared.

**Exploitation.** The `[S11]` gate catches a statically-invalid fuse, so this needs a transient: a fault on the `LC_STATE` shadow read inside this callback. The library re-derives the determination at each gated check and rejects a change (`OCA_FAIL_SECURE_BOOT_STATE_CHANGED`), so the attacker must fault the *first* read and hold it consistently — harder, but a persistent fuse-sense or shadow-register fault does exactly that. Note also the related fail-open hazard the tree documents itself: `include/sep_smc_interface.h:200-206` warns that a pre-sense shadow read returns zero and "LC_STATE zero decodes as TEST_DEV, where secure boot is optional, so an early lifecycle read fails open" — and `doc/rom.adoc:3123` records "Fuse-sense readiness | *gap* | Only the PLL path polls `smc_fuse_sense_done`".

**Fix direction.** Validate inside the callback and return `OCA_SECURE_TRUE` (enforce) for any value that is not a recognised non-enforcing state — i.e. make the default enforce, not permit. Cross-check against `bl0_state.lc_state` and treat disagreement as terminal.

---

### SEC-17 — SEP SRAM is never cleared in the default build, and never cleared on terminal failure — **Medium**

`hw/sys/sep/bootrom/prod/src/rom_mem_clear.c:31-57`, `Makefile:54-57`, `src/oca_boot.c:456-464`

`SRAM_SCRUB_BYTES ?= 0`, so `rom_clear_ext_sram()` at `[S15]` prints `SRAM_CLR_SKIP` and clears nothing. The Makefile's stated reason is a DV convenience: "Off, and not for speed: `rom_clear_ext_sram()` runs before the manifest load and would wipe the warm handler `sep_scratch_7_test` preloads at SRAM_BASE + 0x100." A test fixture is disabling a memory-sanitization control in the default production build.

Independently, `clear_sram_region()` runs only *between* retries and only on the SPI path (`oca_boot.c:459-462`). On the terminal path — every slot exhausted — SRAM is left as-is before `rom_err_fail()` parks in `wfi`. So the decrypted plaintext of a payload that passed the ciphertext hash and then failed a plaintext check (`oca_platform.c:279-281` publishes the plaintext; the library then verifies the hash chain) persists in SRAM across the halt, and SEP SRAM is not reset by a warm reset. Combined with SEC-24 (a warm-reset handler in SRAM is an accepted jump target) and SEC-06 (SRAM is RWX) that residue is both readable and, in principle, executable.

**Fix direction.** Default `SRAM_SCRUB_BYTES` to the full region and move the DV warm-handler preload to a location the cold-boot scrub does not cover, or stage it after `[S15]` — do not invert the dependency. Clear the staging region on every exit from `rom_manifest_boot()`, success and failure alike, retaining only what `bl0_state` must point at.

---

### SEC-18 — No stack, register or SRAM scrub before the BL1 handoff — **Medium**

`hw/sys/sep/bootrom/prod/src/rom_handoff.c:93-105, 244-253`, `src/rom_main.c:541-549`

`jump_to_bl1()` writes `mepc`, fences and `mret`s. Nothing between `[S26]` and the jump clears the ROM's ~128 KB DCCM stack, the general-purpose registers, or the staged payload. The ROM's deepest frames during `[S23]` held the `CLASS_KEY` fuse image, the KDF expanded block, the derived AES key and the HMAC/SHA working buffers. `explicit_memzero()` and `kdf.c`'s `wipe()` clear the named objects, but not compiler spills, not callee-saved register copies, and not the vendored library's frames (`oca_check_payload_at()` receives the plaintext and the key-derivation inputs). `Makefile:50-51` acknowledges the exposure — "explicit_memzero() misses temporaries and spilled registers, so this scrub is what keeps key material off the stack" — but that scrub runs at *cold boot*, before the secrets exist, not before handoff.

The point of `lock_fuse_secrets()` (`rom_main.c:503`) is that BL1 must not be able to read `CLASS_KEY`. Handing BL1 a DCCM that may contain its residue, and a live `bl0_state` neighbouring it, weakens the lock to a formality. On the warm-reset path the residue additionally survives into subsequent BL1 entries (`vector.S:208-263`).

**Fix direction.** Scrub `[__stack_bottom, __stack_top)` immediately before `jump_to_bl1()` — the ROM is about to stop using it, and the stack is ~128 KB of DCCM stores, cheap relative to the BL1 DMA. Zero the GPRs in the asm block just before `mret`, leaving only what the BL1 ABI requires. Clear the manifest/payload staging region except the bytes `bl0_state` documents as live.

---

### SEC-19 — Post-check length rounding and inconsistent 64-bit to 32-bit narrowing of TOC fields — **Low/Medium**

`hw/sys/sep/bootrom/prod/src/rom_handoff.c:137-166, 195-199, 232`

Two related defects at the library boundary.

*Check-then-widen.* `bl1_locate()` validates `[load_addr, load_addr + length)` against ICCM or SRAM at L137-142, and then `rom_handoff_bl1()` rounds the length **up** before using it:

```c
uint32_t img_length = (uint32_t)bl1.length;
img_length = (img_length + 3u) & ~3u;                       // L199
...
sep_dma_copy(load_addr, (uint32_t)bl1.bytes, img_length);   // L232
```

A BL1 whose length is 1..3 mod 4 and whose end is flush with the ICCM (or SRAM) limit is validated at `length` and copied at `length` rounded up, writing up to 3 bytes past the region the check approved, and reading up to 3 bytes past the verified payload span. `dma_transfer()`'s own range check (SEC-04) catches the destination overrun; the source overrun past `payload + payload_span` is not caught when the payload ends flush with SRAM.

*Inconsistent narrowing.* `oca_image_info_t`'s fields are wide; the ROM narrows them with bare casts and never rejects a value that does not fit. `contains_range()` receives `(size_t)` truncations (L139, L142) while `bl1->entry_point >= bl1->length` at L162 compares the **untruncated** values, and L197 then uses the truncated `entry_off`. A TOC entry with `length = 0x1_00000010` and `entry_point = 0x1000` passes the L162 test (because `0x1000 < 0x100000010`) and yields `entry_off = 0x1000` against `img_length = 0x10`, so the entry point lands outside the copied and validated image. The library probably bounds `length` against `payload_len` upstream, which would make this unreachable — marked a **hypothesis**, since the library internals were not audited.

**Fix direction.** Round the length up *before* the bounds check, or check the rounded length explicitly. Narrow the library's fields once, in one place, rejecting anything that does not fit 32 bits with a distinct error, and do every comparison on the narrowed values.

---

### SEC-20 — `DEBUG` is unconditionally on; the console publishes the security state and hands a glitch attacker a trigger oracle — **Medium**

`hw/sys/sep/bootrom/prod/Makefile:207` (`-DTEST_BUILD=1 -DSEP_BL0 -DDEBUG`), `include/rom_virt_console.h:27-101`, `README.md:145-151`

`DEBUG` is in `CFLAGS` with no conditional, so every `simputs`/`simputshex32` is compiled into every build, including one an adopter would call a release. `README.md:145-151` states the problem accurately: "There is no enforced release build mode in the current Makefile: `TEST_BUILD=1` and `DEBUG` are always present in `CFLAGS` ... debug virtual-console output remains compiled in even when the status-report-disable strap skips the SMC status ring."

The content is a precise map of the device's security posture: `LC_STATE=`, `FUSE: SBOOT_DIS:`, `PUBK_SEL=`, `PUBK_REVOKE=`, `FUSE_VER=`, `MFST_VER=`, `FEAT_CTRL_LO/HI=`, `CHIP_ID=`, `COPY_SRC/DST/LEN=`, `BL1_JUMP=`. None is a secret key. The operational problem is different and worse for this attacker model: each marker is a distinctive MMIO store to `cold_scratch[2]`, so `RSA_EXEC`, `PUBK_AUTHORIZED`, `MANIFEST_OK`, `PAYLOAD_OK` and `DECRYPT_OK` give a power/EM attacker a free, byte-accurate trigger for locating the exact instruction window of every verdict this report identifies as a single-fault target — including the `CMD` store of SEC-02. It also costs ~10 KB of the 64 KB ROM (`.rodata` is `0x2718` in the built image).

**Fix direction.** Make `DEBUG` conditional on `BUILD_TYPE`, and have a release build fail the link if any `simputs` reference survives. At minimum, strip the markers that bracket the cryptographic verdicts even in test builds, and keep only the machine-readable `SEP_MSG_*` stream, which is coarser.

---

### SEC-21 — The build enables no warnings at all, while the Makefile claims the opposite — **Medium**

`hw/sys/sep/bootrom/prod/Makefile:197-214, 346-351`

`CFLAGS` contains no `-Wall`, no `-Wextra`, no `-Werror`, no `-std=`, no `-Wconversion`, no `-Wstack-usage`, no `-fstack-protector`, no `-ftrivial-auto-var-init=zero`, no `-fno-strict-aliasing`, no `-fno-common`, no `-mstrict-align`, no LTO. `Makefile:347-349` nonetheless says of the vendored library: "`-Wno-pedantic` is deliberately NOT set: the library builds clean under its own `-Wall -Wextra -Werror -pedantic`, so a warning here means a real toolchain or flag mismatch worth seeing rather than silencing." With no `-W` flag in `CFLAGS`, no warning can be seen — the build is silent by construction, and the comment describes a property it does not have.

This is not theoretical. `src/oca_boot.c:79` sets `oca_result_t st = OCA_OK;` and never reads it — `-Wunused-but-set-variable` would have flagged it. Absent `-std=`, the language is whatever the toolchain defaults to, while `include/harden.h:36-41` depends on GNU statement expressions and `__typeof__`, so the dependency on a GNU dialect is real but unstated.

**Fix direction.** Add `-std=c11 -Wall -Wextra -Werror -Wconversion -Wsign-conversion -Wshadow -Wcast-qual -Wundef -Wstack-usage=<budget> -fno-strict-aliasing -fno-common -mstrict-align -ftrivial-auto-var-init=zero`, and `-Wl,--print-memory-usage`. `-fstack-protector-strong` is worth measuring against the ROM budget (~20 KB free by `size` on the existing image) given the canary today is a single word checked once. Treat any new warning from the vendored library as the signal `Makefile:347-349` already says it is.

---

### SEC-22 — Anti-rollback narrowed from 256 to 128 fuse bits — **Medium** (regression)

`hw/sys/sep/bootrom/prod/src/oca_platform.c:635-656`; contrast `git show origin/main:.../src/manifest_crypto.c` (`get_security_version_from_fuse`)

The deleted implementation read all eight words (256 bits) of `BL1_VERSION` and derived a thermometer count. The new `plat_get_security_version()` reads 16 bytes and stops: "BL1_VERSION is a 32-byte bank; only its low 16 bytes map onto OCA's 128-bit field. Anything set above bit 127 cannot be expressed and is not read."

The scheme change (count to bit-superset) is intended and declared closed in `doc/rom.adoc:3040`. The *narrowing* is not. Once a device has advanced its anti-rollback state past bit 127, the upper half of the fuse bank is invisible to the check, and a manifest whose flags cover only the low 128 bits satisfies `manifest & device == device`. Whether that is reachable depends on how the field is allocated over the product's life — if the fuse bank is sized at 256 bits it is presumably meant to be used.

**Fix direction.** Decide explicitly whether the device's anti-rollback state is 128 or 256 bits. If 256, either fold the upper 128 bits into the comparison outside the library (a second gate in `plat_get_security_version()`'s caller) or treat any bit set above 127 as a terminal provisioning error rather than silently ignoring it. Record the decision in `doc/rom.adoc`, which currently says only "128-bit flag superset".

---

### SEC-23 — Payload gap zeroization dropped — **Low/Medium** (regression, declared)

`git show origin/main:.../src/manifest_load.c:373-394, 449-451`; no equivalent in the new path

The old path zeroed the bytes between described images and after the last one, so that "every byte of the payload is either inside a validated image or has been cleared". The new path does not. `doc/rom.adoc:3105-3107` declares this: *Payload gap zeroing | gap (should) | Un-hashed inter-image bytes not zeroed after validation (legacy ROM did)*.

The gap bytes are still covered by the whole-payload hash, so they are authenticated, not arbitrary. What is lost is the stronger property: content can sit in the staged payload that no per-image digest attributes to anything, in a region that is RWX (SEC-06), is a permitted BL1 execution region by default (`Makefile:73`, `BL1_SRAM_EXEC_ENABLE ?= 1`), is a permitted warm-reset jump target (SEC-24), and is never scrubbed (SEC-17).

**Fix direction.** Restore the gap-and-tail zeroization after `oca_check_payload_at()` succeeds, using the TOC extents the library already validated.

---

### SEC-24 — Warm-reset path jumps to an unauthenticated pointer, with untrusted staging SRAM an accepted target — **Medium**

`hw/sys/sep/bootrom/prod/src/vector.S:211-263`

`_start` reads `cold_scratch[7]`, range-checks it against ICCM or (with `BL1_SRAM_EXEC_ENABLE=1`, the default) SEP SRAM, and `jr`s to it. No integrity check on the code at the target, no DCCM scrub, no measurement, and the accept arm deliberately leaves the slot armed for subsequent resets (L251-260, with a well-reasoned justification). SEP SRAM is where the untrusted manifest and payload are staged, is RWX (SEC-06), and is not cleared on failure (SEC-17).

The whole security of this path rests on one unstated premise: that only BL1 can write `cold_scratch[7]` and SEP SRAM. That could not be settled from the source. `hw/sys/sep/regs/blocks/sep_scratch/sep_scratch.rdl` declares `SCRATCH.data` as `sw=rw, hw=r` and the block is instantiated in `sep_system_peripherals/rtl/sep_system_csr.sv`; whether any non-SEP master (the SMC, a host, or a JTAG/debug path) can reach it is an integration property that was not traced. **The reachability is marked a hypothesis.** If it is reachable, this is a complete secure-boot bypass: write an SRAM address into `cold_scratch[7]`, put code at that address, trigger a watchdog reset, and the ROM transfers to it in M-mode before any validation runs. The cold path's `-1` poison (L295-297) closes the window only until BL1 first arms the slot.

**Fix direction.** Settle and then document who can write `cold_scratch[7]`; if anything outside SEP can, move the slot to a SEP-private, write-once-per-boot register. Restrict the accepted range to ICCM only (`BL1_SRAM_EXEC_ENABLE` should not widen the warm target as well as the cold one), and have BL1 store a keyed tag alongside the handler address that the ROM checks with the HMAC engine before jumping.

---

### SEC-25 — The invalid-lifecycle containment action writes the wrong register with the wrong polarity — **Medium** (pre-existing, not introduced by this branch)

`hw/sys/sep/bootrom/prod/src/lifecycle.c:24-26, 131-138`

```c
#define SMC_CPU_CTRL_RESET_CTRL_OFFSET 0x0020u
...
uint32_t rst = mmio_read32(smc_base + SMC_CPU_CTRL_RESET_CTRL_OFFSET);
rst |= 0xFu; // core0~core3 reset_n bits -> hold all cores in reset
mmio_write32(smc_base + SMC_CPU_CTRL_RESET_CTRL_OFFSET, rst);
simputs("SMC_RESET_ON_INVALID_LC\n");
```

Both halves are wrong, and both were verified against the generated collateral.

*Wrong address.* `hw/sys/smc/regs/gen/c/smc_addr.h:2306` gives `SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR = 0xC0039020` (SMC-local). The ROM's SEP view strips the `0xC0000000` prefix and adds `0x40000000` — which `include/sep_smc_interface.h:45-46` confirms for the sibling register ("0x39080 is `SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR` ... `0xC0039080` SMC-local"), and `SMC_SCRATCH_BASE_OFFSET` is accordingly `0x39080`. The correct offset is therefore **`0x39020`, not `0x0020`**. As written, the ROM read-modify-writes `0x40000020` — an unidentified register in a different SMC block. This is the only SMC access in the ROM that uses a hand-rolled offset rather than a named one from `sep_smc_interface.h`.

*Wrong polarity.* `hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl:24-44` defines `core0..3_reset_n_n0_scan` as "Reset control for the CPU, **active low**" with reset value `0x1`. Setting a bit therefore **releases** a core; holding cores in reset requires `rst &= ~0xFu`.

**Failure scenario.** The ROM reaches this code only when `LC_STATE` is outside the valid set — the case the comment describes as "may indicate fuse attack or HW fault". The stated containment ("Put SMC in reset to make the whole SMU inoperative") does not happen; instead four bits are OR'd into an unknown register in a neighbouring subsystem, from the root of trust's tamper-response path, with unbounded side effects. The boot itself still halts via `rom_err_fail_ext()`, so this is a failure of defence-in-depth plus a stray write, not a bypass.

**Fix direction.** Use the generated symbol (`SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR` rebased to the SEP view) rather than a local literal, clear the bits rather than setting them, and read back to confirm the cores are held. Add a DV case that asserts an invalid `LC_STATE` leaves the SMC cores in reset — none exists today, which is why a fully inverted action has gone unnoticed.

---

### Low and Informational

| ID | Finding | Anchor |
|---|---|---|
| SEC-26 | `README.md` is stale against this branch: it tells a new developer to init the submodule `tools/tt-boot-manifest` (renamed to `tt-oca-manifest`), and documents `pack-images`, `secure_boot_spi` and `encrypted_boot_spi` targets that no longer exist in the Makefile (all three verified absent). Its `ROM_ICCM_CLEAR_ENABLE` default of `0` contradicts `Makefile:78` (`?= 1`). | `README.md:24,68-71,132` |
| SEC-27 | `doc/boot-flow.adoc`, `spi-manifest.adoc`, `memory-security.adoc`, `status-errors.adoc` and `index.adoc` still describe the **deleted** manifest path in normative terms — "a packed 1184-byte `manifest_t`", "defined by `include/manifest.h`", "manifest and payload processing in `src/manifest_load.c` and `src/manifest_crypto.c`", "`MANIFEST_ERR_*` registry in `include/manifest.h`" — and `memory-security.adoc:48` states a 128-byte `bl0_state` reserve where `link/rom.ld:71` says 256. They are included from `index.adoc`, so a doc build publishes them. | `doc/index.adoc:35-36`, `doc/spi-manifest.adoc:47-55`, `doc/status-errors.adoc:75`, `doc/memory-security.adoc:48,100-104` |
| SEC-28 | `STATUS_ENCODE` shifts into the sign bit of `int`: `(0x80 << 24)` for `STATUS_TYPE_DEBUG` is not representable in `int`, which is undefined behaviour under C11 6.5.7p4. Its parameters are also unparenthesised, so `STATUS_ENCODE(a|b, c)` misparses. Used pervasively, including for the literals hand-computed in `vector.S`. | `include/errors.h:30-31` |
| SEC-29 | `mmio_write64()` is dead code and unusable as written on RV32: there is no 64-bit store, so GCC splits it into two `sw`s in an unspecified order — wrong for any register that commits on one half. | `include/rom_mmio.h:19-21` |
| SEC-30 | Three different range-check implementations with three different edge-case conventions coexist: `boot_flash_range_within` (`boot_flash.h:102`, zero length = in bounds), `contains_range_u32` (`sep_dma.c:57`, zero length = in bounds), `contains_range` (`sep_helpers.h:54`, zero length = **out of** bounds), plus a fourth in `status_ring.c:36`. Two zeroization idioms likewise: `explicit_memzero` (`sep_helpers.h:44`, barrier after a non-volatile loop) and `wipe` (`kdf.c:47`, volatile stores). | as listed |
| SEC-31 | `fuse_read_bytes()` writes `out[i+1..i+3]` unconditionally while stepping `i` by 4, so any `len` not a multiple of 4 overflows the caller's buffer. All five call sites pass 32, 16 or 4 today; nothing enforces it. | `src/oca_platform.c:74-82` |
| SEC-32 | `hmac_sha256()` selects `KEY_LENGTH_128` for any `key_len <= 16` while zero-padding the register file to 32 bytes — a 20-byte key would be silently truncated to 16. Latent; the only caller passes 32. | `src/hmac_sha256.c:254-259` |
| SEC-33 | `rom_oca_demotion_control()` hardcodes offsets 172/173 in a comment that names the macro `OCA_OFF_DEMOTION_CONTROL` (which the file already includes via `oca_layout.h:92`), while `rom_oca_manifest_hash()` twenty lines earlier explains at length why offsets must come from the variant descriptor. 172 was confirmed variant-independent and inside the signed region, so this is correct today and fragile across a submodule uprev. | `src/oca_boot.c:87-95`, `oca_layout.h:92` |
| SEC-34 | `sep_entropy_init()` caches success in a single plain global, `g_entropy_state`, with no complement or magic value: a fault setting it non-zero makes every later caller believe the chain is up, so AES runs with an unseeded masking PRNG and OTBN with unseeded URND. The header also overstates the contract ("later calls return that same outcome") when only success is cached. | `src/sep_entropy.c:140,233-238`; `include/sep_entropy.h:23-33` |
| SEC-35 | On the external-TRNG path, `sep_entropy_init()` locks `EXT_TRNG_SRC_SEL` without first confirming that `sel[1]` still selects the external source, so a build whose override left it clear locks the mux onto the unconfigured internal chain and reports success. | `src/sep_entropy.c:224-231,246-253`; `include/sep_entropy.h:57-61` |
| SEC-36 | `plat_verify_signature()` checks `signature == NULL` but not `signature->bytes == NULL`, unlike `plat_is_key_authorized()` which checks `public_key->bytes`. `rsa_3072_verify()` also performs no sanity check on the modulus (odd, top bit set) or on `sig < n`; the modulus is anchored to a trusted digest before use, so this is defence-in-depth only. | `src/oca_platform.c:121-123,365-366`; `src/rsa_verify.c:127-154` |
| SEC-37 | `measurement_enroll_rom_hash()` enrolls the *parsed embedded* hash, not the *computed* one, after a single early-returning compare loop. A glitched loop causes slot 0 to attest the build-time claim for a ROM that does not match it. | `src/measurement.c:99-112` |
| SEC-38 | `static uint32_t g_vconsole_prev_val;` is defined in a header consumed by ~15 translation units, giving each its own copy and its own `.bss`. Harmless, but the de-duplication the toggle bit is for works only within a TU. | `include/rom_virt_console.h:33` |
| SEC-39 | `boot_recovery` and `primary_chiplet` are read once from SMC straps with no redundancy and no lifecycle restriction, so holding a pin switches a PROD part from the SPI boot source to the SMC-staged one (which is where SEC-08 lives). The manifest must still authenticate, so this is attack surface rather than a bypass. | `src/boot_straps.c:22-26`; `src/rom_main.c:748-776` |

---

## 3. Regressions vs the old manifest path

Security properties the deleted `manifest_load.c` / `manifest_crypto.c` enforced that the new OCA path does not, or enforces more weakly:

1. **`SBOOT_DIS` was bit-masked and passed by value; it is now a whole-word `!= 0` MMIO re-read.** The old `secure_boot_enabled()` took a masked `bool` argument with an explicit comment about not re-reading mutable shared state; the new `plat_is_secure_boot_disabled()` reads the register and tests the whole word, making 31 hardware-driven reserved bits equivalent to the chicken bit. **SEC-03, High.** The strongest regression in the change set.
2. **Secret zeroization lost its single-exit discipline.** `decrypt_payload()` funnelled every path — `aes_init()` failure included — through one `cleanup:` label that wiped `class_key`, `derived_key`, `info` and `salt`. `plat_decrypt_payload()` has five returns, and the `aes_init()` one leaves the raw `CLASS_KEY` on the stack. **SEC-07, Medium.**
3. **Anti-rollback narrowed from 256 fuse bits to 128.** The old `get_security_version_from_fuse()` read all eight `BL1_VERSION` words; the new callback reads 16 bytes and documents that anything above bit 127 "is not read". **SEC-22, Medium.**
4. **Payload gap and tail zeroization dropped.** The old TOC walk cleared the bytes between images and after the last one so that every payload byte was either inside a validated image or zero. Nothing does this now. Declared in `doc/rom.adoc:3105-3107`. **SEC-23, Low/Medium.**
5. **The trusted-key set widened from one key to six, and the private halves moved into this repository.** `origin/main`'s `key_digests.c` populated slot 0 only, from a key in an external submodule, and carried the warning "Production builds MUST replace this file with real key digests". This branch populates all six slots from PEMs committed at `tests/signing_keys/`, and replaces that warning with "The slot number is the whole identity". **SEC-01, Critical.**

Two things the new path does **better**, worth stating so the comparison is fair:

- **Retry scope.** Under the old code a slot that failed signature or payload verification ended the boot; the new `try_manifest_slot()` runs the entire per-slot sequence inside the retry, so the backup slot genuinely recovers from a crypto failure, and per-slot verdicts report as `WARN` rather than `ERROR` (`src/oca_boot.c:424-479`).
- **Fuse-key digest addressing.** The old path derived the fuse digest banks as `CHIPLET_PUBK_REVOKE + 0x100/+0x120`, which landed on `SPI_PHY_DLL_SLAVE` and the middle of `CHIPLET_PUBK_HASH0`. `otp_key_digest_addr()` now uses the generated register symbols (`src/oca_platform.c:337-361`). The bug was latent because only slot 0 was ever exercised; it is now fixed and the reasoning is recorded at the call site.

---

## 4. Dimensions reviewed with nothing material to report

- **Heap usage.** None. No `malloc`/`free`/`sbrk` anywhere; `-nostdlib` at link and `--specs=picolibc.specs` only for the generated headers' `<assert.h>`. The `.data`/`.bss` footprint in the built image is 28 + 104 bytes; everything else is stack.
- **Stack overflow.** Not a practical risk. The built image leaves `[0xC0040084, 0xC005FF00)` ~= 130 KB of stack for an RSA-3072 verify whose largest frames are three 384-byte word arrays. `link/rom.ld:84-89` carries two link-time `ASSERT`s on DCCM overflow and the stack window's orientation, and `rom_main.c:667-671` cross-checks the linker's reserve against the header's constant — a genuinely good check, correctly explained. The only note is the absence of `-Wstack-usage` (SEC-21).
- **Classic memory-safety bugs in the ROM's own parsing.** The called-out classes were looked for specifically and not found. The staging arithmetic at `src/oca_boot.c:253,332-336` is correct at every constructible boundary: `pk.body_size > SRAM_SIZE` rejects first, `payload_off = (body_size + 7) & ~7` cannot exceed `SRAM_SIZE` for any accepted `body_size`, and `payload_span > SRAM_SIZE - payload_off` cannot underflow. `boot_flash_range_within()` and both `contains_range*` variants guard addition overflow explicitly. The structural parsing that would historically carry these bugs has been delegated to the library, which is the single largest architectural improvement in the change.
- **Dangerous libc.** Clean. No `printf`, `sprintf`, `strcpy`, `strcat`, `strlen`, `memcpy`, `atoi` or format strings anywhere in `src/` or `include/`; all output is the fixed-form scratch-register protocol, and all copies are explicit byte loops or the DMA. This is exactly right for a boot ROM.
- **TOCTOU / double-fetch on the status ring.** `status_ring_buffer_insert()` snapshots `head`, `tail`, `entries` and `num_entries` once, validates the snapshots, and writes using the snapshots (`src/status_ring.c:77-129`). The wrapped pointer arithmetic was traced for adversarial `num_entries` and the destination check remains consistent with the store, so an SMC that lies about the ring cannot make the ROM write outside SMC SRAM. Correct as written, and the ordering comment is accurate.
- **TOCTOU between verification and use of the payload.** Verification and use both operate on the single staged copy in SEP SRAM, never on flash — `src/oca_boot.c:9-19` states this as the design rule and `try_manifest_slot()` follows it ("authenticate the COPY, never storage"). There is a residual window between `oca_check_payload_at()` and the ICCM copy at `rom_handoff.c:232`, which matters only if another bus master can write SEP SRAM; see section 5.
- **Constant-time comparison.** Every security-relevant comparison accumulates over all bytes: the root-key digest (`oca_platform.c:491-494`), the full PKCS#1 v1.5 structure (`rsa_verify.c:97-121`, with a `volatile` accumulator), and PKCS#7 padding (`aes_driver.c:291-319`, folded over a fixed 16 iterations). The early-returning compares found — `measurement.c:99-104` on the ROM hash, `rom_handoff.c:58-64` on the image type, `rom_main.c:335-340` on the self-test vector — are all over public values. No standard `memcmp` is used on a secret.
- **Endianness and word size.** Consistently handled. Every multi-byte field is assembled byte-by-byte with explicit shifts (`oca_platform.c:74-86`, `hmac_sha256.c:136-141`, `rsa_verify.c:72-89`), so nothing depends on host byte order, and `hmac_sha256.c:10-12` and `rsa_verify.c:9-20` document the word/byte conventions against the specific IP. No type-punned struct overlay on an untrusted buffer anywhere in the ROM's own code. The 64-bit narrowing at the library boundary is the one gap (SEC-19).
- **BSS clearing and startup ordering.** Sound and well argued. The memory-health gate runs in assembly before any DCCM write (`vector.S:426-548`), with the reasoning for the placement — a corrupted `lc_state` biasing toward `TEST_DEV` — spelled out at L438-445. `.data`/`.bss` init is verified from C by two sentinels (`rom_main.c:108-109, 229-233`), and `init_bl0_state()` is correctly ordered before every `bl0_state` writer with the reason stated (`rom_main.c:651-658`).
- **Error-code hygiene.** `rom_err_fail()` deliberately declines to truncate a 32-bit subsystem code into the 16-bit status field, with a concrete example of the misdecode that motivated it (`rom_main.c:203-215`). `status_for_result()` maps 30 library verdicts to distinct `SEP_MSG_*` values rather than collapsing them (`oca_boot.c:159-224`). No error code collapses to success on any traced path; `OCA_BOOT_ERR_RESULT(OCA_OK)` is `0x00030000`, non-zero. `rom_manifest_boot()`'s retry loop was checked specifically for a path that returns `last_err == 0` without a successful slot; none could be constructed.
- **Doxygen and code clarity.** Uneven but above average for firmware. `include/harden.h`, `include/sep_helpers.h`, `include/measurement.h`, `include/sep_entropy.h` and `include/oca_boot.h` are genuinely well documented, and `src/` comments consistently explain *why* — often recording the specific failure that motivated a line, which is exactly what a future maintainer needs. What is missing is Doxygen on the `oca_platform.c` callbacks (the most security-critical functions in the file have no `@param`/`@retval`) and explicit security markers: `doc/rom.adoc`'s requirement IDs (`SEP-ROM-SB-050`) are referenced from only a handful of sites, so a reader cannot tell from the code which blocks are the enforcement points. A consistent `/* SECURITY-CRITICAL: SEP-ROM-xxx-nnn */` marker at each verdict identified in SEC-05 would close that.

---

## 5. Assumptions and limits

What could not be settled from the source, and what would settle it:

1. **The RISC-V toolchain is not available on this host** (`riscv64-unknown-elf-gcc` and `riscv-none-elf-gcc` both absent; `RISCV_TOOLCHAIN` unset), and the audit was read-only by instruction. Every statement about the *built* image comes from the pre-existing `build/boot_rom.elf` (dated after every source file in `src/` and `include/`), inspected read-only with host `readelf`/`nm` 2.30. That is sufficient for section placement, symbol addresses and sizes — which is all that was claimed from it. It does not permit verifying codegen, so SEC-05's premise that the redundant-check idiom survives `-Os` is argued from the source and from `harden.h`'s design, not from disassembly. Rebuilding in the toolchain container and disassembling the verdict sites would settle it.
2. **Whether any non-SEP master can write `cold_scratch[7]` or SEP SRAM.** This is the hinge of SEC-24 and of the residual verify-to-use window noted in section 4. `sep_scratch.rdl` declares `sw=rw, hw=r` and the block lives in `sep_system_peripherals`, but the inbound fabric and the debug/JTAG path were not traced. Settled by the SEP xbar inbound filter configuration and the DFT/debug access policy for the peripheral window.
3. **Whether the `hmac_idle` / `otbn_idle` race in SEC-02 and SEC-15 is physically winnable.** The instruction-skip variant of SEC-02 is stated as fact, because it needs no timing assumption. The pure-race variant is a hypothesis. Settled by an RTL check of when `STATUS` de-asserts idle relative to the `CMD`/`hash_process` register write, or by a DV test that reads `STATUS` immediately after the command write.
4. **Whether the library rejects TOC `length`/`entry_point` values that exceed 32 bits**, which determines whether SEC-19's narrowing bug is reachable. The library internals were out of scope. Settled by a fuzz or directed test that packs a TOC entry with bits set above 32 and checks the verdict.
5. **Whether SEP SRAM is readable from outside SEP**, which determines whether SEC-17's plaintext residue is a disclosure path or only a hygiene issue. Settled the same way as (2).
6. **The physical register at SEP-view `0x40000020`**, which SEC-25's stray write targets. It was established *not* to be `SMC_CPU_CTRL.RESET_CTRL` (that is `0x39020`); what it actually is was not determined. Settled by the SMC address map for the block at the window base.
7. **Whether `CHIPLET_PUBK_REVOKE[5:0]` is burned on production parts.** This is the only device-side control that could neutralise SEC-01 without a source change. Nothing in this repository can answer it, and `src/oca_platform.c:664-668` confirms the ROM never burns it. Settled by the production provisioning flow.
8. **`SEP_ENTROPY_BRINGUP` in adopter builds.** `Makefile:157` defaults it to 1, so the chain comes up in this tree. With it 0, `ENTROPY_PREREQ()` compiles to `((void)0)` (`src/oca_platform.c:48-53`) and AES and OTBN run with whatever the DV `+sep_crypto_edn_force` shortcut leaves — i.e. on silicon, unseeded. No guard was found that prevents a release build from setting it to 0; adding an `#error` for that combination would close it.
9. **`mstatus.MPP` at the `mret` in `jump_to_bl1()`** (`src/rom_handoff.c:97-103`) is never set. This is safe only if the fitted VeeR EL2 hardwires `MPP` to M-mode. `doc/rom.adoc:893-895` states the snapshot has `RV_USER_MODE 1`, which makes `MPP` writable and its reset value implementation-defined — so BL1 could in principle be entered in U-mode. DV passing suggests it reads 3 in practice. Settled by reading `mstatus` in the ROM immediately before the jump, or by setting `MPP` explicitly, which costs two instructions and removes the dependency.
