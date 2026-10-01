# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO external interrupt VIP helpers for SMC OSS tests.

Caller: ``smc_gpio_irq_active_test``, which runs ``smc_gpio_irq_active_test_seq``
first, programming GPIO0 as RX + interrupt_enable + interrupt_type=active-low
level (DATA_CTRL field bits sourced from generated ``gpio_intf.h``).

Public interface:

* :func:`check_gpio0_active_low_irq` -- the full three-leg proof; drives the pad
  and releases it before returning.
* :func:`await_gpio_irq_level` -- the bounded assert-and-hold poll the three-leg
  proof is built from, published for callers that need the pad left *held* while
  they sample something else inside the asserted window (the IRQ positive
  control in ``smc_5agent_observability_test_seq``); the caller owns pad drive
  and release (`[REUSE-AND-LAYERING]`).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

# Liveness bound on the pad -> tb_gpio_irq_any path, in clk_smc_i cycles. No
# published SPEC latency exists for this aggregate, so this is a generous
# upper bound whose expiry is a FAILURE -- it is not a settle delay and the
# check never samples "after N cycles", it samples every cycle until the exact
# expected level appears ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).
_IRQ_BOUND_CYCLES = 64
# interrupt_type=active-low is a *level* type, so once the expected level is
# reached it must persist while the pad is held. Re-checking it for a few
# cycles rejects a one-cycle glitch that merely brushed the expected value.
_IRQ_HOLD_CYCLES = 4


def _irq_level(dut) -> int:
    """X-aware read of ``tb_gpio_irq_any``.

    The aggregate is a registered DUT output that is out of reset by the time
    the caller's CSR sequence has completed, so X/Z here is a defect, not a
    don't-care: fail with a diagnostic instead of letting ``int()`` resolve it
    arbitrarily ([X-AWARE-CHECK]).
    """
    raw = dut.tb_gpio_irq_any.value
    assert raw.is_resolvable, f"tb_gpio_irq_any is not resolvable (X/Z): {raw}"
    return int(raw)


async def await_gpio_irq_level(dut, expected: int, label: str) -> int:
    """Bounded poll until ``tb_gpio_irq_any == expected``, then hold-verify it.

    Assert-and-hold, caller-releases: this helper only *observes*. It never
    drives or releases ``tb_gpio_ext_drive_*``, so the caller may keep the pad
    held and sample other observables inside the asserted window.

    Returns the number of clk_smc_i cycles the level took to appear. Raises on
    bound expiry with the last observed state (`[TIMEOUT-MUST-FAIL]`), and on
    any X/Z seen while polling (`[X-AWARE-CHECK]`).
    """
    clk = dut.clk_smc_i
    last = None
    for cycle in range(1, _IRQ_BOUND_CYCLES + 1):
        await ClockCycles(clk, 1)
        last = _irq_level(dut)
        if last == expected:
            for hold in range(1, _IRQ_HOLD_CYCLES + 1):
                await ClockCycles(clk, 1)
                held = _irq_level(dut)
                assert held == expected, (
                    f"{label}: tb_gpio_irq_any reached {expected} after "
                    f"{cycle} clk_smc_i cycles but did not hold it -- became "
                    f"{held} {hold} cycle(s) later while the pad was still held "
                    f"(active-low level interrupt must be stable)"
                )
            return cycle
    raise AssertionError(
        f"{label}: tb_gpio_irq_any never reached {expected} within "
        f"{_IRQ_BOUND_CYCLES} clk_smc_i cycles (last observed {last})"
    )


async def check_gpio0_active_low_irq() -> None:
    """Drive GPIO0 externally and verify the GPIO interrupt aggregate.

    Three exact legs, each proven by a bounded poll on the real observable:

    * pad high  -> tb_gpio_irq_any == 0 (active-low level not satisfied)
    * pad low   -> tb_gpio_irq_any == 1
    * pad high  -> tb_gpio_irq_any == 0 again

    The two idle-zero legs are negative checks that a stuck-at-0 or mis-bound
    aggregate would also pass; the assert leg in the middle is their positive
    control -- the same probe is proven able to read 1 in the same run
    ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    """
    dut = cocotb.top

    dut.tb_gpio_ext_drive_en.value = 0x1
    dut.tb_gpio_ext_drive_value.value = 0x1
    cycles = await await_gpio_irq_level(dut, 0, "gpio0_pad_high_idle")
    cocotb.log.info(
        "CHK-GPIO-IRQ-ACTIVE-LOW-IDLE: pad held 1 -> tb_gpio_irq_any==0 after "
        "%d clk_smc_i cycles, held %d",
        cycles,
        _IRQ_HOLD_CYCLES,
    )

    dut.tb_gpio_ext_drive_value.value = 0x0
    cycles = await await_gpio_irq_level(dut, 1, "gpio0_pad_low_assert")
    cocotb.log.info(
        "CHK-GPIO-IRQ-ACTIVE-LOW-ASSERT: pad 1->0 asserted tb_gpio_irq_any==1 "
        "after %d clk_smc_i cycles, held %d",
        cycles,
        _IRQ_HOLD_CYCLES,
    )

    dut.tb_gpio_ext_drive_value.value = 0x1
    cycles = await await_gpio_irq_level(dut, 0, "gpio0_pad_high_clear")
    cocotb.log.info(
        "CHK-GPIO-IRQ-ACTIVE-LOW-CLEAR: pad 0->1 cleared tb_gpio_irq_any==0 "
        "after %d clk_smc_i cycles, held %d",
        cycles,
        _IRQ_HOLD_CYCLES,
    )

    dut.tb_gpio_ext_drive_en.value = 0x0
    cocotb.log.info(
        "CHK-GPIO-IRQ-ACTIVE-LOW: all three exact tb_gpio_irq_any legs "
        "(0 -> 1 -> 0) passed under external GPIO0 pad drive"
    )
