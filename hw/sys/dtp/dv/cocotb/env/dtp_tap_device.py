# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP primary TAP register map.

One table of the TDRs the tests exercise, so the JTAG driver and the sequences
agree on register names, sizes, and IR opcodes; ``dtp_tap_device()`` builds it
as the shared ``OcahJtagDevice`` the JTAG master reads and writes through. The
opcodes are the interface-unit instruction table
(`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc`, "Instruction Encodings"); the
register sizes are the TDR layouts in `hw/ip/jtag/jtag_ptap/doc/architecture.adoc`
and, for the instructions that document does not lay out, the interface-unit
table's "Register Size" column.
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
from .dtp_types import DMI_LEN, DTMCS_LEN, DTP_IR_WIDTH, JTAG2AXI_TARGETS, DtpJtagInstr

__all__ = [
    "DTP_BSR_MODEL_LEN",
    "DTP_DEBUG_CONTROL_LEN",
    "DTP_DEFAULT_IDCODE",
    "DTP_EXPECTED_JTAG_CAPS",
    "DTP_IC_RESET_LEN",
    "DTP_IC_RESET_PORTS",
    "DTP_JTAG_CAPS_LEN",
    "DTP_TMP_STATUS_LEN",
    "dtp_tap_device",
    "pack_jtag_caps",
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
# JTAG_CAPS[59:0] ("JTAG Capabilities" table).
DTP_JTAG_CAPS_LEN = 60
# SELECT_IJTAG: one bit per SIB of the DTP iJTAG network
# (dtp_ijtag_sib_model.IJTAG_SIB_ORDER).
DTP_SELECT_IJTAG_MIN_LEN = 3
# The bench models the boundary-scan register as an 8-bit loopback (DtpScanModel).
DTP_BSR_MODEL_LEN = 8


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


DTP_EXPECTED_JTAG_CAPS = pack_jtag_caps()


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


def dtp_tap_device(idle_delay: int = 0) -> OcahJtagDevice:
    """DTP primary TAP with the TDRs the tests exercise.

    ``idle_delay`` is the idle TCK cycles after every register access, in
    which a DMI operation crosses to the Debug Module and back.
    """
    registers = _fixed_registers()
    for cfg in JTAG2AXI_TARGETS.values():
        registers[cfg.dtmcs_reg] = (DTMCS_LEN, int(cfg.dtmcs_instr), True)
        registers[cfg.dmi_reg] = (DMI_LEN, int(cfg.dmi_instr), True)
    return OcahJtagDevice.from_registers(
        name="dtp",
        idcode=DTP_DEFAULT_IDCODE,
        ir_width=DTP_IR_WIDTH,
        registers=registers,
        idle_delay=idle_delay,
        add_bypass=False,
    )
