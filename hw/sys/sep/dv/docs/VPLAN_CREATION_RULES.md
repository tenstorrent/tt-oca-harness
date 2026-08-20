<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS DV VPLAN Creation Rules

This document defines the OSS-vs-OCAH **VPLAN creation rules** for SEP DV.
Testcase creation and implementation rules live in `../AGENTS.md`; testcase work
must follow the VPLAN after coverage intent, overlap, and ownership are
understood.

VPLAN creation starts from the public SEP RTL, specifications, and current
testlists. It builds a subsystem coverage map, then chooses a regression that
proves each feature intent with frontdoor, evidence-backed checks — broad enough
to cover every IP's basic behavior and compact enough to stay auditable.

**Where these artifacts live.** This doc refers to "the VPLAN/detail/tracker"
throughout. There is one VPLAN pair per phase; **Phase 2 (current) is the active
target**, so new planning work writes to the Phase-2 files:

- Summary VPLAN (active): `docs/SEP_OSS_VPLAN_PHASE2.md` — the per-test mapping rows,
  per-subsystem coverage accounting, and status.
- Detailed entries + per-subsystem basic-feature ledger (active):
  `docs/SEP_OSS_VPLAN_PHASE2_DETAIL.txt` (the ledger may instead live in a dedicated
  `docs/SEP_OSS_FEATURE_LEDGER.md`; see "Basic-Feature Coverage Ledger").
- Phase-1 record (closed, smoke + TOP-20): `docs/SEP_OSS_VPLAN_PHASE1.md` +
  `docs/SEP_OSS_VPLAN_PHASE1_DETAIL.txt` — the 31-test baseline this phase builds on.
- Tracker: the GitHub issue/board mirroring the checker boxes.

## Phase Context and Objective

VPLAN creation happens in phases, and the phase decides which way the rules lean.

- **Phase 1 (complete): density-first compression.** ~689 OCAH tests were
  compressed into a 31-test representative baseline (the TOP-20 cross-module /
  security-headline ports plus a bring-up/smoke suite). The risk then was *bloat*,
  so "fewest tests for the most coverage" was the primary driver.
- **Phase 2 (current): breadth-first basic coverage.** Grow the baseline toward
  100+ testcases so that **every IP has its basic functional behavior covered**.
  Use the public SEP RTL and specifications to define basic feature intent and
  aim to cover **at least 60% (stretch 75%)**. The risk now *inverts* to
  *under-coverage*, so the primary driver is **coverage completeness**, measured
  against the per-IP basic-feature ledger (see "Basic-Feature Coverage Ledger").

**What Phase 2 covers, and what it defers.** Phase 2 is **basic functional
scenarios only** — the normal-operation datapath, the common modes/configs, the
CSR/status sanity, and the cross-subsystem happy path for each IP. Phase 2
defers **advanced** corner cases, error injection, security permutations, and
negative-path matrices to a later coverage phase (the remaining ~25%+).
It does **not** defer the checks that make a basic test truthful:

- Any status/interrupt/RW1C bit observed by a Phase-2 test must still prove the
  full observe -> W1C clear -> readback-0 contract.
- Any access-control or security gate that defines an IP's normal basic behavior
  must be covered as basic functionality, not postponed as a corner case.
- Any negative response that is the expected result of the basic datapath under
  test must be checked exactly (`DECERR`, `SLVERR`, blocked data, etc.), not
  treated as optional depth.

When a Phase-2 test naturally touches a deeper negative/corner intent beyond
those basic contracts, record that extra intent as a `GAP (deferred)` in the
ledger for the later phase; do not let it expand the basic test.

**Coverage completeness is primary; compression is the technique.** The
no-overlap, merge, and randomized-representative rules below are *how* you reach
the ≥60% basic-feature target with ~100 tests instead of a 1:1 OCAH port — they
are the **means**, not the goal. No-overlap is a guard against *true* duplicates,
not a reason to leave an IP's basic feature uncovered. When the two pull against
each other, coverage completeness wins and compression yields.

**Coverage is a mindset/checklist, not a measured percentage.** The ≥60% target
is read off the basic-feature ledger (covered vs GAP per IP), not from a vdb/FCOV
number. SV covergroups are compiled out under the Verilator merge gate
(`` `ifndef VERILATOR `` per `../AGENTS.md` §6), so do not plan around a measured
functional-coverage figure; plan around the ledger.

## VPLAN Strategy

OCAH SEP is broad: hundreds of UVM and firmware tests, many narrow tests, many
proxy paths, and many overlapping CSR/status permutations. To reach the Phase-2
basic-coverage target without a 1:1 port, the OSS VPLAN uses compression as its
selection technique (in service of the completeness goal above):

- Start from subsystem-level coverage, not from individual testcase names.
- For each subsystem, identify the important IPs, cross-IP datapaths, security
  boundaries, interrupts/resets, negative/error behavior, and required DV infra.
- Port unique coverage intent, not every OCAH testcase name.
- Prefer one representative OSS test that covers several overlapping OCAH tests
  when the run mode, fuse mode, runtime, and debug story remain reasonable.
- Keep separate tests when behavior needs a different execution owner, fuse-sense
  mode, long runtime, failure-isolation boundary, or fundamentally different
  checker/golden model.
- Prefer real frontdoor datapaths over OCAH proxy/backdoor shortcuts when feasible.
- Preserve or strengthen OCAH's real checkers. Do not silently drop a checker just
  because the OCAH mechanism does not map directly onto the OSS DUT.
- Use randomized representatives when they are stronger coverage compression than
  many directed tests. One well-constrained, seeded, logged PyUVM randomized test
  with exact checkers can cover a family of overlapping OCAH directed tests.

### Phase-2 Randomized Strategy

Phase 2 uses **randomization as controlled breadth**, not as unbounded stress. A
randomized Phase-2 test still has a fixed, auditable checker contract; only the
legal point selected inside that contract varies by seed.

There are two distinct categories:

- **`RAND-REP` / RANDOMIZED-REP**: a `MERGED_INTO` representative whose purpose is to collapse a
  family of OCAH directed tests or a mode/facet matrix into one seeded test. Examples:
  KM-1/KM-2, CRY-1/2/3, SPI-1/2, and PIO-1.
- **`RANDCFG` / directed rep with constrained-random point selection**: a `COVERED_BY` or
  `COVERED_STRONGER` representative whose coverage intent remains directed, but the
  specific legal instance is selected by seed. Examples: FAB-1, TD-2, FAB-3, and
  RST-1. These should not be relabeled `RANDOMIZED-REP`; record the `RANDOMIZATION`
  config in the detail card and keep the original mapping outcome.
- **`RAND-NONE`**: no randomization is intended; the testcase is fully directed. This
  is the default when the VPLAN has no `RANDOMIZATION` field.

Every Phase-2 row or detailed card that uses randomization must carry one of the
explicit labels above. Use `RANDCFG` for constrained-random upgrades to directed
representatives; use `RAND-REP` only for merged randomized representatives.

The preferred pattern is:

- Walk the discrete coverage intent deterministically in one run when the intent is
  a family of modes/facets (commands, algorithms, CSR facets, error classes, source
  sets). Do not let one random seed accidentally skip a required coverage cell.
- Randomize only legal continuous knobs: vetted addresses, source subsets, CSR
  field patterns with RO/reserved bits masked, thresholds inside bounded sim-time
  limits, payload/key/message data, or representative region/entry indices.
- Keep OCAH anchors when they define the original coverage intent, then add seeded
  randomized points around them. For example, a decode-error test keeps the OCAH
  invalid-target addresses and adds reserved-gap randoms; it does not replace the
  OCAH anchors with arbitrary addresses.
- Use one small config object as the single source of truth for the selected points,
  DUT programming, and checker/golden expectations. Log the seed and resolved
  config at the start of the test.
- Keep positive evidence per checker (`CHK-* PASS`) and make the evidence name the
  resolved randomized point when useful.
- Keep status-clear/security proofs deterministic in meaning. Randomization may
  choose which legal source or threshold is used, but it must not weaken the
  observe -> clear -> readback-0, exact response, or non-vacuity contract.

Current Phase-2 examples:

- `RANDCFG` `FAB-1`: OCAH invalid-target anchors plus seeded reserved-gap unmapped reads and
  a seeded unmapped write target, all expecting exact DECERR.
- `RANDCFG` `TD-2`: seeded subset of at least two vetted cross-IP interrupt sources plus a
  seeded single-source baseline, with full anti-alias and W1C clear proof.
- `RANDCFG` `FAB-3`: seeded remap/filter region and entry indices plus masked legal CSR field
  patterns; permanent lock checks are still ordered last.
- `RANDCFG` `RST-1`: seeded small/large WKUP thresholds and pre/post-lock WDOG_BARK values,
  bounded so the sim-time contract stays stable.
- `RAND-REP` `PIO-1`: seeded WIRQT, first-fill length, and 64-bit payloads with a fixed TX-side
  mailbox facet walk.

The output of this strategy is a VPLAN-backed OSS regression that is smaller than
OCAH but easier to audit: every test has clear subsystem ownership, checkers,
evidence, and accepted deltas.

## Top-Down Value Rule (OSS vs OCAH)

OCAH SEP DV is **bottom-up** (IP-by-IP, ~100% complete) — treat it as the authority
for **IP-internal** behavior. The OSS env is **top-down**: a rep earns its place by
proving something OCAH's per-IP testbenches *structurally cannot* —

- **(A) an integration edge** — a cross-IP / system-level path no single IP tb sees
  (real fabric routing, sideload across IPs, shared-resource arbitration, interrupt
  fan-in/aggregation, reset-domain propagation, real CPU frontdoor), or
- **(B) a hole** — something OCAH's bottom-up approach leaves (bare-sep hookup, a
  config/connectivity gap, an orphan source, a negative/security path at the system
  level).

Re-deriving an IP's internal mode/feature matrix on bare-sep, when OCAH already owns
it ~100%, is **redundant (class C)** — its only OSS value is the thin slice where the
integration genuinely differs (entropy bring-up, real routing, status-clear/RW1C that
makes a basic test truthful). **Classify each rep A / B / C.** A class-C rep must be
trimmed to its integration/status-clear slice or carry an explicit integration
justification; do not spend OSS effort rebuilding goldens for an OCAH-owned matrix.
**Compress against OCAH, not only against Phase-1** — the No-Overlap Rule applies to
OCAH's coverage too, not just the existing OSS suite. Evidence this lens pays off: the
OSS env's real bug finds (mailbox IRQ truncation, inbound-filter polarity, the SS-1
KM×crypto interconnect gap) were all integration-seam / fan-in-out-packing bugs no
IP-internal test could see.

## Creation Flow

Do not create tests directly from a list of OCAH testcase names. Create or update
the VPLAN with this flow:

1. Build a subsystem map from OCAH SEP, architecture docs, and existing OSS tests.
2. Group OCAH tests by coverage intent: datapath, CSR/status, interrupt/reset,
   security gate, negative/error path, or integration flow.
3. Remove overlap by selecting one OSS representative for each coverage intent.
   Start from the current OSS baseline regression (the live `all.toml` "all"
   group): do not add a new representative until the basic-feature ledger shows
   the intent is a real GAP, not already covered by the baseline or closable by
   strengthening one baseline test.
4. Decide whether each representative is an existing OSS test to strengthen or a
   new test to add.
5. Record the mapping, required checkers, run mode, fuse mode, and DV infra in the
   VPLAN/detail/tracker.
6. Only then hand the selected representative to the testcase creation workflow
   in `AGENTS.md`.

Test creation is a downstream action. If the VPLAN cannot explain why a new test
is unique, the test should not be created.

## OCAH Provenance Gate

**Every Phase-2 basic-feature coverage test must trace to at least one public
RTL, specification, test, sequence, or firmware source in its `OCAH-REFS`
field.** A Phase-2 test with an empty `OCAH-REFS` field fails the No-Coding
Gate. Traceability may take any of
these forms (record which one in the `MAPPING` outcome):

- A 1:1 port of one OCAH test (`COVERED_BY` / `COVERED_STRONGER`).
- A merge of several OCAH tests into one representative (`MERGED_INTO`; see
  "Combined-Per-Group Representative Rule").
- A randomized representative that covers a family of OCAH directed tests
  (`MERGED_INTO`; see "Randomized Representative Rule").
- A stronger or more-frontdoor OSS re-expression of an OCAH intent
  (`COVERED_STRONGER`).

If no OCAH test exercises the intent, it is **not** a Phase-2 basic-coverage item:
record it as a `GAP` against the IP `.adoc` spec for a later phase — do not invent
a Phase-2 test to "cover" it. The single carve-out is **OSS bring-up / responder /
smoke infrastructure** (the Phase-1 smoke suite and any future responder self-test),
which validates the OSS DV harness itself and needs no OCAH origin; tag these
explicitly as infra-smoke, not basic-feature coverage. Re-read the OCAH ref
(`git log`) before claiming provenance and again before merge — OCAH is a moving
target (see "Required Mapping Artifact").

**Provenance must be DISTINCT (anti-redundancy check).** Citing a real OCAH test is
necessary but not sufficient: before adding a rep, confirm no *existing OSS test*
(Phase-1 or an already-planned Phase-2 rep) already covers that OCAH ref's behavior.
If the cited OCAH test is already ported, the new rep is redundant unless it proves a
genuinely different edge — name that edge explicitly in `RELATION`. (Lesson: a planned
DRBG dual-endpoint rep cited the same OCAH ref as a Phase-1 test that already ran the
concurrent fork, and had to be dropped.) Two reps citing the same OCAH ref is a red flag.

## Hardware-Under-Test, Not Firmware Application

SEP OSS DV verifies the **hardware**. Firmware / ROMCODE (boot ROM BL0/BL1, KM
firmware, test firmware) is a **stimulus vehicle** that exercises a HW datapath,
register, interrupt, or reset path — it is not the verification target. We do not
own the ROMCODE and do not re-verify its application logic.

- **Boot ROM example.** The HW contract is "the CPU can fetch and execute from the
  ROM" (IFU fetch → retire → correct return). It is **not** "BL0/BL1 performs its
  boot-application steps correctly" (BSS-zero, manifest/secure-boot validation,
  eFuse read-lock policy, failover FSM). Prove the former; the latter is firmware
  verification, out of DV scope.
- A firmware-driven test is **in scope** when its checkers assert a HW behavior
  (NMI vector wiring, PIC source-id delivery, reset-wire pulse, CSR default/RW,
  memory datapath). It is **out of scope** when its checkers assert what the
  application code computes or decides.
- Map application-only OCAH tests as `OSS_DELTA_ACCEPTED` (firmware-application, not
  HW) with a one-line reason, so they are recorded — not silently dropped.

## Subsystem View

Use subsystem coverage groups for planning. IPs are still tracked, but they are
not the top-level planning unit.

| Subsystem group | Coverage intent |
|---|---|
| CPU complex | EL2 boot/run, IFU/LSU, TCM (ICCM/DCCM), CPU CSRs, traps, NMI, the PIC + interrupt delivery to the CPU (mailbox→PIC, IP-IRQ→PIC, RISC-V timer/soft int), CPU reset (warm/cold domains, dbg_rstb, sep_cpu_reset_n gating), firmware PASS/FAIL harness, CPU debug. The VeeR EL2 core complex — the PIC and TCM live *inside* it, so interrupt delivery and CPU reset are CPU, not a separate group. |
| Fabric and security routing | Address map, xbar, local/global remap, alias/output remap, inbound/outbound filters, blocked/allowed responses. |
| Memory subsystem | External SRAM, boot ROM (AXI read-port behavior), memory responders, DMA/CPU memory visibility. (CPU-visible TCM/ICCM/DCCM access belongs to CPU complex.) |
| Reset & timer glue | Per-IP SW-reset (`SW_RESET_N` resetting crypto/KM/OTBN), reset propagation across IPs, clock-gating distribution, the WDT/AON-timer peripheral internals (counter/thresholds/CSRs; its bark→NMI and bite→reset effects are proven in CPU complex). |
| DMA and data movement | DMA copy/hash, DMA/FW contention, peripheral-triggered DMA, status/error/RW1C. |
| eFuse/lifecycle/security state | OTP sense/image/shadow, LC state, LCC feat_ctrl, JTAG/eFuse gates, security-state transitions. |
| KM and key distribution | KM boot/firmware, commands, mailbox, OTP dependency, sideload to crypto consumers, isolation. |
| Crypto and entropy | AES/HMAC/KMAC/OTBN, ESRC/CSRNG/EDN/DRBG, entropy consumers, engine KATs and alerts. |
| Peripheral IO | OpenTitan SPI, flash model, peripheral data movement, future UART/I2C/GPIO/timer if in OSS scope. |

Each subsystem should eventually have at least: one smoke/CSR/status proof, one
real datapath/integration proof, one negative/error/status-clear proof, and one
cross-subsystem proof when the subsystem participates in a security or fabric
edge. In Phase 2 the smoke, datapath, and cross-subsystem axes are in scope; the
advanced negative/error/status-clear axis is recorded as a ledger GAP for the
later phase, except for status-clear/access-control checks that are part of a
basic test's contract (see "Phase Context and Objective").

## Basic-Feature Coverage Ledger

This is the **primary Phase-2 planning artifact**. The ≥60% basic-coverage goal
is a ratio, so it needs an explicit denominator (OCAH's basic features per IP)
and numerator (which the OSS suite covers). The per-test mapping blocks and the
block-touch coverage matrix do **not** give you this: a single test touching AES
marks the *block* covered while leaving most of AES's basic features untested, so
a block checkmark overstates basic-feature coverage. The ledger is the instrument
the Coverage Accounting Rule and Maturity Claim Rule require.

Maintain, per subsystem (incrementally, as you plan that subsystem), a table:

```text
IP   | basic feature (from OCAH)        | OCAH test(s)   | OSS coverage          | outcome
AES  | ECB-256 encrypt                  | aes_ecb_test   | sep_km_aes_..._kat    | COVERED_BY
AES  | CBC mode                         | aes_cbc_test   | —                     | GAP
AES  | key-load + status sanity         | aes_..._test   | —                     | GAP (basic)
```

Rules for the ledger:

- **Granularity is coarse and checklist-style**, not covergroup bins or a vdb
  percentage. List the basic features a reviewer would expect an IP to have
  (modes, key/config widths, datapath, CSR/status sanity, the cross-subsystem
  happy path), derived from the OCAH tests + the IP `.adoc`.
- **OCAH is the 100% denominator.** Enumerate only OCAH's *basic* features here;
  advanced corner/negative/error features belong to the later phase and are
  listed as `GAP (deferred)` so they are not silently lost. Keep basic
  access-control and any observed status-clear contract in the Phase-2 ledger.
- The **≥60% read-off** for an IP is `COVERED / total-basic-features`, judged as a
  mindset, not a precise number.
- Each row's `outcome` uses the OCAH Mapping Outcomes taxonomy
  (`COVERED_BY` / `COVERED_STRONGER` / `MERGED_INTO` / `OSS_DELTA_ACCEPTED` / `GAP`).
- The ledger **feeds the No-Coding Gate**: a new test is justified only by the
  ledger GAP(s) it closes. If the ledger shows no basic-feature gap, do not add
  the test — strengthen an existing representative instead.
- Where it lives: a ledger section per subsystem in `SEP_OSS_VPLAN_PHASE2_DETAIL.txt`
  (or a dedicated `SEP_OSS_FEATURE_LEDGER.md`), kept beside the per-test entries.

## Testlist Taxonomy

Keep the number of `.toml` files small. Local testlists are execution and review
buckets, not a full IP taxonomy. Use tags and VPLAN mapping for finer ownership.

Default subsystem-to-testlist mapping (primary coverage intent can override — see
below):

| VPLAN subsystem group | Owning testlist |
|---|---|
| CPU complex | `cpu.toml` by default. A CPU-complex test whose proof is CPU-internal-to-firmware (trap/NMI/PIC-claim seen only by firmware) lives in `cpu.toml`; one whose execution/glue intent is system-level (e.g. mailbox→PIC delivery, reset propagation) may live in `system.toml` per the override below — the planning *group* stays CPU complex regardless of bucket. |
| Fabric and security routing | `system.toml` |
| Memory subsystem | `memory.toml` (external SRAM/ROM; CPU-visible TCM access is a CPU-complex test) |
| Reset & timer glue | `system.toml` (per-IP SW-reset, reset propagation, WDT/AON-timer peripheral) |
| DMA and data movement | `cpu.toml` for CPU-visible DMA datapath proofs; `system.toml` when the primary intent is fabric arbitration/contention or system glue |
| eFuse/lifecycle/security state | `efuse_lcc.toml` |
| KM and key distribution | `km.toml` |
| Crypto and entropy | `crypto.toml`, except KM-owned flows go to `km.toml` |
| Peripheral IO | `spi.toml` for SPI; otherwise the closest existing owner until a new bucket is justified |

This mapping is the default for VPLAN creation, but **primary coverage intent
wins over run-mode/owner when they conflict.** A `cpu`-mode firmware test whose
headline coverage is *not* the CPU core lives in `system.toml`, not `cpu.toml`.
The current baseline follows this: CPU-complex tests live in `cpu.toml`
(`sep_mailbox_plic_test` = mailbox→PIC→CPU delivery, `sep_nmi_sanity_test` = NMI,
`sep_cpu_ifu_lsu_alias_remap_matrix_test` = CPU IFU/LSU remap — the PIC, NMI, and
IFU/LSU are CPU-core), while `sep_dma_cpu_contention_test` (DMA/fabric arbitration)
and `sep_reset_wdt_sanity_test` (reset_ctrl + WDT timer glue) are `run_modes =
["cpu"]` firmware tests that stay in `system.toml` because their headline is
fabric / reset-&-timer-glue, not the CPU core. When a placement deviates from the
table for execution-infra or ownership reasons, note it in the VPLAN row/detail
and the testlist comment.

Current bucket meanings:

| Testlist | Owns |
|---|---|
| `cpu.toml` | The CPU complex: EL2 boot, firmware harness, CPU-visible DMA/TCM/ICCM/DCCM datapath, CPU CSRs, traps/NMI, PIC + interrupt delivery to the CPU, and CPU reset (warm/cold/dbg_rstb) whose proof is CPU-internal to firmware. |
| `system.toml` | Fabric, address map, routing, remap, filters, external masters, subsystem glue, security routing, reset & timer glue (per-IP SW-reset, reset propagation, WDT/AON-timer peripheral), non-CPU system stimulus, and CPU-complex tests whose execution intent is system-level integration (e.g. mailbox→PIC delivery, DMA/CPU contention, reset propagation). |
| `memory.toml` | External SRAM, boot ROM (AXI read-port), memory responders, memory-only smoke. (CPU-visible TCM access is a `cpu.toml` test.) |
| `crypto.toml` | AES, HMAC, KMAC, OTBN, ESRC/CSRNG/EDN/DRBG, crypto entropy and crypto-engine integration, except KM-owned flows. |
| `km.toml` | Key Manager CPU, KM commands, KM mailbox, KM boot, KM sideload source, KM plus entropy/security flows. |
| `efuse_lcc.toml` | eFuse/OTP, shadow/sense/image, lifecycle controller, LCC feat_ctrl, JTAG-OTP gating. |
| `spi.toml` | OpenTitan SPI, flash BFM flows, SPI-triggered DMA. |

Do not create a new testlist just because OCAH has a separate feature directory.
Add a new `.toml` only when an existing bucket becomes unreadable or the execution
requirements are genuinely different.

## OCAH Mapping Outcomes

These labels are not a formal taxonomy to memorize. They are short VPLAN outcomes
that answer one question: **what did we do with this OCAH coverage intent?**

Use them in the VPLAN/detail/tracker when reviewing OCAH tests and deciding the
OSS representative:

| Label | Meaning |
|---|---|
| `COVERED_BY` | Existing/new OSS test proves the same meaningful checker contract. No extra testcase needed. |
| `COVERED_STRONGER` | OSS proves the intent in a better way, usually more frontdoor or more exact than OCAH. |
| `MERGED_INTO` | OCAH test is not ported as its own test; its useful checkers are folded into a broader OSS representative. |
| `OSS_DELTA_ACCEPTED` | OCAH behavior is not directly portable or not worth duplicating because of licensed IP, internal-only proxy, backdoor, or non-OSS path. The replacement or omission is documented. |
| `GAP` | Unique coverage remains missing. It needs a future OSS representative test or an explicit waiver. |

`GAP` carries a Phase qualifier wherever the basic-vs-advanced split matters (the
ledger and Phase Context):

- `GAP (basic)` — an uncovered OCAH *basic* feature: a Phase-2 numerator miss that is
  in scope now and must be closed by a representative or strengthened baseline test.
- `GAP (deferred)` — an advanced/corner/negative/security-permutation feature pushed to
  the later coverage phase; recorded in the ledger so it is not silently lost, but it
  does not count against the Phase-2 ≥60% basic target.

`COVERED_STRONGER` is the preferred outcome when feasible. Examples include:
frontdoor RW1C clear proof where OCAH only observes DONE, exact data/golden
comparison where OCAH only observes activity, or real CPU/IFU execution where
OCAH drives a synthetic VIP/proxy path.

Example:

```text
OCAH intent: CPU IFU/LSU alias-remap route check.
OSS representative: sep_cpu_ifu_lsu_alias_remap_matrix_test.
Outcome: COVERED_STRONGER.
Reason: OSS boots real EL2 firmware and executes through the IFU alias remap;
OCAH drives synthetic VIP/proxy traffic.
```

## Selection Gate

Before adding a new OSS testcase to the VPLAN or GitHub tracker, answer these
questions at subsystem level:

1. Which subsystem coverage intent is missing or weak?
2. Which IPs, interconnect edges, interrupts/resets, security states, and error
   paths are involved?
3. Which OCAH tests/checkers map to this intent?
4. Can those OCAH intents be covered by strengthening an existing OSS test?
5. If not, can several OCAH tests be merged into one new OSS representative?
6. If still not merged, why does this need a separate test?
7. Which run mode is required: `cpu` (VeeR EL2 firmware boot) or `no_cpu` (host
   AXI on the CPU-LSU splice)? These are the only two run modes. A test that
   drives the inbound filter / security boundary is a `no_cpu` test that *adds*
   the external SMN-inbound master (`../AGENTS.md` §3) — that master is an add-on
   within `no_cpu`, not a third run mode.
8. Does this need real fuse sense? Default to `+skip_fuse_sense` unless the
   checking depends on sensed OTP data, LC_STATE shadowing, resense, or an
   eFuse→consumer stitch (LCC/KM) — then omit it and use the real eFuse responder
   (`../AGENTS.md` §4 / §9.1).
9. What exact positive evidence must appear in the log?
10. What OCAH proxy/backdoor/licensed behavior is replaced, excluded, or stronger
   in OSS?
11. Does this PyUVM-side representative need a config object as the single source
   of truth for DUT programming and checker/golden expectations?
12. What reusable DV infrastructure should be built first?
13. Which existing `.toml` bucket owns it?

If the answers show overlap with an existing OSS representative, update that test
or its checker list instead of creating another narrow test.

## No-Overlap Rule

No-overlap is a guard against *true duplicates*, not a cap on coverage (see
"Phase Context and Objective" — in Phase 2, completeness wins over compression).
New VPLAN work starts from the current baseline (the live `all.toml` "all" group;
31 tests at the close of Phase 1) and preserves a **no-overlap** mindset:

- Do not add a testcase only because OCAH has a testcase with that name.
- Do not add a testcase if an existing OSS representative already proves the same
  checker contract.
- Do not add a testcase if the missing intent can be covered by adding a checker,
  config point, or constrained-random point to an existing representative without
  hurting debug/runtime.
- If overlap is intentional, document the incremental coverage that justifies it:
  different run mode, fuse mode, owner, negative/security behavior, KAT/golden,
  or failure-isolation reason.

Overlap is allowed only when it buys clear coverage or debug value. Otherwise it
is testcase bloat.

## Randomized Representative Rule

Constrained randomization is a strong OSS compression tool when used carefully.
A single randomized PyUVM representative may replace many OCAH directed tests
when all are true:

- The random domain is constrained to legal, meaningful values.
- The seed and resolved choices are logged.
- The same config object feeds DUT programming and golden/checker expectations.
- Every sampled point has exact expected behavior, not just "no crash".
- Negative/error/security choices specify exact expected responses.
- The test remains debuggable: a failing seed can be reproduced directly.

Use randomized representatives for matrix-like spaces such as legal address
ranges, permission cells, lifecycle/config states, masks, timing choices, and
small feature permutations. Keep directed tests for security-critical KATs,
long-running firmware/entropy flows, one-off integration paths, or when a random
failure would be hard to triage.

Do **not** call a randomized test audit-green unless the kept log shows:

- the seed and resolved config values,
- the required deterministic coverage cells or fixed anchors,
- one positive evidence line per checker,
- no unproven checker boxes, and
- VCS/Xcelium vs Verilator status stated correctly.

When an existing directed test is strengthened with constrained randomization,
the VPLAN detail and GitHub issue must both be updated with a `RANDOMIZATION` /
`Randomization Strategy` section that names the config object, legal randomized
knobs, fixed checker contract, resolved VCS seed/config, and accepted deltas. Keep
the GitHub Project item **In progress** for VCS/Xcelium-only evidence; only a kept
Verilator PASS with the same positive checker evidence can move it to **Done**.

**Seed-sweep infrastructure.** Constrained randomization assumes you can run a
test across multiple seeds without creating duplicate testlist entries. The
runlib regression scheduler assigns fresh random seeds per regression leaf, and a
testlist entry may set `reseed = N` to run that test under N fresh random seeds
in one regression invocation. Keep single-test debug deterministic with
`--stage sim --seed N`; do not commit cloned entries just to fake seed sweeps.
Every randomized representative must log the seed and resolved config for each
leaf so a failure can be reproduced with `--stage sim --seed N`.

## Combined-Per-Group Representative Rule

The second Phase-2 compression technique is the **combined-per-group test**: one
test that walks several *basic* features of one IP (or one tight subsystem group)
in sequence, instead of one test per feature. This is the breadth workhorse for
Phase 2 — a `sep_<ip>_basic_test` that proves an IP's smoke + common modes +
CSR/status sanity in one boot usually fills a ledger row-cluster better than five
micro-tests. Use it when all are true:

- The features share one run mode and one fuse-sense policy.
- Each feature gets its **own positive-evidence line** (`CHK-<feature> PASS …`)
  so the log stays per-feature auditable and a failure names the exact feature.
- A failure in one feature does not mask the others (independent sub-checks, not
  one pass/fail at the end).
- The combined runtime stays reasonable (see "Runtime And Regression Balance").

Stop combining before it becomes a hard-to-triage mega-test (see "Merge And
Shrink Rules"); when a feature has a distinct failure domain or a heavy golden,
keep it separate.

## Planning Pass Deliverables

Each subsystem planning sweep must leave behind enough written evidence for the
next person to understand the decision without redoing the whole OCAH read. At
minimum, record:

- OCAH tests/sequences/docs reviewed.
- Coverage intents found.
- Existing OSS tests that already cover or partially cover the intent.
- Proposed OSS representative test(s).
- OCAH intents marked `COVERED_BY`, `COVERED_STRONGER`, `MERGED_INTO`,
  `OSS_DELTA_ACCEPTED`, or `GAP`.
- Required detailed-VPLAN checker boxes.
- Required DV infrastructure, scoreboards, goldens, agents, responders, firmware,
  or probes.
- Required PyUVM config object, if the representative has programmable policy,
  randomization, matrix points, or golden/scoreboard parameters.
- Expected run mode, fuse mode, and rough runtime class: short, medium, or long.
- Main risk: licensed dependency, missing frontdoor path, runtime, checker/golden
  complexity, or unclear spec.

## Coverage Accounting Rule

Do not claim subsystem maturity from testcase count. Claim it from coverage
accounting plus kept-log evidence.

For each subsystem group, track whether the OSS VPLAN has:

- Smoke or CSR/status sanity.
- Real datapath or firmware integration.
- Negative/error/status-clear proof.
- Interrupt/reset/security-state proof when applicable.
- Cross-subsystem proof when the subsystem participates in a fabric/security edge.
- Remaining `GAP` items and accepted deltas.

The **Basic-Feature Coverage Ledger** is the instrument for this accounting — it
is where the per-IP basic-feature denominator/numerator lives. In Phase 2 the
smoke/CSR, datapath, and cross-subsystem axes are the in-scope numerator; the
advanced negative/error/status-clear and security-state axes are tracked as
ledger GAPs for the later phase, while basic access-control and any observed
status-clear contract stay in scope. Use this accounting (not a raw test count)
to discuss basic-function maturity; a count is regression size, not coverage.

## No-Coding Gate

A representative test is not ready for implementation until the VPLAN detail has:

- Subsystem owner.
- Owning `.toml` bucket.
- The basic-feature ledger GAP(s) this test closes (what it adds to the numerator).
- At least one OCAH reference in `OCAH-REFS` plus the coverage intent (the **OCAH
  Provenance Gate** — an empty `OCAH-REFS` rejects the test, infra-smoke excepted).
- Mapping outcome (`COVERED_BY`, `COVERED_STRONGER`, `MERGED_INTO`,
  `OSS_DELTA_ACCEPTED`, or `GAP`).
- Detailed checker boxes.
- Run mode and fuse mode.
- Config-object owner for PyUVM-side programmable policy, or a note that the test
  is fixed/simple or firmware-owned and does not need one.
- Required DV infrastructure.
- Accepted deltas or stronger-than-OCAH notes.

If these are missing, continue VPLAN work instead of starting code.

## Priority Ranking

When choosing between possible representatives, prefer higher coverage density:

1. Cross-subsystem datapath or security-critical integration.
2. Security boundary, lifecycle, filter, privilege, or access-control behavior.
3. Interrupt/reset/error/status-clear behavior.
4. Real CPU firmware path over proxy path when feasible.
5. Standalone IP datapath or KAT.
6. CSR/status smoke.
7. Duplicated permutations and corner cases.

Do not spend early OSS capacity on duplicated permutations while a subsystem lacks
basic datapath, negative/error, or cross-subsystem coverage.

**Phase-2 override.** The ranking above is the all-phases default. In Phase 2
(basic breadth, see "Phase Context and Objective") the dominant tie-breaker is
**an uncovered IP's basic feature beats any depth on an already-basic-covered
IP**: rank (1) any IP with no basic coverage at all, (2) basic datapath/mode/CSR
breadth for partially-covered IPs, (3) the basic cross-subsystem happy path. The
advanced security-permutation / negative / error-injection rankings move to the
*front* in the later corner-case phase, not now. Basic security gates and
status-clear checks that define the Phase-2 feature remain in scope.

## GAP And Waiver Rule

Every `GAP` needs an explicit disposition:

- Future OSS representative test.
- `OSS_DELTA_ACCEPTED` with reason.
- Blocked by licensed/internal-only dependency.
- Blocked by missing frontdoor path or missing DV infrastructure.
- Deferred corner/permutation beyond current basic-function goal.

Do not leave a `GAP` as an ambiguous note. Ambiguous gaps become accidental
coverage holes.

## Runtime And Regression Balance

Estimate runtime during VPLAN creation:

- **Short**: smoke/CSR/simple no-CPU or small firmware test.
- **Medium**: firmware datapath, DMA/peripheral, or modest scoreboard test.
- **Long**: KM firmware, OTBN, entropy/DRBG, crypto KAT, or heavy scoreboard test.

Long tests need stronger justification and should not absorb many unrelated
checkers. Merging is good only while failure triage and log evidence remain clear.
Avoid creating a giant mega-test that is hard to debug, slow to iterate, or
unclear about which checker failed.

## Maturity Claim Rule

Do not claim "75%" or any other maturity number from testcase count alone. A
maturity claim must cite:

- Subsystem coverage accounting (the basic-feature ledger).
- Which representative tests are proven by kept logs.
- Which checker boxes are still open.
- Which `GAP` and `OSS_DELTA_ACCEPTED` items remain.
- Whether evidence is VCS/Xcelium-only or Verilator-confirmed.

## PyUVM Config-Object Planning Rule

During VPLAN creation, decide whether each PyUVM-side representative needs a
config object. Use one when the test has programmable policy: modes, masks,
address ranges, LC states, timing, randomization, matrix points, or golden /
scoreboard parameters.

If a config object is required, the VPLAN detail must identify it as the single
source of truth for:

- DUT programming sequences.
- Golden/checker/scoreboard expectations.
- Randomized or selected legal values.
- Positive-evidence logging.

The entropy flow is the model: one `SepEntropyCfg` configures the ESRC sequence
and the DRBG scoreboard golden. Do not require this for fixed/simple PyUVM smoke
tests, and do not duplicate firmware-owned policy into Python for CPU firmware
tests.

## Detailed VPLAN Checker Boxes

Every selected OSS testcase must have explicit checker boxes in the detailed
VPLAN entry (`SEP_OSS_VPLAN_PHASE2_DETAIL.txt`) before implementation. These checkboxes
are the quality contract for the test. They define what the test must prove, what
the log must show, and what GitHub issue checkboxes should mirror.

Checker boxes are not status notes. They are coverage and quality requirements.
Write them as concrete, auditable proofs:

```text
CHECKERS:
- [ ] CHK-CSR: <exact CSR/status/data condition to prove>
- [ ] CHK-DATA: <exact data/golden/readback comparison>
- [ ] CHK-NEG: <exact blocked/error/DECERR/timeout-fail behavior>
- [ ] CHK-RW1C: <status observed -> W1C clear -> readback 0>
- [ ] CHK-NONVAC: <why the test cannot pass through a dummy/default path>
```

Rules for checker boxes:

- Each box must map to a unique coverage intent. Do not create vague boxes such
  as "test passes" or "feature works".
- Each box must name the expected evidence style: `CHK-* PASS`, exact value
  compare, scoreboard summary, firmware PASS text naming the contract, or
  specific response/status proof.
- Every status/interrupt checker that observes a sticky or RW1C bit must include
  the clear/readback proof.
- Every negative/security-boundary checker must specify the exact expected
  response (`DECERR`, `OKAY`, `SLVERR`, blocked read data, etc.); timeout is not
  accepted unless the contract explicitly says timeout is the expected behavior.
- Every merged OSS representative must include boxes for every OCAH checker it
  claims to cover or strengthen. Merging tests must not merge away evidence.
- A checkbox may be marked `[x]` only after a kept log proves that exact item.
  VCS/Xcelium evidence may make the VPLAN/GitHub audit green for development;
  Verilator evidence is still required for final Done.

During VPLAN creation, the detailed checker boxes are more important than the
testcase name. A small number of strong boxes on one representative test is
better than many overlapping tests with weak or invisible proof.

## Merge And Shrink Rules

Merge OCAH tests into one OSS representative when all are true:

- They target the same IP/block contract or adjacent status/error facets.
- They can share one run mode and one fuse-sense policy.
- One log can provide clear named evidence for every merged checker.
- The combined runtime remains reasonable.
- A failure can still be debugged without hiding which contract broke.

Keep tests separate when any are true:

- Different owners must drive the DUT: `cpu` firmware vs `no_cpu` host (the
  external SMN-inbound master is an add-on *within* `no_cpu`, not a third owner).
- One test needs real OTP/eFuse sense and another should use `+skip_fuse_sense`.
- A KAT or golden model has long runtime or heavyweight setup.
- The checker failure domains are unrelated enough that merging would obscure
  triage.
- A unique negative/security boundary would become only a side effect.

Shrink tests when OCAH repeats the same mechanism with many values, but keep
enough points to prove the contract. Shrinking is allowed for sim-time and
overlap reduction; it is not allowed to remove the only proof of a feature.

## Checker Standard

An OSS representative test is only useful if it proves more than activity:

- Use exact data, digest, response, status, or count comparisons.
- Prove RW1C/status-clear behavior for interrupt/status paths.
- Fail on timeout; never discard bounded-wait results.
- Log one positive evidence line per checker (`CHK-* PASS`, scoreboard summary,
  firmware PASS text naming the contract, or exact value compare).
- Make non-vacuity explicit when possible: prove the stimulus could not pass by
  reading a dummy/default path.
- If OCAH is weaker and a stronger OSS proof is feasible, require the stronger
  proof and document it as `COVERED_STRONGER`.
- **Infra-feasibility:** a planned checker must be producible by existing DV infra,
  or be explicitly marked **new-infra / prove-first** in the card. Do not claim
  evidence the scoreboard/monitor cannot generate — e.g. do not promise bit-exact
  per-sink genbits when the scoreboard only supports membership for multiple
  concurrent sinks; downgrade to membership + KAT + real-beats and defer the
  bit-exact form as new infra.
- **Name the real register for any clear/RW1C checker.** An RW1C/status-clear
  checker must name the actual sticky source CSR being cleared — an aggregate
  interrupt wire (e.g. `sep_internal_interrupts[N]`) is *not* a register. If the
  source is pulse-only with no sticky CSR, the checker is "asserts for the event,
  deasserts after it completes," not W1C; pin which from the reg map (prove-first).

Do not mark a VPLAN/GitHub checkbox until a kept log proves that exact checker.

## DV Infrastructure Standard

Build shared infrastructure before adding repeated tests:

- Sequences own protocol stimulus and register constants.
- Base-test helpers own common bring-up, polling, and reusable checks.
- Env modules own scoreboards, monitors, agents, goldens, and responders.
- Concrete tests read like scenario steps, not raw repeated register scripts.
- New probes/backdoors are not allowed unless explicitly signed off in `AGENTS.md`.

If the second test needs similar staging, polling, responder access, scoreboard
logic, or golden comparison, move the common code to the proper layer before
copying it.

## Required Mapping Artifact

For each new or reshaped OSS testcase, update the VPLAN/detail/tracker with a
short mapping block:

```text
OCAH refs (pin the version — OCAH is the 100% reference and a moving target):
- <test/seq/doc path> @ <git SHA or date>: <relevant checker intent>

OSS representative:
- <oss_test_name>: <what it proves>

Mapping:
- COVERED_BY / COVERED_STRONGER / MERGED_INTO / OSS_DELTA_ACCEPTED / GAP

Why separate or merged:
- <run mode, fuse mode, runtime, debug, or coverage reason>

Evidence required:
- CHK-...
```

This mapping is the source of truth for deciding whether the OSS suite needs a
new testcase or should strengthen an existing representative. Record the OCAH
ref's git SHA/date so a later auditor knows the baseline; re-read and re-check the
OCAH test+sequence (`git log`) before claiming parity and again before merge — the
OCAH reference can change after the initial scope read (`../AGENTS.md` §9).

## Detailed VPLAN Entry Template

Use this shape for new or substantially rewritten entries in
`SEP_OSS_VPLAN_PHASE2_DETAIL.txt`. Keep entries concise, but do not omit the fields that
decide whether the test is ready for implementation.

```text
--------------------------------------------------------------------------------
#NN <oss_test_name>                                      <subsystem> · <type>
--------------------------------------------------------------------------------
SUBSYSTEM : <one VPLAN subsystem group>
LEDGER    : <IP + the basic-feature ledger GAP(s) this entry closes>
OCAH-REFS : <OCAH test/sequence/doc paths + testcase IDs @ git SHA/date>
MAPPING   : <COVERED_BY / COVERED_STRONGER / MERGED_INTO /
             OSS_DELTA_ACCEPTED / GAP, with one-line reason>
TOML      : <owning *.toml bucket; primary coverage intent wins over run-mode/owner>
RUN-MODE  : <cpu | no_cpu (+ external SMN-inbound master add-on if inbound-filter)>
FUSE-MODE : <real fuse sense, or +skip_fuse_sense (the default unless checking
             depends on sensed OTP/LC_STATE/resense/eFuse->consumer stitch)>
SUMMARY   : <what representative OSS behavior proves>
DATA-PATH : <frontdoor path through DUT blocks/IPs>
STEPS     : 1) <step>
            2) <step>
CHECKERS  :
- [ ] CHK-...: <exact proof required in the kept log>
- [ ] CHK-...: <exact proof required in the kept log>
COVERAGE  : <subsystem/IP/edge coverage intents>
DV-INFRA  : <needed/built helpers, agents, scoreboards, goldens, responders, fw>
RUNTIME   : <short / medium / long; reason if medium/long>
RISKS     : <licensed dependency, missing frontdoor, runtime, golden complexity, etc.>
DELTAS    : <stronger-than-OCAH and accepted OSS deltas>
STATUS    : <planned / implemented / VCS dev green / Verilator done>
```

The `CHECKERS` block is the most important part. It must be detailed enough that
a future auditor can match each checkbox to a positive line or summary in a kept
log without guessing.

## Planning Heuristic

For each subsystem group, aim for a compact basic-function set while tracking the
important IPs inside that subsystem:

1. One smoke or CSR/status sanity path.
2. One real datapath or firmware integration path.
3. One negative/error/status-clear path.
4. One cross-subsystem path when the IP participates in security or fabric edges.

Do not fill every OCAH corner-case permutation before the basic subsystem map is
covered.
When in doubt, choose the test that covers the widest real datapath with the
fewest OSS-specific shims.
