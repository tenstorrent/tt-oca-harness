# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fill the DST trace packetizer accumulator from the SMC debug bus.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. The vendored
RTL is not a source for any value this sequence programs or compares against.

The contract this sequence drives, all of it from the RDL:

* ``DFX_CTRL.DEBUG_CTRL.force_clk_en``, which the RDL describes as forcing
  the clock on, holds the DFD clock up while ``cg_en`` stays 0.
* ``DFX_CTRL.DEBUG_BUS_MUX.Dbmmode``, whose RDL description numbers the mux
  modes with one of them the normal debug mode, and ``.Dbmid``, which the RDL
  describes as the unique identifier of a mux instance. A mux takes the mode
  only while the programmed id is its own, so normal debug mode is written
  once per value of the 6-bit id field and every mux of the array ends up
  passing its lanes. ``Muxselseg0..7`` stay 0, which the RDL description
  gives each output lane its own static segment.
* ``DST.Trdstcontrol`` -- ``Trdstactive`` / ``Trdstenable``, and ``Trdstformat``
  at the uncompressed value its own RDL description names.
* ``FUNNEL.Trfunnelcontrol`` and the ``DST_SINK`` window and enables, so the
  packetizer has somewhere to hand a filled bank.
* ``CDbgNode0Eap0.Action0``, six bits, which the RDL describes only as
  selecting an action. Which action code starts a trace is **not** published
  by the RDL, the generated headers or the MMR specification, so this sequence
  names no code: it drives the field over its whole range, one value at a
  time, and lets the DUT report what happened.

Two hardware-driven, software-readable values carry the result, and both are
read at their RDL reset first so what changes is attributable to the sweep:

* ``DST.Trdstcontrol.Trdstempty`` (read-only, reset 1) clears while the
  packetizer holds trace data, which is the accumulator bank out of its empty
  state.
* ``DST_SINK.Trdstramwplow`` (reset 0, carrying the write pointer and the
  hardware-set wrap flag) leaves its reset once the sink has taken a filled
  bank, which is the accumulator bank handing data on and going empty again.
  The write pointer field itself has to move and stay inside the window; the
  wrap flag alone does not say where the sink wrote.

The sink's limit field sits above two reserved bits and hardware writes it
too, so the register's plain read-write mask leaves it out; the window is
written through the field's own bit positions.
"""

from __future__ import annotations

from functools import lru_cache

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlField, RdlReg, rdl_register, rdl_registers_under

_CLA_ADDRMAP = "smc_cla"
_DST_SEGMENT = "dst"
_SINK_SEGMENT = "dst_sink"
_FUNNEL_SEGMENT = "funnel"

# Window the trace RAM sink is given, in bytes, from the base its start
# registers reset to. The RDL fixes neither the RAM's size nor its base, so the
# window is a DV-owned choice, small enough to be filled inside the sweep.
_SINK_WINDOW_BYTES = 0x1000

# dfd_dst.rdl gives Trdstformat bit 0 as XOR enable and bit 1 as VLT enable,
# and names 3, 1 and 0 as the supported values. Uncompressed, every debug-bus
# sample becomes a packet; the compressing reset value emits almost nothing
# while the selected lanes hold still, and the accumulator never fills.
_DST_FORMAT_NONE = 0

# clk_smc_i cycles between a configuration write and the first status read, and
# the number of reads a configuration gets before it counts as not having
# accumulated. Both observed registers are hardware-driven and continuously
# rewritten, so these are bounded polls on DUT-driven state rather than delays
# standing in for a handshake.
_SETTLE_CYCLES = 32
_EMPTY_POLLS = 3
_HANDOFF_POLLS = 32


def reg_field(reg: RdlReg, name: str) -> RdlField:
    for field in reg.fields:
        if field.name == name:
            return field
    raise KeyError(f"{reg.path} has no field {name} in the generated map")


def pack_fields(reg: RdlReg, values: dict[str, int]) -> int:
    """Register word with the named fields set and every other bit 0."""
    word = 0
    for name, value in values.items():
        field = reg_field(reg, name)
        assert value < (1 << field.width), (
            f"{reg.path}.{name} is {field.width} bits, cannot hold {value}"
        )
        word |= value << field.offset
    return word


def field_word(reg: RdlReg, name: str, value: int) -> int:
    """Register word carrying ``value`` in the bit positions of one field.

    For the sink pointer and limit registers, whose field starts above two
    reserved bits and holds a byte address, ``value`` is that byte address.
    Those fields are written by hardware as well, so they are not in the
    register's plain read-write mask and masking with it would send zero.
    """
    field = reg_field(reg, name)
    assert value & ~field.mask == 0, (
        f"0x{value:x} does not fit {reg.path}.{name}, bits {field.offset} to "
        f"{field.offset + field.width - 1}"
    )
    return value


def checked_mask(reg: RdlReg, values: dict[str, int]) -> int:
    """Bits a write/readback must return: the plain read-write fields plus the named ones.

    A named field that hardware also writes is still compared, because the
    readback directly follows the write.
    """
    mask = reg.rw_mask
    for name in values:
        field = reg_field(reg, name)
        if field.access == "read-write":
            mask |= field.mask
    return mask


@lru_cache(maxsize=None)
def block_register(block: str, name: str) -> RdlReg:
    """One register of a sub-block of the SMC_CLA aperture, by its RDL name.

    A sub-block is a register file the map may spell with or without its
    element index, so the lookup matches the path segment either way and holds
    the matches to one address.
    """
    matches = {
        reg.addr: reg
        for reg in rdl_registers_under(_CLA_ADDRMAP)
        if reg.path.rsplit("/", 1)[1] == name and reg.path.split("/")[1].split("[", 1)[0] == block
    }
    assert len(matches) == 1, (
        f"the generated map spells {_CLA_ADDRMAP}/{block}/{name} at "
        f"{sorted(hex(a) for a in matches)}; the lookup needs exactly one address"
    )
    return next(iter(matches.values()))


def dst_register(name: str) -> RdlReg:
    return block_register(_DST_SEGMENT, name)


def sink_register(name: str) -> RdlReg:
    return block_register(_SINK_SEGMENT, name)


def funnel_register(name: str) -> RdlReg:
    return block_register(_FUNNEL_SEGMENT, name)


def dfd_register(path: str) -> RdlReg:
    """One register of the SMC DFX control block, by its IP-XACT path."""
    return rdl_register(path)


class smc_dfd_trace_accumulator_fill_test_seq(SmcCsrSeq):
    """Drive debug-bus trace into the DST packetizer and watch a bank fill and hand on."""

    def __init__(self, name: str = "smc_dfd_trace_accumulator_fill_test_seq") -> None:
        super().__init__(name)
        self.actions_swept = 0
        self.actions_accumulating = 0
        self.dbmids_programmed = 0
        self.value_checks = 0
        self.sink_pointer = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg: RdlReg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg: RdlReg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write_check(self, reg: RdlReg, values: dict[str, int], label: str) -> None:
        """Write the named fields and require the writable bits to read back."""
        word = pack_fields(reg, values)
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)
        readback = await self._read(reg, f"{label}_rb")
        mask = checked_mask(reg, values)
        assert readback & mask == word & mask, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: wrote 0x{word & mask:x} into "
            f"its software-writable bits, reads 0x{readback & mask:x}"
        )
        self.value_checks += 1

    # -- bring-up ---------------------------------------------------------

    async def _hold_dfd_clock(self) -> None:
        await self._write_check(dfd_register("dfx_ctrl/DEBUG_CTRL"), {"force_clk_en": 1}, "force")

    async def _idle_witness(self) -> None:
        """Both observed registers carry their RDL reset before any trace runs."""
        dst = dst_register("Trdstcontrol")
        empty = reg_field(dst, "Trdstempty")
        word = await self._read(dst, "idle")
        expected = (dst.reset_word & empty.mask) >> empty.offset
        assert (word & empty.mask) >> empty.offset == expected, (
            f"DST Trdstcontrol.Trdstempty @ 0x{dst.addr:08x} reads "
            f"{(word & empty.mask) >> empty.offset} before any trace was started; its RDL "
            f"reset is {expected}, so the packetizer already holds data and a later 'it "
            f"filled' observation would prove nothing"
        )
        wp = sink_register("Trdstramwplow")
        at_reset = await self._read(wp, "idle")
        assert at_reset == wp.reset_word, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} reads 0x{at_reset:08x} before any "
            f"trace was started; its RDL reset is 0x{wp.reset_word:08x}, so a later 'the "
            f"sink took a bank' observation would not be attributable to this run"
        )
        self.value_checks += 2
        cocotb.log.info(
            "CHK-DST-TRACE-IDLE: DST Trdstcontrol.Trdstempty reads its RDL reset of %d and "
            "DST_SINK Trdstramwplow reads its RDL reset of 0x%08x with the DFD clock held "
            "on and no trace running, so the packetizer accumulator starts this run empty "
            "and the sink has taken nothing",
            expected,
            wp.reset_word,
        )

    async def _open_debug_bus(self) -> None:
        """Put every debug-bus mux of the array into normal debug mode."""
        reg = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(reg, "Dbmid")
        for value in range(1 << dbmid.width):
            await self.csr_write(
                f"DEBUG_BUS_MUX:normal_id{value}",
                reg.addr,
                pack_fields(reg, {"Dbmmode": 1, "Dbmid": value}),
                length=reg.width_bytes,
            )
            self.dbmids_programmed += 1
        assert self.dbmids_programmed == (1 << dbmid.width), (
            f"the debug-bus mux sweep wrote {self.dbmids_programmed} of the "
            f"{1 << dbmid.width} values of the {dbmid.width}-bit Dbmid field"
        )

    async def _open_sink(self) -> None:
        """Give the trace RAM sink a window and enable it."""
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", _SINK_WINDOW_BYTES),
            ("Trdstramlimithigh", 0),
        ):
            reg = sink_register(name)
            await self.csr_write(
                f"{name}:window", reg.addr, field_word(reg, name, value), length=reg.width_bytes
            )
        await self._write_check(
            sink_register("Trdstramcontrol"),
            {"Trdstramactive": 1, "Trdstramenable": 1},
            "enable",
        )

    async def _open_funnel(self) -> None:
        await self._write_check(
            funnel_register("Trfunnelcontrol"),
            {"Trfunnelactive": 1, "Trfunnelenable": 1},
            "enable",
        )

    async def _enable_dst(self) -> None:
        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "enable",
        )

    async def _arm_cla(self) -> int:
        """Enable the CLA and return a LogicalOp value that activates node 0 EAP 0."""
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        eap = cla_register("CDbgNode0Eap0")
        status = cla_register("CDbgEapStatus")
        await self.csr_write(
            "CDbgNode0Eap0:reset", eap.addr, eap.reset_word, length=eap.width_bytes
        )
        await self.csr_write(
            "CDbgClaCtrlStatus:arm",
            ctrl.addr,
            pack_fields(
                ctrl,
                {
                    "EnableCla": 1,
                    "EnableEap": 1,
                    "DisableGlobalClockHalt": 1,
                    "DisableLocalClockHalt": 1,
                    "ClaChainLoopDelay": (ctrl.reset_word & chain.mask) >> chain.offset,
                },
            ),
            length=ctrl.width_bytes,
        )
        logical_op = cla_field(eap, "LogicalOp")
        activated = cla_field(status, "Node0Eap0")
        for value in range(1 << logical_op.width):
            await self.csr_write(
                f"CDbgNode0Eap0:op{value}",
                eap.addr,
                pack_fields(eap, {"LogicalOp": value, "DestNode": 0}),
                length=eap.width_bytes,
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            word = await self.csr_read(
                f"CDbgEapStatus:op{value}", status.addr, length=status.width_bytes
            )
            if word & activated.mask:
                self.value_checks += 1
                return value
        raise AssertionError(
            "no value of the 2-bit LogicalOp field activated node 0 EAP 0 with the CLA and "
            "its EAPs enabled, so no action of that pair can ever be driven and the trace "
            "cannot be started from the register interface"
        )

    # -- observation ------------------------------------------------------

    async def _sweep_actions(self, logical_op: int) -> None:
        """Drive Action0 over its whole range and watch the packetizer fill."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        dst = dst_register("Trdstcontrol")
        empty = reg_field(dst, "Trdstempty")
        for value in range(1 << action.width):
            await self.csr_write(
                f"CDbgNode0Eap0:action{value}",
                eap.addr,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                length=eap.width_bytes,
            )
            self.actions_swept += 1
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            for _ in range(_EMPTY_POLLS):
                if await self._read(dst, f"action{value}") & empty.mask == 0:
                    self.actions_accumulating += 1
                    self.value_checks += 1
                    break
        assert self.actions_swept == (1 << action.width), (
            f"the action sweep drove {self.actions_swept} of the {1 << action.width} values "
            f"of the {action.width}-bit Action0 field"
        )
        assert self.actions_accumulating > 0, (
            f"DST Trdstcontrol.Trdstempty @ 0x{dst.addr:08x} stayed 1 for all "
            f"{self.actions_swept} values of the Action0 field with the CLA armed, the DST "
            f"enabled uncompressed and every debug-bus mux in normal debug mode; no action "
            f"the register contract offers put data into the packetizer accumulator"
        )
        cocotb.log.info(
            "CHK-DST-TRACE-ACCUMULATE: %d of the %d values of the 6-bit Action0 field made "
            "the DUT clear DST Trdstcontrol.Trdstempty while node 0 EAP 0 was activating, "
            "so the debug bus reached the packetizer and its accumulator bank left the "
            "empty state; no action code is named by this sequence",
            self.actions_accumulating,
            self.actions_swept,
        )

    async def _bank_handoff(self) -> None:
        """The sink takes a filled bank, so the accumulator hands data on."""
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        wrap = reg_field(wp, "Trdstramwrap")
        word = wp.reset_word
        for _ in range(_HANDOFF_POLLS):
            word = await self._read(wp, "handoff")
            if word != wp.reset_word:
                break
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        assert word != wp.reset_word, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} still reads its RDL reset of "
            f"0x{wp.reset_word:08x} after the action sweep, so the trace RAM sink never "
            f"took a bank and the packetizer accumulator never handed one on"
        )
        assert 0 < word & pointer.mask <= _SINK_WINDOW_BYTES, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} reads 0x{word:08x}: the write pointer "
            f"field is 0x{word & pointer.mask:x}, not inside the 0x{_SINK_WINDOW_BYTES:x}-byte "
            f"window; a wrap flag alone does not show where the sink wrote"
        )
        self.sink_pointer = word
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-TRACE-BANK-HANDOFF: DST_SINK Trdstramwplow left its RDL reset and "
            "reads 0x%08x (write pointer 0x%x, hardware wrap flag %d) over the 0x%x-byte "
            "window, so the trace RAM sink took at least one filled bank from the "
            "packetizer accumulator and the bank went empty again",
            word,
            (word & pointer.mask) >> pointer.offset,
            (word & wrap.mask) >> wrap.offset,
            _SINK_WINDOW_BYTES,
        )

    async def _restore(self) -> None:
        for reg in (
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            dst_register("Trdstcontrol"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self.csr_write(
                f"{self._short(reg)}:restore",
                reg.addr,
                reg.reset_word,
                length=reg.width_bytes,
            )

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        await self._hold_dfd_clock()
        await self._idle_witness()
        await self._open_debug_bus()
        await self._open_sink()
        await self._open_funnel()
        await self._enable_dst()
        await self._sweep_actions(await self._arm_cla())
        await self._bank_handoff()
        await self._restore()
