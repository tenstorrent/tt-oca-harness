# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine `INTR_ENABLE` as an output mask.

`hw/ip/uart/log_engine/doc/architecture.adoc` (Errors and Interrupts):
"`INTR_STATUS.LOG_FETCH_ERR` (bit 0) and `LOG_WRITE_ERR` (bit 4) latch bus
response errors whether or not their interrupts are enabled. `INTR_ENABLE`
masks the corresponding contributions to `irq_o`. Write 1 to a status bit to
clear it; `INTR_TEST` can force either condition." `interface.adoc`: "`irq_o`
is the active-high OR of enabled, latched fetch and write error status."
`log_engine.rdl` declares the status fields `level intr` with `woclr`. Two
consequences follow, and this sequence scores both:

* **Held.** Clearing `INTR_ENABLE` releases `irq_o` while `INTR_STATUS` keeps
  the bit; only a W1C clears the status.
* **Kept.** An event that arrives while `INTR_ENABLE` is 0 is latched, so
  enabling later fires it and an `INTR_STATUS` poll finds it.

Both are measured before either is allowed to raise, so neither hides the
other.

Stimulus. `INTR_TEST` is `sw = w` with `singlepulse` (log_engine.rdl), so a
write is a one-cycle event on the same line as the real event and needs no bus
traffic or log region.

Observation. `irq_o` has no probe of its own. `hw/sys/smc/doc/interrupts.adoc`
(PLIC sources 274-277, "UART/Log Engine interrupt 0..3") routes the combined
UART IRQ, UART error and log-engine interrupt of each instance to
`peripheral_interrupts[21:18]`, one bit per UART instance, through the
peripheral clock-domain crossing. `tb_uart_irq_combined` exports that slice.
`tb_uart_irq_any` is *not* usable here: it is `|uart_interrupt`, the 16550 half
only, and carries no log-engine contribution at all.

Attribution. The bit is shared with the 16550 IRQ and the UART error line, so
this sequence requires instance 0's bit to read 0 before it starts and touches
no UART register other than the clock gate. A 1 later can only be the log
engine's.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import UART_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_UART0 = 0  # UART_LOG_ENGINE_WRAP idx

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

LOG_INTR_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR", _UART0
)
LOG_INTR_ENABLE = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR", _UART0
)
LOG_INTR_TEST = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_TEST_BASE_ADDR", _UART0
)

_LOG_ENGINE_H = (
    Path(__file__).resolve().parents[6]
    / "hw"
    / "ip"
    / "uart"
    / "log_engine"
    / "regs"
    / "gen"
    / "c"
    / "log_engine.h"
)
# One field is enough to make the point and keeps the stimulus unambiguous.
FETCH_ERR_STATUS = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__INTR_STATUS__LOG_FETCH_ERR_bm")
FETCH_ERR_ENABLE = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__INTR_ENABLE__LOG_FETCH_ERR_bm")
FETCH_ERR_TEST = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__INTR_TEST__LOG_FETCH_ERR_bm")

# The IRQ crosses smc_peripherals_cdc's flop plus a synchroniser, so a sample
# taken immediately after a CSR write would read the pre-write value. Bounded:
# expiry is a failure and reports the last value seen.
_IRQ_BOUND = 512
_HOLD = 32


class smc_log_engine_intr_mask_test_seq(SmcCsrSeq):
    """INTR_ENABLE must mask the log-engine interrupt output, not its set path."""

    def __init__(self, name: str = "smc_log_engine_intr_mask_test_seq") -> None:
        super().__init__(name)

    def _irq(self, dut) -> int:
        """Instance 0's bit of peripheral_interrupts[21:18]."""
        sig = dut.tb_uart_irq_combined.value
        assert sig.is_resolvable, "tb_uart_irq_combined is X/Z"
        return (int(sig) >> _UART0) & 0x1

    async def _wait_irq(self, dut, want: int, label: str) -> int:
        """Wait for the aggregate to reach `want`; expiry raises."""
        got = self._irq(dut)
        for _ in range(_IRQ_BOUND):
            got = self._irq(dut)
            if got == want:
                return got
            await ClockCycles(dut.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: tb_uart_irq_combined[0] still {got}, expected {want}, after "
            f"{_IRQ_BOUND} clk_smc_i cycles"
        )

    async def _held_irq(self, dut, want: int) -> tuple[int, int] | None:
        """First (cycle, value) at which the line left `want`, else None.

        Non-raising twin of `_hold_irq`, for the legs that collect their
        failures instead of raising at the first one.
        """
        for cycle in range(_HOLD):
            got = self._irq(dut)
            if got != want:
                return (cycle, got)
            await ClockCycles(dut.clk_smc_i, 1)
        return None

    async def _hold_irq(self, dut, want: int, label: str) -> None:
        broke = await self._held_irq(dut, want)
        assert broke is None, (
            f"{label}: tb_uart_irq_combined[0] left {want} after {broke[0]} of "
            f"{_HOLD} hold cycles (read {broke[1]})"
        )

    async def body(self) -> None:
        dut = cocotb.top

        # The log engine's register interface is clocked by the gated peripheral
        # clock, so an access with UART_CG_EN set would not reach it.
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)

        # Attribution precondition. tb_uart_irq_combined[0] also carries the 16550 IRQ
        # and the UART error line; if either were already asserted, nothing
        # below could be credited to the log engine.
        pre_irq = await self._wait_irq(dut, 0, "quiet pre-check")
        status0 = await self.csr_read("LOG_INTR_STATUS_PRE", LOG_INTR_STATUS)
        if status0 & FETCH_ERR_STATUS:
            await self.csr_write("LOG_INTR_STATUS_W1C_PRE", LOG_INTR_STATUS, FETCH_ERR_STATUS)
            status0 = await self.csr_read("LOG_INTR_STATUS_PRE2", LOG_INTR_STATUS)
        assert (status0 & FETCH_ERR_STATUS) == 0, (
            f"LOG_FETCH_ERR still set after W1C (INTR_STATUS=0x{status0:x}); the "
            f"legs below could not then attribute a set bit to their own stimulus"
        )

        # ---- Arm: prove the whole path is alive -------------------------------
        # Without this, every assertion below is satisfied by a dead INTR_TEST,
        # a dead INTR_STATUS, or a dead probe
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        await self.csr_write("LOG_INTR_ENABLE_SET", LOG_INTR_ENABLE, FETCH_ERR_ENABLE)
        await self.csr_write("LOG_INTR_TEST_ARM", LOG_INTR_TEST, FETCH_ERR_TEST)
        armed = await self.csr_read("LOG_INTR_STATUS_ARMED", LOG_INTR_STATUS)
        assert (armed & FETCH_ERR_STATUS) == FETCH_ERR_STATUS, (
            f"arm: INTR_TEST.LOG_FETCH_ERR written with INTR_ENABLE.LOG_FETCH_ERR "
            f"set did not latch INTR_STATUS (0x{armed:x}); INTR_TEST is a "
            f"singlepulse on the same line as the real event, so this is the "
            f"stimulus the legs below depend on"
        )
        await self._wait_irq(dut, 1, "arm irq")
        await self._hold_irq(dut, 1, "arm irq hold")
        cocotb.log.info(
            "CHK-LOG-ENGINE-INTR-MASK-ARM: INTR_ENABLE=0x%x then a singlepulse "
            "INTR_TEST=0x%x latched INTR_STATUS=0x%x and raised "
            "tb_uart_irq_combined[0], held for %d cycles. The aggregate read %d before "
            "any of this, and no UART register other than the clock gate was "
            "touched, so the 1 is the log engine's",
            FETCH_ERR_ENABLE,
            FETCH_ERR_TEST,
            armed,
            _HOLD,
            pre_irq,
        )

        # Both legs below are measured before either is allowed to raise, so a
        # failure in the first cannot hide the second.
        failures: list[str] = []

        # ---- Mask: clear INTR_ENABLE only; nothing else changes --------------
        await self.csr_write("LOG_INTR_ENABLE_CLR", LOG_INTR_ENABLE, 0)
        await ClockCycles(dut.clk_smc_i, _IRQ_BOUND)
        stuck = self._irq(dut)
        still = await self.csr_read("LOG_INTR_STATUS_MASKED", LOG_INTR_STATUS)
        # Held for the same span the arm leg holds the asserted level, so a
        # one-cycle sample or a glitch cannot read as a drop.
        broke = await self._held_irq(dut, 0) if stuck == 0 else None
        if stuck == 0 and broke is not None:
            failures.append(
                f"CHK-LOG-ENGINE-INTR-MASK-DEASSERT: tb_uart_irq_combined[0] "
                f"dropped after INTR_ENABLE -> 0x0 but returned to {broke[1]} "
                f"at hold cycle {broke[0]} of {_HOLD}, with no further stimulus"
            )
        elif stuck == 0 and (still & FETCH_ERR_STATUS) != FETCH_ERR_STATUS:
            # INTR_ENABLE masks the *output*. A DUT that cleared INTR_STATUS
            # instead would also drop the line, and would satisfy this leg if
            # the status were not required to survive.
            failures.append(
                f"CHK-LOG-ENGINE-INTR-MASK-DEASSERT: the line dropped, but "
                f"INTR_STATUS lost the bit too (0x{still:x}, wanted "
                f"0x{FETCH_ERR_STATUS:x} still set). INTR_ENABLE masks irq_o "
                f"over a latched status, so the status must survive the mask "
                f"-- a drop that also clears the status is a different "
                f"mechanism"
            )
        elif stuck == 0:
            cocotb.log.info(
                "CHK-LOG-ENGINE-INTR-MASK-DEASSERT: INTR_ENABLE 0x%x -> 0x0 "
                "dropped tb_uart_irq_combined[0] for %d held cycles with "
                "INTR_STATUS still 0x%x",
                FETCH_ERR_ENABLE,
                _HOLD,
                still,
            )
        else:
            failures.append(
                f"CHK-LOG-ENGINE-INTR-MASK-DEASSERT: tb_uart_irq_combined[0] "
                f"stayed {stuck} after INTR_ENABLE 0x{FETCH_ERR_ENABLE:x} -> 0x0 "
                f"with no other stimulus (INTR_STATUS still 0x{still:x}). "
                f"INTR_ENABLE masks irq_o, so the line must fall with the "
                f"enable while INTR_STATUS keeps the bit"
            )

        # ---- Latch: an event while masked must not be dropped ----------------
        # The W1C restores a known state, so this leg's own stimulus is the only
        # thing that can set the bit.
        await self.csr_write("LOG_INTR_STATUS_W1C", LOG_INTR_STATUS, FETCH_ERR_STATUS)
        cleared = await self.csr_read("LOG_INTR_STATUS_CLEARED", LOG_INTR_STATUS)
        assert (cleared & FETCH_ERR_STATUS) == 0, (
            f"W1C did not clear LOG_FETCH_ERR (INTR_STATUS=0x{cleared:x}); the "
            f"latch leg below could not then attribute a clear bit to the "
            f"masked pulse being dropped"
        )
        await self._wait_irq(dut, 0, "post-W1C irq")

        await self.csr_write("LOG_INTR_ENABLE_OFF", LOG_INTR_ENABLE, 0)
        await self.csr_write("LOG_INTR_TEST_MASKED", LOG_INTR_TEST, FETCH_ERR_TEST)
        await self.csr_write("LOG_INTR_ENABLE_LATE", LOG_INTR_ENABLE, FETCH_ERR_ENABLE)
        late = await self.csr_read("LOG_INTR_STATUS_LATE", LOG_INTR_STATUS)
        if (late & FETCH_ERR_STATUS) == FETCH_ERR_STATUS:
            cocotb.log.info(
                "CHK-LOG-ENGINE-INTR-MASK-LATCH: a singlepulse INTR_TEST issued "
                "with INTR_ENABLE=0 was latched and surfaced once the enable "
                "was set (INTR_STATUS=0x%x)",
                late,
            )
        else:
            failures.append(
                f"CHK-LOG-ENGINE-INTR-MASK-LATCH: a singlepulse INTR_TEST "
                f"issued with INTR_ENABLE=0 was never latched -- INTR_STATUS "
                f"reads 0x{late:x} after INTR_ENABLE was set back to "
                f"0x{FETCH_ERR_ENABLE:x}. INTR_STATUS latches an event whether "
                f"or not the interrupt is enabled, so the pulse must be held "
                f"until a W1C and a later enable must surface it"
            )

        await self.csr_write("LOG_INTR_STATUS_W1C_POST", LOG_INTR_STATUS, FETCH_ERR_STATUS)
        await self.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        assert not failures, "\n".join(failures)
