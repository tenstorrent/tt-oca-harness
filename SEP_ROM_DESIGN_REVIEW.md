# SEP Boot ROM — Design & Product-Readiness Review

| | |
|---|---|
| **Subject** | SEP production boot ROM, `hw/sys/sep/bootrom/prod/` |
| **PR** | [#1590 `dv/sep: Integrate the SEP ROM OCA manifest`](https://github.com/tenstorrent/tt-oca-harness/pull/1590) — open, CHANGES_REQUESTED |
| **Branch** | `inmcm/sep_rom_oca_manifest_int` (bootrom diff byte-identical to PR head) |
| **Baseline** | `origin/main` |
| **Date** | 2026-09-16 |
| **Reviewer** | `embedded-software-design-reviewer` agent |
| **Method** | Read-only. No builds, make targets or simulations were run. Measurements taken from pre-existing committed artifacts. |
| **Companion** | Deep cryptographic / fault-injection / side-channel analysis is a separate `embedded-security-auditor` pass; see §6 for the handoff list. |

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

**Not ready to mask; ship-with-fixes as a pre-silicon/VP deliverable.** The OCA integration itself is the strongest part of this change: the split between `oca_boot.c` (storage, slot selection, reporting) and `oca_platform.c` (hardware callbacks) is the right boundary, it earns its complexity by deleting 1200 lines of hand-rolled parsing, the per-slot retry now correctly spans crypto, and `doc/rom.adoc` is unusually honest engineering documentation with a requirement index and a gap matrix. But three properties block mask and a fourth blocks non-owner ownership: **(a)** there are six unbounded hardware waits on the cold-boot path in a ROM that by ratified policy never arms a watchdog — and two of them (secure-DMA completion, HMAC message-FIFO) are outside the enumerated, ratified set and are not observable through the status channel the policy relies on; **(b)** **no release build configuration exists at all** — `-DTEST_BUILD=1 -DDEBUG` are unconditional in `CFLAGS`, so the image that would be masked has never been compiled, and 54 of 82 DV test files assert on `simputs()` console text that a release build compiles out, so the suite cannot validate it either; **(c)** the ROM self-measurement (`soft_pcr[MEAS_SLOT_ROM]`, the attestation root) covers `.text` only and provably excludes `.rodata` — which holds all six root-key digests, the OTBN RSA-3072 program and the PKCS#1 constants — while the trust-anchor pointer table itself sits in *writable* DCCM; **(d)** the ROM firmware has **zero CI coverage** — `rom_fw` is explicitly excluded from `all`, and no GitHub workflow references it, so nothing gates this code but a manual ~20-hour regression run by its author. The code has had no substantive human engineering review yet, and the documentation entry point a new maintainer is pointed at (`README.md` → `doc/index.adoc`) still describes `src/manifest_load.c` and `src/manifest_crypto.c`, which this branch deletes.

---

## 2. Findings

### Blockers

---

**DES-01 — Six unbounded hardware waits on the cold-boot path, no watchdog, two of them outside the ratified policy and unobservable**
Severity: **Blocker** · Dimension: Reliability & robustness · Effort: **M**

`hw/sys/sep/bootrom/prod/src/sep_dma.c:154-171`, `src/hmac_sha256.c:95-97`, `src/hmac_sha256.c:122-133`, `src/hmac_sha256.c:149-152`, `src/pll_init.c:48-51`, `src/status_ring.c:41-46`, `src/oca_boot.c:411-414`, `include/sep_smc_interface.h:205-213`

`doc/rom.adoc:677-683` ratifies the policy: *"The ROM shall not arm the watchdog timer … Consequently every unbounded wait in the ROM (fuse sense, PLL lock, SMC hand-shake spins) hangs the boot rather than triggering a retry — this is the accepted failure mode for BL0, observable through the status channel."* That enumeration is incomplete in two load-bearing places:

- `sep_dma.c:154` — *"Wait for completion (no timeout in the ROM DMA path)"*, `for (;;)` on `SECURE_DMA_STATUS`. Every manifest head read, body read, payload read, ICCM zero and BL1 copy goes through this. A DMA that neither completes nor errors (clock/reset sequencing, a stalled crossbar master, an ASID misprogramming) hangs the ROM permanently.
- `hmac_sha256.c:95/124/150` — `do { … } while (s.f.fifo_full)` and `while (credit == 0u)` in `fifo_feed()`, with no bound, inside `sha256()`. The surrounding `wait_for_completion()` *is* bounded by `HMAC_TIMEOUT`; the feed is not. This is on the ROM self-hash, the manifest hash, the payload hash and the KDF.

Neither is "observable through the status channel" at the claimed granularity: neither emits a status word before entering the spin, so a hang leaves `cold_scratch[1]` at a coarse stage marker (`SEP_MSG_MANIFEST_LOAD_START`, or whatever preceded the measurement), and the `simputs()` text that would disambiguate is DEBUG-only (see DES-02). `src/sep_ot_spi.c` bounds every one of its polls with `OT_SPI_POLL_MAX` — the team plainly knows how; the DMA and HMAC drivers are inconsistent with it, not with a considered policy.

*Failure scenario:* a part whose secure-DMA clock gate is mis-sequenced by an SoC integration bug boots to a dead core with `cold_scratch[1] = 0x01010212` (MANIFEST_LOAD_START) and no further evidence. It is indistinguishable from a manifest that is slow, a stalled SPI read, and a hung HMAC. In the field it is an RMA with no diagnosis; pre-silicon it is a DV timeout that costs a full debug cycle to attribute.

*Direction:* bound the DMA completion poll and the HMAC FIFO polls the way `sep_ot_spi.c` does, returning the existing `SEP_MSG_DMA_ERROR` / `-1` paths; emit a distinct `report_status()` immediately before entering each remaining ratified spin so `cold_scratch[1]` names the wait rather than the stage; and extend `doc/rom.adoc:681`'s enumeration to be exhaustive and machine-checkable (a grep gate over `src/` would do it). The ratified no-watchdog posture can stand — what cannot stand is a hang whose location the ROM does not report.

---

**DES-02 — No release build exists; the image that would be masked has never been compiled, and the DV suite cannot validate it**
Severity: **Blocker** · Dimension: Build system / CI · Effort: **M**

`Makefile:207` (`-DTEST_BUILD=1 -DSEP_BL0 -DDEBUG`, unconditional), `Makefile:82` (`BUILD_TYPE ?= test`, used only in the rebuild stamp at `Makefile:299`), `include/rom_virt_console.h:26,97-110`, `README.md` ("Configuration" section)

`README.md` states the problem plainly and then ships it: *"There is no enforced release build mode in the current Makefile: `TEST_BUILD=1` and `DEBUG` are always present in `CFLAGS`, and `BUILD_TYPE` only participates in the rebuild stamp."* Consequences that compound:

1. The three built variants (`build/`, `build_ot/`, `build_ot_pio/`) are all debug images. There is no target that produces the candidate mask image, so its footprint, timing, and control flow are unmeasured — `-DDEBUG` off removes several hundred `simputs()` call sites and will change code layout, size, and the ROM self-hash.
2. 54 of the 82 files under `hw/sys/sep/dv/cocotb/tests/rom_fw/` reference the console, and the assertions are on `simputs()` strings (`MANIFEST_OK`, `PAYLOAD_OK`, `PUBK_AUTHORIZED`, `MANIFEST_ERR=0x…`, `MANIFEST_ALL_FAILED`). With `DEBUG` undefined those macros become `((void)0)` and the evidence vanishes. The suite is structurally unable to test a release image.
3. `rom_metadata.c:14-17` pins the version string to a fixed placeholder to keep the debug image's hash reproducible — so the ROM identity a release image would report is also unexercised.

*Failure scenario:* the team decides to mask. Someone defines `-UDEBUG`, the image shrinks and relocates, the whole `rom_fw` regression goes red on missing console markers, and the only way to get a green signal is to mask the debug image — which is what will then happen under schedule pressure.

*Direction:* introduce a real `BUILD_TYPE=release` that drops `DEBUG`/`TEST_BUILD` (and keep it in `BUILD_FLAGS` so the stamp catches it), then move the DV suite's *pass/fail* assertions onto the always-compiled `report_status()` stream (`cold_scratch[1]` and the SMC status ring), keeping console markers as diagnostic-only enrichment. Add one release-build variant to the regression so the mask candidate is exercised. This finding gates DES-01's observability claim and DES-06's usefulness.

---

**DES-03 — No compiler warnings enabled anywhere, with a comment asserting the opposite**
Severity: **Blocker** · Dimension: Build system & quality gates · Effort: **S**

`Makefile:197-214` (full `CFLAGS`), `Makefile:346-351`

`CFLAGS` contains `-Os -ffreestanding -fno-builtin -fdata-sections -ffunction-sections -mno-relax -MMD -MP --specs=picolibc.specs` plus `-D` flags and `$(CC_ABI)`. There is **no** `-Wall`, `-Wextra`, `-Werror`, `-Wconversion`, `-std=`, or `-pedantic`. `ASFLAGS` and `LDFLAGS` likewise. For ~8 100 lines of freestanding C driving a security processor's root of trust, this is the single cheapest gate in the review and it is absent.

Worse, the rule that compiles the vendored library asserts a discipline the build does not apply:

```make
# -Wno-pedantic is deliberately NOT set: the library builds clean under its own
# -Wall -Wextra -Werror -pedantic, so a warning here means a real toolchain or
# flag mismatch worth seeing rather than silencing.
$(OCA_LIB_OBJS): $(OCA_OBJ_DIR)/%.o: $(OCA_LIB_DIR)/%.c | $(OCA_OBJ_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"
```

`$(CFLAGS)` carries no warning flags at all, so "a warning here means a real mismatch" is vacuous — there are no warnings to see. A reader of this comment will believe the library is compiled under `-Werror` in this tree. It is not.

*Maintenance scenario:* a non-owner adds a `uint16_t` truncation, a missing `return`, a sign-compare in a bounds check, or an uninitialised local in a new callback. Nothing in the build, and nothing in CI (DES-06), says a word. Several existing constructs would light up immediately — the ignored `oca_result_t st` at `src/oca_boot.c:79`, the ignored return values of `otbn_dmem_write`/`otbn_dmem_read` (`src/rsa_verify.c:150-158`), the `uint64_t` loop counter on RV32 at `src/rom_handoff.c:75`.

*Direction:* `-std=c11 -Wall -Wextra -Werror -Wconversion -Wshadow -Wundef -Wvla -Wstack-usage=<N>` on the ROM's own objects (the submodule's may need a staged ramp), plus `-fstack-usage` for DES-25. Given the language standard is currently unspecified, pin it. Fix the misleading comment or make it true.

---

**DES-04 — The ROM self-measurement excludes every trust anchor and the RSA verifier program**
Severity: **Blocker** · Dimension: Architecture / observability / security hygiene · Effort: **M**

`src/measurement.c:88-96`, `tools/insert-rom-sha256.py` (`ICCM_SECTIONS`), `link/rom.ld:34-45`, `Makefile:221-222`

The hashed region is `[OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR, __metadata_end)` — `.text` plus `.metadata`. Read from the committed artifact:

```
100482c8 R __metadata_end        # == __metadata_start: .metadata is EMPTY
100482c8 R __metadata_start      # nothing in the tree uses section(".metadata")
10049170 r digest_rom_key0       # .rodata — OUTSIDE the hashed range
1004922c R otbn_rsa_3072_app_imem (0x1734 = 5940 B)  # .rodata — OUTSIDE
1004a9e0 A __data_load_start     # .data ROM image — OUTSIDE
```

`.metadata` is empty, so the measured region is exactly `.text` (33 480 B). Outside it: all six ROM root-key digests, the OTBN RSA-3072 application image that performs the modexp, the PKCS#1 v1.5 `DigestInfo` constants (`src/rsa_verify.c:60-67`), the SHA-256 self-test vector, and the ROM image of `.data` — 10 036 bytes, 23 % of the ROM, comprising the entire trust anchor set and the verifier.

`insert-rom-sha256.py`'s own docstring says `ICCM_SECTIONS` *"must match Makefile ITCM_ELF_SECTIONS"*; the Makefile variable was renamed to `ROM_ELF_SECTIONS` and **does** include `.rodata`/`.srodata` (`Makefile:221-222`), so the image loaded into the part and the image measured have diverged and the stated invariant is unchecked. The tool, `rom_metadata.c:6-9` and `measurement.h:43-48` all describe the hashed region as "ICCM" and place `g_rom_sha256_str` "in `.rodata` (DCCM)"; `link/rom.ld:40-45` puts `.rodata` in ROM and `boot_rom.sym` puts the symbol at `0x10049000`. Three artifacts documenting a memory model the linker script contradicts.

*Failure scenario:* two mask revisions differing only in `key_digests.c` — different production root keys, or a test-key ROM versus a production-key ROM — produce byte-identical `soft_pcr[MEAS_SLOT_ROM]` and identical `g_rom_sha256_str`. An attestation verifier cannot tell them apart, and the boot-state record (`MEAS_SLOT_BOOT_STATE`) does not cover the anchors either. Equally, a mask defect in the OTBN program is invisible to the self-check at `src/measurement.c:93-104` that is specifically meant to prove "what is executing" matches "what the build claimed".

*Direction:* extend the hashed region to the full ROM contents that are loaded (`.text` + `.metadata` + `.rodata` + `.data` LMA), keep `g_rom_sha256_str` out of it by placing it in a dedicated section after the hashed range with a linker-provided `__rom_hash_region_end`, and make `insert-rom-sha256.py` derive its section list from one Make variable shared with `ROM_ELF_SECTIONS` so the two cannot drift. Add a `_Static_assert`-equivalent build check that the measured range and the loaded image agree. Hand the attestation-semantics question (what the PCRV record must commit to) to the security auditor.

---

**DES-05 — The root-key trust-anchor table lives in writable DCCM**
Severity: **Blocker** · Dimension: Architecture / security hygiene · Effort: **S**

`src/key_digests.c:40-47`, `include/key_digests.h:52`, `src/oca_platform.c:432-439`

```c
public_key_info_t public_key_digests[NUM_PUBLIC_KEY_DIGESTS] = { … };   // not const
```

```
c0040004 D public_key_digests    # .data — DCCM, writable, 0xC0040004
10049170 r digest_rom_key0       # the digests themselves are const, in ROM
```

The digest *arrays* are correctly `static const` in ROM, but the pointer table indexed by `plat_is_key_authorized()` at `oca_platform.c:436` is a mutable RAM object. `key_digests.h:37-40` says *"Per-key information stored in ROM"* and `vector.S:586-597` copies it into DCCM at boot, contradicting that. The ROM's whole value proposition is immutability; a single mutable indirection defeats it for the secure-boot anchor.

*Failure scenario:* any DCCM write with a controlled address before `[S23]` — a stack overflow (undetectable, DES-25), a DMA destination bug, a future BL0 feature, or a fault-injected store — can repoint `public_key_digests[0].digest` at attacker-chosen bytes staged in SEP SRAM, and `plat_is_key_authorized()` will then compare the presented key's SHA-256 against those bytes and authorise it. The fail-closed `NULL` guard at `oca_platform.c:432` does not help; a non-NULL wrong pointer passes it.

*Direction:* make the table `const public_key_info_t public_key_digests[]` (it becomes `.rodata`/ROM, also shrinking `.data` to 4 bytes), update the `extern` in `key_digests.h`, and have `generate_key_digests.py` emit `const`. Consider dropping the indirection entirely for a fixed-size `const uint8_t [6][32]`, which removes the pointer from the trust path. Defer fault-injection hardening of the comparison itself to the security auditor.

---

**DES-06 — The ROM firmware is gated by nothing in CI**
Severity: **Blocker** · Dimension: CI / quality gates · Effort: **M**

`hw/sys/sep/dv/testlists/all.toml:7-10,47-54` and the `rom_fw` group definition; `.github/workflows/sim.yml:91-101`; `.github/workflows/regress.yml:98-115,225-232`

`rom_fw` holds 71 enrolled tests (`grep -c '^\[\[tests\]\]' testlists/rom_fw.toml` → 71) across 82 files. `all.toml` states it explicitly: *"Boot ROM firmware (`rom_fw`) is NOT a member … Reaching these tests means naming `rom_fw` (or the test) explicitly."* The PR gate (`sim.yml`) runs `items: smoke_sep0` for `sep`; the nightly (`regress.yml`) runs `items: sep0_all`. Both are the toolchain-free SEP=0 sets with no `c_compile` stage. `rg -l 'rom_fw' .github/` returns nothing.

So: **no CI job compiles this ROM, and no CI job executes it.** The only gate is the ~20-hour manual `rom_fw` regression the ROM-FW owner runs by hand. Combined with DES-03 (no warnings), a non-owner can merge a change to this masked-ROM codebase with no automated signal whatsoever — not even a compile.

Note that `hw/sys/sep/doc/checks/` (added by this branch) provides six mechanical doc-consistency checkers and its own README nominates four as *"the ones worth gating CI on"* — and none is wired into any Makefile or workflow either.

*Direction:* add, in ascending cost: (1) a PR-gate job that *compiles* all three ROM variants plus the OCA library under `-Werror` and reports `size` (needs only the toolchain container, no simulator); (2) a small `rom_fw_smoke` group — `sep_rom_non_secure_boot_test`, `sep_rom_ot_dma_boot_test`, `sep_rom_oca_tamper_test`, one demotion test — on the nightly; (3) the four gate-worthy doc checks as a `make` target in the lint job. The full 71-test group can stay owner-driven, but "it compiles and the happy path plus one refusal path boot" must not be a manual step.

---

**DES-07 — `[S02]` "PMP execution fences" do not constrain the ROM at all in the default build**
Severity: **Blocker** · Dimension: Architecture / security hygiene · Effort: **L**

`src/vector.S:352-424`, `Makefile:80-81` (`PMP_ENABLE ?= 1`, `PMP_LOCK ?= 0`), `src/rom_main.c:20` (`[S02] PMP execution fences`)

Unlocked PMP entries do not apply to machine-mode accesses, and the ROM runs exclusively in M-mode. With the default `PMP_LOCK=0`, the seven entries programmed at `vector.S:368-424` have **zero** effect on the ROM's own fetches, loads or stores; `[S02]` is a no-op that reads as a security control at every call site and in the boot-flow comment header. The entries are also mislabelled: the block comment at `vector.S:364-366` describes `entry4` as "Periph `0x1090_0000..0x10BF_FFFF` (3MiB)" while `vector.S:381-383` computes `0x0421ffff` for 4 MiB at `0x10800000`, and `entry6` is labelled "SMC MMIO" at `0xC000_0000..0xCFFF_FFFF` while the SMC window this ROM actually uses is `0x40000000` (`vector.S:73`) and is covered by no entry at all. Entry 3 grants SRAM RWX from cold boot, before any manifest has been validated.

To the team's credit this is documented, not hidden: `doc/rom.adoc:836-837,900,983,989,3066` states it, and `SEP-ROM-PMP-020` ("Fences must bind machine mode (lock/Smepmp)") plus `-060/-070/-080` specify the Smepmp mechanism as *"ratified, not implemented"*.

*Failure scenario:* the ROM's stated defence against "skipped-stage faults" (`doc/rom.adoc:936`) does not exist in silicon. A control-flow fault that lands in staged SRAM executes, because SRAM is RWX and M-mode is unconstrained. Once masked, this cannot be added.

*Direction:* implement the ratified `SEP-ROM-PMP-060/-070/-080` sequence (`RLB` → locked rules → `MMWP`) before mask, flip `PMP_LOCK` to 1 by default, correct the three wrong region comments, and — until it is implemented — remove or qualify the `[S02] PMP execution fences` label in `rom_main.c` so no reader infers a control that is not there. Depth on fault-injection value belongs to the security auditor.

---

**DES-08 — The documentation entry point describes the design this branch deleted**
Severity: **Blocker** · Dimension: Documentation & onboarding · Effort: **M**

`doc/index.adoc:34-35`, `doc/index.adoc:51-63`, `README.md:24`, `README.md` ("Build variants", "Outputs", "Configuration")

`README.md` points a new engineer at `doc/index.adoc`, whose Overview says the implementation comprises *"manifest and payload processing in `src/manifest_load.c` and `src/manifest_crypto.c`"* — both deleted by this branch (−809 and −393 lines). `index.adoc` then `include::`s seven chapters (`boot-flow`, `hardware-initialization`, `memory-security`, `spi-manifest`, `smc-coordination`, `status-errors`, `bl1-handoff`, 709 lines total) **none of which this branch touched**, so every one of them describes the pre-OCA format and flow. `README.md:24` still tells the reader to init the `tt-boot-manifest` submodule (replaced by `tt-oca-manifest`), and its target/output tables list `pack-images`, `secure_boot_spi`, `encrypted_boot_spi`, `non_secure_boot.bin`, `smc_mem.hex` — none of which exist in the new Makefile, which has `oca-images`, `oca_*.bin` and `oca_smc_mem.hex`. Its Configuration table gives `ROM_ICCM_CLEAR_ENABLE` default `0`; `Makefile:78` now defaults it to `1`.

The new `doc/rom.adoc` (3 347 lines) is genuinely good and supersedes all of this — but it is not reachable from `README.md` or from `doc/index.adoc`, so a non-owner following the documented path lands on the obsolete set.

*Maintenance scenario:* the first non-owner task on this ROM starts by running `make pack-images` (fails), then reading `spi-manifest.adoc` to understand the format (wrong format), then looking for `manifest_load.c` (absent). Every documented starting point is wrong; only the undocumented one is right.

*Direction:* make `doc/rom.adoc` the ROM document — either replace `doc/index.adoc`'s body and includes with it, or delete the seven superseded chapters and re-point `index.adoc`. Rewrite `README.md`'s Prerequisites, Build variants, Outputs and Configuration tables against the current Makefile. Note the open reviewer request against this PR on `hw/sys/sep/doc/index.adoc:28` (keep the SEP ROM doc standalone, drop the include so lowRISC can wire it later) — that request and this consolidation should be resolved together so the ROM doc has exactly one home.

---

### Major

---

**DES-09 — `sep_dma_zero()` corrupts the first word of the staged, authenticated manifest**
Severity: **Major** · Dimension: Business-logic correctness · Effort: **S**

`src/sep_dma.c:185-194`, `src/oca_boot.c:234`, `src/rom_handoff.c:201-224`, `src/oca_boot.c:373`

```c
uint32_t sep_dma_zero(uint32_t dest, size_t len) {
    const uint32_t zero_word = (uint32_t)SEP_EXT_SRAM_BASE;   // 0x10000000
    *(volatile uint32_t *)(uintptr_t)zero_word = 0u;          // CPU store
    return dma_transfer(dest, zero_word, (uint32_t)len, 0);
}
```

`SEP_EXT_SRAM_BASE` is `OCH_SEP_TOP_SEP_SRAM_BASE_ADDR`; `oca_boot.c:234` stages the manifest body at exactly that address (`uint8_t *const body = (uint8_t *)(uintptr_t)SRAM_BASE;`). The comment at `sep_dma.c:188-189` claims *"the word is consumed before any payload is staged there"* — true for `rom_iccm_clear()` at `[S16]`, false for the ICCM ECC pad in `rom_handoff_bl1()`, which runs at `[S29]` **after** staging and is enabled in the default build (`ROM_ICCM_CLEAR_ENABLE=1`, `ROM_ICCM_CLEAR_FULL=0`, `Makefile:78-79`) whenever BL1 targets ICCM.

So at hand-off the first four bytes of the authenticated body — the OCA magic — are overwritten with zero, and `bl0_state.sep_sram_manifest_addr` (set at `oca_boot.c:373`) then hands BL1 a pointer to a manifest that no longer parses.

*Failure scenario:* BL1 (or a debugger, or `trap_handler_c`'s `MADDR=` diagnostic at `rom_main.c:93`) re-reads the manifest BL0 vouched for and gets `OCA_FAIL_MAGIC` on a perfectly good boot. Today nothing in the ROM re-reads it after `[S27]`, so this is latent — it becomes a hard BL1 boot failure the moment BL1 parses the manifest it is handed, which is precisely what `sep_sram_manifest_addr` exists for.

*Direction:* source the fill word from somewhere the boot flow does not stage into — a word of `.rodata` in ROM is an allowed DMA source only if the range check at `sep_dma.c:99-103` is extended, so the simplest correct fix is a dedicated 4-byte scratch at the *top* of the SEP SRAM window (above any staged payload, bounds-checked) or a `.data` word in DCCM with DCCM added as a permitted source. Delete the now-false comment either way.

---

**DES-10 — BL1 copy length is rounded up *after* the region bounds check**
Severity: **Major** · Dimension: Reliability / bounds correctness · Effort: **S**

`src/rom_handoff.c:137-142` (check), `src/rom_handoff.c:199` (rounding), `src/rom_handoff.c:232` (copy)

```c
const bool iccm_span = contains_range(ICCM_BASE, ICCM_SIZE, bl1->load_addr, bl1->length);
…
img_length = (img_length + 3u) & ~3u;          // line 199 — after the check
uint32_t dma_err = sep_dma_copy(load_addr, bl1.bytes, img_length);
```

The permitted-region check at `:137-142` uses the manifest's `length`; the DMA is issued with `length` rounded up to a word. A BL1 whose `load_addr + length` lands within 1–3 bytes of the ICCM (or SRAM) end passes the check and then has up to 3 bytes written past the region it was authorised for. `sep_dma.c:91-94` re-checks the destination, so today the transfer is rejected rather than escaping — meaning the observable symptom is a spurious `BL1_COPY_FAIL` on a legitimate image, reported as `SEP_MSG_BL1_BAD_ADDR`. There is no bounds check on `load_addr` alignment either, and the `#if ROM_ICCM_CLEAR_ENABLE && !ROM_ICCM_CLEAR_FULL` pad at `:210` computes `pad_start = (load_addr + img_length) & ~7u` from the *rounded* length.

*Failure scenario:* a production BL1 grows to a size that puts its end 2 bytes short of the ICCM top. It validates, it is authorised, and the copy is refused with an address error — an un-bootable part with a misleading verdict, discovered only in the field or in a late size-pressure respin.

*Direction:* round `img_length` up before the placement check and validate the rounded value, or check both the declared and the rounded span. Either way the checked quantity and the copied quantity must be the same number.

---

**DES-11 — Two readers of `SBOOT_DIS` disagree on which bits matter**
Severity: **Major** · Dimension: Business-logic correctness · Effort: **S**

`src/oca_platform.c:605-610` versus `src/rom_main.c:726-728`

```c
// oca_platform.c — the value the validation library uses
uint32_t sboot_dis = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR);
return (sboot_dis != 0u) ? OCA_SECURE_TRUE : OCA_SECURE_FALSE;

// rom_main.c — the value recorded in bl0_state and in the boot measurement
sboot_dis = (sboot_dis_reg & SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm) != 0u;
```

The library's secure-boot determination treats *any* set bit in the `SBOOT_DIS` fuse word as "secure boot disabled"; the ROM's own record masks bit 0. The comment at `oca_platform.c:606-607` asserts they are the "same `SBOOT_DIS` shadow", which is true of the address and false of the predicate.

*Failure scenario:* a later fuse-map revision allocates any other bit in that word, or a single stuck/aggressed bit elsewhere in it reads 1 — and `plat_is_secure_boot_disabled()` returns `OCA_SECURE_TRUE`, relaxing the library's secure-boot invariant, while `bl0_state.sboot_dis` and the boot-state measurement (`measurement.c:124`) record `0`. Secure boot is disabled and the attestation record says it was not. This is also a divergence the auditor should look at as a fault-injection target.

*Direction:* one accessor, in one place, masking `SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm`, called by both `rom_main.c` and the callback. Add a DV case that sets a non-bit-0 bit in the word and requires the two to agree.

---

**DES-12 — The "only check that the source stays inside the boot slot" does neither in the default build**
Severity: **Major** · Dimension: Architecture / trust boundary · Effort: **M**

`include/boot_flash.h:196-205` (Cadence branch), `include/boot_flash.h:158-195` (OT branch), `src/oca_boot.c:105-118`

`oca_boot.c:105-118` asserts of `boot_flash_bounds_ok()`: *"It is the only check that the SOURCE stays inside the boot slot being tried … The gate is fault-injection hardened (doubled, laundered evaluation) and defaults to reject."* Both claims hold only on the `BOOT_SPI_CONTROLLER_OT=1` branch. The default build is `BOOT_SPI_CONTROLLER_OT=0` (`Makefile:87`), where the entire gate is:

```c
uint32_t src = (uint32_t)SEP_SPI_BASE + flash_off;
return boot_flash_range_within(src, len, (uint32_t)SEP_SPI_BASE, (uint32_t)SEP_SPI_MAX_SIZE);
```

— a single, un-laundered check against the whole XIP window, with no slot confinement at all. `PRIMARY_MANIFEST_OFFSET`/`BACKUP_MANIFEST_OFFSET` and `slot_span` do not appear.

*Failure scenario:* on the Cadence path a manifest in the primary slot can name a payload anywhere in the XIP window, including inside the backup slot, and the transport gate permits it. The library's `oca_locate_payload()` bounds the payload *location* against `[region_base, region_limit)` — which `oca_boot.c:402-403` sets to the entire XIP window on this path, not to the slot — so nothing confines a slot to itself. The stated defence-in-depth is absent exactly where the comment says it is present. Cross-slot confinement semantics warrant the security auditor's attention.

*Direction:* make the Cadence branch structurally identical to the OT branch — same slot-span test, same doubled/laundered evaluation, same default-reject — and pass per-slot `region_base`/`region_limit` into `oca_locate_payload()` (currently whole-window) so the library bounds the slot the ROM is actually trying.

---

**DES-13 — Storage-read failures lose their cause, DMA errors emit no status word, and the obvious fix will not compile**
Severity: **Major** · Dimension: Observability · Effort: **S**

`src/oca_boot.c:240-242,258-261,339-342`; `src/sep_dma.c:45-48,161-170`; `include/status_values.h:110`

All three call sites collapse every non-zero result to one code:

```c
if (manifest_src_read(…) != 0u) { return OCA_BOOT_ERR_DMA; }
```

so `OCA_BOOT_ERR_READ_OUT_OF_BOUNDS` (0x00030106), the code the header defines for a refused read, is **unreachable** — a bounds refusal and a DMA hardware error both report 0x00030100. The distinction survives only in `simputs("FLASH_READ_OOB\n")`, which a release build compiles out (DES-02).

Separately, `dma_transfer()` emits no `report_status()` at all on error — only DEBUG console text (`sep_dma.c:163-167`) — so a DMA failure contributes nothing to the status ring. And the natural remedy is blocked: `sep_dma.c:46-47` defines a local enum member `SEP_MSG_DMA_ERROR = 0x00020002u` while `status_values.h:110` defines the macro `SEP_MSG_DMA_ERROR 0x9d`. The build only survives because `sep_dma.c` does not include `errors.h` (confirmed: `grep -c status_values.h build/sep_dma.d` → 0). Adding one `report_status()` call to that file makes the preprocessor expand `0x9d = 0x00020002u` inside an enum and the build fails with an error that names neither cause.

*Failure scenario:* a field RMA reports "boot stopped, error 0x00030100". That is equally a wedged DMA engine, a flash that returned a bus error, and a manifest whose payload offset pointed out of the slot — three different dispositions (board rework, flash replacement, re-sign the image). Meanwhile the next maintainer's first instinct — report DMA errors on the status channel — hits a preprocessor collision.

*Direction:* propagate `manifest_src_read()`'s return value instead of overwriting it; rename the `sep_dma.c` local enum out of the `SEP_MSG_*` namespace (e.g. `SEP_DMA_ERR_*`) and give the DMA its own `report_status()` codes; add `SEP_MSG_DMA_OUT_OF_RANGE` to the status table.

---

**DES-14 — The SMC-published manifest offset is used unvalidated as a DMA source**
Severity: **Major** · Dimension: Reliability / trust boundary · Effort: **S**

`src/oca_boot.c:411-419,437-446` versus `src/rom_main.c:258-280`

On the recovery and secondary paths:

```c
for (;;) { if (smc_scratch_read(SMC_SCRATCH_STATUS_TO_SEP_IDX) & SMC_SEP_STATUS_MANIFEST_READY) break; }
offsets[0] = smc_scratch_read(SMC_SCRATCH_MANIFEST_ADDR_IDX);
…
manifest_src = sep_get_smc_sram_base() + offset;
```

`offset` is a 32-bit value from an SMC-writable scratch register, added to the SRAM base with no range check and no overflow check. `manifest_src_read()` explicitly skips its bounds gate for non-SPI sources (`oca_boot.c:119`, *"Non-SPI sources … are bounded by their own region"*) — but nothing bounds this one; only `dma_transfer()`'s destination/source range check at `sep_dma.c:96-103` stands between it and an arbitrary read, and that check accepts any address in the SMC SRAM window, the XIP window or SEP SRAM. Notably `rom_smc_coordination_probe()` at `rom_main.c:273` *does* reject `0xFFFFFFFF`; the code that actually consumes the offset does not.

*Failure scenario:* an SMC that publishes a stale or garbage offset (its own firmware bug, an uninitialised scratch, a partial reset) causes the ROM to peek 20 bytes from an unrelated address. Best case `oca_peek_manifest()` rejects it and, since `num_retries = 0` on this path (`oca_boot.c:417`), the boot ends with a single attempt and no retry. Worst case the source lands outside every permitted window, `dma_transfer()` returns out-of-range, and the failure reports as `OCA_BOOT_ERR_DMA` (DES-13) — blaming the DMA for the SMC's bad pointer.

*Direction:* validate `offset` against `[0, SMC_SRAM_SIZE_BYTES - OCA_MANIFEST_PEEK_MIN]` with the same `boot_flash_range_within()` helper before use, reject `0xFFFFFFFF` as `rom_smc_coordination_probe()` already does, and give the refusal its own status code. Document whether the SMC is inside or outside the ROM's trust boundary on this path — the code currently treats it as fully trusted while `oca_boot.c:406-408` describes it as "just another address space".

---

**DES-15 — A magic offset where the named constant is already in scope, against an unpinned submodule**
Severity: **Major** · Dimension: Maintainability / coupling · Effort: **S**

`src/oca_boot.c:87-95`, `src/oca_boot.c:28`, `.gitmodules`

```c
// Little-endian u16 at OCA_OFF_DEMOTION_CONTROL (172). Read by hand rather
// than through the library: it exposes no accessor for this field …
return (uint32_t)g_body[172] | ((uint32_t)g_body[173] << 8);
```

`oca_boot.c:28` includes `oca_layout.h`, which defines `#define OCA_OFF_DEMOTION_CONTROL 172u` (`tools/tt-oca-manifest/validators/oca/lib/oca_layout.h:92`). The comment names the constant and the code uses the literal. The sibling accessor forty lines up argues the opposite case for itself: *"Located through the library's own variant descriptor rather than a literal offset … Asking the library keeps this correct across a submodule uprev instead of silently measuring the wrong 32 bytes"* (`oca_boot.c:76-84`). The reasoning is right; it just was not applied here.

This matters more than usual because the submodule is unpinned by design — `.gitmodules` specifies `branch = main`, the library sources are globbed (`Makefile:145`), and there is no format-version or layout assertion anywhere in the ROM build. `doc/rom.adoc:3122-3127` records that a previous uprev already moved *"every offset from `payload_encryption_control` onward"*.

*Failure scenario:* the next uprev moves `demotion_control`. `rom_oca_demotion_control()` silently reads two unrelated bytes. If the stray bits happen to clear `OCA_DEMOTE_BL1_VALID` and set `BL2_VALID|BL2_ENABLE`, `rom_main.c:450-455` takes the one branch that leaves `DEMOTE_1` **unlocked** — the failing-open case the comment at `rom_main.c:417-420` was written to prevent. No test would catch it; the demotion tests use fixed manifests and assert console markers.

*Direction:* use `OCA_OFF_DEMOTION_CONTROL`. Add `_Static_assert`s in `oca_boot.c` pinning the layout constants and the `oca_result_t` range the error encoding at `oca_boot.h:22-26` depends on (*"an `oca_result_t` is 0..34"*), so a submodule uprev that breaks an assumption fails the build instead of the boot. Record the expected submodule commit in the ROM docs, or pin it.

---

**DES-16 — `[S15]` SEP SRAM clear is disabled by default to accommodate a DV fixture**
Severity: **Major** · Dimension: Use-case fit / security hygiene · Effort: **M**

`Makefile:54-57`, `src/rom_mem_clear.c:37-64`, `src/rom_main.c:708-711`

```make
# Off, and not for speed: rom_clear_ext_sram() runs before the manifest load and
# would wipe the warm handler sep_scratch_7_test preloads at SRAM_BASE + 0x100.
# Stays off until that preload can be staged after the cold-boot scrub.
SRAM_SCRUB_BYTES ?= 0
```

`SEP-ROM-CPU-100` requires *"SRAM + ICCM cleared before external content"* (`doc/rom.adoc` requirement index). With the default, `[S15]` prints `SRAM_CLR_SKIP` and clears nothing, in all three shipped variants. The stated reason is not cost — it is that one cocotb test (`sep_scratch_7_test`) preloads a warm handler into the region the scrub would clear.

*Failure scenario:* SEP SRAM is the staging area for decrypted BL1 plaintext and the manifest body. Across a warm/watchdog reset the region is *not* reset by hardware (`vector.S:186-190`), and the cold path does not clear it either, so a previous boot's decrypted payload persists into a subsequent boot that may take a different, non-secure manifest — and into whatever reads SRAM next. Separately, on silicon the region powers up with undefined ECC, which `rom_clear_ext_sram()` is the ROM's only means of establishing for the parts of SRAM a manifest does not fill.

The retry path makes this doubly inconsistent: `oca_boot.c:460` calls `clear_sram_region(SRAM_BASE, SRAM_SIZE)` — the same 65 536 CPU stores the scrub was disabled to avoid — on every failover, so the cost argument is not being applied consistently either.

*Direction:* stage `sep_scratch_7_test`'s preload after the cold-boot scrub (the testlist already notes this as inherited), then default `SRAM_SCRUB_BYTES` to the full window and let DV override it downward. A production ROM's memory sanitisation policy must not be a function of one testbench's fixture ordering.

---

**DES-17 — `bl0_state.error_code` is four unrelated numbering schemes in one field, and subsystem codes never reach the status register**
Severity: **Major** · Dimension: Observability · Effort: **M**

`src/rom_main.c:165-181,196-227,250`; `src/lifecycle.c:110,140`; `src/sep_dma.c:45-48`; `src/sep_entropy.c:117-120`; `include/oca_boot.h:25-36`

Four conventions arrive at the same `uint32_t`:

| Source | Encoding | Example |
|---|---|---|
| `rom_main.c:165-181` | `0x0000X00Y` | `ROM_ERR_STACK_OVERFLOW 0xF001` |
| `oca_boot.h:25-36` | `0x0003xxxx` (tagged subsystem) | `0x00030100` |
| `sep_dma.c:46-47` | `0x0002000x` | `0x00020002` |
| `sep_entropy.c:119` | a raw `SEP_MSG_*` value | `0x226` |

plus two bare literals outside every registry: `0x0000A001` (`rom_main.c:250`, SMC memory sanity) and `0x0000A002` (`lifecycle.c:110`). A debugger or BL1 reading `error_code` cannot tell which namespace a small value belongs to — `0x226` is simultaneously a plausible `SEP_MSG_*` and a plausible `ROM_ERR_*`.

Compounding it, `rom_err_fail()` deliberately suppresses the status word for any tagged code:

```c
if ((error_code & 0xFFFF0000u) == 0u) { STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_ERROR, error_code & 0xFFFF)); }
```

The suppression reasoning is sound, but the comment's justification is not: *"The full 32-bit code still reaches the mailbox below, so DV loses no information"* — and the code eleven lines later says *"The error code is NOT repeated here"*. The 32-bit value reaches only `bl0_state.error_code` in DCCM (lost on cold reset) and the DEBUG console (compiled out in release). The `rom_manifest_boot()` re-report at `oca_boot.c:474-477` recovers most of it, which is good design — but the comment as written will mislead the next person to touch this.

*Direction:* one `errors.h` registry with a mandatory subsystem tag in the upper half for *every* code, including the two literals and the entropy path; assign `0x0000Fxxx` to the ROM core rather than leaving it untagged; fix the contradictory comment pair at `rom_main.c:203-219`.

---

**DES-18 — Uncalibrated, fail-closed MBIST timeout in the pre-C boot gate**
Severity: **Major** · Dimension: Reliability / timing · Effort: **S**

`src/vector.S:139-159,484-492`

```
/* Bound on the wait for mbist_done. PLACEHOLDER, NOT CALIBRATED -- no expected
 * MBIST duration was available when this was written. */
.equ MBIST_DONE_WAIT_ITERS, 10000
```

Timeout → `dft_gate_failed` → hang unless the `SKIP_MEM_CHECK` fuse is blown. The analysis in the comment is careful and the value is justified as a simulation-cost trade-off, but an uncalibrated bound on a fail-closed gate is a yield risk that cannot be fixed after mask.

*Failure scenario:* MBIST on silicon at a cold corner takes longer than ~300 K REFCLK cycles. Healthy parts hang at `cold_scratch[1] = 0x08010219` and the only recovery is blowing a fuse that the same comment (`vector.S:112-118`) says *"nobody has any reason to have blown"*. That is a field-return class of failure affecting good silicon.

Note also that the fuse this gate depends on is documented at `vector.S:125-135` as *"an unallocated bit borrowed from another chip's map"* inside `reserved[31:2]` of `STATUS_RPT` — so the escape hatch itself is not yet allocated in the register map.

*Direction:* obtain the MBIST duration before mask and set the bound to measured worst case plus margin; until then, prefer proceeding-with-a-WARN over hanging if the hardware genuinely releases the CPU only after repair (the comment at `vector.S:155-157` already argues this), and allocate `STATUS_RPT[2]` in the RDL.

---

**DES-19 — Virtual-console de-duplication state is per-translation-unit, so console output is silently dropped across module boundaries**
Severity: **Major** · Dimension: Observability · Effort: **S**

`include/rom_virt_console.h:35-43`

```c
static uint32_t g_vconsole_prev_val;                 // in a header, non-inline

static inline void vconsole_write_scratch2(uint32_t val) {
    if (val == g_vconsole_prev_val) val ^= 1u;       // toggle so the monitor sees a change
    mmio_write32(…COLD_SCRATCH…(2), val);
    g_vconsole_prev_val = val;
}
```

Every translation unit that includes this header gets its own `g_vconsole_prev_val`. The toggle bit exists because the cocotb monitor detects a *change* in `cold_scratch[2]`, so two identical consecutive writes are indistinguishable from one. Across a TU boundary each unit's shadow is stale, the toggle is not applied, and the second write is lost.

*Failure scenario:* `oca_boot.c` ends a slot attempt with a 3-character ASCII group and `rom_main.c` begins with the same group — the second write never appears in the log. Concretely, three-character-aligned repeats such as the trailing `"\n"` groups and repeated markers straddling `oca_boot.c`/`rom_handoff.c`/`rom_main.c` will drop. Because `simputs()` packs three characters per write, this silently corrupts console text in exactly the multi-module failover sequences that matter most for triage — and 54 of 82 DV tests assert on that text (DES-02).

*Direction:* move the shadow to a single definition (one `.c` file with an `extern` declaration, or `__attribute__((used))` in `rom_metadata.c`), or make it a hardware read-back. This also removes ~30 redundant `.bss` words.

---

**DES-20 — The invalid-lifecycle SMC reset uses a hand-coded offset and mask on the one path that runs under a fuse fault**
Severity: **Major** · Dimension: Maintainability / reliability · Effort: **S**

`src/lifecycle.c:24-26,131-139`

```c
#define SMC_CPU_CTRL_RESET_CTRL_OFFSET 0x0020u
…
uint32_t rst = mmio_read32(smc_base + SMC_CPU_CTRL_RESET_CTRL_OFFSET);
rst |= 0xFu;   // core0~core3 reset_n bits → hold all cores in reset
mmio_write32(smc_base + SMC_CPU_CTRL_RESET_CTRL_OFFSET, rst);
```

Every other register access in this ROM goes through generated `OCH_*_BASE_ADDR` symbols. This one — which asserts reset on four SMC cores, the most destructive action the ROM takes — uses a literal offset and a literal mask, on the path taken when the lifecycle fuse is invalid (i.e. a suspected fuse attack or hardware fault). The comment at `lifecycle.c:25-26` describes the bits as `core*_reset_n_n0_scan`; whether OR-ing 1s asserts or releases reset for an active-low field is not verifiable from here, and `hw/sys/sep/doc/checks/check_reg_addresses.py` (added by this branch) exists precisely to catch this class of drift but does not cover `src/`.

*Failure scenario:* the SMC register map moves `RESET_CTRL`. The ROM writes `|0xF` into whatever now lives at `+0x20` — plausibly a clock or power control — on a fault path, then hangs. The resulting behaviour is a different, worse failure than the one being handled, and it is only reachable under conditions nobody tests.

*Direction:* use the generated SMC symbol and field mask. If the SMC map is not visible from the SEP ROM's include path, add the one symbol to `sep_smc_interface.h` with a comment naming the RDL field, and extend `check_reg_addresses.py` to cover bootrom sources.

---

**DES-21 — `pll_init()` reports the fuse-declared frequency without confirming the mux switched, and that value programs SPI timing**
Severity: **Major** · Dimension: Reliability · Effort: **S**

`src/pll_init.c:46-64`, `src/rom_main.c:647,762`

After spinning on lock detect (unbounded, DES-01) the function writes `0x04040101` to a mux register — *"Value … selects PLL for both sysclk and peripheral clock and may need platform-specific tuning"* — performs no read-back, and returns `pll_freq_mhz` read from the fuse. `rom_main.c` passes that value to `rom_spi_init()` → `boot_flash_init()` → `spi_set_sysclk()`, which derives SPI divisors from it.

*Failure scenario:* the mux write does not take (wrong value for the part, a locked field, an SMC-side gate). The ROM continues on REFCLK at 100 MHz while every consumer believes it is running at the fuse-declared PLL frequency. SPI divisors are then wrong by that ratio, the flash read returns corrupt data, and the failure surfaces as `OCA_FAIL_MAGIC` or `OCA_FAIL_MANIFEST_HASH` — a signed-image problem, reported for a clock problem, on both slots. Worse: `report_status(STATUS_TYPE_INFO_EXT, smu_freq_mhz)` at `rom_main.c:648` publishes the wrong number as fact.

*Direction:* read back the mux select and, where the hardware permits, confirm the frequency (a counted REFCLK/sysclk ratio, or an SMC-published status bit); on mismatch fall back to REFCLK with a distinct WARN rather than returning an unverified value. The magic `0x04040101` should be built from generated field macros the way `sep_entropy.c:63-76` does.

---

**DES-22 — Stale build artifacts committed to git as part of this branch**
Severity: **Major** · Dimension: Build hygiene · Effort: **S**

`hw/sys/sep/dv/fw/tests/bl1_pass_test/build2/`, `build2_ot/`, `build2_ot_pio/`, `build3/`

`git ls-files` shows eight tracked binaries — four `bl1_pass_test.bin` and four `.sym` — added by this branch. `.gitignore:22` ignores `**/build/` but not `build2`/`build3`, and the ROM Makefile consumes only `$(BL1_TEST_DIR)/build/bl1_pass_test.bin` (`Makefile:115`). So these are unreferenced snapshots of the BL1 payload that the boot chain depends on, which will silently diverge from `bl1_pass_test.c`.

*Maintenance scenario:* a new maintainer debugging a BL1 handoff finds four checked-in BL1 binaries and reasonably assumes one is authoritative. None is. Meanwhile the secret scanner noise on this PR is on test keys, not these — so they merge unremarked.

*Direction:* delete them and widen the ignore pattern to `build*/`.

---

**DES-23 — `doc/rom.adoc` describes a `cold_scratch[0]` write the code explicitly refuses to make**
Severity: **Major** · Dimension: Documentation accuracy · Effort: **S**

`doc/rom.adoc:695` versus `src/rom_main.c:618-625`

Doc: *"[S05] ROM identity | ROM version string and build-time SHA-256 are emitted …, and the `'COLD'` marker is written to `cold_scratch[0]`."*

Code:

```c
// Nothing is written to cold_scratch[0] here: it carries the terminal verdict
// only (errors.h VERDICT_OUT), and a second writer with unrelated semantics
// would make a single read ambiguous. The console line below reports the cold
// boot instead.
simputs("COLD\n");
```

The code's reasoning is correct and the doc is wrong — about the verdict register, which is the channel the doc itself nominates as the observable one (`doc/rom.adoc:683`) and which DV gates on. A post-mortem procedure written from the doc would look for a `'COLD'` marker that never exists, and worse, might interpret a stale `cold_scratch[0]` as evidence of a cold boot.

*Direction:* correct the doc row. More generally, the four `hw/sys/sep/doc/checks/` scripts this branch adds cover xrefs, tables, manifest offsets, register addresses and error codes — none checks doc claims about *which register the ROM writes*; the status/verdict channel table at `doc/rom.adoc:2880-2900` is a good candidate for a mechanical check against `rg 'VERDICT_OUT|STATUS_OUT' src/`.

---

**DES-24 — Doc-consistency checks and the status-table generator are wired into nothing**
Severity: **Major** · Dimension: CI / quality gates · Effort: **S**

`hw/sys/sep/doc/checks/README.md`, `hw/sys/sep/doc/gen_status_table.py`

Six checkers and one generator, added by this branch, all invoked only by hand:

> *"Run them all before publishing a doc change: `for f in hw/sys/sep/doc/checks/check_*.py; do … done`"* … *"`check_tables.py`, `check_manifest_offsets.py`, `check_reg_addresses.py` and `check_error_codes.py` are clean-exit-on-success and are the ones worth gating CI on."*

The README names the four that should gate CI; none does. `gen/status_values.adoc` is generated from `include/status_values.h` but nothing verifies the committed output is current, so the ROM's published status table can silently drift from the header the firmware uses. Given DES-08 (a whole stale doc set merged alongside a new one), a mechanical check is the only thing that will keep `doc/rom.adoc` true as the ROM evolves.

*Direction:* add a `make` target running those four checks plus a `--check` mode on `gen_status_table.py`, and put it in the existing lint workflow (docs-only PRs already skip the heavy jobs, so the cost is trivial).

---

**DES-25 — The stack canary sits 130 KB below the stack top and cannot detect any realistic overflow; worst-case depth is unmeasured**
Severity: **Major** · Dimension: Performance & resource budget · Effort: **S**

`src/rom_main.c:158-163,734-738,527-539`, `link/rom.ld:71-89`

From the committed ELF:

```
c0040084 A __stack_bottom     # == __bss_end, where the canary is written
c005ff00 B __stack_top        # initial sp
```

The stack window is 0x1FE7C = **130 684 bytes**. Measured consumers are tiny by comparison: `rsa_3072_verify()` alone holds `n_words[96] + sig_words[96] + result[96]` ≈ 1 160 B (`src/rsa_verify.c:141-158`), the deepest chain is `rom_manifest_boot → try_manifest_slot → oca_validate_manifest → plat_verify_signature → rsa_3072_verify`, and `kdf.c` adds a 196-byte `msg[]`. The canary at `__stack_bottom` would only be disturbed by an overflow of roughly 128 KB.

So `[S19]`/`[S28]` — described at `rom_main.c:527-536` as the check that *"has to be after [S23], which is where the stack actually peaks"* — cannot fail for any plausible cause, and `doc/rom.adoc` records the canary re-check as **closed**. The real gap is that nobody knows the worst-case depth: there is no `-fstack-usage`, no `-Wstack-usage=`, no watermark fill, and no reported number. The `SEP-ROM-HOFF-020` stack-top check is separately recorded as absent.

*Direction:* keep the canary (it is nearly free) but make the measurement real: fill the stack window with a pattern in `vector.S` alongside the DCCM scrub, and at `[S28]` scan for the watermark and emit the high-water mark via `report_status()`. One DV run then yields a number for the datasheet and for the DCCM budget, and a regression in it becomes visible. Add `-fstack-usage -Wstack-usage=4096` to the build so a new deep frame or a VLA fails the compile.

---

**DES-26 — No footprint reporting or headroom check in the build**
Severity: **Major** · Dimension: Build system / resource budget · Effort: **S**

`Makefile:380-400`, `link/rom.ld:13-22,84-89`

The link step produces `.elf`, `.dis`, `.sym`, `.vmem`, `.itcm.hex`, `.dtcm.hex` and no size report. `rom.ld` asserts DCCM overflow and stack-window sanity but says nothing about ROM occupancy — `ld` will error on overflow, which means the first signal that the 64 KiB budget is gone is a hard link failure, with no warning as headroom shrinks. There is no documented ROM size target anywhere in `README.md` or `doc/rom.adoc`.

Measured from the committed artifacts (host `size -A`, three variants):

| Variant | `.text` | `.rodata` | ROM used | of 64 KiB | free |
|---|---|---|---|---|---|
| `build/` (Cadence) | 33 480 | 10 008 | 43 516 | 66.4 % | 22 020 |
| `build_ot/` | 36 188 | 10 236 | 46 456 | 70.9 % | 19 080 |
| `build_ot_pio/` | 35 428 | 10 172 | 45 632 | 69.6 % | 19 904 |

Comfortable today — but the not-yet-implemented work (Smepmp PMP sequence, handoff self-check ledger, payload gap zeroing, a real release-logging path) all lands in `.text`, and `Makefile:151-152` notes PQC support as *"the largest ROM-size lever available if the 64 KiB budget gets tight"*, implying it is being watched informally.

*Direction:* add a `size` target to the link recipe printing per-section and total ROM occupancy against 65 536, and a `rom.ld` `ASSERT` on a headroom floor (e.g. fail under 8 KiB free) so shrinkage is caught as it happens rather than at the moment it becomes a blocker. Wire the size print into the CI build job from DES-06.

---

### Minor

---

**DES-27 — Hardware failures reported as image failures, contrary to the file's own stated convention**
Severity: **Minor** · Dimension: Observability · Effort: **S** · `src/oca_platform.c:247-249,272-274`

`oca_platform.c:106-110` establishes the rule and follows it: a wedged HMAC core returns `OCA_FAIL_CALLBACK_UNAVAILABLE`, not a hash mismatch, *"reporting it as one would blame the image for a hardware fault."* Twenty lines later `aes_init()` failing (AES stuck in reset, or never reporting idle after an EDN reseed) returns `OCA_FAIL_DECRYPT`, and so does `aes_pkcs7_strip()`. A dead AES block reports as a bad encrypted payload, which fails over to the backup slot — where the same dead block will fail again, costing a full second slot attempt before the boot ends with the wrong verdict. Return `OCA_FAIL_CALLBACK_UNAVAILABLE` for `aes_init()`.

---

**DES-28 — 34 library verdicts collapse onto ~20 status values**
Severity: **Minor** · Dimension: Observability · Effort: **S** · `src/oca_boot.c:159-224`

`OCA_FAIL_MAGIC` and `OCA_FAIL_TRAILER` both → `SEP_MSG_INVALID_MANIFEST_ID`; `PAYLOAD_HASH` and `PAYLOAD_HASH_CHAIN` → one code; four distinct secure-boot verdicts → `SEP_MSG_MANIFEST_SECURE_BOOT`. The full verdict survives in the low byte of `error_code` (good design, `oca_boot.h:20-26`), but a field triage working from the status ring alone cannot distinguish "not an OCA manifest at all" from "trailer malformed" — different dispositions. Add status values for the collapsed pairs; `status_values.h` has ample room above `0x226`.

---

**DES-29 — Dead code and stale API left by the manifest swap**
Severity: **Minor** · Dimension: Maintainability · Effort: **S**

Verified single-occurrence (definition only, no caller): `ranges_overlap` (`include/sep_helpers.h:25`), `smc_read_lc_state` (`include/sep_smc_interface.h:189`), `smc_read_dft_status` (`:193`), `lc_state_is_rma` (`src/lifecycle.c:71`), `rom_oca_body()` (`src/oca_boot.c:59`, exported but unused), `ROM_ERR_SMC_COORD_NOT_READY` / `ROM_ERR_SPI_INIT_FAILED` / `ROM_ERR_DFT_GATE_BLOCKED` (`src/rom_main.c:170-172`), and four status values orphaned by the deletion of the separate `[S24]` stage: `SEP_MSG_CRYPTO_VALIDATE_START`, `SEP_MSG_READ_BL1_SECURITY_VERSION`, `SEP_MSG_VALIDATE_CHECK`, `SEP_MSG_USING_SEP_SRAM`. `-Wunused` (DES-03) would have surfaced the statics.

---

**DES-30 — Comments that record what changed rather than what is true (`AGENTS.md` bans these)**
Severity: **Minor** · Dimension: Code quality · Effort: **S**

Commented-out dead code kept as history: `src/rom_main.c:127-129` — *"SPI init failure is no longer fatal. Kept as documentation of the previous approach. `// #define ROM_FAIL_ON_SPI_INIT_ERROR 0`"*. Breadcrumbs: `src/oca_platform.c:312-320` (*"NOTE the addresses are the generated symbols, not the previous ROM's … arithmetic, which landed on SPI_PHY_DLL_SLAVE … That path was never exercised … so the bug sat latent"*); `src/oca_platform.c:43-47` (*"which is what this replaces"*); `src/rom_main.c:417-420` (*"Skipping the write whenever the BL1 valid bit was clear left DEMOTE_1 unwritten and unlocked … it failed open"*); `src/rom_main.c:400-401` (*"Keeping the SBOOT_OFF marker because DV asserts its absence"* — justification aimed at a reviewer); `src/vector.S:62-64` (*"and a comment claiming 'must be within ICCM' while the constants said SRAM"*); `src/vector.S:465-466` (*"which the previous version of this gate did not implement at all"*). The same pattern runs through `doc/rom.adoc`'s implementation matrix, which mixes current status with change history (*"Rows marked closed were gaps in an earlier revision … kept rather than deleted so the record of what changed is not lost"*, `:3020-3022`) and cites merge state that this PR invalidates (*"unmerged | Implemented (commit `3de14630f`); not on `main`"*, twice). All of this belongs in commit messages and a changelog. Note that `ROM_FW_REGRESSION_RESULTS_20260915.md`, `ROM_FW_REGRESSION_TRIAGE.md`, `DV_LONG_RUNS_GUIDE.md`, `EVIDENCE_GATE_ROM_FW_TICKET.md` and `OCA_CLASS_CONTROL_DOC_TICKET.md` are untracked in the worktree root — confirm they are not intended for the PR.

---

**DES-31 — Duplicated and factually wrong file headers**
Severity: **Minor** · Dimension: Documentation · Effort: **S**

`src/rom_handoff.c:4-26` carries **two** versions of the same "BL1 handoff sequence" block, the first saying *"copy to ICCM"* and the second *"copy to SRAM"* — the pre- and post-rewrite text, both left in place. `src/status_ring.c:4-10` repeats its two-line description verbatim. `src/aes_driver.c:4-16` is titled *"AES-128-CBC decryption driver"* and its step list says *"Configure: DEC mode, CBC, AES-128"* although the driver now implements 128 and 256 (`:204-218`) and AES-256 is the new default per the PR intent. `src/rom_metadata.c:6-9` and `tools/insert-rom-sha256.py`'s docstring both state the hash *"covers the ICCM content"* and that `g_rom_sha256_str` lives *"in `.rodata` (DCCM)"* — the hashed region is Boot ROM, not ICCM, and `.rodata` is in ROM per `link/rom.ld:40-45` (symbol at `0x10049000`). These are the comments a maintainer reads first.

---

**DES-32 — `OCA_BOOT_ERR_BL1_TOO_LARGE` returned for a zero-length image**
Severity: **Nit** · Dimension: Naming · Effort: **S** · `src/rom_handoff.c:157-161`

The ordering rationale (`:154-156`) is correct — length must be checked before entry point — but the code returned for `length == 0` is named "too large". Add `OCA_BOOT_ERR_BL1_EMPTY`, or rename to `OCA_BOOT_ERR_BL1_BAD_LENGTH`.

---

**DES-33 — `report_rom_hash()` comment and behaviour disagree; invalid hex silently reads as zero**
Severity: **Nit** · Dimension: Observability · Effort: **S** · `src/rom_main.c:552-581`

The comment says *"the first 4 hex chars (2 × uint16_t)"*; the loop emits two 16-bit words covering **8** hex chars. `char_to_int()` (`:555-562`) returns 0 for anything outside `[0-9a-f]` — uppercase included — so an unpatched or malformed `g_rom_sha256_str` reports a plausible-looking hash rather than an error. Since `Makefile:375-382` now makes the insert non-optional, prefer failing loudly on a malformed string.

---

**DES-34 — `status_values.h` claims to be generated from a file that does not exist**
Severity: **Minor** · Dimension: Maintainability · Effort: **S** · `include/errors.h:4-5,33`, `include/status_values.h`

Both headers say *"generated from `meta/status/status_values.tsv`"*. `find . -name status_values.tsv` returns nothing, and `hw/sys/sep/doc/gen_status_table.py:21` treats `include/status_values.h` as the source of truth. This branch hand-edits the "generated" file (three new defines). A file labelled generated invites `make`-then-overwrite; either add the generator and the TSV, or delete the claim and mark the header hand-maintained with the doc generator as its only consumer.

---

**DES-35 — Seven private keys committed to the open repository, with misleading provisioning guidance**
Severity: **Minor** (product-hygiene; see §6) · Dimension: Security hygiene · Effort: **S**

`tests/signing_keys/rsa_private_key.rom_key{0..5}.pem`, `tests/signing_keys/ec_private_key.pem`, `Makefile:458-461,522-527`

Six RSA-3072 private keys and one EC key are added to the open tree, and `src/key_digests.c` pins their public digests as the ROM's six root-key anchors. `doc/rom.adoc` records this correctly (*"ROM key digests | placeholder | `key_digests.c` holds six test keys, one per slot; production digests must land before mask finalization"*), and the rationale for six distinct keys (`Makefile:479-484`) is sound — it is what makes per-slot resolution and per-slot revocation testable.

Two problems remain. The Makefile's guard emits guidance that is now wrong: *"It ships in the tt-oca-manifest submodule, so this normally means the submodule is stale; re-run git submodule update"* — the path is `$(CURDIR)/tests/signing_keys/…`, inside this repo. And nothing in the build refuses to produce an image whose anchors are the committed test keys, so the only thing standing between a test-key ROM and a mask is the doc matrix row.

*Direction:* fix the guard text; add a `BUILD_TYPE=release` gate (DES-02) that fails the build if `key_digests.c` matches the test-key digests; and add a `README`/`doc` note next to the keys stating they are non-secret DV assets.

---

**DES-36 — `sep_entropy_init()`'s documented failure state is unreachable and its return value unused**
Severity: **Nit** · Dimension: API design · Effort: **S** · `src/sep_entropy.c:140,233-238`, `src/oca_platform.c:50`

`static int g_entropy_state; // 0 = untried, 1 = up, -1 = failed` — `-1` is never assigned, because `entropy_fail()` is `noreturn`. `ENTROPY_PREREQ()` discards the `int` return. The comment at `:236-237` acknowledges it. Either make the function `void` or give the caller a failure to handle; the current shape suggests a recoverable error that does not exist. The comment at `oca_platform.c:129` — *"Does not return on failure, but does fail the secure boot process"* — is confusing for the same reason.

---

**DES-37 — Zero-length transfers pass the DMA bounds check and then enter an unbounded wait**
Severity: **Nit** · Dimension: Reliability · Effort: **S** · `src/sep_dma.c:57-71,148-171`

`contains_range_u32()` returns 1 for `len == 0` (under a comment that reads *"Reject wraparound"*), so a zero-length request reaches `dma_write(CHUNK_DATA_SIZE, 0)` / `TOTAL_DATA_SIZE, 0` and then `for (;;)` on `DONE`. Whether the engine completes a zero-length descriptor is not documented here. All current callers bound their lengths above zero, so this is latent — but it is one length check away from being DES-01's worst case. Reject `len == 0` explicitly.

---

**DES-38 — Bare magic lifecycle values beside named constants**
Severity: **Nit** · Dimension: Code quality · Effort: **S** · `src/oca_platform.c:567-570`, `src/lifecycle.c:57-60`

```c
case LC_STATE_RMA_CHIPLET_LO:
case 0x5u:
case 0x6u:
case LC_STATE_RMA_CHIPLET_HI:
```

in both files. The RMA chiplet range is 0x4–0x7; name the two interior values or express the arm as a range test as `lc_state_is_rma()` does.

---

**DES-39 — Duplicate variable assignment and stale README config table**
Severity: **Nit** · Dimension: Build system · Effort: **S**

`Makefile:103` and `Makefile:414` assign `TT_OCA_MANIFEST_DIR` identically; the second (with its own comment block, also duplicated from the first) is redundant. `README.md`'s Configuration table gives `ROM_ICCM_CLEAR_ENABLE` default `0` against `Makefile:78`'s `1`, omits `BL1_SRAM_EXEC_ENABLE`, `ROM_ICCM_CLEAR_FULL`, `SEP_ENTROPY_BRINGUP`, `SEP_ENTROPY_DEFER_*` and `OCA_SUPPORT_*`, and its rebuild-stamp caveat is inverted (`BUILD_FLAGS` at `:298-307` tracks `ICCM_FULL`, not `ROM_ICCM_CLEAR_ENABLE`).

---

## 3. Regressions versus the replaced manifest path

Compared against `git show origin/main:hw/sys/sep/bootrom/prod/src/manifest_load.c` (809 lines) and `manifest_crypto.c` (393 lines):

| # | Property | Then | Now | Severity |
|---|---|---|---|---|
| R1 | **Documentation coherence** | `doc/index.adoc` + 7 chapters described the implemented flow and named the implementing files | Entry point names two deleted files; 7 chapters describe a format the ROM no longer parses; the accurate doc is unreachable from `README.md` | **Blocker** (DES-08) |
| R2 | **Staged-manifest integrity through hand-off** | The old loader staged and did not later reuse `SRAM_BASE` as a DMA fill source on the hand-off path | `sep_dma_zero()`'s fill word aliases the staged body's first word; the manifest handed to BL1 via `sep_sram_manifest_addr` is corrupted | **Major** (DES-09) |
| R3 | **Payload gap zeroing** | Legacy ROM zeroed un-hashed inter-image bytes after validation | Not done. `doc/rom.adoc` records it as *"gap (should) … legacy ROM did"* | Major (tracked) |
| R4 | **Read-refusal attribution** | Manifest-load errors were ROM-local codes reported directly | `OCA_BOOT_ERR_READ_OUT_OF_BOUNDS` is defined but unreachable — all read failures report as `OCA_BOOT_ERR_DMA` | Major (DES-13) |
| R5 | **Trust-anchor immutability** | `public_key_digests` had one populated slot; five `NULL` | Six populated slots, still in writable `.data`, now a live six-way trust path | Blocker (DES-05) |
| R6 | **Error-code namespace** | One manifest-error space | Four schemes plus two bare literals in one field | Major (DES-17) |

Genuine improvements over the replaced path, worth protecting: the retry now spans signature verification, decryption and payload checks (so a slot failing crypto rotates to the backup, where before it was terminal — `doc/rom.adoc` "Retry scope: closed"); per-slot verdicts are WARN and only exhaustion is ERROR (`oca_boot.c:248,474-477`); root-key authorisation happens *before* any public-key operation; the fuse-key digest banks are addressed by generated symbols instead of the old `CHIPLET_PUBK_REVOKE + 0x100` arithmetic that landed on the wrong register; the `DEMOTE_1` default is now closed rather than open; and `rom_bl1_check()` runs per slot before the fuse-secret lock so an unplaceable BL1 fails over instead of bricking after `[S25]`.

---

## 4. Resource budget

**Measured** (host `size`/`readelf`/`nm` on the pre-existing committed artifacts; `build/.build_flags` = `CTRL_OT=0 USE_PIO=0 PROFILE=0 BUILD_TYPE=test PMP_ENABLE=1 PMP_LOCK=0 BL1_SRAM_EXEC=1 ICCM_FULL=0 DCCM_SCRUB=0x20000 SRAM_SCRUB=0 OCA_CLASSIC=1 OCA_PQC=1 OCA_TOC_MAX=32 ENTROPY=1`):

ROM (64 KiB at `0x10040000`):

| Variant | `.text` | `.rodata` | `.data` LMA | Total | Used | Free |
|---|---|---|---|---|---|---|
| `build/` | 33 480 | 10 008 | 28 | 43 516 | 66.4 % | 22 020 |
| `build_ot/` | 36 188 | 10 236 | 32 | 46 456 | 70.9 % | 19 080 |
| `build_ot_pio/` | 35 428 | 10 172 | 32 | 45 632 | 69.6 % | 19 904 |

DCCM (128 KiB at `0xC0040000`): `.data` 28 B + `.bss` 104 B = 132 B; `bl0_state` reserve 256 B at the top (`__bl0_state_reserve = 256`, raised from 128 by this branch, matching `BL0_STATE_RESERVE_BYTES`; both `_Static_assert`s in `bl0_state.h:113,119` hold and the runtime cross-check at `rom_main.c:667` covers linker/header drift). Stack window `0xC0040084 → 0xC005FF00` = **130 684 B**. DCCM is ~99.8 % free.

Largest contributors (`nm -S --size-sort`): `otbn_rsa_3072_app_imem` 5 940 B (`.rodata`), `rom_main` 2 776 B, `rom_manifest_boot` 1 580 B, `_start` 916 B, `oca_check_payload_at` 824 B, `aes_cbc_decrypt` 788 B, `oca_validate_manifest` 720 B, `plat_is_key_authorized` 708 B, `sep_entropy_init` 680 B. `rom_main` at 2.7 KB for one function is almost entirely inlined `simputs()` — confirming DES-02's point that a release build will move significantly.

**Stack depth:** deepest observed single frame is `rsa_3072_verify` at ≈1 160 B of automatics (`src/rsa_verify.c:141-158`); `oca_derive_payload_key` adds a 196-byte `msg[]`; `measurement_enroll` a 64+32-byte pair. No recursion and no VLAs were found (`rg 'alloca|\[[a-z_]+\]' src/` clean; `find_bl1`'s loop bound comes from the library-validated TOC count). Against 130 KB the margin is enormous. The canary is therefore inert (DES-25).

**Not measurable read-only:**

- Actual worst-case stack depth through the OCA library — needs `-fstack-usage`/`-Wstack-usage` or a watermark fill; neither exists.
- Release-image footprint and timing — there is no release build (DES-02). The 66–71 % figures are for debug images.
- Boot latency / WCET on any critical path. No measured numbers appear in `README.md` or `doc/rom.adoc`. The only hard cycle figures found are DV-side: the `sep_rom_oca_tamper_test` docstring records ~1.65 M cycles for two slots read-and-rejected, and `Makefile:62` estimates the full-ICCM clear at ~1.8 M cycles.
- Effect of `OCA_SUPPORT_PQC=0` (named as the largest size lever, `Makefile:151-152`) — unquantified.
- Whether 19–22 KB of headroom absorbs the remaining pre-mask work (Smepmp PMP sequence, handoff self-check ledger, payload gap zeroing, release logging). No documented ROM budget target exists to check it against.

---

## 5. Test and CI gap table

`rom_fw` holds 71 enrolled tests across 82 files; it is excluded from `all`, from `smoke_sep0` (PR gate) and from `sep0_all` (nightly), and no workflow references it. **Every row's "Gated in CI" is No.** The PR test plan's *"covers nearly all new ROM changes"* is fair for the manifest-validation surface and optimistic elsewhere.

| ROM behaviour | Tested by | Gated in CI |
|---|---|---|
| OCA happy path, SMC-SRAM | `sep_rom_non_secure_boot_test` | No |
| OCA happy path, OT SPI, DMA + PIO drains | `sep_rom_ot_dma_boot_test`, `sep_rom_ot_pio_boot_test` | No |
| Signed boot, all 6 ROM key slots | `sep_firmware_{primary,backup}_rom_key_valid`, `rom_key1..5` images | No |
| Per-slot revocation, all 6 slots | `sep_firmware_{primary,backup}_pubkey_rom_0..5_revoked_key_test` | No |
| OTP key anchors (`CHIPLET_PUBK_HASH0/1`) | `sep_firmware_chiplet_pubkey_0/1{,_revoke,_wrong_digest}` | No |
| Tamper in signed region, both slots | `sep_rom_oca_tamper_test` | No |
| Backup failover (signature, sec-version, key select, empty slot) | 4 × `sep_firmware_backup_*` | No |
| Encrypted payload, AES-256 + OTP class key | `sep_rom_oca_encrypted_boot_test`, `sep_rom_oca_otp_key_boot_test` | No |
| Decrypt failure: failover and terminal | `sep_decryption_failure_{failover,terminal}_test` | No |
| Demotion matrix (PROD / PROD_END × flags) | 8 × `sep_firmware_demotion_*` | No |
| BL1 placement/entry/size rejects | `sep_bl1_{entry_invalid,size_invalid}_test` | No |
| Warm-reset dispatch, 4 arms | `sep_warm_reset_*`, `sep_scratch_7_test` | No |
| MBIST / MEM_REPAIR gate, 4 arms | `sep_firmware_mbist_*`, `sep_mbist_fail_continue_test` | No |
| Failover SRAM clear | `sep_failover_sram_clear_assertion_test` | No |
| OTBN modexp failure | `sep_otbn_rsa_verify_failure_test` | No |
| **The ROM compiles at all** | **nothing** | **No** |
| **Release build (`DEBUG` off)** | **nothing — cannot exist** (DES-02) | No |
| **Entropy bring-up failure paths** (`entropy_fail`, ESRC health fail/alert, EDN instantiate error, FIPS/src-sel lock failure) | **nothing.** Happy path is exercised; `doc/rom.adoc` notes simulation *"forces only the ESRC noise source"* | No |
| **PLL path** (`bl0_pll_clk` strap, lock wait, blank-fuse fallback, mux write) | **nothing** — no `rom_fw` test references PLL | No |
| **Full ICCM clear** (`ROM_ICCM_CLEAR_FULL=1`) **and the ICCM ECC pad** | **nothing** — neither build variant sets it | No |
| **DMA error and out-of-range refusal paths** | **nothing** | No |
| **HMAC engine failure / FIFO stall** | **nothing** | No |
| **ROM self-hash mismatch** (`ROM_ERR_ROM_HASH_MISMATCH`) | **nothing** — success path only | No |
| **Stack canary trip** (`ROM_ERR_STACK_OVERFLOW`) | **nothing**, and untrippable in practice (DES-25) | No |
| **`bl0_state`/linker reserve drift** (`ROM_ERR_BL0_STATE_OVERLAPS_STACK`) | **nothing** | No |
| **Fuse-secret lock failure** (`check_fuse_secrets_locked` false) | **nothing** | No |
| **Secondary-chiplet boot mode** (`BOOT_MODE_SECONDARY`) | **nothing** — recovery mode only (`sep_boot_recovery_test`) | No |
| **`status_report_disable` strap** | 1 reference; no dedicated test | No |
| **Secondary-hart park** (`vector.S:679`) | **nothing** | No |
| **SMC scratch sanity failure** (`0xA001`) | **nothing** | No |
| **Invalid-LC SMC core reset** (`lifecycle.c:131-139`) | **nothing** | No |
| **8 of 17 built OCA images** — `aes128_boot`, `sip_key_boot`, `identity_boot`, `pqc_boot`, `ecdsa_boot`, `der_boot`, `multi_image_boot`, `no_bl1_boot` | **no test loads them** (only 9 appear in any `flash_image`/preload assignment), so the algorithm-refusal, encoding-refusal, identity-constraint and multi-image TOC paths in `plat_verify_signature` / `plat_is_key_authorized` / `find_bl1` are unexercised despite the images being built every run | No |

**Host-side unit-testability:** none. `oca_boot.c`'s slot-failover loop, `status_for_result()`, `bl1_locate()`'s placement algebra, `rom_oca_demotion_control()`'s bit predicate and `aes_pkcs7_strip()` are all pure functions of their inputs and all currently require an RTL simulation and a ~20-hour regression to exercise. `rg -l 'oca_boot|rom_handoff|status_for_result|bl1_locate'` outside the ROM directory finds only DV tests and scratch notes. A small host harness (compile those files for the host with MMIO and `simputs` stubbed) would move most of DES-10, DES-11, DES-15 and DES-32 into a second-long test and give the ROM its first fast gate. The `tt-oca-manifest` submodule already ships `validators/oca/test/main.c` as a model.

---

## 6. Security notes & handoff

Product-hygiene observations (full crypto/fault/side-channel analysis is the `embedded-security-auditor`'s):

- **Unchecked returns on the crypto path.** `otbn_dmem_write()` / `otbn_dmem_read()` are `void` (`include/otbn_driver.h:31-35`) and their results are unobservable at `src/rsa_verify.c:150-158`; `oca_platform.c:79-83`'s `oca_result_t st` is passed to `oca_variant_for_body()` and then discarded, so a variant lookup failure returns `NULL` without recording why. `-Wunused-result` plus non-void returns would close both.
- **Two readers of `SBOOT_DIS` with different predicates** (DES-11) — a secure-boot-enabling decision that can disagree with the recorded measurement.
- **Trust anchors in writable RAM** (DES-05) and **unmeasured by the ROM self-hash** (DES-04).
- **A security gate whose documented properties do not hold in the default build** (DES-12).
- **Unvalidated SMC-supplied pointer used as a DMA source** (DES-14) with no stated trust boundary for the SMC on the recovery path.
- **Test private keys committed and pinned as ROM anchors**, with nothing in the build preventing a mask on them (DES-35).
- **PMP fences that do not bind M-mode** (DES-07).

Items warranting a full `embedded-security-auditor` pass, in priority order:

1. The KDF construction (`src/kdf.c`) — SP 800-108r1 counter-mode KBKDF with a zero entropy field, `doc/rom.adoc`-flagged as *provisional*, plus the fixed 32-byte header semantics.
2. `plat_decrypt_payload()` (`src/oca_platform.c:191-282`) — in-place decryption aliasing, the PKCS#7 strip's constant-time claim (`src/aes_driver.c:279-320`), and the padding-oracle argument that rests on ciphertext-hash-before-decrypt ordering in the library.
3. `plat_is_key_authorized()` (`src/oca_platform.c:363-501`) — the 128-bit select→slot resolution, the reserved/PQC refusal bands versus the `CHIPLET_PUBK_REVOKE` bit map, the all-zero-anchor rejection, and the constant-time digest compare as a single-fault target.
4. `rsa_3072_verify()` and `verify_pkcs1_v15()` (`src/rsa_verify.c`) — PKCS#1 v1.5 structural verification, the F4-only exponent constraint (`oca_platform.c:154-156`), and OTBN word-order handling.
5. Fault-injection coverage: `include/harden.h` is used in exactly two places (`boot_flash.h:184-187`, `sep_ot_spi.c:287-288`) and both are on the OT path only — the secure-boot decision at `oca_boot.c:294`, the demotion decision at `rom_main.c:423-465`, the fuse-lock confirmation at `rom_main.c:507-510` and the digest compare above are single-evaluation.
6. Entropy chain bring-up and the one-way locks (`src/sep_entropy.c`) — ESRC configuration, health-test window, EDN instantiate, `FIPS_LOCK`/`EXT_TRNG_SRC_SEL_LOCK` timing, and the external-TRNG stub seam.
7. Secret hygiene: `explicit_memzero()` (`include/sep_helpers.h:44-47`) is a plain byte loop with a trailing barrier; `kdf.c`'s `wipe()` uses `volatile` stores. The class key, derived key and HMAC key transit the stack, and `DCCM_SCRUB_BYTES` (`Makefile:50-52`) is the stated mitigation for spilled temporaries.
8. Warm-reset re-entry (`vector.S:182-263`): the handler slot is deliberately *not* poisoned on the warm path, and `BL1_SRAM_EXEC_ENABLE=1` accepts a handler in SRAM — a region left RWX and unscrubbed (DES-07, DES-16).
9. `plat_get_root_key_revocation()` / `plat_get_security_version()` (`src/oca_platform.c:614-656`) — only the low 32 of 128 revocation bits and the low 16 of 32 version bytes are fuse-backed; the rest read zero. Whether "not backed" is safely equivalent to "not revoked"/"no requirement" is a policy question for the auditor.

---

## 7. Positive findings — preserve these

- **`src/sep_entropy.c`** is the model the rest of the ROM should follow: every wait bounded (`SEP_ENTROPY_SEED_TIMEOUT`, `SEP_ENTROPY_CMD_TIMEOUT`), alert/error bits polled so a reported failure short-circuits a 2 M-iteration wait (`:157-163`), register values built from generated field macros with the reason spelled out (`:20-25` — `ESRC_CTRL.MODULE_ENABLE` resets to 1, so a hand-built literal silently disables the source), a distinct console marker per failure mode, `apply_lock()` read-back verification (`:129-138`), lock ordering tied to the point at which the source is proven live (`:214-231`), and a weak adopter seam that fails closed rather than reporting success on an unconfigured stream (`:330-336`).
- **`src/sep_ot_spi.c`** bounds every poll with `OT_SPI_POLL_MAX` and uses `harden_u32` on its destination-region lookup — the counterexample that makes DES-01 an inconsistency rather than a philosophy.
- **`src/vector.S`** — the MEM_REPAIR/MBIST gate moved into assembly ahead of the DCCM scrub for a stated and correct reason (a repair failure must not reach the lifecycle decision, and `LC_STATE_TEST_DEV` is `0x0`, the permissive answer); two bypass straps correctly kept separate because one stops the check running and the other only discards its verdict; the stack-free early trap vector for the window before `sp` exists; halt paths deliberately confined to SEP-internal `cold_scratch` so a bus error cannot turn a clean stop into an NMI loop; the warm-handler no-poison decision reasoned from what a repeating watchdog actually needs.
- **The layering choice at the heart of this PR.** Delegating structural parsing, integrity, usage constraints, anti-rollback and payload verification to the vendored library while the ROM keeps only storage transport, slot selection and reporting is the right boundary, and it is what makes `oca_boot.c` 480 lines where `manifest_load.c` was 809. Not calling `oca_commit_security_state()` and documenting why (`oca_boot.c:23-24`, `oca_platform.c:663-671`) is exactly the right call for a ROM with no OTP write path — and the designated-initialiser callback table so an upstream-added callback defaults to `NULL` rather than to the neighbouring field is a genuinely good fail-closed detail.
- **`doc/rom.adoc`** — 95 tagged requirements with a cross-referenced index, a specification-versus-implementation matrix that names its own gaps (PMP fence policy, payload gap zeroing, secure-boot escalation flag, fuse-sense readiness, demotion directive width, peripheral reset stub, placeholder key digests) rather than claiming completeness, and a layout-table re-verification against the submodule uprev that caught a real off-by-27 in the signed region. This is better than most silicon ROM documentation and is the single biggest reason the Blockers above are fixable rather than discoverable-in-the-field.
- **The DV suite's assertion discipline** — `sep_rom_oca_tamper_test` asserts the *specific* verdict (`OCA_FAIL_MANIFEST_HASH`) and explains why "some failure" would be a worthless assertion; it corrupts *both* slots because corrupting one would prove nothing; it forbids `MANIFEST_OK`/`PAYLOAD_OK` as well as requiring the error; and it records a measured cycle count as the justification for its run budget. Six distinct signing keys so per-slot resolution and per-slot revocation are actually distinguishable is the same instinct. This quality of test design deserves a CI gate to run it (DES-06).
- **Ordering rationale captured where it is load-bearing** — the `DEMOTE_1` write deferred past the fuse-secret lock so a fault while writing it cannot leave secret fuses readable (`rom_main.c:513-523`), the boot-state measurement enrolled after the demotion decision but before the locks per `SEP-ROM-ATT-030`, the `length`-before-`entry_point` check order at `rom_handoff.c:154-156`, and the `bl0_state`/linker-reserve runtime cross-check at `rom_main.c:661-671` that catches the drift the header's own `_Static_assert` cannot.
