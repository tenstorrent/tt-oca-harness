# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA linear copy breadth through the SYS_OUT responder.

Specs hw/sys/smc/doc/dma.adoc, vendor idma overlay dma_ctrl.rdl.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor, so the DMA adds the only bus traffic. Every AR and AW handshake of the
exported SYS_OUT probes is recorded with its length and size from u_output_axi_if.
"""

from __future__ import annotations

import os
import random

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
GUARD = 8
GUARD_BYTE = 0xEE
POISON = 0xA5
POLL_LIMIT = 3000
POLL_CYCLES = 50
KIB2 = 2048
MAX_BEATS = 256

S2_LENGTH = 40
S2_STRIDE = 0x400
S2_DST_BASE = 0x200
S2_OFFSETS = (
    [(o, 0) for o in range(1, 8)]
    + [(0, o) for o in range(1, 8)]
    + [(1, 7), (2, 6), (3, 5), (5, 3), (6, 2), (7, 1), (4, 6)]
)
S3_LENGTH = 3000
S3_SRC_CROSS = WINDOW + 0x1_0000 + KIB2 - 1000
S3_DST_ALIGNED = WINDOW + 0x1_4000
S3_SRC_ALIGNED = WINDOW + 0x1_8000
S3_DST_CROSS = WINDOW + 0x1_C000 + KIB2 - 1000
S4_SIZES = (8 * 1024, 64 * 1024)
S4_SRC = (WINDOW + 0x2_0000, WINDOW + 0x4_0000)
S4_DST = (WINDOW + 0x3_0000, WINDOW + 0x6_0000)
S5_SRC = 0x0012_3456_0000_1000
S5_DST = 0x0034_5678_0000_2000
S5_LENGTH = 200
S6_LENGTH = 64
S6_SHIFT = 16
S6_BASE = WINDOW + 0x8_0000
S7_COUNT = 20
S7_BASE = WINDOW + 0x10_0000
S7_STRIDE = 0x4000
S7_DST_BASE = 0x2000
LENGTH_BUCKETS = ((1, 64), (65, 1024), (1025, 4000))
OFFSET_BUCKETS = ((0, 0), (1, 3), (4, 7))

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


def _pattern(seed: int, addr: int) -> int:
    return ((addr * 13) ^ (addr >> 7) ^ seed ^ 0x3C) & 0xFF


class _Copy:
    def __init__(self, name: str, src: int, dst: int, length: int) -> None:
        self.name = name
        self.src = src
        self.dst = dst
        self.length = length
        self.id = -1
        self.payload = b""
        self.ar: list[tuple[int, int, int]] = []
        self.aw: list[tuple[int, int, int]] = []


class _BurstSampler:
    """Records every AR and AW handshake as (address, beats, bytes per beat)."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar: list[tuple[int, int, int]] = []
        self.aw: list[tuple[int, int, int]] = []

    @staticmethod
    def _bit(sig, name: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    async def run(self) -> None:
        dut = self.dut
        ifc = dut.u_output_axi_if
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            for ch, store in (("ar", self.ar), ("aw", self.aw)):
                valid = self._bit(getattr(dut, f"tb_output_axi_{ch}valid"), f"{ch}valid")
                ready = self._bit(getattr(dut, f"tb_output_axi_{ch}ready"), f"{ch}ready")
                if valid and ready:
                    addr = self._bit(getattr(dut, f"tb_output_axi_{ch}addr"), f"{ch}addr")
                    beats = self._bit(getattr(ifc, f"{ch}len"), f"u_output_axi_if.{ch}len") + 1
                    size = self._bit(getattr(ifc, f"{ch}size"), f"u_output_axi_if.{ch}size")
                    store.append((addr, beats, 1 << size))


def _burst_last_byte(addr: int, beats: int, bytes_per_beat: int) -> int:
    return (addr & ~(bytes_per_beat - 1)) + beats * bytes_per_beat - 1


class smc_dma_linear_copy_test_seq(SmcCsrSeq):
    """Linear copies with offsets, 2 KiB-crossing sources, large sizes, 56-bit addresses."""

    def __init__(self, name: str = "smc_dma_linear_copy_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.sampler: _BurstSampler | None = None
        self.seed = 0
        self.rng = random.Random(0)
        self.next_expected_id = 0

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

    def _fill_guards(self, c: _Copy) -> None:
        self._responder.write(c.dst - GUARD, bytes([GUARD_BYTE]) * GUARD)
        self._responder.write(c.dst, bytes([POISON]) * c.length)
        self._responder.write(c.dst + c.length, bytes([GUARD_BYTE]) * GUARD)

    def _seed_copy(self, c: _Copy, payload: bytes | None = None) -> None:
        c.payload = payload or bytes(_pattern(self.seed, c.src + i) for i in range(c.length))
        self._responder.write(c.src, c.payload)
        self._fill_guards(c)

    def _compare(self, c: _Copy) -> None:
        got = bytes(self._responder.read(c.dst, c.length))
        assert got == c.payload, (
            f"{c.name}: destination 0x{c.dst:x} differs from the source at byte "
            f"{next(i for i, (a, b) in enumerate(zip(got, c.payload)) if a != b)} "
            f"({c.length} bytes, got {got[:16].hex()}..., want {c.payload[:16].hex()}...)"
        )
        before = bytes(self._responder.read(c.dst - GUARD, GUARD))
        after = bytes(self._responder.read(c.dst + c.length, GUARD))
        want = bytes([GUARD_BYTE]) * GUARD
        assert before == want and after == want, (
            f"{c.name}: guard bytes changed: before={before.hex()} after={after.hex()}"
        )
        src = bytes(self._responder.read(c.src, c.length))
        assert src == c.payload, f"{c.name}: the source bytes changed"

    async def _program(self, c: _Copy) -> None:
        for reg, value in (
            (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            (DMA_CTRL_DST_ADDRESS_LO, c.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, c.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, c.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, c.src >> 32),
            (DMA_CTRL_LENGTH_LO, c.length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, 0),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, 0),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, 1),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{c.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, c: _Copy) -> None:
        # Reading NEXT_ID launches the programmed descriptor.
        c.id = await self.csr_read(f"{c.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        assert c.id == self.next_expected_id + 1, (
            f"{c.name}: NEXT_ID returned {c.id} after DONE {self.next_expected_id}"
        )

    async def _await_done(self, c: _Copy) -> None:
        done = -1
        for _ in range(POLL_LIMIT):
            done = await self.csr_read(f"{c.name}_DONE", DMA_CTRL_DONE_0)
            if done == c.id:
                self.next_expected_id = c.id
                return
            assert done < c.id, f"{c.name}: DONE_0 reads {done}, past its id {c.id}"
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        status = await self.csr_read(f"{c.name}_STATUS", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"{c.name}: DONE_0 reached {done}, not id {c.id} within {POLL_LIMIT} polls "
            f"(status 0x{status:x}, tb_dma_busy {self._busy()})"
        )

    def _busy(self) -> int:
        value = cocotb.top.tb_dma_busy.value
        assert value.is_resolvable, f"tb_dma_busy is X/Z ({value})"
        return int(value)

    async def _run(self, c: _Copy, *, seed: bool = True) -> None:
        if seed:
            self._seed_copy(c)
        s = self.sampler
        ar0, aw0 = len(s.ar), len(s.aw)
        await self._program(c)
        await self._launch(c)
        await self._await_done(c)
        c.ar = [b for b in s.ar[ar0:] if c.src - 8 <= b[0] < c.src + c.length + 8]
        c.aw = [b for b in s.aw[aw0:] if c.dst - 8 <= b[0] < c.dst + c.length + 8]

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        for name in _IF_SIGNALS:
            assert hasattr(dut.u_output_axi_if, name), f"u_output_axi_if has no {name}"
        await self._pass_all()
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.rng = random.Random(self.seed)
        cocotb.log.info("seed=%d", self.seed)
        self.sampler = _BurstSampler(dut)
        cocotb.start_soon(self.sampler.run())
        self.next_expected_id = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> str:
        for i, (so, do) in enumerate(S2_OFFSETS):
            base = WINDOW + i * S2_STRIDE
            c = _Copy(f"UNAL{i}", base + so, base + S2_DST_BASE + do, S2_LENGTH)
            await self._run(c)
            self._compare(c)
        self._mark("S2")
        kinds = (
            f"{sum(1 for so, do in S2_OFFSETS if so and not do)} source-offset, "
            f"{sum(1 for so, do in S2_OFFSETS if do and not so)} destination-offset, "
            f"{sum(1 for so, do in S2_OFFSETS if so and do and so != do)} unequal-offset"
        )
        return (
            f"{len(S2_OFFSETS)} copies of {S2_LENGTH} bytes ({kinds}) delivered the exact payload "
            f"with {GUARD} guard bytes either side unchanged and the source unchanged"
        )

    def _check_bursts(self, c: _Copy) -> tuple[int, int, int]:
        assert c.ar and c.aw, f"{c.name}: no AR or AW burst observed (ar={c.ar} aw={c.aw})"
        longest = 0
        for kind, bursts in (("AR", c.ar), ("AW", c.aw)):
            for addr, beats, bpb in bursts:
                last = _burst_last_byte(addr, beats, bpb)
                assert beats <= MAX_BEATS, f"{c.name}: {kind} 0x{addr:x} has {beats} beats"
                assert addr // KIB2 == last // KIB2, (
                    f"{c.name}: {kind} burst 0x{addr:x}..0x{last:x} ({beats} beats) crosses a "
                    f"2 KiB boundary"
                )
                longest = max(longest, beats)
        return len(c.ar), len(c.aw), longest

    async def _s3(self) -> str:
        cases = (
            _Copy("SRC_CROSS", S3_SRC_CROSS, S3_DST_ALIGNED, S3_LENGTH),
            _Copy("DST_CROSS", S3_SRC_ALIGNED, S3_DST_CROSS, S3_LENGTH),
        )
        assert (cases[0].src // KIB2) != ((cases[0].src + S3_LENGTH - 1) // KIB2)
        assert (cases[1].dst // KIB2) != ((cases[1].dst + S3_LENGTH - 1) // KIB2)
        parts = []
        for c in cases:
            await self._run(c)
            self._compare(c)
            nar, naw, longest = self._check_bursts(c)
            parts.append(
                f"{c.name} src 0x{c.src:x} dst 0x{c.dst:x}: {nar} AR and {naw} AW bursts, "
                f"longest {longest} beats"
            )
        self._mark("S3")
        return (
            f"with SRC_REDUCE_LEN and DST_REDUCE_LEN clear, two {S3_LENGTH}-byte copies delivered "
            f"the exact payload and every observed AR and AW burst has at most {MAX_BEATS} beats "
            f"and stays inside one 2 KiB-aligned block ({'; '.join(parts)})"
        )

    async def _s4(self) -> str:
        parts = []
        for i, size in enumerate(S4_SIZES):
            c = _Copy(f"LARGE{size >> 10}K", S4_SRC[i], S4_DST[i], size)
            await self._run(c)
            self._compare(c)
            parts.append(f"{size} bytes (id {c.id}, DONE_0 {self.next_expected_id})")
        self._mark("S4")
        return (
            f"copies of {' and '.join(parts)} retired with DONE_0 equal to the returned ID and "
            f"every destination byte equals its source byte"
        )

    async def _s5(self) -> str:
        c = _Copy("HI_ADDR", S5_SRC, S5_DST, S5_LENGTH)
        assert (S5_SRC >> 32) and (S5_DST >> 32) and S5_SRC < (1 << 56) and S5_DST < (1 << 56)
        await self._run(c)
        self._compare(c)
        assert c.ar and c.aw, f"{c.name}: no AR or AW burst observed"
        first_ar, first_aw = c.ar[0][0], c.aw[0][0]
        assert first_ar == S5_SRC, f"first AR 0x{first_ar:x}, programmed source 0x{S5_SRC:x}"
        assert first_aw == S5_DST, f"first AW 0x{first_aw:x}, programmed destination 0x{S5_DST:x}"
        self._mark("S5")
        return (
            f"first AR address 0x{first_ar:014x} equals the programmed source 0x{S5_SRC:014x} and "
            f"first AW address 0x{first_aw:014x} equals the programmed destination "
            f"0x{S5_DST:014x}, bits [55:32] 0x{first_ar >> 32:06x} and 0x{first_aw >> 32:06x} "
            f"preserved, {S5_LENGTH} destination bytes equal the source"
        )

    async def _s6(self) -> str:
        results = []
        cases = (
            ("DST_ABOVE", S6_BASE, S6_BASE + S6_SHIFT),
            ("DST_BELOW", S6_BASE + 0x1000 + S6_SHIFT, S6_BASE + 0x1000),
            ("SRC_EQ_DST", S6_BASE + 0x2000, S6_BASE + 0x2000),
        )
        for name, src, dst in cases:
            c = _Copy(name, src, dst, S6_LENGTH)
            lo = min(src, dst)
            span = S6_LENGTH + (S6_SHIFT if src != dst else 0)
            region = bytes(_pattern(self.seed, lo + i) for i in range(span))
            self._responder.write(lo, region)
            original = bytes(self._responder.read(src, S6_LENGTH))
            await self._run(c, seed=False)
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            assert self._busy() == 0, f"{name}: tb_dma_busy still high after DONE_0 reached {c.id}"
            result = bytes(self._responder.read(dst, S6_LENGTH))
            if src == dst:
                assert result == original, (
                    f"{name}: region {result.hex()} changed from {original.hex()}"
                )
            results.append(
                f"{name} src 0x{src:x} dst 0x{dst:x} source pattern {original.hex()} "
                f"result {result.hex()} equals_original_source={result == original}"
            )
        self._mark("S6")
        return (
            f"each overlapping copy retired with DONE_0 equal to its ID and tb_dma_busy low "
            f"(SRC_EQ_DST compared with the unchanged region, the other cases' resulting bytes "
            f"measured and printed): {'; '.join(results)}"
        )

    def _draw_offset(self, bucket: int) -> int:
        lo, hi = OFFSET_BUCKETS[bucket]
        return self.rng.randint(lo, hi)

    async def _s7(self) -> str:
        counts = {"len": [0, 0, 0], "src": [0, 0, 0], "dst": [0, 0, 0]}
        rows = []
        for i in range(S7_COUNT):
            lb, sb, db = i % 3, (i // 3) % 3, (i + i // 3) % 3
            length = self.rng.randint(*LENGTH_BUCKETS[lb])
            so, do = self._draw_offset(sb), self._draw_offset(db)
            payload = bytes(self.rng.getrandbits(8) for _ in range(length))
            counts["len"][lb] += 1
            counts["src"][sb] += 1
            counts["dst"][db] += 1
            base = S7_BASE + i * S7_STRIDE
            c = _Copy(f"RND{i}", base + so, base + S7_DST_BASE + do, length)
            self._seed_copy(c, payload)
            await self._run(c, seed=False)
            self._compare(c)
            rows.append(f"{length}B/{so}/{do}")
        self._mark("S7")
        return (
            f"seed {self.seed} printed before the first copy; {S7_COUNT} copies "
            f"(length/src offset/dst offset {', '.join(rows)}) delivered their exact payload with "
            f"intact guards; length buckets small/mid/large {counts['len']}, source-offset buckets "
            f"aligned/1-3/4-7 {counts['src']}, destination-offset buckets {counts['dst']}"
        )

    async def body(self) -> None:
        await self._s1()
        steps = (
            ("S2", self._s2, "CHK-DMA-LIN-UNALIGNED"),
            ("S3", self._s3, "CHK-DMA-LIN-2KIB-BOUNDARY"),
            ("S4", self._s4, "CHK-DMA-LIN-LARGE"),
            ("S5", self._s5, "CHK-DMA-LIN-HI-ADDR"),
            ("S6", self._s6, "CHK-DMA-LIN-OVERLAP"),
            ("S7", self._s7, "CHK-DMA-LIN-RANDOM"),
        )
        for step, fn, chk in steps:
            text = await fn()
            self._chk(step, chk, text)
        self._nonvac()

    def _nonvac(self) -> None:
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]
        assert [s for s, _ in self.steps] == order, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        want = [
            ("S2", "CHK-DMA-LIN-UNALIGNED"),
            ("S3", "CHK-DMA-LIN-2KIB-BOUNDARY"),
            ("S4", "CHK-DMA-LIN-LARGE"),
            ("S5", "CHK-DMA-LIN-HI-ADDR"),
            ("S6", "CHK-DMA-LIN-OVERLAP"),
            ("S7", "CHK-DMA-LIN-RANDOM"),
        ]
        assert self.chk_steps == want, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
