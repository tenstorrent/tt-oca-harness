# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA reference-mode copies through the SYS_OUT responder with both decouple bits clear.

Spec sources: dma.adoc Linear and Two-Dimensional Copies, dma_ctrl.rdl CONFIG / NEXT_ID / DONE.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
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
)

MODEL_REGION = "dma_traffic_shape"
MODEL_BASE = 0x0200_0000
MODEL_SIZE = 0x1_0000
SENTINEL = 0xEE
FUSE_SENSE_BOUND = 200_000
AXI_TIMEOUT_NS = 50_000
DONE_POLL_BOUND = 2000
S2_ROWS = 4
S2_ROW_BYTES = 8
S2_SRC = 0x0200_0000
S2_DST = 0x0200_1000
S2_DST_STRIDE = 0x40
S3_SRC = 0x0200_2000
S3_DST = 0x0200_3000
S3_BYTES = 64
S4_COUNT = 4
S4_SRC = 0x0200_4000
S4_DST = 0x0200_5000
S4_STEP = 0x100
S4_ROW_BYTES = 8
S5_SRC = 0x0200_8000
S5_DST = 0x0200_A000
S5_BYTES = 256
DESCRIPTORS = 1 + 1 + S4_COUNT + 1
# S1 CONFIG read and write, DONE baseline, 13 accesses per descriptor, S6 write and read.
MIN_SEP_IN_ACCESSES = 3 + 13 * DESCRIPTORS + 2

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_TERMS = ("SETUP", "COUPLED_2D", "LINEAR", "QUEUE_FOUR", "PAGE_ALIGNED", "TEARDOWN")
_CHECKERS = (
    ("CHK-DTS-COUPLED-COPY", "S2"),
    ("CHK-DTS-LINEAR", "S3"),
    ("CHK-DTS-QUEUE-FOUR", "S4"),
    ("CHK-DTS-PAGE-ALIGNED", "S5"),
)
_TB_SIGNALS = tuple(
    f"tb_output_axi_{ch}{kind}" for ch in ("ar", "aw", "w") for kind in ("valid", "ready")
) + ("tb_output_axi_araddr", "tb_output_axi_awaddr")


def _pattern(tag: int, addr: int) -> int:
    return ((addr * 29) ^ (addr >> 5) ^ tag) & 0xFF


class _OutputSampler:
    """Records first-valid cycles and AR/AW handshake addresses at output_axi."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cycle = 0
        self.first: dict[str, int] = {}
        self.ar: list[int] = []
        self.aw: list[int] = []
        self.w_beats = 0

    def begin(self) -> None:
        self.first = {}
        self.ar = []
        self.aw = []
        self.w_beats = 0

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
            self.cycle += 1
            for ch in ("ar", "aw", "w"):
                valid = self._bit(getattr(dut, f"tb_output_axi_{ch}valid"), f"{ch}valid")
                ready = self._bit(getattr(dut, f"tb_output_axi_{ch}ready"), f"{ch}ready")
                if valid:
                    self.first.setdefault(ch, self.cycle)
                if valid and ready:
                    if ch == "w":
                        self.w_beats += 1
                    else:
                        addr = self._bit(getattr(dut, f"tb_output_axi_{ch}addr"), f"{ch}addr")
                        (self.ar if ch == "ar" else self.aw).append(addr)

    def first_order(self) -> str:
        seen = sorted((cyc, ch) for ch, cyc in self.first.items())
        return ",".join(f"{ch}valid@{cyc}" for cyc, ch in seen) or "none"

    def addrs(self) -> str:
        ar = ",".join(f"0x{a:x}" for a in self.ar) or "none"
        aw = ",".join(f"0x{a:x}" for a in self.aw) or "none"
        return f"AR[{len(self.ar)}]={ar} AW[{len(self.aw)}]={aw} W beats={self.w_beats}"


class smc_dma_traffic_shape_test_seq(SmcCsrSeq):
    """Coupled-mode DMA copies programmed over SEP_IN and checked in the SYS_OUT responder."""

    def __init__(self, name: str = "smc_dma_traffic_shape_test_seq") -> None:
        super().__init__(name)
        self.finished = False
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._sampler: _OutputSampler | None = None
        self._done = 0
        self._last_id = 0
        self._submitted = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    def _seed(self, tag: int, src: int, nbytes: int, dst: int, dst_bytes: int) -> bytes:
        data = bytes(_pattern(tag, src + i) for i in range(nbytes))
        self._responder.write(src, data)
        self._responder.write(dst, bytes([SENTINEL]) * dst_bytes)
        return data

    async def _program(
        self, tag: str, src: int, dst: int, length: int, reps: int, dst_stride: int, src_stride: int
    ) -> None:
        for name, reg, value in (
            ("DST_LO", DMA_CTRL_DST_ADDRESS_LO, dst & 0xFFFF_FFFF),
            ("DST_HI", DMA_CTRL_DST_ADDRESS_HI, dst >> 32),
            ("SRC_LO", DMA_CTRL_SRC_ADDRESS_LO, src & 0xFFFF_FFFF),
            ("SRC_HI", DMA_CTRL_SRC_ADDRESS_HI, src >> 32),
            ("LEN_LO", DMA_CTRL_LENGTH_LO, length),
            ("LEN_HI", DMA_CTRL_LENGTH_HI, 0),
            ("DSTR_LO", DMA_CTRL_DST_STRIDE_LO, dst_stride),
            ("DSTR_HI", DMA_CTRL_DST_STRIDE_HI, 0),
            ("SSTR_LO", DMA_CTRL_SRC_STRIDE_LO, src_stride),
            ("SSTR_HI", DMA_CTRL_SRC_STRIDE_HI, 0),
            ("REP_LO", DMA_CTRL_NUM_REPETITIONS_LO, reps),
            ("REP_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{tag}_{name}", reg, value)

    async def _submit(self, tag: str) -> int:
        """Read NEXT_ID, which launches the programmed descriptor."""
        nid = await self.csr_read(f"{tag}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        self._submitted += 1
        assert nid != 0, f"{tag}: NEXT_ID returned 0"
        assert nid > self._last_id, f"{tag}: NEXT_ID {nid} did not rise above {self._last_id}"
        self._last_id = nid
        return nid

    async def _await_done(self, tag: str, want: int) -> int:
        """Poll DONE until it reaches `want`; return the number of polls."""
        done = -1
        for n in range(1, DONE_POLL_BOUND + 1):
            done = await self.csr_read(f"{tag}_DONE", DMA_CTRL_DONE_0)
            if done >= want:
                assert done == want, f"{tag}: DONE {done} advanced past {want}"
                self._waits.append(
                    f"done_poll[{tag}] bound={DONE_POLL_BOUND} polls last DONE={done} "
                    f"want={want} polls={n}"
                )
                self._done = done
                return n
        status = await self.csr_read(f"{tag}_STATUS", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"{tag}: DONE reached {done}, not {want} within {DONE_POLL_BOUND} polls "
            f"(STATUS 0x{status:x})"
        )

    def _compare(self, tag: str, dst: int, want: bytes) -> None:
        got = bytes(self._responder.read(dst, len(want)))
        if got != want:
            idx = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
            raise AssertionError(
                f"{tag}: destination byte 0x{dst + idx:x} (offset {idx}) is 0x{got[idx]:02x}, "
                f"want 0x{want[idx]:02x}"
            )

    async def _copy(
        self, tag: str, src: int, dst: int, length: int, reps: int, dst_stride: int, src_stride: int
    ) -> tuple[int, int, str]:
        sampler = self._sampler
        sampler.begin()
        before = self._done
        await self._program(tag, src, dst, length, reps, dst_stride, src_stride)
        nid = await self._submit(tag)
        await self._await_done(tag, before + 1)
        return nid, before, f"{sampler.first_order()} {sampler.addrs()}"

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        dut = cocotb.top
        state = ",".join(
            f"{n}={int(getattr(dut, n).value)}"
            for n in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n")
        )
        self._waits.append(f"wait_fuse_sense_done 3 sub-waits bound={FUSE_SENSE_BOUND} {state}")
        if MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(MODEL_REGION, MODEL_BASE, MODEL_SIZE)
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        self._sampler = _OutputSampler(dut)
        cocotb.start_soon(self._sampler.run())

        config = await self.csr_read("CONFIG_RESET", DMA_CTRL_CONFIG)
        assert config == 0, f"DMA_CTRL CONFIG reads 0x{config:x}, want 0x0"
        await self.csr_write("CONFIG_ND", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        self._done = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        self._last_id = self._done
        self._mark_step("S1")

        # S2: four 8-byte rows, source contiguous, destinations 0x40 apart.
        src = self._seed(1, S2_SRC, S2_ROWS * S2_ROW_BYTES, S2_DST, S2_ROWS * S2_DST_STRIDE)
        nid, before, shape = await self._copy(
            "S2", S2_SRC, S2_DST, S2_ROW_BYTES, S2_ROWS, S2_DST_STRIDE, S2_ROW_BYTES
        )
        for r in range(S2_ROWS):
            lo = r * S2_ROW_BYTES
            self._compare(f"S2_ROW{r}", S2_DST + r * S2_DST_STRIDE, src[lo : lo + S2_ROW_BYTES])
        self._mark_step("S2")
        rows = ",".join(f"0x{S2_DST + r * S2_DST_STRIDE:x}" for r in range(S2_ROWS))
        self._log_chk(
            "CHK-DTS-COUPLED-COPY",
            f"NEXT_ID {nid} non-zero, DONE {before} -> {self._done}, {S2_ROWS} rows landed at "
            f"{rows} equal to their sources; output_axi shape (not specified, measured, printed): "
            f"{shape}",
        )

        # S3: linear 64-byte copy.
        src = self._seed(2, S3_SRC, S3_BYTES, S3_DST, S3_BYTES)
        nid, before, shape = await self._copy("S3", S3_SRC, S3_DST, S3_BYTES, 1, 0, 0)
        self._compare("S3", S3_DST, src)
        self._mark_step("S3")
        self._log_chk(
            "CHK-DTS-LINEAR",
            f"NEXT_ID {nid} rose, DONE {before} -> {self._done}, all {S3_BYTES} bytes at "
            f"0x{S3_DST:x} equal the source; bursts at output_axi (not specified, measured): "
            f"AR bursts={len(self._sampler.ar)} AW bursts={len(self._sampler.aw)} {shape}",
        )

        # S4: four queued descriptors, DONE polled only afterwards.
        srcs = [
            self._seed(
                3 + i, S4_SRC + S4_STEP * i, S4_ROW_BYTES, S4_DST + S4_STEP * i, S4_ROW_BYTES
            )
            for i in range(S4_COUNT)
        ]
        self._sampler.begin()
        before = self._done
        ids = []
        for i in range(S4_COUNT):
            tag = f"S4_{i}"
            await self._program(
                tag, S4_SRC + S4_STEP * i, S4_DST + S4_STEP * i, S4_ROW_BYTES, 1, 0, 0
            )
            ids.append(await self._submit(tag))
        await self._await_done("S4", before + S4_COUNT)
        for i in range(S4_COUNT):
            self._compare(f"S4_{i}", S4_DST + S4_STEP * i, srcs[i])
        self._mark_step("S4")
        self._log_chk(
            "CHK-DTS-QUEUE-FOUR",
            f"NEXT_ID reads {ids} non-zero and rising, DONE {before} -> {self._done} "
            f"(advance {self._done - before}), each destination equals its own source; "
            f"transfer order at output_axi (not specified, measured, printed): "
            f"{self._sampler.first_order()} {self._sampler.addrs()}",
        )

        # S5: 256 bytes starting on a 4 KiB boundary.
        src = self._seed(9, S5_SRC, S5_BYTES, S5_DST, S5_BYTES)
        nid, before, shape = await self._copy("S5", S5_SRC, S5_DST, S5_BYTES, 1, 0, 0)
        self._compare("S5", S5_DST, src)
        sampler = self._sampler
        first_ar = f"0x{sampler.ar[0]:x}" if sampler.ar else "none"
        self._mark_step("S5")
        self._log_chk(
            "CHK-DTS-PAGE-ALIGNED",
            f"NEXT_ID {nid}, DONE {before} -> {self._done}, all {S5_BYTES} bytes at "
            f"0x{S5_DST:x} equal the source starting at 0x{S5_SRC:x}; split rule "
            f"(not specified, measured, printed): first AR address {first_ar}; {shape}",
        )

        await self.csr_write("CONFIG_RESTORE", DMA_CTRL_CONFIG, 0)
        back = await self.csr_read("CONFIG_RESTORE", DMA_CTRL_CONFIG, expected=0)
        assert back == 0, f"DMA_CTRL CONFIG reads 0x{back:x} after teardown"
        self._mark_step("S6")
        self.finished = True
        self._finish()

    def _finish(self) -> None:
        assert self._submitted >= 7, f"only {self._submitted} descriptors submitted"
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        stamp_of = dict(self._stamps)
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        self._waits.append(
            f"axi_access bound={AXI_TIMEOUT_NS} ns allow_timeout=False SEP_IN accesses "
            f"{self.accesses}"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self._waits),
            " | ".join(self._waits),
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; descriptors submitted "
            "%d; SEP_IN accesses %d (floor %d)",
            "<".join(f"{t}@{s}" for t, s in zip(_TERMS, _STEPS)),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self._submitted,
            self.accesses,
            MIN_SEP_IN_ACCESSES,
        )
