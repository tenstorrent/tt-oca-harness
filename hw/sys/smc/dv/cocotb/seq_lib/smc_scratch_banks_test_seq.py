# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratch bank reset value and independent read/write of the sixteen scratch registers.

Contract SMC_RESET_048, anchor smc_scratch_banks_test.
Allocated scenarios: RST-SCRATCH.S1, RST-SCRATCH.S2.
Spec sources: hw/sys/smc/regs/blocks/scratch/scratch.rdl,
hw/sys/smc/regs/blocks/misc_wrap/misc_wrap.rdl.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
BANK_BASES = (("cold", SCRATCH_COLD_0), ("cold_warm", SCRATCH_COLD_WARM_0))
REGS_PER_BANK = 8
PATTERN_BASE = 0xA5000000
MASK32 = 0xFFFFFFFF
ACCESS_FLOOR = 16 + 2 * 16 * 17
STEP_ORDER = ("S1", "S2", "S3")
CHK_ORDER = ("CHK-SCRATCH-RESET-0", "CHK-SCRATCH-INDEPENDENT-RW")
CHK_STEP = {"CHK-SCRATCH-RESET-0": "S2", "CHK-SCRATCH-INDEPENDENT-RW": "S3"}


class smc_scratch_banks_test_seq(SmcCsrSeq):
    """Reset value and per-register independence of scratch_cold and scratch_cold_warm."""

    def __init__(self, name: str = "smc_scratch_banks_test_seq") -> None:
        super().__init__(name)
        self._steps: list[tuple[str, int]] = []
        self._chk_lines: list[tuple[str, int]] = []
        self._shadow: dict[tuple[str, int], int] = {}
        self._observed: dict[tuple[str, int], int] = {}

    def _mark_step(self, step_id: str) -> None:
        self._steps.append((step_id, int(get_sim_time("ps"))))

    def _emit_chk(self, chk_id: str, text: str) -> None:
        self._chk_lines.append((chk_id, int(get_sim_time("ps"))))
        cocotb.log.info("%s: %s", chk_id, text)

    def _addr(self, bank: str, n: int) -> int:
        return dict(BANK_BASES)[bank] + 4 * n

    async def _read_all(self, tag: str) -> int:
        reads = 0
        for bank, _base in BANK_BASES:
            for n in range(REGS_PER_BANK):
                got = await self.csr_read(
                    f"{tag}_{bank}_{n}",
                    self._addr(bank, n),
                    expected=self._shadow[(bank, n)],
                )
                assert got == self._shadow[(bank, n)], (
                    f"{tag} {bank}[{n}] read 0x{got:08x}, want 0x{self._shadow[(bank, n)]:08x}"
                )
                self._observed[(bank, n)] = got
                reads += 1
        return reads

    def _bank_values(self, bank: str) -> list[str]:
        return [f"0x{self._observed[(bank, n)]:08x}" for n in range(REGS_PER_BANK)]

    async def _write_sweep(self, tag: str, pattern) -> tuple[int, int]:
        writes = reads = 0
        for bank, _base in BANK_BASES:
            for n in range(REGS_PER_BANK):
                value = pattern(n)
                await self.csr_write(f"{tag}_{bank}_{n}", self._addr(bank, n), value)
                self._shadow[(bank, n)] = value
                writes += 1
                reads += await self._read_all(f"{tag}_RB_{bank}_{n}")
        return writes, reads

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        self._mark_step("S1")

        for bank, _base in BANK_BASES:
            for n in range(REGS_PER_BANK):
                self._shadow[(bank, n)] = 0
        await self._read_all("RESET")
        self._mark_step("S2")
        cold = " ".join(self._bank_values("cold"))
        warm = " ".join(self._bank_values("cold_warm"))
        self._emit_chk(
            "CHK-SCRATCH-RESET-0",
            f"scratch_cold[0..7]={cold} scratch_cold_warm[0..7]={warm} "
            "all 0x00000000 after the bring-up cold reset",
        )

        writes = reads = 0
        w, r = await self._write_sweep("TRUE", lambda n: PATTERN_BASE + n)
        writes += w
        reads += r
        w, r = await self._write_sweep("COMPL", lambda n: (~(PATTERN_BASE + n)) & MASK32)
        writes += w
        reads += r
        self._mark_step("S3")
        self._emit_chk(
            "CHK-SCRATCH-INDEPENDENT-RW",
            f"{writes // 2} writes of 0xA5000000+n then {writes // 2} writes of ~(0xA5000000+n); "
            f"after each write all 16 registers read their shadow ({reads} reads, {reads} "
            f"compares); final scratch_cold={self._bank_values('cold')} "
            f"scratch_cold_warm={self._bank_values('cold_warm')}",
        )

        for bank, _base in BANK_BASES:
            for n in range(REGS_PER_BANK):
                await self.csr_restore(f"{bank}_{n}", self._addr(bank, n), 0)

        self._assert_fence()

    def _assert_fence(self) -> None:
        ids = tuple(s for s, _ in self._steps)
        assert ids == STEP_ORDER, f"step ids {ids} != contract order {STEP_ORDER}"
        stamps = [t for _, t in self._steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), (
            f"step stamps not increasing: {stamps}"
        )
        chk_ids = tuple(c for c, _ in self._chk_lines)
        assert chk_ids == CHK_ORDER, f"checker lines {chk_ids} != contract order {CHK_ORDER}"
        step_stamp = dict(self._steps)
        for chk_id, t in self._chk_lines:
            stamp = step_stamp[CHK_STEP[chk_id]]
            assert t >= stamp, f"{chk_id} printed at {t} ps before its step stamp {stamp} ps"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s<PASS; checker lines %s; stamps %s",
            "<".join(STEP_ORDER),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._steps),
        )
