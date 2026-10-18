# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI-to-DMA hardware handshake: the trigger mask, GO persistence, the stop and no CHUNK_DONE.

The Secure DMA copies the SPI receive data register (``0x10B0_0024``, WRAP) to
SEP SRAM (INCREMENT) in hardware handshake mode, one chunk of CHUNK_DATA_SIZE
per SPI trigger (``hw/sys/sep/doc/dma.adoc``, OCAH Modifications;
``secure_dma.adoc``, CONTROL.HARDWARE_HANDSHAKE_ENABLE, CONTROL.GO,
STATUS.CHUNK_DONE, HANDSHAKE_INTR_ENABLE). The SPI trigger is the registered OR
of ``TXQD < TX_WATERMARK`` and ``RXQD >= RX_WATERMARK`` and does not depend on
EVENT_ENABLE or INTR_ENABLE (``hw/sys/sep/doc/spi.adoc``, DMA Trigger). The
leaf sets TX_WATERMARK 0, so only the RX term raises the trigger.

The SPI responder is ``OcahSpiFlash`` bound on four lanes (``mode="quad_io"``,
``dq_out`` = ``spi_sd_o``, ``dq_in`` = ``spi_sd_i``); the testlist entry
passes ``+sep_spi_four_lane`` so the DUT receives ``spi_sd_i`` on every lane
(``tb/tb_top.sv``), and the leaf fails at start without it. The flash holds
unique words at address 0 for the READ (0x03) of the handshake runs, and
seeded data at three seeded addresses for the lane reads. Every RX byte packs
into RXDATA with ``ByteOrder = 1``: the first byte received lands in
RXDATA[7:0] (OpenTitan spi_host, Input and Output Byte Ordering).

Runs, each from a cold reset (``rst_ni`` pulse, bounded wait for
``dbg_sep_reset_n_o``), since CFG_REGWEN locks the DMA configuration while a
handshake run keeps GO set:

* depth check (control): an Rx segment of 4*(W+1) bytes with no reader must not
  fill the RX FIFO; the leaf then drains the words;
* reference run (control): the host reads the flash stream through RXDATA; the
  sentinel is drawn as a word that equals no reference word;
* trigger cell: RX_WATERMARK = W_eq, drawn 1..4, with the chunk C = 4*W_eq
  bytes (C/4 == W); the host receives W_eq-1 words, then one more word;
* lane reads: one read at x1, x2 and x4, in a seeded order (READ 0x03, a drawn
  one of 0x3B/0xBB, a drawn one of 0x6B/0xEB), seeded address and length;
* handshake run, mask bit 0 set: the poll for the last word of chunk n sets
  t_fill, the window length of every later run (never an expected value);
* masked run, mask bit 0 clear; the leaf drains the words after the check;
* stop run: n_stop chunks move; with GO still 1, a second Rx segment of W+1
  words after the trigger fell moves the next chunk; firmware clears GO, more
  Rx data arrives; the leaf drains the words after the check;
* interrupt-clear run, mask bit 0 set, CLEAR_INTR_SRC bit 0 = 1 and
  CLEAR_INTR_BUS bit 0 = 1, INTR_SRC_ADDR_0 a SEP SRAM word outside the
  destination, INTR_SRC_WR_VAL_0 a drawn word that differs from the word the
  leaf writes there first; the same copy as the handshake run;
* normal-mode control: a 4096-byte memory-to-memory copy in chunks of 1024.

Wire monitor sessions: ``SepSpiWireMonitor`` (with the output-enable taps)
runs in each run with SPI traffic. It starts after the ``rst_ni`` release and
stops, with the bus idle, before the next ``rst_ni`` pulse. Each session
starts with an empty flash record and an empty monitor history, so the record
index and the monitor frame index stay aligned, and has its own
``SepSpiScoreboard``. The normal-mode run has no SPI traffic and no session.

Checkers:
  CHK-HS-MASKED   mask bit 0 clear: the destination keeps its sentinel while the
                  trigger probe is high, and CONTROL.GO reads 1 at the end of
                  the window.
  CHK-HS-GO       In handshake operation the engine does not clear GO between
                  chunks; firmware clears it to stop (secure_dma.adoc,
                  CONTROL.GO). GO stays 1 between chunks below
                  TOTAL_DATA_SIZE (stop run, before the firmware clear). GO
                  once the destination holds TOTAL_DATA_SIZE bytes, GO after a
                  further wait as long as t_fill, and STATUS.DONE at the total
                  are logged only (OBS-HS-GO-TOTAL, OBS-HS-DONE): the register
                  text does not state a GO clear at the total.
  CHK-HS-STOP     re-trigger leg, GO=1: after the trigger fell, a second Rx
                  segment raises it again and the engine moves at least one more
                  chunk; the moved chunks equal the RX stream (the first segment,
                  then the second, each from flash address 0) and the words after
                  them keep their sentinel. "In response to the assertion of an
                  enabled bit of the `lsio_trigger_i` input, the DMA controller
                  will proceed to transfer an entire chunk of data from the
                  source to the destination." and "Whilst the `lsio_trigger_i`
                  input is not asserted, the DMA controller will remain in its
                  Idle state awaiting instruction to proceed with the next chunk
                  of the transfer." (``vendor/lowRISC/opentitan/upstream/hw/ip/
                  dma/doc/theory_of_operation.md:461,463``). Controls: the
                  trigger probe reads low before the second segment and rises in
                  it. Stop leg: after the GO clear the words after the moved
                  chunks keep their sentinel while the trigger probe is high,
                  and the moved chunks keep the words read before the clear.
  CHK-HS-NOCHUNK  STATUS.CHUNK_DONE reads 0 at every poll of the handshake run,
                  and with INTR_ENABLE.DMA_CHUNK_DONE=1 PIC source 10 (bit 9 of
                  ``sep_internal_interrupts_probe_o``) stays low at every clock
                  from before GO to the end of the t_fill wait, so a CHUNK_DONE
                  pulse between two polls also fails.
  CHK-HS-DATA     handshake run: the n chunks the DMA moved, read from the
                  destination over the frontdoor, equal the flash bytes at
                  address 0 packed with ``ByteOrder = 1``, word for word and in
                  order. Control: the reference words are distinct
                  (``ref_distinct``), so a chunk in the wrong place fails.
  CHK-HS-TRIG-EQ  trigger cell: with RXQD = W_eq-1 the trigger probe is low and
                  did not rise; the next word makes RXQD = W_eq, and the probe
                  rises once, after the last sample edge of that word, and reads
                  high (``RXQD >= RX_WATERMARK``, spi.adoc DMA Trigger).
                  Controls: STATUS.RXQD reads W_eq-1 and then W_eq.
  CHK-HS-LANE-RX  lane reads: the RXDATA bytes of each read equal the seeded
                  flash bytes at its address (``width=``, ``bytes=``).
  CHK-SPI-SESSION-FRAMES  per session: the monitor saw at least one frame, and
                  every frame carries one scoreboard expectation whose bytes
                  cover the frame's RX segment (the handshake frame: the moved
                  chunks).
  CHK-SPI-SB-RX   per session (``SepSpiScoreboard.expect_rx``): the bytes the DUT
                  delivered == the flash ``data_out`` prefix == the monitor wire
                  decode at the command's lane width.
  CHK-SPI-WIRE    per session: no wire or output-enable rule violation
                  (``SepSpiWireMonitor``), with the flash ledger and frame
                  shape.

  CHK-HS-CLR      interrupt-clear run: at least one AW on the DMA master tap
                  (``dma_axi_req_probe_o``, ``env/sep_dma_tap.py``) carries the
                  address INTR_SRC_ADDR_0, and that SRAM word reads
                  INTR_SRC_WR_VAL_0 over the frontdoor after the run. The tap
                  carries no write data, so the data comes from that readback.
                  Contract: "configure `CLEAR_INTR_SRC`, `CLEAR_INTR_BUS`,
                  `INTR_SRC_ADDR` and `INTR_SRC_WR_VAL` for the connected host
                  port (`CLEAR_INTR_BUS` bit 0 = 1)"
                  (``doc/programmer/src/sep-programming.adoc:774-776``); "DMA
                  issues writes with address from INTR_SRC_ADDR and write value
                  from INTR_SRC_WR_VAL corresponding to each bit set in this
                  register" (``vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/
                  dma.hjson:756-757``, CLEAR_INTR_SRC). Control: the handshake run
                  (CLEAR_INTR_SRC = 0 from reset) moves its chunks with no AW to
                  that address. The clock of each clear write, the count of clear
                  writes and the WSTRB of the paired W beat are logged
                  (``OBS-HS-CLR``): the text says only "when ... lsio_trigger
                  becomes set".

Controls: RX depth above W+1; mask=1 run fills the destination; trigger high in
each "never" window; 1 <= n_moved, and the chunks moved before the GO clear are
fewer than chunks_total; the normal-mode copy reads GO=0 at DONE, shows
CHUNK_DONE in a poll, and shows a rise of PIC source 10 (bit 9 of
``sep_internal_interrupts_probe_o``), so a dead or mis-bound bit-9 tap fails
the control of the line leg of CHK-HS-NOCHUNK. A missing control logs
CTRL-MISSING and fails the leaf.

Probes: ``spi_lsio_trigger_probe_o``, ``dma_busy_probe_o``, ``spi_tx_qd_probe_o``
(logged), ``dma_axi_req_probe_o`` (handshake and interrupt-clear runs), ``dbg_sep_reset_n_o``, ``sep_internal_interrupts_probe_o`` bit 9, the
SPI pad ports and lane taps, and the register frontdoor over ``s_axi``.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense, both simulators,
``+sep_spi_four_lane``. Every draw comes from ``SepSeededRng`` and the run seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_dma_tap import SepDmaTap
from env.sep_efuse_image import SepEfuseImage
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_lane_responder import spi_lane_fcov
from env.sep_spi_pad_sampler import SepSpiPadSampler, SpiPadTimeout
from env.sep_spi_scoreboard import SepSpiScoreboard
from env.sep_spi_wire_monitor import SepSpiWireMonitor
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_dma_ops import (
    CONTROL as DMA_CONTROL,
)
from seq_lib.sep_dma_ops import (
    HANDSHAKE_INTR_ENABLE,
    INTR_ENABLE,
    OP_COPY,
    SECURE_DMA,
    DmaStatus,
    SepDmaOps,
    SepMemWords,
    asid_word,
)
from seq_lib.sep_spi_host_csr_seq import (
    CONTROL as SPI_CONTROL,
)
from seq_lib.sep_spi_host_csr_seq import (
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_SPIEN,
    EVENT_ENABLE,
    RXDATA,
    SPI_CONTROLLER,
)
from seq_lib.sep_spi_host_csr_seq import (
    INTR_ENABLE as SPI_INTR_ENABLE,
)
from seq_lib.sep_spi_host_ops import (
    DIR_DUMMY,
    DIR_RX,
    DIR_TX,
    SPEED_DUAL,
    SPEED_QUAD,
    SPEED_STD,
    SepSpiHostOps,
    command_word,
    configopts_word,
)

TEST = "sep_spi_dma_handshake_rand_test"

M32 = 0xFFFF_FFFF
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
# Handshake range: the SRAM base to the end of the SPI window (memory_map.adoc).
HS_RANGE_BASE = SRAM_BASE
HS_RANGE_LIMIT = 0x10BF_FFFF
# Normal-mode range: the SEP SRAM.
NM_RANGE_LIMIT = SRAM_BASE + SRAM_SIZE - 1
ASID = asid_word(7, 7)

# Destination of the handshake runs and the normal-mode footprints (SRAM).
HS_DST = SRAM_BASE + 0x1000
# INTR_SRC_ADDR_0 of the interrupt-clear run: an SRAM word below HS_DST, inside
# the handshake range and outside every destination.
CLR_ADDR = SRAM_BASE + 0x800
CLEAR_INTR_SRC = SECURE_DMA.addr("CLEAR_INTR_SRC")
CLEAR_INTR_BUS = SECURE_DMA.addr("CLEAR_INTR_BUS")
INTR_SRC_ADDR_0 = sym("SECURE_DMA_INTR_SRC_ADDR_0_0__REG_ADDR")
INTR_SRC_WR_VAL_0 = sym("SECURE_DMA_INTR_SRC_WR_VAL_0_0__REG_ADDR")
NM_SRC = SRAM_BASE + 0x8000
NM_DST = SRAM_BASE + 0x10000
NM_TOTAL = 4096
NM_CHUNK = 1024

CTRL_RX_WM_LSB = SPI_CONTROLLER.field_lsb("CONTROL", "rx_watermark")
GO_MASK = SECURE_DMA.field_mask("CONTROL", "go")
INTR_EN_CHUNK = SECURE_DMA.field_mask("INTR_ENABLE", "dma_chunk_done")
HS_MASK_FIELD = SECURE_DMA.field_mask("HANDSHAKE_INTR_ENABLE", "mask")

# OcahSpiFlash READ: opcode 0x03 then a 24-bit address, sent low byte of the
# TXDATA word first. Address 0.
FLASH_READ = 0x03
FLASH_ADDR = 0
READ_CMD_WORD = FLASH_READ
READ_CMD_BYTES = 4
FLASH_WORDS = 64

# Flash read commands per lane width, and their shape: the address lane count
# and the dummy clocks between the address and the data (the 0x3B, 0x6B, 0xBB
# and 0xEB formats of the four-lane flash model; READ has no dummy clock).
LANE_OPCODES = {1: (0x03,), 2: (0x3B, 0xBB), 4: (0x6B, 0xEB)}
LANE_SHAPE = {0x03: (1, 0), 0x3B: (1, 8), 0x6B: (1, 8), 0xBB: (2, 4), 0xEB: (4, 6)}
SPEED = {1: SPEED_STD, 2: SPEED_DUAL, 4: SPEED_QUAD}
FOUR_LANE_PLUSARG = "sep_spi_four_lane"

# The committed default OTP image: the harness disable vectors, never randomized.
EFUSE_IMAGE = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "sep_efuse_default.hex"
)

# Bounds.
SENSE_CYCLES = 20_000
STABLE_READS = 8
TRIG_RISE_CLKS = 200
CS_HIGH_CLKS = 2_000


def unique_words(rng: SepSeededRng, k: int, *, exclude: set[int] | None = None) -> list[int]:
    """``k`` distinct 32-bit words drawn in order from ``rng``, none in ``exclude``."""
    seen = set(exclude or ())
    out: list[int] = []
    while len(out) < k:
        w = rng.getrandbits(32)
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def words_bytes(words: list[int]) -> bytes:
    """RXDATA words as the received byte stream (``ByteOrder = 1``)."""
    return b"".join((w & M32).to_bytes(4, "little") for w in words)


class _Cfg:
    """Every draw of the leaf, from the run seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = SepSeededRng(seed)
        r = self.rng
        self.chunk = 4 * r.randrange(1, 5)  # C: 4..16, multiple of 4
        self.n = r.randrange(2, 9)  # chunk count 2..8
        self.mask_hi = r.getrandbits(10)  # HANDSHAKE_INTR_ENABLE.MASK bits 10:1
        self.n_stop = r.randrange(1, self.n)  # 1..n-1
        self.clkdiv = r.randrange(0, 8)
        self.wm = r.randrange(self.chunk // 4, 8)  # W: C/4..7
        self.flash_words = unique_words(r, FLASH_WORDS)
        # Normal-mode control data: unique source words and a sentinel outside them.
        self.nm_src = unique_words(r, NM_TOTAL // 4)
        self.nm_sentinel = unique_words(r, 1, exclude=set(self.nm_src))[0]
        # Trigger cell: RX_WATERMARK W_eq and the chunk C_eq = 4 * W_eq bytes (C/4 == W).
        self.eq_wm = r.randrange(1, 5)
        # Lane reads: one per width, in a seeded order, each in its own 4 KiB
        # sector (sector 0 holds the handshake words).
        self.lane_order = [1, 2, 4]
        r.shuffle(self.lane_order)
        sectors = r.sample(range(1, 4096), 3)
        self.lane_reads: dict[int, tuple[int, int, bytes]] = {}
        for lanes, sector in zip((1, 2, 4), sectors):
            opcode = r.choice(LANE_OPCODES[lanes])
            addr = (sector << 12) | r.randrange(0, 0x400)
            data = bytearray(r.getrandbits(8) for _ in range(4 * r.randrange(2, 9)))
            if data[1] == data[0]:
                data[1] ^= 0xFF  # at least two distinct bytes by construction
            self.lane_reads[lanes] = (opcode, addr, bytes(data))

    @property
    def eq_chunk(self) -> int:
        return 4 * self.eq_wm

    @property
    def cw(self) -> int:
        return self.chunk // 4

    @property
    def mask_on(self) -> int:
        return 0x001 | (self.mask_hi << 1)

    @property
    def mask_off(self) -> int:
        return self.mask_hi << 1

    @property
    def extra_bytes(self) -> int:
        return 4 * (self.wm + 1)

    @property
    def chunks_total_stop(self) -> int:
        # Room for the first segment, the re-trigger segment and one unmoved chunk.
        return self.n_stop + 2 * -(-self.extra_bytes // self.chunk) + 1

    def flash_bytes(self) -> bytes:
        return b"".join(w.to_bytes(4, "little") for w in self.flash_words)

    def seg_clks(self, rx_bytes: int) -> int:
        """Clock bound of one Tx+Rx frame: 8 bits per byte, 2*(CLKDIV+1) clocks per bit."""
        return 4 * (READ_CMD_BYTES + rx_bytes) * 8 * 2 * (self.clkdiv + 1) + 50_000


@dataclass
class _RxExpect:
    """One frame's RX expectation of a monitor session."""

    lanes: int
    opcode: int
    got: int  # bytes registered with the scoreboard
    want: int  # bytes of the frame's RX segment the expectation covers
    label: str


@dataclass
class _Session:
    """One wire monitor session: from an ``rst_ni`` release to the next pulse."""

    tag: str
    tally0: int
    sb: SepSpiScoreboard
    rx: list[_RxExpect] = field(default_factory=list)


@pyuvm.test()
class sep_spi_dma_handshake_rand_test(sep_base_test):
    """SPI-to-DMA hardware handshake: mask, GO, stop, chunk, data and trigger rules."""

    required_evidence = (
        "CHK-HS-MASKED",
        "CHK-HS-GO",
        "CHK-HS-STOP",
        "CHK-HS-NOCHUNK",
        "CHK-HS-DATA",
        "CHK-HS-TRIG-EQ",
        "CHK-HS-LANE-RX",
        "CHK-HS-CLR",
        "CHK-SPI-SESSION-FRAMES",
        "CHK-SPI-SB-RX",
        "CHK-SPI-WIRE",
    )

    # The open wire monitor session; None between sessions.
    sess: _Session | None = None

    # ---- logging helpers ---------------------------------------------------
    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.cfg_.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, chk: str, line: str) -> None:
        msg = f"CTRL-MISSING {chk} seed={self.cfg_.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.cfg_.seed, line)
        self.n_checks += 1

    # ---- wire monitor sessions ---------------------------------------------
    async def _session_begin(self, tag: str) -> None:
        """Clear the flash record and the monitor history together, then start the monitor."""
        self.flash.clear_transactions()
        self.wire.monitor.clear_history()
        sb = SepSpiScoreboard(self.wire, self.flash, self.logger, seed=self.cfg_.seed)
        self.sess = _Session(tag, sum(self.wire.tally.values()), sb)
        # MUTATION hook (step 14, item 7): skip the next line for one tag; the
        # zero-frame rule of CHK-SPI-SESSION-FRAMES fails.
        await self.wire.monitor.start()

    def _expect_rx(self, opcode: int, lanes: int, data: bytes, *, want: int, label: str) -> None:
        """Register the bytes the DUT delivered for one frame of the open session."""
        sess = self.sess
        if sess is None:
            raise AssertionError(f"{label}: RX expectation outside a monitor session")
        full = f"{sess.tag}:{label} width=x{lanes}"
        sess.sb.expect_rx(opcode, data, source="dut", label=full)
        sess.rx.append(_RxExpect(lanes, opcode, len(data), want, full))

    async def _session_end(self) -> None:
        """Bus idle, monitor stop, then the session checks; returns with no session open."""
        cfg = self.cfg_
        sess = self.sess
        assert sess is not None
        await self.spi.poll_status(
            lambda s: s.active == 0 and s.cmdqd == 0, 2_000, f"session {sess.tag}: bus idle"
        )
        for _ in range(CS_HIGH_CLKS):
            if not self.pads.cs_low():
                break
            await ClockCycles(cocotb.top.clk_i, 1)
        else:
            self._fail("CHK-SPI-SESSION-FRAMES", f"session={sess.tag} chip select still low")
        await ClockCycles(cocotb.top.clk_i, 4)
        await self.wire.monitor.stop()
        frames = sum(self.wire.tally.values()) - sess.tally0
        short = [e.label for e in sess.rx if e.got != e.want]
        line = (
            f"session={sess.tag} frames={frames} expectations={len(sess.rx)} "
            f"widths={','.join(f'x{e.lanes}' for e in sess.rx) or '-'} "
            f"bytes={sum(e.got for e in sess.rx)} short={','.join(short) or '-'}"
        )
        if frames == 0 or frames != len(sess.rx) or short:
            self._fail("CHK-SPI-SESSION-FRAMES", line)
        await self.wire.finish(self.logger, seed=cfg.seed, flash=self.flash)
        sess.sb.finish()
        self._pass("CHK-SPI-SESSION-FRAMES", line)
        for e in sess.rx:
            await spi_lane_fcov(TEST, "data", lanes=e.lanes, rx=True)
        self.sess = None

    # ---- reset and SPI -----------------------------------------------------
    async def _cold_reset(self, tag: str, *, session: bool = True) -> None:
        """Non-graded cold reset: session end, window closed, rst_ni pulse, SEP reset release."""
        if self.sess is not None:
            await self._session_end()
        close_graded_window(self.logger)
        await self.flash.stop()
        rel = await self.pulse_rst_ni(max_sense_cycles=SENSE_CYCLES)
        self.flash.init_signals()
        await self.flash.start()
        self.logger.info(
            "RESET LOG run=%s release_clks=%d sep_reset_n_at_hold_end=%d",
            tag,
            rel["release_clks"],
            rel["sep_reset_n_at_hold_end"],
        )
        if session:
            await self._session_begin(tag)

    async def _spi_config(self, wm: int) -> None:
        cfg = self.cfg_
        spi = self.spi
        await spi.wr(SPI_CONTROL, CTRL_SPIEN | CTRL_OUTPUT_EN | (wm << CTRL_RX_WM_LSB))
        await spi.wr(EVENT_ENABLE, 0)
        await spi.wr(SPI_INTR_ENABLE, 0)
        await spi.wr(CSID, 0)
        await spi.write_configopts(configopts_word(clkdiv=cfg.clkdiv))

    async def _spi_sequence(self, rx_bytes: int, *, wm: int | None = None):
        """The READ (0x03, address 0) of every run; returns the pad mark taken before it."""
        spi = self.spi
        await self._spi_config(self.cfg_.wm if wm is None else wm)
        await spi.push_tx(READ_CMD_WORD)
        mark = self.pads.mark()
        await spi.issue_command(
            command_word(READ_CMD_BYTES - 1, speed=SPEED_STD, direction=DIR_TX, csaat=1)
        )
        await spi.issue_command(
            command_word(rx_bytes - 1, speed=SPEED_STD, direction=DIR_RX, csaat=0)
        )
        return mark

    async def _drain_words(self, want: int, mark, what: str) -> list[int]:
        """Read RXDATA until the frame after ``mark`` ended and the RX FIFO is empty."""
        words: list[int] = []
        bound = self.cfg_.seg_clks(4 * want)
        t0 = self.tw.clk
        while True:
            if self.tw.clk - t0 > bound:
                self._fail(
                    "CHK-SPI-SESSION-FRAMES",
                    f"{what}: RX drain did not end in {bound} clocks "
                    f"({len(words)} of {want} words)",
                )
            st = await self.spi.read_status()
            if not st.rxempty:
                words.append(await self.spi.rd(RXDATA) & M32)
                continue
            if self.pads.windows_since(mark) and st.active == 0 and st.cmdqd == 0:
                return words

    # ---- DMA ---------------------------------------------------------------
    async def _hs_start(self, *, mask: int, total: int, dst_words: int, rx_bytes: int):
        """Step 5: program the handshake copy, GO, then the SPI sequence.

        Returns the clock of the GO write and the pad mark of the SPI frame.
        """
        cfg = self.cfg_
        dma = self.dma
        await dma.program_range(HS_RANGE_BASE, HS_RANGE_LIMIT)
        await dma.wr(SECURE_DMA.addr("ADDR_SPACE_ID"), ASID)
        await self.mem.fill(HS_DST, [self.sentinel] * dst_words)
        await dma.program_transfer(
            src=RXDATA,
            dst=HS_DST,
            total=total,
            chunk=cfg.chunk,
            width_enc=2,
            src_inc=False,
            src_wrap=True,
            dst_inc=True,
            dst_wrap=False,
        )
        await dma.wr(HANDSHAKE_INTR_ENABLE, mask & HS_MASK_FIELD)
        t_go = self.tw.clk
        await dma.go(opcode=OP_COPY, hs=1, initial=1)
        mark = await self._spi_sequence(rx_bytes)
        return t_go, mark

    def _probe_log(self, tag: str) -> None:
        self.logger.info(
            "PROBE LOG run=%s dma_busy_probe_o=%s spi_tx_qd_probe_o=%s",
            tag,
            self.busy.level(),
            self.rd(cocotb.top.spi_tx_qd_probe_o, allow_unknown=True),
        )

    def _go_cmp(self, raw: int):
        return field_compare(raw, GO_MASK, GO_MASK)

    async def _wait_clocks(self, until: int) -> None:
        if until > self.tw.clk:
            await ClockCycles(cocotb.top.clk_i, until - self.tw.clk)

    async def _stable_image(self, n_words: int, t_fill: int, what: str) -> list[int]:
        """Destination words once two reads ``t_fill`` clocks apart are equal."""
        img1 = await self.mem.read(HS_DST, n_words)
        for _ in range(STABLE_READS):
            await self._wait_clocks(self.tw.clk + t_fill)
            img2 = await self.mem.read(HS_DST, n_words)
            if img2 == img1:
                return img1
            img1 = img2
        self._ctrl_missing(
            "CHK-HS-STOP", f"{what}: destination not stable after {STABLE_READS} reads"
        )
        raise AssertionError  # unreachable: _ctrl_missing raises

    def _filled(self, img: list[int], n_chunks: int) -> list[bool]:
        """Per chunk of ``img``: True when no word of the chunk holds the sentinel."""
        cw = self.cfg_.cw
        return [
            all(w != self.sentinel for w in img[c * cw : (c + 1) * cw]) for c in range(n_chunks)
        ]

    # ---- runs --------------------------------------------------------------
    async def _clear_run(
        self, nw: int, rx_bytes: int, t_fill: int, hs_clr_aw: int, hs_aw: int
    ) -> None:
        """CHK-HS-CLR: the source 0 clear write reaches INTR_SRC_ADDR_0 on the DMA master.

        The handshake run (CLEAR_INTR_SRC = 0) is the control: ``hs_aw`` AWs and
        ``hs_clr_aw`` of them at CLR_ADDR. The wait after the last word lands is
        ``t_fill``, the clocks the handshake run took from GO to its last word.
        """
        cfg = self.cfg_
        dma = self.dma
        await self._cold_reset("clear")
        open_graded_window(TEST, self.logger)
        # Appended draw: the clear value, never the word written there first.
        clr_val = unique_words(cfg.rng, 1, exclude={self.sentinel})[0]
        self.logger.info(
            "DRAW seed=%d clear_addr=0x%08x clear_wr_val=0x%08x clear_pre=0x%08x",
            cfg.seed,
            CLR_ADDR,
            clr_val,
            self.sentinel,
        )
        await self.mem.fill(CLR_ADDR, [self.sentinel])
        await dma.wr(CLEAR_INTR_SRC, 0x1)
        await dma.wr(CLEAR_INTR_BUS, 0x1)
        await dma.wr(INTR_SRC_ADDR_0, CLR_ADDR)
        await dma.wr(INTR_SRC_WR_VAL_0, clr_val)
        self.dtap.start()
        m_tap = self.dtap.mark()
        t_go, _ = await self._hs_start(
            mask=cfg.mask_on, total=cfg.n * cfg.chunk, dst_words=nw, rx_bytes=rx_bytes
        )
        bound = cfg.seg_clks(rx_bytes)
        last_addr = HS_DST + 4 * (nw - 1)
        polls = 0
        while (await self.mem.read(last_addr, 1))[0] == self.sentinel:
            polls += 1
            if self.tw.clk - t_go > bound:
                self._fail(
                    "CHK-HS-CLR",
                    f"last word of chunk {cfg.n} still holds the sentinel {bound} clocks "
                    f"after GO (polls={polls})",
                )
        t_last = self.tw.clk
        await self._wait_clocks(t_last + t_fill)
        await dma.wr(DMA_CONTROL, dma.last_control & ~GO_MASK)
        ev = self.dtap.since(m_tap)
        await self.dtap.stop()
        clr_rb = (await self.mem.read(CLR_ADDR, 1))[0]
        dest = await self.mem.read(HS_DST, nw)
        clr_idx = [i for i, b in enumerate(ev.aw) if b.addr == CLR_ADDR]
        self.logger.info(
            "OBS-HS-CLR LOG seed=%d clear_aw=%d aw_total=%d clear_aw_clks=%s "
            "clear_aw_size=%s clear_w_strb=%s go_tap_clk=%d last_word_clks_after_go=%d",
            cfg.seed,
            len(clr_idx),
            len(ev.aw),
            ",".join(str(ev.aw[i].clk - m_tap.clk) for i in clr_idx) or "-",
            ",".join(str(ev.aw[i].size) for i in clr_idx) or "-",
            ",".join(f"0x{ev.w[i].strb:x}" if i < len(ev.w) else "-" for i in clr_idx) or "-",
            m_tap.clk,
            t_last - t_go,
        )
        self._probe_log("clear")
        close_graded_window(self.logger)
        line = (
            f"clear_addr=0x{CLR_ADDR:08x} clear_aw={len(clr_idx)} "
            f"readback=0x{clr_rb:08x} expect=0x{clr_val:08x} pre=0x{self.sentinel:08x} "
            f"clear_src=0x1 clear_bus=0x1 control_hs_aw={hs_aw} "
            f"control_hs_clear_aw={hs_clr_aw} window_clks={t_fill}"
        )
        if hs_aw < 1 or hs_clr_aw != 0:
            self._ctrl_missing("CHK-HS-CLR", line)
        if not clr_idx or clr_rb != clr_val:
            self._fail("CHK-HS-CLR", line)
        self._pass("CHK-HS-CLR", line)
        self._expect_rx(FLASH_READ, 1, words_bytes(dest), want=4 * nw, label="clear")

    async def _depth_check(self) -> None:
        cfg = self.cfg_
        await self._cold_reset("depth")
        rx_bytes = cfg.extra_bytes
        mark = await self._spi_sequence(rx_bytes)
        try:
            await self.pads.wait_windows(1, mark, cfg.seg_clks(rx_bytes))
        except SpiPadTimeout as exc:
            self._ctrl_missing("CHK-HS-DEPTH", f"segment of {rx_bytes} bytes did not end: {exc}")
        st = await self.spi.poll_status(lambda s: s.active == 0, 2_000, "depth: ACTIVE=0")
        self.logger.info(
            "CTL-HS-DEPTH LOG seed=%d rx_bytes=%d rxqd=%d rxfull=%d",
            cfg.seed,
            rx_bytes,
            st.rxqd,
            st.rxfull,
        )
        if st.rxfull:
            self._ctrl_missing(
                "CHK-HS-DEPTH", f"RXFULL=1 after {rx_bytes // 4} words; RX depth is not above W+1"
            )
        words = await self.spi.drain_rx()
        self._expect_rx(FLASH_READ, 1, words_bytes(words), want=rx_bytes, label="depth")

    async def _reference_run(self) -> list[int]:
        cfg = self.cfg_
        await self._cold_reset("reference")
        rx_bytes = cfg.n * cfg.chunk + cfg.extra_bytes
        n_words = rx_bytes // 4
        mark = await self._spi_sequence(rx_bytes)
        words: list[int] = []
        bound = cfg.seg_clks(rx_bytes)
        t0 = self.tw.clk
        while True:
            if self.tw.clk - t0 > bound:
                self._ctrl_missing(
                    "CHK-HS-DATA",
                    f"reference read did not end in {bound} clocks ({len(words)} words)",
                )
            st = await self.spi.read_status()
            if not st.rxempty:
                words.append(await self.spi.rd(RXDATA) & M32)
                continue
            if self.pads.windows_since(mark) and st.active == 0 and st.cmdqd == 0:
                break
        if len(words) != n_words:
            self._ctrl_missing(
                "CHK-HS-DATA", f"reference stream has {len(words)} words, segment holds {n_words}"
            )
        self._expect_rx(FLASH_READ, 1, words_bytes(words), want=rx_bytes, label="reference")
        return words

    async def _trigger_cell(self) -> None:
        """CHK-HS-TRIG-EQ: the trigger rises at RXQD == RX_WATERMARK (C/4 == W)."""
        cfg = self.cfg_
        w = cfg.eq_wm
        await self._cold_reset("trigger")
        open_graded_window(TEST, self.logger)
        # Spec rule: trigger = RXQD >= RX_WATERMARK (TX_WATERMARK 0 keeps the TX term low).
        # MUTATION hook (step 14, item 5): set ``rule_wm = w + 1``; the level
        # expected at RXQD == W turns 0 and CHK-HS-TRIG-EQ fails.
        rule_wm = w
        exp_below = int(w - 1 >= rule_wm)
        exp_at = int(w >= rule_wm)
        await self._spi_config(w)
        m_below = self.trig.mark()
        below_bytes = 4 * (w - 1)
        if below_bytes:
            mark_a = await self._spi_sequence(below_bytes, wm=w)
            await self.spi.wait_segment_done(
                self.pads, mark_a, bound_clks=cfg.seg_clks(below_bytes)
            )
        await ClockCycles(cocotb.top.clk_i, 4)
        st_below = await self.spi.read_status()
        lvl_below = self.tw.level()
        rises_below = self.trig.rises_since(m_below)
        m_at = self.trig.mark()
        mark_b = await self._spi_sequence(4, wm=w)
        wins = await self.spi.wait_segment_done(self.pads, mark_b, bound_clks=cfg.seg_clks(4))
        try:
            rise = await self.trig.wait_rise(m_at, TRIG_RISE_CLKS)
        except BitWatchTimeout:
            rise = None
        st_at = await self.spi.read_status()
        lvl_at = self.tw.level()
        rises_at = self.trig.rises_since(m_at)
        # Both watchers count the same clk_i edges, so the offset converts a
        # trigger clock to a pad clock.
        offset = self.tw.clk - self.pads.now()
        last_edge = wins[0].leading_edge_clks[-1] if wins[0].leading_edge_clks else None
        rise_pad = None if rise is None else rise - offset
        after_last_bit = int(
            rise_pad is not None and last_edge is not None and rise_pad > last_edge
        )
        line = (
            f"width=x1 bytes={4 * w} wm={w} chunk={cfg.eq_chunk} "
            f"rxqd_below={st_below.rxqd} trig_below={lvl_below} rises_below={rises_below} "
            f"rxqd_at={st_at.rxqd} trig_at={lvl_at} rises_at={rises_at} "
            f"rise_pad_clk={rise_pad} last_sample_edge_clk={last_edge} "
            f"after_last_bit={after_last_bit} expect_below={exp_below} expect_at={exp_at}"
        )
        if st_below.rxqd != w - 1 or st_at.rxqd != w:
            self._ctrl_missing("CHK-HS-TRIG-EQ", line)
        ok_below = lvl_below == exp_below and rises_below == exp_below
        ok_at = lvl_at == exp_at and rises_at == exp_at and bool(after_last_bit) == bool(exp_at)
        if not (ok_below and ok_at):
            self._fail("CHK-HS-TRIG-EQ", line)
        self._pass("CHK-HS-TRIG-EQ", line)
        await spi_lane_fcov(TEST, "trigger")
        close_graded_window(self.logger)
        words = await self.spi.drain_rx()
        if below_bytes:
            self._expect_rx(
                FLASH_READ,
                1,
                words_bytes(words[: w - 1]),
                want=below_bytes,
                label="trigger_below",
            )
        self._expect_rx(FLASH_READ, 1, words_bytes(words[w - 1 :]), want=4, label="trigger_at")

    async def _lane_read(self, lanes: int, opcode: int, addr: int, nbytes: int) -> bytes:
        """One flash read at ``lanes`` lanes; returns the RXDATA bytes (``ByteOrder = 1``)."""
        spi = self.spi
        addr_lanes, dummy = LANE_SHAPE[opcode]
        a = addr.to_bytes(3, "big")
        if addr_lanes == 1:
            tx_segs = [(1, bytes([opcode]) + a)]
        else:
            tx_segs = [(1, bytes([opcode])), (addr_lanes, a)]
        # Each TX segment takes its own TXDATA words: the host drops the unused
        # bytes of a word at the end of a segment.
        for _, seg in tx_segs:
            padded = seg + b"\0" * (-len(seg) % 4)
            for j in range(0, len(padded), 4):
                await spi.push_tx(int.from_bytes(padded[j : j + 4], "little"))
        mark = self.pads.mark()
        for seg_lanes, seg in tx_segs:
            await spi.issue_command(
                command_word(len(seg) - 1, speed=SPEED[seg_lanes], direction=DIR_TX, csaat=1)
            )
        if dummy:
            await spi.issue_command(
                command_word(dummy - 1, speed=SPEED[lanes], direction=DIR_DUMMY, csaat=1)
            )
        await spi.issue_command(
            command_word(nbytes - 1, speed=SPEED[lanes], direction=DIR_RX, csaat=0)
        )
        words = await self._drain_words(nbytes // 4, mark, f"lane read x{lanes}")
        return words_bytes(words)

    async def _lane_leg(self) -> None:
        """CHK-HS-LANE-RX: one read at x1, x2 and x4, in the seeded order."""
        cfg = self.cfg_
        await self._cold_reset("lanes")
        open_graded_window(TEST, self.logger)
        # The rst_ni pulse clears the SPI host configuration (SPIEN, CONFIGOPTS).
        await self._spi_config(cfg.wm)
        for lanes in cfg.lane_order:
            opcode, addr, data = cfg.lane_reads[lanes]
            delivered = await self._lane_read(lanes, opcode, addr, len(data))
            line = (
                f"width=x{lanes} opcode=0x{opcode:02x} addr=0x{addr:06x} bytes={len(data)} "
                f"expected={data.hex()} delivered={delivered.hex()}"
            )
            if delivered != data:
                self._fail("CHK-HS-LANE-RX", line)
            self._pass("CHK-HS-LANE-RX", line)
            # MUTATION hook (step 14, item 11d): for lanes == 2 register
            # ``delivered`` with one byte flipped (XOR 0xFF); the byte count
            # stays the same, so CHK-SPI-SB-RX fails on the x2 byte compare.
            self._expect_rx(opcode, lanes, delivered, want=len(data), label=f"lane_x{lanes}")
        close_graded_window(self.logger)

    async def run_scenario(self) -> None:
        self.cfg_ = cfg = _Cfg(self.random_seed())
        self.n_checks = 0
        self.sess = None
        dut = cocotb.top
        if FOUR_LANE_PLUSARG not in cocotb.plusargs:
            raise AssertionError(
                f"{TEST} needs +{FOUR_LANE_PLUSARG}: the DUT must receive spi_sd_i on every lane"
            )
        self.logger.info(
            "PLAN seed=%d runs=depth,reference,trigger,lanes,handshake,masked,stop,clear,"
            "normal graded=trigger,lanes,handshake,masked,stop,clear checks=CHK-HS-MASKED,"
            "CHK-HS-GO,CHK-HS-STOP,CHK-HS-NOCHUNK,CHK-HS-DATA,CHK-HS-TRIG-EQ,CHK-HS-LANE-RX,"
            "CHK-HS-CLR,CHK-SPI-SESSION-FRAMES,CHK-SPI-SB-RX,CHK-SPI-WIRE",
            cfg.seed,
        )
        self.logger.info(
            "DRAW seed=%d chunk=%d n=%d mask_hi=0x%03x n_stop=%d clkdiv=%d wm=%d "
            "chunks_total_stop=%d eq_wm=%d eq_chunk=%d",
            cfg.seed,
            cfg.chunk,
            cfg.n,
            cfg.mask_hi,
            cfg.n_stop,
            cfg.clkdiv,
            cfg.wm,
            cfg.chunks_total_stop,
            cfg.eq_wm,
            cfg.eq_chunk,
        )
        self.logger.info(
            "DRAW seed=%d flash_addr=0x%06x flash_words=%s",
            cfg.seed,
            FLASH_ADDR,
            ",".join(f"{w:08x}" for w in cfg.flash_words),
        )
        self.logger.info(
            "DRAW seed=%d lane_order=%s lane_reads=%s",
            cfg.seed,
            ",".join(f"x{lanes}" for lanes in cfg.lane_order),
            " ".join(
                f"x{lanes}:op=0x{op:02x},addr=0x{addr:06x},bytes={len(data)}"
                for lanes, (op, addr, data) in sorted(cfg.lane_reads.items())
            ),
        )
        self.logger.info(
            "DRAW seed=%d nm_sentinel=0x%08x nm_src_words=%d",
            cfg.seed,
            cfg.nm_sentinel,
            len(cfg.nm_src),
        )

        self.write_efuse_image(SepEfuseImage().load(str(EFUSE_IMAGE)))
        await self.bring_up_no_cpu(max_cycles=SENSE_CYCLES)
        self.suppress_host_axi_transaction_info()
        self.tw = SepBitWatch(dut.spi_lsio_trigger_probe_o, {"trig": 0}).start()
        self.trig = self.tw
        self.busy = SepBitWatch(dut.dma_busy_probe_o, {"busy": 0}).start()
        self.irq = SepBitWatch(dut.sep_internal_interrupts_probe_o, {"chunk": 9}).start()
        self.pads = SepSpiPadSampler(keep_edges=False).start()
        self.spi = SepSpiHostOps(self, clock=self.pads.now)
        self.dma = SepDmaOps(self)
        self.mem = SepMemWords(self)
        # Runs only inside the handshake and interrupt-clear runs, never across
        # an rst_ni pulse.
        self.dtap = SepDmaTap(dut)
        self.wire = SepSpiWireMonitor(dut, name="sep_spi_hs_wire")
        self.flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            dq_out=dut.spi_sd_o,
            dq_in=dut.spi_sd_i,
            mode="quad_io",
            name="sep_spi_hs_flash",
        )
        self.flash.write_memory(FLASH_ADDR, cfg.flash_bytes())
        for _, addr, data in cfg.lane_reads.values():
            self.flash.write_memory(addr, data)
        self.flash.init_signals()
        await self.flash.start()
        try:
            await self._body()
        finally:
            close_graded_window(self.logger)
            if self.sess is not None:
                # Only after an earlier failure: stop without grading.
                self.sess = None
                try:
                    await self.wire.monitor.stop()
                except AssertionError as exc:
                    self.logger.error("SPI wire monitor stop after a failure: %s", exc)
            await self.flash.stop()
            for w in (self.tw, self.busy, self.irq):
                await w.stop()
            await self.dtap.stop()
            await self.pads.stop()
        self.result_pass(TEST, cfg.seed, self.n_checks)

    async def _body(self) -> None:
        cfg = self.cfg_
        nw = cfg.n * cfg.cw

        # Steps 1-3: depth check (control).
        await self._depth_check()

        # Step 4: reference run (control) and the sentinel.
        ref = await self._reference_run()
        ref_set = set(ref)
        self.sentinel = unique_words(cfg.rng, 1, exclude=ref_set)[0]
        ref_distinct = int(len(set(ref[:nw])) == nw)
        # Golden of CHK-HS-DATA: the flash bytes at address 0, packed with
        # ByteOrder = 1 (the first byte received lands in RXDATA[7:0]).
        fb = cfg.flash_bytes()
        golden = [int.from_bytes(fb[4 * i : 4 * i + 4], "little") for i in range(nw)]
        # MUTATION hook (step 14, item 2): reverse the chunk order of ``golden``
        # (chunks of cfg.cw words); CHK-HS-DATA fails.
        ref_match = sum(1 for i in range(nw) if ref[i] == golden[i])
        self.logger.info(
            "CTL-HS-REF LOG seed=%d words=%d ref_distinct=%d ref_match_golden=%d/%d "
            "sentinel=0x%08x ref=%s",
            cfg.seed,
            len(ref),
            ref_distinct,
            ref_match,
            nw,
            self.sentinel,
            ",".join(f"{w:08x}" for w in ref),
        )

        # Trigger cell and lane reads.
        await self._trigger_cell()
        await self._lane_leg()

        # Steps 5-6: handshake run, mask bit 0 set.
        await self._cold_reset("handshake")
        open_graded_window(TEST, self.logger)
        rx_bytes = cfg.n * cfg.chunk + cfg.extra_bytes
        bound = cfg.seg_clks(rx_bytes)
        await self.dma.wr(INTR_ENABLE, INTR_EN_CHUNK)
        m_hs_irq = self.irq.mark()
        self.dtap.start()
        m_hs_tap = self.dtap.mark()
        t_go, _ = await self._hs_start(
            mask=cfg.mask_on, total=cfg.n * cfg.chunk, dst_words=nw, rx_bytes=rx_bytes
        )
        hs_polls: list[DmaStatus] = []
        last_addr = HS_DST + 4 * (nw - 1)
        while True:
            if self.tw.clk - t_go > bound:
                msg = (
                    f"FAIL-DMA-TIMEOUT seed={cfg.seed}: last word of chunk {cfg.n} still holds the "
                    f"sentinel {bound} clocks after GO (polls={len(hs_polls)})"
                )
                self.logger.error(msg)
                raise AssertionError(msg)
            hs_polls.append(await self.dma.read_status())
            if (await self.mem.read(last_addr, 1))[0] != self.sentinel:
                break
        t_fill = self.tw.clk - t_go
        dest = await self.mem.read(HS_DST, nw)
        mismatch = [i for i in range(nw) if dest[i] != golden[i]]
        line = (
            f"width=x1 bytes={4 * nw} words={nw} chunks={cfg.n} chunk={cfg.chunk} wm={cfg.wm} "
            f"mask=0x{cfg.mask_on:03x} mismatch={len(mismatch)} "
            f"first_mismatch_word={mismatch[0] if mismatch else '-'} ref_distinct={ref_distinct} "
            f"dest={','.join(f'{w:08x}' for w in dest)}"
        )
        if not ref_distinct:
            self._ctrl_missing("CHK-HS-DATA", line)
        if mismatch:
            self._fail("CHK-HS-DATA", line)
        self._pass("CHK-HS-DATA", line)
        self._expect_rx(FLASH_READ, 1, words_bytes(dest), want=4 * nw, label="handshake")
        self.logger.info(
            "T-FILL LOG seed=%d t_fill_clks=%d polls=%d", cfg.seed, t_fill, len(hs_polls)
        )
        # In handshake operation the engine does not clear GO (CONTROL.GO):
        # expected GO=1 at TOTAL_DATA_SIZE and after the wait.
        go1 = field_compare(await self.dma.rd(DMA_CONTROL), GO_MASK, GO_MASK)
        st_total = await self.dma.read_status()
        t1 = self.tw.clk
        while self.tw.clk - t1 < t_fill:
            hs_polls.append(await self.dma.read_status())
        go2 = field_compare(await self.dma.rd(DMA_CONTROL), GO_MASK, GO_MASK)
        # Firmware stops the handshake operation by clearing GO.
        await self.dma.wr(DMA_CONTROL, self.dma.last_control & ~GO_MASK)
        hs_ev = self.dtap.since(m_hs_tap)
        await self.dtap.stop()
        # Control of CHK-HS-CLR: CLEAR_INTR_SRC = 0 from reset.
        hs_clr_aw = sum(1 for b in hs_ev.aw if b.addr == CLR_ADDR)
        hs_aw = len(hs_ev.aw)
        hs_irq_rises = self.irq.rises_since(m_hs_irq, "chunk")
        hs_irq_high = self.irq.high_clocks_since(m_hs_irq, "chunk")
        self._probe_log("handshake")
        for i, st in enumerate(hs_polls):
            self.logger.debug("HS-POLL %d %s", i, st.fmt())
        hs_chunk_polls = sum(st.chunk_done for st in hs_polls)
        self.logger.info(
            "HS-POLL LOG seed=%d polls=%d polls_with_chunk_done=%d chunk_irq_rises=%d "
            "chunk_irq_high_clks=%d last=%s",
            cfg.seed,
            len(hs_polls),
            hs_chunk_polls,
            hs_irq_rises,
            hs_irq_high,
            hs_polls[-1].fmt(),
        )
        close_graded_window(self.logger)
        mask1_filled = 1  # the poll above ended on a non-sentinel last word

        # Step 7: masked run, mask bit 0 clear.
        await self._cold_reset("masked")
        open_graded_window(TEST, self.logger)
        m_trig = self.trig.mark()
        t_go, masked_mark = await self._hs_start(
            mask=cfg.mask_off, total=cfg.n * cfg.chunk, dst_words=nw, rx_bytes=rx_bytes
        )
        masked_written = 0
        polls = 0
        while self.tw.clk - t_go < t_fill:
            img = await self.mem.read(HS_DST, nw)
            polls += 1
            masked_written += sum(1 for w in img if w != self.sentinel)
        img = await self.mem.read(HS_DST, nw)
        end_written = sum(1 for w in img if w != self.sentinel)
        trig_high = self.trig.high_clocks_since(m_trig)
        go_masked = self._go_cmp(await self.dma.rd(DMA_CONTROL))
        self.logger.info(
            "OBS-HS-GO-MASKED LOG seed=%d go=%d %s",
            cfg.seed,
            int(go_masked.ok),
            go_masked.fields(),
        )
        self._probe_log("masked")
        close_graded_window(self.logger)
        line = (
            f"dest_sentinel_kept={int(masked_written == 0 and end_written == 0)} "
            f"go={int(go_masked.ok)} {go_masked.fields()} "
            f"control_mask1_filled={mask1_filled} trigger_high_clk={trig_high} "
            f"window_clks={t_fill} dest_polls={polls} words_written_end={end_written} "
            f"mask=0x{cfg.mask_off:03x}"
        )
        if trig_high < 1:
            self._ctrl_missing("CHK-HS-MASKED", line)
        if masked_written or end_written or not go_masked.ok:
            self._fail("CHK-HS-MASKED", line)
        self._pass("CHK-HS-MASKED", line)
        # The masked frame's words stay in the RX FIFO; the host reads them out.
        masked_words = await self._drain_words(rx_bytes // 4, masked_mark, "masked run")
        self._expect_rx(FLASH_READ, 1, words_bytes(masked_words), want=rx_bytes, label="masked")

        # Step 8: stop run.
        await self._cold_reset("stop")
        open_graded_window(TEST, self.logger)
        n_tot = cfg.chunks_total_stop
        tot_words = n_tot * cfg.cw
        rx_stop = cfg.n_stop * cfg.chunk + cfg.extra_bytes
        t_go, pad_mark = await self._hs_start(
            mask=cfg.mask_on, total=n_tot * cfg.chunk, dst_words=tot_words, rx_bytes=rx_stop
        )
        await self.spi.wait_segment_done(self.pads, pad_mark, bound_clks=cfg.seg_clks(rx_stop))
        img1 = await self._stable_image(tot_words, t_fill, "first segment")
        filled = self._filled(img1, n_tot)
        n_moved = sum(filled)
        self.logger.info(
            "STOP-PRE LOG seed=%d n_moved=%d chunks_total=%d filled=%s",
            cfg.seed,
            n_moved,
            n_tot,
            "".join(str(int(f)) for f in filled),
        )
        # Re-trigger leg, GO still 1: the DMA drained RXQD below RX_WATERMARK, so
        # the trigger is low; a second segment of W+1 words raises it again and
        # the engine moves the next chunk (OpenTitan DMA theory of operation:
        # an assertion of an enabled trigger moves an entire chunk; while it is
        # not asserted the engine waits for the next chunk).
        # Stream of the RX FIFO: the first segment, then the second segment;
        # each segment is a READ at flash address 0.
        stream = cfg.flash_words[: rx_stop // 4] + cfg.flash_words[: cfg.extra_bytes // 4]
        re_low_before = int(self.tw.level() == 0)
        m_re = self.trig.mark()
        mark_re = await self._spi_sequence(cfg.extra_bytes)
        await self.spi.wait_segment_done(
            self.pads, mark_re, bound_clks=cfg.seg_clks(cfg.extra_bytes)
        )
        img_re = await self._stable_image(tot_words, t_fill, "re-trigger segment")
        re_rises = self.trig.rises_since(m_re)
        filled_re = self._filled(img_re, n_tot)
        n_re = sum(filled_re)
        re_words = n_re * cfg.cw
        re_data = int(
            img_re[:re_words] == stream[:re_words]
            and all(w == self.sentinel for w in img_re[re_words:])
        )
        self.logger.info(
            "STOP-RETRIG LOG seed=%d n_moved_retrigger=%d filled=%s trigger_low_before=%d "
            "trigger_rises=%d",
            cfg.seed,
            n_re,
            "".join(str(int(f)) for f in filled_re),
            re_low_before,
            re_rises,
        )
        # Step 9: GO clear, more Rx data.
        # Control: GO still reads 1 before the clear, so the stop is caused by
        # the firmware write and not by an engine that cleared GO itself.
        go_before = int(bool(await self.dma.rd(DMA_CONTROL) & GO_MASK))
        stop_ctrl = self.dma.last_control & ~GO_MASK
        m_trig = self.trig.mark()
        await self.dma.wr(DMA_CONTROL, stop_ctrl)
        t_clr = self.tw.clk
        mark_more = await self._spi_sequence(cfg.extra_bytes)
        await self._wait_clocks(t_clr + t_fill)
        trig_high = self.trig.high_clocks_since(m_trig)
        img3 = await self.mem.read(HS_DST, tot_words)
        after = img3[re_words:]
        after_kept = int(all(w == self.sentinel for w in after))
        moved_kept = int(img3[:re_words] == img_re[:re_words])
        self._probe_log("stop")
        close_graded_window(self.logger)
        line = (
            f"n_stop={cfg.n_stop} n_moved={n_moved} n_moved_retrigger={n_re} "
            f"chunks_total={n_tot} re_data_match={re_data} "
            f"control_re_trigger_low_before={re_low_before} "
            f"control_re_trigger_rises={re_rises} "
            f"dest_after_clear_sentinel={after_kept} trigger_high_clk={trig_high} "
            f"window_clks={t_fill} go_before_clear={go_before} "
            f"control_after_clear=0x{stop_ctrl:08x} "
            f"moved_unchanged={moved_kept}"
        )
        if n_moved < 1 or n_re >= n_tot or trig_high < 1 or not go_before:
            self._ctrl_missing("CHK-HS-STOP", line)
        if not re_low_before or re_rises < 1:
            self._ctrl_missing("CHK-HS-STOP", line)
        # With GO=1 the trigger that rises again moves the next chunk.
        if n_re <= n_moved or not re_data:
            self._fail("CHK-HS-STOP", line)
        if not (after_kept and moved_kept):
            self._fail("CHK-HS-STOP", line)
        self._pass("CHK-HS-STOP", line)
        # The words the DMA left in the RX FIFO (rest of the first two frames,
        # then the third frame) go out through RXDATA.
        moved = img3[:re_words]
        held = rx_stop // 4 + cfg.extra_bytes // 4
        rest = await self._drain_words(
            held - len(moved) + cfg.extra_bytes // 4, mark_more, "stop run after the GO clear"
        )
        got = moved + rest
        f1, f2 = rx_stop // 4, held
        self._expect_rx(FLASH_READ, 1, words_bytes(got[:f1]), want=rx_stop, label="stop_first")
        self._expect_rx(
            FLASH_READ, 1, words_bytes(got[f1:f2]), want=cfg.extra_bytes, label="stop_retrigger"
        )
        self._expect_rx(
            FLASH_READ, 1, words_bytes(got[f2:]), want=cfg.extra_bytes, label="stop_more"
        )

        # Interrupt-clear run: the handshake copy with the source 0 clear write.
        await self._clear_run(nw, rx_bytes, t_fill, hs_clr_aw, hs_aw)

        # Steps 10-12: normal-mode control (no SPI traffic, no monitor session).
        await self._cold_reset("normal", session=False)
        dma = self.dma
        await dma.program_range(SRAM_BASE, NM_RANGE_LIMIT)
        await dma.wr(SECURE_DMA.addr("ADDR_SPACE_ID"), ASID)
        await self.mem.fill(NM_SRC, cfg.nm_src)
        await self.mem.fill(NM_DST, [cfg.nm_sentinel] * (NM_TOTAL // 4))
        await dma.program_transfer(
            src=NM_SRC, dst=NM_DST, total=NM_TOTAL, chunk=NM_CHUNK, width_enc=2
        )
        await dma.wr(INTR_ENABLE, INTR_EN_CHUNK)
        m_irq = self.irq.mark()
        await dma.go(opcode=OP_COPY, hs=0, initial=1)
        res = await dma.run_to_done(NM_TOTAL, busy=self.busy, w1c_chunk_done=True)
        st = res.status
        statuses = list(res.statuses)
        if st.busy:
            st = await dma.poll_status(lambda s: s.busy == 0, 2_000, "normal mode: BUSY=0")
            statuses.append(st)
        irq_rises = self.irq.rises_since(m_irq, "chunk")
        nm_chunk_polls = sum(s.chunk_done for s in statuses)
        go_nm = self._go_cmp(await dma.rd(DMA_CONTROL))
        nm_img = await self.mem.read(NM_DST, NM_TOTAL // 4)
        self.logger.info(
            "CTL-HS-NORMAL LOG seed=%d done=%d error=%d polls=%d polls_with_chunk_done=%d "
            "chunk_irq_rises=%d go_writes=%d go=%d image_equal=%d",
            cfg.seed,
            st.done,
            st.error,
            len(statuses),
            nm_chunk_polls,
            irq_rises,
            res.go_writes,
            int(bool(go_nm.got & GO_MASK)),
            int(nm_img == cfg.nm_src),
        )
        if not st.done or st.error:
            self._ctrl_missing("CHK-HS-GO", f"normal-mode copy did not end in DONE: {st.fmt()}")

        # CHK-HS-NOCHUNK.
        line = (
            f"polls_with_chunk_done={hs_chunk_polls} polls={len(hs_polls)} "
            f"chunk_irq_rises={hs_irq_rises} chunk_irq_high_clks={hs_irq_high} "
            f"control_normal_polls={len(statuses)} control_chunk_irq_rises={irq_rises} "
            f"control_normal_polls_with_chunk_done={nm_chunk_polls}"
        )
        # The poll leg and the line leg each need their own control: a dead or
        # mis-bound bit-9 tap reads 0 here.
        if nm_chunk_polls < 1 or irq_rises < 1:
            self._ctrl_missing("CHK-HS-NOCHUNK", line)
        if hs_chunk_polls or hs_irq_rises or hs_irq_high:
            self._fail("CHK-HS-NOCHUNK", line)
        self._pass("CHK-HS-NOCHUNK", line)

        # CHK-HS-GO. "For Hardware handshake operation, DMA engine does not
        # auto clear the Go bit. Firmware shall clear the Go bit when it
        # intends to stop the hardware handshake operation" (secure_dma.adoc,
        # CONTROL.GO). The text does not state GO at TOTAL_DATA_SIZE, so GO at
        # the total and after the wait are logged only.
        control_normal_go = int(bool(go_nm.got & GO_MASK))
        go_at_total = int(bool(go1.got & GO_MASK))
        go_after_wait = int(bool(go2.got & GO_MASK))
        line = f"go_held_between_chunks={go_before} control_normal_go={control_normal_go}"
        if control_normal_go != 0:
            self._ctrl_missing("CHK-HS-GO", line)
        self.logger.info(
            "OBS-HS-DONE seed=%d done_at_total=%d go_at_total=%d",
            cfg.seed,
            st_total.done,
            go_at_total,
        )
        self.logger.info(
            "OBS-HS-GO-TOTAL seed=%d go_at_total=%d go_after_wait=%d done_at_total=%d "
            "control_at_total=0x%08x control_after_wait=0x%08x t_fill=%d",
            cfg.seed,
            go_at_total,
            go_after_wait,
            st_total.done,
            go1.got,
            go2.got,
            t_fill,
        )
        if go_before != 1:
            self._fail("CHK-HS-GO", line)
        self._pass("CHK-HS-GO", line)
