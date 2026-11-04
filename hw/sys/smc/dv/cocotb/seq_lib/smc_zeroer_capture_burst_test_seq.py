# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer command capture at the trigger, 256-beat bursts, SIZE storage and a constant BREADY.

Sources: hw/sys/smc/doc/zeroer.adoc (the state-machine paragraph after the "SMC memory zeroer
state machine and AXI write flow" figure, the "SMC zeroer AXI4 Master Characteristics" table and
"Outstanding Transaction Management") and hw/ip/zeroer/regs/zeroer_ctrl.rdl (SIZE, CTRL_STATUS).

Jobs run in the SYS_OUT responder window and are poisoned and compared through the responder's
backdoor. A passive clk_smc_i sampler records every zeroer AW handshake with its address and
AWLEN, every B handshake, the trigger strobes, and ``tb_zeroer_bready`` with the hold, busy and
outstanding state at every rise.

* **SIZE storage.** All ones, 0 and the 64 walking-one words read back over SIZE without a
  trigger: no trigger strobe and no AW handshake, SIZE restored to 0.
* **Capture at the start.** A 64 KiB job with its B responses held (``tb_output_axi_resp_hold``)
  is in ST_ISSUE_ADDR or ST_ISSUE_DATA when new DEST_ADDR and SIZE values naming a second
  poisoned region are written without a trigger. Every AW handshake of the job lies in the
  original range, the second region keeps its poison after the release, and DEST_ADDR and SIZE
  read back the new values during and after the job.
* **AWLEN 255.** An 8 KiB job at a 4 KiB-aligned address issues SIZE / 2048 bursts (256 beats of
  8 bytes), every one with AWLEN 255, and the range reads zero.
* **BREADY constant.** ``tb_zeroer_bready`` is 1 at every sampled rise: with a response held
  (hold set and ``tb_zeroer_outstanding`` above 0), with responses outstanding and no hold, and
  while the zeroer is idle; the B handshakes the sampler counts through it equal the AW
  handshakes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

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
_MASK64 = (1 << 64) - 1
#: 64-bit data path: 256 beats of 8 bytes per full burst.
_BEAT_BYTES = 8
_MAX_BEATS = 256
_FULL_BURST_BYTES = _BEAT_BYTES * _MAX_BEATS
_AWLEN_MAX = _MAX_BEATS - 1

ST_IDLE = 0b001
_ST_NAME = {0: "ST_ERROR", 1: "ST_IDLE", 2: "ST_ISSUE_ADDR", 4: "ST_ISSUE_DATA"}

#: The captured job, the region the mid-job rewrite names, and the 256-beat job.
_CAP_DEST, _CAP_SIZE = OUTPUT_FABRIC_ADDR + 0x10000, 64 * KIB
_NEW_DEST, _NEW_SIZE = OUTPUT_FABRIC_ADDR + 0x30000, 4 * KIB
_BURST_DEST, _BURST_SIZE = OUTPUT_FABRIC_ADDR + 0x20000, 8 * KIB
_SIZE_PATTERNS = (_MASK64, 0, *(1 << k for k in range(64)))

# Liveness ceilings, not checked quantities: expiry FAILS with the last observed state.
_WAIT_RISES = 200_000
_POLL_LIMIT = 50_000
_QUIET_RISES = 256

_PROBES = (
    "tb_zeroer_state",
    "tb_zeroer_busy",
    "tb_zeroer_outstanding",
    "tb_zeroer_trigger",
    "tb_zeroer_awvalid",
    "tb_zeroer_awready",
    "tb_zeroer_awaddr",
    "tb_zeroer_awlen",
    "tb_zeroer_bvalid",
    "tb_zeroer_bready",
    "tb_output_axi_resp_hold",
)

#: Checker lines in print order, each with the step it is printed after.
_CHECKERS = (
    ("CHK-ZEROER-SIZE-PATTERN", "S2"),
    ("CHK-ZEROER-CAPTURE-AT-START", "S3"),
    ("CHK-ZEROER-AWLEN-255", "S4"),
    ("CHK-ZEROER-BREADY-CONSTANT", "S5"),
)


class _Wire:
    """Passive clk_smc_i sampler of the zeroer AW, B, trigger and BREADY signals."""

    def __init__(self) -> None:
        self.rise = 0
        self.aw: list[tuple[int, int, int]] = []
        self.b_rises: list[int] = []
        self.triggers = 0
        self.bready_low: list[tuple[int, int, int, int]] = []
        self.rises_held = 0
        self.rises_draining = 0
        self.rises_idle = 0
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
            if g("tb_zeroer_trigger"):
                self.triggers += 1
            if g("tb_zeroer_awvalid") and g("tb_zeroer_awready"):
                self.aw.append((self.rise, g("tb_zeroer_awaddr"), g("tb_zeroer_awlen")))
            bready = g("tb_zeroer_bready")
            if g("tb_zeroer_bvalid") and bready:
                self.b_rises.append(self.rise)
            hold, busy = g("tb_output_axi_resp_hold"), g("tb_zeroer_busy")
            outstanding = g("tb_zeroer_outstanding")
            if hold and outstanding:
                self.rises_held += 1
            elif outstanding and not hold:
                self.rises_draining += 1
            elif not busy:
                self.rises_idle += 1
            if not bready:
                self.bready_low.append((self.rise, hold, busy, outstanding))


def _inside(addr: int, dest: int, size: int) -> bool:
    return dest <= addr < dest + size


class smc_zeroer_capture_burst_test_seq(output_fabric_pass_all_cfg_seq):
    """SIZE storage, command capture at the trigger, AWLEN 255 bursts and a constant BREADY."""

    def __init__(self, name: str = "smc_zeroer_capture_burst_test_seq") -> None:
        super().__init__(name)
        self._wire = _Wire()
        self._stamps: list[tuple[str, int]] = []
        self._printed: list[tuple[str, str]] = []

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

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id} printed while the last completed step is "
            f"{self._stamps[-1][0] if self._stamps else None}, expected {step}"
        )
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self._printed.append((chk_id, step))

    async def _hold(self, value: int) -> None:
        dut = cocotb.top
        await FallingEdge(dut.clk_smc_i)
        dut.tb_output_axi_resp_hold.value = value

    async def _status(self, name: str) -> int:
        word = await self.csr_read(name, ZEROER_CTRL_STATUS, length=8)
        return 1 if word & STATUS_BM else 0

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

    async def _trigger(self, label: str) -> None:
        trig0 = self._wire.triggers
        await self.csr_write(
            f"ZEROER_START_{label}", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )
        await ClockCycles(cocotb.top.clk_smc_i, 4)
        assert self._wire.triggers == trig0 + 1, (
            f"the {label} CTRL_STATUS write raised {self._wire.triggers - trig0} trigger "
            "strobe(s), want 1"
        )

    async def _wait(self, what: str, cond, limit: int = _WAIT_RISES) -> None:
        for _ in range(limit):
            if cond():
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{what} not reached within {limit} clk_smc_i rises: state="
            f"{_ST_NAME.get(self._sig('tb_zeroer_state'))} busy={self._sig('tb_zeroer_busy')} "
            f"outstanding={self._sig('tb_zeroer_outstanding')} aw={len(self._wire.aw)}"
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

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _PROBES:
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        dut.tb_output_axi_resp_hold.value = 0
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        self._wire.start()
        idle = await self._status("ZEROER_IDLE")
        assert idle == 0, f"STATUS reads {idle} with the zeroer idle"
        self._stamp("S1")

    async def _s2(self) -> str:
        wire = self._wire
        trig0, aw0 = wire.triggers, len(wire.aw)
        await self.csr_write("ZEROER_DEST_S2", ZEROER_DEST_ADDR, 0, length=8)
        mismatches: list[tuple[int, int]] = []
        for k, pattern in enumerate(_SIZE_PATTERNS):
            await self.csr_write(f"ZEROER_SIZE_PAT_{k}", ZEROER_SIZE, pattern, length=8)
            got = await self.csr_read(f"ZEROER_SIZE_PAT_RB_{k}", ZEROER_SIZE, length=8)
            if got != pattern:
                mismatches.append((pattern, got))
        await self.csr_write("ZEROER_SIZE_RESTORE", ZEROER_SIZE, 0, length=8)
        restored = await self.csr_read("ZEROER_SIZE_RESTORE_RB", ZEROER_SIZE, length=8)
        await ClockCycles(cocotb.top.clk_smc_i, 8)
        assert not mismatches, (
            f"{len(mismatches)} of {len(_SIZE_PATTERNS)} SIZE patterns read back wrong: "
            + ", ".join(f"wrote 0x{w:016x} read 0x{g:016x}" for w, g in mismatches[:4])
        )
        assert restored == 0, f"SIZE reads 0x{restored:016x} after the restore to 0"
        assert wire.triggers == trig0 and len(wire.aw) == aw0, (
            f"{wire.triggers - trig0} trigger strobe(s) and {len(wire.aw) - aw0} AW handshake(s) "
            "during the SIZE pattern walk, which writes CTRL_STATUS never"
        )
        status = await self._status("ZEROER_S2_AFTER")
        assert status == 0, "STATUS reads 1 after the SIZE pattern walk"
        self._stamp("S2")
        return (
            f"all ones, 0 and the 64 walking-one words ({len(_SIZE_PATTERNS)} patterns) each read "
            f"back over SIZE exactly with no trigger strobe and no AW handshake (the strobe probe "
            f"rises once per CTRL_STATUS write of the later jobs), SIZE restored to "
            f"0x{restored:x} and STATUS {status}"
        )

    async def _s3(self) -> str:
        wire = self._wire
        self._prime(_CAP_DEST, _CAP_SIZE)
        self._prime(_NEW_DEST, _NEW_SIZE)
        aw0 = len(wire.aw)
        await self._hold(1)
        try:
            await self._program("CAP", _CAP_DEST, _CAP_SIZE)
            await self._trigger("CAP")
            await self._wait(
                "ST_ISSUE_* of the 64 KiB job", lambda: self._sig("tb_zeroer_state") != ST_IDLE
            )
            await self._program("NEW", _NEW_DEST, _NEW_SIZE)
            state_at_rewrite = self._sig("tb_zeroer_state")
            aw_at_rewrite = len(wire.aw) - aw0
            during = await self._readback("DURING")
            out_at_rewrite = self._sig("tb_zeroer_outstanding")
            assert (
                state_at_rewrite != ST_IDLE
                and 1 <= aw_at_rewrite < _CAP_SIZE // _FULL_BURST_BYTES
                and out_at_rewrite >= 1
            ), (
                f"the rewrite landed in {_ST_NAME.get(state_at_rewrite)} after {aw_at_rewrite} "
                f"of {_CAP_SIZE // _FULL_BURST_BYTES} AW handshakes with {out_at_rewrite} "
                "outstanding, not during the clear with a response held"
            )
        finally:
            await self._hold(0)
        busy_polls = await self._poll_to_zero("CAP")
        await ClockCycles(cocotb.top.clk_smc_i, _QUIET_RISES)
        after = await self._readback("AFTER")
        aws = wire.aw[aw0:]
        in_cap = [a for a in aws if _inside(a[1], _CAP_DEST, _CAP_SIZE)]
        in_new = [a for a in aws if _inside(a[1], _NEW_DEST, _NEW_SIZE)]
        elsewhere = len(aws) - len(in_cap) - len(in_new)
        cap_nz = self._nonzero(_CAP_DEST, _CAP_SIZE)
        new_poison = self._poisoned(_NEW_DEST, _NEW_SIZE)
        assert in_cap and cap_nz == 0, (
            f"the 64 KiB job did not retire: {len(in_cap)} AW handshakes in its range, "
            f"{cap_nz} of {_CAP_SIZE} bytes not 0"
        )
        assert not in_new and elsewhere == 0, (
            f"{len(in_new)} AW handshakes in the rewritten range and {elsewhere} outside both "
            f"ranges after DEST_ADDR/SIZE were rewritten in {_ST_NAME.get(state_at_rewrite)}"
        )
        assert new_poison == _NEW_SIZE, (
            f"{_NEW_SIZE - new_poison} of {_NEW_SIZE} bytes of the rewritten range 0x{_NEW_DEST:x} "
            "lost their poison"
        )
        assert during == (_NEW_DEST, _NEW_SIZE) and after == (_NEW_DEST, _NEW_SIZE), (
            f"DEST_ADDR/SIZE read back 0x{during[0]:x}/0x{during[1]:x} during and "
            f"0x{after[0]:x}/0x{after[1]:x} after the job; want the rewritten "
            f"0x{_NEW_DEST:x}/0x{_NEW_SIZE:x}"
        )
        await self.csr_write("ZEROER_SIZE_S3_CLEAR", ZEROER_SIZE, 0, length=8)
        self._stamp("S3")
        return (
            f"DEST_ADDR/SIZE rewritten to 0x{_NEW_DEST:x}/0x{_NEW_SIZE:x} in "
            f"{_ST_NAME.get(state_at_rewrite)} after {aw_at_rewrite} of the 64 KiB job's "
            f"{len(in_cap)} AW handshakes with {out_at_rewrite} response(s) held; after the "
            f"release all {len(aws)} AW "
            f"handshakes lie in 0x{_CAP_DEST:x}..0x{_CAP_DEST + _CAP_SIZE - 1:x} (0 in the "
            f"rewritten range, 0 elsewhere), the original range is zero, the rewritten range "
            f"keeps all {new_poison} poison bytes, the registers read back the rewritten values "
            f"during and after the job, STATUS read 1 at {busy_polls} polls then 0"
        )

    async def _s4(self) -> str:
        wire = self._wire
        self._prime(_BURST_DEST, _BURST_SIZE)
        aw0 = len(wire.aw)
        await self._program("BURST", _BURST_DEST, _BURST_SIZE)
        await self._trigger("BURST")
        busy_polls = await self._poll_to_zero("BURST")
        await ClockCycles(cocotb.top.clk_smc_i, _QUIET_RISES)
        aws = wire.aw[aw0:]
        want = _BURST_SIZE // _FULL_BURST_BYTES
        short = [(a, n) for _r, a, n in aws if n != _AWLEN_MAX]
        nz = self._nonzero(_BURST_DEST, _BURST_SIZE)
        assert _BURST_DEST % (4 * KIB) == 0 and _BURST_SIZE % _FULL_BURST_BYTES == 0
        assert len(aws) == want and not short, (
            f"the {_BURST_SIZE}-byte job at 4 KiB-aligned 0x{_BURST_DEST:x} issued {len(aws)} "
            f"bursts with AWLEN {[n for _r, _a, n in aws]}; want {want} bursts of AWLEN "
            f"{_AWLEN_MAX}"
        )
        assert all(_inside(a, _BURST_DEST, _BURST_SIZE) for _r, a, _n in aws) and nz == 0, (
            f"{nz} of {_BURST_SIZE} bytes not 0 or an AW outside the range: "
            f"{[hex(a) for _r, a, _n in aws]}"
        )
        self._stamp("S4")
        return (
            f"the {_BURST_SIZE}-byte job at 4 KiB-aligned 0x{_BURST_DEST:x} issued {len(aws)} "
            f"bursts (SIZE / {_FULL_BURST_BYTES}), every one with AWLEN {_AWLEN_MAX} "
            f"({_MAX_BEATS} beats of {_BEAT_BYTES} bytes), the range is zero, STATUS read 1 at "
            f"{busy_polls} polls then 0"
        )

    async def _s5(self) -> str:
        wire = self._wire
        await ClockCycles(cocotb.top.clk_smc_i, _QUIET_RISES)
        assert wire.rises_held >= 1 and wire.rises_draining >= 1 and wire.rises_idle >= 1, (
            f"the sampled rises miss a condition: held {wire.rises_held}, draining "
            f"{wire.rises_draining}, idle {wire.rises_idle}"
        )
        assert not wire.bready_low, (
            f"tb_zeroer_bready read 0 at {len(wire.bready_low)} of {wire.rise} rises, first at "
            f"(rise, hold, busy, outstanding) {wire.bready_low[0]}"
        )
        assert wire.b_rises and len(wire.b_rises) == len(wire.aw), (
            f"{len(wire.b_rises)} B handshakes through tb_zeroer_bready for {len(wire.aw)} AW "
            "handshakes"
        )
        self._stamp("S5")
        return (
            f"tb_zeroer_bready read 1 at all {wire.rise} sampled rises: {wire.rises_held} with "
            f"a response held, {wire.rises_draining} with responses outstanding and no "
            f"hold, {wire.rises_idle} with the zeroer idle; {len(wire.b_rises)} B handshakes "
            f"for {len(wire.aw)} AW handshakes"
        )

    async def body(self) -> None:
        try:
            await self._s1()
            self._chk("S2", "CHK-ZEROER-SIZE-PATTERN", await self._s2())
            self._chk("S3", "CHK-ZEROER-CAPTURE-AT-START", await self._s3())
            self._chk("S4", "CHK-ZEROER-AWLEN-255", await self._s4())
            self._chk("S5", "CHK-ZEROER-BREADY-CONSTANT", await self._s5())
            self._nonvac()
        finally:
            self._wire.stop()
            cocotb.top.tb_output_axi_resp_hold.value = 0

    def _nonvac(self) -> None:
        steps = [s for s, _t in self._stamps]
        assert steps == ["S1", "S2", "S3", "S4", "S5"], f"step stamps {steps} out of order"
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"step stamps {times} are not strictly increasing"
        )
        assert self._printed == list(_CHECKERS), f"checker lines {self._printed} out of order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines %s print in step order, step stamps "
            "strictly increasing, each line after its own compare; stamps %s ps",
            ",".join(c for c, _s in _CHECKERS),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
