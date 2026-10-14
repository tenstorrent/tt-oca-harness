# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang detector register field access, isolation and SMC_ATTRIBUTES interrupt counts.

Spec sources: smc_base_config.rdl HANG_DET_CTRL and TIMEOUT_THRESHOLD, cpu_ctrl.rdl SMC_ATTRIBUTES.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_DATA_ACCEL_TIMEOUT,
    HANG_DET_ENABLE,
    HANG_DET_IRQ,
    HANG_DET_IRQ_EN,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_SYS_AXI_TIMEOUT,
    HANG_DET_THR_VALUE,
    cpu_ctrl_u32,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
CTRL_DEFINED = HANG_DET_ENABLE | HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST | HANG_DET_IRQ
FIELDS = (("enable", HANG_DET_ENABLE), ("irq_en", HANG_DET_IRQ_EN), ("irq_test", HANG_DET_IRQ_TEST))
DETECTORS = (
    ("SYS_AXI", HANG_DET_SYS_AXI_CTRL, HANG_DET_SYS_AXI_TIMEOUT),
    ("SEP_AXI", HANG_DET_SEP_AXI_CTRL, HANG_DET_SEP_AXI_TIMEOUT),
    ("DATA_ACCEL", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_DATA_ACCEL_TIMEOUT),
)
THRESHOLDS = (0, 1, 0x1000, 0xFFFFF)
ISO_CTRL = HANG_DET_ENABLE | HANG_DET_IRQ_EN
ISO_THR = 0x123
SMC_ATTRIBUTES = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
NUM_EXT_BM = cpu_ctrl_u32("CPU_CTRL__SMC_ATTRIBUTES__NUM_EXT_INTERRUPTS_bm")
NUM_EXT_BP = cpu_ctrl_u32("CPU_CTRL__SMC_ATTRIBUTES__NUM_EXT_INTERRUPTS_bp")
NUM_CPU_BM = cpu_ctrl_u32("CPU_CTRL__SMC_ATTRIBUTES__NUM_CPU_INTERRUPTS_bm")
NUM_CPU_BP = cpu_ctrl_u32("CPU_CTRL__SMC_ATTRIBUTES__NUM_CPU_INTERRUPTS_bp")
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_CHECKERS = (
    "CHK-HANGREG-CTRL-RW",
    "CHK-HANGREG-IRQ-RO",
    "CHK-HANGREG-THR-RANGE",
    "CHK-HANGREG-ISOLATION",
    "CHK-ATTR-COUNTS-LOG",
)
_CHECK_STEP = ("S2", "S3", "S4", "S5", "S6")


class smc_irq_csr_readback_test_seq(SmcCsrSeq):
    """Write and read the hang detector registers over SEP_IN and log SMC_ATTRIBUTES."""

    def __init__(self, name: str = "smc_irq_csr_readback_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._saved: dict[str, tuple[int, int]] = {}

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))
        self.phases += 1

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _log_legs(chk: str, set_text: str, observed: str, cleared: str, checked: str) -> None:
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def _ctrl(self, tag: str, addr: int) -> int:
        return await self.csr_read(f"CTRL_{tag}", addr) & CTRL_DEFINED

    async def _thr(self, tag: str, addr: int) -> int:
        return await self.csr_read(f"THR_{tag}", addr) & HANG_DET_THR_VALUE

    async def _write_ctrl_expect(self, tag: str, addr: int, wr: int, want: int) -> int:
        await self.csr_write(f"CTRL_{tag}", addr, wr)
        got = await self._ctrl(tag, addr)
        assert got == want, f"{tag}: CTRL wrote 0x{wr:x}, read 0x{got:x}, want 0x{want:x}"
        return got

    async def _clear_ctrl(self, tag: str, addr: int) -> None:
        await self.csr_write(f"CTRL_{tag}_CLR", addr, 0)
        got = await self._ctrl(f"{tag}_CLR", addr)
        assert got == 0, f"{tag}: CTRL defined bits 0x{got:x} after write 0"

    async def _read_all(self, tag: str) -> dict[str, tuple[int, int]]:
        return {
            n: (await self._ctrl(f"{tag}_{n}", c), await self._thr(f"{tag}_{n}", t))
            for n, c, t in DETECTORS
        }

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        cocotb.log.info("SEED RANDOM_SEED=%s", os.environ.get("RANDOM_SEED", "1"))
        for n, c, t in DETECTORS:
            self._saved[n] = (
                await self.csr_read(f"SAVE_CTRL_{n}", c),
                await self.csr_read(f"SAVE_THR_{n}", t),
            )
        cocotb.log.info("SAVED %s", {n: (hex(a), hex(b)) for n, (a, b) in self._saved.items()})
        self._mark_step("S1")

        rw = []
        for n, c, _ in DETECTORS:
            for fname, bm in FIELDS:
                got = await self._write_ctrl_expect(f"RW_{n}_{fname}", c, bm, bm)
                assert got & HANG_DET_IRQ == 0, f"{n}: irq reads 1 with {fname} alone"
                rw.append(f"{n}.{fname}=0x{got:x}")
                await self._clear_ctrl(f"RW_{n}_{fname}", c)
        self._mark_step("S2")
        self._log_legs(
            "CHK-HANGREG-CTRL-RW",
            "CTRL field written 1",
            "CTRL readback over SEP_IN",
            "CTRL written 0",
            "CTRL defined bits read 0",
        )
        self._log_chk(
            "CHK-HANGREG-CTRL-RW",
            f"9 field writes read back as written with irq=0, reserved masked: "
            f"{' '.join(rw)}; each cleared and read 0",
        )

        ro = []
        for n, c, _ in DETECTORS:
            got = await self._write_ctrl_expect(f"RO_{n}", c, HANG_DET_IRQ, 0)
            ro.append(f"{n}=0x{got:x}")
            await self._clear_ctrl(f"RO_{n}", c)
        self._mark_step("S3")
        self._log_legs(
            "CHK-HANGREG-IRQ-RO",
            "irq bit written 1",
            "CTRL readback",
            "CTRL written 0",
            "defined bits read 0",
        )
        self._log_chk(
            "CHK-HANGREG-IRQ-RO",
            f"CTRL written with bit 12 alone reads 0 on all defined bits: {' '.join(ro)}",
        )

        thr = []
        for n, c, t in DETECTORS:
            await self.csr_write(f"CTRL_{n}_ZERO", c, 0)
            for v in THRESHOLDS:
                await self.csr_write(f"THR_{n}_{v:x}", t, v)
                got = await self._thr(f"{n}_{v:x}", t)
                assert got == v, f"{n}: threshold wrote 0x{v:x}, bits 19:0 read 0x{got:x}"
                thr.append(f"{n}[0x{v:x}]=0x{got:x}")
        self._mark_step("S4")
        self._log_chk(
            "CHK-HANGREG-THR-RANGE",
            f"12 threshold writes read back equal over bits 19:0: {' '.join(thr)}",
        )

        iso = []
        for w, wc, wt in DETECTORS:
            before = await self._read_all(f"ISO_{w}_PRE")
            await self.csr_write(f"CTRL_{w}_ISO", wc, ISO_CTRL)
            await self.csr_write(f"THR_{w}_ISO", wt, ISO_THR)
            after = await self._read_all(f"ISO_{w}_POST")
            assert after[w] == (ISO_CTRL, ISO_THR), f"{w}: written detector reads {after[w]}"
            for n, _, _ in DETECTORS:
                if n != w:
                    assert after[n] == before[n], f"{w} write changed {n}: {before[n]}->{after[n]}"
            iso.append(f"{w}: others unchanged {[(n, after[n]) for n in after if n != w]}")
            await self.csr_write(f"CTRL_{w}_ISO_OFF", wc, 0)
            await self.csr_write(f"THR_{w}_ISO_OFF", wt, self._saved[w][1])
            end = await self._read_all(f"ISO_{w}_END")
            want_w = (0, self._saved[w][1] & HANG_DET_THR_VALUE)
            assert end[w] == want_w, f"{w}: restore read {end[w]}, want {want_w}"
            assert {n: end[n] for n in end if n != w} == {n: before[n] for n in before if n != w}
        self._mark_step("S5")
        self._log_legs(
            "CHK-HANGREG-ISOLATION",
            "one detector written with distinct values",
            "all six registers read",
            "written registers restored",
            "all six read the saved values",
        )
        self._log_chk(
            "CHK-HANGREG-ISOLATION",
            f"3 written-detector choices, six registers read each time: {'; '.join(iso)}",
        )

        attrs = await self.csr_read("SMC_ATTRIBUTES", SMC_ATTRIBUTES, length=8)
        ext = (attrs & NUM_EXT_BM) >> NUM_EXT_BP
        cpu = (attrs & NUM_CPU_BM) >> NUM_CPU_BP
        self._mark_step("S6")
        self._log_chk(
            "CHK-ATTR-COUNTS-LOG",
            f"SMC_ATTRIBUTES=0x{attrs:x} num_ext_interrupts={ext} "
            f"num_cpu_interrupts={cpu} candidate counts 256 and 328",
        )

        for n, c, t in DETECTORS:
            await self.csr_write(f"RESTORE_CTRL_{n}", c, 0)
            await self.csr_write(f"RESTORE_THR_{n}", t, self._saved[n][1])
        for n, c, t in DETECTORS:
            got_c, got_t = await self._ctrl(f"RESTORE_{n}", c), await self._thr(f"RESTORE_{n}", t)
            assert got_c == 0, f"{n}: CTRL defined bits 0x{got_c:x} after restore"
            assert got_t == self._saved[n][1] & HANG_DET_THR_VALUE, f"{n}: threshold 0x{got_t:x}"
        self._mark_step("S7")
        self._log_legs(
            "CHK-HANGREG-THR-RANGE",
            "threshold value written",
            "threshold readback",
            "threshold restored in S7",
            "saved value read back",
        )

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
            "CHK-NONVAC: ordered fence SAVE<FIELD-RW<IRQ-RO<THRESHOLD-RANGE<ISOLATION<"
            "ATTRIBUTES<RESTORE; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        waits = [
            ("fuse sense wait tb_fuse_sense_done", self._level("tb_fuse_sense_done")),
            ("fuse sense wait tb_fuse_reset_n", self._level("tb_fuse_reset_n")),
            ("fuse sense wait tb_rst_warm_smc_clk_n", self._level("tb_rst_warm_smc_clk_n")),
        ]
        parts = [f"{n} bound={FUSE_SENSE_RISES} rises last[level={s}]" for n, s in waits]
        parts.append(
            "SEP_IN csr_read/csr_write of the six hang detector registers and SMC_ATTRIBUTES "
            f"x{self.accesses} accesses bound={AXI_TIMEOUT_NS} ns last[{self.accesses} completed]"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: no own wait loops; every bounded wait raises AssertionError on "
            "expiry; %s",
            "; ".join(parts),
        )
