# SPDX-License-Identifier: Apache-2.0
"""DTP primary TAP register map.

Centralizes the TDR map so the JTAG driver and sequences agree on register
names, widths, and IR opcodes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dtp_types import DTP_IR_WIDTH, DtpJtagInstr, JTAG2AXI_TARGETS

DTP_DEFAULT_IDCODE = 0x0000_0001
DTP_BYPASS_LEN = 1
DTP_TMP_STATUS_LEN = 2
DTP_DEBUG_CONTROL_LEN = 5
DTP_IC_RESET_PORTS = 3
DTP_IC_RESET_LEN = (2 * DTP_IC_RESET_PORTS) + 1
DTP_JTAG_CAPS_LEN = 60
DTP_JTAG2AXI_CAPS_LEN = 14
DTP_TAP_3DCR_LEN = 2
DTP_SELECT_IJTAG_MIN_LEN = 3
DTP_NUM_XTRIG_CTP = 16
DTP_NUM_XTRIG_INT_CT = 10
DTP_NUM_CLK_STOP_REQ = 9
DTP_NUM_EXTRA_STAPS = 1
DTP_NUM_SMC_IC_RESET = 1
DTP_NUM_SEP_IC_RESET = 1
DTP_NUM_EXT_IC_RESET = 1
DTP_OCH_VER = 0
DTP_JTAG2AXI_RD_PL_DEPTH = 3
DTP_JTAG2AXI_WR_PL_DEPTH = 3
DTP_SMC_ADDR_WIDTH = 56
DTP_SMC_DATA_WIDTH = 64
DTP_OTP_ADDR_WIDTH = 32
DTP_OTP_DATA_WIDTH = 32
# The current OSS TB uses a compact local scan model for boundary-scan scenarios.
DTP_BSR_MODEL_LEN = 8


def _data_width_to_size_encoding(width_bits: int) -> int:
    """Return the JTAG2AXI CAPS data-size encoding for a power-of-two data width."""
    byte_width = width_bits // 8
    return byte_width.bit_length() - 1


def pack_jtag_caps() -> int:
    """Pack the default DTP JTAG_CAPS value for the standalone OSS DTP instance."""
    return (
        (DTP_NUM_XTRIG_INT_CT << 54)
        | (DTP_NUM_XTRIG_CTP << 48)
        | (DTP_NUM_EXTRA_STAPS << 44)
        | (1 << 43)  # STAP_IO_EN
        | (1 << 42)  # SEP_DBG_EN
        | (1 << 41)  # SMC_DBG_EN
        | (DTP_NUM_SMC_IC_RESET << 33)
        | (DTP_NUM_SEP_IC_RESET << 25)
        | (DTP_NUM_EXT_IC_RESET << 17)
        | (1 << 16)  # IC_RST_INST_EN
        | (1 << 15)  # TMP_INST_EN
        | (1 << 14)  # RUNBIST_INST_EN
        | (1 << 13)  # HIGHZ_INST_EN
        | (1 << 12)  # CLAMP_INST_EN
        | (1 << 11)  # INTEST_INST_EN
        | (1 << 10)  # EXTEST_PULSE_EN
        | (1 << 9)   # EXTEST_TRAIN_EN
        | (1 << 8)   # BSR_INST_EN
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
    """Pack a JTAG2AXI_CAPS value using the RTL bit-field encoding."""
    return (
        ((rd_pl_depth & 0x3) << 12)
        | ((wr_pl_depth & 0x3) << 10)
        | ((_data_width_to_size_encoding(data_width) & 0x7) << 7)
        | ((addr_width & 0x3F) << 1)
        | (bus_type & 0x1)
    )


DTP_EXPECTED_JTAG_CAPS = pack_jtag_caps()
DTP_EXPECTED_SMC_JTAG2AXI_CAPS = pack_jtag2axi_caps(
    bus_type=0,
    addr_width=DTP_SMC_ADDR_WIDTH,
    data_width=DTP_SMC_DATA_WIDTH,
)
DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS = pack_jtag2axi_caps(
    bus_type=1,
    addr_width=DTP_OTP_ADDR_WIDTH,
    data_width=DTP_OTP_DATA_WIDTH,
)
DTP_EXPECTED_SEP_OTP_JTAG2AXI_CAPS = DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS


@dataclass(frozen=True)
class DtpTapRegister:
    width: int
    instr: int
    write: bool = False


class DtpTapDevice:
    """DTP primary TAP with the TDRs exercised by the OSS tests."""

    def __init__(self, idle_delay: int = 0) -> None:
        self.name = "dtp"
        self.idcode = DTP_DEFAULT_IDCODE
        self.ir_len = DTP_IR_WIDTH
        self.regs: dict[str, DtpTapRegister] = {
            "BYPASS_00": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.BYPASS_00)),
            "IDCODE": DtpTapRegister(32, int(DtpJtagInstr.IDCODE)),
            "RUNBIST": DtpTapRegister(DTP_BSR_MODEL_LEN, int(DtpJtagInstr.RUNBIST)),
            "SAMPLE_PRELOAD": DtpTapRegister(
                DTP_BSR_MODEL_LEN,
                int(DtpJtagInstr.SAMPLE_PRELOAD),
                write=True,
            ),
            "EXTEST": DtpTapRegister(DTP_BSR_MODEL_LEN, int(DtpJtagInstr.EXTEST), write=True),
            "EXTEST_TRAIN": DtpTapRegister(
                DTP_BSR_MODEL_LEN,
                int(DtpJtagInstr.EXTEST_TRAIN),
                write=True,
            ),
            "EXTEST_PULSE": DtpTapRegister(
                DTP_BSR_MODEL_LEN,
                int(DtpJtagInstr.EXTEST_PULSE),
                write=True,
            ),
            "CLAMP": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP)),
            "HIGHZ": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.HIGHZ)),
            "INTEST": DtpTapRegister(DTP_BSR_MODEL_LEN, int(DtpJtagInstr.INTEST), write=True),
            "CLAMP_HOLD": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP_HOLD)),
            "CLAMP_RELEASE": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.CLAMP_RELEASE)),
            "TMP_STATUS": DtpTapRegister(
                DTP_TMP_STATUS_LEN,
                int(DtpJtagInstr.TMP_STATUS),
                write=True,
            ),
            "IC_RESET": DtpTapRegister(
                DTP_IC_RESET_LEN,
                int(DtpJtagInstr.IC_RESET),
                write=True,
            ),
            "TAP_3DCR": DtpTapRegister(
                DTP_TAP_3DCR_LEN,
                int(DtpJtagInstr.TAP_3DCR),
                write=True,
            ),
            "DEBUG_CONTROL": DtpTapRegister(
                DTP_DEBUG_CONTROL_LEN,
                int(DtpJtagInstr.DEBUG_CONTROL),
                write=True,
            ),
            "JTAG_CAPS": DtpTapRegister(DTP_JTAG_CAPS_LEN, int(DtpJtagInstr.JTAG_CAPS)),
            "SELECT_IJTAG": DtpTapRegister(
                DTP_SELECT_IJTAG_MIN_LEN,
                int(DtpJtagInstr.SELECT_IJTAG),
                write=True,
            ),
            "SMC_OTP_JTAG2AXI_CAPS": DtpTapRegister(
                DTP_JTAG2AXI_CAPS_LEN,
                int(DtpJtagInstr.SMC_OTP_JTAG2AXI_CAPS),
            ),
            "SEP_OTP_JTAG2AXI_CAPS": DtpTapRegister(
                DTP_JTAG2AXI_CAPS_LEN,
                int(DtpJtagInstr.SEP_OTP_JTAG2AXI_CAPS),
            ),
            "ZERO_LENGTH_BYPASS": DtpTapRegister(0, int(DtpJtagInstr.ZERO_LENGTH_BYPASS)),
            "INV_BYPASS": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.INV_BYPASS)),
            "BYPASS_3F": DtpTapRegister(DTP_BYPASS_LEN, int(DtpJtagInstr.BYPASS_3F)),
            "SMC_JTAG2AXI_CAPS": DtpTapRegister(
                DTP_JTAG2AXI_CAPS_LEN,
                int(DtpJtagInstr.SMC_JTAG2AXI_CAPS),
            ),
            "SMC_AXI_SINGLE_OP": DtpTapRegister(
                JTAG2AXI_TARGETS["smc_axi"].single_op_len,
                int(DtpJtagInstr.SMC_AXI_SINGLE_OP),
                write=True,
            ),
            "SMC_AXI_SERIES_CTRL": DtpTapRegister(
                JTAG2AXI_TARGETS["smc_axi"].series_ctrl_len,
                int(DtpJtagInstr.SMC_AXI_SERIES_CTRL),
                write=True,
            ),
            "SMC_OTP_AXI_SINGLE_OP": DtpTapRegister(
                JTAG2AXI_TARGETS["smc_otp"].single_op_len,
                int(DtpJtagInstr.SMC_OTP_AXI_SINGLE_OP),
                write=True,
            ),
            "SMC_OTP_AXI_SERIES_CTRL": DtpTapRegister(
                JTAG2AXI_TARGETS["smc_otp"].series_ctrl_len,
                int(DtpJtagInstr.SMC_OTP_AXI_SERIES_CTRL),
                write=True,
            ),
            "SEP_OTP_AXI_SINGLE_OP": DtpTapRegister(
                JTAG2AXI_TARGETS["sep_otp"].single_op_len,
                int(DtpJtagInstr.SEP_OTP_AXI_SINGLE_OP),
                write=True,
            ),
            "SEP_OTP_AXI_SERIES_CTRL": DtpTapRegister(
                JTAG2AXI_TARGETS["sep_otp"].series_ctrl_len,
                int(DtpJtagInstr.SEP_OTP_AXI_SERIES_CTRL),
                write=True,
            ),
        }
        # Idle TCK cycles after every op (JTAG2AXI CDC + AXI round trip).
        self.idle_delay = idle_delay

    def reg(self, name: str) -> DtpTapRegister:
        return self.regs[name]
