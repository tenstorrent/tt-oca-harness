# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA zero fill continued by GO=1 with INITIAL_TRANSFER=0.

DIRECTED. The leaf programs the secure DMA over the CPU-LSU splice (no CPU) and
keeps every buffer in SEP SRAM (``memory_map.adoc``). Each leg starts a zero
fill (OPCODE 4) and then continues it with a CONTROL write of GO=1 and
INITIAL_TRANSFER=0. The range and handshake rules of the zero fill have no
condition on INITIAL_TRANSFER, so they hold for the continuation too:

* ``hw/sys/sep/doc/dma.adoc:86-92``: the fill writes only inside
  ENABLED_MEMORY_RANGE_BASE to ENABLED_MEMORY_RANGE_LIMIT inclusive, and the
  engine checks each write before it issues it, so the bound holds across
  chunks. The first write that would leave the range is not issued, and the
  fill stops with STATUS.ERROR and ERROR_CODE.DST_ADDR_ERROR. Locking the range
  with RANGE_REGWEN fixes the erase window until reset.
* ``hw/sys/sep/doc/dma.adoc:97-99``: with HARDWARE_HANDSHAKE_ENABLE set, a zero
  fill ends in ERROR_CODE.OPCODE_ERROR when the first trigger arrives.

Legs, in this order (the lock leg is last because the lock holds until reset):

* Leg E, per TRANSFER_WIDTH encoding 2, 1, 0: a two-chunk fill of a 64-byte
  window whose last write ends at LIMIT, then GO=1 with INITIAL_TRANSFER=0 and
  no other register write.
* Leg H: chunk 1 of a two-chunk fill with HARDWARE_HANDSHAKE_ENABLE=0, the SPI
  trigger held high (SPI CONTROL.TX_WATERMARK 1 with an empty TX FIFO,
  ``hw/sys/sep/doc/spi.adoc``, DMA Trigger), then CONTROL with
  HARDWARE_HANDSHAKE_ENABLE=1, INITIAL_TRANSFER=0 and GO=1.
* Leg L: chunk 1 of a two-chunk fill with a range that holds both chunks, then
  the range narrowed to chunk 1 and locked with RANGE_REGWEN False, then GO=1
  with INITIAL_TRANSFER=0.

Probes: register and SRAM frontdoor over ``s_axi``; ``dma_axi_req_probe_o`` and
``dma_status_probe_o`` through ``env/sep_dma_tap.py`` (AW address and WSTRB of
each write); ``spi_lsio_trigger_probe_o``. WDATA is not on the probe, so the
leaf writes non-zero sentinel words around each window and reads them back.
No inject.

Checkers (log shape ``CHK-<ID> PASS|FAIL seed=<n> ...``; every leg is graded,
and the leaf fails at the end when one or more checks fail):
  CHK-DMA-ZERO-CONT-LIMIT  per width: after the continuation no write byte is
                           outside BASE..LIMIT on the probe and the sentinel
                           words after LIMIT read unchanged. Control
                           (``CTRL ... PASS``): the fill before it writes the
                           whole window, its last write byte is LIMIT and the
                           guards read the sentinel, so the probe and the
                           readback see writes up to the bound.
  CHK-DMA-ZERO-CONT-HS     the continuation sets ERROR with ERROR_CODE equal to
                           OPCODE_ERROR alone and issues no write. Controls:
                           chunk 1 completes with handshake off; the trigger
                           probe reads 1 at the GO write; the same CONTROL
                           value with INITIAL_TRANSFER=1 gives OPCODE_ERROR and
                           no write, so the check reads an error the engine
                           reports.
  CHK-DMA-ZERO-CONT-LOCK   the continuation issues no write byte outside the
                           locked window, zeroes no word outside it, and stops
                           with ERROR and ERROR_CODE equal to DST_ADDR_ERROR
                           alone (its first write is outside the window).
                           Controls: chunk 1 completes inside the wide range;
                           RANGE_REGWEN reads other than True and LIMIT keeps
                           the narrow value through a later write; a new fill
                           with INITIAL_TRANSFER=1 stops at the locked LIMIT
                           with DST_ADDR_ERROR, so the lock is in force.

A control that does not hold fails the leaf with ``CTRL-MISSING``.

Run mode: no_cpu, target ``lsu_stub_all_live``, ``+skip_fuse_sense`` (no fuse
content is needed); Verilator and VCS. The stimulus does not depend on the
seed.
"""

from __future__ import annotations

from collections.abc import Callable

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_bit_watch import SepBitWatch
from env.sep_dma_tap import DmaTapEvents, SepDmaTap
from sep_base_test import sep_base_test
from sep_reg_meta import SPI_CONTROLLER, sym
from seq_lib.sep_dma_ops import (
    _D,
    CONTROL,
    DST_ADDR_HI,
    ERROR_CODE,
    ERROR_CODE_MASK,
    HANDSHAKE_INTR_ENABLE,
    INTR_ENABLE,
    OP_ZERO,
    RANGE_LIMIT,
    RANGE_REGWEN,
    SRC_ADDR_HI,
    DmaStatus,
    SepDmaOps,
    SepMemWords,
    control_word,
)
from seq_lib.sep_spi_host_csr_seq import CONTROL as SPI_CONTROL

TEST = "sep_dma_zero_fill_continuation_test"

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LIMIT = SRAM_BASE + SRAM_SIZE - 1
ASID = 0x7
# TRANSFER_WIDTH encoding -> bytes per write.
WIDTH = {0: 1, 1: 2, 2: 4}

DST_ERR = _D.field_mask("ERROR_CODE", "dst_addr_error")
OPC_ERR = _D.field_mask("ERROR_CODE", "opcode_error")
HS_RESET = _D.reset32("HANDSHAKE_INTR_ENABLE")
HS_TRIGGER0 = 1 << _D.field_lsb("HANDSHAKE_INTR_ENABLE", "mask")
SPI_TX_WM = SPI_CONTROLLER.field_mask("CONTROL", "tx_watermark")
SPI_TX_WM_LSB = SPI_CONTROLLER.field_lsb("CONTROL", "tx_watermark")
REGWEN_MASK = _D.field_mask("RANGE_REGWEN", "regwen")
REGWEN_LSB = _D.field_lsb("RANGE_REGWEN", "regwen")
# RANGE_REGWEN is MuBi4 with reset True; False is its bitwise complement.
REGWEN_TRUE = (_D.reset32("RANGE_REGWEN") & REGWEN_MASK) >> REGWEN_LSB
REGWEN_FALSE = ~REGWEN_TRUE & (REGWEN_MASK >> REGWEN_LSB)

POLL = 400  # STATUS reads per bounded wait
TRIGGER_BOUND = 200  # clocks for the SPI trigger to rise
SETTLE = 200  # clocks after a GO-only write before the BUSY=0 wait
GUARD = 16  # sentinel bytes on each side of a window
SENT = 0xA5C3_5A3C  # sentinel word, no zero byte

CHECKS = ("CHK-DMA-ZERO-CONT-LIMIT", "CHK-DMA-ZERO-CONT-HS", "CHK-DMA-ZERO-CONT-LOCK")


def _aw_list(beats: list[tuple[int, int]]) -> str:
    return "[" + ",".join(f"0x{a:08x}/strb=0x{s:02x}" for a, s in beats) + "]"


@pyuvm.test()
class sep_dma_zero_fill_continuation_test(sep_base_test):
    """Zero fill continued by GO=1 with INITIAL_TRANSFER=0: range, lock and handshake rules."""

    # ---- log helpers ------------------------------------------------------
    def _check(self, chk: str, ok: bool, values: str) -> None:
        """Grade one check; a FAIL is recorded and the leaf fails at the end."""
        line = f"{chk} {'PASS' if ok else 'FAIL'} seed={self.seed} {values}"
        if ok:
            self.logger.info(line)
        else:
            self.logger.error(line)
            self.failed.append(chk)
        self.graded.append(chk)

    def _ctrl(self, what: str, ok: bool, values: str) -> None:
        if not ok:
            line = f"CTRL-MISSING {what} seed={self.seed} {values}"
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info("CTRL %s PASS seed=%d %s", what, self.seed, values)

    def _beats(self, tag: str, ev: DmaTapEvents) -> list[tuple[int, int]]:
        """(AW address, WSTRB) of each write, in order; one W beat per AW (AxLEN 0)."""
        if len(ev.w) != len(ev.aw):
            self._ctrl(f"{tag}.beats", False, f"aw={len(ev.aw)} w={len(ev.w)}")
        out = [(aw.addr or 0, w.strb or 0) for aw, w in zip(ev.aw, ev.w)]
        self.logger.info(
            "BEATS %s ar=%d aw=%d w=%d b=%d bresp=%s writes=%s",
            tag,
            len(ev.ar),
            len(ev.aw),
            len(ev.w),
            len(ev.b),
            [b.resp for b in ev.b],
            _aw_list(out),
        )
        return out

    @staticmethod
    def _bytes_written(beats: list[tuple[int, int]]) -> list[int]:
        """Byte addresses of the writes: the 8-byte beat of AxADDR and its WSTRB lanes."""
        out: list[int] = []
        for addr, strb in beats:
            base = addr & ~7
            out += [base + lane for lane in range(8) if strb >> lane & 1]
        return out

    # ---- DMA helpers ------------------------------------------------------
    async def _wait(self, pred: Callable[[DmaStatus], bool], what: str) -> DmaStatus:
        return await self.ops.poll_status(pred, POLL, what)

    async def _go(self, *, hs: int = 0, initial: int) -> None:
        await self.ops.wr(CONTROL, control_word(opcode=OP_ZERO, hs=hs, initial=initial, go=1))

    async def _ec(self) -> int:
        return await self.ops.rd(ERROR_CODE) & ERROR_CODE_MASK

    async def _idle(self) -> None:
        await self.ops.clean_state()
        await self._wait(lambda s: not s.busy, "BUSY=0")

    async def _chunk1(self, tag: str, chunk: int, *, hs: int = 0) -> None:
        """GO with INITIAL_TRANSFER=1 and wait for CHUNK_DONE of chunk 1 (width 4)."""
        m = self.tap.mark()
        await self._go(hs=hs, initial=1)
        await self._wait(lambda s: bool(s.chunk_done or s.done or s.error), "CHUNK_DONE")
        st = await self._wait(lambda s: not s.busy, "BUSY=0 after chunk 1")
        beats = self._beats(f"{tag}.chunk1", self.tap.since(m))
        self._ctrl(
            f"{tag}.chunk1",
            st.chunk_done and not st.done and not st.error and len(beats) == chunk // 4,
            f"{st.fmt()} writes={len(beats)} expect={chunk // 4}",
        )

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.failed: list[str] = []
        self.graded: list[str] = []
        self.logger.info("PLAN %s seed=%d legs=E(w4,w2,w1),H,L", TEST, self.seed)
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        dut = cocotb.top
        self.tap = SepDmaTap(dut).start()
        self.trigger = SepBitWatch(dut.spi_lsio_trigger_probe_o, name="spi_lsio_trigger").start()
        self.ops = SepDmaOps(self)
        self.mem = SepMemWords(self)
        try:
            await self.ops.set_asid(ASID, ASID)
            await self.ops.wr(SRC_ADDR_HI, 0)
            await self.ops.wr(DST_ADDR_HI, 0)
            await self.ops.wr(INTR_ENABLE, 0)
            await self.ops.clean_state()
            for enc in (2, 1, 0):
                await self._leg_limit(enc, SRAM_BASE + 0x1000 + 0x400 * enc)
            await self._leg_hs(SRAM_BASE + 0x3000)
            await self._leg_lock(SRAM_BASE + 0x4000)
        finally:
            for w in (self.tap, self.trigger):
                await w.stop()
        n_want = 3 + 1 + 1
        if len(self.graded) != n_want:
            self._ctrl("graded-count", False, f"graded={len(self.graded)} expect={n_want}")
        fails = sorted(set(self.failed))
        line = f"RESULT {TEST} seed={self.seed} graded={len(self.graded)} failed={','.join(fails)}"
        if fails:
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)

    # ---- Leg E: continuation after a fill that ends at LIMIT -------------
    async def _leg_limit(self, enc: int, base: int) -> None:
        ops = self.ops
        w = WIDTH[enc]
        size = 64
        limit = base + size - 1
        lo = base - GUARD
        nwords = (GUARD + size + GUARD) // 4
        tag = f"E.w{w}"
        await ops.program_range(base, limit, valid=True)
        await self.mem.fill(lo, [SENT] * nwords)

        # Control: a two-chunk fill of the whole window; the last write ends at LIMIT.
        await ops.program_transfer(src=0, dst=base, total=size, chunk=size // 2, width_enc=enc)
        m = self.tap.mark()
        await ops.go(opcode=OP_ZERO)
        res = await ops.run_to_done(size, stop_on=lambda s: bool(s.error or s.aborted))
        ec = await self._ec()
        beats = self._beats(f"{tag}.fill", self.tap.since(m))
        written = self._bytes_written(beats)
        img = await self.mem.read(lo, nwords)
        exp = [SENT] * (GUARD // 4) + [0] * (size // 4) + [SENT] * (GUARD // 4)
        self._ctrl(
            f"{tag}.fill",
            res.status.done
            and not res.status.error
            and ec == 0
            and len(beats) == size // w
            and sorted(written) == list(range(base, limit + 1))
            and img == exp,
            f"base=0x{base:08x} limit=0x{limit:08x} {res.status.fmt()} error_code=0x{ec:x} "
            f"writes={len(beats)} last_byte=0x{max(written, default=0):08x} "
            f"image_ok={int(img == exp)}",
        )

        # Continuation: GO=1, INITIAL_TRANSFER=0, no other register write.
        await ops.clean_state()
        m = self.tap.mark()
        await self._go(initial=0)
        await ClockCycles(cocotb.top.clk_i, SETTLE)
        # The engine holds BUSY=1 in its error state until the ERROR W1C.
        st = await self._wait(
            lambda s: bool(not s.busy or s.error), "BUSY=0 or ERROR after GO-only"
        )
        ec = await self._ec()
        beats = self._beats(f"{tag}.cont", self.tap.since(m))
        out = sorted(a for a in self._bytes_written(beats) if not base <= a <= limit)
        img = await self.mem.read(lo, nwords)
        changed = [
            f"0x{lo + 4 * i:08x}=0x{v:08x}"
            for i, v in enumerate(img)
            if not base <= lo + 4 * i <= limit and v != SENT
        ]
        self._check(
            "CHK-DMA-ZERO-CONT-LIMIT",
            not out and not changed,
            f"w={w} base=0x{base:08x} limit=0x{limit:08x} {st.fmt()} error_code=0x{ec:x} "
            f"writes={_aw_list(beats)} bytes_outside={len(out)} "
            f"first_outside={f'0x{out[0]:08x}' if out else 'none'} guard_words_changed={changed}",
        )
        await self._idle()

    # ---- Leg H: continuation with HARDWARE_HANDSHAKE_ENABLE set -----------
    async def _leg_hs(self, base: int) -> None:
        ops = self.ops
        size = 64
        chunk = 32
        lo = base - GUARD
        nwords = (GUARD + size + GUARD) // 4
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)
        await self.mem.fill(lo, [SENT] * nwords)
        await ops.program_transfer(src=0, dst=base, total=size, chunk=chunk, width_enc=2)
        await self._chunk1("H", chunk, hs=0)

        # Trigger held high: SPI TX watermark 1 with an empty TX FIFO.
        spi_ctrl = await ops.rd(SPI_CONTROL)
        await ops.wr(SPI_CONTROL, (spi_ctrl & ~SPI_TX_WM) | (1 << SPI_TX_WM_LSB))
        await ops.wr(HANDSHAKE_INTR_ENABLE, HS_TRIGGER0)
        try:
            await self.trigger.wait_level(1, TRIGGER_BOUND)
        except AssertionError:
            self._ctrl("H.trigger", False, f"no rise within {TRIGGER_BOUND} clocks")

        # Continuation: HARDWARE_HANDSHAKE_ENABLE=1, INITIAL_TRANSFER=0, GO=1.
        m = self.tap.mark()
        trig = self.trigger.level()
        await self._go(hs=1, initial=0)
        st = await self._wait(lambda s: bool(s.done or s.error), "DONE or ERROR after HS GO-only")
        ec = await self._ec()
        await ClockCycles(cocotb.top.clk_i, 50)
        beats = self._beats("H.cont", self.tap.since(m))
        self._ctrl("H.trigger_at_go", trig == 1, f"trigger_at_go={trig}")
        self._check(
            "CHK-DMA-ZERO-CONT-HS",
            bool(st.error) and ec == OPC_ERR and not beats,
            f"{st.fmt()} error_code=0x{ec:x} expect_error_code=0x{OPC_ERR:x} "
            f"writes={_aw_list(beats)}",
        )
        await ops.wr(CONTROL, 0)
        await self._idle()

        # Control: the same CONTROL value with INITIAL_TRANSFER=1.
        await self.mem.fill(lo, [SENT] * nwords)
        m = self.tap.mark()
        await self._go(hs=1, initial=1)
        st = await self._wait(lambda s: bool(s.done or s.error), "DONE or ERROR after HS initial")
        ec = await self._ec()
        beats = self._beats("H.initial", self.tap.since(m))
        self._ctrl(
            "H.initial",
            bool(st.error) and ec == OPC_ERR and not beats,
            f"{st.fmt()} error_code=0x{ec:x} writes={len(beats)}",
        )
        await ops.wr(CONTROL, 0)
        await self._idle()
        await ops.wr(HANDSHAKE_INTR_ENABLE, HS_RESET)
        await ops.wr(SPI_CONTROL, spi_ctrl)

    # ---- Leg L: continuation after the range is narrowed and locked ------
    async def _leg_lock(self, base: int) -> None:
        ops = self.ops
        size = 128
        chunk = 64
        wide_limit = base + size - 1
        narrow_limit = base + chunk - 1
        lo = base - GUARD
        nwords = (GUARD + size + GUARD) // 4
        await ops.program_range(base, wide_limit, valid=True)
        await self.mem.fill(lo, [SENT] * nwords)
        await ops.program_transfer(src=0, dst=base, total=size, chunk=chunk, width_enc=2)
        await self._chunk1("L", chunk)

        # Narrow the window to chunk 1 and lock it.
        await ops.program_range(base, narrow_limit, valid=True)
        await ops.wr(RANGE_REGWEN, REGWEN_FALSE << REGWEN_LSB)
        regwen = (await ops.rd(RANGE_REGWEN) & REGWEN_MASK) >> REGWEN_LSB
        await ops.wr(RANGE_LIMIT, wide_limit)
        limit_rb = await ops.rd(RANGE_LIMIT)
        self._ctrl(
            "L.lock",
            regwen != REGWEN_TRUE and limit_rb == narrow_limit,
            f"regwen=0x{regwen:x} limit_readback=0x{limit_rb:08x} expect=0x{narrow_limit:08x}",
        )

        # Continuation: GO=1, INITIAL_TRANSFER=0.
        m = self.tap.mark()
        await self._go(initial=0)
        st = await self._wait(lambda s: bool(s.done or s.error), "DONE or ERROR after GO-only")
        ec = await self._ec()
        await ClockCycles(cocotb.top.clk_i, 50)
        beats = self._beats("L.cont", self.tap.since(m))
        out = sorted(a for a in self._bytes_written(beats) if not base <= a <= narrow_limit)
        img = await self.mem.read(lo, nwords)
        zero_outside = [
            f"0x{lo + 4 * i:08x}"
            for i, v in enumerate(img)
            if v == 0 and not base <= lo + 4 * i <= narrow_limit
        ]
        self._check(
            "CHK-DMA-ZERO-CONT-LOCK",
            not out and not zero_outside and bool(st.error) and ec == DST_ERR,
            f"base=0x{base:08x} limit=0x{narrow_limit:08x} {st.fmt()} error_code=0x{ec:x} "
            f"expect_error_code=0x{DST_ERR:x} writes={len(beats)} bytes_outside={len(out)} "
            f"first_outside={f'0x{out[0]:08x}' if out else 'none'} "
            f"last_outside={f'0x{out[-1]:08x}' if out else 'none'} "
            f"words_zeroed_outside={len(zero_outside)}",
        )
        await self._idle()

        # Control: a new fill with INITIAL_TRANSFER=1 stops at the locked LIMIT.
        await self.mem.fill(lo, [SENT] * nwords)
        await ops.program_transfer(src=0, dst=base, total=size, chunk=size, width_enc=2)
        m = self.tap.mark()
        await self._go(initial=1)
        st = await self._wait(lambda s: bool(s.done or s.error), "DONE or ERROR after initial")
        ec = await self._ec()
        beats = self._beats("L.initial", self.tap.since(m))
        last = max(self._bytes_written(beats), default=0)
        self._ctrl(
            "L.initial",
            bool(st.error) and ec == DST_ERR and len(beats) == chunk // 4 and last == narrow_limit,
            f"{st.fmt()} error_code=0x{ec:x} writes={len(beats)} last_byte=0x{last:08x}",
        )
        await self._idle()
