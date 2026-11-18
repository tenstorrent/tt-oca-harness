# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CTRL_STATUS writes of any strobe start a clear, and STATUS reads 1 through the CSR in ST_ERROR.

Sources: hw/ip/zeroer/regs/zeroer_ctrl.rdl (CTRL_STATUS: "Any write to this register triggers
the start of the zeroer, irrespective of WSTRB, including a write with no byte lanes enabled";
STATUS: 1 means active, has pending work, or is in an error state; 0 means idle) and
hw/sys/smc/doc/zeroer.adoc ("SMC zeroer state machine" table: ST_ERROR holds the zeroer busy,
with no interrupt, until reset).

* **Strobed starts.** With a 64-byte poisoned region in the SYS_OUT responder programmed into
  DEST_ADDR and SIZE and the B response held (``tb_output_axi_resp_hold``), an 8-byte
  CTRL_STATUS write with WSTRB 0x00, 0x0F and 0xF0 each raises one trigger strobe, issues one
  AW that stays outstanding with no B handshake while the hold lasts, reads STATUS 1 in that
  window, zeroes the 64 bytes once the hold is released, and leaves INT_EN at its value before
  the write when lane 0 is disabled (a lane WSTRB disables carries no write data: AMBA AXI
  protocol, write strobes) or takes the written bit when lane 0 is enabled; every
  disabled-lane word differs from the INT_EN it meets; the completion pulses once when INT_EN
  is 1 after the write and not at all when it is 0. The full-strobe start that precedes them,
  with INT_EN written 1, is the control for the same compares and the live interrupt.
* **STATUS in ST_ERROR through the CSR.** With INT_EN set beforehand (a CTRL_STATUS write while
  SIZE is 0, which starts nothing) and the state flop forced to an illegal encoding
  (``tb_zeroer_state_inject``), the machine enters ST_ERROR; a CTRL_STATUS read then has STATUS 1
  with INT_EN still 1 and the rest of the word unchanged, a second read still has it, DEST_ADDR
  and SIZE keep their values, no AW is issued and ``tb_zeroer_intp`` stays 0; after a cold reset
  CTRL_STATUS reads 0. The cold reset is the last stimulus of the leaf.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, NextTimeStep, RisingEdge
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
INT_EN_BM = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", int_en=1)
STATUS_BM = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", status=1)

_POISON_BYTE = 0xA5
ST_ERROR = 0b000
ST_IDLE = 0b001
_ST_NAME = {0: "ST_ERROR", 1: "ST_IDLE", 2: "ST_ISSUE_ADDR", 4: "ST_ISSUE_DATA"}
#: One of the four encodings zeroer.adoc leaves unassigned.
_ILLEGAL_STATE = 0b011

_STROBE_DEST, _STROBE_SIZE = OUTPUT_FABRIC_ADDR + 0x8000, 64
#: (label, WSTRB or None for the address-derived full strobe, written word).
#: The full-strobe control sets INT_EN; the WSTRB 0x00 start then writes 0 on
#: a disabled lane with INT_EN 1, WSTRB 0x0F clears it on an enabled lane, and
#: WSTRB 0xF0 writes 1 on a disabled lane with INT_EN 0: every disabled-lane
#: word differs from the INT_EN it meets, so a start that honoured a disabled
#: lane is told by INT_EN afterwards.
_STROBED_STARTS = (
    ("FULL", None, INT_EN_BM),
    ("W00", 0x00, 0),
    ("W0F", 0x0F, 0),
    ("WF0", 0xF0, 1),
)
_ERROR_DEST, _ERROR_SIZE = OUTPUT_FABRIC_ADDR + 0x9000, 8

# Liveness ceilings, not checked quantities: expiry FAILS with the last observed state.
_WAIT_RISES = 200_000
_POLL_LIMIT = 50_000
_QUIET_RISES = 256
_ERROR_HOLD_RISES = 64

_PROBES = (
    "tb_zeroer_state",
    "tb_zeroer_state_inject",
    "tb_zeroer_state_inject_en",
    "tb_zeroer_busy",
    "tb_zeroer_trigger",
    "tb_zeroer_intp",
    "tb_zeroer_awvalid",
    "tb_zeroer_awready",
    "tb_zeroer_bvalid",
    "tb_zeroer_bready",
    "tb_zeroer_outstanding",
    "tb_output_axi_resp_hold",
    "rst_cold_ni",
    "rst_primary_smc_clk_no",
)

_CHECKERS = (("CHK-ZEROER-ZERO-STROBE-START", "S2"), ("CHK-ZEROER-ERROR-STATUS-CSR", "S3"))


class _Wire:
    """Passive clk_smc_i sampler of the zeroer trigger strobes, AW handshakes, busy and IRQ."""

    def __init__(self) -> None:
        self.rise = 0
        self.triggers = 0
        self.aw = 0
        self.b = 0
        self.busy_rises = 0
        self.intp_rises = 0
        self._prev_intp = 0
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
                self.aw += 1
            if g("tb_zeroer_bvalid") and g("tb_zeroer_bready"):
                self.b += 1
            if g("tb_zeroer_busy"):
                self.busy_rises += 1
            intp = g("tb_zeroer_intp")
            if intp and not self._prev_intp:
                self.intp_rises += 1
            self._prev_intp = intp

    def mark(self) -> tuple[int, int, int, int, int]:
        return self.triggers, self.aw, self.b, self.busy_rises, self.intp_rises


class smc_zeroer_strobe_error_status_test_seq(output_fabric_pass_all_cfg_seq):
    """WSTRB 0x00, 0x0F and 0xF0 starts, and STATUS 1 through the CSR in ST_ERROR."""

    def __init__(self, name: str = "smc_zeroer_strobe_error_status_test_seq") -> None:
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

    async def _ctrl(self, name: str) -> int:
        return await self.csr_read(name, ZEROER_CTRL_STATUS, length=8)

    async def _hold(self, value: int) -> None:
        dut = cocotb.top
        await FallingEdge(dut.clk_smc_i)
        dut.tb_output_axi_resp_hold.value = value

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

    async def _wait(self, what: str, cond, limit: int = _WAIT_RISES) -> None:
        for _ in range(limit):
            if cond():
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{what} not reached within {limit} clk_smc_i rises: state="
            f"{_ST_NAME.get(self._sig('tb_zeroer_state'))} busy={self._sig('tb_zeroer_busy')}"
        )

    async def _poll_to_zero(self, label: str) -> int:
        """Poll CTRL_STATUS until STATUS reads 0; return the number of reads of 1."""
        busy_reads = 0
        for _ in range(_POLL_LIMIT):
            word = await self._ctrl(f"ZEROER_POLL_{label}")
            if not word & STATUS_BM:
                return busy_reads
            busy_reads += 1
        raise AssertionError(
            f"{label}: STATUS still 1 after {_POLL_LIMIT} polls: state="
            f"{_ST_NAME.get(self._sig('tb_zeroer_state'))}"
        )

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _PROBES:
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        dut.tb_output_axi_resp_hold.value = 0
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        self._wire.start()
        idle = await self._ctrl("ZEROER_IDLE")
        assert not idle & STATUS_BM, f"CTRL_STATUS reads 0x{idle:x} with the zeroer idle"
        self._stamp("S1")

    async def _s2(self) -> str:
        wire = self._wire
        legs: list[str] = []
        for label, wstrb, word in _STROBED_STARTS:
            self._prime(_STROBE_DEST, _STROBE_SIZE)
            primed = self._poisoned(_STROBE_DEST, _STROBE_SIZE)
            await self._program(label, _STROBE_DEST, _STROBE_SIZE)
            before = await self._ctrl(f"ZEROER_BEFORE_{label}")
            lane0 = wstrb is None or wstrb & 1
            want_int_en = (word if lane0 else before) & INT_EN_BM
            trig0, aw0, b0, busy0, intp0 = wire.mark()
            await self._hold(1)
            try:
                if wstrb is None:
                    await self.csr_write(
                        f"ZEROER_START_{label}", ZEROER_CTRL_STATUS, word, length=8
                    )
                else:
                    await self.csr_write_strobed(
                        f"ZEROER_START_{label}", ZEROER_CTRL_STATUS, word, wstrb, length=8
                    )
                await self._wait(
                    f"the AW of the {label} start with its response held",
                    lambda: wire.aw > aw0 and self._sig("tb_zeroer_outstanding") >= 1,
                    limit=_QUIET_RISES,
                )
                held = await self._ctrl(f"ZEROER_HELD_{label}")
                held_out, held_b = self._sig("tb_zeroer_outstanding"), wire.b - b0
            finally:
                await self._hold(0)
            busy_polls = await self._poll_to_zero(label)
            await ClockCycles(cocotb.top.clk_smc_i, _QUIET_RISES)
            after = await self._ctrl(f"ZEROER_AFTER_{label}")
            trig, aw, b = wire.triggers - trig0, wire.aw - aw0, wire.b - b0
            busy, intp = wire.busy_rises - busy0, wire.intp_rises - intp0
            nz = self._nonzero(_STROBE_DEST, _STROBE_SIZE)
            strobe = "address-derived 0xff" if wstrb is None else f"0x{wstrb:02x}"
            assert primed == _STROBE_SIZE, f"{primed} of {_STROBE_SIZE} bytes took the poison"
            assert trig == 1 and aw == 1 and b == 1, (
                f"the CTRL_STATUS write with WSTRB {strobe} raised {trig} trigger strobe(s), "
                f"{aw} AW handshake(s) and {b} B handshake(s); want one each"
            )
            assert held & STATUS_BM and held_out >= 1 and held_b == 0, (
                f"with the B response held after the CTRL_STATUS write with WSTRB {strobe}: "
                f"STATUS word 0x{held:x}, tb_zeroer_outstanding {held_out}, {held_b} B "
                "handshake(s); want STATUS 1 with the AW outstanding and no B"
            )
            assert nz == 0, (
                f"{nz} of {_STROBE_SIZE} bytes at 0x{_STROBE_DEST:x} not 0 after the start with "
                f"WSTRB {strobe}"
            )
            assert after & INT_EN_BM == want_int_en, (
                f"INT_EN reads {after & INT_EN_BM} after the start with WSTRB {strobe} and word "
                f"0x{word:x} from {before & INT_EN_BM}; want {want_int_en}"
            )
            assert intp == (1 if want_int_en else 0), (
                f"{intp} completion pulse(s) after the start with WSTRB {strobe} and INT_EN "
                f"{want_int_en}"
            )
            legs.append(
                f"WSTRB {strobe} word 0x{word:x}: {primed}/{_STROBE_SIZE} bytes poisoned, 1 "
                f"trigger strobe, 1 AW, STATUS 1 with that AW outstanding ({held_out}) and no B "
                f"while the response was held ({busy} busy rises, {busy_polls} polls of 1 after "
                f"the release), 1 B, {_STROBE_SIZE} bytes zero, INT_EN {after & INT_EN_BM} "
                f"({'written' if lane0 else 'unchanged'}), {intp} completion pulse"
            )
        await self.csr_write("ZEROER_SIZE_S2_CLEAR", ZEROER_SIZE, 0, length=8)
        self._stamp("S2")
        return "; ".join(legs)

    async def _s3(self) -> str:
        dut = cocotb.top
        wire = self._wire
        self._prime(_ERROR_DEST, _ERROR_SIZE)
        size0 = await self.csr_read("ZEROER_ERR_SIZE0", ZEROER_SIZE, length=8)
        assert size0 == 0, f"SIZE reads 0x{size0:x} before the INT_EN write, want 0"
        _t, aw_en, _b, _r, _i = wire.mark()
        await self.csr_write("ZEROER_ERR_INT_EN", ZEROER_CTRL_STATUS, INT_EN_BM, length=8)
        await ClockCycles(dut.clk_smc_i, 8)
        assert wire.aw == aw_en and self._sig("tb_zeroer_state") == ST_IDLE, (
            f"the INT_EN write with SIZE 0 issued {wire.aw - aw_en} AW and left the machine in "
            f"{_ST_NAME.get(self._sig('tb_zeroer_state'))}"
        )
        await self._program("ERR", _ERROR_DEST, _ERROR_SIZE)
        await self._wait("ST_IDLE", lambda: self._sig("tb_zeroer_state") == ST_IDLE)
        before = await self._ctrl("ZEROER_ERR_BEFORE")
        assert before == INT_EN_BM, (
            f"CTRL_STATUS reads 0x{before:x} before the injection, want INT_EN 1 and STATUS 0"
        )
        _t, aw0, _b, _r, intp0 = wire.mark()
        await NextTimeStep()
        dut.tb_zeroer_state_inject.value = _ILLEGAL_STATE
        dut.tb_zeroer_state_inject_en.value = 1
        await RisingEdge(dut.clk_smc_i)
        await NextTimeStep()
        dut.tb_zeroer_state_inject_en.value = 0
        await self._wait(
            f"ST_ERROR after the {_ILLEGAL_STATE:03b} injection",
            lambda: self._sig("tb_zeroer_state") == ST_ERROR,
            limit=_ERROR_HOLD_RISES,
        )
        err1 = await self._ctrl("ZEROER_ERR_STATUS_1")
        await ClockCycles(dut.clk_smc_i, _ERROR_HOLD_RISES)
        err2 = await self._ctrl("ZEROER_ERR_STATUS_2")
        dest = await self.csr_read("ZEROER_ERR_DEST_RB", ZEROER_DEST_ADDR, length=8)
        size = await self.csr_read("ZEROER_ERR_SIZE_RB", ZEROER_SIZE, length=8)
        state = self._sig("tb_zeroer_state")
        aw, intp = wire.aw - aw0, wire.intp_rises - intp0
        poison = self._nonzero(_ERROR_DEST, _ERROR_SIZE)
        assert state == ST_ERROR, f"the machine left ST_ERROR for {_ST_NAME.get(state)}"
        assert err1 & STATUS_BM and err2 & STATUS_BM, (
            f"CTRL_STATUS reads 0x{err1:x} then 0x{err2:x} in ST_ERROR; want STATUS 1 in both"
        )
        assert (err1 & ~STATUS_BM) == (before & ~STATUS_BM) == (err2 & ~STATUS_BM), (
            f"CTRL_STATUS outside STATUS changed in ST_ERROR: before 0x{before:x}, reads "
            f"0x{err1:x} and 0x{err2:x}"
        )
        assert (dest, size) == (_ERROR_DEST, _ERROR_SIZE), (
            f"DEST_ADDR/SIZE read 0x{dest:x}/0x{size:x} in ST_ERROR, want "
            f"0x{_ERROR_DEST:x}/0x{_ERROR_SIZE:x}"
        )
        assert aw == 0 and intp == 0 and poison == _ERROR_SIZE, (
            f"{aw} AW handshake(s), {intp} interrupt rise(s) and {_ERROR_SIZE - poison} bytes "
            "zeroed in ST_ERROR"
        )
        await self._cold_reset()
        reset = await self._ctrl("ZEROER_RESET_STATUS")
        state = self._sig("tb_zeroer_state")
        assert reset == 0 and state == ST_IDLE, (
            f"CTRL_STATUS reads 0x{reset:x} in {_ST_NAME.get(state)} after the cold reset, want 0 "
            "in ST_IDLE"
        )
        self._stamp("S3")
        return (
            f"state {_ILLEGAL_STATE:03b} injected from ST_IDLE with CTRL_STATUS 0x{before:x}: "
            f"the machine entered ST_ERROR, CTRL_STATUS read 0x{err1:x} and {_ERROR_HOLD_RISES} "
            f"rises later 0x{err2:x} (STATUS 1, INT_EN still 1, the other bits unchanged), "
            f"DEST_ADDR/SIZE "
            f"0x{dest:x}/0x{size:x} unchanged, {aw} AW, {intp} interrupt rises, all {poison} "
            f"bytes still poisoned; after the cold reset CTRL_STATUS reads 0x{reset:x} in "
            f"{_ST_NAME.get(state)}"
        )

    async def _cold_reset(self) -> None:
        dut = cocotb.top
        await NextTimeStep()
        dut.rst_cold_ni.value = 0
        await FallingEdge(dut.rst_primary_smc_clk_no)
        await self._wait(
            "ST_IDLE under the cold reset", lambda: self._sig("tb_zeroer_state") == ST_IDLE
        )
        await NextTimeStep()
        dut.rst_cold_ni.value = 1
        await self.wait_fuse_sense_done()

    async def body(self) -> None:
        try:
            await self._s1()
            self._chk("S2", "CHK-ZEROER-ZERO-STROBE-START", await self._s2())
            self._chk("S3", "CHK-ZEROER-ERROR-STATUS-CSR", await self._s3())
            self._nonvac()
        finally:
            self._wire.stop()
            cocotb.top.tb_zeroer_state_inject_en.value = 0
            cocotb.top.tb_output_axi_resp_hold.value = 0

    def _nonvac(self) -> None:
        steps = [s for s, _t in self._stamps]
        assert steps == ["S1", "S2", "S3"], f"step stamps {steps} out of order"
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
