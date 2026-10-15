# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang detector irq_test OR over detector pairs, drop orders and threshold zero.

Spec sources: HANG_DET_CTRL and HANG_DET_TIMEOUT_THRESHOLD in smc_base_config.rdl; interrupts.adoc.
"""

from __future__ import annotations

import itertools
import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_DATA_ACCEL_TIMEOUT,
    HANG_DET_FIRE,
    HANG_DET_IRQ,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_SYS_AXI_TIMEOUT,
    HANG_DET_THR_VALUE,
)
from .smc_csr_seq_utils import SmcCsrSeq

OR_BIT = 286
LOW_BIT = 285
HIGH_BIT = 287
CEILING_RISES = 64
HOLD_RISES = 64
ORDER_HOLD_RISES = 16
THRESHOLD_CLEANUP = 0x1000
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
DETECTORS = (
    ("SYS", HANG_DET_SYS_AXI_CTRL, HANG_DET_SYS_AXI_TIMEOUT),
    ("SEP", HANG_DET_SEP_AXI_CTRL, HANG_DET_SEP_AXI_TIMEOUT),
    ("DATA", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_DATA_ACCEL_TIMEOUT),
)
_NETS = ("tb_axi_hang_irq_sys", "tb_axi_hang_irq_sep", "tb_axi_hang_irq_data")
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = (
    "CHK-HANGOR-PAIRS",
    "CHK-HANGOR-ORDERS",
    "CHK-HANGOR-NEIGHBOURS",
    "CHK-HANGOR-THR0-TEST",
)
_CHECK_STEP = ("S2", "S3", "S4", "S5")


class smc_hang_irq_or_matrix_test_seq(SmcCsrSeq):
    """Fire hang detector irq_test in pairs, all orders and with threshold zero."""

    def __init__(self, name: str = "smc_hang_irq_or_matrix_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._baseline = (0, 0)
        self._monitor_on = False
        self._monitor_samples = 0
        self._neighbour_errors: list[str] = []
        self._raw_seen: set[int] = set()

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _resolved(sig, label: str) -> int:
        assert sig.value.is_resolvable, f"{label}: {sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    def _sample(self, label: str) -> tuple[tuple[int, int, int], int]:
        """Return ((sys, sep, data) nets, raw bit 286); check the neighbours while monitoring."""
        dut = cocotb.top
        nets = tuple(self._resolved(getattr(dut, n), label) & 1 for n in _NETS)
        vec = self._resolved(dut.tb_cpu_interrupts, label)
        raw = vec >> OR_BIT & 1
        if self._monitor_on:
            self._monitor_samples += 1
            got = (vec >> LOW_BIT & 1, vec >> HIGH_BIT & 1)
            if got != self._baseline:
                self._neighbour_errors.append(
                    f"{label}: raw285/287={got} want {self._baseline} at {get_sim_time('ps')} ps"
                )
        return nets, raw

    async def _monitor(self) -> None:
        while self._monitor_on:
            await RisingEdge(cocotb.top.clk_smc_i)
            if self._monitor_on:
                self._sample("monitor")

    async def _await_state(self, wait: str, nets: tuple[int, ...], raw: int) -> int:
        """Wait until the three nets and raw 286 equal the expected state; return the rises."""
        self._waits[wait] = (CEILING_RISES, "no rise yet")
        for n in range(CEILING_RISES + 1):
            got_nets, got_raw = self._sample(wait)
            self._waits[wait] = (CEILING_RISES, f"nets={got_nets} raw286={got_raw} after {n}")
            if got_nets == nets and got_raw == raw:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{wait}: nets={got_nets} raw286={got_raw}, want nets={nets} raw286={raw} "
            f"within {CEILING_RISES} rises"
        )

    async def _hold_raw(self, wait: str, rises: int, raw: int) -> None:
        """Require raw bit 286 to equal raw at each of rises consecutive rises."""
        self._waits[wait] = (rises, "no rise yet")
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            _, got = self._sample(wait)
            self._waits[wait] = (rises, f"raw286={got} rise {n}")
            assert got == raw, f"{wait}: raw286={got} at rise {n}, want {raw}"

    async def _read_irqs(self, tag: str, want: tuple[int, ...]) -> tuple[int, ...]:
        got = []
        for (name, ctrl, _), exp in zip(DETECTORS, want):
            rdata = await self.csr_read(f"HANG_{name}_CTRL_{tag}", ctrl)
            bit = int(bool(rdata & HANG_DET_IRQ))
            got.append(bit)
            assert bit == exp, f"{tag}: {name} CTRL=0x{rdata:x} irq={bit}, want {exp}"
        return tuple(got)

    async def _fire(self, idx: tuple[int, ...]) -> None:
        for i in idx:
            await self.csr_write(f"HANG_{DETECTORS[i][0]}_FIRE", DETECTORS[i][1], HANG_DET_FIRE)

    async def _drop_sequence(self, tag: str, order: tuple[int, ...], hold: int) -> str:
        """Clear the detectors in order, checking raw 286 and every CTRL.irq after each."""
        live = set(order)
        trail = []
        for i in order:
            await self.csr_write(f"HANG_{DETECTORS[i][0]}_CLR_{tag}", DETECTORS[i][1], 0)
            live.discard(i)
            want = tuple(int(k in live) for k in range(3))
            if live:
                await self._hold_raw(f"{tag} raw286 hold while detector remains", hold, 1)
                await self._read_irqs(f"{tag}_{DETECTORS[i][0]}", want)
                await self._await_state(f"{tag} nets follow clear", want, 1)
            else:
                n = await self._await_state(f"{tag} raw286 clear wait", want, 0)
                await self._read_irqs(f"{tag}_LAST", want)
                trail.append(f"{DETECTORS[i][0]}:raw0@{n}")
                continue
            trail.append(f"{DETECTORS[i][0]}:raw1,irq={want}")
        return ",".join(trail)

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (*_NETS, "tb_cpu_interrupts"):
            assert hasattr(dut, sig), f"{sig} missing"
        cocotb.log.info(
            "SEED RANDOM_SEED=%s; no tb_top pin is driven", os.environ.get("RANDOM_SEED", "1")
        )
        await RisingEdge(dut.clk_smc_i)
        vec = self._resolved(dut.tb_cpu_interrupts, "baseline")
        self._baseline = (vec >> LOW_BIT & 1, vec >> HIGH_BIT & 1)
        nets, raw = self._sample("baseline")
        assert (vec >> OR_BIT & 1, vec >> LOW_BIT & 1, vec >> HIGH_BIT & 1) == (0, 0, 0), (
            f"baseline raw286/285/287 vector bits not 0: 0x{vec:x}"
        )
        assert nets == (0, 0, 0) and raw == 0, f"baseline nets={nets} raw286={raw}"
        await self._read_irqs("BASE", (0, 0, 0))
        cocotb.log.info(
            "BASELINE raw285=%d raw286=%d raw287=%d nets=%s CTRL.irq=0,0,0",
            *self._baseline[:1],
            raw,
            self._baseline[1],
            nets,
        )
        self.phases += 1
        self._mark_step("S1")

        self._monitor_on = True
        monitor = cocotb.start_soon(self._monitor())
        trail = []
        for pair in itertools.combinations(range(3), 2):
            tag = "PAIR_" + "_".join(DETECTORS[i][0] for i in pair)
            want = tuple(int(k in pair) for k in range(3))
            await self._fire(pair)
            n = await self._await_state(f"{tag} raw286 rise wait", want, 1)
            await self._read_irqs(tag, want)
            first, second = pair
            await self.csr_write(f"{tag}_CLR1", DETECTORS[first][1], 0)
            want1 = tuple(int(k == second) for k in range(3))
            await self._hold_raw(f"{tag} raw286 hold after first clear", HOLD_RISES, 1)
            await self._read_irqs(f"{tag}_1", want1)
            await self.csr_write(f"{tag}_CLR2", DETECTORS[second][1], 0)
            m = await self._await_state(f"{tag} raw286 clear wait", (0, 0, 0), 0)
            await self._read_irqs(f"{tag}_2", (0, 0, 0))
            trail.append(f"{tag}:rise@{n},clear@{m}")
        self.phases += 1
        self._mark_step("S2")
        self._log_legs(
            "CHK-HANGOR-PAIRS",
            "two irq_test fires per pair",
            "tb_cpu_interrupts[286], three nets, three CTRL.irq",
            "the two CTRLs cleared one at a time",
            "raw286 and all CTRL.irq read 0",
        )
        self._log_chk(
            "CHK-HANGOR-PAIRS",
            f"3 pairs: raw286=1 while either asserted, held {HOLD_RISES} rises after "
            f"the first clear, 0 after both; CTRL.irq followed each detector; "
            f"{';'.join(trail)}",
        )

        trail = []
        for order in itertools.permutations(range(3)):
            tag = "ORD_" + "".join(DETECTORS[i][0][1] for i in order)
            await self._fire(range(3))
            n = await self._await_state(f"{tag} raw286 rise wait", (1, 1, 1), 1)
            await self._read_irqs(f"{tag}_ALL", (1, 1, 1))
            steps = await self._drop_sequence(tag, order, ORDER_HOLD_RISES)
            trail.append(f"{'>'.join(DETECTORS[i][0] for i in order)}[rise@{n};{steps}]")
        self.phases += 1
        self._mark_step("S3")
        self._log_legs(
            "CHK-HANGOR-ORDERS",
            "three irq_test fires per order",
            "tb_cpu_interrupts[286], three nets, three CTRL.irq",
            "CTRLs cleared in each of 6 orders",
            "raw286 and all CTRL.irq read 0",
        )
        self._log_chk(
            "CHK-HANGOR-ORDERS",
            f"6 orders: raw286 equals any-detector-remaining after each clear and each "
            f"CTRL.irq equals its own detector; {' '.join(trail)}",
        )

        self._monitor_on = False
        await monitor
        assert self._monitor_samples > 0, "neighbour monitor took no samples"
        assert not self._neighbour_errors, f"neighbour deviations: {self._neighbour_errors[:4]}"
        self.phases += 1
        self._mark_step("S4")
        self._log_chk(
            "CHK-HANGOR-NEIGHBOURS",
            f"raw285/287={self._baseline} (baseline) at each of {self._monitor_samples} "
            f"sampled rises across S2 and S3 while raw286 toggled",
        )

        trail = []
        for i, (name, ctrl, thr) in enumerate(DETECTORS):
            tag = f"THR0_{name}"
            want = tuple(int(k == i) for k in range(3))
            await self.csr_write(f"{tag}_THR0", thr, 0)
            thr_rb = await self.csr_read(f"{tag}_THR0_RB", thr, expected=0)
            await self.csr_write(f"{tag}_FIRE", ctrl, HANG_DET_FIRE)
            n = await self._await_state(f"{tag} raw286 rise wait", want, 1)
            await self._read_irqs(tag, want)
            await self.csr_write(f"{tag}_CLR", ctrl, 0)
            m = await self._await_state(f"{tag} raw286 clear wait", (0, 0, 0), 0)
            await self._read_irqs(f"{tag}_CLR", (0, 0, 0))
            await self.csr_write(f"{tag}_THR_RESTORE", thr, THRESHOLD_CLEANUP)
            back = await self.csr_read(f"{tag}_THR_RESTORE_RB", thr, expected=THRESHOLD_CLEANUP)
            assert back & HANG_DET_THR_VALUE == THRESHOLD_CLEANUP, f"{name} threshold 0x{back:x}"
            trail.append(f"{name}:thr=0x{thr_rb:x},net+raw286+irq=1@{n},cleared@{m}")
        self.phases += 1
        self._mark_step("S5")
        self._log_legs(
            "CHK-HANGOR-THR0-TEST",
            "threshold 0 then irq_test fire per detector",
            "own detector net, raw286 and CTRL.irq",
            "CTRL written 0",
            "net, raw286 and CTRL.irq read 0",
        )
        self._log_chk("CHK-HANGOR-THR0-TEST", f"3 detectors, no stall: {';'.join(trail)}")

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
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE<PAIRS<ORDERS<NEIGHBOURS<THRESHOLD-ZERO; "
            "checker lines %s; stamps %s",
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
            f"SEP_IN csr_write/csr_read HANG_DET_* x{self.accesses} accesses "
            "(AssertionError on expiry)": (
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
