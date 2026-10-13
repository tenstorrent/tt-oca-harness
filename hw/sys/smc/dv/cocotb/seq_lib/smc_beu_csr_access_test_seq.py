# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_CPU_MEM_ECC_016 / smc_beu_csr_access_test: BEU register access over SEP_IN.

Scenarios: MEMECC-BEU-CSR.S1 to S9 (aperture, reset, storage, independence, reserved bits).
Sources: hw/sys/smc/regs/blocks/bus_error_unit/bus_error_unit.rdl, hw/sys/smc/doc/cpu.adoc,
hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/fabric.adoc (REGION_SIZE).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import REGION_SIZE_RESET, smc_addr
from .smc_decode_probe_utils import AXI_RESP_DECERR, SmcDecodeProbeSeq

OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
SAMPLER_CATCHUP_CYCLES = 64
REGION_SIZE_256M = 0x1000_0000
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
BEU_COUNT = 4
BEU_REGS = ("CAUSE", "PHYS_ADDR", "ENABLE", "PLIC_ENABLE", "ACCRUED_ENABLE", "LOCAL_ENABLE")
ENABLE_RESET = 0xE6
DEFINED_BITS = (1, 2, 5, 6, 7)
DEFINED_MASK = sum(1 << b for b in DEFINED_BITS)
RESERVED_BITS = (0, 3, 4)
RESERVED_PATTERN = sum(1 << b for b in RESERVED_BITS)
ENABLE_REGS = ("ENABLE", "PLIC_ENABLE", "ACCRUED_ENABLE", "LOCAL_ENABLE")
PHYS_BITS = 56
PHYS_MASK = (1 << PHYS_BITS) - 1
CAUSE_MASK = 0x7
REG_MASK = {
    "CAUSE": CAUSE_MASK,
    "PHYS_ADDR": PHYS_MASK,
    "ENABLE": DEFINED_MASK,
    "PLIC_ENABLE": DEFINED_MASK,
    "ACCRUED_ENABLE": DEFINED_MASK,
    "LOCAL_ENABLE": DEFINED_MASK,
}
PATTERNS = {
    0: {
        "CAUSE": 0x5,
        "PHYS_ADDR": 0x00AB_CDEF_0123_4567,
        "ENABLE": 0x62,
        "PLIC_ENABLE": 0xA4,
        "ACCRUED_ENABLE": 0x46,
        "LOCAL_ENABLE": 0x86,
    },
    3: {
        "CAUSE": 0x6,
        "PHYS_ADDR": 0x0054_3210_FEDC_BA98,
        "ENABLE": 0x8C,
        "PLIC_ENABLE": 0x62,
        "ACCRUED_ENABLE": 0xC2,
        "LOCAL_ENABLE": 0x26,
    },
}
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S10R")
FENCE_TERMS = {
    "S1": "BRINGUP_SENSE_DONE",
    "S2": "DECERR_AT_RESET",
    "S3": "WIDENED_ENABLE_OKAY",
    "S4": "ENABLE_RESET_0xE6",
    "S5": "CAUSE_PHYS_EXACT",
    "S6": "ACCRUED_SET_CLEAR",
    "S7": "INDEPENDENCE_BOTH_WAYS",
    "S8": "RESERVED_BITS_PRINTED",
    "S9": "B2B_EXACT",
    "S10": "INFLIGHT_OVERLAP_MEASURED",
    "S10R": "REGION_SIZE_RESTORED",
}
CHK_ORDER = (
    ("CHK-BEU-DECERR-RESET", "S2"),
    ("CHK-BEU-WIDENED-REACH", "S3"),
    ("CHK-BEU-ENABLE-RESET", "S4"),
    ("CHK-BEU-CAUSE-PHYS", "S5"),
    ("CHK-BEU-ACCRUED", "S6"),
    ("CHK-BEU-INDEPENDENT", "S7"),
    ("CHK-BEU-RESERVED-BITS", "S8"),
    ("CHK-BEU-ENABLE-B2B", "S9"),
    ("CHK-BEU-INFLIGHT", "S10"),
    ("CHK-TIMEOUT-PATHS", "S10R"),
)


def _beu_addr(n: int, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{n}_BEU_{reg}_BASE_ADDR")


def _beu_base(n: int) -> int:
    return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{n}_BEU_BASE_ADDR")


def _reset_of(reg: str) -> int:
    return ENABLE_RESET if reg == "ENABLE" else 0


def _val(dut, name: str) -> int:
    value = getattr(dut, name).value
    assert value.is_resolvable, f"{name} is not resolvable: {value}"
    return int(value)


class _HandshakeSampler:
    """Counts s_axi request and response handshakes per clk_smc cycle."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cycle = 0
        self.outstanding = 0
        self.max_outstanding = 0
        self.overlap_cycles = 0
        self.events: list[tuple[int, str]] = []

    async def run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc)
            self.cycle += 1
            for kind, sig in (
                ("AR", "arvalid"),
                ("AW", "awvalid"),
                ("R", "rvalid"),
                ("B", "bvalid"),
            ):
                ready = {"AR": "arready", "AW": "awready", "R": "rready", "B": "bready"}[kind]
                if _val(dut, f"s_axi_{sig}") and _val(dut, f"s_axi_{ready}"):
                    self.events.append((self.cycle, kind))
                    self.outstanding += 1 if kind in ("AR", "AW") else -1
            self.max_outstanding = max(self.max_outstanding, self.outstanding)
            if self.outstanding >= 2:
                self.overlap_cycles += 1

    def summary(self) -> str:
        return " ".join(f"{k}@{c}" for c, k in self.events)


class smc_beu_csr_access_test_seq(SmcDecodeProbeSeq):
    """BEU register access over SEP_IN with REGION_SIZE at reset and widened."""

    def __init__(self, name: str = "smc_beu_csr_access_test_seq") -> None:
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

    async def _read_expect(self, name: str, addr: int, expected: int, mask: int = (1 << 64) - 1):
        got = await self._read(name, addr)
        assert got & mask == expected & mask, (
            f"{name}@0x{addr:08x} read 0x{got:x} expected 0x{expected:x} (mask 0x{mask:x})"
        )
        return got

    async def _read_decerr(self, name: str, addr: int) -> int:
        self._last_access = f"{name}@0x{addr:08x} DECERR read"
        rdata = await self.read_decerr(name, addr, length=8)
        self._last_access = f"{name}@0x{addr:08x} resp={AXI_RESP_DECERR} rdata=0x{rdata:x}"
        return rdata

    async def _write_region_size(self, name: str, value: int) -> None:
        await self._write(name, REGION_SIZE, value, length=4)
        await self._read_expect(f"{name}_RB", REGION_SIZE, value, 0xFFFF_FFFF)

    async def _run_group(self, name: str, members: list[SmcSysAxiItem]) -> _HandshakeSampler:
        sampler = _HandshakeSampler(cocotb.top)
        task = cocotb.start_soon(sampler.run())
        self._last_access = f"{name} group of {len(members)} accesses"
        try:
            group = SmcSysAxiGroupItem(name, members)
            await self.start_item(group)
            await self.finish_item(group)
            for _ in range(SAMPLER_CATCHUP_CYCLES):
                if sampler.outstanding == 0:
                    break
                await RisingEdge(cocotb.top.clk_smc)
            assert sampler.outstanding == 0, (
                f"{name}: {sampler.outstanding} accesses still outstanding after "
                f"{SAMPLER_CATCHUP_CYCLES} cycles; last access {self._last_access}"
            )
        finally:
            task.cancel()
        self.accesses += len(members)
        for member in members:
            assert member.resp_code in (OKAY, AXI_RESP_DECERR), (
                f"{name} {member.get_name()}: resp={member.resp_code}"
            )
        return sampler

    @staticmethod
    def _member(label: str, op: SmcSysAxiOp, addr: int, length: int, data: int = 0):
        item = SmcSysAxiItem(f"inflight_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.allow_error = True
        return item

    async def body(self) -> None:
        dut = cocotb.top
        axi_bound = self.cfg.axi_timeout_ns
        for name in ("clk_smc", "s_axi_arvalid", "s_axi_awvalid", "s_axi_rvalid", "s_axi_bvalid"):
            assert hasattr(dut, name), f"tb_top has no {name}"

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
        decerr_addrs = (_beu_base(0), _beu_base(3), _beu_addr(0, "ENABLE"))
        self.env.axi_monitor.expected_decerr_addrs.update(decerr_addrs)
        await self._read_expect("REGION_SIZE_RESET", REGION_SIZE, REGION_SIZE_RESET, 0xFFFFFFFF)
        self._stamp("S1")

        # S2
        decerr_data = []
        for n in (0, 3):
            decerr_data.append(await self._read_decerr(f"BEU{n}_BASE_AT_RESET", _beu_base(n)))
        self._stamp("S2")
        self._chk(
            "CHK-BEU-DECERR-RESET",
            f"with REGION_SIZE at its reset 0x{REGION_SIZE_RESET:x} the BEU base of core 0 "
            f"(0x{_beu_base(0):08x}) and core 3 (0x{_beu_base(3):08x}) answered DECERR; "
            f"DECERR read data {[hex(d) for d in decerr_data]} (SF-018 measured)",
        )

        # S3
        await self._write_region_size("REGION_SIZE_256M", REGION_SIZE_256M)
        enable_reads = []
        for n in range(BEU_COUNT):
            enable_reads.append(await self._read(f"BEU{n}_ENABLE_REACH", _beu_addr(n, "ENABLE")))
        self._stamp("S3")
        self._chk(
            "CHK-BEU-WIDENED-REACH",
            f"with REGION_SIZE 0x{REGION_SIZE_256M:x} the ENABLE register of cores 0 to "
            f"{BEU_COUNT - 1} answered OKAY, data {[hex(e) for e in enable_reads]}",
        )

        # S4
        base = {n: {} for n in range(BEU_COUNT)}
        for n in range(BEU_COUNT):
            await self._read_expect(f"BEU{n}_ENABLE_RESET", _beu_addr(n, "ENABLE"), ENABLE_RESET)
            for reg in BEU_REGS:
                base[n][reg] = await self._read(f"BEU{n}_{reg}_BASE", _beu_addr(n, reg))
        walk_cells = 0
        for reg in ("PLIC_ENABLE", "LOCAL_ENABLE"):
            addr = _beu_addr(0, reg)
            for bit in DEFINED_BITS:
                await self._write(f"BEU0_{reg}_BIT{bit}", addr, 1 << bit)
                await self._read_expect(f"BEU0_{reg}_BIT{bit}_RB", addr, 1 << bit, DEFINED_MASK)
                walk_cells += 1
            await self._write(f"BEU0_{reg}_RESTORE", addr, 0)
            await self._read_expect(f"BEU0_{reg}_RESTORE_RB", addr, 0)
        self._stamp("S4")
        self._chk(
            "CHK-BEU-ENABLE-RESET",
            f"ENABLE read 0x{ENABLE_RESET:02x} in each of {BEU_COUNT} BEUs; PLIC_ENABLE and "
            f"LOCAL_ENABLE of core 0 held each walking one over bits {list(DEFINED_BITS)} "
            f"({walk_cells} cells) with no other documented bit changing; both restored to 0",
        )

        # S5
        cause = _beu_addr(0, "CAUSE")
        for value in range(8):
            await self._write(f"BEU0_CAUSE_{value}", cause, value)
            await self._read_expect(f"BEU0_CAUSE_{value}_RB", cause, value, CAUSE_MASK)
        phys = _beu_addr(0, "PHYS_ADDR")
        patterns = [PHYS_MASK] + [1 << b for b in range(PHYS_BITS)]
        for pattern in patterns:
            await self._write(f"BEU0_PHYS_0x{pattern:x}", phys, pattern)
            got = await self._read(f"BEU0_PHYS_0x{pattern:x}_RB", phys)
            assert got == pattern, (
                f"PHYS_ADDR wrote 0x{pattern:x} read 0x{got:x} (bits above 55 "
                f"0x{got >> PHYS_BITS:x})"
            )
        await self._write("BEU0_CAUSE_ZERO", cause, 0)
        await self._read_expect("BEU0_CAUSE_ZERO_RB", cause, 0)
        await self._write("BEU0_PHYS_RESTORE", phys, base[0]["PHYS_ADDR"])
        await self._read_expect("BEU0_PHYS_RESTORE_RB", phys, base[0]["PHYS_ADDR"])
        self._stamp("S5")
        self._chk(
            "CHK-BEU-CAUSE-PHYS",
            f"CAUSE of core 0 read back each value 0 to 7 written and 0 after the final write; "
            f"PHYS_ADDR read back 0x{PHYS_MASK:x} and each of the {PHYS_BITS} walking ones "
            "exactly with no bit above bit 55 set",
        )

        # S6
        acc = _beu_addr(0, "ACCRUED_ENABLE")
        await self._write("ACCRUED_ONES", acc, DEFINED_MASK)
        got = await self._read_expect("ACCRUED_ONES_RB", acc, DEFINED_MASK, DEFINED_MASK)
        await self._write("ACCRUED_ZERO", acc, 0)
        await self._read_expect("ACCRUED_ZERO_RB", acc, 0)
        self._stamp("S6")
        self._chk(
            "CHK-BEU-ACCRUED",
            f"ACCRUED_ENABLE of core 0 read 0x{got:x} after a write of 0x{DEFINED_MASK:x} "
            "and 0 after a write of 0",
        )

        # S7
        for written in (0, 3):
            pat = PATTERNS[written]
            for reg in BEU_REGS:
                await self._write(f"BEU{written}_{reg}_PATTERN", _beu_addr(written, reg), pat[reg])
            for reg in BEU_REGS:
                await self._read_expect(
                    f"BEU{written}_{reg}_PATTERN_RB",
                    _beu_addr(written, reg),
                    pat[reg],
                    REG_MASK[reg],
                )
            for other in range(BEU_COUNT):
                if other == written:
                    continue
                for reg in BEU_REGS:
                    await self._read_expect(
                        f"BEU{other}_{reg}_UNCHANGED_BY_{written}",
                        _beu_addr(other, reg),
                        base[other][reg],
                    )
            for reg in BEU_REGS:
                await self._write(
                    f"BEU{written}_{reg}_RESTORE", _beu_addr(written, reg), base[written][reg]
                )
            for reg in BEU_REGS:
                await self._read_expect(
                    f"BEU{written}_{reg}_RESTORE_RB", _beu_addr(written, reg), base[written][reg]
                )
        self._stamp("S7")
        self._chk(
            "CHK-BEU-INDEPENDENT",
            f"a distinct pattern written to all {len(BEU_REGS)} registers of core 0 and then of "
            "core 3 read back on the written core and left every register of the other three "
            "cores unchanged; all registers restored",
        )

        # S8
        reserved: dict[str, int] = {}
        for reg in ENABLE_REGS:
            addr = _beu_addr(0, reg)
            await self._write(f"BEU0_{reg}_RESERVED", addr, RESERVED_PATTERN)
            reserved[reg] = await self._read(f"BEU0_{reg}_RESERVED_RB", addr)
            await self._write(f"BEU0_{reg}_RESERVED_RESTORE", addr, _reset_of(reg))
            await self._read_expect(f"BEU0_{reg}_RESERVED_RESTORE_RB", addr, _reset_of(reg))
        self._stamp("S8")
        matches = {reg: (v & RESERVED_PATTERN) == RESERVED_PATTERN for reg, v in reserved.items()}
        self._chk(
            "CHK-BEU-RESERVED-BITS",
            f"bits {list(RESERVED_BITS)} written as ones in core 0 registers read "
            f"{ {r: hex(v) for r, v in reserved.items()} } against the expected "
            f"0x{RESERVED_PATTERN:x} (RDL software-writable); matches the expectation "
            f"{matches} (SF-027 measured, not asserted); registers restored",
        )

        # S9
        enable = _beu_addr(0, "ENABLE")
        await self._write("ENABLE_B2B_00", enable, 0x00)
        await self._write("ENABLE_B2B_E6", enable, ENABLE_RESET)
        await self._read_expect("ENABLE_B2B_E6_RB", enable, ENABLE_RESET)
        await self._write("ENABLE_B2B_E6_2", enable, ENABLE_RESET)
        await self._write("ENABLE_B2B_00_2", enable, 0x00)
        await self._read_expect("ENABLE_B2B_00_RB", enable, 0x00)
        await self._write("ENABLE_B2B_RESTORE", enable, ENABLE_RESET)
        await self._read_expect("ENABLE_B2B_RESTORE_RB", enable, ENABLE_RESET)
        self._stamp("S9")
        self._chk(
            "CHK-BEU-ENABLE-B2B",
            "ENABLE of core 0 read 0xe6 after back-to-back writes 0x00 then 0xe6, 0x00 after "
            "0xe6 then 0x00, and 0xe6 after the restore",
        )

        # S10
        await self._write_region_size("REGION_SIZE_256M_G1", REGION_SIZE_256M)
        g1 = [
            self._member("beu_read", SmcSysAxiOp.READ, enable, 8),
            self._member("region_write", SmcSysAxiOp.WRITE, REGION_SIZE, 4, REGION_SIZE_RESET),
        ]
        s1 = await self._run_group("beu_read_with_region_size_write", g1)
        assert s1.max_outstanding >= 2, f"group 1 not overlapped: {s1.summary()}"
        resp1 = [m.resp_code for m in g1]
        await self._read_decerr("BEU0_ENABLE_AFTER_G1", enable)
        await self._write_region_size("REGION_SIZE_256M_G2", REGION_SIZE_256M)
        g2 = [
            self._member("beu_write", SmcSysAxiOp.WRITE, enable, 8, ENABLE_RESET),
            self._member("region_write", SmcSysAxiOp.WRITE, REGION_SIZE, 4, REGION_SIZE_RESET),
        ]
        s2 = await self._run_group("beu_write_with_region_size_write", g2)
        assert s2.max_outstanding >= 2, f"group 2 not overlapped: {s2.summary()}"
        resp2 = [m.resp_code for m in g2]
        await self._read_decerr("BEU0_ENABLE_AFTER_G2", enable)
        await self._read_expect("REGION_SIZE_AFTER_G2", REGION_SIZE, REGION_SIZE_RESET, 0xFFFFFFFF)
        self._waits.append(("sep_in_group", f"{axi_bound}ns", self._last_access))
        self._stamp("S10")
        self._chk(
            "CHK-BEU-INFLIGHT",
            f"group 1 (BEU read + REGION_SIZE write) responses {resp1} max outstanding "
            f"{s1.max_outstanding} overlap cycles {s1.overlap_cycles} handshakes [{s1.summary()}]; "
            f"group 2 (BEU write + REGION_SIZE write) responses {resp2} max outstanding "
            f"{s2.max_outstanding} overlap cycles {s2.overlap_cycles} handshakes [{s2.summary()}]; "
            "the next BEU access after each group answered DECERR",
        )

        # S10R
        await self._read_expect("REGION_SIZE_FINAL", REGION_SIZE, REGION_SIZE_RESET, 0xFFFFFFFF)
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S10R")
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
