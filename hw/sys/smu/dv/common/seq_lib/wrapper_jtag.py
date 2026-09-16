# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary-TAP access for the wrapper flow.

The wrapper testbench exposes the same `jtag_tck/tms/trst/tdi/tdo` pins the
bare `--dut smu_block` harness does, so `OcahJtagMasterDriver` binds to either DUT
unchanged. This module carries the wrapper-side binding: the TAP factory and
the IR opcodes, taken from the DV-owned DTP instruction table. The full DTP
register map is `make_smu_jtag_tap` in `seq_lib/smu_jtag_helpers.py`.
"""

from __future__ import annotations

import cocotb
from dtp_types import DTP_IR_WIDTH, DtpJtagInstr
from ocah_jtag_vip import OcahJtagDevice, OcahJtagMasterDriver

PTAP_IR_WIDTH = DTP_IR_WIDTH
# Every JTAG_IDCODE_* parameter defaults to 0 in doc/integrator/src/smu.adoc,
# "SMU Default Parameters"; only the architecture.adoc "ID Code" marker bit
# (bit 0, always 1) is set.
PTAP_DEFAULT_IDCODE = 0x0000_0001

#: JTAG2AXI CAPS geometry register width (architecture.adoc, bits 13:0).
SMC_JTAG2AXI_CAPS_LEN = 14
#: SINGLE_OP payload: OP2 | SIZE2 | WSTRB8 | DATA64 | ADDR56.
SMC_AXI_SINGLE_OP_LEN = 132

#: SINGLE_OP opcodes.
J2A_OP_READ = 0b01
J2A_OP_WRITE = 0b10
#: AxSIZE encodings.
J2A_SIZE_4B = 0b10
J2A_SIZE_8B = 0b11


def single_op_payload(
    op: int, addr: int, *, size: int = J2A_SIZE_8B, data: int = 0, wstrb: int = 0
) -> int:
    """Pack a SINGLE_OP DR, LSB-first: OP2 | SIZE2 | WSTRB8 | DATA64 | ADDR56.

    `op` sits in the LOWEST bits -- architecture.adoc lists it at [1:0] -- and
    the address at the top. This matches pack_single_op() in
    `seq_lib/smu_jtag_helpers.py`; the field offsets are not obvious from the
    document's relative "(...) +: width" notation alone.
    """
    return (
        (op & 0x3)
        | ((size & 0x3) << 2)
        | ((wstrb & 0xFF) << 4)
        | ((data & ((1 << 64) - 1)) << 12)
        | ((addr & ((1 << 56) - 1)) << 76)
    )


#: SINGLE_OP capture status codes (architecture.adoc: the op field reads back
#: as the previous transaction's result).
J2A_ST_OKAY = 0
J2A_ST_SLVERR = 1
J2A_ST_DECERR = 2
J2A_ST_BUSY = 3

J2A_STATUS_NAME = {
    J2A_ST_OKAY: "OKAY",
    J2A_ST_SLVERR: "SLVERR",
    J2A_ST_DECERR: "DECERR",
    J2A_ST_BUSY: "BUSY (previous op still in flight)",
}


def single_op_status(captured: int) -> int:
    """Status field from a captured SINGLE_OP DR (0 = OKAY)."""
    return int(captured) & 0x3


def single_op_rdata(captured: int) -> int:
    """Read data from a captured SINGLE_OP DR, at the same offset as on write."""
    return (int(captured) >> 12) & ((1 << 64) - 1)


def ptap_ir_opcode(name: str) -> int:
    """PTAP IR opcode for instruction ``name``.

    ``DtpJtagInstr`` (hw/sys/dtp/dv/cocotb/env/dtp_types.py) transcribes the
    "Instruction Encodings" table of hw/ip/jtag/jtag_intf_unit/doc/interface.adoc.
    """
    try:
        return int(DtpJtagInstr[name])
    except KeyError as exc:
        raise KeyError(f"{name} is not a DtpJtagInstr instruction name") from exc


def make_wrapper_ptap(period_ns: float = 100) -> OcahJtagMasterDriver:
    """Bind a primary-TAP driver to the wrapper testbench pins."""
    device = OcahJtagDevice(
        name="smu_wrapper_ptap",
        idcode=PTAP_DEFAULT_IDCODE,
        ir_width=PTAP_IR_WIDTH,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, ptap_ir_opcode("IDCODE"))
    # SMC fabric JTAG2AXI. CAPS is read-only geometry; SINGLE_OP is the write
    # that launches a transaction, and is what dbg_disable.smc_jtag2axi gates.
    # Field order per hw/ip/jtag/jtag_ptap/doc/architecture.adoc:
    #   CAPS      [13:12] rd_pl_depth, [11:10] wr_pl_depth, [9:7] data_size,
    #             [6:1] addr_size, [0] bus_type
    #   SINGLE_OP OP2 | SIZE2 | WSTRB8 | DATA64 | ADDR56 = 132 bits
    device.add_reg(
        "SMC_JTAG2AXI_CAPS",
        SMC_JTAG2AXI_CAPS_LEN,
        ptap_ir_opcode("SMC_JTAG2AXI_CAPS"),
    )
    device.add_reg(
        "SMC_AXI_SINGLE_OP",
        SMC_AXI_SINGLE_OP_LEN,
        ptap_ir_opcode("SMC_AXI_SINGLE_OP"),
        write=True,
    )

    jtag = OcahJtagMasterDriver(
        cocotb.top,
        name="smu_wrapper_ptap",
        tck_period_ns=period_ns,
        ir_width=PTAP_IR_WIDTH,
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


def require_tdo_resolved(label: str) -> None:
    """Fail if TDO is X/Z.

    An unresolved TDO reads as 0 through `int()`, which would let a wrong-value
    check pass by accident; make it a failure instead.
    """
    value = cocotb.top.jtag_tdo.value
    if hasattr(value, "is_resolvable") and not value.is_resolvable:
        raise AssertionError(f"{label}: jtag_tdo is unresolved ({value})")
