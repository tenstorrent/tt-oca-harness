# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
IBI receive diagnostic.

Exercises an IBI containing an MDB and a 24-byte payload, which fits within the
configured eight-DWORD IBI buffer.
"""

import cocotb
from env.i3c_test_base import bring_up_and_assign, make_env


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_ibi_diag(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    await ctrl.enable_ibi_interrupts(ibi_threshold=1)
    await tgt.enable_ibi_mode()

    # Require DAT.ibi_payload so the controller accepts the inbound IBI instead of
    # exercising its abort path.
    ibi_payload_bit = await ctrl.configure_target_ibi(0, 0x10, 0x10)
    assert ibi_payload_bit, (
        "DAT ibi_payload bit not set (GETBCR likely failed) -- the controller would "
        "abort every inbound IBI and this probe would measure the wrong path"
    )

    # ibi_payload_size=0x40 is what makes a 24-byte payload legal for this probe.
    ok, resp = await ctrl.setmrl(0x100, ibi_payload_size=0x40, dat_idx=0)
    assert ok, f"SETMRL failed resp=0x{resp:08X}"

    n = 24
    mdb = 0xB8
    payload = bytes((i ^ 0x5A) & 0xFF for i in range(n))
    tb.log.info(f"DIAG: write_ibi mdb=0x{mdb:02X} payload_len={n}")
    assert await tgt.write_ibi(mdb, payload), (
        f"write_ibi mdb=0x{mdb:02X} payload_len={n} failed (target IBI queue full)"
    )
    ok, reg = await ctrl.wait_ibi_received(max_polls=25000)
    tb.log.info(f"DIAG: wait_ibi_received ok={ok}")
    # This is the probe's whole outcome: a non-arrival must fail, not log one word.
    assert ok, (
        f"IBI mdb=0x{mdb:02X} payload_len={n} never reached the controller "
        f"(ibi_status_thld_stat never set within 25000 polls)"
    )
