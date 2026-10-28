# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Observe what a CTRL_STATUS trigger does while the zeroer is busy.

Sources hw/sys/smc/doc/zeroer.adoc and hw/ip/zeroer/regs/zeroer_ctrl.rdl, which state that a
CTRL_STATUS write starts a clear unless SIZE is 0 and say nothing about a write while STATUS
reads busy. Two windows are exercised and reported as OBS-ZEROER-BUSY lines, not graded:

* ``phase=issue``: a second trigger (with new DEST_ADDR/SIZE) while the clear state machine is
  in ST_ISSUE_ADDR or ST_ISSUE_DATA of a long job.
* ``phase=drain``: a second trigger after the job's last AW has been issued and the machine is
  back in ST_IDLE, while STATUS still reads busy because B responses are held by the SYS_OUT
  responder (``tb_output_axi_resp_hold``).

The CHK line only grades liveness: both windows were hit, the first job of each phase retired
and its region is zero. #3422 asks the zeroer chapter and `zeroer_ctrl.rdl` to state the rule
for a trigger while the zeroer is busy; the leaf is held out of `all` until that ruling lands.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, reg_field_encode
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    output_fabric_pass_all_cfg_seq,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    ZEROER_CTRL_CTRL_STATUS_REG_ADDR,
    ZEROER_CTRL_DEST_ADDR_REG_ADDR,
    ZEROER_CTRL_SIZE_REG_ADDR,
)

ZEROER_DEST_ADDR = ZEROER_CTRL_DEST_ADDR_REG_ADDR
ZEROER_SIZE = ZEROER_CTRL_SIZE_REG_ADDR
ZEROER_CTRL_STATUS = ZEROER_CTRL_CTRL_STATUS_REG_ADDR
_ZEROER_CTRL_H = _REPO / "hw" / "ip" / "zeroer" / "regs" / "gen" / "c" / "zeroer_ctrl.h"
ZEROER_CTRL_STATUS_START = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", int_en=1)
STATUS_BM = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", status=1)

KIB = 1024
_POISON_BYTE = 0xA5

ST_IDLE = 0b001
ST_ISSUE_ADDR = 0b010
ST_ISSUE_DATA = 0b100
_ST_NAME = {0: "ST_ERROR", 1: "ST_IDLE", 2: "ST_ISSUE_ADDR", 4: "ST_ISSUE_DATA"}

# Regions inside the SYS_OUT responder window the busy_outstanding leaf already uses.
_R1_DEST, _R1_SIZE = OUTPUT_FABRIC_ADDR + 0x10000, 64 * KIB
_R2_DEST, _R2_SIZE = OUTPUT_FABRIC_ADDR + 0x30000, 4 * KIB
_R3_DEST, _R3_SIZE = OUTPUT_FABRIC_ADDR + 0x1000, 2 * KIB
_R4_DEST, _R4_SIZE = OUTPUT_FABRIC_ADDR + 0x5000, 4 * KIB

_WAIT_RISES = 200_000
_POLL_LIMIT = 50_000
_SETTLE_RISES = 256
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


class _Wire:
    """Passive clk_smc_i sampler: FSM state, busy, outstanding, trigger strobes, IRQ pulses."""

    def __init__(self) -> None:
        self.rise = 0
        self.triggers: list[tuple[int, int, int, int]] = []
        self.state_changes: list[tuple[int, int]] = []
        self.intp_rises = 0
        self._prev_intp = 0
        self._prev_state = -1
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @staticmethod
    def _get(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z: {sig.value}"
        return int(sig.value)

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.rise += 1
            g = self._get
            state = g("tb_zeroer_state")
            if state != self._prev_state:
                self.state_changes.append((self.rise, state))
                self._prev_state = state
            intp = g("tb_zeroer_intp")
            if intp and not self._prev_intp:
                self.intp_rises += 1
            self._prev_intp = intp
            if g("tb_zeroer_trigger"):
                self.triggers.append(
                    (self.rise, state, g("tb_zeroer_busy"), g("tb_zeroer_outstanding"))
                )


class smc_zeroer_busy_trigger_obs_test_seq(output_fabric_pass_all_cfg_seq):
    """Second CTRL_STATUS trigger in the issue and drain windows of a running clear."""

    def __init__(self, name: str = "smc_zeroer_busy_trigger_obs_test_seq") -> None:
        super().__init__(name)
        self._wire = _Wire()
        self.obs: dict[str, dict] = {}

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    @staticmethod
    def _sig(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z: {sig.value}"
        return int(sig.value)

    async def _hold(self, value: int) -> None:
        dut = cocotb.top
        await FallingEdge(dut.clk_smc_i)
        dut.tb_output_axi_resp_hold.value = value

    async def _status_word(self, name: str) -> int:
        return await self.csr_read(name, ZEROER_CTRL_STATUS, length=8)

    async def _status(self, name: str) -> int:
        return 1 if await self._status_word(name) & STATUS_BM else 0

    def _prime(self, dest: int, size: int) -> None:
        resp = self._responder
        resp.write(dest, bytes([_POISON_BYTE]) * size)
        assert resp.read(dest, size) == bytes([_POISON_BYTE]) * size, (
            f"the {size}-byte region at 0x{dest:x} did not take its poison"
        )

    def _nonzero(self, dest: int, size: int) -> int:
        return sum(1 for b in self._responder.read(dest, size) if b)

    async def _program(self, label: str, dest: int, size: int) -> None:
        await self.csr_write(f"ZEROER_DEST_{label}", ZEROER_DEST_ADDR, dest, length=8)
        await self.csr_write(f"ZEROER_SIZE_{label}", ZEROER_SIZE, size, length=8)

    async def _trigger(self, label: str) -> int | None:
        """Write CTRL_STATUS and return the AXI write response code (no error is asserted)."""
        item = SmcSysAxiItem(f"wr_ZEROER_START_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = ZEROER_CTRL_STATUS
        item.length = 8
        item.wdata = ZEROER_CTRL_STATUS_START
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.resp_code

    async def _wait(self, what: str, cond, limit: int = _WAIT_RISES) -> None:
        for _ in range(limit):
            if cond():
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{what} not reached within {limit} clk_smc_i rises: state="
            f"{_ST_NAME.get(self._sig('tb_zeroer_state'))} busy={self._sig('tb_zeroer_busy')} "
            f"outstanding={self._sig('tb_zeroer_outstanding')}"
        )

    async def _poll_to_zero(self, label: str) -> int:
        busy_reads = 0
        for _ in range(_POLL_LIMIT):
            if await self._status(f"ZEROER_POLL_{label}") == 0:
                return busy_reads
            busy_reads += 1
        raise AssertionError(
            f"{label}: STATUS still 1 after {_POLL_LIMIT} polls: state="
            f"{_ST_NAME.get(self._sig('tb_zeroer_state'))} "
            f"outstanding={self._sig('tb_zeroer_outstanding')}"
        )

    def _obs_line(self, phase: str, o: dict) -> None:
        cocotb.log.info(
            "OBS-ZEROER-BUSY phase=%s second_write_bresp=%s region1_zeroed=%s region2_zeroed=%s "
            "status_after=0x%x completion_irqs=%d trigger2_state=%s trigger2_busy=%d "
            "trigger2_outstanding=%d region1_nonzero=%d/%d region2_nonzero=%d/%d "
            "fsm_left_idle_after_trigger2=%s busy_polls=%d state_trace=%s",
            phase,
            o["bresp"],
            o["r1_zeroed"],
            o["r2_zeroed"],
            o["status_after"],
            o["irqs"],
            o["t2_state"],
            o["t2_busy"],
            o["t2_outstanding"],
            o["r1_nonzero"],
            o["r1_size"],
            o["r2_nonzero"],
            o["r2_size"],
            o["restarted"],
            o["busy_polls"],
            o["trace"],
        )

    async def _phase_issue(self) -> dict:
        wire = self._wire
        self._prime(_R1_DEST, _R1_SIZE)
        self._prime(_R2_DEST, _R2_SIZE)
        irq0 = wire.intp_rises
        await self._program("R1", _R1_DEST, _R1_SIZE)
        t1 = len(wire.triggers)
        await self._trigger("R1")
        await self._wait(
            "ST_ISSUE_* of the 64 KiB job", lambda: self._sig("tb_zeroer_state") != ST_IDLE
        )
        await self._program("R2", _R2_DEST, _R2_SIZE)
        n_before = len(wire.triggers)
        bresp = await self._trigger("R2")
        await ClockCycles(cocotb.top.clk_smc_i, 4)
        new = wire.triggers[n_before:]
        assert new, "the second CTRL_STATUS write produced no tb_zeroer_trigger strobe"
        _r, t2_state, t2_busy, t2_out = new[-1]
        mark = wire.rise
        busy_polls = await self._poll_to_zero("ISSUE")
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_RISES)
        status_after = await self._status_word("ZEROER_ISSUE_AFTER")
        trace = ">".join(_ST_NAME.get(s, str(s)) for r, s in wire.state_changes if r > t1)
        idle_returns = [r for r, s in wire.state_changes if r > mark and s == ST_IDLE]
        restarted = (
            any(r > idle_returns[0] and s != ST_IDLE for r, s in wire.state_changes)
            if idle_returns
            else False
        )
        r1_nz, r2_nz = self._nonzero(_R1_DEST, _R1_SIZE), self._nonzero(_R2_DEST, _R2_SIZE)
        o = {
            "bresp": _RESP_NAME.get(bresp, str(bresp)),
            "r1_zeroed": r1_nz == 0,
            "r2_zeroed": r2_nz == 0,
            "r1_nonzero": r1_nz,
            "r1_size": _R1_SIZE,
            "r2_nonzero": r2_nz,
            "r2_size": _R2_SIZE,
            "status_after": status_after,
            "irqs": wire.intp_rises - irq0,
            "t2_state": _ST_NAME.get(t2_state, str(t2_state)),
            "t2_busy": t2_busy,
            "t2_outstanding": t2_out,
            "restarted": restarted,
            "busy_polls": busy_polls,
            "trace": trace,
            "hit": t2_state in (ST_ISSUE_ADDR, ST_ISSUE_DATA),
        }
        self._obs_line("issue", o)
        return o

    async def _phase_drain(self) -> dict:
        wire = self._wire
        self._prime(_R3_DEST, _R3_SIZE)
        self._prime(_R4_DEST, _R4_SIZE)
        irq0 = wire.intp_rises
        t1 = len(wire.triggers)
        await self._hold(1)
        try:
            await self._program("R3", _R3_DEST, _R3_SIZE)
            await self._trigger("R3")
            await self._wait(
                "ST_ISSUE_* of the 2 KiB job", lambda: self._sig("tb_zeroer_state") != ST_IDLE
            )
            await self._wait(
                "ST_IDLE with outstanding responses (B held)",
                lambda: (
                    self._sig("tb_zeroer_state") == ST_IDLE
                    and self._sig("tb_zeroer_outstanding") >= 1
                ),
            )
            held_status = await self._status("ZEROER_DRAIN_HELD")
            assert held_status == 1, (
                "STATUS reads 0 while the 2 KiB job's write responses are held and "
                f"{self._sig('tb_zeroer_outstanding')} are outstanding, want busy"
            )
            held_out = self._sig("tb_zeroer_outstanding")
            await self._program("R4", _R4_DEST, _R4_SIZE)
            n_before = len(wire.triggers)
            bresp = await self._trigger("R4")
            await ClockCycles(cocotb.top.clk_smc_i, 4)
            new = wire.triggers[n_before:]
            assert new, "the second CTRL_STATUS write produced no tb_zeroer_trigger strobe"
            t2_rise, t2_state, t2_busy, t2_out = new[-1]
            await ClockCycles(cocotb.top.clk_smc_i, 64)
            left_idle = any(r > t2_rise and s != ST_IDLE for r, s in wire.state_changes)
            held_out_after = self._sig("tb_zeroer_outstanding")
        finally:
            await self._hold(0)
        busy_polls = await self._poll_to_zero("DRAIN")
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_RISES)
        status_after = await self._status_word("ZEROER_DRAIN_AFTER")
        trace = ">".join(
            _ST_NAME.get(s, str(s)) for r, s in wire.state_changes if r > wire.triggers[t1][0]
        )
        r1_nz, r2_nz = self._nonzero(_R3_DEST, _R3_SIZE), self._nonzero(_R4_DEST, _R4_SIZE)
        o = {
            "bresp": _RESP_NAME.get(bresp, str(bresp)),
            "r1_zeroed": r1_nz == 0,
            "r2_zeroed": r2_nz == 0,
            "r1_nonzero": r1_nz,
            "r1_size": _R3_SIZE,
            "r2_nonzero": r2_nz,
            "r2_size": _R4_SIZE,
            "status_after": status_after,
            "irqs": wire.intp_rises - irq0,
            "t2_state": _ST_NAME.get(t2_state, str(t2_state)),
            "t2_busy": t2_busy,
            "t2_outstanding": t2_out,
            "restarted": left_idle,
            "busy_polls": busy_polls,
            "trace": trace,
            "hit": t2_state == ST_IDLE and t2_out >= 1,
            "held_status": held_status,
            "held_out": held_out,
            "held_out_after": held_out_after,
        }
        self._obs_line("drain", o)
        cocotb.log.info(
            "OBS-ZEROER-BUSY-DRAIN-DETAIL STATUS_read_during_hold=%d outstanding_at_hold=%d "
            "outstanding_64_rises_after_trigger2=%d",
            held_status,
            held_out,
            held_out_after,
        )
        return o

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_zeroer_state",
            "tb_zeroer_busy",
            "tb_zeroer_outstanding",
            "tb_zeroer_trigger",
            "tb_zeroer_intp",
            "tb_output_axi_resp_hold",
        ):
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        dut.tb_output_axi_resp_hold.value = 0
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        self._wire.start()
        try:
            idle = await self._status("ZEROER_IDLE")
            assert idle == 0, f"STATUS reads {idle} with the zeroer idle"
            self.obs["issue"] = await self._phase_issue()
            self.obs["drain"] = await self._phase_drain()
        finally:
            self._wire.stop()
            dut.tb_output_axi_resp_hold.value = 0
        iss, drn = self.obs["issue"], self.obs["drain"]
        assert iss["hit"], f"issue window missed: second trigger landed in {iss['t2_state']}"
        assert drn["hit"], (
            f"drain window missed: second trigger landed in {drn['t2_state']} with "
            f"outstanding {drn['t2_outstanding']}"
        )
        assert iss["r1_zeroed"] and drn["r1_zeroed"], "a first job's region is not zero"
        assert not (iss["status_after"] & STATUS_BM), "STATUS still busy after the issue phase"
        assert not (drn["status_after"] & STATUS_BM), "STATUS still busy after the drain phase"
        cocotb.log.info(
            "CHK-ZEROER-BUSY-TRIGGER-OBS: both windows hit (issue-phase trigger in %s, "
            "drain-phase trigger in %s with %d outstanding), each first job retired with its "
            "region zero and STATUS 0; the second trigger's effect is reported in the "
            "OBS-ZEROER-BUSY lines and not graded",
            iss["t2_state"],
            drn["t2_state"],
            drn["t2_outstanding"],
        )
