# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA transfers with the read and write channels decoupled, and two queued.

`CONFIG.DECOUPLE_RW` has never been written. Every DMA leaf leaves it at its
reset, so the backend's legalizer has only ever run its coupled arm, where the
read and the write machine advance together; the decoupled arm, where either
may advance alone, has never been entered. Nothing has queued a second
descriptor while the legalizer was still busy either.

This leaf does both, and takes its golden for the field from the generated
header rather than the RTL: `dma_ctrl.h` gives
`DMA_CTRL__CONFIG__DECOUPLE_RW_bm` the value `0x2` and its reset `0x0`, and the
field is `sw = rw` in `dma_ctrl.rdl`, so it reads back what is written and the
sequence requires that before running anything through it.

**Two transfers whose channels have different work to do.** Decoupling only
shows if the two sides are not in step, so each transfer is two-dimensional
with a stride on one side only:

* a **scatter**, where the source rows are contiguous and the destination rows
  are a stride apart, so the read side issues one long run and the write side
  many short ones;
* a **gather**, the other way round, so the fragmented side is the read.

Both move the same four rows and every row is compared against its source, so a
transfer that dropped, duplicated or misplaced a row fails rather than passing
quietly.

**Two descriptors back to back.** `dma_ctrl.rdl` says of `NEXT_ID` that
"Reading this register starts the DMA transfer. Returns an ID value for the
cumulative number of transfers. Returns 0 if command was not set up correctly",
and of `DONE` that it "Holds the cumulative number of completed transfers". So
the second descriptor is programmed and submitted without waiting for the
first, and the sequence requires both ids non-zero and rising, `DONE` to have
advanced by two, and both destinations to hold their own payload.

**Transfers into a stalled SYS_OUT.** The backend's legalizer gates every
request it issues on the read and write request readies. Those readies come
back from SYS_OUT through the AR register, the coupler's AW store and the data
FIFOs. A responder that is always ready leaves them high. The SYS_OUT
responder's `enable_backpressure` holds READY low in bounded repeating windows.

Each backpressured transfer is a 128-row 2D request of single-beat rows, since
`CONFIG.ENABLE_ND` is set, so there are more requests than the path to SYS_OUT
holds. The nine transfers stall the read side, the write side and both, in
three modes: coupled, with the read and write channels decoupled, and with the
channel coupler sending each AW without waiting for its first read beat
(`CONFIG.DECOUPLE_AW`).

The bench counts cycles at the SYS_OUT boundary where VALID is high and READY
is low, and requires a count for every stalled channel. Every row of every
transfer is compared against its source, and each transfer carries its own
payload.

**Rows split at a page on one side only.** AXI bursts may not cross a 4 KB
page, so the legalizer splits a row that does. Two 256-byte rows cross a page
on one side only -- first the source, then the destination -- so one machine
has two bursts to issue while the other has one. Both must arrive intact.

`CONFIG` is restored to its reset and read back at the end. The leaf writes no
other DMA field and touches no fuse.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    DMA_CONFIG_DECOUPLE_AW,
    DMA_CONFIG_DECOUPLE_RW,
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
)
from .smc_csr_seq_utils import SmcCsrSeq

_MODEL_REGION = "dma_decouple_rw"
_MODEL_BASE = 0x0200_0000
_MODEL_SIZE = 0x8000

# Four distinct rows of one bus word each, so a row that landed at the wrong
# stride or was dropped shows up as the wrong content rather than as nothing.
_ROWS = (
    bytes.fromhex("1122334455667788"),
    bytes.fromhex("99AABBCCDDEEFF00"),
    bytes.fromhex("0F1E2D3C4B5A6978"),
    bytes.fromhex("F0E1D2C3B4A59687"),
)
_ROW_BYTES = len(_ROWS[0])
_GAP = 0x40

# Scatter: contiguous source rows, destination rows a gap apart.
_SCATTER_SRC = _MODEL_BASE + 0x0000
_SCATTER_DST = _MODEL_BASE + 0x1000
# Gather: source rows a gap apart, contiguous destination rows.
_GATHER_SRC = _MODEL_BASE + 0x2000
_GATHER_DST = _MODEL_BASE + 0x3000
# The two queued descriptors, one row each.
_QUEUE_SRC = (_MODEL_BASE + 0x4000, _MODEL_BASE + 0x4100)
_QUEUE_DST = (_MODEL_BASE + 0x5000, _MODEL_BASE + 0x5100)

_SENTINEL = bytes.fromhex("5A5A5A5A5A5A5A5A")
_DONE_POLLS = 80

# Backpressured transfers: 128 rows of one bus word each, so each transfer is
# 128 single-beat bursts per side, against a responder that takes one beat in
# 65 cycles. That is more requests than the backend and the fabric between it
# and SYS_OUT can hold, so the stall reaches the legalizer's request readies
# instead of being absorbed on the way. The rows are seeded and compared in the
# responder's memory directly: over JTAG they would cost more than the transfers.
_BP_ROW_BYTES = _ROW_BYTES
_BP_ROWS = 128
_BP_GAP = 0x10
_BP_SRC = _MODEL_BASE + 0x6000
_BP_DST = _MODEL_BASE + 0x8000
_BP_STALL_CYCLES = 64
_BP_DONE_POLLS = 1000
# Page-split rows: 256 bytes, one side starting 128 bytes below a 4 KB page.
_SPLIT_BYTES = 0x100
_SPLIT_SRC_CROSS = _MODEL_BASE + 0xA000 - 0x80
_SPLIT_DST_FLAT = _MODEL_BASE + 0xB000
_SPLIT_SRC_FLAT = _MODEL_BASE + 0xC000
_SPLIT_DST_CROSS = _MODEL_BASE + 0xE000 - 0x80

# (mode, CONFIG) for the backpressured transfers. DECOUPLE_AW lets the channel
# coupler send each AW without waiting for the first read beat of its burst.
_BP_MODES = (
    ("COUPLED", DMA_CONFIG_ENABLED_ND),
    ("DECOUPLED", DMA_CONFIG_ENABLED_ND | DMA_CONFIG_DECOUPLE_RW),
    ("DECOUPLED_AW", DMA_CONFIG_ENABLED_ND | DMA_CONFIG_DECOUPLE_AW),
)
# (label, responder channels held not-ready). "ar" stalls the read requests;
# "aw" and "w" stall the write requests and their data.
_BP_CASES = (
    ("READ", ("ar",)),
    ("WRITE", ("aw", "w")),
    ("BOTH", ("ar", "aw", "w")),
)

# CSR accesses one descriptor costs: the CONFIG write, twelve descriptor
# writes, the NEXT_ID read that submits it and at least one DONE poll.
_ACCESSES_PER_DESCRIPTOR = 16


class _StallWatch:
    """Count SYS_OUT cycles with VALID high and READY low, per address channel."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stalls = {"ar": 0, "aw": 0, "w": 0}
        self._task = cocotb.start_soon(self._run())

    def _bit(self, name: str) -> int:
        value = getattr(self.dut, name).value
        return int(value) if value.is_resolvable else 0

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            for channel in self.stalls:
                valid = self._bit(f"tb_output_axi_{channel}valid")
                ready = self._bit(f"tb_output_axi_{channel}ready")
                if valid and not ready:
                    self.stalls[channel] += 1

    def stop(self) -> dict[str, int]:
        self._task.cancel()
        return dict(self.stalls)


def _bp_rows(transfer: int) -> tuple[bytes, ...]:
    """Distinct rows that name their transfer and index, so none can stand in for another."""
    return tuple(
        (0xB0_00_5EED_0000_0000 | (transfer << 48) | (row << 8) | (row ^ 0xA5)).to_bytes(
            _BP_ROW_BYTES, "little"
        )
        for row in range(_BP_ROWS)
    )


class smc_dma_decouple_rw_test_seq(SmcCsrSeq):
    """Run decoupled read/write DMA transfers and two queued descriptors."""

    def __init__(self, name: str = "smc_dma_decouple_rw_test_seq") -> None:
        super().__init__(name)
        self.decoupled_transfers = 0
        self.rows_checked = 0
        self.queued = 0
        self.backpressured: list[tuple[str, dict[str, int]]] = []
        self.page_splits = 0

    # -- primitives ------------------------------------------------------

    async def _jtag(
        self, op: SmcSysAxiOp, addr: int, *, data: bytes | None = None
    ) -> SmcSysAxiItem:
        assert self.env is not None, "sequence env is not initialized"
        item = SmcSysAxiItem(f"dma_decouple_{op.value}_0x{addr:x}")
        item.op = op
        item.addr = addr
        item.length = _ROW_BYTES if data is None else len(data)
        if data is not None:
            item.wdata = int.from_bytes(data, "little")
        item.memory_region = _MODEL_REGION
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        return item

    async def _seed(self, base: int, stride: int, rows: tuple[bytes, ...]) -> None:
        for index, row in enumerate(rows):
            await self._jtag(SmcSysAxiOp.WRITE, base + index * stride, data=row)

    async def _check_rows(self, base: int, stride: int, rows: tuple[bytes, ...], tag: str) -> None:
        for index, row in enumerate(rows):
            addr = base + index * stride
            got = await self._jtag(SmcSysAxiOp.READ, addr)
            assert got.rdata.to_bytes(_ROW_BYTES, "little") == row, (
                f"[{tag}] row {index} at 0x{addr:x} holds "
                f"0x{got.rdata:0{2 * _ROW_BYTES}x}, the source row is "
                f"0x{int.from_bytes(row, 'little'):0{2 * _ROW_BYTES}x}"
            )
            self.rows_checked += 1

    async def _program(
        self,
        tag: str,
        *,
        src: int,
        dst: int,
        src_stride: int,
        dst_stride: int,
        rows: int,
        length: int = _ROW_BYTES,
    ) -> None:
        for name, addr, value in (
            ("DST_LO", DMA_CTRL_DST_ADDRESS_LO, dst & 0xFFFF_FFFF),
            ("DST_HI", DMA_CTRL_DST_ADDRESS_HI, dst >> 32),
            ("SRC_LO", DMA_CTRL_SRC_ADDRESS_LO, src & 0xFFFF_FFFF),
            ("SRC_HI", DMA_CTRL_SRC_ADDRESS_HI, src >> 32),
            ("LEN_LO", DMA_CTRL_LENGTH_LO, length),
            ("LEN_HI", DMA_CTRL_LENGTH_HI, 0),
            ("DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, dst_stride),
            ("DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0),
            ("SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, src_stride),
            ("SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0),
            ("REPS_LO", DMA_CTRL_NUM_REPETITIONS_LO, rows),
            ("REPS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"DMA_{name}_{tag}", addr, value)

    async def _submit(self, tag: str) -> int:
        """Reading NEXT_ID starts the transfer; 0 means it was not set up."""
        transfer_id = await self.csr_read(f"DMA_NEXT_ID_{tag}", DMA_CTRL_NEXT_ID_0)
        assert transfer_id != 0, (
            f"[{tag}] NEXT_ID returned 0; dma_ctrl.rdl gives that value the meaning "
            f"'command was not set up correctly', so the descriptor was rejected"
        )
        return transfer_id

    async def _await_done(self, target: int, tag: str, polls: int = _DONE_POLLS) -> None:
        for _ in range(polls):
            done = await self.csr_read(f"DMA_DONE_{tag}", DMA_CTRL_DONE_0)
            if done >= target:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read(f"DMA_STATUS_{tag}", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"[{tag}] DONE never reached {target} in {polls} polls; STATUS reads 0x{status:x}"
        )

    # -- legs ------------------------------------------------------------

    async def _decoupled_transfer(
        self, tag: str, *, src: int, dst: int, src_stride: int, dst_stride: int
    ) -> None:
        await self._seed(src, src_stride, _ROWS)
        await self._seed(dst, dst_stride, tuple(_SENTINEL for _ in _ROWS))
        baseline = await self.csr_read(f"DMA_DONE_BASE_{tag}", DMA_CTRL_DONE_0)
        await self.csr_write(
            f"DMA_CONFIG_{tag}", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND | DMA_CONFIG_DECOUPLE_RW
        )
        held = await self.csr_read(f"DMA_CONFIG_RB_{tag}", DMA_CTRL_CONFIG)
        assert held & DMA_CONFIG_DECOUPLE_RW, (
            f"[{tag}] CONFIG reads 0x{held:x} after a write that set DECOUPLE_RW "
            f"(0x{DMA_CONFIG_DECOUPLE_RW:x}); dma_ctrl.rdl makes the field `sw = rw`, so "
            f"it has to read back"
        )
        await self._program(
            tag, src=src, dst=dst, src_stride=src_stride, dst_stride=dst_stride, rows=len(_ROWS)
        )
        await self._submit(tag)
        await self._await_done(baseline + 1, tag)
        await self._check_rows(dst, dst_stride, _ROWS, tag)
        self.decoupled_transfers += 1

    async def _queued_descriptors(self) -> None:
        """The second descriptor is offered while the first is still in flight."""
        for src, dst, row in zip(_QUEUE_SRC, _QUEUE_DST, _ROWS):
            await self._jtag(SmcSysAxiOp.WRITE, src, data=row)
            await self._jtag(SmcSysAxiOp.WRITE, dst, data=_SENTINEL)
        baseline = await self.csr_read("DMA_DONE_BASE_QUEUE", DMA_CTRL_DONE_0)

        await self._program(
            "QUEUE0", src=_QUEUE_SRC[0], dst=_QUEUE_DST[0], src_stride=0, dst_stride=0, rows=1
        )
        first = await self._submit("QUEUE0")
        # No wait here: the second descriptor is programmed and offered while
        # the first is still being legalized.
        await self._program(
            "QUEUE1", src=_QUEUE_SRC[1], dst=_QUEUE_DST[1], src_stride=0, dst_stride=0, rows=1
        )
        second = await self._submit("QUEUE1")
        assert second > first, (
            f"the second descriptor was given id {second} and the first {first}; NEXT_ID "
            f"returns the cumulative number of transfers, so the second has to be higher"
        )
        await self._await_done(baseline + 2, "QUEUE")
        for index, (dst, row) in enumerate(zip(_QUEUE_DST, _ROWS)):
            got = await self._jtag(SmcSysAxiOp.READ, dst)
            assert got.rdata.to_bytes(_ROW_BYTES, "little") == row, (
                f"queued descriptor {index} left 0x{dst:x} holding "
                f"0x{got.rdata:0{2 * _ROW_BYTES}x} instead of its own payload"
            )
            self.rows_checked += 1
        self.queued = 2

    async def _backpressured_transfer(
        self, tag: str, transfer: int, channels: tuple[str, ...], config: int
    ) -> None:
        rows = _bp_rows(transfer)
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        for index, row in enumerate(rows):
            responder.write(_BP_SRC + index * _BP_ROW_BYTES, row)
            responder.write(_BP_DST + index * _BP_GAP, _SENTINEL)
        baseline = await self.csr_read(f"DMA_DONE_BASE_{tag}", DMA_CTRL_DONE_0)
        await self.csr_write(f"DMA_CONFIG_{tag}", DMA_CTRL_CONFIG, config)
        await self.csr_read(f"DMA_CONFIG_RB_{tag}", DMA_CTRL_CONFIG, expected=config)
        await self._program(
            tag,
            src=_BP_SRC,
            dst=_BP_DST,
            src_stride=_BP_ROW_BYTES,
            dst_stride=_BP_GAP,
            rows=_BP_ROWS,
            length=_BP_ROW_BYTES,
        )
        watch = _StallWatch(cocotb.top)
        responder.enable_backpressure(channels=channels, stall_cycles=_BP_STALL_CYCLES)
        try:
            await self._submit(tag)
            await self._await_done(baseline + 1, tag, polls=_BP_DONE_POLLS)
        finally:
            responder.disable_backpressure()
            stalls = watch.stop()
        for channel in channels:
            assert stalls[channel] > 0, (
                f"[{tag}] no SYS_OUT cycle had {channel.upper()}VALID high with "
                f"{channel.upper()}READY low while the responder held that channel's "
                f"READY in stall windows; the transfer never met backpressure ({stalls})"
            )
        for index, row in enumerate(rows):
            addr = _BP_DST + index * _BP_GAP
            got = responder.read(addr, _BP_ROW_BYTES)
            assert got == row, (
                f"[{tag}] row {index} at 0x{addr:x} holds 0x{got[::-1].hex()}, the source "
                f"row is 0x{row[::-1].hex()}"
            )
            self.rows_checked += 1
        self.backpressured.append((tag, stalls))

    async def _page_split_transfer(self, tag: str, src: int, dst: int) -> None:
        """One row whose source and destination cross a 4 KB page at different points."""
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        payload = bytes((0x3D + 7 * i) & 0xFF for i in range(_SPLIT_BYTES))
        responder.write(src, payload)
        responder.write(dst, bytes(_SPLIT_BYTES))
        baseline = await self.csr_read(f"DMA_DONE_BASE_{tag}", DMA_CTRL_DONE_0)
        await self.csr_write(f"DMA_CONFIG_{tag}", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        await self._program(
            tag, src=src, dst=dst, src_stride=0, dst_stride=0, rows=1, length=_SPLIT_BYTES
        )
        await self._submit(tag)
        await self._await_done(baseline + 1, tag)
        got = responder.read(dst, _SPLIT_BYTES)
        assert got == payload, (
            f"[{tag}] {_SPLIT_BYTES} bytes from 0x{src:x} to 0x{dst:x}: the destination "
            f"differs from the source at byte {next(i for i in range(_SPLIT_BYTES) if got[i] != payload[i])}"
        )
        self.page_splits += 1

    async def _backpressured_transfers(self) -> None:
        transfer = 0
        for mode, config in _BP_MODES:
            for label, channels in _BP_CASES:
                await self._backpressured_transfer(f"BP_{mode}_{label}", transfer, channels, config)
                transfer += 1

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        if _MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(_MODEL_REGION, _MODEL_BASE, _MODEL_SIZE)
        assert len(set(_ROWS)) == len(_ROWS), "the payload rows are not distinct"
        assert _SENTINEL not in _ROWS, "the sentinel is one of the payload rows"

        idle = await self.csr_read("DMA_CONFIG_IDLE", DMA_CTRL_CONFIG)
        assert idle & DMA_CONFIG_DECOUPLE_RW == 0, (
            f"CONFIG reads 0x{idle:x} before this leaf wrote it, with DECOUPLE_RW already "
            f"set; dma_ctrl.h gives that field the reset 0x0, so the transfers below "
            f"would not be the first to decouple the channels"
        )

        await self._decoupled_transfer(
            "SCATTER",
            src=_SCATTER_SRC,
            dst=_SCATTER_DST,
            src_stride=_ROW_BYTES,
            dst_stride=_GAP,
        )
        await self._decoupled_transfer(
            "GATHER",
            src=_GATHER_SRC,
            dst=_GATHER_DST,
            src_stride=_GAP,
            dst_stride=_ROW_BYTES,
        )
        await self._queued_descriptors()
        await self._backpressured_transfers()
        # AXI bursts may not cross a 4 KB page, so a row whose source crosses one
        # and whose destination does not is two read bursts against one write
        # burst, and the other way round.
        await self._page_split_transfer("SPLIT_SRC", _SPLIT_SRC_CROSS, _SPLIT_DST_FLAT)
        await self._page_split_transfer("SPLIT_DST", _SPLIT_SRC_FLAT, _SPLIT_DST_CROSS)

        await self.csr_write("DMA_CONFIG_RESTORE", DMA_CTRL_CONFIG, 0)
        restored = await self.csr_read("DMA_CONFIG_RESTORE_RB", DMA_CTRL_CONFIG, expected=0)
        assert restored == 0, (
            f"CONFIG reads 0x{restored:x} after being restored; dma_ctrl.h gives every "
            f"field of it the reset 0"
        )

        assert self.decoupled_transfers == 2, (
            f"{self.decoupled_transfers} decoupled transfers, the leaf runs a scatter and a gather"
        )
        assert self.queued == 2, f"{self.queued} queued descriptors, the leaf submits two"
        assert len(self.backpressured) == len(_BP_MODES) * len(_BP_CASES), (
            f"{len(self.backpressured)} backpressured transfers, the leaf runs {len(_BP_MODES) * len(_BP_CASES)}"
        )
        expected_rows = 2 * len(_ROWS) + 2 + len(_BP_MODES) * len(_BP_CASES) * _BP_ROWS
        assert self.rows_checked == expected_rows, (
            f"{self.rows_checked} rows compared, {expected_rows} were moved"
        )
        assert self.page_splits == 2, f"{self.page_splits} page-split transfers, the leaf runs 2"
        floor = (6 + len(_BP_MODES) * len(_BP_CASES)) * _ACCESSES_PER_DESCRIPTOR
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; its descriptors cannot "
            f"have issued fewer than {floor}"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        cocotb.log.info(
            "CHK-DMA-DECOUPLE-RW: CONFIG.DECOUPLE_RW read back set from the mask "
            "dma_ctrl.h gives it, and %d transfers ran with the read and write channels "
            "decoupled -- a scatter whose write side was the fragmented one and a gather "
            "whose read side was -- with all %d rows of each landing where their stride "
            "puts them and matching their source; CONFIG was restored to its reset and "
            "read back",
            self.decoupled_transfers,
            len(_ROWS),
        )
        cocotb.log.info(
            "CHK-DMA-QUEUED-DESCRIPTORS: a second descriptor was programmed and submitted "
            "without waiting for the first, both NEXT_ID reads returned a non-zero and "
            "rising id rather than the 0 dma_ctrl.rdl gives a rejected command, DONE "
            "advanced by %d, and each destination held its own payload",
            self.queued,
        )
        cocotb.log.info(
            "CHK-DMA-PAGE-SPLIT: a 256-byte row whose source crossed a 4 KB page and "
            "whose destination did not, and one the other way round, each arrived intact"
        )
        cocotb.log.info(
            "CHK-DMA-LEGALIZER-BACKPRESSURE: %d multi-row 2D transfers ran with the SYS_OUT "
            "responder holding READY low in %d-cycle windows -- read side, write side and "
            "both, coupled, decoupled and with DECOUPLE_AW -- each stalled channel showed "
            "VALID high with "
            "READY low at the boundary, and every row of each transfer matched its own "
            "source (stall cycles ar/aw/w: %s)",
            len(self.backpressured),
            _BP_STALL_CYCLES,
            "; ".join(f"{tag}={st['ar']}/{st['aw']}/{st['w']}" for tag, st in self.backpressured),
        )
