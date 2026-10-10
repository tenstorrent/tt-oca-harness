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
leaf sets TX_WATERMARK 0, so only the RX term raises the trigger. The SPI
responder is ``OcahSpiFlash``; it serves one READ (0x03, address 0) of unique
words per run.

Runs, each from a cold reset (``rst_ni`` pulse, bounded wait for
``dbg_sep_reset_n_o``), since CFG_REGWEN locks the DMA configuration while a
handshake run keeps GO set:

* depth check (control): an Rx segment of 4*(W+1) bytes with no reader must not
  fill the RX FIFO;
* reference run (control): the host reads the flash stream through RXDATA; the
  sentinel is drawn as a word that equals no reference word;
* handshake run, mask bit 0 set: the poll for the last word of chunk n sets
  t_fill, the window length of every later run (never an expected value);
* masked run, mask bit 0 clear;
* stop run: n_stop chunks move, firmware clears GO, more Rx data arrives;
* normal-mode control: a 4096-byte memory-to-memory copy in chunks of 1024.

Checkers:
  CHK-HS-MASKED   mask bit 0 clear: the destination keeps its sentinel while the
                  trigger probe is high.
  CHK-HS-GO       GO stays 1 between chunks below TOTAL_DATA_SIZE (stop run,
                  before the firmware clear) and reads 0 with STATUS.DONE=1 once
                  the transfer reaches TOTAL_DATA_SIZE (handshake run).
  CHK-HS-STOP     after the GO clear the words after the moved chunks keep their
                  sentinel while the trigger probe is high.
  CHK-HS-NOCHUNK  STATUS.CHUNK_DONE reads 0 at every poll of the handshake run.
  CHK-HS-DATA     blocked: the specification does not name the pad line that
                  carries the Rx bit in standard mode. The leaf logs
                  ``OBS-HS-DATA LOG`` only; it grades nothing and is not counted.

Controls: RX depth above W+1; mask=1 run fills the destination; trigger high in
each "never" window; 1 <= n_moved < chunks_total; the normal-mode copy reads
GO=0 at DONE and shows CHUNK_DONE in a poll or a rise of PIC source 10 (bit 9
of ``sep_internal_interrupts_probe_o``). A missing control logs CTRL-MISSING and
fails the leaf.

Probes: ``spi_lsio_trigger_probe_o``, ``dma_busy_probe_o``, ``spi_tx_qd_probe_o``
(logged), ``dbg_sep_reset_n_o``, ``sep_internal_interrupts_probe_o`` bit 9, the
SPI pad ports and the register frontdoor over ``s_axi``.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense, both simulators.
Every draw comes from ``SepSeededRng`` and the run seed.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_bit_watch import SepBitWatch
from env.sep_efuse_image import SepEfuseImage
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_pad_sampler import SepSpiPadSampler, SpiPadTimeout
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
    DIR_RX,
    DIR_TX,
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

# The committed default OTP image: the harness disable vectors, never randomized.
EFUSE_IMAGE = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "sep_efuse_default.hex"
)

# Bounds.
SENSE_CYCLES = 20_000
STABLE_READS = 8


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
        return self.n_stop + -(-self.extra_bytes // self.chunk) + 1

    def flash_bytes(self) -> bytes:
        return b"".join(w.to_bytes(4, "little") for w in self.flash_words)

    def seg_clks(self, rx_bytes: int) -> int:
        """Clock bound of one Tx+Rx frame: 8 bits per byte, 2*(CLKDIV+1) clocks per bit."""
        return 4 * (READ_CMD_BYTES + rx_bytes) * 8 * 2 * (self.clkdiv + 1) + 50_000


@pyuvm.test()
class sep_spi_dma_handshake_rand_test(sep_base_test):
    """SPI-to-DMA hardware handshake: mask, GO, stop and chunk rules."""

    required_evidence = ("CHK-HS-MASKED", "CHK-HS-GO", "CHK-HS-STOP", "CHK-HS-NOCHUNK")

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

    # ---- reset and SPI -----------------------------------------------------
    async def _cold_reset(self, tag: str) -> None:
        """Non-graded cold reset: window closed, rst_ni pulse, SEP reset release."""
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

    async def _spi_sequence(self, rx_bytes: int):
        """The SPI sequence of every run; returns the pad mark taken before the Tx command."""
        cfg = self.cfg_
        spi = self.spi
        await spi.wr(SPI_CONTROL, CTRL_SPIEN | CTRL_OUTPUT_EN | (cfg.wm << CTRL_RX_WM_LSB))
        await spi.wr(EVENT_ENABLE, 0)
        await spi.wr(SPI_INTR_ENABLE, 0)
        await spi.wr(CSID, 0)
        await spi.write_configopts(configopts_word(clkdiv=cfg.clkdiv))
        await spi.push_tx(READ_CMD_WORD)
        mark = self.pads.mark()
        await spi.issue_command(
            command_word(READ_CMD_BYTES - 1, speed=SPEED_STD, direction=DIR_TX, csaat=1)
        )
        await spi.issue_command(
            command_word(rx_bytes - 1, speed=SPEED_STD, direction=DIR_RX, csaat=0)
        )
        return mark

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

    # ---- runs --------------------------------------------------------------
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
        return words

    async def run_scenario(self) -> None:
        self.cfg_ = cfg = _Cfg(self.random_seed())
        self.n_checks = 0
        dut = cocotb.top
        self.logger.info(
            "PLAN seed=%d runs=depth,reference,handshake,masked,stop,normal "
            "graded=handshake,masked,stop checks=CHK-HS-MASKED,CHK-HS-GO,CHK-HS-STOP,"
            "CHK-HS-NOCHUNK blocked=CHK-HS-DATA",
            cfg.seed,
        )
        self.logger.info(
            "DRAW seed=%d chunk=%d n=%d mask_hi=0x%03x n_stop=%d clkdiv=%d wm=%d "
            "chunks_total_stop=%d",
            cfg.seed,
            cfg.chunk,
            cfg.n,
            cfg.mask_hi,
            cfg.n_stop,
            cfg.clkdiv,
            cfg.wm,
            cfg.chunks_total_stop,
        )
        self.logger.info(
            "DRAW seed=%d flash_addr=0x%06x flash_words=%s",
            cfg.seed,
            FLASH_ADDR,
            ",".join(f"{w:08x}" for w in cfg.flash_words),
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
        self.flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_spi_hs_flash",
        )
        self.flash.write_memory(FLASH_ADDR, cfg.flash_bytes())
        self.flash.init_signals()
        await self.flash.start()
        try:
            await self._body()
        finally:
            close_graded_window(self.logger)
            await self.flash.stop()
            for w in (self.tw, self.busy, self.irq):
                await w.stop()
            await self.pads.stop()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, cfg.seed, self.n_checks)

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
        self.logger.info(
            "CTL-HS-REF LOG seed=%d words=%d ref_distinct=%d sentinel=0x%08x ref=%s",
            cfg.seed,
            len(ref),
            ref_distinct,
            self.sentinel,
            ",".join(f"{w:08x}" for w in ref),
        )

        # Steps 5-6: handshake run, mask bit 0 set.
        await self._cold_reset("handshake")
        open_graded_window(TEST, self.logger)
        rx_bytes = cfg.n * cfg.chunk + cfg.extra_bytes
        bound = cfg.seg_clks(rx_bytes)
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
        mismatch = sum(1 for i in range(nw) if dest[i] != ref[i])
        self.logger.info(
            "OBS-HS-DATA LOG seed=%d blocked=1 ref_distinct=%d mismatch=%d chunk=%d n=%d wm=%d "
            "mask=0x%03x words=%d dest=%s",
            cfg.seed,
            ref_distinct,
            mismatch,
            cfg.chunk,
            cfg.n,
            cfg.wm,
            cfg.mask_on,
            nw,
            ",".join(f"{w:08x}" for w in dest),
        )
        self.logger.info(
            "T-FILL LOG seed=%d t_fill_clks=%d polls=%d", cfg.seed, t_fill, len(hs_polls)
        )
        go1 = self._go_cmp(await self.dma.rd(DMA_CONTROL))
        st_total = await self.dma.read_status()
        t1 = self.tw.clk
        while self.tw.clk - t1 < t_fill:
            hs_polls.append(await self.dma.read_status())
        go2 = self._go_cmp(await self.dma.rd(DMA_CONTROL))
        self._probe_log("handshake")
        for i, st in enumerate(hs_polls):
            self.logger.debug("HS-POLL %d %s", i, st.fmt())
        hs_chunk_polls = sum(st.chunk_done for st in hs_polls)
        self.logger.info(
            "HS-POLL LOG seed=%d polls=%d polls_with_chunk_done=%d last=%s",
            cfg.seed,
            len(hs_polls),
            hs_chunk_polls,
            hs_polls[-1].fmt(),
        )
        close_graded_window(self.logger)
        mask1_filled = 1  # the poll above ended on a non-sentinel last word

        # Step 7: masked run, mask bit 0 clear.
        await self._cold_reset("masked")
        open_graded_window(TEST, self.logger)
        m_trig = self.trig.mark()
        t_go, _ = await self._hs_start(
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
            f"control_mask1_filled={mask1_filled} trigger_high_clk={trig_high} "
            f"window_clks={t_fill} dest_polls={polls} words_written_end={end_written} "
            f"mask=0x{cfg.mask_off:03x}"
        )
        if trig_high < 1:
            self._ctrl_missing("CHK-HS-MASKED", line)
        if masked_written or end_written:
            self._fail("CHK-HS-MASKED", line)
        self._pass("CHK-HS-MASKED", line)

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
        img1 = await self.mem.read(HS_DST, tot_words)
        for _ in range(STABLE_READS):
            await self._wait_clocks(self.tw.clk + t_fill)
            img2 = await self.mem.read(HS_DST, tot_words)
            if img2 == img1:
                break
            img1 = img2
        else:
            self._ctrl_missing("CHK-HS-STOP", f"destination not stable after {STABLE_READS} reads")
        filled = [
            all(w != self.sentinel for w in img1[c * cfg.cw : (c + 1) * cfg.cw])
            for c in range(n_tot)
        ]
        n_moved = sum(filled)
        self.logger.info(
            "STOP-PRE LOG seed=%d n_moved=%d chunks_total=%d filled=%s",
            cfg.seed,
            n_moved,
            n_tot,
            "".join(str(int(f)) for f in filled),
        )
        # Step 9: GO clear, more Rx data.
        # Control: GO still reads 1 before the clear, so the stop is caused by
        # the firmware write and not by an engine that cleared GO itself.
        go_before = int(bool(await self.dma.rd(DMA_CONTROL) & GO_MASK))
        stop_ctrl = self.dma.last_control & ~GO_MASK
        m_trig = self.trig.mark()
        await self.dma.wr(DMA_CONTROL, stop_ctrl)
        t_clr = self.tw.clk
        await self._spi_sequence(cfg.extra_bytes)
        await self._wait_clocks(t_clr + t_fill)
        trig_high = self.trig.high_clocks_since(m_trig)
        img3 = await self.mem.read(HS_DST, tot_words)
        after = img3[n_moved * cfg.cw :]
        after_kept = int(all(w == self.sentinel for w in after))
        self._probe_log("stop")
        close_graded_window(self.logger)
        line = (
            f"n_stop={cfg.n_stop} n_moved={n_moved} chunks_total={n_tot} "
            f"dest_after_clear_sentinel={after_kept} trigger_high_clk={trig_high} "
            f"window_clks={t_fill} go_before_clear={go_before} "
            f"control_after_clear=0x{stop_ctrl:08x} "
            f"moved_unchanged={int(img3[: n_moved * cfg.cw] == img1[: n_moved * cfg.cw])}"
        )
        if n_moved < 1 or n_moved >= n_tot or trig_high < 1 or not go_before:
            self._ctrl_missing("CHK-HS-STOP", line)
        if not after_kept:
            self._fail("CHK-HS-STOP", line)
        self._pass("CHK-HS-STOP", line)

        # Steps 10-12: normal-mode control.
        await self._cold_reset("normal")
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
            f"control_normal_polls={len(statuses)} control_chunk_irq_rises={irq_rises} "
            f"control_normal_polls_with_chunk_done={nm_chunk_polls}"
        )
        if nm_chunk_polls < 1 and irq_rises < 1:
            self._ctrl_missing("CHK-HS-NOCHUNK", line)
        if hs_chunk_polls:
            self._fail("CHK-HS-NOCHUNK", line)
        self._pass("CHK-HS-NOCHUNK", line)

        # CHK-HS-GO. Handshake mode skips the per-chunk GO clear only; the
        # transfer ends, and GO clears, at TOTAL_DATA_SIZE (dma.hjson
        # TOTAL_DATA_SIZE and CONTROL.GO).
        control_normal_go = int(bool(go_nm.got & GO_MASK))
        go_at_total = int(go1.ok)
        go_after_wait = int(go2.ok)
        line = (
            f"go_held_between_chunks={go_before} go_at_total={go_at_total} "
            f"done_at_total={st_total.done} go_after_wait={go_after_wait} "
            f"control_normal_go={control_normal_go} "
            f"at_total:[{go1.fields()}] after_wait:[{go2.fields()}] t_fill={t_fill}"
        )
        if control_normal_go != 0:
            self._ctrl_missing("CHK-HS-GO", line)
        if not (go_before == 1 and go_at_total == 0 and go_after_wait == 0 and st_total.done):
            self._fail("CHK-HS-GO", line)
        self._pass("CHK-HS-GO", line)
