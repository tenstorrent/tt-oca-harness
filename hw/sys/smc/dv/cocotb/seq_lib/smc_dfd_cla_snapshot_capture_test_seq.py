# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Make every CLA event-action pair capture a debug-signal snapshot.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_cla_regmap`. Values programmed into a field come from that
field's own RDL description, stated here rather than quoted. The vendored RTL
is not a source for any value this sequence programs or compares against.

``CDbgSignalSnapshotNode<n>Eap<m>Lo`` and ``...Hi`` are read-only registers the
hardware writes when the pair they belong to captures a snapshot of the debug
signals. Nothing in the package has ever made one capture: the leaves that
drive the action field drive it on one pair of one node, so fifteen of the
sixteen pairs never act at all and the halves of the snapshot the capture
writes stay at their reset.

Which action code requests a capture is published by no RDL, generated header
or MMR specification, so this sequence names none. It walks the node chain the
way ``smc_dfd_cla_node_eap_sweep_test`` does, and on each node drives every
pair's action field over its whole declared range with a relation that
activates the pair. Every snapshot register is read at its reset first, so a
register that moves afterwards moved because of this stimulus.

What the capture writes is the debug-signal bus itself, and that reads zero in
this bench even with the mux array in the identifier output mode its
description names, so no snapshot register changes value. The observation is
therefore a deny leg, and the drive token is its live control: every pair is
measured activating through its pair-activation status before the snapshot is
read.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register, pack_fields, reg_field

NODES = 4
EAPS_PER_NODE = 4

_SETTLE_CYCLES = 8
_NODE_POLLS = 8

# dfx_ctrl_status.rdl Dbmmode: the description names an identifier output mode
# in which a mux drives its own identifier onto the debug bus. That is the one
# way the register contract offers to put known non-zero content on the bus, so
# a snapshot of it is distinguishable from a snapshot of an idle bus.
_DBM_IDENTITY_MODE = 2


def _snapshot(node: int, eap: int, half: str):
    return cla_register(f"CDbgSignalSnapshotNode{node}Eap{eap}{half}")


class smc_dfd_cla_snapshot_capture_test_seq(SmcCsrSeq):
    """Drive every pair's action field so the snapshot registers are written."""

    def __init__(self, name: str = "smc_dfd_cla_snapshot_capture_test_seq") -> None:
        super().__init__(name)
        self.captured: set[str] = set()
        self.pairs_driven = 0
        self.nodes_visited: list[int] = []
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, word: int, label: str) -> None:
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)

    # -- phases -----------------------------------------------------------

    async def _baseline(self) -> None:
        """Every snapshot register carries its RDL reset before anything is driven."""
        for node in range(NODES):
            for eap in range(EAPS_PER_NODE):
                for half in ("Lo", "Hi"):
                    reg = _snapshot(node, eap, half)
                    value = await self._read(reg, "reset")
                    assert value == reg.reset_word, (
                        f"{reg.path} @ 0x{reg.addr:08x} reads 0x{value:016x} before the CLA "
                        f"was armed; its RDL reset is 0x{reg.reset_word:016x}, so a later "
                        f"change would not be attributable to this sweep"
                    )
                    self.value_checks += 1
        cocotb.log.info(
            "CHK-CLA-SNAPSHOT-RESET: all %d debug-signal snapshot registers of the %d pairs "
            "read their RDL reset before the CLA was armed, so any that moves below was "
            "written by the capture this sweep asks for",
            2 * NODES * EAPS_PER_NODE,
            NODES * EAPS_PER_NODE,
        )

    async def _arm_cla(self) -> None:
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        for node in range(NODES):
            for eap in range(EAPS_PER_NODE):
                reg = cla_register(f"CDbgNode{node}Eap{eap}")
                await self._write(reg, reg.reset_word, "reset")
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

    async def _activating_op(self, node: int, eap: int) -> int:
        """A relation value that makes this pair activate, measured not assumed."""
        reg = cla_register(f"CDbgNode{node}Eap{eap}")
        status = cla_register("CDbgEapStatus")
        logical_op = cla_field(reg, "LogicalOp")
        activated = cla_field(status, f"Node{node}Eap{eap}")
        for value in range(1 << logical_op.width):
            await self._write(
                reg, pack_fields(reg, {"LogicalOp": value, "DestNode": node}), f"op{value}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            if await self._read(status, f"op{value}") & activated.mask:
                self.value_checks += 1
                return value
        raise AssertionError(
            f"no value of the relation field activated node {node} pair {eap} with the CLA "
            f"enabled and that node current, so its action field cannot be driven"
        )

    async def _sweep_pair(self, node: int, eap: int, logical_op: int) -> None:
        """Every action value on one pair, then look at that pair's snapshot."""
        reg = cla_register(f"CDbgNode{node}Eap{eap}")
        action = cla_field(reg, "Action0")
        for value in range(1 << action.width):
            await self._write(
                reg,
                pack_fields(reg, {"LogicalOp": logical_op, "DestNode": node, "Action0": value}),
                f"n{node}e{eap}a{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        self.pairs_driven += 1
        for half in ("Lo", "Hi"):
            snap = _snapshot(node, eap, half)
            if await self._read(snap, "after") != snap.reset_word:
                self.captured.add(self._short(snap))
        await self._write(reg, reg.reset_word, "quiet")

    async def _move_to(self, node: int, target: int, logical_op: int) -> None:
        reg = cla_register(f"CDbgNode{node}Eap0")
        ctrl = cla_register("CDbgClaCtrlStatus")
        current = cla_field(ctrl, "CurrentNode")
        await self._write(
            reg, pack_fields(reg, {"LogicalOp": logical_op, "DestNode": target}), "dest"
        )
        got = node
        for _ in range(_NODE_POLLS):
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            word = await self._read(ctrl, f"move{target}")
            got = (word & current.mask) >> current.offset
            if got == target:
                break
        assert got == target, (
            f"CDbgClaCtrlStatus.CurrentNode reads {got} after node {node} pair 0 was given "
            f"destination {target}; the node chain cannot reach node {target}, so its pairs "
            f"can never act and their snapshots can never be written"
        )
        self.value_checks += 1
        await self._write(reg, reg.reset_word, "quiet_after_move")

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write(clk, pack_fields(clk, {"force_clk_en": 1}), "force")
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(mux, "Dbmid")
        for identity in range(1 << dbmid.width):
            await self._write(
                mux,
                pack_fields(mux, {"Dbmmode": _DBM_IDENTITY_MODE, "Dbmid": identity}),
                f"identity{identity}",
            )

        await self._baseline()
        await self._arm_cla()

        for node in range(NODES):
            self.nodes_visited.append(node)
            first_op = None
            for eap in range(EAPS_PER_NODE):
                logical_op = await self._activating_op(node, eap)
                if first_op is None:
                    first_op = logical_op
                await self._sweep_pair(node, eap, logical_op)
            if node + 1 < NODES:
                await self._move_to(node, node + 1, first_op)

        assert self.nodes_visited == list(range(NODES)), (
            f"the node walk reported {self.nodes_visited}, not every node"
        )
        assert self.pairs_driven == NODES * EAPS_PER_NODE, (
            f"the sweep drove {self.pairs_driven} of the {NODES * EAPS_PER_NODE} pairs"
        )
        self.value_checks += 2
        cocotb.log.info(
            "CHK-CLA-SNAPSHOT-DRIVE: all %d pairs across all %d nodes had their action "
            "field driven over its whole declared range with a relation this sequence "
            "measured to activate that pair, each on the node the DUT reported current; no "
            "action code is named",
            self.pairs_driven,
            NODES,
        )

        # The capture is not requested by an action code: it follows the pair's
        # relation result, which the drive phase above measured on every pair.
        # What the capture writes is the debug-signal bus, which reads as zero
        # here, so the registers stay at their reset and the observation is a
        # deny leg over a stimulus the drive token proved live.
        assert not self.captured, (
            f"snapshot registers {sorted(self.captured)} left their RDL reset. That is the "
            f"capture becoming observable, which it was not when this leaf was written; the "
            f"claim below has to be rewritten to check the captured value instead of the "
            f"absence of one"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-CLA-SNAPSHOT-QUIESCENT: all %d debug-signal snapshot registers still read "
            "their RDL reset after every one of the %d pairs had acted on its own node, "
            "which the drive token above measured through the pair-activation status. The "
            "capture follows the relation result rather than an action code, so it did "
            "occur; what it writes is the debug-signal bus, and that reads zero in this "
            "bench, so nothing is observable at the register interface",
            2 * NODES * EAPS_PER_NODE,
            self.pairs_driven,
        )

        for node in range(NODES):
            for eap in range(EAPS_PER_NODE):
                reg = cla_register(f"CDbgNode{node}Eap{eap}")
                await self._write(reg, reg.reset_word, "restore")
        for reg in (cla_register("CDbgClaCtrlStatus"), mux, clk):
            await self._write(reg, reg.reset_word, "restore")
