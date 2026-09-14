# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Back-to-Back Transactions

Issues a stream of transactions with minimal inter-transaction gap to stress
command/response queue turnaround and bus-free timing.

Constrained-random: each transaction has a random direction, a random small
length and random data (shared framework, seed from +seed/SEED/default), with a
random (often zero) inter-transaction gap to vary queue-turnaround timing. The
built-in scoreboard (sent == received) checks every one.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import I3CTransfer, RandMgr, do_transfer
from env.i3c_test_base import bring_up_and_assign, make_env

N_TXN = 16
SMALL_MWL = 16  # back-to-back stresses turnaround, so keep payloads small


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_back_to_back(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="back_to_back")  # seed logged; +seed/SEED override

    for i in range(N_TXN):
        t = I3CTransfer().randomize(r, mwl=SMALL_MWL)
        await do_transfer(ctrl, tgt, t)  # drives + self-checks
        gap = r.choice([0, 0, 0, 5, 20])  # mostly minimal gap, occasionally spaced
        if gap:
            await ClockCycles(dut.clk, gap)

    tb.log.info(f"{N_TXN} back-to-back transactions complete (seed=0x{r.seed:08X})")
