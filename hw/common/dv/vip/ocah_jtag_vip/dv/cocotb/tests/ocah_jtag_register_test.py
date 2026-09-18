# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared JTAG VIP selftest: scan data lands in the device's registers.

Host writes to the writable ``CTRL`` register latch on Update-DR, are
recorded by the device, and read back over the bus; a write paused in
Pause-DR latches whole and reconstructs at its full width, whether the scan
resumes shifting after the pause or updates straight from Exit2-DR; a
capture-only scan (no Shift-DR cycle) latches the captured value back; the
read-only
``STATUS`` register captures its stored value and never latches; the monitor
reconstructs every IR and DR scan at its driven width. A wrong expected
latch value handed to a fail-fast checker must be rejected.
"""

from __future__ import annotations

import logging
import os

import cocotb
from ocah_jtag_vip import OcahJtagSlaveSequence
from ocah_jtag_vip_harness import (
    CTRL_OPCODE,
    CTRL_WIDTH,
    IR_WIDTH,
    STATUS_OPCODE,
    STATUS_WIDTH,
    build_stack,
    capture_only_scan,
    paused_scan,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_jtag_register_test")

REQUIRED_IDS = (
    "CHK-SLAVE-DR-UPDATE",
    "CHK-SLAVE-DR-UPDATE-COUNT",
    "CHK-SLAVE-REG",
    "CHK-JTAG-DR-READBACK",
    "CHK-JTAG-DR-PAUSE",
    "CHK-JTAG-DR-CAPTURE-ONLY",
    "CHK-JTAG-RO-CAPTURE",
    "CHK-SCAN-IR-LEN",
    "CHK-SCAN-DR-LEN",
    "CHK-JTAG-NEG-UPDATE",
)
PAUSE_CYCLES = 4


@cocotb.test()
async def ocah_jtag_register_test(dut) -> None:
    rng = scenario_rng("register")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    seq, slave, checker = harness.master, harness.slave, harness.checker
    writes = int(os.environ.get("OCAH_JTAG_REGISTER_WRITES", "6"))
    if writes < 2:
        raise ValueError(f"OCAH_JTAG_REGISTER_WRITES must be >= 2 (value corners); got {writes}")
    values = [0, (1 << CTRL_WIDTH) - 1] + [rng.getrandbits(CTRL_WIDTH) for _ in range(writes - 2)]
    log.info("start: %d CTRL writes with readback, read-only STATUS, negative probe", writes)

    await seq.reset_to_tlr()
    for index, value in enumerate(values):
        await seq.shift_ir(CTRL_OPCODE, back_to_rti=True)
        seq.check_last_scan_length(is_ir=True, expected_width=IR_WIDTH, context=f"select {index}")
        await seq.shift_dr(value, CTRL_WIDTH, back_to_rti=True)
        seq.check_last_scan_length(is_ir=False, expected_width=CTRL_WIDTH, context=f"write {index}")
        slave.check_last_update("CTRL", value, context=f"write {index}")
        slave.check_register("CTRL", value, context=f"write {index}")
        # The readback scan shifts zeros in, so its own Update-DR latches 0.
        readback = await seq.shift_dr(0, CTRL_WIDTH, back_to_rti=True)
        checker.expect_equal("CHK-JTAG-DR-READBACK", readback, value, context=f"write {index}")
        log.info("write %d: value=0x%04x readback=0x%04x", index, value, readback)

    # Writes paused in Pause-DR latch whole: one resumes shifting after the
    # pause, one pauses after its last bit and updates from Exit2-DR. A
    # capture-only scan then latches the captured value back, and the readback
    # that follows returns the last paused value: four more CTRL updates.
    for split, label in ((CTRL_WIDTH // 2, "resumed"), (CTRL_WIDTH, "completed")):
        paused = rng.getrandbits(CTRL_WIDTH)
        await paused_scan(
            harness,
            is_ir=False,
            value=paused,
            width=CTRL_WIDTH,
            split=split,
            pause_cycles=PAUSE_CYCLES,
            context=f"{label} paused CTRL write",
        )
        seq.check_last_scan_length(
            is_ir=False, expected_width=CTRL_WIDTH, context=f"{label} paused write"
        )
        slave.check_last_update("CTRL", paused, context=f"{label} paused write")
    updates_before = len(slave.updates())
    await capture_only_scan(harness, is_ir=False)
    checker.expect_equal(
        "CHK-JTAG-DR-CAPTURE-ONLY",
        len(slave.updates()) - updates_before,
        1,
        context="a capture-only scan latches once",
    )
    slave.check_last_update("CTRL", paused, context="capture-only scan latches the captured value")
    readback = await seq.shift_dr(0, CTRL_WIDTH, back_to_rti=True)
    checker.expect_equal(
        "CHK-JTAG-DR-PAUSE",
        readback,
        paused,
        context=f"readback after a write paused {PAUSE_CYCLES} cycles and a capture-only scan",
    )
    slave.check_update_count(
        2 * len(values) + 4,
        reg_name="CTRL",
        context="one write and one readback scan per value, two paused writes, "
        "the capture-only scan, and its readback",
    )

    status = rng.getrandbits(STATUS_WIDTH)
    slave.set_register("STATUS", status)
    await seq.shift_ir(STATUS_OPCODE, back_to_rti=True)
    captured = await seq.shift_dr((1 << STATUS_WIDTH) - 1, STATUS_WIDTH, back_to_rti=True)
    checker.expect_equal("CHK-JTAG-RO-CAPTURE", captured, status, context="read-only capture")
    slave.check_update_count(0, reg_name="STATUS", context="a read-only register never latches")
    slave.check_register("STATUS", status, context="stored value survives the host write")

    last_latched = slave.updates()[-1].value
    rejected = rejects(
        "update",
        lambda probe: OcahJtagSlaveSequence(
            harness.slave_agent.responder, checker=probe
        ).check_last_update("CTRL", last_latched ^ 0x1, context="wrong expected latch"),
    )
    checker.expect_true(
        "CHK-JTAG-NEG-UPDATE", rejected, context="a wrong expected latch value must be rejected"
    )

    await harness.stop()
    checker.finalize()
