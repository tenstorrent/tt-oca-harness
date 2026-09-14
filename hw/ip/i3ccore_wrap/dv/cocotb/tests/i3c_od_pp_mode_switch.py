# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C OD->PP Mode Switch

Runs back-to-back transfers that exercise the controller muxing between the
Open-Drain (broadcast/address phase) and Push-Pull (payload) timing banks.

Constrained-random lengths + data each round (shared framework, seed from
+seed/SEED/default). Every transfer still begins OD (broadcast addr) then PP
(payload), so the OD->PP mux is exercised across a variety of payload sizes.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import RandMgr, rand_bytes, rand_len
from env.i3c_test_base import bring_up_and_assign, make_env

N_ROUNDS = 4
MWL = 32


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_od_pp_mode_switch(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="od_pp")  # seed logged; +seed/SEED override

    for i in range(N_ROUNDS):
        n = rand_len(r, MWL)
        data = rand_bytes(r, n)
        ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
        assert ok, f"{n}B write failed resp=0x{resp:08X}"
        assert rx == data, f"{n}B write data mismatch"
        tb.log.info(f"OD->PP {n}-byte transfer ok")
        await ClockCycles(dut.clk, 50)

    tb.log.info(f"OD/PP mode-switch test complete (seed=0x{r.seed:08X})")
