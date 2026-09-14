# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Multi-Target DAT

Programs multiple Device Address Table entries and exercises addressing the
real target via index 0 while index 1 points to a non-responding address
(mirrors the error-sanity NACK path for a second DAT entry).

Constrained-random: the absent DAT[1] address (and its static addr) and the
DAT[0] payload are randomized (shared framework, seed from +seed/SEED/default).
DAT[0] keeps the real target's assigned dynamic address (0x10 from bring-up);
the absent address is constrained to be legal and distinct from it.
"""

import cocotb
from env.i3c_rand import RandMgr, rand_bytes, rand_i3c_addr, rand_len
from env.i3c_test_base import DEFAULT_DYNAMIC_ADDR, bring_up_and_assign, make_env

MWL = 64


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_multi_target_dat(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="multi_target")  # seed logged; +seed/SEED override

    # DAT[1] -> a legal address distinct from the real target (no device there)
    absent_dyn = rand_i3c_addr(r, exclude={DEFAULT_DYNAMIC_ADDR})
    absent_static = rand_i3c_addr(r, exclude={DEFAULT_DYNAMIC_ADDR, absent_dyn})
    await ctrl.set_dat_entry(1, absent_static, absent_dyn)
    tb.log.info(f"DAT[1] absent: static=0x{absent_static:02X} dynamic=0x{absent_dyn:02X}")

    # Transfer to DAT[0] (real target) should pass
    data = rand_bytes(r, rand_len(r, MWL))
    ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
    assert ok, f"DAT[0] transfer failed resp=0x{resp:08X}"
    assert rx == data, "DAT[0] data mismatch"
    tb.log.info(f"DAT[0] (real target) {len(data)}B transfer ok")

    # Transfer to DAT[1] (absent) is expected to error/NACK
    ok2, resp2, _ = await ctrl.private_write(rand_bytes(r, 1), tgt, dat_idx=1, expect_error=True)
    err2 = (resp2 >> 28) & 0xF
    assert not ok2, f"DAT[1] absent address should NACK/error, got ok=True resp=0x{resp2:08X}"
    assert err2 != 0, f"DAT[1] expected non-zero err_status, got {err2} resp=0x{resp2:08X}"
    tb.log.info(f"DAT[1] (absent) NACK/err as expected: err_status={err2} resp=0x{resp2:08X}")

    tb.log.info(f"Multi-target DAT test complete (seed=0x{r.seed:08X})")
