# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""test_en_i reaches every SEP-owned clock-gater test port and AXI cell test input.

no_cpu on ``lsu_stub_all_live`` with ``+skip_fuse_sense`` (no fuse content is
used), VCS only (the walk reads the hierarchy). No draw: every run walks the
same hierarchy and drives the same two edges. The test drives no AXI
traffic, so it builds no AXI environment and no AXI scoreboard
(``build_env = False``); its evidence is the CHK line on the DUT pins.

Contract (``hw/sys/sep/doc/port_table.adoc``, ``test_en_i``: "Drives
clock-gater test ports and AXI cell test inputs."; read as every such input;
``hw/ip/key_manager/doc/architecture.adoc``, ``test_en_i`` drives the test
inputs of ``u_xbar`` and ``u_mailbox``;
``hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc``, ``test_en_i`` supplies
the AXI demultiplexer test input):

* Every graded pin equals ``test_en_i`` within ``PIN_BOUND`` ``clk_i`` cycles
  after the 0 to 1 edge and after the 1 to 0 edge of ``test_en_i``.

Graded set: the committed inventory ``GRADED_PINS``
(``sep_test_en_pin_inventory.py``, path and class of each pin). Its selection
rule is the SEP-owned boundary: the test inputs of the clock-gater and AXI cell
instances that OCAH RTL instantiates, without the pins inside ``sep_cpu`` (a
different module on the CPU-stub and the full-CPU build), on the
``lsu_stub_all_live`` build. The inventory changes only by a reviewed edit.
It is bench configuration that sets the scope of the "every such input"
reading, not a behaviour golden. ``env/sep_test_en_walk.py`` walks ``u_dut``
and finds the handle of each inventory pin. Its source-tree ownership scan
gives the group of each walked pin for the log only: it never selects or fails
a graded pin. ``PIN_BOUND`` is a bench bound: the specification states no
latency.

Checkers:
  CTL-PIN-WALK      every inventory pin is in the walk with its inventory
                    class: a FAIL names every inventory pin that is not walked
                    and every class mismatch. Walked pins that are not in the
                    inventory are logged with their group and a count per
                    group (OBS-TEST-EN-UNGRADED), and scopes that the simulator
                    cannot iterate are logged by name (OBS-TEST-EN-UNWALKABLE).
  CHK-TEST-EN-PINS  every inventory pin equals test_en_i PIN_BOUND clk_i
                    cycles after each edge. A FAIL names every pin that does
                    not (path, class, cell, instantiating module, edge). A pin
                    that holds 0 on both edges equals test_en_i after the 1 to
                    0 edge, so it fails the 0 to 1 edge only; the FAIL line
                    counts it in fail_pins and in stuck_0.

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
    TestEnWalk,
    pin_value,
    pins_not_equal,
    walk_test_en_pins,
)
from sep_base_test import sep_base_test

from tests.system.sep_test_en_pin_inventory import GRADED_PINS

TEST = "sep_test_en_pin_reach_test"

H = 32  # hold after the bound, clk_i cycles (test parameter)
SENSE_BOUND = 20_000
FAIL_LINES = 64  # failing pins printed in the FAIL line; every pin has a log line


@pyuvm.test()
class sep_test_en_pin_reach_test(sep_base_test):
    """Every SEP-owned test pin follows test_en_i on both edges."""

    build_env = False
    required_evidence = ("CHK-TEST-EN-PINS",)

    async def _edge(
        self, pins: list[TestEnPin], value: int
    ) -> tuple[list[TestEnPin], int, dict[str, int | None]]:
        """Drive test_en_i to ``value`` and read the pins PIN_BOUND cycles later.

        Returns the pins that do not equal ``value`` at that edge, the count
        that equal it on the first clk_i edge after the drive, and the value of
        each pin at the PIN_BOUND read.
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
        vals = {p.path: pin_value(p) for p in pins}
        await RisingEdge(dut.clk_i)
        await ClockCycles(dut.clk_i, H)
        return bad, first, vals

    @staticmethod
    def _select_inventory(walk: TestEnWalk) -> tuple[list[TestEnPin], list[str]]:
        """The walked pin of each inventory path, and every inventory pin that
        is not walked or has another class."""
        walked = walk.by_path()
        graded: list[TestEnPin] = []
        problems: list[str] = []
        for path, cls in GRADED_PINS:
            p = walked.get(path)
            if p is None:
                problems.append(f"missing {path} class={cls} (not walked)")
            elif p.cls != cls:
                problems.append(f"class {path} inventory={cls} walked={p.cls}")
            else:
                graded.append(p)
        return graded, problems

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
        graded, problems = self._select_inventory(walk)
        in_inventory = {p.path for p in graded}
        others = [p for p in walk.pins if p.path not in in_inventory]
        self.logger.info(
            "TEST-EN-WALK LOG: root=%s scopes=%d pins=%d inventory=%d index_files=%d unwalkable=%d",
            walk.root,
            walk.scopes,
            len(walk.pins),
            len(GRADED_PINS),
            walk.index.files,
            len(walk.unwalkable),
        )
        for p in graded:
            self.logger.info("TEST-EN-PIN LOG: %s group=%s graded=1", p.label(), p.owner)
        inv_groups = walk.group_counts(graded)
        for owner, n in inv_groups.items():
            self.logger.info("OBS-TEST-EN-INVENTORY-GROUP: group=%s pins=%d", owner, n)
        other_groups = walk.group_counts(others)
        for owner, n in other_groups.items():
            self.logger.info("OBS-TEST-EN-UNGRADED: group=%s pins=%d", owner, n)
        for p in others:
            self.logger.info("OBS-TEST-EN-UNGRADED pin: %s group=%s", p.label(), p.owner)
        for u in walk.unwalkable:
            self.logger.info("OBS-TEST-EN-UNWALKABLE: %s", u.label())
        per_class = {c: sum(1 for p in graded if p.cls == c) for c in CLASS_NAMES}
        for line in problems:
            self.logger.info("CTL-PIN-WALK mismatch: %s", line)
        assert not problems, (
            f"CTL-PIN-WALK FAIL: walked={len(graded)} inventory={len(GRADED_PINS)} "
            f"problems={len(problems)}: "
            + "; ".join(problems[:FAIL_LINES])
            + (" ..." if len(problems) > FAIL_LINES else "")
        )
        self.logger.info(
            "CTL-PIN-WALK: graded=%d inventory=%d missing=0 class_mismatch=0 %s "
            "walked=%d not_in_inventory=%d unwalkable=%d inventory_groups=%s logged=%s",
            len(graded),
            len(GRADED_PINS),
            " ".join(f"{c}={n}" for c, n in per_class.items()),
            len(walk.pins),
            len(others),
            len(walk.unwalkable),
            ",".join(f"{k}:{v}" for k, v in inv_groups.items()) or "none",
            ",".join(f"{k}:{v}" for k, v in other_groups.items()) or "none",
        )

        await ReadOnly()
        base = pins_not_equal(graded, 0)
        await RisingEdge(dut.clk_i)
        self.logger.info(
            "TEST-EN-BASE LOG: test_en_i=0 graded pins not 0 before the first edge=%d", len(base)
        )

        open_graded_window(TEST, self.logger)
        rise_bad, rise_first, rise_val = await self._edge(graded, 1)
        fall_bad, fall_first, fall_val = await self._edge(graded, 0)
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
        fail_pins = {p.path for p, _e in failing}
        stuck = {
            v: sum(1 for x in fail_pins if rise_val[x] == v and fall_val[x] == v) for v in (0, 1)
        }
        counts = (
            f"graded={len(graded)} "
            + " ".join(f"{c}={n}" for c, n in per_class.items())
            + f" fail_pins={len(fail_pins)} stuck_0={stuck[0]} stuck_1={stuck[1]}"
            f" fail_0to1={len(rise_bad)} fail_1to0={len(fall_bad)}"
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
