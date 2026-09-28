# SEP Boot ROM — BETA-Calibrated Triage

Re-ranking of the findings in `SEP_ROM_SECURITY_AUDIT.md` (SEC-*) and
`SEP_ROM_DESIGN_REVIEW.md` (DES-*) against the actual near-term target.

| | |
|---|---|
| **Target** | BETA release to adopters and customers for hardware evaluation |
| **Bar** | The SEP ROM must work in practice and demonstrate secure boot with the new OCA manifest format |
| **Explicitly not in scope** | Hardening of the code or the build |
| **Key material** | The six in-repo ROM signing keys are demonstration material; a DEBUG/RELEASE split that rebuilds with public key material only, private halves held elsewhere, is planned |
| **Date** | 2026-09-16 |

Both source reports were commissioned and executed against a masked-ROM / PROD-silicon
bar. Their severities are therefore "severity if this were the mask candidate" and should
not be read as BETA blockers. This document is the list to work from.

The ranking below uses three BETA questions in place of severity:

1. **Does it boot?** — will an adopter's part come up, and stay up, on real silicon.
2. **Does the demonstration prove anything?** — can secure boot report success without
   having actually verified anything.
3. **Can an adopter diagnose a failure?** — when it does fail, is there enough evidence
   for them to file something actionable rather than returning the board.

---

## 1. Must-fix for BETA

Seven items. Each one is a functional defect or an evaluation blocker, not missing
hardening.

### 1.1 `SBOOT_DIS` is tested as a whole word — SEC-03 / DES-11

`src/oca_platform.c:605-610`. The RDL makes `SBOOT_DIS.rsvd[31:1]` `hw=rw` — driven from
the fuse array, not tied off — and the callback returns "secure boot disabled" for any
non-zero value in the whole 32-bit word. On real silicon with real fuses, any one of 31
hardware-driven bits reading 1 disables secure-boot enforcement, and an unsigned manifest
with the control bit clear then boots.

This is question 2 in its purest form: the ROM would report a successful boot, `rom_main.c`
masks the same register correctly so `bl0_state.sboot_dis` and the slot-1 boot-state
measurement both record *not disabled*, and the secure-boot demonstration would have
demonstrated nothing. Fix is masking to `SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm`
— one line, plus reading the fuse once in `rom_main` and passing the masked value down so
the two readers cannot diverge. Worth also treating a non-zero `rsvd` as a fuse-integrity
fault, since on a healthy part it must read zero.

### 1.2 The RSA verifier can silently no-op and report success — SEC-02, parts (a) and (b) only

`src/otbn_driver.c:118-134`, `src/rsa_verify.c:154,162-177`. The OTBN modexp uses one DMEM
buffer (`inout` at `0x600`) for both the signature input and the result, and
`otbn_execute()` never confirms the command was accepted — `otbn_wait_idle()` returns OK on
exactly the idle state OTBN is in if `CMD` never landed, and `ERR_BITS` reads 0 because
nothing ran. `verify_pkcs1_v15()` then examines the signature bytes that are still sitting
in the buffer.

**Strip the fault injection out of this finding and it is still a BETA problem.** Any
mundane reason OTBN fails to start — clock or reset sequencing, an unseeded entropy chain,
a wedged block during bring-up — produces `MANIFEST_OK` on an image whose signature was
never checked. That is a false pass in the one thing the BETA exists to demonstrate.

Take parts (a) and (b), which are cheap and are not hardening: write a sentinel over the
result region before executing so a no-op cannot look like a valid PKCS#1 block, and poll
for `STATUS != IDLE` (bounded) after writing `CMD` so a command that never landed is an
error rather than a pass. Part (c) — doubled, laundered evaluation of the verdict — is
hardening; defer it with the rest.

### 1.3 `sep_dma_zero()` destroys the manifest magic before BL1 sees it — DES-09 / SEC-10

`src/sep_dma.c:185-194`, `src/rom_handoff.c:201-224`. The DMA fill word is sourced from
`SEP_EXT_SRAM_BASE`, which is exactly where the manifest body is staged. The comment claims
the word is consumed before anything is staged there; true of the `[S16]` call site, false
of the ICCM ECC pad at `[S29]`, which is in the default build and runs long after staging.
So a normal successful boot zeroes `body[0..3]` — the OCA magic — and
`bl0_state.sep_sram_manifest_addr` hands BL1 a manifest that will not parse.

This lands squarely on adopter BL1 integration, which is the point of the release. Nothing
in the ROM re-reads the manifest after `[S27]`, so DV passes and the first person to hit it
is a customer writing their own BL1. Fix by sourcing the fill word from outside the staging
region.

### 1.4 Unbounded hardware waits, and how to make a hang attributable — DES-01 / SEC-15

`src/sep_dma.c:154-171`, `src/hmac_sha256.c:95-97,122-133,149-152`, plus the ratified spins
in `pll_init.c`, `status_ring.c`, `oca_boot.c` and `sep_smc_interface.h`. The ROM never arms
the watchdog by ratified policy, and `doc/rom.adoc:677-683` accepts a hang as the failure
mode "observable through the status channel" — but the secure-DMA completion poll and the
three HMAC FIFO-feed spins are outside that enumeration, so a hang there is both permanent
and unattributable. For hardware evaluation that is the worst available failure mode: a dead
part, a coarse stage marker in `cold_scratch[1]`, and no way to tell a slow manifest from a
stalled SPI read from a hung HMAC.

This is two separable changes, and they carry different arguments.

**(a) Bound the polls.** Emits nothing on any path; a wedged block becomes an error return
instead of a permanent hang. `src/sep_ot_spi.c` already bounds every poll with
`OT_SPI_POLL_MAX`, so the pattern exists in-tree — the DMA and HMAC drivers are inconsistent
with it rather than with a considered policy. No observability or side-channel cost. Do this.

**(b) Attribute the hang with timeout-only status.** Write nothing on the happy path; write
the distinguishing code *only* when a bound is exceeded.

This supersedes an earlier form of this item that called for a status write immediately
before entering each spin. That was wrong on two counts. It would hand a side-channel or FI
attacker a precise trigger adjacent to crypto activity — the objection SEC-20 raises against
the existing `DEBUG` markers, and it applies with equal force to anything new placed there.
And for the FIFO spins it would sit inside a loop whose author deliberately removed MMIO
traffic: the comment at `hmac_sha256.c:110-119` explains that one status read per word cost
~8k extra reads on the ROM self-hash, roughly half the bus traffic of the hash.

Timeout-only status has neither problem. A successful boot emits not one additional store,
so there is no added power signature and no trigger; the diagnostic appears only on a path
that has already failed and halts, and a halting path is a weak oracle in any case, since
averaged attacks need thousands of repeatable traces of a *completing* operation.

**What these waits actually carry**, since it bounds how much the trigger concern applies
here at all. `fifo_feed()` is CPU MMIO stores, not DMA, and the FIFO carries only the
message — the key is written to `KEY_0..KEY_7` in a separate loop at `hmac_sha256.c:236-246`
before the feed. `hmac_sha256()` has exactly one caller, `kdf.c:113`, so the single keyed
operation in the ROM keeps its secret in a different register file from the wait. Every
`sha256()` caller hashes public data: the ROM region, measurement records, the manifest
signed region, the public-key modulus, the self-test vector. The `sep_dma.c` wait is the
bulk copy path, where timing leaks length rather than content. PLL lock, status-ring init
and the SMC `MANIFEST_READY` spin are nowhere near a cryptographic operation.

**Either way, resolve the doc.** If status near crypto is deliberately kept minimal,
`doc/rom.adoc:681` should name which waits are genuinely observable instead of claiming the
property for all of them — otherwise the next person debugging a dead eval part relies on a
guarantee the code does not make.

### 1.5 The documentation an adopter is handed describes deleted code — DES-08 / SEC-26 / SEC-27

`README.md` points at `doc/index.adoc`, which says the implementation is
`src/manifest_load.c` and `src/manifest_crypto.c` — both deleted by this branch — and then
includes seven chapters (`boot-flow`, `spi-manifest`, `memory-security`, `bl1-handoff`,
`status-errors`, `smc-coordination`, `hardware-initialization`) that this branch does not
touch and that all describe the pre-OCA format. `README.md:24` tells the reader to init the
`tt-boot-manifest` submodule (now `tt-oca-manifest`), and its target and output tables list
`pack-images`, `secure_boot_spi`, `encrypted_boot_spi` and `smc_mem.hex`, none of which
exist in the current Makefile. `memory-security.adoc:48` states a 128-byte `bl0_state`
reserve where `link/rom.ld:71` says 256.

The new `doc/rom.adoc` is genuinely good and supersedes all of it, and is unreachable from
`README.md`. For a release whose entire purpose is evaluation by people who did not write
the code, the documentation *is* the deliverable — an adopter's first hour is
`make pack-images` (fails), then `spi-manifest.adoc` (wrong format), then looking for
`manifest_load.c` (absent). Make `doc/rom.adoc` the ROM document, delete or re-point the
superseded chapters, and rewrite the README's prerequisites, targets, outputs and
configuration tables against the current Makefile. Resolve the open reviewer request on
`hw/sys/sep/doc/index.adoc:28` in the same pass so the ROM doc has one home.

### 1.6 Invalid-lifecycle containment writes the wrong register with inverted polarity — SEC-25

`src/lifecycle.c:24-26,131-138`. Two independent defects, both verified against generated
collateral. The offset is `0x0020` where `smc_addr.h:2306` plus the SEP-view rebase gives
`0x39020`, so the ROM read-modify-writes `0x40000020` — an unidentified register in a
different SMC block. And `cpu_ctrl.rdl:24-44` defines `core0..3_reset_n_n0_scan` as active
low with reset value `0x1`, so `rst |= 0xFu` *releases* the cores; holding them requires
`rst &= ~0xFu`.

Pre-existing rather than introduced here, but this path is reachable during bring-up
whenever the lifecycle fuse is unprogrammed or misread — which is common on eval silicon —
and it issues a stray write into a neighbouring subsystem from the root of trust. Use the
generated symbol, clear rather than set, read back. Add a DV case asserting an invalid
`LC_STATE` leaves the SMC cores in reset; none exists, which is why a fully inverted action
went unnoticed.

### 1.7 Failures are unattributable, and the obvious fix will not compile — DES-13 / DES-17

`src/oca_boot.c:240-242,258-261,339-342`, `src/sep_dma.c:45-48,161-170`,
`include/status_values.h:110`, `src/rom_main.c:165-181,196-227,250`.

Three compounding problems on question 3. Every storage-read failure collapses to
`OCA_BOOT_ERR_DMA`, making `OCA_BOOT_ERR_READ_OUT_OF_BOUNDS` unreachable — so a wedged DMA
engine, a flash bus error and an out-of-slot payload offset all report `0x00030100`, three
different dispositions behind one code. `dma_transfer()` emits no `report_status()` at all,
so DMA failures contribute nothing to the status ring. And `bl0_state.error_code` carries
four unrelated numbering schemes plus two bare literals, so a small value cannot be placed
in a namespace.

Worst of it: `sep_dma.c:46-47` defines an enum member `SEP_MSG_DMA_ERROR = 0x00020002u`
while `status_values.h:110` defines the macro `SEP_MSG_DMA_ERROR 0x9d`, surviving only
because `sep_dma.c` does not include `errors.h`. The first person to add a `report_status()`
call to that file gets `0x9d = 0x00020002u` inside an enum and a build failure naming
neither cause. Rename the local enum out of the `SEP_MSG_*` namespace, propagate the read
error instead of overwriting it, give the DMA its own status codes, and put every code in
one registry with a mandatory subsystem tag.

---

## 2. Should-fix for BETA

Cheap, and each one protects the evaluation or the schedule.

| Item | Why it matters for BETA |
|---|---|
| **DES-02** — a real `BUILD_TYPE=release` | This is where the planned DEBUG/RELEASE split lands. Note the coupling now: 54 of 82 `rom_fw` test files assert on `simputs()` console text that a release build compiles out, so the suite cannot validate the release image. Move the pass/fail assertions onto the always-compiled `report_status()` stream in the same change, keeping console markers as diagnostic enrichment. |
| **DES-03 / SEC-21** — `-std=c11 -Wall -Wextra -Werror` | Not hardening; bug-finding. The build currently enables **no** warnings at all, and `Makefile:347-349` claims the vendored library is compiled under its own `-Werror`, which is vacuous with no `-W` flag in `CFLAGS`. Would already flag the unused-set `oca_result_t st` at `oca_boot.c:79` and the ignored OTBN return values. Cheapest gate available. |
| **Submodule pinning** — `.gitmodules` | `tools/tt-oca-manifest` specifies `branch = main` with globbed sources and no layout assertions, so two adopters cloning a week apart get two different validation libraries. For a release people clone, pin the commit or record it in the ROM docs. |
| **DES-15 / SEC-33** — use `OCA_OFF_DEMOTION_CONTROL` | Follows from the above. `oca_boot.c:87-95` hardcodes offsets 172/173 in a comment that names the macro the file already includes. If an uprev moves the field, `rom_oca_demotion_control()` reads two unrelated bytes and can take the one branch that leaves `DEMOTE_1` unlocked — the fail-open case the neighbouring comment exists to prevent. Add `_Static_assert`s on the layout constants so an uprev fails the build, not the boot. |
| **DES-10 / SEC-19** — round the BL1 length before the bounds check | `rom_handoff.c:137-142` validates the declared length and `:199` rounds it up before the copy. An adopter BL1 whose size lands 1-3 bytes short of the ICCM end validates, is authorised, and is then refused with a misleading `SEP_MSG_BL1_BAD_ADDR`. Adopters build their own BL1; this is their bug report, not yours. |
| **SEC-35** — confirm the TRNG mux before locking it | `sep_entropy.c:224-231` locks `EXT_TRNG_SRC_SEL` without checking that `sel[1]` still selects the external source, so a build whose override left it clear locks onto the unconfigured internal chain and reports success. Entropy bring-up is a new feature this release demonstrates. |
| **SEC-08 / DES-14** — bounds-check the SMC manifest offset | `oca_boot.c:415,445` takes a 32-bit offset from SMC scratch and adds it to the SRAM base unchecked; `manifest_src_read()` deliberately skips its gate for non-SPI sources on the stated but incorrect grounds that the library bounds it. SMC firmware will publish stale or garbage offsets during bring-up, and today it misreports as a DMA error. `rom_smc_coordination_probe()` already rejects `0xFFFFFFFF`; the consumer does not. |
| **DES-19** — one vconsole shadow, not one per translation unit | `rom_virt_console.h:35-43` puts `static uint32_t g_vconsole_prev_val` in a header, so the change-detect toggle is stale across TU boundaries and identical consecutive writes are dropped. Corrupts exactly the multi-module failover traces you triage from, and 54 DV tests assert on that text. |
| **DES-05 / SEC-12** — `const public_key_digests[]` | One keyword. Moves the trust-anchor pointer table out of writable DCCM (`nm` shows it at `0xc0040004` in `.data`) into ROM `.rodata`, and shrinks `.data` to 4 bytes. Update `tools/generate_key_digests.py:98` to emit it. |
| **SEC-07** — single-exit zeroization in `plat_decrypt_payload()` | `oca_platform.c:247-249` returns on `aes_init()` failure with the raw 32-byte `CLASS_KEY` still on the stack; every other exit wipes. Regression against the deleted `manifest_crypto.c`, which had one `cleanup:` label. Restoring it is a few lines. |
| **SEC-28** — `STATUS_ENCODE` | `(0x80 << 24)` is not representable in `int`, so the `STATUS_TYPE_DEBUG` encoding is UB under C11 6.5.7p4, and the parameters are unparenthesised so `STATUS_ENCODE(a|b, c)` misparses. Used pervasively, including hand-computed literals in `vector.S`. |
| **SEC-31** — `fuse_read_bytes()` length guard | Writes `out[i+1..i+3]` while stepping `i` by 4, so any `len` not a multiple of 4 overflows the caller's buffer. All five current call sites are fine; nothing enforces it. One-line guard. |
| **DES-06** — a compile-only CI gate | Today nothing in CI compiles or runs this ROM: `rom_fw` is excluded from `all`, `smoke_sep0` and `sep0_all`, and `rg 'rom_fw' .github/` is empty. A PR job that builds all three variants plus the library under `-Werror` and prints `size` needs the toolchain container and no simulator. Add a 3-4 test `rom_fw_smoke` to the nightly. This is what keeps the BETA working between now and release. |
| **DES-22** — delete `build2*/`, `build3/` | Eight tracked BL1 binaries added by this branch, referenced by nothing (the Makefile consumes `build/bl1_pass_test.bin`). Four checked-in BL1 images in a repo adopters will read. Widen `.gitignore` to `build*/`. |

---

## 3. Deferred — hardening, by plan

Out of scope for BETA per the stated target. Worth carrying as an explicit pre-tapeout
gate rather than an open finding list, since none of it can be added after mask.

| Item | Area |
|---|---|
| SEC-02(c), SEC-05 | Redundant/laundered verdicts; the `doc/rom.adoc:2540-2563` pre-handoff gate ledger. `harden.h` is currently included by one file and used only on the non-default OT path |
| SEC-06 / DES-07 | Smepmp: `PMP_LOCK=0` and `mseccfg` never written, so the fences do not bind M-mode; SRAM and ICCM are RWX through validation. Entry 6 also covers the wrong SMC window and the XIP aperture has no entry |
| SEC-04 | Secure-DMA `ENABLED_MEMORY_RANGE` opened to all 4 GiB; software range checks single-evaluation |
| SEC-09 | Cadence (default) `boot_flash_bounds_ok()` has no slot confinement and no doubling, contrary to its call-site comment; `oca_locate_payload()` gets the whole aperture as its region |
| SEC-13 | AES `KEY_SHARE1 = 0` defeats the Boolean masking the key registers exist for |
| SEC-14 | `bl0_state` security verdicts as plain `bool`/`uint32_t` with no integrity protection; `oca_secure_bool_t` narrowed at the seam |
| SEC-18 | No stack, GPR or staging scrub before the BL1 handoff |
| SEC-16 | `plat_is_secure_boot_active()` fails open on an invalid lifecycle read and does not cross-check `bl0_state.lc_state` |
| SEC-17 / DES-16 | `SRAM_SCRUB_BYTES ?= 0`; no clear on the terminal path. Note the inverted dependency — the default is off because one DV fixture preloads into the scrubbed region |
| SEC-11 / DES-04 | ROM self-measurement covers `.text` only, excluding the six root-key digests, the OTBN RSA program and the PKCS#1 constants |
| SEC-23 | Payload gap and tail zeroization dropped relative to the legacy ROM (declared in `doc/rom.adoc:3105-3107`) |
| SEC-24 | Warm-reset jump to an unauthenticated `cold_scratch[7]` with staging SRAM an accepted target. **Worth answering now even if the fix waits:** whether any non-SEP master can write that register is an open integration question, and the answer changes the design |
| SEC-22 | Anti-rollback narrowed from 256 to 128 fuse bits. A decision to record in `doc/rom.adoc`, not code |
| SEC-20 | `DEBUG` unconditional: publishes the security posture and gives a glitch attacker a per-verdict trigger oracle. Folds into DES-02 |
| DES-25, DES-26 | Stack watermarking (the canary sits 130 KB below the stack top and cannot trip); ROM size reporting and a headroom floor |
| SEC-29-30, 32, 34, 36-39 | Latent and hygiene: unusable `mmio_write64()`, four range-check conventions with three edge-case behaviours, HMAC key-length selection, entropy state caching, `signature->bytes` null check, measurement enrolling the parsed rather than computed hash |

---

## 4. The key material, and the one thing that affects how you build the split

SEC-01 / DES-35 is **already planned** and the planned approach — rebuild with public key
material only, private halves held outside the repository — is exactly what the audit
recommends. Three notes that are about *implementing* that, not about whether to:

- **The DV suite is keyed to the demo digests.** `sep_manifest_mutate.py:924-937` parses
  `key_digests.c` at runtime, and the `sep_efuse_lc_prod_chiplet_key*.toml` preloads set the
  chiplet fuse digest equal to `public_key_digests[0]`. Roughly twenty tests depend on these
  exact values, so flipping the release switch breaks the ROM regression unless DV gets its
  own digest set or build variant. Worth designing in now — otherwise there will be
  schedule pressure to defer precisely this step.
- **`key_digests.c` has to be generated, not committed**, for "public material only" to
  actually hold, with the release build failing hard (`#error`) when it finds the demo
  digests rather than warning.
- **The Makefile guard text is wrong today.** `Makefile:458-461,522-527` tells the reader a
  missing key "ships in the tt-oca-manifest submodule, so this normally means the submodule
  is stale" — the path is `$(CURDIR)/tests/signing_keys/`, in this repository. Fix it while
  you are there, and add a note beside the keys saying they are non-secret demonstration
  assets so a reader cannot mistake them for provisioning material.

---

## 5. Where "not hardened for BETA" does not quite reach

Stated once, because the distinction matters for the demo rather than for the security
posture: **SEC-03, SEC-02(a/b) and SEC-25 are functional defects, not absent hardening.**

Two of them can make a *passing* secure-boot demonstration meaningless — a verifier that
no-ops and reports success, and a fuse word where any of 31 hardware-driven bits disables
enforcement while the boot measurement attests that it did not. The third issues a stray
write into a neighbouring subsystem from the root of trust's tamper path, on a code path
that unprogrammed eval silicon reaches routinely. None requires a glitch, a side channel,
or a threat model. They are in section 1 for that reason, and they are cheap.

Everything in section 3 is genuinely deferrable on the stated schedule.
