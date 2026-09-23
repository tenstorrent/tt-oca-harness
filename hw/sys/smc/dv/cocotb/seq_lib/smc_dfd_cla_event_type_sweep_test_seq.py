# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the CLA event selectors of one node over every event index.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_cla_regmap`. The vendored RTL is not a source for any value
this sequence programs or compares against.

``CDbgNode<n>Eap<m>`` carries three six-bit selectors -- ``EventType0``,
``EventType1`` and ``EventType2``, each "Select a trigger event". Each one is
compared against every index of the CLA event bus, so the selector is a
one-hot pick enumerated over the whole field range, and a pair left at its
reset only ever exercises index zero.

This sequence drives each of the three selectors over all 64 values its field
offers, on every event-action pair of node 0, with the pair's relation left at
its RDL reset so the pair activates when and only when the selected event is
asserted. ``CDbgEapStatus`` is read after every value, so which indices carry
a live event is measured rather than assumed, and the pair is quiesced and its
status cleared between values so each observation stands alone.

The test holds the DUT to two things: every selector value is accepted and
read back exactly, and at least one event index is seen activating a pair.
Without the second, a selector that was wired to nothing would pass.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register, pack_fields, reg_field

# Pairs of node 0. The node walk itself is owned by
# smc_dfd_cla_node_eap_sweep_test; this sequence stays on the node that is
# current out of reset so every pair it drives can set its status.
_NODE = 0
_EAPS = 4

_SELECTORS = ("EventType0", "EventType1", "EventType2")

_SETTLE_CYCLES = 8


class smc_dfd_cla_event_type_sweep_test_seq(SmcCsrSeq):
    """Drive every event index into every event selector of node 0's pairs."""

    def __init__(self, name: str = "smc_dfd_cla_event_type_sweep_test_seq") -> None:
        super().__init__(name)
        self.selector_values = 0
        self.live_events: dict[str, set[int]] = {name: set() for name in _SELECTORS}
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, word: int, label: str) -> None:
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)

    async def _clear_status(self, eap: int) -> None:
        reg = cla_register("CDbgEapStatus")
        w2c = cla_field(reg, f"Node{_NODE}Eap{eap}W2C")
        await self._write(reg, w2c.mask, f"w2c_set{eap}")
        await self._write(reg, 0, f"w2c_clr{eap}")

    # -- phases -----------------------------------------------------------

    async def _arm_cla(self) -> None:
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        for eap in range(_EAPS):
            reg = cla_register(f"CDbgNode{_NODE}Eap{eap}")
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
        current = cla_field(ctrl, "CurrentNode")
        word = await self._read(ctrl, "current")
        node = (word & current.mask) >> current.offset
        assert node == _NODE, (
            f"CDbgClaCtrlStatus.CurrentNode reads {node} after the CLA was armed; this "
            f"sequence drives node {_NODE}'s pairs and their status can only be set while "
            f"their own node is current"
        )
        self.value_checks += 1

    async def _sweep_selector(self, selector: str) -> None:
        """Every value of one selector field, on every pair of the node."""
        status = cla_register("CDbgEapStatus")
        for eap in range(_EAPS):
            reg = cla_register(f"CDbgNode{_NODE}Eap{eap}")
            field = cla_field(reg, selector)
            activated = cla_field(status, f"Node{_NODE}Eap{eap}")
            for value in range(1 << field.width):
                word = pack_fields(reg, {selector: value, "DestNode": _NODE})
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
                    self.live_events[selector].add(value)
                    await self._write(reg, reg.reset_word, f"{selector}{value}_quiet")
                    await self._clear_status(eap)
            await self._write(reg, reg.reset_word, f"{selector}_quiet")

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
        for eap in range(_EAPS):
            live |= cla_field(status, f"Node{_NODE}Eap{eap}").mask
        at_reset = await self._read(status, "reset")
        assert at_reset & live == 0, (
            f"CDbgEapStatus reads 0x{at_reset:016x} before the CLA was armed; "
            f"0x{at_reset & live:x} of node {_NODE}'s pair-status bits are already set, so a "
            f"later activation would not be attributable to the selector this sweep programmed"
        )
        self.value_checks += 1

        await self._arm_cla()
        for selector in _SELECTORS:
            await self._sweep_selector(selector)

        width = cla_field(cla_register(f"CDbgNode{_NODE}Eap0"), _SELECTORS[0]).width
        expected = len(_SELECTORS) * _EAPS * (1 << width)
        assert self.selector_values == expected, (
            f"the sweep drove {self.selector_values} selector values; {len(_SELECTORS)} "
            f"selectors over {_EAPS} pairs at {1 << width} values each is {expected}"
        )
        cocotb.log.info(
            "CHK-CLA-EVENT-SELECT-SWEEP: each of the %d event selectors of all %d pairs of "
            "node %d took every one of the %d values its %d-bit field offers and read back "
            "exactly, %d writes in all; each value is one index of the CLA event bus the "
            "selector compares against",
            len(_SELECTORS),
            _EAPS,
            _NODE,
            1 << width,
            width,
            self.selector_values,
        )

        seen = {name: sorted(values) for name, values in self.live_events.items() if values}
        assert seen, (
            f"no value of any of the {len(_SELECTORS)} event selectors made the DUT set a "
            f"pair-activation bit over the whole {1 << width}-value range, so nothing proves "
            f"the selectors reach the event bus at all rather than being write-only storage"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-CLA-EVENT-SELECT-LIVE: the DUT set a pair-activation bit for the event "
            "indices %s, so the selectors pick a live event bus rather than storing a value "
            "nothing reads; each activation was cleared through the pair's own W2C bit "
            "before the next index was programmed",
            seen,
        )

        for eap in range(_EAPS):
            reg = cla_register(f"CDbgNode{_NODE}Eap{eap}")
            await self._write(reg, reg.reset_word, "restore")
        for reg in (cla_register("CDbgClaCtrlStatus"), mux, clk):
            await self._write(reg, reg.reset_word, "restore")
