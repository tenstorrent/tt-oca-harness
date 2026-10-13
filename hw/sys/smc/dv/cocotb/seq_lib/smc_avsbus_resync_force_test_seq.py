# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A forced AVSBus slave resync from idle, mid-frame, with a queue and twice.

Contract SMC_POWER_AVS_011, anchor smc_avsbus_resync_force_test.
Scenarios: AVS-RESYNC.S6, AVS-RESYNC.S7, AVS-RESYNC.S8, AVS-RESYNC.S9, INT-AVS-RESYNC-INFLIGHT.
Sources: hw/ip/avsbus_controller/doc/architecture.adoc, regs/avsbus_controller.rdl.

AVS_CFG_1.FORCE_SLAVE_RESYNC_OPERATION requests one resync. The leaf counts the
AVS_SLAVE_RESYNC episodes on the FSM debug bus (a code counts once it holds over two
consecutive clk_periph_i samples) and the master subframes on avs_mdata. The instant the
master sees the request and the second-request outcome (SF-013) are not observable at the
SMC boundary, so the leaf prints the measured counts and asserts only what the contract states.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

from .smc_avsbus_protocol_utils import (
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
    SUBFRAME_BITS,
    avs_field,
    build_avs_cmd,
    expected_master_subframe,
    fifo_field,
    set_avs_sdata,
)
from .smc_csr_seq_utils import SmcCsrSeq

FORCE_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__FORCE_SLAVE_RESYNC_OPERATION_bm")

#: Three read commands on distinct rails, plus the two the mid-frame leg queues.
CMD_MID_0 = build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x1, READ_CMD_DATA)
CMD_MID_1 = build_avs_cmd(CMD_TYPE_READ, 0, 0x2, 0x2, READ_CMD_DATA)
CMDS_QUEUE = (
    build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x3, READ_CMD_DATA),
    build_avs_cmd(CMD_TYPE_READ, 0, 0x2, 0x4, READ_CMD_DATA),
    build_avs_cmd(CMD_TYPE_READ, 0, 0xE, 0x5, READ_CMD_DATA),
)
CMD_TWICE = build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x6, READ_CMD_DATA)

#: Bound on every probe wait, in clk_periph_i cycles.
STATE_WAIT_CYCLES = 50_000
#: Bound on every register poll: attempts, each followed by POLL_CYCLES clk_smc_i cycles.
POLL_LIMIT = 400
POLL_CYCLES = 50

IDLE = "AVS_IDLE"
RESYNC = "AVS_SLAVE_RESYNC"


class _Probes:
    """Passive FSM-probe and master-subframe recorders."""

    def __init__(self) -> None:
        self.events: list[tuple[int, str]] = []
        self.resyncs = 0
        self.current = "unseen"
        self.subframes: list[tuple[int, int]] = []
        self.fault: str | None = None
        self._tasks: list = []

    def start(self) -> None:
        self._tasks = [cocotb.start_soon(self._fsm()), cocotb.start_soon(self._mdata())]

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
            if not raw.is_resolvable:
                self.fault = f"tb_avsbus_cur_state_debug is X/Z: {raw}"
                return
            code = int(raw)
            if code == previous:
                name = AVS_CODE_NAME.get(code, f"0x{code:x}")
                if name != self.current:
                    self.current = name
                    self.events.append((int(get_sim_time("ps")), name))
                    if name == RESYNC:
                        self.resyncs += 1
            previous = code

    async def _mdata(self) -> None:
        dut = cocotb.top
        remaining = 0
        word = 0
        start_ps = 0
        while True:
            await FallingEdge(dut.tb_avs_clk_from_dut)
            raw = dut.tb_avs_mdata_from_dut.value
            if not raw.is_resolvable:
                self.fault = f"tb_avs_mdata_from_dut is X/Z: {raw}"
                return
            bit = int(raw)
            if remaining == 0 and bit == 0:
                remaining = SUBFRAME_BITS
                word = 0
                start_ps = int(get_sim_time("ps"))
            if remaining:
                word = (word << 1) | bit
                remaining -= 1
                if remaining == 0:
                    self.subframes.append((start_ps, word & ~0x7))


class smc_avsbus_resync_force_test_seq(SmcCsrSeq):
    """Force the slave resync from idle, mid-frame, with commands queued, and twice."""

    def __init__(self, name: str = "smc_avsbus_resync_force_test_seq") -> None:
        super().__init__(name)
        self.probes = _Probes()
        self.waits: list[tuple[str, int, str]] = []
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, step, int(get_sim_time("ps"))))

    def _last(self) -> str:
        return (
            f"episodes={self.probes.resyncs} state={self.probes.current} "
            f"subframes={len(self.probes.subframes)}"
        )

    async def _wait_probe(self, name: str, cond) -> None:
        for _ in range(STATE_WAIT_CYCLES):
            assert self.probes.fault is None, f"{name}: {self.probes.fault}"
            if cond():
                self.waits.append((name, STATE_WAIT_CYCLES, self._last()))
                return
            await RisingEdge(cocotb.top.clk_periph_i)
        raise AssertionError(
            f"{name}: not met within {STATE_WAIT_CYCLES} clk_periph_i cycles; {self._last()}"
        )

    async def _occupancy(self, label: str) -> int:
        fifos = await self.csr_read(label, AVS_FIFOS_STATUS)
        return fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)

    async def _await_occupancy(self, name: str, wanted: int) -> int:
        occupied = 0
        for _ in range(POLL_LIMIT):
            occupied = await self._occupancy(f"{name}_FIFOS")
            if occupied >= wanted:
                self.waits.append((name, POLL_LIMIT * POLL_CYCLES, f"occupied={occupied}"))
                return occupied
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{name}: readback FIFO holds {occupied} of {wanted} replies after {POLL_LIMIT} "
            f"polls; {self._last()}"
        )

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

    async def _force(self, label: str, cfg1: int | None = None) -> int:
        """Write the force bit; read-modify-write unless ``cfg1`` is given."""
        if cfg1 is None:
            cfg1 = await self.csr_read(f"{label}_CFG_1_RMW", AVS_CFG_1)
        await self.csr_write(f"{label}_CFG_1_FORCE", AVS_CFG_1, cfg1 | FORCE_BM)
        return cfg1

    async def _poll_force_clear(self, name: str, cfg1_base: int) -> None:
        field = FORCE_BM
        for _ in range(POLL_LIMIT):
            cfg1 = await self.csr_read(f"{name}_CFG_1", AVS_CFG_1)
            if not cfg1 & field:
                assert cfg1 == cfg1_base, (
                    f"{name}: AVS_CFG_1=0x{cfg1:08x} after the force cleared, was 0x{cfg1_base:08x}"
                )
                self.waits.append((name, POLL_LIMIT * POLL_CYCLES, f"cfg1=0x{cfg1:08x}"))
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{name}: FORCE_SLAVE_RESYNC_OPERATION still 1 after {POLL_LIMIT} polls; {self._last()}"
        )

    def _episode_window(self, base_events: int) -> tuple[int, int, str]:
        """Entry time, exit time and preceding state of the first resync after ``base_events``."""
        events = self.probes.events
        for i in range(base_events, len(events)):
            if events[i][1] == RESYNC:
                exit_ps = events[i + 1][0] if i + 1 < len(events) else events[i][0]
                prior = events[i - 1][1] if i > 0 else "none"
                return events[i][0], exit_ps, prior
        raise AssertionError(
            f"no AVS_SLAVE_RESYNC episode after event {base_events}; {self._last()}"
        )

    def _words(self, base_sf: int) -> list[int]:
        return [w for _, w in self.probes.subframes[base_sf:]]

    async def body(self) -> None:
        dut = cocotb.top
        for sig in (
            "tb_avs_clk_from_dut",
            "tb_avs_mdata_from_dut",
            "tb_avs_sdata_ext",
            "tb_avsbus_cur_state_debug",
        ):
            assert hasattr(dut, sig), f"{sig} is not visible on the bench top"

        # S1: SETUP
        set_avs_sdata(0)
        cfg0 = await self.csr_read("AVS_CFG_0_SAVE", AVS_CFG_0)
        cfg0_max = cfg0 | RESYNC_INTERVAL_BM
        await self.csr_write("AVS_CFG_0_MAX", AVS_CFG_0, cfg0_max)
        await self.csr_read("AVS_CFG_0_MAX_RB", AVS_CFG_0, expected=cfg0_max)
        self.probes.start()
        await self._drain_readback("SETUP")
        await self._wait_probe("IDLE_WAIT", lambda: self.probes.current == IDLE)
        cfg1_base = await self.csr_read("AVS_CFG_1_BASE", AVS_CFG_1)
        assert not cfg1_base & FORCE_BM, f"AVS_CFG_1=0x{cfg1_base:08x}: force bit set before S2"
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S1")

        # S2: force from idle
        base_r = self.probes.resyncs
        await self._force("S2")
        await self._poll_force_clear("S2_CLEAR_POLL", cfg1_base)
        await self._wait_probe(
            "S2_EPISODE_IDLE_WAIT",
            lambda: self.probes.resyncs > base_r and self.probes.current == IDLE,
        )
        episodes = self.probes.resyncs - base_r
        assert episodes == 1, f"force from idle gave {episodes} resync episodes; {self._last()}"
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-AVS-FORCE-ONE-RESYNC",
            f"one FORCE_SLAVE_RESYNC_OPERATION write from AVS_IDLE gave {episodes} "
            f"AVS_SLAVE_RESYNC episode on the probe, AVS_CFG_1 read the field as 0 within the "
            f"bounded poll (0x{cfg1_base:08x}) and the bus returned to AVS_IDLE",
        )

        # S3: force mid-frame
        base_r = self.probes.resyncs
        base_e = len(self.probes.events)
        base_sf = len(self.probes.subframes)
        await self.csr_write("S3_CMD0", AVS_CMD, CMD_MID_0)
        await self.csr_write("S3_CMD1", AVS_CMD, CMD_MID_1)
        await self._wait_probe("S3_SHIFT_WAIT", lambda: "SHIFT" in self.probes.current)
        state_at_force = self.probes.current
        await self._force("S3")
        req_ps = int(get_sim_time("ps"))
        await self._poll_force_clear("S3_CLEAR_POLL", cfg1_base)
        await self._wait_probe(
            "S3_EPISODE_IDLE_WAIT",
            lambda: self.probes.resyncs > base_r and self.probes.current == IDLE,
        )
        await self._await_occupancy("S3_REPLY_WAIT", 2)
        entry_ps, exit_ps, prior = self._episode_window(base_e)
        starts = [s for s, _ in self.probes.subframes[base_sf:]]
        before_req = sum(1 for s in starts if s < req_ps)
        late = sum(1 for s in starts if req_ps <= s < entry_ps)
        inside = sum(1 for s in starts if entry_ps <= s < exit_ps)
        after = sum(1 for s in starts if s >= exit_ps)
        words = self._words(base_sf)
        want = [expected_master_subframe(CMD_MID_0), expected_master_subframe(CMD_MID_1)]
        episodes = self.probes.resyncs - base_r
        occupied = await self._occupancy("S3_FIFOS_END")
        assert "SHIFT" in state_at_force or before_req > 0, (
            f"S3: no frame was in flight at the force write; {self._last()}"
        )
        assert episodes == 1, f"S3: {episodes} resync episodes; {self._last()}"
        assert "SHIFT" not in prior and "RETRY" not in prior, (
            f"S3: the resync began right after {prior}, a frame still in flight; {self._last()}"
        )
        assert words == want, (
            f"S3: master subframes {[hex(w) for w in words]} != "
            f"{[hex(w) for w in want]}; {self._last()}"
        )
        assert occupied == len(want), f"S3: {occupied} replies for {len(want)} launched commands"
        if state_at_force == "AVS_SHIFT_1ST_SUBFRAME":
            assert late == 0, (
                f"S3: {late} subframes launched between the force write and the episode; "
                f"state_at_force {state_at_force}; {self._last()}"
            )
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-AVS-FORCE-FRAME-COMPLETES",
            f"force written with the probe in {state_at_force}: both queued commands launched "
            f"once each in order ({len(words)} master subframes), {occupied} replies pushed, "
            f"{episodes} resync episode followed (state before "
            f"it {prior}); subframes started before the write {before_req}, between the write "
            f"and the episode {late}, inside the probe-reported episode {inside}, after it "
            f"{after} (late asserted 0 only when the force landed in AVS_SHIFT_1ST_SUBFRAME; "
            f"later states timing dependent)",
        )
        self._chk(
            "S3",
            "CHK-AVS-FORCE-INFLIGHT-INT",
            f"probe order from the force write: {self._sequence(base_e)}; launched before the "
            f"request {before_req} (timing dependent through the synchroniser), replies pushed "
            f"{occupied}, resync from {prior} after the in-flight frames",
        )
        await self._drain_readback("S3_END")

        # S4: force with a queue
        base_r = self.probes.resyncs
        base_e = len(self.probes.events)
        base_sf = len(self.probes.subframes)
        await self._force("S4")
        for i, cmd in enumerate(CMDS_QUEUE):
            await self.csr_write(f"S4_CMD{i}", AVS_CMD, cmd)
        await self._poll_force_clear("S4_CLEAR_POLL", cfg1_base)
        await self._wait_probe(
            "S4_LAUNCH_IDLE_WAIT",
            lambda: (
                self.probes.resyncs > base_r
                and len(self.probes.subframes) - base_sf >= len(CMDS_QUEUE)
                and self.probes.current == IDLE
            ),
        )
        occupied = await self._await_occupancy("S4_REPLY_WAIT", len(CMDS_QUEUE))
        occupied = await self._occupancy("S4_FIFOS_END")
        entry_ps, _, prior = self._episode_window(base_e)
        words = self._words(base_sf)
        want = [expected_master_subframe(c) for c in CMDS_QUEUE]
        pre = sum(1 for s, _ in self.probes.subframes[base_sf:] if s < entry_ps)
        episodes = self.probes.resyncs - base_r
        assert words == want, (
            f"S4: master subframes {[hex(w) for w in words]} != "
            f"{[hex(w) for w in want]}; {self._last()}"
        )
        assert occupied == len(CMDS_QUEUE), f"S4: {occupied} replies for {len(CMDS_QUEUE)} commands"
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-AVS-FORCE-QUEUE-ORDER",
            f"force then three commands on distinct rails: {len(words)} master subframes "
            f"matching the write order once each, {occupied} replies pushed, {episodes} resync "
            f"episode(s) on the probe, {pre} subframes started before the episode",
        )
        await self._drain_readback("S4_END")

        # S5: force twice
        base_r = self.probes.resyncs
        cfg1 = await self.csr_read("S5_CFG_1", AVS_CFG_1)
        await self._force("S5_A", cfg1)
        await self._force("S5_B", cfg1)
        await self._poll_force_clear("S5_CLEAR_POLL", cfg1_base)
        await self._wait_probe(
            "S5_EPISODE_IDLE_WAIT",
            lambda: self.probes.resyncs > base_r and self.probes.current == IDLE,
        )
        episodes = self.probes.resyncs - base_r
        assert 1 <= episodes <= 2, f"S5: {episodes} resync episodes; {self._last()}"
        base_sf = len(self.probes.subframes)
        await self.csr_write("S5_CMD", AVS_CMD, CMD_TWICE)
        occupied = await self._await_occupancy("S5_REPLY_WAIT", 1)
        await self._wait_probe("S5_FINAL_IDLE_WAIT", lambda: self.probes.current == IDLE)
        words = self._words(base_sf)
        assert words == [expected_master_subframe(CMD_TWICE)], (
            f"S5: master subframes {[hex(w) for w in words]} for the queued command"
        )
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-AVS-FORCE-TWICE",
            f"two back-to-back force writes gave {episodes} resync episode(s) (SF-013: owner "
            f"answers one or two), the bus returned to AVS_IDLE, and the command queued "
            f"afterwards launched once and was answered ({occupied} reply)",
        )
        await self._drain_readback("S5_END")

        # S6: restore and timeouts
        await self.csr_write("AVS_CFG_0_RESTORE", AVS_CFG_0, cfg0)
        await self.csr_read("AVS_CFG_0_RESTORE_RB", AVS_CFG_0, expected=cfg0)
        self.probes.stop()
        assert self.probes.fault is None, self.probes.fault
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S6")
        names = " ".join(f"{n}={b} last=[{s}]" for n, b, s in self.waits)
        self._chk(
            "S6",
            "CHK-TIMEOUT-PATHS",
            f"{len(self.waits)} bounded waits (probe waits in clk_periph_i cycles, polls in "
            f"clk_smc_i cycles; each raises AssertionError with the episode count and last "
            f"probe state on expiry): {names}",
        )

        steps = [s for s, _ in self.stamps]
        assert steps == ["S1", "S2", "S3", "S4", "S5", "S6"], f"fence steps {steps} out of order"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        stamp_of = dict(self.stamps)
        ids = [c for c, _, _ in self.chk_lines]
        assert ids == [
            "CHK-AVS-FORCE-ONE-RESYNC",
            "CHK-AVS-FORCE-FRAME-COMPLETES",
            "CHK-AVS-FORCE-INFLIGHT-INT",
            "CHK-AVS-FORCE-QUEUE-ORDER",
            "CHK-AVS-FORCE-TWICE",
            "CHK-TIMEOUT-PATHS",
        ], f"checker lines {ids} out of order"
        assert all(t >= stamp_of[s] for _, s, t in self.chk_lines), "checker line before its step"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence IDLE_REACHED < FORCE_FROM_IDLE < FORCE_MID_FRAME < "
            "FORCE_WITH_QUEUE < FORCE_TWICE; checker lines %s; stamps %s",
            ",".join(ids),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )

    def _sequence(self, base_events: int) -> str:
        names: list[str] = []
        for _, name in self.probes.events[base_events:]:
            if not names or names[-1] != name:
                names.append(name)
        return ">".join(names)
