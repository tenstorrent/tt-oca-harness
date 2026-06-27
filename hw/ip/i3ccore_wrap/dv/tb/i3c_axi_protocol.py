# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

"""
I3C AXI-Lite Protocol  (Test Plan #40)

Exercises AXI-Lite register access: a write/read-back round-trip to a known
read-write register, plus a second mapped read to confirm the bus completes.

Constrained-random: the written pattern is randomized (shared framework, seed
from +seed/SEED/default). QUEUE_THLD_CTRL's threshold fields clamp values to
<= 7, so the random pattern is generated with every byte in 0..7 (and non-zero)
to guarantee an exact read-back — the AXI round-trip is the scoreboard.

Note: uses QUEUE_THLD_CTRL @ 0x090, a confirmed RW register. The DAT region
(0x400+) is NOT used here — it is external 64-bit SRAM, not a plain 32-bit
scratch register, and an un-written entry reads X.
"""
import cocotb
from i3c_test_base import make_env, CTRL_BASE
from i3c_rand import RandMgr

QUEUE_THLD_CTRL = 0x090
HC_CONTROL = 0x004


def _rand_thld_pattern(r):
    """A 32-bit value with every byte in 0..7 (valid threshold fields) and != 0,
    so it round-trips through QUEUE_THLD_CTRL without field clamping."""
    while True:
        p = sum(r.randint(0, 7) << (8 * i) for i in range(4))
        if p != 0:
            return p


@cocotb.test(timeout_time=2000, timeout_unit='us')
async def test_axi_protocol(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    r = RandMgr(name="axi_protocol")          # seed logged; +seed/SEED override

    pattern = _rand_thld_pattern(r)
    # Mapped write / read-back round-trip
    await helper.write(CTRL_BASE + QUEUE_THLD_CTRL, pattern)
    val = await helper.read(CTRL_BASE + QUEUE_THLD_CTRL)
    tb.log.info(f"QUEUE_THLD_CTRL wrote 0x{pattern:08X} read-back 0x{val:08X}")
    assert val == pattern, f"mapped readback mismatch 0x{val:08X} != 0x{pattern:08X}"

    # A second mapped read completes (HC_CONTROL is always readable)
    hc = await helper.read(CTRL_BASE + HC_CONTROL)
    tb.log.info(f"HC_CONTROL = 0x{hc:08X} (bus completed)")

    tb.log.info(f"AXI-Lite protocol test complete (seed=0x{r.seed:08X})")
