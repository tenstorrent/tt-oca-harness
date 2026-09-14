# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C OD->PP Mode Switch against an independent VIP target

The VIP-target counterpart of `i3c_od_pp_mode_switch`: back-to-back transfers
that exercise the controller muxing between the Open-Drain (broadcast/address
phase) and Push-Pull (payload) timing banks. Requires `+i3c_vip_target`.

Constrained-random lengths and data each round (shared framework, seed from
+seed/SEED/default). Every transfer begins OD then switches to PP, so the mux is
exercised across a variety of payload sizes.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import RandMgr, rand_bytes, rand_len
from env.i3c_test_base import make_env
from env.i3c_vip_flow import bring_up_and_assign, private_write

N_ROUNDS = 4
MWL = 32


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_vip_od_pp_mode_switch(dut):
    tb, helper, ctrl, _tgt = await make_env(dut)
    vip = await bring_up_and_assign(dut, ctrl)
    r = RandMgr(name="vip_od_pp")  # seed logged; +seed/SEED override

    for _ in range(N_ROUNDS):
        n = rand_len(r, MWL)
        data = rand_bytes(r, n)
        ok, resp, rx = await private_write(dut, helper, ctrl, vip, data)
        assert ok, f"{n}B write failed resp=0x{resp:08X}"
        assert rx == data, f"{n}B write data mismatch"
        tb.log.info(f"OD->PP {n}-byte transfer ok")
        await ClockCycles(dut.clk, 50)

    tb.log.info(f"OD/PP mode-switch against the VIP target (seed=0x{r.seed:08X})")
