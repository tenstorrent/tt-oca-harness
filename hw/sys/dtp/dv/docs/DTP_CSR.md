# DTP Register Reference

## Overview

DTP exposes state through two access mechanisms:

| Interface | Type | Access Method |
|-----------|------|---------------|
| JTAG TDRs | Scan-chain registers | Load 6-bit IR, then shift DR |
| XTRIG CSRs | AXI4-Lite memory-mapped registers | `axil_xtrig_*` subordinate |

Full register detail is maintained in `dv/dtp/doc/DTP_CSR.md`. This OCAH
open-source document summarizes the TDR/CSR behavior encoded in `env/dtp_types.py`
and used by the public verification plan.

## Register Sources

| Source | Path |
|--------|------|
| Reference CSR document | `dv/dtp/doc/DTP_CSR.md` |
| OCAH design spec | `doc/dist/ocah-documentation.pdf` (Chapter 7, Debug and Test Ports) |
| CTP SystemRDL | `hw/ip/cross_trigger_port/data/registers/rdl/cross_trigger_port.rdl` |
| CTM SystemRDL | `hw/ip/cross_trigger_matrix/data/registers/rdl/cross_trigger_matrix.rdl` |
| CTN SystemRDL | `hw/comp/cross_trigger_network/data/registers/rdl/cross_trigger_network.rdl` |
| Open-source encoders | `dv/oss/hw/sys/dtp/dv/env/dtp_types.py` |

## Part A: JTAG Instruction Data Registers

JTAG TDRs are not memory-mapped. They are selected by instruction register
opcode and shifted through the DR scan chain in IEEE 1149.1 TAP states.

### TDR Summary

| IR Opcode | Name | Width | Access | Description |
|-----------|------|-------|--------|-------------|
| `0x00` | BYPASS | 1 | RW scan | Mandatory 1-bit bypass |
| `0x01` | IDCODE | 32 | RO scan | Device ID read in smoke test |
| `0x02` | RUNBIST | BIST-dependent | Mixed | Built-in self-test path |
| `0x03` | SAMPLE_PRELOAD | BSR-dependent | Mixed | Boundary scan capture/preload |
| `0x04` | EXTEST | BSR-dependent | Mixed | Boundary scan external test |
| `0x05` | EXTEST_TRAIN | BSR-dependent | Mixed | AC boundary scan training |
| `0x06` | EXTEST_PULSE | BSR-dependent | Mixed | AC boundary scan pulse |
| `0x07` | CLAMP | 1 | Mixed | Clamp outputs and bypass data |
| `0x08` | HIGHZ | 1 | Mixed | Tri-state boundary outputs |
| `0x09` | INTEST | BSR-dependent | Mixed | Internal boundary scan |
| `0x0A` | CLAMP_HOLD | 2 | RW scan | TMP hold control |
| `0x0B` | CLAMP_RELEASE | 2 | RW scan | TMP release control |
| `0x0C` | TMP_STATUS | 2 | Mixed | TMP status and bypass escape |
| `0x0D` | IC_RESET | Variable | RW scan | JTAG reset override |
| `0x0E` | TAP_3DCR | 2 plus STAP chain | RW scan | IEEE 1838 3D configuration |
| `0x10`-`0x17` | *Reserved for RISC-V* | — | — | Reserved encodings (behave as BYPASS) |
| `0x18` | DEBUG_CONTROL | 5 | Mixed | Clock stop and boot stall |
| `0x19` | JTAG_CAPS | 60 | RO scan | DTP capability reporting |
| `0x1A` | SELECT_IJTAG | Variable | RW scan | iJTAG SIB selection |
| `0x1B` | SMC_OTP_JTAG2AXI_CAPS | 14 | RO scan | SMC OTP bridge caps |
| `0x1C` | SMC_OTP_AXI_SINGLE_OP | Variable | RW scan | SMC OTP single operation |
| `0x1D` | SMC_OTP_AXI_SERIES_CTRL | Variable | RW scan | SMC OTP series control |
| `0x1E` | SMC_OTP_AXI_SERIES_DATA_INCR | Variable | RW scan | SMC OTP series auto-increment |
| `0x1F` | SMC_OTP_AXI_SERIES_DATA_NO_INCR | Variable | RW scan | SMC OTP series no-increment |
| `0x20` | SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS | Variable | RW scan | SMC OTP series with error bit |
| `0x21` | SEP_OTP_JTAG2AXI_CAPS | 14 | RO scan | SEP OTP bridge caps |
| `0x22` | SEP_OTP_AXI_SINGLE_OP | Variable | RW scan | SEP OTP single operation |
| `0x23` | SEP_OTP_AXI_SERIES_CTRL | Variable | RW scan | SEP OTP series control |
| `0x24` | SEP_OTP_AXI_SERIES_DATA_INCR | Variable | RW scan | SEP OTP series auto-increment |
| `0x25` | SEP_OTP_AXI_SERIES_DATA_NO_INCR | Variable | RW scan | SEP OTP series no-increment |
| `0x26` | SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS | Variable | RW scan | SEP OTP series with error bit |
| `0x27` | SMC_JTAG2AXI_CAPS | 14 | RO scan | SMC fabric bridge caps |
| `0x28` | SMC_AXI_SINGLE_OP | 132 | RW scan | SMC fabric single read/write |
| `0x29` | SMC_AXI_SERIES_CTRL | Variable | RW scan | SMC fabric series control |
| `0x2A` | SMC_AXI_SERIES_DATA_INCR | Variable | RW scan | SMC fabric series auto-increment |
| `0x2B` | SMC_AXI_SERIES_DATA_NO_INCR | Variable | RW scan | SMC fabric series no-increment |
| `0x2C` | SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS | Variable | RW scan | SMC fabric series with error bit |
| `0x3D` | ZERO_LENGTH_BYPASS | 0 | RW scan | IEEE 1838 zero-length bypass |
| `0x3E` | INV_BYPASS | 1 | RW scan | Inverted bypass |
| `0x3F` | BYPASS | 1 | RW scan | Mandatory all-ones bypass |

All instruction encodings not explicitly listed above (including the `0x10`-`0x17`
range reserved for RISC-V) decode to the BYPASS instruction.

### IDCODE

| Bits | Field | Access | Description |
|------|-------|--------|-------------|
| `[31:28]` | `SI_REV` | RO | Silicon revision parameter |
| `[27:12]` | `PART_NUM` | RO | Chiplet part number parameter |
| `[11:1]` | `MFR_ID` | RO | JEDEC manufacturer ID parameter |
| `[0]` | `MARKER` | RO | Always `1` |

The open-source `dtp_jtag_idcode_test` verifies IDCODE readout through the primary TAP.

### TMP_STATUS

TMP_STATUS (IR=`0x0C`) is a 2-bit mixed-access TDR used by the TMP controller.

| Bits | Field | Access | Reset | Description |
|------|-------|--------|-------|-------------|
| `[1]` | `PERSISTENCE` | RO | `0` | TMP FSM Persistence-On status |
| `[0]` | `BYPASS_ESCAPE` | RW | `0` | Arm bit that lets a subsequent BYPASS selection exit TMP persistence |

The open-source `debug_tdr` group verifies reset readback, CLAMP_HOLD-driven
Persistence-On tracking, persistence across chip reset, BYPASS_ESCAPE arming,
BYPASS-triggered release, and side-effect-free reads using multiple DR shift values.

### DEBUG_CONTROL

| Bits | Field | Access | Reset | Description |
|------|-------|--------|-------|-------------|
| `[4]` | `CLA_CLOCK_STOP` | RO | `0` | Readback of CLA clock-stop request |
| `[3]` | `JTAG_CLOCK_STOP` | RW | `0` | JTAG-driven clock stop request |
| `[2]` | `CLA_CLOCK_STOP_EN` | RW | `0` | Exported CLA clock stop enable |
| `[1]` | `BOOT_STALL_OVRD` | RW | `0` | Enables JTAG boot-stall override |
| `[0]` | `BOOT_STALL` | RW | `0` | Boot-stall value when override is enabled |

The open-source `debug_tdr` group verifies reset value, JTAG clock-stop assertion
and release, CLA request readback, all boot-stall override/data combinations,
seeded clock-stop combinations, and independence between boot-stall and clock-stop
fields. Tests poll `stop_clks_o` across the synchronizer/output latency rather than
assuming an immediate same-cycle response.

### JTAG_CAPS

The JTAG_CAPS TDR (IR=`0x19`) is a 60-bit read-only register reporting the DTP
configuration. (The instruction-summary table historically lists 40 bits; the
authoritative field layout below spans `[59:0]`.)

| Bits | Field | Description |
|------|-------|-------------|
| `[59:54]` | `NUM_XTRIG_INT_CT` | Number of internal cross triggers |
| `[53:48]` | `NUM_XTRIG_CTP` | Number of Cross Trigger Ports |
| `[47:44]` | `NUM_XTRA_STAP` | Number of additional STAP interfaces |
| `[43]` | `STAP_IO_EN` | I/O STAP enabled |
| `[42]` | `SEP_DBG_EN` | SEP STAP enabled |
| `[41]` | `SMC_DBG_EN` | SMC JTAG2AXI enabled |
| `[40:33]` | `NUM_SMC_IC_RST` | SMC IC_RESET override ports |
| `[32:25]` | `NUM_SEP_IC_RST` | SEP IC_RESET override ports |
| `[24:17]` | `NUM_EXT_IC_RST` | External IC_RESET override ports |
| `[16]` | `IC_RST_INST_EN` | IC_RESET instruction enabled |
| `[15]` | `TMP_INST_EN` | TMP controller enabled |
| `[14]` | `RUNBIST_INST_EN` | RUNBIST enabled |
| `[13]` | `HIGHZ_INST_EN` | HIGHZ enabled |
| `[12]` | `CLAMP_INST_EN` | CLAMP enabled |
| `[11]` | `INTEST_INST_EN` | INTEST enabled |
| `[10]` | `EXTEST_PULSE_EN` | EXTEST_PULSE enabled |
| `[9]` | `EXTEST_TRAIN_EN` | EXTEST_TRAIN enabled |
| `[8]` | `BSR_INST_EN` | Mandatory boundary-scan instructions enabled |
| `[7:0]` | `OCH_VER` | DTP IP major version |

The open-source `dtp_dbg_jtag_caps_test` verifies the complete field layout,
multi-read stability, read-only behavior across directed and seeded-random write
attempts, and stability after IDCODE/BYPASS instruction switches.

### IC_RESET

The IC_RESET TDR (IR=`0x0D`) provides IEEE 1149.1-compliant reset overrides composed
of three independently-enabled slices — SMC (nearest TDI), SEP, and External
(nearest TDO) — each gated by `IC_RESET_{SMC,SEP,EXT}_ENABLE`. Each reset `i`
contributes `reset_control` (`[2i+2]`) and `reset_enable` (`[2i+1]`), and the register
ends with a single `reset_hold` (`[0]`). Total length is
`2*(NUM_SMC_IC_RESET + NUM_SEP_IC_RESET + NUM_EXT_IC_RESET) + 1`.

| Field | Polarity | Description |
|-------|----------|-------------|
| `reset_enable` | active-low (per 1149.1 §17) | `1` = JTAG override disabled (upstream reset passes through); `0` = override enabled |
| `reset_control` | active-low | Reset value driven while the override is enabled |
| `reset_hold` | — | When `0`, TLR does not clear the register; TRST/POR always clear it |

The PTAP exposes `ic_reset_ovrd_o[i] = !reset_enable[i]` (active-high "JTAG is
overriding this port") and `ic_reset_ctrl_n_o[i] = reset_control[i]` (active-low reset
value). Do not re-invert `ic_reset_ovrd_o` downstream.

The open-source `dtp_jtag_ic_reset_test` verifies the default all-ones value,
flattened SMC/SEP/EXT output polarity, deterministic per-slice override enable and
disable, reset_hold=0 TLR persistence, reset_hold=1 TLR default restore, seeded
random held patterns, and TRST default restore.

### JTAG2AXI Capabilities

Each bridge exposes a 14-bit read-only capabilities TDR.

| Bits | Field | Description |
|------|-------|-------------|
| `[13:12]` | `RD_PL_DEPTH` | Read pipeline depth |
| `[11:10]` | `WR_PL_DEPTH` | Write pipeline depth |
| `[9:7]` | `DATA_SIZE` | Data width as log2(bytes) |
| `[6:1]` | `ADDR_SIZE` | Address width in bits |
| `[0]` | `BUS_TYPE` | `0` = AXI4, `1` = AXI4-Lite |

The open-source `debug_tdr` group verifies SMC fabric, SMC OTP, and SEP OTP CAPS
TDRs for field decode, multi-read stability, read-only behavior across directed and
seeded-random write attempts, and stability after IDCODE/BYPASS instruction
switches. Bridge operation checks are described separately under JTAG2AXI tests.

### SMC Fabric AXI_SINGLE_OP

SMC fabric read/write access uses the bridge geometry derived from `dtp_pkg`:
56-bit address, 64-bit data, 8-bit write strobes.

| Bits | Field | Issue Meaning | Response Meaning |
|------|-------|---------------|------------------|
| `[1:0]` | `OP` | `0` NOP, `1` READ, `2` WRITE | `0` SUCCESS, `1` SLVERR, `2` DECERR, `3` BUSY_OR_FULL |
| `[3:2]` | `SIZE` | AXI transfer size | Captured transfer size |
| `[11:4]` | `WSTRB` | Byte strobes | Captured strobes |
| `[75:12]` | `DATA` | Write data | Read data or last data |
| `[131:76]` | `ADDR` | AXI address | Captured address |

The open-source driver encodes and decodes this TDR in `DtpJtagItem` helpers and polls
with NOP captures until the response status is no longer `BUSY_OR_FULL`.

### AXI Series Operations

Each bridge also provides a series instruction family for efficient block or polling
access: `*_AXI_SERIES_CTRL` preloads the start address plus `pl_depth` (read/write
pipeline depth), `size`, and `op`; `*_AXI_SERIES_DATA_INCR` performs the access and
auto-increments the address by `2**size`; `*_AXI_SERIES_DATA_NO_INCR` repeats the same
address (polling/triggering); and `*_AXI_SERIES_DATA_WITH_ERROR_STATUS` adds a
per-transaction increment/status bit for granular error reporting. Series error status
is sticky until cleared via `*_AXI_SERIES_CTRL.reset`.

## Part B: Cross Trigger Port CSRs

Each CTP instance has a 32-bit AXI-Lite register bank. These registers are
defined by SystemRDL. In the OCAH open-source Verilator flow, functional CSR
scenarios require the generated CSR blocks rather than stubs.

| Offset | Register | Access | Reset | Description |
|--------|----------|--------|-------|-------------|
| `0x000` | `CONFIG` | RW | `0x0000_0000` | Mode, invert, and reset control |
| `0x004` | `STATUS` | RO | `0x0000_0000` | Busy and live req/ack state |
| `0x008` | `STRETCH_MULT` | RW | `0x0000_0000` | Wire-OR pulse stretch multiplier |

### CTP CONFIG

| Bits | Field | Access | Description |
|------|-------|--------|-------------|
| `[2]` | `RESET` | RW | Force-clear P2P handshake state |
| `[1]` | `INVERT` | RW | Invert GPIO polarity. `0`: wire-OR active-low (pull-ups), P2P active-high. `1`: all I/Os inverted |
| `[0]` | `MODE` | RW | `0` wire-OR, `1` point-to-point |

### CTP STATUS

| Bits | Field | Access | Description |
|------|-------|--------|-------------|
| `[7]` | `ACK_OUT` | RO | Current CT_Ack_out |
| `[6]` | `REQ_IN` | RO | Synchronized CT_Req_in |
| `[5]` | `ACK_IN` | RO | Synchronized CT_Ack_in |
| `[4]` | `REQ_OUT` | RO | Current CT_Req_out |
| `[0]` | `BUSY` | RO | Pulse or handshake in progress |

## Part C: Cross Trigger Matrix CSRs

The CTM register bank provides one `CT_SRC[N]_CONFIG_0` register for each CTM
source port. In the default DTP configuration there are 26 ports: 16 CTP ports
and 10 internal CT ports.

| Offset Formula | Register | Access | Reset | Description |
|----------------|----------|--------|-------|-------------|
| `N * 0x08` | `CT_SRC[N]_CONFIG_0` | RW | `0x0000_0000` | Destination select mask for source `N` |

| Bits | Field | Access | Description |
|------|-------|--------|-------------|
| `[31:26]` | `RESERVED` | RW in generated block | Write zero |
| `[25:0]` | `CT_DST_SELECT` | RW | One bit per CT destination; multiple bits multicast |

CTM port indexing: ports `0 .. NUM_CTP-1` are the external CTPs and ports
`NUM_CTP .. NUM_CTP+NUM_INT_CT-1` are the internal CTs (default 26 ports = 16 CTPs +
10 internal CTs). Each output port `i` is driven by a `ctm_src_selector` computing
`ct_src[i] = |(ct_dst & CT_SRC[i]_CONFIG_0.CT_DST_SELECT)`, registered on `clk_i`.

## Register Verification Notes

| Topic | Requirement |
|-------|-------------|
| JTAG2AXI setup | Read capabilities before deriving TDR width for generic tests |
| JTAG2AXI polling | Poll response status until not busy; do not rely on fixed delay |
| Lifecycle gating | Verify gated TDRs fall back safely and do not issue AXI traffic |
| CTP setup | Program mode and stretch before injecting trigger events |
| CTM setup | Program routing masks before enabling source stimulus |
| CSR stubs | Drop Verilator stubs or use a Verilator-safe CSR implementation before sampling XTRIG CSR functional coverage |

## Access Type Legend

| Symbol | Meaning |
|--------|---------|
| RW | Read/write |
| RO | Read only |
| Mixed | Read/write behavior depends on field or TAP state |

## Revision History

| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0 | 2026-06-09 | DV Team | OCAH open-source CSR/TDR reference aligned with the DTP reference plan |
| 1.1 | 2026-06-14 | DV Team | Aligned with OCAH design spec (ocah-documentation.pdf, Chapter 7): corrected JTAG_CAPS to 60-bit with field map, added IC_RESET / AXI-series / CTM-routing detail, the RISC-V-reserved opcode range, and CTP INVERT semantics |
| 1.2 | 2026-06-22 | DV Team | Added TMP_STATUS, IC_RESET, DEBUG_CONTROL, JTAG_CAPS, and JTAG2AXI CAPS TDR verification notes for field, read-only, reset, and side-effect behavior |
