# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP JTAG types and helpers shared by the OSS cocotb tests.

The DTP instantiates one JTAG Interface Unit as its primary debug access point
(`hw/sys/dtp/doc/jtag.adoc`, "DTP JTAG Topology"). The instruction and
JTAG2AXI tables below are transcriptions of that unit's and its PTAP's
documentation; each names the document and section it copies. The TAP states
are the shared ``ocah_jtag_vip.OcahJtagState``, whose one-hot values match the
PTAP's. The three
JTAG2AXI bridge geometries are part of the bench configuration `tb_top`
elaborates the DUT with: `dtp_dv_cfg` republishes them for the parity check
against the SystemVerilog package, the geometry gate compares each bridge's
`*_JTAG2AXI_CAPS` publication with them every pass, and every TDR field width
derives from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum

# Primary TAP instruction register width: "6-bit instruction encodings"
# (`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc` and
# `hw/ip/jtag/jtag_ptap/doc/interface.adoc`, both "Instruction Encodings").
DTP_IR_WIDTH = 6

# The value Capture-IR loads into the instruction shift register: 01 in the
# two LSBs and zeros above (IEEE 1149.1 7.1.1, `jtag_inst_reg`), which is the
# IDCODE opcode.
DTP_IR_CAPTURE_PATTERN = 0b01

# Scoreboard feature names: one Dtp<Feature>RefModel each (a test names the
# ones it must exercise in required_features).
DTP_FEATURE_IR_DECODE = "ir_decode"
DTP_FEATURE_IDCODE = "idcode"
DTP_FEATURE_BYPASS = "bypass"
DTP_FEATURE_XTRIG_CSR = "xtrig_csr"
DTP_FEATURE_XTRIG_DECODE = "xtrig_decode"
DTP_FEATURE_JTAG2AXI_REQ = "jtag2axi_req"
DTP_FEATURE_JTAG2AXI_STATUS = "jtag2axi_status"

# TCK cycles from the AXI-side response handshake to the first scan whose
# Capture-DR shows it: the B/R beat crosses the bridge's clearable CDC (three
# synchronizer stages on the gray pointer, then the FIFO pop), the bridge steps
# from its response wait through its status update into the status register,
# and the first crossing edge adds up to one TCK of phase; measured from the
# scan's start. A status capture whose scan starts inside this window after a
# completion is not checkable.
DTP_J2A_STATUS_SETTLE_TCK = 8


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


# A reset the sequence drove advanced its tb_top assertion counter by one.
RESET_COUNT_CHECK_ID = "CHK-RESET-COUNT"
# Reset-abort scenario evidence: the bridge observed mid-flight before the
# reset, its FSM back in IDLE after it, the CDC's TCK-side clear seen, no
# escaped write, and a recovered status.
ABORT_MIDFLIGHT_CHECK_ID = "CHK-J2A-ABORT-MIDFLIGHT"
ABORT_FSM_CHECK_ID = "CHK-J2A-ABORT-FSM"
CDC_CLEAR_CHECK_ID = "CHK-J2A-CDC-CLEAR"
# A reset placed inside a CDC clear sequence lands in the phase the scenario
# selected: the dtp_tb_if phase observable is set at the deposit.
CDC_PHASE_CHECK_ID = "CHK-J2A-CDC-PHASE"
ABORT_ESCAPE_CHECK_ID = "CHK-J2A-ABORT-ESCAPE"
ABORT_RECOVERY_CHECK_ID = "CHK-J2A-ABORT-RECOVERY"
# TCK-side clear evidence with a request held on the fabric: the held request
# reaches the fabric exactly once, in the clear phase the scenario selects;
# its response never reaches the JTAG side; and a request of the new session
# queued behind it completes after it with its own status and data.
ORPHAN_DRAIN_CHECK_ID = "CHK-J2A-ORPHAN-DRAIN"
ORPHAN_DISCARD_CHECK_ID = "CHK-J2A-ORPHAN-DISCARD"
ORPHAN_ORDER_CHECK_ID = "CHK-J2A-ORPHAN-ORDER"
# A READY stall observed from the DUT side: the bridge FSM dwells on the
# stalled path and the first status poll reads BUSY_OR_FULL.
STALL_FSM_CHECK_ID = "CHK-J2A-STALL-FSM"
STALL_BUSY_CHECK_ID = "CHK-J2A-STALL-BUSY"
# The READY stall observed on the bridge port: the tb_top stall counter of each
# channel the operation stalls advanced across it, and a channel of the
# operation the stall leaves alone counted no stall cycle.
STALL_HOLD_CHECK_ID = "CHK-J2A-STALL-HOLD"
# A gated bridge's SINGLE_OP register stays in the scan path and latches no
# update: every capture while gated equals the NOP capture taken before the
# disable, field by field.
GATE_TDR_CHECK_ID = "CHK-J2A-GATE-TDR"
# The op-status or SERIES_CTRL status carries the injected error code, and the
# WITH_ERROR_STATUS bit follows the faulted beat.
FAULT_STATUS_CHECK_ID = "CHK-J2A-FAULT-STATUS"
# Random-ops end state: every byte lane a stream wrote holds its last word and
# every untouched lane of a touched word holds its prior value.
MEM_IMAGE_CHECK_ID = "CHK-J2A-MEM-IMAGE"


def ic_reset_after_tlr(reset_hold: int, written: int, reset_image: int) -> int:
    """IC_RESET after a Test-Logic-Reset (PTAP document, "PTAP IC_RESET fields").

    With ``reset_hold`` 0 a TLR keeps every reset_enable and reset_control bit,
    and reset_hold with them; with ``reset_hold`` 1 a TLR restores the reset
    image. TRST and POR restore every bit.
    """
    return reset_image if reset_hold else written


# JTAG2AXI bridge geometry. The SMC fabric bridge drives SMC
# `jtag_axi_in_req_i`, whose row in the SMC port table states a 56-bit address
# and 64-bit data. The OTP bridges' AXI-Lite widths and every bridge's read and
# write pipeline depth are the bench's choice, published by each bridge through
# its `*_JTAG2AXI_CAPS` TDR ("PTAP JTAG2AXI capability fields" table). The
# depths differ per bridge and per direction, so a CAPS field wired to the
# wrong parameter reads back a value the bench does not expect.
DTP_SMC_AXI_ADDR_WIDTH = 56
DTP_SMC_AXI_DATA_WIDTH = 64
DTP_OTP_AXIL_ADDR_WIDTH = 32
DTP_OTP_AXIL_DATA_WIDTH = 32
DTP_SMC_OTP_RD_PL_DEPTH = 2
DTP_SMC_OTP_WR_PL_DEPTH = 1
DTP_SEP_OTP_RD_PL_DEPTH = 3
DTP_SEP_OTP_WR_PL_DEPTH = 2
DTP_SMC_RD_PL_DEPTH = 3
DTP_SMC_WR_PL_DEPTH = 0


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

    ``bus_type`` (0 AXI4, 1 AXI4-Lite), ``addr_width``, ``data_width``, and the
    two pipeline depths come from the bench configuration ``tb_top`` elaborates
    the DUT with (``dtp_dv_cfg``); the geometry gate compares the bridge's
    ``*_JTAG2AXI_CAPS`` publication (``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``,
    "*_JTAG2AXI_CAPS") with them every pass. Every other width derives from
    them by the ``*_AXI_SINGLE_OP`` and ``*_AXI_SERIES_CTRL`` tables in the same
    document.
    """

    name: str
    bus_type: int
    addr_width: int
    data_width: int
    rd_pl_depth: int
    wr_pl_depth: int
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

    def axsize(self, size: int) -> int:
        """Transfer size the bridge uses for a scanned ``size`` field.

        A size above ``data_size`` transfers one full beat
        (``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``, "*_AXI_SINGLE_OP").
        """
        return min(size, self.data_size)

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
        addr_width=DTP_SMC_AXI_ADDR_WIDTH,
        data_width=DTP_SMC_AXI_DATA_WIDTH,
        rd_pl_depth=DTP_SMC_RD_PL_DEPTH,
        wr_pl_depth=DTP_SMC_WR_PL_DEPTH,
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
        addr_width=DTP_OTP_AXIL_ADDR_WIDTH,
        data_width=DTP_OTP_AXIL_DATA_WIDTH,
        rd_pl_depth=DTP_SMC_OTP_RD_PL_DEPTH,
        wr_pl_depth=DTP_SMC_OTP_WR_PL_DEPTH,
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
        addr_width=DTP_OTP_AXIL_ADDR_WIDTH,
        data_width=DTP_OTP_AXIL_DATA_WIDTH,
        rd_pl_depth=DTP_SEP_OTP_RD_PL_DEPTH,
        wr_pl_depth=DTP_SEP_OTP_WR_PL_DEPTH,
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


def series_data_len(
    size: int,
    *,
    with_status: bool = False,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> int:
    """Return the series data TDR width for one scanned size on a target.

    `*_AXI_SERIES_DATA_INCR` / `_NO_INCR` are n = 8*(2**E) bits, where E is
    the effective size (the smaller of ``size`` and the target's
    ``data_size``), and `*_AXI_SERIES_DATA_WITH_ERROR_STATUS` is n+1 bits with
    the increment/status bit at n (`hw/ip/jtag/jtag_ptap/doc/architecture.adoc`,
    "JTAG2AXI Support").
    """
    payload_bits = 8 * (1 << get_jtag2axi_target(target).axsize(size))
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


def unpack_single_op_fields(
    value: int,
    *,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> tuple[int, int, int, int, int]:
    """Return (op, size, wstrb, data, addr) of a target SINGLE_OP DR value.

    The field order of ``pack_single_op``; on a capture ``op`` is the status.
    """
    cfg = get_jtag2axi_target(target)
    size_off = 2
    wstrb_off = size_off + cfg.size_bits
    data_off = wstrb_off + cfg.wstrb_bits
    addr_off = data_off + cfg.data_width
    return (
        value & 0x3,
        (value >> size_off) & ((1 << cfg.size_bits) - 1),
        (value >> wstrb_off) & ((1 << cfg.wstrb_bits) - 1),
        (value >> data_off) & ((1 << cfg.data_width) - 1),
        (value >> addr_off) & ((1 << cfg.addr_width) - 1),
    )


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


def pack_series_data(
    data: int,
    size: int,
    *,
    increment: int | None = None,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> tuple[int, int]:
    """Pack a series-data TDR value and return (value, width)."""
    payload_bits = series_data_len(size, target=target)
    value = data & ((1 << payload_bits) - 1)
    if increment is not None:
        value |= (increment & 0x1) << payload_bits
    return value, payload_bits + (1 if increment is not None else 0)


def unpack_series_data(
    value: int,
    size: int,
    *,
    with_status: bool = False,
    target: str | DtpJtag2AxiTargetCfg = "smc_axi",
) -> tuple[int, int]:
    """Return (data, status_bit) from a captured series-data TDR value."""
    payload_bits = series_data_len(size, target=target)
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
