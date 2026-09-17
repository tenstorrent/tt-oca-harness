# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Broadcast CCC

Exercises Broadcast CCCs (MIPI I3C Basic Table 16/17):
  - Broadcast ENEC  = 0x00
  - Broadcast DISEC = 0x01
  - Broadcast RSTDAA = 0x06

Bring-up still uses SETDASA so the target has a Dynamic Address before
RSTDAA; after RSTDAA the test asserts DYNAMIC_ADDR_VALID clears.

Constrained-random: the ENEC/DISEC *event defining byte* is randomized (shared
framework, seed from +seed/SEED/default). Per MIPI I3C
the defined event bits are ENINT/IBI (bit0), ENCR (bit1) and ENHJ (bit3); a
random subset (at least one bit, only legal bits) is generated so the defining-
byte datapath sees the full legal event-mask space. DISEC mirrors whatever
ENEC enabled so the pair is symmetric.
"""

import cocotb
from env.i3c_api import CCC_DISEC_BCAST, CCC_ENEC_BCAST
from env.i3c_rand import RandMgr
from env.i3c_test_base import bring_up_and_assign, make_env

# Legal event-enable bits in the ENEC/DISEC defining byte (MIPI I3C):
#   bit0 = ENINT (IBI), bit1 = ENCR (controller-role req), bit3 = ENHJ (hot-join)
EVENT_BITS = (0x01, 0x02, 0x08)


def rand_event_mask(r):
    """A legal ENEC/DISEC defining byte: a random non-empty subset of the
    defined event bits (never an all-zero or reserved-bit mask)."""
    while True:
        mask = 0
        for bit in EVENT_BITS:
            if r.randint(0, 1):
                mask |= bit
        if mask:  # at least one event bit set
            return mask


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_broadcast_ccc(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)
    r = RandMgr(name="broadcast_ccc")  # seed logged; +seed/SEED override

    event_mask = rand_event_mask(r)

    # Broadcast ENEC: enable a random set of events on all Targets
    ok, resp = await ctrl.broadcast_set_ccc(CCC_ENEC_BCAST, [event_mask])
    tb.log.info(f"Broadcast ENEC(0x00, mask=0x{event_mask:02X}) ok={ok} resp=0x{resp:08X}")
    assert ok, f"Broadcast ENEC failed resp=0x{resp:08X}"

    # Broadcast DISEC: disable the same set of events (symmetric pair)
    ok, resp = await ctrl.broadcast_set_ccc(CCC_DISEC_BCAST, [event_mask])
    tb.log.info(f"Broadcast DISEC(0x01, mask=0x{event_mask:02X}) ok={ok} resp=0x{resp:08X}")
    assert ok, f"Broadcast DISEC failed resp=0x{resp:08X}"

    # Broadcast RSTDAA: clear Dynamic Address on all Targets (must be last)
    ok, resp = await ctrl.send_rstdaa()
    tb.log.info(f"Broadcast RSTDAA(0x06) ok={ok} resp=0x{resp:08X}")
    assert ok, f"Broadcast RSTDAA failed resp=0x{resp:08X}"

    cleared = await tgt.wait_dynamic_addr_cleared()
    assert cleared, "Target DYNAMIC_ADDR_VALID still set after Broadcast RSTDAA"

    tb.log.info(f"Broadcast CCC test complete (seed=0x{r.seed:08X})")
