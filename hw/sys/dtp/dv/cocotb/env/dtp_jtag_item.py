# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP JTAG sequence item.

A single TAP action. Generic JTAG ops (reset, TDR read/write) plus the two
DTP-specific JTAG2AXI single-op transactions, so sequences describe scenarios
and the driver owns the OCAH JTAG BFM mechanics and JTAG2AXI TDR packing.
"""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item

__all__ = ["DtpJtagItem", "DtpJtagOp"]


class DtpJtagOp(Enum):
    """The TAP action a ``DtpJtagItem`` asks the driver for."""

    RESET = "reset"  # await JTAG auto-reset (TRST) completion
    RESET_FSM = "reset_fsm"  # drive TAP to Test-Logic-Reset
    TMS_STEP = "tms_step"  # drive one raw TMS cycle and sample DUT TAP state
    SHIFT_IR = "shift_ir"  # shift a raw IR value -> captured previous IR bits
    SHIFT_DR = "shift_dr"  # shift a raw DR value -> captured TDO bits
    SET_TRST = "set_trst"  # change the TRST_N level and optionally tick TCK
    PULSE_POR = "pulse_por"  # pulse pwr_on_rst_ni and sample TAP state
    SAMPLE = "sample"  # sample exposed DUT observables
    READ = "read"  # read a TDR by name -> result
    WRITE = "write"  # write a TDR by name with value


class DtpJtagItem(uvm_sequence_item):
    """One TAP action with its stimulus fields and the results the driver fills in."""

    def __init__(self, name: str = "DtpJtagItem") -> None:
        super().__init__(name)
        self.op: DtpJtagOp = DtpJtagOp.READ
        self.reg: str = "IDCODE"
        self.value: int = 0
        self.width: int = 0
        self.back_to_rti: bool = True
        self.tms: int = 0
        self.tdi: int = 0  # TDI of a TMS_STEP cycle
        self.cycles: int = 1
        # Results (filled in by the driver)
        self.result: int = 0  # raw TDR read value
        # TAP state sampled with the reset pin asserted and no TCK edge since.
        self.reset_state: int = 0
        self.decoded: int = 0  # raw decoded instruction one-hot value
        self.signals: dict[str, int] = {}

    def __str__(self) -> str:
        return (
            f"{self.op.value} reg={self.reg} value=0x{self.value:x} "
            f"width={self.width} tms={self.tms} cycles={self.cycles} "
            f"result=0x{self.result:x} decoded=0x{self.decoded:x}"
        )
