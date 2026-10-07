# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP primary TAP register map.

One table of the TDRs the tests exercise, so the JTAG driver and the sequences
agree on register names, sizes, and IR opcodes; ``dtp_tap_device()`` builds it
as the shared ``OcahJtagDevice`` the JTAG master reads and writes through. The
opcodes are the
interface-unit instruction table (`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc`,
"Instruction Encodings"); the register sizes are the TDR layouts in
`hw/ip/jtag/jtag_ptap/doc/architecture.adoc` and, for the instructions that
document does not lay out, the interface-unit table's "Register Size" column;
the JTAG2AXI TDR sizes derive from the bridge geometries in
``dtp_types.JTAG2AXI_TARGETS``.
"""

from __future__ import annotations

from ocah_jtag_vip import OcahJtagDevice

from .dtp_dv_cfg import (
    DTP_BSR_ENABLE,
    DTP_CLAMP_ENABLE,
    DTP_DEFAULT_IDCODE,
    DTP_EXTEST_PULSE_ENABLE,
    DTP_EXTEST_TRAIN_ENABLE,
    DTP_HIGHZ_ENABLE,
    DTP_IC_RESET_INSTR_ENABLE,
    DTP_INTEST_ENABLE,
    DTP_NUM_EXT_IC_RESET,
    DTP_NUM_EXTRA_STAPS,
    DTP_NUM_SEP_IC_RESET,
    DTP_NUM_SMC_IC_RESET,
    DTP_NUM_XTRIG_CTP,
    DTP_NUM_XTRIG_INT_CT,
    DTP_OCH_VER,
    DTP_RUNBIST_ENABLE,
    DTP_SEP_DBG_ENABLE,
    DTP_SMC_DBG_ENABLE,
    DTP_STAP_IO_ENABLE,
    DTP_TMP_ENABLE,
)
from .dtp_types import DTP_IR_WIDTH, JTAG2AXI_TARGETS, DtpJtag2AxiTargetCfg, DtpJtagInstr

__all__ = [
    "DTP_BSR_MODEL_LEN",
    "DTP_DEBUG_CONTROL_LEN",
    "DTP_DEFAULT_IDCODE",
    "DTP_EXPECTED_JTAG2AXI_CAPS",
    "DTP_EXPECTED_JTAG_CAPS",
    "DTP_IC_RESET_LEN",
    "DTP_IC_RESET_PORTS",
    "DTP_JTAG2AXI_CAPS_LEN",
    "DTP_JTAG_CAPS_LEN",
    "DTP_TMP_STATUS_LEN",
    "dtp_tap_device",
    "pack_jtag2axi_caps",
    "pack_jtag_caps",
    "unpack_jtag2axi_caps",
]

# Register sizes of the interface-unit instruction table.
DTP_BYPASS_LEN = 1
DTP_TMP_STATUS_LEN = 2
DTP_DEBUG_CONTROL_LEN = 5
DTP_TAP_3DCR_LEN = 2
# IC_RESET: reset_hold plus one {reset_enable, reset_control} pair per port
# ("IC_RESET Support" table) over the bench configuration's slices.
DTP_IC_RESET_PORTS = DTP_NUM_SMC_IC_RESET + DTP_NUM_SEP_IC_RESET + DTP_NUM_EXT_IC_RESET
DTP_IC_RESET_LEN = (2 * DTP_IC_RESET_PORTS) + 1
# JTAG_CAPS[59:0] ("JTAG Capabilities" table) and *_JTAG2AXI_CAPS[13:0]
# ("*_JTAG2AXI_CAPS" table).
DTP_JTAG_CAPS_LEN = 60
DTP_JTAG2AXI_CAPS_LEN = 14
# SELECT_IJTAG: one bit per SIB of the DTP iJTAG network
# (dtp_scan_ref_model.IJTAG_SIB_ORDER).
DTP_SELECT_IJTAG_MIN_LEN = 3
# The OSS TB uses a compact local scan model for boundary-scan scenarios.
DTP_BSR_MODEL_LEN = 8


def _data_width_to_size_encoding(width_bits: int) -> int:
    """Return the JTAG2AXI CAPS data-size encoding for a power-of-two data width."""
    byte_width = width_bits // 8
    return byte_width.bit_length() - 1


def pack_jtag_caps() -> int:
    """Pack the bench configuration's JTAG_CAPS value ("JTAG Capabilities" table)."""
    return (
        (DTP_NUM_XTRIG_INT_CT << 54)
        | (DTP_NUM_XTRIG_CTP << 48)
        | (DTP_NUM_EXTRA_STAPS << 44)
        | (DTP_STAP_IO_ENABLE << 43)
        | (DTP_SEP_DBG_ENABLE << 42)
        | (DTP_SMC_DBG_ENABLE << 41)
        | (DTP_NUM_SMC_IC_RESET << 33)
        | (DTP_NUM_SEP_IC_RESET << 25)
        | (DTP_NUM_EXT_IC_RESET << 17)
        | (DTP_IC_RESET_INSTR_ENABLE << 16)
        | (DTP_TMP_ENABLE << 15)
        | (DTP_RUNBIST_ENABLE << 14)
        | (DTP_HIGHZ_ENABLE << 13)
        | (DTP_CLAMP_ENABLE << 12)
        | (DTP_INTEST_ENABLE << 11)
        | (DTP_EXTEST_PULSE_ENABLE << 10)
        | (DTP_EXTEST_TRAIN_ENABLE << 9)
        | (DTP_BSR_ENABLE << 8)
        | DTP_OCH_VER
    )


def pack_jtag2axi_caps(
    *,
    bus_type: int,
    addr_width: int,
    data_width: int,
    rd_pl_depth: int,
    wr_pl_depth: int,
) -> int:
    """Pack a *_JTAG2AXI_CAPS value ("*_JTAG2AXI_CAPS" table, bits 13:0)."""
    return (
        ((rd_pl_depth & 0x3) << 12)
        | ((wr_pl_depth & 0x3) << 10)
        | ((_data_width_to_size_encoding(data_width) & 0x7) << 7)
        | ((addr_width & 0x3F) << 1)
        | (bus_type & 0x1)
    )


def unpack_jtag2axi_caps(value: int) -> dict[str, int]:
    """Fields of a *_JTAG2AXI_CAPS value by the table's names."""
    return {
        "rd_pl_depth": (value >> 12) & 0x3,
        "wr_pl_depth": (value >> 10) & 0x3,
        "data_size": (value >> 7) & 0x7,
        "addr_size": (value >> 1) & 0x3F,
        "bus_type": value & 0x1,
    }


DTP_EXPECTED_JTAG_CAPS = pack_jtag_caps()
# Expected *_JTAG2AXI_CAPS value per CAPS register name, from the geometry table.
DTP_EXPECTED_JTAG2AXI_CAPS: dict[str, int] = {
    cfg.caps_reg: pack_jtag2axi_caps(
        bus_type=cfg.bus_type,
        addr_width=cfg.addr_width,
        data_width=cfg.data_width,
        rd_pl_depth=cfg.rd_pl_depth,
        wr_pl_depth=cfg.wr_pl_depth,
    )
    for cfg in JTAG2AXI_TARGETS.values()
}


# A TDR entry: its shift length in bits, its IR opcode, and, for a register
# Update-DR writes, True.
_TapRegister = tuple[int, int] | tuple[int, int, bool]


def _fixed_registers() -> dict[str, _TapRegister]:
    """TDRs whose sizes come straight from the instruction table and the PTAP layouts."""
    return {
        "BYPASS_00": (DTP_BYPASS_LEN, int(DtpJtagInstr.BYPASS_00)),
        "IDCODE": (32, int(DtpJtagInstr.IDCODE)),
        "RUNBIST": (DTP_BSR_MODEL_LEN, int(DtpJtagInstr.RUNBIST)),
        "SAMPLE_PRELOAD": (DTP_BSR_MODEL_LEN, int(DtpJtagInstr.SAMPLE_PRELOAD), True),
        "EXTEST": (DTP_BSR_MODEL_LEN, int(DtpJtagInstr.EXTEST), True),
        "EXTEST_TRAIN": (DTP_BSR_MODEL_LEN, int(DtpJtagInstr.EXTEST_TRAIN), True),
        "EXTEST_PULSE": (DTP_BSR_MODEL_LEN, int(DtpJtagInstr.EXTEST_PULSE), True),
        "CLAMP": (DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP)),
        "HIGHZ": (DTP_BYPASS_LEN, int(DtpJtagInstr.HIGHZ)),
        "INTEST": (DTP_BSR_MODEL_LEN, int(DtpJtagInstr.INTEST), True),
        "CLAMP_HOLD": (DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP_HOLD)),
        "CLAMP_RELEASE": (DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP_RELEASE)),
        "TMP_STATUS": (DTP_TMP_STATUS_LEN, int(DtpJtagInstr.TMP_STATUS), True),
        "IC_RESET": (DTP_IC_RESET_LEN, int(DtpJtagInstr.IC_RESET), True),
        "TAP_3DCR": (DTP_TAP_3DCR_LEN, int(DtpJtagInstr.TAP_3DCR), True),
        "DEBUG_CONTROL": (DTP_DEBUG_CONTROL_LEN, int(DtpJtagInstr.DEBUG_CONTROL), True),
        "JTAG_CAPS": (DTP_JTAG_CAPS_LEN, int(DtpJtagInstr.JTAG_CAPS)),
        "SELECT_IJTAG": (DTP_SELECT_IJTAG_MIN_LEN, int(DtpJtagInstr.SELECT_IJTAG), True),
        "ZERO_LENGTH_BYPASS": (0, int(DtpJtagInstr.ZERO_LENGTH_BYPASS)),
        "INV_BYPASS": (DTP_BYPASS_LEN, int(DtpJtagInstr.INV_BYPASS)),
        "BYPASS_3F": (DTP_BYPASS_LEN, int(DtpJtagInstr.BYPASS_3F)),
    }


def _jtag2axi_registers(cfg: DtpJtag2AxiTargetCfg) -> dict[str, _TapRegister]:
    """One bridge's CAPS, SINGLE_OP, and SERIES_CTRL TDRs at its geometry."""
    return {
        cfg.caps_reg: (DTP_JTAG2AXI_CAPS_LEN, int(DtpJtagInstr[cfg.caps_reg])),
        cfg.single_op_reg: (cfg.single_op_len, int(DtpJtagInstr[cfg.single_op_reg]), True),
        cfg.series_ctrl_reg: (cfg.series_ctrl_len, int(DtpJtagInstr[cfg.series_ctrl_reg]), True),
    }


def dtp_tap_device(idle_delay: int = 0) -> OcahJtagDevice:
    """DTP primary TAP with the TDRs exercised by the OSS tests.

    ``idle_delay`` is the idle TCK cycles after every register access (the
    JTAG2AXI CDC and AXI round trip).
    """
    registers = _fixed_registers()
    for cfg in JTAG2AXI_TARGETS.values():
        registers.update(_jtag2axi_registers(cfg))
    return OcahJtagDevice.from_registers(
        name="dtp",
        idcode=DTP_DEFAULT_IDCODE,
        ir_width=DTP_IR_WIDTH,
        registers=registers,
        idle_delay=idle_delay,
        add_bypass=False,
    )
