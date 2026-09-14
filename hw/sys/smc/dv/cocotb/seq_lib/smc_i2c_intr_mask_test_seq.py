# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C `INTR_ENABLE` placement: the enable gates the set path, not the output.

**Fails while `INTR_ENABLE` gates the INTR_STATE set path instead of masking
`irq_o`** (see below).

`hw/ip/i2c/rtl/i2c_core.sv` has this shape::

    :1000  assign reg_in_o.INTR_STATE.CMD_COMPLETE.next =
             (event_cmd_complete || cmd_complete_intr_test) &&
             cmd_complete_intr_en;              // enable gates the SET
    :981   assign irq_o = reg_out_i.INTR_STATE.intr || |{...intr_req};
                                                // output NOT gated

against `vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_intr_hw.sv:66`,
which latches unconditionally, and `:99`, which masks the output.

Two consequences, both scored here and both measured before either is allowed
to raise:

* **Stuck.** A bit latched while enabled keeps `irq_o` asserted after
  `INTR_ENABLE` is cleared; only a W1C releases it.
* **Lost.** An event arriving while `INTR_ENABLE` is 0 is never latched, so
  enabling later never fires it and `INTR_STATE` polling cannot find it. The
  more serious of the two.

`CMD_COMPLETE` is the vehicle. `INTR_TEST` is `sw = w` with `singlepulse`
(`i2c.rdl:312,336`), so a write is a one-cycle event on the same line as the
real event -- no bus traffic, no target model, and it exercises exactly the
path under test.

Observation is `tb_i2c_irq[0]`, instance 0's bit of
`peripheral_interrupts[25:23]` (`smc_peripherals.sv:1161`). That bit carries
only this I2C instance, so there is no sibling source to
exclude -- but it is still required to read 0 before the run starts, so a
stuck-high line from a previous phase cannot be read as this stimulus.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_I2C0 = 0

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

I2C_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", _I2C0)
I2C_INTR_ENABLE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", _I2C0)
I2C_INTR_TEST = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_TEST_BASE_ADDR", _I2C0)

_I2C_H = Path(__file__).resolve().parents[6] / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"
CMD_COMPLETE_STATE = _field_mask(_I2C_H, "I2C__INTR_STATE__CMD_COMPLETE_bm")
CMD_COMPLETE_ENABLE = _field_mask(_I2C_H, "I2C__INTR_ENABLE__CMD_COMPLETE_bm")
CMD_COMPLETE_TEST = _field_mask(_I2C_H, "I2C__INTR_TEST__CMD_COMPLETE_bm")

# The IRQ crosses smc_peripherals_cdc's flop plus a synchroniser, so a sample
# taken immediately after a CSR write would read the pre-write value. Bounded:
# expiry is a failure and reports the last value seen.
_IRQ_BOUND = 512
_HOLD = 32


class smc_i2c_intr_mask_test_seq(SmcCsrSeq):
    """INTR_ENABLE must mask the I2C interrupt output, not its set path."""

    def __init__(self, name: str = "smc_i2c_intr_mask_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

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
            f"set did not latch INTR_STATE (0x{armed:x}); i2c_core.sv:1000 is the "
            f"set path and INTR_TEST is singlepulse, so this is the stimulus the "
            f"legs below depend on"
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
        self.chk_seen.add("CHK-I2C-INTR-MASK-ARM")

        # Both symptoms are measured before either raises: raising at the first
        # would hide the second, and whichever is repaired first the other still
        # needs to be visible.
        failures: list[str] = []

        # ---- Stuck: clear INTR_ENABLE only; nothing else changes -------------
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
            # The claim is that the ENABLE masks the *output*. A repair that
            # cleared INTR_STATE instead would also drop the line, and would
            # satisfy this leg if the state were not required to survive.
            failures.append(
                f"CHK-I2C-INTR-MASK-DEASSERT: the line dropped, but INTR_STATE "
                f"lost the bit too (0x{still:x}, wanted 0x{CMD_COMPLETE_STATE:x} "
                f"still set). prim_intr_hw.sv:99 masks the output over a latched "
                f"state, so the state must survive the mask -- a drop that also "
                f"clears the state is a different mechanism than the one claimed"
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
                f"other stimulus (INTR_STATE still 0x{still:x}). i2c_core.sv:981 "
                f"drives irq_o from INTR_STATE.intr with no enable term, while "
                f"prim_intr_hw.sv:99 masks the output"
            )
        self.chk_seen.add("CHK-I2C-INTR-MASK-DEASSERT")

        # ---- Lost: an event while masked must not be dropped -----------------
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
                f"i2c_core.sv:1000 ANDs the event with the enable before the "
                f"flop, so the pulse is gone and no later enable or INTR_STATE "
                f"poll can recover it. prim_intr_hw.sv:66 latches "
                f"unconditionally for exactly this reason. This is the "
                f"more serious half: an interrupt is silently dropped rather "
                f"than spuriously held"
            )
        self.chk_seen.add("CHK-I2C-INTR-MASK-LATCH")

        await self.csr_write("I2C_INTR_STATE_W1C_POST", I2C_INTR_STATE, CMD_COMPLETE_STATE)
        await self.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        assert not failures, "\n".join(failures)
