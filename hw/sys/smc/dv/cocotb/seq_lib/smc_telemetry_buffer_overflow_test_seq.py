# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receivers 1 and 2 past a full FIFO: backpressure, and no beat lost.

A full receiver FIFO drops ``atready``, the wrapper's ATB crossing FIFO fills behind it, and
the source stalls: ``HELD_CAPACITY`` beats queue and nothing is dropped or overwritten
(``telemetry_receiver.rdl``). ``smc_telemetry_atb_capture_test`` grades one full fill and drain
of receiver 0; this leaf runs receivers 1 and 2 past their bound and holds them there:

* **Full.** A stream longer than ``HELD_CAPACITY`` with no reads sets ``STATUS.BUFFER_FULL``,
  ``atready`` drops with exactly ``HELD_CAPACITY`` beats accepted at the pins, and over a hold
  window the source stays stalled with ``STATUS.BUFFER_FULL`` set.
* **Threshold at depth.** With the FIFO full, ``CTRL.BUFFER_THRESHOLD`` of ``BUFFER_DEPTH - 1``
  asserts ``INTR_STATUS.BUFFER_THRESHOLD`` and ``BUFFER_DEPTH``, ``0x040``, ``0x05F``, ``0x800``
  and ``0xFFF`` do not: "only values below the buffer depth can assert the interrupt".
* **Overflow order.** One ``TELEMETRY_DATA`` read frees one slot, the held source moves exactly
  one beat in and ``STATUS.BUFFER_FULL`` sets again. Reading on returns every beat of the
  stream exactly once and in order, then an empty FIFO.
* **Push against pop.** With one slot free, a beat arrives at each offset from -4 to +4
  ``clk_smc_i`` cycles around a ``TELEMETRY_DATA`` read; the drain is every beat, in order.
* **Transmitter flush.** The bench holds ``afready_i`` of receivers 1 and 2 high, so
  ``CTRL.TELEMETRY_TX_FLUSH`` self-clears; the beats queued before it still drain in order.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_DEPTH,
    BUFFER_FULL_BM,
    HELD_CAPACITY,
    INTR_THRESHOLD_BM,
    POLL_SPACING,
    RX_FLUSH_BM,
    THRESHOLD_BP,
    TX_FLUSH_BM,
    Beat,
    _HeldSource,
    _rx_addr,
    _stream,
    _word,
    expect_empty,
    pop_expect,
    wait_more_than,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

EXT_RECEIVERS = (1, 2)
#: Beats offered beyond what the receiver and the crossing FIFO hold.
OFFER_EXTRA = 24
STREAMS = {
    1: _stream(0x10, 0x01, HELD_CAPACITY + OFFER_EXTRA),
    2: _stream(0x50, 0x81, HELD_CAPACITY + OFFER_EXTRA),
}
#: `CTRL.BUFFER_THRESHOLD` values with the INTR_STATUS each must give on a full FIFO. The values
#: above the depth have their low six bits below it, so a compare that drops the upper bits of
#: the 12-bit field asserts the interrupt on them.
THRESHOLD_AT_DEPTH = (
    (BUFFER_DEPTH - 1, True),
    (BUFFER_DEPTH, False),
    (0x040, False),
    (0x05F, False),
    (0x800, False),
    (0xFFF, False),
)
WINDOW_OFFSETS = tuple(range(-4, 5))
TX_FLUSH_BEATS = {1: _stream(0x70, 0x31, 3), 2: _stream(0x74, 0x61, 3)}
#: Cycles the full FIFO is watched with the source stalled.
HOLD_CYCLES = 200
POLL_BOUND = 200
ATREADY_BOUND = 64
REFILL_BOUND = 64
STEP_ORDER = (
    "TELEM12_FULL",
    "TELEM12_THRESHOLD",
    "TELEM12_OVERFLOW",
    "TELEM12_PUSH_POP",
    "TELEM12_TX_FLUSH",
    "TIMEOUT",
)
CHK_STEP = {
    "CHK-TELEM12-FULL": "TELEM12_FULL",
    "CHK-TELEMETRY-THRESHOLD-AT-DEPTH": "TELEM12_THRESHOLD",
    "CHK-TELEM12-OVERFLOW-ORDER": "TELEM12_OVERFLOW",
    "CHK-TELEM12-PUSH-POP-WINDOW": "TELEM12_PUSH_POP",
    "CHK-TELEM12-TX-FLUSH": "TELEM12_TX_FLUSH",
    "CHK-TIMEOUT-PATHS": "TIMEOUT",
}


def _window_stream(rx: int, trial: int) -> list[Beat]:
    """The `BUFFER_DEPTH` beats of one push-against-pop trial."""
    return _stream(0x08 * trial + rx, 0x11 * trial + 0x40 * rx, BUFFER_DEPTH)


class smc_telemetry_buffer_overflow_test_seq(SmcCsrSeq):
    """Hold receivers 1 and 2 full, then drain them with nothing lost."""

    def __init__(self, name: str = "smc_telemetry_buffer_overflow_test_seq") -> None:
        super().__init__(name)
        self.waits: dict[str, tuple[int, str, str]] = {}
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int, int]] = []
        self.sources: dict[int, _HeldSource] = {}

    def _wait(self, name: str, bound: int, unit: str, last: str) -> None:
        self.waits[name] = (bound, unit, last)

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, int(get_sim_time("ps")), len(self.stamps)))

    async def _end_step(self, step: str) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp(step)

    async def _poll(self, label: str, addr: int, done, wait: str) -> int:
        """Read `addr` until `done(value)`; raise with the last value on expiry."""
        value = 0
        for _ in range(POLL_BOUND):
            value = await self.csr_read(label, addr)
            if done(value):
                self._wait(wait, POLL_BOUND, "register polls", f"0x{value:08x}")
                return value
            await ClockCycles(cocotb.top.clk_smc_i, POLL_SPACING)
        raise AssertionError(
            f"{label}: {wait} expired after {POLL_BOUND} polls (last read 0x{value:08x})"
        )

    async def _sent_reaches(self, source: _HeldSource, want: int, label: str) -> int:
        """Wait until `source` has handed over `want` beats; returns the cycles taken."""
        for cycle in range(REFILL_BOUND + 1):
            if source.sent >= want:
                self._wait("source_refill", REFILL_BOUND, "clk_smc_i", f"sent={source.sent}")
                return cycle
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: the held source handed over {source.sent} beats, not {want}, within "
            f"{REFILL_BOUND} clk_smc_i cycles"
        )

    async def _bringup(self, rx: int) -> None:
        await self.csr_write(f"R{rx}_BRINGUP_FLUSH", _rx_addr("CTRL", rx), RX_FLUSH_BM)
        await self.csr_read(f"R{rx}_BRINGUP_INTR", _rx_addr("INTR_STATUS", rx), expected=0)
        await expect_empty(self, f"R{rx}_BRINGUP", rx)

    async def _full(self) -> None:
        dut = cocotb.top
        held: dict[int, int] = {}
        for rx in EXT_RECEIVERS:
            await self._bringup(rx)
            source = _HeldSource(dut, STREAMS[rx], rx=rx)
            self.sources[rx] = source
            await self._poll(
                f"R{rx}_FULL",
                _rx_addr("STATUS", rx),
                lambda v: v & BUFFER_FULL_BM,
                "buffer_full",
            )
            atready = getattr(dut, f"tb_telemetry{rx}_atready")
            for cycle in range(ATREADY_BOUND + 1):
                if int(atready.value) == 0:
                    self._wait("atready_low", ATREADY_BOUND, "clk_smc_i", f"after {cycle}")
                    break
                await RisingEdge(dut.clk_smc_i)
            else:
                raise AssertionError(
                    f"receiver {rx}: tb_telemetry{rx}_atready stayed high for {ATREADY_BOUND} "
                    f"cycles after STATUS.BUFFER_FULL read 1"
                )
            await FallingEdge(dut.clk_smc_i)
            assert source.sent == HELD_CAPACITY, (
                f"receiver {rx}: {source.sent} beats accepted before atready dropped, expected "
                f"{HELD_CAPACITY}"
            )
            await ClockCycles(dut.clk_smc_i, HOLD_CYCLES)
            status = await self.csr_read(f"R{rx}_FULL_HELD", _rx_addr("STATUS", rx))
            assert source.sent == HELD_CAPACITY and status == BUFFER_FULL_BM, (
                f"receiver {rx}: after {HOLD_CYCLES} stalled cycles {source.sent} beats were "
                f"accepted and STATUS read 0x{status:08x}; expected {HELD_CAPACITY} and "
                f"0x{BUFFER_FULL_BM:02x}"
            )
            held[rx] = source.pending
        self._chk(
            "CHK-TELEM12-FULL",
            f"on receivers {list(EXT_RECEIVERS)}, {len(STREAMS[1])} beats offered with no reads "
            f"set STATUS.BUFFER_FULL and atready dropped with {HELD_CAPACITY} beats accepted "
            f"({BUFFER_DEPTH} in the receiver plus {HELD_CAPACITY - BUFFER_DEPTH} in the "
            f"crossing FIFO); over {HOLD_CYCLES} further cycles none was accepted, STATUS stayed "
            f"0x{BUFFER_FULL_BM:02x}, and the source still held "
            + ", ".join(f"r{rx}={held[rx]}" for rx in EXT_RECEIVERS),
        )
        await self._end_step("TELEM12_FULL")

    async def _threshold_at_depth(self) -> None:
        seen: dict[int, list[str]] = {}
        for rx in EXT_RECEIVERS:
            ctrl = _rx_addr("CTRL", rx)
            seen[rx] = []
            for threshold, want in THRESHOLD_AT_DEPTH:
                word = threshold << THRESHOLD_BP
                await self.csr_write(f"R{rx}_T{threshold:03X}", ctrl, word)
                await self.csr_read(f"R{rx}_T{threshold:03X}_RB", ctrl, expected=word)
                intr = await self.csr_read(
                    f"R{rx}_T{threshold:03X}_INTR", _rx_addr("INTR_STATUS", rx)
                )
                assert bool(intr & INTR_THRESHOLD_BM) == want, (
                    f"receiver {rx}: with {BUFFER_DEPTH} beats and CTRL.BUFFER_THRESHOLD="
                    f"0x{threshold:03x}, INTR_STATUS reads 0x{intr:08x}, want BUFFER_THRESHOLD "
                    f"{int(want)}"
                )
                seen[rx].append(f"0x{threshold:03x}->{int(want)}")
            await self.csr_write(f"R{rx}_T_RESTORE", ctrl, 0)
        self._chk(
            "CHK-TELEMETRY-THRESHOLD-AT-DEPTH",
            f"on receivers {list(EXT_RECEIVERS)} holding {BUFFER_DEPTH} beats, "
            "CTRL.BUFFER_THRESHOLD read back as written and INTR_STATUS.BUFFER_THRESHOLD read "
            + "; ".join(f"r{rx} " + ", ".join(seen[rx]) for rx in EXT_RECEIVERS),
        )
        await self._end_step("TELEM12_THRESHOLD")

    async def _overflow_order(self) -> None:
        refill: dict[int, int] = {}
        for rx in EXT_RECEIVERS:
            source = self.sources[rx]
            stream = STREAMS[rx]
            await pop_expect(self, f"R{rx}_DRAIN_0", stream[0], rx)
            refill[rx] = await self._sent_reaches(source, HELD_CAPACITY + 1, f"receiver {rx}")
            await self._poll(
                f"R{rx}_REFULL",
                _rx_addr("STATUS", rx),
                lambda v: v & BUFFER_FULL_BM,
                "buffer_refull",
            )
            assert source.sent == HELD_CAPACITY + 1, (
                f"receiver {rx}: one read let {source.sent - HELD_CAPACITY} held beats in"
            )
            for index, beat in enumerate(stream[1:], start=1):
                await pop_expect(self, f"R{rx}_DRAIN_{index}", beat, rx)
            await source.task
            await expect_empty(self, f"R{rx}_DRAINED", rx)
        self._chk(
            "CHK-TELEM12-OVERFLOW-ORDER",
            f"on receivers {list(EXT_RECEIVERS)}, the first TELEMETRY_DATA read let exactly one "
            f"held beat in ("
            + ", ".join(f"r{rx} {refill[rx]} cycles" for rx in EXT_RECEIVERS)
            + f") and STATUS.BUFFER_FULL set again; the drain returned all {len(STREAMS[1])} "
            "offered beats once each, in order, then TELEMETRY_DATA 0 and STATUS.BUFFER_EMPTY",
        )
        await self._end_step("TELEM12_OVERFLOW")

    async def _window_trial(self, rx: int, trial: int, offset: int) -> None:
        dut = cocotb.top
        beats = _window_stream(rx, trial)
        await _HeldSource(dut, beats[:-1], rx=rx).task
        await wait_more_than(self, f"R{rx}_W{trial}", BUFFER_DEPTH - 2, rx)
        data = _rx_addr("TELEMETRY_DATA", rx)
        label = f"R{rx}_W{trial}_D{offset:+d}"
        if offset < 0:
            read = cocotb.start_soon(self.csr_read(f"{label}_READ", data))
            await ClockCycles(dut.clk_smc_i, -offset)
            await _HeldSource(dut, beats[-1:], rx=rx).task
        else:
            await _HeldSource(dut, beats[-1:], rx=rx).task
            await ClockCycles(dut.clk_smc_i, offset)
            read = cocotb.start_soon(self.csr_read(f"{label}_READ", data))
        first = await read
        assert first == _word(beats[0]), (
            f"{label}: the read around the push returned 0x{first:08x}, expected "
            f"0x{_word(beats[0]):08x}"
        )
        for index, beat in enumerate(beats[1:], start=1):
            await pop_expect(self, f"{label}_DRAIN_{index}", beat, rx)
        await expect_empty(self, f"{label}_DRAINED", rx)

    async def _push_pop_window(self) -> None:
        trial = 0
        for rx in EXT_RECEIVERS:
            for offset in WINDOW_OFFSETS:
                trial += 1
                await self._window_trial(rx, trial, offset)
        self._chk(
            "CHK-TELEM12-PUSH-POP-WINDOW",
            f"for every offset d in {WINDOW_OFFSETS[0]}..{WINDOW_OFFSETS[-1]} clk_smc_i cycles "
            f"on receivers {list(EXT_RECEIVERS)}, a beat pushed against a TELEMETRY_DATA read "
            f"with {BUFFER_DEPTH - 1} beats queued left all {BUFFER_DEPTH} beats readable once "
            f"each and in order ({trial} trials)",
        )
        await self._end_step("TELEM12_PUSH_POP")

    async def _tx_flush(self) -> None:
        dut = cocotb.top
        for rx in EXT_RECEIVERS:
            beats = TX_FLUSH_BEATS[rx]
            ctrl = _rx_addr("CTRL", rx)
            await _HeldSource(dut, beats, rx=rx).task
            await wait_more_than(self, f"R{rx}_TXF", len(beats) - 1, rx)
            await self.csr_write(f"R{rx}_TXF_FLUSH", ctrl, TX_FLUSH_BM)
            await self._poll(f"R{rx}_TXF_CTRL", ctrl, lambda v: not v & TX_FLUSH_BM, "tx_flush")
            status = await self.csr_read(f"R{rx}_TXF_STATUS", _rx_addr("STATUS", rx))
            assert status == 0, (
                f"receiver {rx} after CTRL.TELEMETRY_TX_FLUSH: STATUS=0x{status:08x}, expected "
                f"0x00 with {len(beats)} beats queued"
            )
            for index, beat in enumerate(beats):
                await pop_expect(self, f"R{rx}_TXF_DRAIN_{index}", beat, rx)
            await expect_empty(self, f"R{rx}_TXF_DRAINED", rx)
        self._chk(
            "CHK-TELEM12-TX-FLUSH",
            f"on receivers {list(EXT_RECEIVERS)} with afready_i at its bench level (high) and "
            f"{len(TX_FLUSH_BEATS[1])} beats queued, CTRL.TELEMETRY_TX_FLUSH self-cleared within "
            f"{POLL_BOUND} polls, STATUS read 0x00, and the queued beats drained in order; the "
            "afready_i-low handshake is NOT-REACHABLE-AT-THIS-LEVEL on this bench",
        )
        await self._end_step("TELEM12_TX_FLUSH")

    async def _fence(self) -> None:
        names = " ".join(
            f"{name}(bound={bound} {unit}, last {last})"
            for name, (bound, unit, last) in sorted(self.waits.items())
        )
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self.waits)} bounded waits, each raising AssertionError with its last "
            f"observed register or pin state on expiry: {names}",
        )
        await self._end_step("TIMEOUT")

        steps = [s for s, _ in self.stamps]
        assert tuple(steps) == STEP_ORDER, f"fence steps {steps} out of order"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        stamp_of = dict(self.stamps)
        for chk_id, t, stamps_before in self.chk_lines:
            step = CHK_STEP[chk_id]
            assert stamps_before == STEP_ORDER.index(step) and t <= stamp_of[step], (
                f"{chk_id} at {t} ps followed {stamps_before} step stamps; it belongs inside "
                f"step {step}"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(STEP_ORDER),
            ",".join(c for c, _, _ in self.chk_lines),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )

    async def body(self) -> None:
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)

        await self._full()
        await self._threshold_at_depth()
        await self._overflow_order()
        await self._push_pop_window()
        await self._tx_flush()
        await self._fence()

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original_cg)
