# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Enumeration Template for CocoTB

This template provides examples of enumeration patterns commonly used
in CocoTB testbenches for hardware verification.

Enumerations help:
- Define protocol states and responses
- Encode transaction types
- Represent hardware register fields
- Improve code readability and maintainability
- Provide type safety

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

import os
from enum import Enum, IntEnum
from dataclasses import dataclass, field


# ==============================================================================
# DTP Protocol Enumerations
# ==============================================================================

class DTPJTAGInstr_e(IntEnum):
    """
    JTAG Instruction Set

    The instruction set for the JTAG protocol.
    """

    BYPASS_00 = 0x0000
    IDCODE = 0x0001
    RUNBIST = 0x0002
    SAMPLE_PRELOAD = 0x0003
    EXTEST = 0x0004
    EXTEST_TRAIN = 0x0005
    EXTEST_PULSE = 0x0006
    CLAMP = 0x0007
    HIGHZ = 0x0008
    INTEST = 0x0009
    CLAMP_HOLD = 0x000A
    CLAMP_RELEASE = 0x000B
    TMP_STATUS = 0x000C
    IC_RESET = 0x000D
    TAP_3DCR = 0x000E
    UNDEFINED_AS_BYPASS_0F = 0x000F
    RISCV_RESERVED_0 = 0x0010
    RISCV_RESERVED_1 = 0x0011
    RISCV_RESERVED_2 = 0x0012
    RISCV_RESERVED_3 = 0x0013
    RISCV_RESERVED_4 = 0x0014
    RISCV_RESERVED_5 = 0x0015
    RISCV_RESERVED_6 = 0x0016
    RISCV_RESERVED_7 = 0x0017
    DEBUG_CONTROL = 0x0018
    JTAG_CAPS = 0x0019
    SELECT_IJTAG = 0x001A
    SMC_OTP_JTAG2AXI_CAPS = 0x001B
    SMC_OTP_AXI_SINGLE_OP = 0x001C
    SMC_OTP_AXI_SERIES_CTRL = 0x001D
    SMC_OTP_AXI_SERIES_DATA_INCR = 0x001E
    SMC_OTP_AXI_SERIES_DATA_NO_INCR = 0x001F
    SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x0020
    SEP_OTP_JTAG2AXI_CAPS = 0x0021
    SEP_OTP_AXI_SINGLE_OP = 0x0022
    SEP_OTP_AXI_SERIES_CTRL = 0x0023
    SEP_OTP_AXI_SERIES_DATA_INCR = 0x0024
    SEP_OTP_AXI_SERIES_DATA_NO_INCR = 0x0025
    SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x0026
    SMC_JTAG2AXI_CAPS = 0x0027
    SMC_AXI_SINGLE_OP = 0x0028
    SMC_AXI_SERIES_CTRL = 0x0029
    SMC_AXI_SERIES_DATA_INCR = 0x002A
    SMC_AXI_SERIES_DATA_NO_INCR = 0x002B
    SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS = 0x002C
    UNDEFINED_AS_BYPASS_2D = 0x002D
    UNDEFINED_AS_BYPASS_2E = 0x002E
    UNDEFINED_AS_BYPASS_2F = 0x002F
    UNDEFINED_AS_BYPASS_30 = 0x0030
    UNDEFINED_AS_BYPASS_31 = 0x0031
    UNDEFINED_AS_BYPASS_32 = 0x0032
    UNDEFINED_AS_BYPASS_33 = 0x0033
    UNDEFINED_AS_BYPASS_34 = 0x0034
    UNDEFINED_AS_BYPASS_35 = 0x0035
    UNDEFINED_AS_BYPASS_36 = 0x0036
    UNDEFINED_AS_BYPASS_37 = 0x0037
    UNDEFINED_AS_BYPASS_38 = 0x0038
    UNDEFINED_AS_BYPASS_39 = 0x0039
    UNDEFINED_AS_BYPASS_3A = 0x003A
    UNDEFINED_AS_BYPASS_3B = 0x003B
    UNDEFINED_AS_BYPASS_3C = 0x003C
    ZERO_LENGTH_BYPASS = 0x003D
    INV_BYPASS = 0x003E
    BYPASS_3F = 0x003F

    @staticmethod
    def get_ir_width() -> int:
        """Get the instruction register width"""
        return 6

    @staticmethod
    def get_all_instructions() -> list[int]:
        """Get all instruction codes"""
        return [instr.value for instr in DTPJTAGInstr_e.__members__.values()]

    @staticmethod
    def get_all_undefined_instructions() -> list[int]:
        """Get all undefined instruction codes"""
        riscv_reserved_instructions = [
            instr.value for instr in DTPJTAGInstr_e.__members__.values()
            if instr.value >= DTPJTAGInstr_e.RISCV_RESERVED_0.value
            and instr.value <= DTPJTAGInstr_e.RISCV_RESERVED_7.value
        ]
        undefined_instructions = [
            instr.value for instr in DTPJTAGInstr_e.__members__.values()
            if (
                (instr.value == DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_0F.value) or
                ((instr.value >= DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_2D.value) and
                (instr.value <= DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_3C.value))
            )
        ]
        return undefined_instructions + riscv_reserved_instructions


@dataclass
class DTPBaseStructure_s:
    """Base structure for all DTP data structures"""

    @staticmethod
    def int_to_bit_list(value: int, bit_width: int) -> list[int]:
        """Convert integer to little-endian bit list"""
        return [(value >> i) & 0x1 for i in range(bit_width)]

    @staticmethod
    def bit_list_to_int(bit_list: list[int]) -> int:
        """Convert little-endian bit list to integer"""
        return sum(bit << i for i, bit in enumerate(bit_list))

    @staticmethod
    def byte_list_to_int(byte_list: list[int]) -> int:
        """Convert byte list to integer"""
        return sum(byte << (i * 8) for i, byte in enumerate(byte_list))

    @staticmethod
    def int_to_byte_list(value: int, byte_width: int) -> list[int]:
        """Convert integer to byte list"""
        return [(value >> (i * 8)) & 0xFF for i in range(byte_width)]


@dataclass
class DTPCustomJTAGInstruction_s:
    """Custom JTAG instruction data field breakdown per JTAG instruction data register"""
    opcode: int
    ir_width: int = 6
    dr_value: int = 0
    dr_width: int = 32
    name: str = ""

    @classmethod
    def from_value(cls, opcode: int, dr_value: int, dr_width: int, name: str):
        return cls(opcode=opcode, dr_value=dr_value, dr_width=dr_width, name=name)



# ==============================================================================
# IDCODE Data Structure
# ==============================================================================
@dataclass
class DTPJTAGIDCODE_s:
    """IDCODE field breakdown per IEEE 1149.1"""

    value: int
    version: int
    part_number: int
    manufacturer_id: int
    lsb: int

    @classmethod
    def from_value(cls, idcode: int):
        """Create IDCODEFields from raw IDCODE value"""
        return cls(
            value=idcode,
            version=(idcode >> 28) & 0xF,
            part_number=(idcode >> 12) & 0xFFFF,
            manufacturer_id=(idcode >> 1) & 0x7FF,
            lsb=idcode & 0x1,
        )

    def is_valid_lsb(self) -> bool:
        """Check if LSB is valid (must be 1 per IEEE 1149.1)"""
        return self.lsb == 1

    def is_all_zeros(self) -> bool:
        """Check if IDCODE is all zeros (except LSB)"""
        return self.value == 0x00000001

    def is_all_ones(self) -> bool:
        """Check if IDCODE is all ones"""
        return self.value == 0xFFFFFFFF

    def has_valid_manufacturer(self) -> bool:
        """Check if manufacturer ID is not reserved (0 or 0x7FF)"""
        return self.manufacturer_id not in (0, 0x7FF)


# ==============================================================================
# JTAG Debug Control Data Structure
# ==============================================================================
@dataclass
class DTPJTAGDebugControl_s:
    """JTAG debug control field breakdown per JTAG debug control register"""

    cla_clock_stop: int
    jtag_clock_stop: int
    cla_clock_stop_en: int
    boot_stall_ovrd: int
    boot_stall: int

    tdr_length: int = 5

    @staticmethod
    def pack_instruction_debug_control(
        cla_clock_stop: int,
        jtag_clock_stop: int,
        cla_clock_stop_en: int,
        boot_stall_ovrd: int,
        boot_stall: int,
    ) -> tuple[int, list[int]]:
        """Get JTAG debug control instruction from jtag_clock_stop, cla_clock_stop, cla_clock_stop_en, boot_stall_ovrd, and boot_stall"""
        return (
            ((cla_clock_stop & 1) << 4)
            | ((jtag_clock_stop & 1) << 3)
            | ((cla_clock_stop_en & 1) << 2)
            | ((boot_stall_ovrd & 1) << 1)
            | ((boot_stall & 1) << 0)
        ),[boot_stall & 0x1, boot_stall_ovrd & 0x1, cla_clock_stop_en & 0x1, jtag_clock_stop & 0x1, cla_clock_stop & 0x1]

    @staticmethod
    def unpack_instruction_debug_control(
        instruction: int,
    ) -> tuple[int, int, int, int, int]:
        """Parse JTAG debug control instruction into cla_clock_stop, jtag_clock_stop, cla_clock_stop_en, boot_stall_ovrd, and boot_stall"""
        cla_clock_stop = (instruction >> 4) & 1
        jtag_clock_stop = (instruction >> 3) & 1
        cla_clock_stop_en = (instruction >> 2) & 1
        boot_stall_ovrd = (instruction >> 1) & 1
        boot_stall = (instruction >> 0) & 1
        return (
            cla_clock_stop,
            jtag_clock_stop,
            cla_clock_stop_en,
            boot_stall_ovrd,
            boot_stall,
        )


# ==============================================================================
# JTAG Caps Data Structure
# ==============================================================================
@dataclass
class DTPJTAGCaps_s:
    """JTAG caps field breakdown per JTAG caps register.

    JTAG_CAPS is a 60-bit read-only register. Three 8-bit per-slice counts
    (SMC, SEP, EXT) report the number of reset override ports in each slice
    of the IC_RESET TDR.
    """

    num_xtrig_int_ct: int
    num_xtrig_ctp: int
    num_xtra_stap: int
    stap_io_en: int
    sep_dbg_en: int
    smc_dbg_en: int
    num_smc_ic_rst: int
    num_sep_ic_rst: int
    num_ext_ic_rst: int
    ic_rst_inst_en: int
    tmp_inst_en: int
    runbist_inst_en: int
    highz_inst_en: int
    clamp_inst_en: int
    intest_inst_en: int
    extest_pulse_en: int
    extest_train_en: int
    bsr_inst_en: int
    och_ver: int

    @staticmethod
    def pack_instruction_jtag_caps(
        num_xtrig_int_ct: int,
        num_xtrig_ctp: int,
        num_xtra_stap: int,
        stap_io_en: int,
        sep_dbg_en: int,
        smc_dbg_en: int,
        num_smc_ic_rst: int,
        num_sep_ic_rst: int,
        num_ext_ic_rst: int,
        ic_rst_inst_en: int,
        tmp_inst_en: int,
        runbist_inst_en: int,
        highz_inst_en: int,
        clamp_inst_en: int,
        intest_inst_en: int,
        extest_pulse_en: int,
        extest_train_en: int,
        bsr_inst_en: int,
        och_ver: int,
    ) -> int:
        """Pack parameters into a JTAG_CAPS TDR integer (60 bits).

        Layout (MSB→LSB, closest to TDI→TDO):
            [59:54] num_xtrig_int_ct (6b)
            [53:48] num_xtrig_ctp    (6b)
            [47:44] num_xtra_stap    (4b)
            [43]    stap_io_en       (1b)
            [42]    sep_dbg_en       (1b)
            [41]    smc_dbg_en       (1b)
            [40:33] num_smc_ic_rst   (8b)
            [32:25] num_sep_ic_rst   (8b)
            [24:17] num_ext_ic_rst   (8b)
            [16]    ic_rst_inst_en   (1b)
            [15]    tmp_inst_en      (1b)
            [14]    runbist_inst_en  (1b)
            [13]    highz_inst_en    (1b)
            [12]    clamp_inst_en    (1b)
            [11]    intest_inst_en   (1b)
            [10]    extest_pulse_en  (1b)
            [9]     extest_train_en  (1b)
            [8]     bsr_inst_en      (1b)
            [7:0]   och_ver          (8b)
        """
        instruction = (
            ((num_xtrig_int_ct & ((1 << 6) - 1)) << 54) |
            ((num_xtrig_ctp & ((1 << 6) - 1)) << 48) |
            ((num_xtra_stap & ((1 << 4) - 1)) << 44) |
            ((stap_io_en & 1) << 43) |
            ((sep_dbg_en & 1) << 42) |
            ((smc_dbg_en & 1) << 41) |
            ((num_smc_ic_rst & ((1 << 8) - 1)) << 33) |
            ((num_sep_ic_rst & ((1 << 8) - 1)) << 25) |
            ((num_ext_ic_rst & ((1 << 8) - 1)) << 17) |
            ((ic_rst_inst_en & 1) << 16) |
            ((tmp_inst_en & 1) << 15) |
            ((runbist_inst_en & 1) << 14) |
            ((highz_inst_en & 1) << 13) |
            ((clamp_inst_en & 1) << 12) |
            ((intest_inst_en & 1) << 11) |
            ((extest_pulse_en & 1) << 10) |
            ((extest_train_en & 1) << 9) |
            ((bsr_inst_en & 1) << 8) |
            ((och_ver & ((1 << 8) - 1)) << 0)
        )
        return instruction

    @staticmethod
    def parse_instruction_jtag_caps(
        instruction: int,
    ) -> tuple[
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
    ]:
        """Parse a JTAG_CAPS TDR integer back into its component fields.

        See :meth:`pack_instruction_jtag_caps` for the 60-bit layout.
        """
        num_xtrig_int_ct = (instruction >> 54) & ((1 << 6) - 1)
        num_xtrig_ctp = (instruction >> 48) & ((1 << 6) - 1)
        num_xtra_stap = (instruction >> 44) & ((1 << 4) - 1)
        stap_io_en = (instruction >> 43) & 1
        sep_dbg_en = (instruction >> 42) & 1
        smc_dbg_en = (instruction >> 41) & 1
        num_smc_ic_rst = (instruction >> 33) & ((1 << 8) - 1)
        num_sep_ic_rst = (instruction >> 25) & ((1 << 8) - 1)
        num_ext_ic_rst = (instruction >> 17) & ((1 << 8) - 1)
        ic_rst_inst_en = (instruction >> 16) & 1
        tmp_inst_en = (instruction >> 15) & 1
        runbist_inst_en = (instruction >> 14) & 1
        highz_inst_en = (instruction >> 13) & 1
        clamp_inst_en = (instruction >> 12) & 1
        intest_inst_en = (instruction >> 11) & 1
        extest_pulse_en = (instruction >> 10) & 1
        extest_train_en = (instruction >> 9) & 1
        bsr_inst_en = (instruction >> 8) & 1
        och_ver = (instruction >> 0) & ((1 << 8) - 1)
        return (
            num_xtrig_int_ct,
            num_xtrig_ctp,
            num_xtra_stap,
            stap_io_en,
            sep_dbg_en,
            smc_dbg_en,
            num_smc_ic_rst,
            num_sep_ic_rst,
            num_ext_ic_rst,
            ic_rst_inst_en,
            tmp_inst_en,
            runbist_inst_en,
            highz_inst_en,
            clamp_inst_en,
            intest_inst_en,
            extest_pulse_en,
            extest_train_en,
            bsr_inst_en,
            och_ver,
        )


# ==============================================================================
# JTAG2AXI Caps Data Structure
# ==============================================================================
@dataclass
class DTPJTAG2AXICaps_s:
    """JTAG2AXI caps field breakdown per JTAG2AXI caps register"""

    rd_pl_depth: int
    wr_pl_depth: int
    data_size: int
    addr_size: int
    bus_type: int

    @staticmethod
    def unpack_instruction(
        instruction: int,
    ) -> tuple[int, int, int, int, int]:
        """Parse JTAG2AXI caps instruction into rd_pl_depth, wr_pl_depth, data_size, addr_size, bus_type"""
        rd_pl_depth = (instruction >> 12) & ((1 << 2) - 1)
        wr_pl_depth = (instruction >> 10) & ((1 << 2) - 1)
        data_size = (instruction >> 7) & ((1 << 3) - 1)
        addr_size = (instruction >> 1) & ((1 << 6) - 1)
        bus_type = (instruction >> 0) & 1
        return rd_pl_depth, wr_pl_depth, data_size, addr_size, bus_type

# ==============================================================================
# AXI-Related Data Structures
# ==============================================================================
class DTPAXITarget_e(IntEnum):
    """AXI Target Types"""

    SMC_OTP = 0
    SEP_OTP = 1
    SMC_FABRIC = 2


# DTPAXIOp_e
class DTPAXIOpOnIssue_e(IntEnum):
    """AXI Operation Types on Issue"""

    NO_OP = 0
    READ = 1
    WRITE = 2
    RESERVED = 3


class DTPAXIOpOnResponse_e(IntEnum):
    """AXI Operation Types on Response"""

    OKAY = 0
    SLVERR = 1
    DECERR = 2
    BACKPRESSURE = (
        3  # The latest command is issued before the previous command is completed
    )


# ------------------------------------------------------------------------------
# AXI Single Op Instruction Data Structure
# ------------------------------------------------------------------------------
@dataclass
class DTPAXISingleOp_s:
    """AXISingleOp field breakdown per *_AXI_SINGLE_OP instruction"""

    addr: int
    data: int
    wstrb: int
    axi_size: int
    op: DTPAXIOpOnIssue_e
    status: DTPAXIOpOnResponse_e

    addr_width: int = 32 # in Bits
    data_width: int = 128 # in Bits

    @staticmethod
    def get_axsize_width(data_width: int) -> int:
        """Get axi_size from data_width"""
        if data_width > 0 and data_width <= 16:
            return 1
        elif data_width > 16 and data_width <= 64:
            return 2
        elif data_width > 64 and data_width <= 1024:
            return 3
        else:
            raise ValueError(f"Invalid data width: {data_width}")

    @staticmethod
    def get_max_axsize(data_width: int) -> int:
        """Get max axi_size from data_width"""
        return (1 << DTPAXISingleOp_s.get_axsize_width(data_width)) - 1

    @staticmethod
    def pack_instruction_single_op(
        addr: int,
        data: int,
        wstrb: int,
        axi_size: int,
        op: DTPAXIOpOnIssue_e,
        addr_width: int = 32, # in Bits
        data_width: int = 128, # in Bits
    ) -> tuple[int, int]:
        """Get TDR instruction from address, data, wstrb, axi_size, and op"""
        axsize_width = DTPAXISingleOp_s.get_axsize_width(data_width)
        max_axsize = DTPAXISingleOp_s.get_max_axsize(data_width)
        if axi_size > max_axsize:
            raise ValueError(f"Invalid axi_size: {axi_size} for data width: {data_width}")
        length = 2 + axsize_width + data_width // 8 + data_width + addr_width
        instruction = (
              ((addr & ((1 << addr_width) - 1))            << (2 + axsize_width + data_width // 8 + data_width))
            | ((data & ((1 << data_width) - 1))            << (2 + axsize_width + data_width // 8))
            | ((wstrb & ((1 << data_width // 8) - 1))      << (2 + axsize_width))
            | ((axi_size & ((1 << axsize_width) - 1))      << 2)
            | ((op & ((1 << 2) - 1))                       << 0)
        )
        return instruction, length

    @staticmethod
    def unpack_instruction_single_op(
        instruction: int, addr_width: int = 32, data_width: int = 128 # in Bits
    ) -> tuple[int, int, int, int, DTPAXIOpOnResponse_e]:
        """Parse TDR instruction into address, data, wstrb, size, and op"""
        axsize_width = DTPAXISingleOp_s.get_axsize_width(data_width)
        max_axsize = DTPAXISingleOp_s.get_max_axsize(data_width)
        status   = (instruction >> 0) & ((1 << 2) - 1)
        axi_size = (instruction >> 2) & ((1 << axsize_width) - 1)
        wstrb    = (instruction >> (2 + axsize_width)) & ((1 << (data_width // 8)) - 1)
        data     = (instruction >> (2 + axsize_width + data_width // 8)) & ((1 << data_width) - 1)
        addr     = (instruction >> (2 + axsize_width + data_width // 8 + data_width)) & ((1 << addr_width) - 1)
        return addr, data, wstrb, axi_size, DTPAXIOpOnResponse_e(status)

    @staticmethod
    def get_wr_op_type(instruction: int) -> DTPAXIOpOnIssue_e:
        """Get write operation type from instruction"""
        return DTPAXIOpOnIssue_e(instruction & ((1 << 2) - 1))

    @staticmethod
    def get_rd_response_type(instruction: int) -> DTPAXIOpOnResponse_e:
        """Get read response type from instruction"""
        return DTPAXIOpOnResponse_e(instruction & ((1 << 2) - 1))


@dataclass
class DTPAXISeriesCtrl_s:
    """AXISeriesCtrl field breakdown per *_AXI_SERIES_CTRL instruction"""

    reset: int  # 1: reset, 0: no reset
    addr: int  # address
    pipeline_depth: int  # pipeline depth
    axi_size: int  # axi size
    op: DTPAXIOpOnIssue_e  # operation
    status: DTPAXIOpOnResponse_e  # status

    addr_width: int = 32 # in Bits
    data_width: int = 128 # in Bits

    @staticmethod
    def get_axsize_width(data_width: int) -> int:
        """Get axi_size from data_width"""
        if data_width > 0 and data_width <= 16:
            return 1
        elif data_width > 16 and data_width <= 64:
            return 2
        elif data_width > 64 and data_width <= 1024:
            return 3
        else:
            raise ValueError(f"Invalid data width: {data_width}")

    @staticmethod
    def pack_instruction_series_ctrl(
        reset: int,
        addr: int,
        pipeline_depth: int,
        axi_size: int,
        op: DTPAXIOpOnIssue_e,
        addr_width: int = 32, # in Bits
        data_width: int = 128, # in Bits
    ) -> tuple[int, int]:
        """Get TDR instruction from reset, address, pipeline depth, axi_size, and op"""
        axsize_width = DTPAXISeriesCtrl_s.get_axsize_width(data_width)
        length = 2 + axsize_width + 2 + addr_width + 1
        instruction = (
              ((reset & 1)                            << (2 + axsize_width + 2 + addr_width))
            | ((addr & ((1 << addr_width) - 1))       << (2 + axsize_width + 2))
            | ((pipeline_depth & ((1 << 2) - 1))      << (2 + axsize_width))
            | ((axi_size & ((1 << axsize_width) - 1)) << 2)
            | ((op & ((1 << 2) - 1))                  << 0)
        )
        return instruction, length

    @staticmethod
    def unpack_instruction_series_ctrl(
        instruction: int, addr_width: int = 32, data_width: int = 128 # in Bits
    ) -> tuple[int, int, int, int, DTPAXIOpOnResponse_e]:
        """Parse TDR instruction into reset, address, pipeline depth, axi_size, and op"""
        axsize_width = DTPAXISeriesCtrl_s.get_axsize_width(data_width)
        status         = (instruction >> 0) & ((1 << 2) - 1)
        axi_size       = (instruction >> 2) & ((1 << axsize_width) - 1)
        pipeline_depth = (instruction >> (2 + axsize_width)) & ((1 << 2) - 1)
        addr           = (instruction >> (2 + axsize_width + 2)) & ((1 << addr_width) - 1)
        reset          = (instruction >> (2 + axsize_width + 2 + addr_width)) & 1
        return reset, addr, pipeline_depth, axi_size, DTPAXIOpOnResponse_e(status)

    @staticmethod
    def get_wr_op_type(instruction: int):
        """Get write operation type from instruction"""
        return DTPAXIOpOnIssue_e(instruction & ((1 << 2) - 1))

    @staticmethod
    def get_rd_response_type(instruction: int):
        """Get read response type from instruction"""
        return DTPAXIOpOnResponse_e(instruction & ((1 << 2) - 1))


# ------------------------------------------------------------------------------
# AXI Series Data Increment Instruction Data Structure
# ------------------------------------------------------------------------------
@dataclass
class DTPAXISeriesData_s:
    """AXISeriesDataIncr field breakdown per *_AXI_SERIES_DATA_INCR instruction"""

    data: int
    axi_size: int

    status: int = 0

    @staticmethod
    def pack_instruction_series_data_with_status(
        data: int, axi_size: int, status: int
    ) -> tuple[int, int]:
        """Get TDR instruction from data"""
        length = 8 * (2**axi_size) + 1
        instruction = 0
        instruction |= (data & ((1 << 8 * (2**axi_size)) - 1)) << 0
        instruction |= (status & 1) << 8 * (2**axi_size)
        return instruction, length

    @staticmethod
    def pack_instruction_series_data_without_status(
        data: int, axi_size: int
    ) -> tuple[int, int]:
        """Get TDR instruction from data"""
        length = 8 * (2**axi_size)
        instruction = 0
        instruction |= (data & ((1 << 8 * (2**axi_size)) - 1)) << 0
        return instruction, length

    @staticmethod
    def unpack_instruction_series_data_with_status(
        instruction: int, axi_size: int
    ) -> tuple[int, int]:
        """Parse TDR instruction into data"""
        data = (instruction >> 0) & ((1 << 8 * (2**axi_size)) - 1)
        status = (instruction >> 8 * (2**axi_size)) & 1
        return data, status

    @staticmethod
    def unpack_instruction_series_data_without_status(
        instruction: int, axi_size: int
    ) -> int:
        """Parse TDR instruction into data"""
        data = (instruction >> 0) & ((1 << 8 * (2**axi_size)) - 1)
        return data


# ==============================================================================
# IJTAG Network
#
#
#
#                 +--Instrument-+
#                 |             |                                          #TODO#   +-----+
#                 +---+     +---+                                          #TODO#   |     |          +------+
#                     |     |                                              #TODO#   |     |          |      |
#      +-------+      |     |                                              #TODO#   |  SEP OTP <-----+   SEP OTP <--- SEP OTP AXI4-Lite Output
#      | IJTAG |<---- DFD SIB ----+                                        #TODO#   |    SIB ->------+  JTAG2AXI ---> SEP OTP AXI4-Lite Input
#      |  TDI  |                  |    +------+                            #TODO#   |     |          |      |
# PTAP |       |                  |    |      |                            #TODO#   |     |          +------+
# CTRL |       |                 DFT <-+      |                            #TODO#<--+     |          +------+
# ---->|       |                 SIB ->+  Instrument                       #TODO#->-+     |          |      |
#      |       |                  |    |      |                            #TODO#   |  SMC OTP <-----+   SMC OTP <--- SMC OTP AXI4-Lite Output
#      | IJTAG |      Secure      |    +------+                            #TODO#   |    SIB ->------+  JTAG2AXI ---> SMC OTP AXI4-Lite Input
#      |  TDO  |----> DFT SIB ----+                                        #TODO#   |     |          |      |
#      +-------+      |     |                                              #TODO#   |     |          +------+
#                     |     |                                              #TODO#   |     |          +------+
#                 +---+     +---+                                          #TODO#   |     |          |      |
#                 |             |                                          #TODO#   |    SMC <-------+     SMC   <--- SMC AXI4 Fabric Output
#                 +--Instrument-+                                          #TODO#   |    SIB ->------+  JTAG2AXI ---> SMC AXI4 Fabric Input
#                                                                          #TODO#   |     |          |      |
#                                                                          #TODO#   |     |          +------+
#                                                                          #TODO#   +-----+
# ==============================================================================


class DTPSIBState_e(IntEnum):
    """SIB state values"""

    SIB_OFF = 0
    SIB_ON = 1


@dataclass
class DTPIJTAGSIB_s:
    """SIB with TDR field breakdown per SIB with TDR"""

    sib_state: DTPSIBState_e
    tdr_data: int = 0
    tdr_size: int = 0  # 0 means no TDR, and TDI is connected to TDO

    @staticmethod
    def get_instruction_sib_with_tdr(
        sib_state: DTPSIBState_e, tdr_data: int, tdr_size: int = 0
    ) -> list[int]:
        """Get TDR instruction from current SIB state to next SIB state, TDR data, and TDR size"""
        instruction = []
        # Generate TDR data bits
        #instruction.append(int(sib_state)) # Add SIB bit to the head of the instruction for SIB pre MUX topology
        tdr_data_bits = [(tdr_data >> i) & 0x1 for i in range(tdr_size)]
        if sib_state == DTPSIBState_e.SIB_ON:
            instruction.extend(tdr_data_bits)
        instruction.append(int(sib_state)) # Add SIB bit to the tail of the instruction for SIB post MUX topology
        return instruction


@dataclass
class DTPIJTAGNetwork_s:
    """IJTAG network field breakdown per IJTAG network"""

    sec_dft_sib: DTPIJTAGSIB_s
    dft_sib:     DTPIJTAGSIB_s
    dfd_sib:     DTPIJTAGSIB_s
    #smc_sib: DTPIJTAGSIB_s
    #smc_otp_sib: DTPIJTAGSIB_s
    #sep_otp_sib: DTPIJTAGSIB_s

    # ------------------------------------------------------------------------------
    # Get IJTAG network chain length
    # ------------------------------------------------------------------------------
    @staticmethod
    def get_ijtag_network_chain_length(
        sec_dft_sib: DTPIJTAGSIB_s,
        dft_sib:     DTPIJTAGSIB_s,
        dfd_sib:     DTPIJTAGSIB_s,
        #smc_sib: DTPIJTAGSIB_s,
        #smc_otp_sib: DTPIJTAGSIB_s,
        #sep_otp_sib: DTPIJTAGSIB_s,
    ) -> int:
        """Get the length of the IJTAG network chain"""
        chain_length = 0
        chain_length += (
            (sec_dft_sib.tdr_size + 1) if sec_dft_sib.sib_state == DTPSIBState_e.SIB_ON else 1
        )
        chain_length += (
            (dft_sib.tdr_size + 1) if dft_sib.sib_state == DTPSIBState_e.SIB_ON else 1
        )
        chain_length += (
            (dfd_sib.tdr_size + 1) if dfd_sib.sib_state == DTPSIBState_e.SIB_ON else 1
        )
        return chain_length

    # ------------------------------------------------------------------------------
    # Get TDR instruction to turn off all SIBs
    # ------------------------------------------------------------------------------
    @staticmethod
    def get_sib_off_instruction(
        sec_dft_sib: DTPIJTAGSIB_s,
        dft_sib:     DTPIJTAGSIB_s,
        dfd_sib:     DTPIJTAGSIB_s,
        #smc_sib: DTPIJTAGSIB_s,
        #smc_otp_sib: DTPIJTAGSIB_s,
        #sep_otp_sib: DTPIJTAGSIB_s,
    ) -> list[int]:
        """Get TDR instruction to turn off all SIBs"""
        instruction = [0] * (
            (sec_dft_sib.tdr_size + 1)
            + (dft_sib.tdr_size + 1)
            + (dfd_sib.tdr_size + 1)
        )
        return instruction

    # ------------------------------------------------------------------------------
    # Get TDR instruction to turn on some SIBs
    # ------------------------------------------------------------------------------
    @staticmethod
    def get_sib_cfg_instruction(
        sec_dft_sib: DTPIJTAGSIB_s,
        dft_sib:     DTPIJTAGSIB_s,
        dfd_sib:     DTPIJTAGSIB_s,
        #smc_sib: DTPIJTAGSIB_s,
        #smc_otp_sib: DTPIJTAGSIB_s,
        #sep_otp_sib: DTPIJTAGSIB_s,
    ) -> list[list[int]]:
        """Get TDR instruction from sib configuration"""
        sib_off_pattern = DTPIJTAGNetwork_s.get_sib_off_instruction(sec_dft_sib, dft_sib, dfd_sib)
        sib_cfg_pattern = [dfd_sib.sib_state.value, dft_sib.sib_state.value, sec_dft_sib.sib_state.value]
        return [sib_off_pattern, sib_cfg_pattern]

    @staticmethod
    def get_sib_tdr_instruction(
        sec_dft_sib: DTPIJTAGSIB_s,
        dft_sib:     DTPIJTAGSIB_s,
        dfd_sib:     DTPIJTAGSIB_s,
        #smc_sib: DTPIJTAGSIB_s,
        #smc_otp_sib: DTPIJTAGSIB_s,
        #sep_otp_sib: DTPIJTAGSIB_s,
    ) -> list[int]:
        """Get TDR instruction from sib setting"""
        sec_dft_tdr_cfg_pattern = DTPIJTAGSIB_s.get_instruction_sib_with_tdr(
            sec_dft_sib.sib_state, sec_dft_sib.tdr_data, sec_dft_sib.tdr_size
        )
        dft_tdr_cfg_pattern = DTPIJTAGSIB_s.get_instruction_sib_with_tdr(
            dft_sib.sib_state, dft_sib.tdr_data, dft_sib.tdr_size
        )
        dfd_tdr_cfg_pattern = DTPIJTAGSIB_s.get_instruction_sib_with_tdr(
            dfd_sib.sib_state, dfd_sib.tdr_data, dfd_sib.tdr_size
        )
        return dfd_tdr_cfg_pattern + dft_tdr_cfg_pattern + sec_dft_tdr_cfg_pattern


# ==============================================================================
# STAP 3DCR Network
# ==============================================================================

class DTPSTAP3DCR_tms_hold_e(IntEnum):
    """STAP 3DCR TMS hold values"""
    TMS_HOLD_0 = 0
    TMS_HOLD_1 = 1


class DTPSTAP3DCR_stap_sel_e(IntEnum):
    """STAP 3DCR STAP select values"""
    STAP_SEL_0 = 0
    STAP_SEL_1 = 1


class DTPSTAP3DCR_config_hold_e(IntEnum):
    """STAP 3DCR configuration hold values"""
    CONFIG_HOLD_0 = 0
    CONFIG_HOLD_1 = 1


@dataclass
class DTPSTAP3DCR_s:
    """STAP 3DCR field breakdown per 3DCR control register"""
    tms_hold: DTPSTAP3DCR_tms_hold_e
    stap_sel: DTPSTAP3DCR_stap_sel_e
    config_hold: DTPSTAP3DCR_config_hold_e

    @staticmethod
    def pack_3dcr_instruction(
        tms_hold: DTPSTAP3DCR_tms_hold_e,
        stap_sel: DTPSTAP3DCR_stap_sel_e,
        config_hold: DTPSTAP3DCR_config_hold_e,
    ) -> dict[str, list[int]]:
        """Get TDR instruction from tms_hold, stap_sel, and config_hold"""
        return {
            "instruction_int": [
                ((tms_hold & 1) << 2) |
                ((stap_sel & 1) << 1) |
                ((config_hold & 1) << 0)
            ],
            "instruction_bits": [
                (config_hold & 1),
                (stap_sel & 1),
                (tms_hold & 1),
            ],
        }

    @staticmethod
    def unpack_3dcr_instruction(instruction: int) -> tuple[DTPSTAP3DCR_tms_hold_e, DTPSTAP3DCR_stap_sel_e, DTPSTAP3DCR_config_hold_e]:
        """Parse TDR instruction into tms_hold, stap_sel, and config_hold"""
        tms_hold = DTPSTAP3DCR_tms_hold_e((instruction >> 2) & 1)
        stap_sel = DTPSTAP3DCR_stap_sel_e((instruction >> 1) & 1)
        config_hold = DTPSTAP3DCR_config_hold_e((instruction >> 0) & 1)
        return tms_hold, stap_sel, config_hold

@dataclass
class DTPSTAPConfig_s:
    """STAP configuration field breakdown per STAP configuration"""
    cfg_3dcr: DTPSTAP3DCR_s
    cfg_sib: DTPSIBState_e

    @staticmethod
    def get_max_scan_bit_size() -> int:
        """Get the maximum scan bit size from stap configuration (4 bits for 3DCR and 1 bit for SIB)"""
        return 4

    @staticmethod
    def pack_stap_config_instruction(
        cfg_3dcr: DTPSTAP3DCR_s,
        cfg_sib: DTPSIBState_e,
        desired_sib: DTPSIBState_e = None,
    ) -> dict[str, list[int]]:
        """Get TDR instruction from cfg_3dcr and cfg_sib.

        Args:
            cfg_3dcr: 3DCR configuration values to write.
            cfg_sib: Current SIB state — determines scan chain width
                     (SIB_ON → 4 bits: SIB + 3DCR; SIB_OFF → 1 bit: SIB only).
            desired_sib: SIB value to shift out. Defaults to cfg_sib when None.
                         Set to SIB_OFF with cfg_sib=SIB_ON to write 3DCR values
                         while simultaneously closing the SIB.
        """
        sib_output = desired_sib if desired_sib is not None else cfg_sib
        stap_3dcr_instruction_dict = DTPSTAP3DCR_s.pack_3dcr_instruction(
            tms_hold=cfg_3dcr.tms_hold,
            stap_sel=cfg_3dcr.stap_sel,
            config_hold=cfg_3dcr.config_hold,
        )
        if cfg_sib == DTPSIBState_e.SIB_ON:
            return {
                "instruction_int": [
                    ((sib_output.value & 1) << 3) |
                    (stap_3dcr_instruction_dict["instruction_int"][0] << 0)
                ],
                "instruction_bits": [
                    (sib_output.value & 1),
                    (stap_3dcr_instruction_dict["instruction_bits"][0] & 1),
                    (stap_3dcr_instruction_dict["instruction_bits"][1] & 1),
                    (stap_3dcr_instruction_dict["instruction_bits"][2] & 1),
                ],
            }
        else:
            return {
                "instruction_int": [
                    sib_output.value & 0x1
                ],
                "instruction_bits": [
                    (sib_output.value & 0x1),
                ],
            }

    @staticmethod
    def unpack_stap_config_instruction(instruction: int):
        """Parse TDR instruction into cfg_3dcr and cfg_sib"""
        cfg_3dcr = DTPSTAP3DCR_s.unpack_3dcr_instruction((instruction >> 0) & ((1 << 3) - 1))
        cfg_sib = DTPSIBState_e((instruction >> 3) & ((1 << 1) - 1))
        return cfg_3dcr, cfg_sib

@dataclass
class DTPSTAPNetwork_s:
    """STAP network field breakdown per STAP network"""
    ds_stap_cfg: DTPSTAPConfig_s
    smc_stap_cfg: DTPSTAPConfig_s
    sep_stap_cfg: DTPSTAPConfig_s
    extra_stap_cfg: list[DTPSTAPConfig_s]

    #ext_stap_tdr_size: int
    #ext_stap_tdr: int

    @staticmethod
    def get_scan_bit_size(
        ds_stap_cfg: DTPSTAPConfig_s,
        smc_stap_cfg: DTPSTAPConfig_s,
        sep_stap_cfg: DTPSTAPConfig_s,
        extra_stap_cfg: list[DTPSTAPConfig_s],
        #ext_stap_tdr_size: int,
    ) -> int:
        """Get the maximum scan bit size from stap network"""
        #return ext_stap_tdr_size + (
        return (
            2 + # PTAP 3DCR configuration
            DTPSTAPConfig_s.get_max_scan_bit_size() if ds_stap_cfg.cfg_sib == DTPSIBState_e.SIB_ON else 1 +
            DTPSTAPConfig_s.get_max_scan_bit_size() if smc_stap_cfg.cfg_sib == DTPSIBState_e.SIB_ON else 1 +
            DTPSTAPConfig_s.get_max_scan_bit_size() if sep_stap_cfg.cfg_sib == DTPSIBState_e.SIB_ON else 1 +
            sum([DTPSTAPConfig_s.get_max_scan_bit_size() if cfg.cfg_sib == DTPSIBState_e.SIB_ON else 1 for cfg in extra_stap_cfg])
        )

    @staticmethod
    def pack_stap_network_sib_off_config_instruction(
        ptap_config_hold: DTPSTAP3DCR_config_hold_e,
        ds_stap_cfg: DTPSTAPConfig_s,
        smc_stap_cfg: DTPSTAPConfig_s,
        sep_stap_cfg: DTPSTAPConfig_s,
        extra_stap_cfg: list[DTPSTAPConfig_s],
    ) -> dict[str, list[int]]:
        """Get the TDR instruction bit list"""
        instruction_bits = []
        instruction_int = 0
        # Extra STAPs
        for i in range(len(extra_stap_cfg)-1,-1,-1):
            instruction_bits.extend([0] * DTPSTAPConfig_s.get_max_scan_bit_size()) # SIB=OFF
        # SEP STAP
        instruction_bits.extend([0] * DTPSTAPConfig_s.get_max_scan_bit_size()) # SIB=OFF
        # SMC STAP
        instruction_bits.extend([0] * DTPSTAPConfig_s.get_max_scan_bit_size()) # SIB=OFF
        # Downstream STAP
        instruction_bits.extend([0] * DTPSTAPConfig_s.get_max_scan_bit_size()) # SIB=OFF
        # PTAP 3DCR configuration
        instruction_bits.append(ptap_config_hold.value & 0x1)
        instruction_bits.append(DTPSTAP3DCR_stap_sel_e.STAP_SEL_1.value & 0x1) # Always enable PTAP STAP selection for STAP network configuration
        # Pack instruction
        for i in range(len(instruction_bits)):
            instruction_int |= (instruction_bits[i] << i)
        return {
            "instruction_int": [instruction_int],
            "instruction_bits": instruction_bits,
        }

    @staticmethod
    def pack_stap_network_sib_only_config_instruction(
        ptap_config_hold: DTPSTAP3DCR_config_hold_e,
        ds_stap_cfg: DTPSTAPConfig_s,
        smc_stap_cfg: DTPSTAPConfig_s,
        sep_stap_cfg: DTPSTAPConfig_s,
        extra_stap_cfg: list[DTPSTAPConfig_s],
        #ext_stap_tdr_size: int,
    ) -> dict[str, int]:
        """Get TDR instruction from stap network (SIB only)"""
        instruction_bits = []
        instruction_int = 0
        # Extended STAP Scan TDR
        #instruction_bits.append([0] * ext_stap_tdr_size)
        # Extra STAPs
        for i in range(len(extra_stap_cfg)-1,-1,-1):
            instruction_bits.append(extra_stap_cfg[i].cfg_sib.value & 0x1)
        # SEP STAP
        instruction_bits.append(sep_stap_cfg.cfg_sib.value & 0x1)
        # SMC STAP
        instruction_bits.append(smc_stap_cfg.cfg_sib.value & 0x1)
        # Downstream STAP
        instruction_bits.append(ds_stap_cfg.cfg_sib.value & 0x1)
        # PTAP 3DCR configuration
        instruction_bits.append(ptap_config_hold.value & 0x1)
        instruction_bits.append(DTPSTAP3DCR_stap_sel_e.STAP_SEL_1.value & 0x1) # Always enable PTAP STAP selection for STAP network configuration
        # Pack instruction
        for i in range(len(instruction_bits)):
            instruction_int |= (instruction_bits[i] << i)
        return {
            "instruction_int": instruction_int,
            "instruction_bits": instruction_bits,
        }

    @staticmethod
    def pack_stap_network_3dcr_instruction(
        ptap_config_hold: DTPSTAP3DCR_config_hold_e,
        ds_stap_cfg: DTPSTAPConfig_s,
        smc_stap_cfg: DTPSTAPConfig_s,
        sep_stap_cfg: DTPSTAPConfig_s,
        extra_stap_cfg: list[DTPSTAPConfig_s],
        #ext_stap_tdr_size: int,
        #ext_stap_tdr: int
    ) -> dict[str, int]:
        """Get the TDR instruction bit list"""
        ds_3dcr = ds_stap_cfg.cfg_3dcr
        smc_3dcr = smc_stap_cfg.cfg_3dcr
        sep_3dcr = sep_stap_cfg.cfg_3dcr
        extra_3dcr = [cfg.cfg_3dcr for cfg in extra_stap_cfg]
        ds_sib = ds_stap_cfg.cfg_sib
        smc_sib = smc_stap_cfg.cfg_sib
        sep_sib = sep_stap_cfg.cfg_sib
        extra_sib = [cfg.cfg_sib for cfg in extra_stap_cfg]
        # Pack configuration instructions based on the assumption that all SIBs are OFF
        config_instruction = 0
        config_instruction_bit_list = []
        ## Extended STAP Scan TDR
        #for i in range(ext_stap_tdr_size):
        #    config_instruction_bit_list.append((ext_stap_tdr >> i) & 1)
        #config_instruction = ext_stap_tdr
        # Extra STAPs — write 3DCR values and close SIB to minimize future scan chain length
        for i in range(len(extra_stap_cfg)-1,-1,-1):
            extra_3dcr_instruction_dict = DTPSTAPConfig_s.pack_stap_config_instruction(
                cfg_3dcr=extra_3dcr[i], cfg_sib=extra_sib[i], desired_sib=DTPSIBState_e.SIB_OFF)
            config_instruction <<= len(extra_3dcr_instruction_dict["instruction_bits"])
            config_instruction |= extra_3dcr_instruction_dict["instruction_int"][0] & ((1 << len(extra_3dcr_instruction_dict["instruction_bits"])) - 1)
            config_instruction_bit_list.extend(extra_3dcr_instruction_dict["instruction_bits"])
        # SEP STAP — write 3DCR values and close SIB
        sep_3dcr_instruction_dict = DTPSTAPConfig_s.pack_stap_config_instruction(
            cfg_3dcr=sep_3dcr, cfg_sib=sep_sib, desired_sib=DTPSIBState_e.SIB_OFF)
        config_instruction <<= len(sep_3dcr_instruction_dict["instruction_bits"])
        config_instruction |= sep_3dcr_instruction_dict["instruction_int"][0] & ((1 << len(sep_3dcr_instruction_dict["instruction_bits"])) - 1)
        config_instruction_bit_list.extend(sep_3dcr_instruction_dict["instruction_bits"])
        # SMC STAP — write 3DCR values and close SIB
        smc_3dcr_instruction_dict = DTPSTAPConfig_s.pack_stap_config_instruction(
            cfg_3dcr=smc_3dcr, cfg_sib=smc_sib, desired_sib=DTPSIBState_e.SIB_OFF)
        config_instruction <<= len(smc_3dcr_instruction_dict["instruction_bits"])
        config_instruction |= smc_3dcr_instruction_dict["instruction_int"][0] & ((1 << len(smc_3dcr_instruction_dict["instruction_bits"])) - 1)
        config_instruction_bit_list.extend(smc_3dcr_instruction_dict["instruction_bits"])
        # Downstream STAP — write 3DCR values and close SIB
        ds_3dcr_instruction_dict = DTPSTAPConfig_s.pack_stap_config_instruction(
            cfg_3dcr=ds_3dcr, cfg_sib=ds_sib, desired_sib=DTPSIBState_e.SIB_OFF)
        config_instruction <<= len(ds_3dcr_instruction_dict["instruction_bits"])
        config_instruction |= ds_3dcr_instruction_dict["instruction_int"][0] & ((1 << len(ds_3dcr_instruction_dict["instruction_bits"])) - 1)
        config_instruction_bit_list.extend(ds_3dcr_instruction_dict["instruction_bits"])
        # PTAP 3DCR configuration
        config_instruction <<= 1
        config_instruction |= ptap_config_hold.value & ((1 << 1) - 1)
        config_instruction_bit_list.append(ptap_config_hold.value)
        config_instruction <<= 1
        config_instruction |= DTPSTAP3DCR_stap_sel_e.STAP_SEL_1.value & ((1 << 1) - 1)
        config_instruction_bit_list.append(DTPSTAP3DCR_stap_sel_e.STAP_SEL_1.value) # Always enable PTAP STAP selection for STAP network configuration
        return {
            "instruction_int": config_instruction,
            "instruction_bits": config_instruction_bit_list,
        }

# ==============================================================================
# 3DCR Network Data Structure
#   This data structure is used to store the 3DCR network configuration.
#   It contains the STAP network configuration and the adjacent die PTAP
#   configuration.
# ==============================================================================
@dataclass
class DTP3DICNetwork_s:
    """3DCR Network data structure"""
    stap_network: DTPSTAPNetwork_s

    ds_ptap_instruction: DTPCustomJTAGInstruction_s
    smc_ptap_instruction: DTPCustomJTAGInstruction_s
    sep_ptap_instruction: DTPCustomJTAGInstruction_s
    extra_staps_instruction: list[DTPCustomJTAGInstruction_s]

    @staticmethod
    def pack_stap2ptap_ir_instruction(
        stap_config: DTPSTAPConfig_s,
        ptap_instruction: DTPCustomJTAGInstruction_s,
    ) -> list[int]:
        """Pack the IR scan instruction for the STAP network in reverse order"""
        ir_scan_instruction = []
        if stap_config.cfg_3dcr.stap_sel == DTPSTAP3DCR_stap_sel_e.STAP_SEL_1:
            # IR
            op_code_bit_list = DTPBaseStructure_s.int_to_bit_list(
                ptap_instruction.opcode,
                ptap_instruction.ir_width
            )
            ir_scan_instruction.extend(op_code_bit_list)
        if stap_config.cfg_sib == DTPSIBState_e.SIB_ON:
            stap_3dcr_instruction_dict = DTPSTAPConfig_s.pack_stap_config_instruction(
                cfg_3dcr=stap_config.cfg_3dcr,
                cfg_sib=stap_config.cfg_sib
            )
            ir_scan_instruction = stap_3dcr_instruction_dict["instruction_bits"] + ir_scan_instruction
        else:
            ir_scan_instruction = [0] + ir_scan_instruction
        return ir_scan_instruction

    @staticmethod
    def pack_stap2ptap_tdr_instruction(
        stap_config: DTPSTAPConfig_s,
        ptap_instruction: DTPCustomJTAGInstruction_s,
    ) -> list[int]:
        """Pack the TDR instruction for the STAP network in reverse order"""
        tdr_instruction = []
        if stap_config.cfg_3dcr.stap_sel == DTPSTAP3DCR_stap_sel_e.STAP_SEL_1:
            # TDR
            tdr_bit_list = DTPBaseStructure_s.int_to_bit_list(
                ptap_instruction.dr_value, ptap_instruction.dr_width
            )
            tdr_instruction.extend(tdr_bit_list)
        if stap_config.cfg_sib == DTPSIBState_e.SIB_ON:
            stap_3dcr_instruction_dict = DTPSTAPConfig_s.pack_stap_config_instruction(
                cfg_3dcr=stap_config.cfg_3dcr,
                cfg_sib=stap_config.cfg_sib
            )
            tdr_instruction = stap_3dcr_instruction_dict["instruction_bits"] + tdr_instruction
        else:
            tdr_instruction = [0] + tdr_instruction
        return tdr_instruction

    # Note:
    #   PTAP TDI -> PTAP IR => PTAP 3DCR =>
    #   DS STAP IR => {DS STAP SIB => DS STAP 3DCR} =>
    #   SMC STAP IR => {SMC STAP SIB => SMC STAP 3DCR} =>
    #   SEP STAP IR => {SEP STAP SIB => SEP STAP 3DCR} =>
    #  [Extra STAPs IR => {Extra STAPs SIB => Extra STAPs 3DCR}] =>
    #   EXT STAP Scan -> PTAP TDO
    @staticmethod
    def pack_ir_scan_instruction(
        stap_network: DTPSTAPNetwork_s,
        ds_ptap_instruction: DTPCustomJTAGInstruction_s,
        smc_ptap_instruction: DTPCustomJTAGInstruction_s,
        sep_ptap_instruction: DTPCustomJTAGInstruction_s,
        extra_ptap_instruction: list[DTPCustomJTAGInstruction_s],
        ptap_config_hold: DTPSTAP3DCR_config_hold_e = DTPSTAP3DCR_config_hold_e.CONFIG_HOLD_1,
        ptap_ir_cmd: DTPJTAGInstr_e = DTPJTAGInstr_e.BYPASS_00,
    ) -> list[int]:
        """Pack the IR scan instruction for the STAP network in reverse order"""
        ## Extended STAP scan interface
        #ir_scan_instruction = [0] * ext_tdr_size
        ir_scan_instruction = []
        # Extra STAPs scan interface
        extra_ptap_instruction_index = 0
        for _stap_cfg in stap_network.extra_stap_cfg:
            ir_extra_stap_instruction = DTP3DICNetwork_s.pack_stap2ptap_ir_instruction(
                stap_config=_stap_cfg,
                ptap_instruction=extra_ptap_instruction[extra_ptap_instruction_index]
            )
            ir_scan_instruction.extend(ir_extra_stap_instruction)
            extra_ptap_instruction_index += 1
        # SEP STAP scan interface
        ir_sep_stap_instruction = DTP3DICNetwork_s.pack_stap2ptap_ir_instruction(
            stap_config=stap_network.sep_stap_cfg,
            ptap_instruction=sep_ptap_instruction
        )
        ir_scan_instruction.extend(ir_sep_stap_instruction)
        # SMC STAP scan interface
        ir_smc_stap_instruction = DTP3DICNetwork_s.pack_stap2ptap_ir_instruction(
            stap_config=stap_network.smc_stap_cfg,
            ptap_instruction=smc_ptap_instruction
        )
        ir_scan_instruction.extend(ir_smc_stap_instruction)
        # DS STAP scan interface
        ir_ds_stap_instruction = DTP3DICNetwork_s.pack_stap2ptap_ir_instruction(
            stap_config=stap_network.ds_stap_cfg,
            ptap_instruction=ds_ptap_instruction
        )
        ir_scan_instruction.extend(ir_ds_stap_instruction)
        # PTAP scan interface
        #ir_scan_instruction.append(ptap_config_hold.value & (((1 << 1)) - 1))
        #ir_scan_instruction.append(DTPSTAP3DCR_stap_sel_e.STAP_SEL_1.value) # Always enable PTAP STAP selection for STAP network configuration
        ir_scan_instruction.extend(DTPBaseStructure_s.int_to_bit_list(
            ptap_ir_cmd, DTPJTAGInstr_e.get_ir_width()
            #DTPJTAGInstr_e.TAP_3DCR, DTPJTAGInstr_e.get_ir_width()
        ))
        # TODO: TO BE REMOVED WHILE FIXING THE ISSUE WITH SCANNING STAP NETWORK
        #       OR CHECK IF THE ISSUE IS FIXED IN MULTI_DTP SIMULATION ENVIRONMENT
        # Workaroung: Dummy Bit for PTAP IR to prevent accumulation beyond IR width
        #             We need to set PTAP.CONFIG_HOLD=1 to prevent removing STAP selection
        #ir_scan_instruction.append(0)
        #print(f"ir_scan_instruction (bubble): {ir_scan_instruction}")
        # Return the IR scan instruction
        return ir_scan_instruction

    # Note:
    #   PTAP TDI -> PTAP IR
    #   DS STAP 3DCR -> DS STAP SIB -> DS STAP IR ->
    #   SMC STAP 3DCR -> SMC STAP SIB -> SMC STAP IR ->
    #   SEP STAP 3DCR -> SEP STAP SIB -> SEP STAP IR ->
    #  [Extra STAPs 3DCR -> Extra STAPs SIB -> Extra STAPs IR]
    #   EXT STAP 3DCR -> PTAP TDO
    @staticmethod
    def pack_tdr_scan_instruction(
        stap_network: DTPSTAPNetwork_s,
        ds_ptap_instruction: DTPCustomJTAGInstruction_s,
        smc_ptap_instruction: DTPCustomJTAGInstruction_s,
        sep_ptap_instruction: DTPCustomJTAGInstruction_s,
        extra_ptap_instruction: list[DTPCustomJTAGInstruction_s],
        ptap_config_hold: DTPSTAP3DCR_config_hold_e = DTPSTAP3DCR_config_hold_e.CONFIG_HOLD_1,
        ptap_tdr_size: int = 1,
    ) -> list[int]:
        """Pack the TDR scan instruction for the STAP network in reverse order"""
        # Extended STAP scan interface
        #tdr_scan_instruction = [0] * ext_tdr_size
        tdr_scan_instruction = []
        # Extra STAPs scan interface
        extra_ptap_instruction_index = 0
        for _stap_cfg in stap_network.extra_stap_cfg:
            extra_tdr_instruction = DTP3DICNetwork_s.pack_stap2ptap_tdr_instruction(
                stap_config=_stap_cfg,
                ptap_instruction=extra_ptap_instruction[extra_ptap_instruction_index]
            )
            tdr_scan_instruction.extend(extra_tdr_instruction)
            extra_ptap_instruction_index += 1
        # SEP STAP scan interface
        sep_tdr_instruction = DTP3DICNetwork_s.pack_stap2ptap_tdr_instruction(
            stap_config=stap_network.sep_stap_cfg,
            ptap_instruction=sep_ptap_instruction
        )
        tdr_scan_instruction.extend(sep_tdr_instruction)
        # SMC STAP scan interface
        smc_tdr_instruction = DTP3DICNetwork_s.pack_stap2ptap_tdr_instruction(
            stap_config=stap_network.smc_stap_cfg,
            ptap_instruction=smc_ptap_instruction
        )
        tdr_scan_instruction.extend(smc_tdr_instruction)
        # DS STAP scan interface
        ds_tdr_instruction = DTP3DICNetwork_s.pack_stap2ptap_tdr_instruction(
            stap_config=stap_network.ds_stap_cfg,
            ptap_instruction=ds_ptap_instruction
        )
        tdr_scan_instruction.extend(ds_tdr_instruction)
        # PTAP scan interface
        #tdr_scan_instruction.append(ptap_config_hold.value & (((1 << 1)) - 1))
        #tdr_scan_instruction.append(DTPSTAP3DCR_stap_sel_e.STAP_SEL_1.value & 0x1) # Always enable PTAP STAP selection for STAP network configuration
        # PTAP TDR
        tdr_scan_instruction.extend([0] * ptap_tdr_size)
        # TODO: TO BE REMOVED WHILE FIXING THE ISSUE WITH SCANNING STAP NETWORK
        #       OR CHECK IF THE ISSUE IS FIXED IN MULTI_DTP SIMULATION ENVIRONMENT
        # Workaroung: Dummy Bit for PTAP IR to prevent accumulation beyond IR width
        #             We need to set PTAP.CONFIG_HOLD=1 to prevent removing STAP selection
        #tdr_scan_instruction.append(0)
        # Return the TDR scan instruction
        return tdr_scan_instruction

    @staticmethod
    def pack_scan_instruction(
        stap_network: DTPSTAPNetwork_s,
        ds_ptap_instruction: DTPCustomJTAGInstruction_s,
        smc_ptap_instruction: DTPCustomJTAGInstruction_s,
        sep_ptap_instruction: DTPCustomJTAGInstruction_s,
        extra_ptap_instruction: list[DTPCustomJTAGInstruction_s],
        ptap_config_hold: DTPSTAP3DCR_config_hold_e = DTPSTAP3DCR_config_hold_e.CONFIG_HOLD_1,
    ) -> dict[str, list[int]]:
        """Pack the scan instruction for the 3DIC network"""
        return {
            "ir_scan_instruction": DTP3DICNetwork_s.pack_ir_scan_instruction(
                stap_network=stap_network,
                ds_ptap_instruction=ds_ptap_instruction,
                smc_ptap_instruction=smc_ptap_instruction,
                sep_ptap_instruction=sep_ptap_instruction,
                extra_ptap_instruction=extra_ptap_instruction,
                ptap_config_hold=ptap_config_hold,
            ),
            "tdr_scan_instruction": DTP3DICNetwork_s.pack_tdr_scan_instruction(
                stap_network=stap_network,
                ds_ptap_instruction=ds_ptap_instruction,
                smc_ptap_instruction=smc_ptap_instruction,
                sep_ptap_instruction=sep_ptap_instruction,
                extra_ptap_instruction=extra_ptap_instruction,
                ptap_config_hold=ptap_config_hold,
            ),
        }


# ==============================================================================
# XTRIG Test Configuration Data Structure
# ==============================================================================
class DTPCTPMode_e(IntEnum):
    """
    CTP Operation Modes

    Cross-Trigger Port (CTP) operation modes for hardware triggering.
    """

    WIRE_OR = 0  # Simple wired-OR mode with pulse stretching
    POINT_TO_POINT = 1  # Handshake-based point-to-point mode

class DTPCTMDeviceType_e(IntEnum):
    """CTM Device Type Enumeration"""
    CTP = 0   # External CTP device
    CLA = 1   # Internal CLA device

@dataclass
class DTPCTMConfig_s:
    """CTM Full Configuration"""
    ctm_mapping: list[int]
    ctp_mode: list[DTPCTPMode_e]
    ctp_invert: list[int]
    def __str__(self):
        return f"CTM P2P Test Configuration: ctm_config={self.ctm_mapping}\nctp_mode={self.ctp_mode}\nctp_invert={self.ctp_invert}"
    def __repr__(self):
        return self.__str__()

# ==============================================================================
# Test Configuration Data Structure
# ==============================================================================


@dataclass
class DTPTestConfig_s:
    """Test configuration data structure"""

    # Test Configuration
    timeout_cycles: int = 1000000 # 1M cycles
    num_iterations: int = 32

    jtag_tck_period_ns: int = 100
    clock_period_ns: int = 10
    num_ctp: int = 16
    num_int_ct: int = 10

    # JTAG Configuration
    jtag_ir_width: int = 6

    # AXI Configuration
    smc_otp_addr_width: int = 32 # Bits
    sep_otp_addr_width: int = 32 # Bits
    smc_fabric_addr_width: int = 32 # Bits
    smc_otp_data_width: int = 32 # Bits
    sep_otp_data_width: int = 32 # Bits
    smc_fabric_data_width: int = 64 # Bits

    # JTAG2AXI Configuration
    smc_otp_rd_pl_depth: int = 3
    smc_otp_wr_pl_depth: int = 3
    sep_otp_rd_pl_depth: int = 3
    sep_otp_wr_pl_depth: int = 3
    smc_fabric_rd_pl_depth: int = 3
    smc_fabric_wr_pl_depth: int = 3

    # IJTAG Network Configuration
    ijtag_bsr_tdr_size:     int = 4
    ijtag_dfd_tdr_size:     int = 4
    ijtag_dft_tdr_size:     int = 4
    ijtag_sec_dft_tdr_size: int = 4
    ijtag_ext_tdr_size:     int = 4

    # STAP Network Configuration
    enable_downstream_stap: bool = True
    enable_smc_stap: bool = True
    enable_sep_stap: bool = True
    num_extra_staps: int = 1

    # STAP TDR Configuration
    stap_tdr_size: int = 16

    # 3DIC Network Configuration
    ds_ptap_instruction_set: list[DTPCustomJTAGInstruction_s] = field(default_factory=list)
    smc_ptap_instruction_set: list[DTPCustomJTAGInstruction_s] = field(default_factory=list)
    sep_ptap_instruction_set: list[DTPCustomJTAGInstruction_s] = field(default_factory=list)
    extra_ptap_instruction_set: list[list[DTPCustomJTAGInstruction_s]] = field(default_factory=list)

    def __post_init__(self):
        # Get Timeout Cycles from environment
        self.timeout_cycles = int(os.environ.get("TIMEOUT_CYCLES", "1000000"))
        # Get number of iterations from environment
        self.num_iterations = int(os.environ.get("TEST_ITERATIONS", "32"))
        self.ds_ptap_instruction_set: list[DTPCustomJTAGInstruction_s] = [
            DTPCustomJTAGInstruction_s(opcode=0x00, dr_value=0x00000000, dr_width=1, name="ds_bypass"),
            DTPCustomJTAGInstruction_s(opcode=0x05, dr_value=0x00000000, dr_width=2, name="ds_scan_2b"),
            DTPCustomJTAGInstruction_s(opcode=0x0A, dr_value=0x00000000, dr_width=4, name="ds_scan_4b"),
            DTPCustomJTAGInstruction_s(opcode=0x15, dr_value=0x00000000, dr_width=8, name="ds_scan_8b"),
            DTPCustomJTAGInstruction_s(opcode=0x1A, dr_value=0x00000000, dr_width=16, name="ds_scan_16b"),
            DTPCustomJTAGInstruction_s(opcode=0x35, dr_value=0x00000000, dr_width=32, name="ds_scan_32b"),
            DTPCustomJTAGInstruction_s(opcode=0x3A, dr_value=0x00000000, dr_width=64, name="ds_scan_64b"),
        ]
        self.smc_ptap_instruction_set: list[DTPCustomJTAGInstruction_s] = [
            DTPCustomJTAGInstruction_s(opcode=0x00, dr_value=0x00000000, dr_width=1, name="smc_bypass"),
            DTPCustomJTAGInstruction_s(opcode=0x05, dr_value=0x00000000, dr_width=2, name="smc_scan_2b"),
            DTPCustomJTAGInstruction_s(opcode=0x0A, dr_value=0x00000000, dr_width=4, name="smc_scan_4b"),
            DTPCustomJTAGInstruction_s(opcode=0x15, dr_value=0x00000000, dr_width=8, name="smc_scan_8b"),
            DTPCustomJTAGInstruction_s(opcode=0x1A, dr_value=0x00000000, dr_width=16, name="smc_scan_16b"),
            DTPCustomJTAGInstruction_s(opcode=0x35, dr_value=0x00000000, dr_width=32, name="smc_scan_32b"),
            DTPCustomJTAGInstruction_s(opcode=0x3A, dr_value=0x00000000, dr_width=64, name="smc_scan_64b"),
        ]
        self.sep_ptap_instruction_set: list[DTPCustomJTAGInstruction_s] = [
            DTPCustomJTAGInstruction_s(opcode=0x00, dr_value=0x00000000, dr_width=1, name="sep_bypass"),
            DTPCustomJTAGInstruction_s(opcode=0x05, dr_value=0x00000000, dr_width=2, name="sep_scan_2b"),
            DTPCustomJTAGInstruction_s(opcode=0x0A, dr_value=0x00000000, dr_width=4, name="sep_scan_4b"),
            DTPCustomJTAGInstruction_s(opcode=0x15, dr_value=0x00000000, dr_width=8, name="sep_scan_8b"),
            DTPCustomJTAGInstruction_s(opcode=0x1A, dr_value=0x00000000, dr_width=16, name="sep_scan_16b"),
            DTPCustomJTAGInstruction_s(opcode=0x35, dr_value=0x00000000, dr_width=32, name="sep_scan_32b"),
            DTPCustomJTAGInstruction_s(opcode=0x3A, dr_value=0x00000000, dr_width=64, name="sep_scan_64b"),
        ]
        self.extra_ptap_instruction_set: list[list[DTPCustomJTAGInstruction_s]] = [
            [
                DTPCustomJTAGInstruction_s(opcode=0x00, dr_value=0x00000000, dr_width=1, name=f"extra{i}_bypass"),
                DTPCustomJTAGInstruction_s(opcode=0x05, dr_value=0x00000000, dr_width=2, name=f"extra{i}_scan_2b"),
                DTPCustomJTAGInstruction_s(opcode=0x0A, dr_value=0x00000000, dr_width=4, name=f"extra{i}_scan_4b"),
                DTPCustomJTAGInstruction_s(opcode=0x15, dr_value=0x00000000, dr_width=8, name=f"extra{i}_scan_8b"),
                DTPCustomJTAGInstruction_s(opcode=0x1A, dr_value=0x00000000, dr_width=16, name=f"extra{i}_scan_16b"),
                DTPCustomJTAGInstruction_s(opcode=0x35, dr_value=0x00000000, dr_width=32, name=f"extra{i}_scan_32b"),
                DTPCustomJTAGInstruction_s(opcode=0x3A, dr_value=0x00000000, dr_width=64, name=f"extra{i}_scan_64b"),
            ] for i in range(self.num_extra_staps)
        ]

    def print_config(self, log_obj):
        """Print the test configuration"""
        log_obj.info("=" * 80)
        log_obj.info("Test Configuration")
        log_obj.info("=" * 80)
        log_obj.info(f"  JTAG TCK Period:           {self.jtag_tck_period_ns} ns")
        log_obj.info(f"  JTAG TCK Frequency:        {1000000000 / self.jtag_tck_period_ns} Hz")
        log_obj.info(f"  JTAG IR Width:             {self.jtag_ir_width}")
        log_obj.info(f"  Clock Period:              {self.clock_period_ns} ns")
        log_obj.info(f"  Clock Frequency:           {1000000000 / self.clock_period_ns} Hz")
        log_obj.info(f"  Number of CTPs:            {self.num_ctp}")
        log_obj.info(f"  Enable Downstream STAP:    {self.enable_downstream_stap}")
        log_obj.info(f"  Enable SMC STAP:           {self.enable_smc_stap}")
        log_obj.info(f"  Enable SEP STAP:           {self.enable_sep_stap}")
        log_obj.info(f"  Number of Extra STAPs:     {self.num_extra_staps}")
        log_obj.info(f"  SMC OTP Address Width:     {self.smc_otp_addr_width} Bits")
        log_obj.info(f"  SEP OTP Address Width:     {self.sep_otp_addr_width} Bits")
        log_obj.info(f"  SMC Fabric Address Width:  {self.smc_fabric_addr_width} Bits")
        log_obj.info(f"  SMC OTP Data Width:        {self.smc_otp_data_width} Bits")
        log_obj.info(f"  SEP OTP Data Width:        {self.sep_otp_data_width} Bits")
        log_obj.info(f"  SMC Fabric Data Width:     {self.smc_fabric_data_width} Bits")
        log_obj.info(f"  IJTAG BSR TDR Size:        {self.ijtag_bsr_tdr_size}")
        log_obj.info(f"  IJTAG DFD TDR Size:        {self.ijtag_dfd_tdr_size}")
        log_obj.info(f"  IJTAG DFT TDR Size:        {self.ijtag_dft_tdr_size}")
        log_obj.info(f"  IJTAG Secure DFT TDR Size: {self.ijtag_sec_dft_tdr_size}")
        log_obj.info(f"  IJTAG EXT TDR Size:        {self.ijtag_ext_tdr_size}")
        log_obj.info(f"  STAP TDR Size:             {self.stap_tdr_size}")
        log_obj.info(f"  DS PTAP Instruction Set:   {self.ds_ptap_instruction_set}")
        log_obj.info(f"  SEP PTAP Instruction Set:  {self.sep_ptap_instruction_set}")
        for i in range(self.num_extra_staps):
            log_obj.info(f"    Extra PTAP {i} Instruction Set: {self.extra_ptap_instruction_set[i]}")
        log_obj.info("=" * 80)


# ==============================================================================
# Utility Functions for Enumerations
# ==============================================================================
def enum_to_str(enum_val) -> str:
    """
    Convert enum value to string representation

    Args:
        enum_val: Enumeration value

    Returns:
        String representation
    """
    if isinstance(enum_val, Enum):
        return f"{enum_val.__class__.__name__}.{enum_val.name} ({enum_val.value})"
    return str(enum_val)


def is_valid_enum(value, enum_class) -> bool:
    """
    Check if value is valid for given enum class

    Args:
        value: Value to check
        enum_class: Enumeration class

    Returns:
        True if value is valid enum member
    """
    try:
        enum_class(value)
        return True
    except ValueError:
        return False


def get_enum_names(enum_class) -> list[str]:
    """
    Get list of all enum member names

    Args:
        enum_class: Enumeration class

    Returns:
        List of member names
    """
    return [member.name for member in enum_class]


def get_enum_values(enum_class) -> list[int]:
    """
    Get list of all enum member values

    Args:
        enum_class: Enumeration class

    Returns:
        List of member values
    """
    return [member.value for member in enum_class]


def print_enum_info(enum_class):
    """
    Print information about an enumeration class

    Args:
        enum_class: Enumeration class to display
    """
    print(f"\n{enum_class.__name__}:")
    print(f"  Members: {len(enum_class)}")
    for member in enum_class:
        print(f"    {member.name:30s} = {member.value}")
