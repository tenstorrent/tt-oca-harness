# SMU OCAH Open-Source Functional Coverage Plan

## Overview

This document defines functional coverage intent for the OCAH open-source SMU
testbench. It mirrors the coverage categories from the working reference plans in
`dv/smu/tb/doc/`, adapted for the public cocotb/Verilator flow.

Verilator does not compile SystemVerilog `covergroup`, `coverpoint`, or `cross`.
The OCAH open-source path therefore uses Python-side coverage/observation counters
in the cocotb environment for public CI, while SV covergroups, assertion coverage,
and full code coverage are collected with commercial simulators.

| Field | Value |
|-------|-------|
| Reference SPEC | `SMU_SPEC.md` |
| Reference VPLAN | `SMU_VPLAN.md` |
| Reference CSR | `SMU_CSR.md` |
| Skill-1 feature list | `SMU_FEATURE_LIST.md` |
| Python ledger | `cocotb/env/smu_fcov.py` |
| Open-source framework | Hybrid UVM + cocotb + firmware |
| Open-source simulator | Verilator (+ VCS for signoff gate) |
| Pinned config | **SEP=0** (SEP=1 / interop bins = OUT) |

## Coverage Goals

| Metric | Target | Open-Source Collection Path |
|--------|--------|-----------------------------|
| Functional coverage | 100% of **P1+P2+P3+P4 SEP=0** scenario intent | Python counters in `cocotb/env/smu_fcov.py` |
| Line/branch/FSM/condition | Collected for signoff in commercial flow | VCS/Xcelium coverage databases |
| Toggle coverage | 95% target in commercial flow | VCS/Xcelium coverage databases |
| Assertion coverage | 100% of enabled assertions | Commercial flow |

## Coverage Summary (SEP=0 P1+P2+P3+P4)

| Category | Covergroup | Collection Notes | Scope |
|----------|------------|------------------|-------|
| SMC boot | `smc_boot_cg` | cold/primary bring-up | P1 |
| AXI crossbar routing | `xbar_route_cg` | SEP=0 ports, DECERR, filter OKAY/edge/shrink | P1–P3 |
| Register-access source | `reg_access_cg` | JTAG2AXI fabric/OTP, hier CTN, SMN, G4 race | P1–P3 |
| Reset / clock | `reset_clock_cg` | IC_RESET (incl. dual_pack), boot-stall, CLA/JTAG stop OR | P1–P3 |
| Fuse / lifecycle | `fuse_lifecycle_cg` | `0xf0` LC, feat_ctrl allow/deny/mid_op | P1–P3 |
| DTP debug | `dtp_debug_cg` | JTAG2AXI rw/error/wstrb/b2b/abort, OTP, CSR | P1–P3 |
| Cross-trigger | `xtrig_cg` | remap, four-phase, illegal, CLA concurrent | P1–P3 |
| WDT | `wdt_cg` | WDOGIP0 + isolate clamp + scratch domain + double_pulse | P2–P4 |
| P4 glue | `glue_p4_cg` | macro AXIL, OCTS, SS IC_RESET, EXTEST, ATB, secure_tm | P4 |
| SEP boot / mailbox / interop | `sep_boot_cg`, `mailbox_interop_cg`, `interop_bins_cg` | — | **OUT** |

## Coverage Definitions (active)

### `smc_boot_cg`
| Coverpoint | Bins |
|------------|------|
| bringup | `cold_primary_release` |

### `xbar_route_cg`
| Coverpoint | Bins |
|------------|------|
| sep0_path | `smc_ext`, `ext_smc`, `decerr`, `id_width`, `atop_reject`, `remap` |
| filter | `inbound_program_okay`, `outside_still_decerr`, `page_edge`, `reprogram_shrink`, `config_clear_deny` |

### `reg_access_cg`
| Coverpoint | Bins |
|------------|------|
| path | `jtag2axi_fabric`, `jtag2axi_otp`, `hier_ctn`, `smn` |
| outcome | `success`, `decerr_poison`, `gated_deny` |
| race | `j2a_vs_smn`, `otp_vs_fabric`, `ctn_vs_j2a` |

### `reset_clock_cg`
| Coverpoint | Bins |
|------------|------|
| ic_reset | `ext`, `smc_fuse`, `smc_warm`, `smc_cool`, `smc_cold`, `dual_pack` |
| boot_stall | `sticky_cold`, `trst_clear`, `reassert_sticky` |
| clock_stop | `jtag`, `cla_loop`, `jtag_or_cla` |

### `fuse_lifecycle_cg`
| Coverpoint | Bins |
|------------|------|
| lc_state | `sep0_0xf0` |
| feat_ctrl | `fabric_allow`, `fabric_deny`, `otp_allow`, `otp_deny`, `net_golden`, `mid_op_gate` |

### `dtp_debug_cg`
| Coverpoint | Bins |
|------------|------|
| jtag2axi | `rw_matrix`, `error_path`, `security_gate`, `wstrb_neighbor`, `error_b2b`, `abort_mid` |
| otp | `map_complete`, `sep0_err_slv`, `partial_feat_deny` |
| csr | `abs_hole`, `hier_ctn`, `cross_domain` |

### `xtrig_cg`
| Coverpoint | Bins |
|------------|------|
| ctm | `remap_p1`, `four_phase`, `smc_glue_1_0`, `ack_hardwire_0`, `illegal_phase`, `smc_bits_clean` |
| cla | `clk_stop_fb`, `concurrent_ctm` |

### `wdt_cg`
| Coverpoint | Bins |
|------------|------|
| timeout | `wdogip0` |
| scratch | `cold_sticky`, `cold_warm_clear`, `double_pulse` |

## VPLAN / Test → FCOV Traceability (P2)

| Test | FCOV bins (auto via `TEST_FCOV_HITS`) |
|------|----------------------------------------|
| `smu_sys_in_filter_program_jtag_test` | `xbar_route_cg.filter.*` |
| `smu_dtp_jtag2axi_smc_rw_matrix_test` | `dtp_debug_cg.jtag2axi.rw_matrix` |
| `smu_dtp_jtag2axi_smc_error_path_test` | `…error_path`, `reg_access_cg.outcome.decerr_poison` |
| `smu_dtp_otp_smc_complete_rw_test` | `dtp_debug_cg.otp.map_complete` |
| `smu_dtp_otp_sep0_err_slv_test` | `…otp.sep0_err_slv` |
| `smu_boot_stall_jtag_cold_reset_matrix_test` | `reset_clock_cg.boot_stall.*` |
| `smu_ic_reset_smc_multi_domain_test` | `reset_clock_cg.ic_reset.smc_*` |
| `smu_dtp_clock_stop_smc_cla_loop_test` | `…clock_stop.cla_loop`, `xtrig_cg.cla` |
| `smu_xtrig_ctm_four_phase_test` | `xtrig_cg.ctm.four_phase` |
| `smu_dtp_xtrigger_smc_cla_test` | `…smc_glue_1_0`, `ack_hardwire_0` |
| `smu_dtp_csr_access_test` | `dtp_debug_cg.csr.abs_hole/hier_ctn` |
| `smu_fabric_smc_dtp_cross_domain_test` | `…csr.cross_domain` |
| `smu_dtp_feat_ctrl_gate_matrix_test` | `fuse_lifecycle_cg.feat_ctrl.*` |
| `smc_wdt_timeout_irq_test` | `wdt_cg.timeout.wdogip0` |
| `smc_reset_unit_wdt_scratch_test` | `wdt_cg.scratch.*` |

Full map: `cocotb/env/smu_fcov.py` (`TEST_FCOV_HITS`) — includes all **16** P3 corner tests.

Skill-1 CHK ↔ FEATURE: `SMU_FEATURE_LIST.md`. `SmuScoreboard.expect_*` logs one
check token per named check (log line format `EVIDENCE: <TOKEN>`).

## Collection Strategy

| Flow | Strategy |
|------|----------|
| Verilator / VCS open-source CI | `SmuFcov` auto-hit per test name + optional `fcov=` on checks |
| Commercial simulation | SV covergroups under commercial-only filelist or `ifndef VERILATOR` |
| Code coverage | VCS/Xcelium line/branch/condition/FSM/toggle/assertion |
| Closure triage | Directed tests for reachable holes; waiver/UNR for structural OUT |

Python-side sampling: end of `run_scenario` auto-hits + scoreboard `check_phase`
summary (`FCOV hits:` lines).

## Coverage Gaps and BLOCKED Items

### Functional coverage gaps (RTL present, no dedicated P1/P2 anchor)
| Item | Note |
|------|------|
| AP / STEE output remap | No dedicated anchor (OUT of P1/P2 density) |
| SEP inbound/outbound filters | SEP=1 OUT |
| SPI mux switching | Detail uncovered |
| IC_RESET SEP + external slices | Partial (`ext` bin reserved) |
| SEP WDT CDC | SEP=1 OUT |

### BLOCKED — RTL integration incomplete
| Item | Note |
|------|------|
| SEP timeout CSRs | unused |
| CTP GPIO pad routing | Tied off (ISSUE-2) |
| Cross-trigger pad ↔ DTP GPIO | TODO wiring |
| External TRNG / entropy | Unwired |
| `ndmreset_request_i` | Not driven |
| Top-level `gpio_interrupts_o` | Undriven |

## Exclusions and Limitations

| Item | Reason |
|------|--------|
| SV covergroups in Verilator | Unsupported |
| SEP=1 / mailbox / interop bins | Program OUT until SEP=1 TB |
| CSR bins for BLOCKED items | Unavailable |
| Static parameters (`SEP`, `Cfg`) | Compile-time |

## Revision History

| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0 | 2026-07-07 | OSS DV Team | Initial OCAH open-source SMU FCOV plan |
| 1.1 | 2026-07-15 | OSS DV Team | SEP=0 P1+P2 bins; Python `smu_fcov.py`; Skill-1 link; OUT SEP/interop |
| 1.2 | 2026-07-17 | OSS DV Team | SEP=0 P3 bins (filter edge, race, abort/mid-op, dual IC_RESET, WDT double) |
| 1.3 | 2026-07-20 | OSS DV Team | SEP=0 P4 `glue_p4_cg` + WDT isolate clamp bins |
| 1.4 | 2026-07-20 | OSS DV Team | Drop false `smc_cold` hit from SS IC_RESET test |
