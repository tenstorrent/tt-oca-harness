# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SPI host COMMAND speed and direction cells give the stated sck count, Rx words and errors.

Contract (``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc``,
COMMAND and ERROR_STATUS; ``hw/sys/sep/doc/spi.adoc``, Features):

* SPEED 0, 1 and 2 move LEN+1 bytes on 1, 2 and 4 data lines at one bit per
  line per sck cycle, so a data segment takes (LEN+1)*8/lanes sck cycles. A
  dummy segment (DIRECTION 0) takes LEN+1 sck cycles and moves no data.
* CSAAT=1 keeps chip select low into the next segment.
* SPEED 3, and DIRECTION 3 at SPEED 1 or 2, set ERROR_STATUS.CMDINVAL.

The leaf walks the 10 legal SPEED x DIRECTION cells as single segments, a dummy
segment between FIFO reads, CSAAT chains that change speed or direction, the
seed-drawn long dummy segment and the 6 illegal cells. A test-side sampler
(``env/sep_spi_pad_sampler.py``) reads ``spi_sck_o`` and ``spi_cs_n_o`` on each
core clock and counts one sck cycle at each leading edge while chip select is
low. ``OcahSpiFlash`` drives ``spi_miso_i`` with the drawn responder stream; the
bits it returns are not graded.

Checks:

* CHK-SPI-CELL: per legal cell, the sck count of the one chip-select-low window
  equals the stated count, and ERROR_STATUS reads 0 after the segment.
* CHK-SPI-RXCNT: for DIRECTION 1 and 3 with LEN+1 a multiple of 4, the RXDATA
  words read and RXQD agree and equal (LEN+1)/4. Control: every Tx-only and
  dummy cell starts with RXEMPTY=1 and leaves RXQD at 0.
* CHK-SPI-DUMMY: a dummy segment leaves TXQD and RXQD unchanged. Control: both
  are at least 1 before the segment.
* CHK-SPI-CHAIN: a CSAAT chain of 2 to 6 segments shows one chip-select-low
  window, its sck count is the sum of the segment counts, and chip select is
  high at the end. Control: two back-to-back CSAAT=0 dummy commands show a
  chip-select rise between them.
* CHK-SPI-ILLEGAL: each of the 5 graded illegal cells sets ERROR_STATUS to
  CMDINVAL only, and a legal control command after the SPI clean state reads
  ERROR_STATUS 0. SPEED 3 with DIRECTION 2 runs as the control
  ``CTL-SPI-ILLEGAL LOG`` and prints no CHK line. The illegal COMMAND is written
  with the core held (CONTROL.SPIEN=0), so the reserved cell never runs on the
  pads, and the SW_RST of the SPI clean state empties the command queue.
* CHK-SPI-LONGDUMMY: on a seed that draws it (1 in 4), LEN 0xFFFFF at CLKDIV 0
  gives 1,048,576 sck cycles. Other seeds do not run it.

Graded window: owner code of this test around each graded segment; closed for
bring-up, the SPI clean state, the SW_RST helper and every control leg.

Run mode: ``no_cpu``, ``lsu_stub_all_live``, ``+skip_fuse_sense``, no ``rst_ni``
pulse. Every random value is a pure function of the seed (``SepSeededRng``).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cocotb
import pyuvm
from env.sep_fcov_gate import close_graded_window, fcov_present, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_pad_sampler import SepSpiPadSampler
from ocah_spi_vip import OcahSpiFlash, OcahSpiFlashError
from sep_base_test import sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    COMMAND,
    CONTROL,
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
    CTRL_SPIEN,
    CTRL_SW_RST,
    ERR_CMDINVAL,
    ERR_STATUS_MASK,
    ERROR_STATUS,
    INTR_STATE,
    INTR_STATE_MASK,
    RXDATA,
    TXDATA,
)
from seq_lib.sep_spi_host_ops import (
    DIR_BIDIR,
    DIR_DUMMY,
    DIR_RX,
    DIR_TX,
    SepSpiHostOps,
    command_word,
    configopts_word,
)

TEST = "sep_spi_pad_speed_dir_matrix_test"

LANES = {0: 1, 1: 2, 2: 4}
LEGAL = [(s, d) for s in (0, 1, 2) for d in (0, 1, 2, 3) if not (d == DIR_BIDIR and s != 0)]
ILLEGAL = [(3, 0), (3, 1), (3, 2), (3, 3), (1, 3), (2, 3)]
CONTROL_ILLEGAL = (3, 2)

LEN_CLASSES = ("len0", "sub_word", "word_multiple", "non_multiple")
LEN_WEIGHTS = (3, 1, 3, 2)
CLKDIV_CLASSES = {"zero": (0, 0), "small": (1, 3), "mid": (4, 7)}

LONG_DUMMY_LEN = 0xFFFFF
LONG_DUMMY_CYCLES = LONG_DUMMY_LEN + 1
N_CHAINS = 2
RESPONDER_BYTES = 256
# The responder streams its memory for this opcode (READ, no address bytes).
RESPONDER_READ = 0x03

# Bounds. Each expiry fails the check that the wait feeds.
SERVICE_READS = 50_000
SEG_BOUND_CLKS = 400_000
LONG_BOUND_CLKS = 2 * LONG_DUMMY_CYCLES + 100_000
ERR_POLLS = 200


def sck_expect(speed: int, direction: int, len_field: int) -> int:
    """The stated sck cycle count of one segment."""
    if direction == DIR_DUMMY:
        return len_field + 1
    return (len_field + 1) * 8 // LANES[speed]


@dataclass
class Seg:
    speed: int
    direction: int
    len_field: int
    csaat: int = 0
    len_class: str = ""
    tx_words: list[int] = field(default_factory=list)

    @property
    def cmd(self) -> int:
        return command_word(
            self.len_field, speed=self.speed, direction=self.direction, csaat=self.csaat
        )

    @property
    def is_rx(self) -> bool:
        return self.direction in (DIR_RX, DIR_BIDIR)

    @property
    def is_tx(self) -> bool:
        return self.direction in (DIR_TX, DIR_BIDIR)

    @property
    def expect(self) -> int:
        return sck_expect(self.speed, self.direction, self.len_field)

    def fmt(self) -> str:
        return f"s{self.speed}d{self.direction}L{self.len_field}c{self.csaat}"


class _RxResponder(OcahSpiFlash):
    """``OcahSpiFlash`` that streams its memory on every frame that starts with READ.

    A frame shorter than the opcode byte (a short dummy segment, a quad segment
    of one byte) ends quietly: it is recorded as a short frame.
    """

    async def _handle_transaction(self) -> None:
        try:
            await super()._handle_transaction()
        except OcahSpiFlashError:
            self._log_transaction(0, 0, b"", b"", ok=False, reason="short_frame")


async def _absorb(opcode, addr, payload):
    """Frame of any opcode other than READ: take the bytes, return nothing."""
    return None


@pyuvm.test()
class sep_spi_pad_speed_dir_matrix_test(sep_base_test):
    """Every legal cell gives the stated sck count; every illegal cell sets CMDINVAL."""

    # ---- plan -------------------------------------------------------------
    def _draw_len(self, rng: SepSeededRng, cls: str, dummy: bool) -> int:
        if cls == "len0":
            return 0
        if cls == "sub_word":
            return 1
        if cls == "word_multiple":
            return rng.choice((3, 15, 31, 0x3FF) if dummy else (3, 15, 31))
        pick = rng.randrange(4)
        if pick < 3:
            return (4, 16, 32)[pick]
        return rng.choice([v for v in range(2, 64) if (v + 1) % 4])

    def _draw_class(self, rng: SepSeededRng) -> str:
        roll = rng.randrange(sum(LEN_WEIGHTS))
        for cls, w in zip(LEN_CLASSES, LEN_WEIGHTS):
            if roll < w:
                return cls
            roll -= w
        raise AssertionError("unreachable")

    def _draw_clkdiv(self, rng: SepSeededRng) -> tuple[str, int]:
        cls = rng.choice(tuple(CLKDIV_CLASSES))
        lo, hi = CLKDIV_CLASSES[cls]
        return cls, rng.randrange(lo, hi + 1)

    def _tx_words(self, rng: SepSeededRng, seg: Seg) -> list[int]:
        if not seg.is_tx:
            return []
        n = (seg.len_field + 1 + 3) // 4
        words = [rng.getrandbits(32) for _ in range(n)]
        if seg.direction == DIR_BIDIR and words:
            # First byte on the pad is the READ opcode, so the responder answers
            # with its stream inside the same segment.
            words[0] = (words[0] & ~0xFF) | RESPONDER_READ
        return words

    def _plan(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        order = LEGAL + ILLEGAL
        rng.shuffle(order)
        self.legal_order = [c for c in order if c in LEGAL]
        self.illegal_order = [c for c in order if c in ILLEGAL]

        classes = {c: self._draw_class(rng) for c in self.legal_order}
        # DIRECTION 3 is legal only at SPEED 0, so that one cell is word_multiple.
        classes[(0, DIR_BIDIR)] = "word_multiple"
        rx1 = [c for c in self.legal_order if c[1] == DIR_RX]
        if not any(classes[c] == "word_multiple" for c in rx1):
            classes[rng.choice(rx1)] = "word_multiple"

        self.cells: list[tuple[Seg, str, int]] = []
        for speed, direction in self.legal_order:
            cls = classes[(speed, direction)]
            seg = Seg(speed, direction, 0, 0, cls)
            seg.len_field = self._draw_len(rng, cls, direction == DIR_DUMMY)
            ck_cls, clkdiv = self._draw_clkdiv(rng)
            seg.tx_words = self._tx_words(rng, seg)
            self.cells.append((seg, ck_cls, clkdiv))

        dcls = self._draw_class(rng)
        self.dummy_seg = Seg(rng.randrange(3), DIR_DUMMY, 0, 0, dcls)
        self.dummy_seg.len_field = self._draw_len(rng, dcls, True)
        self.fifo_tx_word = rng.getrandbits(32)

        self.chain_ctl_lens = (rng.randrange(16), rng.randrange(16))
        self.chains: list[tuple[int, list[Seg]]] = []
        for _ in range(N_CHAINS):
            _, clkdiv = self._draw_clkdiv(rng)
            nseg = rng.randrange(2, 7)
            cells: list[tuple[int, int]] = [rng.choice(LEGAL) for _ in range(nseg)]
            if all(c == cells[0] for c in cells):
                cells[-1] = rng.choice([c for c in LEGAL if c != cells[0]])
            segs = []
            for i, (speed, direction) in enumerate(cells):
                if direction == DIR_DUMMY:
                    cls = self._draw_class(rng)
                    ln = self._draw_len(rng, cls, True)
                else:
                    cls = "word_multiple"
                    ln = 4 * rng.randrange(1, 17) - 1
                seg = Seg(speed, direction, ln, int(i < nseg - 1), cls)
                seg.tx_words = self._tx_words(rng, seg)
                segs.append(seg)
            self.chains.append((clkdiv, segs))

        self.long_dummy = int(rng.randrange(4) == 0)
        self.illegal_lens = {c: rng.randrange(64) for c in self.illegal_order}
        self.illegal_ctl_lens = {c: rng.randrange(16) for c in self.illegal_order}
        self.responder = bytes(rng.getrandbits(8) for _ in range(RESPONDER_BYTES))

        cell_txt = " ".join(
            f"s{s.speed}d{s.direction}:{s.len_class}/L{s.len_field}/{ck}{cd}"
            for s, ck, cd in self.cells
        )
        chain_txt = " ".join(
            f"[clkdiv={cd} " + ",".join(s.fmt() for s in segs) + "]" for cd, segs in self.chains
        )
        csaat_dirs = [[s.direction for s in segs if s.csaat] for _, segs in self.chains]
        self.logger.info(
            "PLAN seed=%d cells=%s illegal=%s dummy_leg=s%dd0:%s/L%d chains=%s "
            "chain_csaat1_dirs=%s long_dummy=%d",
            seed,
            cell_txt,
            ",".join(f"s{s}d{d}" for s, d in self.illegal_order),
            self.dummy_seg.speed,
            self.dummy_seg.len_class,
            self.dummy_seg.len_field,
            chain_txt,
            csaat_dirs,
            self.long_dummy,
        )
        self.logger.info(
            "DRAW seed=%d chain_ctl_lens=%s illegal_lens=%s illegal_ctl_lens=%s "
            "responder_head=%s fifo_tx_word=0x%08x",
            seed,
            self.chain_ctl_lens,
            [self.illegal_lens[c] for c in self.illegal_order],
            [self.illegal_ctl_lens[c] for c in self.illegal_order],
            self.responder[:16].hex(),
            self.fifo_tx_word,
        )

    # ---- helpers ----------------------------------------------------------
    def _graded(self) -> None:
        open_graded_window(TEST, self.logger)

    def _ungraded(self) -> None:
        close_graded_window(self.logger)

    async def _sw_rst(self) -> None:
        self._ungraded()
        await self.ops.sw_rst()

    async def _clean_state(self) -> None:
        self._ungraded()
        await self.ops.clean_state()

    async def _err_status(self) -> int:
        return int(await self.ops.rd(ERROR_STATUS)) & 0xFFFF_FFFF

    async def _configopts(self, clkdiv: int) -> None:
        assert not self.pads.cs_low(), "CONFIGOPTS write with chip select low"
        await self.ops.write_configopts(configopts_word(clkdiv=clkdiv))

    async def _run_segments(self, segs: list[Seg], *, tag: str) -> dict:
        """Write each COMMAND after a READY=1 read, service TX and RX, wait until done.

        TX words of a segment go out after its COMMAND, each after a STATUS read
        with TXFULL=0. One RXDATA word is read after each STATUS read with
        RXFULL=1. Done: every chip-select-low window since the first COMMAND is
        closed, and a STATUS read taken after the last chip-select rise shows
        ACTIVE=0 and CMDQD=0.
        """
        ops, pads = self.ops, self.pads
        mark = pads.mark()
        pending: deque[int] = deque()
        idx = 0
        rx_read = 0
        pre = None
        any_rx = any(s.is_rx for s in segs)
        for _ in range(SERVICE_READS):
            st = await ops.read_status()
            if idx < len(segs) and st.ready:
                if idx == 0:
                    pre = st
                await ops.wr(COMMAND, segs[idx].cmd)
                pending.extend(segs[idx].tx_words)
                idx += 1
                continue
            if pending and not st.txfull:
                await ops.wr(TXDATA, pending.popleft())
                continue
            if any_rx and st.rxfull:
                await ops.rd(RXDATA)
                rx_read += 1
                continue
            if idx < len(segs) or pending:
                continue
            wins = pads.windows_since(mark, complete_only=False)
            if not wins:
                if not any_rx:
                    await pads.wait_windows(1, mark, SEG_BOUND_CLKS)
                continue
            if not wins[-1].complete:
                if not any_rx:
                    n_done = sum(1 for w in wins if w.complete)
                    await pads.wait_windows(n_done + 1, mark, SEG_BOUND_CLKS)
                continue
            if st.clk0 is not None and st.clk0 >= wins[-1].end and not st.active and not st.cmdqd:
                return {"wins": wins, "rx_read": rx_read, "pre": pre, "done": st}
        raise AssertionError(
            f"{tag} FAIL: segment not done after {SERVICE_READS} STATUS reads "
            f"(commands {idx}/{len(segs)}, tx pending {len(pending)}, "
            f"windows {len(pads.windows_since(mark, complete_only=False))})"
        )

    # ---- legs -------------------------------------------------------------
    async def _single_cells(self) -> None:
        seed = self.seed
        rx_rows = []
        nonrx_rxqd: list[int] = []
        for seg, ck_cls, clkdiv in self.cells:
            self._ungraded()
            await self._configopts(clkdiv)
            self._graded()
            res = await self._run_segments([seg], tag="CHK-SPI-CELL")
            wins = res["wins"]
            pre = res["pre"]
            if seg.direction in (DIR_DUMMY, DIR_TX) and not pre.rxempty:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-RXCNT: RXEMPTY=0 before the "
                    f"s{seg.speed}d{seg.direction} COMMAND ({pre.fmt()})"
                )
            st = await self.ops.read_status()
            rxqd = st.rxqd
            drained = len(await self.ops.drain_rx())
            got = sum(w.leading_edges for w in wins)
            exp = seg.expect
            err = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            line = (
                f"seed={seed} speed={seg.speed} dir={seg.direction} len={seg.len_field} "
                f"csaat={seg.csaat} clkdiv={clkdiv} sck_cycles={got} expect={exp} "
                f"err_status=0x{err.got & err.mask:02x} err_mask=0x{err.mask:02x} "
                f"windows={len(wins)} len_class={seg.len_class} clkdiv_class={ck_cls}"
            )
            if len(wins) != 1 or got != exp or not err.ok:
                raise AssertionError(f"CHK-SPI-CELL FAIL {line}")
            self.logger.info("CHK-SPI-CELL PASS %s", line)

            if seg.is_rx:
                rx_rows.append((seg, res["rx_read"], rxqd, drained))
            else:
                nonrx_rxqd.append(rxqd)
                if rxqd or drained:
                    raise AssertionError(
                        f"CHK-SPI-RXCNT FAIL seed={seed} control: s{seg.speed}d{seg.direction} "
                        f"started with RXEMPTY=1 and left rxqd={rxqd} drained={drained}"
                    )
            await self._sw_rst()

        graded = [r for r in rx_rows if (r[0].len_field + 1) % 4 == 0]
        dirs = {r[0].direction for r in graded}
        if DIR_RX not in dirs or DIR_BIDIR not in dirs or not nonrx_rxqd:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} CHK-SPI-RXCNT: graded Rx directions {sorted(dirs)}, "
                f"non-Rx controls {len(nonrx_rxqd)}"
            )
        for seg, in_seg, rxqd, drained in rx_rows:
            nbytes = seg.len_field + 1
            words = in_seg + drained
            row = (
                f"seed={seed} speed={seg.speed} dir={seg.direction} bytes={nbytes} "
                f"words={words} rxqd={rxqd} in_segment={in_seg} drained={drained}"
            )
            if nbytes % 4:
                self.logger.info("OBS-SPI-RXCNT %s graded=0", row)
                continue
            exp = nbytes // 4
            line = f"{row} expect={exp} control_nonrx_rxqd={max(nonrx_rxqd)}"
            if drained != rxqd or words != exp or in_seg + rxqd != exp:
                raise AssertionError(f"CHK-SPI-RXCNT FAIL {line}")
            self.logger.info("CHK-SPI-RXCNT PASS %s", line)
        self.ran.update(("CHK-SPI-CELL", "CHK-SPI-RXCNT"))

    async def _dummy_fifo_leg(self) -> None:
        seed = self.seed
        await self._sw_rst()
        await self._configopts(0)
        await self.ops.push_tx(self.fifo_tx_word)
        rx = Seg(0, DIR_RX, 3)
        mark = self.pads.mark()
        await self.ops.issue_command(rx.cmd)
        await self.ops.wait_segment_done(self.pads, mark, bound_clks=SEG_BOUND_CLKS)
        before = await self.ops.read_status()
        if before.txqd < 1 or before.rxqd < 1:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} CHK-SPI-DUMMY: txqd={before.txqd} "
                f"rxqd={before.rxqd} before the dummy segment"
            )
        self.logger.info(
            "CTL-SPI-DUMMY LOG seed=%d txqd_before=%d rxqd_before=%d",
            seed,
            before.txqd,
            before.rxqd,
        )
        seg = self.dummy_seg
        self._graded()
        mark = self.pads.mark()
        await self.ops.issue_command(seg.cmd)
        wins = await self.ops.wait_segment_done(self.pads, mark, bound_clks=SEG_BOUND_CLKS)
        after = await self.ops.read_status()
        self._ungraded()
        got = sum(w.leading_edges for w in wins)
        line = (
            f"seed={seed} txqd_before={before.txqd} txqd_after={after.txqd} "
            f"rxqd_before={before.rxqd} rxqd_after={after.rxqd} speed={seg.speed} "
            f"len={seg.len_field} len_class={seg.len_class} sck_cycles={got} expect={seg.expect}"
        )
        if before.txqd != after.txqd or before.rxqd != after.rxqd:
            raise AssertionError(f"CHK-SPI-DUMMY FAIL {line}")
        self.logger.info("CHK-SPI-DUMMY PASS %s", line)
        self.ran.add("CHK-SPI-DUMMY")
        await self.ops.drain_rx()
        await self._sw_rst()

    async def _chain_leg(self) -> None:
        seed = self.seed
        ops, pads = self.ops, self.pads
        self._ungraded()
        await self._configopts(0)
        mark = pads.mark()
        for ln in self.chain_ctl_lens:
            await ops.issue_command(Seg(0, DIR_DUMMY, ln).cmd)
        wins = await ops.wait_segment_done(pads, mark, windows=2, bound_clks=SEG_BOUND_CLKS)
        gaps = pads.gaps_since(mark)
        rise = int(len(wins) >= 2 and bool(gaps) and gaps[0] > 0)
        if not rise:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} CHK-SPI-CHAIN: no chip-select rise between two "
                f"CSAAT=0 commands (windows={[w.fmt() for w in wins]} gaps={gaps})"
            )
        self.logger.info(
            "CTL-SPI-CHAIN LOG seed=%d control_cs_rise_between_csaat0=1 gap_clks=%d",
            seed,
            gaps[0],
        )

        for clkdiv, segs in self.chains:
            changes = sum(
                1
                for a, b in zip(segs, segs[1:])
                if (a.speed, a.direction) != (b.speed, b.direction)
            )
            if len(segs) < 2 or changes < 1:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-CHAIN: segs={len(segs)} changes={changes}"
                )
            self._ungraded()
            await self._configopts(clkdiv)
            self._graded()
            res = await self._run_segments(segs, tag="CHK-SPI-CHAIN")
            self._ungraded()
            wins = res["wins"]
            drained = len(await ops.drain_rx())
            got = sum(w.leading_edges for w in wins)
            exp = sum(s.expect for s in segs)
            cs_high_after = int(not pads.cs_low())
            err = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            line = (
                f"seed={seed} segs={len(segs)} sck_cycles_in_chain={got} expect={exp} "
                f"cs_dropped_mid={len(wins) - 1} cs_high_after={cs_high_after} "
                f"control_cs_rise_between_csaat0={rise} clkdiv={clkdiv} changes={changes} "
                f"chain={','.join(s.fmt() for s in segs)} rx_words={res['rx_read'] + drained} "
                f"err_status=0x{err.got & err.mask:02x} err_mask=0x{err.mask:02x}"
            )
            if len(wins) != 1 or got != exp or not cs_high_after or not err.ok:
                raise AssertionError(f"CHK-SPI-CHAIN FAIL {line}")
            self.logger.info("CHK-SPI-CHAIN PASS %s", line)
            await self._sw_rst()
        self.ran.add("CHK-SPI-CHAIN")

    async def _long_dummy_leg(self) -> None:
        seed = self.seed
        self._ungraded()
        await self._configopts(0)
        self._graded()
        mark = self.pads.mark()
        await self.ops.issue_command(Seg(0, DIR_DUMMY, LONG_DUMMY_LEN).cmd)
        wins = await self.ops.wait_segment_done(self.pads, mark, bound_clks=LONG_BOUND_CLKS)
        self._ungraded()
        got = sum(w.leading_edges for w in wins)
        line = f"seed={seed} cycles={got} expect={LONG_DUMMY_CYCLES} windows={len(wins)}"
        if len(wins) != 1 or got != LONG_DUMMY_CYCLES:
            raise AssertionError(f"CHK-SPI-LONGDUMMY FAIL {line}")
        self.logger.info("CHK-SPI-LONGDUMMY PASS %s", line)
        self.ran.add("CHK-SPI-LONGDUMMY")
        await self._sw_rst()

    async def _illegal_leg(self) -> None:
        seed = self.seed
        await self._configopts(0)
        for speed, direction in self.illegal_order:
            control = (speed, direction) == CONTROL_ILLEGAL
            await self._clean_state()
            # The core is held (SPIEN=0) while the illegal COMMAND is written, so
            # the reserved cell is refused at the register interface and never
            # runs on the pads. The SW_RST of the next clean state empties the
            # command queue before the core is enabled again.
            await self.ops.wr(CONTROL, self.ctrl & ~CTRL_SPIEN)
            await self.ops.wait_ready()
            # Control: a legal COMMAND written with SPIEN=0 raises no error, so
            # the CMDINVAL below comes from the cell and not from SPIEN=0.
            await self.ops.wr(COMMAND, Seg(0, DIR_DUMMY, 0).cmd)
            pre = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            if not pre.ok:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-ILLEGAL: legal COMMAND with SPIEN=0 "
                    f"gave err_status=0x{pre.got:02x}"
                )
            await self.ops.wait_ready()
            if not control:
                self._graded()
            await self.ops.wr(
                COMMAND,
                command_word(
                    self.illegal_lens[(speed, direction)], speed=speed, direction=direction
                ),
            )
            err_v = 0
            for _ in range(ERR_POLLS):
                err_v = await self._err_status()
                if err_v & ERR_CMDINVAL:
                    break
            self._ungraded()
            err = field_compare(err_v, ERR_CMDINVAL, ERR_STATUS_MASK)
            if control:
                line = (
                    f"seed={seed} speed={speed} dir={direction} "
                    f"err_status=0x{err.got & err.mask:02x} err_mask=0x{err.mask:02x}"
                )
                if not err.ok:
                    raise AssertionError(f"CTL-SPI-ILLEGAL FAIL {line}")
                self.logger.info("CTL-SPI-ILLEGAL LOG %s", line)
            # Legal control command after the SPI clean state.
            await self._clean_state()
            await self.ops.wr(CONTROL, self.ctrl)
            flushed = await self.ops.read_status()
            if flushed.cmdqd or flushed.active:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} CHK-SPI-ILLEGAL: command queue not empty "
                    f"after the SPI clean state ({flushed.fmt()})"
                )
            mark = self.pads.mark()
            await self.ops.issue_command(
                Seg(0, DIR_DUMMY, self.illegal_ctl_lens[(speed, direction)]).cmd
            )
            await self.ops.wait_segment_done(self.pads, mark, bound_clks=SEG_BOUND_CLKS)
            ctl = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            if control:
                if not ctl.ok:
                    raise AssertionError(
                        f"CTL-SPI-ILLEGAL FAIL seed={seed} control_err_status=0x{ctl.got:02x}"
                    )
                continue
            line = (
                f"seed={seed} speed={speed} dir={direction} "
                f"err_status=0x{err.got & err.mask:02x} "
                f"control_err_status=0x{ctl.got & ctl.mask:02x} "
                f"spien0_legal_err_status=0x{pre.got & pre.mask:02x} err_mask=0x{err.mask:02x} "
                f"len={self.illegal_lens[(speed, direction)]}"
            )
            if not err.ok or not ctl.ok:
                raise AssertionError(f"CHK-SPI-ILLEGAL FAIL {line}")
            self.logger.info("CHK-SPI-ILLEGAL PASS %s", line)
        self.ran.add("CHK-SPI-ILLEGAL")
        await self._clean_state()

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self._plan(self.seed)
        required = ["CHK-SPI-CELL", "CHK-SPI-RXCNT", "CHK-SPI-DUMMY", "CHK-SPI-CHAIN"]
        required.append("CHK-SPI-ILLEGAL")
        if self.long_dummy:
            required.append("CHK-SPI-LONGDUMMY")
        self.required_evidence = tuple(required)
        self.ran: set[str] = set()
        close_graded_window()

        dut = cocotb.top
        flash = _RxResponder(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            addr_bytes=0,
            name="sep_spi_rx_responder",
        )
        flash.preload(self.responder)
        for op in range(256):
            if op != RESPONDER_READ:
                flash.register_command_callback(op, _absorb)
        await flash.start()
        try:
            await self.bring_up_no_cpu()
            self.suppress_host_axi_transaction_info()
            self.pads = SepSpiPadSampler(keep_edges=False)
            self.pads.set_idle_level(0)
            self.pads.start()
            self.ops = SepSpiHostOps(self, clock=self.pads.now)

            ctrl = (CTRL_RESET & ~CTRL_SW_RST) | CTRL_SPIEN | CTRL_OUTPUT_EN
            self.ctrl = ctrl
            await self.ops.wr(CONTROL, ctrl)
            await self.ops.wr(CSID, 0)
            err0 = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            intr0 = field_compare(int(await self.ops.rd(INTR_STATE)), 0, INTR_STATE_MASK)
            if not err0.ok or not intr0.ok:
                raise AssertionError(
                    f"CTL-SPI-BRINGUP FAIL seed={self.seed} error_status {err0.fields()} "
                    f"intr_state {intr0.fields()}"
                )
            self.logger.info(
                "CTL-SPI-BRINGUP LOG seed=%d control=0x%08x error_status=0x%02x "
                "intr_state=0x%x fcov=%d",
                self.seed,
                ctrl,
                err0.got & err0.mask,
                intr0.got & intr0.mask,
                int(fcov_present()),
            )

            await self._single_cells()
            await self._dummy_fifo_leg()
            await self._chain_leg()
            if self.long_dummy:
                await self._long_dummy_leg()
            else:
                self.logger.info("OBS-SPI-LONGDUMMY seed=%d long_dummy=0 graded=0", self.seed)
            await self._illegal_leg()
            self._ungraded()
            await self.pads.stop()
        finally:
            close_graded_window()
            await flash.stop()

        frames = flash.get_transactions()
        self.logger.info(
            "OBS-SPI-RESPONDER seed=%d frames=%d read_frames=%d bytes_out=%d",
            self.seed,
            len(frames),
            sum(1 for f in frames if f["opcode"] == RESPONDER_READ and f["ok"]),
            sum(len(f["data_out"]) for f in frames),
        )
        missing = [c for c in self.required_evidence if c not in self.ran]
        if missing:
            raise AssertionError(f"CTRL-MISSING seed={self.seed} checks not run: {missing}")
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, len(self.ran))
