# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared JTAG VIP selftest: Test-Logic-Reset selects IDCODE and IDCODE reads back.

Against the reactive device, a DR scan straight out of Test-Logic-Reset
returns the device-identification value with the marker bit set, the checked
IDCODE read emits ``CHK-IDCODE-RAW`` / ``CHK-IDCODE-MARKER``, the monitor
reconstructs every scan at its driven width, and a TAP reset after
instruction churn re-selects IDCODE. A wrong expected IDCODE handed to a
fail-fast checker must be rejected.
"""

from __future__ import annotations

import logging
import os

import cocotb
from ocah_jtag_vip_harness import (
    IDCODE,
    IDCODE_MASK,
    IDCODE_WIDTH,
    IR_WIDTH,
    UNUSED_OPCODE,
    build_stack,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_jtag_idcode_test")

REQUIRED_IDS = (
    "CHK-IDCODE-RAW",
    "CHK-IDCODE-MARKER",
    "CHK-JTAG-TLR-IDCODE",
    "CHK-SCAN-IR-LEN",
    "CHK-SCAN-DR-LEN",
    "CHK-JTAG-NEG-IDCODE",
)


@cocotb.test()
async def ocah_jtag_idcode_test(dut) -> None:
    rng = scenario_rng("idcode")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    seq, checker = harness.master, harness.checker
    reads = int(os.environ.get("OCAH_JTAG_IDCODE_READS", "6"))
    log.info("start: TLR-selected IDCODE, %d checked reads, IR churn, negative probe", reads)

    await seq.reset_to_tlr()
    observed = await seq.shift_dr(0, IDCODE_WIDTH, back_to_rti=True)
    checker.expect_equal(
        "CHK-JTAG-TLR-IDCODE",
        observed & IDCODE_MASK,
        IDCODE,
        context="DR scan after TLR, no IR load",
    )
    seq.check_last_scan_length(is_ir=False, expected_width=IDCODE_WIDTH, context="TLR-selected")

    for index in range(reads):
        for _ in range(rng.randint(0, 3)):
            await seq.step(0)
        idcode = await seq.read_idcode_checked(IDCODE, context=f"read {index}")
        seq.check_last_scan_length(
            is_ir=False, expected_width=IDCODE_WIDTH, context=f"read {index}"
        )
        log.info("read %d: idcode=0x%08x", index, idcode)

    await seq.shift_ir(UNUSED_OPCODE, back_to_rti=True)
    seq.check_last_scan_length(is_ir=True, expected_width=IR_WIDTH, context="IR churn")
    await seq.reset_to_tlr()
    observed = await seq.shift_dr(0, IDCODE_WIDTH, back_to_rti=True)
    checker.expect_equal(
        "CHK-JTAG-TLR-IDCODE",
        observed & IDCODE_MASK,
        IDCODE,
        context="TLR re-selects IDCODE after IR churn",
    )

    rejected = rejects(
        "idcode",
        lambda probe: probe.expect_equal(
            "CHK-IDCODE-RAW", observed & IDCODE_MASK, IDCODE ^ 0x2, context="wrong expected"
        ),
    )
    checker.expect_true(
        "CHK-JTAG-NEG-IDCODE", rejected, context="a wrong expected IDCODE must be rejected"
    )

    await harness.stop()
    checker.finalize()
