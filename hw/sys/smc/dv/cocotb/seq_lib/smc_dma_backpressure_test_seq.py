# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA transfers queued behind a destination that stops answering.

The other DMA leaves launch one descriptor at a time, move at most eight bytes
and wait for it to finish, so the DMA never has more than one burst in flight,
never reads a burst longer than one beat, and never has a descriptor waiting
behind another. This leaf queues several behind a stalled destination.

The sources sit in scratchpad memory and every destination in the output-fabric
window. The bench's hold on the output responder's R and B channels is set
before the first launch, so every write the DMA issues there goes unanswered:
the DMA runs out of write credit, its realignment buffer fills from the
scratchpad reads, and the descriptors launched after that wait in the
frontend's queue. `dma_ctrl.rdl` gives `STATUS.BUSY[7:0]` as "readiness to
accept another command", so the leaf launches descriptors until that reads
clear, then launches one more, and releases the hold once that launch's read
has been accepted on SEP_IN. Every descriptor must then finish, `DONE` must
reach the last id handed out, and every destination must hold exactly its
source bytes with the bytes around it untouched.

The queue holds, in order:

* **A 64-byte copy to a destination four bytes into a word**, so the write
  side has a partial first and last beat and the read side a multi-beat burst.
* **A two-dimensional copy** of forty eight-byte rows, one burst per row,
  which is what exhausts the DMA's write credit.
* **A zero-length descriptor**, which the backend answers without a transfer.
* **A 64-byte copy whose source crosses a 4 KB boundary** and whose
  destination does not, so the read side needs two bursts where the write side
  needs one.
* **A 64-byte copy whose destination crosses a 4 KB boundary** and whose
  source does not.
* **Further 64-byte copies** until the frontend reports it cannot take more.

A last leg reads a 64-byte source from the output-fabric window with the
responder answering SLVERR on the third beat of the burst. The DMA has no
error handling configured, so the transfer must still complete; the beats the
responder answered OKAY must arrive, and the errored beat's destination bytes
are recorded.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import SPM_MEMORY_BASE
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dma_sanity_test_seq import (
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    DMA_CTRL_STATUS_0,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)

WORD = 8
PAGE = 0x1000
#: `dma_ctrl.rdl` STATUS.BUSY[7:0]: readiness to accept another command.
READY_BM = 0xFF
SRC_BASE = SPM_MEMORY_BASE + 0x8000
DST_BASE = 0x0200_6000
DST_REGION = "dma_backpressure_dst"
DST_REGION_SIZE = 0x2000
DST_POISON = 0xEE
#: Upper bound on descriptors launched before the frontend reports it is full.
MAX_LAUNCHES = 16
POLL_LIMIT = 400
POLL_CYCLES = 20

#: The error leg: a source in the output-fabric window, answered SLVERR on its
#: third beat.
ERR_SRC = DST_BASE + 0x1C00
ERR_DST = SRC_BASE + 0x4000
ERR_BEAT = 2
ERR_LEN = 64


class _Desc:
    def __init__(self, name: str, src: int, dst: int, length: int, reps: int = 1) -> None:
        self.name = name
        self.src = src
        self.dst = dst
        self.length = length
        self.reps = reps
        self.id = -1

    def spans(self) -> list[tuple[int, int, int]]:
        """(source, destination, length) of each row."""
        return [
            (self.src + r * self.length, self.dst + r * self.length, self.length)
            for r in range(self.reps)
        ]


def _pattern(addr: int) -> int:
    return ((addr * 7) ^ (addr >> 8) ^ 0x5A) & 0xFF


class smc_dma_backpressure_test_seq(SmcCsrSeq):
    """Queue DMA descriptors behind a destination whose responses are held."""

    def __init__(self, name: str = "smc_dma_backpressure_test_seq") -> None:
        super().__init__(name)
        self.launched: list[_Desc] = []
        self.refused_ready = -1
        self.checked_bytes = 0
        self.err_beat_bytes = b""

    # -- plumbing ---------------------------------------------------------

    async def _jtag(self, op: SmcSysAxiOp, addr: int, length: int, data: int = 0) -> int:
        item = SmcSysAxiItem(f"jtag_{op.value}_0x{addr:x}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        await _OneShot(item, f"jtag_{op.value}_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )
        assert item.resp_code == 0, f"JTAG {op.value} 0x{addr:08x} answered {item.resp_code}"
        return item.rdata

    async def _fill(self, base: int, length: int, value_of) -> None:
        start = base & ~(WORD - 1)
        end = (base + length + WORD - 1) & ~(WORD - 1)
        for word in range(start, end, WORD):
            value = 0
            for lane in range(WORD):
                value |= value_of(word + lane) << (8 * lane)
            await self._jtag(SmcSysAxiOp.WRITE, word, WORD, value)

    async def _bytes(self, base: int, length: int) -> bytes:
        start = base & ~(WORD - 1)
        end = (base + length + WORD - 1) & ~(WORD - 1)
        out = bytearray()
        for word in range(start, end, WORD):
            out += (await self._jtag(SmcSysAxiOp.READ, word, WORD)).to_bytes(WORD, "little")
        off = base - start
        return bytes(out[off : off + length])

    async def _pass_all(self) -> None:
        for name, addr, value in (
            ("IN_START", INBOUND0_START, 0),
            ("IN_END", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("IN_CFG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("OUT_START", OUTBOUND0_START, 0),
            ("OUT_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"PASS_{name}", addr, value, length=8)

    async def _program(self, d: _Desc) -> None:
        stride = d.length if d.reps > 1 else 0
        for reg, value in (
            (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            (DMA_CTRL_DST_ADDRESS_LO, d.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, d.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, d.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, d.src >> 32),
            (DMA_CTRL_LENGTH_LO, d.length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, stride),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, stride),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, d.reps),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{d.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, d: _Desc) -> None:
        # Reading NEXT_ID is what launches the programmed descriptor.
        d.id = await self.csr_read(f"{d.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        self.launched.append(d)

    async def _ready(self, label: str) -> int:
        return (await self.csr_read(f"{label}_STATUS", DMA_CTRL_STATUS_0)) & READY_BM

    async def _release_on_ar(self) -> None:
        """Release the responder hold once the refused launch's read is on SEP_IN."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            if int(dut.s_axi_arvalid.value) and int(dut.s_axi_arready.value):
                break
        await FallingEdge(dut.clk_smc_i)
        dut.tb_output_axi_resp_hold.value = 0

    async def _await_done(self, want: int) -> int:
        done = 0
        for _ in range(POLL_LIMIT):
            done = await self.csr_read("DONE_POLL", DMA_CTRL_DONE_0)
            if done >= want:
                return done
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"DONE reached {done}, not the last launched id {want}")

    # -- legs -------------------------------------------------------------

    def _queue(self) -> list[_Desc]:
        rows = 40
        queue = [
            _Desc("UNALIGNED", SRC_BASE, DST_BASE + 4, 64),
            _Desc("ROWS", SRC_BASE + 0x100, DST_BASE + 0x100, WORD, rows),
            _Desc("ZERO", SRC_BASE + 0x400, DST_BASE + 0x400, 0),
            _Desc("SRC_PAGE", SRC_BASE + PAGE - 0x20, DST_BASE + 0x500, 64),
            _Desc("DST_PAGE", SRC_BASE + 0x1100, DST_BASE + PAGE - 0x20, 64),
        ]
        for i in range(MAX_LAUNCHES - len(queue)):
            queue.append(
                _Desc(f"FILL{i}", SRC_BASE + 0x1200 + i * 0x50, DST_BASE + 0x1100 + i * 0x50, 64)
            )
        return queue

    async def _backpressure_leg(self) -> None:
        dut = cocotb.top
        queue = self._queue()
        for d in queue:
            for src, _dst, length in d.spans():
                if length:
                    await self._fill(src, length, _pattern)
        if DST_REGION not in self.memory_model.regions:
            self.memory_model.add_region(DST_REGION, DST_BASE, DST_REGION_SIZE)
        for d in queue:
            total = d.length * d.reps
            if total:
                await self._fill(d.dst - WORD, total + 2 * WORD, lambda _a: DST_POISON)
        base_done = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        assert await self._ready("IDLE") == READY_BM, "the DMA frontend is not ready at idle"

        dut.tb_output_axi_resp_hold.value = 1
        refused = None
        try:
            for d in queue:
                await self._program(d)
                if await self._ready(d.name) == 0:
                    refused = d
                    break
                await self._launch(d)
            assert refused is not None, (
                f"STATUS.BUSY kept reporting readiness through {len(queue)} launches with the "
                f"destination's responses held"
            )
            self.refused_ready = 0
            releaser = cocotb.start_soon(self._release_on_ar())
            await self._launch(refused)
            await releaser
        finally:
            dut.tb_output_axi_resp_hold.value = 0

        last = self.launched[-1].id
        ids = [d.id for d in self.launched]
        assert ids == list(range(ids[0], ids[0] + len(ids))), f"NEXT_ID handed out {ids}"
        assert ids[0] == base_done + 1, f"first id {ids[0]} after DONE {base_done}"
        await self._await_done(last)
        for d in self.launched:
            total = d.length * d.reps
            if not total:
                continue
            got = await self._bytes(d.dst - 4, total + 8)
            want = bytes([DST_POISON] * 4)
            for src, _dst, length in d.spans():
                want += bytes(_pattern(src + i) for i in range(length))
            want += bytes([DST_POISON] * 4)
            assert got == want, (
                f"{d.name}: destination 0x{d.dst:08x} and the four bytes either side hold "
                f"{got.hex()}, expected {want.hex()}"
            )
            self.checked_bytes += total

    async def _error_leg(self) -> None:
        sys_out = self.cfg.sys_out_mem
        assert sys_out is not None, "SYS_OUT responder not bound"
        await self._fill(ERR_SRC, ERR_LEN, _pattern)
        await self._fill(ERR_DST, ERR_LEN, lambda _a: DST_POISON)
        monitor = self.env.output_axi_monitor
        slverr_before = monitor.snapshot()["r_slverr"]
        monitor.allow_slverr = True
        sys_out.inject_error(ERR_SRC + ERR_BEAT * WORD, 2, write=False)
        base_done = await self.csr_read("ERR_DONE_BASE", DMA_CTRL_DONE_0)
        d = _Desc("ERRSRC", ERR_SRC, ERR_DST, ERR_LEN)
        await self._program(d)
        await self._launch(d)
        assert d.id == base_done + 1, f"ERRSRC: id {d.id} after DONE {base_done}"
        await self._await_done(d.id)
        slverr = monitor.snapshot()["r_slverr"] - slverr_before
        monitor.allow_slverr = False
        assert slverr == 1, (
            f"ERRSRC: the output responder answered {slverr} read beats SLVERR, not the one "
            f"injected"
        )
        got = await self._bytes(ERR_DST, ERR_LEN)
        want = bytes(_pattern(ERR_SRC + i) for i in range(ERR_LEN))
        lo, hi = ERR_BEAT * WORD, (ERR_BEAT + 1) * WORD
        assert got[:lo] == want[:lo] and got[hi:] == want[hi:], (
            f"ERRSRC: beats answered OKAY did not arrive intact: {got.hex()} vs {want.hex()}"
        )
        self.err_beat_bytes = got[lo:hi]

    async def body(self) -> None:
        await self._pass_all()
        await self._backpressure_leg()
        cocotb.log.info(
            "CHK-DMA-BACKPRESSURE: with the output responder's responses held, %d descriptors "
            "were launched before STATUS.BUSY reported no readiness; one more was launched and "
            "the hold released once its read reached SEP_IN; every descriptor completed, DONE "
            "reached id %d, and %d destination bytes matched their sources",
            len(self.launched) - 1,
            self.launched[-1].id,
            self.checked_bytes,
        )
        await self._error_leg()
        cocotb.log.info(
            "CHK-DMA-READ-ERROR-BEAT: a 64-byte read answered SLVERR on beat %d (from 0) still completed; "
            "the other beats arrived intact and the errored beat's destination holds %s",
            ERR_BEAT,
            self.err_beat_bytes.hex(),
        )
