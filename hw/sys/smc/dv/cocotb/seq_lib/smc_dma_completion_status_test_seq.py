# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA completion and status reporting through the SYS_OUT responder.

Specs hw/sys/smc/doc/dma.adoc, doc/programmer/src/smc-programming.adoc, vendor idma dma_ctrl.rdl.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. Every AR and AW handshake of the exported SYS_OUT probes is recorded.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
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
POISON = 0xEE
POLL_LIMIT = 3000
STATUS_ROOM_MASK = 0xFF
STATUS_BIT8 = 1 << 8
STATUS_BIT9 = 1 << 9
HOLD_POLLS = 6

ROWS = 8
ROW_LENGTH = 16
SRC_STRIDE = 0x30
DST_STRIDE = 0x28

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_araddr",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_output_axi_resp_hold",
)


def _pattern(addr: int) -> int:
    return ((addr * 13) ^ (addr >> 7) ^ 0x3C) & 0xFF


class _Job:
    def __init__(self, name: str, src: int, dst: int, length: int, reps: int) -> None:
        self.name = name
        self.src = src
        self.dst = dst
        self.length = length
        self.reps = reps
        self.src_stride = SRC_STRIDE
        self.dst_stride = DST_STRIDE
        self.config = DMA_CONFIG_ENABLED_ND
        self.id = -1

    @property
    def span(self) -> int:
        return (max(self.reps, 1) - 1) * self.dst_stride + self.length + 0x40


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


class smc_dma_completion_status_test_seq(SmcCsrSeq):
    """DONE_0 and STATUS_0 reporting at idle, across a copy, for no-data commands and a hold."""

    def __init__(self, name: str = "smc_dma_completion_status_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.sampler: _BurstSampler | None = None
        self.last_done = 1
        self.idle_status: list[int] = []
        self.copy_ar = 0
        self.copy_aw = 0
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

    def _seed(self, j: _Job) -> None:
        for n in range(j.reps):
            addr = j.src + n * j.src_stride
            self._responder.write(addr, bytes(_pattern(addr + i) for i in range(j.length)))
        self._responder.write(j.dst, bytes([POISON]) * j.span)

    def _expected_dst(self, j: _Job, copied: bool) -> bytes:
        image = bytearray([POISON]) * j.span
        if copied:
            for n in range(j.reps):
                src = j.src + n * j.src_stride
                off = n * j.dst_stride
                image[off : off + j.length] = bytes(_pattern(src + i) for i in range(j.length))
        return bytes(image)

    def _compare_dst(self, j: _Job, copied: bool) -> None:
        want = self._expected_dst(j, copied)
        got = bytes(self._responder.read(j.dst, j.span))
        if got != want:
            idx = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
            raise AssertionError(
                f"{j.name}: destination byte 0x{j.dst + idx:x} (offset {idx}) is 0x{got[idx]:02x}, "
                f"want 0x{want[idx]:02x} ({'copied image' if copied else 'poison'})"
            )

    async def _program(self, j: _Job, reps_lo: int | None = None) -> None:
        reps = j.reps if reps_lo is None else reps_lo
        for reg, value in (
            (DMA_CTRL_CONFIG, j.config),
            (DMA_CTRL_DST_ADDRESS_LO, j.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, j.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, j.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, j.src >> 32),
            (DMA_CTRL_LENGTH_LO, j.length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, j.dst_stride),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, j.src_stride),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, reps),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{j.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, j: _Job) -> None:
        j.id = await self.csr_read(f"{j.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        assert j.id == self.last_done + 1, (
            f"{j.name}: NEXT_ID returned {j.id} after DONE {self.last_done}"
        )

    async def _await_done(self, j: _Job) -> int:
        """Polls DONE_0 until it equals the job ID; returns the number of polls."""
        done = -1
        for poll in range(1, POLL_LIMIT + 1):
            done = await self.csr_read(f"{j.name}_DONE", DMA_CTRL_DONE_0)
            if done == j.id:
                self.last_done = j.id
                return poll
            assert done < j.id, f"{j.name}: DONE_0 reads {done}, past its id {j.id}"
        status = await self.csr_read(f"{j.name}_STATUS", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"{j.name}: DONE_0 reached {done}, not id {j.id} within {POLL_LIMIT} polls "
            f"(status 0x{status:x})"
        )

    def _tally_window(self, ar0: int, aw0: int) -> tuple[list[int], list[int]]:
        s = self.sampler
        return s.ar[ar0:], s.aw[aw0:]

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        dut.tb_output_axi_resp_hold.value = 0
        await self._pass_all()
        self.sampler = _BurstSampler(dut)
        cocotb.start_soon(self.sampler.run())
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> str:
        done = await self.csr_read("DONE_RESET", DMA_CTRL_DONE_0)
        assert done == 1, f"DONE_0 reads {done} before any transfer, want 1"
        self.last_done = done
        self._mark("S2")
        return f"DONE_0 reads {done} after reset and before any transfer"

    async def _s3(self) -> str:
        reads = [await self.csr_read(f"STATUS_IDLE{n}", DMA_CTRL_STATUS_0) for n in range(2)]
        for n, value in enumerate(reads):
            assert value & STATUS_ROOM_MASK == STATUS_ROOM_MASK, (
                f"idle STATUS_0 read {n} is 0x{value:x}, bits [7:0] not 0xFF"
            )
            assert not value & STATUS_BIT9, f"idle STATUS_0 read {n} is 0x{value:x}, bit 9 set"
        assert reads[0] == reads[1], f"idle STATUS_0 reads differ: {reads[0]:#x} vs {reads[1]:#x}"
        self.idle_status = reads
        self._mark("S3")
        bit8 = [(v >> 8) & 1 for v in reads]
        return (
            f"idle STATUS_0 reads 0x{reads[0]:x} and 0x{reads[1]:x}: bits [7:0] 0xFF, bit 9 0, "
            f"bit 8 printed {bit8}"
        )

    async def _s4(self) -> str:
        s = self.sampler
        base = self._case_base()
        j = _Job("COPY8", base, base + 0x800, ROW_LENGTH, ROWS)
        self._seed(j)
        ar0, aw0 = len(s.ar), len(s.aw)
        idle_bit8 = [(v >> 8) & 1 for v in self.idle_status]
        assert idle_bit8 == [0, 0], "STATUS_0 bit 8 high at the idle read before the copy"
        await self._program(j)
        t_submit = int(get_sim_time("ps"))
        await self._launch(j)
        samples: list[tuple[int, int, int]] = []
        first_done = -1
        for poll in range(1, POLL_LIMIT + 1):
            status = await self.csr_read("COPY8_STATUS", DMA_CTRL_STATUS_0)
            t_status = int(get_sim_time("ps")) - t_submit
            done = await self.csr_read("COPY8_DONE", DMA_CTRL_DONE_0)
            samples.append((poll, (status >> 8) & 1, t_status))
            if done == j.id:
                first_done = poll
                break
            assert done < j.id, f"COPY8: DONE_0 reads {done}, past its id {j.id}"
        assert first_done > 0, (
            f"COPY8: DONE_0 did not reach {j.id} within {POLL_LIMIT} polls; "
            f"last STATUS_0 bit 8 {samples[-1][1]}"
        )
        self.last_done = j.id
        after = await self.csr_read("COPY8_STATUS_AFTER", DMA_CTRL_STATUS_0)
        self._compare_dst(j, True)
        ar, aw = self._tally_window(ar0, aw0)
        assert ar and aw, f"8-row copy produced ar={len(ar)} aw={len(aw)} handshakes"
        self.copy_ar, self.copy_aw = len(ar), len(aw)
        self._mark("S4")
        high = [p for p, b, _ in samples if b]
        edges = [
            f"{samples[i][0]}:{samples[i - 1][1]}->{samples[i][1]}"
            for i in range(1, len(samples))
            if samples[i][1] != samples[i - 1][1]
        ]
        trace = ",".join(f"{p}@{t}ps={b}" for p, b, t in samples)
        return (
            f"idle bit 8 {idle_bit8}; {ROWS}-row copy id {j.id} submitted; STATUS_0 bit 8 "
            f"samples (poll@time since submit=bit) {trace}; samples with bit 8 high {high}; "
            f"bit 8 transitions {edges}; DONE_0 first equals {j.id} at sample {first_done} of "
            f"{len(samples)}; STATUS_0 bit 8 after retirement {(after >> 8) & 1} "
            f"(STATUS_0 0x{after:x}); AR {len(ar)} AW {len(aw)} handshakes; destination equals "
            f"source rows; timing is measured and printed (not specified)"
        )

    async def _no_data(self, step: str, name: str, config: int, reps_lo: int) -> str:
        s = self.sampler
        base = self._case_base()
        j = _Job(name, base, base + 0x800, ROW_LENGTH, ROWS)
        j.config = config
        self._seed(j)
        ar0, aw0 = len(s.ar), len(s.aw)
        await self._program(j, reps_lo)
        await self._launch(j)
        polls = await self._await_done(j)
        ar, aw = self._tally_window(ar0, aw0)
        assert not ar, f"{name}: AR handshakes at {[hex(a) for a in ar]}"
        assert not aw, f"{name}: AW handshakes at {[hex(a) for a in aw]}"
        self._compare_dst(j, False)
        assert self.copy_ar > 0 and self.copy_aw > 0
        self._mark(step)
        return (
            f"command CONFIG 0x{config:x} NUM_REPETITIONS_LO {reps_lo} returned id {j.id}; "
            f"DONE_0 equals {j.id} after {polls} polls; AR {len(ar)} AW {len(aw)} at the "
            f"programmed addresses (source 0x{j.src:x}, destination 0x{j.dst:x}); "
            f"destination {j.span} poison bytes unchanged; tally positive control: the 8-row "
            f"copy counted AR {self.copy_ar} AW {self.copy_aw}"
        )

    async def _s5(self) -> str:
        return await self._no_data("S5", "ND_CLEAR", 0, ROWS)

    async def _s6(self) -> str:
        return await self._no_data("S6", "REPS_ZERO", DMA_CONFIG_ENABLED_ND, 0)

    async def _s7(self) -> str:
        dut = cocotb.top
        s = self.sampler
        base = self._case_base()
        j = _Job("HELD", base, base + 0x800, 64, 1)
        self._seed(j)
        prev = self.last_done
        ar0 = len(s.ar)
        await self._program(j)
        polls: list[str] = []
        dut.tb_output_axi_resp_hold.value = 1
        try:
            await self._launch(j)
            for n in range(HOLD_POLLS):
                status = await self.csr_read(f"HELD_STATUS{n}", DMA_CTRL_STATUS_0)
                done = await self.csr_read(f"HELD_DONE{n}", DMA_CTRL_DONE_0)
                assert done == prev, (
                    f"DONE_0 reads {done} while held, want previous id {prev} (new id {j.id})"
                )
                polls.append(f"status=0x{status:x} done={done}")
            held_ar = len(s.ar) - ar0
            assert held_ar > 0, "no AR handshake while the transfer was held"
        finally:
            await FallingEdge(dut.clk_smc_i)
            dut.tb_output_axi_resp_hold.value = 0
        count = await self._await_done(j)
        self._compare_dst(j, True)
        self._mark("S7")
        return (
            f"{HOLD_POLLS} STATUS_0 and DONE_0 reads while held completed OKAY "
            f"({'; '.join(polls)}); "
            f"DONE_0 stayed at previous id {prev} until release; AR {held_ar} issued while held; "
            f"after release DONE_0 equals new id {j.id} after {count} polls and the destination "
            f"equals the source"
        )

    async def body(self) -> None:
        await self._s1()
        steps = (
            ("S2", self._s2, "CHK-DMA-DONE-RESET"),
            ("S3", self._s3, "CHK-DMA-STATUS-IDLE"),
            ("S4", self._s4, "CHK-DMA-STATUS-BIT8"),
            ("S5", self._s5, "CHK-DMA-NO-DATA-ND-CLEAR"),
            ("S6", self._s6, "CHK-DMA-NO-DATA-REPS-ZERO"),
            ("S7", self._s7, "CHK-DMA-POLL-IN-FLIGHT"),
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
