# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_reset_release_sync_test.

rst_cold_ni is released at a random phase that sits on no clock edge; the
deassertion edges of the reference-domain outputs are then required to land
on a clk_ref_i rising edge and the subsystem primary-reset deassertions on a
clk_smu_i rising edge, none of them at the release instant itself. Only
alignment is asserted; the synchronizer depth is unstated, so the cycle count
is logged, not compared.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, First, RisingEdge, Timer
from cocotb.utils import get_sim_time

from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_tb_pins import smu_scope

HOLD_REF_CYCLES = 8
BOUND_REF_CYCLES = 2000
MAX_PHASE_ATTEMPTS = 6
TRAILING_REF_CYCLES = 4

REF_DOMAIN = ("rst_cold_n_o", "rst_primary_ref_clk_no")
SMU_DOMAIN = ("rst_primary_smc_clk_n_o", "obs_smc_rst_n_o", "obs_dtp_rst_n_o")


class smu_reset_release_sync_seq:
    """Clock-edge alignment of the cold-reset and primary-reset deassertions."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.cfg = test.cfg
        self.rng = random.Random(test.random_seed() ^ 0x5E5E_C0DE)

    async def _edge_monitor(self, clk, store: list) -> None:
        while True:
            await RisingEdge(clk)
            store.append(get_sim_time("ps"))

    async def _rise_time(self, signal, name: str) -> tuple[str, int | None]:
        bound = Timer(BOUND_REF_CYCLES * self.cfg.ref_clk_period_ns, unit="ns")
        result = await First(RisingEdge(signal), bound)
        if result is bound:
            return name, None
        return name, get_sim_time("ps")

    async def _wait_low(self, signals: dict) -> None:
        for name, sig in signals.items():
            for _ in range(BOUND_REF_CYCLES):
                await RisingEdge(self.dut.clk_ref_i)
                if sample(sig, name) == 0:
                    break
            else:
                raise AssertionError(f"TIMEOUT {name} never asserted low: bound={BOUND_REF_CYCLES}")

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        cfg = self.cfg
        smu = smu_scope(dut)
        await cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        signals = {name: getattr(dut, name) for name in REF_DOMAIN + SMU_DOMAIN}
        # smu.sv wires the DTP's rst_n_i to the SMC primary reset net; the
        # bench's obs_dtp_rst_n_o and obs_smc_rst_n_o taps read the two ends of
        # that one net.
        self.log.info(
            "composition: u_dtp.rst_n_i=%d rst_primary_smc_clk_n_o=%d (one net, two taps)",
            sample(smu.u_dtp.rst_n_i, "u_dtp.rst_n_i"),
            sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o"),
        )

        ref_period_ps = int(round(cfg.ref_clk_period_ns * 1000))
        smu_period_ps = int(round(cfg.smu_clk_period_ns * 1000))
        rises: dict[str, int] = {}
        t_release = None
        ref_edges: list[int] = []
        smu_edges: list[int] = []
        for attempt in range(MAX_PHASE_ATTEMPTS):
            dut.rst_cold_ni.value = 0
            await self._wait_low(signals)
            await ClockCycles(dut.clk_ref_i, HOLD_REF_CYCLES)

            ref_edges.clear()
            smu_edges.clear()
            mon_ref = cocotb.start_soon(self._edge_monitor(dut.clk_ref_i, ref_edges))
            mon_smu = cocotb.start_soon(self._edge_monitor(dut.clk_smu_i, smu_edges))
            waiters = [
                cocotb.start_soon(self._rise_time(sig, name)) for name, sig in signals.items()
            ]

            phase_ps = self.rng.randint(ref_period_ps // 5, (4 * ref_period_ps) // 5)
            await RisingEdge(dut.clk_ref_i)
            await Timer(phase_ps, unit="ps")
            dut.rst_cold_ni.value = 1
            t_release = get_sim_time("ps")

            rises = {}
            for task in waiters:
                name, when = await task
                if when is None:
                    raise AssertionError(
                        f"TIMEOUT {name} did not deassert within {BOUND_REF_CYCLES} clk_ref after release"
                    )
                rises[name] = when
            await ClockCycles(dut.clk_ref_i, TRAILING_REF_CYCLES)
            mon_ref.cancel()
            mon_smu.cancel()
            on_edge = t_release in ref_edges or t_release in smu_edges
            self.log.info(
                "attempt %d: release at %d ps (phase %d ps into clk_ref) on_edge=%s",
                attempt,
                t_release,
                phase_ps,
                on_edge,
            )
            if not on_edge:
                break
        else:
            raise AssertionError("could not place the release off every clock edge")

        sb.expect_true(
            "release instant sits on no clk_ref_i or clk_smu_i rising edge",
            t_release not in ref_edges and t_release not in smu_edges,
        )
        for name, when in rises.items():
            self.log.info(
                "%s deasserted at %d ps, %d ps after release (%.1f clk_ref, %.1f clk_smu)",
                name,
                when,
                when - t_release,
                (when - t_release) / ref_period_ps,
                (when - t_release) / smu_period_ps,
            )
            sb.expect_true(f"{name} deasserts after the release instant", when > t_release)
        for name in REF_DOMAIN:
            sb.expect_true(
                f"{name} deassertion lands on a clk_ref_i rising edge",
                rises[name] in ref_edges,
                evidence="CHK-SMU-RST-PRIMARY-S2"
                if name == "rst_primary_ref_clk_no"
                else "CHK-SMU-RST-COLD-S2",
            )
        for name in SMU_DOMAIN:
            sb.expect_true(
                f"{name} deassertion lands on a clk_smu_i rising edge",
                rises[name] in smu_edges,
                evidence="CHK-SMU-RST-COLD-S2",
            )
        self.log.info(
            "composition: obs_smc_rst_n_o and obs_dtp_rst_n_o rose at %d ps and %d ps "
            "(one net, two taps; not a checker)",
            rises["obs_smc_rst_n_o"],
            rises["obs_dtp_rst_n_o"],
        )
        sb.expect_true(
            "clock monitors observed edges across the release window",
            len(ref_edges) > TRAILING_REF_CYCLES and len(smu_edges) > TRAILING_REF_CYCLES,
        )
