---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cluster_cpu_infra_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094640__verilator__smc_cluster_cpu_infra_test/smc_cluster_cpu_infra_test/logs/smc_cluster_cpu_infra_test.log
  sha256: c61439715a89b0b8ddfbfe1c5247405e1b8b160e94ecd9614c0764e8a70c0cda
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
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:54-88
  observed: >
    The hard gate is `assert_reachable_or_gated(len(CLUSTER_CPU_READS), ...)`, which
    only asserts `self.accesses == expected_accesses`. After the for-loop over
    `CLUSTER_CPU_READS` (each iteration always increments `accesses` once), that
    equality is bookkeeping-tautological — it cannot fail on any RTL response.
    Timeouts only emit a cocotb WARNING; they never raise. On the scoreboard path,
    every probe is issued with `allow_error=True`, `allow_timeout=True`, and
    `expected=None`, so `_check_sys_axi` accepts timeout (`resp_ok=allow_timeout`),
    DECERR (`resp_ok|=allow_error`), and OKAY-with-any-rdata equally as
    `ok=True`. Kept log shows 10 SYS AXI checks all `ok=True` with `exp=None`,
    including six TB "expected timeout" lines, then a WARNING that 6/10 windows
    were gated — and the test still PASSes. No RTL-sensitive FAIL-ON exists for
    the claimed WDT/PLIC/CLINT infra property.
  closure_condition: >
    Replace the vacuous access-count gate with RTL-sensitive FAIL-ON checks for
    each probe class: (a) windows that must respond must not time out and must
    match an independently derived exact resp/rdata (or documented error-slave
    signature); (b) windows intentionally absent must assert a SPEC-defined
    negative outcome with a positive-control allow path elsewhere — not
    "any of OKAY / DECERR / timeout ⇒ pass". Scoreboard `item.expected` /
    `expected_resp` / `expect_error` must be wired so a wrong DUT answer fails.
  waived_by: null
- id: FIND-002
  tag: '[TIMEOUT-MUST-FAIL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:54-71
  observed: >
    `_probe_bounded` sets `item.allow_timeout=True` with `timeout_ns=300`. The
    driver converts wait expiry into a soft return (`resp_ok=allow_timeout`)
    rather than raising. Kept log L282–L330 records six SEP_IN reads that
    "reached expected timeout after 300 ns" (WDT cores 0–3, PLIC_PRIORITY_1,
    CLINT_MSIP_0); `assert_reachable_or_gated` only WARNINGs (L347) and the
    cocotb result is PASS. Policy §1 `[TIMEOUT-MUST-FAIL]` requires every
    bounded wait to convert expiry into testcase failure with last-state
    diagnostics — soft-pass on expiry is forbidden on the proof path.
  closure_condition: >
    Drop `allow_timeout` on the proof path (driver raises on hang), or keep a
    bounded wait only where the SPEC-required outcome is timeout and then
    `assert item.timed_out` (FAIL-ON if the access completes). Do not convert
    expiry into PASS via `allow_timeout` + warning-only gating.
  waived_by: null
- id: FIND-003
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:54-79
  observed: >
    No probe sets `item.expected`, `expected_resp`, or `expect_error`. The four
    non-timeout completions in the kept log are therefore activity-only:
    PLIC_PENDING @ 0xc4001000 returns DECERR + `0xbadcab1e` (L307–L319) with no
    assert of resp/signature; PLIC_ENABLE / CLINT_MTIMECMP_0_LO / CLINT_MTIME_LO
    return OKAY + `0x0` (L323–L345) with no rdata compare. Activity / allowed
    error alone is not an exact WDT/PLIC/CLINT contract.
  closure_condition: >
    For every probe that is in-scope for this bring-up, assert exact AXI resp
    and independently derived rdata (or the documented error-slave signature
    `0xBADCAB1E` via `csr_read_err_signature` / `expect_error`); leave
    `expected=None` only where no independent golden exists and that limit is
    explicit — not as the default for all ten windows.
  waived_by: null
- id: FIND-004
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:27-51
  observed: >
    Partial remediation since prior grade: four WDT probes now use
    `smc_addr("SMC_TOP_SMC_CLUSTER_CORE{0..3}_WDT_BASE_ADDR")`. Remaining
    proof-path addresses are still hand-copied numeric literals —
    `PLIC_PRIORITY_1`/`PENDING_0`/`ENABLE_0` (`0xC400_0004`/`1000`/`2000`),
    `CLINT_MSIP_0`/`MTIMECMP_0_LO`/`MTIME_LO` (`0xC800_0000`/`4000`/`BFF8`),
    plus `CLUSTER_DECERR_RANGES` aperture ends/bases (`0xC000_1000`,
    `0xC400_0000`/`0xC800_0000`/`0xC800_C000`). Generated PeakRDL symbols exist
    via `smc_addr` / `smc_indexed_addr` (e.g.
    `SMC_TOP_SMC_CLUSTER_PLIC_PRIORITY_BASE_ADDR(1)`,
    `SMC_TOP_SMC_CLUSTER_PLIC_PENDING_BASE_ADDR(0)`,
    `SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_BASE_ADDR(0)`,
    `SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR(0)`,
    `SMC_TOP_SMC_CLUSTER_CLINT_MTIMECMP_BASE_ADDR(0)`,
    `SMC_TOP_SMC_CLUSTER_CLINT_MTIME_BASE_ADDR`, plus aperture
    `SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR` /
    `SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR`/`_SIZE`). Current literals match those
    macros (latent-rot class, not false-identity). Sequence labels WDT probes
    `*_CFG` while the map names them `*_CTRL` / `*_WDT_BASE` at the same addresses.
  closure_condition: >
    Import every remaining `CLUSTER_CPU_READS` address (and DECERR aperture
    bases/sizes) from `smc_addr_map` generated symbols; stop using a parallel
    numeric constant table as the addressing source of truth.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cluster_cpu_infra_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 2 Blocking · 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): ten
> frontdoor SEP_IN probes with mixed timeout / DECERR / OKAY outcomes and a
> warning-only "6 gated" gate — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `222b2222…`)

| Item | Prior (log `222b2222…`, PASS) | This audit (log `c6143971…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking · 🟠 2 Major | 🔴 2 Blocking · 🟠 2 Major |
| FIND-001 `[NO-ALWAYS-PASS-CHECKER]` | open — vacuous access-count + soft scoreboard | still open — same gate / soft path on new log |
| FIND-002 `[TIMEOUT-MUST-FAIL]` | open — `allow_timeout` soft-passes 6/10 | still open — L282–L330 six expected timeouts; WARNING L347; PASS |
| FIND-003 `[EXACT-EXPECTATION]` | open — no resp/rdata compares | still open — DECERR/`0xbadcab1e` + three OKAY+`0x0` unchecked |
| FIND-004 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open — all ten addresses + apertures hand-copied | narrowed, still open — WDT ×4 now via `smc_addr`; PLIC/CLINT + DECERR ends still literals (match map → Major) |
| Sequence sha256 | `f8630100…` | `05d1cba7…` (partial address-map migration) |
| Kept log | `222b22223bc56f91e4f9f1312c663332043ccda8529253fe53c0c0b59ad79ac2` | `c61439715a89b0b8ddfbfe1c5247405e1b8b160e94ecd9614c0764e8a70c0cda` |
| Repo / model | `2ecc7b22…` / `2c815fa08277` | `c10b6d63…` / `2c815fa08277` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 4 items (🔴 2 Blocking · 🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_cluster_cpu_infra_test_seq.py:54-88` |
| 2 | finding | FIND-002 | 🔴 Blocking | `smc_cluster_cpu_infra_test_seq.py:54-71` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_cluster_cpu_infra_test_seq.py:54-79` |
| 4 | finding | FIND-004 | 🟠 Major | `smc_cluster_cpu_infra_test_seq.py:27-51` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-ALWAYS-PASS-CHECKER]</code> — vacuous access-count gate + soft scoreboard</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:54-88` (`assert_reachable_or_gated` / `_probe_bounded`)
- **Observed:** Gate only checks `accesses == N` after a loop that always increments once per probe — RTL-insensitive. Scoreboard sees `allow_error` + `allow_timeout` + `exp=None` → all ten checks `ok=True` regardless of DUT answer (timeout / DECERR / OKAY+any data). Log WARNING "4/10 reachable; 6 gated" still PASSes.
- **Closure:** each in-scope probe has an RTL-sensitive FAIL-ON (exact resp/rdata or documented negative with positive control); drop vacuous access-count-as-PASS.

</details>

<details>
<summary>2. FIND-002 — 🔴 Blocking <code>[TIMEOUT-MUST-FAIL]</code> — <code>allow_timeout</code> soft-passes 6/10 probes</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:54-71`
- **Observed:** `allow_timeout=True` / 300 ns: driver soft-returns on expiry. Log L282–L330 shows six "expected timeout" probes; gate only WARNINGs (L347); cocotb PASS. Policy requires bounded-wait expiry → test failure (or an explicit `assert timed_out` when timeout is the SPEC outcome).
- **Closure:** hangs raise, or intentional timeout probes assert `timed_out` (FAIL-ON if the access completes); no soft-pass via `allow_timeout` + warning.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — reachable windows never compare resp/rdata</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:54-79`
- **Observed:** No `expected` / `expected_resp` / `expect_error`. Log: PLIC_PENDING DECERR + `0xbadcab1e` unchecked; three OKAY+`0x0` windows unchecked. Activity alone is not an exact contract.
- **Closure:** in-scope probes assert exact resp/rdata (or error-slave signature); `expected=None` only where no independent golden exists.

</details>

<details>
<summary>4. FIND-004 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — remaining PLIC/CLINT literals</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py:27-51`
- **Observed:** WDT ×4 now via `smc_addr`; PLIC/CLINT probe addresses and DECERR aperture ends/bases remain hand-copied despite generated `smc_addr.h` symbols. Values currently match → Major (latent rot), not Blocking false-identity.
- **Closure:** every remaining proof-path address/aperture is imported from `smc_addr_map` symbols; parallel numeric constants are not the source of truth.

</details>

**Then:** owner remediates FIND-001–FIND-004 on the sequence (and scoreboard wiring), re-keeps a PASS log, and re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; no force/deposit on CSR path; ROM/efuse preload is post-PASS bring-up trailer |
| F2 can't-fail checker | 🔴 Blocking — FIND-001 `[NO-ALWAYS-PASS-CHECKER]` |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; probes always issued |
| E2 empty phase | ✅ clean — ten real SYS AXI transactions issued (scoreboard checks #1–#10) |
| S1 silent fail | ✅ clean — no detected mismatch swallowed to log-only (compares are absent → FIND-003; soft timeout → FIND-002) |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard and AXI monitor active (DECERR ranges extended, not disabled) |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001, FIND-002; 🟠 Major — FIND-003, FIND-004; enrolled in `p1_coverage_gap.toml` / `all.toml`; seed logged; no unconditional CHK token; VIP `timeouts=0` is incomplete wiring (seq counted 6) noted in appendix |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Test: `hw/sys/smc/dv/cocotb/tests/smc_cluster_cpu_infra_test.py`
  sha256 `d81fc6876e457994d6b19f75953621a318c1fc92d1871c3e64f37c4a43c53cc6`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_cpu_infra_test_seq.py`
  sha256 `05d1cba7e50aa349418bef7c1e61ebb2d59263047269ffcb7a4f35a57f9453ec`
- Helpers on proof path: `smc_csr_seq_utils.assert_reachable_or_gated`,
  `smc_sys_axi_agent._drive` / `_timed_event`, `smc_scoreboard._check_sys_axi`,
  `smc_axi_monitor.expected_decerr_ranges`, `smc_addr_map.smc_addr`
- Log: `hw/sys/smc/dv/build/runs/20260806_094640__verilator__smc_cluster_cpu_infra_test/smc_cluster_cpu_infra_test/logs/smc_cluster_cpu_infra_test.log`
  sha256 `c61439715a89b0b8ddfbfe1c5247405e1b8b160e94ecd9614c0764e8a70c0cda`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `exit_code: 0`, cocotb summary L353–L359:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final gate: `assert_reachable_or_gated(10, "Cluster CPU infra", ...)` after ten
  `_probe_bounded` calls; WARNING L347 `4/10 reachable; 6 gated/absent`
- Scoreboard: checks #1–#10 all `exp=None ok=True`; AXI monitor trailer L351:
  `4 R beats, 0 B; R-resp tally OKAY=3, DECERR=1; 0 errors`
- Protocol VIP L348: `csr_accesses=10 timeouts=0 passed=True` — test does not
  pass `timeouts=seq.timeouts` (defaults to 0) while the sequence counted six
  timeouts; incomplete evidence record, not used as a separate finding id
- Addressing: WDT via `smc_addr` at seq `:29-32`; remaining literals `:34-40` /
  DECERR `:47-50`; generated truth in `hw/sys/smc/regs/gen/c/smc_addr.h`
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml` (included by `all.toml`)
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as CSR golden substitution on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`)
- Auditor: `cursor/grok/4.5-reaudit-20260806` (re-audit; prior auditor `cursor/grok/4.5`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>c6143971…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| WDT CORE0–3 | 280–299 | four TB expected timeouts @ `0xc0000{000,400,800,c00}` | seq `:29-32` (`smc_addr`) |
| PLIC_PRIORITY_1 | 300–304 | expected timeout @ `0xc4000004` | seq `:34` (literal) |
| PLIC_PENDING_0 | 305–320 | DECERR (expected) + `0xbadcab1e`, scoreboard ok | seq `:35` |
| PLIC_ENABLE_0 | 321–327 | OKAY + `0x0` | seq `:36` |
| CLINT_MSIP_0 | 328–332 | expected timeout @ `0xc8000000` | seq `:38` |
| CLINT_MTIMECMP / MTIME | 333–346 | OKAY + `0x0` | seq `:39-40` |
| gate WARNING | 347 | `4/10 reachable; 6 gated` | seq `:84-88` |
| protocol VIP | 348–349 | `csr_accesses=10 timeouts=0` | test `:22-28` |
| cocotb result | 353–359 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a no-deadlock / partial-decode probe of WDT+PLIC+CLINT proves the SPEC
  properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
