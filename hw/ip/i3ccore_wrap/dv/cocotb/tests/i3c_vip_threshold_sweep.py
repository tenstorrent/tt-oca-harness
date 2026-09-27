# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C FIFO Threshold Sweep against an independent VIP target

The VIP-target counterpart of `i3c_threshold_sweep`: sweeps the controller TX/RX
FIFO threshold registers and runs a 32-byte transfer at each setting to confirm
the threshold interrupts drive the data path. Requires `+i3c_vip_target`.

Threshold encoding: the RTL threshold is in FIFO *entries* of 4 bytes, mapping
reg value t -> (1 << (t+1)) entries, so t=0 -> 2 entries (8 B), t=1 -> 4 (16 B),
t=2 -> 8 (32 B), t=3 -> 16 (64 B). The sweep stops at t=2 because a 32-byte
transfer is 8 entries and cannot reach the 16 entries t=3 needs.

Only the controller is re-initialized per leg. The VIP target stays attached,
since one model owns the bus for the whole simulation, and it keeps the dynamic
address SETDASA gave it.
"""

import cocotb
from env.i3c_test_base import make_env
from env.i3c_vip_flow import attach_vip, bring_up_and_assign, private_write


@cocotb.test(timeout_time=8000, timeout_unit="us")
async def test_vip_threshold_sweep(dut):
    tb, helper, ctrl, _tgt = await make_env(dut)
    vip = attach_vip(dut)

    for thr in range(0, 3):
        tb.log.info(f"=== threshold reg value {thr} (= {2 ** (thr + 1)} entries) ===")
        await bring_up_and_assign(dut, ctrl, tx_buf=thr, rx_buf=thr, vip=vip)

        data = [(i + thr) & 0xFF for i in range(32)]
        ok, resp, rx = await private_write(dut, helper, ctrl, vip, data)
        assert ok, f"write failed at thr={thr} resp=0x{resp:08X}"
        assert rx == data, f"data mismatch at thr={thr}"

    tb.log.info("Threshold sweep against the VIP target complete")
