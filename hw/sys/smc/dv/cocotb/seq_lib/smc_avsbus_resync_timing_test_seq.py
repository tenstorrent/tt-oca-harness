# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus slave resync after a cold reset: length, interval, status flags and the FSM probe.

Contract SMC_POWER_AVS_010, anchor smc_avsbus_resync_timing_test.
Scenarios: AVS-RESYNC.S1-S5, AVS-RESYNC.S10, AVS-RESYNC.S11, AVS-FSM-DEBUG.S1, S2 and S6.
Sources: hw/ip/avsbus_controller/doc/{architecture,interface}.adoc, regs/avsbus_controller.rdl.

No AVS_CMD traffic runs except the one command that proves the bus returned to service after
RESYNC_INTERVAL 0. The FSM probe is sampled on every clk_periph_i edge; a state counts once it
holds over two consecutive samples. The interval after a RESYNC_INTERVAL write is measured from
the second resync on, so the value in force is the written one whenever the register domain
picks it up (SF-014). Open findings SF-013, SF-014, SF-015 and SF-030 are measured and printed.
"""

from __future__ import annotations

import bisect
import statistics

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_avsbus_protocol_utils import (
    AVS_BUS_IS_IDLE_BM,
    AVS_CFG_0,
    AVS_CFG_1,
    AVS_CMD,
    AVS_CODE_NAME,
    AVS_FIFOS_STATUS,
    AVS_NORMAL_STATUS,
    AVS_READBACK,
    CMD_TYPE_READ,
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
    READ_CMD_DATA,
    READBACK_HAS_DATA_BM,
    RESYNC_INTERVAL_BM,
    STOP_AVS_CLOCK_ON_IDLE_BM,
    avs_field,
    build_avs_cmd,
    fifo_field,
    set_avs_sdata,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

IN_RESYNC_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__AVS_SLAVE_IS_IN_RESYNC_bm")
INTERVAL_RESET = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__RESYNC_INTERVAL_reset")
INTERVAL_SMALL = 0x0040
INTERVAL_MID = 0x0400
RESYNC_CYCLES = 35
SYNC_STAGES = 3

CMD_AFTER_ZERO = build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x1, READ_CMD_DATA)

#: Bound on every probe wait, in clk_periph_i cycles.
STATE_WAIT_CYCLES = 50_000
#: Bound on every register poll: attempts, each followed by POLL_CYCLES clk_smc_i cycles.
POLL_LIMIT = 400
POLL_CYCLES = 50
#: Bound on the flag polling loop, in AVS_NORMAL_STATUS reads.
FLAG_POLL_LIMIT = 4000
#: Reads taken in AVS_IDLE after the observed episode before the flag loop ends.
POST_IDLE_POLLS = 6

IDLE = "AVS_IDLE"
RESYNC = "AVS_SLAVE_RESYNC"
RESET = "AVS_RESET"
RESET_CODE = 1 << 0
RESYNC_CODE = 1 << 1
IDLE_CODE = 1 << 3


class _Probes:
    """Passive recorders: FSM probe, mdata pin and avs_clock_o rising edges."""

    def __init__(self) -> None:
        self.events: list[tuple[int, str]] = []
        self.episodes: list[list[int | None]] = []
        self.current = "unseen"
        self.t_ps: list[int] = []
        self.codes: list[int] = []
        self.mdata: list[int] = []
        self.edges_ps: list[int] = []
        self.bad_samples = 0
        self.reset_zero_samples = 0
        self.zero_run = 0
        self.first_bad = ""
        self.fault: str | None = None
        self._tasks: list = []

    @property
    def samples(self) -> int:
        return len(self.t_ps)

    def start(self) -> None:
        self._tasks = [cocotb.start_soon(self._fsm()), cocotb.start_soon(self._clock())]

    def stop(self) -> None:
        for task in self._tasks:
            task.kill()
        self._tasks = []

    async def _fsm(self) -> None:
        dut = cocotb.top
        previous = None
        while True:
            await RisingEdge(dut.clk_periph_i)
            raw = dut.tb_avsbus_cur_state_debug.value
            pin = dut.tb_avs_mdata_from_dut.value
            if not raw.is_resolvable or not pin.is_resolvable:
                self.fault = f"probe or mdata is X/Z: probe={raw} mdata={pin}"
                return
            code = int(raw)
            now = int(get_sim_time("ps"))
            self.t_ps.append(now)
            self.codes.append(code)
            self.mdata.append(int(pin))
            if code == 0:
                self.zero_run += 1
            else:
                if self.zero_run:
                    if code == RESET_CODE:
                        self.reset_zero_samples += self.zero_run
                    else:
                        self._flag(f"{self.zero_run} zero samples ended by 0x{code:05x}", now)
                    self.zero_run = 0
                if bin(code).count("1") != 1:
                    self._flag(f"0x{code:05x}", now)
            if code == previous:
                name = AVS_CODE_NAME.get(code, f"0x{code:x}")
                if name != self.current:
                    self.current = name
                    self.events.append((now, name))
                    if name == RESYNC:
                        self.episodes.append([now, None])
                    elif self.episodes and self.episodes[-1][1] is None:
                        self.episodes[-1][1] = now
            previous = code

    def _flag(self, text: str, now: int) -> None:
        self.bad_samples += 1
        if not self.first_bad:
            self.first_bad = f"{text} at {now} ps"

    async def _clock(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.tb_avs_clk_from_dut)
            self.edges_ps.append(int(get_sim_time("ps")))


class smc_avsbus_resync_timing_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Cold reset, resync shape, flags, intervals, interval 0 and a mid-count rewrite."""

    def __init__(self, name: str = "smc_avsbus_resync_timing_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.probes = _Probes()
        self.waits: list[tuple[str, int, str]] = []
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []
        self.t_avs_ns = 0.0
        self.t_reg_ns = 0.0

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, step, int(get_sim_time("ps"))))

    def _last(self) -> str:
        return (
            f"episodes={len(self.probes.episodes)} state={self.probes.current} "
            f"samples={self.probes.samples}"
        )

    def _check_probe(self) -> None:
        assert self.probes.fault is None, self.probes.fault
        assert self.probes.bad_samples == 0, (
            f"{self.probes.bad_samples} probe samples without exactly one bit set, "
            f"first {self.probes.first_bad}"
        )

    async def _wait_probe(self, name: str, cond) -> None:
        for _ in range(STATE_WAIT_CYCLES):
            self._check_probe()
            if cond():
                self.waits.append((name, STATE_WAIT_CYCLES, self._last()))
                return
            await RisingEdge(cocotb.top.clk_periph_i)
        raise AssertionError(
            f"{name}: not met within {STATE_WAIT_CYCLES} clk_periph_i cycles; {self._last()}"
        )

    def _complete(self, index: int) -> bool:
        return len(self.probes.episodes) > index and self.probes.episodes[index][1] is not None

    async def _fresh_episode(self, name: str) -> int:
        """Index of the next episode to start and finish after now."""
        index = len(self.probes.episodes)
        await self._wait_probe(name, lambda: self._complete(index))
        return index

    async def _period_after(self, label: str, discard: bool) -> tuple[float, int]:
        """Time in ns from the end of one resync to the start of the next, and the first index."""
        if discard:
            first = await self._fresh_episode(f"{label}_DISCARD_EPISODE")
        else:
            first = len(self.probes.episodes) - 1
            assert self._complete(first), f"{label}: no completed episode to measure from"
        await self._wait_probe(
            f"{label}_NEXT_RESYNC", lambda: len(self.probes.episodes) > first + 1
        )
        return float(self.probes.episodes[first + 1][0] - self.probes.episodes[first][1]), first

    async def _occupancy(self, label: str) -> int:
        fifos = await self.csr_read(label, AVS_FIFOS_STATUS)
        return fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)

    async def _await_reply(self, name: str) -> int:
        occupied = 0
        for _ in range(POLL_LIMIT):
            occupied = await self._occupancy(f"{name}_FIFOS")
            if occupied >= 1:
                self.waits.append((name, POLL_LIMIT * POLL_CYCLES, f"occupied={occupied}"))
                return occupied
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{name}: no reply after {POLL_LIMIT} polls; {self._last()}")

    async def _drain_readback(self, label: str) -> int:
        drained = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_STATUS", AVS_NORMAL_STATUS)
            if not status & READBACK_HAS_DATA_BM:
                self.waits.append((f"{label}_DRAIN", POLL_LIMIT, f"drained={drained}"))
                return drained
            await self.csr_read(f"{label}_READBACK", AVS_READBACK)
            drained += 1
        raise AssertionError(f"{label}: readback FIFO never emptied; {self._last()}")

    def _window_codes(self, lo_ps: float, hi_ps: float) -> set[int]:
        i = bisect.bisect_left(self.probes.t_ps, lo_ps)
        j = bisect.bisect_right(self.probes.t_ps, hi_ps)
        return set(self.probes.codes[i:j])

    def _span_samples(self, enter_ps: int, exit_ps: int) -> tuple[int, int]:
        """First and last sample index holding the resync code inside one episode."""
        i = bisect.bisect_left(self.probes.t_ps, enter_ps - self.t_reg_ns * 1000)
        j = bisect.bisect_left(self.probes.t_ps, exit_ps)
        idx = [k for k in range(i, j) if self.probes.codes[k] == RESYNC_CODE]
        assert idx, f"no resync-coded sample between {enter_ps} and {exit_ps} ps"
        return idx[0], idx[-1]

    async def _write_interval(self, label: str, cfg0: int, value: int) -> None:
        word = (cfg0 & ~RESYNC_INTERVAL_BM) | (value & RESYNC_INTERVAL_BM)
        await self.csr_write(f"AVS_CFG_0_{label}", AVS_CFG_0, word)
        await self.csr_read(f"AVS_CFG_0_{label}_RB", AVS_CFG_0, expected=word)

    async def body(self) -> None:
        dut = cocotb.top
        for sig in (
            "tb_avs_clk_from_dut",
            "tb_avs_mdata_from_dut",
            "tb_avs_sdata_ext",
            "tb_avsbus_cur_state_debug",
        ):
            assert hasattr(dut, sig), f"{sig} is not visible on the bench top"
        probes = self.probes

        # S1: SETUP
        set_avs_sdata(0)
        probes.start()
        await self._wait_probe("S1_IDLE_WAIT", lambda: probes.current == IDLE)
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S1")

        # S2: cold reset
        assert hasattr(dut, "rst_cold_ni"), "rst_cold_ni is not visible on the bench top"
        base_e = len(probes.events)
        base_ep = len(probes.episodes)
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "COLD_ASSERT",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("COLD_RELEASE")
        await self._wait_probe(
            "S2_RESYNC_IDLE_WAIT",
            lambda: self._complete(base_ep) and probes.current == IDLE,
        )
        order = []
        for _, name in probes.events[base_e:]:
            if name == "0x0":
                continue
            if not order or order[-1] != name:
                order.append(name)
        assert any(n == RESET for _, n in probes.events[base_e:]), (
            f"AVS_RESET never seen after the cold reset (SF-030: whether it restarts the AVS "
            f"FSM); sequence {'>'.join(order)}"
        )
        assert order[0] == RESET and order[1] == RESYNC, (
            f"states after the cold reset {'>'.join(order)}: AVS_RESET then AVS_SLAVE_RESYNC "
            f"expected first"
        )
        assert IDLE in order and order.index(IDLE) > order.index(RESYNC), (
            f"states after the cold reset {'>'.join(order)}: AVS_IDLE not reached after the resync"
        )
        allowed = (RESET, RESYNC, IDLE, "AVS_LAUNCH_FRAME_POST_RESYNC")
        command_path = [n for n in order if n not in allowed]
        assert not command_path, f"command-path states {command_path} after the cold reset"
        cfg1 = await self.csr_read("AVS_CFG_1_AFTER_RESET", AVS_CFG_1)
        assert not cfg1 & STOP_AVS_CLOCK_ON_IDLE_BM, (
            f"STOP_AVS_CLOCK_ON_IDLE set (AVS_CFG_1=0x{cfg1:08x}): the clock would stop in idle"
        )
        cfg0 = await self.csr_read("AVS_CFG_0_AFTER_RESET", AVS_CFG_0)
        assert cfg0 & RESYNC_INTERVAL_BM == INTERVAL_RESET, (
            f"RESYNC_INTERVAL reads 0x{cfg0 & RESYNC_INTERVAL_BM:04x} after the cold reset, "
            f"reset value 0x{INTERVAL_RESET:04x}"
        )
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S2")
        seq_text = ">".join(order)
        self._chk(
            "S2",
            "CHK-AVS-RESYNC-STARTUP",
            f"after the cold reset with no AVS_CMD written the probe showed AVS_SLAVE_RESYNC "
            f"held before any command-path state and before AVS_IDLE; sequence {seq_text}",
        )
        self._chk(
            "S2",
            "CHK-AVS-FSM-RESET-SEQUENCE",
            f"probe order after rst_cold_ni low and release: {seq_text}; AVS_RESET first, then "
            f"AVS_SLAVE_RESYNC, then AVS_IDLE with nothing queued (cold reset reached the AVS "
            f"FSM, SF-030 observed as AVS_RESET seen)",
        )

        # S3: resync shape
        ts = probes.t_ps
        self.t_reg_ns = (ts[-1] - ts[0]) / (len(ts) - 1) / 1000
        edge_ps = probes.edges_ps
        assert len(edge_ps) > 8, f"only {len(edge_ps)} avs_clock_o edges seen"
        self.t_avs_ns = statistics.median(b - a for a, b in zip(edge_ps, edge_ps[1:])) / 1000
        enter_ps, exit_ps = probes.episodes[base_ep]
        first_i, last_i = self._span_samples(enter_ps, exit_ps)
        span_ns = (exit_ps - enter_ps) / 1000
        periods = span_ns / self.t_avs_ns
        low = [
            k
            for k in range(first_i, last_i + 1)
            if probes.codes[k] == RESYNC_CODE and probes.mdata[k] != 1
        ]
        in_span = sum(1 for k in range(first_i, last_i + 1) if probes.codes[k] == RESYNC_CODE)
        assert not low, f"avs_mdata low at {len(low)} of {in_span} samples inside the resync span"
        assert RESYNC_CYCLES - 1 <= periods <= RESYNC_CYCLES + 1, (
            f"resync span {span_ns:.1f} ns = {periods:.2f} avs_clock_o periods of "
            f"{self.t_avs_ns:.2f} ns, outside 34 to 36"
        )
        lo_i = first_i
        while lo_i > 0 and probes.mdata[lo_i - 1] == 1:
            lo_i -= 1
        hi_i = last_i
        while hi_i + 1 < len(probes.mdata) and probes.mdata[hi_i + 1] == 1:
            hi_i += 1
        run_ns = (hi_i - lo_i + 1) * self.t_reg_ns
        state_ns = (last_i - first_i + 1) * self.t_reg_ns
        run_periods = run_ns / self.t_avs_ns
        state_periods = state_ns / self.t_avs_ns
        assert run_periods > state_periods, (
            f"pin-high run {run_periods:.2f} avs_clock_o periods is not longer than the state "
            f"span {state_periods:.2f}"
        )
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-AVS-RESYNC-LEN35",
            f"first resync after the cold reset: avs_mdata 1 at all {in_span} probe samples "
            f"inside the span; span {span_ns:.1f} ns = {periods:.2f} avs_clock_o periods "
            f"({self.t_avs_ns:.2f} ns each), 35 expected within 1 (SF-015)",
        )
        self._chk(
            "S3",
            "CHK-AVS-RESYNC-PIN-HIGH",
            f"avs_mdata high run around the same episode {run_periods:.2f} avs_clock_o periods "
            f"({first_i - lo_i} samples before the state, {hi_i - last_i} after) against a state "
            f"span of {state_periods:.2f} periods (sampled once per clk_periph_i cycle)",
        )

        # S4: status flags across the next resync episode and the idle around it
        base_ep4 = len(probes.episodes)
        polls: list[tuple[int, int, int]] = []
        post_idle = 0
        for _ in range(FLAG_POLL_LIMIT):
            self._check_probe()
            t_before = int(get_sim_time("ps"))
            status = await self.csr_read("S4_STATUS", AVS_NORMAL_STATUS)
            polls.append((t_before, int(get_sim_time("ps")), status))
            if self._complete(base_ep4) and probes.current == IDLE:
                post_idle += 1
                if post_idle >= POST_IDLE_POLLS:
                    break
        else:
            raise AssertionError(
                f"S4: flag polling covered no complete episode in {FLAG_POLL_LIMIT} reads; "
                f"{self._last()}"
            )
        self.waits.append(("S4_FLAG_POLL", FLAG_POLL_LIMIT, self._last()))
        enter4, exit4 = probes.episodes[base_ep4]
        margin_ps = SYNC_STAGES * self.t_avs_ns * 1000
        deep_span: list[tuple[int, int, int]] = []
        deep_idle_before: list[tuple[int, int, int]] = []
        deep_idle_after: list[tuple[int, int, int]] = []
        edge_polls: list[str] = []
        for t_b, t_a, status in polls:
            codes = self._window_codes(t_b - margin_ps, t_a + margin_ps)
            in_resync = int(bool(status & IN_RESYNC_BM))
            idle_flag = int(bool(status & AVS_BUS_IS_IDLE_BM))
            if codes == {RESYNC_CODE}:
                deep_span.append((t_b, in_resync, idle_flag))
            elif codes == {IDLE_CODE}:
                (deep_idle_before if t_a < enter4 else deep_idle_after).append(
                    (t_b, in_resync, idle_flag)
                )
            elif t_a >= enter4 - 2 * margin_ps and t_b <= exit4 + 2 * margin_ps:
                names = "/".join(sorted(AVS_CODE_NAME.get(c, hex(c)) for c in codes))
                offset = (t_b - enter4) / 1000
                edge_polls.append(
                    f"t{offset:+.0f}ns:{names}:in_resync={in_resync},idle={idle_flag}"
                )
        assert deep_span, "no flag poll deep inside the resync span"
        assert deep_idle_before and deep_idle_after, (
            f"flag polls deep in AVS_IDLE: {len(deep_idle_before)} before, "
            f"{len(deep_idle_after)} after the episode"
        )
        bad = [p for p in deep_span if p[1] != 1]
        assert not bad, f"AVS_SLAVE_IS_IN_RESYNC read 0 at {len(bad)} polls deep inside the span"
        bad = [p for p in deep_idle_before + deep_idle_after if p[1] != 0]
        assert not bad, f"AVS_SLAVE_IS_IN_RESYNC read 1 at {len(bad)} polls deep inside idle"
        bad = [p for p in deep_idle_before + deep_idle_after if p[2] != 1]
        assert not bad, f"AVS_BUS_IS_IDLE read 0 at {len(bad)} polls deep inside AVS_IDLE"
        bad = [p for p in deep_span if p[2] != 0]
        assert not bad, f"AVS_BUS_IS_IDLE read 1 at {len(bad)} polls deep inside the span"
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S4")
        edges_text = " ".join(edge_polls[:16]) or "none"
        counts = (
            f"{len(deep_idle_before)} deep idle before, {len(deep_span)} deep in the span, "
            f"{len(deep_idle_after)} deep idle after, {len(edge_polls)} near an edge"
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-RESYNC-FLAG set: AVS_SLAVE_IS_IN_RESYNC read 0 at all "
            "%d polls deep in AVS_IDLE before the episode",
            len(deep_idle_before),
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-RESYNC-FLAG observed: read 1 at all %d polls deep inside the span",
            len(deep_span),
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-RESYNC-FLAG cleared: the resync span ended at the probe "
            "(episode %.0f ns)",
            (exit4 - enter4) / 1000,
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-RESYNC-FLAG checked_cleared: read 0 at all %d polls deep in "
            "AVS_IDLE after the episode",
            len(deep_idle_after),
        )
        self._chk(
            "S4",
            "CHK-AVS-RESYNC-FLAG",
            f"AVS_SLAVE_IS_IN_RESYNC read 1 at every poll deep inside the bit-1 span and 0 at "
            f"every poll deep in AVS_IDLE ({counts}; lag window 3 avs_clock_o periods = "
            f"{margin_ps / 1000:.0f} ns, SF-015); polls near an edge, offset from the probe "
            f"entry: {edges_text}",
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-FSM-IDLE-FLAG set: AVS_BUS_IS_IDLE read 1 at all %d polls deep "
            "in AVS_IDLE before the episode",
            len(deep_idle_before),
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-FSM-IDLE-FLAG observed: read 0 at all %d polls deep inside the span",
            len(deep_span),
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-FSM-IDLE-FLAG cleared: the span ended and the probe returned to "
            "AVS_IDLE",
        )
        cocotb.log.info(
            "LIFECYCLE CHK-AVS-FSM-IDLE-FLAG checked_cleared: read 1 at all %d polls deep in "
            "AVS_IDLE after the episode",
            len(deep_idle_after),
        )
        self._chk(
            "S4",
            "CHK-AVS-FSM-IDLE-FLAG",
            f"AVS_BUS_IS_IDLE read 1 at every poll deep in AVS_IDLE with nothing in flight and "
            f"0 at every poll deep inside the resync span ({counts}); edge mapping (SF-015): "
            f"{edges_text}",
        )

        # S5: one-hot
        self._check_probe()
        out_of_reset = probes.samples - probes.reset_zero_samples
        assert out_of_reset >= 1000, f"only {out_of_reset} out-of-reset probe samples"
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-AVS-FSM-ONEHOT",
            f"{probes.samples} probe samples (one per clk_periph_i cycle, S1 to S4), all "
            f"resolvable; {out_of_reset} out-of-reset samples with exactly one of 17 bits set, "
            f"{probes.reset_zero_samples} all-zero samples in the in-reset run ending in "
            f"AVS_RESET (counted, DOC-13), 0 violations out of reset",
        )

        # S6: interval for the default, a small and a mid value
        results: list[tuple[int, float]] = []
        period_ns, _ = await self._period_after("S6_DEFAULT", discard=False)
        results.append((INTERVAL_RESET, period_ns))
        for label, value in (("SMALL", INTERVAL_SMALL), ("MID", INTERVAL_MID)):
            await self._write_interval(f"S6_{label}", cfg0, value)
            period_ns, _ = await self._period_after(f"S6_{label}", discard=True)
            results.append((value, period_ns))
        t_avs_reg = self.t_avs_ns / self.t_reg_ns
        residuals = []
        for value, period in results:
            cycles = period / 1000 / self.t_reg_ns
            residuals.append(cycles - (value + 1) - SYNC_STAGES * t_avs_reg)
        assert all(r >= 0 for r in residuals), f"negative residual L {residuals} clk_reg_i cycles"
        periods_only = [p for _, p in results]
        assert periods_only[1] < periods_only[2] < periods_only[0], (
            f"period does not grow with the interval: {periods_only}"
        )
        period_default = periods_only[0]
        period_small = periods_only[1]
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S6")
        shown = " ".join(
            f"0x{v:04x}:period={p / 1000:.1f}ns({p / 1000 / self.t_reg_ns:.1f} clk_reg_i) L={r:.2f}"
            for (v, p), r in zip(results, residuals)
        )
        self._chk(
            "S6",
            "CHK-AVS-RESYNC-INTERVAL",
            f"end of one resync to the start of the next with no frame in flight: {shown}; "
            f"L = period - (interval + 1) - 3 * {t_avs_reg:.1f} clk_reg_i cycles, all >= 0, "
            f"period grows with the interval; L across intervals {residuals[0]:.2f} / "
            f"{residuals[1]:.2f} / {residuals[2]:.2f} clk_reg_i cycles, constancy is "
            f"SF-013 / DOC-12 (printed, not asserted; 1 avs_clock_o period = "
            f"{self.t_avs_ns:.1f} ns)",
        )

        # S7: interval 0
        await self._write_interval("S7_ZERO", cfg0, 0)
        period_zero, _ = await self._period_after("S7_ZERO", discard=True)
        base_sf = probes.samples
        await self.csr_write("S7_CMD", AVS_CMD, CMD_AFTER_ZERO)
        occupied = await self._await_reply("S7_REPLY_WAIT")
        drained = await self._drain_readback("S7_END")
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S7")
        self._chk(
            "S7",
            "CHK-AVS-RESYNC-INTERVAL-ZERO",
            f"RESYNC_INTERVAL 0: measured period from the end of one resync to the start of the "
            f"next {period_zero / 1000:.1f} ns ({period_zero / 1000 / self.t_reg_ns:.1f} clk_reg_i "
            f"cycles); a command queued afterwards was answered ({occupied} reply, {drained} "
            f"read back within {probes.samples - base_sf} probe samples); owner answer SF-013 "
            f"pending, value printed only",
        )

        # S8: rewrite mid-count
        await self._write_interval("S8_RESTORE", cfg0, INTERVAL_RESET)
        idx = await self._fresh_episode("S8_DISCARD_EPISODE")
        t_end = probes.episodes[idx][1]
        half_ps = INTERVAL_RESET // 2 * self.t_reg_ns * 1000
        await self._wait_probe("S8_HALF_INTERVAL", lambda: probes.t_ps[-1] >= t_end + half_ps)
        word = (cfg0 & ~RESYNC_INTERVAL_BM) | INTERVAL_SMALL
        await self.csr_write("AVS_CFG_0_S8_REWRITE", AVS_CFG_0, word)
        t_write = int(get_sim_time("ps"))
        assert len(probes.episodes) == idx + 1, (
            f"S8: a resync began before the rewrite completed; {self._last()}"
        )
        await self._wait_probe("S8_NEXT_RESYNC", lambda: len(probes.episodes) > idx + 1)
        await self._wait_probe("S8_FOLLOWING_RESYNC", lambda: len(probes.episodes) > idx + 2)
        first_ps = probes.episodes[idx + 1][0]
        second_ps = probes.episodes[idx + 2][0]
        await self._wait_probe("S8_FIRST_END", lambda: probes.episodes[idx + 1][1] is not None)
        first_end = probes.episodes[idx + 1][1]
        since_end = first_ps - t_end
        since_write = first_ps - t_write
        following = second_ps - first_end
        assert since_end <= period_default + self.t_avs_ns * 1000, (
            f"S8: next resync {since_end / 1000:.1f} ns after the previous one ended, beyond the "
            f"old interval period {period_default / 1000:.1f} ns plus one avs_clock_o period"
        )
        assert abs(following - period_small) <= self.t_avs_ns * 1000, (
            f"S8: the following resync came {following / 1000:.1f} ns after the end of the "
            f"first, the 0x{INTERVAL_SMALL:04x} period measured {period_small / 1000:.1f} ns"
        )
        await self._write_interval("S8_FINAL_RESTORE", cfg0, INTERVAL_RESET)
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S8")
        self._chk(
            "S8",
            "CHK-AVS-RESYNC-REWRITE",
            f"0x{INTERVAL_SMALL:04x} written {(t_write - t_end) / 1000:.1f} ns after a resync "
            f"ended (half of 0x{INTERVAL_RESET:04x} = {half_ps / 1000:.1f} ns): next resync "
            f"{since_end / 1000:.1f} ns after that end and {since_write / 1000:.1f} ns after the "
            f"write (old interval period {period_default / 1000:.1f} ns), the following one "
            f"{following / 1000:.1f} ns after the end of the first (new interval period "
            f"{period_small / 1000:.1f} ns); owner answer SF-014 pending, times printed",
        )

        # S9: timeouts and fence
        probes.stop()
        self._check_probe()
        assert probes.zero_run == 0, f"probe ended with {probes.zero_run} zero samples open"
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S9")
        cfg = self.env.cfg
        names = " ".join(f"{n}={b} last=[{s}]" for n, b, s in self.waits)
        names += f" SEP_IN_ACCESS={cfg.axi_timeout_ns}ns last=[enforced-by=smc_sys_axi_agent.py]"
        names += (
            f" COLD_ASSERT={self.ASSERT_BOUND_REF_CYCLES}"
            f" COLD_RELEASE={self.RELEASE_BOUND_REF_CYCLES}"
            f" last=[reset agent WAIT_STATE, enforced-by=smc_reset_agent.py]"
        )
        count = len(self.waits) + 3
        self._chk(
            "S9",
            "CHK-TIMEOUT-PATHS",
            f"{count} bounded waits (probe waits in clk_periph_i cycles, polls in reads or "
            f"clk_smc_i cycles; each raises AssertionError with the episode count and last probe "
            f"state on expiry): {names}",
        )
        steps = [s for s, _ in self.stamps]
        assert steps == [f"S{i}" for i in range(1, 10)], f"fence steps {steps} out of order"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        stamp_of = dict(self.stamps)
        ids = [c for c, _, _ in self.chk_lines]
        assert ids == [
            "CHK-AVS-RESYNC-STARTUP",
            "CHK-AVS-FSM-RESET-SEQUENCE",
            "CHK-AVS-RESYNC-LEN35",
            "CHK-AVS-RESYNC-PIN-HIGH",
            "CHK-AVS-RESYNC-FLAG",
            "CHK-AVS-FSM-IDLE-FLAG",
            "CHK-AVS-FSM-ONEHOT",
            "CHK-AVS-RESYNC-INTERVAL",
            "CHK-AVS-RESYNC-INTERVAL-ZERO",
            "CHK-AVS-RESYNC-REWRITE",
            "CHK-TIMEOUT-PATHS",
        ], f"checker lines {ids} out of order"
        assert all(t >= stamp_of[s] for _, s, t in self.chk_lines), "checker line before its step"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence MONITORS_RUNNING < COLD_RESET_SEQUENCE < RESYNC_SHAPE < "
            "FLAGS_POLLED < ONEHOT_COUNTED < INTERVALS_MEASURED < INTERVAL_ZERO < REWRITE; "
            "checker lines %s; stamps %s; probe samples %d (%d all-zero in reset)",
            ",".join(ids),
            ",".join(f"{s}={t}" for s, t in self.stamps),
            probes.samples,
            probes.reset_zero_samples,
        )
