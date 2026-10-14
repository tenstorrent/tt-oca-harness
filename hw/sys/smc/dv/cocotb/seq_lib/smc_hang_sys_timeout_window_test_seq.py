# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_AXI hang detector below, beyond and at the timeout threshold.

Spec sources: HANG_DET_CTRL and HANG_DET_TIMEOUT_THRESHOLD in smc_base_config.rdl.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_IRQ,
    HANG_DET_SEP_AXI_CTRL,
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
THRESHOLD_CLEANUP = 0x1000
BELOW_HOLD_RISES = 16
BELOW_WINDOW_RISES = 256
BEYOND_CEILING_RISES = 128
AT_AFTER_RISES = 8
AR_CEILING_RISES = 256
DONE_CEILING_RISES = 256
CLEAR_CEILING_RISES = 128
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = ("CHK-SYSWIN-BELOW", "CHK-SYSWIN-BEYOND", "CHK-SYSWIN-AT-LOG")
_CHECK_STEP = ("S2", "S3", "S4")


class _SysInReadSeq(SmcCsrSeq):
    """One SYS_IN read that must answer OKAY."""

    def __init__(self, name: str, addr: int) -> None:
        super().__init__(name)
        self.addr = addr

    async def body(self) -> None:
        item = SmcSysAxiItem(f"rd_{self.get_name()}")
        item.op = SmcSysAxiOp.READ
        item.addr = self.addr
        item.length = 4
        await self.start_item(item)
        await self.finish_item(item)


class smc_hang_sys_timeout_window_test_seq(SmcCsrSeq):
    """Hold one SYS_IN read at R for 16, past-threshold and exactly-threshold rises."""

    def __init__(self, name: str = "smc_hang_sys_timeout_window_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._reads = 0

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
        """Return (sys irq, raw bit 286, sep irq, data irq) at this rise."""
        dut = cocotb.top
        sys_irq = self._resolved(dut.tb_axi_hang_irq_sys, label) & 1
        raw = self._resolved(dut.tb_cpu_interrupts, label) >> SYS_BIT & 1
        sep = self._resolved(dut.tb_axi_hang_irq_sep, label) & 1
        data = self._resolved(dut.tb_axi_hang_irq_data, label) & 1
        return sys_irq, raw, sep, data

    def _hold(self, value: int, why: str) -> None:
        cocotb.top.tb_sys_axi_r_hold.value = value
        cocotb.log.info(
            "DRIVE tb_sys_axi_r_hold=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    def _start_read(self, name: str):
        self._reads += 1
        self._hold(1, f"{name} stall")
        child = _SysInReadSeq(name, SCRATCH_COLD_WARM_0)
        child.cfg = self.cfg
        child.env = self.env
        return cocotb.start_soon(child.start(self.env.sys_in_axi_agent.sequencer))

    async def _await_ar(self, name: str) -> None:
        wait = f"{name} AR handshake wait"
        valid = ready = -1
        self._waits[wait] = (AR_CEILING_RISES, "no rise yet")
        for n in range(1, AR_CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            valid = self._resolved(cocotb.top.sys_axi_arvalid, wait) & 1
            ready = self._resolved(cocotb.top.sys_axi_arready, wait) & 1
            self._waits[wait] = (
                AR_CEILING_RISES,
                f"arvalid={valid} arready={ready} after {n} rises",
            )
            if valid and ready:
                return
        raise AssertionError(
            f"{wait}: SYS_IN AR handshake not seen in {AR_CEILING_RISES} rises "
            f"(last arvalid={valid} arready={ready})"
        )

    async def _await_done(self, task, name: str) -> None:
        wait = f"{name} read completion wait"
        self._waits[wait] = (DONE_CEILING_RISES, "read pending")
        for n in range(1, DONE_CEILING_RISES + 1):
            if task.done():
                self._waits[wait] = (DONE_CEILING_RISES, f"read done after {n - 1} rises")
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        if task.done():
            return
        raise AssertionError(
            f"{wait}: SYS_IN read still pending after {DONE_CEILING_RISES} rises "
            f"with tb_sys_axi_r_hold={int(cocotb.top.tb_sys_axi_r_hold.value)}"
        )

    async def _await_sys_low(self, name: str) -> int:
        wait = f"{name} sys irq clear wait"
        self._waits[wait] = (CLEAR_CEILING_RISES, "no rise yet")
        for n in range(0, CLEAR_CEILING_RISES + 1):
            sys_irq, raw, sep, data = self._sample(wait)
            self._waits[wait] = (CLEAR_CEILING_RISES, f"sys={sys_irq} raw286={raw} after {n} rises")
            if sys_irq == 0 and raw == 0:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{wait}: sys irq still {sys_irq} raw286={raw} after {CLEAR_CEILING_RISES} rises"
        )

    async def _below(self) -> int:
        """Stall 16 rises then release; return the rises sampled at zero."""
        name = "below"
        task = self._start_read(name)
        await self._await_ar(name)
        wait = f"{name} window"
        self._waits[wait] = (BELOW_WINDOW_RISES, "no rise yet")
        for n in range(1, BELOW_WINDOW_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == BELOW_HOLD_RISES:
                self._hold(0, "below-threshold release")
            sys_irq, raw, sep, data = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (BELOW_WINDOW_RISES, f"sys={sys_irq} raw286={raw} rise {n}")
            assert sys_irq == 0 and raw == 0, (
                f"{wait}: sys irq={sys_irq} raw286={raw} at rise {n}, want 0/0 "
                f"(stall {BELOW_HOLD_RISES} rises, threshold 0x{THRESHOLD:x})"
            )
        await self._await_done(task, name)
        return BELOW_WINDOW_RISES

    async def _beyond(self) -> tuple[int, int, int]:
        """Stall past the threshold; return (sys rise, raw rise, CTRL rdata)."""
        name = "beyond"
        task = self._start_read(name)
        await self._await_ar(name)
        wait = f"{name} irq wait"
        self._waits[wait] = (BEYOND_CEILING_RISES, "no rise yet")
        sys_at = raw_at = 0
        sys_irq = raw = sep = data = 0
        for n in range(1, BEYOND_CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            sys_irq, raw, sep, data = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (
                BEYOND_CEILING_RISES,
                f"sys={sys_irq} raw286={raw} sep={sep} data={data} after {n} rises",
            )
            assert sep == 0 and data == 0, (
                f"{wait}: peer irq sep={sep} data={data} at rise {n}, want 0/0"
            )
            sys_at = sys_at or (n if sys_irq else 0)
            raw_at = raw_at or (n if raw else 0)
            if sys_at and raw_at:
                break
        else:
            raise AssertionError(
                f"{wait}: sys irq rose at {sys_at}, raw286 at {raw_at} within "
                f"{BEYOND_CEILING_RISES} rises of the AR handshake (last sys={sys_irq} "
                f"raw286={raw})"
            )
        rdata = await self.csr_read("HANG_SYS_CTRL_IRQ", HANG_DET_SYS_AXI_CTRL)
        assert rdata & HANG_DET_IRQ, f"HANG_DET_SYS_AXI_CTRL=0x{rdata:x}: irq bit reads 0"
        self._hold(0, "beyond-threshold release")
        await self._await_done(task, name)
        await self.csr_write("HANG_SYS_CTRL_OFF_BEYOND", HANG_DET_SYS_AXI_CTRL, 0)
        return sys_at, raw_at, rdata

    async def _at_threshold(self) -> tuple[str, int]:
        """Release exactly 0x40 rises after the AR handshake; return (log text, first rise)."""
        name = "at"
        task = self._start_read(name)
        await self._await_ar(name)
        wait = f"{name} window"
        total = THRESHOLD + AT_AFTER_RISES
        self._waits[wait] = (total, "no rise yet")
        first = 0
        for n in range(1, total + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == THRESHOLD:
                self._hold(0, "at-threshold release")
            sys_irq, raw, sep, data = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (total, f"sys={sys_irq} raw286={raw} rise {n}")
            first = first or (n if sys_irq else 0)
        if not first:
            text = f"sys irq did not rise within {total} rises of the AR handshake"
        elif first <= THRESHOLD:
            text = f"sys irq rose at rise {first}, before the release at rise {THRESHOLD}"
        else:
            text = f"sys irq rose at rise {first}, {first - THRESHOLD} after the release"
        await self._await_done(task, name)
        await self.csr_write("HANG_SYS_CTRL_OFF_AT", HANG_DET_SYS_AXI_CTRL, 0)
        return text, first

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
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
        self.phases += 1
        self._mark_step("S1")

        zero_rises = await self._below()
        self.phases += 1
        self._mark_step("S2")
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

        sys_at, raw_at, rdata = await self._beyond()
        cleared = await self._await_sys_low("beyond")
        self.phases += 1
        self._mark_step("S3")
        self._log_legs(
            "CHK-SYSWIN-BEYOND",
            f"SYS_IN read held past threshold 0x{THRESHOLD:x}",
            "tb_axi_hang_irq_sys, tb_cpu_interrupts[286] and CTRL.irq",
            "CTRL written 0 after the release",
            f"tb_axi_hang_irq_sys and raw286 read 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-SYSWIN-BEYOND",
            f"sys irq first 1 at rise {sys_at}, raw286 first 1 at rise {raw_at} "
            f"(ceiling {BEYOND_CEILING_RISES}); sep=0 data=0; CTRL=0x{rdata:x} irq=1; "
            f"cleared after {cleared} rises",
        )

        text, first = await self._at_threshold()
        cleared_at = await self._await_sys_low("at")
        self.phases += 1
        self._mark_step("S4")
        self._log_chk(
            "CHK-SYSWIN-AT-LOG",
            f"stall of exactly 0x{THRESHOLD:x} rises: first_sys_irq_rise={first}; "
            f"{text}; cleared after {cleared_at} rises (observe-and-log, owner value pending)",
        )

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
        assert self._reads == 3, f"{self._reads} SYS_IN reads started, want 3"
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
        dut = cocotb.top
        fuse = f"{FUSE_SENSE_RISES} rises"
        subs = {
            "fuse sense wait tb_fuse_sense_done (AssertionError on expiry)": (
                fuse,
                f"tb_fuse_sense_done={int(dut.tb_fuse_sense_done.value)}",
            ),
            "fuse sense wait tb_fuse_reset_n (AssertionError on expiry)": (
                fuse,
                f"tb_fuse_reset_n={self._level('tb_fuse_reset_n')}",
            ),
            "fuse sense wait tb_rst_warm_smc_clk_n (AssertionError on expiry)": (
                fuse,
                f"tb_rst_warm_smc_clk_n={self._level('tb_rst_warm_smc_clk_n')}",
            ),
            "SEP_IN csr_write/csr_read HANG_DET_* and INBOUND0 filter "
            f"x{self.accesses} accesses (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self.accesses} accesses completed",
            ),
            f"SYS_IN held reads x{self._reads} (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self._reads} reads completed",
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
