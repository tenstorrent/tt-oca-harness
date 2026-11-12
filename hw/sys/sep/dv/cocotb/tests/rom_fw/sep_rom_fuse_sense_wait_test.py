# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROM reads no eFuse shadow register before fuse sense completes.

rom.adoc, Fuse and System State, Fuse-Sense Readiness:

* SEP-ROM-FUSE-010: "The ROM shall not consume any fuse shadow value before fuse sensing has
  completed. Completion is indicated by `SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS` bit 0
  (`smc_fuse_sense_done`); the ROM polls it without timeout (the accepted BL0 hang failure
  mode, SEP-ROM-CPU-080)."
* "The poll is a discrete stage ([S08]) that runs unconditionally, ahead of every fuse
  consumer"
* "The ROM does not rely on sensing having completed before the SEP core reset released."

Sense completion is the level of the bench SMC input `smc_fuse_sense_done_i`, which
`SMC_FUSE_SENSE_STATUS` bit 0 reflects. The ROM console lines `FUSE_SENSE_WAIT` and
`FUSE_SENSE_DONE` only show that the hold run reached the poll and never left it; no ordering
is graded against them. Consuming a fuse shadow value is graded as a CPU read of the SEP eFuse
map on the PR-LSU-XBAR tap; reads by other masters are not graded. The X check of the sense
port is inert on 2-state Verilator.
Two testlist entries. In the normal entry the bench raises the input 64 clk after reset,
before the CPU is released, so the ordering check holds there by construction; that entry
grades that the ROM polls the register and reads eFuse only after a poll that saw it done,
and it is the positive control that the tap records the ROM's eFuse reads. The hold entry
(`+sep_smc_fuse_sense_hold`) keeps the input low for the whole run, which is where the
ordering claim is graded: no eFuse read and a poll still running at the end of a window twice
as long as a normal boot takes to its first eFuse read. "Without timeout" is graded only up to
that window. A sense that completes after the CPU starts polling is not covered: the bench
cannot release the input in the middle of a run.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_fabric_tap import SepFabricTap
from rom_fw.sep_rom_observe_base import sep_rom_observe_base
from sep_reg_meta import sym

_EFUSE_LO = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
_EFUSE_HI = _EFUSE_LO + sym("SEP_EFUSE_MAP_REG_MAP_SIZE")
_LC_STATE = sym("SEP_EFUSE_MAP_LC_STATE_REG_ADDR")
_SENSE_REG = sym("SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_REG_ADDR")
_SENSE_HI = _SENSE_REG + sym("SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_REG_WIDTH") // 8
_SENSE_PORT = "smc_fuse_sense_done_model"
_DONE_MARK = "FUSE_SENSE_DONE"
_WAIT_MARK = "FUSE_SENSE_WAIT"
# Bound on the clock cycle of a normal boot's first eFuse read; the normal entry checks it.
_FIRST_READ_BOUND = 650_000
_HOLD_WINDOW = 2 * _FIRST_READ_BOUND
# The poll must still be running in the last 1% of the hold window.
_POLL_TAIL = _HOLD_WINDOW // 100


def _value_at(records: list[tuple[int, int]], t: int) -> int | None:
    """Value of a watched port in force at time t."""
    v = None
    for rt, rv in records:
        if rt > t:
            break
        v = rv
    return v


@pyuvm.test()
class sep_rom_fuse_sense_wait_test(sep_rom_observe_base):
    required_evidence = ("CHK-NO-FUSE-READ-BEFORE-SENSE",)
    observer_kwargs = {"watch": (_SENSE_PORT,)}

    @property
    def hold(self) -> bool:
        return "sep_smc_fuse_sense_hold" in cocotb.plusargs

    def done(self, obs) -> bool:
        return obs.cycle >= _HOLD_WINDOW if self.hold else obs.verdict_pass() is not None

    async def run_scenario(self) -> None:
        extra = ("CHK-HOLD-WAITS",) if self.hold else ("CHK-POLL-GATES-READ", "CHK-SENSE-THEN-READ")
        self.required_evidence = (*type(self).required_evidence, *extra)
        self.known: list[bool] = []
        self.t0 = self.clk_ps = None
        # The tap starts before reset release so the first ROM access is in the record.
        self.tap_start_ps = int(get_sim_time("ps"))
        self.lsu = SepFabricTap("PR-LSU-XBAR").start()
        self.mark = self.lsu.mark()
        await super().run_scenario()

    def _sample_known(self) -> None:
        self.known.append(getattr(cocotb.top, _SENSE_PORT).value.is_resolvable)

    async def stimulus(self, obs) -> None:
        # The observer's first sample is on the first clk_i edge, so cycles count from it.
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        t0 = int(get_sim_time("ps"))
        await RisingEdge(clk)
        self.t0, self.clk_ps = t0, int(get_sim_time("ps")) - t0
        # The observer reads the sense port with X as 0, so known-ness is sampled here.
        await RisingEdge(cocotb.top.cpu_trace_valid_o)
        await ReadOnly()
        self._sample_known()

    async def before_grade(self, obs) -> None:
        self._sample_known()
        self.tap_stop_ps = int(get_sim_time("ps"))
        await self.lsu.stop()

    def _cycle(self, t: int | None) -> int | None:
        if t is None or self.t0 is None or not self.clk_ps:
            return None
        return int(t - self.t0) // self.clk_ps + 1

    def grade(self, obs, chk) -> None:
        recs = obs.watched[_SENSE_PORT]
        sense_t = next((t for t, v in recs if v == 1), None)
        levels = [v for _, v in recs]
        # The sense port starts low in reset and, unless held, rises once and stays high.
        chk.ctrl(
            "SENSE-PORT",
            levels == ([0] if self.hold else [0, 1]) and self.known == [True, True],
            leaf="hold" if self.hold else "normal",
            levels=levels,
            sense_cycle=self._cycle(sense_t),
            known=self.known,
        )

        ar = self.lsu.since(self.mark, "ar")
        unknown = sum(1 for b in ar if b.addr is None)
        polls = [b for b in ar if b.addr is not None and _SENSE_REG <= b.addr < _SENSE_HI]
        reads = [b for b in ar if b.addr is not None and _EFUSE_LO <= b.addr < _EFUSE_HI]
        covered = (
            bool(obs.first)
            and self.lsu.stop_clk is not None
            and self.tap_start_ps <= obs.first[0].t_ps
            and self._cycle(self.tap_stop_ps) is not None
            and self._cycle(self.tap_stop_ps) >= obs.cycle
        )
        # The poll reads prove the tap records the ROM's register reads with their address.
        chk.ctrl(
            "LSU-AR-LIVE",
            covered and bool(polls) and not unknown,
            tap_ps=f"{self.tap_start_ps}..{self.tap_stop_ps}",
            ar=len(ar),
            polls=len(polls),
            unknown=unknown,
        )

        early = [b for b in reads if sense_t is None or b.t_ps < sense_t]
        chk.ok(
            "NO-FUSE-READ-BEFORE-SENSE",
            covered and not unknown and not early,
            early=len(early),
            reads=len(reads),
            sense_cycle=self._cycle(sense_t),
            first_early=[f"0x{b.addr:08x}@{self._cycle(b.t_ps)}" for b in early[:4]],
        )

        first_read = reads[0] if reads else None
        wait_t, done_t = obs.line_t(_WAIT_MARK), obs.line_t(_DONE_MARK)
        chk.obs(
            "SENSE-TIMES",
            sense_cycle=self._cycle(sense_t),
            first_poll_cycle=self._cycle(polls[0].t_ps if polls else None),
            first_read_cycle=self._cycle(first_read.t_ps if first_read else None),
            first_read_addr=f"0x{first_read.addr:08x}" if first_read else "none",
            wait_line_cycle=self._cycle(wait_t),
            done_line_cycle=self._cycle(done_t),
            end_cycle=obs.cycle,
        )

        if self.hold:
            last_poll = self._cycle(polls[-1].t_ps) if polls else None
            end = self._cycle(self.tap_stop_ps)
            chk.ctrl("CPU-RAN", obs.retired > 0 and wait_t is not None, retired=obs.retired)
            chk.ok(
                "HOLD-WAITS",
                covered
                and sense_t is None
                and not reads
                and last_poll is not None
                and end is not None
                and end - last_poll <= _POLL_TAIL
                and done_t is None
                and obs.cycle >= _HOLD_WINDOW,
                reads=len(reads),
                polls=len(polls),
                last_poll_cycle=last_poll,
                end_cycle=end,
                tail=_POLL_TAIL,
                done_line=done_t is not None,
                window=_HOLD_WINDOW,
            )
            return

        before = [b for b in polls if first_read is not None and b.t_ps < first_read.t_ps]
        gate = before[-1] if before else None
        gate_level = _value_at(recs, gate.t_ps) if gate is not None else None
        chk.ok(
            "POLL-GATES-READ",
            first_read is not None and gate is not None and gate_level == 1,
            polls_before_read=len(before),
            gating_poll_cycle=self._cycle(gate.t_ps if gate else None),
            level_at_gating_poll=gate_level,
            first_read_cycle=self._cycle(first_read.t_ps if first_read else None),
        )
        lc_reads = sum(1 for b in reads if b.addr == _LC_STATE)
        chk.ok(
            "SENSE-THEN-READ",
            sense_t is not None and bool(reads) and lc_reads > 0,
            reads=len(reads),
            lc_state_reads=lc_reads,
        )
        first_cycle = self._cycle(first_read.t_ps) if first_read else None
        # The hold window must stay twice as long as a normal boot takes to its first eFuse read.
        chk.ctrl(
            "HOLD-WINDOW-SIZED",
            first_cycle is not None and first_cycle <= _FIRST_READ_BOUND,
            first_read_cycle=first_cycle,
            bound=_FIRST_READ_BOUND,
            window=_HOLD_WINDOW,
            fix="raise _FIRST_READ_BOUND above the measured first_read_cycle",
        )
