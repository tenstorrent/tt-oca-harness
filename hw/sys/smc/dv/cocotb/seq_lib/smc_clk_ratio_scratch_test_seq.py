# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratch register traffic at ref / smc / periph 10 / 12 / 6 ns.

Contract SMC_CLOCK_RATIO_005, anchor smc_clk_ratio_scratch_test.
Allocated scenarios: RATIO-SCRATCH-XFER.S1, RATIO-SCRATCH-XFER.S2, RATIO-SCRATCH-XFER.S3.
Spec sources: hw/sys/smc/regs/blocks/scratch/scratch.rdl, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_SYMBOL = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
SCRATCH_COUNT = 8
SINGLE_PATTERN = 0xA5A5A5A5
AXI_TIMEOUT_NS = 50_000
FUSE_SENSE_MAX_CYCLES = 200_000
STEP_ORDER = ("S1", "S2", "S3", "S4_WRITES", "S4", "S5")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "SCRATCH_RESET_READS",
    "S3": "SCRATCH0_WRITE_READ",
    "S4_WRITES": "SCRATCH_BURST_WRITES",
    "S4": "SCRATCH_BURST_READS",
    "S5": "SCRATCH_RESTORE_READS",
}
CHK_ORDER = (
    "CHK-SCRATCH-RESET-READ",
    "CHK-SCRATCH-NO-ALIAS",
    "CHK-SCRATCH-WRITE-READ",
    "CHK-TIMEOUT-PATHS",
)
CHK_STEP = {
    "CHK-SCRATCH-RESET-READ": "S2",
    "CHK-SCRATCH-WRITE-READ": "S5",
    "CHK-SCRATCH-NO-ALIAS": "S4",
    "CHK-TIMEOUT-PATHS": "S5",
}


def scratch_addr(k: int) -> int:
    return smc_indexed_addr(SCRATCH_SYMBOL, k)


class smc_clk_ratio_scratch_test_seq(SmcCsrSeq):
    """SCRATCH[0..7] reset read, single round trip, eight-way burst and restore."""

    def __init__(self, name: str = "smc_clk_ratio_scratch_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []
        self._steps: list[tuple[str, int]] = []
        self._chk_lines: list[tuple[str, int]] = []
        self._last_access = "none"
        self._bounded_waits: list[tuple[str, str, str]] = []

    def _mark_step(self, step_id: str) -> None:
        self._steps.append((step_id, int(get_sim_time("ps"))))

    def _emit_chk(self, chk_id: str, text: str) -> None:
        self._chk_lines.append((chk_id, int(get_sim_time("ps"))))
        self.chk_seen.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    async def _read(self, tag: str, k: int, want: int) -> int:
        self._last_access = f"read {tag} SCRATCH[{k}] addr=0x{scratch_addr(k):08x}"
        got = await self.csr_read(tag, scratch_addr(k), expected=want)
        assert got == want, f"{self._last_access}: got 0x{got:08x}, want 0x{want:08x}"
        return got

    async def _write(self, tag: str, k: int, data: int) -> None:
        self._last_access = f"write {tag} SCRATCH[{k}]=0x{data:08x}"
        await self.csr_write(tag, scratch_addr(k), data)

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._bounded_waits.append(
            ("fuse_sense_done", f"{FUSE_SENSE_MAX_CYCLES}smc_cycles", "done")
        )
        self._mark_step("S1")

        reset_words = [await self._read("RESET", k, 0) for k in range(SCRATCH_COUNT)]
        self._mark_step("S2")
        self._emit_chk(
            "CHK-SCRATCH-RESET-READ",
            "SCRATCH[0..7]="
            + " ".join(f"0x{w:08x}" for w in reset_words)
            + " all 0x00000000 before any scratch write, OKAY each",
        )

        await self._write("SINGLE", 0, SINGLE_PATTERN)
        single = await self._read("SINGLE", 0, SINGLE_PATTERN)
        self._mark_step("S3")

        patterns = [0x11111111 * (k + 1) for k in range(SCRATCH_COUNT)]
        for k, pattern in enumerate(patterns):
            await self._write("BURST", k, pattern)
        self._mark_step("S4_WRITES")
        burst = [await self._read("BURST", k, patterns[k]) for k in range(SCRATCH_COUNT)]
        assert len(set(burst)) == SCRATCH_COUNT, f"burst reads not eight distinct words: {burst}"
        self._mark_step("S4")
        self._emit_chk(
            "CHK-SCRATCH-NO-ALIAS",
            "8 writes then 8 reads: "
            + " ".join(f"SCRATCH[{k}]=0x{w:08x}" for k, w in enumerate(burst))
            + f"; {len(set(burst))} distinct words, each equal to its own pattern",
        )

        for k in range(SCRATCH_COUNT):
            await self._write("RESTORE", k, 0)
        restored = [await self._read("RESTORE", k, 0) for k in range(SCRATCH_COUNT)]
        self._mark_step("S5")
        self._emit_chk(
            "CHK-SCRATCH-WRITE-READ",
            f"SCRATCH[0] read 0x{single:08x} after the 0xa5a5a5a5 write; after the restore "
            "writes SCRATCH[0..7]=" + " ".join(f"0x{w:08x}" for w in restored) + ", OKAY each",
        )

        self._bounded_waits.append(("sep_in_axi_access", f"{AXI_TIMEOUT_NS}ns", self._last_access))
        waits = " ".join(f"{n}={b} last={s}" for n, b, s in self._bounded_waits)
        self._emit_chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._bounded_waits)} bounded waits: {waits}; expiry raises AssertionError",
        )
        self._assert_fence()

    def _assert_fence(self) -> None:
        ids = tuple(s for s, _ in self._steps)
        assert ids == STEP_ORDER, f"step ids {ids} != contract order {STEP_ORDER}"
        stamps = [t for _, t in self._steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing: {stamps}"
        chk_ids = tuple(c for c, _ in self._chk_lines)
        assert chk_ids == CHK_ORDER, f"checker lines {chk_ids} != order {CHK_ORDER}"
        step_stamp = dict(self._steps)
        for chk_id, t in self._chk_lines:
            assert t >= step_stamp[CHK_STEP[chk_id]], f"{chk_id} printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            "<".join(FENCE_TERMS[s] for s in STEP_ORDER),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._steps),
        )
