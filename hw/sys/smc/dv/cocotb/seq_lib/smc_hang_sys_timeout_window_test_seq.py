# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_006 ANCHOR: smc_hang_sys_timeout_window_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: df1683f6c28194c2a230844b8f7f49d7d59852e82dc25fe24a3d9ac47dea2f87
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B4_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""SYS_AXI hang detector window, disable and irq_en clear after a timeout, and irq_test gating.

Spec sources: HANG_DET_CTRL and HANG_DET_TIMEOUT_THRESHOLD in smc_base_config.rdl
(smc_base_config.adoc HANG_DET_SYS_AXI_CTRL fields irq, irq_test, irq_en, enable) and the
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
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
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
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
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

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
SYS_BIT = 286
INBOUND_PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
THRESHOLD = 0x40
THRESHOLD_WIDE = 0x80
THRESHOLD_CLEANUP = 0x1000
BELOW_HOLD_RISES = 16
BELOW_WINDOW_RISES = 256
BEYOND_CEILING_RISES = 128
BEYOND_WIDE_CEILING_RISES = 192
AT_AFTER_RISES = 8
AR_CEILING_RISES = 256
DONE_CEILING_RISES = 256
CLEAR_CEILING_RISES = 128
TEST_RISE_CEILING_RISES = 128
HELD_WINDOW_RISES = 0x80
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
    ("CHK-SYSWIN-BELOW", "EXISTING-BELOW"),
    ("CHK-SYSWIN-BEYOND", "EXISTING-BEYOND"),
    ("CHK-SYSWIN-AT-LOG", "EXISTING-AT"),
    ("CHK-SYSWIN-DISABLE-AFTER-TIMEOUT", "DISABLE-AFTER-TIMEOUT"),
    ("CHK-SYSWIN-IRQEN-CLEAR", "IRQEN-CLEAR"),
    ("CHK-SYSWIN-IRQTEST-RAISE", "IRQTEST-RAISE"),
    ("CHK-SYSWIN-IRQTEST-DISABLED", "IRQTEST-DISABLED"),
    ("CHK-SYSWIN-IRQTEST-NOIRQEN", "IRQTEST-NOIRQEN"),
)
_HELD_READS = 6


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
    """Per-rise record of the sys irq and raw bit 286 from a CTRL write onwards."""

    rises: int = 0
    write_done: int | None = None
    drop: int | None = None
    stop: bool = False
    xz: list[int] = field(default_factory=list)
    reasserted: list[tuple[int, int, int]] = field(default_factory=list)


class _SysInReadSeq(SmcCsrSeq):
    """One SYS_IN read that must answer OKAY."""

    def __init__(self, name: str, addr: int, items: list[SmcSysAxiItem]) -> None:
        super().__init__(name)
        self.addr = addr
        self.items = items

    async def body(self) -> None:
        item = SmcSysAxiItem(f"rd_{self.get_name()}")
        item.op = SmcSysAxiOp.READ
        item.addr = self.addr
        item.length = 4
        await self.start_item(item)
        await self.finish_item(item)
        self.items.append(item)


class smc_hang_sys_timeout_window_test_seq(SmcCsrSeq):
    """Hold SYS_IN reads against the SYS_AXI detector, then gate it through CTRL."""

    def __init__(self, name: str = "smc_hang_sys_timeout_window_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._fence: list[tuple[str, int, int, int]] = []
        self._waits: list[_BoundedWait] = []
        self._windows: list[tuple[str, int, int]] = []
        self._sep_items: list[SmcSysAxiItem] = []
        self._sys_items: list[SmcSysAxiItem] = []
        self._reads = 0
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
        """Return (sys irq, raw bit 286, sep irq, data irq) at this rise."""
        dut = cocotb.top
        sys_irq = self._resolved(dut.tb_axi_hang_irq_sys, label) & 1
        raw = self._resolved(dut.tb_cpu_interrupts, label) >> SYS_BIT & 1
        sep = self._resolved(dut.tb_axi_hang_irq_sep, label) & 1
        data = self._resolved(dut.tb_axi_hang_irq_data, label) & 1
        self._samples += 1
        return sys_irq, raw, sep, data

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
        cocotb.top.tb_sys_axi_r_hold.value = value
        cocotb.log.info(
            "DRIVE tb_sys_axi_r_hold=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    def _start_read(self, name: str):
        self._reads += 1
        self._hold(1, f"{name} stall")
        child = _SysInReadSeq(name, SCRATCH_COLD_WARM_0, self._sys_items)
        child.cfg = self.cfg
        child.env = self.env
        return cocotb.start_soon(child.start(self.env.sys_in_axi_agent.sequencer))

    async def _await_ar(self, name: str) -> None:
        wait = self._wait(f"{name} AR handshake wait", AR_CEILING_RISES)
        for n in range(1, wait.bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            valid = self._resolved(cocotb.top.sys_axi_arvalid, wait.name) & 1
            ready = self._resolved(cocotb.top.sys_axi_arready, wait.name) & 1
            wait.used = n
            wait.last = f"arvalid={valid} arready={ready}"
            if valid and ready:
                self._met(wait)
                return
        self._expire(wait, "SYS_IN AR handshake not seen")

    async def _await_done(self, task, name: str) -> None:
        wait = self._wait(f"{name} read completion wait", DONE_CEILING_RISES)
        for n in range(0, wait.bound + 1):
            wait.used = n
            wait.last = (
                f"read done={task.done()} "
                f"tb_sys_axi_r_hold={int(cocotb.top.tb_sys_axi_r_hold.value)}"
            )
            if task.done():
                self._met(wait)
                return
            if n < wait.bound:
                await RisingEdge(cocotb.top.clk_smc_i)
        self._expire(wait, "SYS_IN read still pending")

    async def _poll_level(self, wait_name: str, bound: int, want: int, raw_too: bool = True) -> int:
        """Sample now and at each rise until the sys irq (and raw bit 286) read `want`."""
        wait = self._wait(wait_name, bound)
        for n in range(0, wait.bound + 1):
            sys_irq, raw, sep, data = self._sample(wait.name)
            wait.used = n
            wait.last = f"sys={sys_irq} raw286={raw} sep={sep} data={data}"
            if sys_irq == want and (raw == want or not raw_too):
                self._met(wait)
                return n
            if n < wait.bound:
                await RisingEdge(cocotb.top.clk_smc_i)
        self._expire(wait, f"sys irq{' and raw286' if raw_too else ''} did not read {want}")
        return -1

    async def _await_sys_low(self, name: str) -> int:
        return await self._poll_level(f"{name} sys irq clear wait", CLEAR_CEILING_RISES, 0)

    async def _window_low(self, name: str, rises: int) -> int:
        """Require the sys irq and raw bit 286 at 0 on every one of `rises` rises."""
        compared = 0
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            sys_irq, raw, sep, data = self._sample(f"{name}[{n}]")
            assert sys_irq == 0 and raw == 0, (
                f"{name}: sys irq={sys_irq} raw286={raw} at rise {n} of {rises}, want 0/0"
            )
            compared += 1
        self._windows.append((name, rises, compared))
        return compared

    async def _below(self) -> int:
        """Stall 16 rises then release; return the rises sampled at zero."""
        name = "below"
        task = self._start_read(name)
        await self._await_ar(name)
        compared = 0
        for n in range(1, BELOW_WINDOW_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == BELOW_HOLD_RISES:
                self._hold(0, "below-threshold release")
            sys_irq, raw, sep, data = self._sample(f"{name} window[{n}]")
            assert sys_irq == 0 and raw == 0, (
                f"{name} window: sys irq={sys_irq} raw286={raw} at rise {n}, want 0/0 "
                f"(stall {BELOW_HOLD_RISES} rises, threshold 0x{THRESHOLD:x})"
            )
            compared += 1
        self._windows.append((f"{name} window", BELOW_WINDOW_RISES, compared))
        await self._await_done(task, name)
        return compared

    async def _set_peers(self, label: str, armed: bool) -> None:
        """Arm or disarm the SEP_AXI and DATA_ACCEL detectors; armed ones use THRESHOLD."""
        for name, ctrl, timeout in (
            ("SEP", HANG_DET_SEP_AXI_CTRL, HANG_DET_SEP_AXI_TIMEOUT),
            ("DATA", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_DATA_ACCEL_TIMEOUT),
        ):
            if armed:
                await self.csr_write(f"HANG_{name}_THR_{label}", timeout, THRESHOLD)
            await self.csr_write(
                f"HANG_{name}_{'ARM' if armed else 'OFF'}_{label}",
                ctrl,
                HANG_DET_ARMED if armed else 0,
            )

    async def _beyond(
        self, name: str = "beyond", ceiling: int = BEYOND_CEILING_RISES
    ) -> tuple[int, int, int]:
        """Stall past the threshold; return (sys rise, raw rise, CTRL rdata)."""
        task = self._start_read(name)
        await self._await_ar(name)
        wait = self._wait(f"{name} irq wait", ceiling)
        sys_at = raw_at = 0
        for n in range(1, wait.bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            sys_irq, raw, sep, data = self._sample(f"{wait.name}[{n}]")
            wait.used = n
            wait.last = f"sys={sys_irq} raw286={raw} sep={sep} data={data}"
            assert sep == 0 and data == 0, (
                f"{wait.name}: peer irq sep={sep} data={data} at rise {n}, want 0/0"
            )
            sys_at = sys_at or (n if sys_irq else 0)
            raw_at = raw_at or (n if raw else 0)
            if sys_at and raw_at:
                self._met(wait)
                break
        else:
            self._expire(wait, f"sys irq rose at {sys_at}, raw286 at {raw_at}, not both")
        rdata = await self.csr_read("HANG_SYS_CTRL_IRQ", HANG_DET_SYS_AXI_CTRL)
        assert rdata & HANG_DET_IRQ, f"HANG_DET_SYS_AXI_CTRL=0x{rdata:x}: irq bit reads 0"
        self._hold(0, "beyond-threshold release")
        await self._await_done(task, name)
        await self.csr_write(f"HANG_SYS_CTRL_OFF_{name.upper()}", HANG_DET_SYS_AXI_CTRL, 0)
        return sys_at, raw_at, rdata

    async def _at_threshold(self) -> tuple[str, int]:
        """Release exactly 0x40 rises after the AR handshake; return (log text, first rise)."""
        name = "at"
        task = self._start_read(name)
        await self._await_ar(name)
        total = THRESHOLD + AT_AFTER_RISES
        first = 0
        sampled = 0
        for n in range(1, total + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == THRESHOLD:
                self._hold(0, "at-threshold release")
            sys_irq, raw, sep, data = self._sample(f"{name} window[{n}]")
            sampled += 1
            first = first or (n if sys_irq else 0)
        self._windows.append((f"{name} window", total, sampled))
        if not first:
            text = f"sys irq did not rise within {total} rises of the AR handshake"
        elif first <= THRESHOLD:
            text = f"sys irq rose at rise {first}, before the release at rise {THRESHOLD}"
        else:
            text = f"sys irq rose at rise {first}, {first - THRESHOLD} after the release"
        await self._await_done(task, name)
        await self.csr_write("HANG_SYS_CTRL_OFF_AT", HANG_DET_SYS_AXI_CTRL, 0)
        return text, first

    async def _watch(self, watch: _DropWatch) -> None:
        dut = cocotb.top
        while not watch.stop:
            await RisingEdge(dut.clk_smc_i)
            watch.rises += 1
            sys_v = dut.tb_axi_hang_irq_sys.value
            vec = dut.tb_cpu_interrupts.value
            if not (sys_v.is_resolvable and vec.is_resolvable):
                watch.xz.append(watch.rises)
                continue
            sys_irq = int(sys_v) & 1
            raw = int(vec) >> SYS_BIT & 1
            if watch.drop is None:
                if sys_irq == 0 and raw == 0:
                    watch.drop = watch.rises
            elif sys_irq or raw:
                watch.reasserted.append((watch.rises, sys_irq, raw))

    def _read_ok(self, item: SmcSysAxiItem, name: str) -> None:
        assert item.resp_ok and not item.timed_out, (
            f"{name}: SYS_IN read resp_ok={item.resp_ok} resp={item.resp_code} "
            f"timed_out={item.timed_out}, want OKAY"
        )

    async def _clear_after_timeout(self, name: str, keep: int, read_irq_first: bool) -> dict:
        """Time out a held read with enable | irq_en, then write `keep` to CTRL while held."""
        tag = name.upper().replace("-", "_")
        await self.csr_write(f"HANG_SYS_ARM_{tag}", HANG_DET_SYS_AXI_CTRL, HANG_DET_ARMED)
        task = self._start_read(name)
        await self._await_ar(name)
        rise = await self._poll_level(
            f"{name} irq rise wait", BEYOND_CEILING_RISES, 1, raw_too=read_irq_first
        )
        sys_irq, raw, _, _ = self._sample(f"{name} after rise")
        set_rd = None
        if read_irq_first:
            set_rd = await self.csr_read(f"HANG_SYS_CTRL_SET_{tag}", HANG_DET_SYS_AXI_CTRL)
            assert set_rd & HANG_DET_IRQ, (
                f"{name}: HANG_DET_SYS_AXI_CTRL=0x{set_rd:x} after the timeout, irq bit reads 0"
            )
        watch = _DropWatch()
        watch_task = cocotb.start_soon(self._watch(watch))
        await self.csr_write(f"HANG_SYS_CTRL_KEEP_{tag}", HANG_DET_SYS_AXI_CTRL, keep)
        watch.write_done = watch.rises
        drop_poll = await self._poll_level(f"{name} irq drop wait", CLEAR_CEILING_RISES, 0)
        clear_rd = await self.csr_read(f"HANG_SYS_CTRL_CLR_{tag}", HANG_DET_SYS_AXI_CTRL)
        assert not clear_rd & HANG_DET_IRQ, (
            f"{name}: HANG_DET_SYS_AXI_CTRL=0x{clear_rd:x} with CTRL=0x{keep:x} and the "
            "stall held, irq bit reads 1"
        )
        held = await self._window_low(f"{name} held window", HELD_WINDOW_RISES)
        watch.stop = True
        await watch_task
        assert not watch.xz, f"{name}: sys irq or raw286 X/Z at rises {watch.xz} after the write"
        assert watch.drop is not None, f"{name}: drop not seen by the per-rise watch"
        assert not watch.reasserted, (
            f"{name}: sys irq/raw286 re-asserted after the drop at (rise, sys, raw) "
            f"{watch.reasserted[:4]}"
        )
        self._hold(0, f"{name} release")
        await self._await_done(task, name)
        self._read_ok(self._sys_items[-1], name)
        return {
            "rise": rise,
            "sys": sys_irq,
            "raw": raw,
            "set_rd": set_rd,
            "drop": watch.drop,
            "write_done": watch.write_done,
            "drop_poll": drop_poll,
            "clear_rd": clear_rd,
            "held": held,
            "watched": watch.rises,
        }

    async def _gated_test(self, name: str, value: int) -> tuple[int, int, int, int]:
        """Write `value` (irq_test with one gate clear); return (window, CTRL, after, CTRL)."""
        tag = name.upper().replace("-", "_")
        await self.csr_write(f"HANG_SYS_CTRL_{tag}", HANG_DET_SYS_AXI_CTRL, value)
        held = await self._window_low(f"{name} window", HELD_WINDOW_RISES)
        rd = await self.csr_read(f"HANG_SYS_CTRL_{tag}_RB", HANG_DET_SYS_AXI_CTRL)
        assert not rd & HANG_DET_IRQ, (
            f"{name}: HANG_DET_SYS_AXI_CTRL=0x{rd:x} with CTRL=0x{value:x}, irq bit reads 1"
        )
        await self.csr_write(f"HANG_SYS_CTRL_{tag}_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        sys_irq, raw, _, _ = self._sample(f"{name} after off")
        off_rd = await self.csr_read(f"HANG_SYS_CTRL_{tag}_OFF_RB", HANG_DET_SYS_AXI_CTRL)
        assert sys_irq == 0 and not off_rd & HANG_DET_IRQ, (
            f"{name}: after CTRL=0 sys irq={sys_irq} raw286={raw} CTRL=0x{off_rd:x}"
        )
        return held, rd, sys_irq, off_rd

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def body(self) -> None:
        dut = cocotb.top
        self._step("S1", "fuse sense, bench signals, INBOUND0 pass-all, SYS threshold 0x40")
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
            "tb_sys_axi_r_hold",
            "tb_axi_hang_irq_sys",
            "tb_axi_hang_irq_sep",
            "tb_axi_hang_irq_data",
            "tb_cpu_interrupts",
            "sys_axi_arvalid",
            "sys_axi_arready",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        self._hold(0, "idle")
        cocotb.log.info("SEED RANDOM_SEED=%s", os.environ.get("RANDOM_SEED", "1"))

        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, INBOUND_PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_PASS_ALL_RB",
            INBOUND0_FILTER_CONFIG,
            expected=PASS_ALL_CONFIG,
            length=8,
        )
        await self.csr_write("HANG_SEP_OFF", HANG_DET_SEP_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self.csr_write("HANG_SYS_THR", HANG_DET_SYS_AXI_TIMEOUT, THRESHOLD)
        thr = await self.csr_read("HANG_SYS_THR_RB", HANG_DET_SYS_AXI_TIMEOUT, expected=THRESHOLD)
        assert (thr & HANG_DET_THR_VALUE) == THRESHOLD, (
            f"SYS threshold readback 0x{thr:x} want 0x{THRESHOLD:x}"
        )
        await self.csr_write("HANG_SYS_ARM", HANG_DET_SYS_AXI_CTRL, HANG_DET_ARMED)
        await self.csr_read("HANG_SYS_ARM_RB", HANG_DET_SYS_AXI_CTRL, expected=HANG_DET_ARMED)
        await RisingEdge(dut.clk_smc_i)
        base = self._resolved(dut.tb_cpu_interrupts, "baseline")
        sys_irq, raw, sep, data = self._sample("baseline")
        assert (sys_irq, raw, sep, data) == (0, 0, 0, 0), (
            f"baseline sys={sys_irq} raw286={raw} sep={sep} data={data}"
        )
        cocotb.log.info(
            "BASELINE vector=0x%x thr=0x%x ctrl=0x%x sys=0 raw286=0", base, thr, HANG_DET_ARMED
        )
        self._mark_step("S1")
        self._term_base = (self._samples, self.accesses)

        self._step("S2", "existing below, beyond (with the 0x80 shift) and at legs")
        zero_rises = await self._below()
        self._term("EXISTING-BELOW")
        self._log_legs(
            "CHK-SYSWIN-BELOW",
            f"SYS_IN read held {BELOW_HOLD_RISES} rises with threshold 0x{THRESHOLD:x}",
            "tb_axi_hang_irq_sys and tb_cpu_interrupts[286] each rise",
            "hold released and read completed",
            f"both probes read 0 for {zero_rises} rises",
        )
        self._log_chk(
            "CHK-SYSWIN-BELOW",
            f"stall {BELOW_HOLD_RISES} rises, threshold 0x{THRESHOLD:x}: sys irq and "
            f"raw286 read 0 at each of {zero_rises} rises from the AR handshake",
        )

        await self._set_peers("BEYOND", True)
        sys_at, raw_at, rdata = await self._beyond()
        cleared = await self._await_sys_low("beyond")
        await self.csr_write("HANG_SYS_THR_WIDE", HANG_DET_SYS_AXI_TIMEOUT, THRESHOLD_WIDE)
        thr = await self.csr_read(
            "HANG_SYS_THR_WIDE_RB", HANG_DET_SYS_AXI_TIMEOUT, expected=THRESHOLD_WIDE
        )
        assert (thr & HANG_DET_THR_VALUE) == THRESHOLD_WIDE, (
            f"SYS threshold readback 0x{thr:x} want 0x{THRESHOLD_WIDE:x}"
        )
        await self.csr_write("HANG_SYS_ARM_WIDE", HANG_DET_SYS_AXI_CTRL, HANG_DET_ARMED)
        wide_at, wide_raw, _ = await self._beyond("beyond_wide", BEYOND_WIDE_CEILING_RISES)
        await self._await_sys_low("beyond_wide")
        assert wide_at - sys_at == THRESHOLD_WIDE - THRESHOLD, (
            f"sys irq rose at rise {sys_at} with threshold 0x{THRESHOLD:x} and at rise "
            f"{wide_at} with threshold 0x{THRESHOLD_WIDE:x}, want a difference of "
            f"{THRESHOLD_WIDE - THRESHOLD}"
        )
        await self._set_peers("BEYOND", False)
        await self.csr_write("HANG_SYS_THR_RESTORE", HANG_DET_SYS_AXI_TIMEOUT, THRESHOLD)
        self._term("EXISTING-BEYOND")
        self._log_legs(
            "CHK-SYSWIN-BEYOND",
            f"SYS_IN read held past threshold 0x{THRESHOLD:x}, SEP_AXI and DATA_ACCEL armed",
            "tb_axi_hang_irq_sys, tb_cpu_interrupts[286] and CTRL.irq",
            "CTRL written 0 after the release",
            f"tb_axi_hang_irq_sys and raw286 read 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-SYSWIN-BEYOND",
            f"sys irq first 1 at rise {sys_at}, raw286 first 1 at rise {raw_at} "
            f"(ceiling {BEYOND_CEILING_RISES}); sep=0 data=0 with both armed at threshold "
            f"0x{THRESHOLD:x}; CTRL=0x{rdata:x} irq=1; cleared after {cleared} rises; threshold "
            f"0x{THRESHOLD_WIDE:x}: sys irq first 1 at rise {wide_at}, raw286 at rise "
            f"{wide_raw}, {wide_at - sys_at} later than at 0x{THRESHOLD:x}",
        )

        text, first = await self._at_threshold()
        cleared_at = await self._await_sys_low("at")
        self._term("EXISTING-AT")
        self._log_chk(
            "CHK-SYSWIN-AT-LOG",
            f"stall of exactly 0x{THRESHOLD:x} rises: first_sys_irq_rise={first}; "
            f"{text}; cleared after {cleared_at} rises (observe-and-log, not specified, measured)",
        )
        self._mark_step("S2")

        self._step("S3", "disable after timeout: enable written 0 with the stall held")
        await self.csr_write("HANG_SEP_OFF_DISABLE", HANG_DET_SEP_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_OFF_DISABLE", HANG_DET_DATA_ACCEL_CTRL, 0)
        dis = await self._clear_after_timeout("disable", HANG_DET_IRQ_EN, read_irq_first=True)
        self._mark_step("S3")
        self._term("DISABLE-AFTER-TIMEOUT")
        self._log_legs(
            "CHK-SYSWIN-DISABLE-AFTER-TIMEOUT",
            f"SYS_IN read held past threshold 0x{THRESHOLD:x} with CTRL=0x{HANG_DET_ARMED:x}",
            f"sys={dis['sys']} raw286={dis['raw']} at rise {dis['rise']}, CTRL=0x{dis['set_rd']:x}",
            f"CTRL written 0x{HANG_DET_IRQ_EN:x} (enable 0) with the stall held",
            f"sys and raw286 0 at rise {dis['drop']} of the watch, 0 for {dis['held']} held "
            f"rises, CTRL=0x{dis['clear_rd']:x}",
        )
        self._log_chk(
            "CHK-SYSWIN-DISABLE-AFTER-TIMEOUT",
            f"irq 1 -> 0 after enable=0 ({dis['drop']} cycles from the write issue, write "
            f"response at cycle {dis['write_done']}; SF-018 measured, not compared), "
            f"0x{dis['held']:x} held rises irq=0 raw286=0, CTRL.irq=0 (CTRL=0x{dis['clear_rd']:x}); "
            f"before: sys=1 raw286=1 at rise {dis['rise']} after AR, CTRL=0x{dis['set_rd']:x} "
            f"irq=1; no re-assertion in {dis['watched']} watched rises",
        )

        self._step("S4", "irq_en clear after timeout: irq_en written 0, enable kept, stall held")
        ien = await self._clear_after_timeout("irqen", HANG_DET_ENABLE, read_irq_first=False)
        await self.csr_write("HANG_SYS_CTRL_OFF_IRQEN", HANG_DET_SYS_AXI_CTRL, 0)
        self._mark_step("S4")
        self._term("IRQEN-CLEAR")
        self._log_legs(
            "CHK-SYSWIN-IRQEN-CLEAR",
            f"SYS_IN read held past threshold 0x{THRESHOLD:x} with CTRL=0x{HANG_DET_ARMED:x}",
            f"sys={ien['sys']} raw286={ien['raw']} at rise {ien['rise']}",
            f"CTRL written 0x{HANG_DET_ENABLE:x} (irq_en 0) with the stall held",
            f"sys and raw286 0 at rise {ien['drop']} of the watch, 0 for {ien['held']} held "
            f"rises, CTRL=0x{ien['clear_rd']:x}",
        )
        self._log_chk(
            "CHK-SYSWIN-IRQEN-CLEAR",
            f"irq 1 -> 0 after irq_en=0 (sys=1 at rise {ien['rise']} after AR; drop "
            f"{ien['drop']} cycles from the write issue), 0x{ien['held']:x} held rises irq=0 "
            f"raw286=0, CTRL.irq=0 (CTRL=0x{ien['clear_rd']:x}); no re-assertion in "
            f"{ien['watched']} watched rises",
        )

        self._step("S5", "irq_test with enable and irq_en, no stall")
        await self.csr_write("HANG_SYS_CTRL_FIRE", HANG_DET_SYS_AXI_CTRL, HANG_DET_FIRE)
        up = await self._poll_level("irqtest irq rise wait", TEST_RISE_CEILING_RISES, 1)
        fire_rd = await self.csr_read("HANG_SYS_CTRL_FIRE_RB", HANG_DET_SYS_AXI_CTRL)
        assert fire_rd & HANG_DET_IRQ, (
            f"HANG_DET_SYS_AXI_CTRL=0x{fire_rd:x} with irq_test set, irq bit reads 0"
        )
        await self.csr_write("HANG_SYS_CTRL_TEST_OFF", HANG_DET_SYS_AXI_CTRL, HANG_DET_ARMED)
        down = await self._poll_level("irqtest irq drop wait", CLEAR_CEILING_RISES, 0)
        off_rd = await self.csr_read("HANG_SYS_CTRL_TEST_OFF_RB", HANG_DET_SYS_AXI_CTRL)
        assert not off_rd & HANG_DET_IRQ, (
            f"HANG_DET_SYS_AXI_CTRL=0x{off_rd:x} after irq_test cleared, irq bit reads 1"
        )
        self._mark_step("S5")
        self._term("IRQTEST-RAISE")
        self._log_legs(
            "CHK-SYSWIN-IRQTEST-RAISE",
            f"CTRL written 0x{HANG_DET_FIRE:x} (enable | irq_en | irq_test), no stall",
            f"sys and raw286 1 after {up} rises, CTRL=0x{fire_rd:x}",
            f"CTRL written 0x{HANG_DET_ARMED:x} (irq_test 0)",
            f"sys and raw286 0 after {down} rises, CTRL=0x{off_rd:x}",
        )
        self._log_chk(
            "CHK-SYSWIN-IRQTEST-RAISE",
            f"irq_test=1 -> irq 1, raw286 1 after {up} rises, CTRL.irq 1 (CTRL=0x{fire_rd:x}); "
            f"irq_test=0 -> irq 0, raw286 0 after {down} rises, CTRL.irq 0 (CTRL=0x{off_rd:x})",
        )

        for step, term, chk, value, gate in (
            (
                "S6",
                "IRQTEST-DISABLED",
                "CHK-SYSWIN-IRQTEST-DISABLED",
                HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST,
                "enable=0",
            ),
            (
                "S7",
                "IRQTEST-NOIRQEN",
                "CHK-SYSWIN-IRQTEST-NOIRQEN",
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
                f"sys and raw286 0 for {held} rises, CTRL=0x{rd:x}",
                "CTRL written 0",
                f"sys={after}, CTRL=0x{off:x}",
            )
            self._log_chk(
                chk,
                f"0x{held:x}/0x{HELD_WINDOW_RISES:x} rises irq=0 raw286=0, CTRL.irq=0 "
                f"(CTRL=0x{rd:x}; {gate}, irq_test=1); after CTRL=0 sys={after} "
                f"CTRL=0x{off:x}",
            )

        self._step("S8", "restore control, threshold and INBOUND0 filter")
        self._hold(0, "cleanup")
        await self.csr_write("HANG_SYS_CTRL_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_SYS_THR_CLEANUP", HANG_DET_SYS_AXI_TIMEOUT, THRESHOLD_CLEANUP)
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
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
        assert self._reads == _HELD_READS, f"{self._reads} SYS_IN reads started, want {_HELD_READS}"
        assert len(self._sys_items) == self._reads, (
            f"{len(self._sys_items)} SYS_IN reads completed of {self._reads} started"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; %s; checker lines %s; step stamps %s; %d held reads",
            " < ".join(terms),
            "; ".join(f"{t} samples={s} accesses={a} t={w}ps" for t, s, a, w in self._fence),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            len(self._sys_items),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        expired = [w.name for w in self._waits if w.timed_out]
        tolerant = [w.name for w in self._waits if w.allow_timeout]
        tallies = []
        for bus, items in (("SEP_IN", self._sep_items), ("SYS_IN", self._sys_items)):
            bounds = sorted({item.timeout_ns or self.cfg.axi_timeout_ns for item in items})
            allow = sum(1 for item in items if item.allow_timeout)
            timed = sum(1 for item in items if item.timed_out)
            assert not allow and not timed, (
                f"{bus}: {allow} accesses tolerate expiry, {timed} expired"
            )
            tallies.append(
                f"{len(items)} {bus} accesses bound={bounds} ns allow_timeout={allow} "
                f"timed_out={timed}"
            )
        assert not expired and not tolerant, (
            f"bounded waits expired {expired} / tolerating expiry {tolerant}"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, %d expired; "
            "expiry raises AssertionError with the last observed state; %s; %s; "
            "observation windows %s",
            len(self._waits),
            len(expired),
            "; ".join(tallies),
            "; ".join(self._wait_text(w) for w in self._waits),
            "; ".join(f"{n} {c}/{r} rises sampled" for n, r, c in self._windows),
        )
