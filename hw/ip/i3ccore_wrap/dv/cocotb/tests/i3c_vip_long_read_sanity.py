# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Long Read Sanity against an independent VIP target

The VIP-target counterpart of `i3c_long_read_sanity`: SETDASA plus a 500-byte
private read, which is far past the controller RX FIFO depth, so it also covers
threshold-driven drain against a bus partner that is not the RTL under test.
Requires `+i3c_vip_target`.
"""

import cocotb
from env.i3c_test_base import make_env
from env.i3c_vip_flow import bring_up_and_assign, private_read

READ_LENGTH = 500


@cocotb.test(timeout_time=8000, timeout_unit="us")
async def test_vip_long_read_sanity(dut):
    tb, helper, ctrl, _tgt = await make_env(dut)
    vip = await bring_up_and_assign(dut, ctrl)

    tx_data = [(i & 0xFF) for i in range(READ_LENGTH)]
    tb.log.info(f"Private read: {READ_LENGTH} bytes from the VIP target")

    ok, resp, rx = await private_read(dut, helper, ctrl, vip, tx_data)
    assert ok, f"long read failed resp=0x{resp:08X}"
    assert len(rx) == READ_LENGTH, f"controller received {len(rx)} bytes, expected {READ_LENGTH}"
    assert rx == tx_data, (
        "long read payload mismatch, first at byte "
        f"{next(i for i, (e, g) in enumerate(zip(tx_data, rx)) if e != g)}"
    )

    tb.log.info(f"{READ_LENGTH}-byte read verified against the VIP target")
