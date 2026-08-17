# SMU OCAH Open-Source Testbench Architecture

## Overview

| Field | Value |
|-------|-------|
| DUT (core) | `smu` (`hw/smu/rtl/smu.sv`) |
| DUT (wrapper) | `smu_wrapper` (`hw/smu/smu_wrappers/rtl/smu_wrapper.sv`) |
| Repository | `tt-oca` |
| Project | OCAH |
| Framework | Hybrid UVM + cocotb + firmware |
| Primary simulator | Verilator (open-source path) |
| Commercial simulator use | Coverage, real SMC+SEP co-sim paths Verilator cannot elaborate today |
| Reference TB | `dv/smu/tb/tb_uvm` (working SMU/SMC-chiplet environment) and `dv/smu/tb/doc/` |

The OCAH open-source SMU testbench follows the canonical `hw/sys/<system>/dv/`
layout under `hw/sys/smu/dv/`. Unlike DTP (a single pure-cocotb PyUVM
flow), the SMU verifies a subsystem that co-simulates **real SMC RTL and real SEP
RTL** around the AXI crossbar, so its working reference environment is a hybrid
UVM + cocotb + firmware flow driven by `ttem` and YAML. This document describes
the public target architecture ported from that reference; the OSS bring-up grows
it incrementally, using unified OCAH BFM packages for standard interfaces.

> **Status (2026-07-29):** OSS SMU TB is live under `run_dv.py`.
> **Policy:** no DUT Force / no TB placeholder. Enrolled green =
> `phase1` 14 / `sep0_all` 19 on bare `--dut smu`; wrapper smoke is a
> separate merge-gate (`--dut smu_wrapper`). Force-era deepeners are
> raise-stubs under `cocotb/tests_deferred/` + `deferred.toml`.
> Cleanup: `hw/sys/smc/doc/dv_hack_cleanup_checklist.md`.
>
> Historical text below that still describes a `tb_top` placeholder or
> Force-based feat_ctrl bring-up is **superseded**.

## VIP Selection Policy

1. Import unified OCAH BFM wrappers from `hw/common/dv/vip` for standard
   protocol access (JTAG, AXI/AXI-Lite).
2. Wrap those BFMs in cocotb/PyUVM agents so tests remain sequence-based.
3. Use OCAH-local BFMs/models for custom OCH protocols (cross-trigger, iJTAG) and
   for firmware-driven interop (mailbox challenge-response, SEP boot observation).
4. Keep every BFM behind the same transaction-level boundary so backend changes
   do not affect sequences or scoreboards.

| SMU Interface | Preferred VIP | Modeling Approach | Notes |
|---------------|---------------|-------------------|-------|
| Primary JTAG TAP | `ocah_jtag_vip` `OcahJtagMasterDriver` | Unified OCAH BFM | Pin-level TAP driver/helper |
| External SMN AXI4 (`smu_axi_out`) | `ocah_axi_vip` `OcahAxiRam` | Unified OCAH BFM | Memory responder with scoreboard backdoor |
| External SMN AXI4 (`smu_axi_in`) | `ocah_axi_vip` master | Unified OCAH BFM | Drives inbound SMN traffic |
| SMC/SEP OTP AXI-Lite | `ocah_axi_vip` AXI-Lite wrapper | Unified OCAH BFM | OTP-over-JTAG2AXI responders |
| SMC scratch / mailbox | Backdoor + cocotb polling | OCAH-local | Firmware pass indication, challenge-response |
| Real SEP RTL boot | Backdoor observation | OCAH-local | PC / instruction-count checks |
| Cross-trigger (CTP/CTM), iJTAG | OCAH-local BFMs/models | OCAH-local | Custom OCH protocols |

## Testbench Hierarchy

The SMU reference TB is organized in four layers. The OSS environment mirrors this
structure, substituting the native cocotb/Verilator runner for `ttem`.

```text
smu_<scenario>_test  (test selection: cocotb plusarg / uvm_testname)
  -> TB wrapper layer  (tb/tb_top.sv -> smu_uvm_top)
       instantiates the SMU DUT (smu / smu_wrapper), clocks/resets,
       struct<->flat adapters, SMC scratch + SEP PC/inst-count +
       mailbox interrupt observation
  -> UVM layer         (AXI/JTAG/fabric/mailbox VIP env, sequences, test classes)
  -> cocotb layer      (firmware boot orchestration, pass/fail classification,
                        register/scratch polling, SEP PC-loop classification)
  -> firmware layer    (SMC fw + ROM, SEP ITCM/DTCM images)
```

### Layer 1: TB wrapper (`tb/tb_top.sv`)

`tb/tb_top.sv` implements `smu_uvm_top`. It instantiates the SMU DUT and provides
the struct↔flat-signal adapters cocotb needs, plus observation points: SMC scratch
registers (firmware pass), SEP PC / instruction-count (real-interop checks), and
mailbox interrupts. The closed-source analogue is
`dv/smu/tb/tb_uvm/sv/smc_chiplet_wrap_uvm_top.sv` (module `smc_uvm_top`).

### Layer 2: UVM

Top test selection, AMBA VIP environment, an IJTAG agent and sequences, chiplet
base tests, and fabric/register/mailbox test classes. Reference anchors:
`uvm_tests/smc_chiplet/smc_chiplet_base_test.sv`, `smc_chiplet_reg_jtag_test.sv`,
`smc_mailbox_register_test.sv`, `smc_output_fabric_*.sv`, `smc_local_fabric_*.sv`.

### Layer 3: cocotb

Firmware boot orchestration, plusarg-driven test selection, register/scratch
polling, pass/fail classification, and SEP PC-loop classification. Key plusargs:
`+COCOTB_TEST`, `+FW_TEST`, `+FW_TEST_TIMEOUT`, `+SEP_ITCM_HEX_FILE`,
`+SEP_DTCM_HEX_FILE`, `+SEP_SYM_FILE`, `+rom_hex`, plus interop-closure args
`+SMC_SEP_REQUIRE_PASS_LOOP`, `+SMC_SEP_REQUIRE_AXI_EVENTS`,
`+SMC_SEP_REQUIRE_MAILBOX_PASS`. The PC-loop helper narrows the loop window to
`{loop_base, loop_base+4}`.

### Layer 4: firmware

SMC firmware (`fw/smc/tests`), SMC ROM (`fw/smc/tests_rom`), and SEP firmware
(`fw/sep/tests`, e.g. `sep_smc_interop` producing `*.itcm.hex`/`*.dtcm.hex`).
Pass/fail is signaled via scratch registers, STDOUT magic word (`0x8000_0000`), or
SEP PC loops.

## Directory Structure

The OSS SMU folder uses the canonical flow-first (`cocotb/`-parented) layout:

```text
hw/sys/smu/dv/
  docs/
    SMU_SPEC.md
    SMU_CSR.md
    SMU_TB_ARCH.md
    SMU_VPLAN.md
    SMU_FCOV.md
  tb/
    tb_top.sv                 # smu_uvm_top
  cocotb/
    env/                      # env cfg, agents/BFM wrappers, monitors, scoreboard, mailbox model
    seq_lib/                  # reusable stimulus sequences
    tests/                    # one cocotb test per VPLAN scenario
  testlists/
    all.toml                  # includes + [[groups]] (smoke, smc, sep, dtp, interop, fabric)
    smc.toml
    sep.toml
    dtp.toml
    interop.toml
    fabric.toml
  smu_sim_cfg.toml
  smu_sim.core                # optional FuseSoC view (native flow ignores it)
  README.md
```

## HDL Top

`tb/tb_top.sv` instantiates the SMU as `smu_uvm_top` and adapts packed RTL structs
to cocotb-friendly scalar/vector ports.

| DUT Interface | `tb_top` Handling |
|---------------|-------------------|
| Clocks/resets | cocotb drives `clk_smu_i`, `clk_ref_i`, `clk_periph_i`, `rst_cold_ni`, `powergood_i` |
| JTAG TAP | Exposes `jtag_tck/tms/trst/tdi/tdo/tdo_oen` for `OcahJtagMasterDriver` |
| External SMN AXI | Flattens `smu_axi_in_*` / `smu_axi_out_*` structs for `OcahAxiRam` / master BFM |
| SMC scratch / mailbox | Exposes scratch words, `smc_test_pass`, and `ext_mailbox_interrupts` for the scoreboard |
| Real SEP RTL | Exposes SEP PC and instruction count; SEP TCM loaded via `+SEP_ITCM_HEX_FILE`/`+SEP_DTCM_HEX_FILE` |
| Cross-trigger / iJTAG | Looped back or tied idle until OCAH-local BFMs are added |

## Environment Components (planned)

### `SmuJtagAgent`
Wraps `ocah_jtag_vip.OcahJtagMasterDriver` for DTP TAP access through the SMU wrapper
(IDCODE/BYPASS, DEBUG_CONTROL, IC_RESET, JTAG2AXI, cross-trigger CSR).

### `SmuAxiAgent`
Wraps `ocah_axi_vip` on the external SMN ports: `OcahAxiRam` responder on
`smu_axi_out` and a master on `smu_axi_in`, with a backdoor view for the
scoreboard.

### `SmuMailboxModel`
Drives/observes the SMC↔SEP mailbox challenge-response: SMC writes the token, SEP
verifies and complements it, SMC pops the response.

### `SmuScoreboard`
Checks firmware pass indication (scratch), mailbox challenge-response, AXI
crossbar routing/decode, and SEP boot progress. `check_phase` requires zero
errors.

### Sequence Library
Hierarchical helpers: a generic base sequence for cross-cutting infrastructure;
feature base sequences per domain (SMC boot, SEP load/release, mailbox, JTAG/
debug, xbar traffic); command-library sequences for random/stress composition;
and one concrete test sequence per scenario. Test files/classes end in `_test`.

## Real SMC + SEP Co-Simulation

Real SMC and real SEP co-sim is enabled by the SEP-RTL compile target
(`+define+SEP_RTL`). The real SEP RTL instance is `smu.gen_sep.u_sep`; SEP
outbound/inbound AXI routes through `u_smu_axi_xbar`. cocotb backdoor-loads SMC
SRAM; the SV testbench loads SEP TCM via plusargs. Because SEP STDOUT
(`0x8000_0000`) writes do not reach the external output in the SMU wrapper, the
SEP pass checks sample the SMC-side mailbox pop plus SEP boot progress (PC in the
SEP ITCM range and instruction count ≥ 1000).

## DTP-to-SEP Reset/Control Observation Points (SEP RTL Mode)

Anchors for DTP-driven SEP debug/reset observation when the real SEP RTL is
present (`smu #(.SEP(1))`, instance `smu.gen_sep.u_sep`). Phase-1 (`SEP=0`)
tests exercise the DTP side of every path plus the `gen_no_sep` tie-offs;
SEP=1 DTP interop tests are inventoried in `testlists/deferred.toml` and
`SMU_VPLAN.md` Appendix A. Signal names refer to `hw/smu/rtl/smu.sv`.

| Path | Signals | SEP=0 behavior | What to observe (SEP=1) |
|------|---------|----------------|-------------------------|
| IC_RESET TDR → SEP domain resets | `u_dtp.jtag_ic_reset_sep_o` → `jtag_sep_reset_ctrl` → `u_sep.jtag_sep_reset_ctrl_i`; also exported as `smu.jtag_sep_reset_ctrl_o` | struct has no consumer | 13 ovrd/val pairs (`sep_pkg::jtag_sep_reset_ctrl_t`): `sep_reset_n`, kmac/hmac/aes/otbn/km `jtag_rst_n`, 7 SPI-domain resets. TDR grows from the SEP=0 139-bit geometry (`smu_jtag_helpers.py`) to `2*(1+68+13)+1 = 165` bits |
| SEP debug STAP chain | `jtag_stap_sep_host_tap_ctrl_o` (`dtp_sep_stap_tap_ctrl` tck/tms/trst_n), `dtp_sep_stap_tdo` → `u_sep.jtag_tdi`, `sep_stap_tdo_to_dtp` ← `u_sep.jtag_tdo` | chain dangles (no SEP TAP) | TAP-control activity and TDO return between DTP and the SEP STAP |
| SEP OTP JTAG2AXI bridge | TDRs `SEP_OTP_JTAG2AXI_CAPS` (IR `0x21`) / `SEP_OTP_AXI_SINGLE_OP` (IR `0x22`) → `dtp_axil_sep_otp_jtag_req/resp` → `u_sep.axil_sep_otp_jtag_*` | bridge absent (`JTAG_SEP_DBG_ENABLE=0`); err_slv DECERR/poison contrast covered by `smu_dtp_otp_sep0_err_slv_test` | AXI-Lite handshake at the SEP boundary; TDR status/rdata via the `sep_otp_jtag2axi_single_read` helper |
| Lifecycle / `feat_ctrl` handoff (SEP→DTP) | `u_sep.lc_state_o` → `sep_lc_state` → `smu.lc_state_o`; `u_sep.feat_ctrl_o` → `sep_feat_ctrl` → `u_dtp.feat_ctrl_i` | tied `8'hf0` / `'0` in `gen_no_sep` — the basis of the `force_feat_ctrl_bits` policy tests | `lc_state_o` value; `feat_ctrl` leaves (`sep_debug/soc_debug/ap_debug/ap_trace/sip_debug`, `fuse_test`@bit32) gating the JTAG2AXI and OTP TDR paths |
| CLA cross-trigger → SEP CPU control | `cla_ext_action_custom[4:0]` → `u_sep.mpc_debug_halt_req` / `mpc_debug_run_req` / `mpc_reset_run_req` (inverted) / `i_cpu_halt_req` / `i_cpu_run_req` | no consumer | SEP EL2 halt/run/reset-mode transitions versus CLA actions |
| Boot-stall visibility | `u_dtp.jtag_boot_stall_ovrd_o` / `jtag_boot_stall_o` → SMC `boot_stall_jtag_*`; combined `boot_stall_combined` net | active — `smu_dft_dtp_boot_stall_test` / `smu_dft_gpio_boot_stall_test` prove SMC `fuse_reset` gating | the combined-stall net is kept at SMU level for DTP/SEP visibility |
| SEP reset effect | `u_sep.sep_reset_n_o` → `smu.sep_reset_n_o` | tied off | end-to-end observation of DTP-commanded SEP resets |

For real-SEP execution today use the wrapper baseline (`--dut smu_wrapper`,
profile `compile_smu_chiplet_sep_rtl`), which boots the real EL2 and takes
backdoor PC / instruction-count checks (see "Real SMC + SEP Co-Simulation").

## Clock and Reset Strategy

| Clock / Reset | Source | Notes |
|---------------|--------|-------|
| `clk_smu_i` | cocotb clock in base test | Primary domain (SMC/SEP/DTP/xbar) |
| `clk_ref_i`, `clk_periph_i` | cocotb | Reference / peripheral domains |
| `rst_cold_ni` | base test | Cold reset (async assert / sync deassert) |
| `powergood_i` | base test | Power-good → DTP power-on reset |
| JTAG TCK / TRST | `OcahJtagMasterDriver` | TAP clock domain |

Interop and JTAG2AXI sequences poll response status / scratch instead of sleeping
for a fixed number of cycles, keeping CDC and AXI latency handling protocol-based.

## Stimulus Strategy

| Area | Strategy |
|------|----------|
| SMU-SMC | Boot SMC firmware, observe scratch/mailbox; wrapper toggle/coverage sweeps |
| SMU-SEP | Load SEP TCM, release reset, observe PC/inst-count; module smoke (SPI/AES/OTBN/…) |
| SMU-DTP | Drive JTAG TAP through the wrapper; boot-stall/clock-stop interaction with SMC boot |
| Interop | Mailbox challenge-response, bidirectional routing, xbar programmability, stall |
| Fabric | Directed + randomized crossbar decode, connectivity, ID-width, remap traffic |

## Checking Strategy

| Check Type | Component | Description |
|------------|-----------|-------------|
| Firmware pass | `SmuScoreboard` | SMC scratch magic / mailbox pass |
| Mailbox interop | `SmuMailboxModel`, `SmuScoreboard` | Token challenge-response correctness |
| AXI routing | `SmuScoreboard` | Crossbar decode / connectivity vs expected |
| SEP boot | Backdoor observation | PC in ITCM range, instruction count threshold |
| JTAG/debug | `SmuJtagAgent` | IDCODE/DEBUG_CONTROL/IC_RESET/JTAG2AXI results |
| Regression parsing | Global DV parser | Requires a positive cocotb test result |

## Coverage Strategy

Verilator does not support SV covergroups. The OCAH open-source path collects
Python-side functional observations in the cocotb environment and relies on
commercial simulators for SV covergroups, assertion coverage, and full code
coverage. See `SMU_FCOV.md`.

## Build and Run

```bash
python3 tools/dv/run_dv.py --dut smu --build-only
python3 tools/dv/run_dv.py --dut smu --items smoke --dry-run
python3 tools/dv/run_dv.py --dut smu --items smc
python3 tools/dv/run_dv.py --dut smu --items interop
python3 tools/dv/run_dv.py --dut smu --items all --dry-run
```

The `smoke` group is a fast cross-block gate (SMC boot + DTP JTAG + fabric
decode). The `smc`, `sep`, `dtp`, `interop`, and `fabric` groups run the
corresponding stream; `all` collects the included SMU testlists.

## Revision History

| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0 | 2026-07-07 | OSS DV Team | Initial OCAH open-source SMU testbench architecture, modeled on DTP_TB_ARCH.md; documents the hybrid UVM+cocotb+firmware four-layer flow, real SMC+SEP co-sim, mailbox challenge-response, and the canonical `cocotb/`-parented layout |
| 1.1 | 2026-07-19 | OSS DV Team | Add "DTP-to-SEP Reset/Control Observation Points (SEP RTL Mode)" — IC_RESET SEP slice, SEP STAP chain, SEP OTP JTAG2AXI bridge, lifecycle/`feat_ctrl` handoff, CLA-to-SEP CPU control, boot-stall visibility (#3360 AC) |
