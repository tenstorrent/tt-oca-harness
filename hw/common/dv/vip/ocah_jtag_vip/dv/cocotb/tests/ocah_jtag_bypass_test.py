# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared JTAG VIP selftest: BYPASS delays TDI to TDO by exactly one TCK.

Random patterns at random widths (the one-bit and 64-bit corners pinned)
scan through BYPASS against the reactive device and the reference-model
prediction emits ``CHK-BYPASS-LATENCY``; an unimplemented instruction behaves
as BYPASS; the monitor reconstructs the IR load and every DR scan at its
driven width. A prediction against a corrupted observation handed to a
fail-fast checker must be rejected.
"""

from __future__ import annotations

import logging
import os

import cocotb
from ocah_jtag_vip import OcahJtagTapRefModel
from ocah_jtag_vip_harness import IR_WIDTH, UNUSED_OPCODE, build_stack, rejects, scenario_rng

log = logging.getLogger("cocotb.tb.ocah_jtag_bypass_test")

REQUIRED_IDS = (
    "CHK-BYPASS-LATENCY",
    "CHK-JTAG-UNDEF-AS-BYPASS",
    "CHK-SCAN-IR-LEN",
    "CHK-SCAN-DR-LEN",
    "CHK-JTAG-NEG-BYPASS",
)
MAX_WIDTH = 64


@cocotb.test()
async def ocah_jtag_bypass_test(dut) -> None:
    rng = scenario_rng("bypass")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    seq, checker = harness.master, harness.checker
    scans = int(os.environ.get("OCAH_JTAG_BYPASS_SCANS", "8"))
    if scans < 2:
        raise ValueError(f"OCAH_JTAG_BYPASS_SCANS must be >= 2 (width corners); got {scans}")
    widths = [1, MAX_WIDTH] + [rng.randint(2, MAX_WIDTH - 1) for _ in range(scans - 2)]
    log.info("start: %d BYPASS scans, undefined instruction, negative probe", scans)

    await seq.reset_to_tlr()
    for index, width in enumerate(widths):
        pattern = rng.getrandbits(width)
        observed = await seq.check_bypass_latency(pattern, width, context=f"scan {index}")
        seq.check_last_scan_length(is_ir=True, expected_width=IR_WIDTH, context=f"load {index}")
        seq.check_last_scan_length(is_ir=False, expected_width=width, context=f"scan {index}")
        log.info("scan %d: width=%d pattern=0x%x observed=0x%x", index, width, pattern, observed)

    await seq.shift_ir(UNUSED_OPCODE, back_to_rti=True)
    pattern = rng.getrandbits(MAX_WIDTH)
    observed = await seq.shift_dr(pattern, MAX_WIDTH, back_to_rti=True)
    expected = OcahJtagTapRefModel.predict_bypass_tdo(pattern, MAX_WIDTH)
    checker.expect_equal(
        "CHK-JTAG-UNDEF-AS-BYPASS", observed, expected, context=f"ir=0x{UNUSED_OPCODE:02x}"
    )

    rejected = rejects(
        "bypass",
        lambda probe: probe.check_bypass_latency(
            observed ^ (1 << 5), pattern=pattern, width=MAX_WIDTH, context="one flipped bit"
        ),
    )
    checker.expect_true(
        "CHK-JTAG-NEG-BYPASS", rejected, context="a corrupted BYPASS observation must be rejected"
    )

    await harness.stop()
    checker.finalize()
