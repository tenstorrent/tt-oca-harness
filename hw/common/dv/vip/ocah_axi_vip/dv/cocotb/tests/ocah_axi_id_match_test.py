# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI VIP selftest: results carry live-sampled response IDs.

Full-stack proof on the s_axi bundle (shared master against the shared fault
slave): every blocking result exposes the issued AWID/ARID and a BID/RID
sampled from the live response handshake — including the RLAST beat of a
burst — and a matching responder yields ``observed_id == issued_id`` with
``id_match is True``.  Data integrity is cross-checked through the slave's
backdoor so an ID-only pass cannot mask a data defect.
"""

from __future__ import annotations

import logging
import os
import random

import cocotb
from ocah_axi_vip_harness import build_full_stack, start_clock_reset

log = logging.getLogger("cocotb.tb.ocah_axi_id_match_test")


@cocotb.test()
async def ocah_axi_id_match_test(dut) -> None:
    await start_clock_reset(dut)
    master, slave = build_full_stack(dut)
    await master.start()
    seq = master.sequence

    n_ops = int(os.environ.get("OCAH_AXI_ID_MATCH_OPS", "12"))
    if n_ops < 2:
        raise ValueError(f"OCAH_AXI_ID_MATCH_OPS must be >= 2 (ID-space corners); got {n_ops}")
    checked = 0
    log.info("start: %d randomized ops plus directed ID corners and a burst", n_ops)

    # Randomized single-beat write/read pairs with independent random IDs;
    # the first two iterations pin the ID-space corners on top of the random
    # sweep.
    directed_ids = [(0x00, 0xFF), (0xFF, 0x00)]
    for index in range(n_ops):
        if index < len(directed_ids):
            awid, arid = directed_ids[index]
        else:
            awid = random.randrange(256)
            arid = random.randrange(256)
        addr = random.randrange(0, 2**14) & ~0x3
        data = random.getrandbits(32)

        wres = await seq.write_result(addr, data, id=awid)
        log.info(
            "op %d: write addr=0x%08x data=0x%08x issued=0x%02x observed=%s",
            index,
            addr,
            data,
            awid,
            wres.observed_id,
        )
        assert wres.ok, f"write resp=0x{wres.resp:x}"
        assert wres.issued_id == awid
        assert wres.observed_id is not None, "BID capture miss on a completing write"
        assert wres.observed_id == awid, f"BID 0x{wres.observed_id:x} != issued AWID 0x{awid:x}"
        assert wres.id_match is True

        backdoor = slave.sequence.read32(addr)
        assert backdoor == data, f"backdoor 0x{backdoor:08x} != written 0x{data:08x}"

        rres = await seq.read_result(addr, id=arid)
        log.info(
            "op %d: read  addr=0x%08x data=0x%08x issued=0x%02x observed=%s",
            index,
            addr,
            rres.data,
            arid,
            rres.observed_id,
        )
        assert rres.ok, f"op {index}: read resp=0x{rres.resp:x} addr=0x{addr:08x}"
        assert rres.data == data, (
            f"op {index}: read data 0x{rres.data:08x} != written 0x{data:08x} at 0x{addr:08x}"
        )
        assert rres.issued_id == arid
        assert rres.observed_id is not None, "RID capture miss on a completing read"
        assert rres.observed_id == arid, (
            f"op {index}: RID 0x{rres.observed_id:x} != issued ARID 0x{arid:x}"
        )
        assert rres.id_match is True
        checked += 2

    # Default-ID transaction: issued_id must report the driven 0, not None.
    addr = 0x40
    data = random.getrandbits(32)
    wres = await seq.write_result(addr, data)
    assert wres.issued_id == 0 and wres.observed_id == 0 and wres.id_match is True, (
        f"default-ID write: issued={wres.issued_id} observed={wres.observed_id}"
    )
    checked += 1

    # Burst: the RID is sampled on the completing (RLAST) beat.
    burst_id = random.randrange(256)
    burst_base = (random.randrange(0, 2**14) & ~0xFF) | 0x10  # 4 beats, page-safe
    words = [random.getrandbits(32) for _ in range(4)]
    bres = await seq.burst_write_result(burst_base, words, id=burst_id)
    assert bres.ok and bres.observed_id == burst_id and bres.id_match is True, (
        f"burst write: issued=0x{burst_id:x} observed={bres.observed_id}"
    )
    rres = await seq.burst_read_result(burst_base, 4, id=burst_id)
    log.info(
        "burst: base=0x%08x issued=0x%02x observed=%s words=%s",
        burst_base,
        burst_id,
        rres.observed_id,
        [f"0x{w:08x}" for w in rres.data_words],
    )
    assert list(rres.data_words) == words, (
        f"burst read data {[hex(w) for w in rres.data_words]} != written {[hex(w) for w in words]}"
    )
    assert rres.issued_id == burst_id and rres.observed_id == burst_id, (
        f"burst read: issued=0x{burst_id:x} observed={rres.observed_id} (RLAST-beat sample)"
    )
    assert rres.id_match is True
    checked += 2

    stats = seq.get_statistics()
    log.info("done: %d ID-checked results, sequence stats=%s", checked, stats)
    assert checked == 2 * n_ops + 3
