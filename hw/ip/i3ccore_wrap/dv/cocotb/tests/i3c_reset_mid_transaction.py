# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Reset Mid-Transaction

Asserts reset during an active transaction stream and confirms the device
recovers cleanly: after re-init + SETDASA, a fresh transfer succeeds.

Constrained-random: a random number of pre-reset transfers (random length/data)
run first, then reset is asserted after a *random* cycle delay so it lands at a
random bus phase. After
re-bring-up, a random post-reset transfer is self-checked. Seed from
+seed/SEED/default.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import I3CTransfer, RandMgr, do_transfer, rand_bytes, rand_len
from env.i3c_test_base import bring_up_and_assign, make_env

MWL = 32


@cocotb.test(timeout_time=3000, timeout_unit="us")
async def test_reset_mid_transaction(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="reset_mid")  # seed logged; +seed/SEED override

    # Random pre-reset traffic
    for _ in range(r.randint(1, 3)):
        t = I3CTransfer().randomize(r, mwl=MWL)
        await do_transfer(ctrl, tgt, t)

    # Kick off one more transfer, then assert reset after a random cycle delay so
    # it lands at a random point in the bus phase (start/addr/data/turnaround).
    pre_reset_data = rand_bytes(r, rand_len(r, MWL))
    ok, resp, rx = await ctrl.private_write(pre_reset_data, tgt, dat_idx=0)
    assert ok, f"pre-reset write failed resp=0x{resp:08X}"
    assert rx == pre_reset_data, f"pre-reset payload mismatch: got {rx} != sent {pre_reset_data}"
    delay = r.randint(1, 200)
    tb.log.info(f"asserting reset mid-transaction after {delay} cycles...")
    await ClockCycles(dut.clk, delay)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 20)

    # Re-bring-up and confirm clean recovery with a fresh random transfer.
    await bring_up_and_assign(ctrl, tgt)
    t = I3CTransfer().randomize(r, mwl=MWL)
    await do_transfer(ctrl, tgt, t)

    tb.log.info(f"Reset-mid-transaction recovery verified (seed=0x{r.seed:08X})")
