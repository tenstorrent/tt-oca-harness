<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS VPLAN — Phase 3 (deferred advanced / security / integration)

> **Phase 3 — CANDIDATES ONLY (planning, not scheduled).** Phase 1 (smoke + TOP-20,
> `SEP_OSS_VPLAN_PHASE1.md`) is closed and Phase 2 (basic-feature breadth,
> `SEP_OSS_VPLAN_PHASE2.md`) is active. Phase 3 collects the work both earlier phases
> explicitly *deferred* — advanced corner cases, error/security permutations, and
> the deeper cross-IP integration edges that are not "basic feature." Nothing here is
> implemented; each candidate needs a full No-Coding-Gate detail card (owner, toml,
> OCAH-REFS, mapping outcome, checker boxes, run/fuse mode, DV-infra, deltas) before
> coding, per `VPLAN_CREATION_RULES.md`. The creation/compression rules are unchanged.

## Qualification test for Phase 3

A candidate belongs in Phase 3 (not Phase 2) when it is **not basic-feature** — i.e.
it is one of: an advanced corner case, an error/security permutation, a negative-path
matrix, or a cross-IP integration edge whose *basic* behavior is already
`COVERED_BY`/`COVERED_STRONGER` elsewhere so only the advanced/integration slice is new.
It still must trace to ≥1 real OCAH test (Provenance Gate) and be frontdoor-stimulable
on the bare `sep` build (or record the DV-infra gate).

## Candidates (from the 2026-07-15 OCAH main-sync audit)

Both arrived from OCAH SEP updates that landed after the OSS env last synced. Neither is
a basic-feature GAP, so both are Phase-3 (deferred), not Phase-2. No GitHub issues exist
yet — leave `GITHUB: TBD (owner to file)` until real issues are created (do not invent
numbers).

### P3-1 — `sep_km_sw_emergency_wipe_test` (TBD)  [KM & key distribution]

- **OCAH provenance:** KM RTL feature #3719 "[SEP][KM] Add software-controlled emergency
  wipe" (`f0d13cb30`), covered force-free in OCAH by `sep_km_uvm_wipe_state_test_seq`
  (frontdoor RAL write to `sep_cpu_ctrl.KM_WIPE_CTRL.wipe_state`, PR #3722 `1af0f0327`).
- **What is new:** a genuinely new SEP→KM integration edge. `sep_system_csr` drives
  `KM_WIPE_CTRL.wipe_state` (offset 0x1A0) → `sep_crypto` → `key_manager.wipe_state_i`
  (previously tied `1'b0`). A 0→1 rising edge zeroes all KPV entries and sets the
  WIPE_STATE IRQ. Zero OSS coverage today.
- **Phase-3 qualification: YES.** KM Phase-2 planning explicitly deferred wipe (KM-1 card:
  "KDF/fault-matrix/wipe/RMA deferred"; KM subsystem "wipe infra-gated"). #3719 makes it
  frontdoor-stimulable, but it is a destructive security/lifecycle action + a cross-IP
  edge, not basic breadth — a Phase-3 (security/integration) rep.
- **Run/fuse (proposed):** `no_cpu` + external/CPU-LSU frontdoor; fuse mode per whether
  the KPV pre-state needs real sense (likely `+skip_fuse_sense` for a pure CSR-edge proof).
- **Checker idea (prove-first):** provision KPV state; frontdoor 0→1 `KM_WIPE_CTRL.wipe_state`;
  prove KPV entries zeroed + WIPE_STATE IRQ asserts → W1C-clear → reads back 0 (full RW1C
  contract per house rules). Frontdoor only (no backdoor KPV read without sign-off).
- **Effort:** moderate (new fw/seq + KPV-state observation path). `GITHUB: TBD (owner to file)`.

### P3-2 — `sep_cpu_sram_aes_sram_test` (TBD)  [Crypto & entropy / CPU integration]

- **OCAH provenance:** new OCAH test `sep_cpu_sram_aes_sram_test` (`6cf1610c3`): real EL2
  CPU firmware provisions an AES-128 key via production KM mailbox firmware
  (CMD_KEY_LOAD + CMD_KEY_TRANSFER sideload to AES), copies a payload SRAM→AES→SRAM
  through the AES DATA_IN/OUT CSRs (encrypt + decrypt, NIST vectors), then ENGINE_SHRED;
  negative `sideload=0` rejected; passive KM→AES private-bus monitor.
- **What is new:** the crypto correctness is already `COVERED_STRONGER` by Phase-1
  `sep_km_aes_sideload_kat_test` (KM→AES sideload consume-proof + ECB round-trip +
  isolation) and Phase-2 CRY-1 `sep_aes_mode_keysize_rand_test`. The only genuinely-new
  intent is the **cpu run-mode** (real EL2 firmware orchestrating KM-mailbox sideload +
  AES compute in one boot) and the **SRAM↔AES↔SRAM CPU data-movement datapath** with
  guard/sentinel checks + negative disable in cpu-fw.
- **Phase-3 qualification: YES (lower priority).** Not a basic GAP (crypto is already
  covered stronger); it is a cpu-firmware *integration* rep. Deferred by construction —
  a Phase-3 integration candidate, not Phase-2 breadth.
- **Run/fuse (proposed):** `cpu` (real EL2 fw boot) + `+km_rom_hex`; `+skip_fuse_sense`
  unless the KM path needs real sense.
- **OSS delta (required):** replace OCAH's backdoor `KeyBusMonitor` (XMR of `sep_tb_km_intf`)
  with the frontdoor isolation proof already used by `sep_km_aes_sideload_kat_test`
  (SW_RESET_N read-back + public-KEY_SHARE=0), per AGENTS.md §7 (no new backdoor without
  sign-off). Infra already exists (km_rom_hex boot, `env/sep_aes_golden.py`, cpu-boot
  harness); AES-128 is a trivial golden extension.
- **Effort:** large (new cpu-fw + SRAM↔AES orchestration + negative + isolation).
  `GITHUB: TBD (owner to file)`.

## Not carried to Phase 3 (audited 2026-07-15, no action)

From the same main-sync audit, these OCAH changes were checked and need no OSS work:
PCRV Caliptra SHA-384 add+revert (open-source hygiene clean, net zero); KM firmware
HMAC-SHA256 split (#3713, committed `.parhex` unaffected; `rom_main.rom.parhex` auto-rebuilt);
boot-ROM startup-flow change (OSS responder self-contained); the TRNG/SPI-reset/LCC→KM
vacuous-pass hardening (OSS ports already fail-closed or the test is not ported); the
token 0x3F rename / SHA-error-leg retire (no OSS reference). One forward guard: a future
KM mailbox-IRQ rep must model KMCSR aggregation as masked (`IRQ_STATUS & IRQ_ENABLE`),
per the #0f66ee69c spec back-port.
