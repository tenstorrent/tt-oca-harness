# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound address, size and length on smu_axi_out, from the two SMC masters a bench can drive.

The SMU crossbar connects ``smc_out`` and ``sep_out`` to ``ext_out`` and gives
``ext_in`` no path there (``hw/sys/smu/doc/index.adoc``), so what
leaves the chiplet on ``smu_axi_out`` is issued by the SMC or the SEP. Without
firmware two SMC masters can be driven from the bench: the JTAG2AXI bridge,
whose single operation carries the programmed address and uses its size field
as AxSIZE (``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``, "JTAG2AXI
single-operation fields"), and the iDMA register frontend, which moves LENGTH
bytes from SRC_ADDRESS to DST_ADDRESS (``dma_ctrl.rdl``). Neither document
states the AxLEN or AxBURST the master drives, or what the iDMA CONFIG fields
do (``dma_ctrl.rdl`` describes each as "Not used"), so burst lengths and
types are recorded rather than compared. An SMC address outside the SMC local
window and the SEP aperture leaves on ``smu_axi_out``.

S1: JTAG2AXI writes 1, 2, 4 and 8 bytes at two 56-bit addresses whose upper
    bits are the 0xAA.. and 0x55.. patterns, and 1, 2 and 4 bytes at byte
    offsets 1, 2, 4, 7 and 6 of one doubleword, then reads each back. Each
    transfer crosses the boundary once with the address and AxSIZE the bridge
    was given, the bench responder holds the bytes written, and the read
    returns them; AxLEN and AxBURST are recorded.
S2: the iDMA copies a 2 KiB block between two addresses outside both
    apertures. The destination holds the source bytes, DONE reports the id
    the launch was given, and the burst lengths and types that carry the
    copy across the boundary are recorded.
S3: the same copy while the bench responder stalls every AW, W and AR
    handshake. The copy still completes with the destination holding the
    source bytes, so the boundary READY stalls lose nothing.
S3 sets CONFIG src/dst_reduce_len with max_llen 0, and the number of address
    phases the copy takes is recorded. A second copy
    stalls only the write handshakes, and longer, so the write addresses the
    iDMA issues as read data returns queue at the boundary; it completes too.
S5: the zeroer (``zeroer_ctrl`` register description) writes zeros over a
    block outside both apertures; the boundary carries writes covering it and
    the responder holds zeros there.
S6: the M-mode and Xvisor output remaps (``output_remap`` register
    description, 1 MiB regions) put region 0 of their windows at a programmed
    target; a JTAG2AXI write and read of region 0 cross the boundary once each
    at the target and read back, and a write and read outside both windows
    then leave by the default path at their own address.
S4: a one-shot SLVERR and DECERR from the responder on a JTAG2AXI read and
    write each reach the bridge as that response (the single-operation op
    field reads 1 for SLVERR and 2 for DECERR, ``architecture.adoc``), and the
    next access at the address succeeds.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import _REPO_ROOT, c_header_u32, smc_addr, smc_indexed_addr
from seq_lib.smu_filter_helpers import program_outbound0_pass_all
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_DECERR,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

ADDR_MASK = (1 << 56) - 1
OUT_A = 0xAA_AAAA_AAAA_AAA0 & ADDR_MASK
OUT_B = 0x55_5555_5555_5550 & ADDR_MASK
SIZES = (0, 1, 2, 3)
# (AxSIZE, byte offset) pairs inside one doubleword.
UNALIGNED = ((0, 1), (1, 2), (2, 4), (0, 7), (1, 6))
PATTERN = 0x8877_6655_4433_2211

DMA_CONFIG = smc_addr("SMC_TOP_DMA_CTRL_CONFIG_BASE_ADDR")
DMA_STATUS_0 = smc_addr("SMC_TOP_DMA_CTRL_STATUS_0_BASE_ADDR")
DMA_NEXT_ID_0 = smc_addr("SMC_TOP_DMA_CTRL_NEXT_ID_0_BASE_ADDR")
DMA_DONE_0 = smc_addr("SMC_TOP_DMA_CTRL_DONE_0_BASE_ADDR")
DMA_DST_LO = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
DMA_DST_HI = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_HI_BASE_ADDR")
DMA_SRC_LO = smc_addr("SMC_TOP_DMA_CTRL_SRC_ADDRESS_LO_BASE_ADDR")
DMA_SRC_HI = smc_addr("SMC_TOP_DMA_CTRL_SRC_ADDRESS_HI_BASE_ADDR")
DMA_LEN_LO = smc_addr("SMC_TOP_DMA_CTRL_LENGTH_LO_BASE_ADDR")
DMA_LEN_HI = smc_addr("SMC_TOP_DMA_CTRL_LENGTH_HI_BASE_ADDR")
DMA_SRC = 0x0200_0000
DMA_DST = 0x0300_0000
DMA_STALLED_SRC = 0x0400_0000
DMA_STALLED_DST = 0x0500_0000
BACKPRESSURE_STALL = 6
WRITE_STALL = 24
WRITE_STALL_OFFSET = 0x10000
AXI_RESP_SLVERR = 2
AXI_RESP_DECERR = 3
DMA_DST_STRIDE_LO = smc_addr("SMC_TOP_DMA_CTRL_DST_STRIDE_LO_BASE_ADDR")
DMA_DST_STRIDE_HI = smc_addr("SMC_TOP_DMA_CTRL_DST_STRIDE_HI_BASE_ADDR")
DMA_SRC_STRIDE_LO = smc_addr("SMC_TOP_DMA_CTRL_SRC_STRIDE_LO_BASE_ADDR")
DMA_SRC_STRIDE_HI = smc_addr("SMC_TOP_DMA_CTRL_SRC_STRIDE_HI_BASE_ADDR")
DMA_REPS_LO = smc_addr("SMC_TOP_DMA_CTRL_NUM_REPETITIONS_LO_BASE_ADDR")
DMA_REPS_HI = smc_addr("SMC_TOP_DMA_CTRL_NUM_REPETITIONS_HI_BASE_ADDR")
_DMA_CTRL_H = _REPO_ROOT / "vendor/pulp-platform/idma/overlay/rdl/gen/c/dma_ctrl.h"
_ZEROER_H = _REPO_ROOT / "hw/ip/zeroer/regs/gen/c/zeroer_ctrl.h"
DMA_CONFIG_ENABLE_ND = c_header_u32(_DMA_CTRL_H, "DMA_CTRL__CONFIG__ENABLED_ND_bm")
DMA_CONFIG_SINGLE_BEAT = (
    DMA_CONFIG_ENABLE_ND
    | c_header_u32(_DMA_CTRL_H, "DMA_CTRL__CONFIG__SRC_REDUCE_LEN_bm")
    | c_header_u32(_DMA_CTRL_H, "DMA_CTRL__CONFIG__DST_REDUCE_LEN_bm")
)
ZEROER_DEST = smc_addr("SMC_TOP_ZEROER_CTRL_BASE_ADDR")
ZEROER_SIZE = smc_addr("SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR")
ZEROER_CTRL = smc_addr("SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR")
ZEROER_BUSY = c_header_u32(_ZEROER_H, "ZEROER_CTRL__CTRL_STATUS__STATUS_bm")
ZEROER_TARGET = 0x0600_0000
ZEROER_LENGTH = 0x200
MMODE_WINDOW = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR")
XVISOR_WINDOW = smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR")
MMODE_REMAP_0 = smc_indexed_addr("SMC_TOP_SMC_MMODE_REMAP_REGION_BASE_ADDR", 0)
XVISOR_REMAP_0 = smc_indexed_addr("SMC_TOP_SMC_XVISOR_REMAP_REGION_BASE_ADDR", 0)
_OUTPUT_REMAP_H = _REPO_ROOT / "hw/ip/output_remap/regs/gen/c/output_remap.h"
OUTPUT_REMAP_VALID = c_header_u32(
    _OUTPUT_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__VALID_bm"
)
# Output remap targets: 1 MiB aligned (the SMC region granularity in the
# output_remap description), outside both apertures.
MMODE_TARGET = 0x0700_0000
XVISOR_TARGET = 0x0710_0000
DMA_LENGTH = 0x800
DMA_DONE_POLLS = 400
DMA_POLL_CYCLES = 64
EGRESS_POLL_CYCLES = 4000


class _OutboundTap:
    """Every address phase and write beat on the outbound boundary interface."""

    def __init__(self, dut) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self.aw: list[tuple[int, int, int, int, int]] = []
        self.ar: list[tuple[int, int, int, int, int]] = []
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    def _phase(self, ch: str) -> tuple[int, int, int, int, int]:
        return tuple(self._int(f"{ch}{f}") for f in ("addr", "len", "size", "burst", "id"))

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self._int("awvalid") and self._int("awready"):
                self.aw.append(self._phase("aw"))
            if self._int("arvalid") and self._int("arready"):
                self.ar.append(self._phase("ar"))

    def mark(self) -> tuple[int, int]:
        return len(self.aw), len(self.ar)

    def since(self, mark: tuple[int, int]):
        return self.aw[mark[0] :], self.ar[mark[1] :]

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class smu_axi_out_addr_len_size_test_seq:
    """Outbound address, AxSIZE and AxLEN from JTAG2AXI and the iDMA."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False
        self.s5_ok = False
        self.s6_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _pin(self, name: str) -> int:
        val = getattr(self.dut, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str, **kwargs) -> None:
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True, **kwargs)
        require_jtag_tdo_resolved(f"J2A WR {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:014x} status={st} want SUCCESS")

    async def _j2a_rd(self, jtag, addr: int, name: str, **kwargs) -> int:
        st, rdata = await jtag2axi_single_read(jtag, addr, require_complete=True, **kwargs)
        require_jtag_tdo_resolved(f"J2A RD {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:014x} status={st} want SUCCESS")
        return int(rdata)

    async def _j2a_wr32(self, jtag, addr: int, data: int, name: str) -> None:
        word = int(data) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        await self._j2a_wr(jtag, addr, packed, name, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)

    async def _j2a_rd32(self, jtag, addr: int, name: str) -> int:
        raw = await self._j2a_rd(jtag, addr, name, size=SMC_DBG_AXSIZE_4B)
        return (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF

    async def _bring_up_tap(self):
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._pin("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC J2A still gated after TCK sync")
        return jtag

    async def _await_counts(self, writes: int, reads: int, label: str) -> None:
        for _ in range(EGRESS_POLL_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            if (
                self._pin("smu_axi_out_write_count_o") >= writes
                and self._pin("smu_axi_out_read_count_o") >= reads
            ):
                return
        raise AssertionError(
            f"TIMEOUT {label}: outbound counts write={self._pin('smu_axi_out_write_count_o')} "
            f"read={self._pin('smu_axi_out_read_count_o')} want >= ({writes}, {reads})"
        )

    async def _step_single(self, jtag, sb, tap) -> None:
        """S1: every AxSIZE at two 56-bit addresses, written, held and read back."""
        phases, held, readback, bursts = {}, {}, {}, {}
        want_phases, want_held, want_rb = {}, {}, {}
        cells = [(base + 8 * size, size, 0) for base in (OUT_A, OUT_B) for size in SIZES]
        # Byte offsets inside one doubleword, so each of address bits [2:0] rises and falls.
        cells += [(OUT_B + 0x40 + off, size, off) for size, off in UNALIGNED]
        for addr, size, off in cells:
            nbytes = 1 << size
            cell = f"0x{addr:014x}/size{size}"
            value = PATTERN & ((1 << (8 * nbytes)) - 1)
            mark = tap.mark()
            w0 = self._pin("smu_axi_out_write_count_o")
            r0 = self._pin("smu_axi_out_read_count_o")
            await self._j2a_wr(
                jtag,
                addr,
                value << (8 * off),
                f"S1_WR_{cell}",
                wstrb=((1 << nbytes) - 1) << off,
                size=size,
            )
            await self._await_counts(w0 + 1, r0, f"s1_write_{cell}")
            rdata = await self._j2a_rd(jtag, addr, f"S1_RD_{cell}", size=size) >> (8 * off)
            await self._await_counts(w0 + 1, r0 + 1, f"s1_read_{cell}")
            aw, ar = tap.since(mark)
            phases[cell] = ([(p[0], p[2]) for p in aw], [(p[0], p[2]) for p in ar])
            want_phases[cell] = ([(addr, size)],) * 2
            bursts[cell] = ([p[1] for p in aw + ar], [p[3] for p in aw + ar])
            held[cell] = self.cfg.axi_out_mem.read_int(addr, nbytes)
            want_held[cell] = value
            readback[cell] = rdata & ((1 << (8 * nbytes)) - 1)
            want_rb[cell] = value
            self._log(f"CHK-AXIOUT-SIZE cell {cell} aw={aw} ar={ar} held=0x{held[cell]:x}")

        self._log(f"OBSERVATION CHK-AXIOUT-SIZE (AxLEN, AxBURST) per cell {bursts}")
        sb.expect_eq(
            "CHK-AXIOUT-SIZE each JTAG2AXI write and read crossed smu_axi_out once with its "
            "address and AxSIZE",
            phases,
            want_phases,
            evidence="CHK-AXIOUT-SIZE",
        )
        sb.expect_eq(
            "CHK-AXIOUT-SIZE the bench responder holds every byte written", held, want_held
        )
        sb.expect_eq("CHK-AXIOUT-SIZE every read returns the bytes written", readback, want_rb)
        self.s1_ok = True

    async def _dma_copy(
        self, jtag, sb, tap, src: int, dst: int, seed: int, config: int = DMA_CONFIG_ENABLE_ND
    ):
        """Copy DMA_LENGTH bytes src->dst with the iDMA; return (done, id, payload, aw, ar)."""
        payload = bytes((i * 37 + seed) & 0xFF for i in range(DMA_LENGTH))
        self.cfg.axi_out_mem.write(src, payload)
        self.cfg.axi_out_mem.write(dst, bytes(DMA_LENGTH))
        await self._j2a_wr32(jtag, DMA_CONFIG, config, "DMA_CONFIG")
        for addr, value, name in (
            (DMA_DST_LO, dst & 0xFFFF_FFFF, "DMA_DST_LO"),
            (DMA_DST_HI, dst >> 32, "DMA_DST_HI"),
            (DMA_SRC_LO, src & 0xFFFF_FFFF, "DMA_SRC_LO"),
            (DMA_SRC_HI, src >> 32, "DMA_SRC_HI"),
            (DMA_LEN_LO, DMA_LENGTH, "DMA_LEN_LO"),
            (DMA_LEN_HI, 0, "DMA_LEN_HI"),
            (DMA_DST_STRIDE_LO, 0, "DMA_DST_STRIDE_LO"),
            (DMA_DST_STRIDE_HI, 0, "DMA_DST_STRIDE_HI"),
            (DMA_SRC_STRIDE_LO, 0, "DMA_SRC_STRIDE_LO"),
            (DMA_SRC_STRIDE_HI, 0, "DMA_SRC_STRIDE_HI"),
            (DMA_REPS_LO, 1, "DMA_REPS_LO"),
            (DMA_REPS_HI, 0, "DMA_REPS_HI"),
        ):
            await self._j2a_wr32(jtag, addr, value, name)
        baseline_done = await self._j2a_rd32(jtag, DMA_DONE_0, "DMA_DONE_BASELINE")
        mark = tap.mark()
        # Reading NEXT_ID submits the programmed descriptor; it is read once.
        start_id = await self._j2a_rd32(jtag, DMA_NEXT_ID_0, "DMA_NEXT_ID_LAUNCH")
        done = baseline_done
        for _ in range(DMA_DONE_POLLS):
            await ClockCycles(self.dut.clk_smu_i, DMA_POLL_CYCLES)
            done = await self._j2a_rd32(jtag, DMA_DONE_0, "DMA_DONE_POLL")
            if done == start_id:
                break
        aw, ar = tap.since(mark)
        return done, start_id, payload, aw, ar

    async def _step_dma(self, jtag, sb, tap) -> None:
        """S2: an iDMA copy crosses the boundary as INCR bursts up to AxLEN 255."""
        await program_outbound0_pass_all(jtag, scoreboard=sb)
        done, start_id, payload, aw, ar = await self._dma_copy(jtag, sb, tap, DMA_SRC, DMA_DST, 11)
        dst = self.cfg.axi_out_mem.read(DMA_DST, DMA_LENGTH)
        status = await self._j2a_rd32(jtag, DMA_STATUS_0, "DMA_STATUS")
        self._log(
            f"CHK-AXIOUT-LEN: start_id={start_id} done={done} status=0x{status:x} "
            f"aw={[(hex(p[0]), p[1], p[2]) for p in aw]} ar={[(hex(p[0]), p[1], p[2]) for p in ar]}"
        )
        sb.expect_eq("CHK-AXIOUT-LEN DONE reports the id the launch was given", done, start_id)
        sb.expect_eq(
            "CHK-AXIOUT-LEN the destination holds the source block", dst.hex(), payload.hex()
        )
        read_bytes = sum((p[1] + 1) << p[2] for p in ar if DMA_SRC <= p[0] < DMA_SRC + DMA_LENGTH)
        write_bytes = sum((p[1] + 1) << p[2] for p in aw if DMA_DST <= p[0] < DMA_DST + DMA_LENGTH)
        self._log(
            f"OBSERVATION CHK-AXIOUT-LEN AxBURST={sorted({p[3] for p in ar + aw})} "
            f"longest AxLEN={max((p[1] for p in ar + aw), default=-1)}"
        )
        sb.expect_eq(
            "CHK-AXIOUT-LEN the boundary carried bursts covering the block both ways",
            (read_bytes, write_bytes),
            (DMA_LENGTH, DMA_LENGTH),
            evidence="CHK-AXIOUT-LEN",
        )
        self.s2_ok = True

    async def _step_backpressure(self, jtag, sb, tap) -> None:
        """S3: the S2 copy through a responder that stalls every address and write handshake."""
        self.cfg.axi_out_mem.enable_backpressure(
            channels=("aw", "w", "ar"), stall_cycles=BACKPRESSURE_STALL
        )
        try:
            done, start_id, payload, aw, ar = await self._dma_copy(
                jtag, sb, tap, DMA_STALLED_SRC, DMA_STALLED_DST, 23, DMA_CONFIG_SINGLE_BEAT
            )
        finally:
            self.cfg.axi_out_mem.disable_backpressure()
        dst = self.cfg.axi_out_mem.read(DMA_STALLED_DST, DMA_LENGTH)
        # Reads run freely and writes stall longer, so the write addresses the
        # iDMA issues as read data returns queue at the boundary.
        self.cfg.axi_out_mem.enable_backpressure(channels=("aw", "w"), stall_cycles=WRITE_STALL)
        try:
            done_w, start_w, payload_w, aw_w, ar_w = await self._dma_copy(
                jtag,
                sb,
                tap,
                DMA_STALLED_SRC + WRITE_STALL_OFFSET,
                DMA_STALLED_DST + WRITE_STALL_OFFSET,
                29,
                DMA_CONFIG_SINGLE_BEAT,
            )
        finally:
            self.cfg.axi_out_mem.disable_backpressure()
        dst_w = self.cfg.axi_out_mem.read(DMA_STALLED_DST + WRITE_STALL_OFFSET, DMA_LENGTH)
        self._log(
            f"CHK-AXIOUT-BACKPRESSURE: start_id={start_id} done={done} "
            f"write-stalled start_id={start_w} done={done_w}"
        )
        self._log(
            f"OBSERVATION CHK-AXIOUT-BACKPRESSURE address phases aw={len(aw)} ar={len(ar)} "
            f"AxLEN={sorted({p[1] for p in ar + aw})}; write-stalled aw={len(aw_w)} "
            f"ar={len(ar_w)}"
        )
        sb.expect_eq(
            "CHK-AXIOUT-BACKPRESSURE",
            ((done, dst.hex()), (done_w, dst_w.hex())),
            ((start_id, payload.hex()), (start_w, payload_w.hex())),
            evidence="CHK-AXIOUT-BACKPRESSURE",
        )
        self.s3_ok = True

    async def _step_errors(self, jtag, sb) -> None:
        """S4: responder SLVERR and DECERR on a read and a write reach JTAG2AXI as that status."""
        mem = self.cfg.axi_out_mem
        observed, want = {}, {}
        for resp, status, name in (
            (AXI_RESP_SLVERR, J2A_STATUS_SLVERR, "SLVERR"),
            (AXI_RESP_DECERR, J2A_STATUS_DECERR, "DECERR"),
        ):
            addr = OUT_A + 0x100 + 8 * resp
            mem.inject_error(addr, resp, read=True, write=False)
            rd_st, _ = await jtag2axi_single_read(jtag, addr, require_complete=True, size=3)
            mem.inject_error(addr, resp, read=False, write=True)
            wr_st, _ = await jtag2axi_single_write(
                jtag, addr, PATTERN, require_complete=True, wstrb=0xFF, size=3
            )
            await self._j2a_wr(jtag, addr, PATTERN, f"S4_{name}_WR", wstrb=0xFF, size=3)
            after = await self._j2a_rd(jtag, addr, f"S4_{name}_RD", size=3)
            observed[name] = (rd_st, wr_st, after)
            want[name] = (status, status, PATTERN)
        mem.clear_errors()
        self._log(f"CHK-AXIOUT-ERROR-RESP {observed}")
        sb.expect_eq("CHK-AXIOUT-ERROR-RESP", observed, want, evidence="CHK-AXIOUT-ERROR-RESP")
        self.s4_ok = True

    async def _step_zeroer(self, jtag, sb, tap) -> None:
        """S5: the zeroer writes zeros to an address outside both apertures."""
        mem = self.cfg.axi_out_mem
        mem.write(ZEROER_TARGET, bytes([0xA5]) * ZEROER_LENGTH)
        mark = tap.mark()
        await self._j2a_wr(jtag, ZEROER_DEST, ZEROER_TARGET, "ZEROER_DEST")
        await self._j2a_wr(jtag, ZEROER_SIZE, ZEROER_LENGTH, "ZEROER_SIZE")
        await self._j2a_wr(jtag, ZEROER_CTRL, 0, "ZEROER_CTRL")
        busy = ZEROER_BUSY
        for _ in range(DMA_DONE_POLLS):
            await ClockCycles(self.dut.clk_smu_i, DMA_POLL_CYCLES)
            busy = await self._j2a_rd(jtag, ZEROER_CTRL, "ZEROER_STATUS") & ZEROER_BUSY
            if not busy:
                break
        aw, _ = tap.since(mark)
        written = sum(
            (p[1] + 1) << p[2] for p in aw if ZEROER_TARGET <= p[0] < ZEROER_TARGET + ZEROER_LENGTH
        )
        self._log(f"CHK-AXIOUT-ZEROER busy={busy} bytes={written} aw={len(aw)}")
        sb.expect_eq(
            "CHK-AXIOUT-ZEROER",
            (busy, written, mem.read(ZEROER_TARGET, ZEROER_LENGTH)),
            (0, ZEROER_LENGTH, bytes(ZEROER_LENGTH)),
            evidence="CHK-AXIOUT-ZEROER",
        )
        self.s5_ok = True

    async def _step_output_remap(self, jtag, sb, tap) -> None:
        """S6: M-mode and Xvisor output remap region 0 put the window at a programmed target."""
        mem = self.cfg.axi_out_mem
        observed, want = {}, {}
        for name, csr, window, target in (
            ("MMODE", MMODE_REMAP_0, MMODE_WINDOW, MMODE_TARGET),
            ("XVISOR", XVISOR_REMAP_0, XVISOR_WINDOW, XVISOR_TARGET),
        ):
            await self._j2a_wr(jtag, csr, OUTPUT_REMAP_VALID | target, f"{name}_REMAP_0")
            value = (PATTERN ^ target) & ((1 << 64) - 1)
            mark = tap.mark()
            await self._j2a_wr(jtag, window + 8, value, f"{name}_WR")
            rdata = await self._j2a_rd(jtag, window + 8, f"{name}_RD")
            aw, ar = tap.since(mark)
            await self._j2a_wr(jtag, csr, 0, f"{name}_REMAP_0_CLEAR")
            observed[name] = (
                [p[0] for p in aw],
                [p[0] for p in ar],
                mem.read_int(target + 8, 8),
                rdata,
            )
            want[name] = ([target + 8], [target + 8], value, value)
        mark = tap.mark()
        await self._j2a_wr(jtag, OUT_A, PATTERN, "DEFAULT_WR")
        rdata = await self._j2a_rd(jtag, OUT_A, "DEFAULT_RD")
        aw, ar = tap.since(mark)
        observed["DEFAULT"] = ([p[0] for p in aw], [p[0] for p in ar], rdata)
        want["DEFAULT"] = ([OUT_A], [OUT_A], PATTERN)
        self._log(f"CHK-AXIOUT-OUTPUT-REMAP {observed}")
        sb.expect_eq("CHK-AXIOUT-OUTPUT-REMAP", observed, want, evidence="CHK-AXIOUT-OUTPUT-REMAP")
        self.s6_ok = True

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)
        jtag = await self._bring_up_tap()
        tap = _OutboundTap(dut)
        try:
            await self._step_single(jtag, sb, tap)
            await self._step_dma(jtag, sb, tap)
            await self._step_backpressure(jtag, sb, tap)
            await self._step_errors(jtag, sb)
            await self._step_zeroer(jtag, sb, tap)
            await self._step_output_remap(jtag, sb, tap)
        finally:
            tap.stop()
