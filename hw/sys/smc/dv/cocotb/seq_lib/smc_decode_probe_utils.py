# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SEP_IN AXI decode probes for the address-map testcases.

Three probe shapes, each fail-capable on its own:

* ``read_reset`` -- an exact compare of a register against its generated
  reset value. Only registers whose reset is non-zero, or which sit next to a
  non-zero one, carry decode evidence: a dead or unmapped window commonly reads
  0, so a 0 == 0 compare alone cannot tell "decoded" from "absent".
* ``rw_coresident`` -- distinct patterns written to several addresses and read
  back only after all of them are resident, so two windows aliased onto one
  physical register return a neighbour's pattern and fail the exact compare.
  A per-address write-then-read cannot see that aliasing.
* ``write_expect_error`` -- a write to a region the specification declares
  read-only. The scoreboard enforces an error response and a non-wedge, so a
  write that is quietly accepted fails.
* ``read_decerr`` -- an access that must be answered by the fabric error slave
  (``fabric.adoc`` Traffic Subordinates: "Error Slave -- invalid address
  response generation"). The scoreboard enforces both the error response and
  the exact DECERR code; an OKAY or a wedge fails.

``read_external_routed`` and ``write_external_routed`` additionally watch the
adopter external AXI-Lite port while the access is in flight and credit only a
request on the matching channel carrying the probed address, so the decode is
proven at the consumer rather than inferred from the response or from port
activity alone.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3

# The probed word inside the adopter external window: the port may carry the
# full local address or the window offset, so both are compared on the window
# bits above the byte lane.
_EXTERNAL_WORD_MASK = (smc_addr("SMC_TOP_SMC_EXTERNAL_SIZE") - 1) & ~0x3

# Cycles the external-window activity sampler keeps running after the access
# completes, so a request that is still being drained is not missed.
_EXTERNAL_DRAIN_CYCLES = 8


class SmcDecodeProbeSeq(SmcCsrSeq):
    """CSR sequence base with the three decode probe shapes and a cell ledger."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        # Coverage cell -> the measured evidence that closed it. A cell is
        # entered only after its compare passed; the testcase-level report
        # prints the ledger so the kept log names what each cell rests on.
        self.cells: dict[str, str] = {}
        # Cells this bench cannot drive, with the reason. Reported, never
        # counted as closed.
        self.unreachable: dict[str, str] = {}

    def close_cell(self, cell: str, evidence: str) -> None:
        assert cell not in self.cells, f"coverage cell {cell!r} closed twice"
        self.cells[cell] = evidence

    def leave_open(self, cell: str, reason: str) -> None:
        assert cell not in self.unreachable, f"cell {cell!r} declared unreachable twice"
        self.unreachable[cell] = reason

    async def read_reset(self, label: str, addr: int, expected: int, length: int = 4) -> int:
        """Exact-compare ``addr`` against its generated reset; scoreboard verdict."""
        got = await self.csr_read(label, addr, expected=expected, length=length)
        return got & ((1 << (length * 8)) - 1)

    async def read_decerr(self, label: str, addr: int, length: int = 4) -> int:
        """Read an address no block declares; the error slave must answer DECERR."""
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_DECERR
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_DECERR, (
            f"{label} @ 0x{addr:08x}: expected DECERR from the error slave, got "
            f"resp={item.resp_code} rdata=0x{item.rdata:x}"
        )
        return item.rdata

    async def write_expect_error(self, label: str, addr: int, data: int, length: int = 4) -> int:
        """Write an address the specification makes read-only; it must be refused.

        The scoreboard enforces both that the access returned an error response
        and that it did not wedge, so an accepted write fails here.
        """
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        item.allow_error = True
        item.expect_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{label} @ 0x{addr:08x}: a write to a read-only region was answered "
            f"resp={item.resp_code}, expected SLVERR/DECERR"
        )
        return item.resp_code

    async def read_any(self, label: str, addr: int, length: int = 4) -> tuple[int, int]:
        """Read tolerating an error response; returns ``(resp_code, rdata)``."""
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.resp_code, item.rdata

    async def _count_external_requests(self, addr: int, channel: str, body) -> int:
        """Run ``body`` and count external-port requests that carry ``addr``.

        A cycle counts only when the adopter external port presents a request
        on ``channel`` ("ar" or "aw") whose address falls on the probed word
        within the external window, so activity from another master or at
        another address does not credit the probe.
        """
        dut = cocotb.top
        valid = getattr(dut, f"tb_axil_external_{channel}valid")
        port_addr = getattr(dut, f"tb_axil_external_{channel}addr")
        want = addr & _EXTERNAL_WORD_MASK
        hits = [0]

        async def _sample() -> None:
            while True:
                await RisingEdge(dut.clk_smc_i)
                v, a = valid.value, port_addr.value
                if v.is_resolvable and int(v) and a.is_resolvable:
                    if int(a) & _EXTERNAL_WORD_MASK == want:
                        hits[0] += 1

        sampler = cocotb.start_soon(_sample())
        try:
            await body()
            await ClockCycles(dut.clk_smc_i, _EXTERNAL_DRAIN_CYCLES)
        finally:
            sampler.cancel()
        return hits[0]

    async def read_external_routed(
        self,
        label: str,
        addr: int,
        *,
        expected: int | None = None,
        decerr: bool = False,
        length: int = 4,
    ) -> tuple[int, int]:
        """Read into the adopter external window and prove the port carried it.

        Returns ``(rdata, request_cycles)`` where ``request_cycles`` is the
        number of ``clk_smc_i`` edges at which the external port presented a
        read request for ``addr``; zero fails, because then the address was
        answered by something other than the external AXI-Lite port.
        """
        result = [0]

        async def _read() -> None:
            if decerr:
                result[0] = await self.read_decerr(label, addr, length=length)
            else:
                result[0] = await self.csr_read(label, addr, expected=expected, length=length)

        hits = await self._count_external_requests(addr, "ar", _read)
        assert hits > 0, (
            f"{label} @ 0x{addr:08x}: the adopter external AXI-Lite port never presented a "
            f"read request for this address while the access was in flight, so it was not "
            f"routed there"
        )
        return result[0] & ((1 << (length * 8)) - 1), hits

    async def write_external_routed(
        self, label: str, addr: int, data: int, *, length: int = 4
    ) -> tuple[int, int]:
        """Write into the adopter external window, expecting a refusal, and prove routing.

        Returns ``(resp_code, request_cycles)``; the write must answer an error
        and the external port must present a write request for ``addr``.
        """
        result = [0]

        async def _write() -> None:
            result[0] = await self.write_expect_error(label, addr, data, length=length)

        hits = await self._count_external_requests(addr, "aw", _write)
        assert hits > 0, (
            f"{label} @ 0x{addr:08x}: the adopter external AXI-Lite port never presented a "
            f"write request for this address while the access was in flight, so it was not "
            f"routed there"
        )
        return result[0], hits

    def report_cells(self, token: str) -> None:
        """Emit the cell ledger; every closed cell names its measured evidence."""
        assert self.cells, f"{token}: no coverage cell was closed"
        for cell, evidence in sorted(self.cells.items()):
            cocotb.log.info("%s cell=%s closed: %s", token, cell, evidence)
        for cell, reason in sorted(self.unreachable.items()):
            cocotb.log.info("%s cell=%s NOT closed in this bench: %s", token, cell, reason)
