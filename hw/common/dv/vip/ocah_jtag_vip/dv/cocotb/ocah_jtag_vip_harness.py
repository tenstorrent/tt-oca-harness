# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared setup for the JTAG VIP wire-harness selftests.

One TAP connection exists in ``tb_top.sv`` (``jtag_tck``, ``jtag_tms``,
``jtag_tdi``, ``jtag_tdo``, ``jtag_trst``, ``jtag_tdo_oen``). The shared master
(``OcahJtagMasterDriver`` behind ``OcahJtagMasterSequence``) drives TCK, TMS,
TDI, and TRST and samples TDO; the shared reactive device
(``OcahJtagSlaveAgent`` behind ``OcahJtagSlaveSequence``) samples the same
nets and drives TDO and its output enable. ``OcahJtagMasterMonitor``
reconstructs the scans for the length evidence, and one ``OcahJtagChecker``
collects every ``CHK-*`` record of a test. ``sva/ocah_jtag_sva.sv`` watches the
nets from ``tb_top.sv``.

The device is the one the simulator-free slave selftest uses: IDCODE
``0x1B34_C0D1``, a writable 16-bit ``CTRL`` register, and a read-only 8-bit
``STATUS`` register behind a 5-bit instruction register.

Each selftest carries an in-band negative case: a second, fail-fast checker
with a silent logger receives a wrong expectation and must raise. The
``OCAH_JTAG_SELFTEST_NEGATIVE`` knob turns ``ocah_jtag_tap_reset_test`` into a
run that must fail (the reference model is desynchronized before the walk).

``clk`` is a free-running reference clock this module drives so the
simulator always holds a timed event while the master bit-bangs TCK.
``jtag_tap_state`` carries the device's TAP controller state as the one-hot a
DUT exports, mirrored after every falling TCK edge and every TRST edge, so
the SVA state rules judge the connection.

The seed accessor and the salted scenario RNG live here: these selftests are
plain cocotb tests without a base test class.
"""

from __future__ import annotations

import logging
import os
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Edge, FallingEdge, First, Timer
from ocah_checker import OcahCheckerError
from ocah_jtag_vip import (
    IDCODE_OPCODE,
    OcahJtagChecker,
    OcahJtagMasterDriver,
    OcahJtagMasterMonitor,
    OcahJtagMasterSequence,
    OcahJtagSlaveAgent,
    OcahJtagSlaveConfig,
    OcahJtagSlaveSequence,
)
from ocah_lib import OcahKnobs, OcahRng

__all__ = [
    "BYPASS_OPCODE",
    "CTRL_OPCODE",
    "CTRL_WIDTH",
    "IDCODE",
    "IDCODE_MASK",
    "IDCODE_WIDTH",
    "CHECKER_NEGATIVE_KNOB",
    "IR_WIDTH",
    "NEGATIVE_KNOB",
    "NEVER_RECORDED_ID",
    "STATUS_OPCODE",
    "STATUS_WIDTH",
    "UNUSED_OPCODE",
    "JtagHarness",
    "base_seed",
    "build_stack",
    "device_config",
    "negative_armed",
    "rejects",
    "scenario_rng",
]

PREFIX = "jtag"
IR_WIDTH = 5
TCK_PERIOD_NS = 20
CLK_PERIOD_NS = 4
IDCODE = 0x1B34_C0D1  # marker bit[0] = 1
IDCODE_WIDTH = 32
IDCODE_MASK = (1 << IDCODE_WIDTH) - 1
CTRL_OPCODE = 0x02
CTRL_WIDTH = 16
STATUS_OPCODE = 0x03
STATUS_WIDTH = 8
UNUSED_OPCODE = 0x0A
BYPASS_OPCODE = (1 << IR_WIDTH) - 1
NEGATIVE_KNOB = "OCAH_JTAG_SELFTEST_NEGATIVE"
CHECKER_NEGATIVE_KNOB = "OCAH_CHECKER_SELFTEST_NEGATIVE"
NEVER_RECORDED_ID = "CHK-NEVER-RECORDED"
_SEED_ENV = "RANDOM_SEED"
_SIGNAL_MAP = {name: f"{PREFIX}_{name}" for name in ("tck", "tms", "tdi", "tdo", "trst", "tdo_oen")}


@dataclass(frozen=True)
class JtagHarness:
    """The bound stack of one selftest: both sequence surfaces and their checker."""

    master: OcahJtagMasterSequence
    slave: OcahJtagSlaveSequence
    slave_agent: OcahJtagSlaveAgent
    monitor: OcahJtagMasterMonitor
    checker: OcahJtagChecker

    async def stop(self) -> None:
        """Stop the monitor and the reactive device.

        The monitor's swallowed-callback count is recorded on the test's
        checker, so a subscriber exception the monitor logged cannot pass.
        """
        await self.monitor.stop()
        await self.slave_agent.stop()
        self.checker.expect_equal(
            "CHK-JTAG-MON-CALLBACKS",
            self.monitor.get_statistics()["callback_errors"],
            0,
            context="subscriber exceptions the monitor swallowed",
        )


def device_config(name: str = "harness_device") -> OcahJtagSlaveConfig:
    """The reactive device the selftests talk to."""
    return OcahJtagSlaveConfig(
        name=name,
        idcode=IDCODE,
        ir_width=IR_WIDTH,
        registers={
            "IDCODE": (IDCODE_WIDTH, IDCODE_OPCODE),
            "CTRL": (CTRL_WIDTH, CTRL_OPCODE, True),
            "STATUS": (STATUS_WIDTH, STATUS_OPCODE),
        },
        signal_map=dict(_SIGNAL_MAP),
    )


async def build_stack(
    dut: Any, *, required_ids: Iterable[str], log: logging.Logger, item_checks: bool = True
) -> JtagHarness:
    """Start the reference clock and attach the master, monitor, and device to the jtag nets.

    ``item_checks`` attaches the checker's per-scan item rules to the monitor;
    a test whose stimulus is a raw TMS walk leaves them off, because a walk
    passes through Shift-IR at arbitrary lengths.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
    slave_agent = OcahJtagSlaveAgent(
        dut, config=device_config(), en_monitor=False, attach_checker=False
    )
    slave_agent.responder.init_signals()
    tap = OcahJtagMasterDriver.from_prefix(
        dut, PREFIX, name="harness_master", tck_period_ns=TCK_PERIOD_NS, ir_width=IR_WIDTH
    )
    tap.init_signals()
    monitor = OcahJtagMasterMonitor.from_prefix(dut, PREFIX, name="harness_monitor")
    ids = list(required_ids)
    if OcahKnobs.is_set(CHECKER_NEGATIVE_KNOB):
        log.warning(
            "NEGATIVE VALIDATION: required ID %s is never recorded; "
            "CHECKER_SUMMARY must report missing=1",
            NEVER_RECORDED_ID,
        )
        ids.append(NEVER_RECORDED_ID)
    checker = OcahJtagChecker(
        name="ocah_jtag_harness", ir_width=IR_WIDTH, required_ids=ids, logger=log
    )
    if item_checks:
        checker.attach_monitor(monitor)
    await slave_agent.start()
    await monitor.start()
    cocotb.start_soon(_mirror_device_state(dut, slave_agent.responder))
    master = OcahJtagMasterSequence(tap, checker, monitor=monitor)
    slave = OcahJtagSlaveSequence(slave_agent.responder, checker=checker)
    return JtagHarness(
        master=master, slave=slave, slave_agent=slave_agent, monitor=monitor, checker=checker
    )


async def _mirror_device_state(dut: Any, responder: Any) -> None:
    """Drive ``jtag_tap_state`` with the device's TAP state.

    ``OcahJtagState`` values are the IEEE one-hot encoding the SVA consumes.
    The device advances its state on the rising TCK edge and resets it on a
    TRST edge; the mirror follows at the falling edge and one nanosecond after
    a TRST edge, after the device has acted on it.
    """
    tck = getattr(dut, f"{PREFIX}_tck")
    trst = getattr(dut, f"{PREFIX}_trst")
    state_net = getattr(dut, f"{PREFIX}_tap_state")
    state_net.value = int(responder.device_state())
    while True:
        trigger = await First(FallingEdge(tck), Edge(trst))
        if trigger is not None and getattr(trigger, "signal", None) is trst:
            await Timer(1, "ns")
        state_net.value = int(responder.device_state())


def base_seed() -> int:
    """Runner-provided seed; the harness's one read of the seed variable."""
    return int(os.environ.get(_SEED_ENV, "1"), 0)


def scenario_rng(label: str) -> random.Random:
    """Seeded stream for one scenario, salted by ``label``."""
    return random.Random(OcahRng.salted_seed(base_seed(), label))


def negative_armed() -> bool:
    """Whether the must-fail knob of the run is set."""
    return OcahKnobs.is_set(NEGATIVE_KNOB)


def rejects(label: str, action: Callable[[OcahJtagChecker], object]) -> bool:
    """Run ``action`` on a fail-fast checker with a silent logger; True when it raised.

    The probe checker owns no evidence of the test: the caller records the
    outcome under a ``CHK-JTAG-NEG-*`` identifier on the test's checker.
    """
    quiet = logging.getLogger(f"cocotb.tb.ocah_jtag_harness.negative.{label}")
    quiet.setLevel(logging.CRITICAL)
    probe = OcahJtagChecker(name=f"negative.{label}", ir_width=IR_WIDTH, logger=quiet)
    try:
        action(probe)
    except OcahCheckerError:
        return True
    return False
