# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_AXI hang detector control writes while a SEP_IN read stays held.

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
    HANG_DET_ENABLE,
    HANG_DET_IRQ,
    HANG_DET_IRQ_EN,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_THR_VALUE,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
SEP_BIT = 286
THRESHOLD = 0x40
THRESHOLD_LARGE = 0x1000
RAISE_CEILING_RISES = 128
HOLD_WINDOW_RISES = 65
GATE_HOLD_RISES = 128
LATE_FIRST_RISES = 4
LATE_CEILING_RISES = 128
TOGGLES = 8
TOGGLE_START_RISE = 60
START_SLACK_RISES = 16
AR_CEILING_RISES = 256
DONE_CEILING_RISES = 256
CLEAR_CEILING_RISES = 128
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_CHECKERS = (
    "CHK-DROPCTL-IRQEN-CLEAR",
    "CHK-DROPCTL-GATE-HOLD",
    "CHK-DROPCTL-ENABLE-CLEAR",
    "CHK-DROPCTL-REENABLE-LOG",
    "CHK-DROPCTL-TOGGLE-GATING",
    "CHK-DROPCTL-TOGGLE-LOG",
    "CHK-DROPCTL-BOTH-CAUSES-LOG",
)
_CHECK_STEP = ("S2", "S3", "S3", "S4", "S5", "S5", "S6")


class _Stall:
    """One held SEP_IN read; ``rises`` counts clk_smc_i rises since its AR handshake."""

    def __init__(self, task) -> None:
        self.task = task
        self.rises = 0
        self.sep_now = 0
        self.stop = False


class smc_hang_sep_drop_controls_test_seq(SmcCsrSeq):
    """Drive SEP_AXI CTRL over JTAG while one SEP_IN read is held at R."""

    def __init__(self, name: str = "smc_hang_sep_drop_controls_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._reads = 0
        self._jtag_reads = 0
        self._jtag_writes = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _resolved(sig, label: str) -> int:
        assert sig.value.is_resolvable, f"{label}: {sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    def _sample(self, label: str) -> tuple[int, int]:
        """Return (tb_axi_hang_irq_sep, tb_cpu_interrupts[286]) at this rise."""
        dut = cocotb.top
        sep = self._resolved(dut.tb_axi_hang_irq_sep, label) & 1
        raw = self._resolved(dut.tb_cpu_interrupts, label) >> SEP_BIT & 1
        return sep, raw

    def _hold(self, value: int, why: str) -> None:
        cocotb.top.tb_sep_axi_r_hold.value = value
        cocotb.log.info(
            "DRIVE tb_sep_axi_r_hold=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    async def _jtag(self, label: str, addr: int, op, data: int = 0) -> int:
        item = SmcSysAxiItem(label)
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        await _OneShot(item, f"{label}_os").start(self.env.jtag_axi_agent.sequencer)
        assert item.resp_code == 0, (
            f"{label}: JTAG access to 0x{addr:08x} answered {item.resp_code}"
        )
        if op == SmcSysAxiOp.READ:
            self._jtag_reads += 1
            return item.rdata & 0xFFFF_FFFF
        self._jtag_writes += 1
        cocotb.log.info("DRIVE JTAG write 0x%08x = 0x%x (%s)", addr, data, label)
        return data

    async def _ctrl(
        self, label: str, value: int, exact: bool = False, readback: bool = True
    ) -> int:
        """Write SEP_AXI CTRL over JTAG and read it back; the irq bit is masked unless exact."""
        await self._jtag(f"{label}_W", HANG_DET_SEP_AXI_CTRL, SmcSysAxiOp.WRITE, value)
        if not readback:
            return value
        rdata = await self._jtag(f"{label}_RB", HANG_DET_SEP_AXI_CTRL, SmcSysAxiOp.READ)
        got = rdata if exact else rdata & ~HANG_DET_IRQ
        assert got == value, f"{label}: CTRL readback 0x{rdata:x}, want 0x{value:x}"
        return rdata

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
            f"{wait}: no SEP_IN AR handshake in {AR_CEILING_RISES} rises "
            f"(last arvalid={valid} arready={ready})"
        )

    async def _count(self, st: _Stall) -> None:
        while not st.stop:
            await RisingEdge(cocotb.top.clk_smc_i)
            st.rises += 1
            st.sep_now = self._sample("stall rise counter")[0]

    async def _begin(self, name: str) -> _Stall:
        self._reads += 1
        self._hold(1, f"{name} stall")
        st = _Stall(cocotb.start_soon(self.csr_read(f"STALL_RD_{name}", SCRATCH_COLD_WARM_0)))
        await self._await_ar(name)
        cocotb.start_soon(self._count(st))
        return st

    async def _end(self, st: _Stall, name: str) -> int:
        """Release the hold, wait for the read, return the rises the hold lasted."""
        held = st.rises
        self._hold(0, f"{name} release after {held} rises")
        st.stop = True
        wait = f"{name} read completion wait"
        self._waits[wait] = (DONE_CEILING_RISES, "read pending")
        for n in range(DONE_CEILING_RISES + 1):
            if st.task.done():
                self._waits[wait] = (DONE_CEILING_RISES, f"read done after {n} rises")
                return held
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{wait}: SEP_IN read pending after {DONE_CEILING_RISES} rises")

    def _assert_held(self, st: _Stall, label: str) -> None:
        assert self._resolved(cocotb.top.tb_sep_axi_r_hold, label) == 1 and not st.task.done(), (
            f"{label}: the SEP_IN read is no longer held"
        )

    async def _rises_to_high(self, label: str, ceiling: int) -> int:
        """Rises until tb_axi_hang_irq_sep reads 1; expiry raises with the last samples."""
        wait = f"{label} sep irq watch"
        self._waits[wait] = (ceiling, "no rise yet")
        for n in range(1, ceiling + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            sep, raw = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (ceiling, f"sep={sep} raw286={raw} rise {n}")
            if sep:
                return n
        raise AssertionError(
            f"{wait}: tb_axi_hang_irq_sep still 0 after {ceiling} rises "
            f"(last sep={sep} raw286={raw})"
        )

    async def _await_high(self, label: str) -> int:
        return await self._rises_to_high(label, RAISE_CEILING_RISES)

    async def _await_sep_low(self, name: str) -> int:
        wait = f"{name} sep irq clear wait"
        self._waits[wait] = (CLEAR_CEILING_RISES, "no rise yet")
        for n in range(CLEAR_CEILING_RISES + 1):
            sep, raw = self._sample(wait)
            self._waits[wait] = (CLEAR_CEILING_RISES, f"sep={sep} raw286={raw} after {n} rises")
            if sep == 0 and raw == 0:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{wait}: sep irq {sep} raw286={raw} after {CLEAR_CEILING_RISES} rises"
        )

    async def _quiet(self, st: _Stall, label: str, rises: int) -> None:
        """Require both probes 0 at each of the next ``rises`` rises with the hold on."""
        wait = f"{label} quiet window"
        self._waits[wait] = (rises, "no rise yet")
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            sep, raw = self._sample(f"{wait}[{n}]")
            self._waits[wait] = (rises, f"sep={sep} raw286={raw} rise {n}")
            self._assert_held(st, wait)
            assert sep == 0 and raw == 0, f"{wait}: sep={sep} raw286={raw} at rise {n}, want 0/0"

    async def _drop_phase(self, st: _Stall) -> None:
        raise_at = await self._await_high("S2 timeout")
        cocotb.log.info("S2 timeout: sep and raw286 1 at rise %d after the AR handshake", raise_at)
        rdata = await self._ctrl("S2_IRQEN_CLEAR", HANG_DET_ENABLE, exact=True)
        await self._quiet(st, "S2", HOLD_WINDOW_RISES)
        status = await self._jtag("S2_CTRL_IRQ", HANG_DET_SEP_AXI_CTRL, SmcSysAxiOp.READ)
        assert not status & HANG_DET_IRQ, f"S2: CTRL=0x{status:x} irq reads 1 after the clear"
        self._mark_step("S2")
        cocotb.log.info(
            "LIFECYCLE CHK-DROPCTL-IRQEN-CLEAR set: SEP_IN read held, sep irq 1 at rise %d",
            raise_at,
        )
        cocotb.log.info(
            "LIFECYCLE CHK-DROPCTL-IRQEN-CLEAR observed: tb_axi_hang_irq_sep, "
            "tb_cpu_interrupts[286], CTRL.irq"
        )
        cocotb.log.info(
            "LIFECYCLE CHK-DROPCTL-IRQEN-CLEAR cleared: CTRL=0x%x written over JTAG",
            HANG_DET_ENABLE,
        )
        cocotb.log.info(
            "LIFECYCLE CHK-DROPCTL-IRQEN-CLEAR checked_cleared: all read 0 for %d rises",
            HOLD_WINDOW_RISES,
        )
        self._log_chk(
            "CHK-DROPCTL-IRQEN-CLEAR",
            f"sep irq 1 at rise {raise_at}; irq_en cleared, readback 0x{rdata:x} == "
            f"enable; sep irq, raw286 0 at {HOLD_WINDOW_RISES} rises with the hold on; "
            f"CTRL.irq 0 (CTRL=0x{status:x})",
        )

        await self._quiet(st, "S3", GATE_HOLD_RISES)
        irq_reads = []
        for i in range(3):
            irq_reads.append(
                await self._jtag(f"S3_CTRL_IRQ{i}", HANG_DET_SEP_AXI_CTRL, SmcSysAxiOp.READ)
            )
            sep, raw = self._sample(f"S3 read {i}")
            assert not irq_reads[-1] & HANG_DET_IRQ and sep == 0 and raw == 0, (
                f"S3 read {i}: CTRL=0x{irq_reads[-1]:x} sep={sep} raw286={raw}, want irq 0"
            )
        self._assert_held(st, "S3")
        self._mark_step("S3")
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-GATE-HOLD set: irq dropped by the irq_en clear")
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-GATE-HOLD observed: sep irq each rise, 3 CTRL reads")
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-GATE-HOLD cleared: no clearing write issued")
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-GATE-HOLD checked_cleared: CTRL.irq 0 x3")
        self._log_chk(
            "CHK-DROPCTL-GATE-HOLD",
            f"sep irq, raw286 0 at each of {GATE_HOLD_RISES} rises with no write; "
            f"CTRL reads {[hex(r) for r in irq_reads]} irq 0 each; sep irq unchanged 0",
        )

        await self._ctrl("S3_ARM_AGAIN", HANG_DET_ARMED)
        live_at = await self._await_high("S3 enable clear")
        await self._ctrl("S3_ENABLE_CLEAR", HANG_DET_IRQ_EN)
        await RisingEdge(cocotb.top.clk_smc_i)
        sep, raw = self._sample("S3 enable clear")
        self._assert_held(st, "S3 enable clear")
        status = await self._jtag(
            "S3_ENABLE_CLEAR_CTRL_IRQ", HANG_DET_SEP_AXI_CTRL, SmcSysAxiOp.READ
        )
        assert sep == 0 and raw == 0 and not status & HANG_DET_IRQ, (
            f"S3 enable clear: sep={sep} raw286={raw} CTRL=0x{status:x}, want irq 0"
        )
        await self._ctrl("S3_ENABLE_RESTORE", HANG_DET_ENABLE)
        await self._quiet(st, "S3 restore", HOLD_WINDOW_RISES)
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-ENABLE-CLEAR set: sep irq 1 at rise %d", live_at)
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-ENABLE-CLEAR observed: sep irq, raw286, CTRL.irq")
        cocotb.log.info(
            "LIFECYCLE CHK-DROPCTL-ENABLE-CLEAR cleared: CTRL=0x%x written over JTAG",
            HANG_DET_IRQ_EN,
        )
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-ENABLE-CLEAR checked_cleared: all read 0")
        self._log_chk(
            "CHK-DROPCTL-ENABLE-CLEAR",
            f"sep irq 1 at rise {live_at} with CTRL armed; enable cleared with irq_en set, "
            f"sep irq, raw286 0 one rise after the readback; CTRL.irq 0 (CTRL=0x{status:x})",
        )

        await self._ctrl("S4_ENABLE_IRQEN", HANG_DET_ARMED)
        first = await self._rises_to_high("S4 irq_en late", LATE_CEILING_RISES)
        await self._ctrl("S4_IRQEN_ONLY", HANG_DET_IRQ_EN, readback=False)
        await self._ctrl("S4_ARMED_AGAIN", HANG_DET_ARMED, readback=False)
        again = await self._rises_to_high("S4 enable re-set", LATE_CEILING_RISES)
        held = await self._end(st, "S4")
        await self._ctrl("S4_CTRL_OFF", 0)
        self._mark_step("S4")
        near = "within" if 0 < first <= LATE_FIRST_RISES else "after"
        self._log_chk(
            "CHK-DROPCTL-REENABLE-LOG",
            f"late irq_en: rises_to_sep_irq={first} ({near} {LATE_FIRST_RISES} rises; "
            f"ceiling {LATE_CEILING_RISES}); after CTRL=irq_en then enable|irq_en: "
            f"rises_to_sep_irq={again}; hold lasted {held} rises (observe-and-log, "
            "not specified, measured)",
        )

    async def _toggle_phase(self, rng: random.Random, seed: str) -> None:
        await self._ctrl("S5_ARM", HANG_DET_ARMED)
        st = await self._begin("toggle")
        wait = "S5 toggle start wait"
        ceiling = TOGGLE_START_RISE + START_SLACK_RISES
        for _ in range(ceiling):
            if st.rises >= TOGGLE_START_RISE:
                break
            await RisingEdge(cocotb.top.clk_smc_i)
            self._waits[wait] = (ceiling, f"rises since AR handshake={st.rises}")
        assert st.rises >= TOGGLE_START_RISE, f"{wait}: {st.rises} rises, want {TOGGLE_START_RISE}"
        rows, gated, live = [], 0, 0
        for i in range(TOGGLES):
            value = (
                HANG_DET_ARMED
                if i == 0
                else rng.choice((0, HANG_DET_ENABLE, HANG_DET_IRQ_EN, HANG_DET_ARMED))
            )
            start = st.rises
            was_live = st.sep_now
            await self._jtag(f"S5_TOGGLE{i}_W", HANG_DET_SEP_AXI_CTRL, SmcSysAxiOp.WRITE, value)
            rdata = await self._jtag(f"S5_TOGGLE{i}_RB", HANG_DET_SEP_AXI_CTRL, SmcSysAxiOp.READ)
            assert rdata & ~HANG_DET_IRQ == value, (
                f"S5 toggle {i}: readback 0x{rdata:x} != 0x{value:x}"
            )
            await RisingEdge(cocotb.top.clk_smc_i)
            sep, raw = self._sample(f"S5 toggle {i}")
            if value != HANG_DET_ARMED:
                gated += 1
                live += was_live
                assert sep == 0 and raw == 0, (
                    f"S5 toggle {i}: CTRL=0x{value:x} sep={sep} raw286={raw}, want 0/0"
                )
            rows.append(
                f"#{i} ctrl=0x{value:x} start_rise={start} sep_before_write={was_live} "
                f"sep={sep} raw286={raw}"
            )
        assert live, f"S5: no gated toggle was applied while the irq was live ({rows})"
        held = await self._end(st, "toggle")
        await self._ctrl("S5_CTRL_OFF", 0)
        cleared = await self._await_sep_low("S5 cleanup")
        self._mark_step("S5")
        cocotb.log.info(
            "LIFECYCLE CHK-DROPCTL-TOGGLE-GATING set: enable or irq_en toggled on a live stall"
        )
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-TOGGLE-GATING observed: sep irq after each readback")
        cocotb.log.info("LIFECYCLE CHK-DROPCTL-TOGGLE-GATING cleared: CTRL written 0")
        cocotb.log.info(
            "LIFECYCLE CHK-DROPCTL-TOGGLE-GATING checked_cleared: sep irq 0 after %d rises", cleared
        )
        self._log_chk(
            "CHK-DROPCTL-TOGGLE-GATING",
            f"{TOGGLES} toggles run, {gated} with enable or irq_en clear ({live} "
            "applied with the irq live) read sep irq and raw286 0 at the first rise "
            "after the readback; every readback matched "
            "the written CTRL",
        )
        self._log_chk(
            "CHK-DROPCTL-TOGGLE-LOG",
            f"seed={seed} hold {held} rises; "
            + "; ".join(rows)
            + " (observe-and-log, not specified, measured)",
        )

    async def _both_causes_phase(self) -> None:
        st = await self._begin("both")
        await self._ctrl("S6_ARM", HANG_DET_ARMED)
        await self._await_high("S6 timeout")
        await self._ctrl("S6_TEST_SET", HANG_DET_ARMED | HANG_DET_IRQ_TEST)
        await self._ctrl("S6_TEST_CLEAR_STALL", HANG_DET_ARMED)
        await RisingEdge(cocotb.top.clk_smc_i)
        stalled = self._sample("S6 stall persists")
        self._assert_held(st, "S6")
        await self._ctrl("S6_TEST_SET_AGAIN", HANG_DET_ARMED | HANG_DET_IRQ_TEST)
        held = await self._end(st, "both")
        await RisingEdge(cocotb.top.clk_smc_i)
        released = self._sample("S6 released with irq_test")
        await self._ctrl("S6_TEST_CLEAR", HANG_DET_ARMED)
        await RisingEdge(cocotb.top.clk_smc_i)
        final = self._sample("S6 irq_test cleared")
        self._mark_step("S6")
        self._log_chk(
            "CHK-DROPCTL-BOTH-CAUSES-LOG",
            f"irq_test cleared with the stall persisting: sep={stalled[0]} "
            f"raw286={stalled[1]}; stall released with irq_test set: sep={released[0]} "
            f"raw286={released[1]}; irq_test cleared: sep={final[0]} raw286={final[1]}; "
            f"hold {held} rises (observe-and-log, not specified, measured)",
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            "tb_sep_axi_r_hold",
            "tb_axi_hang_irq_sep",
            "tb_cpu_interrupts",
            "s_axi_arvalid",
            "s_axi_arready",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        self._hold(0, "idle")
        seed = os.environ.get("RANDOM_SEED", "1")
        cocotb.log.info("SEED RANDOM_SEED=%s", seed)
        rng = random.Random(int(seed))

        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self.csr_write("HANG_SEP_THR", HANG_DET_SEP_AXI_TIMEOUT, THRESHOLD)
        thr = await self.csr_read("HANG_SEP_THR_RB", HANG_DET_SEP_AXI_TIMEOUT, expected=THRESHOLD)
        assert (thr & HANG_DET_THR_VALUE) == THRESHOLD, f"threshold readback 0x{thr:x}"
        await self.csr_write("HANG_SEP_ARM", HANG_DET_SEP_AXI_CTRL, HANG_DET_ARMED)
        await self.csr_read("HANG_SEP_ARM_RB", HANG_DET_SEP_AXI_CTRL, expected=HANG_DET_ARMED)
        await RisingEdge(dut.clk_smc_i)
        assert self._sample("baseline") == (0, 0), "baseline sep irq or raw286 not 0"
        self.phases += 1
        self._mark_step("S1")

        st = await self._begin("drop")
        await self._drop_phase(st)
        self.phases += 3
        await self._toggle_phase(rng, seed)
        self.phases += 1
        await self._both_causes_phase()
        self.phases += 1

        self._hold(0, "cleanup")
        await self.csr_write("HANG_SEP_CTRL_CLEANUP", HANG_DET_SEP_AXI_CTRL, 0)
        await self.csr_write("HANG_SEP_THR_CLEANUP", HANG_DET_SEP_AXI_TIMEOUT, THRESHOLD_LARGE)
        await self._await_sep_low("cleanup")
        self.phases += 1
        self._mark_step("S7")

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
        assert self._reads == 3, f"{self._reads} SEP_IN stalls started, want 3"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence ARM<IRQ-EN-CLEAR<GATE-HOLD<ENABLE-CLEAR<LATE-IRQ-EN<TOGGLES<"
            "IRQ-TEST-PLUS-TIMEOUT<CLEANUP; checker lines %s; stamps %s",
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
            f"JTAG AXI CTRL reads x{self._jtag_reads} and writes x{self._jtag_writes} "
            "(AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self._jtag_reads} reads, {self._jtag_writes} writes completed",
            ),
        }
        waits = "; ".join(
            f"{name} bound={bound} last[{last}]"
            for name, (bound, last) in {**subs, **self._waits}.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry "
            "with the last sampled values; %s",
            waits,
        )
