# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus for the CLA action-release leaves: node 0 pair 0 armed with one action.

The pair is fired by sweeping `LogicalOp` until `CDbgEapStatus.Node0Eap0`
reads 1 and quieted by selecting a relation value that did not fire, so the
action stays selected while the relation is false. The W2C bit of the pair is
pulsed through `CDbgEapStatus`.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import pack_fields

# cla_pkg.svh action encodings written into CDbgNode0Eap0.Action0.
ACTION_CLOCK_HALT = 1
ACTION_DEBUG_INTERRUPT = 2
SETTLE_CYCLES = 8
SAMPLE_CYCLES = 20
_STATUS_POLLS = 4


def _short(reg) -> str:
    return reg.path.rsplit("/", 1)[1]


class SmcDfdClaActionSeq(SmcCsrSeq):
    """CLA register helpers and the fire/quiet steps of node 0 pair 0."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.samples: list[str] = []

    @staticmethod
    def _eap():
        return cla_register("CDbgNode0Eap0")

    @staticmethod
    def _ctrl():
        return cla_register("CDbgClaCtrlStatus")

    @staticmethod
    def _status():
        return cla_register("CDbgEapStatus")

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{_short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, values: dict[str, int], label: str) -> None:
        await self.csr_write(
            f"{_short(reg)}:{label}", reg.addr, pack_fields(reg, values), length=reg.width_bytes
        )

    async def _write_ctrl(
        self, enable_cla: int, enable_eap: int, global_halt_disable: int, label: str
    ) -> None:
        ctrl = self._ctrl()
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        await self._write(
            ctrl,
            {
                "EnableCla": enable_cla,
                "EnableEap": enable_eap,
                "DisableGlobalClockHalt": global_halt_disable,
                "DisableLocalClockHalt": 1,
                "ClaChainLoopDelay": (ctrl.reset_word & chain.mask) >> chain.offset,
            },
            label,
        )

    async def _w2c(self, label: str) -> None:
        status = self._status()
        w2c = cla_field(status, "Node0Eap0W2C")
        await self.csr_write(f"EapStatus:w2c_set_{label}", status.addr, w2c.mask, length=8)
        await self.csr_write(f"EapStatus:w2c_clr_{label}", status.addr, 0, length=8)

    async def _status_bit(self, label: str) -> int:
        mask = cla_field(self._status(), "Node0Eap0").mask
        return 1 if await self._read(self._status(), label) & mask else 0

    @staticmethod
    def _pin(name: str) -> int:
        value = getattr(cocotb.top, name).value
        return int(value) if value.is_resolvable else -1

    async def _fire(self, action: int, label: str) -> tuple[int, int]:
        """Sweep LogicalOp with one action; return (activating op, a quiet op)."""
        eap = self._eap()
        ops = range(1 << cla_field(eap, "LogicalOp").width)
        activating = None
        quiet = None
        for op in ops:
            await self._write(
                eap, {"LogicalOp": op, "DestNode": 0, "Action0": action}, f"{label}_op{op}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
            fired = False
            for _ in range(_STATUS_POLLS):
                if await self._status_bit(f"{label}_poll_op{op}"):
                    fired = True
                    break
            if fired:
                activating = op
                break
            quiet = op
        assert activating is not None, (
            f"CDbgEapStatus.Node0Eap0 never read 1 with action {action} over every LogicalOp"
        )
        if quiet is None:
            quiet = (activating + 1) % len(ops)
        return activating, quiet

    async def _quiet(self, action: int, op: int, label: str) -> None:
        """Hold the pair on a non-activating relation with the action still selected."""
        await self._write(self._eap(), {"LogicalOp": op, "DestNode": 0, "Action0": action}, label)
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
