# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Random Transfer Stress  (Test Plan #44)

Directed-random private write/read transfers with random direction/length/data,
checked for integrity each iteration via the built-in scoreboard.

The seed is resolved by i3c_rand from +seed=<n> / SEED=<n> / default and
logged, so each regression run varies the sequence and accumulates coverage.
A fixed default keeps local runs reproducible.
"""

import cocotb
from cocotb.triggers import ClockCycles
from i3c_rand import I3CTransfer, RandMgr, do_transfer
from i3c_test_base import bring_up_and_assign, make_env

N_ITERS = 24
MWL = 256


@cocotb.test(timeout_time=15000, timeout_unit="us")
async def test_random_transfer_stress(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    await ctrl.setmwl(MWL, dat_idx=0)
    await ctrl.setmrl(MWL, ibi_payload_size=0xFF, dat_idx=0)

    r = RandMgr(name="random_transfer")  # seed logged; +seed/SEED override
    tb.log.info(f"Random transfer stress: seed=0x{r.seed:08X} iterations={N_ITERS} mwl={MWL}")

    for i in range(N_ITERS):
        t = I3CTransfer().randomize(r, mwl=MWL)  # constrained: len<=MWL, data follows
        await do_transfer(ctrl, tgt, t)  # drives + self-checks (scoreboard)
        tb.log.info(f"[{i}] {t.dir.upper()} {t.length}B data={t.data.hex()} ok")
        await ClockCycles(dut.clk, 30)

    tb.log.info(f"Random transfer stress ({N_ITERS} iters, seed=0x{r.seed:08X}) complete")
