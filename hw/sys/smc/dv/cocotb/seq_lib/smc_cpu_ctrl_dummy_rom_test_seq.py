# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_CPU_CTRL_015 / smc_cpu_ctrl_dummy_rom_test: DUMMY_ROM and DUMMY_ROM_NULL line and storage.

Scenarios: CPUCTRL-DUMMYROM.S2 (64-byte line read), CPUCTRL-DUMMYROM.S3 (read-write storage).
Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl, hw/sys/smc/regs/gen/c/smc_addr.h.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

WORD_BYTES = 8
ROM_WORDS = 4
NULL_WORDS = 4
OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
EXPECTED_LINE = (
    0x0145_0513_0000_0517,
    0xFFF0_0693_3055_1073,
    0x1050_0073_3046_B073,
    0x0000_0000_FFDF_F06F,
    0,
    0,
    0,
    0,
)
STEP_ORDER = ("S1", "S2", "S3", "S4")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "LINE_READ_COMPARED",
    "S3": "PATTERNS_COMPARED",
    "S4": "WORDS_RESTORED",
}
CHK_STEP = {"CHK-DROM-LINE": "S2", "CHK-DROM-RW": "S4"}


def _word_addr(index: int) -> int:
    if index < ROM_WORDS:
        return smc_addr(f"SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_{index}_BASE_ADDR")
    return smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", index - ROM_WORDS)


def _word_name(index: int) -> str:
    if index < ROM_WORDS:
        return f"DUMMY_ROM_{index}"
    return f"DUMMY_ROM_NULL[{index - ROM_WORDS}]"


def _pattern(index: int) -> int:
    return 0x5A5A_0000_0000_0000 | (index << 32) | 0x1111_1111


class smc_cpu_ctrl_dummy_rom_test_seq(SmcCsrSeq):
    """Read, overwrite and restore the eight dummy boot-ROM words over SEP_IN."""

    def __init__(self, name: str = "smc_cpu_ctrl_dummy_rom_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    async def _read(self, index: int) -> int:
        addr = _word_addr(index)
        item = SmcSysAxiItem(f"rd_{_word_name(index)}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = WORD_BYTES
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_access = (
            f"read {_word_name(index)}@0x{addr:08x} resp={item.resp_code} rdata=0x{item.rdata:x}"
        )
        assert item.resp_code == OKAY, f"dummy ROM read not OKAY: {self._last_access}"
        return item.rdata

    async def _write(self, index: int, data: int) -> None:
        addr = _word_addr(index)
        item = SmcSysAxiItem(f"wr_{_word_name(index)}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = WORD_BYTES
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_access = (
            f"write {_word_name(index)}@0x{addr:08x} resp={item.resp_code} wdata=0x{data:x}"
        )
        assert item.resp_code == OKAY, f"dummy ROM write not OKAY: {self._last_access}"

    async def _expect(self, index: int, expected: int, what: str) -> None:
        got = await self._read(index)
        assert got == expected, (
            f"{what} {_word_name(index)}@0x{_word_addr(index):08x}: expected 0x{expected:x}, "
            f"got 0x{got:x}; last access {self._last_access}"
        )

    async def body(self) -> None:
        axi_bound = self.cfg.axi_timeout_ns
        count = ROM_WORDS + NULL_WORDS
        assert len(EXPECTED_LINE) == count

        # S1
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(cocotb.top.tb_fuse_sense_done.value)
        assert sense == 1, "tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                "fuse_sense_done",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                f"tb_fuse_sense_done={sense}",
            )
        )
        self._stamp("S1")

        # S2
        original = []
        for index in range(count):
            word = await self._read(index)
            assert word == EXPECTED_LINE[index], (
                f"line {_word_name(index)}@0x{_word_addr(index):08x}: expected "
                f"0x{EXPECTED_LINE[index]:x}, got 0x{word:x}; last access {self._last_access}"
            )
            original.append(word)
        self._stamp("S2")
        self._chk(
            "CHK-DROM-LINE",
            f"{count} consecutive 64-bit words from 0x{_word_addr(0):08x} compared: "
            + " ".join(f"{_word_name(i)}=0x{w:x}" for i, w in enumerate(original))
            + " (the four zero words are reset values; X/Z not observable under Verilator)",
        )

        # S3
        for index in range(count):
            await self._write(index, _pattern(index))
        for index in range(count):
            await self._expect(index, _pattern(index), "pattern in-order")
        for index in reversed(range(count)):
            await self._expect(index, _pattern(index), "pattern reverse-order")
        self._stamp("S3")

        # S4
        for index in range(count):
            await self._write(index, original[index])
        for index in range(count):
            await self._expect(index, original[index], "restore")
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S4")
        self._chk(
            "CHK-DROM-RW",
            f"{count} registers each read back own pattern in order and reverse order "
            + ",".join(f"0x{_pattern(i):x}" for i in range(count))
            + "; restore returned the S2 words (SF-024: writability measured, owner answer pending)",
        )

        self.assert_all_reachable(count * 6, "CPU_CTRL_DUMMY_ROM")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self._chk_order.append(("CHK-TIMEOUT-PATHS", len(self._stamps)))
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    def _fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert tuple(steps) == STEP_ORDER, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order[:2] == ["CHK-DROM-LINE", "CHK-DROM-RW"], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = CHK_STEP.get(chk_id)
            if step:
                assert n_stamps == STEP_ORDER.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
