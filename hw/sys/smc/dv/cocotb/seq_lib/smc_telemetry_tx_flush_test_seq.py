# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry transmitter flush on receiver 0.

Sources: hw/ip/telemetry_receiver/doc/architecture.adoc (Reset and Flush), doc/interface.adoc,
hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl, doc/programmer/src/smc-programming.adoc.
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
    INTR_STATUS,
    INTR_THRESHOLD_BM,
    RX_FLUSH_BM,
    STATUS,
    TELEMETRY_DATA,
    THRESHOLD_BP,
    TX_FLUSH_BM,
    _HeldSource,
    _word,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

THRESHOLD = 3
CTRL_THRESHOLD_ONLY = THRESHOLD << THRESHOLD_BP
# BUFFER_THRESHOLD 1 raises INTR_STATUS.BUFFER_THRESHOLD once more than one beat is queued
# (telemetry_receiver.rdl), which is how the path-separation leg knows both beats are in.
CTRL_THRESHOLD_ONE = 1 << THRESHOLD_BP
CTRL_THRESHOLD_PENDING = CTRL_THRESHOLD_ONLY | TX_FLUSH_BM

FIRST_BEAT = (0x33, 0x0B)
SECOND_BEAT = (0x34, 0x0C)
DISCARD_BEAT = (0x35, 0x0D)

HOLD_CYCLES = 2048
CTRL_SAMPLE_PERIOD = 64
HANDSHAKE_BOUND = 64
RX_FLUSH_QUIET_CYCLES = 64
BUFFER_POLL_BOUND = 200
FUSE_SENSE_MAX_CYCLES = 200_000

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6")
FENCE_TERMS = (
    "SETUP_DONE",
    "READY_HIGH_DONE",
    "LONG_HOLD_DONE",
    "REWRITE_DONE",
    "THRESHOLD_KEPT",
    "PATHS_SEPARATED",
)
CHECKER_FOR_STEP = {
    "S2": "CHK-TELEMETRY-TX-FLUSH-READY-HIGH",
    "S3": "CHK-TELEMETRY-TX-FLUSH-PENDING-HOLD",
    "S4": "CHK-TELEMETRY-TX-FLUSH-REWRITE",
    "S5": "CHK-TELEMETRY-TX-FLUSH-THRESHOLD-KEPT",
    "S6": "CHK-TELEMETRY-FLUSH-PATH-SEPARATION",
}


def _level(signal) -> int:
    raw = signal.value
    assert raw.is_resolvable, f"{signal._name} is X/Z: {raw}"
    return int(raw)


class _AfvalidMonitor:
    """Samples afvalid_o on every clk_smc_i rising edge until stopped."""

    def __init__(self, dut, signal) -> None:
        self._dut = dut
        self._signal = signal
        self.samples = 0
        self.rises = 0
        self.low_samples = 0
        self.unresolved: str | None = None
        self.last: int | None = None
        self.first_rise_at: int | None = None
        self.fall_at: int | None = None
        self._running = True
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        raw = self._signal.value
        prev = int(raw) if raw.is_resolvable else None
        while self._running:
            await RisingEdge(self._dut.clk_smc_i)
            raw = self._signal.value
            if not raw.is_resolvable:
                self.unresolved = str(raw)
                continue
            now = int(raw)
            self.samples += 1
            if now == 0:
                self.low_samples += 1
            if now == 1 and prev == 0:
                self.rises += 1
                if self.first_rise_at is None:
                    self.first_rise_at = self.samples
            if now == 0 and prev == 1 and self.fall_at is None and self.first_rise_at:
                self.fall_at = self.samples
            prev = now
            self.last = now

    def stop(self) -> None:
        self._running = False
        self._task.cancel()

    def check(self, label: str) -> None:
        assert self.unresolved is None, f"{label}: afvalid_o X/Z sample {self.unresolved}"


class smc_telemetry_tx_flush_test_seq(SmcCsrSeq):
    """Drive the transmitter flush request through the AF handshake on receiver 0."""

    def __init__(self, name: str = "smc_telemetry_tx_flush_test_seq") -> None:
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

    async def _await_afvalid(self, dut, want: int, label: str, bound: int = HANDSHAKE_BOUND) -> int:
        signal = dut.tb_telemetry0_afvalid
        self._note_wait(label, f"{bound}cycles fail-on-expiry=AssertionError")
        if _level(signal) == want:
            self._note_wait(label, "", f"afvalid_o={want} after 0 cycles")
            return 0
        for cycle in range(1, bound + 1):
            await RisingEdge(dut.clk_smc_i)
            if _level(signal) == want:
                self._note_wait(label, "", f"afvalid_o={want} after {cycle} cycles")
                return cycle
        raise AssertionError(
            f"{label}: afvalid_o stayed {_level(signal)} for {bound} clk_smc_i cycles, want {want}"
        )

    async def _wait_threshold(self, label: str) -> int:
        """Poll INTR_STATUS until BUFFER_THRESHOLD is set.

        The bit sets once more beats are queued than CTRL's threshold.
        """
        self._note_wait(
            f"threshold_poll_{label}", f"{BUFFER_POLL_BOUND}polls fail-on-expiry=AssertionError"
        )
        intr = 0
        for polls in range(1, BUFFER_POLL_BOUND + 1):
            intr = await self.csr_read(f"TELEMETRY_INTR_{label}", INTR_STATUS)
            if intr & INTR_THRESHOLD_BM:
                self._note_wait(
                    f"threshold_poll_{label}", "", f"INTR_STATUS=0x{intr:08x} after {polls} polls"
                )
                return polls
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: INTR_STATUS.BUFFER_THRESHOLD never set over {BUFFER_POLL_BOUND} polls "
            f"(last INTR_STATUS=0x{intr:08x}): the second beat did not reach the FIFO"
        )

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

    async def body(self) -> None:
        dut = cocotb.top
        for pin in ("tb_telemetry0_afvalid", "tb_telemetry0_afready", "tb_telemetry0_atvalid"):
            assert hasattr(dut, pin), f"{pin} missing from the bench top"
        afready = dut.tb_telemetry0_afready
        afvalid = dut.tb_telemetry0_afvalid
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
        afready.value = 1
        await ClockCycles(dut.clk_smc_i, 1)
        assert _level(afvalid) == 0, "telemetry afvalid_o is not idle at 0 after setup"
        self._stamp("S1")

        # S2: request with afready_i high
        monitor = _AfvalidMonitor(dut, afvalid)
        self._note_wait(
            "ready_high_afvalid_pulse",
            f"{HANDSHAKE_BOUND}cycles rise + {HANDSHAKE_BOUND}cycles fall fail-on-expiry="
            "AssertionError",
        )
        await self.csr_write("TX_FLUSH_READY_HIGH", CTRL, TX_FLUSH_BM)
        while monitor.first_rise_at is None and monitor.samples < HANDSHAKE_BOUND:
            await RisingEdge(dut.clk_smc_i)
        monitor.check("ready_high")
        assert monitor.first_rise_at is not None, (
            f"afvalid_o never rose within {HANDSHAKE_BOUND} cycles of the request "
            f"(last={monitor.last})"
        )
        rise = monitor.first_rise_at
        while monitor.fall_at is None and monitor.samples < rise + HANDSHAKE_BOUND:
            await RisingEdge(dut.clk_smc_i)
        monitor.stop()
        monitor.check("ready_high")
        assert monitor.fall_at is not None, (
            f"afvalid_o never fell within {HANDSHAKE_BOUND} cycles of rising (last={monitor.last})"
        )
        fall = monitor.fall_at - rise
        self._note_wait(
            "ready_high_afvalid_pulse", "", f"rise={rise} fall_after={fall} last={monitor.last}"
        )
        ctrl = await self.csr_read("TX_FLUSH_READY_HIGH_DONE", CTRL)
        assert ctrl & TX_FLUSH_BM == 0, f"CTRL.TELEMETRY_TX_FLUSH still set (CTRL=0x{ctrl:08x})"
        self._stamp("S2")
        self._emit(
            "S2",
            "CHK-TELEMETRY-TX-FLUSH-READY-HIGH",
            "afready_i high: afvalid_o rose %d cycle(s) after the CTRL write was issued and "
            "fell %d cycle(s) later, bounds %d each, CTRL read 0x%08x (bit 8 clear)",
            rise,
            fall,
            HANDSHAKE_BOUND,
            ctrl,
        )

        # S3: long hold
        afready.value = 0
        await self.csr_write("TX_FLUSH_HOLD", CTRL, TX_FLUSH_BM)
        hold_rise = await self._await_afvalid(dut, 1, "hold_afvalid_rise")
        monitor = _AfvalidMonitor(dut, afvalid)
        ctrl_reads = 0
        self._note_wait(
            "hold_window", f"{HOLD_CYCLES}cycles fail-on-drop=AssertionError", "not-ended"
        )
        while monitor.samples < HOLD_CYCLES:
            ctrl = await self.csr_read("TX_FLUSH_HOLD_CTRL", CTRL)
            ctrl_reads += 1
            monitor.check("hold")
            assert monitor.low_samples == 0, (
                f"afvalid_o dropped during the hold after {monitor.samples} cycles "
                f"(last={monitor.last})"
            )
            assert ctrl & TX_FLUSH_BM, (
                f"CTRL.TELEMETRY_TX_FLUSH cleared early after {monitor.samples} cycles "
                f"(CTRL=0x{ctrl:08x})"
            )
            await ClockCycles(dut.clk_smc_i, CTRL_SAMPLE_PERIOD)
        monitor.stop()
        monitor.check("hold")
        assert monitor.low_samples == 0, (
            f"afvalid_o dropped during the hold (samples={monitor.samples}, last={monitor.last})"
        )
        self._note_wait("hold_window", "", f"afvalid_o=1 for {monitor.samples} samples")
        afready.value = 1
        hold_fall = await self._await_afvalid(dut, 0, "hold_afvalid_fall")
        ctrl = await self.csr_read("TX_FLUSH_HOLD_DONE", CTRL)
        assert ctrl & TX_FLUSH_BM == 0, f"CTRL.TELEMETRY_TX_FLUSH still set (CTRL=0x{ctrl:08x})"
        self._stamp("S3")
        self._emit(
            "S3",
            "CHK-TELEMETRY-TX-FLUSH-PENDING-HOLD",
            "afready_i low: afvalid_o rose after %d cycle(s) and stayed 1 on %d consecutive cycle "
            "samples with CTRL bit 8 = 1 on %d reads (every ~%d cycles); after afready_i high "
            "afvalid_o fell in %d cycle(s) (bound %d) and CTRL read 0x%08x",
            hold_rise,
            monitor.samples,
            ctrl_reads,
            CTRL_SAMPLE_PERIOD,
            hold_fall,
            HANDSHAKE_BOUND,
            ctrl,
        )

        # S4: second write while pending
        afready.value = 0
        monitor = _AfvalidMonitor(dut, afvalid)
        await self.csr_write("TX_FLUSH_REWRITE_FIRST", CTRL, TX_FLUSH_BM)
        await self._await_afvalid(dut, 1, "rewrite_afvalid_rise")
        await self.csr_write("TX_FLUSH_REWRITE_SECOND", CTRL, TX_FLUSH_BM)
        pending = await self.csr_read("TX_FLUSH_REWRITE_PENDING", CTRL)
        assert pending & TX_FLUSH_BM, (
            f"CTRL.TELEMETRY_TX_FLUSH clear after the second write with afready_i low "
            f"(CTRL=0x{pending:08x})"
        )
        assert _level(afvalid) == 1, "afvalid_o low after the second write with afready_i low"
        monitor.check("rewrite")
        afready.value = 1
        rewrite_fall = await self._await_afvalid(dut, 0, "rewrite_afvalid_fall")
        ctrl = await self.csr_read("TX_FLUSH_REWRITE_DONE", CTRL)
        monitor.stop()
        monitor.check("rewrite")
        assert ctrl & TX_FLUSH_BM == 0, f"CTRL.TELEMETRY_TX_FLUSH still set (CTRL=0x{ctrl:08x})"
        assert _level(afvalid) == 0, "afvalid_o high after the rewrite completed"
        self._stamp("S4")
        self._emit(
            "S4",
            "CHK-TELEMETRY-TX-FLUSH-REWRITE",
            "second write while pending (CTRL read 0x%08x): completion %d cycle(s) after afready_i "
            "high (bound %d) with afvalid_o 0 and CTRL 0x%08x; afvalid_o rising edges counted "
            "from the first write to completion: %d (not compared)",
            pending,
            rewrite_fall,
            HANDSHAKE_BOUND,
            ctrl,
            monitor.rises,
        )

        # S5: threshold kept
        afready.value = 0
        await self.csr_write("TX_FLUSH_THRESHOLD_WR", CTRL, CTRL_THRESHOLD_PENDING)
        await self._await_afvalid(dut, 1, "threshold_afvalid_rise")
        await self.csr_read("TX_FLUSH_THRESHOLD_PENDING", CTRL, expected=CTRL_THRESHOLD_PENDING)
        afready.value = 1
        await self._await_afvalid(dut, 0, "threshold_afvalid_fall")
        await self.csr_read("TX_FLUSH_THRESHOLD_KEPT", CTRL, expected=CTRL_THRESHOLD_ONLY)
        self._stamp("S5")
        self._emit(
            "S5",
            "CHK-TELEMETRY-TX-FLUSH-THRESHOLD-KEPT",
            "CTRL read 0x%08x while pending and exactly 0x%08x after the hardware clear "
            "(threshold %d kept)",
            CTRL_THRESHOLD_PENDING,
            CTRL_THRESHOLD_ONLY,
            THRESHOLD,
        )

        # S6: path separation
        await self.csr_write("TX_FLUSH_THRESHOLD_ONE", CTRL, CTRL_THRESHOLD_ONE)
        afready.value = 0
        await _HeldSource(dut, [FIRST_BEAT, SECOND_BEAT]).task
        await self._wait_buffer(False, "QUEUED")
        queued_polls = await self._wait_threshold("TWO_QUEUED")
        await self.csr_write("TX_FLUSH_PATHS", CTRL, TX_FLUSH_BM)
        await self._await_afvalid(dut, 1, "paths_afvalid_rise")
        afready.value = 1
        await self._await_afvalid(dut, 0, "paths_afvalid_fall")
        await self.csr_read("TX_FLUSH_PATHS_DONE", CTRL, expected=0)
        status = await self.csr_read("TX_FLUSH_PATHS_STATUS", STATUS)
        assert status & BUFFER_EMPTY_BM == 0, (
            f"transmitter flush emptied the FIFO (STATUS=0x{status:08x})"
        )
        first = await self.csr_read("TX_FLUSH_PATHS_DATA", TELEMETRY_DATA)
        assert first == _word(FIRST_BEAT), (
            f"TELEMETRY_DATA after the transmitter flush is 0x{first:08x}, want "
            f"0x{_word(FIRST_BEAT):08x}"
        )
        second = await self.csr_read("TX_FLUSH_PATHS_DATA_2", TELEMETRY_DATA)
        assert second == _word(SECOND_BEAT), (
            f"TELEMETRY_DATA after the first beat is 0x{second:08x}, want "
            f"0x{_word(SECOND_BEAT):08x}: the transmitter flush dropped the second beat"
        )
        await _HeldSource(dut, [DISCARD_BEAT]).task
        await self._wait_buffer(False, "DISCARD_QUEUED")
        afready.value = 0
        monitor = _AfvalidMonitor(dut, afvalid)
        self._note_wait(
            "rx_flush_quiet", f"{RX_FLUSH_QUIET_CYCLES}cycles fail-on-rise=AssertionError"
        )
        await self.csr_write("RX_FLUSH_PATHS", CTRL, RX_FLUSH_BM)
        polls = await self._wait_buffer(True, "RX_FLUSH")
        await self.csr_read("RX_FLUSH_PATHS_DATA", TELEMETRY_DATA, expected=0)
        while monitor.samples < RX_FLUSH_QUIET_CYCLES:
            await RisingEdge(dut.clk_smc_i)
        monitor.stop()
        monitor.check("rx_flush")
        assert monitor.rises == 0 and monitor.low_samples == monitor.samples, (
            f"afvalid_o rose during the receiver flush (samples={monitor.samples}, "
            f"rises={monitor.rises}, last={monitor.last})"
        )
        self._note_wait(
            "rx_flush_quiet", "", f"afvalid_o 0 for {monitor.samples} samples, STATUS empty"
        )
        await self.csr_write("RX_FLUSH_PATHS_CLEAR", CTRL, 0)
        afready.value = 1
        self._stamp("S6")
        self._emit(
            "S6",
            "CHK-TELEMETRY-FLUSH-PATH-SEPARATION",
            "two beats queued (threshold 1 interrupt after %d poll(s)); after a transmitter flush "
            "TELEMETRY_DATA returned both, 0x%08x then 0x%08x; a third beat queued afterwards was "
            "discarded by a receiver flush, which emptied the FIFO in %d poll(s) with afvalid_o "
            "0 on %d consecutive samples (rises %d)",
            queued_polls,
            first,
            second,
            polls,
            monitor.samples,
            monitor.rises,
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
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={last}" for n, b, last in self._waits),
        )
