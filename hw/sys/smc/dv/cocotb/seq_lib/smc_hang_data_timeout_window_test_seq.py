# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DATA_ACCEL hang detector below, beyond and at the timeout threshold.

Contract SMC_IRQ_021, anchor smc_hang_data_timeout_window_test.
Allocated scenarios: IRQ-HANG-TIMEOUT.S3.
Spec sources: HANG_DET_CTRL and HANG_DET_TIMEOUT_THRESHOLD in smc_base_config.rdl.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_DATA_ACCEL_TIMEOUT,
    HANG_DET_IRQ,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_THR_VALUE,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)

DATA_BIT = 286
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0008
DMA_LENGTH = 8
THRESHOLD = 0x40
THRESHOLD_CLEANUP = 0x1000
BELOW_HOLD_RISES = 16
BELOW_WINDOW_RISES = 256
BEYOND_CEILING_RISES = 128
AT_AFTER_RISES = 8
HANDSHAKE_CEILING_RISES = 4096
CLEAR_CEILING_RISES = 128
DONE_POLLS = 50
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = ("CHK-DATAWIN-BELOW", "CHK-DATAWIN-BEYOND", "CHK-DATAWIN-AT-LOG")
_CHECK_STEP = ("S2", "S3", "S4")


class smc_hang_data_timeout_window_test_seq(SmcCsrSeq):
    """Hold one DMA job at the SYS_OUT responses for 16, past-threshold and 0x40 rises."""

    def __init__(self, name: str = "smc_hang_data_timeout_window_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[str, str]] = {}
        self._jobs = 0
        self._done = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _resolved(sig, label: str) -> int:
        assert sig.value.is_resolvable, f"{label}: {sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    def _sample(self, label: str) -> tuple[int, int, int, int]:
        """Return (data irq, raw bit 286, sys irq, sep irq) at this rise."""
        dut = cocotb.top
        data = self._resolved(dut.tb_axi_hang_irq_data, label) & 1
        raw = self._resolved(dut.tb_cpu_interrupts, label) >> DATA_BIT & 1
        sys_irq = self._resolved(dut.tb_axi_hang_irq_sys, label) & 1
        sep = self._resolved(dut.tb_axi_hang_irq_sep, label) & 1
        return data, raw, sys_irq, sep

    def _hold(self, value: int, why: str) -> None:
        cocotb.top.tb_output_axi_resp_hold.value = value
        cocotb.log.info(
            "DRIVE tb_output_axi_resp_hold=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    async def _await_handshake(self, name: str) -> None:
        dut = cocotb.top
        wait = f"{name} SYS_OUT AR/AW handshake wait"
        last = "no rise yet"
        self._waits[wait] = (f"{HANDSHAKE_CEILING_RISES} rises", last)
        for n in range(1, HANDSHAKE_CEILING_RISES + 1):
            await RisingEdge(dut.clk_smc_i)
            arv, arr, awv, awr = (
                self._resolved(getattr(dut, f"tb_output_axi_{p}"), wait) & 1
                for p in ("arvalid", "arready", "awvalid", "awready")
            )
            last = f"ar={arv}/{arr} aw={awv}/{awr} after {n} rises"
            self._waits[wait] = (f"{HANDSHAKE_CEILING_RISES} rises", last)
            if (arv and arr) or (awv and awr):
                return
        raise AssertionError(
            f"{wait}: no SYS_OUT handshake in {HANDSHAKE_CEILING_RISES} rises (last {last})"
        )

    async def _program_dma(self) -> None:
        regs = (
            ("CONFIG", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            ("DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, DMA_DST_ADDR & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32),
            ("SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32),
            ("LENGTH_LO", DMA_CTRL_LENGTH_LO, DMA_LENGTH),
            ("LENGTH_HI", DMA_CTRL_LENGTH_HI, 0),
            ("DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, 0),
            ("DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0),
            ("SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, 0),
            ("SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0),
            ("NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, 1),
            ("NUM_REPETITIONS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0),
        )
        for label, addr, value in regs:
            await self.csr_write(f"DMA_{label}", addr, value)
        start_id = await self.csr_read("DMA_NEXT_ID_0_START", DMA_CTRL_NEXT_ID_0)
        assert start_id != 0, "DMA command was not accepted"

    async def _run_job(self, name: str, window):
        """Start a held DMA job; run window(name) from the handshake; return its result."""
        self._jobs += 1
        self._hold(1, f"{name} stall")
        track = cocotb.start_soon(self._tracked(name, window))
        await self._program_dma()
        return await track

    async def _tracked(self, name: str, window):
        await self._await_handshake(name)
        return await window(name)

    async def _await_done(self, name: str) -> int:
        wait = f"{name} DMA_CTRL_DONE_0 poll"
        self._waits[wait] = (f"{DONE_POLLS} polls", "no poll yet")
        done = self._done
        for n in range(1, DONE_POLLS + 1):
            done = await self.csr_read(f"DMA_DONE_0_POLL_{name}", DMA_CTRL_DONE_0)
            self._waits[wait] = (
                f"{DONE_POLLS} polls",
                f"done={done} baseline={self._done} after {n} polls",
            )
            if done > self._done:
                self._done = done
                return n
        raise AssertionError(
            f"{wait}: job not complete after {DONE_POLLS} polls (done={done} baseline={self._done})"
        )

    async def _await_data_low(self, name: str) -> int:
        wait = f"{name} data irq clear wait"
        bound = f"{CLEAR_CEILING_RISES} rises"
        self._waits[wait] = (bound, "no rise yet")
        for n in range(0, CLEAR_CEILING_RISES + 1):
            data, raw, _, _ = self._sample(wait)
            self._waits[wait] = (bound, f"data={data} raw286={raw} after {n} rises")
            if data == 0 and raw == 0:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{wait}: data irq={data} raw286={raw} after {bound}")

    async def _below_window(self, name: str) -> int:
        wait = f"{name} window"
        self._waits[wait] = (f"{BELOW_WINDOW_RISES} rises", "no rise yet")
        for n in range(1, BELOW_WINDOW_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == BELOW_HOLD_RISES:
                self._hold(0, "below-threshold release")
            data, raw, _, _ = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (
                f"{BELOW_WINDOW_RISES} rises",
                f"data={data} raw286={raw} rise {n}",
            )
            assert data == 0 and raw == 0, (
                f"{wait}: data irq={data} raw286={raw} at rise {n}, want 0/0 "
                f"(stall {BELOW_HOLD_RISES} rises, threshold 0x{THRESHOLD:x})"
            )
        return BELOW_WINDOW_RISES

    async def _beyond_window(self, name: str) -> tuple[int, int]:
        wait = f"{name} irq wait"
        bound = f"{BEYOND_CEILING_RISES} rises"
        self._waits[wait] = (bound, "no rise yet")
        data_at = raw_at = 0
        data = raw = sys_irq = sep = 0
        for n in range(1, BEYOND_CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            data, raw, sys_irq, sep = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (
                bound,
                f"data={data} raw286={raw} sys={sys_irq} sep={sep} after {n} rises",
            )
            assert sys_irq == 0 and sep == 0, (
                f"{wait}: peer irq sys={sys_irq} sep={sep} at rise {n}, want 0/0"
            )
            data_at = data_at or (n if data else 0)
            raw_at = raw_at or (n if raw else 0)
            if data_at and raw_at:
                return data_at, raw_at
        raise AssertionError(
            f"{wait}: data irq rose at {data_at}, raw286 at {raw_at} within {bound} of the "
            f"handshake (last data={data} raw286={raw})"
        )

    async def _at_window(self, name: str) -> int:
        wait = f"{name} window"
        total = THRESHOLD + AT_AFTER_RISES
        self._waits[wait] = (f"{total} rises", "no rise yet")
        first = 0
        for n in range(1, total + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == THRESHOLD:
                self._hold(0, "at-threshold release")
            data, raw, _, _ = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (f"{total} rises", f"data={data} raw286={raw} rise {n}")
            first = first or (n if data else 0)
        return first

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            "tb_output_axi_resp_hold",
            "tb_axi_hang_irq_data",
            "tb_axi_hang_irq_sys",
            "tb_axi_hang_irq_sep",
            "tb_cpu_interrupts",
            "tb_output_axi_arvalid",
            "tb_output_axi_arready",
            "tb_output_axi_awvalid",
            "tb_output_axi_awready",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        self._hold(0, "idle")
        cocotb.log.info("SEED RANDOM_SEED=%s", os.environ.get("RANDOM_SEED", "1"))

        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_SEP_OFF", HANG_DET_SEP_AXI_CTRL, 0)
        for side, start, end, config in (
            ("INBOUND0", INBOUND0_START, INBOUND0_END, INBOUND0_FILTER_CONFIG),
            ("OUTBOUND0", OUTBOUND0_START, OUTBOUND0_END, OUTBOUND0_FILTER_CONFIG),
        ):
            await self.csr_write(f"{side}_START_PASS_ALL", start, 0, length=8)
            await self.csr_write(f"{side}_END_PASS_ALL", end, PASS_ALL_END, length=8)
            await self.csr_write(f"{side}_CONFIG_PASS_ALL", config, PASS_ALL_CONFIG, length=8)
        await self.csr_write("HANG_DATA_THR", HANG_DET_DATA_ACCEL_TIMEOUT, THRESHOLD)
        thr = await self.csr_read(
            "HANG_DATA_THR_RB", HANG_DET_DATA_ACCEL_TIMEOUT, expected=THRESHOLD
        )
        assert (thr & HANG_DET_THR_VALUE) == THRESHOLD, (
            f"DATA threshold readback 0x{thr:x} want 0x{THRESHOLD:x}"
        )
        await self.csr_write("HANG_DATA_ARM", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_ARMED)
        await self.csr_read("HANG_DATA_ARM_RB", HANG_DET_DATA_ACCEL_CTRL, expected=HANG_DET_ARMED)
        self._done = await self.csr_read("DMA_DONE_0_BASELINE", DMA_CTRL_DONE_0)
        await RisingEdge(dut.clk_smc_i)
        base = self._resolved(dut.tb_cpu_interrupts, "baseline")
        sample = self._sample("baseline")
        assert sample == (0, 0, 0, 0), f"baseline data/raw286/sys/sep = {sample}"
        cocotb.log.info(
            "BASELINE vector=0x%x thr=0x%x ctrl=0x%x data=0 raw286=0", base, thr, HANG_DET_ARMED
        )
        self.phases += 1
        self._mark_step("S1")

        zero_rises = await self._run_job("below", self._below_window)
        polls = await self._await_done("below")
        self.phases += 1
        self._mark_step("S2")
        self._log_legs(
            "CHK-DATAWIN-BELOW",
            f"DMA job held {BELOW_HOLD_RISES} rises with threshold 0x{THRESHOLD:x}",
            "tb_axi_hang_irq_data and tb_cpu_interrupts[286] each rise",
            f"hold released and job completed after {polls} polls",
            f"both probes read 0 for {zero_rises} rises",
        )
        self._log_chk(
            "CHK-DATAWIN-BELOW",
            f"stall {BELOW_HOLD_RISES} rises, threshold 0x{THRESHOLD:x}: data irq and "
            f"raw286 read 0 at each of {zero_rises} rises from the SYS_OUT handshake",
        )

        data_at, raw_at = await self._run_job("beyond", self._beyond_window)
        rdata = await self.csr_read("HANG_DATA_CTRL_IRQ", HANG_DET_DATA_ACCEL_CTRL)
        assert rdata & HANG_DET_IRQ, f"HANG_DET_DATA_ACCEL_CTRL=0x{rdata:x}: irq bit reads 0"
        self._hold(0, "beyond-threshold release")
        await self.csr_write("HANG_DATA_CTRL_OFF_BEYOND", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self._await_done("beyond")
        cleared = await self._await_data_low("beyond")
        self.phases += 1
        self._mark_step("S3")
        self._log_legs(
            "CHK-DATAWIN-BEYOND",
            f"DMA job held past threshold 0x{THRESHOLD:x}",
            "tb_axi_hang_irq_data, tb_cpu_interrupts[286] and CTRL.irq",
            "CTRL written 0 after the release",
            f"tb_axi_hang_irq_data and raw286 read 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-DATAWIN-BEYOND",
            f"data irq first 1 at rise {data_at}, raw286 first 1 at rise {raw_at} "
            f"(ceiling {BEYOND_CEILING_RISES}); sys=0 sep=0; CTRL=0x{rdata:x} irq=1; "
            f"cleared after {cleared} rises",
        )

        await self.csr_write("HANG_DATA_ARM_AT", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_ARMED)
        await self.csr_read(
            "HANG_DATA_ARM_AT_RB", HANG_DET_DATA_ACCEL_CTRL, expected=HANG_DET_ARMED
        )
        first = await self._run_job("at", self._at_window)
        await self.csr_write("HANG_DATA_CTRL_OFF_AT", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self._await_done("at")
        cleared_at = await self._await_data_low("at")
        if not first:
            text = (
                f"data irq did not rise within {THRESHOLD + AT_AFTER_RISES} rises of the handshake"
            )
        elif first <= THRESHOLD:
            text = f"data irq rose at rise {first}, before the release at rise {THRESHOLD}"
        else:
            text = f"data irq rose at rise {first}, {first - THRESHOLD} after the release"
        self.phases += 1
        self._mark_step("S4")
        self._log_chk(
            "CHK-DATAWIN-AT-LOG",
            f"stall of exactly 0x{THRESHOLD:x} rises: first_data_irq_rise={first}; "
            f"{text}; cleared after {cleared_at} rises (observe-and-log, SF-009)",
        )

        self._hold(0, "cleanup")
        await self.csr_write("HANG_DATA_CTRL_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self.csr_write(
            "HANG_DATA_THR_CLEANUP", HANG_DET_DATA_ACCEL_TIMEOUT, THRESHOLD_CLEANUP
        )
        self.phases += 1
        self._mark_step("S5")

        self._nonvac_fence()
        self._log_timeout_paths()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _CHECK_STEP):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self._jobs == 3, f"{self._jobs} DMA jobs started, want 3"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence ARM<BELOW<BEYOND<AT<CLEANUP; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        fuse = f"{FUSE_SENSE_RISES} rises"
        subs = {
            "fuse sense wait tb_fuse_sense_done (AssertionError on expiry)": (
                fuse,
                f"tb_fuse_sense_done={self._level('tb_fuse_sense_done')}",
            ),
            "fuse sense wait tb_fuse_reset_n (AssertionError on expiry)": (
                fuse,
                f"tb_fuse_reset_n={self._level('tb_fuse_reset_n')}",
            ),
            "fuse sense wait tb_rst_warm_smc_clk_n (AssertionError on expiry)": (
                fuse,
                f"tb_rst_warm_smc_clk_n={self._level('tb_rst_warm_smc_clk_n')}",
            ),
            "SEP_IN csr_write/csr_read HANG_DET_*, filter and DMA_CTRL "
            f"x{self.accesses} accesses (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self.accesses} accesses completed",
            ),
        }
        waits = "; ".join(
            f"{name} bound={bound} last[{last}]"
            for name, (bound, last) in {**subs, **self._waits}.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry with the "
            "last sampled values; %s",
            waits,
        )
