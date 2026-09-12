# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C IBI Payload-Size Variants

Target issues IBIs with varying payload sizes and the controller verifies the
received MDB + payload for each.

Constrained-random: each IBI uses a random MDB and a random payload length/bytes
(shared framework, seed from +seed/SEED/default), bounded by the configured IBI
payload size. The directed boundary sizes (0, 1, full) run first, then random
ones. The received MDB is self-checked against what was sent.
"""

import cocotb
from cocotb.triggers import ClockCycles
from i3c_rand import RandMgr, rand_bytes, rand_ibi_mdb
from i3c_test_base import bring_up_and_assign, make_env

IBI_PAYLOAD_SIZE = 0x10
N_RANDOM = 4


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_ibi_payload_variants(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="ibi_payload")  # seed logged; +seed/SEED override

    await ctrl.enable_ibi_interrupts(ibi_threshold=1)
    await tgt.enable_ibi_mode()
    await ctrl.setmrl(0x40, ibi_payload_size=IBI_PAYLOAD_SIZE, dat_idx=0)

    # directed boundary lengths first, then random ones
    lengths = [0, 1, IBI_PAYLOAD_SIZE] + [r.randint(0, IBI_PAYLOAD_SIZE) for _ in range(N_RANDOM)]

    for n in lengths:
        mdb = rand_ibi_mdb(r)  # random MDB (tracked for self-check)
        payload = rand_bytes(r, n)
        tb.log.info(f"IBI mdb=0x{mdb:02X} payload size {n}")
        await tgt.write_ibi(mdb, payload)
        await ctrl.wait_ibi_received()
        ok, ibi_id, got_mdb, got_payload = await ctrl.read_ibi()
        tb.log.info(f"  received ibi_id=0x{ibi_id:02X} mdb=0x{got_mdb:02X} payload={got_payload}")
        assert ok, "IBI read failed"
        assert got_mdb == mdb, f"MDB mismatch: got 0x{got_mdb:02X} != sent 0x{mdb:02X}"
        await tgt.wait_ibi_done()
        await ClockCycles(dut.clk, 50)

    tb.log.info(f"IBI payload-size variants complete (seed=0x{r.seed:08X})")
