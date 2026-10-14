# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_AXI hang detector threshold updates, reset value and small values on live stalls.

Spec sources: HANG_DET_CTRL and HANG_DET_TIMEOUT_THRESHOLD in smc_base_config.rdl.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_IRQ_EN,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_THR_VALUE,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
THR_LOW = 0x40
THR_HIGH = 0x400
THR_DEFAULT = 0x1000
MARGIN = 64
RAISE_WRITE_AT = 16
LOWER_WRITE_AT = 32
RAISE_CEILING = 128
LOWER_QUIET = 512
LOWER_CEILING = 1088
ENABLE_CLEAR_CEILING = 1232
AFTER_COMPLETION_CEILING = 128
SMALL_THRESHOLDS = (1, 2, 16)
AR_CEILING_RISES = 256
DONE_CEILING_RISES = 256
CLEAR_CEILING_RISES = 128
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
_CHECKERS = (
    "CHK-THR-RAISE-DURING",
    "CHK-THR-LOWER-DURING",
    "CHK-THR-AFTER-COMPLETION",
    "CHK-THR-AFTER-ENABLE-CLEAR-LOG",
    "CHK-THR-DEFAULT-BEYOND",
    "CHK-THR-DEFAULT-EXACT-LOG",
    "CHK-THR-SMALL-RISE",
    "CHK-THR-SMALL-LOG",
)
_CHECK_STEP = ("S2", "S3", "S4", "S5", "S6", "S6", "S7", "S7")


class _Stall:
    """Rises counted from the AR handshake and the first rise of the sep irq."""

    def __init__(self) -> None:
        self.n = 0
        self.first = 0
        self.last = -1
        self.finished = False
        self.marks: list[int] = []


class smc_hang_sep_threshold_test_seq(SmcCsrSeq):
    """Update the SEP_AXI threshold during held SEP_IN reads and measure the irq rise."""

    def __init__(self, name: str = "smc_hang_sep_threshold_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._reads = 0
        self._jtag_writes = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _lifecycle(chk_id: str, set_: str, observed: str, cleared: str, checked: str) -> None:
        for leg, text in (
            ("set", set_),
            ("observed", observed),
            ("cleared", cleared),
            ("checked_cleared", checked),
        ):
            cocotb.log.info("LIFECYCLE %s %s: %s", chk_id, leg, text)

    @staticmethod
    def _sep(label: str) -> int:
        sig = cocotb.top.tb_axi_hang_irq_sep
        assert sig.value.is_resolvable, f"{label}: tb_axi_hang_irq_sep is X/Z ({sig.value})"
        return int(sig.value) & 1

    @staticmethod
    def _signal(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z ({sig.value})"
        return int(sig.value) & 1

    def _hold(self, value: int, why: str) -> None:
        cocotb.top.tb_sep_axi_r_hold.value = value
        cocotb.log.info(
            "DRIVE tb_sep_axi_r_hold=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    async def _jtag_write(self, label: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(label)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await _OneShot(item, f"{label}_os").start(self.env.jtag_axi_agent.sequencer)
        assert item.resp_code == 0, f"{label}: JTAG write to 0x{addr:08x} answered {item.resp_code}"
        self._jtag_writes += 1
        cocotb.log.info("DRIVE JTAG write 0x%08x = 0x%x (%s)", addr, data, label)

    async def _await_ar(self, name: str) -> None:
        wait = f"{name} AR handshake wait"
        valid = ready = -1
        self._waits[wait] = (AR_CEILING_RISES, "no rise yet")
        for n in range(1, AR_CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            valid = self._signal("s_axi_arvalid")
            ready = self._signal("s_axi_arready")
            self._waits[wait] = (
                AR_CEILING_RISES,
                f"arvalid={valid} arready={ready} after {n} rises",
            )
            if valid and ready:
                return
        raise AssertionError(
            f"{wait}: no SEP_IN AR handshake in {AR_CEILING_RISES} rises "
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
            f"{wait}: SEP_IN read pending after {DONE_CEILING_RISES} rises "
            f"with tb_sep_axi_r_hold={self._signal('tb_sep_axi_r_hold')}"
        )

    async def _await_sep_low(self, name: str) -> int:
        wait = f"{name} sep irq clear wait"
        self._waits[wait] = (CLEAR_CEILING_RISES, "no rise yet")
        for n in range(CLEAR_CEILING_RISES + 1):
            sep = self._sep(wait)
            self._waits[wait] = (CLEAR_CEILING_RISES, f"sep={sep} after {n} rises")
            if sep == 0:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{wait}: sep irq 1 after {CLEAR_CEILING_RISES} rises")

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

    async def _monitor(self, st: _Stall, wait: str, ceiling: int) -> None:
        self._waits[wait] = (ceiling, "no rise yet")
        while st.n < ceiling and not st.first:
            await RisingEdge(cocotb.top.clk_smc_i)
            st.n += 1
            sep = self._sep(f"{wait}[{st.n}]")
            st.last = sep
            self._waits[wait] = (ceiling, f"sep={sep} rise {st.n}")
            if sep:
                st.first = st.n
        st.finished = True

    async def _stall(self, name: str, ceiling: int, write_at: int = 0, ops=()):
        """Hold one SEP_IN read, sample the sep irq each rise from the AR handshake.

        After write_at rises the JTAG ops run in order; st.marks holds the rise after each.
        Return (stall, read task) once the sampler has seen the irq or reached the ceiling.
        """
        self._reads += 1
        self._hold(1, f"{name} stall")
        task = cocotb.start_soon(self.csr_read(f"STALL_RD_{name}", SCRATCH_COLD_WARM_0))
        await self._await_ar(name)
        st = _Stall()
        cocotb.start_soon(self._monitor(st, f"{name} sep irq wait", ceiling))
        for _ in range(write_at):
            await RisingEdge(cocotb.top.clk_smc_i)
        for label, addr, data in ops:
            await self._jtag_write(f"{name}_{label}", addr, data)
            st.marks.append(st.n)
        for _ in range(ceiling + 4):
            if st.finished:
                break
            await RisingEdge(cocotb.top.clk_smc_i)
        assert st.finished, f"{name}: sampler unfinished at rise {st.n}"
        return st, task

    @staticmethod
    def _need_irq(st: _Stall, name: str, ceiling: int) -> None:
        assert st.first, (
            f"{name}: sep irq still 0 at {ceiling} rises of the AR handshake "
            f"(last sep={st.last} at rise {st.n}, JTAG writes landed after "
            f"{st.marks})"
        )

    async def _release(self, task, name: str) -> None:
        self._hold(0, f"{name} release")
        await self._await_done(task, name)

    async def _ctrl_off(self, name: str) -> int:
        await self.csr_write(f"HANG_SEP_CTRL_OFF_{name}", HANG_DET_SEP_AXI_CTRL, 0)
        return await self._await_sep_low(name)

    async def _measure(self, name: str, threshold: int, ceiling: int) -> tuple[int, int]:
        """Arm with the threshold, hold a stall, return (first sep rise, rises to clear)."""
        await self._arm(name, threshold)
        st, task = await self._stall(name, ceiling)
        await self._release(task, name)
        self._need_irq(st, name, ceiling)
        return st.first, await self._ctrl_off(name)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in ("tb_sep_axi_r_hold", "tb_axi_hang_irq_sep", "s_axi_arvalid", "s_axi_arready"):
            assert hasattr(dut, sig), f"{sig} missing"
        seed = int(os.environ.get("RANDOM_SEED", "1"))
        order = list(SMALL_THRESHOLDS)
        random.Random(seed).shuffle(order)
        self._hold(0, "idle")
        cocotb.log.info("SEED RANDOM_SEED=%d small threshold order %s", seed, order)

        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self.csr_write("HANG_SEP_OFF", HANG_DET_SEP_AXI_CTRL, 0)
        assert self._sep("baseline") == 0, "baseline sep irq is 1"
        self.phases += 1
        self._mark_step("S1")

        # S2: raise during the stall
        await self._arm("RAISE", THR_LOW)
        st, task = await self._stall(
            "raise", RAISE_CEILING, RAISE_WRITE_AT, [("THR", HANG_DET_SEP_AXI_TIMEOUT, THR_HIGH)]
        )
        self._need_irq(st, "raise", RAISE_CEILING)
        await self._release(task, "raise")
        cleared = await self._ctrl_off("raise")
        self.phases += 1
        self._mark_step("S2")
        self._lifecycle(
            "CHK-THR-RAISE-DURING",
            f"stall held, threshold 0x{THR_LOW:x} raised to 0x{THR_HIGH:x}",
            f"tb_axi_hang_irq_sep first 1 at rise {st.first}",
            "hold released and CTRL written 0",
            f"tb_axi_hang_irq_sep read 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-THR-RAISE-DURING",
            f"threshold write 0x{THR_HIGH:x} landed after rise {st.marks[0]}; sep irq "
            f"first 1 at rise {st.first} (ceiling {RAISE_CEILING}); cleared after "
            f"{cleared} rises",
        )

        # S3: lower during the stall
        await self._arm("LOWER", THR_HIGH)
        st, task = await self._stall(
            "lower", LOWER_CEILING, LOWER_WRITE_AT, [("THR", HANG_DET_SEP_AXI_TIMEOUT, THR_LOW)]
        )
        self._need_irq(st, "lower", LOWER_CEILING)
        assert st.first > LOWER_QUIET, f"sep irq rose at rise {st.first}, want 0 through 512"
        await self._release(task, "lower")
        thr = await self.csr_read(
            "HANG_SEP_THR_LOWER_FINAL", HANG_DET_SEP_AXI_TIMEOUT, expected=THR_LOW
        )
        assert (thr & HANG_DET_THR_VALUE) == THR_LOW, f"threshold readback 0x{thr:x}"
        cleared = await self._await_sep_low("lower")
        self.phases += 1
        self._mark_step("S3")
        self._lifecycle(
            "CHK-THR-LOWER-DURING",
            f"stall held, threshold 0x{THR_HIGH:x} lowered to 0x{THR_LOW:x}",
            f"tb_axi_hang_irq_sep 0 through rise {LOWER_QUIET}, first 1 at {st.first}",
            "hold released",
            f"threshold reads 0x{thr & HANG_DET_THR_VALUE:x}, sep irq 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-THR-LOWER-DURING",
            f"threshold write 0x{THR_LOW:x} landed after rise {st.marks[0]}; sep irq 0 "
            f"through rise {LOWER_QUIET}, first 1 at rise {st.first} (ceiling "
            f"{LOWER_CEILING}); threshold reads 0x{thr & HANG_DET_THR_VALUE:x}",
        )

        # S4: the stored threshold applies to the next stall
        st, task = await self._stall("after", AFTER_COMPLETION_CEILING)
        self._need_irq(st, "after", AFTER_COMPLETION_CEILING)
        await self._release(task, "after")
        cleared = await self._ctrl_off("after")
        self.phases += 1
        self._mark_step("S4")
        self._lifecycle(
            "CHK-THR-AFTER-COMPLETION",
            f"new stall held with threshold 0x{THR_LOW:x}",
            f"tb_axi_hang_irq_sep first 1 at rise {st.first}",
            "hold released and CTRL written 0",
            f"tb_axi_hang_irq_sep read 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-THR-AFTER-COMPLETION",
            f"sep irq first 1 at rise {st.first} of the new stall (ceiling "
            f"{AFTER_COMPLETION_CEILING}); cleared after {cleared} rises",
        )

        # S5: lower, clear the enable and set it again during the stall
        await self._arm("ENCLR", THR_HIGH)
        st, task = await self._stall(
            "enclr",
            ENABLE_CLEAR_CEILING,
            LOWER_WRITE_AT,
            [
                ("THR", HANG_DET_SEP_AXI_TIMEOUT, THR_LOW),
                ("IRQ_EN", HANG_DET_SEP_AXI_CTRL, HANG_DET_IRQ_EN),
                ("ARM", HANG_DET_SEP_AXI_CTRL, HANG_DET_ARMED),
            ],
        )
        self._need_irq(st, "enclr", ENABLE_CLEAR_CEILING)
        reenable = st.marks[-1]
        await self._release(task, "enclr")
        cleared = await self._ctrl_off("enclr")
        self.phases += 1
        self._mark_step("S5")
        self._log_chk(
            "CHK-THR-AFTER-ENABLE-CLEAR-LOG",
            f"threshold 0x{THR_LOW:x} written at rise {st.marks[0]}, enable re-set after "
            f"rise {reenable}; sep irq first 1 at rise {st.first} of the stall, "
            f"rises_from_reenable={st.first - reenable} "
            f"(ceiling {ENABLE_CLEAR_CEILING}); cleared after {cleared} rises "
            "(observe-and-log, owner value pending)",
        )

        # S6: reset threshold value
        first, cleared = await self._measure("default", THR_DEFAULT, THR_DEFAULT + MARGIN)
        assert first, f"sep irq still 0 at {THR_DEFAULT + MARGIN} rises"
        self.phases += 1
        self._mark_step("S6")
        self._lifecycle(
            "CHK-THR-DEFAULT-BEYOND",
            f"stall held with threshold 0x{THR_DEFAULT:x}",
            f"tb_axi_hang_irq_sep first 1 at rise {first}",
            "hold released and CTRL written 0",
            f"tb_axi_hang_irq_sep read 0 after {cleared} rises",
        )
        self._log_chk(
            "CHK-THR-DEFAULT-BEYOND",
            f"threshold 0x{THR_DEFAULT:x}: sep irq first 1 at rise {first} within "
            f"ceiling {THR_DEFAULT + MARGIN}",
        )
        self._log_chk(
            "CHK-THR-DEFAULT-EXACT-LOG",
            f"first_sep_irq_rise={first} threshold={THR_DEFAULT} "
            f"offset={first - THR_DEFAULT} (observe-and-log, owner value pending)",
        )

        # S7: small thresholds
        small = {}
        for thr_value in order:
            first, cleared = await self._measure(f"small{thr_value}", thr_value, thr_value + MARGIN)
            assert first, f"threshold {thr_value}: sep irq still 0 at {thr_value + MARGIN} rises"
            small[thr_value] = (first, cleared)
            self._lifecycle(
                "CHK-THR-SMALL-RISE",
                f"stall held with threshold {thr_value}",
                f"tb_axi_hang_irq_sep first 1 at rise {first}",
                "hold released and CTRL written 0",
                f"tb_axi_hang_irq_sep read 0 after {cleared} rises",
            )
        self.phases += 1
        self._mark_step("S7")
        cells = ", ".join(f"thr {t}: rise {small[t][0]} (ceiling {t + MARGIN})" for t in order)
        self._log_chk("CHK-THR-SMALL-RISE", f"order {order}; {cells}")
        offsets = ", ".join(
            f"threshold={t} first_sep_irq_rise={small[t][0]} offset={small[t][0] - t}"
            for t in order
        )
        self._log_chk("CHK-THR-SMALL-LOG", f"{offsets} (observe-and-log, owner value pending)")

        # S8: cleanup
        self._hold(0, "cleanup")
        await self.csr_write("HANG_SEP_CTRL_CLEANUP", HANG_DET_SEP_AXI_CTRL, 0)
        await self.csr_write("HANG_SEP_THR_CLEANUP", HANG_DET_SEP_AXI_TIMEOUT, THR_DEFAULT)
        self.phases += 1
        self._mark_step("S8")

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
        assert self._reads == 8, f"{self._reads} SEP_IN stalls started, want 8"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence RAISE<LOWER<AFTER-COMPLETION<AFTER-ENABLE-CLEAR<DEFAULT"
            "<SMALL<CLEANUP; checker lines %s; stamps %s",
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
            f"SEP_IN csr_write/csr_read x{self.accesses} accesses incl. the "
            f"x{self._reads} held reads (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self.accesses} accesses completed",
            ),
            f"JTAG AXI writes x{self._jtag_writes} (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self._jtag_writes} writes completed",
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
