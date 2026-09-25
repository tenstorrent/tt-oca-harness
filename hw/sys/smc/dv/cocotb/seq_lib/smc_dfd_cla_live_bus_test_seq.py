# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive the CLA's signal event generators, counters and action outputs on a moving bus.

Every address, field position, width, reset value and software-access type
comes from the generated register map through :mod:`seq_lib.smc_cla_regmap`
and :mod:`seq_lib.smc_rdl_regmap`. Values programmed into a field come from
that field's own RDL description or from the bus states this sequence
measures. The vendored RTL is not a source for any value this sequence
programs or compares against.

The other CLA leaves drive the event selectors, counters and actions with the
CLA's own debug-bus mux at its reset, which is off, so every signal event
generator sees a bus that never moves. This sequence first gives the CLA a
bus that moves between two measured states:

* the CLA mux is put in normal mode and the DEBUG_BUS_MUX identifier that feeds
  it is found by measurement, as the odd-offset walk of the concurrent trace
  leaf does; its identifier and normal modes put two different values on the
  bus, both read through the node 0 pair 0 debug-signal snapshot.

The generators are then programmed from those two states and the bus is
switched between them:

* ``CDbgSignalEdgeDetectCfg`` selects the lowest bit that differs between the
  states on both edge detectors, with opposite polarities, and the bus is
  switched again with the polarities swapped;
* ``CDbgAnyChangeLo`` masks the differing bits;
* ``CDbgTransitionMaskLo``, ``...FromValueLo`` and ``...ToValueLo`` describe the
  move from the first state to the second;
* the four arithmetic comparators are given a value between the two states
  and a value equal to the first, each under a mask of the low byte and under
  its complement, since the mask's sense is not stated by its description;
* ``CDbgLfsr`` is enabled from a non-zero seed.

The two debug-bus match events whose indices the RDL descriptions of
``CDbgSignalMask0Lo`` and ``CDbgSignalMask1Lo`` give are set to follow the two
states, and node 0 pair 1, selecting them, is walked over every value of its
relation field while the bus switches, once with the two events and once with
the same event twice.

The actions are then driven with an activating pair:

* ``CDbgClaXtriggerTimestretch`` is given a non-zero stretch for both cross
  triggers and both clock-halt disables in ``CDbgClaCtrlStatus`` are cleared,
  so the cross-trigger and clock-halt actions reach their stretch and halt
  logic; the halt output does not gate the SMC's own clocks in this bench;
* the action value that leaves counter 0 moving after the pair's enable is
  cleared is found by measurement, and is then written before every action value in turn, with the
  counter set back to its target after each pair, so every action meets a
  running counter and the running action meets a counter at its target;
* each counter is given a small target with ``ResetOnTarget`` set, and the
  action field is swept twice over its whole range;
* the action field is swept once more with the CLA enabled but ``EnableEap``
  clear, so the pair's relation and actions are evaluated without the
  enable;
* the action field is swept again with the lowest bit of
  ``DEBUG_CTRL.xtrig_clk_halt_mask`` set, which its description makes the
  enable for that position, and the mask is then cleared;
* the pair's two custom-action enables are each set on its own;
* ``CDbgClaTimestampConfig.Resync`` is set with no cross trigger arriving.

The CLA mux is then put in normal mode with ``Finegraintime`` set and moved
to its identifier mode; the snapshot has to move with each.

Last, node 0's other three pairs select the first match event under a
relation the match phase measured activating on it, with the bus left in the
state that event follows, and all four pairs of node 0 name destination 1,
so the chain moves to node 1 with node 0's pairs still holding, and pairs
whose relation holds sit on a node that is not current.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import (
    DBM_MODE_IDENTIFIER,
    DBM_MODE_NORMAL,
    checked_mask,
    cla_mux_normal,
    dfd_register,
    find_sampled_mux,
    pack_fields,
    set_dbm,
    traced_bus,
)

_SETTLE_CYCLES = 16
_BUS_SWITCHES = 16
_EAPS = 4
_COUNTERS = 4
# A small counter target, reached within a few increments.
_COUNTER_TARGET = 2
# A non-zero stretch for both cross triggers, in the units the description gives.
_XTRIGGER_STRETCH = 3
_LFSR_SEED = 1
# dfd_cla.rdl CDbgSignalMask0Lo and CDbgSignalMask1Lo: the event indices their
# descriptions give the two debug-bus match events.
_MATCH0_EVENT = 0x2
_MATCH1_EVENT = 0x4
# Bus switches under each relation value of the match-event pair.
_LOGIC_SWITCHES = 4
# dfx_ctrl_status.rdl DEBUG_CTRL.xtrig_clk_halt_mask: a set bit enables the
# halt for that position; the lowest position.
_HALT_MASK_LOWEST = 0x1
_LOW_BYTE = 0xFF
_WORD = (1 << 64) - 1


class smc_dfd_cla_live_bus_test_seq(SmcCsrSeq):
    """Program the CLA generators from a moving bus and drive its actions."""

    def __init__(self, name: str = "smc_dfd_cla_live_bus_test_seq") -> None:
        super().__init__(name)
        self.sampled_mux = -1
        self.states: tuple[int, int] = (0, 0)
        self.seen_states: set[int] = set()
        self.action_values = 0
        self.counter_after: list[int] = []
        self.node_after_move = -1
        self.running_action = -1
        self.logic_results: dict[tuple[int, int], bool] = {}
        self.mux_snapshots: list[int] = []
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, word: int, label: str) -> None:
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)

    async def _write_check(self, reg, values: dict[str, int], label: str) -> None:
        word = pack_fields(reg, values)
        await self._write(reg, word, label)
        readback = await self._read(reg, f"{label}_rb")
        mask = checked_mask(reg, values)
        assert readback & mask == word & mask, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: wrote 0x{word & mask:x} into its "
            f"software-writable bits, reads 0x{readback & mask:x}"
        )
        self.value_checks += 1

    async def _ctrl(self, eap_enable: int, halt_disable: int, label: str) -> None:
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        await self._write(
            ctrl,
            pack_fields(
                ctrl,
                {
                    "EnableCla": 1,
                    "EnableEap": eap_enable,
                    "DisableGlobalClockHalt": halt_disable,
                    "DisableLocalClockHalt": halt_disable,
                    "ClaChainLoopDelay": (ctrl.reset_word & chain.mask) >> chain.offset,
                },
            ),
            label,
        )

    async def _activating_op(self, eap: int) -> int:
        """A relation value measured to activate node 0 pair ``eap``."""
        reg = cla_register(f"CDbgNode0Eap{eap}")
        status = cla_register("CDbgEapStatus")
        logical_op = cla_field(reg, "LogicalOp")
        activated = cla_field(status, f"Node0Eap{eap}")
        for value in range(1 << logical_op.width):
            await self._write(
                reg, pack_fields(reg, {"LogicalOp": value, "DestNode": 0}), f"op{eap}_{value}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            if await self._read(status, f"op{eap}_{value}") & activated.mask:
                self.value_checks += 1
                return value
        raise AssertionError(
            f"no value of the LogicalOp field activated node 0 pair {eap}, so its relation "
            f"cannot be held true"
        )

    async def _sweep_actions(self, logical_op: int, label: str) -> None:
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"{label}{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            self.action_values += 1

    # -- phases -----------------------------------------------------------

    async def _moving_bus(self) -> None:
        await cla_mux_normal(self, "clamux")
        self.sampled_mux, first, second = await find_sampled_mux(self, _SETTLE_CYCLES, "live")
        self.states = (first, second)

    async def _program_generators(self) -> None:
        first, second = self.states
        diff = first ^ second
        bit = (diff & -diff).bit_length() - 1
        edge = cla_register("CDbgSignalEdgeDetectCfg")
        await self._write_check(
            edge,
            {"Signal0Select": bit, "PosEdgeSignal0": 1, "Signal1Select": bit, "PosEdgeSignal1": 0},
            "edge",
        )
        await self._write_check(cla_register("CDbgAnyChangeLo"), {"Mask": diff}, "change")
        await self._write_check(cla_register("CDbgTransitionMaskLo"), {"Value": diff}, "tmask")
        await self._write_check(
            cla_register("CDbgTransitionFromValueLo"), {"Value": first & diff}, "tfrom"
        )
        await self._write_check(
            cla_register("CDbgTransitionToValueLo"), {"Value": second & diff}, "tto"
        )
        low, high = sorted((first & _LOW_BYTE, second & _LOW_BYTE))
        between = (low + high) // 2 if high - low > 1 else high
        settings = (
            (between, _LOW_BYTE),
            (first & _LOW_BYTE, _LOW_BYTE),
            (between, _WORD & ~_LOW_BYTE),
            (first & _LOW_BYTE, _WORD & ~_LOW_BYTE),
        )
        for index, (value, mask) in enumerate(settings):
            await self._write_check(
                cla_register(f"CDbgCompare{index}Lo"), {"Value": value}, f"cmp{index}"
            )
            await self._write_check(
                cla_register(f"CDbgCompare{index}MaskLo"), {"Value": mask}, f"cmpmask{index}"
            )
        # The LFSR value is hardware-driven once enabled, so only the enable is
        # compared on readback.
        lfsr = cla_register("CDbgLfsr")
        active = cla_field(lfsr, "LfsrActive")
        await self._write(lfsr, pack_fields(lfsr, {"LfsrActive": 1, "Lfsr": _LFSR_SEED}), "lfsr")
        readback = await self._read(lfsr, "lfsr_rb")
        assert readback & active.mask, (
            f"{lfsr.path} @ 0x{lfsr.addr:08x}: LfsrActive was written 1 and reads 0 "
            f"(0x{readback:x})"
        )
        self.value_checks += 1

    async def _swap_edges(self) -> None:
        """The same selected bit with each edge detector's polarity reversed."""
        first, second = self.states
        diff = first ^ second
        bit = (diff & -diff).bit_length() - 1
        await self._write_check(
            cla_register("CDbgSignalEdgeDetectCfg"),
            {"Signal0Select": bit, "PosEdgeSignal0": 0, "Signal1Select": bit, "PosEdgeSignal1": 1},
            "edge_swapped",
        )

    async def _switch_bus(self) -> None:
        modes = (DBM_MODE_IDENTIFIER, DBM_MODE_NORMAL)
        for step in range(_BUS_SWITCHES):
            await set_dbm(
                self, {"Dbmmode": modes[step % 2], "Dbmid": self.sampled_mux}, f"switch{step}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            self.seen_states.add(await traced_bus(self, f"switch{step}"))
        assert set(self.states) <= self.seen_states, (
            f"the snapshot read {sorted(hex(v) for v in self.seen_states)} across "
            f"{_BUS_SWITCHES} switches, not both measured states "
            f"{[hex(v) for v in self.states]}"
        )
        self.value_checks += 1

    async def _match_logic(self) -> None:
        """Two match events on opposite bus states, under every relation value."""
        first, second = self.states
        diff = first ^ second
        for reg_name, value in (
            ("CDbgSignalMask0Lo", diff),
            ("CDbgSignalMatch0Lo", second & diff),
            ("CDbgSignalMask1Lo", diff),
            ("CDbgSignalMatch1Lo", first & diff),
        ):
            await self._write_check(cla_register(reg_name), {"Value": value}, reg_name)
        pair = cla_register("CDbgNode0Eap1")
        status = cla_register("CDbgEapStatus")
        activated = cla_field(status, "Node0Eap1")
        w2c = cla_field(status, "Node0Eap1W2C")
        relation = cla_field(pair, "LogicalOp")
        modes = (DBM_MODE_IDENTIFIER, DBM_MODE_NORMAL)
        for events in ((_MATCH0_EVENT, _MATCH1_EVENT), (_MATCH0_EVENT, _MATCH0_EVENT)):
            for value in range(1 << relation.width):
                await self._write(
                    pair,
                    pack_fields(
                        pair,
                        {
                            "LogicalOp": value,
                            "DestNode": 0,
                            "EventType0": events[0],
                            "EventType1": events[1],
                        },
                    ),
                    f"logic{events[1]}_{value}",
                )
                await self._write(status, w2c.mask, f"logic{events[1]}_{value}_w2c")
                await self._write(status, 0, f"logic{events[1]}_{value}_w2c0")
                for step in range(_LOGIC_SWITCHES):
                    await set_dbm(
                        self,
                        {"Dbmmode": modes[step % 2], "Dbmid": self.sampled_mux},
                        f"logic{events[1]}_{value}_{step}",
                    )
                    await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
                word = await self._read(status, f"logic{events[1]}_{value}")
                self.logic_results[(events[1], value)] = bool(word & activated.mask)
        await self._write(pair, pair.reset_word, "logic_quiet")
        assert any(self.logic_results.values()), (
            f"node 0 pair 1 never activated with its events on the two match events and its "
            f"relation walked over every value while the bus switched: {self.logic_results}"
        )
        self.value_checks += 1

    async def _counter_modes(self, logical_op: int) -> None:
        """Find the action that keeps counter 0 running, then pair it with every action."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        cfg = cla_register("CDbgClaCounter0Cfg")
        counter = cla_field(cfg, "Counter")
        at_target = pack_fields(
            cfg, {"Counter": _COUNTER_TARGET, "Target": _COUNTER_TARGET, "ResetOnTarget": 1}
        )
        # A target out of reach while the running action is looked for, so a
        # running counter always reads two different values.
        target = cla_field(cfg, "Target")
        upper = cla_field(cfg, "UpperTarget")
        await self._write_check(
            cfg,
            {
                "Counter": 0,
                "Target": (1 << target.width) - 1,
                "UpperTarget": (1 << upper.width) - 1,
                "ResetOnTarget": 0,
            },
            "run_cfg",
        )
        running = -1
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"run{value}",
            )
            # Actions stop with the pair's enable cleared; a counter still moving
            # after that runs on its own.
            await self._ctrl(0, 1, f"run{value}_off")
            first = await self._read(cfg, f"run{value}_a") & counter.mask
            second = await self._read(cfg, f"run{value}_b") & counter.mask
            await self._ctrl(1, 1, f"run{value}_on")
            if first != second:
                running = value
                break
        assert running >= 0, (
            f"no value of the {action.width}-bit Action0 field left counter 0 moving between two "
            f"reads after the pair's enable was cleared, so no action runs a counter on its own"
        )
        self.running_action = running
        for value in range(1 << action.width):
            for word, label in (
                (
                    pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": running}),
                    "a",
                ),
                (pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}), "b"),
            ):
                await self._write(eap, word, f"pair{value}{label}")
            await self._write(cfg, at_target, f"pair{value}_target")
        self.value_checks += 1

    async def _drive_actions(self, logical_op: int) -> None:
        await self._write_check(
            cla_register("CDbgClaXtriggerTimestretch"),
            {"Xtrigger0Stretch": _XTRIGGER_STRETCH, "Xtrigger1Stretch": _XTRIGGER_STRETCH},
            "stretch",
        )
        for index in range(_COUNTERS):
            await self._write_check(
                cla_register(f"CDbgClaCounter{index}Cfg"),
                {"Counter": 0, "Target": _COUNTER_TARGET, "UpperTarget": 0, "ResetOnTarget": 1},
                f"counter{index}",
            )
        await self._counter_modes(logical_op)
        await self._ctrl(1, 0, "halt_enabled")
        for sweep in range(2):
            await self._sweep_actions(logical_op, f"act{sweep}_")
        # The same sweep with the lowest bit of the cross-trigger clock-halt mask set.
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write_check(
            clk, {"force_clk_en": 1, "xtrig_clk_halt_mask": _HALT_MASK_LOWEST}, "halt_mask"
        )
        await self._sweep_actions(logical_op, "masked")
        await self._write_check(clk, {"force_clk_en": 1}, "halt_unmask")
        for index in range(_COUNTERS):
            reg = cla_register(f"CDbgClaCounter{index}Cfg")
            counter = cla_field(reg, "Counter")
            upper = cla_field(reg, "UpperCounter")
            word = await self._read(reg, f"counter{index}_after")
            value = ((word & upper.mask) >> upper.offset << counter.width) | (
                (word & counter.mask) >> counter.offset
            )
            self.counter_after.append(value)
            assert value <= _COUNTER_TARGET, (
                f"CDbgClaCounter{index}Cfg counts {value} after the action sweeps with "
                f"ResetOnTarget set and a target of {_COUNTER_TARGET}; the description of "
                f"ResetOnTarget makes the counter return to 0 on reaching its target"
            )
            self.value_checks += 1
        await self._ctrl(0, 1, "eap_disabled")
        await self._sweep_actions(logical_op, "noeap")
        await self._ctrl(1, 1, "rearm")

    async def _custom_and_resync(self, logical_op: int) -> None:
        eap = cla_register("CDbgNode0Eap0")
        for field in ("CustomAction0Enable", "CustomAction1Enable"):
            await self._write_check(
                eap, {"LogicalOp": logical_op, "DestNode": 0, field: 1}, f"{field}"
            )
        await self._write_check(cla_register("CDbgClaTimestampConfig"), {"Resync": 1}, "resync")

    async def _cla_mux_modes(self) -> None:
        """Take the CLA mux from normal mode with fine-grain time on to its identifier mode.

        The mux takes a mode only under its own identifier, so each mode is
        written once per identifier value, and the snapshot is read after each.
        """
        reg = cla_register("CDbgMuxSelLo")
        dbmid = cla_field(reg, "Dbmid")
        for mode, fine, label in (
            (DBM_MODE_NORMAL, 1, "fine"),
            (DBM_MODE_IDENTIFIER, 1, "ident"),
        ):
            for identity in range(1 << dbmid.width):
                await self._write(
                    reg,
                    pack_fields(reg, {"Dbmmode": mode, "Dbmid": identity, "Finegraintime": fine}),
                    f"{label}{identity}",
                )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            self.mux_snapshots.append(await traced_bus(self, f"clamux_{label}"))
        await cla_mux_normal(self, "clamux_back")

    async def _leave_node(self) -> None:
        op = await self._activating_op(0)
        # Pairs 1-3 select match event 0 twice, under a relation value the match
        # phase measured activating on it; the bus was left in the state that
        # event follows, so their relations hold. All four pairs name destination
        # 1, so no pair of the node that is left asks to stay on it.
        held = next(v for (e, v), ok in self.logic_results.items() if e == _MATCH0_EVENT and ok)
        for eap in range(1, _EAPS):
            reg = cla_register(f"CDbgNode0Eap{eap}")
            await self._write(
                reg,
                pack_fields(
                    reg,
                    {
                        "LogicalOp": held,
                        "DestNode": 1,
                        "EventType0": _MATCH0_EVENT,
                        "EventType1": _MATCH0_EVENT,
                    },
                ),
                f"dest{eap}",
            )
        eap0 = cla_register("CDbgNode0Eap0")
        await self._write(eap0, pack_fields(eap0, {"LogicalOp": op, "DestNode": 1}), "move")
        ctrl = cla_register("CDbgClaCtrlStatus")
        current = cla_field(ctrl, "CurrentNode")
        for poll in range(8):
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            word = await self._read(ctrl, f"move{poll}")
            self.node_after_move = (word & current.mask) >> current.offset
            if self.node_after_move == 1:
                break
        assert self.node_after_move == 1, (
            f"CDbgClaCtrlStatus.CurrentNode reads {self.node_after_move} after node 0 pair 0 "
            f"and node 0's other pairs were given relations holding on match event 0"
        )
        self.value_checks += 1

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write(clk, pack_fields(clk, {"force_clk_en": 1}), "force")
        await self._ctrl(1, 1, "arm")
        logical_op = await self._activating_op(0)

        await self._moving_bus()
        await self._program_generators()
        await self._switch_bus()
        await self._swap_edges()
        await self._switch_bus()
        cocotb.log.info(
            "CHK-CLA-LIVE-BUS: with the CLA mux in normal mode, DEBUG_BUS_MUX identifier %d "
            "was measured feeding the CLA; its two modes put 0x%016x and 0x%016x on the bus. "
            "The edge, change, transition, comparator and LFSR registers were programmed from "
            "those states and read back exactly, and %d switches under each edge polarity "
            "showed the bus in both",
            self.sampled_mux,
            *self.states,
            _BUS_SWITCHES,
        )
        await self._match_logic()
        cocotb.log.info(
            "CHK-CLA-LIVE-MATCH: the debug-bus match events 0x%x and 0x%x the RDL names were "
            "set to follow the two bus states, and node 0 pair 1 selecting them was driven "
            "through all %d values of its relation field with the bus switching; the pair "
            "activated under %s",
            _MATCH0_EVENT,
            _MATCH1_EVENT,
            len(self.logic_results),
            {f"{k[0]}/{k[1]}": v for k, v in self.logic_results.items()},
        )

        await self._drive_actions(logical_op)
        cocotb.log.info(
            "CHK-CLA-LIVE-ACTIONS: with a non-zero cross-trigger stretch, clock halt enabled "
            "and every counter given a target of %d with ResetOnTarget set, the action field "
            "was swept twice with an activating pair, once more with the lowest bit of "
            "DEBUG_CTRL.xtrig_clk_halt_mask set and read back, and once more with EnableEap "
            "clear, %d action writes; every counter read at or below its target afterwards "
            "(%s). Action %d was measured leaving counter 0 running, and was paired with every "
            "action value with the counter set back to its target after each pair",
            _COUNTER_TARGET,
            self.action_values,
            self.counter_after,
            self.running_action,
        )

        await self._custom_and_resync(logical_op)
        await self._cla_mux_modes()
        fine, ident = self.mux_snapshots
        assert fine != self.states[1] and ident != fine, (
            f"the node 0 pair 0 snapshot read 0x{fine:016x} with the CLA mux in normal mode and "
            f"fine-grain time on, against 0x{self.states[1]:016x} with it off, and 0x{ident:016x} "
            f"in identifier mode; each mode change has to move the bus"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-CLA-LIVE-MUXMODES: with the CLA mux in normal mode and Finegraintime set the "
            "snapshot read 0x%016x, not the 0x%016x measured with it clear, and with the mux "
            "then in identifier mode it read 0x%016x",
            fine,
            self.states[1],
            ident,
        )
        await self._leave_node()
        cocotb.log.info(
            "CHK-CLA-LIVE-NODE: each custom-action enable of node 0 pair 0 was set on its own "
            "and read back, Resync was set and read back, and with node 0's other pairs "
            "holding on the first match event and all four naming destination 1, the chain "
            "moved to node %d",
            self.node_after_move,
        )

        restore = [cla_register(f"CDbgNode0Eap{e}") for e in range(_EAPS)]
        restore += [cla_register(f"CDbgClaCounter{i}Cfg") for i in range(_COUNTERS)]
        restore += [
            cla_register(name)
            for name in (
                "CDbgSignalEdgeDetectCfg",
                "CDbgSignalMask0Lo",
                "CDbgSignalMatch0Lo",
                "CDbgSignalMask1Lo",
                "CDbgSignalMatch1Lo",
                "CDbgAnyChangeLo",
                "CDbgTransitionMaskLo",
                "CDbgTransitionFromValueLo",
                "CDbgTransitionToValueLo",
                "CDbgLfsr",
                "CDbgClaXtriggerTimestretch",
                "CDbgClaTimestampConfig",
                "CDbgMuxSelLo",
                "CDbgClaCtrlStatus",
            )
        ]
        for index in range(4):
            restore += [
                cla_register(f"CDbgCompare{index}Lo"),
                cla_register(f"CDbgCompare{index}MaskLo"),
            ]
        restore += [dfd_register("dfx_ctrl/DEBUG_BUS_MUX"), clk]
        for reg in restore:
            await self._write(reg, reg.reset_word, "restore")
