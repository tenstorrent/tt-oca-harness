# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU JTAG / JTAG2AXI helpers (local constants; avoid DTP ``env`` package clash)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagDevice, OcahJtagMasterDriver

from seq_lib.smu_tb_pins import smu_scope

# Lifecycle ungating: use seq_lib.smu_lcc_helpers (SEP=1 eFuse→LCC).
# SEP=0 gen_no_sep ties sep_feat_ctrl='1' (enable); J2A opens after TCK sync.

_REPO_ROOT = Path(__file__).resolve().parents[6]
_JTAG_INST_PKG = _REPO_ROOT / "hw" / "ip" / "jtag" / "jtag_ptap" / "rtl" / "jtag_inst_reg_pkg.sv"
_JTAG_PTAP_ARCH = _REPO_ROOT / "hw" / "ip" / "jtag" / "jtag_ptap" / "doc" / "architecture.adoc"
_IR_ENUM_RE = re.compile(r"^\s+(\w+_INSTR)\s+=\s+6'h([0-9A-Fa-f]+)")
_JTAG_CAPS_SEP_DBG_RE = re.compile(r"^\|(\d+) \|sep_dbg_en \|")
_JTAG2AXI_CAPS_FIELD_RE = re.compile(r"^\|(\d+)(?::(\d+))? \|(\w+) \|")
_SMU_PKG = _REPO_ROOT / "hw" / "sys" / "smu" / "rtl" / "smu_pkg.sv"
_SMU_OTP_PL_RE = re.compile(r"SMC_OTP_(RD|WR)_PL_DEPTH:\s+2'h([0-9A-Fa-f]+)")


@lru_cache(maxsize=1)
def _jtag_ir_opcodes() -> dict[str, int]:
    text = _JTAG_INST_PKG.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = _IR_ENUM_RE.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    if "IDCODE_INSTR" not in out or "TAP_3DCR_INSTR" not in out:
        raise RuntimeError(f"IR opcodes missing from {_JTAG_INST_PKG}")
    return out


def dtp_ir_opcode(rtl_symbol: str) -> int:
    """PTAP opcode from jtag_inst_reg_pkg.sv (authoritative IR map)."""
    table = _jtag_ir_opcodes()
    if rtl_symbol not in table:
        raise KeyError(f"{rtl_symbol} not in {_JTAG_INST_PKG}")
    return table[rtl_symbol]


@lru_cache(maxsize=1)
def dtp_jtag_caps_sep_dbg_en_bit() -> int:
    """JTAG_CAPS sep_dbg_en bit index from the PTAP architecture table."""
    text = _JTAG_PTAP_ARCH.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = _JTAG_CAPS_SEP_DBG_RE.match(line)
        if m:
            return int(m.group(1))
    raise RuntimeError(f"sep_dbg_en bit missing from {_JTAG_PTAP_ARCH}")


@lru_cache(maxsize=1)
def _jtag2axi_caps_field_lsb() -> dict[str, int]:
    """LSB of each *_JTAG2AXI_CAPS field from the PTAP architecture table."""
    text = _JTAG_PTAP_ARCH.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    in_table = False
    for line in text.splitlines():
        if line.startswith("====== *_JTAG2AXI_CAPS"):
            in_table = True
            continue
        if in_table and line.startswith("====== "):
            break
        if not in_table:
            continue
        m = _JTAG2AXI_CAPS_FIELD_RE.match(line)
        if not m:
            continue
        msb = int(m.group(1))
        lsb = int(m.group(2)) if m.group(2) is not None else msb
        out[m.group(3)] = min(msb, lsb)
    need = ("rd_pl_depth", "wr_pl_depth", "data_size", "addr_size", "bus_type")
    missing = [n for n in need if n not in out]
    if missing:
        raise RuntimeError(f"JTAG2AXI_CAPS fields {missing} missing from {_JTAG_PTAP_ARCH}")
    return out


@lru_cache(maxsize=1)
def _smu_otp_pl_depths() -> tuple[int, int]:
    """SMC OTP rd/wr pipeline depths from smu_pkg.sv Cfg defaults."""
    text = _SMU_PKG.read_text(encoding="utf-8")
    found: dict[str, int] = {}
    for m in _SMU_OTP_PL_RE.finditer(text):
        found[m.group(1)] = int(m.group(2), 16)
    if "RD" not in found or "WR" not in found:
        raise RuntimeError(f"SMC_OTP_*_PL_DEPTH missing from {_SMU_PKG}")
    return found["RD"], found["WR"]


@lru_cache(maxsize=1)
def _jtag2axi_caps_encodings() -> dict[str, int]:
    """Named encodings from the architecture.adoc *_JTAG2AXI_CAPS table."""
    text = _JTAG_PTAP_ARCH.read_text(encoding="utf-8")
    data_size_4b = None
    bus_lite = None
    in_table = False
    for line in text.splitlines():
        if line.startswith("====== *_JTAG2AXI_CAPS"):
            in_table = True
            continue
        if in_table and line.startswith("====== "):
            break
        if not in_table:
            continue
        if "|data_size |" in line:
            m = re.search(r"(\d+):\s*4 bytes", line)
            if m:
                data_size_4b = int(m.group(1))
        if "|bus_type |" in line:
            m = re.search(r"(\d+):\s*AXI4-Lite", line)
            if m:
                bus_lite = int(m.group(1))
    if data_size_4b is None or bus_lite is None:
        raise RuntimeError(f"JTAG2AXI_CAPS encodings missing from {_JTAG_PTAP_ARCH}")
    return {"data_size_4b": data_size_4b, "bus_axi4_lite": bus_lite}


def pack_jtag2axi_caps(
    *,
    rd_pl: int,
    wr_pl: int,
    data_size: int,
    addr_size: int,
    bus_type: int,
) -> int:
    """Pack 14-bit *_JTAG2AXI_CAPS using architecture.adoc field LSBs."""
    lsb = _jtag2axi_caps_field_lsb()
    return (
        (int(rd_pl) << lsb["rd_pl_depth"])
        | (int(wr_pl) << lsb["wr_pl_depth"])
        | (int(data_size) << lsb["data_size"])
        | (int(addr_size) << lsb["addr_size"])
        | (int(bus_type) << lsb["bus_type"])
    )


# Mirrors hw/sys/dtp/dv/cocotb/env/{dtp_types,dtp_tap_device}.py
DTP_IR_WIDTH = 6
DTP_DEFAULT_IDCODE = 0x0000_0001
DTP_IR_IDCODE = dtp_ir_opcode("IDCODE_INSTR")
DTP_IR_DEBUG_CONTROL = dtp_ir_opcode("DEBUG_CONTROL_INSTR")
DTP_IR_IC_RESET = dtp_ir_opcode("IC_RESET_INSTR")
DTP_IR_EXTEST = dtp_ir_opcode("EXTEST_INSTR")
DTP_IR_SAMPLE_PRELOAD = dtp_ir_opcode("SAMPLE_PRELOAD_INSTR")
DTP_IR_TAP_3DCR = dtp_ir_opcode("TAP_3DCR_INSTR")

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


DTP_IR_SMC_AXI_SINGLE_OP = dtp_ir_opcode("SMC_AXI_SINGLE_OP_INSTR")
DTP_IR_SMC_JTAG2AXI_CAPS = dtp_ir_opcode("SMC_JTAG2AXI_CAPS_INSTR")
DTP_IR_SMC_AXI_SERIES_CTRL = dtp_ir_opcode("SMC_AXI_SERIES_CTRL_INSTR")
DTP_IR_SMC_AXI_SERIES_DATA_INCR = dtp_ir_opcode("SMC_AXI_SERIES_DATA_INCR_INSTR")
DTP_IR_SMC_OTP_JTAG2AXI_CAPS = dtp_ir_opcode("SMC_OTP_JTAG2AXI_CAPS_INSTR")
DTP_IR_SMC_OTP_AXI_SINGLE_OP = dtp_ir_opcode("SMC_OTP_AXI_SINGLE_OP_INSTR")
DTP_IR_SMC_OTP_AXI_SERIES_CTRL = dtp_ir_opcode("SMC_OTP_AXI_SERIES_CTRL_INSTR")
DTP_IR_SMC_OTP_AXI_SERIES_DATA_NO_INCR = dtp_ir_opcode("SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR")
DTP_IR_SEP_OTP_JTAG2AXI_CAPS = dtp_ir_opcode("SEP_OTP_JTAG2AXI_CAPS_INSTR")
DTP_IR_SEP_OTP_AXI_SINGLE_OP = dtp_ir_opcode("SEP_OTP_AXI_SINGLE_OP_INSTR")
DTP_IR_JTAG_CAPS = dtp_ir_opcode("JTAG_CAPS_INSTR")
DTP_IR_BYPASS = dtp_ir_opcode("BYPASS_INSTR")
DTP_DEBUG_CONTROL_LEN = 5
DTP_JTAG2AXI_CAPS_LEN = 14
DTP_JTAG_CAPS_LEN = 60
DTP_JTAG_CAPS_SEP_DBG_EN_BIT = dtp_jtag_caps_sep_dbg_en_bit()
# Compact OSS BSR loopback model (scan_in <- scan_out); matches DTP OSS.
DTP_BSR_MODEL_LEN = 8
# One-hot EXTEST decode bit in jtag_instruction_decoded_e.
DTP_EXTEST_DECODED_BIT = DTP_IR_EXTEST
# SMU SEP=0 IC_RESET geometry (smu.sv / jtag_ptap):
#   NUM_SMC = $bits(jtag_smc_reset_ctrl_t)/2 = 68, NUM_SEP = 0, NUM_EXT = 1
#   TDR width = 2*NUM_IC_RESET + 1 (hold) = 139
SMU_IC_RESET_NUM_PORTS = 69
SMU_IC_RESET_LEN = 2 * SMU_IC_RESET_NUM_PORTS + 1
SMU_IC_RESET_DEFAULT = (1 << SMU_IC_RESET_LEN) - 1
SMU_IC_RESET_EXT_PORT = 0
SMU_IC_RESET_SMC_FUSE_PORT = 1
SMU_IC_RESET_SMC_WARM_PORT = 2
SMU_IC_RESET_SMC_COOL_PORT = 3
SMU_IC_RESET_SMC_COLD_PORT = 4  # EXT@0 + SMC fuse/warm/cool/cold
SMU_IC_RESET_SMC_SS_COLD0_PORT = 5
SMU_IC_RESET_SMC_SS_WARM0_PORT = 37

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
# APB ERR_DECODE poison (efuse_interface_controller ERR_DECODE prdata).
SMC_OTP_ERR_DECODE_DATA = 0xBADC_AB1E
# axi_err_slv / prim_axi_lite_err_slv default RESP_DATA[31:0].
SMC_AXI_ERR_SLV_POISON = 0xBADC_AB1E
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

# OTP CAPS: field LSBs + AXI4-Lite/4-byte encodings from architecture.adoc;
# pipeline depths from smu_pkg.sv Cfg; ADDR32 matches pack_otp_single_op.
_OTP_RD_PL, _OTP_WR_PL = _smu_otp_pl_depths()
_OTP_CAPS_ENC = _jtag2axi_caps_encodings()
DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS = pack_jtag2axi_caps(
    rd_pl=_OTP_RD_PL,
    wr_pl=_OTP_WR_PL,
    data_size=_OTP_CAPS_ENC["data_size_4b"],
    addr_size=32,
    bus_type=_OTP_CAPS_ENC["bus_axi4_lite"],
)
DTP_EXPECTED_SEP_OTP_JTAG2AXI_CAPS = DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS
# Fabric AXI4 64b/56b packing (same table LSBs; instance defaults).
DTP_EXPECTED_SMC_JTAG2AXI_CAPS = pack_jtag2axi_caps(
    rd_pl=_OTP_RD_PL,
    wr_pl=_OTP_WR_PL,
    data_size=3,
    addr_size=56,
    bus_type=0,
)


def pack_ic_reset_ports(
    *,
    reset_hold: int = 1,
    port_enable: dict[int, int] | None = None,
    port_control: dict[int, int] | None = None,
) -> int:
    """Pack SMU IC_RESET TDR by port index (0=EXT, 4=SMC cold_reset_n)."""
    value = SMU_IC_RESET_DEFAULT & ~0x1
    value |= reset_hold & 0x1
    for idx, en in (port_enable or {}).items():
        bit = 1 + 2 * int(idx)
        value = (value & ~(1 << bit)) | ((en & 0x1) << bit)
    for idx, ctrl in (port_control or {}).items():
        bit = 2 + 2 * int(idx)
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


# jtag_smc_reset_ctrl_t packed [135:0]: ovrd[135:68] | val[67:0]
# Within ovrd/val LSB: fuse, warm, cool, cold, then ss_cold[31:0], ss_warm[31:0].
_SMC_RESET_CTRL_BITS = {
    "fuse_reset_n_ovrd": 68,
    "warm_reset_n_ovrd": 69,
    "cool_reset_n_ovrd": 70,
    "cold_reset_n_ovrd": 71,
    "fuse_reset_n_val": 0,
    "warm_reset_n_val": 1,
    "cool_reset_n_val": 2,
    "cold_reset_n_val": 3,
}


def _ss_reset_ctrl_bit_index(leaf: str, idx: int) -> int:
    """Packed bit index for ss_cold/ss_warm ovrd/val[idx]."""
    if idx < 0 or idx > 31:
        raise AssertionError(f"ss reset index out of range: {idx}")
    if leaf == "ss_cold_reset_n_ovrd":
        return 72 + idx
    if leaf == "ss_warm_reset_n_ovrd":
        return 104 + idx
    if leaf == "ss_cold_reset_n_val":
        return 4 + idx
    if leaf == "ss_warm_reset_n_val":
        return 36 + idx
    raise AssertionError(f"Unknown ss reset leaf: {leaf}")


def _sample_bit(signal, name: str) -> int:
    """Resolve a Logic signal to 0/1; fail closed on X/Z."""
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val) & 1


def read_smc_reset_ctrl_bit(dut, leaf: str, idx: int | None = None) -> int:
    """Read one jtag_smc_reset_ctrl ovrd/val leaf (hierarchical or packed).

    For scalar fuse/warm/cool/cold leaves, pass ``leaf`` only.
    For ss_* vectors, pass ``leaf`` + ``idx`` (0..31).
    """
    ctrl = smu_scope(dut).jtag_smc_reset_ctrl
    if idx is not None:
        bit = _ss_reset_ctrl_bit_index(leaf, idx)
        # Prefer packed whole-struct (VCS may expose ss_* as non-indexable GPI).
        try:
            packed = ctrl.value
            if not packed.is_resolvable:
                raise AssertionError(
                    f"X/Z sample on jtag_smc_reset_ctrl (packed) for {leaf}[{idx}]: {packed}"
                )
            return (int(packed) >> bit) & 1
        except AssertionError:
            raise
        except Exception:  # noqa: BLE001
            pass
        if hasattr(ctrl, "ovrd") and hasattr(ctrl, "val"):
            group = "ovrd" if leaf.endswith("_ovrd") else "val"
            vec = getattr(getattr(ctrl, group), leaf)
            try:
                return _sample_bit(vec[idx], f"jtag_smc_reset_ctrl.{leaf}[{idx}]")
            except Exception:  # noqa: BLE001
                v = vec.value
                if not v.is_resolvable:
                    raise AssertionError(f"X/Z sample on jtag_smc_reset_ctrl.{leaf}: {v}")
                return (int(v) >> idx) & 1
        raise AssertionError(f"Cannot read jtag_smc_reset_ctrl.{leaf}[{idx}]")

    if leaf not in _SMC_RESET_CTRL_BITS:
        raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")
    if hasattr(ctrl, "ovrd") and hasattr(ctrl, "val"):
        group = "ovrd" if leaf.endswith("_ovrd") else "val"
        return _sample_bit(
            getattr(getattr(ctrl, group), leaf),
            f"jtag_smc_reset_ctrl.{leaf}",
        )
    packed = ctrl.value
    if not packed.is_resolvable:
        raise AssertionError(f"X/Z sample on jtag_smc_reset_ctrl (packed) for {leaf}: {packed}")
    return (int(packed) >> _SMC_RESET_CTRL_BITS[leaf]) & 1


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
    # Allow AXI fabric latency before first status sample.
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
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
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
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
