# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""axil_mailbox interface driver (outbound aperture, CPU-LSU, TX path).

Drives the SEP outbound_mailbox_0 aperture (0x10A0_0000) over the CPU-LSU master, the SEP side
of the two-port cross-FIFO, with no inbound filter. WRITE_DATA pushes the TX FIFO as one native
64-bit beat per entry (``memory_map.adoc``). READ_DATA pops the RX FIFO; with no peer port wired
it is empty and returns the 0xFEEDDEAD sentinel with SLVERR. 32-bit CSRs use 4-byte beats.

Register constants and the golden depth model are in env/sep_mbox_golden.py.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_mbox_golden import (
    CLOCK_GATE_CTRL,
    CLOCK_GATE_IMPL_MASK,
    CTRL,
    CTRL_WFLUSH,
    OUTBOUND_BASE,
    READ_DATA,
    WRITE_DATA,
)

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver


class SepMbox(SepAxiRegDriver):
    """Direct-AXI axil_mailbox access on the outbound aperture (CPU-LSU master)."""

    _DRIVER_TAG = "MBOX"

    async def ungate_clock(self) -> None:
        cur = await self._rd(CLOCK_GATE_CTRL)
        await self._wr(CLOCK_GATE_CTRL, cur | CLOCK_GATE_IMPL_MASK)

    # --- 32-bit CSRs --------------------------------------------------------
    async def wr_csr(self, off: int, val: int) -> None:
        await self._wr(OUTBOUND_BASE + off, val)

    async def rd_csr(self, off: int) -> int:
        return await self._rd(OUTBOUND_BASE + off)

    # --- 64-bit TX FIFO push (WRITE_DATA) -----------------------------------
    async def push64(self, value: int, *, expect_error: bool = False) -> int:
        """Push one 64-bit entry via a single 8-byte WRITE_DATA beat. Returns the AXI
        resp_code; expect_error tolerates the write-to-full SLVERR (caller asserts)."""
        seq = SepAxiAccessSeq(
            "mbox_push64",
            op=SepAxiOp.WRITE,
            addr=OUTBOUND_BASE + WRITE_DATA,
            wdata=value,
            length=8,
            size=None,
            allow_unverified_write_resp=expect_error,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    # --- RX FIFO pop (READ_DATA; empty on bare-sep -> SLVERR) ---------------
    async def pop64(self, *, expect_error: bool = False) -> tuple[int, int]:
        """Pop a 64-bit entry via READ_DATA. On bare-sep the RX FIFO is empty, so this
        returns (SLVERR, 0xFEEDDEAD); expect_error tolerates that. Returns (resp, data)."""
        seq = SepAxiAccessSeq(
            "mbox_pop64",
            op=SepAxiOp.READ,
            addr=OUTBOUND_BASE + READ_DATA,
            length=8,
            size=None,
            expect_error=expect_error,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata

    async def rd_write_data(self) -> tuple[int, int]:
        """Read the write-only WRITE_DATA register. Returns (resp, data)."""
        seq = SepAxiAccessSeq(
            "mbox_rd_wdata",
            op=SepAxiOp.READ,
            addr=OUTBOUND_BASE + WRITE_DATA,
            length=8,
            size=None,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata

    # --- FIFO control -------------------------------------------------------
    async def flush_write(self) -> None:
        """CTRL.wflush (bit 0) drains the TX FIFO."""
        await self._wr(OUTBOUND_BASE + CTRL, CTRL_WFLUSH)
