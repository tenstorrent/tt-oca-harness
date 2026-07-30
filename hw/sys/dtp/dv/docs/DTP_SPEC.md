# DTP Design Specification

## Overview

The Debug and Test Ports (DTP) subsystem is the chiplet-level debug and test access
block. It aggregates the primary JTAG TAP, downstream STAP/iJTAG scan paths,
JTAG-to-AXI debug bridges, and the cross-trigger network used for external and
internal trigger routing.

This OCAH open-source verification plan follows the working reference plan in
`dv/dtp/doc/DTP_SPEC.md`, but scopes implementation to the public `tt-oca`
repository using the PyUVM, cocotb, and Verilator environment in
`hw/sys/dtp/dv/`. Standard protocol interfaces use the unified OCAH BFM
packages; custom OCH protocols are modeled by OCAH-local BFMs when no shared
wrapper exists.

| Field | Value |
|-------|-------|
| Design location | `hw/sys/dtp/rtl/` |
| RTL top module | `dtp` |
| Package | `dtp_pkg` (`hw/sys/dtp/rtl/dtp_pkg.sv`) |
| Repository | `tt-oca` |
| Open-source DV location | `hw/sys/dtp/dv/` |
| Reference plan | `dv/dtp/doc/` |
| Standards | IEEE 1149.1-2013 (JTAG), IEEE 1687-2014 (iJTAG), IEEE 1838-2019 (3DIC); OCH Cross Trigger v1.0 (OCCT) |

## Specifications

| Feature | Specification |
|---------|---------------|
| JTAG standard | IEEE 1149.1-2013 |
| iJTAG standard | IEEE 1687-2014 |
| 3DIC standard | IEEE 1838-2019 |
| Cross-trigger protocol | OCH Cross Trigger v1.0 (Open Chiplet Cross Triggering, OCCT) |
| CSR interface | AXI4-Lite (32-bit) |
| Debug AXI interface | AXI4 (configurable width; SMC fabric is 56-bit address / 64-bit data) |
| Maximum external CTPs | 32 |
| Maximum internal CTs | 32 |

## Configuration Parameters

Defaults below are the values `hw/sys/dtp/rtl/dtp.sv` elaborates with, which are what
the open-source TB builds. DTP prefixes the JTAG IP parameters with `JTAG_` (for
example `JTAG_NUM_EXTRA_STAPS`), and overrides some IP-level defaults — noted per row.

### JTAG Interface Unit / PTAP

| Parameter | Range / Type | Default | Description |
|-----------|--------------|---------|-------------|
| `NUM_STAP` | 0-8 | 4 | Number of STAP interfaces |
| `STAP_IO_ENABLE` | 0/1 | 1 | Enable I/O STAP for chiplet-to-chiplet connectivity |
| `SMC_DBG_ENABLE` | 0/1 | 1 | Enable SMC debug STAP and SMC JTAG2AXI bridge |
| `SEP_DBG_ENABLE` | 0/1 | 1 | Enable SEP debug STAP |
| `NUM_EXTRA_STAPS` | 0-4 | 1 | Number of additional STAPs (IP default is 0; DTP elaborates 1) |
| `BSR/EXTEST_TRAIN/EXTEST_PULSE/INTEST/CLAMP/HIGHZ/RUNBIST/TMP_ENABLE` | 0/1 | 1 | Optional instruction enables (a disabled instruction behaves as BYPASS) |
| `IC_RESET_{SMC,SEP,EXT}_ENABLE` | 0/1 | 1 | Enable each IC_RESET slice (IP default is 0; DTP elaborates all three to 1, so the IC_RESET TDR is `2*(NUM_SMC+NUM_SEP+NUM_EXT)+1` bits wide rather than absent) |
| `IDCODE_MFR_ID / PART_NUM / SI_REV` | 11/16/4-bit | 0 | IDCODE field parameters |
| `OCH_VER` | 8-bit | 0 | DTP IP major version reported in JTAG_CAPS |
| `*_PL_DEPTH` | 2-bit | 3 | JTAG2AXI read/write pipeline depths |

### Cross Trigger Network

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| `NUM_CTP` | 1-32 | 16 | Number of external Cross Trigger Ports |
| `NUM_INT_CT` | 0-32 | 10 | Number of internal cross triggers (e.g. to CLAs) |
| `NUM_CLK_STOP_REQ` | 1-32 | 9 | Number of clock-stop request inputs aggregated |
| `INT_CT_MODE` | bit vector | `0` | Per internal CT mode: 0 = pulse, 1 = handshake |

With the default `NUM_CTP=16` and `NUM_INT_CT=10`, the Cross Trigger Matrix routes
26 source ports and 26 destination ports.

## Architecture

### Block Overview

```text
Primary JTAG TAP
  -> jtag_intf_unit
       -> jtag_ptap / TAP FSM / instruction decode / TDR mux
       -> BSR, STAP, iJTAG, 3DCR scan paths
       -> SMC fabric JTAG2AXI bridge
       -> SMC OTP JTAG2AXI bridge
       -> SEP OTP JTAG2AXI bridge

AXI-Lite XTRIG CSR
  -> cross_trigger_network
       -> cross_trigger_matrix
       -> cross_trigger_port[15:0]
       -> clock-stop aggregation
```

### Sub-Blocks

| Block | RTL Module | Verification Relevance |
|-------|------------|------------------------|
| JTAG interface unit | `jtag_intf_unit` | TAP instruction decode, scan routing, security gating, debug controls |
| Primary TAP | `jtag_ptap` | IEEE 1149.1 TAP FSM, IR/DR scans, TDR selection |
| Secondary TAP (STAP) | `jtag_stap` | IEEE 1838 STAP chain (I/O, SMC, SEP, extra STAPs); per-STAP 3-bit 3DCR and lockup latches |
| JTAG2AXI bridges | `jtag2axi` instances | Debug reads/writes across TCK to `clk_i` CDC into AXI/AXI-Lite |
| Cross trigger network | `cross_trigger_network` | CTP/CTM CSR decode, routing, clock-stop integration |
| Cross trigger matrix | `cross_trigger_matrix` | Source-to-destination routing mask behavior |
| Cross trigger port | `cross_trigger_port` | Wire-OR and point-to-point external trigger protocols |

### Data Paths

The primary JTAG data path enters through `jtag_ptap_client_*`, loads a 6-bit
instruction, and shifts the selected TDR in Shift-DR. For JTAG2AXI operations,
the selected TDR encodes a read/write request, crosses from TCK into `clk_i`,
issues AXI or AXI-Lite traffic, and reports completion status on a later DR
capture.

The cross-trigger path is configured through the `axil_xtrig_*` AXI-Lite
subordinate. CTM routing registers map 16 external CTP ports and 10 internal
cross-trigger channels. Each CTP can operate in wire-OR pulse mode or 4-phase
point-to-point handshake mode.

## Interfaces

| Interface | Type | Direction | Open-Source Verification Policy |
|-----------|------|-----------|-------------------------|
| Primary JTAG TAP | Pin-level JTAG (`tck`, `tms`, `trst_n`, `tdi`, `tdo`) | Client | Use `ocah_jtag_vip` |
| SMC fabric debug | AXI4, 56-bit address, 64-bit data | Manager | Use `ocah_axi_vip` `OcahAxiRam` |
| SMC OTP debug | AXI4-Lite, 32-bit address/data | Manager | Use `ocah_axi_vip` when enabled |
| SEP OTP debug | AXI4-Lite, 32-bit address/data | Manager | Use `ocah_axi_vip` when enabled |
| XTRIG CSR | AXI4-Lite, 32-bit address/data | Subordinate | Use `ocah_axi_vip` `OcahAxiLiteMaster` when enabled |
| BSR / STAP scan | `jtag_scan_ctrl_t` plus scan in/out | Host | Loopback first, then OCAH-local scan model |
| iJTAG scan | `jtag_scan_ctrl_t` plus scan in/out | Host | OCAH-local model; no mature public IEEE 1687 VIP identified |
| CTM internal CT | Request/ack arrays | Mixed | OCAH-local BFM; custom OCH protocol |
| CTP GPIO | Four GPIO directions per CTP | Pad | OCAH-local BFM; custom OCH protocol |
| Lifecycle control | `sep_efuse_map_lc_disable_reg_t` | Input | Directed values from TB |

## Features

### Feature 1: IEEE 1149.1 TAP and Instruction Decode

The TAP supports Test-Logic-Reset, IR scans, DR scans, mandatory instructions
such as IDCODE and BYPASS, optional boundary-scan instructions, TMP, IC_RESET,
and debug control instructions. Verification must cover TLR/TRST reset behavior,
IR opcode decode, DR width selection, BYPASS fallback for disabled/undefined
instructions, and correct IDCODE capture.

### Feature 2: Debug Control TDRs

The DEBUG_CONTROL TDR controls boot stall, JTAG clock-stop request, and CLA
clock-stop enable/readback. Verification must observe `stop_clks_o`,
`cla_clock_stop_en_o`, `jtag_boot_stall_ovrd_o`, and `jtag_boot_stall_o`.

### Feature 3: STAP, 3DCR, and iJTAG Scan Routing

DTP forwards scan traffic through a four-level STAP hierarchy — I/O STAP (level 1,
crosses the die boundary with TDI lockup), SMC debug STAP, SEP debug STAP, and
extra STAPs (scan-output lockup on the last) — and exposes three cascaded iJTAG
SIB chains: DFT Secure, DFT Non-Secure, and DFD (Debug Forensics Dump). The PTAP
holds a 2-bit 3DCR (`TAP_3DCR`) that bypasses the whole STAP chain, and each STAP
holds its own 3-bit 3DCR (`config_hold`, `stap_sel`, `tms_hold`). The full
reference plan covers SIB combinations, 3DCR select/config-hold/TMS-hold behavior,
and lifecycle gating. The open-source scenario inventory keeps these scan-routing
categories alongside the standard JTAG/JTAG2AXI flows.

### Feature 4: JTAG2AXI Debug Bridges

Three bridges expose SMC fabric AXI4, SMC OTP AXI-Lite, and SEP OTP AXI-Lite
access through JTAG TDRs. Verification must cover capability reads,
single-operation read/write, response status, backpressure/error handling,
series operations, reset/CDC recovery, and lifecycle security gating.

### Feature 5: Cross Trigger Network

The cross-trigger network implements the OCH Cross Trigger v1.0 (OCCT) protocol and
provides memory-mapped CTP and CTM configuration, wire-OR pulse routing (with a
configurable pulse stretcher), 4-phase point-to-point handshake routing, and
clock-stop aggregation. The CTM is a 26x26 combinatorial AND-OR crossbar with
registered outputs (default `NUM_CTP=16` + `NUM_INT_CT=10`). Clock-stop aggregation
forms the registered `stop_clks_o` halt as `registered(jtag_clock_stop OR
|xtrig_clk_stop_req_i)`, while the DEBUG_CONTROL `cla_clock_stop` readback reflects
only the CLA requests. In the OCAH open-source Verilator path, generated CTP/CTM CSR
blocks are stubbed; functional cross-trigger tests require either commercial
simulation or a Verilator-compatible CSR implementation.

## Operating Modes

| Mode | Description | Entry Condition | Exit Condition |
|------|-------------|-----------------|----------------|
| Normal debug/test | TAP and cross-trigger logic active | Resets deasserted, lifecycle permits access | Reset or lifecycle gating |
| TAP reset | PTAP in Test-Logic-Reset with IDCODE selected | TRST or 5 TMS=1 clocks | TMS sequence to Run-Test/Idle |
| JTAG2AXI debug | JTAG TDR initiates AXI transaction | JTAG2AXI opcode loaded and request shifted | Completion status captured |
| STAP/iJTAG scan | Scan path inserted behind PTAP | 3DCR or SELECT_IJTAG configuration | Deselection or reset |
| Cross-trigger routing | CTM/CTP route trigger events | CSR routing/mode configured | CSR clear or reset |
| Clock stop | DTP asserts chiplet halt | DEBUG_CONTROL or CLA request | Request cleared |

## Clock and Reset

| Domain | Clock | Reset | Notes |
|--------|-------|-------|-------|
| System / AXI / XTRIG | `clk_i` | `rst_n_i` | Active-low system reset |
| JTAG | `jtag_ptap_client_tap_ctrl_i.tck` | `pwr_on_rst_ni` and TRST | TAP/TDR domain |

The JTAG primary reset `jtag_trst_n` is `pwr_on_rst_ni` AND-combined with the
external `trst_n`; the TAP enters Test-Logic-Reset on TRST or power-on, and the
clock-stop output resets to 0 (clocks running).

JTAG2AXI traffic crosses from TCK into `clk_i`. Tests must avoid fixing failures
by adding arbitrary delays; protocol ordering, CDC clear behavior, and response
polling must be verified explicitly.

## Error Handling

| Error Condition | Detection Mechanism | Expected Response |
|-----------------|---------------------|-------------------|
| Undefined or disabled JTAG instruction | IR decode | Select BYPASS behavior |
| AXI SLVERR/DECERR | AXI response captured by JTAG2AXI | Report error status in response TDR |
| JTAG2AXI busy/backpressure | Response status or pending transaction | Poll until non-busy; maintain protocol stability |
| Series-operation error | Series status TDR | Sticky/pending error until cleared |
| Cross-trigger handshake deadlock | CTP STATUS / timeout in BFM | Recover through CTP reset or system reset |
| Lifecycle disabled feature | `feat_ctrl_i` gating | Block access and keep safe inactive outputs |

## Security Considerations

The 64-bit lifecycle feature-control vector (`feat_ctrl_i`, from the SEP eFuse
controller) is synchronized into the TCK domain through 64 individual 2-FF
synchronizers and gates STAP selection, iJTAG SIB access, and the JTAG2AXI bridges.
These fields use enable-polarity: `1` means the feature is enabled, and a
resource is gated whenever any required enable is `0`. The authoritative access
conditions are:

| Debug resource | Enabled when feature control satisfies |
|----------------|----------------------------------------|
| I/O STAP | `sip_debug` |
| SMC debug STAP | `soc_debug && ap_debug` |
| SEP debug STAP | `sep_debug && soc_debug && ap_debug` |
| Extra STAPs | `ap_debug` |
| DFT Secure SIB | `fuse_test && sep_debug && soc_debug && ap_debug` |
| DFT Non-Secure SIB | `soc_debug && ap_debug` |
| DFD SIB | `ap_debug` |
| SMC fabric JTAG2AXI | `soc_debug && ap_debug` |
| SMC OTP JTAG2AXI | `fuse_test && soc_debug && ap_debug` |
| SEP OTP JTAG2AXI | `fuse_test && sep_debug && soc_debug && ap_debug` |

When a resource is gated, STAP selection is forced inactive (with `host_tdo_o` and
the 3DCR update-enable also forced low), a SIB cannot open, and a JTAG2AXI
instruction falls back to BYPASS with no AXI traffic. Open-source tests should keep
this coverage using directed lifecycle values rather than assuming all debug
features are always enabled.

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `prim_jtag_pkg`, `jtag_tap_pkg`, `jtag_inst_reg_pkg` | TAP, scan, and instruction types |
| `dtp_pkg` | DTP default widths and AXI typedefs |
| `cross_trigger_network_pkg` | Cross-trigger topology and types |
| `sep_efuse_pkg` | Lifecycle feature control struct |
| `hw/ip/jtag/jtag_ptap`, `hw/ip/jtag/jtag_stap` | Primary and secondary TAP RTL |
| `hw/ip/cross_trigger/cross_trigger_port`, `hw/ip/cross_trigger/cross_trigger_matrix` | CTP and CTM RTL |
| `hw/ip/cross_trigger/cross_trigger_network` | Cross-trigger network RTL |
| `hw/ip/jtag/jtag2axi` | `jtag2axi` JTAG-to-AXI/AXI-Lite bridge |
| `ocah_jtag_vip` | Unified OCAH primary JTAG BFM wrapper |
| `ocah_axi_vip` | Unified OCAH AXI/AXI-Lite BFM wrappers |

## Verification Alignment

The working reference plan in `dv/dtp/doc/` contains 72 logical tests. The
open-source VPLAN expands multi-scenario CocoTB modules into 147 named OCAH
open-source test cases. Scenario groups cover smoke, Basic JTAG, SMC-fabric
JTAG2AXI read/write, debug TDR scenarios (TMP_STATUS, IC_RESET, DEBUG_CONTROL,
JTAG_CAPS, and JTAG2AXI_CAPS), STAP/iJTAG scan routing, XTRIG, CTP, and CTM while
using unified OCAH BFM wrappers for standard protocols.

## Revision History

| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0 | 2026-06-09 | DV Team | OCAH open-source verification specification aligned with the DTP reference plan |
| 1.1 | 2026-06-14 | DV Team | Aligned with OCAH design spec (ocah-documentation.pdf, Chapter 7): added specifications/config-parameter tables, STAP hierarchy + 3DCR widths, authoritative lifecycle-gating table, clock-stop aggregation, and RTL dependencies |
| 1.2 | 2026-06-22 | DV Team | Updated verification alignment for Basic JTAG, JTAG2AXI single-op, and debug TDR public scenarios |
| 1.3 | 2026-07-29 | DV Team | Corrected stale RTL paths to the `hw/sys/` and `hw/ip/<family>/` layout, renamed the bridge to `jtag2axi`, and fixed the `NUM_EXTRA_STAPS` and `IC_RESET_{SMC,SEP,EXT}_ENABLE` defaults to the values `dtp.sv` actually elaborates |
