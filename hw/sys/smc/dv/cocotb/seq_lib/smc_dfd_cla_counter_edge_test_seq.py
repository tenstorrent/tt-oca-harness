# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Make the CLA counters count and walk the edge-detect configuration surface.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_cla_regmap`. The vendored RTL is not a source for any value
this sequence programs or compares against.

Two surfaces of the CLA's own comparison hardware, both reached from the same
armed CLA:

* **The four counters.** ``CDbgClaCounter<n>Cfg`` splits into fields software
  writes -- ``Target``, ``UpperTarget``, ``ResetOnTarget`` -- and fields
  hardware drives -- ``Counter`` and ``UpperCounter``, both ``sw = r``. The
  counters are moved by the CLA action bus, and which action code increments,
  clears or free-runs a counter is published by no RDL, generated header or
  MMR specification, so this sequence names none: it drives ``Action0`` over
  its whole 6-bit range with an activating pair and reads the hardware-driven
  counter fields back after each value. Every counter has to be seen counting
  and every counter has to be seen back at zero afterwards.

* **The edge-detect configuration.** ``CDbgSignalEdgeDetectCfg`` carries
  ``Signal0Select`` and ``Signal1Select``, each seven bits, which the RDL
  describes as choosing which signal to watch for an edge, and
  ``PosEdgeSignal0`` / ``PosEdgeSignal1``, which it describes as choosing
  between a rising and a falling edge. Every value of both select fields and
  both polarities is written and read back exactly. That is a claim
  about the configuration surface: which debug-bus signal each select value
  names is not in the register contract, so this sequence does not claim that
  an edge was detected, only that the selector took every value the field
  offers while the CLA was armed and the debug bus was moving.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register, pack_fields, reg_field

# CDbgClaCounter<n>Cfg instances the generated map declares.
_COUNTERS = 4

# Target the counters are given. Small enough that a counter driven by the
# action sweep reaches it, and non-zero so a counter sitting at its reset is
# distinguishable from one that has counted.
_COUNTER_TARGET = 0x10

_SETTLE_CYCLES = 16


def _counter_reg(index: int):
    return cla_register(f"CDbgClaCounter{index}Cfg")


def _edge_reg():
    return cla_register("CDbgSignalEdgeDetectCfg")


class smc_dfd_cla_counter_edge_test_seq(SmcCsrSeq):
    """Drive the CLA counters from the action bus and walk the edge-detect selects."""

    def __init__(self, name: str = "smc_dfd_cla_counter_edge_test_seq") -> None:
        super().__init__(name)
        self.counted: set[int] = set()
        self.cleared: set[int] = set()
        self.selects_walked = 0
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, word: int, label: str) -> None:
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)

    @staticmethod
    def _counter_value(reg, word: int) -> int:
        low = cla_field(reg, "Counter")
        high = cla_field(reg, "UpperCounter")
        return ((word & low.mask) >> low.offset) | (
            ((word & high.mask) >> high.offset) << low.width
        )

    # -- phases -----------------------------------------------------------

    async def _counters_at_reset(self) -> None:
        for index in range(_COUNTERS):
            reg = _counter_reg(index)
            value = self._counter_value(reg, await self._read(reg, "reset"))
            assert value == 0, (
                f"CDbgClaCounter{index}Cfg @ 0x{reg.addr:08x} reads {value} in its "
                f"hardware-driven counter fields before the CLA was armed; the RDL reset is "
                f"0, so a later 'this counter counted' observation would not be attributable"
            )
            self.value_checks += 1
        cocotb.log.info(
            "CHK-CLA-COUNTER-RESET: all %d CLA counters read 0 in their hardware-driven "
            "Counter and UpperCounter fields before the CLA was armed, so every count this "
            "sweep observes was produced by the configuration it programmed",
            _COUNTERS,
        )

    async def _program_targets(self) -> None:
        for index in range(_COUNTERS):
            reg = _counter_reg(index)
            await self._write(
                reg,
                pack_fields(reg, {"Target": _COUNTER_TARGET, "UpperTarget": 0, "ResetOnTarget": 0}),
                "target",
            )

    async def _arm_cla(self) -> int:
        """Enable the CLA and return a LogicalOp value that activates node 0 EAP 0."""
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        eap = cla_register("CDbgNode0Eap0")
        status = cla_register("CDbgEapStatus")
        await self._write(eap, eap.reset_word, "reset")
        await self._write(
            ctrl,
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
            "arm",
        )
        logical_op = cla_field(eap, "LogicalOp")
        activated = cla_field(status, "Node0Eap0")
        for value in range(1 << logical_op.width):
            await self._write(
                eap, pack_fields(eap, {"LogicalOp": value, "DestNode": 0}), f"op{value}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            if await self._read(status, f"op{value}") & activated.mask:
                self.value_checks += 1
                return value
        raise AssertionError(
            "no value of the 2-bit LogicalOp field activated node 0 EAP 0 with the CLA and "
            "its EAPs enabled, so no action of that pair can be driven and no counter can move"
        )

    async def _sweep_actions(self, logical_op: int) -> None:
        """Drive Action0 over its whole range and watch the counters move."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"action{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            for index in range(_COUNTERS):
                reg = _counter_reg(index)
                count = self._counter_value(reg, await self._read(reg, f"action{value}"))
                if count:
                    self.counted.add(index)
                elif index in self.counted:
                    self.cleared.add(index)

        missing = sorted(set(range(_COUNTERS)) - self.counted)
        assert not missing, (
            f"CLA counters {missing} never read non-zero in their hardware-driven counter "
            f"fields over the whole 6-bit Action0 range with the CLA armed and a target of "
            f"0x{_COUNTER_TARGET:x} programmed; the counters that did move were "
            f"{sorted(self.counted)}"
        )
        self.value_checks += _COUNTERS
        cocotb.log.info(
            "CHK-CLA-COUNTER-COUNTS: all %d CLA counters were read non-zero in their "
            "hardware-driven Counter and UpperCounter fields while Action0 was driven over "
            "its whole 6-bit range, so the action bus reaches every counter; no action code "
            "is named by this sequence",
            _COUNTERS,
        )

        unresettable = sorted(self.counted - self.cleared)
        assert not unresettable, (
            f"CLA counters {unresettable} were seen counting but never read back at zero "
            f"afterwards over the rest of the Action0 range, so no action the register "
            f"contract offers clears them; the counters that did clear were "
            f"{sorted(self.cleared)}"
        )
        self.value_checks += len(self.cleared)
        cocotb.log.info(
            "CHK-CLA-COUNTER-CLEARS: each of the %d counters that was seen counting was "
            "later read back at zero while the action sweep continued, so the counters are "
            "cleared by the action bus and not merely left running",
            len(self.cleared),
        )

    async def _sweep_edge_selects(self) -> None:
        """Every value of both edge-detect select fields, and both polarities."""
        reg = _edge_reg()
        select0 = cla_field(reg, "Signal0Select")
        select1 = cla_field(reg, "Signal1Select")
        assert select0.width == select1.width, (
            f"{reg.path}: Signal0Select is {select0.width} bits and Signal1Select is "
            f"{select1.width}; this sweep walks both over one range"
        )
        span = 1 << select0.width
        for value in range(span):
            word = pack_fields(
                reg,
                {
                    "Signal0Select": value,
                    "Signal1Select": span - 1 - value,
                    "PosEdgeSignal0": value & 1,
                    "PosEdgeSignal1": (value + 1) & 1,
                },
            )
            await self._write(reg, word, f"select{value}")
            readback = await self._read(reg, f"select{value}")
            assert readback & reg.rw_mask == word & reg.rw_mask, (
                f"{reg.path} @ 0x{reg.addr:08x}: wrote 0x{word & reg.rw_mask:x} into its "
                f"software-writable bits, reads 0x{readback & reg.rw_mask:x}"
            )
            self.selects_walked += 1
            self.value_checks += 1
        assert self.selects_walked == span, (
            f"the edge-detect sweep walked {self.selects_walked} of the {span} values of the "
            f"{select0.width}-bit select fields"
        )
        cocotb.log.info(
            "CHK-CLA-EDGE-SELECT-SWEEP: both %d-bit edge-detect select fields took every one "
            "of their %d values and both polarity bits took both of theirs, each read back "
            "exactly, with the CLA armed and the debug bus in normal debug mode; which "
            "debug-bus signal a select value names is not in the register contract, so this "
            "is a claim about the configuration surface and not about a detected edge",
            select0.width,
            span,
        )

    async def _restore(self) -> None:
        for reg in [_counter_reg(i) for i in range(_COUNTERS)] + [
            _edge_reg(),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ]:
            await self._write(reg, reg.reset_word, "restore")

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write(clk, pack_fields(clk, {"force_clk_en": 1}), "force")
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(mux, "Dbmid")
        for value in range(1 << dbmid.width):
            await self._write(
                mux, pack_fields(mux, {"Dbmmode": 1, "Dbmid": value}), f"normal_id{value}"
            )

        await self._counters_at_reset()
        await self._program_targets()
        logical_op = await self._arm_cla()
        await self._sweep_edge_selects()
        await self._sweep_actions(logical_op)
        await self._restore()
