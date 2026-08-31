# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from dataclasses import dataclass
from typing import List, Optional

from cocotb.triggers import RisingEdge


@dataclass
class APBTransaction:
    address: int
    write: bool
    wdata: int
    rdata: Optional[int] = None


class APBMonitor:
    """
    Lightweight APB4 monitor that observes SETUP/ACCESS and records
    single-beat transactions. Intended for debug/logging.
    """

    def __init__(self, dut):
        self.dut = dut
        # Support either direct DUT ports or an apb interface under tb
        apb = getattr(dut, "apb", None)
        handle = apb if apb is not None else dut
        self.pclk = handle.pclk if apb is not None else handle.pclk_i
        self.psel = handle.psel if apb is not None else handle.psel_i
        self.penable = handle.penable if apb is not None else handle.penable_i
        self.pwrite = handle.pwrite if apb is not None else handle.pwrite_i
        self.paddr = handle.paddr if apb is not None else handle.paddr_i
        self.pwdata = handle.pwdata if apb is not None else handle.pwdata_i
        self.prdata = handle.prdata if apb is not None else handle.prdata_o
        # APB4 signals (optional)
        self.pready = getattr(handle, "pready", None)
        self.pslverr = getattr(handle, "pslverr", None)
        self.transactions: List[APBTransaction] = []
        self._active: Optional[APBTransaction] = None

    async def start(self) -> None:
        """
        Run forever; record a transaction on each ACCESS phase.
        """
        while True:
            await RisingEdge(self.pclk)
            if int(self.psel.value) == 1 and int(self.penable.value) == 0:
                # SETUP phase: capture address and write intent
                self._active = APBTransaction(
                    address=int(self.paddr.value) & 0xFFF,
                    write=bool(int(self.pwrite.value)),
                    wdata=int(self.pwdata.value),
                )
            elif int(self.psel.value) == 1 and int(self.penable.value) == 1:
                # ACCESS phase: complete the transaction
                if self._active is None:
                    continue
                if not self._active.write:
                    self._active.rdata = int(self.prdata.value)
                self.transactions.append(self._active)
                # Debug log
                if self._active.write:
                    self.dut._log.info(
                        f"APBMonitor: WRITE @0x{self._active.address:03X} = 0x{self._active.wdata:08X}"
                    )
                else:
                    self.dut._log.info(
                        f"APBMonitor: READ  @0x{self._active.address:03X} -> 0x{self._active.rdata:08X}"
                    )
                self._active = None
