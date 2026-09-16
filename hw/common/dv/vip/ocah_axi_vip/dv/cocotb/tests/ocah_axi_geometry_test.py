# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI4 VIP selftest: a 32-bit, 8-bit-ID stack bound to a default-geometry interface.

The ``u_wide_axi_if`` members are 64 bits wide with 16-bit ID and user
sidebands. Bound through ``OcahAxiConfig`` at the 32-bit data, 8-bit ID,
1-bit user geometry, the AXI4 master and the RAM responder must agree at
every 32-bit position of the 8-byte member lane, the response ID must equal
the request ID within the configured width, the bus readback and the
responder backdoor must both return the written word, and the member bits
above the configured geometry must read as zero after every transfer.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from ocah_axi_vip import OcahAxiMasterSequence, OcahAxiSlaveAgent
from ocah_axi_vip_harness import (
    WIDE_AXI_GEOMETRY,
    build_wide_full_stack,
    scenario_rng,
    start_clock_reset,
    upper_lanes,
)
from ocah_checker import OcahChecker
from ocah_lib import OcahKnobs, OcahRng

log = logging.getLogger("cocotb.tb.ocah_axi_geometry_test")

CHK_VIEW = "CHK-AXI-GEOM-VIEW"
CHK_RDBACK = "CHK-AXI-GEOM-RDBACK"
CHK_BACKDOOR = "CHK-AXI-GEOM-BACKDOOR"
CHK_LANES = "CHK-AXI-GEOM-LANES"
CHK_ID = "CHK-AXI-GEOM-ID"
RANDOM_OPS_KNOB = "OCAH_AXI_GEOM_RANDOM_OPS"

DATA_WIDTH = WIDE_AXI_GEOMETRY.data_width
ID_WIDTH = WIDE_AXI_GEOMETRY.id_width
# Every 32-bit word position inside the 64-bit member lane.
WORD_OFFSETS = (0x0, 0x4, 0x8, 0xC)
RAM_BYTES = 2**16


def check_view_geometry(checker: OcahChecker, scope: Any) -> None:
    """The bound view reports the configured widths; the raw members keep theirs."""
    bus = WIDE_AXI_GEOMETRY.bus(scope)
    observed = {
        "awaddr": len(bus.write.aw.awaddr),
        "awid": len(bus.write.aw.awid),
        "awuser": len(bus.write.aw.awuser),
        "wdata": len(bus.write.w.wdata),
        "wstrb": len(bus.write.w.wstrb),
        "bid": len(bus.write.b.bid),
        "rdata": len(bus.read.r.rdata),
        "rid": len(bus.read.r.rid),
    }
    expected = {
        "awaddr": WIDE_AXI_GEOMETRY.addr_width,
        "awid": ID_WIDTH,
        "awuser": WIDE_AXI_GEOMETRY.user_width,
        "wdata": DATA_WIDTH,
        "wstrb": WIDE_AXI_GEOMETRY.strb_width,
        "bid": ID_WIDTH,
        "rdata": DATA_WIDTH,
        "rid": ID_WIDTH,
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
    for name, width in WIDE_AXI_GEOMETRY.member_widths().items():
        checker.expect_equal(
            CHK_LANES, upper_lanes(getattr(scope, name), width), 0, context=f"{context} {name}"
        )


async def write_read_word(
    checker: OcahChecker,
    seq: OcahAxiMasterSequence,
    slave: OcahAxiSlaveAgent,
    scope: Any,
    *,
    index: int,
    addr: int,
    data: int,
    axi_id: int,
) -> None:
    """One single-beat write and read with one ID, judged on the bus, backdoor, and lanes."""
    log.debug("op %d: addr=0x%08x data=0x%08x id=0x%02x", index, addr, data, axi_id)
    wres = await seq.write_result(addr, data, id=axi_id)
    check_upper_lanes(checker, scope, context=f"op {index} after write")
    rres = await seq.read_result(addr, id=axi_id)
    check_upper_lanes(checker, scope, context=f"op {index} after read")
    checker.expect_true(CHK_RDBACK, wres.ok and rres.ok, context=f"op {index} responses OKAY")
    checker.expect_equal(CHK_RDBACK, rres.data, data, context=f"op {index} addr=0x{addr:08x}")
    checker.expect_equal(
        CHK_ID, int(scope.bid.value), axi_id, context=f"op {index} BID at the raw member"
    )
    checker.expect_equal(
        CHK_ID, int(scope.rid.value), axi_id, context=f"op {index} RID at the raw member"
    )
    checker.expect_equal(
        CHK_BACKDOOR, slave.sequence.read32(addr), data, context=f"op {index} addr=0x{addr:08x}"
    )


@cocotb.test()
async def ocah_axi_geometry_test(dut: Any) -> None:
    """Directed patterns at every word offset of the wide lane with random IDs, then random words."""
    await start_clock_reset(dut)
    master, slave = build_wide_full_stack(dut)
    await master.start()
    seq = master.sequence
    scope = dut.u_wide_axi_if
    checker = OcahChecker(
        name="ocah_axi_geometry",
        required_ids=(CHK_VIEW, CHK_RDBACK, CHK_BACKDOOR, CHK_LANES, CHK_ID),
        logger=log,
    )
    rng = scenario_rng("ocah_axi_geometry_test")
    random_count = OcahKnobs.get_int_min(RANDOM_OPS_KNOB, 8, 1)
    patterns = OcahRng.directed_patterns(DATA_WIDTH, random_count, rng)
    log.info("=" * 70)
    log.info(
        "AXI4 geometry: %d patterns x %d word offsets, then %d random ops on %s",
        len(patterns),
        len(WORD_OFFSETS),
        random_count,
        WIDE_AXI_GEOMETRY,
    )
    log.info("=" * 70)

    check_view_geometry(checker, scope)

    index = 0
    base = rng.randrange(0, RAM_BYTES - 16) & ~0xF
    for pattern in patterns:
        for offset in WORD_OFFSETS:
            axi_id = OcahRng.random_pattern(ID_WIDTH, rng)
            await write_read_word(
                checker,
                seq,
                slave,
                scope,
                index=index,
                addr=base + offset,
                data=pattern,
                axi_id=axi_id,
            )
            index += 1

    for _ in range(random_count):
        addr = rng.randrange(0, RAM_BYTES) & ~0x3
        data = OcahRng.random_pattern(DATA_WIDTH, rng)
        axi_id = OcahRng.random_pattern(ID_WIDTH, rng)
        await write_read_word(
            checker, seq, slave, scope, index=index, addr=addr, data=data, axi_id=axi_id
        )
        index += 1

    log.info("done: %d words, sequence stats=%s", index, seq.get_statistics())
    checker.finalize()
