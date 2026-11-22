# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scrambler round trip and address permutation on every variant.

For each of the ten instances (five depths, both BYTE_WISE modes), with a
random key per instance:

1. Address permutation — sweeping the whole address space, the scrambled
   addresses are all distinct (a bijection onto the same space) and at least
   one differs from its plain address.
2. Ascending round trip — random words written through the scrambler into a
   Python memory indexed by scrambled address read back unchanged through
   the descrambler, at every address.
3. Descending round trip — the same with sequential data, walking every
   address downwards.
4. Key and address dependence — the same word at the same address scrambles
   differently under a second key, and the same word at a different address
   scrambles differently under the same key (the address tweak takes part).

Every scrambled write of steps 2-4 is also graded against the data cipher
model of ``scrambler_base_test`` (``CHK-SCR-DATA-GOLDEN``): in word mode the
scrambled word equals the model word; in byte-wise mode, where the ``perm8``
table is not documented, each byte of the scrambled word has the popcount of
the same byte of the model's S-box layer output. The scrambled address is
not graded against a model.
"""

from __future__ import annotations

import logging
import random

import cocotb
from scrambler_base_test import (
    DATA_MASK,
    VARIANTS,
    ScramblerPort,
    byte_popcounts,
    model_scramble_pre_perm,
    model_scramble_word,
    random_seed,
)


def check_data_golden(port: ScramblerPort, key: int, addr: int, data: int, sdata: int) -> None:
    """Raise unless ``sdata`` matches the cipher model for this write."""
    variant = port.variant
    if variant.byte_wise:
        pre_perm = model_scramble_pre_perm(key, addr, data, variant.addr_width)
        expected = byte_popcounts(pre_perm)
        observed = byte_popcounts(sdata)
        mode = "byte"
    else:
        expected = model_scramble_word(key, addr, data, variant.addr_width)
        observed = sdata
        mode = "word"
    if observed != expected:
        raise AssertionError(
            f"CHK-SCR-DATA-GOLDEN FAIL mode={mode} depth={variant.depth} addr=0x{addr:x} "
            f"key=0x{key:08x} data=0x{data:08x} sdata=0x{sdata:08x} "
            f"observed={observed} expected={expected}"
        )


async def check_variant(port: ScramblerPort, log: logging.Logger) -> None:
    variant = port.variant
    depth = variant.depth
    key = random.getrandbits(32)
    port.init(key)

    scrambled_of = {}
    for addr in range(depth):
        scrambled_of[addr] = await port.scrambled_address(addr)
    images = set(scrambled_of.values())
    assert len(images) == depth, (
        f"{variant.name}: {depth - len(images)} scrambled addresses collide under key 0x{key:08x}"
    )
    assert max(images) < depth, (
        f"{variant.name}: a scrambled address exceeds the {depth}-word space"
    )
    moved = sum(1 for addr, image in scrambled_of.items() if addr != image)
    assert moved > 0, f"{variant.name}: the address map is the identity under key 0x{key:08x}"
    log.info(
        "%s key 0x%08x: address map is a permutation, %d of %d addresses move",
        variant.name,
        key,
        moved,
        depth,
    )

    graded = 0
    sample = range(depth)
    memory: dict[int, int] = {}
    expected: dict[int, int] = {}
    for addr in sample:
        data = random.getrandbits(32)
        saddr, sdata = await port.scramble(addr, data)
        check_data_golden(port, key, addr, data, sdata)
        graded += 1
        assert saddr == scrambled_of[addr], (
            f"{variant.name}: scrambled address changed with the data"
        )
        memory[saddr] = sdata
        expected[addr] = data
    for addr in sample:
        observed = await port.descramble(addr, memory[scrambled_of[addr]])
        assert observed == expected[addr], (
            f"{variant.name}: ascending round trip at 0x{addr:x}: wrote 0x{expected[addr]:08x}, read 0x{observed:08x}"
        )
    log.info("%s: ascending round trip over %d addresses", variant.name, len(sample))

    for value, addr in enumerate(reversed(sample)):
        saddr, sdata = await port.scramble(addr, value & DATA_MASK)
        check_data_golden(port, key, addr, value & DATA_MASK, sdata)
        graded += 1
        memory[saddr] = sdata
        expected[addr] = value & DATA_MASK
    for addr in reversed(sample):
        observed = await port.descramble(addr, memory[scrambled_of[addr]])
        assert observed == expected[addr], (
            f"{variant.name}: descending round trip at 0x{addr:x}: wrote 0x{expected[addr]:08x}, read 0x{observed:08x}"
        )
    log.info("%s: descending round trip over %d addresses", variant.name, len(sample))

    addr_a, addr_b = random.sample(range(depth), 2)
    data = random.getrandbits(32)
    _, sdata_a = await port.scramble(addr_a, data)
    check_data_golden(port, key, addr_a, data, sdata_a)
    _, sdata_b = await port.scramble(addr_b, data)
    check_data_golden(port, key, addr_b, data, sdata_b)
    graded += 2
    assert sdata_a != sdata_b, (
        f"{variant.name}: 0x{data:08x} scrambles identically at 0x{addr_a:x} and 0x{addr_b:x}"
    )
    other_key = key ^ (1 << random.randrange(32)) ^ random.getrandbits(32)
    port.init(other_key)
    _, sdata_other = await port.scramble(addr_a, data)
    check_data_golden(port, other_key, addr_a, data, sdata_other)
    graded += 1
    assert sdata_other != sdata_a, (
        f"{variant.name}: 0x{data:08x} at 0x{addr_a:x} scrambles identically under two keys"
    )
    log.info("%s: scrambled data depends on the address and on the key", variant.name)
    assert graded == 2 * depth + 3
    log.info(
        "CHK-SCR-DATA-GOLDEN PASS mode=%s depth=%d writes=%d",
        "byte" if variant.byte_wise else "word",
        depth,
        graded,
    )


@cocotb.test()
async def scrambler_roundtrip_test(dut) -> None:
    log = logging.getLogger("cocotb.tb.scrambler_roundtrip_test")
    seed = random_seed()
    random.seed(seed)
    log.info("seed=%d", seed)

    ports = [ScramblerPort(dut, variant) for variant in VARIANTS]
    for port in ports:
        port.init(0)

    for port in ports:
        log.info("=" * 70)
        log.info("%s", port.variant.name)
        log.info("=" * 70)
        await check_variant(port, log)

    log.info("scrambler_roundtrip_test PASSED (seed=%d, %d variants)", seed, len(ports))
