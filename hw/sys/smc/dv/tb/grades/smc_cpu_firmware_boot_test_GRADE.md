---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cpu_firmware_boot_test
ip: SMC_ACTIVE_REGRESSION
anchor: null
mode: NO-CHECKBOX
no_contract_reason: STANDALONE-REQUEST
entry_status: NOT-EVALUATED
repository_revision: c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7
spec: []
card_sha256: null
card_revision: null
card_path: null
testcase_plan:
  path: null
  plan_revision: null
  testcase_revision: null
  testcase_record_sha256: null
  parent_approved: null
evidence_class: null
closure_tier: null
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 2c815fa08277
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smc/dv/build/runs/20260806_094630__verilator__smc_cpu_firmware_boot_test/smc_cpu_firmware_boot_test/logs/smc_cpu_firmware_boot_test.log
  sha256: 508baec64dc2116c1126bec89a5bfa3a13fca6b2a2b374911b5fad031a16ed94
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-reaudit-20260806
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[NO-UNJUSTIFIED-PRELOAD]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/smc_wrapper_sim_cfg.toml:97
  observed: >
    Kept-run `test_args` still carry two `+rom_hex=` values: flow default
    `…/smc_rom_default.hex` then testlist override `…/min_pass.rom.hex`, plus
    `+smc_rom_hex=…/min_pass.rom.hex`. Post-run flush shows
    `OCAH4CORECluster_rom_ext` loaded `smc_rom_default.hex` from first-match
    `+rom_hex` while `[smc_cpu_mem_integration] backdoor ROM` loaded
    `min_pass.rom.hex`. Two distinct ROM images remain resident on the boot
    proof path even though this seed reached PASS magic with
    `tb_cpu_rom_read_count 0→36`; a LIVE `min_pass`-only ROM-target claim is
    still not uniquely identified while the default shortcut wins OCAH's
    `$value$plusargs` first-match.
  closure_condition: >
    Ensure a single authoritative ROM image for this test: drop or override the
    flow-default `+rom_hex` so only `min_pass.rom.hex` is visible to every ROM
    loader (`OCAH4CORECluster_rom_ext` and `smc_cpu_mem_integration`), keep a
    log that names one hex path for both, then re-prove boot with non-zero
    `tb_cpu_rom_read_count` and PASS magic.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cpu_firmware_boot_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): cocotb
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, final `SMC_002 scenario PASS`, zero unexplained
> `ERROR`/`FATAL`/`Traceback` — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade on FAIL log `6f689b9b…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[NO-UNJUSTIFIED-PRELOAD]` | OPEN | Dual `+rom_hex` default vs `min_pass` still in `test_args` and flush L389–L391 on new PASS log `508baec6…` |
| FIND-002 | `[EVIDENCE-TOKEN-CONDITIONAL]` | CLOSED | Success path no longer emits `CHK-TIMEOUT-PATHS`; S4 only logs `CHK-NONVAC` with bound bookkeeping (seq comment + L368–L369) |
| sim result | FAIL → PASS | UPGRADED | Prior stuck `isolate=1` / `rom_reads=0`; this run releases hold, fetches ROM (`0→36`), PASS magic `0xacafaca1` on SCRATCH0 |

## Your to-do — 1 item (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[NO-UNJUSTIFIED-PRELOAD]` — dual `+rom_hex` default vs `min_pass` |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[NO-UNJUSTIFIED-PRELOAD]</code> — conflicting ROM images</summary>

- **Where:** flow `smc_wrapper_sim_cfg.toml:97` default `+rom_hex=smc_rom_default.hex`
  prepended ahead of testlist `+rom_hex=…/min_pass.rom.hex` /
  `+smc_rom_hex=…/min_pass.rom.hex`
- **Observed:** kept-run `test_args` list both hex paths; flush L389–L391 shows OCAH
  loaded default while `smc_cpu_mem_integration` loaded `min_pass`. Boot reached PASS
  with ROM fetch evidence, but the image under test is still not uniquely named for
  every loader.
- **Closure:** one `+rom_hex` / one loader image (`min_pass` only); re-keep a log
  that shows a single hex path for both OCAH and mem_integration.

</details>

**Then:** owner resolves ROM plusarg identity (FIND-001), re-keeps a PASS log with a
single ROM image, then re-invoke `/dv_test_audit smc_cpu_firmware_boot_test`. Do not
invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR program/release + pad57 boot_stall via `tb_gpio_ext_drive_*`; PASS magic / fetch counters from DUT/TB mirrors; no force/deposit of success state |
| F2 can't-fail checker | ✅ clean — boot poll / fuse 0→1 / magic / rom_reads / vector readback asserts are reachable `AssertionError` paths |
| E1 skip-to-pass | ✅ clean — `require_image=True` raises if preload missing; no HDL-path skip-to-pass; fuse already-high without 0→1 raises |
| E2 empty phase | ✅ clean — S1 BFM obs, S2 fuse wait+CHK, S3 boot contract+CHKs, S4 NONVAC all executed on this PASS |
| S1 silent fail | ✅ clean — helper raises with last_csr/tb_mbox/rom_reads/isolate diagnostics; mismatches raise |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks active through release/poll; no scoreboard/VIP disable for boot |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[NO-UNJUSTIFIED-PRELOAD]`; else PeakRDL CPU_CTRL addresses, bounded fuse/boot waits fail-on-expiry, seed logged, enrolled in `vplan_triplets.toml` / `all.toml`, CHK-* after prior asserts on success path, X/Z via `is_resolvable`; prior FIND-002 closed |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Test: `hw/sys/smc/dv/cocotb/tests/smc_cpu_firmware_boot_test.py` — fuse watcher +
  `_bring_up` then `smc_cpu_firmware_boot_test_seq` on `sys_axi_agent.sequencer`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_firmware_boot_test_seq.py`
- Helpers on proof path: `smc_cpu_vip_utils.check_cpu_bfm_observability`,
  `check_cpu_firmware_boot_contract` / `_release_held_cpu_boot`,
  `SmcCsrSeq` AXI CSR R/W, scoreboard SYS AXI
- Log: `hw/sys/smc/dv/build/runs/20260806_094630__verilator__smc_cpu_firmware_boot_test/smc_cpu_firmware_boot_test/logs/smc_cpu_firmware_boot_test.log`
  sha256 `508baec64dc2116c1126bec89a5bfa3a13fca6b2a2b374911b5fad031a16ed94`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L380–L382:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Authoritative PASS facts (policy §5, recorded only — entry not graded in NO-CHECKBOX):
  scenario PASS L370; final assertion gate via boot contract magic + seq asserts;
  zero `ERROR`/`FATAL`/`Traceback` in kept log.
- Boot evidence: S1 BFM obs (L281); S2 `CHK-EFUSE-SENSE-DONE` (L283); S3 release
  `vector=0xc0040000` (L344); SCRATCH0 read `0xacafaca1` (L355); CHKs
  RESET-VECTOR-FETCH / ROM-IS-TARGET / CLK-SMC-LIVE (L365–L367); S4 `CHK-NONVAC`
  (L369) with `rom_reads=36`, `wb_pc0=0xc004001c`.
- Plusarg composition (FIND-001): `test_args` =
  `+rom_hex=…/smc_rom_default.hex` then `+rom_hex=…/min_pass.rom.hex` +
  `+smc_rom_hex=…/min_pass.rom.hex`; flush L389–L391 shows default vs `min_pass`
  dual load.
- Addressing: PeakRDL `smc_reg` symbols for CPU_CTRL RESET_VECTOR / RESET_CTRL /
  SCRATCH_0 / RESET_TIMEOUT.
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`, `all.toml`
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`; `entry_status: NOT-EVALUATED`).
- Provenance: legacy (`test_author.run_id: unknown`).
- Prior waivers: none (`approved_by` null or empty ledger — nothing carried forward).

</details>

<details>
<summary>Stimulus / pass cites (kept log <code>508baec6…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 267–281 | clocks, powergood, cold release; BFM obs | test / `check_cpu_bfm_observability` |
| S2 fuse | 282–283 | `CHK-EFUSE-SENSE-DONE` saw_low/high | seq `_wait_fuse_sense_transition` |
| S3 start | 284–301 | `min_pass.rom.hex`, baselines 0, SCRATCH0 clear | `check_cpu_firmware_boot_contract` |
| release | 302–344 | TIMEOUT force, vectors `0xc0040000`, RESET_CTRL `0x10f`, stall drop | `_release_held_cpu_boot` |
| PASS poll | 345–364 | SCRATCH0=`0xacafaca1`; vector readback `0xc0040000` | helper poll + seq |
| CHKs | 365–370 | FETCH / ROM-IS-TARGET / CLK-SMC-LIVE / NONVAC; scenario PASS | seq body |
| plusarg flush | 384–391 | hold_cpu_boot; OCAH default ROM; mem_integration `min_pass` | TB / loaders |

</details>

## Not concluded

- Whether ROM boot to PASS magic proves the SPEC properties a future card would
  require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
