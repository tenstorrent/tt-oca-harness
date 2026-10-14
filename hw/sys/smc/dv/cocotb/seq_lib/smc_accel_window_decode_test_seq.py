# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA and zeroer register windows: aliasing, boundary, holes, neighbours, REGION_SIZE.

Specs hw/sys/smc/doc/{memmap,dma,zeroer}.adoc, vendor idma overlay dma_ctrl.rdl, zeroer_ctrl.rdl.

Response and data inside the apertures but outside any register and the effect of writes
to read-only registers are measured and printed, not asserted.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import DMA_CG_EN, REGION_SIZE_RESET, ZEROER_CG_EN, smc_addr
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
AXI_RESP_DECERR = 3
ERR_DATA = 0xBADCAB1E

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
DMA_BASE = smc_addr("SMC_TOP_DMA_CTRL_BASE_ADDR")
ZEROER_BASE = smc_addr("SMC_TOP_ZEROER_CTRL_BASE_ADDR")
DMA_CONFIG = smc_addr("SMC_TOP_DMA_CTRL_CONFIG_BASE_ADDR")
DMA_STATUS_0 = smc_addr("SMC_TOP_DMA_CTRL_STATUS_0_BASE_ADDR")
DMA_NEXT_ID_0 = smc_addr("SMC_TOP_DMA_CTRL_NEXT_ID_0_BASE_ADDR")
DMA_DONE_0 = smc_addr("SMC_TOP_DMA_CTRL_DONE_0_BASE_ADDR")
DMA_DST_LO = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
DMA_REPS_HI = smc_addr("SMC_TOP_DMA_CTRL_NUM_REPETITIONS_HI_BASE_ADDR")
ZER_DEST = smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR")
ZER_SIZE = smc_addr("SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR")
ZER_CTRL_STATUS = smc_addr("SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR")

DMA_APERTURE_LAST_WORD = DMA_BASE + 0x1FC
BELOW_DMA = DMA_BASE - 4
ABOVE_ZEROER = ZEROER_BASE + 0x200
REDUCED_REGION_SIZE = 0x2_0000

DMA_HOLES = (
    [DMA_BASE + 0x44]
    + [DMA_BASE + 0x4C + 8 * n for n in range(16)]
    + list(range(DMA_BASE + 0x138, DMA_BASE + 0x200, 4))
)
ZEROER_HOLES = list(range(ZEROER_BASE + 0x18, ZEROER_BASE + 0x200, 8))

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
CHK_ORDER = (
    ("S2", "CHK-ACCEL-WIN-NO-ALIAS"),
    ("S3", "CHK-ACCEL-WIN-FIRST-LAST"),
    ("S4", "CHK-ACCEL-WIN-HOLES"),
    ("S5", "CHK-ACCEL-WIN-DECERR-NEIGHBOURS"),
    ("S6", "CHK-ACCEL-WIN-REGION-SIZE"),
    ("S7", "CHK-ACCEL-WIN-RO-WRITES"),
)


def _runs(rows: list[tuple[int, int, int]]) -> str:
    """Compress (addr, resp, data) rows into runs of equal (resp, data)."""
    out: list[str] = []
    start = prev = None
    key = None
    for addr, resp, data in rows + [(-1, -1, -1)]:
        if (resp, data) != key:
            if key is not None:
                name = AXI_RESP_NAME.get(key[0], str(key[0]))
                out.append(f"0x{start:08x}-0x{prev:08x}={name}/0x{key[1]:x}")
            start, key = addr, (resp, data)
        prev = addr
    return ",".join(out)


class smc_accel_window_decode_test_seq(SmcCsrSeq):
    """Decode of the DMA and zeroer windows against their neighbours."""

    def __init__(self, name: str = "smc_accel_window_decode_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.saved: dict[str, int] = {}
        self.patterns: tuple[int, int] = (0, 0)

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    def _expect_decerr_at(self, addrs) -> None:
        self.env.axi_monitor.expected_decerr_addrs.update(addrs)

    async def _read_any(self, label: str, addr: int, length: int) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out and item.resp_code is not None, f"{label} @ 0x{addr:08x} hung"
        assert isinstance(item.rdata, int), f"{label} @ 0x{addr:08x}: unresolved read data"
        return item.resp_code, item.rdata

    async def _write_any(self, label: str, addr: int, data: int, length: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out and item.resp_code is not None, f"{label} @ 0x{addr:08x} hung"
        return item.resp_code

    async def _read_decerr(self, label: str, addr: int, length: int = 4) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_DECERR
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_DECERR, (
            f"{label} @ 0x{addr:08x}: expected DECERR, got resp={item.resp_code} "
            f"rdata=0x{item.rdata:x}"
        )
        return item.rdata

    async def _write_decerr(self, label: str, addr: int, data: int, length: int = 4) -> None:
        resp = await self.csr_write_expect_error(
            label, addr, data, length=length, resp=AXI_RESP_DECERR
        )
        assert resp == AXI_RESP_DECERR, f"{label} @ 0x{addr:08x}: resp={resp}"

    async def _s1(self) -> str:
        await wait_fuse_sense_done()
        cg = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        await self.csr_write(
            "ACCEL_CG_EN_CLEAR", CLOCK_GATE_CONTROL, cg & ~(DMA_CG_EN | ZEROER_CG_EN), length=8
        )
        cg_rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        assert cg_rb & (DMA_CG_EN | ZEROER_CG_EN) == 0, f"CLOCK_GATE_CONTROL=0x{cg_rb:x}"
        region = await self.csr_read("REGION_SIZE_RD", REGION_SIZE, length=8)
        assert region == REGION_SIZE_RESET, (
            f"REGION_SIZE reads 0x{region:x}, default 0x{REGION_SIZE_RESET:x}"
        )
        self.saved = {
            "REGION_SIZE": region,
            "DMA_CONFIG": await self.csr_read("DMA_CONFIG_RD", DMA_CONFIG),
            "DMA_REPS_HI": await self.csr_read("DMA_REPS_HI_RD", DMA_REPS_HI),
            "DMA_DST_LO": await self.csr_read("DMA_DST_LO_RD", DMA_DST_LO),
            "ZER_DEST": await self.csr_read("ZER_DEST_RD", ZER_DEST, length=8),
            "ZER_SIZE": await self.csr_read("ZER_SIZE_RD", ZER_SIZE, length=8),
        }
        assert self.saved["ZER_SIZE"] == 0, f"zeroer SIZE reads 0x{self.saved['ZER_SIZE']:x}"
        self._mark("S1")
        return f"dma_cg_en and zeroer_cg_en clear (CLOCK_GATE_CONTROL=0x{cg_rb:x})"

    async def _s2(self) -> str:
        rounds = (
            ("DMA_FIRST", 0x1357_9BDF, 0xFEDC_BA98_7654_3210),
            ("ZEROER_FIRST", 0x2468_ACE1, 0x0123_4567_89AB_CDEF),
        )
        seen = []
        for order, dma_pat, zer_pat in rounds:
            if order == "DMA_FIRST":
                await self.csr_write(f"{order}_DMA_WR", DMA_DST_LO, dma_pat)
                await self.csr_write(f"{order}_ZER_WR", ZER_DEST, zer_pat, length=8)
            else:
                await self.csr_write(f"{order}_ZER_WR", ZER_DEST, zer_pat, length=8)
                await self.csr_write(f"{order}_DMA_WR", DMA_DST_LO, dma_pat)
            dma = await self.csr_read(f"{order}_DMA_RD", DMA_DST_LO)
            zer = await self.csr_read(f"{order}_ZER_RD", ZER_DEST, length=8)
            assert dma == dma_pat, f"{order}: DST_ADDRESS_LO 0x{dma:x}, wrote 0x{dma_pat:x}"
            assert zer == zer_pat, f"{order}: DEST_ADDR 0x{zer:x}, wrote 0x{zer_pat:x}"
            seen.append(f"{order}:DST_ADDRESS_LO=0x{dma:08x},DEST_ADDR=0x{zer:016x}")
        self.patterns = (rounds[1][1], rounds[1][2])
        self._mark("S2")
        return "each window read back its own pattern in both write orders; " + "; ".join(seen)

    async def _s3(self) -> str:
        dma_pat, zer_pat = self.patterns
        await self.csr_write("DMA_CONFIG_WR", DMA_CONFIG, 0x5A5)
        await self.csr_write("DMA_REPS_HI_WR", DMA_REPS_HI, 0x0012_3456)
        first_dma = await self.csr_read("DMA_FIRST_RD", DMA_CONFIG, expected=0x5A5)
        last_dma = await self.csr_read("DMA_LAST_RD", DMA_REPS_HI, expected=0x0012_3456)
        first_zer = await self.csr_read("ZER_FIRST_RD", ZER_DEST, expected=zer_pat, length=8)
        last_zer = await self.csr_read("ZER_LAST_RD", ZER_CTRL_STATUS, expected=0, length=8)
        dma_dst = await self.csr_read("DMA_DST_LO_RD", DMA_DST_LO, expected=dma_pat)
        below_resp, below = await self._read_any("DMA_LAST_WORD", DMA_APERTURE_LAST_WORD, 4)
        above = await self.csr_read("ZER_BOUNDARY_RD", ZEROER_BASE, expected=zer_pat, length=8)
        assert not (below_resp == 0 and below in (zer_pat & 0xFFFF_FFFF, zer_pat >> 32)), (
            f"BASE+0x3_81FF word returned zeroer DEST_ADDR content 0x{below:x}"
        )
        await self.csr_write("DMA_CONFIG_RESTORE", DMA_CONFIG, self.saved["DMA_CONFIG"])
        await self.csr_write("DMA_REPS_HI_RESTORE", DMA_REPS_HI, self.saved["DMA_REPS_HI"])
        await self.csr_write("DMA_DST_LO_RESTORE", DMA_DST_LO, self.saved["DMA_DST_LO"])
        await self.csr_write("ZER_DEST_RESTORE", ZER_DEST, self.saved["ZER_DEST"], length=8)
        self._mark("S3")
        return (
            f"DMA first CONFIG=0x{first_dma:x} and last NUM_REPETITIONS_HI=0x{last_dma:x} and "
            f"zeroer first DEST_ADDR=0x{first_zer:x} and last CTRL_STATUS=0x{last_zer:x} "
            f"answered OKAY with their own content; DST_ADDRESS_LO=0x{dma_dst:x}; "
            f"BASE+0x3_81FF word (0x{DMA_APERTURE_LAST_WORD:08x}) answered "
            f"{AXI_RESP_NAME.get(below_resp)}/0x{below:x} and carried no zeroer content; "
            f"BASE+0x3_8200 (0x{ZEROER_BASE:08x}) read zeroer DEST_ADDR 0x{above:x}"
        )

    async def _sweep(self, addrs: list[int], length: int) -> tuple[list, list]:
        reads, writes = [], []
        for addr in addrs:
            resp, data = await self._read_any(f"HOLE_RD_{addr:08x}", addr, length)
            reads.append((addr, resp, data))
        for addr in addrs:
            resp = await self._write_any(f"HOLE_WR_{addr:08x}", addr, 0, length)
            writes.append((addr, resp, 0))
        return reads, writes

    async def _s4(self) -> str:
        self._expect_decerr_at(DMA_HOLES + ZEROER_HOLES)
        parts = []
        for window, addrs, length in (
            ("DMA", DMA_HOLES, 4),
            ("ZEROER", ZEROER_HOLES, 8),
        ):
            reads, writes = await self._sweep(addrs, length)
            parts.append(
                f"{window} {len(addrs)} words reads[{_runs(reads)}] "
                f"writes[{_runs([(a, r, 0) for a, r, _ in writes])}]"
            )
        self._mark("S4")
        return (
            "every hole access completed (owner value pending, measured not asserted); "
            + "; ".join(parts)
        )

    async def _s5(self) -> str:
        self._expect_decerr_at([BELOW_DMA, ABOVE_ZEROER])
        below = await self._read_decerr("BELOW_DMA_RD", BELOW_DMA)
        above = await self._read_decerr("ABOVE_ZEROER_RD", ABOVE_ZEROER)
        await self._write_decerr("ABOVE_ZEROER_WR", ABOVE_ZEROER, 0)
        assert below == ERR_DATA and above == ERR_DATA, (
            f"neighbour data 0x{below:x} / 0x{above:x}, expected 0x{ERR_DATA:x}"
        )
        self._mark("S5")
        return (
            f"read 0x{BELOW_DMA:08x} DECERR/0x{below:08x}; read 0x{ABOVE_ZEROER:08x} "
            f"DECERR/0x{above:08x}; write 0x{ABOVE_ZEROER:08x} DECERR"
        )

    async def _s6(self) -> str:
        dma_pat, zer_pat = 0x0BAD_F00D, 0x5555_AAAA_3333_CCCC
        await self.csr_write("PRE_DMA_WR", DMA_DST_LO, dma_pat)
        await self.csr_write("PRE_ZER_WR", ZER_DEST, zer_pat, length=8)
        self._expect_decerr_at([DMA_DST_LO, ZER_DEST])
        await self.csr_write("REGION_SIZE_REDUCE", REGION_SIZE, REDUCED_REGION_SIZE, length=8)
        try:
            await self.csr_read(
                "REGION_SIZE_REDUCED_RB", REGION_SIZE, expected=REDUCED_REGION_SIZE, length=8
            )
            dma_red = await self._read_decerr("REDUCED_DMA_RD", DMA_DST_LO)
            zer_red = await self._read_decerr("REDUCED_ZER_RD", ZER_DEST, length=8)
            await self._write_decerr("REDUCED_DMA_WR", DMA_DST_LO, 0xDEAD_0001)
            await self._write_decerr("REDUCED_ZER_WR", ZER_DEST, 0xDEAD_0002, length=8)
        finally:
            await self.csr_write(
                "REGION_SIZE_RESTORE", REGION_SIZE, self.saved["REGION_SIZE"], length=8
            )
        await self.csr_read(
            "REGION_SIZE_RESTORED_RB", REGION_SIZE, expected=self.saved["REGION_SIZE"], length=8
        )
        dma = await self.csr_read("RESTORED_DMA_RD", DMA_DST_LO, expected=dma_pat)
        zer = await self.csr_read("RESTORED_ZER_RD", ZER_DEST, expected=zer_pat, length=8)
        await self.csr_write("DMA_DST_LO_RESTORE", DMA_DST_LO, self.saved["DMA_DST_LO"])
        await self.csr_write("ZER_DEST_RESTORE", ZER_DEST, self.saved["ZER_DEST"], length=8)
        self._mark("S6")
        return (
            f"REGION_SIZE 0x{self.saved['REGION_SIZE']:x} reduced to 0x{REDUCED_REGION_SIZE:x}: "
            f"DMA read DECERR/0x{dma_red:x}, zeroer read DECERR/0x{zer_red:x}, both writes "
            f"DECERR; restored to 0x{self.saved['REGION_SIZE']:x}: DMA OKAY/0x{dma:x}, "
            f"zeroer OKAY/0x{zer:x} (patterns written before the reduction, writes during it "
            f"did not land)"
        )

    async def _s7(self) -> str:
        probes = (
            ("DMA_STATUS_0", DMA_STATUS_0, 0xFFFF_FFFF, 4),
            ("DMA_DONE_0", DMA_DONE_0, 0xFFFF_FFFF, 4),
            ("ZER_CTRL_STATUS_BIT", ZER_CTRL_STATUS, 1 << 32, 8),
        )
        out = []
        status_before = await self.csr_read("STATUS_0_BEFORE", DMA_STATUS_0)
        done_before = await self.csr_read("DONE_0_BEFORE", DMA_DONE_0)
        zer_before = await self.csr_read("ZER_CS_BEFORE", ZER_CTRL_STATUS, length=8)
        before = {DMA_STATUS_0: status_before, DMA_DONE_0: done_before, ZER_CTRL_STATUS: zer_before}
        resps = {}
        resps[DMA_STATUS_0] = await self._write_any("STATUS_0_WR", DMA_STATUS_0, 0xFFFF_FFFF, 4)
        resps[DMA_NEXT_ID_0] = await self._write_any("NEXT_ID_0_WR", DMA_NEXT_ID_0, 1, 4)
        resps[DMA_DONE_0] = await self._write_any("DONE_0_WR", DMA_DONE_0, 0xFFFF_FFFF, 4)
        resps[ZER_CTRL_STATUS] = await self._write_any("ZER_CS_WR", ZER_CTRL_STATUS, 1 << 32, 8)
        after = {
            DMA_STATUS_0: await self.csr_read("STATUS_0_AFTER", DMA_STATUS_0),
            DMA_DONE_0: await self.csr_read("DONE_0_AFTER", DMA_DONE_0),
            ZER_CTRL_STATUS: await self.csr_read("ZER_CS_AFTER", ZER_CTRL_STATUS, length=8),
        }
        for name, addr, _data, _len in probes:
            out.append(
                f"{name} 0x{addr:08x} write {AXI_RESP_NAME.get(resps[addr])} "
                f"before=0x{before[addr]:x} after=0x{after[addr]:x}"
            )
        out.append(
            f"NEXT_ID_0 0x{DMA_NEXT_ID_0:08x} write {AXI_RESP_NAME.get(resps[DMA_NEXT_ID_0])} "
            f"(never read; DONE_0 0x{done_before:x}->0x{after[DMA_DONE_0]:x})"
        )
        self._mark("S7")
        return (
            "all writes completed (owner value pending, response and effect measured not "
            "asserted); " + ("; ".join(out))
        )

    async def body(self) -> None:
        await self._s1()
        self._chk("S2", "CHK-ACCEL-WIN-NO-ALIAS", await self._s2())
        self._chk("S3", "CHK-ACCEL-WIN-FIRST-LAST", await self._s3())
        self._chk("S4", "CHK-ACCEL-WIN-HOLES", await self._s4())
        self._chk("S5", "CHK-ACCEL-WIN-DECERR-NEIGHBOURS", await self._s5())
        self._chk("S6", "CHK-ACCEL-WIN-REGION-SIZE", await self._s6())
        self._chk("S7", "CHK-ACCEL-WIN-RO-WRITES", await self._s7())
        self._nonvac()

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, every step stamp later "
            "than the previous one, each line printed after its own compare; checker lines %s; "
            "stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
