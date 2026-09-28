# Scope: entropy chain bring-up in the SEP boot ROM

**Status: scoped and unblocked (2026-08-31).** Direction received: *bring up the **internal**
entropy source; leave a **stub** for the external source.* The external TRNG is third-party
commercial IP that cannot ship in this design, so the open tree gets the contract, not the
driver.

Arises from the OCA manifest integration (`OCA_MANIFEST_PLAN.md`, Phase 6b) but is separate
work: a boot-sequence change, not a manifest change.

## Why this moved from "latent" to "blocking"

When first scoped, the consequence was future-tense: the ROM would stall on silicon because
OTBN never leaves its reseed state and AES never reports `STATUS.IDLE`. Simulation stayed
green because `+sep_crypto_edn_force` grants the EDN handshakes directly.

That is no longer true. Upstream `f4ed43c4 [DV/SEP] Run the SEP assertions under VCS (#1308)`
enabled SVA under VCS, and the force **violates the EDN request/acknowledge protocol**:

```
prim_sync_reqack_data.sv:168/172
  SyncReqAckDataHoldDst2SrcA / SyncReqAckDataHoldDst2SrcB
    …u_otbn.u_prim_edn_urnd_req.u_prim_sync_reqack_data
    …tt_aes.u_prim_sync_reqack_data
```

Both `sep_rom_ot_secure_boot_test` and `sep_rom_oca_encrypted_boot_test` now report FAIL from
these assertions — the cocotb tests themselves pass, the ROM boots to `GO!`, but the shortcut
is caught lying about the handshake. The assertion predates and outlives the AES client: the
OTBN force has always violated it, and only became visible when assertions were switched on.

So this work now fixes a red DV suite, not just a future silicon stall. Doing it properly
removes the shortcut rather than waiving the assertion.

## The decision, concretely

`EXT_TRNG_SRC_SEL.sel[2:0]` (`sep_cpu_ctrl.rdl:323`) is **per-stream**, reset `0x7`:

| Bit | Stream | Reset | ROM action |
|---|---|---|---|
| 0 | Key Manager | external | leave — the ROM does not use the KM |
| 1 | **crypto blocks** (OTBN, AES) | external | **clear → internal DRBG** |
| 2 | entropy pool | external | leave — the ROM does not use it |

`0 = internal DRBG output, 1 = external TRNG (default)`. The ROM needs exactly bit 1. The
dead reference driver writes `0x0` (all three internal); that is broader than the ROM's own
need and would silently make a policy decision for stages that have not run yet.

**External source: stub only.** A named no-op with a documented contract, called where the
selection for an external source would be made. It must be obvious that the open tree
deliberately does not implement it, not that someone forgot.

## What the internal path requires

Nothing auto-initialises. Every stage is off at reset, so this cannot be hardware init:

| Stage | Reset state | Evidence |
|---|---|---|
| Entropy FIFO clock gate | gated off | `SEP_CLOCK_GATE_CTRL` reset `0x001F0021`, needs bit 10 |
| TRNG source select | `0x7` — all streams external | `EXT_TRNG_SRC_SEL.sel[2:0]` |
| ESRC ring oscillators | generators off | `SEP_ESRC_RING_OSC_ENABLE` |
| CSRNG `CTRL` | MuBi4False — disabled | `csrng_reg_top.sv:596` `RESVAL(4'h9)` |
| EDN `CTRL` | disabled | same MuBi4 convention |

`hw/ip/drbg/doc/architecture.adoc` confirms CSRNG "processes firmware-issued commands
(instantiate, reseed, generate, uninstantiate) through TL-UL" and EDN needs "mode
configuration" before it automates anything. Registers sit at CSRNG `0x1091_5000` /
EDN `0x1091_5800` behind a 64-bit AXI-Lite lane adapter — reachable from the SEP CPU.

**A proven sequence exists**, exercised from the testbench by `sep_drbg_real_sink_multi_km_aes_test`,
which passes today on real entropy and explicitly serves **AES's masking PRNG reseed off real
EDN**. Order (`sep_base_test.bring_up_entropy()`), and it is guarded in the reference suite:

1. configure ESRC with generators **off**, enable CSRNG, stage EDN commands
2. enable the ring-oscillator generators
3. wait for a seed to accumulate
4. enable EDN **last** ("configure EDN commands ONLY, do NOT enable EDN yet")

**An unproven C driver exists**: `hw/sys/sep/dv/fw/drivers/sep_entropy.h`, ~14 MMIO writes in
those three phases. Caveat: **it has no callers anywhere in the tree** — never executed.
Treat as a well-informed draft, not a known-good driver.

## The one genuinely unsolved piece

Step 3. The cocotb bring-up polls `drbg_seed_valid_o` — a **testbench probe, not a
software-visible register**. The ROM cannot poll it, and the dead driver ducked this with a
blind delay. Candidates, in preference order:

1. `ESRC.MAIN_SM_STATUS.BOOT_PHASE_DONE[12]` — asserts once the boot health-test window
   passes; documented as the gate before entropy reaches the whitener/FIFO
2. `ESRC.SHA256_STATUS.OUTPUT_COUNT[10:8]` — digest words available downstream
3. CSRNG / EDN status and `INTR_STATE`

**Settle this first — it is the only real unknown.** A blind delay is unacceptable in a boot
ROM: too short and crypto stalls anyway, too long and every boot pays.

## Where it goes

An idempotent `sep_entropy_init()` (once-only guard), called from **`otbn_init()` and
`aes_init()`**, not `rom_main()`:

- mirrors the existing structure — each block's `SW_RESET_N` release already lives in its own
  init, and `rsa_verify.c` already calls `otbn_init()` lazily
- entropy is only needed when crypto runs, and crypto only runs under secure boot; a
  non-secure boot should not pay seed-accumulation latency for something it never uses
- two call sites, one guard, no ordering constraint on the caller

## Cost

**ROM size: negligible.** ~15 MMIO writes plus a bounded poll ≈ 250–450 B against ~24 KiB
headroom.

**Boot time: real but acceptable.** Seed accumulation dominates; the cocotb wait budget is
60,000 cycles. Microseconds on silicon.

## DV changes

On the three crypto ROM tests (`sep_rom_ot_secure_boot_test`,
`sep_rom_oca_encrypted_boot_test`, `sep_rom_oca_otp_key_boot_test`):

- **remove** `+sep_crypto_edn_force` — it bypasses the chain *and* trips the protocol
  assertions
- **add** `+esrc_noise_force` — supplies only raw noise, needed because ESRC ring oscillators
  do not self-oscillate in simulation. The DRBG/CSRNG/EDN math above it is real, so the
  handshake is real and `SyncReqAckDataHold*` should hold.
- **revert** the AES EDN client force in `tb_top.sv` — unnecessary once the chain is real, and
  leaving it would keep masking the very thing this work fixes

Success criterion: those tests pass **with assertions enabled and no EDN force**.

## Open questions

1. **Should the ROM set `EXT_TRNG_SRC_SEL_LOCK`?** Write-one-to-set, frozen until reset. If
   the ROM selects the internal DRBG for the crypto stream and does not lock it, later
   software can move that stream to an external source after BL0's crypto is done. Security
   policy call — and it interacts with the deliberately-skipped `oca_commit_security_state()`.
2. **Health-test failure policy.** What should the ROM do on `INTR_STATUS.PERSISTENT_FAILURE`
   or a bring-up timeout — fail the boot, or continue and let signature verification fail on
   its own? A ROM that proceeds without entropy just stalls later with a worse error.
3. **`FIPS_LOCK.LOCK`.** Several ESRC fields (`BYPASS_COMPRESSOR`, SHA-256 whitening,
   `ALERT_THRESHOLD`) are documented as needing locking for certified operation. Is that a
   ROM responsibility? It is one-way.
4. **CSRNG `SW_APP` bit.** The dead driver's `0x9666` sets `SW_APP=True`. The ROM needs no
   software application reads (it consumes entropy through the hardware EDN path), and the bit
   is separately gated by `otp_en_csrng_sw_app_read_i` / lifecycle. Default to **not** setting
   it unless there is a reason.

## Risks

- **The seed-ready proxy is unvalidated from software.** Everything else is a transcription of
  a working sequence; this step has no firmware precedent.
- **It puts analog behaviour in the critical boot path.** Ring-oscillator bring-up failure
  becomes boot failure. Needs a bounded timeout and its own `SEP_MSG_*` status code so the
  failure is attributable rather than surfacing as a downstream crypto timeout — the lesson
  from `AES_IDLE_TIMEOUT=<status>` in Phase 6b.
- **`sep_entropy.h` has never run.**
- **`+esrc_noise_force` is still a shortcut**, just a far weaker one. It should be tagged and
  stated as such, not quietly treated as full coverage.

## Phasing

**Phase A — spike (the only real unknown).** Port the sequence behind a build flag, determine
the seed-ready proxy empirically against `sep_rom_ot_secure_boot_test` with `+esrc_noise_force`
and no EDN force. Success: RSA verifies off real entropy **with assertions clean**. Mostly sim
turnaround; ~1 day.

**Phase B — productionise.** Idempotent guard, the external-source stub with its contract,
bounded timeouts, a status code and console marker per failure mode, error policy per Q2.
~half day.

**Phase C — flip DV and reconcile docs.** Update the three testlist entries, revert the AES
EDN force, re-run the ROM tests and the VP suite, and fold the outcome into `rom.adoc` — the
`Entropy chain bring-up` matrix row and the `bl0-open-items` entry both close. ~half day plus
sim time.

---

## Phase A result (2026-09-01): unknown resolved, new blocker found

**The seed-ready question is answered, and not by my candidate.** The rebase brought in
`doc/programmer` "OCAH TRNG Bring-Up", which states it outright:

> The EDN Instantiate acknowledgement is the software-visible readiness event: CSRNG cannot
> acknowledge that command until it has accepted a complete ESRC seed. Firmware therefore does
> not need a delay or a hierarchical `drbg_seed_valid` probe. `BOOT_PHASE_DONE` remains useful
> for separating an ESRC startup-health failure from a downstream CSRNG or EDN failure.

So the sequence is: poll `BOOT_PHASE_DONE` (fault localisation), enable EDN, wait
`SW_CMD_STS.CMD_RDY && CMD_REG_RDY`, write Instantiate to `SW_CMD_REQ`, poll `CMD_ACK`, and
require `CMD_STS` to report success. Both polls bounded.

### Scope correction from the same document

The internal source is **not the production path**:

> The OCAH internal entropy source has not been certified. Consequently, `EXT_TRNG_SRC_SEL`
> resets to `0x7` ... **Production firmware should retain that default** and use an
> appropriately qualified external source unless the product security authority explicitly
> approves the OCAH internal path.

That reframes this work: the internal chain is a bring-up/test path, and the external stub is
the production shape. It also answers three of the four open questions — lock the selection
after verifying the source is operational; leave CSRNG `SW_APP_ENABLE` / `READ_INT_STATE` /
`FIPS_FORCE_ENABLE` false; apply `FIPS_LOCK` only if policy requires.

### Three bugs the document caught in the first draft

Written from the dead `sep_entropy.h` and the DV sequence, all three would have failed silently:

1. **TRNG reset must be a pulse, not a release.** Clear *then* set `trng_sw_rst_n`, RMW to
   preserve other bits. A release alone is a no-op when the chain is already out of reset.
2. **`EDN.CTRL.BOOT_REQ_MODE` must be FALSE.** The DV constant `0x9666` sets boot-request
   *and* auto-request true; the document warns boot-request takes precedence and stays in its
   completed state, so that combination never reaches continuous operation.
3. **`CSRNG.CTRL` diagnostic bits must stay false.** `0x9666` enables `SW_APP_ENABLE` and
   `READ_INT_STATE`, which the ROM does not need.

Also confirmed: `ESRC.CTRL[0]` is reserved and is **not** a reset control (the dead driver
used it as one), and firmware must not write the undocumented `CLOCK_GATE_CTRL` bit 10 —
that register is a placeholder here with no entropy gate field.

### Implementation

`src/sep_entropy.c` + `include/sep_entropy.h`, behind `SEP_ENTROPY_BRINGUP` (**default 0**).
Called from `otbn_init()` and `aes_init()` via a once-only guard. Values are built from
generated field macros, never literals — `ESRC_CTRL.MODULE_ENABLE` resets to 1 and a
hand-built literal silently clears it, disabling the whole source.
`sep_entropy_select_external_source()` is the documented stub. ROM 40936 → **42024 B**.

### The blocker: the DV tests have no noise source

The ROM ran the sequence and reported `ESRC_HEALTH_FAIL=0x000005fb` — `ALERT` set (bit 10),
`ERR` clear, `STATE=0x1FB`, no `BOOT_PHASE_DONE`. **That is correct behaviour**, not a ROM bug:

- `tb_top.sv`: `+esrc_noise_force` forces the decorrelator inputs from `esrc_noise_ext_i` —
  an external port, not a generator.
- `sep_base_test.py:133` sets `esrc_noise_ext_i = 0` and leaves it there.
- Only `SepDrbgScoreboard` (`sep_drbg_scoreboard.py:439`) drives varying noise, and **neither
  ROM boot test instantiates it**.

So the forced noise is constant zero, the repetition health test trips immediately, and the
ROM correctly refuses to proceed on a failed entropy source.

**`+esrc_noise_force` alone is therefore not sufficient** — a correction to this plan's DV
section, which assumed it was. Phase C must give the crypto ROM tests a noise driver (the DRBG
scoreboard, or a minimal generator extracted from it) alongside the plusarg.

### State

Spike-only changes reverted: flag default back to 0, `rom_fw.toml` back to
`+sep_crypto_edn_force`. The driver stays in-tree behind the flag, so the tree builds and DV
behaves exactly as before. Phase B (productionise) and Phase C (DV flip + noise driver) remain.

---

## Correction: which path this harness is for (2026-09-01)

An earlier note in this plan read "the internal chain is a bring-up/test path; the external
stub is the production shape." **That is wrong and is corrected here.**

**This harness is the test vehicle for the OCAH internal TRNG.** Bringing up the internal
chain is the deliverable, not a secondary path. The programmer guide's "production firmware
should retain that default [external]" is guidance to an **adopter** taping this design out,
for *their* production firmware — it is not a reason to de-emphasise internal bring-up here.

What that means for the stub: its job is a **seam**, sized so an adopter can switch RNG source
*without rewriting a large part of the ROM*. A hardcoded `return -1` is not a seam.

### The seam, built on the idiom already in this tree

`src/sep_spi.c` establishes the pattern: `__attribute__((weak))` stubs that a companion build
overrides at link time via the Makefile's `NONFREE_BOOTCODE_SOURCES` hook. The entropy seam
now follows it exactly — two weak functions:

| Hook | This tree | An adopter overrides to |
|---|---|---|
| `sep_entropy_use_internal_source()` | returns `true` | return `false` |
| `sep_entropy_bringup_external()` | fails with `ENTROPY_EXT_STUB` | bring up and validate their TRNG |

`sep_entropy_init()` dispatches on the first. On the external path the ROM programs *nothing*
in the internal chain and leaves `EXT_TRNG_SRC_SEL` at its reset value, so the crypto-block
stream keeps taking the external source and the adopter's driver owns everything downstream.

Overriding those two functions is the whole switch: no change to `otbn_init()`, `aes_init()`,
the boot flow, or the testlists. The header states the override's contract — leave `sel[1]`
set, initialise through the device's own interface, and return 0 only once it is actually
producing entropy, because a false success stalls the crypto blocks exactly as an
unconfigured chain would.

### A bug this shook out

`SEP_ENTROPY_BRINGUP` was added to the compile line but **not** to `BUILD_FLAGS`, which feeds
`$(FLAGS_STAMP)` and drives `$(OBJS)` rebuild-on-flag-change. Flipping the flag therefore
silently reused stale objects — both settings produced a byte-identical 42136 B ROM, which is
what exposed it. This is the exact hazard this repo's own Makefile notes warn about. Fixed by
adding `ENTROPY=$(SEP_ENTROPY_BRINGUP)` to `BUILD_FLAGS`; the flag now demonstrably changes
the build:

| Build | ROM text |
|---|---|
| `SEP_ENTROPY_BRINGUP=1` | 42136 B |
| default (`=0`) | 40984 B |
| pre-entropy baseline | 40936 B |

Flag-off costs **+48 B** over the baseline, not zero: the two weak stubs and their string
survive `--gc-sections` even with no caller. Cheap, and worth stating rather than rounding to
nothing.

---

## Decision: a failed entropy bring-up STOPS secure boot (2026-09-01)

Answers open question 2. Implemented, not just recorded.

### Why the previous behaviour was not this

Before the decision the ROM *did* fail — but indirectly and for the wrong reason.
`sep_entropy_init()` returned -1, `otbn_init()` turned that into `OTBN_ERR_NOT_IDLE`,
`rsa_verify.c` reported `RSA_OTBN_INIT_FAIL`, and the manifest slot failed. Three problems:

1. **Wrong cause reported.** The mailbox saw a signature/crypto failure. The image was fine;
   the device's entropy source was not.
2. **Pointless retry.** A slot failure rotates to the backup manifest — which carries the same
   crypto requirement, so it cannot possibly help. The ROM would run the whole flow twice
   before giving up.
3. **Policy in two places.** Each crypto init decided independently what an entropy failure
   meant, so they could drift.

### What it does now

`sep_entropy_init()` owns the policy, once: on any failure path it reports
`SEP_MSG_ENTROPY_INIT_FAILED` and calls `rom_err_fail_ext()`, which is `noreturn`. The boot
stops there. Same idiom `lifecycle.c` already uses for an invalid life-cycle state — the
closest existing analogue, also a device condition no retry can fix.

Consequences, all deliberate:

- Callers need no return check, and theirs were removed rather than left as unreachable code.
- Only success is cacheable in the idempotency guard; there is no failed state for a later
  call to observe.
- Both source paths are terminal, including the external seam: a build that selects the
  external source without providing a driver stops with an attributable code rather than
  handing the crypto blocks a dead stream.

Two status codes added: `SEP_MSG_ENTROPY_INIT_START 0x225` and
`SEP_MSG_ENTROPY_INIT_FAILED 0x226`. The per-stage console markers
(`ESRC_HEALTH_FAIL=`, `ESRC_BOOT_PHASE_TIMEOUT=`, `EDN_CMD_NOT_READY=`,
`EDN_INSTANTIATE_TIMEOUT=`, `EDN_INSTANTIATE_ERR=`) each carry the register value, so the
status code says *entropy failed* and the marker says *which stage and why*.

ROM: **42096 B** with the flag on, **40984 B** default.

### A latent build bug this surfaced

Adding status codes exposed that `virtual_platform/Makefile`'s `VP_CONFIG_SIG` tracked
`$(STATUS_VALUES_PATH)` — the path string — not the file's contents. The path never changes,
so a new `SEP_MSG_*` left the configure-baked VP decoder stale and the code decoded as
`SEP_MSG_UNKNOWN`. The signature's own comment claims it covers "the configure-baked status
table change", so this was a bug against its stated intent, not a missing feature.

Fixed by fingerprinting the contents: `STATUS_VALUES_SIG := $(shell cksum ... )` appended to
the signature, which now reads `...status_values.h@3564028378`. A code addition triggers a
reconfigure from here on.

This is the hazard recorded in `OCA_MANIFEST_PLAN.md` Phase 6b ("adding a new `SEP_MSG_*` does
not trigger a VP reconfigure") — now closed rather than documented.

---

## Layering fix: entropy is a prerequisite OF the engines, not a step INSIDE them (2026-09-01)

The first implementation called `sep_entropy_init()` from inside `otbn_init()` and
`aes_init()`. Within each function the ordering was already correct — entropy first, then the
reset release — but the *structure* was wrong in two ways:

1. **Dependency inversion.** `otbn_driver.c` and `aes_driver.c` are hardware drivers; having
   them reach into the entropy subsystem to satisfy their own precondition inverts the
   layering. A driver should drive its block.
2. **A shared prerequisite duplicated across its consumers.** Two engines each established the
   same dependency independently, so the ordering had to be got right twice and would have to
   be got right again for any third consumer. Engine init does not need entropy at every step
   today, but the dependency belongs to the engines and therefore belongs *ahead* of them —
   not rediscovered inside each one.

### What changed

Entropy is now established at the two crypto gates in `oca_platform.c`, before any engine is
touched:

| Gate | Sequence now |
|---|---|
| `plat_verify_signature()` | structural checks → digest → **entropy** → `rsa_3072_verify()` → `otbn_init()` |
| `plat_decrypt_payload()` | resolve secret → **entropy** → `aes_init()` → KDF → cipher |

Both drivers are back to zero references to the entropy subsystem; each carries a comment
saying entropy is its precondition and naming who establishes it.

The call is wrapped as `ENTROPY_PREREQ()` so the `SEP_ENTROPY_BRINGUP` conditional lives in one
place and both gates read identically whether the flag is on or off.

### One deliberate placement choice

The prerequisite sits *after* the cheap structural rejections in `plat_verify_signature()`
(unsupported algorithm, wrong encoding, short field, wrong exponent), not at the top of the
callback. A manifest refused on structure alone never needed entropy, and bringing up analog
ring-oscillator hardware to then reject the image on a field width is waste. The requirement
is "before the engines", which this satisfies.

ROM: **42104 B** flag-on, **40984 B** default — the default is byte-identical to before this
change, confirming the drivers really are back to pure.

### Refinement: confirmed on entry, and only where entropy is actually used

Two adjustments on top of the layering fix:

**Confirmed on callback entry, not after the structural checks.** The earlier placement gated
entropy behind the cheap manifest rejections in `plat_verify_signature()` to avoid bringing up
analog hardware for an image about to be refused on a field width. That optimisation is not
worth the property it costs: with the confirm on entry, *no path* through the callback can
reach an engine without a live chain, and there is no ordering to re-check when the checks
above it change. Both gates now confirm immediately after argument validation.

**Only the callbacks that actually use entropy.** `plat_sha256()` deliberately does not confirm
it. The HMAC core needs no EDN reseed — established empirically, not assumed: when the
encrypted-payload path ran in simulation with the EDN force absent, the KDF completed on the
HMAC core and only AES hung. Two reasons this matters beyond tidiness:

- `plat_sha256()` runs on **every** boot, since the manifest hash is checked whether or not
  secure boot is in force. Confirming entropy there would make an *unsigned* boot depend on
  the entropy source, and with bring-up failure terminal, a part with a dead entropy source
  would stop on a boot that needs no crypto at all.
- It would also widen Phase C: the DV noise driver would be needed by every ROM test rather
  than the three crypto ones.

So the rule is "confirm entropy where an entropy-dependent engine is driven", which is OTBN
(`plat_verify_signature`) and AES (`plat_decrypt_payload`) — not "on every crypto callback".
The comment at the first gate states the exclusion and why, so the asymmetry is not read as an
oversight later.

ROM: **42112 B** flag-on, **40984 B** default.

---

## Decision: lock both, with independent compile-time deferral (2026-09-01)

Answers the last two open questions. Both locks are **applied by default**; each can be
deferred to SEP BL1 independently.

| Flag (default) | Set to 1 to leave for BL1 |
|---|---|
| `SEP_ENTROPY_DEFER_FIPS_LOCK ?= 0` | `ESRC.FIPS_LOCK` — BL1 can still change conditioning, health-test thresholds, compressor bypass |
| `SEP_ENTROPY_DEFER_SRC_SEL_LOCK ?= 0` | `EXT_TRNG_SRC_SEL_LOCK` — BL1 can still repoint an entropy stream |

Separate knobs because they freeze unrelated things: one the entropy-source *configuration*,
the other the source *mux*. An adopter may well want one and not the other.

Deferring does not mean "never lock" — it means BL1 owns applying it. A build that defers and
whose BL1 never locks ships with the field mutable. The Makefile comment says so, because the
flag name alone reads as permission rather than a transfer of responsibility.

### Placement follows the guide, and the two are not the same point

The programmer guide puts them at different stages, and the reasons are real:

- **`FIPS_LOCK` — after the startup health test passes, before any entropy is exposed.**
  Earlier would freeze a configuration that had not yet proved itself; later would hand
  entropy to a consumer from a still-mutable source. `DEBUG_CTRL` stays outside this lock by
  design.
- **`EXT_TRNG_SRC_SEL_LOCK` — last, once the source is proven operational.** For the internal
  chain that proof is the EDN Instantiate acknowledgement; for the external path it is the
  adopter's driver returning success. Locking a selection whose source had not been proven
  would freeze the device onto a dead stream.

Consequently `lock_source_selection()` runs on **both** source paths — it locks the mux, not
the ESRC configuration, so it is meaningful whichever source was chosen. `FIPS_LOCK` is
internal-path only.

### Locks are verified, not assumed

Both are write-one-to-set and frozen until reset, so `apply_lock()` reads back and fails
terminally (`*_LOCK_FAIL` marker) if the bit did not stick. A lock that silently failed is
worse than no lock: the ROM would believe it had frozen a security-relevant field that later
software can still change, and nothing would ever notice.

### Verified

All four combinations build to distinct sizes, so each flag independently reaches the objects
(both deferred is slightly more than the sum of the two savings because the shared
`apply_lock()` helper then drops entirely):

| `DEFER_FIPS` / `DEFER_SRCSEL` | ROM |
|---|---|
| 0 / 0 (both locked — default) | 42328 B |
| 1 / 0 | 42248 B |
| 0 / 1 | 42200 B |
| 1 / 1 | 42112 B |

Default build (`SEP_ENTROPY_BRINGUP=0`) is **40984 B — byte-identical** to before this change.
Both flags are in `BUILD_FLAGS`, so flipping either forces a rebuild rather than silently
reusing stale objects.

**Phase B is complete.** Only Phase C remains: the DV flip plus the noise driver the ROM tests
need.

---

## Phase C — DV flipped to real entropy (2026-09-01)

**`sep_rom_ot_secure_boot_test` PASSES on the real entropy chain with assertions live and no
EDN force.** That is the result this whole effort was for: the test was red before, failing on
`SyncReqAckDataHold*`, and it now shows **0 assertion hits**.

Boot sequence observed: `PUBK_AUTHORIZED` → `ENTROPY_OK` → `RSA_EXEC` → `RSA_VERIFY_OK` →
`MANIFEST_OK` → `PAYLOAD_OK` → `GO!`. `ENTROPY_OK` only prints after the EDN Instantiate is
acknowledged *and* both one-way locks read back set, so a single marker covers the whole chain.

### The missing piece was a noise driver, not a plusarg

`+esrc_noise_force` (tb_top.sv) *forces* each decorrelator's `noise_i` from the
`esrc_noise_ext_i` **input port** -- it generates nothing. `sep_base_test` pins that port to 0,
so the plusarg alone supplies constant zero: the repetition health test trips, `ALERT` latches,
and `BOOT_PHASE_DONE` never asserts. The ROM then correctly refuses to boot on a dead source.
Only `SepDrbgScoreboard` drove the port, and no ROM test instantiates it (it also brings a
bit-exact golden chain a ROM boot cannot predict).

New `env/sep_esrc_noise.py` is the piece those tests needed: the same `SepNoiseGolden`
generator driven into the port, no golden, no checking. Started from
`sep_rom_ot_dma_boot_test.run_scenario()` so every SPI ROM test gets it.

**Update rate is the one knob worth getting right.** The decorrelator samples on its divided
sample clock, and the ROM programs `SAMPLE_CLK_DIV` to /64, so the port only has to change
faster than that. Driving every cycle would be ~64x the Python callbacks across a
multi-million-cycle boot for no benefit; the driver updates every 8 cycles, comfortably under
the sample period.

### What changed

| Change | Detail |
|---|---|
| 3 crypto tests | `+sep_crypto_edn_force` → `+esrc_noise_force` |
| ROM builds | all 6 DV `make` invocations pass `SEP_ENTROPY_BRINGUP=1` |
| `tb_top.sv` | AES EDN client force removed |
| Testlist comments | rewritten -- they said entropy was *not* exercised, which is now backwards |

`dv_shortcut` tags stay: `+esrc_noise_force` is still a shortcut, just a far weaker and honest
one -- raw noise injected because the ring oscillators do not self-oscillate in simulation,
with the DRBG/CSRNG/EDN handshakes left real.

### `+sep_crypto_edn_force` is now dead

No test in any testlist passes it. Its comment now says so and marks it a debug lever only,
with deletion a candidate once the real path has mileage. Deliberately not deleted in the same
change that replaces it -- keeping the fallback until the replacement has run everywhere is
worth more than the tidiness.

Its `FIXME(SEP-DV)` -- "who is meant to bring up DRBG/EDN before the ROM runs RSA" -- is
answered: **BL0 does**, and now demonstrably.

### Full DV sweep: 7/7 PASS on real entropy

| Test | Result |
|---|---|
| `sep_rom_ot_secure_boot_test` | PASS — **was red** on `SyncReqAckDataHold*` |
| `sep_rom_oca_encrypted_boot_test` | PASS — **was red**; AES masking PRNG now reseeds off real EDN |
| `sep_rom_oca_otp_key_boot_test` | PASS |
| `sep_rom_oca_tamper_test` | PASS |
| `sep_rom_non_secure_boot_test` | PASS |
| `sep_rom_ot_dma_boot_test` | PASS |
| `sep_rom_ot_pio_boot_test` | PASS |

Zero `SyncReqAckDataHold*` hits anywhere. The two tests that were failing are green for the
right reason -- the handshake is real, not waived.

The four non-crypto tests are the regression evidence: they build the same
`SEP_ENTROPY_BRINGUP=1` ROM and run the noise driver, and none of them reaches a crypto
callback, so they confirm the bring-up costs an unsigned or refused boot nothing.

**Phases A, B and C are complete.** The entropy chain is brought up by the ROM, verified in
RTL, and the DV shortcut it replaces is unused.

### Follow-ups (not blocking)

* **Delete `+sep_crypto_edn_force`** and its `FIXME(SEP-DV)` from `tb_top.sv` once the real
  path has mileage. Left in deliberately this cycle -- the fallback outlives the change that
  replaces it by one cycle.
* **Flip `SEP_ENTROPY_BRINGUP ?= 1`** as the Makefile default. It is currently 0 with DV
  passing `=1` explicitly, so a plain `make` still builds the pre-entropy ROM. Flipping it
  makes the ROM's real behaviour the default and the shortcut the opt-out.
* **`rom.adoc`**: the `Entropy chain bring-up` matrix row and the `bl0-open-items` entry can
  both close, and the boot-sequence section should gain the bring-up step.

---

## VP model work for the default flip (2026-09-01) — all 4 gaps closed, flip LANDED

Flipping `SEP_ENTROPY_BRINGUP ?= 1` also changes what the **VP** builds, and the VP model was
missing pieces of the entropy chain. Attempting the flip found four gaps; three are fixed and
one remains, so **the default is reverted to 0 for now** and the tree is green.

Each was found the same way: flip, run, read the ROM's own diagnostic, fix, repeat. The
per-stage markers added in Phase B earned their keep here -- each failure named its stage
directly instead of presenting as one undifferentiated hang.

### Fixed

1. **`MAIN_SM_STATUS` was not modelled at all** (`entropy_src`). `BOOT_PHASE_DONE` never
   asserted, so the ROM spun its 2M-iteration poll and stopped secure boot. Added the register
   at 0xB4 with the RDL's field layout, plus a write handler on `RING_OSC_ENABLE` that asserts
   `BOOT_PHASE_DONE` once the generators are enabled. It models the *handshake firmware
   observes*, not the analog startup -- stated in the comment so nobody mistakes it for a
   health-test model.
2. **`FIPS_LOCK` was not modelled** (`entropy_src`). The ROM's lock read-back correctly caught
   that the lock did not stick and failed the boot -- the verification doing its job. Added at
   0x154 as a real W1S bit.
3. **`EDN.SW_CMD_STS.CMD_RDY` was lying** (`edn`). It reported ready whenever no command was
   processing, ignoring the state machine -- but `handle_write_SW_CMD_REQ` *rejects* writes
   unless the FSM is in `SWPortMode` or `AutoFirstAckWait`. Firmware following the documented
   contract (poll `CMD_RDY`, then write) therefore had its Instantiate silently dropped while
   the FSM was still in `AutoLoadIns`, then waited forever for an ack that could never come.
   `CMD_RDY` now agrees with what the write handler will actually accept.

   This one is a model bug in its own right, independent of the ROM: any firmware using the
   documented sequence would hit it.

### Remaining

4. **The EDN Instantiate is never acknowledged.** With (3) fixed the FSM does reach a state
   that accepts the write (`SW_CMD_STS` reads `0x1` for the first few polls, then `0x3`), but
   `CMD_ACK` never sets -- every subsequent read returns `0x3`, never `0x7`. `process_sw_command_async()`
   does set `CMD_ACK`, so the completion path exists and is not being reached. Next step is the
   command-buffering path in `handle_write_SW_CMD_REQ` (`m_expected_sw_cmd_words` vs the
   single-word `clen=0` Instantiate) and its hand-off to the CSRNG model. That handler logs
   nothing, which is why this one needs instrumentation rather than log reading.

### State

Model tests pass with the changes: **entropy_src 132/0**, **edn all passed**. The three fixes
are strict improvements and stand on their own regardless of when the flip lands -- two add
registers that did not exist, one makes a status bit tell the truth.

`SEP_ENTROPY_BRINGUP` stays `?= 0`; DV continues to pass `=1` explicitly and is unaffected,
since DV runs real RTL where all four of these are non-issues.

### Gap 4 closed: the EDN model mis-parsed the command header

`handle_write_SW_CMD_REQ` extracted `clen` from bits **[11:8]**. The CSRNG
application-command header is:

```
{8'h0, glen[23:12], flag0[11:8], clen[7:4], acmd[3:0]}
```

so [11:8] is **flag0**, not `clen`. And `flag0 = 0x9` is the documented "use real entropy"
value, so a textbook Instantiate (`0x901`) was parsed as `clen = 9`, i.e. a **10-word**
command. The ROM writes one word, the buffer never reached 10,
`process_sw_command_async()` was never called, and `CMD_ACK` never asserted — firmware waited
forever for an acknowledgement the model could not produce.

Only commands with `flag0 = 0` parsed correctly, which is why it survived: the bug is
invisible until flag0 is non-zero, and "use real entropy" is exactly when it becomes non-zero.

Fixed to `(value >> 4) & 0xF`.

### Result

`SEP_ENTROPY_BRINGUP ?= 1` is now the default. A plain `make` builds the ROM that brings up
its own entropy chain, and the shortcut is the opt-out rather than the norm.

| Suite | Result |
|---|---|
| VP | **86 passed**, `ENTROPY_OK` observed on the signed boot |
| VP crypto subset | 4/4 in 14.8 s (was: 3 timeouts) |
| `entropy_src` model tests | 132 passed, 0 failed |
| `edn` model tests | 29 passed, 0 failed |
| DV ROM tests | 7/7 on real entropy (unchanged; DV already passed `=1`) |

### Aside: the EDN test harness's summary line is vacuous

`run_all_tests` reports the real numbers (`Total 29 / Passed 29 / Failed 0`), but the
`report_results` block underneath prints from a *different* counter that nothing increments —
`Tests Run: 0 ... ALL TESTS PASSED`. It would print that even if every test failed, and it is
the last line on screen, so it is the one a human or CI is most likely to read. Pre-existing,
unrelated to this work, and worth fixing before anyone trusts it.

### Four model fixes, all upstreamable independently

1. `entropy_src`: add `MAIN_SM_STATUS` (0xB4) + `BOOT_PHASE_DONE` gating
2. `entropy_src`: add `FIPS_LOCK` (0x154) as a real W1S bit
3. `edn`: make `CMD_RDY` agree with what `handle_write_SW_CMD_REQ` accepts
4. `edn`: parse `clen` from [7:4], not [11:8]

(3) and (4) are model bugs any firmware following the documented CSRNG/EDN sequence would hit,
independent of this ROM. (1) and (2) are missing registers. None depends on the others except
that (4) is only reachable once (3) is fixed.
