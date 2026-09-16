# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Long Write Sanity against an independent VIP target

The VIP-target counterpart of `i3c_long_write_sanity`: SETDASA plus a 500-byte
private write, which is far past the controller TX FIFO depth, so it also covers
threshold-driven refill against a bus partner that is not the RTL under test.
Requires `+i3c_vip_target`.
"""

import cocotb
from env.i3c_test_base import make_env
from env.i3c_vip_flow import bring_up_and_assign, private_write

WRITE_LENGTH = 500


@cocotb.test(timeout_time=8000, timeout_unit="us")
async def test_vip_long_write_sanity(dut):
    tb, helper, ctrl, _tgt = await make_env(dut)
    vip = await bring_up_and_assign(dut, ctrl)

    write_data = [(i & 0xFF) for i in range(WRITE_LENGTH)]
    tb.log.info(f"Private write: {WRITE_LENGTH} bytes to the VIP target")

    ok, resp, rx = await private_write(dut, helper, ctrl, vip, write_data)
    assert ok, f"long write failed resp=0x{resp:08X}"
    assert len(rx) == WRITE_LENGTH, f"VIP target captured {len(rx)} bytes, expected {WRITE_LENGTH}"
    assert rx == write_data, (
        "long write payload mismatch, first at byte "
        f"{next(i for i, (e, g) in enumerate(zip(write_data, rx)) if e != g)}"
    )

    tb.log.info(f"{WRITE_LENGTH}-byte write verified against the VIP target")
