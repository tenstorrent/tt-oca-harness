# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C SETNEWDA

Assigns a dynamic address via SETDASA, then re-assigns it with SETNEWDA
(CCC 0x88) and confirms a private transfer still works on the new address.

Constrained-random: the *new* dynamic address is randomized (shared framework,
seed from +seed/SEED/default) — it is constrained to be a legal, non-reserved
7-bit address and distinct from the original SETDASA
address, so the DAT `dynamic_address` field and target address-match logic see a
wider value space. The verify payload is random bytes. The private write on the
re-assigned address is the built-in scoreboard.
"""

import cocotb
from env.i3c_rand import RandMgr, rand_bytes, rand_i3c_addr, rand_len
from env.i3c_test_base import DEFAULT_DYNAMIC_ADDR, bring_up_and_assign, make_env

SETNEWDA_CCC = 0x88
MWL = 64


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_setnewda(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="setnewda")  # seed logged; +seed/SEED override

    # New dynamic address: legal, non-reserved, and != the SETDASA-assigned one.
    new_dyn = rand_i3c_addr(r, exclude={DEFAULT_DYNAMIC_ADDR})

    # Re-assign dynamic address via SETNEWDA (data = new dynamic addr, left-shifted).
    # set_ccc returns (success, resp) -- unpack, or `ok` is a truthy tuple for every
    # outcome including failure.
    ok, resp = await ctrl.set_ccc(SETNEWDA_CCC, [new_dyn << 1], dat_idx=0)
    tb.log.info(f"SETNEWDA -> 0x{new_dyn:02X} (was 0x{DEFAULT_DYNAMIC_ADDR:02X}) ok={ok}")
    assert ok, f"SETNEWDA to 0x{new_dyn:02X} failed resp=0x{resp:08X}"

    # Update DAT to point at the new dynamic address and verify a transfer
    await ctrl.set_dat_entry(0, DEFAULT_DYNAMIC_ADDR, new_dyn)
    data = rand_bytes(r, rand_len(r, MWL))
    ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
    tb.log.info(f"Private write on new DA 0x{new_dyn:02X}: {len(data)}B ok={ok}")
    # The private write is this test's scoreboard: assert both legs.
    assert ok, f"private write on new DA 0x{new_dyn:02X} failed resp=0x{resp:08X}"
    assert rx == data, f"payload mismatch on new DA 0x{new_dyn:02X}: got {rx} != sent {data}"

    tb.log.info(f"SETNEWDA test complete (seed=0x{r.seed:08X})")
