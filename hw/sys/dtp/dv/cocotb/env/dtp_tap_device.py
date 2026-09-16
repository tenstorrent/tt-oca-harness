# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP primary TAP register map.

One table of the TDRs the tests exercise, so the JTAG driver and the sequences
agree on register names, sizes, and IR opcodes. The opcodes are the
interface-unit instruction table (`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc`,
"Instruction Encodings"); the register sizes are the TDR layouts in
`hw/ip/jtag/jtag_ptap/doc/architecture.adoc` and, for the instructions that
document does not lay out, the interface-unit table's "Register Size" column;
the JTAG2AXI TDR sizes derive from the bridge geometries in
``dtp_types.JTAG2AXI_TARGETS``.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    "DTP_JTAG2AXI_RD_PL_DEPTH",
    "DTP_JTAG2AXI_WR_PL_DEPTH",
    "DTP_JTAG_CAPS_LEN",
    "DTP_NUM_CLK_STOP_REQ",
    "DTP_TMP_STATUS_LEN",
    "DtpTapDevice",
    "DtpTapRegister",
    "pack_jtag2axi_caps",
    "pack_jtag_caps",
    "unpack_jtag2axi_caps",
]

DTP_DEFAULT_IDCODE = 0x0000_0001
# Register sizes of the interface-unit instruction table.
DTP_BYPASS_LEN = 1
DTP_TMP_STATUS_LEN = 2
DTP_DEBUG_CONTROL_LEN = 5
DTP_TAP_3DCR_LEN = 2
# IC_RESET: reset_hold plus one {reset_enable, reset_control} pair per port
# ("IC_RESET Support" table); the standalone DTP has one SMC, one SEP, and one
# external port.
DTP_IC_RESET_PORTS = 3
DTP_IC_RESET_LEN = (2 * DTP_IC_RESET_PORTS) + 1
# JTAG_CAPS[59:0] ("JTAG Capabilities" table) and *_JTAG2AXI_CAPS[13:0]
# ("*_JTAG2AXI_CAPS" table).
DTP_JTAG_CAPS_LEN = 60
DTP_JTAG2AXI_CAPS_LEN = 14
# SELECT_IJTAG: one bit per SIB of the DTP iJTAG network
# (dtp_scan_ref_model.IJTAG_SIB_ORDER).
DTP_SELECT_IJTAG_MIN_LEN = 3
# Elaboration parameters of the standalone DTP that JTAG_CAPS publishes (the
# `dtp` module parameter defaults).
DTP_NUM_XTRIG_CTP = 16
DTP_NUM_XTRIG_INT_CT = 10
DTP_NUM_CLK_STOP_REQ = 9
DTP_NUM_EXTRA_STAPS = 1
DTP_NUM_SMC_IC_RESET = 1
DTP_NUM_SEP_IC_RESET = 1
DTP_NUM_EXT_IC_RESET = 1
DTP_OCH_VER = 0
# Read and write pipeline depth every JTAG2AXI bridge publishes in the
# rd_pl_depth and wr_pl_depth fields of its *_JTAG2AXI_CAPS TDR; the CAPS
# scenarios compare them.
DTP_JTAG2AXI_RD_PL_DEPTH = 3
DTP_JTAG2AXI_WR_PL_DEPTH = 3
# The OSS TB uses a compact local scan model for boundary-scan scenarios.
DTP_BSR_MODEL_LEN = 8


def _data_width_to_size_encoding(width_bits: int) -> int:
    """Return the JTAG2AXI CAPS data-size encoding for a power-of-two data width."""
    byte_width = width_bits // 8
    return byte_width.bit_length() - 1


def pack_jtag_caps() -> int:
    """Pack the standalone DTP's JTAG_CAPS value ("JTAG Capabilities" table)."""
    return (
        (DTP_NUM_XTRIG_INT_CT << 54)
        | (DTP_NUM_XTRIG_CTP << 48)
        | (DTP_NUM_EXTRA_STAPS << 44)
        | (1 << 43)  # stap_io_en
        | (1 << 42)  # sep_dbg_en
        | (1 << 41)  # smc_dbg_en
        | (DTP_NUM_SMC_IC_RESET << 33)
        | (DTP_NUM_SEP_IC_RESET << 25)
        | (DTP_NUM_EXT_IC_RESET << 17)
        | (1 << 16)  # ic_rst_inst_en
        | (1 << 15)  # tmp_inst_en
        | (1 << 14)  # runbist_inst_en
        | (1 << 13)  # highz_inst_en
        | (1 << 12)  # clamp_inst_en
        | (1 << 11)  # intest_inst_en
        | (1 << 10)  # extest_pulse_en
        | (1 << 9)  # extest_train_en
        | (1 << 8)  # bsr_inst_en
        | DTP_OCH_VER
    )


def pack_jtag2axi_caps(
    *,
    bus_type: int,
    addr_width: int,
    data_width: int,
    rd_pl_depth: int = DTP_JTAG2AXI_RD_PL_DEPTH,
    wr_pl_depth: int = DTP_JTAG2AXI_WR_PL_DEPTH,
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
        bus_type=cfg.bus_type, addr_width=cfg.addr_width, data_width=cfg.data_width
    )
    for cfg in JTAG2AXI_TARGETS.values()
}


@dataclass(frozen=True)
class DtpTapRegister:
    """One TDR: its shift length in bits, IR opcode, and whether Update-DR writes it."""

    width: int
    instr: int
    write: bool = False


def _fixed_registers() -> dict[str, DtpTapRegister]:
    """TDRs whose sizes come straight from the instruction table and the PTAP layouts."""
    return {
        "BYPASS_00": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.BYPASS_00)),
        "IDCODE": DtpTapRegister(32, int(DtpJtagInstr.IDCODE)),
        "RUNBIST": DtpTapRegister(DTP_BSR_MODEL_LEN, int(DtpJtagInstr.RUNBIST)),
        "SAMPLE_PRELOAD": DtpTapRegister(
            DTP_BSR_MODEL_LEN, int(DtpJtagInstr.SAMPLE_PRELOAD), write=True
        ),
        "EXTEST": DtpTapRegister(DTP_BSR_MODEL_LEN, int(DtpJtagInstr.EXTEST), write=True),
        "EXTEST_TRAIN": DtpTapRegister(
            DTP_BSR_MODEL_LEN, int(DtpJtagInstr.EXTEST_TRAIN), write=True
        ),
        "EXTEST_PULSE": DtpTapRegister(
            DTP_BSR_MODEL_LEN, int(DtpJtagInstr.EXTEST_PULSE), write=True
        ),
        "CLAMP": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP)),
        "HIGHZ": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.HIGHZ)),
        "INTEST": DtpTapRegister(DTP_BSR_MODEL_LEN, int(DtpJtagInstr.INTEST), write=True),
        "CLAMP_HOLD": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP_HOLD)),
        "CLAMP_RELEASE": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP_RELEASE)),
        "TMP_STATUS": DtpTapRegister(DTP_TMP_STATUS_LEN, int(DtpJtagInstr.TMP_STATUS), write=True),
        "IC_RESET": DtpTapRegister(DTP_IC_RESET_LEN, int(DtpJtagInstr.IC_RESET), write=True),
        "TAP_3DCR": DtpTapRegister(DTP_TAP_3DCR_LEN, int(DtpJtagInstr.TAP_3DCR), write=True),
        "DEBUG_CONTROL": DtpTapRegister(
            DTP_DEBUG_CONTROL_LEN, int(DtpJtagInstr.DEBUG_CONTROL), write=True
        ),
        "JTAG_CAPS": DtpTapRegister(DTP_JTAG_CAPS_LEN, int(DtpJtagInstr.JTAG_CAPS)),
        "SELECT_IJTAG": DtpTapRegister(
            DTP_SELECT_IJTAG_MIN_LEN, int(DtpJtagInstr.SELECT_IJTAG), write=True
        ),
        "ZERO_LENGTH_BYPASS": DtpTapRegister(0, int(DtpJtagInstr.ZERO_LENGTH_BYPASS)),
        "INV_BYPASS": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.INV_BYPASS)),
        "BYPASS_3F": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.BYPASS_3F)),
    }


def _jtag2axi_registers(cfg: DtpJtag2AxiTargetCfg) -> dict[str, DtpTapRegister]:
    """One bridge's CAPS, SINGLE_OP, and SERIES_CTRL TDRs at its geometry."""
    return {
        cfg.caps_reg: DtpTapRegister(DTP_JTAG2AXI_CAPS_LEN, int(DtpJtagInstr[cfg.caps_reg])),
        cfg.single_op_reg: DtpTapRegister(
            cfg.single_op_len, int(DtpJtagInstr[cfg.single_op_reg]), write=True
        ),
        cfg.series_ctrl_reg: DtpTapRegister(
            cfg.series_ctrl_len, int(DtpJtagInstr[cfg.series_ctrl_reg]), write=True
        ),
    }


class DtpTapDevice:
    """DTP primary TAP with the TDRs exercised by the OSS tests."""

    def __init__(self, idle_delay: int = 0) -> None:
        self.name = "dtp"
        self.idcode = DTP_DEFAULT_IDCODE
        self.ir_len = DTP_IR_WIDTH
        self.regs: dict[str, DtpTapRegister] = _fixed_registers()
        for cfg in JTAG2AXI_TARGETS.values():
            self.regs.update(_jtag2axi_registers(cfg))
        # Idle TCK cycles after every op (JTAG2AXI CDC + AXI round trip).
        self.idle_delay = idle_delay

    def reg(self, name: str) -> DtpTapRegister:
        return self.regs[name]
