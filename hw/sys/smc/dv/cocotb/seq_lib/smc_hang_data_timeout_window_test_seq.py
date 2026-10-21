# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_007 ANCHOR: smc_hang_data_timeout_window_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: d9b71cae4533d0963caa8e51ebe1b76291b2af12f09b36945a6e6be8e677556e
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B4_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""DATA_ACCEL hang detector window, disable and irq_en clear after a timeout, and irq_test gating.

Spec sources: HANG_DET_CTRL and HANG_DET_TIMEOUT_THRESHOLD in smc_base_config.rdl
(smc_base_config.adoc HANG_DET_DATA_ACCEL_CTRL fields irq, irq_test, irq_en, enable) and the
bit 286 row of interrupts.adoc.
"""

from __future__ import annotations

import inspect
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

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
    HANG_DET_ENABLE,
    HANG_DET_FIRE,
    HANG_DET_IRQ,
    HANG_DET_IRQ_EN,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_SYS_AXI_TIMEOUT,
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

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

DATA_BIT = 286
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0008
DMA_LENGTH = 8
THRESHOLD = 0x40
THRESHOLD_WIDE = 0x80
THRESHOLD_CLEANUP = 0x1000
BELOW_HOLD_RISES = 16
BELOW_WINDOW_RISES = 256
BEYOND_CEILING_RISES = 128
BEYOND_WIDE_CEILING_RISES = 192
AT_AFTER_RISES = 8
HANDSHAKE_CEILING_RISES = 4096
CLEAR_CEILING_RISES = 128
TEST_RISE_CEILING_RISES = 128
HELD_WINDOW_RISES = 0x80
DONE_POLLS = 50
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
_FENCE = (
    "EXISTING-BELOW",
    "EXISTING-BEYOND",
    "EXISTING-AT",
    "DISABLE-AFTER-TIMEOUT",
    "IRQEN-CLEAR",
    "IRQTEST-RAISE",
    "IRQTEST-DISABLED",
    "IRQTEST-NOIRQEN",
    "RESTORE",
)
_CHECKER_TERM = (
    ("CHK-DATAWIN-BELOW", "EXISTING-BELOW"),
    ("CHK-DATAWIN-BEYOND", "EXISTING-BEYOND"),
    ("CHK-DATAWIN-AT-LOG", "EXISTING-AT"),
    ("CHK-DATAWIN-DISABLE-AFTER-TIMEOUT", "DISABLE-AFTER-TIMEOUT"),
    ("CHK-DATAWIN-IRQEN-CLEAR", "IRQEN-CLEAR"),
    ("CHK-DATAWIN-IRQTEST-RAISE", "IRQTEST-RAISE"),
    ("CHK-DATAWIN-IRQTEST-DISABLED", "IRQTEST-DISABLED"),
    ("CHK-DATAWIN-IRQTEST-NOIRQEN", "IRQTEST-NOIRQEN"),
)
_DMA_JOBS = 6
_FILTERS = (
    ("INBOUND0", INBOUND0_START, INBOUND0_END, INBOUND0_FILTER_CONFIG),
    ("OUTBOUND0", OUTBOUND0_START, OUTBOUND0_END, OUTBOUND0_FILTER_CONFIG),
)


@dataclass
class _BoundedWait:
    """One bounded wait: its bound, whether expiry is tolerated, and what it last saw."""

    name: str
    bound: int
    unit: str
    allow_timeout: bool = False
    timed_out: bool = False
    used: int | None = None
    last: str = "not sampled"


@dataclass
class _DropWatch:
    """Per-rise record of the data irq and raw bit 286 from a CTRL write onwards."""

    rises: int = 0
    write_done: int | None = None
    drop: int | None = None
    stop: bool = False
    xz: list[int] = field(default_factory=list)
    reasserted: list[tuple[int, int, int]] = field(default_factory=list)


class smc_hang_data_timeout_window_test_seq(SmcCsrSeq):
    """Hold DMA jobs at the SYS_OUT responses against the DATA_ACCEL detector, then gate it."""

    def __init__(self, name: str = "smc_hang_data_timeout_window_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._fence: list[tuple[str, int, int, int]] = []
        self._waits: list[_BoundedWait] = []
        self._windows: list[tuple[str, int, int]] = []
        self._sep_items: list = []
        self._jobs = 0
        self._done = 0
        self._samples = 0
        self._term_base = (0, 0)

    async def finish_item(self, item) -> None:
        await super().finish_item(item)
        self._sep_items.append(item)

    def _step(self, step_id: str, text: str) -> None:
        cocotb.log.info("STEP %s: %s", step_id, text)

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))
        self.phases += 1

    def _term(self, term: str) -> None:
        """Close a fence term with the samples and SEP_IN accesses counted since the last."""
        samples = self._samples - self._term_base[0]
        accesses = self.accesses - self._term_base[1]
        self._fence.append((term, samples, accesses, int(get_sim_time("ps"))))
        self._term_base = (self._samples, self.accesses)

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
        self._samples += 1
        return data, raw, sys_irq, sep

    def _wait(self, name: str, bound: int, unit: str = "rises") -> _BoundedWait:
        wait = _BoundedWait(name, bound, unit)
        self._waits.append(wait)
        return wait

    @staticmethod
    def _wait_text(wait: _BoundedWait) -> str:
        used = "-" if wait.used is None else str(wait.used)
        return (
            f"{wait.name} bound={wait.bound} {wait.unit} allow_timeout={wait.allow_timeout} "
            f"timed_out={wait.timed_out} used={used} last=[{wait.last}]"
        )

    def _met(self, wait: _BoundedWait) -> None:
        cocotb.log.info("WAIT %s", self._wait_text(wait))

    def _expire(self, wait: _BoundedWait, what: str) -> None:
        wait.timed_out = True
        cocotb.log.info("WAIT expired %s", self._wait_text(wait))
        if not wait.allow_timeout:
            raise AssertionError(
                f"{wait.name}: {what} within {wait.bound} {wait.unit}; last observed {wait.last}"
            )

    def _hold(self, value: int, why: str) -> None:
        cocotb.top.tb_output_axi_resp_hold.value = value
        cocotb.log.info(
            "DRIVE tb_output_axi_resp_hold=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    async def _await_handshake(self, name: str) -> None:
        dut = cocotb.top
        wait = self._wait(f"{name} SYS_OUT AR/AW handshake wait", HANDSHAKE_CEILING_RISES)
        for n in range(1, wait.bound + 1):
            await RisingEdge(dut.clk_smc_i)
            arv, arr, awv, awr = (
                self._resolved(getattr(dut, f"tb_output_axi_{p}"), wait.name) & 1
                for p in ("arvalid", "arready", "awvalid", "awready")
            )
            wait.used = n
            wait.last = f"ar={arv}/{arr} aw={awv}/{awr}"
            if (arv and arr) or (awv and awr):
                self._met(wait)
                return
        self._expire(wait, "no SYS_OUT AR or AW handshake")

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
        wait = self._wait(f"{name} DMA_CTRL_DONE_0 poll", DONE_POLLS, "polls")
        done = self._done
        for n in range(1, wait.bound + 1):
            done = await self.csr_read(f"DMA_DONE_0_POLL_{name}", DMA_CTRL_DONE_0)
            wait.used = n
            wait.last = f"done={done} baseline={self._done}"
            if done > self._done:
                self._done = done
                self._met(wait)
                return n
        self._expire(wait, "DMA job not complete")
        return -1

    async def _poll_level(self, wait_name: str, bound: int, want: int, raw_too: bool = True) -> int:
        """Sample now and at each rise until the data irq (and raw bit 286) read `want`."""
        wait = self._wait(wait_name, bound)
        for n in range(0, wait.bound + 1):
            data, raw, sys_irq, sep = self._sample(wait.name)
            wait.used = n
            wait.last = f"data={data} raw286={raw} sys={sys_irq} sep={sep}"
            if data == want and (raw == want or not raw_too):
                self._met(wait)
                return n
            if n < wait.bound:
                await RisingEdge(cocotb.top.clk_smc_i)
        self._expire(wait, f"data irq{' and raw286' if raw_too else ''} did not read {want}")
        return -1

    async def _await_data_low(self, name: str) -> int:
        return await self._poll_level(f"{name} data irq clear wait", CLEAR_CEILING_RISES, 0)

    async def _window_low(self, name: str, rises: int) -> int:
        """Require the data irq and raw bit 286 at 0 on every one of `rises` rises."""
        compared = 0
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            data, raw, _, _ = self._sample(f"{name}[{n}]")
            assert data == 0 and raw == 0, (
                f"{name}: data irq={data} raw286={raw} at rise {n} of {rises}, want 0/0"
            )
            compared += 1
        self._windows.append((name, rises, compared))
        return compared

    async def _below_window(self, name: str) -> int:
        wname = f"{name} window"
        compared = 0
        for n in range(1, BELOW_WINDOW_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == BELOW_HOLD_RISES:
                self._hold(0, "below-threshold release")
            data, raw, _, _ = self._sample(f"{wname}[{n}]")
            assert data == 0 and raw == 0, (
                f"{wname}: data irq={data} raw286={raw} at rise {n}, want 0/0 "
                f"(stall {BELOW_HOLD_RISES} rises, threshold 0x{THRESHOLD:x})"
            )
            compared += 1
        self._windows.append((wname, BELOW_WINDOW_RISES, compared))
        return compared

    async def _beyond_window(
        self, name: str, ceiling: int = BEYOND_CEILING_RISES
    ) -> tuple[int, int]:
        wait = self._wait(f"{name} irq wait", ceiling)
        data_at = raw_at = 0
        for n in range(1, wait.bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            data, raw, sys_irq, sep = self._sample(f"{wait.name}[{n}]")
            wait.used = n
            wait.last = f"data={data} raw286={raw} sys={sys_irq} sep={sep}"
            assert sys_irq == 0 and sep == 0, (
                f"{wait.name}: peer irq sys={sys_irq} sep={sep} at rise {n}, want 0/0"
            )
            data_at = data_at or (n if data else 0)
            raw_at = raw_at or (n if raw else 0)
            if data_at and raw_at:
                self._met(wait)
                return data_at, raw_at
        self._expire(wait, f"data irq rose at {data_at}, raw286 at {raw_at}, not both")
        return data_at, raw_at

    async def _set_peers(self, label: str, armed: bool) -> None:
        """Arm or disarm the SYS_AXI and SEP_AXI detectors; armed ones use THRESHOLD."""
        for name, ctrl, timeout in (
            ("SYS", HANG_DET_SYS_AXI_CTRL, HANG_DET_SYS_AXI_TIMEOUT),
            ("SEP", HANG_DET_SEP_AXI_CTRL, HANG_DET_SEP_AXI_TIMEOUT),
        ):
            if armed:
                await self.csr_write(f"HANG_{name}_THR_{label}", timeout, THRESHOLD)
            await self.csr_write(
                f"HANG_{name}_{'ARM' if armed else 'OFF'}_{label}",
                ctrl,
                HANG_DET_ARMED if armed else 0,
            )

    async def _at_window(self, name: str) -> int:
        wname = f"{name} window"
        total = THRESHOLD + AT_AFTER_RISES
        first = 0
        sampled = 0
        for n in range(1, total + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == THRESHOLD:
                self._hold(0, "at-threshold release")
            data, raw, _, _ = self._sample(f"{wname}[{n}]")
            sampled += 1
            first = first or (n if data else 0)
        self._windows.append((wname, total, sampled))
        return first

    async def _watch(self, watch: _DropWatch) -> None:
        dut = cocotb.top
        while not watch.stop:
            await RisingEdge(dut.clk_smc_i)
            watch.rises += 1
            data_v = dut.tb_axi_hang_irq_data.value
            vec = dut.tb_cpu_interrupts.value
            if not (data_v.is_resolvable and vec.is_resolvable):
                watch.xz.append(watch.rises)
                continue
            data = int(data_v) & 1
            raw = int(vec) >> DATA_BIT & 1
            if watch.drop is None:
                if data == 0 and raw == 0:
                    watch.drop = watch.rises
            elif data or raw:
                watch.reasserted.append((watch.rises, data, raw))

    async def _clear_after_timeout(self, name: str, keep: int, read_irq_first: bool) -> dict:
        """Time out a held DMA job with enable | irq_en, then write `keep` to CTRL while held."""
        tag = name.upper().replace("-", "_")
        await self.csr_write(f"HANG_DATA_ARM_{tag}", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_ARMED)
        rise = await self._run_job(
            name,
            lambda n: self._poll_level(
                f"{n} irq rise wait", BEYOND_CEILING_RISES, 1, raw_too=read_irq_first
            ),
        )
        data, raw, _, _ = self._sample(f"{name} after rise")
        set_rd = None
        if read_irq_first:
            set_rd = await self.csr_read(f"HANG_DATA_CTRL_SET_{tag}", HANG_DET_DATA_ACCEL_CTRL)
            assert set_rd & HANG_DET_IRQ, (
                f"{name}: HANG_DET_DATA_ACCEL_CTRL=0x{set_rd:x} after the timeout, irq bit reads 0"
            )
        watch = _DropWatch()
        watch_task = cocotb.start_soon(self._watch(watch))
        await self.csr_write(f"HANG_DATA_CTRL_KEEP_{tag}", HANG_DET_DATA_ACCEL_CTRL, keep)
        watch.write_done = watch.rises
        drop_poll = await self._poll_level(f"{name} irq drop wait", CLEAR_CEILING_RISES, 0)
        clear_rd = await self.csr_read(f"HANG_DATA_CTRL_CLR_{tag}", HANG_DET_DATA_ACCEL_CTRL)
        assert not clear_rd & HANG_DET_IRQ, (
            f"{name}: HANG_DET_DATA_ACCEL_CTRL=0x{clear_rd:x} with CTRL=0x{keep:x} and the "
            "stall held, irq bit reads 1"
        )
        held = await self._window_low(f"{name} held window", HELD_WINDOW_RISES)
        watch.stop = True
        await watch_task
        assert not watch.xz, f"{name}: data irq or raw286 X/Z at rises {watch.xz} after the write"
        assert watch.drop is not None, f"{name}: drop not seen by the per-rise watch"
        assert not watch.reasserted, (
            f"{name}: data irq/raw286 re-asserted after the drop at (rise, data, raw) "
            f"{watch.reasserted[:4]}"
        )
        self._hold(0, f"{name} release")
        polls = await self._await_done(name)
        return {
            "rise": rise,
            "data": data,
            "raw": raw,
            "set_rd": set_rd,
            "drop": watch.drop,
            "write_done": watch.write_done,
            "drop_poll": drop_poll,
            "clear_rd": clear_rd,
            "held": held,
            "watched": watch.rises,
            "polls": polls,
        }

    async def _gated_test(self, name: str, value: int) -> tuple[int, int, int, int]:
        """Write `value` (irq_test with one gate clear); return (window, CTRL, after, CTRL)."""
        tag = name.upper().replace("-", "_")
        await self.csr_write(f"HANG_DATA_CTRL_{tag}", HANG_DET_DATA_ACCEL_CTRL, value)
        held = await self._window_low(f"{name} window", HELD_WINDOW_RISES)
        rd = await self.csr_read(f"HANG_DATA_CTRL_{tag}_RB", HANG_DET_DATA_ACCEL_CTRL)
        assert not rd & HANG_DET_IRQ, (
            f"{name}: HANG_DET_DATA_ACCEL_CTRL=0x{rd:x} with CTRL=0x{value:x}, irq bit reads 1"
        )
        await self.csr_write(f"HANG_DATA_CTRL_{tag}_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        data, raw, _, _ = self._sample(f"{name} after off")
        off_rd = await self.csr_read(f"HANG_DATA_CTRL_{tag}_OFF_RB", HANG_DET_DATA_ACCEL_CTRL)
        assert data == 0 and not off_rd & HANG_DET_IRQ, (
            f"{name}: after CTRL=0 data irq={data} raw286={raw} CTRL=0x{off_rd:x}"
        )
        return held, rd, data, off_rd

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def body(self) -> None:
        dut = cocotb.top
        self._step("S1", "fuse sense, bench signals, INBOUND0/OUTBOUND0 pass-all, threshold 0x40")
        fuse_bound = inspect.signature(self.wait_fuse_sense_done).parameters["max_cycles"].default
        fuse = self._wait("fuse sense wait (per signal)", fuse_bound)
        fuse_t0 = int(get_sim_time("ns"))
        await self.wait_fuse_sense_done(fuse.bound)
        fuse.last = (
            f"tb_fuse_sense_done={int(dut.tb_fuse_sense_done.value)} "
            f"tb_fuse_reset_n={self._level('tb_fuse_reset_n')} "
            f"tb_rst_warm_smc_clk_n={self._level('tb_rst_warm_smc_clk_n')} "
            f"after {int(get_sim_time('ns')) - fuse_t0} ns"
        )
        self._met(fuse)
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
        for side, start, end, config in _FILTERS:
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
        self._mark_step("S1")
        self._term_base = (self._samples, self.accesses)

        self._step("S2", "existing below, beyond (with the 0x80 shift) and at legs")
        zero_rises = await self._run_job("below", self._below_window)
        polls = await self._await_done("below")
        self._term("EXISTING-BELOW")
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

        await self._set_peers("BEYOND", True)
        data_at, raw_at = await self._run_job("beyond", self._beyond_window)
        rdata = await self.csr_read("HANG_DATA_CTRL_IRQ", HANG_DET_DATA_ACCEL_CTRL)
        assert rdata & HANG_DET_IRQ, f"HANG_DET_DATA_ACCEL_CTRL=0x{rdata:x}: irq bit reads 0"
        self._hold(0, "beyond-threshold release")
        await self.csr_write("HANG_DATA_CTRL_OFF_BEYOND", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self._await_done("beyond")
        cleared = await self._await_data_low("beyond")

        await self.csr_write("HANG_DATA_THR_WIDE", HANG_DET_DATA_ACCEL_TIMEOUT, THRESHOLD_WIDE)
        thr = await self.csr_read(
            "HANG_DATA_THR_WIDE_RB", HANG_DET_DATA_ACCEL_TIMEOUT, expected=THRESHOLD_WIDE
        )
        assert (thr & HANG_DET_THR_VALUE) == THRESHOLD_WIDE, (
            f"DATA threshold readback 0x{thr:x} want 0x{THRESHOLD_WIDE:x}"
        )
        await self.csr_write("HANG_DATA_ARM_WIDE", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_ARMED)
        wide_at, wide_raw = await self._run_job(
            "beyond_wide", lambda name: self._beyond_window(name, BEYOND_WIDE_CEILING_RISES)
        )
        self._hold(0, "wide beyond-threshold release")
        await self.csr_write("HANG_DATA_CTRL_OFF_WIDE", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self._await_done("beyond_wide")
        await self._await_data_low("beyond_wide")
        assert wide_at - data_at == THRESHOLD_WIDE - THRESHOLD, (
            f"data irq rose at rise {data_at} with threshold 0x{THRESHOLD:x} and at rise "
            f"{wide_at} with threshold 0x{THRESHOLD_WIDE:x}, want a difference of "
            f"{THRESHOLD_WIDE - THRESHOLD}"
        )
        await self._set_peers("BEYOND", False)
        await self.csr_write("HANG_DATA_THR_RESTORE", HANG_DET_DATA_ACCEL_TIMEOUT, THRESHOLD)
        self._term("EXISTING-BEYOND")
        self._log_legs(
            "CHK-DATAWIN-BEYOND",
            f"DMA job held past threshold 0x{THRESHOLD:x}, SYS_AXI and SEP_AXI armed",
            "tb_axi_hang_irq_data, tb_cpu_interrupts[286] and CTRL.irq",
            "CTRL written 0 after the release",
            f"tb_axi_hang_irq_data and raw286 read 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-DATAWIN-BEYOND",
            f"data irq first 1 at rise {data_at}, raw286 first 1 at rise {raw_at} "
            f"(ceiling {BEYOND_CEILING_RISES}); sys=0 sep=0 with both armed at threshold "
            f"0x{THRESHOLD:x}; CTRL=0x{rdata:x} irq=1; cleared after {cleared} rises; threshold "
            f"0x{THRESHOLD_WIDE:x}: data irq first 1 at rise {wide_at}, raw286 at rise "
            f"{wide_raw}, {wide_at - data_at} later than at 0x{THRESHOLD:x}",
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
        self._term("EXISTING-AT")
        self._log_chk(
            "CHK-DATAWIN-AT-LOG",
            f"stall of exactly 0x{THRESHOLD:x} rises: first_data_irq_rise={first}; "
            f"{text}; cleared after {cleared_at} rises (observe-and-log, not specified, measured)",
        )
        self._mark_step("S2")

        self._step("S3", "disable after timeout: enable written 0 with the stall held")
        await self.csr_write("HANG_SYS_OFF_DISABLE", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_SEP_OFF_DISABLE", HANG_DET_SEP_AXI_CTRL, 0)
        dis = await self._clear_after_timeout("disable", HANG_DET_IRQ_EN, read_irq_first=True)
        self._mark_step("S3")
        self._term("DISABLE-AFTER-TIMEOUT")
        self._log_legs(
            "CHK-DATAWIN-DISABLE-AFTER-TIMEOUT",
            f"DMA job held past threshold 0x{THRESHOLD:x} with CTRL=0x{HANG_DET_ARMED:x}",
            f"data={dis['data']} raw286={dis['raw']} at rise {dis['rise']}, "
            f"CTRL=0x{dis['set_rd']:x}",
            f"CTRL written 0x{HANG_DET_IRQ_EN:x} (enable 0) with the stall held",
            f"data and raw286 0 at rise {dis['drop']} of the watch, 0 for {dis['held']} held "
            f"rises, CTRL=0x{dis['clear_rd']:x}",
        )
        self._log_chk(
            "CHK-DATAWIN-DISABLE-AFTER-TIMEOUT",
            f"irq 1 -> 0 after enable=0 ({dis['drop']} cycles from the write issue, write "
            f"response at cycle {dis['write_done']}; SF-018 measured, not compared), "
            f"0x{dis['held']:x} held rises irq=0 raw286=0, CTRL.irq=0 "
            f"(CTRL=0x{dis['clear_rd']:x}); before: data=1 raw286=1 at rise {dis['rise']} after "
            f"the SYS_OUT handshake, CTRL=0x{dis['set_rd']:x} irq=1; no re-assertion in "
            f"{dis['watched']} watched rises; job completed after {dis['polls']} polls",
        )

        self._step("S4", "irq_en clear after timeout: irq_en written 0, enable kept, stall held")
        ien = await self._clear_after_timeout("irqen", HANG_DET_ENABLE, read_irq_first=False)
        await self.csr_write("HANG_DATA_CTRL_OFF_IRQEN", HANG_DET_DATA_ACCEL_CTRL, 0)
        self._mark_step("S4")
        self._term("IRQEN-CLEAR")
        self._log_legs(
            "CHK-DATAWIN-IRQEN-CLEAR",
            f"DMA job held past threshold 0x{THRESHOLD:x} with CTRL=0x{HANG_DET_ARMED:x}",
            f"data={ien['data']} raw286={ien['raw']} at rise {ien['rise']}",
            f"CTRL written 0x{HANG_DET_ENABLE:x} (irq_en 0) with the stall held",
            f"data and raw286 0 at rise {ien['drop']} of the watch, 0 for {ien['held']} held "
            f"rises, CTRL=0x{ien['clear_rd']:x}",
        )
        self._log_chk(
            "CHK-DATAWIN-IRQEN-CLEAR",
            f"irq 1 -> 0 after irq_en=0 (data=1 at rise {ien['rise']} after the SYS_OUT "
            f"handshake; drop {ien['drop']} cycles from the write issue), 0x{ien['held']:x} held "
            f"rises irq=0 raw286=0, CTRL.irq=0 (CTRL=0x{ien['clear_rd']:x}); no re-assertion in "
            f"{ien['watched']} watched rises; job completed after {ien['polls']} polls",
        )

        self._step("S5", "irq_test with enable and irq_en, no stall")
        await self.csr_write("HANG_DATA_CTRL_FIRE", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_FIRE)
        up = await self._poll_level("irqtest irq rise wait", TEST_RISE_CEILING_RISES, 1)
        fire_rd = await self.csr_read("HANG_DATA_CTRL_FIRE_RB", HANG_DET_DATA_ACCEL_CTRL)
        assert fire_rd & HANG_DET_IRQ, (
            f"HANG_DET_DATA_ACCEL_CTRL=0x{fire_rd:x} with irq_test set, irq bit reads 0"
        )
        await self.csr_write("HANG_DATA_CTRL_TEST_OFF", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_ARMED)
        down = await self._poll_level("irqtest irq drop wait", CLEAR_CEILING_RISES, 0)
        off_rd = await self.csr_read("HANG_DATA_CTRL_TEST_OFF_RB", HANG_DET_DATA_ACCEL_CTRL)
        assert not off_rd & HANG_DET_IRQ, (
            f"HANG_DET_DATA_ACCEL_CTRL=0x{off_rd:x} after irq_test cleared, irq bit reads 1"
        )
        self._mark_step("S5")
        self._term("IRQTEST-RAISE")
        self._log_legs(
            "CHK-DATAWIN-IRQTEST-RAISE",
            f"CTRL written 0x{HANG_DET_FIRE:x} (enable | irq_en | irq_test), no stall",
            f"data and raw286 1 after {up} rises, CTRL=0x{fire_rd:x}",
            f"CTRL written 0x{HANG_DET_ARMED:x} (irq_test 0)",
            f"data and raw286 0 after {down} rises, CTRL=0x{off_rd:x}",
        )
        self._log_chk(
            "CHK-DATAWIN-IRQTEST-RAISE",
            f"irq_test=1 -> irq 1, raw286 1 after {up} rises, CTRL.irq 1 (CTRL=0x{fire_rd:x}); "
            f"irq_test=0 -> irq 0, raw286 0 after {down} rises, CTRL.irq 0 (CTRL=0x{off_rd:x})",
        )

        for step, term, chk, value, gate in (
            (
                "S6",
                "IRQTEST-DISABLED",
                "CHK-DATAWIN-IRQTEST-DISABLED",
                HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST,
                "enable=0",
            ),
            (
                "S7",
                "IRQTEST-NOIRQEN",
                "CHK-DATAWIN-IRQTEST-NOIRQEN",
                HANG_DET_ENABLE | HANG_DET_IRQ_TEST,
                "irq_en=0",
            ),
        ):
            self._step(step, f"irq_test with {gate}")
            held, rd, after, off = await self._gated_test(term.lower(), value)
            self._mark_step(step)
            self._term(term)
            self._log_legs(
                chk,
                f"CTRL written 0x{value:x} ({gate}, irq_test=1)",
                f"data and raw286 0 for {held} rises, CTRL=0x{rd:x}",
                "CTRL written 0",
                f"data={after}, CTRL=0x{off:x}",
            )
            self._log_chk(
                chk,
                f"0x{held:x}/0x{HELD_WINDOW_RISES:x} rises irq=0 raw286=0, CTRL.irq=0 "
                f"(CTRL=0x{rd:x}; {gate}, irq_test=1); after CTRL=0 data={after} "
                f"CTRL=0x{off:x}",
            )

        self._step("S8", "restore control, threshold and INBOUND0/OUTBOUND0 filters")
        self._hold(0, "cleanup")
        await self.csr_write("HANG_DATA_CTRL_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self.csr_write(
            "HANG_DATA_THR_CLEANUP", HANG_DET_DATA_ACCEL_TIMEOUT, THRESHOLD_CLEANUP
        )
        for side, start, end, config in _FILTERS:
            await self.csr_write(
                f"{side}_CONFIG_RESTORE", config, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT, length=8
            )
            await self.csr_write(
                f"{side}_START_RESTORE", start, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
            )
            await self.csr_write(
                f"{side}_END_RESTORE", end, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
            )
            await self.csr_read(
                f"{side}_CONFIG_RESTORE_RB",
                config,
                expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
                length=8,
            )
        self._mark_step("S8")
        self._term("RESTORE")

        self._nonvac_fence()
        self._log_timeout_paths()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        terms = tuple(t for t, *_ in self._fence)
        assert terms == _FENCE, f"fence terms {terms}, want {_FENCE}"
        ftimes = [t for *_, t in self._fence]
        assert all(b > a for a, b in zip(ftimes, ftimes[1:])), (
            f"fence times not increasing: {ftimes}"
        )
        for term, samples, accesses, _ in self._fence:
            assert samples + accesses > 0, f"fence term {term} counted nothing"
            assert term == "RESTORE" or samples > 0, f"fence term {term} sampled no rise"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        want_chk = tuple(c for c, _ in _CHECKER_TERM)
        assert chk_ids == want_chk, f"checker lines {chk_ids}, want {want_chk}"
        term_at = {t: when for t, *_, when in self._fence}
        for (chk_id, when), (_, term) in zip(self._chk_marks, _CHECKER_TERM):
            assert when >= term_at[term], f"{chk_id} printed before its fence term {term}"
        assert self._jobs == _DMA_JOBS, f"{self._jobs} DMA jobs started, want {_DMA_JOBS}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; %s; checker lines %s; step stamps %s; %d DMA jobs",
            " < ".join(terms),
            "; ".join(f"{t} samples={s} accesses={a} t={w}ps" for t, s, a, w in self._fence),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self._jobs,
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        expired = [w.name for w in self._waits if w.timed_out]
        tolerant = [w.name for w in self._waits if w.allow_timeout]
        items = self._sep_items
        bounds = sorted({item.timeout_ns or self.cfg.axi_timeout_ns for item in items})
        allow = sum(1 for item in items if item.allow_timeout)
        timed = sum(1 for item in items if item.timed_out)
        assert not allow and not timed, f"SEP_IN: {allow} accesses tolerate expiry, {timed} expired"
        assert not expired and not tolerant, (
            f"bounded waits expired {expired} / tolerating expiry {tolerant}"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, %d expired; "
            "expiry raises AssertionError with the last observed state; %d SEP_IN accesses "
            "bound=%s ns allow_timeout=%d timed_out=%d; %s; observation windows %s",
            len(self._waits),
            len(expired),
            len(items),
            bounds,
            allow,
            timed,
            "; ".join(self._wait_text(w) for w in self._waits),
            "; ".join(f"{n} {c}/{r} rises sampled" for n, r, c in self._windows),
        )
