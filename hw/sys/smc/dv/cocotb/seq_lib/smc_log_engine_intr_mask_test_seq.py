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

Engines 1-3. After the engine-0 legs, the log engines of UART1-3 are taken in
turn with INTR_ENABLE=0: INTR_TEST=0x01 then 0x10 must read back 0x01 then
0x11 on the stimulated engine only, a written 0x11 clears both and nothing
returns within 64 cycles. Each bit is then enabled, forced, masked and cleared
while `tb_uart_irq_combined` is sampled; the line levels are logged, not
compared, because no pinned source states the combining function of the
instance line (SF-001). A real fetch error comes from `LOG_REGION_ADDR` at the
refusing address `smc_log_engine_fetch_error_test` uses, with the UART in
loopback so the write side can drain; it must latch LOG_FETCH_ERR alone. The
write port reaches only the wrapper's own UART, so LOG_WRITE_ERR is set
through INTR_TEST=0x10 (SF-039), and the two bits clear one written 1 at a
time. A last erroring fetch with only INTR_ENABLE.LOG_FETCH_ERR set on the
stimulated engine logs the line before submission, while latched and after
the clear.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import UART_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_fetch_error_test_seq import REFUSING_ADDR
from .smc_log_engine_utils import (
    CTRL_EN,
    LOG_CTRL_PATH,
    LOG_CTRL_PY,
    LOG_LEN,
    THR_OFFSET,
    WRAP_STRIDE_SYMBOL,
    arm_uart,
    engine_reg,
    log_engine_u32,
    restore_uart,
    uart_base,
    uart_reg,
)
from .smc_regblock_field_sweep_utils import array_reg_instances

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
FETCH_ERR_STATUS = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__INTR_STATUS__LOG_FETCH_ERR_bm")
FETCH_ERR_ENABLE = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__INTR_ENABLE__LOG_FETCH_ERR_bm")
FETCH_ERR_TEST = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__INTR_TEST__LOG_FETCH_ERR_bm")

# The IRQ crosses smc_peripherals_cdc's flop plus a synchroniser, so a sample
# taken immediately after a CSR write would read the pre-write value. Bounded:
# expiry is a failure and reports the last value seen.
_IRQ_BOUND = 512
_HOLD = 32

# Engines 1-3 legs (contract SMC_LOG_ENGINE_INTR_MASK revision 2).
_ENGINES = (1, 2, 3)
STATUS_FETCH = log_engine_u32("LOG_ENGINE__INTR_STATUS__LOG_FETCH_ERR_bm")
STATUS_WRITE = log_engine_u32("LOG_ENGINE__INTR_STATUS__LOG_WRITE_ERR_bm")
STATUS_BOTH = STATUS_FETCH | STATUS_WRITE
TEST_FETCH = log_engine_u32("LOG_ENGINE__INTR_TEST__LOG_FETCH_ERR_bm")
TEST_WRITE = log_engine_u32("LOG_ENGINE__INTR_TEST__LOG_WRITE_ERR_bm")
ENABLE_FETCH = log_engine_u32("LOG_ENGINE__INTR_ENABLE__LOG_FETCH_ERR_bm")
ENABLE_WRITE = log_engine_u32("LOG_ENGINE__INTR_ENABLE__LOG_WRITE_ERR_bm")
# (INTR_ENABLE bit, INTR_TEST bit, INTR_STATUS bit) per interrupt.
_BITS = (
    ("LOG_FETCH_ERR", ENABLE_FETCH, TEST_FETCH, STATUS_FETCH),
    ("LOG_WRITE_ERR", ENABLE_WRITE, TEST_WRITE, STATUS_WRITE),
)
_ERR_REGION_SIZE = 0x80
_ERR_LOG_BYTES = 8
_REREAD_CYCLES = 64
_SAMPLE_GAP = 64
_QUIET_BOUND = 512
_POLL_LIMIT = 400
_POLL_CYCLES = 50
_TERMS = (
    "BRINGUP",
    "LOGENG13_TEST_FORCE",
    "LOGENG13_LINE_MASK",
    "LOGENG13_FETCH_ERR_LATCH",
    "LOGENG13_WRITE_ERR_TEST",
    "LOGENG13_LINE_REAL",
)


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

    async def _engine0_legs(self) -> None:
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

    # ---- Engines 1-3 ------------------------------------------------------

    def _line_vec(self) -> str:
        """tb_uart_irq_combined[3:0] as a binary string; X/Z is logged, not compared."""
        return str(cocotb.top.tb_uart_irq_combined.value)

    async def _sample_line(self) -> str:
        """Two samples of tb_uart_irq_combined[3:0], _SAMPLE_GAP clk_smc_i cycles apart."""
        first = self._line_vec()
        await ClockCycles(cocotb.top.clk_smc_i, _SAMPLE_GAP)
        second = self._line_vec()
        self._wait_last["line_sample"] = f"{first}/{second}"
        return f"{first}/{second}"

    def _fence(self, term: str, checkers: tuple[str, ...]) -> None:
        missing = [c for c in checkers if c not in self._chk_printed]
        assert not missing, f"fence {term}: checker lines {missing} not printed"
        now = get_sim_time("ns")
        assert not self._stamps or now > self._stamps[-1][1], (
            f"fence {term} at {now} ns is not later than {self._stamps[-1]}"
        )
        self._stamps.append((term, now))

    def _chk(self, token: str, text: str) -> None:
        cocotb.log.info("%s: %s", token, text)
        self._chk_printed.append(token)

    async def _status(self, label: str, n: int) -> int:
        return await self.csr_read(label, engine_reg(n, "INTR_STATUS"))

    async def _others_zero(self, label: str, n: int) -> None:
        for m in _ENGINES:
            if m == n:
                continue
            got = await self._status(f"{label}_E{m}", m)
            assert got == 0, (
                f"{label}: engine {m} INTR_STATUS=0x{got:x} while only engine {n} was "
                f"stimulated; it must read 0x0"
            )

    async def _others_hold(self, label: str, n: int, latched: set[int], bit: int) -> None:
        """Other engines read `bit` if their own erroring fetch latched it, else 0x0."""
        for m in _ENGINES:
            if m == n:
                continue
            want = bit if m in latched else 0
            got = await self._status(f"{label}_E{m}", m)
            assert got == want, (
                f"{label}: engine {m} INTR_STATUS=0x{got:x} while engine {n} was stimulated; "
                f"expected 0x{want:x} from its own history"
            )

    async def _expect_status(self, label: str, n: int, want: int, why: str) -> int:
        got = await self._status(label, n)
        assert got == want, f"{label}: engine {n} INTR_STATUS=0x{got:x}, expected 0x{want:x} {why}"
        return got

    async def _poll_quiet_lines(self) -> str:
        last = self._line_vec()
        for _ in range(_QUIET_BOUND):
            last = self._line_vec()
            raw = cocotb.top.tb_uart_irq_combined.value
            if raw.is_resolvable and (int(raw) & 0xE) == 0:
                self._wait_last["quiet_lines"] = last
                return last
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._wait_last["quiet_lines"] = last
        raise AssertionError(
            f"S1: tb_uart_irq_combined[3:1] not 0b000 after {_QUIET_BOUND} clk_smc_i cycles "
            f"(last tb_uart_irq_combined={last})"
        )

    async def _poll_len_clear(self, label: str, n: int, addr: int) -> None:
        remaining = None
        for _ in range(_POLL_LIMIT):
            remaining = (await self.csr_read(f"{label}_LEN", addr)) & LOG_LEN
            if remaining == 0:
                self._wait_last["log_len_clear"] = f"E{n}=0"
                return
            await ClockCycles(cocotb.top.clk_smc_i, _POLL_CYCLES)
        self._wait_last["log_len_clear"] = f"E{n}={remaining}"
        raise AssertionError(
            f"{label}: engine {n} LOG_CTRL[0].LOG_LEN still {remaining} after "
            f"{_POLL_LIMIT}x{_POLL_CYCLES} clk_smc_i cycles"
        )

    async def _poll_status_bit(self, label: str, n: int, bit: int) -> int:
        status = 0
        for _ in range(_POLL_LIMIT):
            status = await self._status(f"{label}_POLL", n)
            if status & bit:
                self._wait_last["status_set"] = f"E{n}=0x{status:x}"
                return status
            await ClockCycles(cocotb.top.clk_smc_i, _POLL_CYCLES)
        self._wait_last["status_set"] = f"E{n}=0x{status:x}"
        raise AssertionError(
            f"{label}: engine {n} INTR_STATUS never showed 0x{bit:x} within "
            f"{_POLL_LIMIT}x{_POLL_CYCLES} clk_smc_i cycles (last 0x{status:x})"
        )

    async def _submit_fetch_error(self, label: str, n: int) -> int:
        """Program engine n for one log from the refusing address and submit it."""
        element = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, n)[0]
        await self.csr_write(f"{label}_OFF", engine_reg(n, "CTRL"), 0)
        await self.csr_write(f"{label}_SIZE", engine_reg(n, "LOG_REGION_SIZE"), _ERR_REGION_SIZE)
        region = engine_reg(n, "LOG_REGION_ADDR")
        await self.csr_write(f"{label}_REGION_LO", region, REFUSING_ADDR & 0xFFFF_FFFF)
        await self.csr_write(f"{label}_REGION_HI", region + 4, REFUSING_ADDR >> 32)
        await self.csr_write(
            f"{label}_WRITE_ADDR", engine_reg(n, "LOG_WRITE_ADDR"), uart_base(n) + THR_OFFSET
        )
        await self.csr_write(f"{label}_ON", engine_reg(n, "CTRL"), CTRL_EN)
        await self.csr_write(f"{label}_GO", element.addr, _ERR_LOG_BYTES)
        return element.addr

    async def _engines13_legs(self) -> None:
        dut = cocotb.top
        self._chk_printed: list[str] = []
        self._stamps: list[tuple[str, float]] = []
        self._wait_last: dict[str, str] = {}

        # ---- S1: bring-up --------------------------------------------------
        cg = await self.csr_read("E13_UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("E13_UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        for n in _ENGINES:
            await self.csr_write(f"E{n}_IER_OFF", uart_reg(n, "IER"), 0)
            await self.csr_write(f"E{n}_MCR_OFF", uart_reg(n, "MCR"), 0)
        for n in _ENGINES:
            await self._expect_status(f"E{n}_STATUS_RESET", n, 0, "at bring-up")
            en = await self.csr_read(f"E{n}_ENABLE_RESET", engine_reg(n, "INTR_ENABLE"))
            assert en == 0, f"S1: engine {n} INTR_ENABLE=0x{en:x}, expected 0x0 at bring-up"
        quiet = await self._poll_quiet_lines()
        self._fence("BRINGUP", ())

        # ---- S2/S3: INTR_TEST forcing with INTR_ENABLE=0 -------------------
        force_log = []
        for n in _ENGINES:
            await self.csr_write(f"E{n}_TF_TEST_FETCH", engine_reg(n, "INTR_TEST"), TEST_FETCH)
            a = await self._expect_status(
                f"E{n}_TF_AFTER_FETCH", n, STATUS_FETCH, "after INTR_TEST=0x01"
            )
            await self._others_zero(f"E{n}_TF_AFTER_FETCH", n)
            await self.csr_write(f"E{n}_TF_TEST_WRITE", engine_reg(n, "INTR_TEST"), TEST_WRITE)
            b = await self._expect_status(
                f"E{n}_TF_AFTER_WRITE", n, STATUS_BOTH, "after INTR_TEST=0x10"
            )
            await self._others_zero(f"E{n}_TF_AFTER_WRITE", n)
            await self.csr_write(f"E{n}_TF_W1C", engine_reg(n, "INTR_STATUS"), STATUS_BOTH)
            c = await self._expect_status(f"E{n}_TF_CLEARED", n, 0, "after the written 0x11")
            await ClockCycles(dut.clk_smc_i, _REREAD_CYCLES)
            d = await self._expect_status(
                f"E{n}_TF_REREAD", n, 0, f"{_REREAD_CYCLES} cycles after the written 0x11"
            )
            force_log.append(f"E{n} 0x{a:x}/0x{b:x}/0x{c:x}/0x{d:x}")
        self._chk(
            "CHK-LOGENG13-TEST-FORCE",
            "INTR_ENABLE=0x0; INTR_STATUS after INTR_TEST=0x01 / INTR_TEST=0x10 / written 0x11 / "
            f"{_REREAD_CYCLES}-cycle re-read: {'; '.join(force_log)}; the other two engines "
            "read 0x0 after every test write",
        )
        self._fence("LOGENG13_TEST_FORCE", ("CHK-LOGENG13-TEST-FORCE",))

        # ---- S4: line with the mask on / off / cleared (SF-001) ------------
        mask_log = []
        for n in _ENGINES:
            for name, enable, test, status in _BITS:
                await self.csr_write(f"E{n}_{name}_EN", engine_reg(n, "INTR_ENABLE"), enable)
                await self.csr_write(f"E{n}_{name}_TEST", engine_reg(n, "INTR_TEST"), test)
                on = await self._sample_line()
                await self.csr_write(f"E{n}_{name}_EN_OFF", engine_reg(n, "INTR_ENABLE"), 0)
                off = await self._sample_line()
                held = await self._expect_status(
                    f"E{n}_{name}_MASKED", n, status, "with INTR_ENABLE cleared"
                )
                await self.csr_write(f"E{n}_{name}_EN_ON", engine_reg(n, "INTR_ENABLE"), enable)
                await self.csr_write(f"E{n}_{name}_W1C", engine_reg(n, "INTR_STATUS"), status)
                cleared_line = await self._sample_line()
                cleared = await self._expect_status(
                    f"E{n}_{name}_CLEARED", n, 0, f"after the written 0x{status:x}"
                )
                await self.csr_write(f"E{n}_{name}_EN_END", engine_reg(n, "INTR_ENABLE"), 0)
                mask_log.append(
                    f"E{n} b=0x{status:x} status_masked=0x{held:x} status_cleared=0x{cleared:x} "
                    f"line[3:0] enabled={on} masked={off} cleared={cleared_line}"
                )
        self._chk(
            "CHK-LOGENG13-LINE-MASK",
            "LINKED-ISSUE SF-001 line levels measured, not compared; " + "; ".join(mask_log),
        )
        self._fence("LOGENG13_LINE_MASK", ("CHK-LOGENG13-LINE-MASK",))

        # ---- S5: real fetch error, INTR_TEST bit 4, partial W1C ------------
        for n in _ENGINES:
            await arm_uart(self, n)
            await self.csr_write(f"E{n}_FE_EN_OFF", engine_reg(n, "INTR_ENABLE"), 0)
        fetch_log, wtest_log, partial_log = [], [], []
        latched_set: set[int] = set()
        for n in _ENGINES:
            addr = await self._submit_fetch_error(f"E{n}_FE", n)
            await self._poll_len_clear(f"E{n}_FE", n, addr)
            latched = await self._expect_status(
                f"E{n}_FE_LATCHED", n, STATUS_FETCH, "after the erroring fetch, INTR_ENABLE=0x0"
            )
            latched_set.add(n)
            await self._others_hold(f"E{n}_FE_LATCHED", n, latched_set, STATUS_FETCH)
            await self.csr_write(f"E{n}_FE_STOP", engine_reg(n, "CTRL"), 0)
            fetch_log.append(f"E{n} 0x{latched:x}")
        self._chk(
            "CHK-LOGENG13-FETCH-ERR",
            f"LOG_REGION_ADDR=0x{REFUSING_ADDR:x} (refusing), LOG_REGION_SIZE=0x{_ERR_REGION_SIZE:x}, "
            f"LOG_CTRL[0].LOG_LEN={_ERR_LOG_BYTES} returned to 0, INTR_ENABLE=0x0; INTR_STATUS "
            f"{'; '.join(fetch_log)}; each other engine read 0x01 if its own fetch had erred, else 0x0",
        )
        self._fence("LOGENG13_FETCH_ERR_LATCH", ("CHK-LOGENG13-FETCH-ERR",))
        for n in _ENGINES:
            await self.csr_write(f"E{n}_WT_TEST_WRITE", engine_reg(n, "INTR_TEST"), TEST_WRITE)
            both = await self._expect_status(
                f"E{n}_WT_BOTH", n, STATUS_BOTH, "with the fetch error latched and INTR_TEST=0x10"
            )
            await self.csr_write(f"E{n}_WT_W1C_WRITE", engine_reg(n, "INTR_STATUS"), STATUS_WRITE)
            after_w = await self._expect_status(
                f"E{n}_WT_AFTER_W1C_WRITE", n, STATUS_FETCH, "after the written 0x10"
            )
            await self.csr_write(f"E{n}_WT_W1C_FETCH", engine_reg(n, "INTR_STATUS"), STATUS_FETCH)
            after_f = await self._expect_status(
                f"E{n}_WT_AFTER_W1C_FETCH", n, 0, "after the written 0x01"
            )
            latched_set.discard(n)
            await self._others_hold(f"E{n}_WT_CLEARED", n, latched_set, STATUS_FETCH)
            wtest_log.append(f"E{n} bit4 {(both >> 4) & 1}->{(after_w >> 4) & 1}")
            partial_log.append(f"E{n} 0x{both:x}->0x{after_w:x}->0x{after_f:x}")
        self._chk(
            "CHK-LOGENG13-WRITE-ERR-TEST",
            "INTR_TEST=0x10 with INTR_ENABLE=0x0 set LOG_WRITE_ERR and the written 0x10 cleared "
            f"it: {'; '.join(wtest_log)}; a real write-port error is NOT-REACHABLE-AT-THIS-LEVEL "
            "(SF-039)",
        )
        self._chk(
            "CHK-LOGENG13-PARTIAL-W1C",
            "real fetch error + INTR_TEST=0x10, then written 0x10, then written 0x01: "
            + "; ".join(partial_log),
        )
        self._fence(
            "LOGENG13_WRITE_ERR_TEST", ("CHK-LOGENG13-WRITE-ERR-TEST", "CHK-LOGENG13-PARTIAL-W1C")
        )

        # ---- S6: enabled real fetch error and the line (SF-001) ------------
        real_log = []
        for n in _ENGINES:
            for m in _ENGINES:
                await self.csr_write(
                    f"E{n}_LR_EN_E{m}",
                    engine_reg(m, "INTR_ENABLE"),
                    ENABLE_FETCH if m == n else 0,
                )
            before = await self._sample_line()
            addr = await self._submit_fetch_error(f"E{n}_LR", n)
            await self._poll_status_bit(f"E{n}_LR", n, STATUS_FETCH)
            await self._poll_len_clear(f"E{n}_LR", n, addr)
            got = await self._expect_status(
                f"E{n}_LR_STATUS", n, STATUS_FETCH, "after the erroring fetch, INTR_ENABLE=0x01"
            )
            await self._others_zero(f"E{n}_LR_STATUS", n)
            raised = await self._sample_line()
            await self.csr_write(f"E{n}_LR_W1C", engine_reg(n, "INTR_STATUS"), STATUS_FETCH)
            cleared = await self._expect_status(f"E{n}_LR_CLEARED", n, 0, "after the written 0x01")
            after = await self._sample_line()
            await self.csr_write(f"E{n}_LR_STOP", engine_reg(n, "CTRL"), 0)
            await self.csr_write(f"E{n}_LR_EN_OFF", engine_reg(n, "INTR_ENABLE"), 0)
            real_log.append(
                f"E{n} status=0x{got:x}->0x{cleared:x} line[3:0] before_submit={before} "
                f"latched={raised} after_w1c={after}"
            )
        self._chk(
            "CHK-LOGENG13-LINE-REAL",
            "LINKED-ISSUE SF-001 line levels measured, not compared; INTR_ENABLE=0x01 on the "
            "stimulated engine only, others read INTR_STATUS=0x0; " + "; ".join(real_log),
        )
        self._fence("LOGENG13_LINE_REAL", ("CHK-LOGENG13-LINE-REAL",))

        for n in _ENGINES:
            await self.csr_write(f"E{n}_WRITE_ADDR_CLR", engine_reg(n, "LOG_WRITE_ADDR"), 0)
            await self.csr_write(f"E{n}_REGION_SIZE_CLR", engine_reg(n, "LOG_REGION_SIZE"), 0)
            region = engine_reg(n, "LOG_REGION_ADDR")
            await self.csr_write(f"E{n}_REGION_LO_CLR", region, 0)
            await self.csr_write(f"E{n}_REGION_HI_CLR", region + 4, 0)
            await restore_uart(self, n)
        await self.csr_write("E13_UART_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        waits = (
            ("quiet_lines", f"{_QUIET_BOUND}clk_smc_i", self._wait_last.get("quiet_lines", quiet)),
            (
                "log_len_clear",
                f"{_POLL_LIMIT}x{_POLL_CYCLES}clk_smc_i",
                self._wait_last.get("log_len_clear", "-"),
            ),
            (
                "status_set",
                f"{_POLL_LIMIT}x{_POLL_CYCLES}clk_smc_i",
                self._wait_last.get("status_set", "-"),
            ),
            ("line_sample", f"2x{_SAMPLE_GAP}clk_smc_i", self._wait_last.get("line_sample", "-")),
            ("reread", f"{_REREAD_CYCLES}clk_smc_i", "INTR_STATUS=0x0"),
            ("engine0_irq", f"{_IRQ_BOUND}clk_smc_i", "reached"),
            ("sep_in_axi_access", "agent timeout", f"{self.accesses} accesses done"),
        )
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(waits)} bounded waits: "
            + " ".join(f"{w}={b} last={s}" for w, b, s in waits)
            + "; expiry raises AssertionError with the last state",
        )
        terms = tuple(t for t, _ in self._stamps)
        assert terms == _TERMS, f"fence terms {terms}, expected {_TERMS}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s",
            " < ".join(_TERMS),
            ",".join(f"{t}={ns}ns" for t, ns in self._stamps),
            ",".join(self._chk_printed),
        )

    async def body(self) -> None:
        await self._engine0_legs()
        await self._engines13_legs()
