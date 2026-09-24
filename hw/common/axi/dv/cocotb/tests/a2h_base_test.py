# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench for the axi_lite_to_ahb IP-level cocotb tests.

``axi_lite_to_ahb_tb_top`` elaborates the converter three times, and ``Bench``
builds one ``ConverterEnv`` per instance:

* cfg A (``a_*`` pins): AHB_DATA_WIDTH = 64, AllowSubWordWrite = 0,
  AckZeroStrobeWrite = 1, the SEP Adams Bridge parameter set;
* cfg B (``b_*`` pins): AHB_DATA_WIDTH = 32, AllowSubWordWrite = 1,
  AckZeroStrobeWrite = 0;
* cfg C (``c_*`` pins): AHB_DATA_WIDTH = 64, AllowSubWordWrite = 1,
  AckZeroStrobeWrite = 0, sub-word writes on either half of a 64-bit bus.

Each env carries the AHB-Lite slave model, the passive AXI monitor and the
scoreboard, which check every transaction of every test. The AXI side is
driven by one of three agents, chosen per test: ``AxiLiteMaster`` from
cocotbext-axi (``axi="master"``), ``AxilPort`` for arbitrary WSTRB and
per-channel throttling (``axi="port"``), or the pins directly
(``axi="raw"``).

Every positive check goes through ``Bench.chk``, which logs it with a ``CHK``
prefix and raises on failure.
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from models.a2h_scoreboard import ConverterCfg, ConverterScoreboard, expected_write
from models.ahb_lite_slave import AhbLiteSlaveModel
from models.axil_agents import AxilMonitor, AxilPort, AxilRawPort, PortOp

CLK_PERIOD_NS = 10

CFG_A = ConverterCfg("a", ahb_data_width=64, allow_sub_word_write=False, ack_zero_strobe_write=True)
CFG_B = ConverterCfg("b", ahb_data_width=32, allow_sub_word_write=True, ack_zero_strobe_write=False)
CFG_C = ConverterCfg("c", ahb_data_width=64, allow_sub_word_write=True, ack_zero_strobe_write=False)
CFGS = (CFG_A, CFG_B, CFG_C)


class Checks:
    """Positive-check recorder: logs each check and raises on the first failure."""

    def __init__(self, log) -> None:
        self.log = log
        self.count = 0

    def __call__(self, cond: bool, msg: str, quiet: bool = False) -> None:
        if not cond:
            self.log.error("CHK FAIL: %s", msg)
            raise AssertionError(msg)
        self.count += 1
        if not quiet:
            self.log.info("CHK PASS: %s", msg)


class ConverterEnv:
    """Agents, slave model, monitor and scoreboard for one converter instance."""

    def __init__(self, dut, cfg: ConverterCfg, rng: random.Random, axi: str) -> None:
        self.dut = dut
        self.cfg = cfg
        self.rng = rng
        axil, ahb = f"{cfg.name}_axil", f"{cfg.name}_ahb"
        self.model = AhbLiteSlaveModel(
            dut,
            ahb,
            dut.clk,
            dut.rst_n,
            cfg.ahb_data_width,
            random.Random(rng.getrandbits(32)),
            name=f"ahb_{cfg.name}",
        )
        self.monitor = AxilMonitor(dut, axil, ahb, dut.clk, dut.rst_n, name=f"axil_{cfg.name}")
        self.scoreboard = ConverterScoreboard(cfg, self.model, self.monitor)
        self.port: AxilPort | None = None
        self.master: AxiLiteMaster | None = None
        self.raw: AxilRawPort | None = None
        if axi == "port":
            self.port = AxilPort(dut, axil, dut.clk, dut.rst_n)
        elif axi == "master":
            self.master = AxiLiteMaster(
                AxiLiteBus.from_prefix(dut, axil), dut.clk, dut.rst_n, reset_active_level=False
            )
        elif axi == "raw":
            self.raw = AxilRawPort(dut, axil)
        else:
            raise ValueError(f"unknown AXI agent {axi!r}")

    def pin(self, name: str):
        return getattr(self.dut, f"{self.cfg.name}_{name}")

    def violations(self) -> list[str]:
        found = [*self.model.violations, *self.monitor.violations, *self.scoreboard.violations]
        if self.port is not None:
            found += self.port.violations
        return found

    def quiescent(self) -> bool:
        if self.port is not None and self.port.outstanding:
            return False
        if self.master is not None and not self.master.idle():
            return False
        return self.scoreboard.idle and not self.model.busy

    def transfers_since(self, start: int):
        return self.model.transfers[start:]


class Bench:
    """Clock, reset and one env per converter instance."""

    def __init__(self, dut, axi: str) -> None:
        self.dut = dut
        self.log = dut._log
        self.run_seed = os.environ.get("COCOTB_RANDOM_SEED", os.environ.get("RANDOM_SEED", "-"))
        self.seed = cocotb.RANDOM_SEED
        self.rng = random.Random(self.seed)
        self.chk = Checks(self.log)
        self.axi = axi
        self.envs: dict[str, ConverterEnv] = {}

    @classmethod
    async def create(cls, dut, axi: str = "port") -> Bench:
        tb = cls(dut, axi)
        await tb._start()
        return tb

    async def _start(self) -> None:
        dut = self.dut
        self.log.info(
            "axi_lite_to_ahb bench: run seed=%s (per-test PRNG seed %d) agent=%s",
            self.run_seed,
            self.seed,
            self.axi,
        )
        dut.rst_n.value = 0
        Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start(start_high=False)
        for cfg in CFGS:
            self.envs[cfg.name] = ConverterEnv(
                dut, cfg, random.Random(self.rng.getrandbits(32)), self.axi
            )
            self.log.info("env %s", cfg.describe())
        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 2)

    @property
    def a(self) -> ConverterEnv:
        return self.envs["a"]

    @property
    def all_envs(self) -> tuple[ConverterEnv, ...]:
        return tuple(self.envs.values())

    async def cycles(self, n: int) -> None:
        await ClockCycles(self.dut.clk, n)

    async def wait_until(self, pred: Callable[[], bool], max_cycles: int, what: str) -> int:
        """Advance until ``pred()`` holds after an edge; return the cycles taken."""
        for n in range(1, max_cycles + 1):
            await RisingEdge(self.dut.clk)
            if pred():
                return n
        self.chk(False, f"timed out after {max_cycles} cycles waiting for {what}")
        return max_cycles

    async def wait_ops(self, ops: list[PortOp], max_cycles: int, what: str) -> None:
        await self.wait_until(lambda: all(op.done.is_set() for op in ops), max_cycles, what)

    async def finish(self, envs: tuple[ConverterEnv, ...] | None = None) -> None:
        """Drain every env, then check every always-on rule and the memory image."""
        for env in envs or tuple(self.envs.values()):
            await self.wait_until(env.quiescent, 20000, f"cfg {env.cfg.name.upper()} to drain")
            name = env.cfg.name.upper()
            problems = env.violations()
            for text in problems[:20]:
                self.log.error("%s", text)
            self.chk(
                not problems,
                f"cfg {name}: no protocol, ordering or scoreboard violation "
                f"({len(problems)} found)",
            )
            self.chk(
                env.model.pipelined_accepts == 0,
                f"cfg {name}: no AHB address phase overlapped a data phase",
            )
            compared = env.scoreboard.compare_memory()
            self.chk(
                not env.scoreboard.violations,
                f"cfg {name}: slave memory matches the reference ({compared} bytes)",
            )
            m, mon = env.model, env.monitor
            self.log.info(
                "SUMMARY cfg %s: ahb_transfers=%d errors=%d addr_stall_edges=%d "
                "data_wait_edges=%d r_stall_edges=%d b_stall_edges=%d ar_wait_edges=%d | %s",
                name,
                len(m.transfers),
                m.error_responses,
                m.addr_stall_edges,
                m.data_wait_edges,
                mon.r_stall_edges,
                mon.b_stall_edges,
                mon.ar_wait_edges,
                env.scoreboard.summary(),
            )
        self.log.info("%d checks passed (run seed=%s)", self.chk.count, self.run_seed)


def random_strobe(cfg: ConverterCfg, rng: random.Random) -> int:
    """WSTRB biased toward the values the cfg issues on AHB, covering all 16 overall."""
    if rng.random() < 0.6:
        legal = [s for s in range(16) if expected_write(cfg, s).transfer]
        return rng.choice(legal)
    return rng.randrange(16)


async def random_traffic(
    tb: Bench,
    env: ConverterEnv,
    count: int,
    base: int,
    words: int,
    max_queue: int = 4,
    read_share: float = 0.5,
    unaligned: bool = True,
) -> None:
    """Issue ``count`` random requests through ``env.port`` in bursts of up to ``max_queue``."""
    port = env.port
    if port is None:
        raise ValueError(f"cfg {env.cfg.name.upper()}: random traffic needs the AxilPort agent")
    rng = env.rng
    issued = 0
    while issued < count:
        burst = []
        for _ in range(min(rng.randint(1, max_queue), count - issued)):
            addr = base + 4 * rng.randrange(words)
            if unaligned and rng.random() < 0.25:
                addr += rng.randrange(1, 4)
            prot = rng.randrange(8)
            if rng.random() < read_share:
                burst.append(port.issue_read(addr, prot))
            else:
                burst.append(
                    port.issue_write(addr, rng.getrandbits(32), random_strobe(env.cfg, rng), prot)
                )
            issued += 1
        await tb.wait_ops(burst, 5000, f"cfg {env.cfg.name.upper()} random burst")
