# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU JTAG / JTAG2AXI helpers.

Every opcode, field position and geometry constant in this module is a
DV-owned table. The instruction opcodes come from the DTP bench's
``dtp_types`` module; everything else is transcribed from the PTAP
architecture document, the SMU design specification and the Integrator
Guide, cited next to the value.
"""

from __future__ import annotations

from typing import Optional

import cocotb
from cocotb.triggers import ClockCycles
from dtp_types import DTP_IR_WIDTH, DtpJtagInstr
from ocah_jtag_vip import OcahJtagDevice, OcahJtagMasterDriver

from seq_lib.smu_tb_pins import smu_scope

# Lifecycle ungating: use seq_lib.smu_lcc_helpers (SEP=1 eFuse→LCC).


def dtp_ir_opcode(name: str) -> int:
    """PTAP IR opcode for instruction ``name``.

    ``DtpJtagInstr`` (hw/sys/dtp/dv/cocotb/env/dtp_types.py) transcribes the
    "Instruction Encodings" table of hw/ip/jtag/jtag_intf_unit/doc/interface.adoc.
    """
    try:
        return int(DtpJtagInstr[name])
    except KeyError as exc:
        raise KeyError(f"{name} is not a DtpJtagInstr instruction name") from exc


# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, "JTAG Capabilities" table.
DTP_JTAG_CAPS_SEP_DBG_EN_BIT = 42

# Same document, "JTAG2AXI Support" / "*_JTAG2AXI_CAPS" table:
#   [13:12] rd_pl_depth, [11:10] wr_pl_depth, [9:7] data_size (log2 of the
#   AxDATA width in bytes), [6:1] addr_size (AxADDR width in bits),
#   [0] bus_type (0: AXI4, 1: AXI4-Lite).
JTAG2AXI_CAPS_RD_PL_DEPTH_LSB = 12
JTAG2AXI_CAPS_WR_PL_DEPTH_LSB = 10
JTAG2AXI_CAPS_DATA_SIZE_LSB = 7
JTAG2AXI_CAPS_ADDR_SIZE_LSB = 1
JTAG2AXI_CAPS_BUS_TYPE_LSB = 0
JTAG2AXI_CAPS_DATA_SIZE_4B = 2
JTAG2AXI_CAPS_DATA_SIZE_8B = 3
JTAG2AXI_CAPS_BUS_AXI4 = 0
JTAG2AXI_CAPS_BUS_AXI4_LITE = 1

# doc/integrator/src/smu.adoc, "SMU Default Parameters": SMC_OTP_RD/WR_PL_DEPTH
# and SMC_RD/WR_PL_DEPTH default to 2'h3; the SEP OTP depths are fixed at 3.
SMU_JTAG2AXI_RD_PL_DEPTH = 3
SMU_JTAG2AXI_WR_PL_DEPTH = 3
# doc/integrator/src/smu.adoc, "AXI Interface Configuration": "a 56-bit address
# space with 64-bit data width".
# The fabric bridge is the AXI4 instance and the OTP bridges the AXI-Lite
# instances of the PTAP "Module Hierarchy" table; the OTP word is 32 bits
# (hw/ip/efuse/doc/interface.adoc) and the eFuse AXI-Lite interface is
# 32-bit (doc/integrator/src/smu.adoc, "eFuse Interface").
SMU_FABRIC_J2A_ADDR_BITS = 56
SMU_OTP_J2A_ADDR_BITS = 32


def pack_jtag2axi_caps(
    *,
    rd_pl: int,
    wr_pl: int,
    data_size: int,
    addr_size: int,
    bus_type: int,
) -> int:
    """Pack a 14-bit *_JTAG2AXI_CAPS word."""
    return (
        (int(rd_pl) << JTAG2AXI_CAPS_RD_PL_DEPTH_LSB)
        | (int(wr_pl) << JTAG2AXI_CAPS_WR_PL_DEPTH_LSB)
        | (int(data_size) << JTAG2AXI_CAPS_DATA_SIZE_LSB)
        | (int(addr_size) << JTAG2AXI_CAPS_ADDR_SIZE_LSB)
        | (int(bus_type) << JTAG2AXI_CAPS_BUS_TYPE_LSB)
    )


# IDCODE with every JTAG_IDCODE_* parameter at the default given in
# doc/integrator/src/smu.adoc, "SMU Default Parameters" (MFR_ID 11'h000,
# PART_NUM 16'h0000, SI_REV 4'h0): only the architecture.adoc "ID Code"
# marker bit (bit 0, always 1) is set.
DTP_DEFAULT_IDCODE = 0x0000_0001
DTP_IR_IDCODE = dtp_ir_opcode("IDCODE")
DTP_IR_DEBUG_CONTROL = dtp_ir_opcode("DEBUG_CONTROL")
DTP_IR_IC_RESET = dtp_ir_opcode("IC_RESET")
DTP_IR_EXTEST = dtp_ir_opcode("EXTEST")
DTP_IR_SAMPLE_PRELOAD = dtp_ir_opcode("SAMPLE_PRELOAD")
DTP_IR_TAP_3DCR = dtp_ir_opcode("TAP_3DCR")

# SEP=0 SMU STAP chain: gen_stap_io + gen_stap_smc_dbg + extra[0] (no SEP STAP).
# DTP TB STAP_ORDER includes "sep"; SMU cannot import env.dtp_scan_ref_model
# (python_root env/ is SMU). Packing matches dtp_scan_base_test_seq.select_stap.
SMU_STAP_ORDER = ("io", "smc", "extra0")
PTAP_3DCR_WIDTH = 2
STAP_3DCR_WIDTH = 3


def ptap_3dcr_value(*, config_hold: int, select: int) -> int:
    """LSB-first PTAP 3DCR: config_hold then stap_select (DtpStap3dcrModel)."""
    return (config_hold & 0x1) | ((select & 0x1) << 1)


def stap_sib_pattern(name: str, enabled: int = 1) -> int:
    idx = SMU_STAP_ORDER.index(name)
    return (enabled & 0x1) << (len(SMU_STAP_ORDER) - 1 - idx)


def stap_3dcr_payload(*, config_hold: int, stap_sel: int, tms_hold: int) -> int:
    """LSB-first STAP 3DCR: config_hold, stap_sel, tms_hold."""
    return (config_hold & 0x1) | ((stap_sel & 0x1) << 1) | ((tms_hold & 0x1) << 2)


def stap_3dcr_scan_word(
    name: str,
    *,
    config_hold: int,
    stap_sel: int,
    tms_hold: int,
    close_sib: int = 0,
) -> tuple[int, int]:
    """SIB bits then 3-bit 3DCR; width = len(SMU_STAP_ORDER) + STAP_3DCR_WIDTH."""
    payload = stap_3dcr_payload(config_hold=config_hold, stap_sel=stap_sel, tms_hold=tms_hold)
    value = (close_sib & 0x1) << (len(SMU_STAP_ORDER) - 1 - SMU_STAP_ORDER.index(name))
    value |= payload << len(SMU_STAP_ORDER)
    return value, len(SMU_STAP_ORDER) + STAP_3DCR_WIDTH


def ptap_prefixed(
    stap_word: int, stap_width: int, *, config_hold: int = 1, select: int = 1
) -> tuple[int, int]:
    """Prefix PTAP 3DCR bits so TAP_3DCR DR shifts do not clear stap_select.

    Scan order is TDI -> 2-bit PTAP 3DCR -> STAP SIB chain. LSB-first, so
    the PTAP field lives in the MSBs of the combined word.
    """
    ptap = ptap_3dcr_value(config_hold=config_hold, select=select)
    return (ptap << stap_width) | (stap_word & ((1 << stap_width) - 1)), (
        PTAP_3DCR_WIDTH + stap_width
    )


DTP_IR_SMC_AXI_SINGLE_OP = dtp_ir_opcode("SMC_AXI_SINGLE_OP")
DTP_IR_SMC_JTAG2AXI_CAPS = dtp_ir_opcode("SMC_JTAG2AXI_CAPS")
DTP_IR_SMC_AXI_SERIES_CTRL = dtp_ir_opcode("SMC_AXI_SERIES_CTRL")
DTP_IR_SMC_AXI_SERIES_DATA_INCR = dtp_ir_opcode("SMC_AXI_SERIES_DATA_INCR")
DTP_IR_SMC_OTP_JTAG2AXI_CAPS = dtp_ir_opcode("SMC_OTP_JTAG2AXI_CAPS")
DTP_IR_SMC_OTP_AXI_SINGLE_OP = dtp_ir_opcode("SMC_OTP_AXI_SINGLE_OP")
DTP_IR_SMC_OTP_AXI_SERIES_CTRL = dtp_ir_opcode("SMC_OTP_AXI_SERIES_CTRL")
DTP_IR_SMC_OTP_AXI_SERIES_DATA_NO_INCR = dtp_ir_opcode("SMC_OTP_AXI_SERIES_DATA_NO_INCR")
DTP_IR_SEP_OTP_JTAG2AXI_CAPS = dtp_ir_opcode("SEP_OTP_JTAG2AXI_CAPS")
DTP_IR_SEP_OTP_AXI_SINGLE_OP = dtp_ir_opcode("SEP_OTP_AXI_SINGLE_OP")
DTP_IR_JTAG_CAPS = dtp_ir_opcode("JTAG_CAPS")
# IEEE 1149.1 all-ones BYPASS encoding; the instruction table also decodes
# 0x00 as BYPASS.
DTP_IR_BYPASS = dtp_ir_opcode("BYPASS_3F")
DTP_DEBUG_CONTROL_LEN = 5
DTP_JTAG2AXI_CAPS_LEN = 14
DTP_JTAG_CAPS_LEN = 60
# Compact OSS BSR loopback model (scan_in <- scan_out); matches DTP OSS.
DTP_BSR_MODEL_LEN = 8
# The 6-bit IR decodes to a 64-wide one-hot bus indexed by opcode
# (architecture.adoc "Module Hierarchy", jtag_inst_reg).
DTP_EXTEST_DECODED_BIT = DTP_IR_EXTEST

# IC_RESET TDR. architecture.adoc "IC_RESET Support" gives the per-port
# layout: bit 0 reset_hold, port n at {reset_enable: 2n+1, reset_control:
# 2n+2}, every bit resetting to 1 (reset_enable=1 is "override disabled"),
# length 2 * ports + 1. doc/integrator/src/smu.adoc "IC_RESET TDR
# Structure" gives the SMU composition: TDI -> SMC slice (68 ports) -> SEP
# slice (0 ports at SEP=0, SMU_IC_RESET_NUM_SEP_PORTS_AT_SEP1 at SEP=1) ->
# external slice -> reset_hold -> TDO, so with LSB-first shifting port 0 is
# the external port and the SMC slice follows.
# The slice widths have to match the DUT exactly: a DR shorter than the TDR by
# 2k bits lands every packed field k ports away from the one it names.
# "SMC slice (TDI to TDO)" lists ss_warm_reset_n[31:0], ss_cold_reset_n[31:0],
# cold, cool, warm, fuse (nearest the SEP slice), [31] nearer TDI than [0]:
# counted from the TDO end that is fuse, warm, cool, cold, ss_cold[0..31],
# ss_warm[0..31]. The external slice type is adopter-defined; the SMU bench
# elaborates one port.
SMU_IC_RESET_NUM_SMC_PORTS = 68
# doc/integrator/src/smu.adoc "SEP slice (TDI to TDO)": the ports the SEP
# slice carries at SEP=1, in scan order from TDI (abr_jtag_rst_n) to the
# external slice (km_jtag_rst_n). The same document's "IC_RESET TDR
# Structure" table gives the slice 8 ports at SEP=1 and 0 otherwise, so the
# count is this tuple's length. A port added to the SEP slice moves every
# SMC port index up by one.
SMU_IC_RESET_SEP_PORTS = (
    "abr_jtag_rst_n",
    "trng_jtag_rst_n",
    "sep_reset_n",
    "kmac_jtag_rst_n",
    "hmac_jtag_rst_n",
    "aes_jtag_rst_n",
    "otbn_jtag_rst_n",
    "km_jtag_rst_n",
)
SMU_IC_RESET_NUM_SEP_PORTS_AT_SEP1 = len(SMU_IC_RESET_SEP_PORTS)


def _smu_ic_reset_sep_ports() -> int:
    """SEP IC_RESET slice width for the DUT this run elaborated.

    doc/integrator/src/smu.adoc "IC_RESET TDR Structure" enables the SEP
    slice only at SEP=1. The wrapper (tb_wrapper_top.sv, top module
    smu_wrapper_uvm_top) elaborates SEP=1 and carries the full SEP slice.
    Resolved from the cocotb top handle; outside a simulation, or under any
    other top, it falls back to the SEP=0 shape.
    """
    try:
        name = str(getattr(cocotb.top, "_name", "") or "")
    except Exception:  # noqa: BLE001 - no simulator, e.g. tooling imports
        return 0
    return SMU_IC_RESET_NUM_SEP_PORTS_AT_SEP1 if name == "smu_wrapper_uvm_top" else 0


SMU_IC_RESET_NUM_SEP_PORTS = _smu_ic_reset_sep_ports()
SMU_IC_RESET_NUM_EXT_PORTS = 1
SMU_IC_RESET_NUM_PORTS = (
    SMU_IC_RESET_NUM_SMC_PORTS + SMU_IC_RESET_NUM_SEP_PORTS + SMU_IC_RESET_NUM_EXT_PORTS
)
SMU_IC_RESET_LEN = 2 * SMU_IC_RESET_NUM_PORTS + 1
SMU_IC_RESET_DEFAULT = (1 << SMU_IC_RESET_LEN) - 1
SMU_IC_RESET_EXT_PORT = 0
SMU_IC_RESET_SMC_FUSE_PORT = SMU_IC_RESET_NUM_EXT_PORTS + SMU_IC_RESET_NUM_SEP_PORTS
SMU_IC_RESET_SMC_WARM_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 1
SMU_IC_RESET_SMC_COOL_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 2
SMU_IC_RESET_SMC_COLD_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 3
SMU_IC_RESET_SMC_SS_COLD0_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 4
SMU_IC_RESET_SMC_SS_WARM0_PORT = SMU_IC_RESET_SMC_SS_COLD0_PORT + 32


def ic_reset_enable_bit(port: int) -> int:
    """TDR bit of a port's reset_enable field."""
    return 1 + 2 * int(port)


def ic_reset_control_bit(port: int) -> int:
    """TDR bit of a port's reset_control field."""
    return 2 + 2 * int(port)


SMC_DBG_SINGLE_OP_LEN = 132  # OP2|SIZE2|WSTRB8|DATA64|ADDR56
SMC_DBG_AXSIZE_8B = 3
SMC_DBG_AXSIZE_4B = 2
# SMC fabric SERIES_CTRL: OP2|SIZE2|PL_DEPTH2|ADDR56|RESET1 = 63
SMC_DBG_SERIES_CTRL_LEN = 63
# SERIES_DATA_* payload for AxSIZE=8B.
SMC_DBG_SERIES_DATA_LEN = 64
# OTP bridge: OP2|SIZE2|WSTRB4|DATA32|ADDR32 = 72
SMC_OTP_SINGLE_OP_LEN = 72
# OTP SERIES_CTRL: OP2|SIZE2|PL_DEPTH2|ADDR32|RESET1 = 39
SMC_OTP_SERIES_CTRL_LEN = 39
# OTP SERIES_DATA_NO_INCR payload for AxSIZE=4B (default OTP size).
SMC_OTP_SERIES_DATA_NO_INCR_LEN = 32
SMC_OTP_AXSIZE_4B = 2
# hw/ip/efuse/doc/architecture.adoc, "Access Permissions and Security": the
# eFuse controller's error slave answers with data 0xbadcab1e.
SMC_OTP_ERR_DECODE_DATA = 0xBADC_AB1E
# Relative OTP probe (routes to the SHIM when the MAP base is absolute).
SMC_OTP_DEFAULT_PROBE_ADDR = 0x80

# hw/ip/jtag/jtag_ptap/doc/architecture.adoc Debug Control TDR table:
# bit 0 boot_stall, bit 1 boot_stall_ovrd (no PeakRDL #define).
DBG_BOOT_STALL_BIT = 0
DBG_BOOT_STALL_OVRD_BIT = 1
DBG_CLA_CLOCK_STOP_EN_BIT = 2
DBG_JTAG_CLOCK_STOP_BIT = 3
DBG_CLA_CLOCK_STOP_BIT = 4  # status readback (CLA / CTN OR)

J2A_OP_NOP = 0
J2A_OP_READ = 1
J2A_OP_WRITE = 2
J2A_STATUS_SUCCESS = 0
J2A_STATUS_SLVERR = 1
J2A_STATUS_DECERR = 2
J2A_STATUS_BUSY = 3

DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS = pack_jtag2axi_caps(
    rd_pl=SMU_JTAG2AXI_RD_PL_DEPTH,
    wr_pl=SMU_JTAG2AXI_WR_PL_DEPTH,
    data_size=JTAG2AXI_CAPS_DATA_SIZE_4B,
    addr_size=SMU_OTP_J2A_ADDR_BITS,
    bus_type=JTAG2AXI_CAPS_BUS_AXI4_LITE,
)
DTP_EXPECTED_SEP_OTP_JTAG2AXI_CAPS = DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS
DTP_EXPECTED_SMC_JTAG2AXI_CAPS = pack_jtag2axi_caps(
    rd_pl=SMU_JTAG2AXI_RD_PL_DEPTH,
    wr_pl=SMU_JTAG2AXI_WR_PL_DEPTH,
    data_size=JTAG2AXI_CAPS_DATA_SIZE_8B,
    addr_size=SMU_FABRIC_J2A_ADDR_BITS,
    bus_type=JTAG2AXI_CAPS_BUS_AXI4,
)


def pack_ic_reset_ports(
    *,
    reset_hold: int = 1,
    port_enable: dict[int, int] | None = None,
    port_control: dict[int, int] | None = None,
) -> int:
    """Pack the SMU IC_RESET TDR by port index (SMU_IC_RESET_*_PORT)."""
    value = SMU_IC_RESET_DEFAULT & ~0x1
    value |= reset_hold & 0x1
    for idx, en in (port_enable or {}).items():
        bit = ic_reset_enable_bit(idx)
        value = (value & ~(1 << bit)) | ((en & 0x1) << bit)
    for idx, ctrl in (port_control or {}).items():
        bit = ic_reset_control_bit(idx)
        value = (value & ~(1 << bit)) | ((ctrl & 0x1) << bit)
    return value & SMU_IC_RESET_DEFAULT


def pack_debug_control(
    *,
    boot_stall: int = 0,
    boot_stall_ovrd: int = 0,
    cla_clock_stop_en: int = 0,
    jtag_clock_stop: int = 0,
) -> int:
    return (
        ((boot_stall & 0x1) << DBG_BOOT_STALL_BIT)
        | ((boot_stall_ovrd & 0x1) << DBG_BOOT_STALL_OVRD_BIT)
        | ((cla_clock_stop_en & 0x1) << DBG_CLA_CLOCK_STOP_EN_BIT)
        | ((jtag_clock_stop & 0x1) << DBG_JTAG_CLOCK_STOP_BIT)
    )


def pack_single_op(
    op: int,
    addr: int,
    data: int = 0,
    wstrb: int = 0,
    size: int = SMC_DBG_AXSIZE_8B,
) -> int:
    """Pack SMC_AXI_SINGLE_OP DR (LSB-first): OP|SIZE|WSTRB|DATA|ADDR."""
    return (
        (int(op) & 0x3)
        | ((size & 0x3) << 2)
        | ((wstrb & 0xFF) << 4)
        | ((data & ((1 << 64) - 1)) << 12)
        | ((addr & ((1 << 56) - 1)) << 76)
    )


def unpack_single_op(value: int) -> tuple[int, int]:
    """Return (status, rdata) from captured SINGLE_OP DR."""
    status = int(value) & 0x3
    rdata = (int(value) >> 12) & ((1 << 64) - 1)
    return status, rdata


def apply_axi_wstrb(prev: int, data: int, wstrb: int, nbytes: int) -> int:
    """Merge ``data`` into ``prev`` for each set WSTRB lane in ``nbytes``."""
    out = int(prev)
    for byte_idx in range(nbytes):
        if (wstrb >> byte_idx) & 1:
            shift = 8 * byte_idx
            out = (out & ~(0xFF << shift)) | (((int(data) >> shift) & 0xFF) << shift)
    return out


def pack_smc_series_ctrl(
    op: int,
    addr: int,
    *,
    pipeline_depth: int = 1,
    size: int = SMC_DBG_AXSIZE_8B,
    reset: int = 0,
) -> int:
    """Pack SMC_AXI_SERIES_CTRL DR: OP|SIZE|PL_DEPTH|ADDR56|RESET."""
    return (
        (int(op) & 0x3)
        | ((size & 0x3) << 2)
        | ((pipeline_depth & 0x3) << 4)
        | ((addr & ((1 << 56) - 1)) << 6)
        | ((reset & 0x1) << 62)
    )


def unpack_smc_series_ctrl(value: int) -> tuple[int, int, int, int, int]:
    """Return (reset, addr, pipeline_depth, size, status) from SERIES_CTRL."""
    status = int(value) & 0x3
    size = (int(value) >> 2) & 0x3
    pipeline_depth = (int(value) >> 4) & 0x3
    addr = (int(value) >> 6) & ((1 << 56) - 1)
    reset = (int(value) >> 62) & 0x1
    return reset, addr, pipeline_depth, size, status


def smc_series_data_mask(size: int = SMC_DBG_AXSIZE_8B) -> int:
    return (1 << (8 * (1 << size))) - 1


def make_smu_jtag_tap(dut, period_ns: float) -> OcahJtagMasterDriver:
    """Build OcahJtagMasterDriver with DEBUG_CONTROL + SMC JTAG2AXI register map."""
    device = OcahJtagDevice(
        name="smu_ptap",
        idcode=DTP_DEFAULT_IDCODE,
        ir_width=DTP_IR_WIDTH,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, DTP_IR_IDCODE)
    device.add_reg("DEBUG_CONTROL", DTP_DEBUG_CONTROL_LEN, DTP_IR_DEBUG_CONTROL, write=True)
    device.add_reg("JTAG_CAPS", DTP_JTAG_CAPS_LEN, DTP_IR_JTAG_CAPS)
    device.add_reg("IC_RESET", SMU_IC_RESET_LEN, DTP_IR_IC_RESET, write=True)
    device.add_reg("EXTEST", DTP_BSR_MODEL_LEN, DTP_IR_EXTEST, write=True)
    device.add_reg("SMC_JTAG2AXI_CAPS", DTP_JTAG2AXI_CAPS_LEN, DTP_IR_SMC_JTAG2AXI_CAPS)
    device.add_reg(
        "SMC_AXI_SINGLE_OP",
        SMC_DBG_SINGLE_OP_LEN,
        DTP_IR_SMC_AXI_SINGLE_OP,
        write=True,
    )
    device.add_reg(
        "SMC_AXI_SERIES_CTRL",
        SMC_DBG_SERIES_CTRL_LEN,
        DTP_IR_SMC_AXI_SERIES_CTRL,
        write=True,
    )
    device.add_reg(
        "SMC_AXI_SERIES_DATA_INCR",
        SMC_DBG_SERIES_DATA_LEN,
        DTP_IR_SMC_AXI_SERIES_DATA_INCR,
        write=True,
    )
    device.add_reg(
        "SMC_OTP_JTAG2AXI_CAPS",
        DTP_JTAG2AXI_CAPS_LEN,
        DTP_IR_SMC_OTP_JTAG2AXI_CAPS,
    )
    device.add_reg(
        "SMC_OTP_AXI_SINGLE_OP",
        SMC_OTP_SINGLE_OP_LEN,
        DTP_IR_SMC_OTP_AXI_SINGLE_OP,
        write=True,
    )
    device.add_reg(
        "SMC_OTP_AXI_SERIES_CTRL",
        SMC_OTP_SERIES_CTRL_LEN,
        DTP_IR_SMC_OTP_AXI_SERIES_CTRL,
        write=True,
    )
    device.add_reg(
        "SMC_OTP_AXI_SERIES_DATA_NO_INCR",
        SMC_OTP_SERIES_DATA_NO_INCR_LEN,
        DTP_IR_SMC_OTP_AXI_SERIES_DATA_NO_INCR,
        write=True,
    )
    device.add_reg(
        "SEP_OTP_JTAG2AXI_CAPS",
        DTP_JTAG2AXI_CAPS_LEN,
        DTP_IR_SEP_OTP_JTAG2AXI_CAPS,
    )
    device.add_reg(
        "SEP_OTP_AXI_SINGLE_OP",
        SMC_OTP_SINGLE_OP_LEN,
        DTP_IR_SEP_OTP_AXI_SINGLE_OP,
        write=True,
    )
    jtag = OcahJtagMasterDriver(
        dut,
        name="smu_ptap",
        tck_period_ns=period_ns,
        ir_width=DTP_IR_WIDTH,
        tap_type="ptap",
        signal_map={
            "tck": "jtag_tck",
            "tms": "jtag_tms",
            "tdi": "jtag_tdi",
            "tdo": "jtag_tdo",
            "trst": "jtag_trst",
            "tdo_oen": "jtag_tdo_oen",
        },
    )
    jtag.add_device(device)
    jtag.init_signals()
    return jtag


# smc_pkg::jtag_smc_reset_ctrl_t as doc/integrator/src/smu.adoc describes it
# ("IC_RESET TDR Structure", "SMC slice (TDI to TDO)"): a packed struct of an
# `.ovrd` half above a `.val` half, each one bit per SMC port, whose fields
# are declared in TDI-to-TDO order -- ss_warm_reset_n[31:0],
# ss_cold_reset_n[31:0], cold, cool, warm, fuse. A packed struct places its
# first-declared field at the MSB, so within each half fuse_reset_n is bit 0
# and ss_warm_reset_n[31] the top bit.
_SMC_RESET_CTRL_HALF_BITS = SMU_IC_RESET_NUM_SMC_PORTS
_SMC_RESET_CTRL_VAL_LSB = 0
_SMC_RESET_CTRL_OVRD_LSB = _SMC_RESET_CTRL_HALF_BITS
_SMC_RESET_CTRL_FIELD_LSB = {
    "fuse_reset_n": 0,
    "warm_reset_n": 1,
    "cool_reset_n": 2,
    "cold_reset_n": 3,
    "ss_cold_reset_n": 4,
    "ss_warm_reset_n": 36,
}
_SMC_RESET_CTRL_SS_WIDTH = 32
_SMC_RESET_CTRL_SCALAR_LEAVES = (
    "fuse_reset_n_ovrd",
    "warm_reset_n_ovrd",
    "cool_reset_n_ovrd",
    "cold_reset_n_ovrd",
    "fuse_reset_n_val",
    "warm_reset_n_val",
    "cool_reset_n_val",
    "cold_reset_n_val",
)


def _smc_reset_ctrl_split(leaf: str) -> tuple[str, str]:
    """Split ``<field>_ovrd`` / ``<field>_val`` into (field, half)."""
    for half in ("ovrd", "val"):
        suffix = f"_{half}"
        if leaf.endswith(suffix):
            return leaf[: -len(suffix)], half
    raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")


def smc_reset_ctrl_packed_bit(leaf: str, idx: int | None = None) -> int:
    """Bit index of a leaf in the packed jtag_smc_reset_ctrl_t word."""
    field, half = _smc_reset_ctrl_split(leaf)
    if field not in _SMC_RESET_CTRL_FIELD_LSB:
        raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")
    base = _SMC_RESET_CTRL_OVRD_LSB if half == "ovrd" else _SMC_RESET_CTRL_VAL_LSB
    if field.startswith("ss_"):
        if idx is None or idx < 0 or idx >= _SMC_RESET_CTRL_SS_WIDTH:
            raise AssertionError(f"ss reset index out of range: {idx}")
        return base + _SMC_RESET_CTRL_FIELD_LSB[field] + idx
    if idx is not None:
        raise AssertionError(f"{leaf} is scalar; idx={idx} not allowed")
    return base + _SMC_RESET_CTRL_FIELD_LSB[field]


def _ss_reset_ctrl_bit_index(leaf: str, idx: int) -> int:
    """Packed bit index for ss_cold/ss_warm ovrd/val[idx]."""
    if not leaf.startswith("ss_"):
        raise AssertionError(f"Unknown ss reset leaf: {leaf}")
    return smc_reset_ctrl_packed_bit(leaf, idx)


def _sample_bit(signal, name: str) -> int:
    """Resolve a Logic signal to 0/1; fail closed on X/Z."""
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val) & 1


_RESET_CTRL_BRANCH_LOGGED: set[tuple[str, str]] = set()


def _log_reset_ctrl_branch(leaf: str, idx: int | None, branch: str) -> None:
    """Log which access path served a jtag_smc_reset_ctrl read.

    The first read of each (leaf, branch) pair goes to INFO so the kept log
    shows whether a verdict rested on the hierarchical leaf or on the
    DV-owned packed layout; repeats go to DEBUG.
    """
    where = leaf if idx is None else f"{leaf}[{idx}]"
    msg = f"jtag_smc_reset_ctrl read {where} via {branch}"
    key = (leaf, branch)
    if key in _RESET_CTRL_BRANCH_LOGGED:
        cocotb.log.debug(msg)
        return
    _RESET_CTRL_BRANCH_LOGGED.add(key)
    cocotb.log.info(msg)


def read_smc_reset_ctrl_bit(dut, leaf: str, idx: int | None = None) -> int:
    """Read one jtag_smc_reset_ctrl ovrd/val leaf.

    For scalar fuse/warm/cool/cold leaves, pass ``leaf`` only.
    For ss_* vectors, pass ``leaf`` + ``idx`` (0..31).

    The hierarchical leaf is read first (``ctrl.<half>.<field>[idx]``, then
    the vector's own bit ``idx``); only when the simulator exposes neither is
    the whole struct read and the bit taken from the DV-owned packed layout.
    Every read logs the branch it took.
    """
    ctrl = smu_scope(dut).jtag_smc_reset_ctrl
    if idx is None and leaf not in _SMC_RESET_CTRL_SCALAR_LEAVES:
        raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")
    field, half = _smc_reset_ctrl_split(leaf)
    bit = smc_reset_ctrl_packed_bit(leaf, idx)
    name = f"jtag_smc_reset_ctrl.{half}.{field}" + ("" if idx is None else f"[{idx}]")

    if hasattr(ctrl, half):
        group = getattr(ctrl, half)
        if hasattr(group, field):
            handle = getattr(group, field)
            if idx is None:
                _log_reset_ctrl_branch(leaf, idx, "hierarchical leaf")
                return _sample_bit(handle, name)
            try:
                elem = handle[idx]
            except Exception:  # noqa: BLE001
                elem = None
            if elem is not None:
                try:
                    value = _sample_bit(elem, name)
                except AssertionError:
                    raise
                except Exception:  # noqa: BLE001
                    value = None
                if value is not None:
                    _log_reset_ctrl_branch(leaf, idx, "hierarchical leaf element")
                    return value
            vec = handle.value
            if not vec.is_resolvable:
                raise AssertionError(f"X/Z sample on {name}: {vec}")
            _log_reset_ctrl_branch(leaf, idx, "hierarchical leaf vector bit")
            return (int(vec) >> idx) & 1

    packed = ctrl.value
    if not packed.is_resolvable:
        raise AssertionError(f"X/Z sample on jtag_smc_reset_ctrl (packed) for {name}: {packed}")
    _log_reset_ctrl_branch(leaf, idx, f"packed struct bit {bit} (DV table)")
    return (int(packed) >> bit) & 1


def pack_otp_single_op(
    op: int,
    addr: int,
    data: int = 0,
    wstrb: int = 0,
    size: int = SMC_OTP_AXSIZE_4B,
) -> int:
    """Pack SMC_OTP_AXI_SINGLE_OP DR: OP|SIZE|WSTRB|DATA32|ADDR32."""
    return (
        (int(op) & 0x3)
        | ((size & 0x3) << 2)
        | ((wstrb & 0xF) << 4)
        | ((data & ((1 << 32) - 1)) << 8)
        | ((addr & ((1 << 32) - 1)) << 40)
    )


def unpack_otp_single_op(value: int) -> tuple[int, int]:
    """Return (status, rdata) from captured OTP SINGLE_OP DR."""
    status = int(value) & 0x3
    rdata = (int(value) >> 8) & ((1 << 32) - 1)
    return status, rdata


def pack_otp_series_ctrl(
    op: int,
    addr: int,
    *,
    pipeline_depth: int = 1,
    size: int = SMC_OTP_AXSIZE_4B,
    reset: int = 0,
) -> int:
    """Pack SMC_OTP_AXI_SERIES_CTRL DR: OP|SIZE|PL_DEPTH|ADDR32|RESET."""
    return (
        (int(op) & 0x3)
        | ((size & 0x3) << 2)
        | ((pipeline_depth & 0x3) << 4)
        | ((addr & ((1 << 32) - 1)) << 6)
        | ((reset & 0x1) << 38)
    )


def unpack_otp_series_ctrl(value: int) -> tuple[int, int, int, int, int]:
    """Return (reset, addr, pipeline_depth, size, status) from SERIES_CTRL."""
    status = int(value) & 0x3
    size = (int(value) >> 2) & 0x3
    pipeline_depth = (int(value) >> 4) & 0x3
    addr = (int(value) >> 6) & ((1 << 32) - 1)
    reset = (int(value) >> 38) & 0x1
    return reset, addr, pipeline_depth, size, status


def otp_series_data_mask(size: int = SMC_OTP_AXSIZE_4B) -> int:
    return (1 << (8 * (1 << size))) - 1


async def otp_jtag2axi_series_ctrl(
    jtag: OcahJtagMasterDriver,
    op: int,
    addr: int,
    *,
    pipeline_depth: int = 1,
    size: int = SMC_OTP_AXSIZE_4B,
    reset: int = 0,
) -> None:
    raw = pack_otp_series_ctrl(op, addr, pipeline_depth=pipeline_depth, size=size, reset=reset)
    await jtag.write("SMC_OTP_AXI_SERIES_CTRL", raw)
    require_jtag_tdo_resolved(f"OTP SERIES_CTRL issue op={op} @0x{addr:08x}")


async def otp_jtag2axi_series_ctrl_status(
    jtag: OcahJtagMasterDriver,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 64,
    require_complete: bool = False,
) -> tuple[int, int, int, int, int]:
    """Poll SERIES_CTRL until status leaves BUSY. Returns unpack_otp_series_ctrl."""
    decoded = (0, 0, 0, size, J2A_STATUS_BUSY)
    nop = pack_otp_series_ctrl(J2A_OP_NOP, 0, pipeline_depth=0, size=size)
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_OTP_AXI_SERIES_CTRL", shift_value=nop)
        require_jtag_tdo_resolved("OTP SERIES_CTRL poll")
        decoded = unpack_otp_series_ctrl(capt)
        if decoded[4] != J2A_STATUS_BUSY:
            return decoded
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete:
        raise TimeoutError(
            f"OTP SERIES_CTRL stuck BUSY after {poll_limit} polls status={decoded[4]}"
        )
    return decoded


async def otp_jtag2axi_series_data_no_incr(
    jtag: OcahJtagMasterDriver,
    data: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
) -> int:
    """Shift OTP SERIES_DATA_NO_INCR; return captured TDO payload."""
    mask = otp_series_data_mask(size)
    if 8 * (1 << size) != SMC_OTP_SERIES_DATA_NO_INCR_LEN:
        raise AssertionError(
            f"OTP series data width {8 * (1 << size)} != registered "
            f"{SMC_OTP_SERIES_DATA_NO_INCR_LEN}"
        )
    capt = await jtag.read("SMC_OTP_AXI_SERIES_DATA_NO_INCR", shift_value=data & mask)
    require_jtag_tdo_resolved("OTP SERIES_DATA_NO_INCR")
    return int(capt) & mask


async def otp_jtag2axi_series_no_incr_write(
    jtag: OcahJtagMasterDriver,
    addr: int,
    data: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    pipeline_depth: int = 1,
    poll_limit: int = 64,
) -> int:
    """Series NO_INCR write; return SERIES_CTRL status."""
    mask = otp_series_data_mask(size)
    await otp_jtag2axi_series_ctrl(
        jtag, J2A_OP_WRITE, addr, pipeline_depth=pipeline_depth, size=size
    )
    await otp_jtag2axi_series_data_no_incr(jtag, data & mask, size=size)
    await ClockCycles(cocotb.top.clk_smu_i, 64)
    *_, status = await otp_jtag2axi_series_ctrl_status(
        jtag, size=size, poll_limit=poll_limit, require_complete=True
    )
    return status


async def otp_jtag2axi_series_no_incr_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    pipeline_depth: int = 1,
    poll_limit: int = 64,
) -> tuple[int, int]:
    """Series NO_INCR read; return (status, rdata)."""
    await otp_jtag2axi_series_ctrl(
        jtag, J2A_OP_READ, addr, pipeline_depth=pipeline_depth, size=size
    )
    await otp_jtag2axi_series_data_no_incr(jtag, 0, size=size)
    await ClockCycles(cocotb.top.clk_smu_i, 64)
    *_, status = await otp_jtag2axi_series_ctrl_status(
        jtag, size=size, poll_limit=poll_limit, require_complete=True
    )
    rdata = await otp_jtag2axi_series_data_no_incr(jtag, 0, size=size)
    return status, rdata


async def jtag2axi_single_write(
    jtag: OcahJtagMasterDriver,
    addr: int,
    data: int,
    *,
    wstrb: int = 0xFF,
    size: int = SMC_DBG_AXSIZE_8B,
    poll_limit: int = 128,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_single_op(J2A_OP_WRITE, addr, data, wstrb=wstrb, size=size)
    await jtag.write("SMC_AXI_SINGLE_OP", raw)
    require_jtag_tdo_resolved(f"J2A WR issue @0x{addr:08x}")
    # Allow AXI fabric latency before first status sample.
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved(f"J2A WR poll @0x{addr:08x}")
        status, rdata = unpack_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(f"JTAG2AXI write stuck BUSY after {poll_limit} polls @ {addr:#x}")
    return status, rdata


async def jtag2axi_single_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_DBG_AXSIZE_8B,
    poll_limit: int = 128,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=size)
    await jtag.write("SMC_AXI_SINGLE_OP", raw)
    require_jtag_tdo_resolved(f"J2A RD issue @0x{addr:08x}")
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved(f"J2A RD poll @0x{addr:08x}")
        status, rdata = unpack_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(f"JTAG2AXI read stuck BUSY after {poll_limit} polls @ {addr:#x}")
    return status, rdata


async def jtag2axi_series_ctrl(
    jtag: OcahJtagMasterDriver,
    op: int,
    addr: int,
    *,
    pipeline_depth: int = 1,
    size: int = SMC_DBG_AXSIZE_8B,
    reset: int = 0,
) -> None:
    raw = pack_smc_series_ctrl(op, addr, pipeline_depth=pipeline_depth, size=size, reset=reset)
    await jtag.write("SMC_AXI_SERIES_CTRL", raw)
    require_jtag_tdo_resolved(f"SMC SERIES_CTRL issue op={op} @0x{addr:08x}")


async def jtag2axi_series_ctrl_status(
    jtag: OcahJtagMasterDriver,
    *,
    size: int = SMC_DBG_AXSIZE_8B,
    poll_limit: int = 64,
    require_complete: bool = False,
) -> tuple[int, int, int, int, int]:
    decoded = (0, 0, 0, size, J2A_STATUS_BUSY)
    nop = pack_smc_series_ctrl(J2A_OP_NOP, 0, pipeline_depth=0, size=size)
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SERIES_CTRL", shift_value=nop)
        require_jtag_tdo_resolved("SMC SERIES_CTRL poll")
        decoded = unpack_smc_series_ctrl(capt)
        if decoded[4] != J2A_STATUS_BUSY:
            return decoded
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete:
        raise TimeoutError(
            f"SMC SERIES_CTRL stuck BUSY after {poll_limit} polls status={decoded[4]}"
        )
    return decoded


async def jtag2axi_series_data_incr(
    jtag: OcahJtagMasterDriver,
    data: int,
    *,
    size: int = SMC_DBG_AXSIZE_8B,
) -> int:
    mask = smc_series_data_mask(size)
    if 8 * (1 << size) != SMC_DBG_SERIES_DATA_LEN:
        raise AssertionError(
            f"SMC series data width {8 * (1 << size)} != registered {SMC_DBG_SERIES_DATA_LEN}"
        )
    capt = await jtag.read("SMC_AXI_SERIES_DATA_INCR", shift_value=data & mask)
    require_jtag_tdo_resolved("SMC SERIES_DATA_INCR")
    return int(capt) & mask


async def jtag2axi_series_incr_write(
    jtag: OcahJtagMasterDriver,
    addr: int,
    data: int,
    *,
    size: int = SMC_DBG_AXSIZE_8B,
    pipeline_depth: int = 1,
    poll_limit: int = 64,
) -> int:
    mask = smc_series_data_mask(size)
    await jtag2axi_series_ctrl(jtag, J2A_OP_WRITE, addr, pipeline_depth=pipeline_depth, size=size)
    await jtag2axi_series_data_incr(jtag, data & mask, size=size)
    await ClockCycles(cocotb.top.clk_smu_i, 64)
    *_, status = await jtag2axi_series_ctrl_status(
        jtag, size=size, poll_limit=poll_limit, require_complete=True
    )
    return status


async def jtag2axi_series_incr_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_DBG_AXSIZE_8B,
    pipeline_depth: int = 1,
    poll_limit: int = 64,
) -> tuple[int, int]:
    await jtag2axi_series_ctrl(jtag, J2A_OP_READ, addr, pipeline_depth=pipeline_depth, size=size)
    await jtag2axi_series_data_incr(jtag, 0, size=size)
    await ClockCycles(cocotb.top.clk_smu_i, 64)
    *_, status = await jtag2axi_series_ctrl_status(
        jtag, size=size, poll_limit=poll_limit, require_complete=True
    )
    rdata = await jtag2axi_series_data_incr(jtag, 0, size=size)
    return status, rdata


def require_jtag_tdo_resolved(where: str) -> None:
    """Fail closed if PTAP TDO is X/Z (VIP _logic_int would coerce that to 0)."""
    pin = getattr(cocotb.top, "jtag_tdo", None)
    if pin is None:
        raise AssertionError(f"jtag_tdo unobservable ({where})")
    val = pin.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z on jtag_tdo during {where}: {val}")


async def otp_jtag2axi_single_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 64,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_otp_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=size)
    await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
    require_jtag_tdo_resolved(f"OTP J2A WR issue @0x{addr:08x}")
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved(f"OTP J2A RD poll @0x{addr:08x}")
        status, rdata = unpack_otp_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(f"OTP JTAG2AXI read stuck BUSY after {poll_limit} polls @ {addr:#x}")
    return status, rdata


async def otp_jtag2axi_single_write(
    jtag: OcahJtagMasterDriver,
    addr: int,
    data: int,
    *,
    wstrb: int = 0xF,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 64,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_otp_single_op(J2A_OP_WRITE, addr, data, wstrb=wstrb, size=size)
    await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
    require_jtag_tdo_resolved(f"OTP J2A WR issue @0x{addr:08x}")
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved(f"OTP J2A WR poll @0x{addr:08x}")
        status, rdata = unpack_otp_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(f"OTP JTAG2AXI write stuck BUSY after {poll_limit} polls @ {addr:#x}")
    return status, rdata


async def sep_otp_jtag2axi_single_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 32,
) -> tuple[int, int]:
    """Issue SEP OTP SINGLE_OP read (SEP=0: bridge absent; for idle contrast)."""
    raw = pack_otp_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=size)
    await jtag.write("SEP_OTP_AXI_SINGLE_OP", raw)
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SEP_OTP_AXI_SINGLE_OP", shift_value=0)
        status, rdata = unpack_otp_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    return status, rdata


# PeakRDL wdt.h has no KEY-magic #define. Literal is the SPEC table in
# hw/sys/smc/regs/gen/adoc/blocks/wdt.adoc KEY: "Magic key (0x51F15E)".
# Same paragraph: a KEY read returns 1 if unlocked, 0 otherwise.
WDT_KEY_MAGIC = 0x51F15E
WDT_KEY_UNLOCKED_RD = 1


def axi64_pack32(addr: int, word32: int) -> tuple[int, int]:
    """WSTRB and beat data for a 32b CSR on a 64b J2A lane (from addr[2])."""
    word32 &= 0xFFFF_FFFF
    if addr & 0x4:
        return 0xF0, word32 << 32
    return 0x0F, word32


def axi64_unpack32(addr: int, beat: int) -> int:
    """Extract a 32b CSR from a 64b J2A beat (from addr[2])."""
    beat = int(beat)
    if addr & 0x4:
        return (beat >> 32) & 0xFFFF_FFFF
    return beat & 0xFFFF_FFFF


async def wdt_unlock(jtag: OcahJtagMasterDriver, magic: int = WDT_KEY_MAGIC) -> int:
    """Write CORE0 WDT KEY once; lane packing follows the map address."""
    from seq_lib.smu_addr_map import smc_addr

    key_addr = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
    wstrb, data = axi64_pack32(key_addr, magic)
    st, _ = await jtag2axi_single_write(
        jtag,
        key_addr,
        data,
        wstrb=wstrb,
        size=SMC_DBG_AXSIZE_4B,
        require_complete=True,
    )
    require_jtag_tdo_resolved("WDT_KEY unlock")
    return st


async def wdt_key_read(jtag: OcahJtagMasterDriver) -> tuple[int, int]:
    """Read KEY from the 64b FEED/KEY lane (KEY sits at +0x4 of that beat)."""
    from seq_lib.smu_addr_map import smc_addr

    key_addr = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
    lane = key_addr & ~0x7
    st, rdata = await jtag2axi_single_read(
        jtag,
        lane,
        size=SMC_DBG_AXSIZE_8B,
        require_complete=True,
    )
    require_jtag_tdo_resolved("WDT_KEY read")
    return st, axi64_unpack32(key_addr, rdata)


def shadow_map_word32(dut, byte_off: int) -> Optional[int]:
    """Best-effort 32b word from TB ``smc_shadow_regs`` (packed union).

    Returns None if the handle is not integer-accessible under this simulator.
    """
    word_idx = int(byte_off) // 4
    handle = getattr(dut, "smc_shadow_regs", None)
    if handle is None:
        return None
    # Flat LogicArray / IntegerObject
    try:
        raw = int(handle.value)
        return (raw >> (word_idx * 32)) & 0xFFFF_FFFF
    except (AttributeError, TypeError, ValueError):
        pass
    # Packed union: .values[word] or .values as array
    try:
        values = handle.values
        elem = values[word_idx]
        return int(elem.value if hasattr(elem, "value") else elem) & 0xFFFF_FFFF
    except (AttributeError, TypeError, ValueError, IndexError, KeyError):
        return None
