# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_AXI hang detector below, beyond and at the timeout threshold.

Spec sources: HANG_DET_CTRL and HANG_DET_TIMEOUT_THRESHOLD in smc_base_config.rdl.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._hang_status import check_hang_status
from ._one_shot import _OneShot
from .smc_addr_map import (
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_DATA_ACCEL_TIMEOUT,
    HANG_DET_IRQ,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_SYS_AXI_TIMEOUT,
    HANG_DET_THR_VALUE,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
SEP_BIT = 286
THRESHOLD = 0x40
THRESHOLD_LARGE = 0x1000
BELOW_HOLD_RISES = 16
BELOW_WINDOW_RISES = 256
BEYOND_CEILING_RISES = 128
AT_AFTER_RISES = 8
EXACT_MARGIN_RISES = 256
AR_CEILING_RISES = 256
DONE_CEILING_RISES = 256
CLEAR_CEILING_RISES = 128
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_CHECKERS = (
    "CHK-SEPWIN-BELOW",
    "CHK-SEPWIN-BEYOND",
    "CHK-SEPWIN-AT-LOG",
    "CHK-SEPWIN-EXACT-DELTA",
)
_CHECK_STEP = ("S2", "S3", "S4", "S5")


class smc_hang_sep_timeout_window_test_seq(SmcCsrSeq):
    """Hold one SEP_IN read at R for 16, past-threshold and exactly-threshold rises."""

    def __init__(self, name: str = "smc_hang_sep_timeout_window_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._reads = 0
        self._jtag_reads = 0

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
        """Return (sep irq, raw bit 286, sys irq, data irq) at this rise."""
        dut = cocotb.top
        sep = self._resolved(dut.tb_axi_hang_irq_sep, label) & 1
        raw = self._resolved(dut.tb_cpu_interrupts, label) >> SEP_BIT & 1
        sys_irq = self._resolved(dut.tb_axi_hang_irq_sys, label) & 1
        data = self._resolved(dut.tb_axi_hang_irq_data, label) & 1
        return sep, raw, sys_irq, data

    def _hold(self, value: int, why: str) -> None:
        cocotb.top.tb_sep_axi_r_hold.value = value
        cocotb.log.info(
            "DRIVE tb_sep_axi_r_hold=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    def _start_read(self, name: str):
        self._reads += 1
        self._hold(1, f"{name} stall")
        return cocotb.start_soon(self.csr_read(f"STALL_RD_{name}", SCRATCH_COLD_WARM_0))

    async def _jtag_read(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(label)
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        await _OneShot(item, f"{label}_os").start(self.env.jtag_axi_agent.sequencer)
        assert item.resp_code == 0, f"{label}: JTAG read of 0x{addr:08x} answered {item.resp_code}"
        self._jtag_reads += 1
        return item.rdata & 0xFFFF_FFFF

    async def _await_ar(self, name: str) -> None:
        wait = f"{name} AR handshake wait"
        valid = ready = -1
        self._waits[wait] = (AR_CEILING_RISES, "no rise yet")
        for n in range(1, AR_CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            valid = self._resolved(cocotb.top.s_axi_arvalid, wait) & 1
            ready = self._resolved(cocotb.top.s_axi_arready, wait) & 1
            self._waits[wait] = (
                AR_CEILING_RISES,
                f"arvalid={valid} arready={ready} after {n} rises",
            )
            if valid and ready:
                return
        raise AssertionError(
            f"{wait}: SEP_IN AR handshake not seen in {AR_CEILING_RISES} rises "
            f"(last arvalid={valid} arready={ready})"
        )

    async def _await_done(self, task, name: str) -> None:
        wait = f"{name} read completion wait"
        self._waits[wait] = (DONE_CEILING_RISES, "read pending")
        for n in range(DONE_CEILING_RISES + 1):
            if task.done():
                self._waits[wait] = (DONE_CEILING_RISES, f"read done after {n} rises")
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{wait}: SEP_IN read still pending after {DONE_CEILING_RISES} rises "
            f"with tb_sep_axi_r_hold={int(cocotb.top.tb_sep_axi_r_hold.value)}"
        )

    async def _await_sep_low(self, name: str) -> int:
        wait = f"{name} sep irq clear wait"
        self._waits[wait] = (CLEAR_CEILING_RISES, "no rise yet")
        for n in range(CLEAR_CEILING_RISES + 1):
            sep, raw, _, _ = self._sample(wait)
            self._waits[wait] = (CLEAR_CEILING_RISES, f"sep={sep} raw286={raw} after {n} rises")
            if sep == 0 and raw == 0:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{wait}: sep irq {sep} raw286={raw} after {CLEAR_CEILING_RISES} rises"
        )

    async def _arm(self, label: str, threshold: int | None = None) -> None:
        if threshold is not None:
            await self.csr_write(f"HANG_SEP_THR_{label}", HANG_DET_SEP_AXI_TIMEOUT, threshold)
            thr = await self.csr_read(
                f"HANG_SEP_THR_{label}_RB", HANG_DET_SEP_AXI_TIMEOUT, expected=threshold
            )
            assert (thr & HANG_DET_THR_VALUE) == threshold, (
                f"SEP threshold readback 0x{thr:x} want 0x{threshold:x}"
            )
        await self.csr_write(f"HANG_SEP_ARM_{label}", HANG_DET_SEP_AXI_CTRL, HANG_DET_ARMED)

    async def _set_peers(self, label: str, armed: bool) -> None:
        """Arm or disarm the SYS_AXI and DATA_ACCEL detectors; armed ones use THRESHOLD."""
        for name, ctrl, timeout in (
            ("SYS", HANG_DET_SYS_AXI_CTRL, HANG_DET_SYS_AXI_TIMEOUT),
            ("DATA", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_DATA_ACCEL_TIMEOUT),
        ):
            if armed:
                await self.csr_write(f"HANG_{name}_THR_{label}", timeout, THRESHOLD)
            await self.csr_write(
                f"HANG_{name}_{'ARM' if armed else 'OFF'}_{label}",
                ctrl,
                HANG_DET_ARMED if armed else 0,
            )

    async def _stall(self, name: str, release_at: int, watch: int, assert_zero: bool = False):
        """Stall from the AR handshake, release at rise release_at, sample watch rises.

        Return the first rise of the sep irq and of raw bit 286 (0 when never seen).
        """
        task = self._start_read(name)
        await self._await_ar(name)
        wait = f"{name} window"
        self._waits[wait] = (watch, "no rise yet")
        sep_at = raw_at = 0
        for n in range(1, watch + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == release_at:
                self._hold(0, f"{name} release at rise {n}")
            sep, raw, sys_irq, data = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (watch, f"sep={sep} raw286={raw} rise {n}")
            assert not assert_zero or (sep == 0 and raw == 0), (
                f"{wait}: sep irq={sep} raw286={raw} at rise {n}, want 0/0 "
                f"(stall {release_at} rises, threshold 0x{THRESHOLD:x})"
            )
            sep_at = sep_at or (n if sep else 0)
            raw_at = raw_at or (n if raw else 0)
        await self._await_done(task, name)
        return sep_at, raw_at

    async def _beyond(self) -> tuple[int, int, int]:
        """Stall past the threshold; return (sep rise, raw rise, CTRL rdata)."""
        name = "beyond"
        task = self._start_read(name)
        await self._await_ar(name)
        wait = f"{name} irq wait"
        self._waits[wait] = (BEYOND_CEILING_RISES, "no rise yet")
        sep_at = raw_at = 0
        sep = raw = 0
        for n in range(1, BEYOND_CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            sep, raw, sys_irq, data = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (
                BEYOND_CEILING_RISES,
                f"sep={sep} raw286={raw} sys={sys_irq} data={data} rise {n}",
            )
            assert sys_irq == 0 and data == 0, (
                f"{wait}: peer irq sys={sys_irq} data={data} at rise {n}, want 0/0"
            )
            sep_at = sep_at or (n if sep else 0)
            raw_at = raw_at or (n if raw else 0)
            if sep_at and raw_at:
                break
        else:
            raise AssertionError(
                f"{wait}: sep irq rose at {sep_at}, raw286 at {raw_at} within "
                f"{BEYOND_CEILING_RISES} rises of the AR handshake (last sep={sep} raw286={raw})"
            )
        rdata = await self._jtag_read("HANG_SEP_CTRL_IRQ", HANG_DET_SEP_AXI_CTRL)
        assert rdata & HANG_DET_IRQ, f"HANG_DET_SEP_AXI_CTRL=0x{rdata:x}: irq bit reads 0"
        await check_hang_status(self._jtag_read, "BEYOND", {"SEP"})
        self._hold(0, "beyond-threshold release")
        await self._await_done(task, name)
        await self.csr_write("HANG_SEP_CTRL_OFF_BEYOND", HANG_DET_SEP_AXI_CTRL, 0)
        return sep_at, raw_at, rdata

    async def _exact(self, label: str, threshold: int) -> tuple[int, int]:
        """Measure the rises from the AR handshake to the sep irq and to raw bit 286."""
        task = self._start_read(label)
        await self._await_ar(label)
        wait = f"exact {label} irq wait"
        ceiling = threshold + EXACT_MARGIN_RISES
        self._waits[wait] = (ceiling, "no rise yet")
        sep_at = raw_at = 0
        for n in range(1, ceiling + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            sep, raw, _, _ = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (ceiling, f"sep={sep} raw286={raw} rise {n}")
            sep_at = sep_at or (n if sep else 0)
            raw_at = raw_at or (n if raw else 0)
            if sep_at and raw_at:
                break
        else:
            raise AssertionError(
                f"{wait}: sep irq rose at {sep_at}, raw286 at {raw_at} within {ceiling} rises"
            )
        self._hold(0, f"exact {label} release")
        await self._await_done(task, label)
        await self.csr_write(f"HANG_SEP_CTRL_OFF_{label}", HANG_DET_SEP_AXI_CTRL, 0)
        await self._await_sep_low(f"exact {label}")
        return sep_at, raw_at

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            "tb_sep_axi_r_hold",
            "tb_axi_hang_irq_sys",
            "tb_axi_hang_irq_sep",
            "tb_axi_hang_irq_data",
            "tb_cpu_interrupts",
            "s_axi_arvalid",
            "s_axi_arready",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        self._hold(0, "idle")
        cocotb.log.info("SEED RANDOM_SEED=%s", os.environ.get("RANDOM_SEED", "1"))

        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self._arm("SETUP", THRESHOLD)
        ctrl = await self.csr_read(
            "HANG_SEP_ARM_RB", HANG_DET_SEP_AXI_CTRL, expected=HANG_DET_ARMED
        )
        await RisingEdge(dut.clk_smc_i)
        base = self._resolved(dut.tb_cpu_interrupts, "baseline")
        assert self._sample("baseline") == (0, 0, 0, 0), "baseline irq nets not all 0"
        cocotb.log.info(
            "BASELINE vector=0x%x thr=0x%x ctrl=0x%x sep=0 raw286=0", base, THRESHOLD, ctrl
        )
        self.phases += 1
        self._mark_step("S1")

        sep_at, raw_at = await self._stall(
            "below", BELOW_HOLD_RISES, BELOW_WINDOW_RISES, assert_zero=True
        )
        self.phases += 1
        self._mark_step("S2")
        cocotb.log.info(
            "LIFECYCLE CHK-SEPWIN-BELOW set: SEP_IN read held %d rises, threshold 0x%x",
            BELOW_HOLD_RISES,
            THRESHOLD,
        )
        cocotb.log.info(
            "LIFECYCLE CHK-SEPWIN-BELOW observed: tb_axi_hang_irq_sep and "
            "tb_cpu_interrupts[286] each rise: never (first %d/%d)",
            sep_at,
            raw_at,
        )
        cocotb.log.info("LIFECYCLE CHK-SEPWIN-BELOW cleared: hold released and read completed")
        cocotb.log.info(
            "LIFECYCLE CHK-SEPWIN-BELOW checked_cleared: both probes read 0 for %d rises",
            BELOW_WINDOW_RISES,
        )
        self._log_chk(
            "CHK-SEPWIN-BELOW",
            f"stall {BELOW_HOLD_RISES} rises, threshold 0x{THRESHOLD:x}: sep irq and "
            f"raw286 read 0 at each of {BELOW_WINDOW_RISES} rises from the AR handshake",
        )

        await self._set_peers("BEYOND", True)
        sep_at, raw_at, rdata = await self._beyond()
        cleared = await self._await_sep_low("beyond")
        await self._set_peers("BEYOND", False)
        self.phases += 1
        self._mark_step("S3")
        cocotb.log.info(
            "LIFECYCLE CHK-SEPWIN-BEYOND set: SEP_IN read held past threshold 0x%x, SYS_AXI "
            "and DATA_ACCEL armed",
            THRESHOLD,
        )
        cocotb.log.info(
            "LIFECYCLE CHK-SEPWIN-BEYOND observed: sep irq at rise %d, raw286 at "
            "rise %d, CTRL=0x%x",
            sep_at,
            raw_at,
            rdata,
        )
        cocotb.log.info("LIFECYCLE CHK-SEPWIN-BEYOND cleared: CTRL written 0 after the release")
        cocotb.log.info(
            "LIFECYCLE CHK-SEPWIN-BEYOND checked_cleared: sep irq and raw286 read 0 after %d rises",
            cleared,
        )
        self._log_chk(
            "CHK-SEPWIN-BEYOND",
            f"sep irq first 1 at rise {sep_at}, raw286 first 1 at rise {raw_at} "
            f"(ceiling {BEYOND_CEILING_RISES}); sys=0 data=0 with both armed at threshold "
            f"0x{THRESHOLD:x}; CTRL=0x{rdata:x} irq=1, only SEP status set; cleared after "
            f"{cleared} rises",
        )

        await self._arm("AT")
        at_sep, at_raw = await self._stall("at", THRESHOLD, THRESHOLD + AT_AFTER_RISES)
        await self.csr_write("HANG_SEP_CTRL_OFF_AT", HANG_DET_SEP_AXI_CTRL, 0)
        cleared_at = await self._await_sep_low("at")
        if not at_sep:
            text = f"sep irq did not rise within {THRESHOLD + AT_AFTER_RISES} rises"
        elif at_sep <= THRESHOLD:
            text = f"sep irq rose at rise {at_sep}, before the release at rise {THRESHOLD}"
        else:
            text = f"sep irq rose at rise {at_sep}, {at_sep - THRESHOLD} after the release"
        self.phases += 1
        self._mark_step("S4")
        self._log_chk(
            "CHK-SEPWIN-AT-LOG",
            f"stall of exactly 0x{THRESHOLD:x} rises: first_sep_irq_rise={at_sep} "
            f"first_raw286_rise={at_raw}; {text}; cleared after {cleared_at} rises "
            "(observe-and-log, not specified, measured)",
        )

        await self._arm("EXACT_SMALL")
        small = await self._exact("small", THRESHOLD)
        await self._arm("EXACT_LARGE", THRESHOLD_LARGE)
        large = await self._exact("large", THRESHOLD_LARGE)
        self.phases += 1
        self._mark_step("S5")
        assert large[0] - small[0] == THRESHOLD_LARGE - THRESHOLD, (
            f"sep irq rose at rise {small[0]} with threshold 0x{THRESHOLD:x} and at rise "
            f"{large[0]} with threshold 0x{THRESHOLD_LARGE:x}, want a difference of "
            f"{THRESHOLD_LARGE - THRESHOLD}"
        )
        self._log_chk(
            "CHK-SEPWIN-EXACT-DELTA",
            f"threshold 0x{THRESHOLD:x}: sep_irq_rise={small[0]} raw286_rise={small[1]} "
            f"irq_to_raw={small[1] - small[0]}; threshold 0x{THRESHOLD_LARGE:x}: "
            f"sep_irq_rise={large[0]} raw286_rise={large[1]} "
            f"irq_to_raw={large[1] - large[0]}; sep irq rise difference "
            f"{large[0] - small[0]} == 0x{THRESHOLD_LARGE:x} - 0x{THRESHOLD:x}",
        )

        self._hold(0, "cleanup")
        await self.csr_write("HANG_SEP_CTRL_CLEANUP", HANG_DET_SEP_AXI_CTRL, 0)
        await self.csr_write("HANG_SEP_THR_CLEANUP", HANG_DET_SEP_AXI_TIMEOUT, THRESHOLD_LARGE)
        self.phases += 1
        self._mark_step("S6")

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
        assert self._reads == 5, f"{self._reads} SEP_IN stalls started, want 5"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence ARM<BELOW<BEYOND<AT<EXACT<CLEANUP; checker lines %s; "
            "stamps %s",
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
            f"SEP_IN csr_write/csr_read x{self.accesses} accesses incl. the "
            f"x{self._reads} held reads (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self.accesses} accesses completed",
            ),
            f"JTAG AXI CTRL reads x{self._jtag_reads} (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self._jtag_reads} reads completed",
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
