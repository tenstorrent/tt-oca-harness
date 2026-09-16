# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C IBI Payload-Size Variants

Target issues IBIs with varying payload sizes and the controller verifies the
received MDB + payload for each.

Constrained-random: each IBI uses a random MDB and a random payload length/bytes
(shared framework, seed from +seed/SEED/default), bounded by the configured IBI
payload size. The directed boundary sizes (0, 1, full) are still covered first,
then random ones are added. The received MDB is self-checked against what was
sent.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import RandMgr, rand_bytes, rand_ibi_mdb
from env.i3c_test_base import bring_up_and_assign, make_env

IBI_PAYLOAD_SIZE = 0x10
N_RANDOM = 4


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_ibi_payload_variants(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    # Program the DAT IBI-payload policy from the target's BCR[2], else the
    # controller aborts inbound IBIs (ibi_abort = ibi_reject | ~ibi_payload).
    # The returned bit is the programmed policy: if the internal GETBCR failed it is
    # left clear and every inbound IBI is aborted, so it has to be asserted.
    ibi_payload_bit = await ctrl.configure_target_ibi(0, 0x10, 0x10)
    assert ibi_payload_bit, (
        "DAT ibi_payload bit not set (GETBCR likely failed); the controller would "
        "abort every inbound IBI"
    )
    r = RandMgr(name="ibi_payload")  # seed logged; +seed/SEED override

    await ctrl.enable_ibi_interrupts(ibi_threshold=1)
    await tgt.enable_ibi_mode()
    # This SETMRL programs the IBI payload envelope every iteration below relies on.
    ok, resp = await ctrl.setmrl(0x40, ibi_payload_size=IBI_PAYLOAD_SIZE, dat_idx=0)
    assert ok, f"SETMRL(ibi_payload_size=0x{IBI_PAYLOAD_SIZE:02X}) failed resp=0x{resp:08X}"

    # directed boundary lengths first, then random ones
    lengths = [0, 1, IBI_PAYLOAD_SIZE] + [r.randint(0, IBI_PAYLOAD_SIZE) for _ in range(N_RANDOM)]

    for n in lengths:
        mdb = rand_ibi_mdb(r)  # random MDB (tracked for self-check)
        payload = rand_bytes(r, n)
        tb.log.info(f"IBI mdb=0x{mdb:02X} payload size {n}")
        assert await tgt.write_ibi(mdb, payload), (
            f"write_ibi mdb=0x{mdb:02X} len={n} failed (target IBI queue full)"
        )
        ok, _reg = await ctrl.wait_ibi_received()
        assert ok, (
            f"IBI mdb=0x{mdb:02X} len={n} never reached the controller "
            f"(ibi_status_thld_stat never set)"
        )
        ok, ibi_id, got_mdb, got_payload = await ctrl.read_ibi()
        tb.log.info(f"  received ibi_id=0x{ibi_id:02X} mdb=0x{got_mdb:02X} payload={got_payload}")
        assert ok, "IBI read failed"
        assert got_mdb == mdb, f"MDB mismatch: got 0x{got_mdb:02X} != sent 0x{mdb:02X}"
        # read_ibi truncates to the descriptor's data_length, so this compare is exact.
        assert list(got_payload) == list(payload), (
            f"IBI payload mismatch at len={n}: got {[f'0x{b:02X}' for b in got_payload]} "
            f"!= sent {[f'0x{b:02X}' for b in payload]}"
        )
        ok, ibi_status = await tgt.wait_ibi_done()
        assert ok, f"target IBI never completed at len={n} (last status=0x{ibi_status:08X})"
        await ClockCycles(dut.clk, 50)

    tb.log.info(f"IBI payload-size variants complete (seed=0x{r.seed:08X})")
