# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A CTRL_STATUS write while the zeroer is busy: ignored while issuing, accepted while draining.

Sources: hw/sys/smc/doc/zeroer.adoc (the state-machine paragraph after the "SMC memory zeroer
state machine and AXI write flow" figure) and the CTRL_STATUS description of
hw/ip/zeroer/regs/zeroer_ctrl.rdl. A CTRL_STATUS write is considered only in ST_IDLE: while the
machine is in ST_ISSUE_ADDR or ST_ISSUE_DATA the write completes with OKAY but starts nothing;
once the last burst has been issued the machine is back in ST_IDLE, so a write while write
responses are still outstanding starts a new clear at once; STATUS reads 1 in both windows and
stays 1 across back-to-back clears, and the completion interrupt pulses once, when STATUS falls
to 0.

Two windows, each with its own pair of poisoned regions in the SYS_OUT responder:

* ``issue``: a second trigger, with new DEST_ADDR and SIZE read back as the second region,
  while the clear state machine of a 64 KiB job is in ST_ISSUE_ADDR or ST_ISSUE_DATA. The write
  answers OKAY, the 32 AW handshakes of the window all lie in the first region, the second
  region keeps its poison, STATUS reads 1 at the polls before it falls, the machine does not
  return to ST_IDLE before the first job's last AW, and it does not leave ST_IDLE again after
  that.
* ``drain``: a second trigger after a 2 KiB job's last AW has been issued and the machine is in
  ST_IDLE while its B responses are held by the SYS_OUT responder (``tb_output_axi_resp_hold``).
  The machine leaves ST_IDLE and the first AW of the second region handshakes while the first
  job's responses are still held, STATUS reads 1 at every poll until the last B of the second
  job, and ``tb_zeroer_intp`` rises exactly once, after that B.
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
_RESP_OKAY = 0

ST_IDLE = 0b001
ST_ISSUE_ADDR = 0b010
ST_ISSUE_DATA = 0b100
_ST_NAME = {0: "ST_ERROR", 1: "ST_IDLE", 2: "ST_ISSUE_ADDR", 4: "ST_ISSUE_DATA"}

# Regions inside the SYS_OUT responder window the busy_outstanding leaf already uses.
_R1_DEST, _R1_SIZE = OUTPUT_FABRIC_ADDR + 0x10000, 64 * KIB
_R2_DEST, _R2_SIZE = OUTPUT_FABRIC_ADDR + 0x30000, 4 * KIB
_R3_DEST, _R3_SIZE = OUTPUT_FABRIC_ADDR + 0x1000, 2 * KIB
_R4_DEST, _R4_SIZE = OUTPUT_FABRIC_ADDR + 0x5000, 4 * KIB
#: 64-bit data path, 256 beats per full burst: the 64 KiB job is 32 bursts.
_R1_BURSTS = _R1_SIZE // (8 * 256)

# Liveness ceilings, not checked quantities: expiry FAILS with the last observed state.
_WAIT_RISES = 200_000
_POLL_LIMIT = 50_000
_QUIET_RISES = 256
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

_PROBES = (
    "tb_zeroer_state",
    "tb_zeroer_busy",
    "tb_zeroer_outstanding",
    "tb_zeroer_trigger",
    "tb_zeroer_intp",
    "tb_zeroer_awvalid",
    "tb_zeroer_awready",
    "tb_zeroer_awaddr",
    "tb_zeroer_bvalid",
    "tb_zeroer_bready",
    "tb_output_axi_resp_hold",
)


class _Wire:
    """Passive clk_smc_i sampler: FSM state, outstanding, trigger strobes, AW, B and IRQ rises."""

    def __init__(self) -> None:
        self.rise = 0
        self.triggers: list[tuple[int, int, int, int]] = []
        self.state_changes: list[tuple[int, int]] = []
        self.aw: list[tuple[int, int, int]] = []
        self.b_rises: list[int] = []
        self.intp_rises: list[int] = []
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
                self.intp_rises.append(self.rise)
            self._prev_intp = intp
            outstanding = g("tb_zeroer_outstanding")
            if g("tb_zeroer_trigger"):
                self.triggers.append((self.rise, state, g("tb_zeroer_busy"), outstanding))
            if g("tb_zeroer_awvalid") and g("tb_zeroer_awready"):
                self.aw.append((self.rise, g("tb_zeroer_awaddr"), outstanding))
            if g("tb_zeroer_bvalid") and g("tb_zeroer_bready"):
                self.b_rises.append(self.rise)


def _inside(addr: int, dest: int, size: int) -> bool:
    return dest <= addr < dest + size


class smc_zeroer_busy_trigger_test_seq(output_fabric_pass_all_cfg_seq):
    """Second CTRL_STATUS trigger in the issue and drain windows of a running clear."""

    def __init__(self, name: str = "smc_zeroer_busy_trigger_test_seq") -> None:
        super().__init__(name)
        self._wire = _Wire()

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

    def _poisoned(self, dest: int, size: int) -> int:
        return sum(1 for b in self._responder.read(dest, size) if b == _POISON_BYTE)

    async def _program(self, label: str, dest: int, size: int) -> None:
        await self.csr_write(f"ZEROER_DEST_{label}", ZEROER_DEST_ADDR, dest, length=8)
        await self.csr_write(f"ZEROER_SIZE_{label}", ZEROER_SIZE, size, length=8)

    async def _readback(self, label: str) -> tuple[int, int]:
        dest = await self.csr_read(f"ZEROER_DEST_RB_{label}", ZEROER_DEST_ADDR, length=8)
        size = await self.csr_read(f"ZEROER_SIZE_RB_{label}", ZEROER_SIZE, length=8)
        return dest, size

    async def _trigger(self, label: str) -> int:
        """Write CTRL_STATUS with INT_EN set and return the AXI write response code."""
        item = SmcSysAxiItem(f"wr_ZEROER_START_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = ZEROER_CTRL_STATUS
        item.length = 8
        item.wdata = ZEROER_CTRL_STATUS_START
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out, f"the CTRL_STATUS write {label} timed out"
        assert item.resp_code is not None, f"the CTRL_STATUS write {label} has no response"
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

    async def _poll_to_zero(self, label: str) -> tuple[int, int]:
        """Poll STATUS until it reads 0; return (reads of 1, B handshakes once the 0 read is in)."""
        busy_reads = 0
        for _ in range(_POLL_LIMIT):
            if await self._status(f"ZEROER_POLL_{label}") == 0:
                return busy_reads, len(self._wire.b_rises)
            busy_reads += 1
        raise AssertionError(
            f"{label}: STATUS still 1 after {_POLL_LIMIT} polls: state="
            f"{_ST_NAME.get(self._sig('tb_zeroer_state'))} "
            f"outstanding={self._sig('tb_zeroer_outstanding')}"
        )

    def _second_trigger(self, n_before: int) -> tuple[int, int, int, int]:
        new = self._wire.triggers[n_before:]
        assert len(new) == 1, (
            f"the second CTRL_STATUS write produced {len(new)} tb_zeroer_trigger strobes, want 1"
        )
        return new[0]

    async def _phase_issue(self) -> None:
        wire = self._wire
        self._prime(_R1_DEST, _R1_SIZE)
        self._prime(_R2_DEST, _R2_SIZE)
        irq0, aw0 = len(wire.intp_rises), len(wire.aw)
        await self._program("R1", _R1_DEST, _R1_SIZE)
        bresp1 = await self._trigger("R1")
        assert bresp1 == _RESP_OKAY, f"the first trigger answered {_RESP_NAME.get(bresp1)}"
        await self._wait(
            "ST_ISSUE_* of the 64 KiB job", lambda: self._sig("tb_zeroer_state") != ST_IDLE
        )
        await self._program("R2", _R2_DEST, _R2_SIZE)
        landed = await self._readback("R2")
        assert landed == (_R2_DEST, _R2_SIZE), (
            f"DEST_ADDR/SIZE read back 0x{landed[0]:x}/0x{landed[1]:x} during the 64 KiB job; "
            f"want the second region 0x{_R2_DEST:x}/0x{_R2_SIZE:x}"
        )
        n_before = len(wire.triggers)
        bresp2 = await self._trigger("R2")
        await ClockCycles(cocotb.top.clk_smc_i, 4)
        t2_rise, t2_state, t2_busy, _t2_out = self._second_trigger(n_before)
        assert t2_state in (ST_ISSUE_ADDR, ST_ISSUE_DATA), (
            f"the second trigger landed in {_ST_NAME.get(t2_state)}, not an issue state"
        )
        busy_polls, _b = await self._poll_to_zero("ISSUE")
        await ClockCycles(cocotb.top.clk_smc_i, _QUIET_RISES)
        status_after = await self._status_word("ZEROER_ISSUE_AFTER")

        aws = wire.aw[aw0:]
        in_r1 = [a for a in aws if _inside(a[1], _R1_DEST, _R1_SIZE)]
        in_r2 = [a for a in aws if _inside(a[1], _R2_DEST, _R2_SIZE)]
        elsewhere = [a for a in aws if a not in in_r1 and a not in in_r2]
        last_r1_aw = in_r1[-1][0] if in_r1 else 0
        idle_entries = [r for r, s in wire.state_changes if r > t2_rise and s == ST_IDLE]
        early_idle = [r for r in idle_entries if r <= last_r1_aw]
        restarted = [
            (r, s)
            for r, s in wire.state_changes
            if idle_entries and r > idle_entries[0] and s != ST_IDLE
        ]
        r1_nz = self._nonzero(_R1_DEST, _R1_SIZE)
        r2_poison = self._poisoned(_R2_DEST, _R2_SIZE)
        irqs = len(wire.intp_rises) - irq0

        assert bresp2 == _RESP_OKAY, (
            f"the CTRL_STATUS write in {_ST_NAME.get(t2_state)} answered "
            f"{_RESP_NAME.get(bresp2, bresp2)}, want OKAY"
        )
        assert len(in_r1) == _R1_BURSTS and r1_nz == 0 and busy_polls >= 1, (
            f"the 64 KiB job did not retire as one job: {len(in_r1)} AW handshakes in its range "
            f"(want {_R1_BURSTS}), {r1_nz} of {_R1_SIZE} bytes not 0, {busy_polls} polls of "
            "STATUS 1"
        )
        assert not in_r2 and not elsewhere, (
            f"{len(in_r2)} AW handshakes in the second region and {len(elsewhere)} outside both "
            f"regions after a CTRL_STATUS write in {_ST_NAME.get(t2_state)}, want 0"
        )
        assert r2_poison == _R2_SIZE, (
            f"{_R2_SIZE - r2_poison} of {_R2_SIZE} bytes of the second region lost their poison "
            f"after a CTRL_STATUS write in {_ST_NAME.get(t2_state)}"
        )
        assert not early_idle, (
            f"ST_IDLE entered at rise {early_idle[0]} after the second trigger at rise "
            f"{t2_rise}, before the first job's last AW at rise {last_r1_aw}"
        )
        assert len(idle_entries) == 1 and not restarted, (
            f"the machine left ST_IDLE again after the first job: idle entries {idle_entries}, "
            f"later states {[(r, _ST_NAME.get(s)) for r, s in restarted]}"
        )
        assert irqs == 1, f"{irqs} completion interrupt pulses across the issue window, want 1"
        assert not (status_after & STATUS_BM), "STATUS still 1 after the issue window"
        cocotb.log.info(
            "CHK-ZEROER-BUSY-TRIGGER-ISSUE-IGNORED: with DEST_ADDR/SIZE read back as the second "
            "region 0x%x/0x%x, the CTRL_STATUS write at rise %d landed in %s with busy %d and "
            "answered %s; the %d AW handshakes of the window (SIZE / 2048 of the 64 KiB job) all "
            "lie in the first region 0x%x..0x%x (0 in the second region 0x%x, 0 elsewhere), the "
            "first region is zero and the second keeps all %d poison bytes, ST_IDLE was entered "
            "once at rise %d after the first job's last AW at rise %d and never left again, "
            "STATUS read 1 at %d polls then 0, %d completion pulse",
            landed[0],
            landed[1],
            t2_rise,
            _ST_NAME.get(t2_state),
            t2_busy,
            _RESP_NAME.get(bresp2),
            len(aws),
            _R1_DEST,
            _R1_DEST + _R1_SIZE - 1,
            _R2_DEST,
            r2_poison,
            idle_entries[0],
            last_r1_aw,
            busy_polls,
            irqs,
        )

    async def _phase_drain(self) -> None:
        wire = self._wire
        self._prime(_R3_DEST, _R3_SIZE)
        self._prime(_R4_DEST, _R4_SIZE)
        irq0, aw0, b0 = len(wire.intp_rises), len(wire.aw), len(wire.b_rises)
        await self._hold(1)
        try:
            await self._program("R3", _R3_DEST, _R3_SIZE)
            bresp1 = await self._trigger("R3")
            assert bresp1 == _RESP_OKAY, f"the first trigger answered {_RESP_NAME.get(bresp1)}"
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
                f"{self._sig('tb_zeroer_outstanding')} are outstanding, want 1"
            )
            held_out = self._sig("tb_zeroer_outstanding")
            await self._program("R4", _R4_DEST, _R4_SIZE)
            n_before = len(wire.triggers)
            bresp2 = await self._trigger("R4")
            await ClockCycles(cocotb.top.clk_smc_i, 4)
            t2_rise, t2_state, _t2_busy, t2_out = self._second_trigger(n_before)
            assert t2_state == ST_IDLE and t2_out >= 1, (
                f"the second trigger landed in {_ST_NAME.get(t2_state)} with {t2_out} "
                "outstanding, not the drain window"
            )
            await self._wait(
                "ST_ISSUE_* and the first AW of the second job with the first job's responses held",
                lambda: (
                    self._sig("tb_zeroer_state") != ST_IDLE
                    and any(_inside(a[1], _R4_DEST, _R4_SIZE) for a in wire.aw[aw0:])
                ),
                limit=_QUIET_RISES,
            )
            left_idle = [(r, s) for r, s in wire.state_changes if r > t2_rise and s != ST_IDLE]
            assert left_idle and self._sig("tb_zeroer_outstanding") >= held_out, (
                f"the machine did not leave ST_IDLE within {_QUIET_RISES} rises of the trigger "
                f"while {held_out} responses were held"
            )
            assert len(wire.b_rises) == b0, "a B handshake completed during the hold"
        finally:
            await self._hold(0)
        busy_polls, b_total_at_zero = await self._poll_to_zero("DRAIN")
        b_at_zero = b_total_at_zero - b0
        await ClockCycles(cocotb.top.clk_smc_i, _QUIET_RISES)
        status_after = await self._status_word("ZEROER_DRAIN_AFTER")

        aws = wire.aw[aw0:]
        in_r3 = [a for a in aws if _inside(a[1], _R3_DEST, _R3_SIZE)]
        in_r4 = [a for a in aws if _inside(a[1], _R4_DEST, _R4_SIZE)]
        elsewhere = [a for a in aws if a not in in_r3 and a not in in_r4]
        bs = wire.b_rises[b0:]
        irqs = wire.intp_rises[irq0:]
        r3_nz, r4_nz = self._nonzero(_R3_DEST, _R3_SIZE), self._nonzero(_R4_DEST, _R4_SIZE)

        assert bresp2 == _RESP_OKAY, (
            f"the CTRL_STATUS write in the drain window answered {_RESP_NAME.get(bresp2, bresp2)}"
        )
        assert in_r3 and in_r4 and not elsewhere, (
            f"{len(in_r3)} AW handshakes in the first region, {len(in_r4)} in the second, "
            f"{len(elsewhere)} elsewhere; want both regions issued and nothing else"
        )
        first_r4 = in_r4[0]
        assert first_r4[0] > t2_rise and first_r4[2] >= held_out, (
            f"the first AW of the second region handshook at rise {first_r4[0]} with "
            f"tb_zeroer_outstanding {first_r4[2]}; want after the trigger at rise {t2_rise} with "
            f"at least the {held_out} held response(s) still outstanding"
        )
        assert r3_nz == 0 and r4_nz == 0, (
            f"{r3_nz} of {_R3_SIZE} and {r4_nz} of {_R4_SIZE} bytes of the two regions are not 0"
        )
        assert len(bs) == len(aws), f"{len(bs)} B handshakes for {len(aws)} AW handshakes"
        assert b_at_zero == len(aws), (
            f"STATUS read 0 with {b_at_zero} of {len(aws)} B handshakes consumed once that read "
            "was in; want 1 at every poll until the last B of the second job"
        )
        assert busy_polls >= 1, "no STATUS poll read 1 after the release"
        assert len(irqs) == 1 and irqs[0] > bs[-1], (
            f"completion interrupt rises at {irqs} across both jobs; want exactly one, after the "
            f"last B handshake at rise {bs[-1] if bs else None}"
        )
        assert not (status_after & STATUS_BM), "STATUS still 1 after the drain window"
        cocotb.log.info(
            "CHK-ZEROER-BUSY-TRIGGER-DRAIN-STARTS: with %d response(s) of the 2 KiB job held, "
            "STATUS read 1 and the CTRL_STATUS write at rise %d landed in ST_IDLE with %d "
            "outstanding and answered %s; the machine entered %s at rise %d and the first AW of "
            "the second region 0x%x handshook at rise %d, with the responses still held and "
            "tb_zeroer_outstanding %d (%d AW in the first region, %d in the second, 0 elsewhere); "
            "after the release STATUS read 1 at %d polls and 0 only with all %d B handshakes "
            "consumed, both regions are zero and "
            "tb_zeroer_intp rose once at rise %d after the last B at rise %d",
            held_out,
            t2_rise,
            t2_out,
            _RESP_NAME.get(bresp2),
            _ST_NAME.get(left_idle[0][1]),
            left_idle[0][0],
            _R4_DEST,
            first_r4[0],
            first_r4[2],
            len(in_r3),
            len(in_r4),
            busy_polls,
            len(bs),
            irqs[0],
            bs[-1],
        )

    async def body(self) -> None:
        dut = cocotb.top
        for name in _PROBES:
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        dut.tb_output_axi_resp_hold.value = 0
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        self._wire.start()
        try:
            idle = await self._status("ZEROER_IDLE")
            assert idle == 0, f"STATUS reads {idle} with the zeroer idle"
            await self._phase_issue()
            await self._phase_drain()
        finally:
            self._wire.stop()
            dut.tb_output_axi_resp_hold.value = 0
