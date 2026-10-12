# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer busy status, completion and outstanding writes under a stalling SYS_OUT responder.

Contract SMC_POWER_DMA_ZEROER_023, anchor smc_zeroer_busy_outstanding_test.
Scenarios ZEROER-BUSY-COMPLETION.S1 to S5 and ZEROER-OUTSTANDING.S1 to S3.
Sources hw/sys/smc/doc/zeroer.adoc, hw/sys/smc/doc/fabric.adoc, hw/ip/zeroer/regs/zeroer_ctrl.rdl.

Jobs run in the SYS_OUT window and are poisoned and compared through the responder's backdoor.
A passive clk_smc_i sampler counts the zeroer AW and W handshakes and the SYS_OUT AW and B
handshakes; the SYS_OUT outstanding AW count is the AW handshakes minus the B handshakes.
"""

from __future__ import annotations

import os
import random
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
_GUARD = 8
_GUARD_BYTE = 0xEE
_POISON_BYTE = 0xA5
_MAX_BURST_BYTES = 256 * 8

_S2_DEST = OUTPUT_FABRIC_ADDR + 0x1000
_S3_DEST = OUTPUT_FABRIC_ADDR + 0x3000
_S4_DEST = OUTPUT_FABRIC_ADDR + 0x5000
_S5_DEST = OUTPUT_FABRIC_ADDR + 0x7000
_S6_DEST = OUTPUT_FABRIC_ADDR + 0x10000
_S8_DEST = OUTPUT_FABRIC_ADDR + 0x30000
_JOB_2K = 2 * KIB
_JOB_4K = 4 * KIB
_JOB_96K = 96 * KIB

LONG_HOLD_RISES = 4096
HOLD_POLLS = 16
PLATEAU_RISES = 256

# Liveness ceilings, not checked quantities: expiry FAILS with the last observed state.
_WAIT_RISES = 60000
_POLL_LIMIT = 20000

_PROBES = (
    "tb_zeroer_busy",
    "tb_zeroer_outstanding",
    "tb_zeroer_intp",
    "tb_zeroer_state",
    "tb_zeroer_awvalid",
    "tb_zeroer_awready",
    "tb_zeroer_awlen",
    "tb_zeroer_wvalid",
    "tb_zeroer_wready",
    "tb_zeroer_wlast",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_bvalid",
    "tb_output_axi_bready",
    "tb_output_axi_resp_hold",
)


class _Wire:
    """Passive clk_smc_i sampler of the zeroer and SYS_OUT write channels."""

    def __init__(self) -> None:
        self.rise = 0
        self.aw: list[tuple[int, int]] = []
        self.w: list[tuple[int, int]] = []
        self.b_rises: list[int] = []
        self.out_aw_hs = 0
        self.out_b_hs = 0
        self.out_count = 0
        self.out_max = 0
        self.z_max = 0
        self.last_out_change = 0
        self.intp_rises = 0
        self.state_changes: list[tuple[int, int]] = []
        self.busy_changes: list[tuple[int, int]] = []
        self.stall_aw = 0
        self.stall_w = 0
        self.checked = 0
        self.error: str | None = None
        self._prev_intp = 0
        self._prev_state = -1
        self._prev_busy = -1
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def reset_maxima(self) -> None:
        self.out_max = self.out_count
        self.z_max = 0

    def check(self) -> None:
        assert self.error is None, self.error

    def _get(self, name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z: {sig.value}"
        return int(sig.value)

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            try:
                self._sample()
            except AssertionError as exc:
                self.error = self.error or str(exc)
                raise

    def _sample(self) -> None:
        self.rise += 1
        g = self._get
        z_out = g("tb_zeroer_outstanding")
        # The SYS_OUT count covers the handshakes of earlier rises, as the zeroer counter does.
        if self.out_count > z_out and self.error is None:
            self.error = (
                f"rise {self.rise}: SYS_OUT outstanding AW count {self.out_count} exceeds "
                f"tb_zeroer_outstanding {z_out}"
            )
        self.checked += 1
        self.z_max = max(self.z_max, z_out)
        self.out_max = max(self.out_max, self.out_count)
        state = g("tb_zeroer_state")
        if state != self._prev_state:
            self.state_changes.append((self.rise, state))
            self._prev_state = state
        busy = g("tb_zeroer_busy")
        if busy != self._prev_busy:
            self.busy_changes.append((self.rise, busy))
            self._prev_busy = busy
        intp = g("tb_zeroer_intp")
        if intp and not self._prev_intp:
            self.intp_rises += 1
        self._prev_intp = intp
        awv, awr = g("tb_zeroer_awvalid"), g("tb_zeroer_awready")
        wv, wr = g("tb_zeroer_wvalid"), g("tb_zeroer_wready")
        if awv and awr:
            self.aw.append((self.rise, g("tb_zeroer_awlen")))
        if wv and wr:
            self.w.append((self.rise, g("tb_zeroer_wlast")))
        if wv and not wr:
            self.stall_w += 1
        out_awv, out_awr = g("tb_output_axi_awvalid"), g("tb_output_axi_awready")
        if out_awv and out_awr:
            self.out_aw_hs += 1
        if out_awv and not out_awr:
            self.stall_aw += 1
        if g("tb_output_axi_bvalid") and g("tb_output_axi_bready"):
            self.out_b_hs += 1
            self.b_rises.append(self.rise)
        count = self.out_aw_hs - self.out_b_hs
        if count != self.out_count:
            self.last_out_change = self.rise
        self.out_count = count

    @property
    def plateau_rises(self) -> int:
        return self.rise - self.last_out_change


class smc_zeroer_busy_outstanding_test_seq(output_fabric_pass_all_cfg_seq):
    """Zeroer STATUS lifecycle, busy until the last B, stalls, holds, bursts and AW and W order."""

    def __init__(self, name: str = "smc_zeroer_busy_outstanding_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._printed: list[tuple[str, str]] = []
        self._wire = _Wire()
        self._seed = 0
        self._held: dict = {}

    # -- plumbing ---------------------------------------------------------

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id} printed while the last completed step is "
            f"{self._stamps[-1][0] if self._stamps else None}, expected {step}"
        )
        self._wire.check()
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self._printed.append((chk_id, step))

    async def _hold(self, value: int) -> None:
        dut = cocotb.top
        await FallingEdge(dut.clk_smc_i)
        dut.tb_output_axi_resp_hold.value = value

    async def _status_word(self, name: str) -> int:
        return await self.csr_read(name, ZEROER_CTRL_STATUS, length=8)

    async def _status(self, name: str = "ZEROER_STATUS") -> int:
        return 1 if await self._status_word(name) & STATUS_BM else 0

    def _prime(self, dest: int, size: int) -> None:
        resp = self._responder
        resp.write(dest - _GUARD, bytes([_GUARD_BYTE]) * _GUARD)
        resp.write(dest, bytes([_POISON_BYTE]) * size)
        resp.write(dest + size, bytes([_GUARD_BYTE]) * _GUARD)
        assert resp.read(dest, size) == bytes([_POISON_BYTE]) * size, (
            f"the {size}-byte region at 0x{dest:x} did not take its poison"
        )

    def _compare_zeroed(self, label: str, dest: int, size: int) -> None:
        resp = self._responder
        got = resp.read(dest, size)
        nonzero = sum(1 for b in got if b)
        assert nonzero == 0, f"{label}: {nonzero} of {size} bytes at 0x{dest:x} are not 0"
        want = bytes([_GUARD_BYTE]) * _GUARD
        before, after = resp.read(dest - _GUARD, _GUARD), resp.read(dest + size, _GUARD)
        assert before == want and after == want, (
            f"{label}: bytes outside the range changed: before={before.hex()} after={after.hex()}"
        )

    async def _start(self, label: str, dest: int, size: int) -> int:
        """Program DEST_ADDR and SIZE and write the start; return the sampler rise mark."""
        await self.csr_write(f"ZEROER_DEST_{label}", ZEROER_DEST_ADDR, dest, length=8)
        await self.csr_write(f"ZEROER_SIZE_{label}", ZEROER_SIZE, size, length=8)
        mark = self._wire.rise
        await self.csr_write(
            f"ZEROER_START_{label}", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )
        return mark

    async def _wait(self, what: str, cond, limit: int = _WAIT_RISES) -> None:
        wire = self._wire
        for _ in range(limit):
            wire.check()
            if cond():
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{what} not reached within {limit} clk_smc_i rises: aw={len(wire.aw)} "
            f"w={len(wire.w)} out_aw={wire.out_aw_hs} out_b={wire.out_b_hs} "
            f"out_count={wire.out_count} plateau={wire.plateau_rises}"
        )

    async def _poll_to_zero(self, label: str) -> int:
        """Poll STATUS until it reads 0; return the number of reads that read 1."""
        busy_reads = 0
        for _ in range(_POLL_LIMIT):
            self._wire.check()
            if await self._status(f"ZEROER_POLL_{label}") == 0:
                return busy_reads
            busy_reads += 1
        wire = self._wire
        raise AssertionError(
            f"{label}: STATUS still 1 after {_POLL_LIMIT} polls: aw={len(wire.aw)} "
            f"w={len(wire.w)} out_aw={wire.out_aw_hs} out_b={wire.out_b_hs} "
            f"zeroer_outstanding={int(cocotb.top.tb_zeroer_outstanding.value)}"
        )

    def _outstanding(self) -> int:
        sig = cocotb.top.tb_zeroer_outstanding
        assert sig.value.is_resolvable, f"tb_zeroer_outstanding is X/Z: {sig.value}"
        return int(sig.value)

    async def _finish(self, label: str, dest: int, size: int) -> int:
        """Poll to completion, then require STATUS 0 again, zero outstanding and a zeroed range."""
        busy_reads = await self._poll_to_zero(label)
        again = await self._status(f"ZEROER_AGAIN_{label}")
        assert again == 0, f"{label}: a further STATUS read after completion reads {again}"
        assert self._outstanding() == 0, f"{label}: tb_zeroer_outstanding is not 0 at the end"
        self._compare_zeroed(label, dest, size)
        return busy_reads

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _PROBES:
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        dut.tb_output_axi_resp_hold.value = 0
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        self._seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        cocotb.log.info("ZEROER-BUSY-OUTSTANDING seed=%d", self._seed)
        self._wire.start()
        idle = await self._status("ZEROER_IDLE")
        assert idle == 0, f"STATUS reads {idle} with the zeroer idle"
        self._stamp("S1")

    async def _s2(self) -> str:
        wire = self._wire
        self._prime(_S2_DEST, _JOB_2K)
        before = await self._status("ZEROER_BEFORE")
        assert before == 0, f"STATUS reads {before} before the start write"
        aw0 = len(wire.aw)
        mark = await self._start("S2", _S2_DEST, _JOB_2K)
        reads: list[int] = []
        issuing = 0
        for _ in range(_POLL_LIMIT):
            wire.check()
            status = await self._status("ZEROER_S2")
            reads.append(status)
            if status == 0:
                break
            if len(wire.aw) > aw0:
                issuing += 1
        else:
            raise AssertionError(f"S2: STATUS still 1 after {_POLL_LIMIT} reads: {reads[-8:]}")
        assert reads[0] == 1, f"STATUS reads {reads[0]} after the start write"
        assert issuing >= 1, (
            f"no STATUS read of 1 while the job was issuing (aw handshakes {len(wire.aw) - aw0})"
        )
        again = await self._status("ZEROER_S2_AGAIN")
        assert again == 0, f"a further STATUS read after completion reads {again}"
        assert self._outstanding() == 0, "tb_zeroer_outstanding is not 0 after completion"
        self._compare_zeroed("S2", _S2_DEST, _JOB_2K)
        fell = [r for r, v in wire.busy_changes if v == 0 and r > mark]
        assert fell and len(wire.aw) > aw0, "tb_zeroer_busy never fell after the start write"
        self._stamp("S2")
        return (
            f"STATUS {before} before the start write, {reads[0]} after it, {issuing} reads of 1 "
            f"while the job issued ({len(reads) - 1} polls to completion), then {reads[-1]} and "
            f"{again}; tb_zeroer_busy fell at rise {fell[0]} after {len(wire.aw) - aw0} AW "
            f"handshake(s)"
        )

    async def _s3(self) -> str:
        wire = self._wire
        self._prime(_S3_DEST, _JOB_2K)
        w_last0 = sum(1 for _r, last in wire.w if last)
        b0, aw0 = wire.out_b_hs, len(wire.aw)
        await self._hold(1)
        try:
            mark = await self._start("S3", _S3_DEST, _JOB_2K)
            await self._wait(
                "the last W beat of the held job",
                lambda: sum(1 for _r, last in wire.w if last) > w_last0,
            )
            outstanding_min = 1 << 32
            for _ in range(HOLD_POLLS):
                status = await self._status("ZEROER_S3_HELD")
                outstanding = self._outstanding()
                assert status == 1, f"STATUS reads {status} with B held after all W beats"
                assert outstanding >= 1, "tb_zeroer_outstanding is 0 with B held"
                outstanding_min = min(outstanding_min, outstanding)
            assert wire.out_b_hs == b0, "a B handshake completed during the hold"
        finally:
            await self._hold(0)
        busy_reads = await self._finish("S3", _S3_DEST, _JOB_2K)
        bursts = len(wire.aw) - aw0
        assert wire.out_b_hs - b0 == bursts, (
            f"{wire.out_b_hs - b0} B handshakes for {bursts} AW handshakes"
        )
        fell = [r for r, v in wire.busy_changes if v == 0 and r > mark]
        assert fell, "tb_zeroer_busy never fell"
        assert fell[0] > wire.b_rises[-1], (
            f"tb_zeroer_busy fell at rise {fell[0]}, before the last B handshake at rise "
            f"{wire.b_rises[-1]}"
        )
        self._stamp("S3")
        return (
            f"with B held after the last W beat STATUS read 1 and tb_zeroer_outstanding was at "
            f"least {outstanding_min} at all {HOLD_POLLS} polls; after the release STATUS read 1 "
            f"{busy_reads} more time(s), tb_zeroer_busy fell at rise {fell[0]} after the last B "
            f"handshake at rise {wire.b_rises[-1]} ({bursts} burst), then STATUS 0 and "
            f"tb_zeroer_outstanding 0"
        )

    async def _s4(self) -> str:
        wire = self._wire
        resp = self._responder
        rng = random.Random(self._seed)
        aw_stall, w_stall = rng.randint(4, 8), rng.randint(1, 5)
        applied = [0]

        def delays():
            while True:
                applied[0] += 1
                yield rng.randint(1, 8)

        self._prime(_S4_DEST, _JOB_4K)
        stall_aw0, stall_w0 = wire.stall_aw, wire.stall_w
        resp.enable_backpressure(channels=["aw"], stall_cycles=aw_stall)
        resp.enable_backpressure(channels=["w"], stall_cycles=w_stall)
        resp.set_response_delay(delays(), read=False, write=True)
        try:
            await self._start("S4", _S4_DEST, _JOB_4K)
            await self._finish("S4", _S4_DEST, _JOB_4K)
        finally:
            resp.disable_backpressure()
            resp.clear_response_delay()
        aw_stalls, w_stalls = wire.stall_aw - stall_aw0, wire.stall_w - stall_w0
        assert aw_stalls > 0 and w_stalls > 0 and applied[0] > 0, (
            f"stimulus never applied: aw stall rises {aw_stalls}, w stall rises {w_stalls}, "
            f"B delay draws {applied[0]}"
        )
        self._stamp("S4")
        return (
            f"seed {self._seed}; AWREADY stall {aw_stall}, WREADY stall {w_stall}, per-beat B "
            f"delays 1..8 ({applied[0]} drawn); {aw_stalls} SYS_OUT AW and "
            f"{w_stalls} zeroer W stalled rises; "
            f"the {_JOB_4K}-byte range is exactly zero with the guard bytes either side "
            f"unchanged and STATUS reads 0 with tb_zeroer_outstanding 0 after the last response"
        )

    async def _s5(self) -> tuple[str, str]:
        wire = self._wire
        dut = cocotb.top
        self._prime(_S5_DEST, _JOB_2K)
        intp0 = wire.intp_rises
        await self._hold(1)
        try:
            mark = await self._start("S5", _S5_DEST, _JOB_2K)
            accesses0 = self.accesses
            reads = 0
            words: set[int] = set()
            while wire.rise - mark < LONG_HOLD_RISES:
                wire.check()
                word = await self._status_word("ZEROER_S5_HELD")
                reads += 1
                assert word & STATUS_BM, f"STATUS reads 0 during the hold (read {reads})"
                words.add(word & ~STATUS_BM)
                assert reads <= LONG_HOLD_RISES, "the hold loop made no progress"
            held_rises = wire.rise - mark
            intp_hold = wire.intp_rises - intp0
            state_end = int(dut.tb_zeroer_state.value)
            seen = [s for r, s in wire.state_changes if r > mark]
            writes_in_hold = self.accesses - accesses0 - reads
            outstanding_end = self._outstanding()
        finally:
            await self._hold(0)
        assert writes_in_hold == 0, f"{writes_in_hold} register write(s) during the hold"
        assert intp_hold == 0, f"{intp_hold} interrupt pulse(s) during the hold"
        assert words == {ZEROER_CTRL_STATUS_START}, (
            f"CTRL_STATUS held bits {sorted(f'0x{w:x}' for w in words)} besides STATUS, "
            f"expected only INT_EN (0x{ZEROER_CTRL_STATUS_START:x})"
        )
        busy_reads = await self._finish("S5", _S5_DEST, _JOB_2K)
        pulses = wire.intp_rises - intp0
        assert pulses >= 1, "no completion interrupt pulse after the release"
        self._stamp("S5")
        long_text = (
            f"through the {held_rises}-rise hold STATUS read 1 at all {reads} reads, "
            f"tb_zeroer_intp stayed 0 and {writes_in_hold} register writes were made; after the "
            f"release STATUS read 1 {busy_reads} more time(s), then 0, tb_zeroer_outstanding 0, "
            f"the range zeroed and {pulses} completion interrupt pulse(s)"
        )
        none_text = (
            f"during the {held_rises}-rise hold CTRL_STATUS bits besides STATUS stayed "
            f"0x{ZEROER_CTRL_STATUS_START:x} (INT_EN only) over {reads} reads, interrupt pulses "
            f"{intp_hold}, tb_zeroer_state at the end of the hold {state_end} after transitions "
            f"{'>'.join(str(s) for s in seen)}, tb_zeroer_outstanding {outstanding_end}; no "
            f"timeout indication observed (SF-019 open)"
        )
        return long_text, none_text

    async def _s6(self) -> str:
        wire = self._wire
        self._prime(_S6_DEST, _JOB_96K)
        aw0, b0 = len(wire.aw), wire.out_b_hs
        wire.reset_maxima()
        await self._hold(1)
        try:
            await self._start("S6", _S6_DEST, _JOB_96K)
            await self._wait(
                "the SYS_OUT outstanding AW plateau",
                lambda: wire.out_count >= 1 and wire.plateau_rises >= PLATEAU_RISES,
            )
            status = await self._status("ZEROER_S6_HELD")
            assert status == 1, f"STATUS reads {status} with all B held"
            self._held = {
                "out_max": wire.out_max,
                "z_max": wire.z_max,
                "plateau": wire.plateau_rises,
                "out_at": wire.out_count,
                "aw_issued": len(wire.aw) - aw0,
                "out_b": wire.out_b_hs - b0,
            }
        finally:
            await self._hold(0)
        busy_reads = await self._finish("S6", _S6_DEST, _JOB_96K)
        bursts = len(wire.aw) - aw0
        assert bursts > 32, f"the {_JOB_96K}-byte job issued {bursts} bursts, not more than 32"
        assert wire.out_b_hs - b0 == bursts, (
            f"{wire.out_b_hs - b0} B handshakes for {bursts} AW handshakes"
        )
        assert self._held["out_b"] == 0, "a B handshake completed during the hold"
        self._stamp("S6")
        h = self._held
        return (
            f"{_JOB_96K}-byte job of {bursts} bursts with all B held: {h['aw_issued']} AW "
            f"handshakes issued before the ready handshakes stopped it with {h['out_at']} "
            f"outstanding at SYS_OUT and no B handshake; after the release every response was "
            f"consumed ({wire.out_b_hs - b0} B), STATUS read 1 {busy_reads} more time(s) then 0, "
            f"tb_zeroer_outstanding 0 and the range is exactly zero"
        )

    async def _s7(self) -> str:
        wire = self._wire
        h = self._held
        again = await self._status("ZEROER_S7")
        assert again == 0, f"STATUS reads {again} after the held job completed"
        assert wire.checked > 0, "no rise was sampled"
        self._stamp("S7")
        return (
            f"during the held {_JOB_96K}-byte job the maximum outstanding AW count at SYS_OUT "
            f"was {h['out_max']} and the maximum tb_zeroer_outstanding was {h['z_max']}, "
            f"plateau {h['plateau']} rises; at all {wire.checked} sampled rises the SYS_OUT count "
            f"was not above tb_zeroer_outstanding; the cap value is not asserted (SF-017 open)"
        )

    async def _s8(self) -> str:
        wire = self._wire
        self._prime(_S8_DEST, _JOB_4K)
        aw0, w0 = len(wire.aw), len(wire.w)
        await self._start("S8", _S8_DEST, _JOB_4K)
        await self._finish("S8", _S8_DEST, _JOB_4K)
        aws, ws = wire.aw[aw0:], wire.w[w0:]
        assert len(aws) >= 2, f"the {_JOB_4K}-byte job issued {len(aws)} burst(s)"
        k = beats = total = 0
        for rise, last in ws:
            assert k < len(aws) and aws[k][0] < rise, (
                f"W beat at rise {rise} before the AW handshake of burst {k}"
            )
            beats += 1
            total += 1
            want = aws[k][1] + 1
            if last:
                assert beats == want, f"burst {k}: {beats} W beats, AWLEN + 1 = {want}"
                k += 1
                beats = 0
            else:
                assert beats < want, f"burst {k}: WLAST missing on beat {beats} of {want}"
        assert beats == 0 and k == len(aws), (
            f"{k} of {len(aws)} bursts completed their W beats ({beats} trailing)"
        )
        assert total * 8 == _JOB_4K, f"{total} W beats carry {total * 8} of {_JOB_4K} bytes"
        self._stamp("S8")
        return (
            f"{len(aws)} bursts of a {_JOB_4K}-byte job: every AW handshake preceded the first W "
            f"beat of its burst, AWLEN + 1 = "
            f"{'/'.join(str(a[1] + 1) for a in aws)} W beats with WLAST on the last, "
            f"{total} W beats in all"
        )

    async def body(self) -> None:
        try:
            await self._s1()
            text = await self._s2()
            self._chk("S2", "CHK-ZEROER-BUSY-LIFECYCLE", text)
            text = await self._s3()
            self._chk("S3", "CHK-ZEROER-BUSY-UNTIL-LAST-B", text)
            text = await self._s4()
            self._chk("S4", "CHK-ZEROER-RANDOM-STALL", text)
            long_text, none_text = await self._s5()
            self._chk("S5", "CHK-ZEROER-LONG-STALL", long_text)
            self._chk("S5", "CHK-ZEROER-NO-TIMEOUT-INDICATION", none_text)
            text = await self._s6()
            self._chk("S6", "CHK-ZEROER-GT32-BURSTS", text)
            text = await self._s7()
            self._chk("S7", "CHK-ZEROER-AW-CAP", text)
            text = await self._s8()
            self._chk("S8", "CHK-ZEROER-AW-W-ORDER", text)
            self._wire.check()
            self._nonvac()
        finally:
            self._wire.stop()
            cocotb.top.tb_output_axi_resp_hold.value = 0

    def _nonvac(self) -> None:
        steps = [s for s, _t in self._stamps]
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
        assert steps == order, f"step stamps {steps} not in contract order"
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"step stamps {times} are not strictly increasing"
        )
        ids = [c for c, _s in self._printed]
        want = [
            ("CHK-ZEROER-BUSY-LIFECYCLE", "S2"),
            ("CHK-ZEROER-BUSY-UNTIL-LAST-B", "S3"),
            ("CHK-ZEROER-RANDOM-STALL", "S4"),
            ("CHK-ZEROER-LONG-STALL", "S5"),
            ("CHK-ZEROER-NO-TIMEOUT-INDICATION", "S5"),
            ("CHK-ZEROER-GT32-BURSTS", "S6"),
            ("CHK-ZEROER-AW-CAP", "S7"),
            ("CHK-ZEROER-AW-W-ORDER", "S8"),
        ]
        assert self._printed == want, f"checker lines {self._printed} not in step order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines CHK-ZEROER-BUSY-LIFECYCLE, "
            "CHK-ZEROER-BUSY-UNTIL-LAST-B, CHK-ZEROER-RANDOM-STALL, CHK-ZEROER-LONG-STALL, "
            "CHK-ZEROER-NO-TIMEOUT-INDICATION, CHK-ZEROER-GT32-BURSTS, CHK-ZEROER-AW-CAP, "
            "CHK-ZEROER-AW-W-ORDER print in step order, step stamps strictly increasing, each "
            "line after its own compare; checker lines %s; stamps %s ps",
            ",".join(ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
