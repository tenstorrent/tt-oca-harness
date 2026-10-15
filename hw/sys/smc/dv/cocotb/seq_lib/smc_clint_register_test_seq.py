# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_clint_register_test: CLINT MSIP, MTIMECMP and MTIME register behaviour.

Sources: hw/sys/smc/regs/blocks/clint/clint.rdl, hw/sys/smc/doc/clk_rst.adoc,
hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/fabric.adoc (REGION_SIZE).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import REGION_SIZE_RESET, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

CORES = 4
OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
MTIME_CHANGE_MAX_CYCLES = 20_000
MTIME_LOAD_MAX_READS = 200
MTIME_READS = 4
REGION_SIZE_256M = 0x1000_0000
ALL_ONES_32 = 0xFFFF_FFFF
ALL_ONES_64 = 0xFFFF_FFFF_FFFF_FFFF
MTIMECMP_PATTERN = 0x0123_4567_89AB_CD00
MTIME_LOAD_VALUE = 0x0000_0001_0000_0000
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
MTIME_ADDR = smc_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIME_BASE_ADDR")
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S6R")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "REGION_SIZE_WIDENED",
    "S3": "MSIP_COMPARED",
    "S4": "MTIMECMP_COMPARED",
    "S5": "MTIME_ADVANCE_COMPARED",
    "S6": "MTIME_LOAD_COMPARED",
    "S6R": "REGISTERS_RESTORED",
}
CHK_ORDER = (
    ("CHK-CLINT-MSIP", "S3"),
    ("CHK-CLINT-MTIMECMP", "S4"),
    ("CHK-CLINT-MTIME-ADV", "S5"),
    ("CHK-CLINT-MTIME-LOAD", "S6"),
    ("CHK-TIMEOUT-PATHS", "S6R"),
)


def _msip_addr(core: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR", core)


def _mtimecmp_addr(core: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIMECMP_BASE_ADDR", core)


def _mtimecmp_value(core: int) -> int:
    return MTIMECMP_PATTERN | core


class smc_clint_register_test_seq(SmcCsrSeq):
    """Drive the CLINT registers over SEP_IN and compare them with the exported CLINT probes."""

    def __init__(self, name: str = "smc_clint_register_test_seq") -> None:
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

    @staticmethod
    def _probe(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z: {sig.value}"
        return int(sig.value)

    async def _read(self, name: str, addr: int, length: int = 4) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_access = f"{name}@0x{addr:08x} resp={item.resp_code} rdata=0x{item.rdata:x}"
        assert item.resp_code == OKAY, f"read not OKAY: {self._last_access}"
        return item.rdata

    async def _write(self, name: str, addr: int, data: int, length: int = 4) -> None:
        await self.csr_write(name, addr, data, length=length)
        self._last_access = f"{name}@0x{addr:08x} wdata=0x{data:x} written"

    async def _read_expect(self, name: str, addr: int, expected: int, length: int = 4) -> None:
        got = await self._read(name, addr, length)
        assert got == expected, f"{name}@0x{addr:08x} read 0x{got:x} expected 0x{expected:x}"

    async def _msip_set(self, core: int) -> str:
        await self._write(f"MSIP{core}_ONES", _msip_addr(core), ALL_ONES_32)
        await self._read_expect(f"MSIP{core}_RB", _msip_addr(core), 1)
        probe = self._probe("tb_clint_msip")
        assert (probe >> core) & 1 == 1, f"tb_clint_msip=0x{probe:x} bit {core} not set"
        for other in range(CORES):
            if other != core:
                await self._read_expect(f"MSIP{other}_OTHER", _msip_addr(other), 0)
        assert probe == 1 << core, f"tb_clint_msip=0x{probe:x} expected 0x{1 << core:x}"
        await self._write(f"MSIP{core}_ZERO", _msip_addr(core), 0)
        await self._read_expect(f"MSIP{core}_ZERO_RB", _msip_addr(core), 0)
        assert self._probe("tb_clint_msip") == 0, "tb_clint_msip nonzero after MSIP clear"
        return f"MSIP[{core}]=0x1 probe=0x{probe:x}"

    def _probe_mtimecmp(self, core: int, expected: int) -> str:
        if core > 1:
            return ""
        probe = self._probe(f"tb_clint_mtimecmp{core}")
        assert probe == expected, f"tb_clint_mtimecmp{core}=0x{probe:x} expected 0x{expected:x}"
        return f"probe{core}=0x{probe:x}"

    async def _mtimecmp_all(self, expected: list[int], tag: str) -> list[str]:
        notes = []
        for core in range(CORES):
            addr = _mtimecmp_addr(core)
            await self._read_expect(f"MTIMECMP{core}_{tag}", addr, expected[core], 8)
            note = self._probe_mtimecmp(core, expected[core])
            if note:
                notes.append(note)
        return notes

    async def _wait_mtime_change(self, before: int) -> tuple[int, int]:
        clk = cocotb.top.clk_smc_i
        for cycle in range(MTIME_CHANGE_MAX_CYCLES + 1):
            now = self._probe("tb_clint_mtime")
            if now != before:
                return now, cycle
            await RisingEdge(clk)
        raise AssertionError(
            f"tb_clint_mtime stayed 0x{before:x} for {MTIME_CHANGE_MAX_CYCLES} clk_smc_i cycles; "
            f"last access {self._last_access}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        for sig in ("tb_clint_mtime", "tb_clint_mtimecmp0", "tb_clint_mtimecmp1", "tb_clint_msip"):
            assert hasattr(dut, sig), f"{sig} not exported"
        axi_bound = self.cfg.axi_timeout_ns

        # S1
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(dut.tb_fuse_sense_done.value)
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
        await self._write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self._read_expect("REGION_SIZE_256M_RB", REGION_SIZE, REGION_SIZE_256M)
        saved_msip = [await self._read(f"MSIP{n}_SAVE", _msip_addr(n)) for n in range(CORES)]
        saved_cmp = [
            await self._read(f"MTIMECMP{n}_SAVE", _mtimecmp_addr(n), 8) for n in range(CORES)
        ]
        for n in range(CORES):
            await self._write(f"MSIP{n}_CLEAR", _msip_addr(n), 0)
        self._stamp("S2")

        # S3
        notes = [await self._msip_set(core) for core in range(CORES)]
        self._stamp("S3")
        self._chk(
            "CHK-CLINT-MSIP",
            "ones written to each MSIP[n] read bit0=1 and bits[31:1]=0, the other three read 0, "
            "tb_clint_msip bit n followed the register: "
            + " ".join(notes)
            + f" (saved MSIP={[hex(v) for v in saved_msip]})",
        )

        # S4
        distinct = [_mtimecmp_value(n) for n in range(CORES)]
        for n in range(CORES):
            await self._write(f"MTIMECMP{n}_PATTERN", _mtimecmp_addr(n), distinct[n], 8)
        notes = await self._mtimecmp_all(distinct, "PATTERN_RB")
        for n in range(CORES):
            await self._write(f"MTIMECMP{n}_ONES", _mtimecmp_addr(n), ALL_ONES_64, 8)
            expected = list(distinct)
            expected[n] = ALL_ONES_64
            notes += await self._mtimecmp_all(expected, f"ONES{n}_RB")
            await self._write(f"MTIMECMP{n}_PATTERN_BACK", _mtimecmp_addr(n), distinct[n], 8)
        self._stamp("S4")
        self._chk(
            "CHK-CLINT-MTIMECMP",
            f"four distinct 64-bit values 0x{MTIMECMP_PATTERN:x}|n and the all-ones value read "
            f"back independently per core, probes agree for cores 0 and 1 ({len(notes)} probe "
            f"samples); reset values not specified, measured, saved="
            f"{[hex(v) for v in saved_cmp]}",
        )

        # S5
        reads = [await self._read("MTIME_0", MTIME_ADDR, 8)]
        probe0 = self._probe("tb_clint_mtime")
        probe1, cycles = await self._wait_mtime_change(probe0)
        self._waits.append(
            (
                "mtime_probe_change",
                f"{MTIME_CHANGE_MAX_CYCLES}cyc",
                f"tb_clint_mtime 0x{probe0:x}->0x{probe1:x} after {cycles}cyc",
            )
        )
        reads.append(await self._read("MTIME_1", MTIME_ADDR, 8))
        for i in range(2, MTIME_READS):
            reads.append(await self._read(f"MTIME_{i}", MTIME_ADDR, 8))
        assert reads[1] > reads[0], f"MTIME did not advance: reads {[hex(r) for r in reads]}"
        assert all(b >= a for a, b in zip(reads, reads[1:])), (
            f"MTIME read went backwards: {[hex(r) for r in reads]}"
        )
        self._stamp("S5")
        self._chk(
            "CHK-CLINT-MTIME-ADV",
            f"MTIME reads {[hex(r) for r in reads]} never smaller, second read above first after "
            f"tb_clint_mtime changed 0x{probe0:x}->0x{probe1:x} in {cycles} clk_smc_i cycles; "
            "tick-to-clock relation not specified, measured",
        )

        # S6
        await self._write("MTIME_LOAD", MTIME_ADDR, MTIME_LOAD_VALUE, 8)
        hit = None
        for poll in range(1, MTIME_LOAD_MAX_READS + 1):
            p_before = self._probe("tb_clint_mtime")
            value = await self._read("MTIME_POLL", MTIME_ADDR, 8)
            p_after = self._probe("tb_clint_mtime")
            if value >= MTIME_LOAD_VALUE:
                hit = (poll, value, p_before, p_after)
                break
        assert hit is not None, (
            f"MTIME never reached 0x{MTIME_LOAD_VALUE:x} in {MTIME_LOAD_MAX_READS} reads; "
            f"last access {self._last_access}"
        )
        poll, value, p_before, p_after = hit
        assert p_before <= value <= p_after, (
            f"tb_clint_mtime disagrees with MTIME read: probe 0x{p_before:x}..0x{p_after:x} "
            f"read 0x{value:x}"
        )
        self._waits.append(
            (
                "mtime_load_poll",
                f"{MTIME_LOAD_MAX_READS}reads",
                f"hit at read {poll} value=0x{value:x}",
            )
        )
        self._stamp("S6")
        self._chk(
            "CHK-CLINT-MTIME-LOAD",
            f"MTIME at or above 0x{MTIME_LOAD_VALUE:x} at read {poll} of {MTIME_LOAD_MAX_READS}, "
            f"value 0x{value:x}, probe 0x{p_before:x}..0x{p_after:x}; reflected minus written = "
            f"{value - MTIME_LOAD_VALUE} (not specified, measured)",
        )

        # S6R
        for n in range(CORES):
            await self._write(f"MSIP{n}_RESTORE", _msip_addr(n), saved_msip[n])
            await self._read_expect(f"MSIP{n}_RESTORE_RB", _msip_addr(n), saved_msip[n])
            await self._write(f"MTIMECMP{n}_RESTORE", _mtimecmp_addr(n), saved_cmp[n], 8)
            await self._read_expect(f"MTIMECMP{n}_RESTORE_RB", _mtimecmp_addr(n), saved_cmp[n], 8)
        await self._write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self._read_expect("REGION_SIZE_RESTORE_RB", REGION_SIZE, REGION_SIZE_RESET)
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S6R")

        self.assert_all_reachable(self.accesses, "CLINT")
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
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEP_ORDER.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
