# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot-time register reads over SEP_IN after bring-up.

Contract SMC_CPU_WEDGE_BOOT_006, anchor smc_cpu_boot_regs_read_test.
Scenarios: CPU-BOOT-RESET-VECTOR-SELECT.S1, CPU-BOOT-SCRATCH-HANDSHAKE.S2,
CPU-BOOT-STRAP-WORD-READ.S1, CPU-BOOT-CHIPCFG-READ.S1, CPU-BOOT-APERTURE-PREREQ.S1/.S2,
CPU-BOOT-DUMMY-ROM-STUB.S1/.S2, CPU-ISO-DEBUG-RESET-CTRL.S1.
Sources: cpu.adoc, memmap.adoc, regs/blocks/{cpu_ctrl,straps,chip_config,smc_base_config}.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

RESET_VECTOR_RESET = 0x0000_0000_C004_0000
DEBUG_RESET_N_BIT = 24
VERSION_LO_RESET = 0x0001_00A0
GLOBAL_BASE_RESET = 0x0000_0000_4000_0000
LOCAL_BASE_RESET = 0x0000_0000_C000_0000
REGION_SIZE_RESET = 0x0000_0000_0100_0000
LOCAL_BASE_WRITE = 0x0000_0000_D000_0000
DUMMY_ROM_WORDS = (
    0x0145_0513_0000_0517,
    0xFFF0_0693_3055_1073,
    0x1050_0073_3046_B073,
    0x0000_0000_FFDF_F06F,
)
DUMMY_ROM_NULL_WORDS = (0, 0, 0, 0)
SCRATCH_ALL_ONES = 0xFFFF_FFFF_FFFF_FFFF
SCRATCH_ALL_ONES_READ = 0x0000_0000_FFFF_FFFF
SCRATCH_PATTERN = 0x0000_0000_A5C3_9E71
BURST_BEATS = 8
BEAT_BYTES = 8

RESET_VECTOR = [
    smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", i) for i in range(4)
]
RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
STRAPS_LO = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR")
STRAPS_HI = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_HI_BASE_ADDR")
VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
VERSION_HI = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_HI_BASE_ADDR")
CHIP_ID = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR")
GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
DUMMY_ROM = [smc_addr(f"SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_{i}_BASE_ADDR") for i in range(4)]
DUMMY_ROM_NULL = [
    smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", i) for i in range(4)
]
SCRATCH0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

STEP_IDS = tuple(f"S{i}" for i in range(1, 11))
CHK_ORDER = (
    ("CHK-BOOT-RESET-VECTOR-RESET", "S2"),
    ("CHK-BOOT-DEBUG-RESET-N", "S3"),
    ("CHK-BOOT-STRAP-WORD", "S4"),
    ("CHK-BOOT-CHIPCFG-RESET", "S5"),
    ("CHK-BOOT-APERTURE-RESET", "S6"),
    ("CHK-BOOT-LOCALBASE-RO", "S7"),
    ("CHK-BOOT-DUMMY-WORDS", "S8"),
    ("CHK-BOOT-DUMMY-BURST", "S9"),
    ("CHK-BOOT-SCRATCH-WIDTH", "S10"),
)


class smc_cpu_boot_regs_read_test_seq(SmcCsrSeq):
    """Read the boot-time registers over SEP_IN and compare them with the contract values."""

    def __init__(self, name: str = "smc_cpu_boot_regs_read_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_log: list[tuple[str, str]] = []

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step: str, text: str) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id}: printed outside step {step} (stamps={self._stamps})"
        )
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_log.append((chk_id, step))
        self.chk_seen.add(chk_id)

    async def _rd(self, name: str, addr: int, expected: int, length: int = 8) -> int:
        got = await self.csr_read(name, addr, expected=expected, length=length)
        assert got == expected, f"{name} @ 0x{addr:08x}: read 0x{got:x}, expected 0x{expected:x}"
        return got

    async def _rd_any(self, name: str, addr: int, length: int) -> int:
        return await self.csr_read(name, addr, length=length)

    async def body(self) -> None:
        self._stamp("S1")

        vectors = [
            await self._rd(f"RESET_VECTOR_{i}", a, RESET_VECTOR_RESET)
            for i, a in enumerate(RESET_VECTOR)
        ]
        self._stamp("S2")
        self._chk(
            "CHK-BOOT-RESET-VECTOR-RESET",
            "S2",
            "RESET_VECTOR_0..3 read "
            + ", ".join(f"0x{v:016x}" for v in vectors)
            + f", each == 0x{RESET_VECTOR_RESET:016x}",
        )

        reset_ctrl = await self._rd_any("RESET_CTRL", RESET_CTRL, 8)
        self._stamp("S3")
        debug_bit = (reset_ctrl >> DEBUG_RESET_N_BIT) & 1
        assert debug_bit == 0, f"RESET_CTRL=0x{reset_ctrl:x}: debug_reset_n bit reads {debug_bit}"
        self._chk(
            "CHK-BOOT-DEBUG-RESET-N",
            "S3",
            f"RESET_CTRL read 0x{reset_ctrl:016x}; bit {DEBUG_RESET_N_BIT} (debug_reset_n) == 0 "
            "before any write",
        )

        lo = await self._rd_any("STRAPS_LO", STRAPS_LO, 4)
        hi = await self._rd_any("STRAPS_HI", STRAPS_HI, 4)
        word = await self._rd_any("STRAPS_WORD", STRAPS_LO, 8)
        self._stamp("S4")
        assert word == (hi << 32) | lo, (
            f"STRAPS 64-bit read 0x{word:x} != (HI 0x{hi:x} << 32) | LO 0x{lo:x}"
        )
        self._chk(
            "CHK-BOOT-STRAP-WORD",
            "S4",
            f"STRAPS_LO=0x{lo:08x} STRAPS_HI=0x{hi:08x} 64-bit@STRAPS_LO=0x{word:016x} "
            "== (HI<<32)|LO",
        )

        ver_lo = await self._rd("VERSION_LO", VERSION_LO, VERSION_LO_RESET, 4)
        ver_hi = await self._rd("VERSION_HI", VERSION_HI, 0, 4)
        chip_id = await self._rd("CHIP_ID", CHIP_ID, 0, 4)
        self._stamp("S5")
        self._chk(
            "CHK-BOOT-CHIPCFG-RESET",
            "S5",
            f"VERSION_LO=0x{ver_lo:08x} VERSION_HI=0x{ver_hi:08x} CHIP_ID=0x{chip_id:08x} "
            f"(expected 0x{VERSION_LO_RESET:08x} 0x0 0x0)",
        )

        glob = await self._rd("GLOBAL_BASE", GLOBAL_BASE, GLOBAL_BASE_RESET)
        local = await self._rd("LOCAL_BASE", LOCAL_BASE, LOCAL_BASE_RESET)
        size = await self._rd("REGION_SIZE", REGION_SIZE, REGION_SIZE_RESET)
        self._stamp("S6")
        self._chk(
            "CHK-BOOT-APERTURE-RESET",
            "S6",
            f"GLOBAL_BASE=0x{glob:016x} LOCAL_BASE=0x{local:016x} REGION_SIZE=0x{size:016x}",
        )

        wr = SmcSysAxiItem("wr_LOCAL_BASE_RO")
        wr.op = SmcSysAxiOp.WRITE
        wr.addr = LOCAL_BASE
        wr.length = 8
        wr.wdata = LOCAL_BASE_WRITE
        wr.allow_error = True
        await self.start_item(wr)
        await self.finish_item(wr)
        self.accesses += 1
        assert wr.resp_code is not None, "LOCAL_BASE write returned no response"
        local_after = await self._rd("LOCAL_BASE_AFTER_WRITE", LOCAL_BASE, LOCAL_BASE_RESET)
        self._stamp("S7")
        self._chk(
            "CHK-BOOT-LOCALBASE-RO",
            "S7",
            f"write of 0x{LOCAL_BASE_WRITE:016x} to LOCAL_BASE answered resp={wr.resp_code} "
            f"(printed, not asserted, SF-029); LOCAL_BASE reads 0x{local_after:016x} "
            f"== 0x{LOCAL_BASE_RESET:016x}",
        )

        stub = [
            await self._rd(f"DUMMY_ROM_{i}", a, w)
            for i, (a, w) in enumerate(zip(DUMMY_ROM, DUMMY_ROM_WORDS))
        ]
        null = [
            await self._rd(f"DUMMY_ROM_NULL_{i}", a, w)
            for i, (a, w) in enumerate(zip(DUMMY_ROM_NULL, DUMMY_ROM_NULL_WORDS))
        ]
        self._stamp("S8")
        self._chk(
            "CHK-BOOT-DUMMY-WORDS",
            "S8",
            "DUMMY_ROM_0..3 read "
            + " ".join(f"0x{v:016x}" for v in stub)
            + "; DUMMY_ROM_NULL[0..3] read "
            + " ".join(f"0x{v:x}" for v in null),
        )

        burst = SmcSysAxiItem("rd_DUMMY_ROM_BURST")
        burst.op = SmcSysAxiOp.READ
        burst.addr = DUMMY_ROM[0]
        burst.length = BEAT_BYTES
        burst.beats = BURST_BEATS
        burst.allow_error = True
        await self.start_item(burst)
        await self.finish_item(burst)
        self.accesses += 1
        assert burst.resp_code is not None, "dummy ROM burst read returned no response"
        words = list(DUMMY_ROM_WORDS) + list(DUMMY_ROM_NULL_WORDS)
        beats = [
            (burst.rdata >> (8 * BEAT_BYTES * i)) & ((1 << (8 * BEAT_BYTES)) - 1)
            for i in range(BURST_BEATS)
        ]
        assert burst.rdata >> (8 * BEAT_BYTES * BURST_BEATS) == 0, (
            f"burst read returned more than {BURST_BEATS} beats: 0x{burst.rdata:x}"
        )
        if burst.resp_code <= 1:
            assert beats == words, (
                "dummy ROM burst beats "
                + " ".join(f"0x{b:x}" for b in beats)
                + " differ from DUMMY_ROM_0..3 then DUMMY_ROM_NULL[0..3]"
            )
        self._stamp("S9")
        self._chk(
            "CHK-BOOT-DUMMY-BURST",
            "S9",
            f"{BURST_BEATS}-beat burst read at DUMMY_ROM_0 0x{DUMMY_ROM[0]:08x} answered "
            f"resp={burst.resp_code} (SF-032); beats "
            + " ".join(f"0x{b:x}" for b in beats)
            + (
                "; equal to the stub then null words in address order"
                if burst.resp_code <= 1
                else "; data not asserted on a non-OKAY response"
            ),
        )

        await self.csr_write("SCRATCH0_ALL_ONES", SCRATCH0, SCRATCH_ALL_ONES, length=8)
        ones_rb = await self._rd("SCRATCH0_ALL_ONES_RB", SCRATCH0, SCRATCH_ALL_ONES_READ)
        await self.csr_write("SCRATCH0_PATTERN", SCRATCH0, SCRATCH_PATTERN, length=8)
        pat_rb = await self._rd("SCRATCH0_PATTERN_RB", SCRATCH0, SCRATCH_PATTERN)
        self._stamp("S10")
        self._chk(
            "CHK-BOOT-SCRATCH-WIDTH",
            "S10",
            f"SCRATCH[0] after write 0x{SCRATCH_ALL_ONES:016x} reads 0x{ones_rb:016x}; "
            f"after write 0x{SCRATCH_PATTERN:016x} reads 0x{pat_rb:016x}",
        )

        self._fence()

    def _fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert steps == list(STEP_IDS), f"step stamps out of contract order: {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        assert [c for c, _ in self._chk_log] == [c for c, _ in CHK_ORDER], (
            f"checker lines out of order: {self._chk_log}"
        )
        assert self._chk_log == list(CHK_ORDER), f"checker/step mismatch: {self._chk_log}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines CHK-BOOT-RESET-VECTOR-RESET, "
            "CHK-BOOT-DEBUG-RESET-N, CHK-BOOT-STRAP-WORD, CHK-BOOT-CHIPCFG-RESET, "
            "CHK-BOOT-APERTURE-RESET, CHK-BOOT-LOCALBASE-RO, CHK-BOOT-DUMMY-WORDS, "
            "CHK-BOOT-DUMMY-BURST, CHK-BOOT-SCRATCH-WIDTH print in step order, each step stamp "
            "later than the previous; checker lines %s; stamps %s",
            ",".join(c for c, _ in self._chk_log),
            " ".join(f"{s}={t}" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
