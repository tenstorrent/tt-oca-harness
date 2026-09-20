# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Back-to-Back Transactions against an independent VIP target

The VIP-target counterpart of `i3c_back_to_back`: a stream of transactions with
minimal inter-transaction gap, stressing command/response queue turnaround and
bus-free timing. Requires `+i3c_vip_target`.

Constrained-random direction, small length and data (shared framework, seed from
+seed/SEED/default), with a random and often zero gap. The scoreboard is
sent == received on every transaction.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import I3CTransfer, RandMgr
from env.i3c_test_base import make_env
from env.i3c_vip_flow import bring_up_and_assign, do_transfer

N_TXN = 16
SMALL_MWL = 16  # back-to-back stresses turnaround, so keep payloads small


@cocotb.test(timeout_time=8000, timeout_unit="us")
async def test_vip_back_to_back(dut):
    tb, helper, ctrl, _tgt = await make_env(dut)
    vip = await bring_up_and_assign(dut, ctrl)
    r = RandMgr(name="vip_back_to_back")  # seed logged; +seed/SEED override

    for _ in range(N_TXN):
        t = I3CTransfer().randomize(r, mwl=SMALL_MWL)
        await do_transfer(dut, helper, ctrl, vip, t)
        gap = r.choice([0, 0, 0, 5, 20])  # mostly minimal, occasionally spaced
        if gap:
            await ClockCycles(dut.clk, gap)

    tb.log.info(f"{N_TXN} back-to-back transactions against the VIP target (seed=0x{r.seed:08X})")
