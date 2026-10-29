# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the CLA event selectors of every node over every event index.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_cla_regmap`. The vendored RTL is not a source for any value
this sequence programs or compares against.

``CDbgNode<n>Eap<m>`` carries three six-bit selectors -- ``EventType0``,
``EventType1`` and ``EventType2`` -- which the RDL describes as each choosing
a trigger event. Each one is compared against every index of the CLA event
bus, so the selector is a one-hot pick enumerated over the whole field range,
and a pair left at its reset only ever exercises index zero.

This sequence drives each of the three selectors over all 64 values its field
offers, on every event-action pair of every node. ``CDbgEapStatus`` is read
after every value, so which indices carry a live event is measured rather than
assumed, and the pair is quiesced and its status cleared between values so each
observation stands alone.

``EventType0`` and ``EventType1`` are swept with the pair's relation left at
its RDL reset. The RDL names ``EventType2`` only as an argument of ``Udf``
("User Defined Function with event type 0, 1, and 2 as arguments",
``dfd_cla.rdl``), and neither ``LogicalOp`` nor ``Udf`` has an encoding in the
RDL, so the relation for the ``EventType2`` sweep is measured: with the other
two selectors on an index the first two sweeps saw idle, ``LogicalOp`` and
``Udf`` are walked over their RDL field ranges until pair 0 activates with
``EventType2`` on an index seen live and stays idle with it on the idle index.
Each candidate is probed from the pair's reset word, and the live index is
probed again written over the idle one, as the sweep writes it, so an
activation that depends on the pair's previous programming is not taken as the
relation. The ``EventType2`` sweep then runs under that relation.

A node's pairs can only set their status while that node is current, so the
sweep walks the nodes in order: once a node's selectors are done, one of its
pairs is re-programmed with an event index the sweep saw live and
``DestNode`` pointing at the next node, and ``CurrentNode`` is polled until
the DUT reports the move. A node that never becomes current fails.

The test holds the DUT to two things: every selector value is accepted and
read back exactly, and on every node each of the three selectors has at least
one event index seen activating a pair and at least one index seen leaving it
idle. Without the second, a selector that was wired to nothing, or a status bit
that sets whatever the selector holds, would pass.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register, pack_fields, reg_field

_NODES = 4
_EAPS = 4

_DIRECT_SELECTORS = ("EventType0", "EventType1")
_UDF_SELECTOR = "EventType2"
_SELECTORS = (*_DIRECT_SELECTORS, _UDF_SELECTOR)

_SETTLE_CYCLES = 8

# Bounded poll of the hardware-driven CurrentNode field after a
# destination-node change.
_NODE_POLLS = 8


class smc_dfd_cla_event_type_sweep_test_seq(SmcCsrSeq):
    """Drive every event index into every event selector of every node's pairs."""

    def __init__(self, name: str = "smc_dfd_cla_event_type_sweep_test_seq") -> None:
        super().__init__(name)
        self.selector_values = 0
        self.live_events: dict[int, dict[str, set[int]]] = {
            node: {name: set() for name in _SELECTORS} for node in range(_NODES)
        }
        self.relations: dict[int, dict[str, int]] = {}
        self.node_readbacks: list[int] = []
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, word: int, label: str) -> None:
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)

    async def _read_current_node(self, label: str) -> int:
        ctrl = cla_register("CDbgClaCtrlStatus")
        current = cla_field(ctrl, "CurrentNode")
        return ((await self._read(ctrl, label)) & current.mask) >> current.offset

    async def _clear_status(self, node: int, eap: int) -> None:
        reg = cla_register("CDbgEapStatus")
        w2c = cla_field(reg, f"Node{node}Eap{eap}W2C")
        await self._write(reg, w2c.mask, f"w2c_set{node}_{eap}")
        await self._write(reg, 0, f"w2c_clr{node}_{eap}")

    async def _quiesce_all(self, label: str) -> None:
        for node in range(_NODES):
            for eap in range(_EAPS):
                reg = cla_register(f"CDbgNode{node}Eap{eap}")
                await self._write(reg, reg.reset_word, label)

    async def _activates(self, node: int, eap: int, fields: dict[str, int], label: str) -> bool:
        """Program one pair, read its status bit, and quiesce and clear it if set."""
        reg = cla_register(f"CDbgNode{node}Eap{eap}")
        status = cla_register("CDbgEapStatus")
        activated = cla_field(status, f"Node{node}Eap{eap}")
        await self._write(reg, pack_fields(reg, {**fields, "DestNode": node}), label)
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        if not await self._read(status, label) & activated.mask:
            return False
        await self._write(reg, reg.reset_word, f"{label}_quiet")
        await self._clear_status(node, eap)
        return True

    # -- phases -----------------------------------------------------------

    async def _arm_cla(self) -> None:
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        await self._quiesce_all("reset")
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
        node = await self._read_current_node("current")
        assert node == 0, (
            f"CDbgClaCtrlStatus.CurrentNode reads {node} after the CLA was armed; the sweep "
            f"starts on node 0 and a node's pairs can only set their status while their own "
            f"node is current"
        )
        self.value_checks += 1

    async def _sweep_selector(self, node: int, selector: str, relation: dict[str, int]) -> None:
        """Every value of one selector field, on every pair of one node."""
        status = cla_register("CDbgEapStatus")
        for eap in range(_EAPS):
            reg = cla_register(f"CDbgNode{node}Eap{eap}")
            field = cla_field(reg, selector)
            activated = cla_field(status, f"Node{node}Eap{eap}")
            for value in range(1 << field.width):
                word = pack_fields(reg, {**relation, selector: value, "DestNode": node})
                await self._write(reg, word, f"{selector}{value}")
                readback = await self._read(reg, f"{selector}{value}_rb")
                assert readback & reg.rw_mask == word & reg.rw_mask, (
                    f"{reg.path} @ 0x{reg.addr:08x}: wrote 0x{word & reg.rw_mask:x} with "
                    f"{selector} = {value}, reads 0x{readback & reg.rw_mask:x}"
                )
                self.selector_values += 1
                self.value_checks += 1
                await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
                if await self._read(status, f"{selector}{value}") & activated.mask:
                    self.live_events[node][selector].add(value)
                    await self._write(reg, reg.reset_word, f"{selector}{value}_quiet")
                    await self._clear_status(node, eap)
            await self._write(reg, reg.reset_word, f"{selector}_quiet")

    def _check_live(self, node: int, selector: str) -> None:
        width = cla_field(cla_register(f"CDbgNode{node}Eap0"), selector).width
        live = self.live_events[node][selector]
        assert live, (
            f"no value of {selector} made the DUT set a pair-activation bit of node {node} over "
            f"the whole field range, so nothing proves node {node}'s {selector} reaches the "
            f"event bus rather than being write-only storage"
        )
        assert len(live) < 1 << width, (
            f"every one of the {1 << width} values of {selector} set a pair-activation bit of "
            f"node {node}, so the status does not depend on which event the selector picks"
        )
        self.value_checks += 2

    async def _find_relation(self, node: int) -> dict[str, int]:
        """LogicalOp and Udf under which EventType2 alone decides whether pair 0 activates."""
        reg = cla_register(f"CDbgNode{node}Eap0")
        width = cla_field(reg, _UDF_SELECTOR).width
        live = self.live_events[node]
        hot = min(live[_DIRECT_SELECTORS[0]])
        idle_set = set(range(1 << width)).difference(*(live[s] for s in _DIRECT_SELECTORS))
        assert idle_set, (
            f"every event index was live on {' or '.join(_DIRECT_SELECTORS)} of node {node}, "
            f"so no idle index is left to hold them on while {_UDF_SELECTOR} is swept"
        )
        idle = min(idle_set)
        op = cla_field(reg, "LogicalOp")
        udf = cla_field(reg, "Udf")
        candidates = [(o, u) for o in range(1 << op.width) for u in range(1 << udf.width)]
        if self.relations:
            last = self.relations[node - 1]
            candidates.insert(0, (last["LogicalOp"], last["Udf"]))
        for o, u in candidates:
            relation = {
                "LogicalOp": o,
                "Udf": u,
                _DIRECT_SELECTORS[0]: idle,
                _DIRECT_SELECTORS[1]: idle,
            }
            label = f"rel{o}_{u}"
            hot_fields = {**relation, _UDF_SELECTOR: hot}
            await self._write(reg, reg.reset_word, f"{label}_reset")
            if (
                await self._activates(node, 0, hot_fields, f"{label}_hot")
                and not await self._activates(
                    node, 0, {**relation, _UDF_SELECTOR: idle}, f"{label}_idle"
                )
                and await self._activates(node, 0, hot_fields, f"{label}_hot_over_idle")
            ):
                await self._write(reg, reg.reset_word, f"{label}_quiet")
                self.relations[node] = relation
                return relation
        await self._write(reg, reg.reset_word, "rel_quiet")
        raise AssertionError(
            f"no LogicalOp and Udf value made node {node}'s pair 0 activate with "
            f"{_UDF_SELECTOR} = {hot} (seen live) and stay idle with {_UDF_SELECTOR} = {idle} "
            f"(seen idle), with {' and '.join(_DIRECT_SELECTORS)} both on {idle}; nothing "
            f"shows {_UDF_SELECTOR} reaching the pair's relation"
        )

    async def _sweep_node(self, node: int) -> None:
        for selector in _DIRECT_SELECTORS:
            await self._sweep_selector(node, selector, {})
            self._check_live(node, selector)
        relation = await self._find_relation(node)
        await self._sweep_selector(node, _UDF_SELECTOR, relation)
        self._check_live(node, _UDF_SELECTOR)

    async def _move_to_node(self, node: int, target: int) -> None:
        """Send the current node to `target` through pair 0 and a live event index."""
        selector, values = next(
            (name, values) for name, values in self.live_events[node].items() if values
        )
        reg = cla_register(f"CDbgNode{node}Eap0")
        await self._write(
            reg, pack_fields(reg, {selector: min(values), "DestNode": target}), "dest"
        )
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        current = node
        for _ in range(_NODE_POLLS):
            current = await self._read_current_node(f"move_{node}_{target}")
            if current == target:
                break
        self.node_readbacks.append(current)
        assert current == target, (
            f"CDbgClaCtrlStatus.CurrentNode reads {current} after node {node}'s pair 0 was "
            f"given live event index {min(values)} on {selector} with DestNode = {target}; the "
            f"node walk cannot reach node {target}, so its pairs would never be able to set "
            f"their status"
        )
        self.value_checks += 1
        await self._write(reg, reg.reset_word, "quiet_after_move")
        await self._clear_status(node, 0)

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

        status = cla_register("CDbgEapStatus")
        live = 0
        for node in range(_NODES):
            for eap in range(_EAPS):
                live |= cla_field(status, f"Node{node}Eap{eap}").mask
        at_reset = await self._read(status, "reset")
        assert at_reset & live == 0, (
            f"CDbgEapStatus reads 0x{at_reset:016x} before the CLA was armed; "
            f"0x{at_reset & live:x} of the pair-status bits are already set, so a later "
            f"activation would not be attributable to the selector this sweep programmed"
        )
        self.value_checks += 1

        await self._arm_cla()
        for node in range(_NODES):
            await self._sweep_node(node)
            if node + 1 < _NODES:
                await self._move_to_node(node, node + 1)

        width = cla_field(cla_register("CDbgNode0Eap0"), _SELECTORS[0]).width
        expected = len(_SELECTORS) * _NODES * _EAPS * (1 << width)
        assert self.selector_values == expected, (
            f"the sweep drove {self.selector_values} selector values; {len(_SELECTORS)} "
            f"selectors over {_NODES} nodes x {_EAPS} pairs at {1 << width} values each is "
            f"{expected}"
        )
        cocotb.log.info(
            "CHK-CLA-EVENT-SELECT-SWEEP: each of the %d event selectors of all %d pairs of "
            "each of the %d nodes took every one of the %d values its %d-bit field offers "
            "and read back exactly, %d writes in all; each value is one index of the CLA "
            "event bus the selector compares against, and CurrentNode read back %s after each "
            "node move",
            len(_SELECTORS),
            _EAPS,
            _NODES,
            1 << width,
            width,
            self.selector_values,
            self.node_readbacks,
        )

        seen = {
            node: {name: sorted(values) for name, values in by_selector.items()}
            for node, by_selector in self.live_events.items()
        }
        cocotb.log.info(
            "CHK-CLA-EVENT-SELECT-LIVE: on every node each of the %d selectors set a "
            "pair-activation bit for at least one event index and left at least one index "
            "idle; the live indices were %s, with %s swept under the measured relation %s "
            "and the others under the RDL reset relation, so each selector picks a live "
            "event bus rather than storing a value nothing reads; each activation was "
            "cleared through the pair's own W2C bit before the next index was programmed",
            len(_SELECTORS),
            seen,
            _UDF_SELECTOR,
            self.relations,
        )

        await self._quiesce_all("restore")
        for reg in (cla_register("CDbgClaCtrlStatus"), mux, clk):
            await self._write(reg, reg.reset_word, "restore")
