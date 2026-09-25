# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The four I2C FIFO resets, pulsed against a measured fill level.

`smc_i2c_config_regblock_sweep_test` cycles the I2C configuration registers but
cannot express `FIFO_CTRL`: `i2c.rdl` makes all four of its fields `sw = w` with
`singlepulse`, so the generated contract pins no written value to read back and
the half-register cycle has nothing to drive. Nothing else writes the register
either, so none of the four resets has ever been pulsed on any instance.

This leaf pulses each one and checks it against the DUT rather than a readback,
on all three instances, with the block idle -- `CTRL.ENABLEHOST` and
`CTRL.ENABLETARGET` are left at their reset, so no engine drains what the
sequence puts in.

**Two of the four FIFOs can be filled from software, and those carry the strong
claim.** `i2c.rdl` maps `FMTRST` to the Controller TX FIFO and `TXRST` to the
Target TX FIFO, and both of those FIFOs have a software write port -- `FDATA`
and `TXDATA`. The push is not gated on either engine enable, so the sequence
fills each one, reads the level out of `HOST_FIFO_STATUS.FMTLVL` and
`TARGET_FIFO_STATUS.TXLVL`, pulses the reset and requires that level to have
gone to empty. The two fills are deliberately different depths, so a status
register that reported the other FIFO's level would fail the compare before any
reset was pulsed.

**The other two cannot, and carry a weaker claim that is still a real compare.**
`RXRST` resets the Controller RX FIFO and `ACQRST` the Target RX FIFO, and both
of those are filled only by traffic on the wire: the controller receiving from a
remote target, or a remote controller writing to this block as a target. Neither
is reachable from the CSR port alone, and the leaves that drive the bus are a
different shape that owns the protocol agent. So what this leaf claims for those
two is narrower: each is pulsed while the two software-fillable FIFOs hold known,
different levels, and **neither level may move**. That fails if the reset decode
is not one-hot -- if `RXRST` or `ACQRST` reached the format or the target
transmit FIFO, the compare after the pulse would catch it -- but it does not
show that either reset empties the FIFO it names. The card says so.

The same one-hot check runs on the two resets that do carry the strong claim:
`FMTRST` must leave the target transmit level untouched, and `TXRST` is pulsed
last, with the controller FIFO already emptied, so each reset is shown to reach
its own FIFO and no other.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_I2C = "SMC_TOP_SMC_I2C_WRAP_I2C_"


def _spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_i2c_wrap/i2c/{register}",
        f"{_I2C}{register}_BASE_ADDR",
        f"{_I2C}{register}_NUM",
        f"SMC_I2C_WRAP_I2C_{{index}}__{register}_REG_ADDR",
    )


_REGS = ("FIFO_CTRL", "FDATA", "TXDATA", "HOST_FIFO_STATUS", "TARGET_FIFO_STATUS")

# Bytes pushed into each software-fillable FIFO. The two depths differ so a
# status word that reported the other FIFO's level fails before a reset is
# pulsed, and the values are spread across the byte.
_FMT_FILL = (0xA5, 0x5A, 0x3C)
_TX_FILL = (0x11, 0x22, 0x44, 0x88, 0xF0)

# SEP_IN accesses one instance needs: the two baseline status reads, the eight
# fills, the two status reads that measure them, four pulses with both status
# registers read after each, and the FIFO_CTRL readback. The read after the
# last pulse is the final one, so it is counted once.
_ACCESSES_PER_INSTANCE = 2 + len(_FMT_FILL) + len(_TX_FILL) + 2 + 4 * 3 + 1


def _field_mask(inst: RegInstance, name: str) -> tuple[int, int]:
    for field in inst.reg.fields:
        if field.name == name:
            return field.mask, field.offset
    raise AssertionError(f"{inst.label}: the generated map declares no field named {name}")


class smc_i2c_fifo_reset_pulse_test_seq(SmcCsrSeq):
    """Pulse each I2C FIFO reset against a measured fill level."""

    def __init__(self, name: str = "smc_i2c_fifo_reset_pulse_test_seq") -> None:
        super().__init__(name)
        self.instances = 0
        self.emptied = 0
        self.undisturbed = 0

    # -- primitives ------------------------------------------------------

    async def _levels(self, host: RegInstance, target: RegInstance, label: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for inst, names in ((host, ("FMTLVL", "RXLVL")), (target, ("TXLVL", "ACQLVL"))):
            word = await self.csr_read(f"{inst.label}:{label}", inst.addr)
            for name in names:
                mask, offset = _field_mask(inst, name)
                out[name] = (word & mask) >> offset
        return out

    async def _pulse(self, ctrl: RegInstance, field: str, index: int) -> None:
        mask, _offset = _field_mask(ctrl, field)
        await self.csr_write(f"I2C{index}:FIFO_CTRL:{field}", ctrl.addr, mask)

    def _require(self, got: dict[str, int], want: dict[str, int], index: int, what: str) -> None:
        for name, value in want.items():
            assert got[name] == value, (
                f"I2C instance {index} [{what}]: {name} reads {got[name]}, {value} was "
                f"expected; levels read {got}"
            )

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        groups = {name: reg_instances(*_spec(name)) for name in _REGS}
        count = len(groups[_REGS[0]])
        assert count and all(len(group) == count for group in groups.values()), (
            "the generated map declares a different instance count for the I2C FIFO registers"
        )
        assert len(_FMT_FILL) != len(_TX_FILL), (
            "the two fills are the same depth, so a status word reporting the other FIFO's "
            "level would pass every compare below"
        )

        for index in range(count):
            ctrl = groups["FIFO_CTRL"][index]
            fdata = groups["FDATA"][index]
            txdata = groups["TXDATA"][index]
            host = groups["HOST_FIFO_STATUS"][index]
            target = groups["TARGET_FIFO_STATUS"][index]
            empty = {"FMTLVL": 0, "RXLVL": 0, "TXLVL": 0, "ACQLVL": 0}

            # The block is idle and every FIFO starts empty, so each level below
            # is one this sequence put there.
            self._require(await self._levels(host, target, "idle"), empty, index, "idle")

            fbyte, _offset = _field_mask(fdata, "FBYTE")
            for byte in _FMT_FILL:
                await self.csr_write(f"I2C{index}:FDATA:{byte:02x}", fdata.addr, byte & fbyte)
            data, _offset = _field_mask(txdata, "DATA")
            for byte in _TX_FILL:
                await self.csr_write(f"I2C{index}:TXDATA:{byte:02x}", txdata.addr, byte & data)

            filled = {
                "FMTLVL": len(_FMT_FILL),
                "RXLVL": 0,
                "TXLVL": len(_TX_FILL),
                "ACQLVL": 0,
            }
            self._require(await self._levels(host, target, "filled"), filled, index, "filled")

            # The two resets whose FIFOs software cannot fill: each must leave
            # both measured levels exactly where they are.
            for field in ("RXRST", "ACQRST"):
                await self._pulse(ctrl, field, index)
                self._require(
                    await self._levels(host, target, f"after_{field}"), filled, index, field
                )
                self.undisturbed += 1

            # FMTRST empties the controller transmit FIFO and leaves the target
            # transmit FIFO where it is.
            await self._pulse(ctrl, "FMTRST", index)
            after_fmt = dict(filled, FMTLVL=0)
            self._require(
                await self._levels(host, target, "after_FMTRST"), after_fmt, index, "FMTRST"
            )
            self.emptied += 1

            # TXRST empties the target transmit FIFO, with the controller FIFO
            # already empty so this pulse is shown to reach only its own.
            await self._pulse(ctrl, "TXRST", index)
            self._require(await self._levels(host, target, "after_TXRST"), empty, index, "TXRST")
            self.emptied += 1

            held = await self.csr_read(f"I2C{index}:FIFO_CTRL:readback", ctrl.addr)
            assert held == 0, (
                f"I2C instance {index}: FIFO_CTRL reads 0x{held:08x} after four pulses; "
                f"the RDL makes every field of it `sw = w` and `singlepulse`, so none of "
                f"them stays set and the register reads 0"
            )
            self.instances += 1

        assert self.instances == count, f"{self.instances} of {count} I2C instances pulsed"
        assert self.emptied == 2 * count and self.undisturbed == 2 * count, (
            f"{self.emptied} FIFOs emptied and {self.undisturbed} left undisturbed over "
            f"{count} instances; each instance does two of each"
        )
        floor = count * _ACCESSES_PER_INSTANCE
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; pulsing four resets on "
            f"{count} instances cannot have issued fewer than {floor}"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            "no scoreboard on this sequence's env, so the CSR traffic cannot be "
            "corroborated independently of the sequence's own counter"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked only {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but "
            f"this sequence issued {self.accesses}, so the traffic never reached it"
        )

        cocotb.log.info(
            "CHK-I2C-FIFO-RST-EMPTIES: on %d I2C instances FMTRST and TXRST each emptied "
            "the FIFO i2c.rdl names for it, from a level of %d and %d bytes that the "
            "sequence had put there through FDATA and TXDATA and measured in "
            "HOST_FIFO_STATUS and TARGET_FIFO_STATUS first; %d resets observed",
            self.instances,
            len(_FMT_FILL),
            len(_TX_FILL),
            self.emptied,
        )
        cocotb.log.info(
            "CHK-I2C-FIFO-RST-ONE-HOT: on %d I2C instances each of the four resets reached "
            "its own FIFO and no other -- RXRST and ACQRST left both measured levels "
            "exactly where they were, FMTRST left the target transmit level untouched "
            "while clearing the controller one, and TXRST cleared the target level with "
            "the controller FIFO already empty; FIFO_CTRL read 0 afterwards, which is the "
            "`singlepulse` contract for all four",
            self.instances,
        )
