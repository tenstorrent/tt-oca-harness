# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI-Lite VIP selftest: a 32-bit stack bound to a default-geometry interface.

The ``u_wide_axil_if`` members are 64 bits wide. Bound through ``OcahAxiConfig``
at the 32-bit bus geometry, the lite master and the lite RAM responder must
agree at every 32-bit position of the 8-byte member lane (offsets 0x0
through 0xC), the bus readback and the responder backdoor must both return
the written word, and the member bits above the configured geometry must
read as zero after every transfer.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from ocah_axi_vip import OcahAxiLiteMasterSequence, OcahAxiLiteSlaveAgent
from ocah_axi_vip_harness import (
    WIDE_LITE_GEOMETRY,
    build_wide_lite_stack,
    scenario_rng,
    start_clock_reset,
    upper_lanes,
)
from ocah_checker import OcahChecker
from ocah_lib import OcahKnobs, OcahRng

log = logging.getLogger("cocotb.tb.ocah_axi_lite_geometry_test")

CHK_VIEW = "CHK-AXI-GEOM-VIEW"
CHK_RDBACK = "CHK-AXI-GEOM-RDBACK"
CHK_BACKDOOR = "CHK-AXI-GEOM-BACKDOOR"
CHK_LANES = "CHK-AXI-GEOM-LANES"
RANDOM_OPS_KNOB = "OCAH_AXI_GEOM_RANDOM_OPS"

DATA_WIDTH = WIDE_LITE_GEOMETRY.data_width
STRB_WIDTH = WIDE_LITE_GEOMETRY.strb_width
# Every 32-bit word position inside the 64-bit member lane.
WORD_OFFSETS = (0x0, 0x4, 0x8, 0xC)
RAM_BYTES = 2**16


def check_view_geometry(checker: OcahChecker, scope: Any) -> None:
    """The bound view reports the configured widths; the raw members keep theirs."""
    bus = WIDE_LITE_GEOMETRY.bus(scope)
    observed = {
        "awaddr": len(bus.write.aw.awaddr),
        "wdata": len(bus.write.w.wdata),
        "wstrb": len(bus.write.w.wstrb),
        "araddr": len(bus.read.ar.araddr),
        "rdata": len(bus.read.r.rdata),
    }
    expected = {
        "awaddr": WIDE_LITE_GEOMETRY.addr_width,
        "wdata": DATA_WIDTH,
        "wstrb": STRB_WIDTH,
        "araddr": WIDE_LITE_GEOMETRY.addr_width,
        "rdata": DATA_WIDTH,
    }
    checker.expect_equal(CHK_VIEW, observed, expected, context="view widths")
    raw = {name: len(getattr(scope, name)) for name in observed}
    checker.expect_true(
        CHK_VIEW,
        all(raw[name] > expected[name] for name in raw),
        context=f"raw member widths {raw} exceed the configured geometry",
    )


def check_upper_lanes(checker: OcahChecker, scope: Any, *, context: str) -> None:
    """Every geometry-bearing member holds zero above its configured width."""
    for name, width in WIDE_LITE_GEOMETRY.member_widths().items():
        checker.expect_equal(
            CHK_LANES, upper_lanes(getattr(scope, name), width), 0, context=f"{context} {name}"
        )


async def write_read_word(
    checker: OcahChecker,
    seq: OcahAxiLiteMasterSequence,
    slave: OcahAxiLiteSlaveAgent,
    scope: Any,
    *,
    index: int,
    addr: int,
    data: int,
) -> None:
    """One word written and read back through the bus and the backdoor, lanes judged."""
    log.debug("op %d: addr=0x%08x data=0x%08x", index, addr, data)
    await seq.write(addr, data)
    check_upper_lanes(checker, scope, context=f"op {index} after write")
    readback = await seq.read(addr)
    check_upper_lanes(checker, scope, context=f"op {index} after read")
    checker.expect_equal(CHK_RDBACK, readback, data, context=f"op {index} addr=0x{addr:08x}")
    checker.expect_equal(
        CHK_BACKDOOR, slave.sequence.read32(addr), data, context=f"op {index} addr=0x{addr:08x}"
    )


@cocotb.test()
async def ocah_axi_lite_geometry_test(dut: Any) -> None:
    """Directed patterns at every word offset of the wide lane, then random words."""
    await start_clock_reset(dut)
    master, slave = build_wide_lite_stack(dut)
    await master.start()
    seq = master.sequence
    scope = dut.u_wide_axil_if
    checker = OcahChecker(
        name="ocah_axi_lite_geometry",
        required_ids=(CHK_VIEW, CHK_RDBACK, CHK_BACKDOOR, CHK_LANES),
        logger=log,
    )
    rng = scenario_rng("ocah_axi_lite_geometry_test")
    random_count = OcahKnobs.get_int_min(RANDOM_OPS_KNOB, 8, 1)
    patterns = OcahRng.directed_patterns(DATA_WIDTH, random_count, rng)
    log.info("=" * 70)
    log.info(
        "AXI-Lite geometry: %d patterns x %d word offsets, then %d random ops on %s",
        len(patterns),
        len(WORD_OFFSETS),
        random_count,
        WIDE_LITE_GEOMETRY,
    )
    log.info("=" * 70)

    check_view_geometry(checker, scope)

    index = 0
    base = rng.randrange(0, RAM_BYTES - 16) & ~0xF
    for pattern in patterns:
        for offset in WORD_OFFSETS:
            await write_read_word(
                checker, seq, slave, scope, index=index, addr=base + offset, data=pattern
            )
            index += 1

    for _ in range(random_count):
        addr = rng.randrange(0, RAM_BYTES) & ~0x3
        data = OcahRng.random_pattern(DATA_WIDTH, rng)
        await write_read_word(checker, seq, slave, scope, index=index, addr=addr, data=data)
        index += 1

    log.info("done: %d words, sequence stats=%s", index, seq.get_statistics())
    checker.finalize()
