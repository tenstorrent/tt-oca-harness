# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA burst-length reduction and AW decoupling on the SYS_OUT address channels.

Contract SMC_POWER_DMA_ZEROER_016, anchor smc_dma_burst_shaping_test.
Scenarios DMA-BURST-SHAPING.S1, S2, S3, S4, S5, S6, S8 (reduction off, source and destination
length limits, ignored and independent limits, AW after and before the first R beat, all bits).
Specs vendor idma overlay dma_ctrl.rdl (CONFIG), hw/sys/smc/doc/dma.adoc.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. Every AR and AW handshake and every R beat of the exported SYS_OUT probes
is recorded per clk_smc_i rise with the length and size from u_output_axi_if.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    _DMA_CTRL_H,
    DMA_CONFIG_DECOUPLE_AW,
    DMA_CONFIG_DECOUPLE_RW,
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
    _field_mask,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import PASS_ALL_CONFIG

WINDOW = 0x0200_0000
LENGTH = 4096
GUARD = 8
GUARD_BYTE = 0xEE
POISON = 0xA5
KIB2 = 2048
MAX_BEATS = 256
POLL_LIMIT = 3000
POLL_CYCLES = 50
AR_WAIT_CYCLES = 2000
AW_WAIT_CYCLES = 2000
HOLD_WINDOW_CYCLES = 256

SRC_REDUCE = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__SRC_REDUCE_LEN_bm")
DST_REDUCE = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__DST_REDUCE_LEN_bm")
SRC_LLEN_BP = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__SRC_MAX_LLEN_bp")
DST_LLEN_BP = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__DST_MAX_LLEN_bp")
SRC_LLEN_BM = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__SRC_MAX_LLEN_bm")
DST_LLEN_BM = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__DST_MAX_LLEN_bm")

# Both ends sit 1 KiB into a 2 KiB block, so a 4 KiB copy crosses 2 KiB boundaries on each side.
SRC_UNALIGNED = WINDOW + 0x1_0400
DST_UNALIGNED = WINDOW + 0x2_0400
# Both ends are 4 KiB aligned, so unreduced bursts can reach 256 beats.
SRC_ALIGNED = WINDOW + 0x3_0000
DST_ALIGNED = WINDOW + 0x4_0000

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
CHECKS = (
    ("S2", "CHK-DMA-BURST-REDUCE-OFF"),
    ("S3", "CHK-DMA-BURST-SRC-LLEN"),
    ("S4", "CHK-DMA-BURST-DST-LLEN"),
    ("S5", "CHK-DMA-BURST-IGNORED-INDEPENDENT"),
    ("S6", "CHK-DMA-AW-AFTER-FIRST-R"),
    ("S7", "CHK-DMA-AW-BEFORE-FIRST-R"),
    ("S8", "CHK-DMA-BURST-ALL-BITS"),
)

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_araddr",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_output_axi_rvalid",
    "tb_output_axi_rready",
    "tb_output_axi_resp_hold",
)
_IF_SIGNALS = ("arlen", "arsize", "awlen", "awsize")

# (cycle, address, beats, bytes per beat)
Burst = tuple[int, int, int, int]


def _pattern(tag: int, addr: int) -> int:
    return ((addr * 13) ^ (addr >> 7) ^ tag ^ 0x3C) & 0xFF


def _last_byte(addr: int, beats: int, bytes_per_beat: int) -> int:
    return (addr & ~(bytes_per_beat - 1)) + beats * bytes_per_beat - 1


class _Sampler:
    """Records AR and AW handshakes and R beat cycles at every clk_smc_i rise."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cycle = 0
        self.ar: list[Burst] = []
        self.aw: list[Burst] = []
        self.r_beats: list[int] = []

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
            self.cycle += 1
            for ch, store in (("ar", self.ar), ("aw", self.aw)):
                valid = self._bit(getattr(dut, f"tb_output_axi_{ch}valid"), f"{ch}valid")
                ready = self._bit(getattr(dut, f"tb_output_axi_{ch}ready"), f"{ch}ready")
                if valid and ready:
                    addr = self._bit(getattr(dut, f"tb_output_axi_{ch}addr"), f"{ch}addr")
                    beats = self._bit(getattr(ifc, f"{ch}len"), f"u_output_axi_if.{ch}len") + 1
                    size = self._bit(getattr(ifc, f"{ch}size"), f"u_output_axi_if.{ch}size")
                    store.append((self.cycle, addr, beats, 1 << size))
            if self._bit(dut.tb_output_axi_rvalid, "rvalid") and self._bit(
                dut.tb_output_axi_rready, "rready"
            ):
                self.r_beats.append(self.cycle)


class _Run:
    def __init__(self, name: str, src: int, dst: int, config: int) -> None:
        self.name = name
        self.src = src
        self.dst = dst
        self.config = config
        self.id = -1
        self.payload = b""
        self.ar: list[Burst] = []
        self.aw: list[Burst] = []
        self.r_first = -1


class smc_dma_burst_shaping_test_seq(SmcCsrSeq):
    """4 KiB copies under each CONFIG burst-shaping mode."""

    def __init__(self, name: str = "smc_dma_burst_shaping_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.sampler: _Sampler | None = None
        self.next_expected_id = 0
        self.tag = 0

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

    @staticmethod
    def _config(
        *,
        aw: bool = False,
        rw: bool = False,
        src: int | None = None,
        dst: int | None = None,
        src_llen: int = 0,
        dst_llen: int = 0,
    ) -> int:
        value = DMA_CONFIG_ENABLED_ND
        value |= DMA_CONFIG_DECOUPLE_AW if aw else 0
        value |= DMA_CONFIG_DECOUPLE_RW if rw else 0
        value |= SRC_REDUCE if src is not None else 0
        value |= DST_REDUCE if dst is not None else 0
        value |= (src_llen << SRC_LLEN_BP) & SRC_LLEN_BM
        value |= (dst_llen << DST_LLEN_BP) & DST_LLEN_BM
        return value

    def _seed(self, r: _Run) -> None:
        self.tag += 1
        r.payload = bytes(_pattern(self.tag, r.src + i) for i in range(LENGTH))
        self._responder.write(r.src, r.payload)
        self._responder.write(r.dst - GUARD, bytes([GUARD_BYTE]) * GUARD)
        self._responder.write(r.dst, bytes([POISON]) * LENGTH)
        self._responder.write(r.dst + LENGTH, bytes([GUARD_BYTE]) * GUARD)

    def _compare(self, r: _Run) -> None:
        got = bytes(self._responder.read(r.dst, LENGTH))
        assert got == r.payload, (
            f"{r.name}: destination 0x{r.dst:x} differs from the source at byte "
            f"{next(i for i, (a, b) in enumerate(zip(got, r.payload)) if a != b)} "
            f"(got {got[:16].hex()}..., want {r.payload[:16].hex()}...)"
        )
        want = bytes([GUARD_BYTE]) * GUARD
        before = bytes(self._responder.read(r.dst - GUARD, GUARD))
        after = bytes(self._responder.read(r.dst + LENGTH, GUARD))
        assert before == want and after == want, (
            f"{r.name}: guard bytes changed: before={before.hex()} after={after.hex()}"
        )

    async def _program(self, r: _Run) -> None:
        await self.csr_write(f"{r.name}_CONFIG", DMA_CTRL_CONFIG, r.config)
        await self.csr_read(f"{r.name}_CONFIG_RB", DMA_CTRL_CONFIG, expected=r.config)
        for reg, value in (
            (DMA_CTRL_DST_ADDRESS_LO, r.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, r.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, r.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, r.src >> 32),
            (DMA_CTRL_LENGTH_LO, LENGTH),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, 0),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, 0),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, 1),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{r.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, r: _Run) -> None:
        r.id = await self.csr_read(f"{r.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        assert r.id == self.next_expected_id + 1, (
            f"{r.name}: NEXT_ID returned {r.id} after DONE {self.next_expected_id}"
        )

    async def _await_done(self, r: _Run) -> None:
        done = -1
        for _ in range(POLL_LIMIT):
            done = await self.csr_read(f"{r.name}_DONE", DMA_CTRL_DONE_0)
            if done == r.id:
                self.next_expected_id = r.id
                return
            assert done < r.id, f"{r.name}: DONE_0 reads {done}, past its id {r.id}"
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        status = await self.csr_read(f"{r.name}_STATUS", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"{r.name}: DONE_0 reached {done}, not id {r.id} within {POLL_LIMIT} polls "
            f"of {POLL_CYCLES} clk_smc_i cycles (status 0x{status:x}, "
            f"AR {len(self._s.ar)} AW {len(self._s.aw)} R beats {len(self._s.r_beats)})"
        )

    @property
    def _s(self) -> _Sampler:
        assert self.sampler is not None, "sampler not started"
        return self.sampler

    def _collect(self, r: _Run, ar0: int, aw0: int, rb0: int) -> None:
        s = self._s
        r.ar = [b for b in s.ar[ar0:] if r.src - 8 <= b[1] < r.src + LENGTH + 8]
        r.aw = [b for b in s.aw[aw0:] if r.dst - 8 <= b[1] < r.dst + LENGTH + 8]
        beats = s.r_beats[rb0:]
        r.r_first = beats[0] if beats else -1

    async def _run(self, r: _Run) -> None:
        self._seed(r)
        s = self._s
        marks = (len(s.ar), len(s.aw), len(s.r_beats))
        await self._program(r)
        await self._launch(r)
        await self._await_done(r)
        self._collect(r, *marks)
        self._compare(r)
        total_ar = sum(b[2] * b[3] for b in r.ar)
        total_aw = sum(b[2] * b[3] for b in r.aw)
        assert total_ar >= LENGTH and total_aw >= LENGTH, (
            f"{r.name}: AR bursts cover {total_ar} bytes and AW bursts {total_aw}, "
            f"the copy is {LENGTH}"
        )

    @staticmethod
    def _limit(r: _Run, kind: str, bursts: list[Burst], beats_max: int, block: int) -> int:
        """Assert every burst has at most beats_max beats inside one aligned block."""
        assert bursts, f"{r.name}: no {kind} burst observed"
        longest = 0
        for _, addr, beats, bpb in bursts:
            last = _last_byte(addr, beats, bpb)
            assert beats <= beats_max, (
                f"{r.name}: {kind} burst 0x{addr:x} has {beats} beats, limit {beats_max}"
            )
            assert addr // block == last // block, (
                f"{r.name}: {kind} burst 0x{addr:x}..0x{last:x} ({beats} beats) crosses a "
                f"{block}-byte boundary"
            )
            longest = max(longest, beats)
        return longest

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        for name in _IF_SIGNALS:
            assert hasattr(dut.u_output_axi_if, name), f"u_output_axi_if has no {name}"
        await self.wait_fuse_sense_done()
        dut.tb_output_axi_resp_hold.value = 0
        await self._pass_all()
        self.sampler = _Sampler(dut)
        cocotb.start_soon(self.sampler.run())
        self.next_expected_id = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> str:
        r = _Run("OFF", SRC_UNALIGNED, DST_UNALIGNED, self._config())
        assert r.src // KIB2 != (r.src + LENGTH - 1) // KIB2
        assert r.dst // KIB2 != (r.dst + LENGTH - 1) // KIB2
        await self._run(r)
        lr = self._limit(r, "AR", r.ar, MAX_BEATS, KIB2)
        lw = self._limit(r, "AW", r.aw, MAX_BEATS, KIB2)
        self._mark("S2")
        return (
            f"with SRC_REDUCE_LEN and DST_REDUCE_LEN clear, a {LENGTH}-byte copy from 0x{r.src:x} "
            f"to 0x{r.dst:x} (both crossing a 2 KiB boundary) delivered the exact payload; "
            f"{len(r.ar)} AR bursts (longest {lr} beats) and {len(r.aw)} AW bursts (longest "
            f"{lw} beats) each have at most {MAX_BEATS} beats and stay inside one 2 KiB block"
        )

    async def _s3(self) -> str:
        parts = []
        for n in range(8):
            r = _Run(f"SRC{n}", SRC_UNALIGNED, DST_UNALIGNED, self._config(src=1, src_llen=n))
            await self._run(r)
            longest = self._limit(r, "AR", r.ar, 1 << n, 1 << (n + 3))
            if n == 0:
                assert longest == 1, f"{r.name}: multi-beat read at SRC_MAX_LLEN 0"
            parts.append(f"n={n}: {len(r.ar)} AR bursts longest {longest} (limit {1 << n})")
        self._mark("S3")
        return (
            f"with SRC_REDUCE_LEN set, each {LENGTH}-byte copy delivered the exact payload and "
            f"every AR burst has at most 2^n beats inside one 2^(n+3)-byte block; "
            + "; ".join(parts)
        )

    async def _s4(self) -> str:
        parts = []
        for n in range(8):
            r = _Run(f"DST{n}", SRC_UNALIGNED, DST_UNALIGNED, self._config(dst=1, dst_llen=n))
            await self._run(r)
            longest = self._limit(r, "AW", r.aw, 1 << n, 1 << (n + 3))
            if n == 0:
                assert longest == 1, f"{r.name}: multi-beat write at DST_MAX_LLEN 0"
            parts.append(f"n={n}: {len(r.aw)} AW bursts longest {longest} (limit {1 << n})")
        self._mark("S4")
        return (
            f"with DST_REDUCE_LEN set, each {LENGTH}-byte copy delivered the exact payload and "
            f"every AW burst has at most 2^n beats inside one 2^(n+3)-byte block; "
            + "; ".join(parts)
        )

    async def _s5(self) -> str:
        cases = (
            ("IGN_BOTH", self._config(src_llen=0, dst_llen=0), None, None),
            ("SRC_ONLY", self._config(src=1, src_llen=1, dst_llen=0), 2, None),
            ("DST_ONLY", self._config(dst=1, dst_llen=1, src_llen=0), None, 2),
        )
        parts = []
        for name, config, src_cap, dst_cap in cases:
            r = _Run(name, SRC_ALIGNED, DST_ALIGNED, config)
            await self._run(r)
            cap = src_cap or dst_cap
            if cap is None:
                lr = self._limit(r, "AR", r.ar, MAX_BEATS, KIB2)
                lw = self._limit(r, "AW", r.aw, MAX_BEATS, KIB2)
                assert lr == MAX_BEATS, f"{name}: AR longest {lr} beats, not capped by anything"
                assert lw == MAX_BEATS, f"{name}: AW longest {lw} beats, not capped by anything"
            else:
                lr = self._limit(r, "AR", r.ar, cap, KIB2)
                lw = self._limit(r, "AW", r.aw, cap, KIB2)
                assert len(r.ar) == len(r.aw), (
                    f"{name}: {len(r.ar)} AR bursts but {len(r.aw)} AW bursts in coupled mode"
                )
            parts.append(
                f"{name} CONFIG 0x{config:x}: AR longest {lr} beats, AW longest {lw} beats, "
                f"{len(r.ar)} AR and {len(r.aw)} AW bursts"
            )
        self._mark("S5")
        return (
            f"in coupled mode, MAX_LLEN with the reduction bit clear leaves bursts at up to "
            f"{MAX_BEATS} beats, and with reduction on one direction only every burst of both "
            f"directions has at most the reduced cap of 2 beats; each copy delivered the exact "
            f"payload; " + "; ".join(parts)
        )

    async def _held(self, r: _Run, *, aw: bool) -> tuple[int, int, int, int]:
        """Run one copy with the SYS_OUT R channel held through the first read burst.

        Returns (AW handshakes while held, R beats while held, AW before first R beat,
        cycles held).
        """
        dut = cocotb.top
        s = self._s
        self._seed(r)
        marks = (len(s.ar), len(s.aw), len(s.r_beats))
        await self._program(r)
        dut.tb_output_axi_resp_hold.value = 1
        try:
            await self._launch(r)
            held_from = s.cycle
            for _ in range(AR_WAIT_CYCLES):
                if len(s.ar) > marks[0]:
                    break
                await RisingEdge(dut.clk_smc_i)
            else:
                raise AssertionError(
                    f"{r.name}: no AR handshake within {AR_WAIT_CYCLES} clk_smc_i cycles of the "
                    f"launch with R held (AR {len(s.ar) - marks[0]})"
                )
            if aw:
                for _ in range(AW_WAIT_CYCLES):
                    if len(s.aw) > marks[1]:
                        break
                    await RisingEdge(dut.clk_smc_i)
                else:
                    raise AssertionError(
                        f"{r.name}: no AW handshake within {AW_WAIT_CYCLES} clk_smc_i cycles "
                        f"with R held and DECOUPLE_AW set (AR {len(s.ar) - marks[0]}, "
                        f"R beats {len(s.r_beats) - marks[2]})"
                    )
            else:
                await ClockCycles(dut.clk_smc_i, HOLD_WINDOW_CYCLES)
            aw_held = len(s.aw) - marks[1]
            r_held = len(s.r_beats) - marks[2]
            held_cycles = s.cycle - held_from
        finally:
            dut.tb_output_axi_resp_hold.value = 0
        await self._await_done(r)
        self._collect(r, *marks)
        self._compare(r)
        assert r.r_first >= 0, f"{r.name}: no R beat returned after the release"
        before = sum(1 for b in r.aw if b[0] < r.r_first)
        return aw_held, r_held, before, held_cycles

    async def _s6(self) -> str:
        r = _Run("AW_COUPLED", SRC_ALIGNED, DST_ALIGNED, self._config())
        aw_held, r_held, before, cycles = await self._held(r, aw=False)
        assert r_held == 0, f"{r.name}: {r_held} R beats returned while the hold was set"
        assert aw_held == 0, (
            f"{r.name}: {aw_held} AW handshakes while R was held for {cycles} cycles with "
            f"DECOUPLE_AW clear"
        )
        assert before == 0, (
            f"{r.name}: {before} AW handshakes before the first R beat at cycle {r.r_first}"
        )
        self._mark("S6")
        return (
            f"with DECOUPLE_AW clear and R held for {cycles} clk_smc_i cycles after the first AR "
            f"handshake, {aw_held} AW handshakes and {r_held} R beats occurred while held and "
            f"{before} AW handshakes preceded the first R beat (cycle {r.r_first}); after the "
            f"release the {LENGTH}-byte payload is exact"
        )

    async def _s7(self) -> str:
        r = _Run("AW_DECOUPLED", SRC_ALIGNED, DST_ALIGNED, self._config(aw=True))
        aw_held, r_held, before, cycles = await self._held(r, aw=True)
        assert r_held == 0, f"{r.name}: {r_held} R beats returned while the hold was set"
        assert aw_held >= 1 and before >= 1, (
            f"{r.name}: {aw_held} AW handshakes while R was held, {before} before the first R "
            f"beat at cycle {r.r_first}"
        )
        self._mark("S7")
        return (
            f"with DECOUPLE_AW set and R held, {aw_held} AW handshake(s) occurred within {cycles} "
            f"clk_smc_i cycles of the first AR handshake with {r_held} R beats returned, and "
            f"{before} AW handshakes preceded the first R beat (cycle {r.r_first}); after the "
            f"release the {LENGTH}-byte payload is exact"
        )

    async def _s8(self) -> str:
        config = self._config(aw=True, rw=True, src=1, dst=1, src_llen=2, dst_llen=2)
        r = _Run("ALL_BITS", SRC_UNALIGNED, DST_UNALIGNED, config)
        await self._run(r)
        lr = self._limit(r, "AR", r.ar, 4, 32)
        lw = self._limit(r, "AW", r.aw, 4, 32)
        await self.csr_write("RESTORE_CONFIG", DMA_CTRL_CONFIG, 0)
        await self.csr_read("RESTORE_CONFIG_RB", DMA_CTRL_CONFIG, expected=0)
        self._mark("S8")
        return (
            f"with DECOUPLE_AW, DECOUPLE_RW, SRC_REDUCE_LEN and DST_REDUCE_LEN set and both "
            f"MAX_LLEN at 2 (CONFIG 0x{config:x}) the {LENGTH}-byte copy completed within "
            f"{POLL_LIMIT} DONE polls of {POLL_CYCLES} clk_smc_i cycles with the exact payload; "
            f"{len(r.ar)} AR bursts (longest {lr} beats) and {len(r.aw)} AW bursts (longest "
            f"{lw} beats) each have at most 4 beats inside one 32-byte block"
        )

    async def body(self) -> None:
        await self._s1()
        steps = (
            ("S2", self._s2),
            ("S3", self._s3),
            ("S4", self._s4),
            ("S5", self._s5),
            ("S6", self._s6),
            ("S7", self._s7),
            ("S8", self._s8),
        )
        checks = dict(CHECKS)
        for step, fn in steps:
            text = await fn()
            self._chk(step, checks[step], text)
        self._nonvac()

    def _nonvac(self) -> None:
        assert [s for s, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_steps == list(CHECKS), f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
