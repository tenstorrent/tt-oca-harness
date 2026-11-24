# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver flush on receiver 0.

Sources: hw/ip/telemetry_receiver/doc/architecture.adoc (Reset and Flush, Interrupts),
hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl, doc/programmer/src/smc-programming.adoc.

``CTRL.TELEMETRY_RX_FLUSH`` discards every beat queued in the receiver FIFO. Beats still in the
wrapper's ATB crossing FIFO are not in the receiver yet, so a flush written while a source is
streaming keeps a contiguous tail of the stream. ``INTR_TEST`` is not buffer state and the
flush leaves it alone.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_EMPTY_BM,
    CTRL,
    ENABLE_THRESHOLD_BM,
    HELD_CAPACITY,
    INTR_ENABLE,
    INTR_STATUS,
    INTR_THRESHOLD_BM,
    RX_FLUSH_BM,
    STATUS,
    TELEMETRY_DATA,
    THRESHOLD_BP,
    VALID_BM,
    Beat,
    _beat,
    _HeldSource,
    _rx_addr,
    _stream,
    _tel,
    _word,
    wait_more_than,
)

INTR_TEST = _rx_addr("INTR_TEST")
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
TEST_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm")

THRESHOLD = 1
CTRL_THRESHOLD = THRESHOLD << THRESHOLD_BP
CTRL_FLUSH = CTRL_THRESHOLD | RX_FLUSH_BM

POPULATE_BEATS = _stream(0x01, 0x10, 3)
ONE_SHOT_BEAT = (0x1B, 0x2B)
RESTART_BEAT = (0x1A, 0x3A)
# As many beats as the receiver and the crossing FIFO hold, so the whole tail that
# survives the flush is buffered by the time the source finishes.
AROUND_BEATS = _stream(0x40, 0x81, HELD_CAPACITY)
AROUND_RECOVERY_BEAT = (0x14, 0x4C)
FORCE_BEATS = _stream(0x60, 0xC1, 2)

BUFFER_POLL_BOUND = 200
IRQ_WAIT_BOUND = 64
QUIET_CYCLES = 64
IN_FLIGHT_BEATS = 2
FUSE_SENSE_MAX_CYCLES = 200_000

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6")
FENCE_TERMS = (
    "SETUP_DONE",
    "POPULATED_FLUSH_DONE",
    "ONE_SHOT_DONE",
    "RESTART_DONE",
    "BEATS_AROUND_DONE",
    "TEST_FORCE_KEPT",
)
CHECKER_FOR_STEP = {
    "S2": "CHK-TELEMETRY-RX-FLUSH-EMPTIES",
    "S3": "CHK-TELEMETRY-RX-FLUSH-ONE-SHOT",
    "S4": "CHK-TELEMETRY-RX-FLUSH-RESTART",
    "S5": "CHK-TELEMETRY-RX-FLUSH-BEATS-AROUND",
    "S6": "CHK-TELEMETRY-RX-FLUSH-KEEPS-TEST-FORCE",
}


def _level(signal) -> int:
    raw = signal.value
    assert raw.is_resolvable, f"{signal._name} is X/Z: {raw}"
    return int(raw)


class smc_telemetry_rx_flush_test_seq(SmcCsrSeq):
    """Flush receiver 0 with a populated FIFO, beats in flight and an INTR_TEST force."""

    def __init__(self, name: str = "smc_telemetry_rx_flush_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_log: list[tuple[str, str, int]] = []
        self._waits: list[list[str]] = []
        self._wait_index: dict[str, int] = {}

    def _note_wait(self, name: str, bound: str, last: str = "not-ended") -> None:
        if name in self._wait_index:
            self._waits[self._wait_index[name]][2] = last
            return
        self._wait_index[name] = len(self._waits)
        self._waits.append([name, bound, last])

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _emit(self, step: str, check_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{check_id} printed before step {step} was stamped"
        )
        self._chk_log.append((check_id, step, len(self._stamps)))
        cocotb.log.info(f"{check_id}: {text}", *args)

    def _irq0(self) -> int:
        return _level(cocotb.top.tb_telemetry_irq) & 1

    async def _wait_irq0(self, want: int, label: str) -> int:
        self._note_wait(f"irq_{label}", f"{IRQ_WAIT_BOUND}cycles fail-on-expiry=AssertionError")
        for cycle in range(IRQ_WAIT_BOUND + 1):
            if self._irq0() == want:
                self._note_wait(f"irq_{label}", "", f"irq[0]={want} after {cycle} cycles")
                return cycle
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: tb_telemetry_irq[0] stayed {self._irq0()} for {IRQ_WAIT_BOUND} "
            f"clk_smc_i cycles, want {want}"
        )

    async def _hold_irq0(self, want: int, cycles: int, label: str) -> None:
        for cycle in range(cycles):
            assert self._irq0() == want, (
                f"{label}: tb_telemetry_irq[0] left {want} after {cycle} of {cycles} cycles"
            )
            await RisingEdge(cocotb.top.clk_smc_i)

    async def _wait_buffer(self, empty: bool, label: str) -> int:
        self._note_wait(
            f"buffer_poll_{label}", f"{BUFFER_POLL_BOUND}polls fail-on-expiry=AssertionError"
        )
        status = 0
        for polls in range(1, BUFFER_POLL_BOUND + 1):
            status = await self.csr_read(f"TELEMETRY_STATUS_{label}", STATUS)
            if bool(status & BUFFER_EMPTY_BM) == empty:
                self._note_wait(
                    f"buffer_poll_{label}", "", f"STATUS=0x{status:08x} after {polls} polls"
                )
                return polls
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: STATUS.BUFFER_EMPTY never reached {int(empty)} over "
            f"{BUFFER_POLL_BOUND} polls (last STATUS=0x{status:08x})"
        )

    async def _flush_and_wait(self, label: str) -> None:
        await self.csr_write(f"{label}_FLUSH", CTRL, CTRL_FLUSH)
        await self._wait_buffer(True, f"{label}_FLUSHED")

    async def _read_data(self, label: str) -> int:
        return await self.csr_read(f"{label}_DATA", TELEMETRY_DATA)

    async def _drain_one(self, beat: Beat, label: str) -> int:
        """Read `beat` once it has crossed, then require an empty FIFO; returns the polls."""
        polls = await self._wait_buffer(False, label)
        await self.csr_read(f"{label}_DATA", TELEMETRY_DATA, expected=_word(beat))
        await self.csr_read(f"{label}_DATA_EMPTY", TELEMETRY_DATA, expected=0)
        await self.csr_read(f"{label}_STATUS_EMPTY", STATUS, expected=BUFFER_EMPTY_BM)
        return polls

    async def body(self) -> None:
        dut = cocotb.top
        for pin in ("tb_telemetry0_atvalid", "tb_telemetry0_atready", "tb_telemetry_irq"):
            assert hasattr(dut, pin), f"{pin} missing from the bench top"
        self._note_wait(
            "sep_in_access", f"{self.cfg.axi_timeout_ns}ns driver bound fail-on-expiry=driver raise"
        )
        self._note_wait(
            "fuse_sense", f"{FUSE_SENSE_MAX_CYCLES}cycles fail-on-expiry=AssertionError"
        )

        # S1: setup
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._note_wait("fuse_sense", "", "tb_rst_warm_smc_clk_n high")
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)
        await self._flush_and_wait("SETUP")
        await self.csr_write("SETUP_INTR_ENABLE", INTR_ENABLE, 0)
        await self.csr_write("SETUP_INTR_TEST", INTR_TEST, 0)
        self._stamp("S1")

        # S2: populated flush
        await _HeldSource(dut, POPULATE_BEATS).task
        await wait_more_than(self, "POPULATE", len(POPULATE_BEATS) - 1)
        await self.csr_write("POP_THRESHOLD", CTRL, CTRL_THRESHOLD)
        await self.csr_write("POP_INTR_ENABLE", INTR_ENABLE, ENABLE_THRESHOLD_BM)
        status_before = await self.csr_read("POP_STATUS_BEFORE", STATUS)
        assert not status_before & BUFFER_EMPTY_BM, f"STATUS 0x{status_before:x} before the flush"
        intr = await self.csr_read("POP_INTR_BEFORE", INTR_STATUS)
        assert intr & INTR_THRESHOLD_BM, f"three beats above threshold 1: INTR_STATUS 0x{intr:x}"
        await self._wait_irq0(1, "populated_rise")
        await self.csr_write("POP_FLUSH", CTRL, CTRL_FLUSH)
        polls = await self._wait_buffer(True, "POP_FLUSHED")
        after = await self._read_data("POP_AFTER")
        assert after == 0, f"TELEMETRY_DATA after the flush reads 0x{after:08x}"
        intr = await self.csr_read("POP_INTR_AFTER", INTR_STATUS)
        assert not intr & INTR_THRESHOLD_BM, f"INTR_STATUS.BUFFER_THRESHOLD still set (0x{intr:x})"
        await self._wait_irq0(0, "populated_fall")
        await self.csr_write("POP_INTR_DISABLE", INTR_ENABLE, 0)
        self._stamp("S2")
        self._emit(
            "S2",
            "CHK-TELEMETRY-RX-FLUSH-EMPTIES",
            "three beats gave STATUS 0x%08x, INTR_STATUS BUFFER_THRESHOLD 1 and irq[0] 1; after "
            "one flush BUFFER_EMPTY 1 in %d poll(s) (bound %d), TELEMETRY_DATA 0, "
            "BUFFER_THRESHOLD 0 and irq[0] 0",
            status_before,
            polls,
            BUFFER_POLL_BOUND,
        )

        # S3: one-shot
        ctrl_after = await self.csr_read("ONE_SHOT_CTRL", CTRL)
        assert not ctrl_after & RX_FLUSH_BM, f"CTRL.TELEMETRY_RX_FLUSH reads 1 (0x{ctrl_after:x})"
        ctrl_reads = [ctrl_after]
        for repeat in range(2):
            if repeat:
                await self._hold_irq0(0, QUIET_CYCLES, "one_shot_quiet")
            await self.csr_write(f"ONE_SHOT_FLUSH_{repeat}", CTRL, CTRL_FLUSH)
            await self._wait_buffer(True, f"ONE_SHOT_{repeat}")
            data = await self._read_data(f"ONE_SHOT_{repeat}")
            assert data == 0, f"TELEMETRY_DATA after an empty flush: 0x{data:08x}"
            intr = await self.csr_read(f"ONE_SHOT_INTR_{repeat}", INTR_STATUS)
            assert not intr & INTR_THRESHOLD_BM, f"an empty flush raised INTR_STATUS 0x{intr:x}"
            ctrl = await self.csr_read(f"ONE_SHOT_CTRL_{repeat}", CTRL)
            assert not ctrl & RX_FLUSH_BM, f"CTRL.TELEMETRY_RX_FLUSH reads 1 (0x{ctrl:x})"
            ctrl_reads.append(ctrl)
        await _HeldSource(dut, [ONE_SHOT_BEAT]).task
        await self._drain_one(ONE_SHOT_BEAT, "ONE_SHOT_AFTER")
        self._stamp("S3")
        self._emit(
            "S3",
            "CHK-TELEMETRY-RX-FLUSH-ONE-SHOT",
            "CTRL bit 4 read 0 after the flush and after two further flushes (CTRL reads %s; "
            "TELEMETRY_RX_FLUSH is sw=w in the RDL, so the read is 0); each empty flush left "
            "BUFFER_EMPTY 1, TELEMETRY_DATA 0 and no interrupt source, and a beat sent after the "
            "repeated flushes read back as 0x%08x, the only beat in the FIFO",
            [hex(word) for word in ctrl_reads],
            _word(ONE_SHOT_BEAT),
        )

        # S4: restart
        await _HeldSource(dut, [RESTART_BEAT]).task
        polls = await self._drain_one(RESTART_BEAT, "RESTART")
        self._stamp("S4")
        self._emit(
            "S4",
            "CHK-TELEMETRY-RX-FLUSH-RESTART",
            "a beat sent after the flush cleared BUFFER_EMPTY in %d poll(s) (bound %d) and "
            "TELEMETRY_DATA read 0x%08x, then 0",
            polls,
            BUFFER_POLL_BOUND,
            _word(RESTART_BEAT),
        )

        # S5: beats around the pulse
        self._note_wait(
            "beats_around_in_flight", f"{BUFFER_POLL_BOUND}cycles fail-on-expiry=AssertionError"
        )
        source = _HeldSource(dut, AROUND_BEATS)
        for _ in range(BUFFER_POLL_BOUND):
            if source.sent >= IN_FLIGHT_BEATS:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError(f"only {source.sent} beats accepted in {BUFFER_POLL_BOUND} cycles")
        in_flight = source.sent
        self._note_wait("beats_around_in_flight", "", f"{in_flight} beats accepted before write")
        await self.csr_write("BEATS_FLUSH", CTRL, CTRL_FLUSH)
        at_write = source.sent
        assert at_write < len(AROUND_BEATS), (
            f"all {len(AROUND_BEATS)} beats were accepted before the flush write returned; "
            f"none is certain to arrive after the flush"
        )
        await source.task
        await ClockCycles(dut.clk_smc_i, QUIET_CYCLES)
        survivors: list[Beat] = []
        for _ in range(len(AROUND_BEATS) + 1):
            word = await self._read_data(f"BEATS_TAIL_{len(survivors)}")
            if word == 0:
                break
            assert word & VALID_BM, f"BEATS: read 0x{word:08x} has VALID clear"
            survivors.append(_beat(word))
        dropped = len(AROUND_BEATS) - len(survivors)
        assert survivors == AROUND_BEATS[dropped:], (
            f"the {len(survivors)} beats read after the flush are not the contiguous tail of "
            f"the stream: {survivors}"
        )
        assert dropped, "the flush written with beats queued discarded none of them"
        assert len(survivors) >= len(AROUND_BEATS) - at_write, (
            f"{len(AROUND_BEATS) - at_write} beats were accepted after the flush write returned, "
            f"but only {len(survivors)} read back"
        )
        await self._flush_and_wait("BEATS")
        await _HeldSource(dut, [AROUND_RECOVERY_BEAT]).task
        polls = await self._drain_one(AROUND_RECOVERY_BEAT, "BEATS_NEXT")
        self._stamp("S5")
        self._emit(
            "S5",
            "CHK-TELEMETRY-RX-FLUSH-BEATS-AROUND",
            "%d beats accepted before the flush write and %d when it returned, of %d offered; "
            "after %d quiet cycles the %d beats read back were the contiguous tail of the stream "
            "in order, every beat accepted after the write returned among them (%d discarded); "
            "after one quiet flush the next beat read back alone in %d poll(s)",
            in_flight,
            at_write,
            len(AROUND_BEATS),
            QUIET_CYCLES,
            len(survivors),
            dropped,
            polls,
        )

        # S6: flush against an INTR_TEST force
        await _HeldSource(dut, FORCE_BEATS).task
        await wait_more_than(self, "FORCE", len(FORCE_BEATS) - 1)
        await self.csr_write("FORCE_INTR_ENABLE", INTR_ENABLE, ENABLE_THRESHOLD_BM)
        await self.csr_write("FORCE_INTR_TEST", INTR_TEST, TEST_THRESHOLD_BM)
        await self._wait_irq0(1, "force_rise")
        await self.csr_write("FORCE_FLUSH", CTRL, RX_FLUSH_BM)
        await self._wait_buffer(True, "FORCE_FLUSHED")
        intr_flush = await self.csr_read("FORCE_INTR_FLUSH", INTR_STATUS)
        assert intr_flush & INTR_THRESHOLD_BM, (
            f"the flush released the INTR_TEST force (INTR_STATUS 0x{intr_flush:x})"
        )
        test_flush = await self.csr_read("FORCE_TEST_FLUSH", INTR_TEST, expected=TEST_THRESHOLD_BM)
        await self._hold_irq0(1, QUIET_CYCLES, "force_hold")
        await self.csr_write("FORCE_INTR_TEST_RELEASE", INTR_TEST, 0)
        intr_clear = await self.csr_read("FORCE_INTR_RELEASED", INTR_STATUS)
        assert not intr_clear & INTR_THRESHOLD_BM, (
            f"INTR_TEST written to 0 left BUFFER_THRESHOLD set (0x{intr_clear:x})"
        )
        await self._wait_irq0(0, "force_fall")
        await self.csr_write("FORCE_INTR_DISABLE", INTR_ENABLE, 0)
        await self.csr_read("END_DATA", TELEMETRY_DATA, expected=0)
        self._stamp("S6")
        self._emit(
            "S6",
            "CHK-TELEMETRY-RX-FLUSH-KEEPS-TEST-FORCE",
            "with INTR_TEST.BUFFER_THRESHOLD written to 1 and %d beats queued, "
            "CTRL.TELEMETRY_RX_FLUSH emptied the FIFO while INTR_STATUS read 0x%x and INTR_TEST "
            "0x%x, and irq[0] stayed 1 for %d cycles; INTR_TEST written to 0 released it "
            "(INTR_STATUS 0x%x) and irq[0] fell",
            len(FORCE_BEATS),
            intr_flush,
            test_flush,
            QUIET_CYCLES,
            intr_clear,
        )

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original_cg)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORE_RB", CLOCK_GATE_CONTROL, expected=original_cg
        )

        self._finish()

    def _finish(self) -> None:
        steps = [step for step, _ in self._stamps]
        assert steps == list(STEP_ORDER), f"step stamps {steps} differ from {list(STEP_ORDER)}"
        times = [ps for _, ps in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = [check for check, _, _ in self._chk_log]
        expected = [CHECKER_FOR_STEP[s] for s in STEP_ORDER[1:]]
        assert printed == expected, f"checker lines {printed} differ from {expected}"
        for check, step, stamps_seen in self._chk_log:
            assert stamps_seen == STEP_ORDER.index(step) + 1, (
                f"{check} printed with {stamps_seen} steps stamped, not after {step}"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ",".join(printed),
            ",".join(f"{s}={ps}" for s, ps in self._stamps),
        )
        self._note_wait("sep_in_access", "", f"{self.accesses} accesses completed")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={last}" for n, b, last in self._waits),
        )
