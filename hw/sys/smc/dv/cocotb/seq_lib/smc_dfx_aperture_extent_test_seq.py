# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""dfx_ctrl register addresses, past-extent DECERR and the gap at offset 0xC.

Spec: smc.rdl dfx_ctrl placement, dfx_ctrl_status.rdl address map, memmap.adoc address space.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    DFX_MBIST_DONE,
    DFX_MBIST_PASS,
    DFX_MEM_REPAIR_DONE,
    DFX_MEM_REPAIR_SUCCESS,
    _component_row,
    generated_past_extent_resp,
    generated_window,
    smc_addr,
)
from .smc_csr_seq_utils import ALL_ONES_WORD, SmcCsrSeq

_FUSE_SENSE_MAX_CYCLES = 200_000
_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "REGISTERS_OKAY",
    "S3": "PAST_READS_DECERR",
    "S4": "PAST_WRITES_DECERR_NO_EFFECT",
    "S5": "NEXT_BLOCK_DECERR",
    "S6": "HOLE_OKAY_ZERO",
    "S7": "CLOCK_EDGE",
}
_STEPS = tuple(_TERMS)
RESP_CODES = {"OKAY": 0, "EXOKAY": 1, "SLVERR": 2, "DECERR": 3}
_RESP_NAMES = {code: name for name, code in RESP_CODES.items()}
_IDLE_MASK = DFX_MEM_REPAIR_DONE | DFX_MEM_REPAIR_SUCCESS | DFX_MBIST_DONE | DFX_MBIST_PASS
_ABORT_PINS = ("tb_mem_repair_abort", "tb_mbist_abort")
# memmap.adoc: a read between unit apertures answers DECERR with this data word.
DEADSPACE_RDATA = 0xBADCAB1E
DEBUG_CTRL_PATTERN = 0x2A5A5A5A
DEBUG_BUS_MUX_PATTERN = 0x0123456789ABCDEF


def observed_idle_word(dut) -> int:
    """STATUS_SMU idle word: the four done and pass bits, with both abort pins required at 0."""
    for pin in _ABORT_PINS:
        assert int(getattr(dut, pin).value) == 0, f"{pin} is 1 where the idle word is read"
    return _IDLE_MASK


DFX_BASE = smc_addr("SMC_TOP_DFX_CTRL_BASE_ADDR")
DFX_EXTENT = smc_addr("SMC_TOP_DFX_CTRL_SIZE")
_DFX_FIRST, _DFX_LAST = generated_window("dfx_ctrl")
DFX_APERTURE = _DFX_LAST - _DFX_FIRST + 1
_DFX_ROW = _component_row("dfx_ctrl")
PAST_RRESP, PAST_BRESP = (RESP_CODES[n] for n in generated_past_extent_resp("dfx_ctrl"))
PAST_RDATA = _DFX_ROW["past_response"]["rdata"]
_HOLE_ROW = _DFX_ROW["hole_responses"][0][1]
HOLE_RRESP = RESP_CODES[_HOLE_ROW["rresp"]]
HOLE_RDATA = _HOLE_ROW["rdata"]
DFX_STATUS_SMU_ADDR = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
DFX_DEBUG_CTRL_ADDR = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR")
DFX_DEBUG_BUS_MUX_ADDR = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR")
HOLE_ADDR = DFX_DEBUG_CTRL_ADDR + 4
PAST_EXTENT_ADDR = DFX_BASE + DFX_EXTENT
PAST_MID_ADDR = DFX_BASE + 0x100
PAST_LAST_ADDR = DFX_BASE + DFX_APERTURE - 4
NEXT_BLOCK_ADDR = DFX_BASE + DFX_APERTURE


class smc_dfx_aperture_extent_test_seq(SmcCsrSeq):
    """Register reads, past-extent reads and writes, next block, gap."""

    def __init__(self, name: str = "smc_dfx_aperture_extent_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, float]] = []
        self._chk_lines: list[tuple[str, str]] = []
        self.hole_resp: int | None = None
        self.hole_data: int | None = None

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, get_sim_time("ps")))

    def _chk(self, chk_id: str, step: str, text: str) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id}: printed before {step} completed (last stamp {self._stamps[-1:]})"
        )
        self._chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _read_regs(self) -> tuple[int, int, int]:
        status = await self.csr_read(
            "STATUS_SMU", DFX_STATUS_SMU_ADDR, expected=observed_idle_word(cocotb.top), length=8
        )
        ctrl = await self.csr_read("DEBUG_CTRL", DFX_DEBUG_CTRL_ADDR, expected=0, length=4)
        mux = await self.csr_read("DEBUG_BUS_MUX", DFX_DEBUG_BUS_MUX_ADDR, expected=0, length=8)
        return status, ctrl, mux

    async def body(self) -> None:
        await self.wait_fuse_sense_done(_FUSE_SENSE_MAX_CYCLES)
        self._stamp("S1")

        idle = observed_idle_word(cocotb.top)
        status, ctrl, mux = await self._read_regs()
        assert status == idle, f"STATUS_SMU=0x{status:x} want 0x{idle:x}"
        assert ctrl == 0 and mux == 0, f"DEBUG_CTRL=0x{ctrl:x} DEBUG_BUS_MUX=0x{mux:x} want 0"
        await self.csr_write("DEBUG_CTRL_WR", DFX_DEBUG_CTRL_ADDR, DEBUG_CTRL_PATTERN, length=4)
        await self.csr_read(
            "DEBUG_CTRL_RB", DFX_DEBUG_CTRL_ADDR, expected=DEBUG_CTRL_PATTERN, length=4
        )
        await self.csr_write(
            "DEBUG_BUS_MUX_WR", DFX_DEBUG_BUS_MUX_ADDR, DEBUG_BUS_MUX_PATTERN, length=8
        )
        await self.csr_read(
            "DEBUG_BUS_MUX_RB", DFX_DEBUG_BUS_MUX_ADDR, expected=DEBUG_BUS_MUX_PATTERN, length=8
        )
        await self.csr_write("DEBUG_CTRL_CLR", DFX_DEBUG_CTRL_ADDR, 0, length=4)
        await self.csr_read("DEBUG_CTRL_CLR_RB", DFX_DEBUG_CTRL_ADDR, expected=0, length=4)
        await self.csr_write("DEBUG_BUS_MUX_CLR", DFX_DEBUG_BUS_MUX_ADDR, 0, length=8)
        await self.csr_read("DEBUG_BUS_MUX_CLR_RB", DFX_DEBUG_BUS_MUX_ADDR, expected=0, length=8)
        self._stamp("S2")
        self._chk(
            "CHK-APERTURE-REGISTERS",
            "S2",
            f"STATUS_SMU@0x{DFX_STATUS_SMU_ADDR:x}=0x{status:x} (idle word), "
            f"DEBUG_CTRL@0x{DFX_DEBUG_CTRL_ADDR:x}=0x{ctrl:x}, "
            f"DEBUG_BUS_MUX@0x{DFX_DEBUG_BUS_MUX_ADDR:x}=0x{mux:x}, all OKAY; DEBUG_CTRL "
            f"0x{DEBUG_CTRL_PATTERN:x} and DEBUG_BUS_MUX 0x{DEBUG_BUS_MUX_PATTERN:x} read back "
            "exactly, then cleared",
        )

        past_reads = []
        for label, addr in (
            ("PAST_EXTENT", PAST_EXTENT_ADDR),
            ("PAST_MID", PAST_MID_ADDR),
            ("PAST_LAST", PAST_LAST_ADDR),
        ):
            item = await self._read_item(label, addr)
            data = item.rdata & 0xFFFFFFFF
            assert item.resp_code == PAST_RRESP and data == PAST_RDATA, (
                f"{label} @ 0x{addr:08x}: resp={item.resp_code} data=0x{data:08x}, "
                f"want resp={PAST_RRESP} data=0x{PAST_RDATA:08x}"
            )
            past_reads.append(f"0x{addr:x}->{_RESP_NAMES[item.resp_code]} data=0x{data:08x}")
        self._stamp("S3")
        self._chk(
            "CHK-APERTURE-PAST-READ",
            "S3",
            f"{'; '.join(past_reads)}; each answered with the generated past-extent response "
            f"and data 0x{PAST_RDATA:08x}",
        )

        past_writes = []
        for label, addr in (("PAST_EXTENT_WR", PAST_EXTENT_ADDR), ("PAST_LAST_WR", PAST_LAST_ADDR)):
            resp = await self.csr_write_expect_error(label, addr, ALL_ONES_WORD, resp=PAST_BRESP)
            past_writes.append(f"0x{addr:x}->{_RESP_NAMES[resp]}")
        status2, ctrl2, mux2 = await self._read_regs()
        assert (status2, ctrl2, mux2) == (status, ctrl, mux), (
            f"registers changed by past-extent writes: "
            f"STATUS_SMU 0x{status:x}->0x{status2:x}, DEBUG_CTRL 0x{ctrl:x}->0x{ctrl2:x}, "
            f"DEBUG_BUS_MUX 0x{mux:x}->0x{mux2:x}"
        )
        self._stamp("S4")
        self._chk(
            "CHK-APERTURE-PAST-WRITE",
            "S4",
            f"{'; '.join(past_writes)}; STATUS_SMU=0x{status2:x} DEBUG_CTRL=0x{ctrl2:x} "
            f"DEBUG_BUS_MUX=0x{mux2:x} equal to their earlier values",
        )

        next_item = await self._read_item("NEXT_BLOCK", NEXT_BLOCK_ADDR)
        assert (
            next_item.resp_code == RESP_CODES["DECERR"]
            and next_item.rdata & 0xFFFFFFFF == DEADSPACE_RDATA
        ), (
            f"read @0x{NEXT_BLOCK_ADDR:x}: resp={next_item.resp_code} "
            f"rdata=0x{next_item.rdata:x}, want DECERR 0x{DEADSPACE_RDATA:08x}"
        )
        self._stamp("S5")
        self._chk(
            "CHK-APERTURE-NEXT-BLOCK",
            "S5",
            f"read @0x{NEXT_BLOCK_ADDR:x} answered DECERR carrying 0x{next_item.rdata:x}",
        )

        hole = await self._read_item("HOLE", HOLE_ADDR)
        assert hole.resp_code == HOLE_RRESP and hole.rdata == HOLE_RDATA, (
            f"hole @0x{HOLE_ADDR:x}: resp={hole.resp_code} rdata=0x{hole.rdata:x}, "
            f"want {_RESP_NAMES[HOLE_RRESP]} 0x{HOLE_RDATA:x} (generated map Hole in Extent)"
        )
        self.hole_resp = hole.resp_code
        self.hole_data = hole.rdata
        self._stamp("S6")
        self._chk(
            "CHK-APERTURE-HOLE",
            "S6",
            f"read @0x{HOLE_ADDR:x} (offset 0xc) resp={_RESP_NAMES.get(hole.resp_code)} "
            f"data=0x{hole.rdata:x} matches the generated Hole in Extent answer",
        )

        await RisingEdge(cocotb.top.clk_smc_i)
        self._stamp("S7")
        bound_ns = self.env.cfg.axi_timeout_ns
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 2 bounded waits: sep_in_axi_access=%dns "
            "fail-on-expiry=driver raises, last=%s fuse_sense=%dcycles "
            "fail-on-expiry=AssertionError, last=tb_fuse_sense_done high",
            bound_ns,
            f"hole resp={_RESP_NAMES.get(hole.resp_code)}",
            _FUSE_SENSE_MAX_CYCLES,
        )
        self._finish_fence()

    async def _read_item(self, name: str, addr: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"read @0x{addr:x}: no response code"
        return item

    def _finish_fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert steps == list(_STEPS), f"step order {steps} want {list(_STEPS)}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_steps = [s for _, s in self._chk_lines]
        assert chk_steps == sorted(chk_steps), f"checker lines out of order: {self._chk_lines}"
        ids = [c for c, _ in self._chk_lines]
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(_TERMS[s] for s, _ in self._stamps),
            ",".join(ids),
            ",".join(f"{s}={t:.0f}" for s, t in self._stamps),
        )
