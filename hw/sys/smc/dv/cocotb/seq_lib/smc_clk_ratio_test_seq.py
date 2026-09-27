# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN register traffic across the SMC and peripheral clock domains at a fixed clock ratio.

``clk_rst.adoc`` constrains one input clock only: ``clk_periph_i`` runs at
100 MHz or faster. It states no relation between ``clk_smc_i`` and
``clk_ref_i``, nor between ``clk_smc_i`` and ``clk_periph_i``, so every ratio
between them is a legal configuration. The base test draws each period from a
narrow set in which the SMC clock is always the fastest; the leaves that drive
this sequence pin the periods to a relation that draw never produces.

The sequence first counts the three clocks' rising edges over one window and
requires the counts to match the configured periods, so the leaf is known to
run at the relation its name states. It then drives SEP_IN register traffic
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
from cocotb.triggers import RisingEdge

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

# Rising edges of clk_ref_i over which the three clocks are counted. An edge
# count can differ from the exact ratio by one at either end of the window.
RATIO_WINDOW_REF_EDGES = 240
RATIO_TOLERANCE_EDGES = 1

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


class smc_clk_ratio_test_seq(SmcDecodeProbeSeq):
    """Confirm the configured clock relation, then cross the peripheral clock domain."""

    def __init__(self, name: str = "smc_clk_ratio_test_seq") -> None:
        super().__init__(name)
        self.edges: dict[str, int] = {}

    async def _count_edges(self) -> None:
        dut = cocotb.top
        counts = {"ref": 0, "smc": 0, "periph": 0}
        done = [False]

        async def _count(name: str, clk) -> None:
            while not done[0]:
                await RisingEdge(clk)
                counts[name] += 1

        tasks = [
            cocotb.start_soon(_count("smc", dut.clk_smc_i)),
            cocotb.start_soon(_count("periph", dut.clk_periph_i)),
        ]
        for _ in range(RATIO_WINDOW_REF_EDGES):
            await RisingEdge(dut.clk_ref_i)
            counts["ref"] += 1
        done[0] = True
        for task in tasks:
            task.cancel()
        self.edges = counts

    def _check_ratio(self) -> None:
        cfg = self.cfg
        window_ns = RATIO_WINDOW_REF_EDGES * cfg.ref_clk_period_ns
        for name, period in (("smc", cfg.smc_clk_period_ns), ("periph", cfg.periph_clk_period_ns)):
            want = window_ns / period
            got = self.edges[name]
            assert abs(got - want) <= RATIO_TOLERANCE_EDGES, (
                f"clk_{name}_i made {got} rising edges over {RATIO_WINDOW_REF_EDGES} clk_ref_i "
                f"edges; a {period} ns period against a {cfg.ref_clk_period_ns} ns reference "
                f"gives {want:.1f}"
            )
        cocotb.log.info(
            "CHK-CLK-RATIO-PERIODS: over %d clk_ref_i edges (%d ns) clk_smc_i made %d and "
            "clk_periph_i %d rising edges, the counts the %d / %d / %d ns ref / smc / periph "
            "periods give",
            RATIO_WINDOW_REF_EDGES,
            window_ns,
            self.edges["smc"],
            self.edges["periph"],
            cfg.ref_clk_period_ns,
            cfg.smc_clk_period_ns,
            cfg.periph_clk_period_ns,
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._count_edges()
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
            "CHK-CLK-RATIO-CSR: at %d / %d / %d ns ref / smc / periph, %d SEP_IN accesses into "
            "the SMC and peripheral clock domains returned their generated resets and %d "
            "co-resident UART scratch and I2C target-address patterns (%d exact compares)",
            self.cfg.ref_clk_period_ns,
            self.cfg.smc_clk_period_ns,
            self.cfg.periph_clk_period_ns,
            self.accesses,
            UART_NUM + I2C_NUM,
            value_checks,
        )
