# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM environment configuration object."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Event, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import OcahAxiConfig, OcahAxiProtocol, OcahAxiSlaveSequence
from pyuvm import uvm_object

from .smc_memory_model import SmcMemoryModel

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


# SYS_OUT AXI4 egress geometry (smc_pkg smc_sys_out_56_64_8_12_axi_*) and the
# responder's sparse memory span; the dual bench binds one responder per
# instance from the same values.
SYS_OUT_AXI_GEOMETRY = OcahAxiConfig(
    protocol=OcahAxiProtocol.AXI4,
    addr_width=56,
    data_width=64,
    id_width=8,
    user_width=12,
)
SYS_OUT_MEM_SIZE = 1 << 56


class SmcEnvCfg(uvm_object):
    """Shared environment configuration / handshakes for the SMC OSS TB."""

    def __init__(self, name: str = "SmcEnvCfg") -> None:
        super().__init__(name)
        # Periods of the three clock domains the bench drives into pll_wrap
        # through clk_ref_i / clk_smc_i / clk_periph_i. ``resolve_timing``
        # takes the sys period from the plusarg.
        self.ref_clk_period_ns = PLL_REF_CLK_PERIOD_NS
        self.smc_clk_period_ns = PLL_SYS_CLK_PERIOD_NS_DEFAULT
        self.periph_clk_period_ns = PLL_PERIPH_CLK_PERIOD_NS
        # Cycles to wait after cold reset deassertion before sampling.
        self.post_reset_settle_cycles = 500
        self.axi_timeout_ns = 50_000
        # Testcase-local golden memory. This is not a DUT backdoor; sequences
        # use it to track data driven through public AXI/protocol VIP paths.
        self.memory_model = SmcMemoryModel()
        # Slave sequence of the SYS_OUT responder smc_base_test.bring_up binds to
        # u_output_axi_if: backdoor memory access and one-shot faults.
        self.sys_out_mem: OcahAxiSlaveSequence | None = None
        # Set by the base test once clocks are running and cold reset is
        # released, so the env agents start their observations at the right
        # time.
        self.reset_done = Event("smc_reset_done")

    def resolve_timing(self) -> None:
        """Take the sys-clock period from ``+pll_sys_period_ns``."""
        self.smc_clk_period_ns = pll_sys_clk_period_ns()
