# SMU Design Specification

## Overview

The System Management Unit (SMU) is the chiplet's system-management subsystem. It
composes three functional blocks around a runtime-programmable AXI crossbar:

- **SMC** — System Management Controller: the management CPU cluster plus resets,
  power, clocking, mailboxes, PLIC, reset unit, GPIO/PLL/PVT/eFuse shims,
  telemetry, ROM/cache/scratch memory, and the OCTS system timer.
- **SEP** — Security Processor (`SEP=1`): a real RISC-V security core with crypto
  (HMAC/KMAC/AES/OTBN/KM), DMA, SPI, eFuse, watchdog, lifecycle/`feat_ctrl`, and
  the mailbox interface to SMC.
- **DTP** — Debug & Test Ports: the JTAG PTAP/STAP/BSR/DFT/DFD chains, IC_RESET
  TDR reset overrides, the cross-trigger network (CTM/CTP/clock-stop), and the
  JTAG2AXI debug bridges into SMC fabric and SMC/SEP OTP.

These are joined by the **SMU AXI crossbar** (`smu_axi_xbar`), a 3×3 fully
connected AXI4 crossbar that routes SEP, SMC, and one external SMN-facing port
using CSR-programmed SEP/SMC apertures.

This specification describes the public `tt-oca` implementation and its
cocotb/Verilator environment in `hw/sys/smu/dv/`. Standard
protocol interfaces use the unified OCAH BFM packages; custom OCAH protocols are
modeled by OCAH-local BFMs when no shared wrapper exists.

| Field | Value |
|-------|-------|
| Design location | `hw/smu/rtl/` |
| RTL top module (core) | `smu` (`hw/smu/rtl/smu.sv`) |
| RTL integration wrapper | `smu_wrapper` (`hw/smu/smu_wrappers/rtl/smu_wrapper.sv`) |
| Packages | `smu_pkg` (`hw/smu/rtl/smu_pkg.sv`), `smu_axi_xbar_pkg` |
| Repository | `tt-oca` |
| Open-source DV location | `hw/sys/smu/dv/` |
| Standards | AMBA AXI4/AXI4-Lite; IEEE 1149.1 (JTAG) via DTP; OCAH Cross Trigger v1.0 (OCCT) via DTP; OCAC/OCS compliance mapping |

## Specifications

| Feature | Specification |
|---------|---------------|
| Subsystem composition | SMC + SEP (`SEP=1`) + DTP + AXI crossbar |
| Crossbar | 3×3 fully-connected AXI4 (`smu_axi_xbar`), CSR-programmed apertures |
| Crossbar address width | 56-bit address, 64-bit data, 12-bit user |
| Crossbar ID widths | 8-bit max input → 10-bit crossbar → 6-bit SMC/SEP outputs |
| Atomics | `ATOPs = 1'b0` — AXI atomic operations unsupported (rejected) |
| SMC mailboxes | `smc_pkg::NUM_MAILBOXES = 32` |
| SEP mailboxes | `sep_pkg::NUM_MAILBOXES = 8` |
| Interrupts to SMC | `Cfg.NUM_INT_TO_SMC = 256` |
| Cross-trigger CTP GPIO ports | 16 (`XTRIG_NUM_CTP`) |
| Cross-trigger external CTM ports | 8 (`XTRIG_NUM_INT_CT`; DTP `[1:0]` reserved for SMC) |
| Clock-stop request ports | 8 (`XTRIG_NUM_CLK_STOP_REQ`; DTP `[0]` reserved for SMC) |
| Lifecycle state width | `2 * LC_STATE_WIDTH = 8` bits |

## Configuration Parameters

Default SMU build parameters from `smu_pkg.sv` (`smu_cfg_t` / `DefaultCfg`) and
the top-level `smu` parameter list.

### Top-level parameters (`smu.sv`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SEP` | `int unsigned` | `1` | SEP enable. Declared `int` (not `bit`) so SpyGlass `-param SEP=0` can override. `SEP=0` ties off SEP outputs and substitutes an AXI-Lite error slave on the SEP-OTP path. |
| `SEP_SEC_DISABLE_TOKEN` | `bit [255:0]` | `256'b0` | SEP security-disable token digest; tied `0` at SMU, replaced with the real digest at synthesis. |
| `Cfg` | `smu_pkg::smu_cfg_t` | `DefaultCfg` | Subsystem configuration struct (see below). Presets: `DefaultCfg`, `NoSepCfg` (`SmuConfigs[0]`/`[1]`, `NumSmuConfigs=2`). |

### Subsystem configuration (`smu_pkg::smu_cfg_t` / `DefaultCfg`)

| Field | Default | Description |
|-------|---------|-------------|
| `NUM_INT_TO_SMC` | `256` | External interrupts aggregated to SMC. |
| `JTAG_NUM_EXTRA_STAPS` | `1` | Extra STAP ports (min 1 exposed → `JTAG_NUM_EXTRA_STAP_PORTS`). |
| `JTAG_*_ENABLE` (BSR/EXTEST/INTEST/CLAMP/HIGHZ/RUNBIST/TMP/IC_RESET/SMC_DBG/STAP_IO) | `1` | DTP optional JTAG instruction enables. |
| `IDCODE_MFR_ID / PART_NUM / SI_REV / OCH_VER` | `0` | DTP IDCODE and version fields. |
| `SMC_OTP_RD/WR_PL_DEPTH`, `SMC_RD/WR_PL_DEPTH` | `3` | JTAG2AXI pipeline depths (SEP OTP RD/WR forced to `2'h3`). |
| `XTRIG_INT_CT_MODE` | config-dependent | Per internal-CT mode fed to DTP as `{Cfg.XTRIG_INT_CT_MODE, 2'b00}` (bits `[1:0]=0` for SMC pulse-sync). |
| `SEP_KM_LATCHED_MEM_RDATA` | `1'b1` | SEP KM latched read-data behavior. |
| `SEP_ABR_SRAM_LATENCY` | `1` | ABR 1R1W registered-read latency, in clocks. |
| `SEP_ABR_MASKING_EN` | `1'b1` | Adams Bridge 2-share DOM masking. |

`NoSepCfg` is field-identical to `DefaultCfg`; the SEP/no-SEP distinction is
carried by the separate `SEP` parameter, not by the `Cfg` struct.

## Architecture

### Block Overview

```text
                         Primary JTAG TAP / STAP / iJTAG
                                    |
  clk_smu_i domain            +-----v------ u_dtp (dtp) -------------------+
  ------------------          | PTAP/STAP/BSR/DFT/DFD, IC_RESET TDR,       |
  external SMN AXI            | cross-trigger (CTM/CTP/clock-stop),        |
   smu_axi_in/out             | JTAG2AXI -> SMC fabric, OTP -> SMC/SEP     |
        |                     +----+------------------+--------------------+
        v                          | JTAG2AXI              | OTP AXI-Lite
  +-----+----- u_smu_axi_xbar -----v----+                  v
  | 3x3 AXI4, CSR apertures:            |            u_smc (smc)  <----> u_sep (sep, SEP=1)
  |  sep_out -> {smc_in, ext_out}       |            CPU/boot/reset       real security core
  |  smc_out -> {sep_in, ext_out}       |            mailbox(32)/PLIC     mailbox(8)/crypto/DMA
  |  ext_in  -> {sep_in, smc_in}        |            aperture CSR         feat_ctrl/security-disable
  +----+-------------------+------------+                  ^
       | ID conv 10->6     | ID conv 10->6                 | SEP->SMC alias remap (fixed 0x4000_0000 -> 0x0)
       v                   v                               |
   u_iw_conv_sep      u_iw_conv_smc  --------------------- +
```

When `SEP=0`, the crossbar and SEP are replaced by direct SMC↔external
ID-width converters (`u_iw_conv_smc_out`/`u_iw_conv_smc_in`) and an AXI-Lite error
slave on the SEP-OTP path.

### Sub-Blocks

| Instance | RTL Module | Present | Verification Relevance |
|----------|------------|---------|------------------------|
| `u_dtp` | `dtp` | always | JTAG PTAP/STAP/BSR/DFT/DFD, IDCODE/BYPASS, IC_RESET TDR override, boot-stall, clock-stop, cross-trigger, JTAG2AXI + OTP-over-JTAG to SMC/SEP. |
| `u_smc` | `smc` | always | SMC CPU boot/reset/mailbox/PLIC/reset-unit/lifecycle-demote/PVT, aperture CSR, GPIO/PLL/PVT/eFuse shims, telemetry, ROM/cache/scratch, OCTS timer. |
| `u_sep` | `sep` | `SEP=1` | Real SEP CPU boot/execute, SPI/HMAC/KMAC/DMA/AES/OTBN/eFuse/WDT, lifecycle/`feat_ctrl`/security-disable, mailbox IRQ to SMC, KM/crypto memories, AXI extension. |
| `sep_ext_to_smc_axi_local_alias_remap` | `axi_window_remap` | `SEP=1` | SEP→SMC alias remap (fixed `0x4000_0000`/1 GB → `0x0`), bypasses the crossbar. |
| `u_smu_axi_xbar` | `smu_axi_xbar` | `SEP=1` | Address decode, connectivity matrix, aperture programmability, ATOP rejection, no-overlap SVA, error-response routing. |
| `u_iw_conv_sep` / `u_iw_conv_smc` | `axi_iw_converter` | `SEP=1` | Crossbar 10-bit → SEP/SMC 6-bit ID conversion. |
| `u_sep_otp_axil_err_slv` | `prim_axi_lite_err_slv` | `SEP=0` | SEP=0 SEP-OTP path returns DECERR (`0xBADCAB1E`). |
| `u_iw_conv_smc_out` / `u_iw_conv_smc_in` | `axi_iw_converter` | `SEP=0` | Direct SMC↔external ID conversion (no crossbar). |

At the wrapper level, `smu_wrapper` adds `u_smc_ip_integration` (3rd-party IP,
macros, pads, SPI padring, telemetry, JTAG pads) and, when `SEP=1`,
`u_sep_ip_integration` (SEP SRAM/ROM/TCM, eFuse, SPI, KM, OTBN, TRNG shims).

### Data Paths

**Crossbar routing** (`smu_axi_xbar`): slave (initiator) ports are `sep_out`(0),
`smc_out`(1), `ext_in`(2); master (target) ports are `sep_in`(0), `smc_in`(1),
`ext_out`(2). Connectivity: `sep_out→{smc_in, ext_out}`, `smc_out→{sep_in,
ext_out}`, `ext_in→{sep_in, smc_in}` — a master cannot reach its own inbound
port. `ext_out` is the default (catch-all) master port for unmatched `sep_out`/
`smc_out` accesses; `ext_in` has no default, so its unmatched accesses
decode-error.

**SEP→SMC alias remap**: a dedicated SEP-to-SMC port (bypassing the crossbar)
remaps the fixed region `SEP_SMC_REGION_BASE=0x4000_0000` (size `0x4000_0000`, 1
GB) to `SEP_SMC_REGION_ALIAS_BASE=0x0000_0000`.

**Mailbox challenge-response**: SMC writes a token to an outbound mailbox; SEP
reads it from its inbound mailbox, verifies, and writes the complement back; SMC
pops the response. This is the primary real SMC↔SEP interoperability path.

## Interfaces

Directions/types from the `smu` core boundary (`smu.sv`).

| Interface | Type | Direction | Open-Source Verification Policy |
|-----------|------|-----------|---------------------------------|
| Primary JTAG TAP | Pin-level (`tck`,`tms`,`trst_n`,`tdi`,`tdo`) via `jtag_ptap_client_*` | Client | Use `ocah_jtag_vip` |
| External SMN AXI in | `smu_axi_in_req_i`/`resp_o` (`axi_56_64`, 8-bit ID) | Subordinate | Use `ocah_axi_vip` master |
| External SMN AXI out | `smu_axi_out_req_o`/`resp_i` (`axi_out`, 10-bit ID) | Manager | Use `ocah_axi_vip` `OcahAxiSlaveAgent` |
| SMC/SEP OTP debug (over JTAG2AXI) | AXI4-Lite 32/32 | Manager | Use `ocah_axi_vip` AXI-Lite wrappers |
| SMC AXI-Lite shims (PLL/PVT/GPIO/eFuse/extension) | `smc_axil_32_32` | Mixed | Use `ocah_axi_vip` AXI-Lite when exercised |
| SMC mailbox interrupts | `ext_mailbox_interrupts_o [31:0]` | Output | Observe; scoreboard checks |
| SEP mailbox interrupts | internal `[7:0]` | Internal | Observe via wrapper (note ISSUE-7) |
| BSR / STAP / iJTAG scan | `jtag_scan_ctrl_t` + scan in/out | Host | Loopback first, then OCAH-local scan model |
| Cross-trigger CTM/CTP | Request/ack arrays + GPIO | Mixed | OCAH-local BFM; custom OCAH protocol |
| Clocks | `clk_smu_i`, `clk_ref_i`, `clk_periph_i`, `clk_telemetry_i`, `clk_sep_wdt_i` | Input | Driven by TB |
| Resets / power | `rst_cold_ni`, `powergood_i`; outputs `rst_cold_stable_ref_clk_no`, `rst_primary_*_clk_no` | Mixed | Driven/observed by TB |
| Lifecycle / feature control | `feat_ctrl` (`sep_efuse_map_lc_disable_reg_t`), `lc_state_o [7:0]`, `lcc_demote_state_*` | Mixed | Directed values from TB |
| CPU memory (ROM/scratch/cache) | `chipyard_4core_mem_pkg` req/rsp | Mixed | Backdoor load/observe |
| Peripheral hooks | SPI IRQ, I3C DAT/DCT mem, OCTS `timer_count_o [63:0]`, UART IRQ | Mixed | Observe / OCAH-local where needed |

## Features

### Feature 1: SMC Boot and Firmware Execution

SMC boots from ROM, releases resets, runs firmware, and signals pass/fail via
scratch registers and mailbox interrupts. Verification covers reset control,
mailbox sanity/interrupts, PLIC, reset unit, GPIO/strap, eFuse, WDT, and the
`SEP=0` no-SEP wrapper configuration.

### Feature 2: Real SEP RTL Under the SMU

With `SEP=1`, the real SEP core is instantiated (`smu.gen_sep.u_sep`). SEP TCM is
loaded (ITCM/DTCM hex), reset is released, and CPU execution is observed (PC
movement, instruction retirement, STDOUT/symbol pass-fail). SEP-side modules
(SPI/HMAC/KMAC/DMA/AES/OTBN/eFuse/WDT) get smoke/KAT/CSR checks.

### Feature 3: DTP Debug and Test Access

DTP provides JTAG TAP access through the SMU wrapper: IDCODE/BYPASS/state
transitions, boot-stall/debug-control interaction with SMC boot, DTP→SMC CSR and
JTAG2AXI local-fabric access, OTP-over-JTAG, IC_RESET reset override, clock-stop
coordination, and cross-trigger routing — all subject to lifecycle/debug gating.

### Feature 4: AXI Crossbar Fabric

The crossbar routes SEP/SMC/external traffic through CSR-programmed apertures.
Verification covers address decode, the connectivity matrix, the external SMN
port, performance/backpressure, error handling, ID-width conversion, atomics
rejection (`ATOPs=0`), and programmable global-base remap.

### Feature 5: SMC↔SEP Interoperability

Real SMC CPU and real SEP RTL exchange data through the mailbox
challenge-response protocol, bidirectional routing, and xbar programmability,
including the SMC-executes-while-SEP-stalled path. Modeled SEP-facing BFM tests
exercise wrapper connectivity only and are reported separately from real interop.

### Feature 6: Cross-Trigger and Clock-Stop Coordination

DTP's cross-trigger matrix and clock-stop aggregation coordinate SMC CLA
clock-stop and external trigger routing. Verification covers CTM routing, CTP
wire-OR/P2P protocols, and DTP↔SMC clock-stop handshake.

### Feature 7: Lifecycle and Security

SEP drives `dbg_disable` into DTP and `security_disable` and lifecycle state
into SMC. Verification covers lifecycle/debug policy matrices, the
security handoff, and fuse-sense handshake.

## Operating Modes

| Mode | Description | Entry Condition | Exit Condition |
|------|-------------|-----------------|----------------|
| Normal operation | SMC (+SEP) running, DTP idle | Resets deasserted, boot complete | Reset |
| No-SEP configuration | `SEP=0` build; SEP paths tied off | `-param SEP=0` | N/A (compile-time) |
| Debug/test | DTP TAP active, boot-stall/clock-stop asserted | JTAG instruction loaded | Reset or deselection |
| Interop | SMC↔SEP mailbox exchange | Both cores running | Test complete |
| Reset override | DTP IC_RESET TDR overriding downstream resets | IC_RESET override enabled | TRST/POR or override cleared |

## Clock and Reset

| Domain | Clock | Reset | Notes |
|--------|-------|-------|-------|
| Primary | `clk_smu_i` | `rst_primary_smc_clk_no` | SMC, SEP, DTP, crossbar, and IW converters all run here. |
| Reference | `clk_ref_i` | `rst_primary_ref_clk_no` | SMC ref-clk resets; `SEP=0` SEP-OTP error slave. |
| Peripheral | `clk_periph_i` | `rst_primary_periph_clk_no` | Peripheral logic; `gated_clk_periph_i3c_o` gated variant. |
| Telemetry | `clk_telemetry_i` | `rst_telemetry_ni` | Independent ATB telemetry domain. |
| SEP WDT | `clk_sep_wdt_i` | `rst_wdt_n` | SEP watchdog low-frequency domain. |

DTP uses `pwr_on_rst_ni = powergood_stable` (from SMC `powergood_stable_o`) as its
power-on reset. Tests must avoid fixing failures with arbitrary delays; CDC
ordering and reset behavior must be verified explicitly.

**CDC notes** (from `smu_rtl_suspected_issues.md`): the SEP=0 SEP-OTP error slave
sits on `clk_ref_i` while the driving DTP AXI-Lite is on `clk_smu_i` (review if
`clk_ref != clk_smu`); the SEP debug bus is synchronized as a 512-bit vector into
SMC; the crossbar `addr_map` is built combinationally from CSR base/size and is
not stability-checked against in-flight transactions.

## Error Handling

| Error Condition | Detection Mechanism | Expected Response |
|-----------------|---------------------|-------------------|
| Unmapped crossbar access (`ext_in`) | Address decode | DECERR (no default master port) |
| AXI atomic operation | `ATOPs=1'b0` | Rejected / not supported |
| SEP=0 SEP-OTP access | AXI-Lite error slave | DECERR (`0xBADCAB1E`) |
| Mailbox protocol mismatch | Scoreboard | Test fail |
| SEP WDT timeout | `sep_wdt_timer_rst_req` | SEP reset request into SMC |
| Lifecycle-gated debug | `dbg_disable_i` gating in DTP | Debug resource blocked (BYPASS fallback / no AXI traffic) |

## Security Considerations

The SEP lifecycle controller drives `dbg_disable_o` (`dbg_disable_t`) into DTP
`dbg_disable_i` to gate debug (STAP selection, iJTAG SIB access, the SMC fabric
JTAG2AXI bridge). The SMC and SEP OTP JTAG2AXI bridges remain enabled;
fuse-controller access control is the enforcement point.
SEP also drives `security_disable` into SMC and the lifecycle state (`lc_state_o`,
8 bits; `SEP=0` → `8'hf0`). The 256-bit `SEP_SEC_DISABLE_TOKEN` is passed to SEP,
tied `0` at SMU and replaced with the real digest at synthesis. eFuse gating and
the SMC↔SEP fuse-sense handshake (`fuse_sense_done`) are part of the security
bring-up. Open review items: SMC-egress SEP outbound traffic bypassing the SEP
outbound filter (ISSUE-16); SEP eFuse `shadow_regs` tied `0` at the wrapper
(ISSUE-9).

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `smu_pkg`, `smu_axi_xbar_pkg` | SMU config struct, crossbar topology and AXI typedefs |
| `smc_pkg`, `sep_pkg`, `dtp_pkg` | Sub-block widths, mailbox counts, cross-trigger defaults |
| `sep_efuse_pkg` | Lifecycle feature-control struct |
| `chipyard_4core_mem_pkg` | SMC CPU memory interface types |
| `hw/smu/rtl/{smu,smu_axi_xbar}.sv` | SMU core and crossbar RTL |
| `hw/smu/smu_wrappers/rtl/smu_wrapper.sv` | Integration wrapper (IP integration) |
| `axi_iw_converter`, `axi_window_remap`, `prim_axi_lite_err_slv` | Crossbar ID conversion, alias remap, SEP=0 error slave |
| `ocah_jtag_vip`, `ocah_axi_vip` | Unified OCAH JTAG and AXI/AXI-Lite BFM wrappers |

## Verification Alignment

Enrolled SMU open-source DV is defined by `hw/sys/smu/dv/testlists/*.toml`
(primarily `all.toml` for SEP=0 density and `wrapper.toml` for the production
wrapper baseline). The deferred / SEP=1 inventory is not ported
and is not reportable as PASS. Live stimulus and checkers are under
`hw/sys/smu/dv/cocotb/` and `hw/sys/smu/dv/cocotb_wrapper/`.
