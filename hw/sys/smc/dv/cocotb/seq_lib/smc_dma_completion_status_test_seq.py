# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA completion and status reporting through the SYS_OUT responder.

Specs hw/sys/smc/doc/dma.adoc, doc/programmer/src/smc-programming.adoc, vendor idma dma_ctrl.rdl.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. Every AR and AW handshake of the exported SYS_OUT probes is recorded with
its address and time, and bit 322 of tb_cpu_interrupts and tb_dma_busy at every clk_smc_i rise.
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
IRQ_BIT = 322
#: NEXT_ID_0 resets to 2 and DONE_0 to 1 (dma.adoc, Retirement Counting).
RESET_NEXT_ID = 2

ROWS = 8
ROW_LENGTH = 16
SRC_STRIDE = 0x30
DST_STRIDE = 0x28
#: The queued commands: QUEUE1 has more rows than the backend issues with the read responses
#: held, so its expansion stalls and the commands behind it wait in the request FIFO, whose
#: depth dma.adoc (SMC DMA elaboration settings) gives as F2M_FIFO_DEPTH 4. The chapter does
#: not state whether the command being expanded keeps its slot, so readiness may fall after
#: F2M_FIFO_DEPTH - 1 or after F2M_FIFO_DEPTH launches behind QUEUE1.
QUEUE1_ROWS = 40
QUEUE1_LENGTH = 8
QUEUE2_ROWS = 4
F2M_FIFO_DEPTH = 4
QUEUE_TAIL = 3

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_araddr",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_output_axi_resp_hold",
    "tb_cpu_interrupts",
    "tb_dma_busy",
)


def _pulse_widths(bits: list[int], lo: int, hi: int) -> list[int]:
    """Widths, in samples, of the pulses whose first high sample lies in bits[lo:hi]."""
    widths = []
    for i in range(lo, min(hi, len(bits))):
        if bits[i] and (i == 0 or not bits[i - 1]):
            end = i
            while end < len(bits) and bits[end]:
                end += 1
            widths.append(end - i)
    return widths


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
    """Records every AR and AW handshake address, the time of every AW handshake, and per
    clk_smc_i rise the interrupt bit and tb_dma_busy."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar: list[int] = []
        self.aw: list[int] = []
        self.aw_ps: list[int] = []
        self.irq: list[int] = []
        self.busy: list[int] = []

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
                    if ch == "aw":
                        self.aw_ps.append(int(get_sim_time("ps")))
            self.irq.append((self._bit(dut.tb_cpu_interrupts, "tb_cpu_interrupts") >> IRQ_BIT) & 1)
            self.busy.append(self._bit(dut.tb_dma_busy, "tb_dma_busy"))


class smc_dma_completion_status_test_seq(SmcCsrSeq):
    """DONE_0 and STATUS_0 reporting at idle, for the reset-state command, across two queued
    copies, for no-data commands and under a hold (dma.adoc, Submission and Completion and
    Retirement Counting)."""

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
        self.dma_writes = 0

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
            self.dma_writes += 1

    async def _readback(self, name: str, config: int, length: int, reps: int) -> str:
        """Reads CONFIG, LENGTH_LO and NUM_REPETITIONS_LO and requires the given values."""
        got = {}
        for label, reg, want in (
            ("CONFIG", DMA_CTRL_CONFIG, config),
            ("LENGTH_LO", DMA_CTRL_LENGTH_LO, length),
            ("NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, reps),
        ):
            got[label] = await self.csr_read(f"{name}_{label}_RB", reg)
            assert got[label] == want, (
                f"{name}: {label} reads 0x{got[label]:x}, want 0x{want:x} before the launch"
            )
        return " ".join(f"{k}=0x{v:x}" for k, v in got.items())

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
        """The reset-state command: no descriptor register written since reset."""
        s = self.sampler
        assert self.dma_writes == 0, (
            f"{self.dma_writes} DMA register writes before the reset-state command"
        )
        ar0, aw0, irq0 = len(s.ar), len(s.aw), len(s.irq)
        j = _Job("RESET_STATE", 0, 0, 0, 0)
        regs = await self._readback("RESET_STATE", 0, 0, 0)
        await self._launch(j)
        assert j.id == RESET_NEXT_ID, (
            f"CHK-DMA-RESET-STATE-COMMAND FAIL: the first NEXT_ID_0 read returned {j.id}, "
            f"want {RESET_NEXT_ID}"
        )
        polls = await self._await_done(j)
        low = await self._busy_low_sample(len(s.busy), "RESET_STATE")
        irq_end = low + 2
        while len(s.irq) < irq_end:
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
        widths = _pulse_widths(s.irq, irq0, irq_end)
        ar, aw = self._tally_window(ar0, aw0)
        assert not ar and not aw, (
            f"CHK-DMA-RESET-STATE-COMMAND FAIL: AR {[hex(a) for a in ar]} AW "
            f"{[hex(a) for a in aw]} handshakes for the reset-state command"
        )
        assert widths == [1], (
            f"CHK-DMA-RESET-STATE-COMMAND FAIL: bit {IRQ_BIT} pulse widths {widths} between the "
            f"launch and one rise after tb_dma_busy read low, want one one-cycle pulse"
        )
        self._mark("S4")
        return (
            f"with no DMA register written since reset ({regs} read back at their reset "
            f"values), the first NEXT_ID_0 read returned {j.id}; DONE_0 reached {j.id} after "
            f"{polls} polls; AR {len(ar)} AW {len(aw)} "
            f"handshakes; bit {IRQ_BIT} pulses {widths} (count, width in clk_smc_i cycles) over "
            f"{irq_end - irq0} samples"
        )

    async def _busy_low_sample(self, first: int, name: str) -> int:
        """Index of the first tb_dma_busy sample at or after `first` that reads low, once the
        sample after it exists."""
        s = self.sampler
        for _ in range(POLL_LIMIT):
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            lows = [i for i in range(first, len(s.busy)) if not s.busy[i]]
            if lows and len(s.busy) > lows[0] + 1:
                return lows[0]
        raise AssertionError(f"{name}: tb_dma_busy did not read low in {POLL_LIMIT} rises")

    async def _s5(self) -> list[str]:
        dut = cocotb.top
        s = self.sampler
        queue = [
            _Job("QUEUE1", 0, 0, QUEUE1_LENGTH, QUEUE1_ROWS),
            _Job("QUEUE2", 0, 0, ROW_LENGTH, QUEUE2_ROWS),
        ] + [_Job(f"QUEUE{n + 3}", 0, 0, ROW_LENGTH, 1) for n in range(QUEUE_TAIL)]
        for j in queue:
            base = self._case_base()
            j.src, j.dst = base, base + 0x800
            self._seed(j)
        q1 = queue[0]
        ar0, aw0 = len(s.ar), len(s.aw)
        idle_bit8 = [(v >> 8) & 1 for v in self.idle_status]
        assert idle_bit8 == [0, 0], "STATUS_0 bit 8 high at the idle read before the copy"
        after_launch: list[int] = []
        held: list[int] = []
        polls: list[tuple[int, int, int]] = []
        await self._program(q1)
        dut.tb_output_axi_resp_hold.value = 1
        try:
            await self._launch(q1)
            after_launch.append(await self.csr_read("QUEUE1_STATUS", DMA_CTRL_STATUS_0))
            for prev, j in zip(queue, queue[1:]):
                if after_launch[-1] & STATUS_ROOM_MASK == 0:
                    break
                await self._program(j)
                j.id = await self.csr_read(f"{j.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
                assert j.id == prev.id + 1, (
                    f"{j.name}: NEXT_ID returned {j.id} after {prev.name} id {prev.id}"
                )
                after_launch.append(await self.csr_read(f"{j.name}_STATUS", DMA_CTRL_STATUS_0))
            queue = [j for j in queue if j.id > 0]
            last = queue[-1]
            for n in range(HOLD_POLLS):
                held.append(await self.csr_read(f"QUEUE_HELD_STATUS{n}", DMA_CTRL_STATUS_0))
            waiting_rows = {j.src + n * j.src_stride for j in queue[1:] for n in range(j.reps)}
            early = [a for a in s.ar[ar0:] if a in waiting_rows]
            assert not early, (
                f"CHK-DMA-STATUS-BIT8-QUEUED FAIL: rows {[hex(a) for a in early]} of the queued "
                f"commands were read while the responses were held, so they did not wait behind "
                f"QUEUE1"
            )
            assert all((v >> 8) & 1 for v in after_launch + held), (
                f"CHK-DMA-STATUS-BIT8-QUEUED FAIL: STATUS_0 reads "
                f"{[hex(v) for v in after_launch + held]} while commands waited behind QUEUE1, "
                f"want bit 8 set on every read"
            )
            assert not any(v & STATUS_BIT9 for v in after_launch + held), (
                f"CHK-DMA-STATUS-BIT8-QUEUED FAIL: STATUS_0 reads "
                f"{[hex(v) for v in after_launch + held]} with bit 9 set"
            )
            room = [v & STATUS_ROOM_MASK for v in after_launch]
            fell_at = len(room) - 1
            assert room[:-1] == [STATUS_ROOM_MASK] * (len(room) - 1) and room[-1] == 0, (
                f"CHK-DMA-FE-QUEUE-DEPTH FAIL: STATUS_0[7:0] after each launch "
                f"{[hex(r) for r in room]}, want 0xFF until the one read of 0"
            )
            assert fell_at in (F2M_FIFO_DEPTH - 1, F2M_FIFO_DEPTH), (
                f"CHK-DMA-FE-QUEUE-DEPTH FAIL: readiness read 0 after launch {fell_at} behind "
                f"the stalled QUEUE1, want launch {F2M_FIFO_DEPTH - 1} or {F2M_FIFO_DEPTH} for "
                f"a request FIFO of depth {F2M_FIFO_DEPTH}"
            )
            assert all(v & STATUS_ROOM_MASK == 0 for v in held), (
                f"CHK-DMA-FE-QUEUE-DEPTH FAIL: STATUS_0 reads {[hex(v) for v in held]} with "
                f"{F2M_FIFO_DEPTH} commands queued, want bits [7:0] 0 on every read"
            )
        finally:
            await FallingEdge(dut.clk_smc_i)
            dut.tb_output_axi_resp_hold.value = 0
        retired_at = -1
        for poll in range(1, POLL_LIMIT + 1):
            t_before = int(get_sim_time("ps"))
            status = await self.csr_read("QUEUE_STATUS", DMA_CTRL_STATUS_0)
            done = await self.csr_read("QUEUE_DONE", DMA_CTRL_DONE_0)
            polls.append((poll, t_before, (status >> 8) & 1))
            if done == last.id:
                retired_at = poll
                break
            assert done < last.id, f"{last.name}: DONE_0 reads {done}, past its id {last.id}"
        assert retired_at > 0, (
            f"{last.name}: DONE_0 did not reach {last.id} within {POLL_LIMIT} polls"
        )
        self.last_done = last.id
        t_before = int(get_sim_time("ps"))
        after = await self.csr_read("QUEUE_STATUS_AFTER", DMA_CTRL_STATUS_0)
        polls.append((retired_at + 1, t_before, (after >> 8) & 1))
        aw_ps = [t for a, t in zip(s.aw[aw0:], s.aw_ps[aw0:]) if a == last.dst]
        assert len(aw_ps) == 1, (
            f"CHK-DMA-STATUS-BIT8-QUEUED FAIL: {len(aw_ps)} AW handshakes at the last queued "
            f"row 0x{last.dst:x}, want one"
        )
        late = [(p, b) for p, t, b in polls if t > aw_ps[0]]
        assert late and all(b == 0 for _, b in late), (
            f"CHK-DMA-STATUS-BIT8-QUEUED FAIL: STATUS_0 bit 8 reads (poll, bit) {late} on the "
            f"polls started after the last-row AW handshake at {aw_ps[0]} ps, want 0 on each"
        )
        first_zero = next(p for p, _, b in polls if b == 0)
        for j in queue:
            self._compare_dst(j, True)
        rows = sum(j.reps for j in queue)
        ar, aw = self._tally_window(ar0, aw0)
        assert len(ar) >= rows and len(aw) >= rows, (
            f"{len(queue)} queued copies of {rows} rows produced ar={len(ar)} aw={len(aw)} "
            f"handshakes"
        )
        self.copy_ar, self.copy_aw = len(ar), len(aw)
        self._mark("S5")
        ids = ", ".join(f"{j.name} {j.reps} rows id {j.id}" for j in queue)
        trace = ",".join(f"{p}@{t}ps={b}" for p, t, b in polls)
        return [
            f"idle bit 8 {idle_bit8}; with the responses held {ids} launched; STATUS_0 after each "
            f"launch {[hex(v) for v in after_launch]} and {len(held)} further reads "
            f"{[hex(v) for v in held]} while the commands waited (bit 8 set on each, no row of "
            f"a waiting command read); after the release the last queued row's AW handshake "
            f"came at {aw_ps[0]} ps, the {len(late)} STATUS_0 reads started after it read bit 8 "
            f"clear (poll@start=bit {trace}); first bit 8 clear at poll {first_zero}, DONE_0 "
            f"equal to {last.id} at poll {retired_at} (the fall before the retirement is "
            f"measured, not compared); AR {len(ar)} AW {len(aw)} handshakes; all {len(queue)} "
            f"destinations equal their source rows",
            f"with QUEUE1 stalled at the head of the request FIFO (no row of a later command "
            f"read while held), STATUS_0[7:0] read {[hex(r) for r in room]} after the "
            f"{len(queue)} launches: 0xFF after each launch until launch {fell_at} behind "
            f"QUEUE1 read 0, within the {F2M_FIFO_DEPTH - 1}..{F2M_FIFO_DEPTH} a request FIFO "
            f"of depth F2M_FIFO_DEPTH {F2M_FIFO_DEPTH} allows (whether the command being "
            f"expanded keeps a slot is measured, not compared); {len(held)} further reads kept "
            f"bits [7:0] 0; after the release all {len(queue)} commands retired",
        ]

    async def _no_data(self, step: str, name: str, config: int, reps_lo: int) -> str:
        s = self.sampler
        base = self._case_base()
        j = _Job(name, base, base + 0x800, ROW_LENGTH, ROWS)
        j.config = config
        self._seed(j)
        ar0, aw0 = len(s.ar), len(s.aw)
        await self._program(j, reps_lo)
        regs = await self._readback(name, config, ROW_LENGTH, reps_lo)
        await self._launch(j)
        polls = await self._await_done(j)
        ar, aw = self._tally_window(ar0, aw0)
        assert not ar, f"{name}: AR handshakes at {[hex(a) for a in ar]}"
        assert not aw, f"{name}: AW handshakes at {[hex(a) for a in aw]}"
        self._compare_dst(j, False)
        assert self.copy_ar > 0 and self.copy_aw > 0
        self._mark(step)
        return (
            f"command CONFIG 0x{config:x} NUM_REPETITIONS_LO {reps_lo} (read back {regs}) "
            f"returned id {j.id}; "
            f"DONE_0 equals {j.id} after {polls} polls; AR {len(ar)} AW {len(aw)} at the "
            f"programmed addresses (source 0x{j.src:x}, destination 0x{j.dst:x}); "
            f"destination {j.span} poison bytes unchanged; tally positive control: the queued "
            f"copies counted AR {self.copy_ar} AW {self.copy_aw}"
        )

    async def _s6(self) -> str:
        return await self._no_data("S6", "ND_CLEAR", 0, ROWS)

    async def _s7(self) -> str:
        return await self._no_data("S7", "REPS_ZERO", DMA_CONFIG_ENABLED_ND, 0)

    async def _s8(self) -> str:
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
        self._mark("S8")
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
            ("S2", self._s2, ("CHK-DMA-DONE-RESET",)),
            ("S3", self._s3, ("CHK-DMA-STATUS-IDLE",)),
            ("S4", self._s4, ("CHK-DMA-RESET-STATE-COMMAND",)),
            ("S5", self._s5, ("CHK-DMA-STATUS-BIT8-QUEUED", "CHK-DMA-FE-QUEUE-DEPTH")),
            ("S6", self._s6, ("CHK-DMA-NO-DATA-ND-CLEAR",)),
            ("S7", self._s7, ("CHK-DMA-NO-DATA-REPS-ZERO",)),
            ("S8", self._s8, ("CHK-DMA-POLL-IN-FLIGHT",)),
        )
        for step, fn, chks in steps:
            texts = await fn()
            if isinstance(texts, str):
                texts = [texts]
            assert len(texts) == len(chks), f"{step}: {len(texts)} texts for {chks}"
            for chk, text in zip(chks, texts):
                self._chk(step, chk, text)
        self._nonvac(steps)

    def _nonvac(self, steps) -> None:
        order = ["S1"] + [s for s, _, _ in steps]
        assert [s for s, _ in self.steps] == order, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        want = [(s, c) for s, _, cs in steps for c in cs]
        assert self.chk_steps == want, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
