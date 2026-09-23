# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLA event-action-pair sweep over the four nodes of the SMC CLA.

Every address, field position, field width and reset value comes from the
generated register map through :mod:`seq_lib.smc_cla_regmap`, which reads the
PeakRDL IP-XACT export of ``smc_cla.rdl``. The vendored RTL is not a source for
any value this sequence programs or compares against.

``smc_cla.rdl`` gives the contract this sequence drives:

* ``CDbgClaCtrlStatus.EnableCla`` / ``.EnableEap`` arm the CLA and its EAPs,
  ``.CurrentNode`` is the hardware-driven id of the node whose EAPs are live,
  and ``.DisableGlobalClockHalt`` / ``.DisableLocalClockHalt`` keep a clock-halt
  action out of the bench's clocks while the EAPs are armed.
* ``CDbgNode<n>Eap<m>.LogicalOp`` is the "relation to be satisfied among events
  to activate the actions" and ``.DestNode`` selects the destination node.
* ``CDbgEapStatus.Node<n>Eap<m>`` is set by hardware when that EAP pair is
  activated, and the matching ``.Node<n>Eap<m>W2C`` bit resets the status.

``LogicalOp`` is two bits wide, so its four values are the whole relation set
the register contract offers; which of them is satisfied while no event is
selected is a property of the CLA, not something this sequence asserts. Each
EAP is driven over that whole range one value at a time, with every other EAP
of the node left at its RDL reset, and the sweep requires the hardware status
bit of every one of the 16 EAPs to have been observed set at least once and
then cleared by its own W2C bit.

The node walk uses the same mechanism: the EAP that activated on the current
node is re-programmed with ``DestNode`` pointing at the next node, and
``CurrentNode`` is polled until the DUT reports the move. A node that never
becomes current fails, so the sweep cannot quietly grade 4 EAPs as 16.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg

# Node and EAP counts, taken from the CDbgNode<n>Eap<m> registers the generated
# map declares rather than assumed.
NODES = 4
EAPS_PER_NODE = 4

# clk_smc_i cycles between arming a configuration and the first status read,
# and the number of status reads a pair gets before it is declared not to have
# activated. The CLA runs on its own gated clock and the EAP status is set
# combinationally from the logic-operation result, so this is a bounded poll on
# a hardware-driven register, not a delay standing in for a handshake.
_SETTLE_CYCLES = 8
_STATUS_POLLS = 4

# The same bounded poll for the hardware-driven CurrentNode field after a
# destination-node change.
_NODE_POLLS = 8


def _pack(reg: RdlReg, values: dict[str, int]) -> int:
    """Register word with the named fields set and every other bit 0."""
    word = 0
    for name, value in values.items():
        field = cla_field(reg, name)
        assert value < (1 << field.width), (
            f"{reg.path}.{name} is {field.width} bits, cannot hold {value}"
        )
        word |= value << field.offset
    return word


def _eap_reg(node: int, eap: int) -> RdlReg:
    return cla_register(f"CDbgNode{node}Eap{eap}")


def _ctrl_reg() -> RdlReg:
    return cla_register("CDbgClaCtrlStatus")


def _status_reg() -> RdlReg:
    return cla_register("CDbgEapStatus")


# LogicalOp is the whole relation set the register contract offers.
_LOGICAL_OPS = tuple(range(1 << cla_field(_eap_reg(0, 0), "LogicalOp").width))


class smc_dfd_cla_node_eap_sweep_test_seq(SmcCsrSeq):
    """Activate every EAP of every CLA node and clear it through its W2C bit."""

    def __init__(self, name: str = "smc_dfd_cla_node_eap_sweep_test_seq") -> None:
        super().__init__(name)
        self.pairs_activated = 0
        self.pairs_cleared = 0
        self.nodes_visited: list[int] = []
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    async def _read_status(self, label: str) -> int:
        reg = _status_reg()
        return await self.csr_read(f"EapStatus:{label}", reg.addr, length=reg.width_bytes)

    async def _read_current_node(self, label: str) -> int:
        reg = _ctrl_reg()
        word = await self.csr_read(f"ClaCtrlStatus:{label}", reg.addr, length=reg.width_bytes)
        field = cla_field(reg, "CurrentNode")
        return (word & field.mask) >> field.offset

    async def _write_eap(self, node: int, eap: int, values: dict[str, int], label: str) -> None:
        reg = _eap_reg(node, eap)
        await self.csr_write(
            f"Node{node}Eap{eap}:{label}", reg.addr, _pack(reg, values), length=reg.width_bytes
        )

    async def _clear_status_bit(self, node: int, eap: int) -> None:
        """Pulse the W2C bit of one pair and require the status bit to drop."""
        reg = _status_reg()
        w2c = cla_field(reg, f"Node{node}Eap{eap}W2C")
        status = cla_field(reg, f"Node{node}Eap{eap}")
        await self.csr_write(
            f"EapStatus:w2c_set_{node}_{eap}", reg.addr, w2c.mask, length=reg.width_bytes
        )
        await self.csr_write(f"EapStatus:w2c_clr_{node}_{eap}", reg.addr, 0, length=reg.width_bytes)
        after = await self._read_status(f"after_w2c_{node}_{eap}")
        assert after & status.mask == 0, (
            f"CDbgEapStatus.Node{node}Eap{eap} still reads 1 after its W2C bit "
            f"0x{w2c.mask:x} was pulsed; the status word is 0x{after:016x}"
        )
        self.value_checks += 1
        self.pairs_cleared += 1

    # -- phases -----------------------------------------------------------

    async def _arm_cla(self) -> None:
        """Enable the CLA and its EAPs with both clock-halt actions disabled."""
        reg = _ctrl_reg()
        chain_delay = cla_field(reg, "ClaChainLoopDelay")
        armed = _pack(
            reg,
            {
                "EnableCla": 1,
                "EnableEap": 1,
                "DisableGlobalClockHalt": 1,
                "DisableLocalClockHalt": 1,
                "ClaChainLoopDelay": (reg.reset_word & chain_delay.mask) >> chain_delay.offset,
            },
        )
        await self.csr_write("ClaCtrlStatus:arm", reg.addr, armed, length=reg.width_bytes)
        readback = await self.csr_read("ClaCtrlStatus:arm_rb", reg.addr, length=reg.width_bytes)
        writable = reg.rw_mask & ~cla_field(reg, "ClaLock").mask
        assert readback & writable == armed & writable, (
            f"CDbgClaCtrlStatus @ 0x{reg.addr:08x}: armed with 0x{armed & writable:x} but "
            f"reads 0x{readback & writable:x}, so the CLA is not in the state this sweep runs in"
        )
        lock = cla_field(reg, "ClaLock")
        assert readback & lock.mask == 0, (
            "CDbgClaCtrlStatus.ClaLock is set; enable_cla is latched forever and the "
            "restore at the end of this sweep cannot put the CLA back"
        )
        self.value_checks += 2

    async def _quiesce_node(self, node: int) -> None:
        """Put every EAP of one node back to its RDL reset."""
        for eap in range(EAPS_PER_NODE):
            reg = _eap_reg(node, eap)
            await self.csr_write(
                f"Node{node}Eap{eap}:reset", reg.addr, reg.reset_word, length=reg.width_bytes
            )

    async def _await_status(self, node: int, eap: int) -> bool:
        """Bounded poll of one pair's hardware status bit."""
        mask = cla_field(_status_reg(), f"Node{node}Eap{eap}").mask
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        for _ in range(_STATUS_POLLS):
            if await self._read_status(f"poll_{node}_{eap}") & mask:
                return True
        return False

    async def _sweep_pair(self, node: int, eap: int) -> int:
        """Drive one pair over the whole LogicalOp range; return an activating value."""
        activating = None
        for op in _LOGICAL_OPS:
            await self._write_eap(node, eap, {"LogicalOp": op, "DestNode": node}, f"op{op}")
            fired = await self._await_status(node, eap)
            # The status bit is re-asserted every clock the relation still holds,
            # so the pair goes back to its RDL reset before the W2C pulse.
            await self._write_eap(node, eap, {}, f"quiet_op{op}")
            if fired:
                activating = op if activating is None else activating
                await self._clear_status_bit(node, eap)
        assert activating is not None, (
            f"CDbgEapStatus.Node{node}Eap{eap} never read 1 with the CLA and its EAPs "
            f"enabled and CurrentNode = {node}, over all {len(_LOGICAL_OPS)} values of the "
            f"{cla_field(_eap_reg(node, eap), 'LogicalOp').width}-bit LogicalOp field; no "
            f"relation the register contract offers activated this pair"
        )
        self.pairs_activated += 1
        return activating

    async def _move_to_node(self, node: int, eap: int, op: int, target: int) -> None:
        """Send the current node to `target` through one activating EAP."""
        await self._write_eap(node, eap, {"LogicalOp": op, "DestNode": target}, "dest")
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        current = node
        for _ in range(_NODE_POLLS):
            current = await self._read_current_node(f"move_{node}_{target}")
            if current == target:
                break
        assert current == target, (
            f"CDbgClaCtrlStatus.CurrentNode reads {current} after node {node}'s EAP {eap} "
            f"activated with DestNode = {target}; the node walk cannot reach node {target}, "
            f"so its four EAPs would never be able to set their status"
        )
        self.value_checks += 1
        await self._write_eap(node, eap, {}, "quiet_after_move")
        await self._clear_status_bit(node, eap)

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        status = _status_reg()
        at_reset = await self._read_status("reset")
        live = 0
        for node in range(NODES):
            for eap in range(EAPS_PER_NODE):
                live |= cla_field(status, f"Node{node}Eap{eap}").mask
        assert at_reset & live == 0, (
            f"CDbgEapStatus reads 0x{at_reset:016x} before the CLA was enabled; "
            f"0x{at_reset & live:x} of the 16 pair-status bits are already set, so a later "
            f"'this pair activated' observation would not be attributable to this sweep"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-CLA-EAP-STATUS-RESET: all 16 CDbgEapStatus pair-activation bits read 0 "
            "before the CLA was armed, so every bit this sweep observes set was set by the "
            "configuration it programmed"
        )

        for node in range(NODES):
            await self._quiesce_node(node)
        await self._arm_cla()

        for node in range(NODES):
            current = await self._read_current_node(f"node{node}")
            assert current == node, (
                f"CDbgClaCtrlStatus.CurrentNode reads {current}, the sweep is about to "
                f"drive node {node}'s EAPs and their status can only be set while their "
                f"own node is current"
            )
            self.value_checks += 1
            self.nodes_visited.append(node)
            activating = [await self._sweep_pair(node, eap) for eap in range(EAPS_PER_NODE)]
            if node + 1 < NODES:
                await self._move_to_node(node, 0, activating[0], node + 1)

        assert self.pairs_activated == NODES * EAPS_PER_NODE, (
            f"{self.pairs_activated} of the {NODES * EAPS_PER_NODE} EAP pairs were observed "
            f"activating; the sweep drives every pair of every node"
        )
        assert self.nodes_visited == list(range(NODES)), (
            f"the node walk reported {self.nodes_visited}, not every node id 0..{NODES - 1}"
        )
        cocotb.log.info(
            "CHK-CLA-EAP-LOGICAL-OP-FIRE: each of the %d EAP pairs (%d nodes x %d pairs) "
            "was driven over all %d values of its LogicalOp field while its node was "
            "current, and the hardware set its CDbgEapStatus bit for at least one of them",
            self.pairs_activated,
            NODES,
            EAPS_PER_NODE,
            len(_LOGICAL_OPS),
        )
        cocotb.log.info(
            "CHK-CLA-EAP-STATUS-W2C: %d observed pair activations were each cleared by "
            "pulsing that pair's own W2C bit, and the status bit read 0 afterwards",
            self.pairs_cleared,
        )
        cocotb.log.info(
            "CHK-CLA-NODE-TRAVERSAL: CurrentNode reported node ids %s in turn, each move "
            "driven by an activating EAP of the then-current node whose DestNode named the "
            "next one",
            self.nodes_visited,
        )

        for node in range(NODES):
            await self._quiesce_node(node)
        ctrl = _ctrl_reg()
        await self.csr_write(
            "ClaCtrlStatus:restore", ctrl.addr, ctrl.reset_word, length=ctrl.width_bytes
        )
        final = await self._read_status("final")
        assert final & live == 0, (
            f"CDbgEapStatus reads 0x{final:016x} after every observed activation was "
            f"cleared and the CLA was disarmed; 0x{final & live:x} pair-status bits are "
            f"still set"
        )
        self.value_checks += 1
