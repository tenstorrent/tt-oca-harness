# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer completion interrupt count, timing, INT_EN control and PLIC source 324.

Contract SMC_POWER_DMA_ZEROER_025, anchor smc_zeroer_irq_test.
Scenarios ZEROER-IRQ.S1 to ZEROER-IRQ.S5.
Sources hw/sys/smc/doc/zeroer.adoc, hw/sys/smc/doc/interrupts.adoc, zeroer_ctrl.rdl.

A passive sampler reads tb_zeroer_intp, tb_plic_pending_324, tb_dma_intp, the SYS_OUT
B handshake and the zeroer's last W beat at every clk_smc_i rise. A 2 KiB job with
INT_EN set must raise exactly one pulse after its last B handshake, with the PLIC
pending bit set and tb_dma_intp low; the same job with INT_EN clear raises none; a job
whose B responses are held raises none until they are released; two back-to-back jobs
raise two pulses; a SIZE 0 trigger raises none. The pulse width and the outcome of an
INT_EN write while a job is held busy are measured and printed.
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
INT_EN_SET = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", int_en=1)
INT_EN_CLEAR = 0
STATUS_BM = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", status=1)

_JOB_BYTES = 2 * 1024
_POISON_BYTE = 0xA5

# Bounds are liveness ceilings, not checked quantities: expiry FAILS.
_BUSY_ASSERT_CYCLES = 4000
_BUSY_CLEAR_CYCLES = 40000
_PULSE_WAIT_CYCLES = 4000
_W_LAST_WAIT_CYCLES = 4000
# Observation windows over which an absence (no further or no early pulse) is required.
_QUIET_CYCLES = 64
_HELD_CYCLES = 200
_ZERO_SIZE_CYCLES = 400

_PROBES = (
    "tb_zeroer_intp",
    "tb_plic_pending_324",
    "tb_dma_intp",
    "tb_output_axi_bvalid",
    "tb_output_axi_bready",
    "tb_zeroer_wvalid",
    "tb_zeroer_wready",
    "tb_zeroer_wlast",
    "tb_output_axi_resp_hold",
)


class _Sampler:
    """Clk_smc_i-rise sampler; events are stamped with the rise index."""

    def __init__(self) -> None:
        self.cycle = 0
        self.intp_rises: list[int] = []
        self.widths: list[int] = []
        self.pending_rises: list[int] = []
        self.pending = 0
        self.dma_high = 0
        self.b_hs: list[int] = []
        self.w_last: list[int] = []
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        prev_intp = prev_pending = width = 0
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.cycle += 1
            sigs = [getattr(dut, name) for name in _PROBES]
            for sig in sigs:
                assert sig.value.is_resolvable, f"{sig._name} is X/Z at rise {self.cycle}"
            intp, pending, dma, bv, br, wv, wr, wl, _hold = (int(s.value) for s in sigs)
            if intp and not prev_intp:
                self.intp_rises.append(self.cycle)
                width = 0
            if intp:
                width += 1
            elif prev_intp:
                self.widths.append(width)
            if pending and not prev_pending:
                self.pending_rises.append(self.cycle)
            self.pending = pending
            self.dma_high += dma
            if bv and br:
                self.b_hs.append(self.cycle)
            if wv and wr and wl:
                self.w_last.append(self.cycle)
            prev_intp, prev_pending = intp, pending


class smc_zeroer_irq_test_seq(output_fabric_pass_all_cfg_seq):
    """Zeroer completion interrupt checks for INT_EN set, clear, held, repeated and zero size."""

    def __init__(self, name: str = "smc_zeroer_irq_test_seq") -> None:
        super().__init__(name)
        self.jobs = 0
        self._stamps: list[tuple[str, int]] = []
        self._printed: list[tuple[str, str]] = []

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id} printed while the last completed step is "
            f"{self._stamps[-1][0] if self._stamps else None}, expected {step}"
        )
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self._printed.append((chk_id, step))

    async def _status_word(self) -> int:
        return await self.csr_read("ZEROER_CTRL_STATUS_POLL", ZEROER_CTRL_STATUS, length=8)

    async def _status(self) -> int:
        return 1 if await self._status_word() & STATUS_BM else 0

    async def _await_status(self, want: int, cycles: int, what: str) -> None:
        last = -1
        for _ in range(cycles):
            last = await self._status()
            if last == want:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"CTRL_STATUS.STATUS never {what} within {cycles} polls; last STATUS {last}, "
            f"interrupt rises {self.sampler.intp_rises}, B handshakes {len(self.sampler.b_hs)}"
        )

    async def _await_cycles(self, cond, cycles: int, what: str) -> None:
        for _ in range(cycles):
            if cond():
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{what} within {cycles} clk_smc_i cycles; interrupt rises "
            f"{self.sampler.intp_rises}, B handshakes {len(self.sampler.b_hs)}, "
            f"last W beats {self.sampler.w_last}"
        )

    async def _set_hold(self, value: int) -> None:
        dut = cocotb.top
        await FallingEdge(dut.clk_smc_i)
        dut.tb_output_axi_resp_hold.value = value

    def _poison(self) -> None:
        poison = bytes([_POISON_BYTE]) * _JOB_BYTES
        self._responder.write(OUTPUT_FABRIC_ADDR, poison)
        assert self._responder.read(OUTPUT_FABRIC_ADDR, _JOB_BYTES) == poison, (
            f"the {_JOB_BYTES}-byte region did not take its poison"
        )

    def _assert_zeroed(self, label: str) -> None:
        left = sum(1 for b in self._responder.read(OUTPUT_FABRIC_ADDR, _JOB_BYTES) if b)
        assert left == 0, f"{label}: {left} non-zero byte(s) left in the {_JOB_BYTES}-byte region"

    async def _start(self, label: str, int_en: int) -> None:
        await self.csr_write(
            f"ZEROER_CTRL_STATUS_START_{label}", ZEROER_CTRL_STATUS, int_en, length=8
        )
        self.jobs += 1

    async def _complete(self, label: str, expect_rises: int | None, busy_first: bool = True) -> int:
        """Wait for busy then idle, then for `expect_rises` rises and a quiet window."""
        s = self.sampler
        if busy_first:
            await self._await_status(1, _BUSY_ASSERT_CYCLES, f"{label}: left its idle level")
        await self._await_status(0, _BUSY_CLEAR_CYCLES, f"{label}: returned to its idle level")
        if expect_rises is not None:
            await self._await_cycles(
                lambda: len([c for c in s.intp_rises if c > self._mark]) >= expect_rises,
                _PULSE_WAIT_CYCLES,
                f"{label}: fewer than {expect_rises} interrupt pulse(s) after STATUS returned idle",
            )
        await ClockCycles(cocotb.top.clk_smc_i, _QUIET_CYCLES)
        return len([c for c in s.intp_rises if c > self._mark])

    def _rises_since(self) -> list[int]:
        return [c for c in self.sampler.intp_rises if c > self._mark]

    async def body(self) -> None:
        dut = cocotb.top
        for name in _PROBES:
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        self._responder = self.cfg.sys_out_mem
        assert self._responder is not None, "SYS_OUT responder not bound"
        s = self.sampler = _Sampler()
        self._mark = 0

        # S1: setup.
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8)
        await self.csr_read(
            "ZEROER_DEST_ADDR_RB", ZEROER_DEST_ADDR, expected=OUTPUT_FABRIC_ADDR, length=8
        )
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, _JOB_BYTES, length=8)
        await self.csr_read("ZEROER_SIZE_RB", ZEROER_SIZE, expected=_JOB_BYTES, length=8)
        idle = await self._status()
        assert idle == 0, f"STATUS reads {idle} with the zeroer idle before any job"
        s.start()
        await ClockCycles(dut.clk_smc_i, 4)
        assert s.cycle >= 3, f"the sampler saw {s.cycle} clk_smc_i rise(s) in 4 cycles"
        assert s.pending == 0, "tb_plic_pending_324 is already set before any job"
        self._stamp("S1")

        # S2: INT_EN = 1 job.
        self._poison()
        self._mark = s.cycle
        await self._start("S2", INT_EN_SET)
        n = await self._complete("S2", 1)
        self._assert_zeroed("S2")
        status_word = await self._status_word()
        rises = self._rises_since()
        last_b = s.b_hs[-1] if s.b_hs else -1
        pend = [c for c in s.pending_rises if c > self._mark]
        assert n == 1, f"S2: {n} interrupt pulse(s), expected 1 (rises {rises})"
        assert last_b > 0, "S2: no B handshake observed on the SYS_OUT egress"
        assert rises[0] > last_b, f"S2: pulse rise {rises[0]} before the last B handshake {last_b}"
        assert pend and pend[0] >= rises[0], (
            f"S2: tb_plic_pending_324 rises {pend} not observed at or after the pulse rise "
            f"{rises[0]}"
        )
        assert s.pending == 1, "S2: tb_plic_pending_324 is not set after the pulse"
        assert s.dma_high == 0, f"S2: tb_dma_intp high for {s.dma_high} rise(s)"
        s2_width = s.widths[-1] if s.widths else -1
        assert s2_width >= 1, "S2: the pulse did not fall inside the quiet window"
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-ZEROER-IRQ-ONE-PULSE",
            "INT_EN job of %d bytes: %d tb_zeroer_intp pulse at rise %d after the last B "
            "handshake at rise %d, tb_plic_pending_324 rose at rise %d and stayed set "
            "(observation point SF-007), tb_dma_intp high %d rise(s), quiet window %d rises, "
            "pulse width %d rise(s), STATUS word 0x%x",
            _JOB_BYTES,
            n,
            rises[0],
            last_b,
            pend[0],
            s.dma_high,
            _QUIET_CYCLES,
            s2_width,
            status_word,
        )

        # S3: INT_EN = 0 job.
        self._poison()
        self._mark = s.cycle
        await self._start("S3", INT_EN_CLEAR)
        n = await self._complete("S3", None)
        self._assert_zeroed("S3")
        status_word = await self._status_word()
        assert status_word & STATUS_BM == 0, f"S3: STATUS set at completion (0x{status_word:x})"
        assert n == 0, f"S3: {n} interrupt pulse(s) with INT_EN clear (rises {self._rises_since()})"
        assert s.dma_high == 0, f"S3: tb_dma_intp high for {s.dma_high} rise(s)"
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-ZEROER-IRQ-NONE-WHEN-DISABLED",
            "INT_EN clear job of %d bytes: STATUS 0 at completion (word 0x%x), %d "
            "tb_zeroer_intp pulses through completion and a %d rise quiet window, after the "
            "INT_EN job raised %d pulse with the same sampler",
            _JOB_BYTES,
            status_word,
            n,
            _QUIET_CYCLES,
            len(s.intp_rises),
        )

        # S4: B responses held after the last W beat.
        self._poison()
        await self._set_hold(1)
        self._mark = s.cycle
        try:
            await self._start("S4", INT_EN_SET)
            await self._await_cycles(
                lambda: any(c > self._mark for c in s.w_last),
                _W_LAST_WAIT_CYCLES,
                "S4: no last W beat",
            )
            await ClockCycles(dut.clk_smc_i, _HELD_CYCLES)
            held_status = await self._status()
            release = s.cycle
            held_rises = self._rises_since()
            held_b = [c for c in s.b_hs if c > self._mark]
        finally:
            await self._set_hold(0)
        await ClockCycles(dut.clk_smc_i, 1)
        n = await self._complete("S4", 1, busy_first=False)
        self._assert_zeroed("S4")
        rises = self._rises_since()
        last_w = [c for c in s.w_last if c > self._mark][-1]
        last_b = s.b_hs[-1]
        assert held_status == 1, f"S4: STATUS {held_status} while the responses are held"
        assert not held_b, f"S4: B handshakes {held_b} while the responses are held"
        assert not held_rises, f"S4: pulse(s) at rises {held_rises} while held until {release}"
        assert last_b > release, f"S4: last B handshake {last_b} not after the release {release}"
        assert n == 1, f"S4: {n} interrupt pulse(s), expected 1 (rises {rises})"
        assert rises[0] >= last_b, f"S4: pulse rise {rises[0]} before last B handshake {last_b}"
        assert rises[0] != last_w, f"S4: pulse rise {rises[0]} at the last W beat {last_w}"
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-ZEROER-IRQ-AFTER-LAST-B",
            "B held from the job start across %d rises past the last W beat at rise %d: STATUS "
            "%d, %d B handshakes and %d pulses while held; released at rise %d, last B "
            "handshake at rise %d, pulse rose at rise %d (%d rise(s) after the last B)",
            _HELD_CYCLES,
            last_w,
            held_status,
            len(held_b),
            len(held_rises),
            release,
            last_b,
            rises[0],
            rises[0] - last_b,
        )

        # S5: two back-to-back jobs.
        self._poison()
        self._mark = s.cycle
        await self._start("S5_JOB1", INT_EN_SET)
        await self._await_status(1, _BUSY_ASSERT_CYCLES, "S5 job 1: left its idle level")
        await self._await_status(0, _BUSY_CLEAR_CYCLES, "S5 job 1: returned to its idle level")
        await self._start("S5_JOB2", INT_EN_SET)
        n = await self._complete("S5", 2)
        self._assert_zeroed("S5")
        rises = self._rises_since()
        assert n == 2, f"S5: {n} interrupt pulse(s) for two jobs, expected 2 (rises {rises})"
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-ZEROER-IRQ-TWO-JOBS",
            "two back-to-back INT_EN jobs of %d bytes: %d tb_zeroer_intp pulses at rises %s, "
            "quiet window %d rises",
            _JOB_BYTES,
            n,
            ",".join(str(c) for c in rises),
            _QUIET_CYCLES,
        )

        # S6: SIZE 0 trigger, then an INT_EN write while a job is held busy.
        await self.csr_write("ZEROER_SIZE_ZERO", ZEROER_SIZE, 0, length=8)
        await self.csr_read("ZEROER_SIZE_ZERO_RB", ZEROER_SIZE, expected=0, length=8)
        self._mark = s.cycle
        await self._start("S6_ZERO", INT_EN_SET)
        status_seen = []
        for _ in range(_ZERO_SIZE_CYCLES // 8):
            status_seen.append(await self._status())
            await ClockCycles(dut.clk_smc_i, 8)
        zero_rises = self._rises_since()
        assert not zero_rises, f"S6: pulse(s) at rises {zero_rises} from a SIZE 0 trigger"
        assert s.widths, "S6: the sampler saw no pulse of any earlier job; its width is unknown"
        widths = list(s.widths)

        await self.csr_write("ZEROER_SIZE_HELD", ZEROER_SIZE, _JOB_BYTES, length=8)
        self._poison()
        await self._set_hold(1)
        self._mark = s.cycle
        try:
            await self._start("S6_HELD", INT_EN_SET)
            await self._await_status(1, _BUSY_ASSERT_CYCLES, "S6 held job: left its idle level")
            await self.csr_write(
                "ZEROER_INT_EN_WHILE_BUSY", ZEROER_CTRL_STATUS, INT_EN_CLEAR, length=8
            )
            word_busy = await self._status_word()
            rises_busy = len(self._rises_since())
        finally:
            await self._set_hold(0)
        await ClockCycles(dut.clk_smc_i, 1)
        n = await self._complete("S6 held job", None, busy_first=False)
        word_end = await self._status_word()
        self._stamp("S6")
        self._chk(
            "S6",
            "CHK-ZEROER-IRQ-ZERO-SIZE-WIDTH",
            "SIZE 0 trigger with INT_EN set: %d pulses over %d rises, STATUS samples %s; pulse "
            "widths of the earlier jobs %s rise(s) (SF-008); INT_EN cleared by a write while a "
            "job was held busy: CTRL_STATUS word 0x%x right after, %d pulse(s) while held, "
            "%d pulse(s) after release, CTRL_STATUS word 0x%x at the end (SF-005)",
            len(zero_rises),
            _ZERO_SIZE_CYCLES,
            "".join(str(v) for v in status_seen),
            ",".join(str(w) for w in widths),
            word_busy,
            rises_busy,
            n,
            word_end,
        )

        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
        s.stop()
        self._nonvac()

    def _nonvac(self) -> None:
        steps = [s for s, _t in self._stamps]
        assert steps == ["S1", "S2", "S3", "S4", "S5", "S6"], (
            f"step stamps {steps} not in contract order"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"step stamps {times} are not strictly increasing"
        )
        want = [
            ("CHK-ZEROER-IRQ-ONE-PULSE", "S2"),
            ("CHK-ZEROER-IRQ-NONE-WHEN-DISABLED", "S3"),
            ("CHK-ZEROER-IRQ-AFTER-LAST-B", "S4"),
            ("CHK-ZEROER-IRQ-TWO-JOBS", "S5"),
            ("CHK-ZEROER-IRQ-ZERO-SIZE-WIDTH", "S6"),
        ]
        assert self._printed == want, f"checker lines {self._printed} not in step order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6 with checker lines %s printed in step "
            "order after their own compares; checker lines %s; stamps %s ps",
            "CHK-ZEROER-IRQ-ONE-PULSE,CHK-ZEROER-IRQ-NONE-WHEN-DISABLED,"
            "CHK-ZEROER-IRQ-AFTER-LAST-B,CHK-ZEROER-IRQ-TWO-JOBS,CHK-ZEROER-IRQ-ZERO-SIZE-WIDTH",
            ",".join(c for c, _s in self._printed),
            ",".join(str(t) for t in times),
        )
