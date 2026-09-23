# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP JTAG types and helpers shared by the OSS cocotb tests.

The DTP instantiates one JTAG Interface Unit as its primary debug access point
(`hw/sys/dtp/doc/jtag.adoc`, "DTP JTAG Topology"). The instruction, TAP-state and
JTAG2AXI tables below are transcriptions of that unit's and its PTAP's
documentation; each names the document and section it copies. The three
JTAG2AXI bridge geometries are the values each bridge publishes in its
`*_JTAG2AXI_CAPS` TDR, compared with the DUT every pass by the geometry gate,
and every TDR field width derives from them.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum, IntEnum

# Primary TAP instruction register width: "6-bit instruction encodings"
# (`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc` and
# `hw/ip/jtag/jtag_ptap/doc/interface.adoc`, both "Instruction Encodings").
DTP_IR_WIDTH = 6


class DtpJtagInstr(IntEnum):
    """DTP primary TAP (PTAP) instruction opcodes, one member per 6-bit encoding.

    Transcription of the "Instruction Encodings" table in
    `hw/ip/jtag/jtag_intf_unit/doc/interface.adoc`. The PTAP's own table
    (`hw/ip/jtag/jtag_ptap/doc/interface.adoc`, "Instruction Encodings") lists
    the same encodings for the instructions it defines and omits the RISC-V
    reserved range and the JTAG2AXI bridge TDRs. Member names are the document's
    names; the two BYPASS rows and the encodings without a row carry the encoding
    as a suffix. Both tables note that every encoding not explicitly defined in
    the table maps to BYPASS.
    """

    # IEEE 1149.1 and IEEE 1838 instructions.
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
    # No row in either table; maps to BYPASS.
    UNDEFINED_BYPASS_0F = 0x0F
    # "Reserved for RISC-V" in the interface-unit table; the PTAP table has no
    # row for 0x10-0x17, so they map to BYPASS.
    RISCV_RESERVED_0 = 0x10
    RISCV_RESERVED_1 = 0x11
    RISCV_RESERVED_2 = 0x12
    RISCV_RESERVED_3 = 0x13
    RISCV_RESERVED_4 = 0x14
    RISCV_RESERVED_5 = 0x15
    RISCV_RESERVED_6 = 0x16
    RISCV_RESERVED_7 = 0x17
    # Debug and clock stop control, capabilities readback, iJTAG network selection.
    DEBUG_CONTROL = 0x18
    JTAG_CAPS = 0x19
    SELECT_IJTAG = 0x1A
    # SMC OTP controller JTAG2AXI bridge TDRs (interface-unit table only).
    SMC_OTP_JTAG2AXI_CAPS = 0x1B
    SMC_OTP_AXI_SINGLE_OP = 0x1C
    SMC_OTP_AXI_SERIES_CTRL = 0x1D
    SMC_OTP_AXI_SERIES_DATA_INCR = 0x1E
    SMC_OTP_AXI_SERIES_DATA_NO_INCR = 0x1F
    SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x20
    # SEP OTP controller JTAG2AXI bridge TDRs (interface-unit table only).
    SEP_OTP_JTAG2AXI_CAPS = 0x21
    SEP_OTP_AXI_SINGLE_OP = 0x22
    SEP_OTP_AXI_SERIES_CTRL = 0x23
    SEP_OTP_AXI_SERIES_DATA_INCR = 0x24
    SEP_OTP_AXI_SERIES_DATA_NO_INCR = 0x25
    SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x26
    # SMC fabric debug JTAG2AXI bridge TDRs (interface-unit table only).
    SMC_JTAG2AXI_CAPS = 0x27
    SMC_AXI_SINGLE_OP = 0x28
    SMC_AXI_SERIES_CTRL = 0x29
    SMC_AXI_SERIES_DATA_INCR = 0x2A
    SMC_AXI_SERIES_DATA_NO_INCR = 0x2B
    SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x2C
    # No row in either table for 0x2D-0x3C; they map to BYPASS.
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
    # Zero-length, inverted, and all-ones IEEE 1149.1 BYPASS.
    ZERO_LENGTH_BYPASS = 0x3D
    INV_BYPASS = 0x3E
    BYPASS_3F = 0x3F


# Encodings for which neither table defines an instruction; the tables' note
# maps them to BYPASS.
UNDEFINED_BYPASS_INSTRS = tuple(
    DtpJtagInstr(value) for value in [0x0F, *range(0x10, 0x18), *range(0x2D, 0x3D)]
)


class DtpTapState(IntEnum):
    """IEEE 1149.1 TAP controller states as 16-bit one-hot encodings.

    Transcription of the state table in `hw/ip/jtag/jtag_ptap/doc/architecture.adoc`,
    "TAP Controller State Machine".
    """

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
    """JTAG2AXI `op` field as written by the debugger.

    From the `*_AXI_SINGLE_OP` and `*_AXI_SERIES_CTRL` tables in
    `hw/ip/jtag/jtag_ptap/doc/architecture.adoc`, "JTAG2AXI Support": 0 nop,
    1 read, 2 write, 3 reserved.
    """

    NOP = 0
    READ = 1
    WRITE = 2


class DtpJtag2AxiStatus(IntEnum):
    """JTAG2AXI `op` field as read back by the debugger.

    From the same `*_AXI_SINGLE_OP` / `*_AXI_SERIES_CTRL` tables: 0 OKAY,
    1 SLVERR, 2 DECERR or other error, 3 operation attempted while the previous
    one was still pending.
    """

    SUCCESS = 0
    SLVERR = 1
    DECERR = 2
    BUSY_OR_FULL = 3


class DtpScanCtrlExpect(Enum):
    """What a window over one host chain's scan controls shows across a DR scan.

    ``SELECTED``: the chain's select is high and the TAP's capture, shift, and
    update strobes pulse; ``UNSELECTED``: select stays low while the strobes
    pulse (the strobes are the TAP's and only select is qualified by the
    instruction); ``GATED``: the chain's host holds select and every strobe low.
    """

    SELECTED = "selected"
    UNSELECTED = "unselected"
    GATED = "gated"


# Reset-abort scenario evidence: the bridge observed mid-flight before the
# reset, its FSM back in IDLE after it, the CDC's TCK-side clear seen, no
# escaped write, and a recovered status.
ABORT_MIDFLIGHT_CHECK_ID = "CHK-J2A-ABORT-MIDFLIGHT"
ABORT_FSM_CHECK_ID = "CHK-J2A-ABORT-FSM"
CDC_CLEAR_CHECK_ID = "CHK-J2A-CDC-CLEAR"
ABORT_ESCAPE_CHECK_ID = "CHK-J2A-ABORT-ESCAPE"
ABORT_RECOVERY_CHECK_ID = "CHK-J2A-ABORT-RECOVERY"
# A READY stall observed from the DUT side: the bridge FSM dwells on the
# stalled path and the first status poll reads BUSY_OR_FULL.
STALL_FSM_CHECK_ID = "CHK-J2A-STALL-FSM"
STALL_BUSY_CHECK_ID = "CHK-J2A-STALL-BUSY"


def size_field_bits(data_width: int) -> int:
    """Width of the JTAG2AXI ``size`` field for a bridge data width.

    The smallest width that encodes every AxSIZE up to a full beat, and at
    least one bit; the ``*_AXI_SINGLE_OP`` table of
    ``hw/ip/jtag/jtag_ptap/doc/architecture.adoc`` names this width ``$bits(size)``.
    """
    data_size = (data_width // 8).bit_length() - 1
    return max(1, data_size.bit_length())


@dataclass(frozen=True)
class DtpJtag2AxiTargetCfg:
    """Geometry and TDR register names for one DTP JTAG2AXI bridge target.

    ``bus_type`` (0 AXI4, 1 AXI4-Lite), ``addr_width``, and ``data_width`` are
    the values the bridge publishes in its ``*_JTAG2AXI_CAPS`` TDR
    (``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``, "*_JTAG2AXI_CAPS"); the
    geometry gate compares them with the DUT every pass. Every other width
    derives from them by the ``*_AXI_SINGLE_OP`` and ``*_AXI_SERIES_CTRL``
    tables in the same document.
    """

    name: str
    bus_type: int
    addr_width: int
    data_width: int
    caps_reg: str
    single_op_reg: str
    series_ctrl_reg: str
    series_data_incr_instr: DtpJtagInstr
    series_data_no_incr_instr: DtpJtagInstr
    series_data_with_status_instr: DtpJtagInstr
    memory_attr: str
    activity_prefix: str
    dbg_disable_bit: str

    @property
    def data_size(self) -> int:
        """CAPS ``data_size``: the beat width in bytes as a power of two."""
        return (self.data_width // 8).bit_length() - 1

    @property
    def beat_bytes(self) -> int:
        return self.data_width // 8

    @property
    def default_size(self) -> int:
        """AxSIZE of a full-width beat."""
        return self.data_size

    @property
    def size_bits(self) -> int:
        return size_field_bits(self.data_width)

    @property
    def wstrb_bits(self) -> int:
        """One strobe per beat byte (``2**data_size``)."""
        return 1 << self.data_size

    @property
    def single_op_len(self) -> int:
        """``op | size | wstrb | data | address``, LSB first."""
        return 2 + self.size_bits + self.wstrb_bits + self.data_width + self.addr_width

    @property
    def series_ctrl_len(self) -> int:
        """``op | size | pl_depth | address | reset``, LSB first."""
        return 2 + self.size_bits + 2 + self.addr_width + 1


# One row per bridge. The TDR names are the interface-unit instruction table's
# (`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc`).
JTAG2AXI_TARGETS: dict[str, DtpJtag2AxiTargetCfg] = {
    "smc_axi": DtpJtag2AxiTargetCfg(
        name="smc_axi",
        bus_type=0,
        addr_width=56,
        data_width=64,
        caps_reg="SMC_JTAG2AXI_CAPS",
        single_op_reg="SMC_AXI_SINGLE_OP",
        series_ctrl_reg="SMC_AXI_SERIES_CTRL",
        series_data_incr_instr=DtpJtagInstr.SMC_AXI_SERIES_DATA_INCR,
        series_data_no_incr_instr=DtpJtagInstr.SMC_AXI_SERIES_DATA_NO_INCR,
        series_data_with_status_instr=DtpJtagInstr.SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS,
        memory_attr="axi_ram",
        activity_prefix="smc_axi",
        dbg_disable_bit="smc_jtag2axi",
    ),
    "smc_otp": DtpJtag2AxiTargetCfg(
        name="smc_otp",
        bus_type=1,
        addr_width=32,
        data_width=32,
        caps_reg="SMC_OTP_JTAG2AXI_CAPS",
        single_op_reg="SMC_OTP_AXI_SINGLE_OP",
        series_ctrl_reg="SMC_OTP_AXI_SERIES_CTRL",
        series_data_incr_instr=DtpJtagInstr.SMC_OTP_AXI_SERIES_DATA_INCR,
        series_data_no_incr_instr=DtpJtagInstr.SMC_OTP_AXI_SERIES_DATA_NO_INCR,
        series_data_with_status_instr=DtpJtagInstr.SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS,
        memory_attr="smc_otp_axil_ram",
        activity_prefix="smc_otp_axil",
        dbg_disable_bit="smc_otp_jtag2axi",
    ),
    "sep_otp": DtpJtag2AxiTargetCfg(
        name="sep_otp",
        bus_type=1,
        addr_width=32,
        data_width=32,
        caps_reg="SEP_OTP_JTAG2AXI_CAPS",
        single_op_reg="SEP_OTP_AXI_SINGLE_OP",
        series_ctrl_reg="SEP_OTP_AXI_SERIES_CTRL",
        series_data_incr_instr=DtpJtagInstr.SEP_OTP_AXI_SERIES_DATA_INCR,
        series_data_no_incr_instr=DtpJtagInstr.SEP_OTP_AXI_SERIES_DATA_NO_INCR,
        series_data_with_status_instr=DtpJtagInstr.SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS,
        memory_attr="sep_otp_axil_ram",
        activity_prefix="sep_otp_axil",
        dbg_disable_bit="sep_otp_jtag2axi",
    ),
}

# SMC fabric bridge shorthands of the SMC-only helpers.
SMC_DBG_AXSIZE_8B = JTAG2AXI_TARGETS["smc_axi"].default_size
SMC_DBG_SINGLE_OP_LEN = JTAG2AXI_TARGETS["smc_axi"].single_op_len
SMC_DBG_SERIES_CTRL_LEN = JTAG2AXI_TARGETS["smc_axi"].series_ctrl_len


def get_jtag2axi_target(target: str | DtpJtag2AxiTargetCfg) -> DtpJtag2AxiTargetCfg:
    """Return normalized target metadata for JTAG2AXI helper code."""
    if isinstance(target, DtpJtag2AxiTargetCfg):
        return target
    return JTAG2AXI_TARGETS[target]


def series_data_len(size: int, *, with_status: bool = False) -> int:
    """Return the series data TDR width for one transfer size.

    `*_AXI_SERIES_DATA_INCR` / `_NO_INCR` are n = 8*(2**size) bits and
    `*_AXI_SERIES_DATA_WITH_ERROR_STATUS` is n+1 bits with the increment/status
    bit at n (`hw/ip/jtag/jtag_ptap/doc/architecture.adoc`, "JTAG2AXI Support").
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
    """Pack a target-specific *_AXI_SINGLE_OP DR value (issue direction).

    Field order is that of the `*_AXI_SINGLE_OP` table: OP in the low bits,
    then SIZE, WSTRB, DATA, and ADDR.
    """
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

    Field order is that of the `*_AXI_SERIES_CTRL` table: OP in the low bits,
    then SIZE, pipeline depth, ADDR, and RESET as the MSB.
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
