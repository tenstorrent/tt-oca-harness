# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_clock_domain_composition_test.

Each secondary domain is checked at its consumer: clock identity with the
wrapper clock pin at both edges, toggle rate over a window that is a whole
number of every configured period, reset released after bring-up, and, for the
telemetry domain, independence from the primary domain by asserting the SMC
cold reset through the DTP IC_RESET override while rst_telemetry_ni stays
released and clk_telemetry_i keeps toggling.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

from seq_lib.smu_compose_helpers import count_transitions, hier, sample
from seq_lib.smu_jtag_helpers import (
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_SMC_COLD_PORT,
    make_smu_jtag_tap,
    pack_ic_reset_ports,
)
from seq_lib.smu_tb_pins import smu_scope

# Whole multiple of every domain period: the pll_wrap clocks (smu 1.25 or 10,
# ref 10, periph 5 ns) and every wdt period randomize_timing can draw
# (80/100/120 ns).
RATE_WINDOW_NS = 1200
INDEP_WINDOW_NS = 240
EDGE_SAMPLES = 4
BOUND_REF_CYCLES = 2000


class smu_clock_domain_composition_seq:
    """Telemetry, SEP-watchdog and peripheral domains on their own clock and reset."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.cfg = test.cfg

    async def _wait_value(self, signal, expected: int, name: str, limit: int) -> int:
        last = None
        for cycle in range(limit):
            await RisingEdge(self.dut.clk_ref_i)
            last = sample(signal, name)
            if last == expected:
                return cycle
        raise AssertionError(f"TIMEOUT {name}: bound={limit} last={last} expected={expected}")

    async def _edge_identity(self, pin, pin_name: str, consumers: dict) -> int:
        mismatches = 0
        for _ in range(EDGE_SAMPLES):
            for edge in (RisingEdge, FallingEdge):
                await edge(pin)
                await Timer(1, unit="ns")
                ref = sample(pin, pin_name)
                for name, sig in consumers.items():
                    if sample(sig, name) != ref:
                        mismatches += 1
        return mismatches

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        cfg = self.cfg
        smu = smu_scope(dut)
        await cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        tel_clk = hier(smu, "u_smc.clk_telemetry_i")
        tel_rst = hier(smu, "u_smc.rst_telemetry_ni")
        periph_clk = hier(smu, "u_smc.clk_periph_i")
        periph_rst = hier(smu, "u_smc.rst_primary_periph_clk_no")
        wdt_rst = hier(smu, "rst_wdt_n")
        wdt_rst_src = hier(smu, "u_smc.rst_wdt_smc_clk_no")
        wdt_clk = dut.obs_sep_wdt_clk_o
        smc_clk = dut.obs_smc_clk_o

        periods = {
            "clk_smu_i": cfg.smu_clk_period_ns,
            "clk_ref_i": cfg.ref_clk_period_ns,
            "clk_periph_i": cfg.periph_clk_period_ns,
            "clk_sep_wdt_i": cfg.sep_wdt_clk_period_ns,
        }
        for other in ("clk_ref_i", "clk_periph_i", "clk_sep_wdt_i"):
            if periods[other] == periods["clk_smu_i"]:
                raise AssertionError(
                    f"{other} and clk_smu_i share a {periods[other]} ns period; domain separation "
                    "is not observable at this seed"
                )
        self.log.info("domain periods (ns): %s", periods)

        # Clock identity at the consumers, both edges.
        domains = (
            (
                "clk_ref_i",
                dut.clk_ref_i,
                {
                    "u_smc.clk_telemetry_i": tel_clk,
                    "smu.clk_telemetry_i": hier(smu, "clk_telemetry_i"),
                },
                "CHK-SMU-CLK-DOMAINS-S2",
            ),
            (
                "clk_sep_wdt_i",
                dut.clk_sep_wdt_i,
                {"obs_sep_wdt_clk_o": wdt_clk, "smu.clk_sep_wdt_i": hier(smu, "clk_sep_wdt_i")},
                "CHK-SMU-CLK-DOMAINS-S3",
            ),
            (
                "clk_periph_o",
                dut.clk_periph_o,
                {"u_smc.clk_periph_i": periph_clk},
                "CHK-SMU-CLK-DOMAINS-S4",
            ),
        )
        for pin_name, pin, consumers, token in domains:
            mism = await self._edge_identity(pin, pin_name, consumers)
            sb.expect_eq(
                f"{pin_name} identity at {sorted(consumers)} over {2 * EDGE_SAMPLES} edges",
                mism,
                0,
                evidence=token,
            )

        # Toggle rate at the consumers over a whole number of every period.
        counts = await count_transitions(
            {
                "telemetry": tel_clk,
                "sep_wdt": wdt_clk,
                "periph": periph_clk,
                "smc": smc_clk,
            },
            RATE_WINDOW_NS,
        )
        expected = {
            "telemetry": round(2 * RATE_WINDOW_NS / periods["clk_ref_i"]),
            "sep_wdt": round(2 * RATE_WINDOW_NS / periods["clk_sep_wdt_i"]),
            "periph": round(2 * RATE_WINDOW_NS / periods["clk_periph_i"]),
            "smc": round(2 * RATE_WINDOW_NS / periods["clk_smu_i"]),
        }
        self.log.info("transitions over %d ns: %s expected %s", RATE_WINDOW_NS, counts, expected)
        tokens = {
            "telemetry": "CHK-SMU-CLK-DOMAINS-S2",
            "sep_wdt": "CHK-SMU-CLK-DOMAINS-S3",
            "periph": "CHK-SMU-CLK-DOMAINS-S4",
        }
        for name, token in tokens.items():
            sb.expect_true(
                f"{name} consumer toggles at its own period ({counts[name]} vs {expected[name]})",
                abs(counts[name] - expected[name]) <= 1,
                evidence=token,
            )
            sb.expect_true(
                f"{name} consumer does not toggle at the clk_smu_i rate",
                counts[name] != counts["smc"],
                evidence=token,
            )
        sb.expect_true(
            "clk_smu_i consumer toggles at the primary period",
            abs(counts["smc"] - expected["smc"]) <= 1,
        )

        # Resets released after bring-up, seen at the consumer.
        sb.expect_eq(
            "rst_telemetry_ni released at the SMC consumer and the smu port",
            (
                sample(tel_rst, "u_smc.rst_telemetry_ni"),
                sample(hier(smu, "rst_telemetry_ni"), "smu.rst_telemetry_ni"),
            ),
            (1, 1),
            evidence="CHK-SMU-CLK-DOMAINS-S2",
        )
        sb.expect_eq(
            "rst_wdt_n released and sourced from the SMC watchdog reset",
            (sample(wdt_rst, "rst_wdt_n"), sample(wdt_rst_src, "u_smc.rst_wdt_smc_clk_no")),
            (1, 1),
            evidence="CHK-SMU-CLK-DOMAINS-S3",
        )
        sb.expect_eq(
            "rst_primary_periph_clk_no released at the SMC and the boundary",
            (
                sample(periph_rst, "u_smc.rst_primary_periph_clk_no"),
                sample(dut.rst_primary_periph_clk_no, "rst_primary_periph_clk_no"),
            ),
            (1, 1),
            evidence="CHK-SMU-CLK-DOMAINS-S4",
        )

        # Independence: assert the SMC cold reset through IC_RESET; the primary
        # and peripheral resets follow, the telemetry reset does not.
        jtag = make_smu_jtag_tap(dut, cfg.jtag_period_ns)
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)
        smc_assert = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_SMC_COLD_PORT: 0},
            port_control={SMU_IC_RESET_SMC_COLD_PORT: 0},
        )
        await jtag.write("IC_RESET", smc_assert)
        cycles = await self._wait_value(
            dut.rst_primary_smc_clk_n_o, 0, "rst_primary_smc_clk_n_o", BOUND_REF_CYCLES
        )
        self.log.info("IC_RESET cold override asserted primary reset after %d clk_ref", cycles)
        sb.expect_eq(
            "override asserted: SMC primary reset low at the consumer",
            sample(dut.obs_smc_rst_n_o, "obs_smc_rst_n_o"),
            0,
        )
        sb.expect_eq(
            "override asserted: peripheral primary reset low",
            sample(periph_rst, "u_smc.rst_primary_periph_clk_no"),
            0,
            evidence="CHK-SMU-CLK-DOMAINS-S4",
        )
        wdt_under_override = sample(wdt_rst, "rst_wdt_n")
        self.log.info("rst_wdt_n while the SMC cold override is asserted: %d", wdt_under_override)
        tel_rst_held = []
        for _ in range(16):
            await RisingEdge(dut.clk_ref_i)
            tel_rst_held.append(sample(tel_rst, "u_smc.rst_telemetry_ni"))
        sb.expect_true(
            "rst_telemetry_ni stays released while the primary domain is in reset",
            all(v == 1 for v in tel_rst_held),
            evidence="CHK-SMU-CLK-DOMAINS-S2",
        )
        indep = await count_transitions({"telemetry": tel_clk, "smc": smc_clk}, INDEP_WINDOW_NS)
        sb.expect_true(
            "clk_telemetry_i keeps toggling at the consumer during primary reset",
            indep["telemetry"] > 0,
            evidence="CHK-SMU-CLK-DOMAINS-S2",
        )

        await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
        for name, sig in (
            ("rst_primary_smc_clk_n_o", dut.rst_primary_smc_clk_n_o),
            ("rst_primary_periph_clk_no", dut.rst_primary_periph_clk_no),
            ("rst_cold_n_o", dut.rst_cold_n_o),
            ("rst_wdt_n", wdt_rst),
        ):
            cycles = await self._wait_value(sig, 1, name, BOUND_REF_CYCLES)
            self.log.info("%s released %d clk_ref after clearing the override", name, cycles)
        sb.expect_eq(
            "domains back out of reset after the override clears",
            (
                sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o"),
                sample(periph_rst, "u_smc.rst_primary_periph_clk_no"),
                sample(wdt_rst, "rst_wdt_n"),
                sample(tel_rst, "u_smc.rst_telemetry_ni"),
            ),
            (1, 1, 1, 1),
        )
