# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus for the CLA action-release leaves: node 0 pair 0 armed with one action.

The pair is fired by sweeping `LogicalOp` until `CDbgEapStatus.Node0Eap0`
reads 1 and quieted by selecting a relation value that did not fire, so the
action stays selected while the relation is false. The W2C bit of the pair is
pulsed through `CDbgEapStatus`.

`dfd.adoc` Action Codes and the `Action0` description of `dfd_cla.rdl` give
the code of each action: 1 is the clock halt and 2 the debug interrupt. The
code that drives an action line is measured and held to that table: `Action0`
is walked upward from 0 over its RDL-declared range, each value fired from a
quiet relation with the status cleared and the line sampled on each of
`SAMPLE_CYCLES` cycles after the status reads 1, and the first value under
which the line reads 1 has to be the documented code (`CHK-CLA-ACTION-CODE`).
That code is the one the release legs use.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import pack_fields

CHK_ACTION_CODE = "CHK-CLA-ACTION-CODE"
# dfd.adoc Action Codes: the code of the action that drives each observed line.
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

    async def _poll_status(self, label: str) -> bool:
        for _ in range(_STATUS_POLLS):
            if await self._status_bit(label):
                return True
        return False

    async def _arm(self, action: int, op: int, label: str) -> None:
        await self._write(self._eap(), {"LogicalOp": op, "DestNode": 0, "Action0": action}, label)
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)

    async def _fire(self, action: int, label: str) -> tuple[int, int]:
        """Sweep LogicalOp with one action; return (activating op, a quiet op)."""
        ops = range(1 << cla_field(self._eap(), "LogicalOp").width)
        activating = None
        quiet = None
        for op in ops:
            await self._arm(action, op, f"{label}_op{op}")
            if await self._poll_status(f"{label}_poll_op{op}"):
                activating = op
                break
            quiet = op
        assert activating is not None, (
            f"CDbgEapStatus.Node0Eap0 never read 1 with action {action} over every LogicalOp"
        )
        if quiet is None:
            quiet = (activating + 1) % len(ops)
        return activating, quiet

    async def _discover(self, pin: str, label: str, documented: int) -> tuple[int, int, int]:
        """Walk Action0 until `pin` rises; return (action code, activating op, quiet op).

        The first code that raises `pin` has to be `documented`, the code
        `dfd.adoc` Action Codes gives the action. The pair is left fired with
        the returned code selected.
        """
        before = self._pin(pin)
        assert before == 0, f"{pin}={before} before any Action0 value was fired, want 0"
        activating, quiet = await self._fire(0, f"{label}_a0")
        width = cla_field(self._eap(), "Action0").width
        for action in range(1 << width):
            if action:
                await self._quiet(action, quiet, f"{label}_q{action}")
                await self._w2c(f"{label}_a{action}")
                status = await self._status_bit(f"{label}_quiet_a{action}")
                idle = self._pin(pin)
                assert (status, idle) == (0, 0), (
                    f"Action0={action} on quiet LogicalOp {quiet} after the W2C: "
                    f"status={status} {pin}={idle}, want 0 0"
                )
                await self._arm(action, activating, f"{label}_fire_a{action}")
                assert await self._poll_status(f"{label}_poll_a{action}"), (
                    f"CDbgEapStatus.Node0Eap0 did not read 1 with Action0={action} on "
                    f"LogicalOp {activating}"
                )
            raised = False
            for _ in range(SAMPLE_CYCLES):
                await ClockCycles(cocotb.top.clk_smc_i, 1)
                seen = self._pin(pin)
                assert seen in (0, 1), (
                    f"{CHK_ACTION_CODE} FAIL: {pin} is X or Z with Action0={action} fired on "
                    f"LogicalOp {activating}"
                )
                raised = raised or seen == 1
            if raised:
                line = (
                    f"OBS-CLA-ACTION-CODE pin={pin} Action0={action} LogicalOp={activating} "
                    f"quiet_op={quiet}"
                )
                cocotb.log.info(line)
                self.samples.append(line)
                assert action == documented, (
                    f"{CHK_ACTION_CODE} FAIL: {pin} first read 1 with Action0={action}, "
                    f"dfd.adoc Action Codes gives code {documented} for this action"
                )
                cocotb.log.info(
                    "%s PASS: pin=%s first read 1 at Action0=%d, the documented code, and "
                    "read 0 on every sampled cycle after each lower code was fired",
                    CHK_ACTION_CODE,
                    pin,
                    action,
                )
                return action, activating, quiet
        raise AssertionError(
            f"{pin} never read 1 over every value of the {width}-bit Action0 field fired on "
            f"LogicalOp {activating}"
        )

    async def _quiet(self, action: int, op: int, label: str) -> None:
        """Hold the pair on a non-activating relation with the action still selected."""
        await self._arm(action, op, label)
