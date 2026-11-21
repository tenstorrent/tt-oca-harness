# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary-TAP access for the wrapper flow.

The wrapper testbench exposes the primary TAP as the `jtag_tck/tms/trst/tdi/tdo`
pins `OcahJtagMasterDriver` binds to. This module carries the TAP factory and
the IR opcodes, taken from the DV-owned DTP instruction table, and registers the
JTAG2AXI bridge TDRs the `seq_lib/smu_jtag_helpers.py` transports scan. The full
DTP register map is `make_smu_jtag_tap` in that module.
"""

from __future__ import annotations

import cocotb
from dtp_types import DTP_IR_WIDTH, DtpJtagInstr
from ocah_jtag_vip import OcahJtagDevice, OcahJtagMasterDriver

from seq_lib.smu_jtag_helpers import add_jtag2axi_regs

PTAP_IR_WIDTH = DTP_IR_WIDTH
# Every JTAG_IDCODE_* parameter defaults to 0 in doc/integrator/src/smu.adoc,
# "SMU Default Parameters"; only the architecture.adoc "ID Code" marker bit
# (bit 0, always 1) is set.
PTAP_DEFAULT_IDCODE = 0x0000_0001


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
    add_jtag2axi_regs(device)

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
