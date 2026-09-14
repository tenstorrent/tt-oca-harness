# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Multi-Instance Independence

Confirms the wrapper's AXI-Lite address decode isolates the two instances:
writing instance-0's register space must not disturb instance-1's, and each
instance retains its own value.

Constrained-random: a random non-zero, field-legal pattern is used (shared
framework, seed from +seed/SEED/default). Each byte is in 0..7 so it round-trips
QUEUE_THLD_CTRL exactly; isolation is checked by giving the two instances
distinct values and swapping them.
The DAT region (0x400+) is avoided: it is external SRAM, not a 32-bit scratch.
"""

import cocotb
from env.i3c_rand import RandMgr
from env.i3c_test_base import CTRL_BASE, TGT_BASE, make_env

QUEUE_THLD_CTRL = 0x090


def _rand_thld_pattern(r, exclude=()):
    """32-bit value, every byte 0..7 (round-trips QUEUE_THLD_CTRL), not in exclude."""
    while True:
        p = sum(r.randint(0, 7) << (8 * i) for i in range(4))
        if p not in exclude:
            return p


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_multi_instance_indep(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    r = RandMgr(name="multi_instance")  # seed logged; +seed/SEED override

    # Two distinct random patterns (and distinct from 0)
    pat_a = _rand_thld_pattern(r, exclude={0})
    pat_b = _rand_thld_pattern(r, exclude={0, pat_a})

    # Distinct values to the same offset in each instance
    await helper.write(CTRL_BASE + QUEUE_THLD_CTRL, pat_a)  # instance 0
    await helper.write(TGT_BASE + QUEUE_THLD_CTRL, pat_b)  # instance 1
    a = await helper.read(CTRL_BASE + QUEUE_THLD_CTRL)
    b = await helper.read(TGT_BASE + QUEUE_THLD_CTRL)
    tb.log.info(f"instance0 = 0x{a:08X}, instance1 = 0x{b:08X}")
    assert a == pat_a, f"instance0 wrong: 0x{a:08X} != 0x{pat_a:08X}"
    assert b == pat_b, f"instance1 disturbed/decode leak: 0x{b:08X} != 0x{pat_b:08X}"

    # Swap to prove instance 1 is independently writable and isolated
    await helper.write(CTRL_BASE + QUEUE_THLD_CTRL, pat_b)  # instance 0
    await helper.write(TGT_BASE + QUEUE_THLD_CTRL, pat_a)  # instance 1
    a2 = await helper.read(CTRL_BASE + QUEUE_THLD_CTRL)
    b2 = await helper.read(TGT_BASE + QUEUE_THLD_CTRL)
    tb.log.info(f"after swap: instance0 = 0x{a2:08X}, instance1 = 0x{b2:08X}")
    assert a2 == pat_b, f"instance0 swap wrong: 0x{a2:08X} != 0x{pat_b:08X}"
    assert b2 == pat_a, f"instance1 swap wrong: 0x{b2:08X} != 0x{pat_a:08X}"

    # --- Directional leak checks: victim written FIRST, aggressor SECOND ---
    # Writing instance 0 then instance 1 hides a 0->1 leak: the instance-1 write
    # overwrites the leaked value before the read samples it. Writing the victim
    # first makes each direction observable.

    # Direction A: does writing instance 0 disturb instance 1?
    await helper.write(TGT_BASE + QUEUE_THLD_CTRL, pat_a)  # victim first
    await helper.write(CTRL_BASE + QUEUE_THLD_CTRL, pat_b)  # aggressor second
    b3 = await helper.read(TGT_BASE + QUEUE_THLD_CTRL)
    tb.log.info(f"leak check 0->1: instance1 = 0x{b3:08X} (expect 0x{pat_a:08X})")
    assert b3 == pat_a, f"instance-0 write leaked into instance 1: 0x{b3:08X} != 0x{pat_a:08X}"

    # Direction B: does writing instance 1 disturb instance 0?
    await helper.write(CTRL_BASE + QUEUE_THLD_CTRL, pat_a)  # victim first
    await helper.write(TGT_BASE + QUEUE_THLD_CTRL, pat_b)  # aggressor second
    a3 = await helper.read(CTRL_BASE + QUEUE_THLD_CTRL)
    tb.log.info(f"leak check 1->0: instance0 = 0x{a3:08X} (expect 0x{pat_a:08X})")
    assert a3 == pat_a, f"instance-1 write leaked into instance 0: 0x{a3:08X} != 0x{pat_a:08X}"

    tb.log.info(f"Multi-instance independence verified (seed=0x{r.seed:08X})")
