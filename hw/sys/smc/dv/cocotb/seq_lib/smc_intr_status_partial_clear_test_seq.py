# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write-one-to-clear status registers cleared a few bits at a time.

Three blocks carry an interrupt status register whose bits software raises
through the matching `INTR_TEST` register and clears by writing a one back:
the I2C `INTR_STATE`, the log engine `INTR_STATUS` and the telemetry receiver
`INTR_STATUS`. Every leaf that touches them raises the whole declared mask and
then clears the whole declared mask, so no write has ever carried a zero over a
bit that was set, and the half of the contract that says such a bit *stays* set
has never been exercised on any instance.

This leaf drives that half. On each instance of each of the three registers it

* reads the register and requires it clear, so every bit it goes on to see set
  is one this sequence raised;
* writes the event bits of `INTR_TEST` and requires the status register to
  report exactly those raised. Only the `read-write` fields take part: a status
  register also carries `read-only` level bits that hardware drives from a
  condition -- the I2C FIFO thresholds, the stretch and halt indications -- and
  a write cannot clear one of those while its condition holds;
* writes back **half** of the raised bits, and requires precisely those to have
  gone and the other half to still be set -- the write carried a zero over
  them, and a `oneToClear` field holds its value against a zero. Where a
  register has only one clearable bit that write carries no bits at all, which
  puts the same contract to the same test;
* writes the remaining half and requires the register to read clear again.

The two halves are alternating bits of the mask, so neither is a contiguous run
that a byte-granular decode could clear by accident, and the sequence fails if
the half that has to survive the write is empty.

Raising a status bit through `INTR_TEST` is the same mechanism
`smc_i2c_intr_reg_sweep_test` already uses, and nothing here leaves a bit set:
each register ends the leg reading clear, which is its reset.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_I2C = "SMC_TOP_SMC_I2C_WRAP_I2C_"
_WRAP = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_"
_TELEMETRY = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_"


def _i2c_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_i2c_wrap/i2c/{register}",
        f"{_I2C}{register}_BASE_ADDR",
        f"{_I2C}{register}_NUM",
        f"SMC_I2C_WRAP_I2C_{{index}}__{register}_REG_ADDR",
    )


def _log_engine_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_uart_wrap/uart_log_engine_wrap/log_engine/{register}",
        f"{_WRAP}LOG_ENGINE_{register}_BASE_ADDR",
        f"{_WRAP}LOG_ENGINE_{register}_NUM",
        f"SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_{{index}}__LOG_ENGINE_{register}_REG_ADDR",
    )


def _telemetry_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_telemetry_receiver_wrap/telemetry_receiver/{register}",
        f"{_TELEMETRY}{register}_BASE_ADDR",
        f"{_TELEMETRY}{register}_NUM",
        f"SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{{index}}__{register}_REG_ADDR",
    )


# Each entry is a block name, the status register spec and the INTR_TEST spec
# that raises its bits.
_BLOCKS: tuple[tuple[str, tuple[str, str, str, str], tuple[str, str, str, str]], ...] = (
    ("i2c", _i2c_spec("INTR_STATE"), _i2c_spec("INTR_TEST")),
    ("log_engine", _log_engine_spec("INTR_STATUS"), _log_engine_spec("INTR_TEST")),
    ("telemetry", _telemetry_spec("INTR_STATUS"), _telemetry_spec("INTR_TEST")),
)

# Accesses one register instance costs: the idle read, the INTR_TEST write and
# the raised read, the partial clear and its read, the rest and its read.
_ACCESSES_PER_INSTANCE = 7


def _alternating(mask: int) -> tuple[int, int]:
    """Split a mask into two interleaved halves, lowest set bit first."""
    first = 0
    second = 0
    for index, bit in enumerate(b for b in range(mask.bit_length()) if mask >> b & 1):
        if index % 2:
            second |= 1 << bit
        else:
            first |= 1 << bit
    return first, second


class smc_intr_status_partial_clear_test_seq(SmcCsrSeq):
    """Clear write-one-to-clear status bits a few at a time, not all at once."""

    def __init__(self, name: str = "smc_intr_status_partial_clear_test_seq") -> None:
        super().__init__(name)
        self.registers = 0
        self.bits_held = 0

    @staticmethod
    def _clearable(status: RegInstance) -> int:
        """The `oneToClear` event bits, which the generated map marks read-write.

        A status register mixes two kinds of field. The event bits are
        `read-write`: hardware sets them, software clears them by writing a
        one, and they hold their value otherwise -- those are the ones this
        leaf is about. The rest are `read-only` level bits the hardware drives
        from a condition, such as the I2C FIFO thresholds and the stretch and
        halt indications; a write cannot clear those while their condition
        holds, so they are excluded here rather than expected to go.
        """
        mask = 0
        for field in status.reg.fields:
            if field.access == "read-write":
                mask |= field.mask
        return mask

    async def _leg(self, block: str, status: RegInstance, test: RegInstance) -> None:
        common = self._clearable(status) & test.reg.declared_mask
        assert common, (
            f"{block} [{status.label}]: the status register and INTR_TEST declare no field "
            f"in common, so nothing here could raise a bit to clear"
        )
        first, second = _alternating(common)
        if not second:
            # A single clearable bit cannot be split. The contract is the same
            # one either way -- a `oneToClear` field holds its value against a
            # zero -- so the write that has to leave it set carries no bits at
            # all instead of the other half.
            first, second = 0, common
        assert second, (
            f"{block} [{status.label}]: the clearable mask 0x{common:x} is empty, so there "
            f"is nothing for a partial clear to hold"
        )

        idle = await self.csr_read(f"{block}{status.index}_STATUS_IDLE", status.addr)
        assert idle & common == 0, (
            f"{block} [{status.label}]: reads 0x{idle:x} before this sequence raised "
            f"anything; every bit it goes on to clear has to be one it raised itself"
        )

        await self.csr_write(f"{block}{status.index}_INTR_TEST", test.addr, common)
        raised = await self.csr_read(f"{block}{status.index}_STATUS_RAISED", status.addr)
        assert raised & common == common, (
            f"{block} [{status.label}]: reads 0x{raised:x} after INTR_TEST was written with "
            f"0x{common:x}; every one of those bits has to be set"
        )

        await self.csr_write(f"{block}{status.index}_CLEAR_FIRST", status.addr, first)
        held = await self.csr_read(f"{block}{status.index}_STATUS_HELD", status.addr)
        assert held & first == 0, (
            f"{block} [{status.label}]: reads 0x{held:x} after a write of 0x{first:x}; a "
            f"`oneToClear` field written with a one has to go"
        )
        assert held & second == second, (
            f"{block} [{status.label}]: reads 0x{held:x} after a write of 0x{first:x}, "
            f"which carried a zero over 0x{second:x}; a `oneToClear` field holds its value "
            f"against a zero, so those bits have to still be set"
        )
        self.bits_held += bin(second).count("1")

        await self.csr_write(f"{block}{status.index}_CLEAR_REST", status.addr, second)
        cleared = await self.csr_read(f"{block}{status.index}_STATUS_CLEARED", status.addr)
        assert cleared & common == 0, (
            f"{block} [{status.label}]: reads 0x{cleared:x} after both halves were written "
            f"back; the register has to end the leg at its reset"
        )
        self.registers += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        legs: list[tuple[str, RegInstance, RegInstance]] = []
        for block, status_spec, test_spec in _BLOCKS:
            statuses = reg_instances(*status_spec)
            tests = reg_instances(*test_spec)
            assert statuses and len(statuses) == len(tests), (
                f"{block}: the generated map declares {len(statuses)} status and "
                f"{len(tests)} INTR_TEST instances"
            )
            legs.extend(zip([block] * len(statuses), statuses, tests))
        assert len({status.addr for _b, status, _t in legs}) == len(legs), (
            "two status registers resolve to the same address"
        )

        for block, status, test in legs:
            await self._leg(block, status, test)

        assert self.registers == len(legs), (
            f"{self.registers} of {len(legs)} status registers driven"
        )
        assert self.bits_held >= len(legs), (
            f"{self.bits_held} bits were held set across {len(legs)} registers; each leg "
            f"holds at least one"
        )
        floor = len(legs) * _ACCESSES_PER_INSTANCE
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; {len(legs)} registers "
            f"cannot have taken fewer than {floor}"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        cocotb.log.info(
            "CHK-INTR-STATUS-PARTIAL-CLEAR: on %d write-one-to-clear status registers "
            "across the I2C blocks, the log engines and the telemetry receivers, the whole "
            "declared mask was raised through INTR_TEST, half of it was written back and "
            "went, and the %d bit(s) the write carried a zero over stayed set, which is "
            "the `oneToClear` contract; every register then took the other half and read "
            "clear again",
            self.registers,
            self.bits_held,
        )
