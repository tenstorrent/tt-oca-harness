# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Configuration and deterministic timing choices for the SMU OSS environment."""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import Event, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import OcahAxiConfig, OcahAxiProtocol, OcahAxiSlaveSequence
from pyuvm import uvm_object

# Periods of the three domain clocks, as pll_wrap (hw/sys/smc/dv/models/
# pll_wrap.sv) defines them: ref and periph are fixed, sys follows
# +pll_sys_period_ns and defaults to 800 MHz. The bench toggles the model's
# oscillators at these periods through the clock inputs.
PLL_REF_CLK_PERIOD_NS = 10
PLL_PERIPH_CLK_PERIOD_NS = 5
PLL_SYS_CLK_PERIOD_NS_DEFAULT = 1.25
PLL_SYS_CLK_PERIODS_NS = (1.25, 10.0)
# Relative tolerance the measured model outputs are held to at bring-up.
PLL_PERIOD_TOLERANCE = 0.01


def pll_sys_clk_period_ns() -> float:
    """Return the sys-clock period for this simulation.

    Reads the same ``+pll_sys_period_ns`` plusarg pll_wrap reads, so the
    sequences' wait-math, the clock the bench drives and a free-running model
    all agree.
    """
    raw = cocotb.plusargs.get("pll_sys_period_ns")
    if raw is None or raw is True:
        return PLL_SYS_CLK_PERIOD_NS_DEFAULT
    period = float(raw)
    if period not in PLL_SYS_CLK_PERIODS_NS:
        raise ValueError(f"+pll_sys_period_ns={raw}: pll_wrap accepts {PLL_SYS_CLK_PERIODS_NS}")
    return period


async def measure_clock_period_ns(clk, edges: int = 4) -> float:
    """Return the mean period of ``clk`` over ``edges`` rising edges, in ns."""
    await RisingEdge(clk)
    start_ps = get_sim_time("ps")
    for _ in range(edges):
        await RisingEdge(clk)
    return (get_sim_time("ps") - start_ps) / edges / 1000.0


async def check_pll_clock_periods(log, clocks: dict) -> None:
    """Measure each ``name: (handle, expected_ns)`` model clock and hold it to the cfg.

    Run after the primary reset has released: the anti-glitch mux in pll_wrap
    selects the reference oscillator while its reset is asserted.
    """
    for name, (clk, want_ns) in clocks.items():
        got_ns = await measure_clock_period_ns(clk)
        log.info(
            "PLL clock %s: measured %.4f ns (%.1f MHz), cfg %s ns",
            name,
            got_ns,
            1000.0 / got_ns,
            want_ns,
        )
        assert abs(got_ns - want_ns) <= PLL_PERIOD_TOLERANCE * want_ns, (
            f"{name} runs at {got_ns:.4f} ns but the env cfg expects {want_ns} ns: the "
            f"clock pll_wrap delivers does not match the one the bench drives"
        )


class SmuEnvCfg(uvm_object):
    """Shared clock/reset configuration for SMU wrapper tests."""

    def __init__(self, name: str = "SmuEnvCfg") -> None:
        super().__init__(name)
        # clk_ref_i / clk_smu_i / clk_periph_i toggle the pll_wrap oscillators
        # inside the wrapper; ``resolve_pll_timing`` takes the sys period from
        # the plusarg.
        self.ref_clk_period_ns = PLL_REF_CLK_PERIOD_NS
        self.smu_clk_period_ns = PLL_SYS_CLK_PERIOD_NS_DEFAULT
        self.periph_clk_period_ns = PLL_PERIPH_CLK_PERIOD_NS
        # Clocks the bench owns outright.
        self.entropy_clk_period_ns = 3
        self.sep_wdt_clk_period_ns = 100
        self.jtag_period_ns = 40
        self.idle_tck = 2
        self.post_reset_settle_cycles = 500
        self.powergood_delay_cycles = 8
        self.reset_hold_cycles = 12
        self.post_reset_cycles = 24
        self.reset_done = Event("smu_reset_done")
        # Outbound SMN AXI4 egress: the crossbar's ext_out geometry
        # (smu_axi_xbar_pkg axi_out_*), the responder's sparse memory span, and
        # the slave sequence smu_base_test.bring_up binds to u_axi_out_if
        # (backdoor memory access, one-shot faults).
        self.axi_out_geometry = OcahAxiConfig(
            protocol=OcahAxiProtocol.AXI4,
            addr_width=56,
            data_width=64,
            id_width=10,
            user_width=12,
        )
        self.axi_out_mem_size = 1 << 56
        self.axi_out_mem: OcahAxiSlaveSequence | None = None

    def resolve_pll_timing(self) -> None:
        """Take the sys-clock period from ``+pll_sys_period_ns``."""
        self.smu_clk_period_ns = pll_sys_clk_period_ns()

    def randomize_timing(self, seed: int) -> None:
        """Choose the bench-owned clock periods and the reset timing from the seed."""
        rng = random.Random(seed)
        self.sep_wdt_clk_period_ns = rng.choice((80, 100, 120))
        self.powergood_delay_cycles = rng.randint(6, 10)
        self.reset_hold_cycles = rng.randint(10, 16)
        self.post_reset_cycles = rng.randint(20, 32)
        # The sequences under cocotb/seq_lib read these off cfg and raise
        # AttributeError without them.
        self.jtag_period_ns = rng.choice((32, 40, 48))
        self.idle_tck = rng.randint(2, 4)
        self.post_reset_settle_cycles = rng.randint(500, 700)
