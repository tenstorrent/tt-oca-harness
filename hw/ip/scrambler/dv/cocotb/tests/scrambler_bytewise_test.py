# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scrambler byte-wise lane independence.

A byte-maskable memory stores only the masked lanes of a scrambled write and
keeps the other lanes from the previous word. In BYTE_WISE mode every lane
scrambles on its own, so the merged word descrambles to the merge of the
plain words; in word mode the permutation mixes lanes, so the same merge
corrupts the unmasked lanes.

For each byte-wise variant, over random addresses and every partial mask:

1. A full-mask write followed by a masked write; the memory merges the two
   scrambled words lane by lane and the descrambled result equals the merge
   of the two plain words.

For one word-mode variant, as the contrast that shows the mode matters:

2. The same procedure produces a descrambled word that differs from the
   plain merge for at least one partial mask.
"""

from __future__ import annotations

import logging
import random

import cocotb
from scrambler_base_test import (
    BYTEWISE_VARIANTS,
    FULL_MASK,
    WORD_VARIANTS,
    ScramblerPort,
    merge_lanes,
    random_seed,
)

# Addresses sampled per variant; every non-trivial mask runs at each.
SAMPLE_ADDRS = 24
PARTIAL_MASKS = tuple(mask for mask in range(1, FULL_MASK) if mask != FULL_MASK)


async def masked_readback(port: ScramblerPort, addr: int, old: int, new: int, mask: int) -> int:
    """Write ``old`` fully, then ``new`` under ``mask`` into a lane-merging memory; return the read."""
    _, old_s = await port.scramble(addr, old)
    _, new_s = await port.scramble(addr, new, mask)
    stored = merge_lanes(old_s, new_s, mask)
    return await port.descramble(addr, stored)


@cocotb.test()
async def scrambler_bytewise_test(dut) -> None:
    log = logging.getLogger("cocotb.tb.scrambler_bytewise_test")
    seed = random_seed()
    random.seed(seed)
    log.info("seed=%d", seed)

    # ------------------------------------------------------------------
    log.info("=" * 70)
    log.info("TEST 1: byte-wise variants merge lanes independently")
    log.info("=" * 70)
    for variant in BYTEWISE_VARIANTS:
        port = ScramblerPort(dut, variant)
        key = random.getrandbits(32)
        port.init(key)
        checks = 0
        for addr in random.sample(range(variant.depth), SAMPLE_ADDRS):
            old = random.getrandbits(32)
            new = random.getrandbits(32)
            for mask in PARTIAL_MASKS:
                observed = await masked_readback(port, addr, old, new, mask)
                expected = merge_lanes(old, new, mask)
                assert observed == expected, (
                    f"{variant.name}: addr 0x{addr:x} mask 0b{mask:04b}: old 0x{old:08x} new 0x{new:08x} "
                    f"expected 0x{expected:08x}, read 0x{observed:08x}"
                )
                checks += 1
        log.info(
            "%s key 0x%08x: %d masked writes descrambled lane-exact", variant.name, key, checks
        )

    # ------------------------------------------------------------------
    log.info("=" * 70)
    log.info("TEST 2: word mode does not keep lanes independent")
    log.info("=" * 70)
    variant = random.choice(WORD_VARIANTS)
    port = ScramblerPort(dut, variant)
    port.init(random.getrandbits(32))
    addr = random.randrange(variant.depth)
    old = random.getrandbits(32)
    new = old ^ random.getrandbits(32) | 1
    corrupted = 0
    for mask in PARTIAL_MASKS:
        observed = await masked_readback(port, addr, old, new, mask)
        if observed != merge_lanes(old, new, mask):
            corrupted += 1
    assert corrupted > 0, (
        f"{variant.name}: partial writes merged cleanly, which only byte-wise mode guarantees"
    )
    log.info(
        "%s: %d of %d partial masks corrupt the merge, as word-mode permutation implies",
        variant.name,
        corrupted,
        len(PARTIAL_MASKS),
    )

    log.info("scrambler_bytewise_test PASSED (seed=%d)", seed)
