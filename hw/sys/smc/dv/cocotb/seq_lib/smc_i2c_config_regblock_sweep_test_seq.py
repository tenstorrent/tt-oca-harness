# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The I2C configuration registers, cycled on every instance.

This leaf drives the block's configuration -- the control register, the timing
set, the FIFO thresholds, the three timeout controls, the target identity, the
bus override and the SMBus control -- through the half-register cycle, on all
three instances, and restores the RDL reset.

**The block stays idle throughout.** `CTRL.ENABLEHOST` and `CTRL.ENABLETARGET`
are the two fields that start the controller and the target, so they are held
at their reset for the whole cycle and the sequence fails before it issues
anything if the pattern it is about to write does not leave both clear. Every
other CTRL field only changes how a running block behaves, and with neither
engine enabled none of them can reach the bus. The bus monitor
`CTRL.MULTI_CONTROLLER_MONITOR_EN` selects is a monitor -- its outputs are
detect and event strobes, nothing that drives SCL or SDA -- and CTRL is cycled
first, so it is back at its reset before the timeout registers are given
values.

**The override never pulls a line down.** `i2c.rdl` gives `OVRD.SCLVAL` and
`OVRD.SDAVAL` the sense "0 - Pull the line low, 1 - Release the line", and
`TXOVRDEN` enables both. All three sit in the same byte, so one write moves
them together: the ones pattern releases both lines while enabling the
override, and the zero pattern clears `TXOVRDEN` in the same write that clears
the values. The sequence checks that for every word it is about to write, and
fails rather than drive a line low under an override.

**The all-zeros leg restores the reset.** `i2c.rdl` says of `TIMING0.THIGH`
and `TIMING0.TLOW` that each "Must be `>= 2`", a programming rule for a running
controller; this leaf never enables one. Every register in the set resets to
zero over the fields the cycle drives, so the zero leg writes only what reset
already holds, and the sequence asserts that relation for each register before
it starts.

`FIFO_CTRL` is not in the set. The generated contract gives it no
software-writable field with a pinned readback at all -- `RXRST`, `FMTRST`,
`ACQRST` and `TXRST` are every one of them self-clearing -- so there is nothing
for the cycle to write and a sweep of it would assert rather than run. The FIFO
data ports and the status registers are excluded for the same reason: the
engine writes only fields the contract pins exactly.
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


# The two CTRL fields that start an engine. Held at their reset for the whole
# cycle: every other field of CTRL only shapes how a running block behaves.
_CTRL_ENABLES = frozenset({"ENABLEHOST", "ENABLETARGET"})

# The configuration registers no leaf writes, with the fields each cycle holds.
# CTRL leads so the bus monitor it can enable is back at its reset before the
# timeout registers below are given values.
_REGISTERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("CTRL", _CTRL_ENABLES),
    ("SMBUS_CTRL", frozenset()),
    ("OVRD", frozenset()),
    ("TIMING0", frozenset()),
    ("TIMING1", frozenset()),
    ("TIMING2", frozenset()),
    ("TIMING3", frozenset()),
    ("TIMING4", frozenset()),
    ("HOST_FIFO_CONFIG", frozenset()),
    ("TARGET_FIFO_CONFIG", frozenset()),
    ("TIMEOUT_CTRL", frozenset()),
    ("HOST_TIMEOUT_CTRL", frozenset()),
    ("TARGET_TIMEOUT_CTRL", frozenset()),
    ("HOST_NACK_HANDLER_TIMEOUT", frozenset()),
    ("TARGET_ID", frozenset()),
)

# Accesses one `granule_cycle` issues: the reset read, four half writes with a
# readback each, and the two restore writes with one readback.
_ACCESSES_PER_GRANULE_CYCLE = 12
# Reads of those twelve, each one a contract compare.
_READS_PER_GRANULE_CYCLE = 6


def _field(inst: RegInstance, name: str) -> int:
    """Mask of one named field of the register, from the generated contract."""
    for field in inst.reg.fields:
        if field.name == name:
            return field.mask
    raise AssertionError(f"{inst.label}: the generated map declares no field named {name}")


class smc_i2c_config_regblock_sweep_test_seq(SmcRegblockFieldSweepSeq):
    """Cycle the I2C configuration registers on every instance, block idle."""

    def __init__(self, name: str = "smc_i2c_config_regblock_sweep_test_seq") -> None:
        super().__init__(name)
        self.instances = 0
        self.registers_checked = 0
        self.pinned_cycles = 0

    # -- host-side guards ------------------------------------------------

    @staticmethod
    def _held_and_driven(inst: RegInstance, hold: frozenset[str]) -> tuple[int, int]:
        held = 0
        for name in hold:
            held |= _field(inst, name)
        return held, inst.reg.rw_mask & ~held

    @classmethod
    def _cycle_words(cls, inst: RegInstance, hold: frozenset[str]) -> tuple[int, ...]:
        """Every word `granule_cycle` leaves resident, the half steps included.

        The two halves go out as separate writes, so the word between them is
        resident too and has to satisfy the same guards as the ones either side
        of it.
        """
        _held, driven = cls._held_and_driven(inst, hold)
        half = inst.width_bytes // 2
        granules = ((0, half), (half, inst.width_bytes - half))
        word = inst.reg.reset_word
        words = [word]
        for pattern in (driven, 0):
            for offset, width in granules:
                gmask = ((1 << (width * 8)) - 1) << (offset * 8)
                touched = driven & gmask
                word = (word & ~touched) | (pattern & touched)
                words.append(word)
        words.append(inst.reg.reset_word)
        return tuple(words)

    def _check_register(self, inst: RegInstance, hold: frozenset[str]) -> None:
        """Refuse the cycle unless every word it writes leaves the block idle."""
        held, driven = self._held_and_driven(inst, hold)
        words = self._cycle_words(inst, hold)

        # The zero leg must not undercut a minimum the RDL states, and it
        # cannot: over the fields the cycle drives, zero is the reset.
        assert inst.reg.reset_word & driven == 0, (
            f"{inst.label}: the RDL reset 0x{inst.reg.reset_word:08x} is not zero over the "
            f"0x{driven:08x} this cycle drives, so the all-zeros leg would leave a value "
            f"the reset does not hold and any minimum the RDL states has to be checked"
        )

        for word in words:
            assert word & held == inst.reg.reset_word & held, (
                f"{inst.label}: the cycle would leave 0x{word:08x} resident, which moves "
                f"{', '.join(sorted(hold))} off its reset"
            )

        names = {field.name for field in inst.reg.fields}
        if {"TXOVRDEN", "SCLVAL", "SDAVAL"} <= names:
            enable = _field(inst, "TXOVRDEN")
            released = _field(inst, "SCLVAL") | _field(inst, "SDAVAL")
            for word in words:
                if word & enable:
                    assert word & released == released, (
                        f"{inst.label}: the cycle would leave 0x{word:08x} resident, which "
                        f"enables the override with SCLVAL or SDAVAL clear; the RDL gives "
                        f"0 on either the sense 'pull the line low'"
                    )
        if self.volatile_mask(inst) == 0:
            self.pinned_cycles += 1
        self.registers_checked += 1

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        groups = {name: reg_instances(*_spec(name)) for name, _ in _REGISTERS}
        count = len(groups[_REGISTERS[0][0]])
        assert count and all(len(group) == count for group in groups.values()), (
            "the generated map declares a different instance count for the I2C "
            "configuration registers"
        )

        # Every word of every cycle is checked before a single access goes out,
        # so a contract that changed under the sweep stops it rather than
        # starting an engine or pulling a bus line down.
        for name, hold in _REGISTERS:
            for inst in groups[name]:
                self._check_register(inst, hold)
        assert self.registers_checked == count * len(_REGISTERS), (
            f"{self.registers_checked} register instances cleared the guards, "
            f"{count * len(_REGISTERS)} were to be cycled"
        )

        sb_before = self.env.scoreboard.sys_axi_value_checks_seen

        for idx in range(count):
            for name, hold in _REGISTERS:
                await self.granule_cycle(groups[name][idx], hold_fields=hold)
            self.instances += 1

        assert self.instances == count, f"{self.instances} of {count} I2C instances cycled"
        assert self.registers_swept == count * len(_REGISTERS), (
            f"{self.registers_swept} register cycles completed, "
            f"{count * len(_REGISTERS)} were planned"
        )
        floor = self.registers_swept * _ACCESSES_PER_GRANULE_CYCLE
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; "
            f"{self.registers_swept} half-register cycles cannot have issued fewer "
            f"than {floor}"
        )
        assert self.value_checks == self.registers_swept * _READS_PER_GRANULE_CYCLE, (
            f"{self.value_checks} contract compares over {self.registers_swept} cycles, "
            f"each of which reads the whole register {_READS_PER_GRANULE_CYCLE} times"
        )
        # `read_check` hands the scoreboard an expected word only for a register
        # no field of which hardware drives; SMBUS_CTRL.SMBALERT is `hwclr`, so
        # that one register carries its field asserts alone and the scoreboard
        # books nothing for it.
        checks = self.env.scoreboard.sys_axi_value_checks_seen - sb_before
        expected_checks = self.pinned_cycles * _READS_PER_GRANULE_CYCLE
        assert checks == expected_checks, (
            f"the scoreboard booked {checks} SEP_IN value compare(s); the "
            f"{self.pinned_cycles} cycles on registers whose whole word the contract pins "
            f"read {expected_checks} of them, so the traffic did not reach it intact"
        )

        cocotb.log.info(
            "CHK-I2C-CONFIG-REG-SWEEP: %d I2C instances each drove %d configuration "
            "registers -- the control register, the five timing registers, both FIFO "
            "threshold registers, the three timeout controls, the NACK handler timeout, "
            "the target identity, the bus override and the SMBus control -- to all-ones "
            "and all-zeros over the fields their RDL pins, through half-register writes "
            "whose byte lanes over the other half were deasserted, and were restored to "
            "their reset; %d contract compares",
            self.instances,
            len(_REGISTERS),
            self.value_checks,
        )
        cocotb.log.info(
            "CHK-I2C-CONFIG-IDLE-GUARD: every one of the %d register cycles was checked "
            "before any access that the words it would leave resident hold "
            "CTRL.ENABLEHOST and CTRL.ENABLETARGET at their reset, never enable the "
            "override with SCLVAL or SDAVAL clear, and are zero over the driven fields "
            "wherever the reset is, so no leg of the sweep starts an engine, pulls a bus "
            "line low, or writes a value below a minimum the RDL states",
            self.registers_checked,
        )
