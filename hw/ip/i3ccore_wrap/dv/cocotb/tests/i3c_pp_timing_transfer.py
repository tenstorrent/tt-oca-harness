# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Push-Pull Timing Transfer

Runs a private write/read using the Push-Pull timing bank (configure_timing_pp).
Verifies data transfers using the configured Push-Pull timing bank.

Constrained-random length + data (shared framework, seed from +seed/SEED/default).
"""

import cocotb
from env.i3c_rand import RandMgr, rand_bytes, rand_len
from env.i3c_test_base import bring_up_and_assign, make_env

MWL = 64


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_pp_timing_transfer(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    # bring_up_and_assign already programs both OD and PP timing banks
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="pp_timing")  # seed logged; +seed/SEED override

    write_data = rand_bytes(r, rand_len(r, MWL))
    ok, resp, rx = await ctrl.private_write(write_data, tgt, dat_idx=0)
    assert ok, f"PP-timed write failed resp=0x{resp:08X}"
    assert rx == write_data, "PP-timed write data mismatch"

    read_data = rand_bytes(r, rand_len(r, MWL))
    ok, resp, crx = await ctrl.private_read(tgt, read_data, dat_idx=0)
    assert ok, f"PP-timed read failed resp=0x{resp:08X}"
    assert crx == read_data, "PP-timed read data mismatch"

    tb.log.info(f"Push-Pull timing transfer complete (seed=0x{r.seed:08X})")
