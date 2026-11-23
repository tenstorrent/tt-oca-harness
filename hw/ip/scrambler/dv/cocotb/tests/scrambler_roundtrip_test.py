# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scrambler round trip and address permutation on every variant.

For each of the ten instances (five depths, both BYTE_WISE modes), with a
random key per instance:

1. Address permutation — sweeping the whole address space, the scrambled
   addresses are all distinct (a bijection onto the same space) and at least
   one differs from its plain address (``CHK-SCR-ADDR-PERM``).
2. Ascending round trip — random words written through the scrambler into a
   Python memory indexed by scrambled address read back unchanged through
   the descrambler, at every address (``CHK-SCR-ROUNDTRIP-ASC``); the scrambled
   address of each write equals the address map of step 1, whatever the data
   (``CHK-SCR-ADDR-STABLE``).
3. Descending round trip — the same with sequential data, walking every
   address downwards (``CHK-SCR-ROUNDTRIP-DESC``).
4. Key and address dependence — the same word at the same address scrambles
   differently under a second key, and the same word at a different address
   scrambles differently under the same key (the address tweak takes part;
   ``CHK-SCR-KEY-DEP``, ``CHK-SCR-ADDR-DEP``).

Every scrambled write of steps 2-4 is also graded against the data cipher
model of ``scrambler_base_test`` (``CHK-SCR-DATA-GOLDEN``): in word mode the
scrambled word equals the model word; in byte-wise mode, where the ``perm8``
table is not documented, each byte of the scrambled word has the popcount of
the same byte of the model's S-box layer output. The scrambled address is
not graded against a model.

Each check logs one ``CHK-SCR-<name> PASS`` line per variant; a failing check
raises with its ``FAIL`` line, which fails the test.
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


def data_golden_mismatch(port: ScramblerPort, key: int, addr: int, data: int, sdata: int) -> list:
    """Return ``[]`` if ``sdata`` matches the cipher model for this write, else one mismatch."""
    variant = port.variant
    if variant.byte_wise:
        pre_perm = model_scramble_pre_perm(key, addr, data, variant.addr_width)
        expected = byte_popcounts(pre_perm)
        observed = byte_popcounts(sdata)
    else:
        expected = model_scramble_word(key, addr, data, variant.addr_width)
        observed = sdata
    if observed == expected:
        return []
    return [
        f"addr=0x{addr:x},key=0x{key:08x},data=0x{data:08x},sdata=0x{sdata:08x},"
        f"observed={observed},expected={expected}".replace(" ", "")
    ]


def chk(log: logging.Logger, name: str, ok: bool, **fields) -> None:
    """Log ``CHK-SCR-<name> PASS``, or raise with the ``FAIL`` line."""
    line = f"CHK-SCR-{name} {'PASS' if ok else 'FAIL'} " + " ".join(
        f"{k}={v}" for k, v in fields.items()
    )
    if not ok:
        raise AssertionError(line)
    log.info("%s", line)


async def check_roundtrip(
    port: ScramblerPort, name: str, addrs, memory, expected, scrambled_of, log, **fields
) -> None:
    """Descramble each address of ``addrs`` and grade it against ``expected``."""
    bad = []
    for addr in addrs:
        observed = await port.descramble(addr, memory[scrambled_of[addr]])
        if observed != expected[addr]:
            bad.append(f"0x{addr:x}:0x{expected[addr]:08x}->0x{observed:08x}")
    chk(
        log,
        name,
        not bad,
        addresses=len(addrs),
        mismatches=len(bad),
        first=bad[0] if bad else "none",
        **fields,
    )


async def check_variant(port: ScramblerPort, log: logging.Logger) -> None:
    variant = port.variant
    depth = variant.depth
    key = random.getrandbits(32)
    port.init(key)
    mode = "byte" if variant.byte_wise else "word"
    ids = {"mode": mode, "depth": depth}

    scrambled_of = {}
    for addr in range(depth):
        scrambled_of[addr] = await port.scrambled_address(addr)
    images = set(scrambled_of.values())
    moved = sum(1 for addr, image in scrambled_of.items() if addr != image)
    chk(
        log,
        "ADDR-PERM",
        len(images) == depth and max(images) < depth and moved > 0,
        **ids,
        key=f"0x{key:08x}",
        distinct=len(images),
        max_image=max(images),
        moved=moved,
    )

    graded = 0
    golden_bad: list = []
    sample = range(depth)
    memory: dict[int, int] = {}
    expected: dict[int, int] = {}
    addr_changed = 0
    for addr in sample:
        data = random.getrandbits(32)
        saddr, sdata = await port.scramble(addr, data)
        golden_bad += data_golden_mismatch(port, key, addr, data, sdata)
        graded += 1
        addr_changed += saddr != scrambled_of[addr]
        memory[saddr] = sdata
        expected[addr] = data
    chk(log, "ADDR-STABLE", addr_changed == 0, **ids, writes=depth, addr_changed=addr_changed)
    await check_roundtrip(port, "ROUNDTRIP-ASC", sample, memory, expected, scrambled_of, log, **ids)

    for value, addr in enumerate(reversed(sample)):
        saddr, sdata = await port.scramble(addr, value & DATA_MASK)
        golden_bad += data_golden_mismatch(port, key, addr, value & DATA_MASK, sdata)
        graded += 1
        memory[saddr] = sdata
        expected[addr] = value & DATA_MASK
    await check_roundtrip(
        port, "ROUNDTRIP-DESC", sample[::-1], memory, expected, scrambled_of, log, **ids
    )

    addr_a, addr_b = random.sample(range(depth), 2)
    data = random.getrandbits(32)
    _, sdata_a = await port.scramble(addr_a, data)
    golden_bad += data_golden_mismatch(port, key, addr_a, data, sdata_a)
    _, sdata_b = await port.scramble(addr_b, data)
    golden_bad += data_golden_mismatch(port, key, addr_b, data, sdata_b)
    graded += 2
    chk(
        log,
        "ADDR-DEP",
        sdata_a != sdata_b,
        **ids,
        data=f"0x{data:08x}",
        addr_a=f"0x{addr_a:x}",
        addr_b=f"0x{addr_b:x}",
        sdata_a=f"0x{sdata_a:08x}",
        sdata_b=f"0x{sdata_b:08x}",
    )
    other_key = key ^ (1 << random.randrange(32)) ^ random.getrandbits(32)
    port.init(other_key)
    _, sdata_other = await port.scramble(addr_a, data)
    golden_bad += data_golden_mismatch(port, other_key, addr_a, data, sdata_other)
    graded += 1
    chk(
        log,
        "KEY-DEP",
        sdata_other != sdata_a,
        **ids,
        data=f"0x{data:08x}",
        addr=f"0x{addr_a:x}",
        key=f"0x{key:08x}",
        other_key=f"0x{other_key:08x}",
        sdata=f"0x{sdata_a:08x}",
        sdata_other=f"0x{sdata_other:08x}",
    )
    chk(
        log,
        "DATA-GOLDEN",
        not golden_bad,
        **ids,
        writes=graded,
        mismatches=len(golden_bad),
        first=golden_bad[0] if golden_bad else "none",
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
