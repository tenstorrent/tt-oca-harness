# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Random Transfer Stress

Directed-random private write/read transfers with random direction/length/data,
checked for integrity each iteration via the built-in scoreboard.

Uses the shared constrained-random framework (constrained_random + i3c_rand):
the seed is resolved from +seed=<n> / SEED=<n> / default and logged, so each
regression run varies the sequence and accumulates coverage (run multiple seeds
and merge). A fixed default keeps local runs reproducible.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import I3CTransfer, RandMgr, do_transfer
from env.i3c_test_base import bring_up_and_assign, make_env

N_ITERS = 24
MWL = 256


@cocotb.test(timeout_time=15000, timeout_unit="us")
async def test_random_transfer_stress(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    # These two CCCs establish the whole randomization envelope; set_ccc reports
    # failure only through a returned flag, so an unprogrammed envelope would
    # otherwise go unnoticed for the entire run.
    ok, resp = await ctrl.setmwl(MWL, dat_idx=0)
    assert ok, f"SETMWL({MWL}) failed resp=0x{resp:08X}"
    ok, resp = await ctrl.setmrl(MWL, ibi_payload_size=0xFF, dat_idx=0)
    assert ok, f"SETMRL({MWL}) failed resp=0x{resp:08X}"

    r = RandMgr(name="random_transfer")  # seed logged; +seed/SEED override

    for i in range(N_ITERS):
        t = I3CTransfer().randomize(r, mwl=MWL)  # constrained: len<=MWL, data follows
        await do_transfer(ctrl, tgt, t)  # drives + self-checks (scoreboard)
        tb.log.info(f"[{i}] {t.dir.upper()} {t.length}B ok")
        await ClockCycles(dut.clk, 30)

    tb.log.info(f"Random transfer stress ({N_ITERS} iters, seed=0x{r.seed:08X}) complete")
