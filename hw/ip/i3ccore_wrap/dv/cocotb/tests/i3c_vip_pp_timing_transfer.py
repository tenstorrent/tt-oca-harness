# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Push-Pull Timing Transfer against an independent VIP target

The VIP-target counterpart of `i3c_pp_timing_transfer`: a private write and read
using the Push-Pull timing bank. A timing mismatch between the model and the
controller shows up here, because the VIP's own timing defaults come from MIPI
I3C Basic v1.1.1 Tables 86/87 rather than from the controller's programmed banks.
Requires `+i3c_vip_target`.

Constrained-random length and data (shared framework, seed from +seed/SEED/default).
"""

import cocotb
from env.i3c_rand import RandMgr, rand_bytes, rand_len
from env.i3c_test_base import make_env
from env.i3c_vip_flow import bring_up_and_assign, private_read, private_write

MWL = 64


@cocotb.test(timeout_time=4000, timeout_unit="us")
async def test_vip_pp_timing_transfer(dut):
    tb, helper, ctrl, _tgt = await make_env(dut)
    # bring_up_and_assign programs both the OD and PP timing banks
    vip = await bring_up_and_assign(dut, ctrl)
    r = RandMgr(name="vip_pp_timing")  # seed logged; +seed/SEED override

    write_data = rand_bytes(r, rand_len(r, MWL))
    ok, resp, rx = await private_write(dut, helper, ctrl, vip, write_data)
    assert ok, f"PP-timed write failed resp=0x{resp:08X}"
    assert rx == write_data, "PP-timed write data mismatch"

    read_data = rand_bytes(r, rand_len(r, MWL))
    ok, resp, crx = await private_read(dut, helper, ctrl, vip, read_data)
    assert ok, f"PP-timed read failed resp=0x{resp:08X}"
    assert crx == read_data, "PP-timed read data mismatch"

    tb.log.info(f"Push-Pull timing transfer against the VIP target (seed=0x{r.seed:08X})")
