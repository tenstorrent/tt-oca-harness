# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0: raw ATB beat capture, readout through TELEMETRY_DATA, and flushes.

The receiver stores each accepted ATB beat as ``{atid, atdata}`` in a FIFO.
One read of ``TELEMETRY_DATA`` returns the oldest beat with ``VALID`` set and
removes it; a read of an empty FIFO returns ``0x0000_0000`` and removes nothing
(``telemetry_receiver.rdl`` TELEMETRY_DATA). A full FIFO holds the source off
rather than dropping or overwriting a beat, ``CTRL.TELEMETRY_RX_FLUSH`` discards
what is queued, ``INTR_STATUS.BUFFER_THRESHOLD`` counts beats, and
``CTRL.TELEMETRY_TX_FLUSH`` can finish only while firmware makes room.

No ``(atid, data)`` beat appears in two checks, so a beat left behind by one
check, or one read twice, fails the next compare.

``_HeldSource`` drives the ATB pins. It keeps ``atvalid`` up for as long as
``atready`` is low and samples ``atready`` mid-cycle, so a beat is counted once
however long it waits.

The receiver stores ``BUFFER_DEPTH`` beats and the wrapper's ATB crossing FIFO
holds ``ATB_CROSSING_DEPTH`` more, so ``HELD_CAPACITY`` beats are accepted at
the pins before ``atready_o`` drops.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, TELEMETRY_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_TELEMETRY_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)

RX = 0


def _tel(symbol: str) -> int:
    """Field mask / position / reset value from generated ``telemetry_receiver.h``."""
    return _field_mask(_TELEMETRY_H, symbol)


def _rx_addr(register: str, rx: int = RX) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{register}_BASE_ADDR", rx
    )


CTRL = _rx_addr("CTRL")
STATUS = _rx_addr("STATUS")
INTR_STATUS = _rx_addr("INTR_STATUS")
INTR_ENABLE = _rx_addr("INTR_ENABLE")
TELEMETRY_DATA = _rx_addr("TELEMETRY_DATA")
RX_BASE = smc_indexed_addr("SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR", RX)
RX_MAP_SIZE = smc_addr("SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_SIZE")
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

RX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
TX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_TX_FLUSH_bm")
THRESHOLD_BP = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
BUFFER_EMPTY_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
BUFFER_FULL_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_FULL_bm")
INTR_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
ENABLE_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__BUFFER_THRESHOLD_bm")
DATA_BM = _tel("TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_bm")
DATA_BP = _tel("TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_bp")
ATID_BM = _tel("TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_bm")
ATID_BP = _tel("TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_bp")
VALID_BM = _tel("TELEMETRY_RECEIVER__TELEMETRY_DATA__VALID_bm")

# smc_config_pkg::TelemetryReceiverBufferDepth and the AtFifoDepth of the
# wrapper's ATB crossing FIFO.
BUFFER_DEPTH = 32
ATB_CROSSING_DEPTH = 8
HELD_CAPACITY = BUFFER_DEPTH + ATB_CROSSING_DEPTH
FULL_OFFER = HELD_CAPACITY + 1

# Bounds on the DUT-side observations. Expiry is a failure, never a pass.
POLL_BOUND = 200
#: clk_smc_i cycles between two polls of a register.
POLL_SPACING = 4
ATREADY_LOW_BOUND = 50
FLUSH_POLL_BOUND = 64
IRQ_POLL_BOUND = 64
# Cycles the TX flush is watched with the FIFO full and no reads issued.
TX_FLUSH_HOLD_CYCLES = 200
WRITE_TIMEOUT_NS = 2000
WRITE_PATTERN = 0xFFFF_FFFF
AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
DECERR_RDATA = 0xBADCAB1E
# Offsets in the receiver's slot past its last register: the first byte past
# the map, and one whose low five bits are TELEMETRY_DATA's offset.
PAST_END_OFFSETS = (RX_MAP_SIZE, 0x34)

Beat = tuple[int, int]


def _word(beat: Beat) -> int:
    """The TELEMETRY_DATA value a read of ``beat`` returns."""
    atid, data = beat
    return VALID_BM | ((atid << ATID_BP) & ATID_BM) | ((data << DATA_BP) & DATA_BM)


def _beat(word: int) -> Beat:
    return (word & ATID_BM) >> ATID_BP, (word & DATA_BM) >> DATA_BP


def _stream(first_atid: int, first_data: int, count: int) -> list[Beat]:
    """``count`` beats, each with an ATID and a data byte no other beat in it shares."""
    return [((first_atid + i) & 0x7F, (first_data + 3 * i) & 0xFF) for i in range(count)]


CAPTURE_BEATS = [(0x11 + i, 0xA0 + i) for i in range(5)]
EMPTY_READ_BEAT = (0x21, 0x5A)
FULL_BEATS = _stream(0x30, 0x01, FULL_OFFER)
BACK_TO_BACK_BEATS = [(0x08, 0xC1), (0x09, 0xC2), (0x0A, 0xC3), (0x0B, 0xC4)]
RX_FLUSH_BEATS = _stream(0x50, 0x80, HELD_CAPACITY + 20)
THRESHOLD = 3
THRESHOLD_BEATS = [(0x0C, 0xD1), (0x0D, 0xD2), (0x0E, 0xD3), (0x0F, 0xD4)]
TX_FLUSH_BEATS = _stream(0x01, 0x40, FULL_OFFER)
WRITE_BEAT = (0x7E, 0x3C)
PAST_END_BEAT = (0x7D, 0x6B)


async def poll_mask(seq, label: str, addr: int, mask: int, want: bool) -> int:
    """Poll ``addr`` until ``mask`` reads ``want``; raise on expiry. Returns the polls taken."""
    value = 0
    for polls in range(1, POLL_BOUND + 1):
        value = await seq.csr_read(f"{label}_POLL", addr)
        if bool(value & mask) == want:
            return polls
        await ClockCycles(cocotb.top.clk_smc_i, POLL_SPACING)
    raise AssertionError(
        f"{label}: mask 0x{mask:08x} at 0x{addr:08x} never reached {int(want)} over "
        f"{POLL_BOUND} polls (last 0x{value:08x})"
    )


async def expect_empty(seq, label: str, rx: int = RX) -> None:
    """Require receiver ``rx`` to report an empty FIFO and its TELEMETRY_DATA to read 0."""
    await seq.csr_read(f"{label}_STATUS_EMPTY", _rx_addr("STATUS", rx), expected=BUFFER_EMPTY_BM)
    await seq.csr_read(f"{label}_DATA_EMPTY", _rx_addr("TELEMETRY_DATA", rx), expected=0)


async def pop_expect(seq, label: str, beat: Beat, rx: int = RX) -> int:
    """Read ``beat`` from receiver ``rx``, re-reading while the beat is still crossing.

    A read that returns 0 is an empty FIFO and is retried; any other value
    must be ``beat`` exactly. Returns the word read.
    """
    want = _word(beat)
    addr = _rx_addr("TELEMETRY_DATA", rx)
    for _ in range(POLL_BOUND):
        word = await seq.csr_read(f"{label}_DATA", addr)
        if word == 0:
            await ClockCycles(cocotb.top.clk_smc_i, POLL_SPACING)
            continue
        assert word == want, (
            f"{label}: receiver {rx} TELEMETRY_DATA read 0x{word:08x} (ATID "
            f"0x{_beat(word)[0]:02x}, DATA 0x{_beat(word)[1]:02x}, VALID {word >> 31}), "
            f"expected 0x{want:08x} (ATID 0x{beat[0]:02x}, DATA 0x{beat[1]:02x}, VALID 1)"
        )
        return word
    raise AssertionError(
        f"{label}: receiver {rx} TELEMETRY_DATA stayed empty over {POLL_BOUND} reads waiting "
        f"for ATID 0x{beat[0]:02x} DATA 0x{beat[1]:02x}"
    )


async def wait_more_than(seq, label: str, count: int, rx: int = RX, restore: int = 0) -> None:
    """Wait until receiver ``rx`` holds more than ``count`` beats, read off INTR_STATUS.

    CTRL carries the temporary threshold while waiting and is written to
    ``restore`` afterwards.
    """
    ctrl = _rx_addr("CTRL", rx)
    await seq.csr_write(f"{label}_THRESHOLD", ctrl, count << THRESHOLD_BP)
    await poll_mask(seq, label, _rx_addr("INTR_STATUS", rx), INTR_THRESHOLD_BM, True)
    await seq.csr_write(f"{label}_THRESHOLD_RESTORE", ctrl, restore)


class _HeldSource:
    """An ATB source that holds each beat on the pins until ``atready`` takes it."""

    def __init__(self, dut, beats: list[Beat], rx: int = RX) -> None:
        self.dut = dut
        self.beats = beats
        self.rx = rx
        self.sent = 0
        self.done = False
        self.task = cocotb.start_soon(self._run())

    @property
    def pending(self) -> int:
        return len(self.beats) - self.sent

    async def _run(self) -> None:
        dut, rx = self.dut, self.rx
        atdata = getattr(dut, f"tb_telemetry{rx}_atdata")
        atid = getattr(dut, f"tb_telemetry{rx}_atid")
        atvalid = getattr(dut, f"tb_telemetry{rx}_atvalid")
        atready = getattr(dut, f"tb_telemetry{rx}_atready")
        for beat_atid, beat_data in self.beats:
            atid.value = beat_atid
            atdata.value = beat_data
            atvalid.value = 1
            while True:
                await FallingEdge(dut.clk_smc_i)
                raw = atready.value
                assert raw.is_resolvable, f"tb_telemetry{rx}_atready is X/Z: {raw}"
                if int(raw):
                    break
            await RisingEdge(dut.clk_smc_i)
            self.sent += 1
        atvalid.value = 0
        self.done = True


class smc_telemetry_atb_capture_test_seq(SmcCsrSeq):
    """Drive raw ATB beats into receiver 0 and read them back through TELEMETRY_DATA."""

    def __init__(self, name: str = "smc_telemetry_atb_capture_test_seq") -> None:
        super().__init__(name)
        self.write_resp: int | None = None
        self.past_end_resps: dict[int, int | None] = {}

    async def body(self) -> None:
        dut = cocotb.top
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)

        await self.csr_read("TELEMETRY_STATUS_ENTRY", STATUS, expected=BUFFER_EMPTY_BM)

        await self._capture_in_order(dut)
        await self._empty_read_does_not_pop(dut)
        await self._full_fifo_backpressures_and_preserves_order(dut)
        await self._back_to_back_reads_pop_once_each(dut)
        await self._rx_flush_while_full(dut)
        await self._threshold_counts_beats(dut)
        await self._tx_flush_completes_while_draining(dut)
        await self._write_does_not_pop_or_hang(dut)
        await self._past_end_offset_does_not_pop(dut)

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original_cg)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORE_RB", CLOCK_GATE_CONTROL, expected=original_cg
        )

    # ------------------------------------------------------------------ helpers

    async def _send(self, dut, beats: list[Beat]) -> None:
        await _HeldSource(dut, beats).task

    async def _await_irq(self, dut, want: int, label: str) -> int:
        """Wait for ``tb_telemetry_irq_any`` to reach ``want``; raise on expiry."""
        for cycle in range(IRQ_POLL_BOUND + 1):
            if int(dut.tb_telemetry_irq_any.value) == want:
                return cycle
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label}: tb_telemetry_irq_any stayed {1 - want} for {IRQ_POLL_BOUND} clk_smc_i "
            f"cycles, want {want}"
        )

    async def _read_beat(self, label: str) -> int:
        return await self.csr_read(f"{label}_DATA", TELEMETRY_DATA)

    async def _wait_atready_low(self, dut, label: str) -> int:
        atready = getattr(dut, f"tb_telemetry{RX}_atready")
        for cycle in range(ATREADY_LOW_BOUND + 1):
            if int(atready.value) == 0:
                return cycle
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label}: tb_telemetry{RX}_atready stayed high for {ATREADY_LOW_BOUND} clk_smc_i "
            f"cycles after STATUS.BUFFER_FULL read 1"
        )

    async def _fill(self, dut, label: str, beats: list[Beat]) -> tuple[_HeldSource, int]:
        """Offer ``beats`` with no reads; return once the pins hold the source off."""
        source = _HeldSource(dut, beats)
        await poll_mask(self, f"{label}_FULL", STATUS, BUFFER_FULL_BM, True)
        cycles = await self._wait_atready_low(dut, label)
        await FallingEdge(dut.clk_smc_i)
        assert source.sent == HELD_CAPACITY, (
            f"{label}: {source.sent} beats were accepted before atready_o dropped, expected "
            f"{HELD_CAPACITY} ({BUFFER_DEPTH} in the receiver plus {ATB_CROSSING_DEPTH} in the "
            f"ATB crossing FIFO)"
        )
        return source, cycles

    # ------------------------------------------------------------------- checks

    async def _capture_in_order(self, dut) -> None:
        await self._send(dut, CAPTURE_BEATS)
        for index, beat in enumerate(CAPTURE_BEATS):
            await pop_expect(self, f"CAPTURE_{index}", beat)
        await expect_empty(self, "CAPTURE")
        cocotb.log.info(
            "CHK-TELEMETRY-RAW-CAPTURE-IN-ORDER: %d beats %s on receiver %d read back in order "
            "through TELEMETRY_DATA with VALID=1 and matching ATID and DATA, then "
            "STATUS.BUFFER_EMPTY=1",
            len(CAPTURE_BEATS),
            ", ".join(f"({a:#04x},{d:#04x})" for a, d in CAPTURE_BEATS),
            RX,
        )

    async def _empty_read_does_not_pop(self, dut) -> None:
        await expect_empty(self, "EMPTY_READ_FIRST")
        await self._send(dut, [EMPTY_READ_BEAT])
        await pop_expect(self, "EMPTY_READ_BEAT", EMPTY_READ_BEAT)
        await expect_empty(self, "EMPTY_READ_AFTER")
        cocotb.log.info(
            "CHK-TELEMETRY-EMPTY-READ-NO-POP: a read of the empty FIFO returned 0x00000000, the "
            "next beat (ATID %#04x, DATA %#04x) read back as 0x%08x, and the FIFO was empty again",
            *EMPTY_READ_BEAT,
            _word(EMPTY_READ_BEAT),
        )

    async def _full_fifo_backpressures_and_preserves_order(self, dut) -> None:
        source, cycles = await self._fill(dut, "FULL", FULL_BEATS)
        assert source.pending == 1, f"FULL: {source.pending} beats pending, expected 1"
        for index, beat in enumerate(FULL_BEATS):
            await pop_expect(self, f"FULL_{index}", beat)
        await source.task
        await expect_empty(self, "FULL")
        cocotb.log.info(
            "CHK-TELEMETRY-FULL-BACKPRESSURE: %d beats offered with no reads set "
            "STATUS.BUFFER_FULL, atready_o[%d] fell %d cycles later with %d accepted and one "
            "held on the pins, and the drain returned all %d in order",
            FULL_OFFER,
            RX,
            cycles,
            HELD_CAPACITY,
            FULL_OFFER,
        )

    async def _back_to_back_reads_pop_once_each(self, dut) -> None:
        await self._send(dut, BACK_TO_BACK_BEATS)
        await wait_more_than(self, "BACK_TO_BACK", len(BACK_TO_BACK_BEATS) - 1)
        words = [await self._read_beat(f"BACK_TO_BACK_{i}") for i in range(4)]
        fifth = await self._read_beat("BACK_TO_BACK_FIFTH")
        want = [_word(b) for b in BACK_TO_BACK_BEATS]
        assert words == want, (
            "BACK_TO_BACK: four consecutive TELEMETRY_DATA reads returned "
            f"{[f'0x{w:08x}' for w in words]}, expected {[f'0x{w:08x}' for w in want]}"
        )
        assert fifth == 0, f"BACK_TO_BACK: the fifth read returned 0x{fifth:08x}, expected 0"
        await expect_empty(self, "BACK_TO_BACK")
        cocotb.log.info(
            "CHK-TELEMETRY-BACK-TO-BACK-POP: four queued beats came back from four consecutive "
            "reads as %s and the fifth read returned 0x00000000",
            ", ".join(f"0x{w:08x}" for w in words),
        )

    async def _rx_flush_while_full(self, dut) -> None:
        source, _ = await self._fill(dut, "RX_FLUSH", RX_FLUSH_BEATS)
        await self.csr_write("RX_FLUSH", CTRL, RX_FLUSH_BM)
        await source.task
        read: list[Beat] = []
        for _ in range(POLL_BOUND):
            word = await self._read_beat(f"RX_FLUSH_TAIL_{len(read)}")
            if word == 0:
                await ClockCycles(dut.clk_smc_i, POLL_SPACING)
                continue
            assert word & VALID_BM, f"RX_FLUSH: read 0x{word:08x} has VALID clear"
            read.append(_beat(word))
            if read[-1] == RX_FLUSH_BEATS[-1]:
                break
        else:
            raise AssertionError(
                f"RX_FLUSH: the last offered beat never read back; read {len(read)} beats"
            )
        await expect_empty(self, "RX_FLUSH")
        dropped = len(RX_FLUSH_BEATS) - len(read)
        assert dropped >= BUFFER_DEPTH, (
            f"RX_FLUSH: {len(read)} beats read back after the flush; at least {BUFFER_DEPTH} "
            f"queued beats should have been discarded"
        )
        assert read == RX_FLUSH_BEATS[dropped:], (
            f"RX_FLUSH: the {len(read)} beats read after the flush are not the contiguous tail "
            f"of the offered stream: {read}"
        )
        cocotb.log.info(
            "CHK-TELEMETRY-RX-FLUSH-WHILE-FULL: CTRL.TELEMETRY_RX_FLUSH on a full FIFO discarded "
            "the first %d of %d offered beats; the %d read afterwards were the contiguous tail "
            "of the stream, in order, ending at the last beat offered",
            dropped,
            len(RX_FLUSH_BEATS),
            len(read),
        )

    async def _threshold_counts_beats(self, dut) -> None:
        await self.csr_write("THRESHOLD_ENABLE", INTR_ENABLE, ENABLE_THRESHOLD_BM)
        await self._send(dut, THRESHOLD_BEATS[:THRESHOLD])
        await wait_more_than(self, "THRESHOLD_THREE", THRESHOLD - 1)
        await self.csr_write("THRESHOLD_SET", CTRL, THRESHOLD << THRESHOLD_BP)
        at_three = await self.csr_read("THRESHOLD_AT_THREE", INTR_STATUS)
        assert at_three & INTR_THRESHOLD_BM == 0, (
            f"THRESHOLD: {THRESHOLD} beats against threshold {THRESHOLD} read INTR_STATUS "
            f"0x{at_three:08x}; BUFFER_THRESHOLD must be 0"
        )
        await self._await_irq(dut, 0, "THRESHOLD_AT_THREE")

        await self._send(dut, THRESHOLD_BEATS[THRESHOLD:])
        await poll_mask(self, "THRESHOLD_FOUR", INTR_STATUS, INTR_THRESHOLD_BM, True)
        irq_rise = await self._await_irq(dut, 1, "THRESHOLD_AT_FOUR")

        await pop_expect(self, "THRESHOLD_POP", THRESHOLD_BEATS[0])
        after_pop = await self.csr_read("THRESHOLD_AFTER_POP", INTR_STATUS)
        assert after_pop & INTR_THRESHOLD_BM == 0, (
            f"THRESHOLD: one pop from 4 beats left INTR_STATUS 0x{after_pop:08x}"
        )
        irq_fall = await self._await_irq(dut, 0, "THRESHOLD_AFTER_POP")

        for index, beat in enumerate(THRESHOLD_BEATS[1:], start=1):
            await pop_expect(self, f"THRESHOLD_DRAIN_{index}", beat)
        await self.csr_write("THRESHOLD_RESTORE", CTRL, 0)
        await self.csr_write("THRESHOLD_DISABLE", INTR_ENABLE, 0)
        await expect_empty(self, "THRESHOLD")
        cocotb.log.info(
            "CHK-TELEMETRY-THRESHOLD-BEATS: with CTRL.BUFFER_THRESHOLD=%d and the interrupt "
            "enabled, %d beats read INTR_STATUS.BUFFER_THRESHOLD=0 with the interrupt low, %d "
            "beats read 1 with the interrupt high (%d cycles after the poll), and one "
            "TELEMETRY_DATA read returned both to 0 (%d cycles)",
            THRESHOLD,
            THRESHOLD,
            len(THRESHOLD_BEATS),
            irq_rise,
            irq_fall,
        )

    async def _tx_flush_completes_while_draining(self, dut) -> None:
        afready = getattr(dut, f"tb_telemetry{RX}_afready")
        afvalid = getattr(dut, f"tb_telemetry{RX}_afvalid")
        afready.value = 0
        source, _ = await self._fill(dut, "TX_FLUSH", TX_FLUSH_BEATS)

        async def drained_source_acks() -> None:
            while not (int(afvalid.value) and source.done):
                await RisingEdge(dut.clk_smc_i)
            afready.value = 1

        responder = cocotb.start_soon(drained_source_acks())
        await self.csr_write("TX_FLUSH", CTRL, TX_FLUSH_BM)
        await self._await_afvalid(dut, afvalid, 1, "TX_FLUSH_RISE")
        await ClockCycles(dut.clk_smc_i, TX_FLUSH_HOLD_CYCLES)
        held = await self.csr_read("TX_FLUSH_HELD", CTRL)
        assert held & TX_FLUSH_BM, (
            f"TX_FLUSH: CTRL.TELEMETRY_TX_FLUSH cleared with the FIFO full and {source.pending} "
            f"beats still held at the source (CTRL=0x{held:08x})"
        )

        for index, beat in enumerate(TX_FLUSH_BEATS):
            await pop_expect(self, f"TX_FLUSH_{index}", beat)
        await source.task
        await responder
        polls = await poll_mask(self, "TX_FLUSH_CLEAR", CTRL, TX_FLUSH_BM, False)
        await self._await_afvalid(dut, afvalid, 0, "TX_FLUSH_FALL")
        await expect_empty(self, "TX_FLUSH")
        cocotb.log.info(
            "CHK-TELEMETRY-TX-FLUSH-WHILE-DRAINING: with the FIFO full and the source holding a "
            "beat, CTRL.TELEMETRY_TX_FLUSH stayed set for %d cycles; after %d TELEMETRY_DATA "
            "reads drained the source it acknowledged, and the bit cleared within %d polls",
            TX_FLUSH_HOLD_CYCLES,
            len(TX_FLUSH_BEATS),
            polls,
        )

    async def _write_does_not_pop_or_hang(self, dut) -> None:
        await self._send(dut, [WRITE_BEAT])
        await poll_mask(self, "WRITE_QUEUED", STATUS, BUFFER_EMPTY_BM, False)
        item = SmcSysAxiItem("wr_TELEMETRY_DATA")
        item.op = SmcSysAxiOp.WRITE
        item.addr = TELEMETRY_DATA
        item.wdata = WRITE_PATTERN
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = WRITE_TIMEOUT_NS
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.bounded_accesses += 1
        assert not item.timed_out, (
            f"WRITE: a write to TELEMETRY_DATA got no response within {WRITE_TIMEOUT_NS} ns"
        )
        self.write_resp = item.resp_code
        assert self.write_resp == AXI_RESP_OKAY, (
            f"WRITE: a write to TELEMETRY_DATA returned resp={self.write_resp}, expected OKAY"
        )
        await pop_expect(self, "WRITE_AFTER", WRITE_BEAT)
        await expect_empty(self, "WRITE")
        cocotb.log.info(
            "CHK-TELEMETRY-WRITE-NO-POP: a write of 0x%08x to TELEMETRY_DATA completed with "
            "resp=%s (OKAY), and the queued beat (ATID %#04x, DATA %#04x) still read back afterwards",
            WRITE_PATTERN,
            self.write_resp,
            *WRITE_BEAT,
        )

    async def _past_end_offset_does_not_pop(self, dut) -> None:
        await self._send(dut, [PAST_END_BEAT])
        await poll_mask(self, "PAST_END_QUEUED", STATUS, BUFFER_EMPTY_BM, False)
        self.env.axi_monitor.expected_decerr_addrs.update(RX_BASE + o for o in PAST_END_OFFSETS)
        for offset in PAST_END_OFFSETS:
            addr = RX_BASE + offset
            item = SmcSysAxiItem(f"rd_PAST_END_{offset:#04x}")
            item.op = SmcSysAxiOp.READ
            item.addr = addr
            item.expect_error = True
            item.allow_error = True
            item.expected_resp = AXI_RESP_DECERR
            item.allow_timeout = True
            item.timeout_ns = WRITE_TIMEOUT_NS
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
            self.bounded_accesses += 1
            assert not item.timed_out, (
                f"PAST_END: a read at receiver {RX} base + {offset:#04x} (0x{addr:08x}) got no "
                f"response within {WRITE_TIMEOUT_NS} ns"
            )
            self.past_end_resps[offset] = item.resp_code
            assert item.resp_code == AXI_RESP_DECERR and item.rdata == DECERR_RDATA, (
                f"PAST_END: a read at receiver {RX} base + {offset:#04x} (0x{addr:08x}) returned "
                f"resp={item.resp_code} data=0x{item.rdata:08x}, expected DECERR "
                f"({AXI_RESP_DECERR}) with data 0x{DECERR_RDATA:08x}"
            )
        await pop_expect(self, "PAST_END_AFTER", PAST_END_BEAT)
        await expect_empty(self, "PAST_END")
        cocotb.log.info(
            "CHK-TELEMETRY-PAST-END-NO-POP: reads at receiver %d base + %s returned resp %s "
            "(DECERR) with data 0x%08x, and the queued beat (ATID %#04x, DATA %#04x) still read back "
            "afterwards",
            RX,
            ", ".join(f"{o:#04x}" for o in PAST_END_OFFSETS),
            ", ".join(str(self.past_end_resps[o]) for o in PAST_END_OFFSETS),
            DECERR_RDATA,
            *PAST_END_BEAT,
        )

    async def _await_afvalid(self, dut, afvalid, want: int, label: str) -> int:
        for cycle in range(FLUSH_POLL_BOUND + 1):
            raw = afvalid.value
            assert raw.is_resolvable, f"{label}: tb_telemetry{RX}_afvalid is X/Z: {raw}"
            if int(raw) == want:
                return cycle
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label}: tb_telemetry{RX}_afvalid stayed {int(afvalid.value)} for "
            f"{FLUSH_POLL_BOUND} clk_smc_i cycles, want {want}"
        )
