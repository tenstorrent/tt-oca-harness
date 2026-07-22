# SPDX-License-Identifier: Apache-2.0
"""DTP JTAG types and helpers shared by the OSS cocotb tests.

Only the pieces needed by the public smoke/functional tests are defined here.
The full instruction set lives in the DTP spec; this mirrors the opcodes used by
the open-source JTAG and JTAG2AXI tests.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import IntEnum

# Primary TAP instruction register width (6 bits; opcodes span 0x00..0x2C).
DTP_IR_WIDTH = 6


class DtpJtagInstr(IntEnum):
    """DTP primary TAP (PTAP) instruction opcodes (subset used by OSS tests)."""

    BYPASS_00 = 0x00
    IDCODE = 0x01
    RUNBIST = 0x02
    SAMPLE_PRELOAD = 0x03
    EXTEST = 0x04
    EXTEST_TRAIN = 0x05
    EXTEST_PULSE = 0x06
    CLAMP = 0x07
    HIGHZ = 0x08
    INTEST = 0x09
    CLAMP_HOLD = 0x0A
    CLAMP_RELEASE = 0x0B
    TMP_STATUS = 0x0C
    IC_RESET = 0x0D
    TAP_3DCR = 0x0E
    UNDEFINED_BYPASS_0F = 0x0F
    RISCV_RESERVED_0 = 0x10
    RISCV_RESERVED_1 = 0x11
    RISCV_RESERVED_2 = 0x12
    RISCV_RESERVED_3 = 0x13
    RISCV_RESERVED_4 = 0x14
    RISCV_RESERVED_5 = 0x15
    RISCV_RESERVED_6 = 0x16
    RISCV_RESERVED_7 = 0x17
    DEBUG_CONTROL = 0x18
    JTAG_CAPS = 0x19
    SELECT_IJTAG = 0x1A
    SMC_OTP_JTAG2AXI_CAPS = 0x1B
    SMC_OTP_AXI_SINGLE_OP = 0x1C
    SMC_OTP_AXI_SERIES_CTRL = 0x1D
    SMC_OTP_AXI_SERIES_DATA_INCR = 0x1E
    SMC_OTP_AXI_SERIES_DATA_NO_INCR = 0x1F
    SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x20
    SEP_OTP_JTAG2AXI_CAPS = 0x21
    SEP_OTP_AXI_SINGLE_OP = 0x22
    SEP_OTP_AXI_SERIES_CTRL = 0x23
    SEP_OTP_AXI_SERIES_DATA_INCR = 0x24
    SEP_OTP_AXI_SERIES_DATA_NO_INCR = 0x25
    SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x26
    # SMC fabric debug JTAG2AXI bridge TDRs
    SMC_JTAG2AXI_CAPS = 0x27
    SMC_AXI_SINGLE_OP = 0x28
    SMC_AXI_SERIES_CTRL = 0x29
    SMC_AXI_SERIES_DATA_INCR = 0x2A
    SMC_AXI_SERIES_DATA_NO_INCR = 0x2B
    SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x2C
    UNDEFINED_BYPASS_2D = 0x2D
    UNDEFINED_BYPASS_2E = 0x2E
    UNDEFINED_BYPASS_2F = 0x2F
    UNDEFINED_BYPASS_30 = 0x30
    UNDEFINED_BYPASS_31 = 0x31
    UNDEFINED_BYPASS_32 = 0x32
    UNDEFINED_BYPASS_33 = 0x33
    UNDEFINED_BYPASS_34 = 0x34
    UNDEFINED_BYPASS_35 = 0x35
    UNDEFINED_BYPASS_36 = 0x36
    UNDEFINED_BYPASS_37 = 0x37
    UNDEFINED_BYPASS_38 = 0x38
    UNDEFINED_BYPASS_39 = 0x39
    UNDEFINED_BYPASS_3A = 0x3A
    UNDEFINED_BYPASS_3B = 0x3B
    UNDEFINED_BYPASS_3C = 0x3C
    ZERO_LENGTH_BYPASS = 0x3D
    INV_BYPASS = 0x3E
    BYPASS_3F = 0x3F


UNDEFINED_BYPASS_INSTRS = tuple(
    DtpJtagInstr(value)
    for value in [0x0F, *range(0x10, 0x18), *range(0x2D, 0x3D)]
)


class DtpTapState(IntEnum):
    """IEEE 1149.1 TAP controller states as one-hot values from `tap_state_e`."""

    TEST_LOGIC_RESET = 0x0001
    RUN_TEST_IDLE = 0x0002
    SELECT_DR_SCAN = 0x0004
    CAPTURE_DR = 0x0008
    SHIFT_DR = 0x0010
    EXIT1_DR = 0x0020
    PAUSE_DR = 0x0040
    EXIT2_DR = 0x0080
    UPDATE_DR = 0x0100
    SELECT_IR_SCAN = 0x0200
    CAPTURE_IR = 0x0400
    SHIFT_IR = 0x0800
    EXIT1_IR = 0x1000
    PAUSE_IR = 0x2000
    EXIT2_IR = 0x4000
    UPDATE_IR = 0x8000


class DtpTapFsm:
    """Reference IEEE 1149.1 TAP state machine used by open-source sequences."""

    _TRANSITIONS: dict[DtpTapState, tuple[DtpTapState, DtpTapState]] = {
        DtpTapState.TEST_LOGIC_RESET: (
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.TEST_LOGIC_RESET,
        ),
        DtpTapState.RUN_TEST_IDLE: (
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.SELECT_DR_SCAN,
        ),
        DtpTapState.SELECT_DR_SCAN: (
            DtpTapState.CAPTURE_DR,
            DtpTapState.SELECT_IR_SCAN,
        ),
        DtpTapState.CAPTURE_DR: (
            DtpTapState.SHIFT_DR,
            DtpTapState.EXIT1_DR,
        ),
        DtpTapState.SHIFT_DR: (
            DtpTapState.SHIFT_DR,
            DtpTapState.EXIT1_DR,
        ),
        DtpTapState.EXIT1_DR: (
            DtpTapState.PAUSE_DR,
            DtpTapState.UPDATE_DR,
        ),
        DtpTapState.PAUSE_DR: (
            DtpTapState.PAUSE_DR,
            DtpTapState.EXIT2_DR,
        ),
        DtpTapState.EXIT2_DR: (
            DtpTapState.SHIFT_DR,
            DtpTapState.UPDATE_DR,
        ),
        DtpTapState.UPDATE_DR: (
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.SELECT_DR_SCAN,
        ),
        DtpTapState.SELECT_IR_SCAN: (
            DtpTapState.CAPTURE_IR,
            DtpTapState.TEST_LOGIC_RESET,
        ),
        DtpTapState.CAPTURE_IR: (
            DtpTapState.SHIFT_IR,
            DtpTapState.EXIT1_IR,
        ),
        DtpTapState.SHIFT_IR: (
            DtpTapState.SHIFT_IR,
            DtpTapState.EXIT1_IR,
        ),
        DtpTapState.EXIT1_IR: (
            DtpTapState.PAUSE_IR,
            DtpTapState.UPDATE_IR,
        ),
        DtpTapState.PAUSE_IR: (
            DtpTapState.PAUSE_IR,
            DtpTapState.EXIT2_IR,
        ),
        DtpTapState.EXIT2_IR: (
            DtpTapState.SHIFT_IR,
            DtpTapState.UPDATE_IR,
        ),
        DtpTapState.UPDATE_IR: (
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.SELECT_DR_SCAN,
        ),
    }

    @classmethod
    def get_next_state(cls, current_state: DtpTapState, tms: int) -> DtpTapState:
        """Return the TAP state reached after one TMS-sampled TCK edge."""
        return cls._TRANSITIONS[current_state][int(tms) & 0x1]

    @classmethod
    def get_final_state(
        cls,
        start_state: DtpTapState,
        tms_list: list[int],
    ) -> DtpTapState:
        """Return the state reached after applying a TMS sequence."""
        state = start_state
        for tms in tms_list:
            state = cls.get_next_state(state, tms)
        return state

    @classmethod
    def get_tms_path(
        cls,
        start_state: DtpTapState,
        target_state: DtpTapState,
    ) -> list[int]:
        """Return a shortest TMS path between two TAP states."""
        if start_state == target_state:
            return []

        queue: deque[tuple[DtpTapState, list[int]]] = deque([(start_state, [])])
        seen = {start_state}

        while queue:
            state, path = queue.popleft()
            for tms in (0, 1):
                next_state = cls.get_next_state(state, tms)
                if next_state in seen:
                    continue
                next_path = path + [tms]
                if next_state == target_state:
                    return next_path
                seen.add(next_state)
                queue.append((next_state, next_path))

        raise ValueError(f"no TAP path from {start_state.name} to {target_state.name}")


class DtpJtag2AxiOp(IntEnum):
    """JTAG2AXI single-op operation request (OP field on issue)."""

    NOP = 0
    READ = 1
    WRITE = 2


class DtpJtag2AxiStatus(IntEnum):
    """JTAG2AXI single-op capture status (OP field on response)."""

    SUCCESS = 0
    SLVERR = 1
    DECERR = 2
    BUSY_OR_FULL = 3


@dataclass(frozen=True)
class DtpJtag2AxiTargetCfg:
    """Geometry and TDR register names for one DTP JTAG2AXI bridge target."""

    name: str
    single_op_reg: str
    series_ctrl_reg: str
    series_data_incr_instr: DtpJtagInstr
    series_data_no_incr_instr: DtpJtagInstr
    series_data_with_status_instr: DtpJtagInstr
    addr_width: int
    data_width: int
    size_bits: int
    wstrb_bits: int
    default_size: int
    beat_bytes: int
    memory_attr: str
    activity_prefix: str
    security_disable_bits: tuple[str, ...]

    @property
    def single_op_len(self) -> int:
        return 2 + self.size_bits + self.wstrb_bits + self.data_width + self.addr_width

    @property
    def series_ctrl_len(self) -> int:
        return 2 + self.size_bits + 2 + self.addr_width + 1

    @property
    def required_enable_bits(self) -> tuple[str, ...]:
        """Lifecycle feat_ctrl enables that must all be high for this bridge."""
        return self.security_disable_bits


# SMC fabric debug AXI geometry (dtp_pkg: ADDR=56, DATA=64).
SMC_DBG_ADDR_WIDTH = 56
SMC_DBG_DATA_WIDTH = 64
SMC_DBG_SIZE_BITS = 2          # SCAN_CHAIN_SIZE_FIELD_WIDTH for 64-bit data
SMC_DBG_WSTRB_BITS = 8         # DATA_WIDTH/8
SMC_DBG_AXSIZE_8B = 3          # AXI awsize/arsize for a full 8-byte beat

# SINGLE_OP DR layout (LSB-first): OP[2] | SIZE | WSTRB | DATA | ADDR
_OP_OFF = 0
_SIZE_OFF = _OP_OFF + 2
_WSTRB_OFF = _SIZE_OFF + SMC_DBG_SIZE_BITS
_DATA_OFF = _WSTRB_OFF + SMC_DBG_WSTRB_BITS
_ADDR_OFF = _DATA_OFF + SMC_DBG_DATA_WIDTH
SMC_DBG_SINGLE_OP_LEN = _ADDR_OFF + SMC_DBG_ADDR_WIDTH  # 132

# SERIES_CTRL DR layout (LSB-first): OP[2] | SIZE | PL_DEPTH[2] | ADDR | RESET
_SERIES_OP_OFF = 0
_SERIES_SIZE_OFF = _SERIES_OP_OFF + 2
_SERIES_PL_DEPTH_OFF = _SERIES_SIZE_OFF + SMC_DBG_SIZE_BITS
_SERIES_ADDR_OFF = _SERIES_PL_DEPTH_OFF + 2
_SERIES_RESET_OFF = _SERIES_ADDR_OFF + SMC_DBG_ADDR_WIDTH
SMC_DBG_SERIES_CTRL_LEN = _SERIES_RESET_OFF + 1  # 63

JTAG2AXI_TARGETS: dict[str, DtpJtag2AxiTargetCfg] = {
    "smc_axi": DtpJtag2AxiTargetCfg(
        name="smc_axi",
        single_op_reg="SMC_AXI_SINGLE_OP",
        series_ctrl_reg="SMC_AXI_SERIES_CTRL",
        series_data_incr_instr=DtpJtagInstr.SMC_AXI_SERIES_DATA_INCR,
        series_data_no_incr_instr=DtpJtagInstr.SMC_AXI_SERIES_DATA_NO_INCR,
        series_data_with_status_instr=DtpJtagInstr.SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS,
        addr_width=SMC_DBG_ADDR_WIDTH,
        data_width=SMC_DBG_DATA_WIDTH,
        size_bits=SMC_DBG_SIZE_BITS,
        wstrb_bits=SMC_DBG_WSTRB_BITS,
        default_size=SMC_DBG_AXSIZE_8B,
        beat_bytes=8,
        memory_attr="axi_ram",
        activity_prefix="smc_axi",
        security_disable_bits=("soc_debug", "ap_debug"),
    ),
    "smc_otp": DtpJtag2AxiTargetCfg(
        name="smc_otp",
        single_op_reg="SMC_OTP_AXI_SINGLE_OP",
        series_ctrl_reg="SMC_OTP_AXI_SERIES_CTRL",
        series_data_incr_instr=DtpJtagInstr.SMC_OTP_AXI_SERIES_DATA_INCR,
        series_data_no_incr_instr=DtpJtagInstr.SMC_OTP_AXI_SERIES_DATA_NO_INCR,
        series_data_with_status_instr=DtpJtagInstr.SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS,
        addr_width=32,
        data_width=32,
        size_bits=2,
        wstrb_bits=4,
        default_size=2,
        beat_bytes=4,
        memory_attr="smc_otp_axil_ram",
        activity_prefix="smc_otp_axil",
        security_disable_bits=("fuse_test", "soc_debug", "ap_debug"),
    ),
    "sep_otp": DtpJtag2AxiTargetCfg(
        name="sep_otp",
        single_op_reg="SEP_OTP_AXI_SINGLE_OP",
        series_ctrl_reg="SEP_OTP_AXI_SERIES_CTRL",
        series_data_incr_instr=DtpJtagInstr.SEP_OTP_AXI_SERIES_DATA_INCR,
        series_data_no_incr_instr=DtpJtagInstr.SEP_OTP_AXI_SERIES_DATA_NO_INCR,
        series_data_with_status_instr=DtpJtagInstr.SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS,
        addr_width=32,
        data_width=32,
        size_bits=2,
        wstrb_bits=4,
        default_size=2,
        beat_bytes=4,
        memory_attr="sep_otp_axil_ram",
        activity_prefix="sep_otp_axil",
        security_disable_bits=("fuse_test", "sep_debug", "soc_debug", "ap_debug"),
    ),
}


def get_jtag2axi_target(target: str | DtpJtag2AxiTargetCfg) -> DtpJtag2AxiTargetCfg:
    """Return normalized target metadata for JTAG2AXI helper code."""
    if isinstance(target, DtpJtag2AxiTargetCfg):
        return target
    return JTAG2AXI_TARGETS[target]


def series_data_len(size: int, *, with_status: bool = False) -> int:
    """Return the SMC series data TDR width for one transfer size.

    The DTP series-data TDR is sized to the active transfer payload, not the
    whole 64-bit bridge width. The optional status/increment bit is the MSB used
    by *_DATA_WITH_ERROR_STATUS.
    """
    payload_bits = 8 * (1 << size)
    return payload_bits + (1 if with_status else 0)


def pack_single_op(
    op: DtpJtag2AxiOp,
    addr: int,
    data: int = 0,
    wstrb: int = 0,
    size: int = SMC_DBG_AXSIZE_8B,
    *,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> int:
    """Pack a target-specific *_AXI_SINGLE_OP DR value (issue direction)."""
    cfg = get_jtag2axi_target(target)
    size_off = 2
    wstrb_off = size_off + cfg.size_bits
    data_off = wstrb_off + cfg.wstrb_bits
    addr_off = data_off + cfg.data_width
    return (
        (int(op) & 0x3)
        | ((size & ((1 << cfg.size_bits) - 1)) << size_off)
        | ((wstrb & ((1 << cfg.wstrb_bits) - 1)) << wstrb_off)
        | ((data & ((1 << cfg.data_width) - 1)) << data_off)
        | ((addr & ((1 << cfg.addr_width) - 1)) << addr_off)
    )


def unpack_single_op(
    value: int,
    *,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> tuple[int, int]:
    """Return (status, rdata) from a captured target SINGLE_OP DR value."""
    cfg = get_jtag2axi_target(target)
    data_off = 2 + cfg.size_bits + cfg.wstrb_bits
    status = value & 0x3
    rdata = (value >> data_off) & ((1 << cfg.data_width) - 1)
    return status, rdata


def pack_series_ctrl(
    op: DtpJtag2AxiOp,
    addr: int,
    *,
    pipeline_depth: int = 0,
    size: int = SMC_DBG_AXSIZE_8B,
    reset: int = 0,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> int:
    """Pack a target-specific *_AXI_SERIES_CTRL DR value.

    Bit ordering matches the legacy DTP cocotb helper and RTL scan direction:
    OP in the low bits, then SIZE, pipeline depth, ADDR, and RESET as the MSB.
    """
    cfg = get_jtag2axi_target(target)
    size_off = 2
    pl_depth_off = size_off + cfg.size_bits
    addr_off = pl_depth_off + 2
    reset_off = addr_off + cfg.addr_width
    return (
        (int(op) & 0x3)
        | ((size & ((1 << cfg.size_bits) - 1)) << size_off)
        | ((pipeline_depth & 0x3) << pl_depth_off)
        | ((addr & ((1 << cfg.addr_width) - 1)) << addr_off)
        | ((reset & 0x1) << reset_off)
    )


def unpack_series_ctrl(
    value: int,
    *,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> tuple[int, int, int, int, int]:
    """Return (reset, addr, pipeline_depth, size, status) from SERIES_CTRL."""
    cfg = get_jtag2axi_target(target)
    size_off = 2
    pl_depth_off = size_off + cfg.size_bits
    addr_off = pl_depth_off + 2
    reset_off = addr_off + cfg.addr_width
    status = value & 0x3
    size = (value >> size_off) & ((1 << cfg.size_bits) - 1)
    pipeline_depth = (value >> pl_depth_off) & 0x3
    addr = (value >> addr_off) & ((1 << cfg.addr_width) - 1)
    reset = (value >> reset_off) & 0x1
    return reset, addr, pipeline_depth, size, status


def pack_series_data(data: int, size: int, *, increment: int | None = None) -> tuple[int, int]:
    """Pack a series-data TDR value and return (value, width)."""
    payload_bits = series_data_len(size)
    value = data & ((1 << payload_bits) - 1)
    if increment is not None:
        value |= (increment & 0x1) << payload_bits
    return value, payload_bits + (1 if increment is not None else 0)


def unpack_series_data(value: int, size: int, *, with_status: bool = False) -> tuple[int, int]:
    """Return (data, status_bit) from a captured series-data TDR value."""
    payload_bits = series_data_len(size)
    data = value & ((1 << payload_bits) - 1)
    status = (value >> payload_bits) & 0x1 if with_status else 0
    return data, status


def decode_idcode(idcode: int) -> dict[str, int]:
    """Decode an IEEE 1149.1 32-bit IDCODE into its named fields."""
    return {
        "lsb": idcode & 0x1,
        "manufacturer": (idcode >> 1) & 0x7FF,
        "part_number": (idcode >> 12) & 0xFFFF,
        "version": (idcode >> 28) & 0xF,
    }
