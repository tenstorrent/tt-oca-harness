# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""test_en_i reaches every SEP-owned clock-gater test port and AXI cell test input.

no_cpu on ``lsu_stub_all_live`` with ``+skip_fuse_sense`` (no fuse content is
used), VCS only (the walk reads the hierarchy). No draw: every run walks the
same hierarchy and drives the same two edges.

Contract (``hw/sys/sep/doc/port_table.adoc``, ``test_en_i``: "Drives
clock-gater test ports and AXI cell test inputs."; read as every such input;
``hw/ip/key_manager/doc/architecture.adoc``, ``test_en_i`` drives the test
inputs of ``u_xbar`` and ``u_mailbox``;
``hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc``, ``test_en_i`` supplies
the AXI demultiplexer test input):

* Every graded pin equals ``test_en_i`` within ``PIN_BOUND`` ``clk_i`` cycles
  after the 0 to 1 edge and after the 1 to 0 edge of ``test_en_i``.

Graded set: ``env/sep_test_en_walk.py`` walks ``u_dut`` and grades a pin when
the module that instantiates its cell is OCAH-owned (the SEP-owned boundary).
Pins nested inside vendor IP or a third-party library, and every pin inside
``sep_cpu`` (a different module on the CPU-stub and the full-CPU build), are
logged with a count per group and not graded. ``PIN_BOUND`` is a bench bound:
the specification states no latency.

Checkers:
  CTL-PIN-WALK      the walk finds at least one graded pin of each class, and
                    no instantiating module is unresolved.
  CHK-TEST-EN-PINS  every graded pin equals test_en_i PIN_BOUND clk_i cycles
                    after each edge. A FAIL names every pin that does not
                    (path, class, cell, instantiating module, edge).

The graded window (owner code of this test) is open from the 0 to 1 edge to
the end of the hold after the 1 to 0 edge.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_test_en_walk import (
    CLASS_NAMES,
    PIN_BOUND,
    TestEnPin,
    pin_value,
    pins_not_equal,
    walk_test_en_pins,
)
from sep_base_test import sep_base_test

TEST = "sep_test_en_pin_reach_test"

H = 32  # hold after the bound, clk_i cycles (test parameter)
SENSE_BOUND = 20_000
FAIL_LINES = 64  # failing pins printed in the FAIL line; every pin has a log line


@pyuvm.test()
class sep_test_en_pin_reach_test(sep_base_test):
    """Every SEP-owned test pin follows test_en_i on both edges."""

    required_evidence = ("CHK-TEST-EN-PINS",)

    async def _edge(self, pins: list[TestEnPin], value: int) -> tuple[list[TestEnPin], int]:
        """Drive test_en_i to ``value`` and read the pins PIN_BOUND cycles later.

        Returns the pins that do not equal ``value`` at that edge and the count
        that equal it on the first clk_i edge after the drive.
        """
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = value
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        first = sum(1 for p in pins if pin_value(p) == value)
        await ClockCycles(dut.clk_i, PIN_BOUND - 1)
        await ReadOnly()
        bad = pins_not_equal(pins, value)
        await RisingEdge(dut.clk_i)
        await ClockCycles(dut.clk_i, H)
        return bad, first

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.logger.info("CFG pin_bound=%d hold=%d (no draw)", PIN_BOUND, H)
        dut = cocotb.top
        close_graded_window(self.logger)
        dut.test_en_i.value = 0
        dut.scan_rst_ni_i.value = 1
        await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        dut.test_en_i.value = 0
        dut.scan_rst_ni_i.value = 1

        walk = walk_test_en_pins(dut.u_dut, "u_dut")
        graded = walk.graded
        self.logger.info(
            "TEST-EN-WALK LOG: root=%s scopes=%d pins=%d graded=%d index_files=%d",
            walk.root,
            walk.scopes,
            len(walk.pins),
            len(graded),
            walk.index.files,
        )
        for p in walk.pins:
            self.logger.info(
                "TEST-EN-PIN LOG: %s owner=%s graded=%d", p.label(), p.owner, int(p.graded)
            )
        logged = walk.logged_counts()
        for owner, n in logged.items():
            self.logger.info("OBS-TEST-EN-UNGRADED: group=%s pins=%d", owner, n)
        per_class = {c: walk.graded_count(c) for c in CLASS_NAMES}
        unresolved = walk.unresolved()
        for p in unresolved:
            self.logger.info("CTL-PIN-WALK unresolved: %s", p.label())
        assert all(n > 0 for n in per_class.values()) and not unresolved, (
            "CTL-PIN-WALK FAIL: graded "
            + " ".join(f"{c}={n}" for c, n in per_class.items())
            + f" unresolved={len(unresolved)} (each class needs a graded pin and every "
            "instantiating module must resolve)"
        )
        self.logger.info(
            "CTL-PIN-WALK: graded %s unresolved=0 logged=%s",
            " ".join(f"{c}={n}" for c, n in per_class.items()),
            ",".join(f"{k}:{v}" for k, v in logged.items()) or "none",
        )

        await ReadOnly()
        base = pins_not_equal(graded, 0)
        await RisingEdge(dut.clk_i)
        self.logger.info(
            "TEST-EN-BASE LOG: test_en_i=0 graded pins not 0 before the first edge=%d", len(base)
        )

        open_graded_window(TEST, self.logger)
        rise_bad, rise_first = await self._edge(graded, 1)
        fall_bad, fall_first = await self._edge(graded, 0)
        close_graded_window(self.logger)

        failing: list[tuple[TestEnPin, str]] = [(p, "0to1") for p in rise_bad]
        failing += [(p, "1to0") for p in fall_bad]
        for p, edge in failing:
            self.logger.info(
                "TEST-EN-PINS not_following: edge=%s %s value=%s",
                edge,
                p.label(),
                pin_value(p),
            )
        parents = sorted({f"{p.parent}.{p.cell}" for p, _e in failing})
        for name in parents:
            n = sum(1 for p, _e in failing if f"{p.parent}.{p.cell}" == name)
            self.logger.info("TEST-EN-PINS group: parent.cell=%s failing_edges=%d", name, n)
        counts = (
            f"graded={len(graded)} "
            + " ".join(f"{c}={n}" for c, n in per_class.items())
            + f" fail_0to1={len(rise_bad)} fail_1to0={len(fall_bad)}"
            f" follow_first_edge_0to1={rise_first} follow_first_edge_1to0={fall_first}"
            f" pin_bound={PIN_BOUND}"
        )
        assert not failing, (
            f"CHK-TEST-EN-PINS FAIL: {counts}: "
            + "; ".join(f"{e}:{p.path} ({p.cls}, {p.parent})" for p, e in failing[:FAIL_LINES])
            + (" ..." if len(failing) > FAIL_LINES else "")
        )
        self.logger.info("CHK-TEST-EN-PINS PASS: %s", counts)
        self.result_pass(TEST, seed, 1)
