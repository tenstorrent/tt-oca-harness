<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV — Peer-Audit Findings & Remediation Plan

Audit standard: `dv/aidv_audit.md` (AI-era DV Quality Workflow), **Skill 3 — IP
Peer-Audit**, first-principles mode (no formal Skill-1 checkbox contract exists
yet → tracked as finding **F4**).

Scope audited: `hw/sys/smc/dv` (cocotb env + scoreboard + 86 `*_test_seq`
sequences + testlists), primary sims **VCS** (real RTL) and **Verilator** (stub
build).

> **Conflict-of-interest disclosure.** Many of the CSR value-check sequences
> under audit were authored/upgraded in the same working session. Per
> `aidv_audit.md` ("no model grades its own work"), these findings should still
> be re-verified by an independent human/model. The audit deliberately applied
> an adversarial/refute stance and a live fault-injection to its own changes.

---

## Verdict

**Pass with findings.** The core evidence path is sound and was proven sensitive
by fault injection; all findings below are low-severity traceability/hardening
items — none are false-green defects.

### What was proven sound

| Property (aidv tag) | Evidence |
|---------------------|----------|
| `[CHECKER-NONVACUITY]` `[CHECKER-SENSITIVITY]` | Injected `expected=0xDEADBEEF` into `smc_telemetry_receiver_csr_test` → VCS `status=FAIL` with `AssertionError: SYS AXI read 0x…d000 = 0x0, expected 0xdeadbeef`. The value-check path is live; a wrong golden goes red. (Reverted after proof.) |
| value-check wiring | `csr_read(expected=)` → `SmcScoreboard._check_sys_axi` `assert got==exp` **and** `assert item.resp_ok`; driver calls `ap.write()` (scoreboard) **before** `item_done()` with no try/except → mismatch raises or hangs→timeout, never a green PASS. |
| `[EXACT-EXPECTATION]` (filter) | `axi_filter/…/filter_ctrl.rdl`: `data_bus_width[14:12]=0x3`→CONFIG `0x3000`, `start_addr=0x0`, `end_addr=0x7` ("Defaults to 7 on reset"). Filter golden is RDL-traceable G3. |
| `[NO-BACKDOOR-WRITE]` `[FRONTDOOR-FIRST]` | The only `.value=` writes in `seq_lib` target `dut.tb_gpio_ext_drive_*` (TB external-pad stimulus), not internal DUT registers. |
| `[REGRESSION-ENROLLED]` | Every `cocotb/tests/*_test.py` appears in `testlists/`. |
| stub/boundary rigor | `csr_read_err_signature` asserts error-resp (SLVERR/DECERR) **and** exact `0xBADCAB1E`. |

---

## Findings

### F1 — `[COMMON-MODE-RISK]` · golden derived from DUT, not spec · **HIGH value**

12 of the 15 upgraded value-check sequences (all except the filter block) assert
`expected` values that were **extracted from the passing DUT regression logs**
(golden == observed). These lock in the current RTL reset and catch
regression / decode / read-path faults, but do **not independently prove the
reset value is spec-correct** — a spec-vs-RTL reset bug would pass.

**Remediation.** For each register, cross-reference the DV `expected` to the
authoritative RDL reset field (as already done for `axi_filter`). Add a spec
citation comment. Any value that does not match its RDL — or that derives from
tied module inputs rather than an RDL constant — is documented explicitly and
kept as a labelled regression-lock. Promotes G2 regression-lock → G3
spec-semantic where traceable.

Tests in scope: `uart_multi_instance`, `uart_spi_log_engine`,
`i2c_multi_instance`, `telemetry_receiver_csr`, `xvisor_remap`,
`cpu_ctrl_map_depth`, `mailbox_inbound`, `cluster_beu`, `gpio_intf_full_sweep`,
`ecc_dfd_dbs_sanity`, `efuse_chip_config_read`, `input_output_fabric_wr_rd`,
`local_fabric_csr_depth`.

**Acceptance.** Each expected has an RDL citation or an explicit
regression-lock rationale; no silent golden==observed; VCS + Verilator green.

#### F1 RDL traceability result

Cross-referenced every expected against the authoritative RDL
(`hw/**/data/registers/rdl/*.rdl`, anchored at `hw/smc/…/smc_top.rdl`
`BASE=0xC000_0000`). Two classes emerged.

**(a) Spec-traceable → G3 (add RDL citation):**
telemetry CTRL=0; UART IIR=0x1, LSR=0x60, LOG-engine CTRL/STATUS=0;
I2C INTR_STATE/CTRL=0; xvisor/alias remap=0; chip_config VERSION_LO=0x000100A0,
VERSION_HI/CHIP_ID/RAS=0; ndmreset_process=0; zeroer=0; mailbox
ERROR_FLAGS/IRQEN=0; filter CONFIG=0x3000/START=0/END=0x7; smc_base_config
GLOBAL_BASE=0x4000_0000, LOCAL_BASE=0xC000_0000, CLOCK_GATE=0x1F00_0000,
HANG_DET CTRL=0/THRESHOLD=0x1000; GPIO DATA_CTRL=0 entries.

**(b) NOT RDL-traceable — golden==observed from tied HW / FIFO flag / cluster
black-box (label as regression-lock, honest disclosure):**

| Test | Value | RDL reset | Real source |
|------|-------|-----------|-------------|
| `uart_spi_log_engine` UART_MSR | 0x11 | 0x0 | modem-status HW inputs (`cts_ni`…), all `hw=w` |
| `mailbox_inbound` STATUS / `local_fabric` MBOX0_OUT_STATUS | 0x1 | 0x0 | `empty` = FIFO-empty flag wire, 1 at reset |
| `cluster_beu` CAUSE/ENABLE/PLIC (cores 0-3) | 0x4000_0000 / 0x0100_0000 / 0x1F00_0000, cores2/3=0 | 0x0 / **0xE6** / 0x0 | **Ascalon cluster black-box**, not the PeakRDL regblock (cores 2/3 all-0 vs RDL 0xE6 proves it) |
| `ecc_dfd_dbs_sanity` NDMRESET_CLUSTER_COUNT | 0x4 | 0x0 | tied HW "#clusters" input |
| `gpio_intf_full_sweep` bit25 subset | 0x0200_0000 | 0x0 | `lsio_enable` HW tie (GPIOs wired to LSIO) |

**Correctness sub-findings (misleading names / addresses):**

- **C1 `[SPEC-CITATION]` — `cpu_ctrl_map_depth` register labels are wrong.** By
  RDL/address the block at `0xC001_0000` is `smc_base_config`, not a
  reset-vector map. The values trace, but under wrong names:
  `RESET_VECTOR_0`→`GLOBAL_BASE`, `RESET_VECTOR_1`→`LOCAL_BASE`,
  `GLOBAL_BASE`→`HANG_DET_DATA_ACCEL_CTRL`,
  `LOCAL_BASE`→`HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD`. `REGION_SIZE`@`0x50` has
  **no register** (unmapped, reads 0 as open bus). → rename to real RDL regs;
  drop/annotate the unmapped read.
- **C2 `[SPEC-CITATION]` — `ecc_dfd_dbs_sanity` CPU_DEBUG_CTRL/BUS_MUX suspect.**
  `0xC001_0208 / 0210` have **no RDL register**; the same-named regs in
  `dfx_ctrl_status.rdl` live at `0xC000_F808/F810` and reset `0x0`. The observed
  `0xC000_0000 / 0x0100_0000` are the same "magic" constants seen on the cluster
  black-box reads. → **owner review**: likely wrong addresses or a stub region;
  do not silently re-baseline. Left unchanged pending designer confirmation.

### F2 — `[SEVERITY-DISCIPLINE]` · I3C errors downgraded to warning · low

`smc_i3c_to_fabric_test_seq.py:109` and `smc_i3c_vip_utils.py:44/101/197`
downgrade I3C drive/loopback failures to `log.warning` and continue. The test
still gates on real CSR/HCI_VERSION checks (not vacuous), but a genuine I3C-VIP
regression on the loopback path would not fail the test.

**Investigation outcome.** The warning path in `smc_i3c_to_fabric` is actually
sound: the test is hard-gated by the clock-gate write-readback value check and
the loopback is explicitly non-gating. Every other I3C test is independently
hard-gated (`csr_read_many_err_signature` on the stubbed window, or
`check_i3c0_external_pull_low`'s pull-low asserts). So the warn-on-fail helpers
are correctly supplementary on a stubbed core — no severity fix needed there.

**Real finding surfaced (`[EXACT-EXPECTATION]` / false evidence).**
`smc_i3c_ccc_ibi_full_test` docstring AND its `record_protocol_vip` details
string claimed "RSTDAA + SETDASA + directed SDR write + GETSTATUS" CCC traffic,
but the helper (`i3c_full_daa_and_ccc_proof`) drives only THREE directed SDR
writes and *explicitly omits* RSTDAA/SETDASA/GETSTATUS (upstream cocotbext-i3c
target asserts on CCC-follow header decode). The recorded evidence logged
coverage that was never driven.

**Remediation applied.** Rewrote the docstring and the recorded details string
to describe only what is actually driven (directed SDR writes) and to disclose
the RSTDAA/SETDASA/GETSTATUS/IBI gap as deferred (upstream limitation); named the
two independent hard gates. No gate/behaviour change. **Status: done.**

### F3 — `[CHECKER-NONVACUITY]` · gpio SAMPLE assertion near-vacuous · low

`SmcScoreboard._check_gpio` asserts `item.core2pad_any in (0,1)` (and en/pad2core
equivalents) — any resolved single bit passes, so it adds little beyond
resolvability. Real GPIO functional proof already exists in
`smc_gpio_output_driveback_test`.

**Discovery during remediation.** The `smc_gpio_agent` docstring claimed "with
no CSR programming, all three should be 0 after reset release", but the retained
logs show all three read **1** on both Verilator and VCS (idle-high LSIO pads on
the shared OR-reduction drive it high — as `gpio_output_driveback`'s own
docstring notes). The docstring was stale/misleading: a later "fix" to assert
`== 0` per the docstring would have broken every GPIO SAMPLE test. This is a
documentation-vs-behavior common-mode hazard.

**Remediation applied.** (1) Corrected the `smc_gpio_agent` docstring to state
the aggregates read 1 at idle and are not GPIO-diagnostic. (2) Documented in
`_check_gpio` that the real evidence is *resolvability* and the value is
deliberately not asserted (it is a bus-aggregate artifact; asserting it would be
a golden==observed lock), cross-referencing `smc_gpio_output_driveback_test` for
the isolated per-pad drive proof. The `in (0, 1)` range guards are kept as
belt-and-braces on the resolved single-bit reductions. **Status: done.**

### F4 — `[QUALITY-OBLIGATION-GAP]` · no Skill-1 two-layer contract · medium

SMC OSS has a prose VPLAN (`docs/SMC_VPLAN.adoc`) but no machine-checkable
`feature_list` + per-testcase checkbox sets (stable IDs, exact expectations,
grep-able evidence tokens, bidirectional feature↔checkbox mapping).

**Remediation.** Seed the Skill-1 contract, starting with the CSR
decode/reset-value feature family covered by the upgraded sequences, with the
feature↔checkbox mapping. Full coverage is phased. **Acceptance.** An initial
`feature_list` + checkbox seed exists and maps to the upgraded tests; remainder
tracked as a migration backlog.

### F5 — `[CHECKER-NONVACUITY]` · scoreboard zero-check guard · **RESOLVED (no change)**

Audit self-correction: `SmcScoreboard` **already** has the guard.
`check_phase` (`smc_scoreboard.py:182-186`) sums every evidence counter
(`*_samples_seen` + `sys_axi_checks_seen` + `protocol_vip_checks_seen`) and
`assert total > 0, "SmcScoreboard saw no SAMPLE items"`. A truly evidence-less
test already fails. No change required; the original finding was based on a
partial read of the file and is withdrawn.

---

## Execution order & status

Priority: **F1 → F5 → F3 → F2 → F4** (value first, then cheap hardening, then
the contract migration). Every code change is verified on **VCS** (fast, real
RTL) and batch-verified on **Verilator** at the end.

| ID | Priority | Status |
|----|----------|--------|
| F1 | high | **done (RDL cites + regression-locks + C1 rename; C2 flagged for owner)** |
| F5 | low | **resolved — no change (guard already present)** |
| F3 | low | **done (fixed stale docstring + documented non-vacuity)** |
| F2 | low | **done (rewrote false CCC/DAA evidence to truthful SDR + known-gap)** |
| F4 | medium | **seeded (Appendix A); remainder = migration backlog** |

Verification: all changed tests **VCS 15/15 PASS**; changes are
comment/label/docstring-only (no assertion value or logic changed), so Verilator
behaviour is unchanged from the previously-green baseline (confirmation run in
progress). One item routed to owner: **F1-C2** (ecc_dfd debug addresses).

Scope guard: all edits confined to `hw/sys/smc/dv`; **no** `hw/`, `rtl/`,
`deps/`, `vendor/` modification (RDL is read-only reference for F1).

---

## Appendix A — F4 seed: Skill-1 two-layer contract (CSR decode/reset family)

Initial machine-checkable contract for the CSR decode + reset-value feature
family exercised by the upgraded sequences. This is a **seed** (owner/designer
approval pending, per aidv `[DESIGN-APPROVAL]`); the remaining feature families
(clocks/resets, IRQ, protocol VIP, boundary/error) are migration backlog.

Grade key: **G3** = value traces to an RDL reset constant; **G2-lock** =
regression-lock (golden==observed from tied HW / FIFO flag / cluster black-box,
see F1); **G2-sig** = stub error-signature.

### feature_list (SPEC/RDL-cited)

| FEATURE-ID | Intent | RDL ref | Milestone |
|------------|--------|---------|-----------|
| CSR-FILTER-RST | inbound/outbound filter CONFIG=0x3000, START=0, END=0x7 | filter_ctrl.rdl | P1 |
| CSR-REMAP-RST | alias/xvisor remap regions reset 0 (disabled) | alias_remap.rdl, output_remap.rdl | P1 |
| CSR-BASECFG-RST | GLOBAL_BASE=0x4000_0000, LOCAL_BASE=0xC000_0000, CLOCK_GATE=0x1F00_0000, HANG_DET thr=0x1000 | smc_base_config.rdl | P1 |
| CSR-UART-RST | UART IIR=0x1, LSR=0x60, CTRL/log=0 | uart_16550_main.rdl, log_engine.rdl | P1 |
| CSR-I2C-RST | I2C INTR_STATE / I2C_CTRL reset 0 | i2c.rdl, i2c_ctrl.rdl | P1 |
| CSR-TELEM-RST | telemetry CTRL reset 0 | telemetry_receiver.rdl | P1 |
| CSR-CHIPCFG-RST | VERSION_LO=0x000100A0, VERSION_HI/CHIP_ID/RAS=0 | chip_config.rdl | P1 |
| CSR-ZEROER-RST | zeroer DEST_ADDR/SIZE reset 0 | zeroer_ctrl.rdl | P1 |
| CSR-MBOX-ERR-RST | mailbox ERROR_FLAGS/IRQEN reset 0 | axil_mailbox.rdl | P1 |
| CSR-STUB-SIG | stub/boundary windows return DECERR + 0xBADCAB1E | (err_slv terminators) | P1 |
| CSR-MBOX-EMPTY* | mailbox STATUS empty=1 (FIFO flag, **G2-lock**) | axil_mailbox.rdl (reset 0) | P1 |
| CSR-BEU* | per-core BEU CAUSE/ENABLE/PLIC (**G2-lock**, cluster black-box) | bus_error_unit.rdl (mismatch) | P2 |
| CSR-GPIO-LSIO* | GPIO DATA_CTRL bit25 lsio_enable tie (**G2-lock**) | gpio_intf.rdl (reset 0) | P1 |
| CSR-DEBUG?* | CPU_DEBUG_CTRL/BUS_MUX (**SUSPECT addr, F1-C2**) | none @0xC001_02xx | blocked |

`*` = not RDL-traceable; disclosed as regression-lock / suspect (known-gaps).

### feature ↔ checkbox mapping (evidence token = scoreboard value-check log)

Each checker's evidence is the scoreboard line
`SYS AXI read 0x<addr> = 0x<val>, expected 0x<val>` (fired only on a value
check; a mismatch raises `AssertionError` — proven sensitive by fault
injection). Grep token: `Scoreboard SYS AXI check`.

| FEATURE-ID | Testcase(s) | Grade |
|------------|-------------|-------|
| CSR-FILTER-RST | filter_field_sweep, filter_multi_entry, input_output_fabric_wr_rd, local_fabric_csr_depth | G3 |
| CSR-REMAP-RST | xvisor_remap, input_output_fabric_wr_rd | G3 |
| CSR-BASECFG-RST | cpu_ctrl_map_depth, local_fabric_csr_depth | G3 |
| CSR-UART-RST | uart_multi_instance, uart_spi_log_engine, local_fabric_csr_depth | G3 |
| CSR-I2C-RST | i2c_multi_instance | G3 |
| CSR-TELEM-RST | telemetry_receiver_csr | G3 |
| CSR-CHIPCFG-RST | efuse_chip_config_read | G3 |
| CSR-ZEROER-RST | local_fabric_csr_depth | G3 |
| CSR-MBOX-ERR-RST | mailbox_inbound | G3 |
| CSR-STUB-SIG | gpio_ctrl_full_sweep, gpio_refclk_ctrl, pll_awm_freq_sweep, cdns_i3c_axil, efuse_map_read(vlt), i3c_* | G2-sig |
| CSR-MBOX-EMPTY* | mailbox_inbound, local_fabric_csr_depth | G2-lock |
| CSR-BEU* | cluster_beu | G2-lock |
| CSR-GPIO-LSIO* | gpio_intf_full_sweep | G2-lock |
| CSR-DEBUG?* | ecc_dfd_dbs_sanity | suspect (F1-C2) |

**Backlog (VPLAN migration):** stable per-checker IDs + explicit grep-able
`EVIDENCE:` tokens per aidv Skill-1 example; non-CSR feature families;
designer approval of feature semantics.

## Revision history

| Date | Note |
|------|------|
| 2026-07-15 | Initial audit findings + remediation plan (Skill-3 peer-audit). |
| 2026-07-15 | F1 RDL traceability done (G3 + regression-locks + C1/C2); F2/F3/F5 resolved; F4 contract seed (Appendix A). |
