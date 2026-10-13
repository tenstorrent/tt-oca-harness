# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_CPU_CTRL_027 / smc_beu_register_test: BEU register map behaviour over SEP_IN.

Scenarios: CPUCTRL-BEUREG.S1 (resets), S2 (enable bits), S3 (ACCRUED_ENABLE), S4 (CAUSE),
S5 (PHYS_ADDR).
Sources: hw/sys/smc/regs/blocks/bus_error_unit/bus_error_unit.rdl, hw/sys/smc/doc/interrupts.adoc,
doc/programmer/src/smc-programming.adoc, hw/sys/smc/doc/fabric.adoc (REGION_SIZE).
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import REGION_SIZE_RESET, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
REGION_SIZE_256M = 0x1000_0000
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
BEU_COUNT = 4
BEU_REGS = ("CAUSE", "PHYS_ADDR", "ENABLE", "PLIC_ENABLE", "ACCRUED_ENABLE", "LOCAL_ENABLE")
ENABLE_RESET = 0xE6
DEFINED_BITS = (1, 2, 5, 6, 7)
DEFINED_MASK = sum(1 << b for b in DEFINED_BITS)
ENABLE_REGS = ("ENABLE", "PLIC_ENABLE", "LOCAL_ENABLE")
ALL_ONES_64 = 0xFFFF_FFFF_FFFF_FFFF
CAUSE_VALUES = (0, 1, 2, 3, 5, 6, 7)
CAUSE_UNDEFINED = 4
PHYS_BITS = 56
PHYS_DISTINCT = 0x0012_3456_789A_BC00
PHYS_ALL_ONES = 0x00FF_FFFF_FFFF_FFFF
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S7R")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "REGION_SIZE_WIDENED",
    "S3": "RESETS_COMPARED",
    "S4": "ENABLE_BITS_COMPARED",
    "S5": "ACCRUED_COMPARED",
    "S6": "CAUSE_COMPARED",
    "S7": "PHYS_ADDR_COMPARED",
    "S7R": "REGISTERS_RESTORED",
}
CHK_ORDER = (
    ("CHK-BEUREG-RESET", "S3"),
    ("CHK-BEUREG-BITS", "S4"),
    ("CHK-BEUREG-ACCRUED", "S5"),
    ("CHK-BEUREG-CAUSE", "S6"),
    ("CHK-BEUREG-PHYS", "S7"),
    ("CHK-TIMEOUT-PATHS", "S7R"),
)


def _beu_addr(n: int, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{n}_BEU_{reg}_BASE_ADDR")


class smc_beu_register_test_seq(SmcCsrSeq):
    """Drive the four BEU register blocks over SEP_IN and compare by readback."""

    def __init__(self, name: str = "smc_beu_register_test_seq") -> None:
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

    async def _read(self, name: str, addr: int, length: int = 8) -> int:
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

    async def _write(self, name: str, addr: int, data: int, length: int = 8) -> None:
        await self.csr_write(name, addr, data, length=length)
        self._last_access = f"{name}@0x{addr:08x} wdata=0x{data:x} written"

    async def _read_expect(self, name: str, addr: int, expected: int, mask: int = ALL_ONES_64):
        got = await self._read(name, addr)
        assert got & mask == expected & mask, (
            f"{name}@0x{addr:08x} read 0x{got:x} expected 0x{expected:x} (mask 0x{mask:x})"
        )
        return got

    async def body(self) -> None:
        dut = cocotb.top
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
        await self._write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M, length=4)
        await self._read_expect("REGION_SIZE_256M_RB", REGION_SIZE, REGION_SIZE_256M, 0xFFFF_FFFF)
        self._stamp("S2")

        # S3
        phys_saved = []
        for n in range(BEU_COUNT):
            await self._read_expect(f"BEU{n}_ENABLE_RESET", _beu_addr(n, "ENABLE"), ENABLE_RESET)
            for reg in ("PLIC_ENABLE", "LOCAL_ENABLE", "ACCRUED_ENABLE", "CAUSE"):
                await self._read_expect(f"BEU{n}_{reg}_RESET", _beu_addr(n, reg), 0)
            phys_saved.append(await self._read(f"BEU{n}_PHYS_ADDR_SAVE", _beu_addr(n, "PHYS_ADDR")))
        self._stamp("S3")
        self._chk(
            "CHK-BEUREG-RESET",
            f"BEU 0..{BEU_COUNT - 1} ENABLE read 0x{ENABLE_RESET:016x}; PLIC_ENABLE, LOCAL_ENABLE, "
            "ACCRUED_ENABLE and CAUSE read 0 (the 0x0 reads are reset-equal under 2-state "
            "Verilator); PHYS_ADDR has no reset value (SF-023) read "
            f"{[hex(p) for p in phys_saved]}",
        )

        # S4
        cur = {reg: [ENABLE_RESET if reg == "ENABLE" else 0] * BEU_COUNT for reg in ENABLE_REGS}
        reserved_seen: dict[str, set[int]] = {reg: set() for reg in ENABLE_REGS}
        bit_cells = 0
        for reg in ENABLE_REGS:
            for n in range(BEU_COUNT):
                addr = _beu_addr(n, reg)
                for bit in DEFINED_BITS:
                    await self._write(f"BEU{n}_{reg}_BIT{bit}", addr, 1 << bit)
                    got = await self._read_expect(
                        f"BEU{n}_{reg}_BIT{bit}_RB", addr, 1 << bit, DEFINED_MASK
                    )
                    reserved_seen[reg].add(got & ~DEFINED_MASK)
                    cur[reg][n] = got
                    for other in range(BEU_COUNT):
                        if other != n:
                            await self._read_expect(
                                f"BEU{other}_{reg}_UNCHANGED",
                                _beu_addr(other, reg),
                                cur[reg][other],
                            )
                    bit_cells += 1
                await self._write(f"BEU{n}_{reg}_ONES", addr, ALL_ONES_64)
                got = await self._read(f"BEU{n}_{reg}_ONES_RB", addr)
                reserved_seen[reg].add(got & ~DEFINED_MASK)
                assert got & DEFINED_MASK == DEFINED_MASK, (
                    f"BEU{n} {reg} defined bits after all-ones write: 0x{got:x}"
                )
                restore = ENABLE_RESET if reg == "ENABLE" else 0
                await self._write(f"BEU{n}_{reg}_RESTORE", addr, restore)
                cur[reg][n] = await self._read_expect(f"BEU{n}_{reg}_RESTORE_RB", addr, restore)
        self._stamp("S4")
        self._chk(
            "CHK-BEUREG-BITS",
            f"defined bits {list(DEFINED_BITS)} of ENABLE, PLIC_ENABLE and LOCAL_ENABLE read back "
            f"as written alone on each of {BEU_COUNT} BEUs ({bit_cells} cells) with the other "
            "three instances unchanged; reserved bits readbacks (SF-023) "
            f"{ {r: sorted(hex(v) for v in s) for r, s in reserved_seen.items()} }",
        )

        # S5
        addr = _beu_addr(0, "ACCRUED_ENABLE")
        await self._write("ACCRUED_0x22", addr, 0x22)
        await self._read_expect("ACCRUED_0x22_RB", addr, 0x22)
        await self._write("ACCRUED_0x84", addr, 0x84)
        await self._read_expect("ACCRUED_0x84_RB", addr, 0x84)
        await self._write("ACCRUED_ZERO", addr, 0)
        await self._read_expect("ACCRUED_ZERO_RB", addr, 0)
        self._stamp("S5")
        self._chk(
            "CHK-BEUREG-ACCRUED",
            "BEU0 ACCRUED_ENABLE read 0x22 after a write of 0x22, 0x84 after a write of 0x84 "
            "(replaced, not merged 0xa6) and 0 after a write of 0",
        )

        # S6
        for value in CAUSE_VALUES:
            for n in range(BEU_COUNT):
                await self._write(f"BEU{n}_CAUSE_{value}", _beu_addr(n, "CAUSE"), value)
                await self._read_expect(f"BEU{n}_CAUSE_{value}_RB", _beu_addr(n, "CAUSE"), value)
        undefined = []
        for n in range(BEU_COUNT):
            await self._write(f"BEU{n}_CAUSE_4", _beu_addr(n, "CAUSE"), CAUSE_UNDEFINED)
            undefined.append(await self._read(f"BEU{n}_CAUSE_4_RB", _beu_addr(n, "CAUSE")))
        for n in range(BEU_COUNT):
            await self._write(f"BEU{n}_CAUSE_REARM", _beu_addr(n, "CAUSE"), 0)
            await self._read_expect(f"BEU{n}_CAUSE_REARM_RB", _beu_addr(n, "CAUSE"), 0)
        self._stamp("S6")
        self._chk(
            "CHK-BEUREG-CAUSE",
            f"CAUSE read back each written value {list(CAUSE_VALUES)} on every BEU and 0 after the "
            f"re-arm write; the readback of {CAUSE_UNDEFINED} (SF-023) per BEU is "
            f"{[hex(u) for u in undefined]}",
        )

        # S7
        distinct = [PHYS_DISTINCT | n for n in range(BEU_COUNT)]
        for n in range(BEU_COUNT):
            await self._write(f"BEU{n}_PHYS_DISTINCT", _beu_addr(n, "PHYS_ADDR"), distinct[n])
        for n in range(BEU_COUNT):
            await self._read_expect(
                f"BEU{n}_PHYS_DISTINCT_RB", _beu_addr(n, "PHYS_ADDR"), distinct[n]
            )
        patterns = [1 << b for b in range(PHYS_BITS)] + [PHYS_ALL_ONES]
        expected = list(distinct)
        for n in range(BEU_COUNT):
            addr = _beu_addr(n, "PHYS_ADDR")
            for pattern in patterns:
                await self._write(f"BEU{n}_PHYS_0x{pattern:x}", addr, pattern)
                await self._read_expect(f"BEU{n}_PHYS_0x{pattern:x}_RB", addr, pattern)
                expected[n] = pattern
                for other in range(BEU_COUNT):
                    if other != n:
                        await self._read_expect(
                            f"BEU{other}_PHYS_UNCHANGED",
                            _beu_addr(other, "PHYS_ADDR"),
                            expected[other],
                        )
        self._stamp("S7")
        self._chk(
            "CHK-BEUREG-PHYS",
            f"PHYS_ADDR of each BEU read back the distinct value {[hex(d) for d in distinct]}, "
            f"all {PHYS_BITS} walking-one bits and 0x{PHYS_ALL_ONES:x} exactly with the other "
            "instances unchanged",
        )

        # S7R
        for n in range(BEU_COUNT):
            await self._write(f"BEU{n}_PHYS_RESTORE", _beu_addr(n, "PHYS_ADDR"), phys_saved[n])
            await self._read_expect(
                f"BEU{n}_PHYS_RESTORE_RB", _beu_addr(n, "PHYS_ADDR"), phys_saved[n]
            )
        await self._write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET, length=4)
        await self._read_expect(
            "REGION_SIZE_RESTORE_RB", REGION_SIZE, REGION_SIZE_RESET, 0xFFFF_FFFF
        )
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S7R")

        self.assert_all_reachable(self.accesses, "BEU")
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
