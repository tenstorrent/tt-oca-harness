# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP JTAG types and helpers shared by the cocotb tests.

The DTP instantiates one JTAG Interface Unit as its primary debug access point
(`hw/sys/dtp/doc/jtag.adoc`, "DTP JTAG Topology"). The instruction and JTAG2AXI
tables below are transcriptions of that unit's and its PTAP's documentation;
each names the document and section it copies. The TAP states are the shared
``ocah_jtag_vip.OcahJtagState``, whose one-hot values match the PTAP's. The
three JTAG2AXI bridge geometries are part of the bench configuration `tb_top`
elaborates the DUT with: `dtp_dv_cfg` republishes them for the parity check
against the SystemVerilog package, and the geometry gate compares each bridge's
`sbcs` publication with them every pass. The SV-UVM twin is ``dtp_types.svh``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, StrEnum

__all__ = [
    "DMI_DATA_WIDTH",
    "DMI_LEN",
    "DTMCS_LEN",
    "DTP_DMI_BUSY_TCK",
    "DTP_DMI_SETTLE_TCK",
    "DTP_J2A_RESET_SYNC_TCK",
    "DTP_EXPECTED_DTMCS",
    "DTP_FEATURE_BYPASS",
    "DTP_FEATURE_IDCODE",
    "DTP_FEATURE_IR_DECODE",
    "DTP_FEATURE_JTAG2AXI_REQ",
    "DTP_FEATURE_JTAG2AXI_STATUS",
    "DTP_FEATURE_XTRIG_CSR",
    "DTP_FEATURE_XTRIG_DECODE",
    "DTP_IR_CAPTURE_PATTERN",
    "DTP_IR_WIDTH",
    "DTP_OTP_AXIL_ADDR_WIDTH",
    "DTP_OTP_AXIL_DATA_WIDTH",
    "DTP_SMC_AXI_ADDR_WIDTH",
    "DTP_SMC_AXI_DATA_WIDTH",
    "DTP_SMC_AXI_ID_WIDTH",
    "DTP_SMC_AXI_USER_WIDTH",
    "DtpDmReg",
    "DtpDmiOp",
    "DtpDmiStatus",
    "DtpJtag2AxiTargetCfg",
    "DtpJtagInstr",
    "DtpScanCtrlExpect",
    "DtpScanKind",
    "JTAG2AXI_TARGETS",
    "RESET_COUNT_CHECK_ID",
    "UNDEFINED_BYPASS_INSTRS",
    "decode_idcode",
    "get_jtag2axi_target",
    "ic_reset_after_tlr",
    "pack_dmi",
    "pack_sbcs",
    "unpack_dmi",
    "unpack_dtmcs",
    "unpack_sbcs",
]

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

# TCK cycles from the Update-DR of a DMI read or write to the first DMI
# capture or update that finds it complete: the request crosses into the
# system clock domain and the response back through the bridge's two-phase
# CDCs, three synchronizer stages each, at a system clock no slower than TCK,
# with the simulation CDC delay on every crossing. The bench's idle cycles
# after each access exceed it.
DTP_DMI_SETTLE_TCK = 24

# TCK cycles from the Update-DR of a DMI read or write in which every DMI
# capture or update still finds it in progress, at any clock ratio: the
# request leaves on the next TCK cycle, and the response then passes a
# three-stage synchronizer and one more register in the TCK domain before the
# bridge state machine samples it.
DTP_DMI_BUSY_TCK = 6

# TCK edges after the release of a JTAG2AXI bridge's reset for which its TCK
# side stays in reset outside test mode: the depth of the bridge's reset
# synchronizer. A DMI capture on one of them returns 0 and an update or a
# dmireset does nothing.
DTP_J2A_RESET_SYNC_TCK = 3


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
    # JTAG2AXI bridges: a DTMCS TDR and a DMI TDR each (interface-unit table only).
    SMC_OTP_DTMCS = 0x1B
    SMC_OTP_DMI = 0x1C
    SEP_OTP_DTMCS = 0x1D
    SEP_OTP_DMI = 0x1E
    SMC_DTMCS = 0x1F
    SMC_DMI = 0x20
    # No row in either table for 0x21-0x3C; they map to BYPASS.
    UNDEFINED_BYPASS_21 = 0x21
    UNDEFINED_BYPASS_22 = 0x22
    UNDEFINED_BYPASS_23 = 0x23
    UNDEFINED_BYPASS_24 = 0x24
    UNDEFINED_BYPASS_25 = 0x25
    UNDEFINED_BYPASS_26 = 0x26
    UNDEFINED_BYPASS_27 = 0x27
    UNDEFINED_BYPASS_28 = 0x28
    UNDEFINED_BYPASS_29 = 0x29
    UNDEFINED_BYPASS_2A = 0x2A
    UNDEFINED_BYPASS_2B = 0x2B
    UNDEFINED_BYPASS_2C = 0x2C
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
    DtpJtagInstr(value) for value in [0x0F, *range(0x10, 0x18), *range(0x21, 0x3D)]
)


class DtpDmiOp(IntEnum):
    """DMI ``op`` field as written by the debugger.

    From the "PTAP JTAG2AXI DMI fields" table in
    `hw/ip/jtag/jtag_ptap/doc/architecture.adoc`: 0 no operation, 1 read,
    2 write, 3 clear the sticky status.
    """

    NOP = 0
    READ = 1
    WRITE = 2
    CLEAR = 3


class DtpDmiStatus(IntEnum):
    """DMI ``op`` field as captured: the sticky status of the same table.

    0 the last operation completed, 2 an operation failed, 3 an operation was
    attempted while one was in progress.
    """

    SUCCESS = 0
    FAILED = 2
    BUSY = 3


class DtpDmReg(IntEnum):
    """Debug Module register addresses ("PTAP JTAG2AXI Debug Module registers")."""

    DMCONTROL = 0x10
    DMSTATUS = 0x11
    SBCS = 0x38
    SBADDRESS0 = 0x39
    SBADDRESS1 = 0x3A
    SBDATA0 = 0x3C
    SBDATA1 = 0x3D


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


class DtpScanKind(StrEnum):
    """The scan a composed STAP chain image is built for.

    ``DR``: a TAP_3DCR data scan, PTAP 3DCR first; ``IR``: an instruction
    scan, PTAP IR first; ``ZLB``: a data scan under ZERO_LENGTH_BYPASS;
    ``BYPASS``: a data scan under BYPASS, the PTAP bypass register first.
    """

    DR = "dr"
    IR = "ir"
    ZLB = "zlb"
    BYPASS = "bypass"


# A reset the sequence drove advanced its tb_top assertion counter by one.
RESET_COUNT_CHECK_ID = "CHK-RESET-COUNT"


def ic_reset_after_tlr(reset_hold: int, written: int, reset_image: int) -> int:
    """IC_RESET after a Test-Logic-Reset (PTAP document, "PTAP IC_RESET fields").

    With ``reset_hold`` 0 a TLR keeps every reset_enable and reset_control bit,
    and reset_hold with them; with ``reset_hold`` 1 a TLR restores the reset
    image. TRST and POR restore every bit.
    """
    return reset_image if reset_hold else written


# JTAG2AXI bridge geometry. The SMC fabric bridge drives SMC
# `jtag_axi_in_req_i`, whose row in the SMC port table states a 56-bit address
# and 64-bit data. The OTP bridges' AXI-Lite widths are the bench's choice.
# Each bridge publishes its geometry in `sbcs` ("PTAP JTAG2AXI Debug Module
# registers": `sbasize` and the `sbaccess*` bits).
DTP_SMC_AXI_ADDR_WIDTH = 56
DTP_SMC_AXI_DATA_WIDTH = 64
# The bench's SMC fabric request ID and user widths (dtp_dv_cfg_pkg
# SmcAxiIdWidth, SmcAxiUserWidth).
DTP_SMC_AXI_ID_WIDTH = 2
DTP_SMC_AXI_USER_WIDTH = 12
DTP_OTP_AXIL_ADDR_WIDTH = 32
DTP_OTP_AXIL_DATA_WIDTH = 32

# DTMCS and DMI register widths ("PTAP JTAG2AXI DTMCS fields" and "PTAP
# JTAG2AXI DMI fields"): DMI is address 40:34, data 33:2, op 1:0.
DTMCS_LEN = 32
DMI_LEN = 41
DMI_DATA_WIDTH = 32
_DMI_ADDR_LSB = 34
_DMI_DATA_LSB = 2
# DTMCS capture with no sticky DMI status: idle 7 (14:12), abits 7 (9:4),
# version 1 (3:0).
DTP_EXPECTED_DTMCS = (7 << 12) | (7 << 4) | 1


@dataclass(frozen=True)
class DtpJtag2AxiTargetCfg:
    """Geometry and TDR register names for one DTP JTAG2AXI bridge target.

    ``bus_type`` (0 AXI4, 1 AXI4-Lite), ``addr_width`` and ``data_width`` come
    from the bench configuration ``tb_top`` elaborates the DUT with
    (``dtp_dv_cfg``); the geometry gate compares the bridge's ``sbcs``
    (``sbasize`` and the ``sbaccess*`` bits) with them every pass.
    """

    name: str
    bus_type: int
    addr_width: int
    data_width: int
    dtmcs_reg: str
    dmi_reg: str
    memory_attr: str
    activity_prefix: str
    dbg_disable_bit: str
    # tb_top instances of the bridge port: the responder side and the
    # monitor tap, and the port's bit in dtp_tb_if.sys_rst_on_ar_arm,
    # j2a_b_hold and j2a_r_hold.
    slave_if: str
    monitor_if: str
    reset_arm_bit: int

    @property
    def data_size(self) -> int:
        """The beat width in bytes as a power of two: the largest ``sbaccess``."""
        return (self.data_width // 8).bit_length() - 1

    @property
    def beat_bytes(self) -> int:
        return self.data_width // 8

    @property
    def monitor_name(self) -> str:
        """Name of the port monitor, the ``source`` of every item it publishes."""
        return f"dtp_{self.name}_monitor"

    @property
    def watcher_name(self) -> str:
        return f"dtp_{self.name}_watcher"

    @property
    def default_size(self) -> int:
        """``sbaccess`` of a full-width beat."""
        return self.data_size

    @property
    def dtmcs_instr(self) -> DtpJtagInstr:
        return DtpJtagInstr[self.dtmcs_reg]

    @property
    def dmi_instr(self) -> DtpJtagInstr:
        return DtpJtagInstr[self.dmi_reg]


# One row per bridge. The TDR names are the interface-unit instruction table's
# (`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc`).
JTAG2AXI_TARGETS: dict[str, DtpJtag2AxiTargetCfg] = {
    "smc_axi": DtpJtag2AxiTargetCfg(
        name="smc_axi",
        bus_type=0,
        addr_width=DTP_SMC_AXI_ADDR_WIDTH,
        data_width=DTP_SMC_AXI_DATA_WIDTH,
        dtmcs_reg="SMC_DTMCS",
        dmi_reg="SMC_DMI",
        memory_attr="axi_ram",
        activity_prefix="smc_axi",
        dbg_disable_bit="smc_jtag2axi",
        slave_if="u_smc_axi_slave_if",
        monitor_if="u_m_axi_if",
        reset_arm_bit=0,
    ),
    "smc_otp": DtpJtag2AxiTargetCfg(
        name="smc_otp",
        bus_type=1,
        addr_width=DTP_OTP_AXIL_ADDR_WIDTH,
        data_width=DTP_OTP_AXIL_DATA_WIDTH,
        dtmcs_reg="SMC_OTP_DTMCS",
        dmi_reg="SMC_OTP_DMI",
        memory_attr="smc_otp_axil_ram",
        activity_prefix="smc_otp_axil",
        dbg_disable_bit="smc_otp_jtag2axi",
        slave_if="u_smc_otp_slave_if",
        monitor_if="u_smc_otp_axil_if",
        reset_arm_bit=1,
    ),
    "sep_otp": DtpJtag2AxiTargetCfg(
        name="sep_otp",
        bus_type=1,
        addr_width=DTP_OTP_AXIL_ADDR_WIDTH,
        data_width=DTP_OTP_AXIL_DATA_WIDTH,
        dtmcs_reg="SEP_OTP_DTMCS",
        dmi_reg="SEP_OTP_DMI",
        memory_attr="sep_otp_axil_ram",
        activity_prefix="sep_otp_axil",
        dbg_disable_bit="sep_otp_jtag2axi",
        slave_if="u_sep_otp_slave_if",
        monitor_if="u_sep_otp_axil_if",
        reset_arm_bit=2,
    ),
}


def get_jtag2axi_target(target: str | DtpJtag2AxiTargetCfg) -> DtpJtag2AxiTargetCfg:
    """Return normalized target metadata for JTAG2AXI helper code."""
    if isinstance(target, DtpJtag2AxiTargetCfg):
        return target
    return JTAG2AXI_TARGETS[target]


def pack_dmi(address: int, data: int, op: DtpDmiOp | int) -> int:
    """A DMI Update-DR value: address 40:34, data 33:2, op 1:0."""
    return (
        ((int(address) & 0x7F) << _DMI_ADDR_LSB)
        | ((int(data) & 0xFFFF_FFFF) << _DMI_DATA_LSB)
        | (int(op) & 0x3)
    )


def unpack_dmi(value: int) -> tuple[int, int, int]:
    """(address, data, op-or-status) of a DMI value, as ``pack_dmi`` places them."""
    return (
        (value >> _DMI_ADDR_LSB) & 0x7F,
        (value >> _DMI_DATA_LSB) & 0xFFFF_FFFF,
        value & 0x3,
    )


def unpack_dtmcs(value: int) -> dict[str, int]:
    """Fields of a DTMCS value by the "PTAP JTAG2AXI DTMCS fields" names."""
    return {
        "dmihardreset": (value >> 17) & 0x1,
        "dmireset": (value >> 16) & 0x1,
        "idle": (value >> 12) & 0x7,
        "dmistat": (value >> 10) & 0x3,
        "abits": (value >> 4) & 0x3F,
        "version": value & 0xF,
    }


# sbcs fields of debug specification 0.13 by bit position and width.
_SBCS_FIELDS: dict[str, tuple[int, int]] = {
    "sbversion": (29, 3),
    "sbbusyerror": (22, 1),
    "sbbusy": (21, 1),
    "sbreadonaddr": (20, 1),
    "sbaccess": (17, 3),
    "sbautoincrement": (16, 1),
    "sbreadondata": (15, 1),
    "sberror": (12, 3),
    "sbasize": (5, 7),
    "sbaccess128": (4, 1),
    "sbaccess64": (3, 1),
    "sbaccess32": (2, 1),
    "sbaccess16": (1, 1),
    "sbaccess8": (0, 1),
}


def pack_sbcs(**fields: int) -> int:
    """An ``sbcs`` value from named fields; unnamed fields are 0."""
    value = 0
    for name, field_value in fields.items():
        lsb, width = _SBCS_FIELDS[name]
        value |= (int(field_value) & ((1 << width) - 1)) << lsb
    return value


def unpack_sbcs(value: int) -> dict[str, int]:
    """Every ``sbcs`` field by name."""
    return {
        name: (value >> lsb) & ((1 << width) - 1) for name, (lsb, width) in _SBCS_FIELDS.items()
    }


def decode_idcode(idcode: int) -> dict[str, int]:
    """Decode an IEEE 1149.1 32-bit IDCODE into its named fields."""
    return {
        "lsb": idcode & 0x1,
        "manufacturer": (idcode >> 1) & 0x7FF,
        "part_number": (idcode >> 12) & 0xFFFF,
        "version": (idcode >> 28) & 0xF,
    }
