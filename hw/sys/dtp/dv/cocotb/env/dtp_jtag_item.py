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


class DtpJtagOp(Enum):
    RESET = "reset"  # await JTAG auto-reset (TRST) completion
    RESET_FSM = "reset_fsm"  # drive TAP to Test-Logic-Reset
    TMS_STEP = "tms_step"  # drive one raw TMS cycle and sample DUT TAP state
    SHIFT_IR = "shift_ir"  # shift a raw IR value -> captured previous IR bits
    SHIFT_DR = "shift_dr"  # shift a raw DR value -> captured TDO bits
    SET_TRST = "set_trst"  # directly drive TRST_N and optionally tick TCK
    PULSE_POR = "pulse_por"  # pulse pwr_on_rst_ni and sample TAP state
    SAMPLE = "sample"  # sample exposed DUT observables
    READ = "read"  # read a TDR by name -> result
    WRITE = "write"  # write a TDR by name with value
    J2A_WRITE = "j2a_write"  # JTAG2AXI single write (addr, data)
    J2A_READ = "j2a_read"  # JTAG2AXI single read (addr) -> status, rdata


class DtpJtagItem(uvm_sequence_item):
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
        # JTAG2AXI fields
        self.axi_addr: int = 0
        self.axi_data: int = 0
        self.axi_wstrb: int = 0xFF
        self.axi_size: int = 3
        # Results (filled in by the driver)
        self.result: int = 0  # raw TDR read value
        # TAP state sampled with the reset pin asserted and no TCK edge since.
        self.reset_state: int = 0
        self.decoded: int = 0  # raw decoded instruction one-hot value
        self.signals: dict[str, int] = {}
        self.status: int = 0  # JTAG2AXI capture status
        self.rdata: int = 0  # JTAG2AXI read data

    def __str__(self) -> str:
        return (
            f"{self.op.value} reg={self.reg} value=0x{self.value:x} "
            f"width={self.width} tms={self.tms} cycles={self.cycles} "
            f"addr=0x{self.axi_addr:x} data=0x{self.axi_data:x} "
            f"result=0x{self.result:x} decoded=0x{self.decoded:x} "
            f"status={self.status} rdata=0x{self.rdata:x}"
        )
