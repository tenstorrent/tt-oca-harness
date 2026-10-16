# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA commands with ENABLED_ND cleared and with a zero length, against a valid copy.

Specs hw/sys/smc/doc/dma.adoc, vendor idma dma_ctrl.rdl.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. Every SYS_OUT AR and AW handshake and bit 322 of tb_cpu_interrupts is
sampled on each clk_smc_i rise. The valid copy of leg c is the positive control of the
no-data compares.
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
SRC_BASE = WINDOW
DST_BASE = WINDOW + 0x800
POISON = 0xEE
POLL_LIMIT = 3000
POLL_CYCLES = 50
FURTHER_READS = 6
IRQ_BIT = 322
STATUS_MASK = 0x3FF

LENGTH = 16
SRC_STRIDE = 0x30
DST_STRIDE = 0x28
ROWS_2D = 4
SPAN_2D = (ROWS_2D - 1) * DST_STRIDE + LENGTH

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_araddr",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_output_axi_resp_hold",
    "tb_dma_busy",
    "tb_cpu_interrupts",
)


def _pattern(addr: int) -> int:
    return ((addr * 13) ^ (addr >> 7) ^ 0x3C) & 0xFF


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


class _Sampler:
    """Records every AR and AW handshake address and, per clk_smc_i rise, the interrupt bit
    and tb_dma_busy."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar: list[int] = []
        self.aw: list[int] = []
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
            self.irq.append((self._bit(dut.tb_cpu_interrupts, "tb_cpu_interrupts") >> IRQ_BIT) & 1)
            self.busy.append(self._bit(dut.tb_dma_busy, "tb_dma_busy"))


class _Leg:
    def __init__(self, name: str) -> None:
        self.name = name
        self.next_id = -1
        self.done_before = -1
        self.done_after = -1
        self.status_before = -1
        self.status_after = -1
        self.changed = False
        self.reads = 0
        self.further: list[int] = []
        self.ar0 = self.aw0 = self.irq0 = 0
        self.ar: list[int] = []
        self.aw: list[int] = []
        self.irq_end = 0
        self.widths: list[int] = []
        self.data = b""


class smc_dma_invalid_descriptor_test_seq(SmcCsrSeq):
    """ENABLED_ND-cleared and zero-length commands move no data; the valid copy is the control."""

    def __init__(self, name: str = "smc_dma_invalid_descriptor_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.sampler: _Sampler | None = None
        self.legs: dict[str, _Leg] = {}

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
    def _source_image(rows: int) -> list[tuple[int, bytes]]:
        return [
            (
                SRC_BASE + n * SRC_STRIDE,
                bytes(_pattern(SRC_BASE + n * SRC_STRIDE + i) for i in range(LENGTH)),
            )
            for n in range(rows)
        ]

    def _seed_source(self, rows: int) -> None:
        for addr, data in self._source_image(rows):
            self._responder.write(addr, data)

    def _poison(self, span: int) -> None:
        self._responder.write(DST_BASE, bytes([POISON]) * span)

    def _dst(self, span: int) -> bytes:
        return bytes(self._responder.read(DST_BASE, span))

    @staticmethod
    def _expect_poison(label: str, got: bytes) -> None:
        for idx, byte in enumerate(got):
            assert byte == POISON, (
                f"{label}: destination byte 0x{DST_BASE + idx:x} (offset {idx}) is 0x{byte:02x}, "
                f"want 0x{POISON:02x}"
            )

    def _expect_copy(self, label: str, got: bytes) -> None:
        want = b"".join(data for _, data in self._source_image(1))
        assert len(got) == len(want), f"{label}: read {len(got)} bytes, want {len(want)}"
        for idx, (a, b) in enumerate(zip(got, want)):
            assert a == b, (
                f"{label}: destination byte 0x{DST_BASE + idx:x} (offset {idx}) is 0x{a:02x}, "
                f"source byte is 0x{b:02x}"
            )

    async def _program(self, leg: _Leg, config: int, length: int, reps: int) -> None:
        for reg, value in (
            (DMA_CTRL_CONFIG, config),
            (DMA_CTRL_DST_ADDRESS_LO, DST_BASE & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, DST_BASE >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, SRC_BASE & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, SRC_BASE >> 32),
            (DMA_CTRL_LENGTH_LO, length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, DST_STRIDE),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, SRC_STRIDE),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, reps),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{leg.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _submit(self, leg: _Leg, length_bytes: int = 4) -> None:
        """The read of NEXT_ID_0 launches the programmed descriptor."""
        s = self.sampler
        leg.done_before = await self.csr_read(f"{leg.name}_DONE_BEFORE", DMA_CTRL_DONE_0)
        leg.status_before = (
            await self.csr_read(f"{leg.name}_STATUS_BEFORE", DMA_CTRL_STATUS_0)
        ) & STATUS_MASK
        leg.ar0, leg.aw0, leg.irq0 = len(s.ar), len(s.aw), len(s.irq)
        leg.next_id = await self.csr_read(
            f"{leg.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0, length=length_bytes
        )

    async def _poll(self, leg: _Leg) -> None:
        """Polls DONE_0 until it differs from its pre-command value or POLL_LIMIT reads pass."""
        s = self.sampler
        done = leg.done_before
        for _ in range(POLL_LIMIT):
            done = await self.csr_read(f"{leg.name}_DONE", DMA_CTRL_DONE_0)
            leg.reads += 1
            if done != leg.done_before:
                leg.changed = True
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        leg.done_after = done
        leg.ar = s.ar[leg.ar0 :]
        leg.aw = s.aw[leg.aw0 :]
        leg.irq_end = len(s.irq)
        leg.status_after = (
            await self.csr_read(f"{leg.name}_STATUS_AFTER", DMA_CTRL_STATUS_0)
        ) & STATUS_MASK

    async def _further_reads(self, leg: _Leg) -> None:
        for n in range(FURTHER_READS):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            leg.further.append(await self.csr_read(f"{leg.name}_DONE_MORE{n}", DMA_CTRL_DONE_0))
        s = self.sampler
        leg.ar = s.ar[leg.ar0 :]
        leg.aw = s.aw[leg.aw0 :]

    async def _wait_busy_low(self, leg: _Leg) -> None:
        """Ends the leg's interrupt window one clk_smc_i rise after tb_dma_busy first reads low."""
        s = self.sampler
        first = len(s.busy)
        low = None
        for _ in range(POLL_LIMIT):
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            lows = [i for i in range(first, len(s.busy)) if not s.busy[i]]
            if lows and len(s.busy) > lows[0] + 1:
                low = lows[0]
                break
        assert low is not None, f"{leg.name}: tb_dma_busy did not read low in {POLL_LIMIT} rises"
        leg.irq_end = low + 2

    def _irq_window(self, leg: _Leg) -> str:
        s = self.sampler
        assert leg.irq_end > leg.irq0, f"{leg.name}: interrupt sampler holds no sample"
        leg.widths = _pulse_widths(s.irq, leg.irq0, leg.irq_end)
        last_low = not s.irq[leg.irq_end - 1]
        return f"pulses {len(leg.widths)} widths {leg.widths} cycles last_sample_low {last_low}"

    @staticmethod
    def _fmt(leg: _Leg) -> str:
        return (
            f"next_id=0x{leg.next_id:x} done_before={leg.done_before} done_after={leg.done_after} "
            f"done_delta={leg.done_after - leg.done_before} changed={leg.changed} "
            f"polls={leg.reads} status_before=0x{leg.status_before:x} "
            f"status_after=0x{leg.status_after:x} ar={len(leg.ar)} aw={len(leg.aw)}"
        )

    def _copy_leg_checks(self, leg: _Leg) -> None:
        assert leg.changed, (
            f"{leg.name}: DONE_0 still {leg.done_before} after {POLL_LIMIT} reads "
            f"(status 0x{leg.status_after:x})"
        )
        assert leg.further == [leg.done_after] * FURTHER_READS, (
            f"{leg.name}: DONE_0 read {leg.done_after} at the change and {leg.further} on the "
            f"{FURTHER_READS} further reads"
        )

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        dut.tb_output_axi_resp_hold.value = 0
        await self._pass_all()
        self.sampler = _Sampler(dut)
        cocotb.start_soon(self.sampler.run())
        await self.csr_read("DONE_SETUP", DMA_CTRL_DONE_0)
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> list[tuple[str, str]]:
        leg = self.legs["a"] = _Leg("ND_CLEAR")
        self._seed_source(1)
        self._poison(LENGTH)
        await self._program(leg, 0, LENGTH, 1)
        await self._submit(leg)
        await self._poll(leg)
        leg.data = self._dst(LENGTH)
        irq = self._irq_window(leg)
        self._mark("S2")
        measured = (
            f"measured {self._fmt(leg)} bit{IRQ_BIT} {irq}; "
            f"relation of NEXT_ID_0 to DONE_0 and the pulse count are not compared"
        )
        assert leg.changed, (
            f"ND_CLEAR: DONE_0 still {leg.done_before} after {POLL_LIMIT} reads "
            f"(status 0x{leg.status_after:x})"
        )
        self._expect_poison("ND_CLEAR", leg.data)
        assert not leg.ar, f"ND_CLEAR: AR handshakes at {[hex(a) for a in leg.ar]}"
        assert not leg.aw, f"ND_CLEAR: AW handshakes at {[hex(a) for a in leg.aw]}"
        return [
            ("CHK-DMA-ND-CLEAR-MEASURED", measured),
            (
                "CHK-DMA-ND-CLEAR-NO-DATA",
                f"CONFIG 0 command retired (DONE_0 {leg.done_before} -> {leg.done_after}); "
                f"all {LENGTH} destination bytes are 0x{POISON:02x} and the window from the "
                f"submit to the DONE_0 change holds AR {len(leg.ar)} AW {len(leg.aw)}; "
                f"positive control: the valid copy of leg c moves data",
            ),
            (
                "CHK-DMA-ND-CLEAR-DONE-ADVANCES",
                f"DONE_0 read {leg.done_after} after the CONFIG 0 command, differing from the "
                f"pre-command {leg.done_before}, after {leg.reads} reads (bound {POLL_LIMIT})",
            ),
        ]

    async def _zero_leg(self, name: str, reps: int, span: int) -> _Leg:
        leg = self.legs[name] = _Leg(name)
        self._seed_source(max(reps, 1))
        self._poison(span)
        await self._program(leg, DMA_CONFIG_ENABLED_ND, 0, reps)
        await self._submit(leg)
        await self._poll(leg)
        leg.data = self._dst(span)
        return leg

    async def _s3(self) -> list[tuple[str, str]]:
        leg = await self._zero_leg("ZERO_LINEAR", 1, LENGTH)
        self._irq_window(leg)
        self._mark("S3")
        return []

    async def _s4(self) -> list[tuple[str, str]]:
        lin = self.legs["ZERO_LINEAR"]
        leg = await self._zero_leg("ZERO_2D", ROWS_2D, SPAN_2D)
        irq = self._irq_window(leg)
        self._mark("S4")
        for one, span in ((lin, LENGTH), (leg, SPAN_2D)):
            self._expect_poison(one.name, one.data)
            assert len(one.data) == span
            assert not one.ar, f"{one.name}: AR handshakes at {[hex(a) for a in one.ar]}"
            assert not one.aw, f"{one.name}: AW handshakes at {[hex(a) for a in one.aw]}"
        measured = (
            f"measured linear {self._fmt(lin)} bit{IRQ_BIT} pulses {len(lin.widths)} "
            f"widths {lin.widths} cycles; "
            f"2d {self._fmt(leg)} bit{IRQ_BIT} {irq}; post-conditions are not compared"
        )
        return [
            ("CHK-DMA-ZEROLEN-MEASURED", measured),
            (
                "CHK-DMA-ZEROLEN-NO-DATA",
                f"zero-length linear command: {LENGTH} destination bytes all 0x{POISON:02x}, "
                f"AR {len(lin.ar)} AW {len(lin.aw)}; zero-length 2D command (4 rows, strides "
                f"0x{SRC_STRIDE:x}/0x{DST_STRIDE:x}): {SPAN_2D} destination bytes all "
                f"0x{POISON:02x}, AR {len(leg.ar)} AW {len(leg.aw)}; DONE_0 change not compared",
            ),
        ]

    async def _copy_leg(self, name: str, length_bytes: int) -> _Leg:
        leg = self.legs[name] = _Leg(name)
        self._seed_source(1)
        self._poison(LENGTH)
        await self._program(leg, DMA_CONFIG_ENABLED_ND, LENGTH, 1)
        await self._submit(leg, length_bytes)
        await self._poll(leg)
        await self._further_reads(leg)
        return leg

    async def _s5(self) -> list[tuple[str, str]]:
        s = self.sampler
        leg = await self._copy_leg("COPY32", 4)
        await self._wait_busy_low(leg)
        leg.data = self._dst(LENGTH)
        irq = self._irq_window(leg)
        self._mark("S5")
        self._copy_leg_checks(leg)
        self._expect_copy("COPY32", leg.data)
        assert len(leg.ar) >= 1 and len(leg.aw) >= 1, (
            f"COPY32: AR {len(leg.ar)} AW {len(leg.aw)} handshakes for a {LENGTH}-byte copy"
        )
        assert leg.widths == [1], f"COPY32: bit {IRQ_BIT} pulse widths {leg.widths}, want [1]"
        assert not s.irq[leg.irq_end - 1], f"COPY32: bit {IRQ_BIT} high on the last sample"
        return [
            (
                "CHK-DMA-COPY-CONTROL",
                f"CONFIG ENABLED_ND set, LENGTH {LENGTH}: destination equals source after DONE_0 "
                f"{leg.done_before} -> {leg.done_after} in {leg.reads} reads; AR {len(leg.ar)} "
                f"AW {len(leg.aw)} (each at least 1)",
            ),
            (
                "CHK-DMA-SUBMIT-32BIT",
                f"32-bit read of NEXT_ID_0 launched one command: DONE_0 {leg.done_before} -> "
                f"{leg.done_after} and {leg.further} on the {FURTHER_READS} further reads; "
                f"destination equals source",
            ),
            (
                "CHK-DMA-IRQ-PULSE-COPY",
                f"bit {IRQ_BIT} {irq}: exactly one pulse, one clk_smc_i cycle wide, between the "
                f"submit and one rise after tb_dma_busy read low; last sample low",
            ),
        ]

    async def _s6(self) -> list[tuple[str, str]]:
        leg = await self._copy_leg("COPY64", 8)
        leg.data = self._dst(LENGTH)
        self._mark("S6")
        ref = self.legs["COPY32"]
        self._copy_leg_checks(leg)
        self._expect_copy("COPY64", leg.data)
        assert (len(leg.ar), len(leg.aw)) == (len(ref.ar), len(ref.aw)), (
            f"COPY64: AR {len(leg.ar)} AW {len(leg.aw)}, the 32-bit copy counted "
            f"AR {len(ref.ar)} AW {len(ref.aw)}"
        )
        return [
            (
                "CHK-DMA-SUBMIT-64BIT",
                f"64-bit read at 0x48 launched one command: destination equals source, DONE_0 "
                f"{leg.done_before} -> {leg.done_after} and {leg.further} on {FURTHER_READS} "
                f"further reads; AR {len(leg.ar)} AW {len(leg.aw)} equal the 32-bit copy's "
                f"AR {len(ref.ar)} AW {len(ref.aw)}",
            )
        ]

    async def body(self) -> None:
        await self._s1()
        steps = (
            ("S2", self._s2),
            ("S3", self._s3),
            ("S4", self._s4),
            ("S5", self._s5),
            ("S6", self._s6),
        )
        order = ["S1"]
        for step, fn in steps:
            lines = await fn()
            order.append(step)
            for chk, text in lines:
                self._chk(step, chk, text)
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S7")
        order.append("S7")
        self._nonvac(order)

    def _nonvac(self, order: list[str]) -> None:
        assert [s for s, _ in self.steps] == order, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        s = self.sampler
        copies = [self.legs["COPY32"], self.legs["COPY64"]]
        want_ar = sum(len(leg.ar) for leg in copies)
        want_aw = sum(len(leg.aw) for leg in copies)
        assert (len(s.ar), len(s.aw)) == (want_ar, want_aw), (
            f"leaf-wide handshakes AR {len(s.ar)} AW {len(s.aw)}, the two copies account for "
            f"AR {want_ar} AW {want_aw}"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; leaf-wide AR %d AW %d equal the two "
            "copies' AR %d AW %d; checker lines %s; stamps %s",
            len(s.ar),
            len(s.aw),
            want_ar,
            want_aw,
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
