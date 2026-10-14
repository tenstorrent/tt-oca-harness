# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA two-dimensional copy breadth through the SYS_OUT responder.

Specs hw/sys/smc/doc/dma.adoc, vendor idma overlay dma_ctrl.rdl.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. Every AR and AW handshake of the exported SYS_OUT probes is recorded.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dma_sanity_test_seq import (
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    DMA_CTRL_STATUS_0,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)

WINDOW = 0x0200_0000
CASE_SPAN = 0x2000
SENTINEL = 0xEE
POLL_LIMIT = 3000
POLL_CYCLES = 50
TWO_POW_56 = 1 << 56

S2_ROWS = 5
S2_LENGTH = 24
S2_SRC_STRIDE = 0x50
S2_DST_STRIDE = 0x38
S3_COUNTS = (1, 2, 3, 16)
S3_LENGTH = 20
S3_SRC_STRIDE = 0x40
S3_DST_STRIDE = 0x30
S4_ROWS = 4
S4_LENGTH = 13
S4_SRC_OFFSET = 3
S4_DST_OFFSET = 5
S4_STRIDE = 0x20
S5_ROWS = 8
S5_LENGTH = 16
S5_SRC_STRIDE = 0x30
S5_DST_STRIDE = 0x28
S6_ROWS = 3
S6_LENGTH = 16
# (name, source stride, destination stride, destination offset from the source base)
S6_CASES = (
    ("ZERO_BOTH", 0, 0, 0x400),
    ("ZERO_SRC", 0, 0x20, 0x400),
    ("ZERO_DST", 0x20, 0, 0x400),
    ("SHORT_BOTH", 8, 8, 0x400),
    ("SRC_DST_OVERLAP", 16, 16, 8),
)
S7_ROWS = 4
S7_LENGTH = 16
S7_SRC_STRIDE = 0x80
S7_DST_STRIDE = 0x100
S7_SRC_BASE = TWO_POW_56 - 0x80
S7_DST_BASE = TWO_POW_56 - 0x1C0

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_araddr",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_dma_busy",
)
_IF_SIGNALS = ("arlen", "arsize", "awlen", "awsize")


def _pattern(addr: int) -> int:
    return ((addr * 13) ^ (addr >> 7) ^ 0x3C) & 0xFF


class _Job:
    def __init__(
        self,
        name: str,
        src: int,
        dst: int,
        length: int,
        reps: int,
        src_stride: int,
        dst_stride: int,
    ) -> None:
        self.name = name
        self.src = src
        self.dst = dst
        self.length = length
        self.reps = reps
        self.src_stride = src_stride
        self.dst_stride = dst_stride
        self.id = -1
        self.ar: list[int] = []
        self.aw: list[int] = []


class _BurstSampler:
    """Records every AR and AW handshake address."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar: list[int] = []
        self.aw: list[int] = []

    @staticmethod
    def _bit(sig, name: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    async def run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            for ch, store in (("ar", self.ar), ("aw", self.aw)):
                valid = self._bit(getattr(dut, f"tb_output_axi_{ch}valid"), f"{ch}valid")
                ready = self._bit(getattr(dut, f"tb_output_axi_{ch}ready"), f"{ch}ready")
                if valid and ready:
                    store.append(self._bit(getattr(dut, f"tb_output_axi_{ch}addr"), f"{ch}addr"))


class smc_dma_2d_copy_test_seq(SmcCsrSeq):
    """2D copies with independent strides, row counts, unaligned rows and edge strides."""

    def __init__(self, name: str = "smc_dma_2d_copy_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.sampler: _BurstSampler | None = None
        self.last_done = 0
        self.next_id_reads = 0
        self.case = 0

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        self.chk_ids.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    def _busy(self) -> int:
        value = cocotb.top.tb_dma_busy.value
        assert value.is_resolvable, f"tb_dma_busy is X/Z ({value})"
        return int(value)

    def _case_base(self) -> int:
        base = WINDOW + self.case * CASE_SPAN
        self.case += 1
        return base

    async def _pass_all(self) -> None:
        for name, addr, value in (
            ("IN_START", INBOUND0_START, 0),
            ("IN_END", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("IN_CFG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("OUT_START", OUTBOUND0_START, 0),
            ("OUT_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"PASS_{name}", addr, value, length=8)

    @staticmethod
    def _src_rows(j: _Job) -> list[int]:
        return [j.src + n * j.src_stride for n in range(j.reps)]

    @staticmethod
    def _dst_rows(j: _Job) -> list[int]:
        return [j.dst + n * j.dst_stride for n in range(j.reps)]

    def _seed(self, j: _Job, dst_span: int) -> None:
        """Pattern every source row and fill the destination span with the sentinel."""
        for addr in self._src_rows(j):
            self._responder.write(addr, bytes(_pattern(addr + i) for i in range(j.length)))
        self._responder.write(j.dst, bytes([SENTINEL]) * dst_span)

    def _expected_image(self, j: _Job, dst_span: int) -> bytearray:
        image = bytearray([SENTINEL]) * dst_span
        for n, src in enumerate(self._src_rows(j)):
            off = n * j.dst_stride
            image[off : off + j.length] = bytes(_pattern(src + i) for i in range(j.length))
        return image

    def _compare_image(self, j: _Job, dst_span: int) -> None:
        want = bytes(self._expected_image(j, dst_span))
        got = bytes(self._responder.read(j.dst, dst_span))
        if got != want:
            idx = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
            raise AssertionError(
                f"{j.name}: destination byte 0x{j.dst + idx:x} (offset {idx}) is 0x{got[idx]:02x}, "
                f"want 0x{want[idx]:02x}; rows {j.reps} length {j.length} src stride "
                f"0x{j.src_stride:x} dst stride 0x{j.dst_stride:x}"
            )
        for addr in self._src_rows(j):
            src = bytes(self._responder.read(addr, j.length))
            want_src = bytes(_pattern(addr + i) for i in range(j.length))
            assert src == want_src, f"{j.name}: source row at 0x{addr:x} changed"

    async def _program(self, j: _Job) -> None:
        for reg, value in (
            (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            (DMA_CTRL_DST_ADDRESS_LO, j.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, j.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, j.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, j.src >> 32),
            (DMA_CTRL_LENGTH_LO, j.length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, j.dst_stride & 0xFFFF_FFFF),
            (DMA_CTRL_DST_STRIDE_HI, j.dst_stride >> 32),
            (DMA_CTRL_SRC_STRIDE_LO, j.src_stride & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_STRIDE_HI, j.src_stride >> 32),
            (DMA_CTRL_NUM_REPETITIONS_LO, j.reps),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{j.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, j: _Job) -> None:
        # Reading NEXT_ID launches the programmed descriptor.
        j.id = await self.csr_read(f"{j.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        self.next_id_reads += 1
        assert j.id == self.last_done + 1, (
            f"{j.name}: NEXT_ID returned {j.id} after DONE {self.last_done}"
        )

    async def _await_done(self, j: _Job) -> None:
        done = -1
        for _ in range(POLL_LIMIT):
            done = await self.csr_read(f"{j.name}_DONE", DMA_CTRL_DONE_0)
            if done == j.id:
                self.last_done = j.id
                return
            assert done < j.id, f"{j.name}: DONE_0 reads {done}, past its id {j.id}"
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        status = await self.csr_read(f"{j.name}_STATUS", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"{j.name}: DONE_0 reached {done}, not id {j.id} within {POLL_LIMIT} polls "
            f"(status 0x{status:x}, tb_dma_busy {self._busy()})"
        )

    async def _run(self, j: _Job) -> None:
        s = self.sampler
        ar0, aw0 = len(s.ar), len(s.aw)
        await self._program(j)
        await self._launch(j)
        await self._await_done(j)
        j.ar, j.aw = s.ar[ar0:], s.aw[aw0:]

    def _span(self, j: _Job) -> int:
        return (j.reps - 1) * j.dst_stride + j.length + 0x40

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        for name in _IF_SIGNALS:
            assert hasattr(dut.u_output_axi_if, name), f"u_output_axi_if has no {name}"
        await self._pass_all()
        self.sampler = _BurstSampler(dut)
        cocotb.start_soon(self.sampler.run())
        self.last_done = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> str:
        base = self._case_base()
        j = _Job("INDEP", base, base + 0x800, S2_LENGTH, S2_ROWS, S2_SRC_STRIDE, S2_DST_STRIDE)
        span = self._span(j)
        self._seed(j, span)
        await self._run(j)
        self._compare_image(j, span)
        self._mark("S2")
        rows = ", ".join(f"0x{a:x}" for a in self._dst_rows(j))
        return (
            f"{S2_ROWS} rows of {S2_LENGTH} bytes with source stride 0x{S2_SRC_STRIDE:x} and "
            f"destination stride 0x{S2_DST_STRIDE:x} (id {j.id}) match the source rows at "
            f"destination rows {rows}; the {span - S2_ROWS * S2_LENGTH} sentinel bytes of the "
            f"destination span are unchanged and the source rows are unchanged"
        )

    async def _s3(self) -> str:
        parts = []
        for count in S3_COUNTS:
            base = self._case_base()
            j = _Job(
                f"ROWS{count}", base, base + 0x800, S3_LENGTH, count, S3_SRC_STRIDE, S3_DST_STRIDE
            )
            span = self._span(j) + S3_DST_STRIDE + S3_LENGTH
            self._seed(j, span)
            await self._run(j)
            self._compare_image(j, span)
            nxt = j.dst + count * S3_DST_STRIDE
            tail = bytes(self._responder.read(nxt, S3_LENGTH))
            assert tail == bytes([SENTINEL]) * S3_LENGTH, (
                f"{j.name}: row {count + 1} destination 0x{nxt:x} holds {tail.hex()}, not sentinel"
            )
            parts.append(f"{count} rows (id {j.id}, next-row destination 0x{nxt:x} sentinel)")
        self._mark("S3")
        return (
            f"{'; '.join(parts)}: exactly that many {S3_LENGTH}-byte rows were copied, the first "
            f"row included, and the destination of the following row still holds the sentinel"
        )

    async def _s4(self) -> str:
        base = self._case_base()
        j = _Job(
            "UNAL",
            base + S4_SRC_OFFSET,
            base + 0x800 + S4_DST_OFFSET,
            S4_LENGTH,
            S4_ROWS,
            S4_STRIDE,
            S4_STRIDE,
        )
        assert j.src % 8 == S4_SRC_OFFSET and j.dst % 8 == S4_DST_OFFSET
        span = self._span(j)
        self._seed(j, span)
        await self._run(j)
        self._compare_image(j, span)
        self._mark("S4")
        return (
            f"{S4_ROWS} rows of {S4_LENGTH} bytes from source 0x{j.src:x} (word offset "
            f"{S4_SRC_OFFSET}) to destination 0x{j.dst:x} (word offset {S4_DST_OFFSET}), id "
            f"{j.id}, arrived byte for byte and the {span - S4_ROWS * S4_LENGTH} bytes between "
            f"and around the rows are unchanged"
        )

    async def _s5(self) -> str:
        base = self._case_base()
        j = _Job("SINGLE", base, base + 0x800, S5_LENGTH, S5_ROWS, S5_SRC_STRIDE, S5_DST_STRIDE)
        span = self._span(j)
        self._seed(j, span)
        baseline = await self.csr_read("S5_DONE_BASE", DMA_CTRL_DONE_0)
        assert baseline == self.last_done, f"DONE_0 baseline {baseline}, tracked {self.last_done}"
        reads0 = self.next_id_reads
        await self._run(j)
        reads = self.next_id_reads - reads0
        after = await self.csr_read("S5_DONE_AFTER", DMA_CTRL_DONE_0)
        assert reads == 1, f"{reads} NEXT_ID_0 reads for the {S5_ROWS}-row command"
        assert after == j.id, f"DONE_0 {after} after retirement, returned ID {j.id}"
        assert after - baseline == 1, f"DONE_0 advanced {after - baseline} over baseline {baseline}"
        self._compare_image(j, span)
        self._mark("S5")
        return (
            f"{S5_ROWS}-row command took {reads} NEXT_ID_0 read returning ID {j.id}; DONE_0 "
            f"baseline {baseline}, DONE_0 after retirement {after}, advance {after - baseline} "
            f"(not {S5_ROWS}); all {S5_ROWS} rows copied"
        )

    async def _s6(self) -> str:
        results = []
        for name, sstride, dstride, dst_off in S6_CASES:
            base = self._case_base()
            j = _Job(name, base, base + dst_off, S6_LENGTH, S6_ROWS, sstride, dstride)
            span = max(sstride, dstride) * (S6_ROWS - 1) + S6_LENGTH
            src_span = sstride * (S6_ROWS - 1) + S6_LENGTH
            region = bytes((i * 7 + 0x11) & 0xFF for i in range(src_span))
            self._responder.write(j.src, region)
            if dst_off >= 0x100:
                self._responder.write(j.dst, bytes([SENTINEL]) * span)
            await self._run(j)
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            assert self._busy() == 0, f"{name}: tb_dma_busy high after DONE_0 reached {j.id}"
            result = bytes(self._responder.read(j.dst, span))
            results.append(
                f"{name} src stride 0x{sstride:x} dst stride 0x{dstride:x} id {j.id} "
                f"source {region.hex()} destination {result.hex()}"
            )
        self._mark("S6")
        return (
            f"{len(S6_CASES)} commands retired within {POLL_LIMIT} polls with tb_dma_busy low "
            f"(owner value pending, resulting bytes measured and printed): {'; '.join(results)}"
        )

    async def _s7(self) -> str:
        j = _Job("WRAP", S7_SRC_BASE, S7_DST_BASE, S7_LENGTH, S7_ROWS, S7_SRC_STRIDE, S7_DST_STRIDE)
        assert S7_SRC_BASE < TWO_POW_56 and S7_DST_BASE < TWO_POW_56
        src_logical = self._src_rows(j)
        dst_logical = self._dst_rows(j)
        past_src = [a for a in src_logical if a >= TWO_POW_56]
        past_dst = [a for a in dst_logical if a >= TWO_POW_56]
        assert past_src and past_dst
        for addr in src_logical:
            low = addr % TWO_POW_56
            self._responder.write(low, bytes(_pattern(addr + i) for i in range(S7_LENGTH)))
        for addr in dst_logical:
            self._responder.write(addr % TWO_POW_56, bytes([SENTINEL]) * S7_LENGTH)
        await self._run(j)
        ar = ",".join(f"0x{a:x}" for a in j.ar)
        aw = ",".join(f"0x{a:x}" for a in j.aw)
        assert j.ar and j.aw, f"no AR or AW handshake observed (ar={ar} aw={aw})"
        wrapped = any(a < S7_DST_STRIDE * S7_ROWS for a in j.ar + j.aw)
        low_rows = []
        for addr in dst_logical:
            low = addr % TWO_POW_56
            low_rows.append(f"0x{low:x}={bytes(self._responder.read(low, S7_LENGTH)).hex()}")
        self._mark("S7")
        return (
            f"{S7_ROWS} rows from source base 0x{S7_SRC_BASE:x} stride 0x{S7_SRC_STRIDE:x} to "
            f"destination base 0x{S7_DST_BASE:x} stride 0x{S7_DST_STRIDE:x}, id {j.id} retired "
            f"within {POLL_LIMIT} polls; logical rows past 2^56: source "
            f"{[hex(a) for a in past_src]} destination {[hex(a) for a in past_dst]}; issued AR "
            f"addresses {ar}; issued AW addresses {aw}; "
            f"address_wrapped_to_low_range={wrapped} (owner value pending, measured and printed); "
            f"low-range destination bytes {'; '.join(low_rows)}"
        )

    async def body(self) -> None:
        await self._s1()
        steps = (
            ("S2", self._s2, "CHK-DMA-2D-INDEP-STRIDES"),
            ("S3", self._s3, "CHK-DMA-2D-ROW-COUNTS"),
            ("S4", self._s4, "CHK-DMA-2D-UNALIGNED-ROWS"),
            ("S5", self._s5, "CHK-DMA-2D-SINGLE-ID"),
            ("S6", self._s6, "CHK-DMA-2D-STRIDE-EDGES"),
            ("S7", self._s7, "CHK-DMA-2D-WRAP-2POW56"),
        )
        for step, fn, chk in steps:
            text = await fn()
            self._chk(step, chk, text)
        self._nonvac(steps)

    def _nonvac(self, steps) -> None:
        order = ["S1"] + [s for s, _, _ in steps]
        assert [s for s, _ in self.steps] == order, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        want = [(s, c) for s, _, c in steps]
        assert self.chk_steps == want, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
