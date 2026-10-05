# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C `INTR_ENABLE` as an output mask.

The I2C block carries the OpenTitan interrupt registers, whose contract the
OpenTitan comportability specification states: `INTR_ENABLE` "enables/masks
the output of INTR_STATE to create the wired interrupt signal", "the contents
of the INTR_STATE register are not qualified by INTR_ENABLE, but rather show
the raw state of all latched hardware interrupt events", an Event interrupt
"can only be cleared by an acknowledgement from the handler (ack is a W1C
operation to INTR_STATE)", and a Status interrupt follows its input with
`INTR_STATE` read-only. `i2c.rdl` declares the same per field: an Event
source is `woclr` in `INTR_STATE` with a `singlepulse` `INTR_TEST` field, a
Status source is `sw = r` in `INTR_STATE` with a plain `rw` `INTR_TEST` field
that "releases" it when written back to 0. Two consequences follow, both
scored here and both measured before either is allowed to raise:

* **Held.** Clearing `INTR_ENABLE` releases `irq_o` while `INTR_STATE` keeps
  the bit; only a W1C clears the state.
* **Kept.** An event arriving while `INTR_ENABLE` is 0 is latched, so enabling
  later fires it and an `INTR_STATE` poll finds it.

`CMD_COMPLETE` is the vehicle. `INTR_TEST` is `sw = w` with `singlepulse`
(`i2c.rdl`), so a write is a one-cycle event on the same line as the real
event -- no bus traffic and no target model.

Observation is `tb_i2c_irq[0]`, instance 0's bit of the three I2C peripheral
interrupts (`hw/ip/i2c/doc/index.adoc` routes `i2c_irq_o` to peripheral
interrupts 23 to 25). That bit carries only this I2C instance, so there is no
sibling source to exclude -- but it is still required to read 0 before the run
starts, so a stuck-high line from a previous phase cannot be read as this
stimulus.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_contract

_I2C0 = 0

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

I2C_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", _I2C0)
I2C_INTR_ENABLE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", _I2C0)
I2C_INTR_TEST = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_TEST_BASE_ADDR", _I2C0)

_I2C_H = Path(__file__).resolve().parents[6] / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"
CMD_COMPLETE_STATE = _field_mask(_I2C_H, "I2C__INTR_STATE__CMD_COMPLETE_bm")
CMD_COMPLETE_ENABLE = _field_mask(_I2C_H, "I2C__INTR_ENABLE__CMD_COMPLETE_bm")
CMD_COMPLETE_TEST = _field_mask(_I2C_H, "I2C__INTR_TEST__CMD_COMPLETE_bm")

# The interrupt sources, split as the RDL declares them: an Event source has a
# write-only (`singlepulse`) `INTR_TEST` field and a write-one-to-clear
# `INTR_STATE` field, so one write raises it and only a W1C clears it; a Status
# source has a read-write `INTR_TEST` field and a read-only `INTR_STATE` field,
# so it follows that field and is released by writing it back to 0. The split
# is read from the generated IP-XACT export of `i2c.rdl`, and both registers
# must agree on every field.
_INTR_TEST_CONTRACT = rdl_contract(f"smc_i2c_wrap/i2c[{_I2C0}]/INTR_TEST")
_INTR_STATE_CONTRACT = rdl_contract(f"smc_i2c_wrap/i2c[{_I2C0}]/INTR_STATE")


def _source_split() -> tuple[tuple[str, ...], tuple[str, ...]]:
    state_by_name = {field.name: field for field in _INTR_STATE_CONTRACT.fields}
    latched: list[str] = []
    level: list[str] = []
    for test in _INTR_TEST_CONTRACT.fields:
        state = state_by_name.get(test.name)
        assert state is not None, f"INTR_STATE declares no field {test.name}"
        if test.access == "write-only":
            assert state.modified_write == "oneToClear", (
                f"{test.name}: INTR_TEST is write-only but INTR_STATE is not W1C "
                f"({state.access}, {state.modified_write})"
            )
            latched.append(test.name)
        else:
            assert test.access == "read-write" and state.access == "read-only", (
                f"{test.name}: INTR_TEST {test.access} with INTR_STATE {state.access} is "
                f"neither the Event nor the Status shape"
            )
            level.append(test.name)
    assert latched and level, f"the RDL split has no {'Event' if not latched else 'Status'} source"
    return tuple(latched), tuple(level)


_LATCHED_SOURCES, _LEVEL_SOURCES = _source_split()
# Every source must reach the output on its own. A source the bench holds
# asserted cannot be swept from a measured clear, so it is reported and
# skipped; the sweep still has to carry most of the map.
_MIN_SWEPT_SOURCES = 16

# The IRQ crosses smc_peripherals_cdc's flop plus a synchroniser, so a sample
# taken immediately after a CSR write would read the pre-write value. Bounded:
# expiry is a failure and reports the last value seen.
_IRQ_BOUND = 512
_HOLD = 32


class smc_i2c_intr_mask_test_seq(SmcCsrSeq):
    """INTR_ENABLE must mask the I2C interrupt output, not its set path."""

    def __init__(self, name: str = "smc_i2c_intr_mask_test_seq") -> None:
        super().__init__(name)

    def _irq(self, dut) -> int:
        sig = dut.tb_i2c_irq.value
        assert sig.is_resolvable, "tb_i2c_irq is X/Z"
        return (int(sig) >> _I2C0) & 0x1

    async def _wait_irq(self, dut, want: int, label: str) -> int:
        got = self._irq(dut)
        for _ in range(_IRQ_BOUND):
            got = self._irq(dut)
            if got == want:
                return got
            await ClockCycles(dut.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: tb_i2c_irq[{_I2C0}] still {got}, expected {want}, after "
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
            f"{label}: tb_i2c_irq[{_I2C0}] left {want} after {broke[0]} of "
            f"{_HOLD} hold cycles (read {broke[1]})"
        )

    async def _sweep_source(self, dut, name: str, latched: bool) -> str | None:
        """Raise one source alone and require the output to follow it.

        Returns a failure description, or None when the source rose with its
        own enable set and fell again when it was released.
        """
        state_bm = _field_mask(_I2C_H, f"I2C__INTR_STATE__{name}_bm")
        enable_bm = _field_mask(_I2C_H, f"I2C__INTR_ENABLE__{name}_bm")
        test_bm = _field_mask(_I2C_H, f"I2C__INTR_TEST__{name}_bm")

        # Only this source is enabled, so the output carries this term of the
        # reduction and no other.
        await self.csr_write(f"I2C_INTR_ENABLE_{name}", I2C_INTR_ENABLE, enable_bm)
        await self._wait_irq(dut, 0, f"{name} quiet")

        await self.csr_write(f"I2C_INTR_TEST_{name}", I2C_INTR_TEST, test_bm)
        raised = await self.csr_read(f"I2C_INTR_STATE_{name}", I2C_INTR_STATE)
        if (raised & state_bm) != state_bm:
            return (
                f"{name}: INTR_TEST 0x{test_bm:x} did not set INTR_STATE "
                f"(0x{raised:x}, wanted 0x{state_bm:x} set)"
            )
        try:
            await self._wait_irq(dut, 1, f"{name} rise")
        except AssertionError as exc:
            return f"{name}: {exc}"

        if latched:
            await self.csr_write(f"I2C_INTR_STATE_W1C_{name}", I2C_INTR_STATE, state_bm)
        else:
            await self.csr_write(f"I2C_INTR_TEST_OFF_{name}", I2C_INTR_TEST, 0)
        try:
            await self._wait_irq(dut, 0, f"{name} fall")
        except AssertionError as exc:
            return f"{name}: {exc}"
        cleared = await self.csr_read(f"I2C_INTR_STATE_CLR_{name}", I2C_INTR_STATE)
        if (cleared & state_bm) != 0:
            return (
                f"{name}: the output fell but INTR_STATE keeps the bit "
                f"(0x{cleared:x}); the release must clear the source, not the "
                f"output alone"
            )
        return None

    async def _clear_source(self, dut, name: str, latched: bool) -> bool:
        """True when the source reads clear, after a W1C if it needs one."""
        state_bm = _field_mask(_I2C_H, f"I2C__INTR_STATE__{name}_bm")
        state = await self.csr_read(f"I2C_INTR_STATE_PRE_{name}", I2C_INTR_STATE)
        if (state & state_bm) == 0:
            return True
        if latched:
            await self.csr_write(f"I2C_INTR_STATE_PREW1C_{name}", I2C_INTR_STATE, state_bm)
        else:
            await self.csr_write(f"I2C_INTR_TEST_PREOFF_{name}", I2C_INTR_TEST, 0)
        state = await self.csr_read(f"I2C_INTR_STATE_PRE2_{name}", I2C_INTR_STATE)
        return (state & state_bm) == 0

    async def body(self) -> None:
        dut = cocotb.top

        # The I2C register interface is clocked by the gated peripheral clock,
        # so an access with I2C_CG_EN set would not reach it.
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        pre_irq = await self._wait_irq(dut, 0, "quiet pre-check")
        state0 = await self.csr_read("I2C_INTR_STATE_PRE", I2C_INTR_STATE)
        if state0 & CMD_COMPLETE_STATE:
            await self.csr_write("I2C_INTR_STATE_W1C_PRE", I2C_INTR_STATE, CMD_COMPLETE_STATE)
            state0 = await self.csr_read("I2C_INTR_STATE_PRE2", I2C_INTR_STATE)
        assert (state0 & CMD_COMPLETE_STATE) == 0, (
            f"CMD_COMPLETE still set after W1C (INTR_STATE=0x{state0:x}); the "
            f"legs below could not then attribute a set bit to their own stimulus"
        )

        # ---- Arm: prove the whole path is alive -------------------------------
        # Without this, every assertion below is satisfied by a dead INTR_TEST,
        # a dead INTR_STATE, or a dead probe
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        await self.csr_write("I2C_INTR_ENABLE_SET", I2C_INTR_ENABLE, CMD_COMPLETE_ENABLE)
        await self.csr_write("I2C_INTR_TEST_ARM", I2C_INTR_TEST, CMD_COMPLETE_TEST)
        armed = await self.csr_read("I2C_INTR_STATE_ARMED", I2C_INTR_STATE)
        assert (armed & CMD_COMPLETE_STATE) == CMD_COMPLETE_STATE, (
            f"arm: INTR_TEST.CMD_COMPLETE written with INTR_ENABLE.CMD_COMPLETE "
            f"set did not latch INTR_STATE (0x{armed:x}); INTR_TEST is a "
            f"singlepulse on the same line as the real event, so this is the "
            f"stimulus the legs below depend on"
        )
        await self._wait_irq(dut, 1, "arm irq")
        await self._hold_irq(dut, 1, "arm irq hold")
        cocotb.log.info(
            "CHK-I2C-INTR-MASK-ARM: INTR_ENABLE=0x%x then a singlepulse "
            "INTR_TEST=0x%x latched INTR_STATE=0x%x and raised tb_i2c_irq[%d], "
            "held for %d cycles. The line read %d before any of this",
            CMD_COMPLETE_ENABLE,
            CMD_COMPLETE_TEST,
            armed,
            _I2C0,
            _HOLD,
            pre_irq,
        )

        # Both legs below are measured before either is allowed to raise, so a
        # failure in the first cannot hide the second.
        failures: list[str] = []

        # ---- Mask: clear INTR_ENABLE only; nothing else changes --------------
        await self.csr_write("I2C_INTR_ENABLE_CLR", I2C_INTR_ENABLE, 0)
        await ClockCycles(dut.clk_smc_i, _IRQ_BOUND)
        stuck = self._irq(dut)
        still = await self.csr_read("I2C_INTR_STATE_MASKED", I2C_INTR_STATE)
        # Held for the same span the arm leg holds the asserted level, so a
        # one-cycle sample or a glitch cannot read as a drop.
        broke = await self._held_irq(dut, 0) if stuck == 0 else None
        if stuck == 0 and broke is not None:
            failures.append(
                f"CHK-I2C-INTR-MASK-DEASSERT: tb_i2c_irq[{_I2C0}] dropped after "
                f"INTR_ENABLE -> 0x0 but returned to {broke[1]} at hold cycle "
                f"{broke[0]} of {_HOLD}, with no further stimulus"
            )
        elif stuck == 0 and (still & CMD_COMPLETE_STATE) != CMD_COMPLETE_STATE:
            # INTR_ENABLE masks the *output*. A DUT that cleared INTR_STATE
            # instead would also drop the line, and would satisfy this leg if
            # the state were not required to survive.
            failures.append(
                f"CHK-I2C-INTR-MASK-DEASSERT: the line dropped, but INTR_STATE "
                f"lost the bit too (0x{still:x}, wanted 0x{CMD_COMPLETE_STATE:x} "
                f"still set). INTR_ENABLE masks irq_o over a latched state, so "
                f"the state must survive the mask -- a drop that also clears "
                f"the state is a different mechanism"
            )
        elif stuck == 0:
            cocotb.log.info(
                "CHK-I2C-INTR-MASK-DEASSERT: INTR_ENABLE 0x%x -> 0x0 dropped "
                "tb_i2c_irq[%d] for %d held cycles with INTR_STATE still 0x%x",
                CMD_COMPLETE_ENABLE,
                _I2C0,
                _HOLD,
                still,
            )
        else:
            failures.append(
                f"CHK-I2C-INTR-MASK-DEASSERT: tb_i2c_irq[{_I2C0}] stayed {stuck} "
                f"after INTR_ENABLE 0x{CMD_COMPLETE_ENABLE:x} -> 0x0 with no "
                f"other stimulus (INTR_STATE still 0x{still:x}). INTR_ENABLE "
                f"masks irq_o, so the line must fall with the enable while "
                f"INTR_STATE keeps the bit"
            )

        # ---- Latch: an event while masked must not be dropped ----------------
        await self.csr_write("I2C_INTR_STATE_W1C", I2C_INTR_STATE, CMD_COMPLETE_STATE)
        cleared = await self.csr_read("I2C_INTR_STATE_CLEARED", I2C_INTR_STATE)
        assert (cleared & CMD_COMPLETE_STATE) == 0, (
            f"W1C did not clear CMD_COMPLETE (INTR_STATE=0x{cleared:x}); the "
            f"latch leg below could not then attribute a clear bit to the "
            f"masked pulse being dropped"
        )
        await self._wait_irq(dut, 0, "post-W1C irq")

        await self.csr_write("I2C_INTR_ENABLE_OFF", I2C_INTR_ENABLE, 0)
        await self.csr_write("I2C_INTR_TEST_MASKED", I2C_INTR_TEST, CMD_COMPLETE_TEST)
        await self.csr_write("I2C_INTR_ENABLE_LATE", I2C_INTR_ENABLE, CMD_COMPLETE_ENABLE)
        late = await self.csr_read("I2C_INTR_STATE_LATE", I2C_INTR_STATE)
        if (late & CMD_COMPLETE_STATE) == CMD_COMPLETE_STATE:
            cocotb.log.info(
                "CHK-I2C-INTR-MASK-LATCH: a singlepulse INTR_TEST issued with "
                "INTR_ENABLE=0 was latched and surfaced once the enable was set "
                "(INTR_STATE=0x%x)",
                late,
            )
        else:
            failures.append(
                f"CHK-I2C-INTR-MASK-LATCH: a singlepulse INTR_TEST issued with "
                f"INTR_ENABLE=0 was never latched -- INTR_STATE reads 0x{late:x} "
                f"after INTR_ENABLE was set back to 0x{CMD_COMPLETE_ENABLE:x}. "
                f"INTR_STATE latches an event whether or not the interrupt is "
                f"enabled, so the pulse must be held until a W1C and a later "
                f"enable must surface it"
            )

        await self.csr_write("I2C_INTR_STATE_W1C_POST", I2C_INTR_STATE, CMD_COMPLETE_STATE)

        # ---- Sweep: every source reaches the output through its own term ----
        # The legs above exercise one source. `irq_o` is a twenty-term
        # reduction, and a term is only proved by a source that is the sole
        # enabled one when the output moves.
        swept: list[str] = []
        held: list[str] = []
        for name, latched in [(n, True) for n in _LATCHED_SOURCES] + [
            (n, False) for n in _LEVEL_SOURCES
        ]:
            if not await self._clear_source(dut, name, latched):
                held.append(name)
                continue
            failure = await self._sweep_source(dut, name, latched)
            if failure is None:
                swept.append(name)
            else:
                failures.append(f"CHK-I2C-INTR-MASK-EVERY-SOURCE: {failure}")
        await self.csr_write("I2C_INTR_ENABLE_SWEPT_OFF", I2C_INTR_ENABLE, 0)
        if len(swept) < _MIN_SWEPT_SOURCES:
            failures.append(
                f"CHK-I2C-INTR-MASK-EVERY-SOURCE: only {len(swept)} of "
                f"{len(_LATCHED_SOURCES) + len(_LEVEL_SOURCES)} sources were swept from a "
                f"measured clear, below the {_MIN_SWEPT_SOURCES} this leg requires "
                f"(held by the bench: {', '.join(held) or 'none'})"
            )
        elif not failures:
            cocotb.log.info(
                "CHK-I2C-INTR-MASK-EVERY-SOURCE: %d of %d interrupt sources each raised "
                "tb_i2c_irq[%d] as the only enabled source and released it again: %s "
                "(held asserted by the bench and skipped: %s)",
                len(swept),
                len(_LATCHED_SOURCES) + len(_LEVEL_SOURCES),
                _I2C0,
                ", ".join(swept),
                ", ".join(held) or "none",
            )

        await self.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        assert not failures, "\n".join(failures)
