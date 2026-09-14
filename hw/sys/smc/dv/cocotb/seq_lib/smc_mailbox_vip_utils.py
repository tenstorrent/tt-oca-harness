# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox IRQ-source VIP helpers for SMC OSS tests.

Callers: ``smc_mailbox_irq_test`` (mask 0x1), ``smc_mailbox_data_error_test``
(mask 0x2) and ``smc_mailbox_event_irq_test`` (mask 0x4). Each drives the
top-level ``tb_sep_mailbox_interrupts`` pins and observes the DUT-side
aggregate ``tb_mailbox_irq_any`` (``|peripheral_interrupts[7:0]``).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

# Liveness bound on the tb_sep_mailbox_interrupts -> tb_mailbox_irq_any path, in
# clk_smc_i cycles. No published SPEC latency exists for this aggregate, so this
# is a generous upper bound whose expiry is a FAILURE with the last observed
# state -- it is not a settle delay, and the check never samples "after N
# cycles": it samples every cycle until the exact expected level appears
# ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).
_IRQ_BOUND_CYCLES = 64
# The injected interrupt is a level, so once the expected level is reached it
# must persist while the pins are held. Re-checking rejects a one-cycle glitch
# that merely brushed the expected value.
_IRQ_HOLD_CYCLES = 4


def _mailbox_irq_level(dut) -> int:
    """X-aware read of ``tb_mailbox_irq_any``.

    The aggregate is a DUT interrupt output that is long out of reset by the
    time these helpers run, so X/Z here is a defect, not a don't-care: fail with
    a diagnostic on every leg instead of letting ``int()`` raise or resolve it
    arbitrarily ([X-AWARE-CHECK]).
    """
    raw = dut.tb_mailbox_irq_any.value
    assert raw.is_resolvable, f"tb_mailbox_irq_any is not resolvable (X/Z): {raw}"
    return int(raw)


async def _await_mailbox_irq_level(dut, expected: int, label: str) -> int:
    """Bounded poll until ``tb_mailbox_irq_any == expected``, then hold-verify.

    Returns the number of clk_smc_i cycles the level took to appear. Raises on
    bound expiry with the last observed state, and on any X/Z seen while
    polling.
    """
    clk = dut.clk_smc_i
    last = None
    for cycle in range(1, _IRQ_BOUND_CYCLES + 1):
        await ClockCycles(clk, 1)
        last = _mailbox_irq_level(dut)
        if last == expected:
            for hold in range(1, _IRQ_HOLD_CYCLES + 1):
                await ClockCycles(clk, 1)
                held = _mailbox_irq_level(dut)
                assert held == expected, (
                    f"{label}: tb_mailbox_irq_any reached {expected} after "
                    f"{cycle} clk_smc_i cycles but did not hold it -- became "
                    f"{held} {hold} cycle(s) later while the injection was "
                    f"unchanged (level interrupt must be stable)"
                )
            return cycle
    raise AssertionError(
        f"{label}: tb_mailbox_irq_any never reached {expected} within "
        f"{_IRQ_BOUND_CYCLES} clk_smc_i cycles (last observed {last})"
    )


async def check_mailbox_irq_source(mask: int = 0x1) -> None:
    """Inject SEP mailbox interrupts and verify the SMC IRQ aggregate.

    Three exact legs, each proven by a bounded poll on the real observable:

    * pins 0    -> tb_mailbox_irq_any == 0 (idle)
    * pins mask -> tb_mailbox_irq_any == 1
    * pins 0    -> tb_mailbox_irq_any == 0 again

    The two idle-zero legs are negative checks that a stuck-at-0 or mis-bound
    aggregate would also pass; the assert leg between them is their positive
    control -- the same probe is proven able to read 1 in the same run
    ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    """
    dut = cocotb.top

    dut.tb_sep_mailbox_interrupts.value = 0
    cycles = await _await_mailbox_irq_level(dut, 0, "mailbox_irq_idle")
    cocotb.log.info(
        "CHK-MAILBOX-IRQ-IDLE: interrupts held 0 -> tb_mailbox_irq_any==0 after "
        "%d clk_smc_i cycles, held %d",
        cycles,
        _IRQ_HOLD_CYCLES,
    )

    dut.tb_sep_mailbox_interrupts.value = mask
    cycles = await _await_mailbox_irq_level(dut, 1, "mailbox_irq_assert")
    cocotb.log.info(
        "CHK-MAILBOX-IRQ-ASSERT: interrupts 0->0x%02x asserted "
        "tb_mailbox_irq_any==1 after %d clk_smc_i cycles, held %d",
        mask,
        cycles,
        _IRQ_HOLD_CYCLES,
    )

    dut.tb_sep_mailbox_interrupts.value = 0
    cycles = await _await_mailbox_irq_level(dut, 0, "mailbox_irq_clear")
    cocotb.log.info(
        "CHK-MAILBOX-IRQ-CLEAR: interrupts 0x%02x->0 cleared "
        "tb_mailbox_irq_any==0 after %d clk_smc_i cycles, held %d",
        mask,
        cycles,
        _IRQ_HOLD_CYCLES,
    )
    cocotb.log.info(
        "CHK-MAILBOX-IRQ-SOURCE: all three exact tb_mailbox_irq_any legs "
        "(0 -> 1 -> 0) passed under mask=0x%02x SEP mailbox interrupt injection",
        mask,
    )
