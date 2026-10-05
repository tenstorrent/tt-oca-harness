# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Interrupt and event register cycles on every SMC I2C instance.

The I2C interrupt registers are the block's software-owned state that no bus
traffic is needed to drive, so this sequence takes every one of them on all
three instances while the controller and target stay disabled at their reset
configuration.

* INTR_ENABLE takes the generic half-register cycle.
* INTR_TEST takes that cycle over the fields the contract pins, and then a
  pulse leg for the fields the contract makes `write-only` and hardware-driven:
  a write of those raises the matching INTR_STATE events, and a write of the
  same mask back into INTR_STATE clears them, which is the `oneToClear`
  contract. INTR_ENABLE is back at its reset 0 by then, so the raised events do
  not reach the interrupt output.
* CONTROLLER_EVENTS and TARGET_EVENTS take a write of their whole declared mask
  and then a half-register write of it, each followed by a read. Both registers
  are `oneToClear` over fields only bus activity sets, so with no traffic on the
  bus the contract is that they read clear before and after: a write of 1 into a
  clear `oneToClear` field must not set it.
* TARGET_ACK_CTRL and ACQ_FIFO_NEXT_DATA are read against their RDL reset, under
  the STATUS word that shows the block idle with both FIFOs empty.

VAL is not read here. Its two fields are hardware-sampled and together cover the
whole word, so with no stimulus on the I2C lines this sequence has neither a
word it can predict nor a bit it could find wrong.

The `oneToClear` fields of CONTROLLER_EVENTS, TARGET_EVENTS and INTR_STATE that
no INTR_TEST field maps to are never observed set here: only a start, stop,
arbitration loss or timeout on the bus sets them, and this sequence drives no
bus traffic.
"""

from __future__ import annotations

import cocotb

from .smc_regblock_field_sweep_utils import RegInstance, SmcRegblockFieldSweepSeq, reg_instances

_I2C = "SMC_TOP_SMC_I2C_WRAP_I2C_"


def _spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_i2c_wrap/i2c/{register}",
        f"{_I2C}{register}_BASE_ADDR",
        f"{_I2C}{register}_NUM",
        f"SMC_I2C_WRAP_I2C_{{index}}__{register}_REG_ADDR",
    )


_INTR_ENABLE = _spec("INTR_ENABLE")
_INTR_TEST = _spec("INTR_TEST")
_INTR_STATE = _spec("INTR_STATE")
_CONTROLLER_EVENTS = _spec("CONTROLLER_EVENTS")
_TARGET_EVENTS = _spec("TARGET_EVENTS")
_STATUS = _spec("STATUS")
_TARGET_ACK_CTRL = _spec("TARGET_ACK_CTRL")
_ACQ_FIFO_NEXT_DATA = _spec("ACQ_FIFO_NEXT_DATA")

_ACCESSES_PER_GRANULE_CYCLE = 12
_ACCESSES_PER_PULSE_LEG = 5
_ACCESSES_PER_EVENT_LEG = 5
_ACCESSES_PER_TAIL = 3


def _write_only_mask(inst: RegInstance) -> int:
    mask = 0
    for field in inst.reg.fields:
        if field.access == "write-only":
            mask |= field.mask
    return mask


class smc_i2c_intr_reg_sweep_test_seq(SmcRegblockFieldSweepSeq):
    """Cycle the I2C interrupt and event registers on every instance."""

    def __init__(self, name: str = "smc_i2c_intr_reg_sweep_test_seq") -> None:
        super().__init__(name)
        self.pulses = 0
        self.event_legs = 0
        self.tail_reads = 0

    async def _intr_test_pulse(self, test: RegInstance, state: RegInstance) -> None:
        pulse = _write_only_mask(test)
        assert pulse, (
            f"{test.label}: the generated map declares no write-only field, so there is "
            f"no interrupt this leg could raise"
        )
        clearable = 0
        for field in state.reg.fields:
            if field.modified_write == "oneToClear":
                clearable |= field.mask
        assert pulse & ~clearable == 0, (
            f"{test.label}: 0x{pulse & ~clearable:x} of the write-only test mask has no "
            f"`oneToClear` field at the same position in {state.label}"
        )

        # INTR_STATE also carries status-type events hardware drives from the
        # FIFO levels, so the whole word is not predicted here. The word read
        # before the pulse is the reference: the pulse must change exactly the
        # pulsed bits, and the clear must return the word to it.
        before = await self.csr_read(f"{state.label}:idle", state.addr)
        assert before & pulse == 0, (
            f"{state.label} @ 0x{state.addr:08x}: reads 0x{before & pulse:x} in the "
            f"event bits before anything raised them"
        )
        await self.csr_write(f"{test.label}:pulse", test.addr, pulse)
        raised = await self.csr_read(f"{state.label}:raised", state.addr)
        assert raised & pulse == pulse, (
            f"{state.label} @ 0x{state.addr:08x}: a write of 0x{pulse:x} into the "
            f"write-only test fields left the matching events at 0x{raised & pulse:x}"
        )
        extra = (raised ^ before) & ~pulse
        assert extra == 0, (
            f"{state.label} @ 0x{state.addr:08x}: a write of 0x{pulse:x} into the "
            f"write-only test fields also changed 0x{extra:x} outside them "
            f"(before=0x{before:08x} after=0x{raised:08x}); the events raised are not "
            f"exactly the ones pulsed"
        )
        await self.csr_write(f"{state.label}:clear", state.addr, pulse)
        cleared = await self.csr_read(f"{state.label}:cleared", state.addr)
        assert cleared & pulse == 0, (
            f"{state.label} @ 0x{state.addr:08x}: a write of 0x{pulse:x} into the "
            f"`oneToClear` events left 0x{cleared & pulse:x} of them set"
        )
        assert cleared == before, (
            f"{state.label} @ 0x{state.addr:08x}: reads 0x{cleared:08x} after the pulsed "
            f"events were cleared, not the 0x{before:08x} measured before the pulse"
        )
        self.pulses += 1

    async def _event_leg(self, inst: RegInstance) -> None:
        declared = inst.reg.declared_mask
        half = inst.width_bytes // 2
        await self.csr_read(f"{inst.label}:idle", inst.addr, expected=0)
        await self.csr_write(f"{inst.label}:w1c_word", inst.addr, declared)
        after_word = await self.csr_read(f"{inst.label}:after_word", inst.addr, expected=0)
        assert after_word & declared == 0, (
            f"{inst.label} @ 0x{inst.addr:08x}: a write of 0x{declared:x} into `oneToClear` "
            f"fields no bus event had set left 0x{after_word & declared:x} of them set"
        )
        await self.csr_write(
            f"{inst.label}:w1c_half", inst.addr, declared & ((1 << (half * 8)) - 1), length=half
        )
        after_half = await self.csr_read(f"{inst.label}:after_half", inst.addr, expected=0)
        assert after_half & declared == 0, (
            f"{inst.label} @ 0x{inst.addr:08x}: a half-register write of the same mask left "
            f"0x{after_half & declared:x} of the `oneToClear` fields set"
        )
        self.event_legs += 1

    async def _tail_reads(self, status: RegInstance, tail: tuple[RegInstance, ...]) -> None:
        word = await self.csr_read(
            f"{status.label}:idle", status.addr, expected=status.reg.reset_word
        )
        assert word == status.reg.reset_word, (
            f"{status.label} @ 0x{status.addr:08x}: reads 0x{word:08x}, not the RDL reset "
            f"0x{status.reg.reset_word:08x} that says the block is idle with both FIFOs empty"
        )
        for inst in tail:
            got = await self.csr_read(
                f"{inst.label}:reset", inst.addr, expected=inst.reg.reset_word
            )
            outside = got & ~inst.reg.declared_mask & self.word_mask(inst)
            assert outside == 0, (
                f"{inst.label} @ 0x{inst.addr:08x}: reads 0x{got:08x}, which drives "
                f"0x{outside:x} in bits no field of the register occupies"
            )
            assert got == inst.reg.reset_word, (
                f"{inst.label} @ 0x{inst.addr:08x}: reads 0x{got:08x} while the block is "
                f"idle, its RDL reset is 0x{inst.reg.reset_word:08x}"
            )
            self.tail_reads += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        enables = reg_instances(*_INTR_ENABLE)
        tests = reg_instances(*_INTR_TEST)
        states = reg_instances(*_INTR_STATE)
        controller_events = reg_instances(*_CONTROLLER_EVENTS)
        target_events = reg_instances(*_TARGET_EVENTS)
        status = reg_instances(*_STATUS)
        ack_ctrl = reg_instances(*_TARGET_ACK_CTRL)
        acq_next = reg_instances(*_ACQ_FIFO_NEXT_DATA)
        count = len(enables)
        assert count and all(
            len(group) == count
            for group in (
                tests,
                states,
                controller_events,
                target_events,
                status,
                ack_ctrl,
                acq_next,
            )
        ), "the generated map declares a different instance count for the I2C registers"

        sb_before = self.env.scoreboard.sys_axi_value_checks_seen

        for idx in range(count):
            await self.granule_cycle(enables[idx])
            await self.granule_cycle(tests[idx])
            await self._intr_test_pulse(tests[idx], states[idx])
        cocotb.log.info(
            "CHK-I2C-INTR-REG-SWEEP: %d I2C instances each drove INTR_ENABLE and INTR_TEST "
            "to all-ones and all-zeros over the fields their RDL pins, through "
            "half-register writes whose byte lanes over the other half were deasserted, "
            "and were restored to their reset; %d contract compares",
            count,
            self.value_checks,
        )
        cocotb.log.info(
            "CHK-I2C-INTR-TEST-STATE: on %d I2C instances a write of the write-only "
            "INTR_TEST fields raised exactly those INTR_STATE events from a measured clear "
            "state, and a write of the same mask back into INTR_STATE cleared them again",
            self.pulses,
        )

        for idx in range(count):
            await self._event_leg(controller_events[idx])
            await self._event_leg(target_events[idx])
        cocotb.log.info(
            "CHK-I2C-EVENTS-W1C: %d CONTROLLER_EVENTS and TARGET_EVENTS instances took a "
            "full-width and a half-register write of their whole declared mask and stayed "
            "clear through both, which is the `oneToClear` contract for a field no bus "
            "event has set",
            self.event_legs,
        )

        for idx in range(count):
            await self._tail_reads(status[idx], (ack_ctrl[idx], acq_next[idx]))
        cocotb.log.info(
            "CHK-I2C-READMUX-TAIL: %d TARGET_ACK_CTRL and ACQ_FIFO_NEXT_DATA reads each "
            "returned their RDL reset word under a STATUS word showing the block idle "
            "with both FIFOs empty",
            self.tail_reads,
        )

        expected = count * (
            2 * _ACCESSES_PER_GRANULE_CYCLE
            + _ACCESSES_PER_PULSE_LEG
            + 2 * _ACCESSES_PER_EVENT_LEG
            + _ACCESSES_PER_TAIL
        )
        self.assert_all_reachable(expected, "I2C_INTR_REG_SWEEP")
        assert self.registers_swept == 2 * count, (
            f"the sweep completed {self.registers_swept} field cycles for {2 * count} registers"
        )
        assert self.pulses == count and self.event_legs == 2 * count, (
            f"{self.pulses} pulse legs and {self.event_legs} event legs for {count} instances"
        )
        assert self.tail_reads == 2 * count, (
            f"{self.tail_reads} tail reads for {2 * count} registers"
        )
        # Predicted words per instance: the six reads of the INTR_ENABLE cycle,
        # the six of the two event legs and the three tail reads. The INTR_TEST
        # cycle and the INTR_STATE reads carry hardware-driven fields, so their
        # whole word is not predicted and they book no scoreboard compare.
        self.assert_value_checks(sb_before, count * 15, "I2C_INTR_REG_SWEEP")
