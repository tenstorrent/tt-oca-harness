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
  enable for every cross-trigger lane and the halt-clock request, and the
  mask is then cleared;
* the pair's two custom-action enables are each set on its own;
* ``CDbgClaTimestampConfig.Resync`` is set with no cross trigger arriving.

The CLA mux is then put in normal mode with ``Finegraintime`` set and moved
to its identifier mode; the snapshot has to move with each.

Node 0's other three pairs then select the first match event under a
relation the match phase measured activating on it, with the bus left in the
state that event follows, and all four pairs of node 0 name destination 1,
so the chain moves to node 1 with node 0's pairs still holding, and pairs
whose relation holds sit on a node that is not current.

Last, ``CDbgMuxSelLo`` is written with a distinct non-zero value in every
field and read back, then with the complement of each field and read back;
every field is read-write, so each readback is the written word. It is then
written in toggle mode under identifier 0, the identifier its description
gives the mode, read back, and the node 0 pair 0 snapshot is read 16 times.
The toggle-mode bus content is not described, so those snapshots are logged
and not compared.

With every CLA register back at its reset, the toggle-mode bus is then traced
uncompressed into the trace sink over the whole 16 KiB the eight trace RAMs
hold (``hw/sys/smc/doc/dfd.adoc``):

* ``CDbgMuxSelLo`` is written ``Dbmmode`` 3 under ``Dbmid`` 0 and read back,
  and ``Trdstcontrol.Trdstformat`` is written 0 with the register's other
  read-write fields as read, and read back;
* the sink window starts at 0 with its limit on the last word, both pointers
  at the start, and the sink enabled and active in mode 0 without stop on
  wrap; ``Trdstramempty`` is read after the enable and logged, since when it
  clears and sets is not documented;
* the DST is enabled and active, the ``Action0`` field of the current node's
  pair 0 is driven over its range, whose start encoding is not documented,
  and ``Trdstramwplow`` is polled until ``Trdstramwrap`` reads 1, every pointer
  sample before it no lower than the one before; the DST enable is then
  cleared and ``Trdstempty`` polled until it reads 1, and ``Trdstramempty``
  is read again and logged;
* the read pointer is placed on the final write pointer and ``Trdstramdata``
  is read 4096 times, the read pointer sampled every 64 reads and after the
  read from the limit; each sample is the start plus one word per read,
  modulo the window, so it wraps to the start once and ends where it began;
* the 4096 words are summarised (distinct values, per-bit toggle counts over
  bits 31:0, the first 16 words) and logged, not compared, since the
  toggle-mode bus content is not described;
* ``CDbgMuxSelLo``, ``Trdstcontrol``, ``Trdstramcontrol`` and the sink
  pointers are put back at their reset and read back.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import (
    DBM_MODE_IDENTIFIER,
    DBM_MODE_NORMAL,
    checked_mask,
    cla_mux_normal,
    dfd_register,
    dst_register,
    field_word,
    find_sampled_mux,
    funnel_register,
    pack_fields,
    reg_field,
    set_dbm,
    sink_register,
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
# dfx_ctrl_status.rdl DEBUG_CTRL.xtrig_clk_halt_mask: bit 0 enables every
# cross-trigger lane and the halt-clock request; the other bits have no effect.
_HALT_MASK_LOWEST = 0x1
_LOW_BYTE = 0xFF
_WORD = (1 << 64) - 1
# dfd_cla.rdl CDbgMuxSelLo.Dbmmode: 3 is toggle mode.
_DBM_MODE_TOGGLE = 3
# CDbgMuxSelLo field values with every field non-zero and the eight segment
# selects distinct; the second write is the complement of each field.
_MUXSEL_FIELDS = {
    **{f"Muxselseg{seg}": seg + 1 for seg in range(8)},
    "Rsvd159": 0x55,
    "Finegraintime": 1,
    "Dbmid": 0x2A,
    "Dbmmode": DBM_MODE_NORMAL,
}
_TOGGLE_SNAPSHOTS = 16
# dfd_dst.rdl Trdstformat: 0 is no compression.
_DST_FORMAT_NONE = 0
# smc_cla.adoc Trdstcontrol: the read-write image at reset, Trdstformat 3.
_DST_CONTROL_RESET_RW = 0x0300_0000
# dfd.adoc: eight trace RAMs of 256 x 64 bits, 16 KiB in total.
_TRACE_WINDOW_BYTES = 8 * 256 * 8
_TRACE_WORDS = _TRACE_WINDOW_BYTES // 4
_TRACE_LIMIT = _TRACE_WINDOW_BYTES - 4
_RP_SAMPLE_STRIDE = 64
_HEAD_WORDS = 16
# Bounds of the polls on the trace path.
_ACTIVATION_POLLS = 4
_WRAP_POLLS = 8192
_EMPTY_POLLS = 64
_WP_STABLE_POLLS = 16
_AXI_OKAY = 0
_SINK_POINTERS = (
    "Trdstramstartlow",
    "Trdstramstarthigh",
    "Trdstramlimitlow",
    "Trdstramlimithigh",
    "Trdstramwplow",
    "Trdstramwphigh",
    "Trdstramrplow",
    "Trdstramrphigh",
)
_FENCE = (
    "EXISTING_LEGS",
    "FIELD_WRITE",
    "TOGGLE",
    "RESTORE",
    "TOGGLE-CFG",
    "SINK-SETUP",
    "TRACE-FILLED",
    "READBACK",
    "CONTENT",
    "RESTORED",
)


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
        self.toggle_snapshots: list[int] = []
        self.value_checks = 0
        self.fence: list[tuple[str, int, int]] = []
        self._fence_accesses = 0
        self.okay_reads = 0
        self.dst_rw = 0
        self.trace_node = -1
        self.trace_op = -1
        self.activation_polls = 0
        self.wp_samples: list[int] = []
        self.trace_reissues = 0
        self.empty_polls = 0
        self.empty_last = 0
        self.wp_stable_polls = 0
        self.final_wp = -1
        self.ram_empty_before = -1
        self.ram_empty_after = -1
        self.trace_words: list[int] = []
        self.rp_samples: list[tuple[int, int]] = []

    def _mark(self, term: str) -> None:
        """Close a fence term with its sim time and the accesses it issued."""
        self.fence.append((term, int(get_sim_time("ps")), self.accesses - self._fence_accesses))
        self._fence_accesses = self.accesses

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

    async def _muxsel_fields(self) -> None:
        """Write every CDbgMuxSelLo field, read it back, then the same with each field complemented."""
        reg = cla_register("CDbgMuxSelLo")
        complement = {
            name: value ^ ((1 << cla_field(reg, name).width) - 1)
            for name, value in _MUXSEL_FIELDS.items()
        }
        assert complement["Dbmmode"] == DBM_MODE_IDENTIFIER
        pairs = []
        for values, label in ((_MUXSEL_FIELDS, "fields"), (complement, "fields_inv")):
            word = pack_fields(reg, values)
            await self._write(reg, word, label)
            readback = await self._read(reg, f"{label}_rb")
            assert readback == word, (
                f"{reg.path} @ 0x{reg.addr:08x} [{label}]: wrote 0x{word:016x}, every field "
                f"read-write, reads 0x{readback:016x} (differing bits 0x{readback ^ word:016x})"
            )
            pairs.append((word, readback))
            self.value_checks += 1
        (w1, r1), (w2, r2) = pairs
        cocotb.log.info(
            "CHK-CLA-LIVE-MUXSEL-FIELDS: write1=0x%016x rb1=0x%016x; write2=0x%016x "
            "rb2=0x%016x; every field of CDbgMuxSelLo, Muxselseg4..7 and Rsvd159 included, "
            "read back as written; access width %d bytes, one access per write and per read",
            w1,
            r1,
            w2,
            r2,
            reg.width_bytes,
        )

    async def _toggle_mode(self) -> None:
        """CDbgMuxSelLo in toggle mode under identifier 0, then 16 snapshots."""
        reg = cla_register("CDbgMuxSelLo")
        word = pack_fields(reg, {"Dbmmode": _DBM_MODE_TOGGLE, "Dbmid": 0})
        await self._write(reg, word, "toggle")
        readback = await self._read(reg, "toggle_rb")
        assert readback == word, (
            f"{reg.path} @ 0x{reg.addr:08x}: wrote Dbmmode=3 Dbmid=0 and every other field 0 "
            f"(0x{word:016x}), reads 0x{readback:016x}"
        )
        self.value_checks += 1
        mode = cla_field(reg, "Dbmmode")
        dbmid = cla_field(reg, "Dbmid")
        for index in range(_TOGGLE_SNAPSHOTS):
            self.toggle_snapshots.append(await traced_bus(self, f"toggle_snap{index}"))
        cocotb.log.info(
            "CHK-CLA-LIVE-TOGGLE-MODE: CDbgMuxSelLo rb Dbmmode=%d Dbmid=%d (0x%016x, every other "
            "field 0); snapshots %s (observed, not compared: LINKED-ISSUE SF-020, SF-024)",
            (readback & mode.mask) >> mode.offset,
            (readback & dbmid.mask) >> dbmid.offset,
            readback,
            " ".join(f"{v & 0xFFFFFFFF:08x}:{v >> 32:08x}" for v in self.toggle_snapshots),
        )

    # -- toggle-mode trace ------------------------------------------------

    async def _read_okay(self, reg, label: str) -> int:
        """Read a register and require an OKAY response."""
        item = SmcSysAxiItem(f"rd_{self._short(reg)}:{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = reg.addr
        item.length = reg.width_bytes
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == _AXI_OKAY, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: read answered resp={item.resp_code}, "
            f"not OKAY"
        )
        self.okay_reads += 1
        return item.rdata

    async def _toggle_uncompressed_cfg(self) -> None:
        """S2: the CLA mux in toggle mode and the DST set to no compression."""
        mux = cla_register("CDbgMuxSelLo")
        word = pack_fields(mux, {"Dbmmode": _DBM_MODE_TOGGLE, "Dbmid": 0})
        await self._write(mux, word, "trace_toggle")
        mux_rb = await self._read_okay(mux, "trace_toggle_rb")
        assert mux_rb == word, (
            f"{mux.path} @ 0x{mux.addr:08x}: wrote Dbmmode=3 Dbmid=0 and every other field 0 "
            f"(0x{word:016x}), reads 0x{mux_rb:016x}"
        )
        dst = dst_register("Trdstcontrol")
        fmt = reg_field(dst, "Trdstformat")
        mask = checked_mask(dst, {"Trdstformat": _DST_FORMAT_NONE})
        current = await self._read_okay(dst, "trace_fmt_cur")
        self.dst_rw = (current & mask & ~fmt.mask) | (_DST_FORMAT_NONE << fmt.offset)
        await self._write(dst, self.dst_rw, "trace_fmt")
        dst_rb = await self._read_okay(dst, "trace_fmt_rb")
        got_fmt = (dst_rb & fmt.mask) >> fmt.offset
        assert dst_rb & mask == self.dst_rw and got_fmt == _DST_FORMAT_NONE, (
            f"{dst.path} @ 0x{dst.addr:08x}: read 0x{current:08x}, wrote 0x{self.dst_rw:08x} "
            f"with Trdstformat 0 and the other read-write fields as read, reads 0x{dst_rb:08x} "
            f"(Trdstformat {got_fmt})"
        )
        self.value_checks += 2
        cocotb.log.info(
            "CHK-CLA-TOGGLE-UNCOMP-CFG: CDbgMuxSelLo=0x%x (wrote 0x%x), Trdstformat=%d "
            "(Trdstcontrol before 0x%08x, wrote 0x%08x, rb 0x%08x), resp OKAY on all 3 reads",
            mux_rb,
            word,
            got_fmt,
            current,
            self.dst_rw,
            dst_rb,
        )

    async def _arm_trace_pair(self) -> None:
        """Enable the CLA and find a relation value that activates the current node's pair 0."""
        ctrl = cla_register("CDbgClaCtrlStatus")
        current = cla_field(ctrl, "CurrentNode")
        await self._ctrl(1, 1, "trace_arm")
        self.trace_node = (await self._read(ctrl, "trace_node") & current.mask) >> current.offset
        node = self.trace_node
        reg = cla_register(f"CDbgNode{node}Eap0")
        status = cla_register("CDbgEapStatus")
        activated = cla_field(status, f"Node{node}Eap0")
        logical_op = cla_field(reg, "LogicalOp")
        for value in range(1 << logical_op.width):
            await self._write(
                reg, pack_fields(reg, {"LogicalOp": value, "DestNode": node}), f"trace_op{value}"
            )
            for poll in range(_ACTIVATION_POLLS):
                self.activation_polls = max(self.activation_polls, poll + 1)
                if await self._read(status, f"trace_op{value}_{poll}") & activated.mask:
                    self.trace_op = value
                    break
            if self.trace_op >= 0:
                break
        assert self.trace_op >= 0, (
            f"no value of the LogicalOp field activated node {node} pair 0 within "
            f"{_ACTIVATION_POLLS} CDbgEapStatus reads each, so no action can start the trace"
        )
        after = (await self._read(ctrl, "trace_node_after") & current.mask) >> current.offset
        assert after == node, (
            f"CDbgClaCtrlStatus.CurrentNode moved from {node} to {after} with node {node} "
            f"pair 0 naming its own node"
        )
        self.value_checks += 2

    async def _sink_setup(self) -> None:
        """S3: the sink window over the 16 KiB, pointers at the start, sink in RAM mode 0."""
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write_check(clk, {"force_clk_en": 1}, "trace_force")
        await self._write_check(
            funnel_register("Trfunnelcontrol"),
            {"Trfunnelactive": 1, "Trfunnelenable": 1},
            "trace_funnel",
        )
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, "trace_sink_off")
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", _TRACE_LIMIT),
            ("Trdstramlimithigh", 0),
            ("Trdstramwplow", 0),
            ("Trdstramrplow", 0),
        ):
            reg = sink_register(name)
            await self._write(reg, field_word(reg, name, value), "trace_sink")
        await self._write_check(
            control,
            {
                "Trdstramactive": 1,
                "Trdstramenable": 1,
                "Trdstrammode": 0,
                "Trdstramstoponwrap": 0,
            },
            "trace_sink_on",
        )
        empty = reg_field(control, "Trdstramempty")
        word = await self._read_okay(control, "trace_sink_empty")
        self.ram_empty_before = (word & empty.mask) >> empty.offset
        await self._arm_trace_pair()

    async def _trace_actions(self, label: str) -> None:
        reg = cla_register(f"CDbgNode{self.trace_node}Eap0")
        action = cla_field(reg, "Action0")
        for value in range(1 << action.width):
            await self._write(
                reg,
                pack_fields(
                    reg,
                    {"LogicalOp": self.trace_op, "DestNode": self.trace_node, "Action0": value},
                ),
                f"{label}{value}",
            )

    async def _trace_fill(self) -> tuple[int, int]:
        """S4: run the trace until the sink wraps, then stop it and wait for the DST to empty."""
        dst = dst_register("Trdstcontrol")
        mask = checked_mask(dst, {"Trdstenable": 1, "Trdstactive": 1})
        on = self.dst_rw | pack_fields(dst, {"Trdstenable": 1, "Trdstactive": 1})
        await self._write(dst, on, "trace_dst_on")
        rb = await self._read_okay(dst, "trace_dst_on_rb")
        assert rb & mask == on & mask, (
            f"{dst.path} @ 0x{dst.addr:08x}: wrote 0x{on:08x}, reads 0x{rb:08x}"
        )
        self.value_checks += 1
        await self._trace_actions("trace_start")

        wp = sink_register("Trdstramwplow")
        wp_field = reg_field(wp, "Trdstramwplow")
        wrap = reg_field(wp, "Trdstramwrap")
        last = -1
        peak = 0
        wrapped = False
        for poll in range(_WRAP_POLLS):
            word = await self._read_okay(wp, f"trace_wp{poll}")
            self.wp_samples.append(word)
            pointer = word & wp_field.mask
            assert pointer <= _TRACE_LIMIT, (
                f"Trdstramwplow sample {poll} reads 0x{word:08x}, pointer 0x{pointer:x} past "
                f"the limit 0x{_TRACE_LIMIT:x}"
            )
            if word & wrap.mask:
                wrapped = True
                break
            assert pointer >= peak, (
                f"Trdstramwplow sample {poll} reads pointer 0x{pointer:x} with Trdstramwrap 0, "
                f"below the earlier sample 0x{peak:x}"
            )
            peak = pointer
            if word == last:
                self.trace_reissues += 1
                await self._trace_actions(f"trace_re{self.trace_reissues}_")
            last = word
        assert wrapped, (
            f"Trdstramwrap stayed 0 through {_WRAP_POLLS} Trdstramwplow polls "
            f"({self.trace_reissues} action re-issues); last sample 0x{self.wp_samples[-1]:08x}, "
            f"highest pointer 0x{peak:x}"
        )
        self.value_checks += 1

        off = self.dst_rw | pack_fields(dst, {"Trdstenable": 0, "Trdstactive": 1})
        await self._write(dst, off, "trace_dst_stop")
        dst_empty = reg_field(dst, "Trdstempty")
        for poll in range(_EMPTY_POLLS):
            self.empty_last = await self._read_okay(dst, f"trace_dst_empty{poll}")
            self.empty_polls = poll + 1
            if self.empty_last & dst_empty.mask:
                break
        assert self.empty_last & dst_empty.mask, (
            f"Trdstempty stayed 0 through {_EMPTY_POLLS} Trdstcontrol polls after the DST "
            f"enable was cleared; last 0x{self.empty_last:08x}"
        )
        self.value_checks += 1

        previous = -1
        stable = False
        for poll in range(_WP_STABLE_POLLS):
            word = await self._read_okay(wp, f"trace_wp_final{poll}")
            self.wp_stable_polls = poll + 1
            if word == previous:
                stable = True
                break
            previous = word
        assert stable, (
            f"Trdstramwplow kept moving through {_WP_STABLE_POLLS} reads after Trdstempty read "
            f"1; last 0x{word:08x}"
        )
        self.final_wp = word & wp_field.mask

        control = sink_register("Trdstramcontrol")
        ram_empty = reg_field(control, "Trdstramempty")
        after = await self._read_okay(control, "trace_sink_after")
        self.ram_empty_after = (after & ram_empty.mask) >> ram_empty.offset
        self.value_checks += 1
        return peak, word

    def _rp_expected(self, start_index: int, reads: int) -> int:
        return ((start_index + reads) % _TRACE_WORDS) * 4

    async def _trace_read(self) -> int:
        """S5: 4096 Trdstramdata reads from the final write pointer, read pointer sampled."""
        rp = sink_register("Trdstramrplow")
        rp_field = reg_field(rp, "Trdstramrplow")
        data = sink_register("Trdstramdata")
        await self._write(rp, field_word(rp, "Trdstramrplow", self.final_wp), "trace_rp")
        initial = await self._read_okay(rp, "trace_rp_rb") & rp_field.mask
        assert initial == self.final_wp, (
            f"Trdstramrplow reads 0x{initial:x} after being written the final write pointer "
            f"0x{self.final_wp:x}"
        )
        start_index = initial // 4
        crossing = _TRACE_WORDS - start_index
        previous = initial
        wraps = 0
        for read in range(1, _TRACE_WORDS + 1):
            self.trace_words.append(await self._read_okay(data, f"trace_data{read}"))
            if read % _RP_SAMPLE_STRIDE and read != crossing:
                continue
            got = (await self._read_okay(rp, f"trace_rp{read}")) & rp_field.mask
            want = self._rp_expected(start_index, read)
            assert got == want, (
                f"Trdstramrplow reads 0x{got:x} after {read} Trdstramdata reads from 0x{initial:x}; "
                f"one word per read from the limit 0x{_TRACE_LIMIT:x} back to the start 0 gives "
                f"0x{want:x}"
            )
            if got < previous:
                wraps += 1
            previous = got
            self.rp_samples.append((read, got))
        assert len(self.trace_words) == _TRACE_WORDS
        assert wraps == 1 and previous == initial, (
            f"the read pointer wrapped {wraps} times over {_TRACE_WORDS} reads and ended at "
            f"0x{previous:x}, started at 0x{initial:x}"
        )
        self.value_checks += len(self.rp_samples) + 1
        return wraps

    def _content_summary(self) -> tuple[int, list[int]]:
        toggles = [0] * 32
        for a, b in zip(self.trace_words, self.trace_words[1:]):
            diff = a ^ b
            for bit in range(32):
                toggles[bit] += (diff >> bit) & 1
        return len(set(self.trace_words)), toggles

    async def _trace_restore(self) -> None:
        """S7: the CLA mux, the DST control, the sink control and pointers back at reset."""
        mux = cla_register("CDbgMuxSelLo")
        await self._write(mux, 0, "trace_restore")
        mux_rb = await self._read_okay(mux, "trace_restore_rb")
        assert mux_rb == 0, f"CDbgMuxSelLo reads 0x{mux_rb:016x} after being written 0"
        dst = dst_register("Trdstcontrol")
        mask = checked_mask(dst, {"Trdstformat": 3})
        await self._write(dst, _DST_CONTROL_RESET_RW, "trace_restore")
        dst_rb = await self._read_okay(dst, "trace_restore_rb")
        assert dst_rb & mask == _DST_CONTROL_RESET_RW, (
            f"Trdstcontrol reads 0x{dst_rb:08x} after being written its reset read-write image "
            f"0x{_DST_CONTROL_RESET_RW:08x}; read-write bits 0x{dst_rb & mask:08x}"
        )
        control = sink_register("Trdstramcontrol")
        control_mask = checked_mask(
            control,
            {"Trdstramactive": 0, "Trdstramenable": 0, "Trdstrammode": 0, "Trdstramstoponwrap": 0},
        )
        await self._write(control, 0, "trace_restore")
        control_rb = await self._read_okay(control, "trace_restore_rb")
        assert control_rb & control_mask == 0, (
            f"Trdstramcontrol reads 0x{control_rb:08x} after being written 0"
        )
        self.value_checks += 3
        for name in _SINK_POINTERS:
            reg = sink_register(name)
            field = reg_field(reg, name)
            await self._write(reg, 0, "trace_restore")
            got = await self._read_okay(reg, "trace_restore_rb")
            assert got & field.mask == 0, f"{name} reads 0x{got:08x} after being written 0"
            self.value_checks += 1
        for reg in (
            cla_register(f"CDbgNode{self.trace_node}Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            funnel_register("Trfunnelcontrol"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "trace_restore")

    async def _toggle_trace(self) -> None:
        await self._toggle_uncompressed_cfg()
        self._mark("TOGGLE-CFG")

        await self._sink_setup()
        self._mark("SINK-SETUP")

        peak, last_wp = await self._trace_fill()
        wp = sink_register("Trdstramwplow")
        wp_field = reg_field(wp, "Trdstramwplow")
        wrap = reg_field(wp, "Trdstramwrap")
        cocotb.log.info(
            "CHK-CLA-TRACE-FILL: pre-trace empty=%d (SF-032), WP samples %d monotonic from "
            "start over 0x0..0x%x (highest before the wrap 0x%x), wrap=%d at sample %d of the "
            "%d-poll bound, %d action re-issues; node %d pair 0 LogicalOp %d driven over "
            "Action0; Trdstempty=1 after stop within %d polls; post-trace Trdstramempty=%d "
            "(logged, SF-032); final WP 0x%x (raw 0x%08x)",
            self.ram_empty_before,
            len(self.wp_samples),
            _TRACE_LIMIT,
            peak,
            (self.wp_samples[-1] & wrap.mask) >> wrap.offset,
            len(self.wp_samples),
            _WRAP_POLLS,
            self.trace_reissues,
            self.trace_node,
            self.trace_op,
            self.empty_polls,
            self.ram_empty_after,
            self.final_wp,
            last_wp,
        )
        runs: list[list[int]] = []
        for w in self.wp_samples:
            if runs and runs[-1][0] == w:
                runs[-1][1] += 1
            else:
                runs.append([w, 1])
        cocotb.log.info(
            "CLA trace WP samples (pointer/wrap, xN repeats): %s",
            " ".join(
                f"{w & wp_field.mask:x}/{w & wrap.mask}" + (f"x{n}" if n > 1 else "")
                for w, n in runs
            ),
        )
        self._mark("TRACE-FILLED")

        okay_before = self.okay_reads
        wraps = await self._trace_read()
        cocotb.log.info(
            "CHK-CLA-TRACE-READ: %d/%d reads OKAY, RP samples %d/%d on schedule (every %d reads "
            "and after read %d from the limit), %d wrap, final RP==start RP 0x%x",
            len(self.trace_words),
            _TRACE_WORDS,
            len(self.rp_samples),
            len(self.rp_samples),
            _RP_SAMPLE_STRIDE,
            _TRACE_WORDS - self.final_wp // 4,
            wraps,
            self.rp_samples[-1][1],
        )
        assert self.okay_reads - okay_before == _TRACE_WORDS + len(self.rp_samples) + 1
        self._mark("READBACK")

        distinct, toggles = self._content_summary()
        mux = cla_register("CDbgMuxSelLo")
        mux_after = await self._read_okay(mux, "trace_content_mux")
        dst = dst_register("Trdstcontrol")
        fmt = reg_field(dst, "Trdstformat")
        fmt_after = (await self._read_okay(dst, "trace_content_fmt") & fmt.mask) >> fmt.offset
        assert mux_after == pack_fields(mux, {"Dbmmode": _DBM_MODE_TOGGLE, "Dbmid": 0}), (
            f"CDbgMuxSelLo reads 0x{mux_after:016x} after the read-out, not the toggle-mode word"
        )
        assert fmt_after == _DST_FORMAT_NONE, f"Trdstformat reads {fmt_after} after the read-out"
        self.value_checks += 2
        cocotb.log.info(
            "CHK-CLA-TOGGLE-TRACE-DATA: %d words, distinct=%d, toggles[31:0]=%s, head=%s; "
            "captured with CDbgMuxSelLo=0x%x and Trdstformat=%d (observed, not compared: "
            "LINKED-ISSUE SF-024)",
            len(self.trace_words),
            distinct,
            ",".join(str(toggles[bit]) for bit in range(31, -1, -1)),
            " ".join(f"{w:08x}" for w in self.trace_words[:_HEAD_WORDS]),
            mux_after,
            fmt_after,
        )
        self._mark("CONTENT")

        await self._trace_restore()
        self._mark("RESTORED")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 5 bounded waits, 0 expired: activation bound=%d CDbgEapStatus "
            "reads per LogicalOp value used=%d last=op %d active; wrap bound=%d Trdstramwplow "
            "polls used=%d last=0x%08x; Trdstempty bound=%d Trdstcontrol polls used=%d "
            "last=0x%08x; WP settle bound=%d reads used=%d last=0x%08x; sep_in_access=%dns per "
            "access (%d accesses, enforced by smc_sys_axi_agent); each expiry raises "
            "AssertionError with the last sample",
            _ACTIVATION_POLLS,
            self.activation_polls,
            self.trace_op,
            _WRAP_POLLS,
            len(self.wp_samples),
            self.wp_samples[-1],
            _EMPTY_POLLS,
            self.empty_polls,
            self.empty_last,
            _WP_STABLE_POLLS,
            self.wp_stable_polls,
            last_wp,
            self.cfg.axi_timeout_ns,
            self.accesses,
        )

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
        self._mark("EXISTING_LEGS")
        await self._muxsel_fields()
        self._mark("FIELD_WRITE")
        await self._toggle_mode()
        self._mark("TOGGLE")

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
        self._mark("RESTORE")
        await self._toggle_trace()
        terms = tuple(term for term, _, _ in self.fence)
        times = [t for _, t, _ in self.fence]
        assert terms == _FENCE, f"fence terms {terms}, expected {_FENCE}"
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times {self.fence}"
        assert all(count > 0 for _, _, count in self.fence), f"fence counts {self.fence}"
        cocotb.log.info(
            "CHK-NONVAC: %s (%s); %d accesses",
            "<".join(terms),
            ", ".join(f"{term} count={count} t={t}ps" for term, t, count in self.fence),
            self.accesses,
        )
