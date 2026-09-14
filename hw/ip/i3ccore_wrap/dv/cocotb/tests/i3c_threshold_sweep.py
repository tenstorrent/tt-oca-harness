# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C FIFO Threshold Sweep

Sweeps TX/RX FIFO threshold register values and runs a 32-byte transfer at each
setting to confirm threshold interrupts drive the data path.

Threshold encoding note: the RTL threshold is in FIFO *entries* (4 bytes each),
mapping reg value t -> (1 << (t+1)) entries:
    t=0 -> 2 entries (8 B), t=1 -> 4 (16 B), t=2 -> 8 (32 B), t=3 -> 16 (64 B).

The sweep covers t = 0..2 only. The 32-byte transfer is exactly 8 entries, so t=0/1/2
thresholds (2/4/8 entries) are reachable and the RX-data threshold interrupt
fires and drives the drain as intended. t=3 needs >=16 entries (>=64 B) before
the threshold can fire, so a 32-byte transfer cannot exercise it.
"""

import cocotb
from env.i3c_test_base import (
    DEFAULT_DYNAMIC_ADDR,
    DEFAULT_STATIC_ADDR,
    init_controller,
    init_target,
    make_env,
)


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_threshold_sweep(dut):
    tb, helper, ctrl, tgt = await make_env(dut)

    for thr in range(0, 3):
        tb.log.info(f"=== threshold reg value {thr} (= {2 ** (thr + 1)} entries) ===")
        await init_controller(ctrl, tx_buf=thr, rx_buf=thr)
        await init_target(tgt, DEFAULT_STATIC_ADDR, tx_buf=thr, rx_buf=thr)

        ok, resp = await ctrl.send_setdasa(DEFAULT_STATIC_ADDR, DEFAULT_DYNAMIC_ADDR)
        assert ok, f"SETDASA failed at thr={thr}"
        # wait_dynamic_addr returns (success, addr) and logs nothing on expiry, so a
        # target that never took its address would otherwise walk silently into the
        # transfer below. This test bypasses bring_up_and_assign to re-init per leg,
        # so it has to make that helper's two assertions itself.
        ok, dyn = await tgt.wait_dynamic_addr()
        assert ok, f"target never took a dynamic address at thr={thr}"
        assert dyn == DEFAULT_DYNAMIC_ADDR, (
            f"target addr mismatch at thr={thr}: 0x{dyn:02X} != 0x{DEFAULT_DYNAMIC_ADDR:02X}"
        )

        data = [(i + thr) & 0xFF for i in range(32)]
        ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
        assert ok, f"write failed at thr={thr} resp=0x{resp:08X}"
        assert rx == data, f"data mismatch at thr={thr}"

    tb.log.info("Threshold sweep complete")
