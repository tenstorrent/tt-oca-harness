# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Broadcast CCC  (Test Plan #32)

Exercises broadcast CCCs beyond SETDASA: ENEC / DISEC (enable/disable events)
and RSTDAA (via RSTACT defining byte 0x01).

Constrained-random: the ENEC/DISEC *event defining byte* is randomized (shared
framework, seed from +seed/SEED/default) instead of a fixed 0x01. Per MIPI I3C
the defined event bits are ENINT/IBI (bit0), ENCR (bit1) and ENHJ (bit3); a
random subset (at least one bit, only legal bits) is generated so the broadcast
defining-byte datapath sees the full event-mask space. DISEC mirrors whatever
ENEC enabled so the pair is symmetric.
"""

import cocotb
from i3c_rand import RandMgr
from i3c_test_base import bring_up_and_assign, make_env

ENEC_CCC = 0x80  # broadcast enable events command
DISEC_CCC = 0x81  # broadcast disable events command

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

    # ENEC: enable a random set of events
    ok = await ctrl.set_ccc(ENEC_CCC, [event_mask], dat_idx=0)
    tb.log.info(f"ENEC(mask=0x{event_mask:02X}) ok={ok}")

    # DISEC: disable the same set of events (symmetric pair)
    ok = await ctrl.set_ccc(DISEC_CCC, [event_mask], dat_idx=0)
    tb.log.info(f"DISEC(mask=0x{event_mask:02X}) ok={ok}")

    # RSTDAA via RSTACT defining byte 0x01
    ok = await ctrl.rstact(0x01, dat_idx=0)
    tb.log.info(f"RSTACT/RSTDAA ok={ok}")

    tb.log.info(f"Broadcast CCC test complete (seed=0x{r.seed:08X})")
