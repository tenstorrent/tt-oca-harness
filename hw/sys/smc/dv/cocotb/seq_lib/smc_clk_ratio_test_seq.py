# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN register traffic across the SMC and peripheral clock domains at a fixed clock ratio.

``clk_rst.adoc`` constrains one input clock only: ``clk_periph_i`` runs at
100 MHz or faster. It states no relation between ``clk_smc_i`` and
``clk_ref_i``, nor between ``clk_smc_i`` and ``clk_periph_i``, so every ratio
between them is a legal configuration. The bench drives ref / periph at
10 / 5 ns and the SMC clock at the ``+pll_sys_period_ns`` period (1.25 ns by
default), so the SMC clock runs more than twice the reference and the
peripheral clock twice it. The leaves that drive this sequence pin the other
relations, one leaf per cell of ``smc_clk_fcov``'s ``cg_clk_ratio`` cross: the
SMC clock slower than, equal to, up to twice or more than twice the
reference, against the peripheral clock slower than, equal to, up to twice or
more than twice it. Each leaf states its ref / smc / periph periods.

The sequence first measures each clock's period over its own rising edges
and requires the period the leaf declares, then counts the SMC and peripheral
edges together across one ratio-collector window of reference edges and
requires the counts the declared periods give and the cg_clk_ratio classes the
leaf names. That is a stimulus-integrity check: it shows the bench drove the
declared relation, not a property of the DUT. It then drives SEP_IN register traffic
into blocks on both sides of the peripheral clock-domain crossing: exact
compares of non-zero generated resets, and distinct patterns written to every
UART scratch register and every I2C target address before any is read back,
so a crossing that drops or reorders a transfer at this ratio returns the
wrong word.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import GLOBAL_BASE_RESET, smc_addr, smc_indexed_addr
from .smc_decode_probe_utils import SmcDecodeProbeSeq
from .smc_output_fabric_vip_utils import reg_field_pack

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT,
    I2C_TARGET_ID_REG_DEFAULT,
    UART_16550_MAIN_LSR_REG_DEFAULT,
    UART_16550_MAIN_SCR_REG_DEFAULT,
    WDT_CMP_REG_DEFAULT,
)

# Rising edges of each clock over which its period is measured.
RATIO_WINDOW_EDGES = 64
# Reference-clock edges over which the SMC and peripheral edges are counted
# together: smc_clk_fcov's WindowCycles, so the run spans at least one closed
# window of the ratio collector at the relation it pins.
RELATION_WINDOW_REF_EDGES = 1024

GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
WDT0_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
AVS_CFG_0 = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")
UART_NUM = smc_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_NUM")
I2C_NUM = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_NUM")

_UART_SCR_PATTERNS = (0x5A, 0xA5, 0x3C, 0xC3)
assert len(_UART_SCR_PATTERNS) == UART_NUM


def _uart(reg: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_{reg}_BASE_ADDR", idx)


def _i2c_target_id(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", idx)


# Reads carrying an exact expectation and total SEP_IN accesses the body issues.
EXPECTED_VALUE_CHECKS = 3 + UART_NUM + 2 * (UART_NUM + I2C_NUM)
EXPECTED_ACCESSES = 3 + UART_NUM + 4 * (UART_NUM + I2C_NUM)


# The relation classes smc_clk_fcov's cg_clk_ratio buckets a domain into, by its
# edge count per reference edge in quarters over one window.
_RELATION_BUCKETS = (
    ("slower", range(1, 4)),
    ("same", range(4, 5)),
    ("faster", range(5, 9)),
    ("much_faster", range(9, 33)),
)


def relation_class(edges: int, ref_edges: int) -> str:
    """The cg_clk_ratio bucket a domain with ``edges`` per ``ref_edges`` falls in."""
    quarters = (edges * 4) // ref_edges
    for name, bucket in _RELATION_BUCKETS:
        if quarters in bucket:
            return name
    return "stalled" if quarters == 0 else "beyond"


class smc_clk_ratio_test_seq(SmcDecodeProbeSeq):
    """Confirm the declared clock relation, then cross the peripheral clock domain.

    ``periods_ns`` is the leaf's declared ref / smc / periph periods and
    ``relations`` the cg_clk_ratio classes its name states for the SMC and the
    peripheral clock against the reference. The measured clocks are compared
    with those, not with the bench configuration that drives them.
    """

    def __init__(
        self,
        name: str = "smc_clk_ratio_test_seq",
        *,
        periods_ns: tuple[float, float, float],
        relations: tuple[str, str],
    ) -> None:
        super().__init__(name)
        self.declared_ns = dict(zip(("ref", "smc", "periph"), periods_ns))
        self.declared_relations = dict(zip(("smc", "periph"), relations))
        self.periods_ps: dict[str, float] = {}
        self.relation_edges: dict[str, int] = {}
        self.measured_relations: dict[str, str] = {}

    async def _measure_periods(self) -> None:
        """Mean period of each input clock over RATIO_WINDOW_EDGES of its own rising edges."""
        dut = cocotb.top
        for name, clk in (
            ("ref", dut.clk_ref_i),
            ("smc", dut.clk_smc_i),
            ("periph", dut.clk_periph_i),
        ):
            await RisingEdge(clk)
            start = get_sim_time("ps")
            for _ in range(RATIO_WINDOW_EDGES):
                await RisingEdge(clk)
            self.periods_ps[name] = (get_sim_time("ps") - start) / RATIO_WINDOW_EDGES

    async def _count_relation(self) -> None:
        """Count SMC and peripheral rising edges across one window of reference periods.

        Each clock's rising edges are timestamped by a task of its own, and the
        window is a half-open span of simulation time that opens on a reference
        edge every task is already waiting for. An edge that coincides with a
        window bound is therefore counted by its timestamp, not by the order in
        which the simulator wakes the tasks in that timestep.
        """
        dut = cocotb.top
        stamps: dict[str, list[float]] = {"smc": [], "periph": []}

        async def stamp(name: str, clk) -> None:
            while True:
                await RisingEdge(clk)
                stamps[name].append(get_sim_time("ps"))

        ref_period_ps = self.declared_ns["ref"] * 1000
        await RisingEdge(dut.clk_ref_i)
        tasks = [
            cocotb.start_soon(stamp("smc", dut.clk_smc_i)),
            cocotb.start_soon(stamp("periph", dut.clk_periph_i)),
        ]
        start = get_sim_time("ps") + ref_period_ps
        end = start + RELATION_WINDOW_REF_EDGES * ref_period_ps
        await ClockCycles(dut.clk_ref_i, RELATION_WINDOW_REF_EDGES + 2)
        for task in tasks:
            task.cancel()
        self.relation_edges = {
            name: sum(1 for t in edges if start <= t < end) for name, edges in stamps.items()
        }

    def _check_ratio(self) -> None:
        want = self.declared_ns
        for name, period_ns in want.items():
            got = self.periods_ps[name]
            assert got == period_ns * 1000, (
                f"clk_{name}_i measured {got:.1f} ps per cycle over {RATIO_WINDOW_EDGES} "
                f"rising edges; the leaf declares {period_ns} ns, so the bench did not drive "
                f"the declared period"
            )
        span_ps = RELATION_WINDOW_REF_EDGES * want["ref"] * 1000
        expected = {
            "smc": span_ps / (want["smc"] * 1000),
            "periph": span_ps / (want["periph"] * 1000),
        }
        for name, want_edges in expected.items():
            got = self.relation_edges[name]
            assert abs(got - want_edges) <= 1, (
                f"clk_{name}_i made {got} rising edges across {RELATION_WINDOW_REF_EDGES} "
                f"clk_ref_i edges; the declared periods give {want_edges:g}"
            )
            self.measured_relations[name] = relation_class(got, RELATION_WINDOW_REF_EDGES)
        assert self.measured_relations == self.declared_relations, (
            f"the edge counts put the SMC / peripheral clock in the cg_clk_ratio classes "
            f"{self.measured_relations['smc']} / {self.measured_relations['periph']}; the leaf "
            f"names {self.declared_relations['smc']} / {self.declared_relations['periph']}"
        )
        cocotb.log.info(
            "CHK-CLK-RATIO-PERIODS: over %d rising edges each, clk_ref_i / clk_smc_i / "
            "clk_periph_i measured %d / %d / %d ps per cycle, the periods the leaf declares; "
            "across %d clk_ref_i edges clk_smc_i made %d and clk_periph_i %d rising edges (%g "
            "and %g from the declared periods), the cg_clk_ratio classes %s / %s the leaf names",
            RATIO_WINDOW_EDGES,
            self.periods_ps["ref"],
            self.periods_ps["smc"],
            self.periods_ps["periph"],
            RELATION_WINDOW_REF_EDGES,
            self.relation_edges["smc"],
            self.relation_edges["periph"],
            expected["smc"],
            expected["periph"],
            self.measured_relations["smc"],
            self.measured_relations["periph"],
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._measure_periods()
        await self._count_relation()
        self._check_ratio()

        value_checks_before = self.env.scoreboard.sys_axi_value_checks_seen
        # clk_smc_i domain: the fabric base configuration and a watchdog.
        await self.read_reset("GLOBAL_BASE", GLOBAL_BASE, GLOBAL_BASE_RESET, length=8)
        await self.read_reset("WDT0_CMP", WDT0_CMP, WDT_CMP_REG_DEFAULT)
        # clk_periph_i domain, behind the peripheral AXI-Lite crossing.
        await self.read_reset("AVS_CFG_0", AVS_CFG_0, AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT)
        for idx in range(UART_NUM):
            await self.read_reset(
                f"UART{idx}_LSR", _uart("LSR", idx), UART_16550_MAIN_LSR_REG_DEFAULT
            )
        await self.rw_coresident(
            [
                (
                    f"UART{idx}_SCR",
                    _uart("SCR", idx),
                    _UART_SCR_PATTERNS[idx],
                    UART_16550_MAIN_SCR_REG_DEFAULT,
                )
                for idx in range(UART_NUM)
            ]
            + [
                (
                    f"I2C{idx}_TARGET_ID",
                    _i2c_target_id(idx),
                    reg_field_pack("I2C_TARGET_ID_reg_t", address0=0x31 + idx, mask0=0x7F),
                    I2C_TARGET_ID_REG_DEFAULT,
                )
                for idx in range(I2C_NUM)
            ]
        )
        value_checks = self.env.scoreboard.sys_axi_value_checks_seen - value_checks_before
        assert value_checks >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {value_checks} exact-value compares, expected at least "
            f"{EXPECTED_VALUE_CHECKS}"
        )
        self.assert_all_reachable(EXPECTED_ACCESSES, "CLK_RATIO")
        cocotb.log.info(
            "CHK-CLK-RATIO-CSR: at %s / %s / %s ns ref / smc / periph, %d SEP_IN accesses into "
            "the SMC and peripheral clock domains returned their generated resets and %d "
            "co-resident UART scratch and I2C target-address patterns (%d exact compares)",
            self.declared_ns["ref"],
            self.declared_ns["smc"],
            self.declared_ns["periph"],
            self.accesses,
            UART_NUM + I2C_NUM,
            value_checks,
        )
