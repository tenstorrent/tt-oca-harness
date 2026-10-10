# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI host FIFO stalls, watermarks, queue depths and full/empty flags in STATUS.

RANDOMIZED. Drives the SPI host registers over the CPU-LSU splice and samples
the pad ports ``spi_sck_o`` and ``spi_cs_n_o`` on each core clock
(``env/sep_spi_pad_sampler.py``). No responder is attached: ``spi_miso_i``
stays at its testbench default and the Rx bit content is not graded. The
contract is the CONTROL and STATUS registers of
``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc``.

The TX and RX FIFO depths are found at run time from STATUS and size the
stimulus only; no depth is compared with a value.

Checkers:
  CHK-SPI-TXSTALL  An active Tx segment that waits for TX data shows TXSTALL=1
                   and no sck edge in a stall window of 8 sck periods. After the
                   rest of the words arrive TXSTALL reads 0 and the segment ends
                   with 4*m*8/lanes sck cycles. Control: the same segment with
                   every word written first reads TXSTALL=0 in each STATUS read
                   taken while chip select is low, and at least one such read
                   exists.
  CHK-SPI-RXSTALL  An Rx segment of 1032 bytes with no RXDATA read reaches
                   RXFULL=1 and RXSTALL=1; no sck edge appears in the stall
                   window and RXQD does not move. The drain then delivers all
                   258 words and the segment ends. Control: sck toggles before
                   RXFULL.
  CHK-SPI-WM       TXWM reads 0 at TX_WATERMARK 0 and 1 at the TX depth plus 1,
                   at each occupancy up to the full FIFO. RXWM equals
                   (RXQD > RX_WATERMARK) one below and one above RX_WATERMARK
                   0, 1 and a drawn mid value, and reads 0 when a drain takes
                   RXQD to RX_WATERMARK minus 1. Control: TX_WATERMARK 1 with
                   TXQD 0 gives TXWM=1. The TX cells at watermark 1, a mid value
                   and the TX depth are logged with OBS-SPI-WM only.
  CHK-SPI-QD       With ACTIVE=0 each RXDATA read lowers RXQD by 1. TXFULL is
                   set with ACTIVE=1 during a Tx segment of twice the TX depth
                   in words, and that segment ends with every sck cycle. An Rx
                   segment of exactly the RX depth sets RXFULL; one more 4-byte
                   segment does not raise RXQD above the depth and the drain
                   reads depth plus 1 words. TXFULL/TXEMPTY and RXFULL/RXEMPTY
                   are never set together in any STATUS read; each of the four
                   flags is set in at least one read (control).
  CHK-SPI-CMDQD    CMDQD rises by 1 per COMMAND accepted while the head segment
                   waits for TX data; after one TXDATA word releases it, every
                   queued command shows one chip-select-low window and the
                   queue empties. Control: the head is held (ACTIVE=1,
                   TXSTALL=1) and at least one COMMAND is accepted.

Not graded: TXQD and RXQD at idle (logged with OBS-SPI-QD), TXQD and RXQD while
ACTIVE=1, RXWM at RXQD equal to RX_WATERMARK, RX_WATERMARK 0x7F against the
reset value, the RXDATA values, overflow and underflow.

Run mode: no_cpu (target ``lsu_stub_all_live``), ``+skip_fuse_sense``, no
``rst_ni`` pulse. Every draw comes from ``SepSeededRng`` and the run seed.
"""

from __future__ import annotations

from collections.abc import Callable

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_pad_sampler import SepSpiPadSampler
from sep_base_test import sep_base_test
from sep_reg_meta import SPI_CONTROLLER
from seq_lib.sep_spi_host_csr_seq import (
    COMMAND,
    CONTROL,
    CTRL_OUTPUT_EN,
    CTRL_RX_WM,
    CTRL_SPIEN,
    CTRL_TX_WM,
    RXDATA,
    TXDATA,
)
from seq_lib.sep_spi_host_ops import (
    DIR_DUMMY,
    DIR_RX,
    DIR_TX,
    SepSpiHostOps,
    SpiStatus,
    command_word,
    configopts_word,
)

TEST = "sep_spi_fifo_stall_watermark_rand_test"

_R = SPI_CONTROLLER
# Bits per sck cycle at COMMAND.SPEED 0, 1, 2 (spi_controller.adoc, COMMAND).
LANES = {0: 1, 1: 2, 2: 4}
# The stall window, in sck periods (a test parameter).
STALL_PERIODS = 8
# The RX stall segment: more words than the 8-bit RXQD counts.
RX_STALL_BYTES = 1032
RX_STALL_WORDS = RX_STALL_BYTES // 4
# The largest value of the 8-bit queue-depth fields and of TX_WATERMARK.
QD_MAX = _R.field_mask("STATUS", "rxqd") >> _R.field_lsb("STATUS", "rxqd")
TX_WM_MAX = CTRL_TX_WM >> _R.field_lsb("CONTROL", "tx_watermark")
TX_WM_LSB = _R.field_lsb("CONTROL", "tx_watermark")
RX_WM_LSB = _R.field_lsb("CONTROL", "rx_watermark")
ST_TXWM = _R.field_mask("STATUS", "txwm")
ST_RXWM = _R.field_mask("STATUS", "rxwm")
ST_TXSTALL = _R.field_mask("STATUS", "txstall")
ST_RXSTALL = _R.field_mask("STATUS", "rxstall")
ST_RXFULL = _R.field_mask("STATUS", "rxfull")
# The CLKDIV of the TX-full-while-active leg.
TXFULL_CLKDIV = 3
PAYLOAD_POOL = 512


class _CtrlMissing(AssertionError):
    pass


@pyuvm.test()
class sep_spi_fifo_stall_watermark_rand_test(sep_base_test):
    """TX/RX stalls, TX/RX watermarks, RXQD per read, CMDQD and FIFO flags of the SPI host."""

    required_evidence = (
        "CHK-SPI-TXSTALL",
        "CHK-SPI-RXSTALL",
        "CHK-SPI-WM",
        "CHK-SPI-QD",
        "CHK-SPI-CMDQD",
    )

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def _gate(self, graded: bool) -> None:
        if graded:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    def _fail(self, chk: str, msg: str) -> None:
        line = f"{chk} FAIL seed={self.seed} {msg}"
        self.logger.error(line)
        raise AssertionError(line)

    def _ctrl_missing(self, chk: str, msg: str) -> None:
        line = f"CTRL-MISSING {chk} seed={self.seed} {msg}"
        self.logger.error(line)
        raise _CtrlMissing(line)

    def _word(self) -> int:
        w = self.payload[self._pi % PAYLOAD_POOL]
        self._pi += 1
        return w

    def _period(self) -> int:
        """Core clocks per sck period at the current CLKDIV (CPOL=0, FULLCYC=0)."""
        return 2 * (self.clkdiv_now + 1)

    def _stall_win(self) -> int:
        return STALL_PERIODS * self._period()

    def _seg_bound(self, nbytes: int, speed: int) -> int:
        """Clock bound of one segment: four times its sck time plus a fixed margin."""
        return 4 * (nbytes * 8 // LANES[speed]) * self._period() + 20_000

    async def _clocks(self, n: int) -> None:
        if n > 0:
            await ClockCycles(cocotb.top.clk_i, n)

    async def _poll(
        self, pred: Callable[[SpiStatus], bool], bound_clks: int, what: str, chk: str
    ) -> SpiStatus:
        """Read STATUS until ``pred`` holds; fail ``chk`` after ``bound_clks`` clocks."""
        deadline = self.pads.now() + bound_clks
        st = None
        while True:
            st = await self.ops.read_status()
            if pred(st):
                return st
            if self.pads.now() > deadline:
                self._fail(chk, f"wait '{what}' expired after {bound_clks} clocks ({st.fmt()})")

    async def _write_control(self, *, tx_wm: int | None = None, rx_wm: int | None = None) -> None:
        """Write CONTROL with the named watermark changed and the other fields kept."""
        if tx_wm is not None:
            self.ctrl = (self.ctrl & ~CTRL_TX_WM) | (tx_wm << TX_WM_LSB)
        if rx_wm is not None:
            self.ctrl = (self.ctrl & ~CTRL_RX_WM) | (rx_wm << RX_WM_LSB)
        await self.ops.wr(CONTROL, self.ctrl)

    async def _set_clkdiv(self, clkdiv: int) -> None:
        await self.ops.write_configopts(configopts_word(clkdiv=clkdiv))
        self.clkdiv_now = clkdiv

    async def _clean(self) -> None:
        """SPI clean state, outside the graded window."""
        self._gate(False)
        await self.ops.clean_state()

    async def _sw_rst(self) -> None:
        self._gate(False)
        await self.ops.sw_rst()

    def _obs_qd(self, st: SpiStatus, where: str) -> None:
        self.logger.info(
            "OBS-SPI-QD seed=%d txqd=%d rxqd=%d where=%s active=%d",
            self.seed,
            st.txqd,
            st.rxqd,
            where,
            st.active,
        )

    def _done_read(self, st: SpiStatus, mark, windows: int) -> bool:
        """True when ``st`` ends a segment: the windows are complete before the read."""
        wins = self.pads.windows_since(mark)
        if len(wins) < windows:
            return False
        last_end = wins[windows - 1].end
        return (
            last_end is not None
            and st.clk0 is not None
            and st.clk0 >= last_end
            and st.active == 0
            and st.cmdqd == 0
        )

    async def _rx_segment(self, nwords: int, speed: int, chk: str) -> None:
        """Rx segment of 4*nwords bytes, CSAAT=0, no RXDATA read; wait until done."""
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(4 * nwords - 1, speed=speed, direction=DIR_RX))
        try:
            await self.ops.wait_segment_done(
                self.pads, mark, windows=1, bound_clks=self._seg_bound(4 * nwords, speed)
            )
        except AssertionError as exc:
            self._fail(chk, f"Rx segment of {4 * nwords} bytes not done: {exc}")

    async def _drain_rx(self, limit: int = QD_MAX + 2) -> int:
        """RXDATA reads, each after a STATUS read with RXEMPTY=0, until RXEMPTY=1."""
        return len(await self.ops.drain_rx(limit=limit))

    # ------------------------------------------------------------------
    # Scenario
    # ------------------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        rng = SepSeededRng(self.seed)
        # Draw order is fixed; values that depend on a depth found at run time
        # are drawn as raw values here and resolved when the depth is known.
        self.speed = rng.randrange(0, 3)
        self.tx_gap = rng.randrange(0, 65)
        self.rx_gap = rng.randrange(0, 33)
        self.rx_burst = rng.randrange(1, 9)
        self.clkdiv = rng.randrange(1, 4)
        self.mid_tx_raw = rng.getrandbits(16)
        self.mid_rx_raw = rng.getrandbits(16)
        self.tx_ctrl_class = rng.choice(["one", "mid", "depth"])
        self.rx_order = ["zero", "one", "mid"]
        rng.shuffle(self.rx_order)
        self.m_raw = rng.getrandbits(16)
        self.m1_raw = rng.getrandbits(16)
        self.n_cmds = rng.randrange(1, 4)
        self.payload = [rng.getrandbits(32) for _ in range(PAYLOAD_POOL)]
        self._pi = 0
        self.logger.info(
            "PLAN seed=%d speed=%d tx_gap_clk=%d rx_gap_clk=%d rx_burst=%d clkdiv=%d "
            "mid_tx_raw=%d mid_rx_raw=%d tx_ctrl_class=%s rx_order=%s m_raw=%d m1_raw=%d "
            "n_cmds=%d payload_words=%d payload0=0x%08x stall_periods=%d legs=%s",
            self.seed,
            self.speed,
            self.tx_gap,
            self.rx_gap,
            self.rx_burst,
            self.clkdiv,
            self.mid_tx_raw,
            self.mid_rx_raw,
            self.tx_ctrl_class,
            ",".join(self.rx_order),
            self.m_raw,
            self.m1_raw,
            self.n_cmds,
            PAYLOAD_POOL,
            self.payload[0],
            STALL_PERIODS,
            "txdepth,rxstall,rxdepth,txstall,txstall_ctrl,txwm,txwm_ctrl,rxwm,cmdqd,"
            "txfull_active,rxfull_idle,flag_pairs",
        )

        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.pads = SepSpiPadSampler().start()
        self.pads.set_idle_level(0)
        self.ops = SepSpiHostOps(self, clock=self.pads.now)
        try:
            await self._run()
        finally:
            self._gate(False)
            await self.pads.stop()

    async def _run(self) -> None:
        # Step 2: harness reset state, then the leaf configuration.
        self.ctrl = CTRL_SPIEN | CTRL_OUTPUT_EN | (0 << TX_WM_LSB) | (0x7F << RX_WM_LSB)
        await self.ops.wr(CONTROL, self.ctrl)
        self.clkdiv_now = self.clkdiv
        await self.ops.write_configopts(configopts_word(clkdiv=self.clkdiv))
        await self.ops.clean_state()
        st = await self.ops.read_status()
        self.logger.info(
            "START seed=%d txempty=%d rxempty=%d %s", self.seed, st.txempty, st.rxempty, st.fmt()
        )

        self.tx_depth = await self._find_tx_depth()
        rx_stall = await self._rx_stall_leg()
        self.rx_depth = await self._find_rx_depth(rx_stall["s"])
        self._resolve_draws()
        tx_stall = await self._tx_stall_leg()
        await self._tx_stall_control(tx_stall)
        await self._tx_wm_leg()
        await self._tx_wm_control()
        qd = await self._rx_wm_leg()
        await self._cmdqd_leg()
        qd.update(await self._tx_full_active_leg())
        qd.update(await self._rx_full_idle_leg())
        self._flag_pairs(qd)
        self._gate(False)
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, 5)

    # ---- step 3 -------------------------------------------------------
    async def _find_tx_depth(self) -> int:
        """Write TXDATA with no COMMAND until a STATUS read shows TXFULL=1."""
        written = 0
        for _ in range(QD_MAX + 2):
            st = await self.ops.read_status()
            if st.txfull:
                break
            if st.active:
                self._fail("CHK-SPI-QD", f"ACTIVE=1 with no COMMAND ({st.fmt()})")
            await self.ops.wr(TXDATA, self._word())
            written += 1
        else:
            self._ctrl_missing("CHK-SPI-QD", f"TXFULL=0 after {written} TXDATA writes")
        self.logger.info(
            "DRAW seed=%d tx_depth=%d (words written before TXFULL=1)", self.seed, written
        )
        await self._sw_rst()
        if written < 3:
            self._fail("CHK-SPI-WM", f"TX depth {written} leaves no mid watermark in 2..depth-1")
        return written

    # ---- step 4 and 5 -------------------------------------------------
    async def _rx_stall_leg(self) -> dict:
        chk = "CHK-SPI-RXSTALL"
        await self._clean()
        self._gate(True)
        mark = self.pads.mark()
        await self.ops.issue_command(
            command_word(RX_STALL_BYTES - 1, speed=self.speed, direction=DIR_RX)
        )
        c_cmd = self.pads.now()
        st0 = await self._poll(
            lambda s: s.rxfull == 1 and s.rxstall == 1,
            self._seg_bound(RX_STALL_BYTES, self.speed),
            "RXFULL=1 and RXSTALL=1",
            chk,
        )
        toggles = len(self.pads.sck_edges_between(c_cmd, st0.clk1))
        if toggles == 0:
            self._ctrl_missing(chk, "no sck edge between the COMMAND write and RXFULL=1")
        await self._clocks(self._stall_win())
        st1 = await self.ops.read_status()
        edges = len(self.pads.sck_edges_between(st0.clk1, st1.clk0))
        span = st1.clk0 - st0.clk1
        self.logger.info(
            "RX stall window seed=%d clocks=%d (>= %d) sck_edges=%d start: %s end: %s",
            self.seed,
            span,
            self._stall_win(),
            edges,
            st0.fmt(),
            st1.fmt(),
        )
        if st0.rxqd != st1.rxqd:
            self._ctrl_missing(chk, f"RXQD moved in the stall window: {st0.rxqd} -> {st1.rxqd}")
        if not (st1.rxfull == 1 and st1.rxstall == 1):
            fc = field_compare(st1.raw, ST_RXFULL | ST_RXSTALL, ST_RXFULL | ST_RXSTALL)
            self._fail(chk, f"end of the stall window: {fc.fields()}")
        if edges != 0:
            self._fail(chk, f"sck_edges_in_stall={edges} with RXFULL=1 and RXSTALL=1")

        # Step 5: drain in bursts with the drawn gap until the segment is done.
        drained = 0
        deadline = self.pads.now() + 4 * self._seg_bound(RX_STALL_BYTES, self.speed)
        while True:
            for _ in range(self.rx_burst):
                st = await self.ops.read_status()
                if st.rxempty:
                    break
                await self.ops.rd(RXDATA)
                drained += 1
            if st.rxempty and self._done_read(st, mark, 1):
                break
            if self.pads.now() > deadline:
                self._fail(chk, f"segment not done after drained_words={drained} ({st.fmt()})")
            await self._clocks(self.rx_gap)
        cycles = self.pads.leading_edges_since(mark)
        exp_cycles = RX_STALL_BYTES * 8 // LANES[self.speed]
        if drained != RX_STALL_WORDS:
            self._fail(chk, f"drained_words={drained} expect={RX_STALL_WORDS}")
        if cycles != exp_cycles:
            self._fail(chk, f"cycles={cycles}/{exp_cycles} drained_words={drained}")
        self.logger.info(
            "%s PASS seed=%d speed=%d rxfull=1 rxstall=1 sck_edges_in_stall=0 "
            "ctrl_toggles_before_rxfull=%d drained_words=%d window_clk=%d rxqd_in_stall=%d "
            "cycles=%d/%d status_masked=0x%x mask=0x%x",
            chk,
            self.seed,
            self.speed,
            toggles,
            drained,
            span,
            st0.rxqd,
            cycles,
            exp_cycles,
            st1.raw & (ST_RXFULL | ST_RXSTALL),
            ST_RXFULL | ST_RXSTALL,
        )
        return {"s": st0.rxqd}

    async def _find_rx_depth(self, s: int) -> int:
        """First idle Rx segment length r (from max(1, s-1) up) whose read shows RXFULL=1."""
        self._gate(False)
        r = max(1, s - 1)
        while True:
            await self._clean()
            await self._rx_segment(r, self.speed, "CHK-SPI-QD")
            st = await self.ops.read_status()
            if st.rxfull:
                break
            self._obs_qd(st, f"rx_depth_search r={r} rxfull=0")
            if r >= QD_MAX:
                self._ctrl_missing("CHK-SPI-QD", f"RXFULL=0 at r={r}, the largest RXQD")
            r += 1
        self._obs_qd(st, f"rx_depth_search r={r} rxfull=1")
        self.logger.info("DRAW seed=%d rx_depth=%d (search start %d)", self.seed, r, max(1, s - 1))
        await self._drain_rx()
        await self._sw_rst()
        if r < 4:
            self._fail("CHK-SPI-WM", f"RX depth {r} leaves no mid watermark in 2..depth-2")
        return r

    def _resolve_draws(self) -> None:
        d, r = self.tx_depth, self.rx_depth
        self.mid_tx = 2 + self.mid_tx_raw % (d - 2)  # 2 .. D-1
        self.mid_rx = 2 + self.mid_rx_raw % (r - 3)  # 2 .. R-2
        self.tx_ctrl = {"one": 1, "mid": self.mid_tx, "depth": d}[self.tx_ctrl_class]
        self.m = 2 + self.m_raw % (d - 1)  # 2 .. D
        self.m1 = 1 + self.m1_raw % (self.m - 1)  # 1 .. m-1
        self.logger.info(
            "DRAW seed=%d mid_tx=%d mid_rx=%d tx_ctrl_wm=%d (%s) m=%d m1=%d",
            self.seed,
            self.mid_tx,
            self.mid_rx,
            self.tx_ctrl,
            self.tx_ctrl_class,
            self.m,
            self.m1,
        )

    # ---- step 6 and 7 -------------------------------------------------
    async def _tx_stall_leg(self) -> dict:
        chk = "CHK-SPI-TXSTALL"
        lanes = LANES[self.speed]
        m, m1 = self.m, self.m1
        words = [self._word() for _ in range(m)]
        self.tx_words = words
        await self._clean()
        self._gate(True)
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(4 * m - 1, speed=self.speed, direction=DIR_TX))
        for w in words[:m1]:
            await self.ops.push_tx(w)
        pre = 4 * m1 * 8 // lanes
        try:
            await self.pads.wait_leading_edges(pre, mark, self._seg_bound(4 * m1, self.speed))
        except AssertionError as exc:
            self._fail(chk, f"sck cycles of the first {m1} words: {exc}")
        st0 = await self._poll(lambda s: s.txstall == 1, self._seg_bound(4, 0), "TXSTALL=1", chk)
        await self._clocks(self._stall_win())
        st1 = await self.ops.read_status()
        edges = len(self.pads.sck_edges_between(st0.clk1, st1.clk0))
        span = st1.clk0 - st0.clk1
        self.logger.info(
            "TX stall window seed=%d m=%d m1=%d clocks=%d (>= %d) sck_edges=%d cycles_before=%d "
            "start: %s end: %s",
            self.seed,
            m,
            m1,
            span,
            self._stall_win(),
            edges,
            self.pads.leading_edges_since(mark),
            st0.fmt(),
            st1.fmt(),
        )
        if st1.txstall != 1:
            fc = field_compare(st1.raw, ST_TXSTALL, ST_TXSTALL)
            self._fail(chk, f"end of the stall window: {fc.fields()}")
        if edges != 0:
            self._fail(chk, f"sck_edges_in_stall={edges} with TXSTALL=1")
        await self._clocks(self.tx_gap)
        for w in words[m1:]:
            await self.ops.push_tx(w)
        # TXSTALL must drop while the segment still runs: a host that holds it
        # until the segment ends shows its first TXSTALL=0 read with chip
        # select high. The words left after the last write keep chip select
        # low for longer than one STATUS read.
        st2 = await self._poll(
            lambda s: s.txstall == 0 or not self.pads.cs_low(),
            self._seg_bound(4 * m, self.speed),
            "TXSTALL=0 or chip select high",
            chk,
        )
        in_seg = int(self.pads.cs_low())
        if st2.txstall != 0 or not in_seg:
            self._fail(
                chk, f"TXSTALL still set with the data written: in_segment={in_seg} {st2.fmt()}"
            )
        try:
            await self.ops.wait_segment_done(
                self.pads, mark, windows=1, bound_clks=self._seg_bound(4 * m, self.speed)
            )
        except AssertionError as exc:
            self._fail(chk, f"segment not done: {exc}")
        cycles = self.pads.leading_edges_since(mark)
        exp = 4 * m * 8 // lanes
        if cycles != exp:
            self._fail(chk, f"cycles={cycles}/{exp}")
        return {"cycles": cycles, "exp": exp, "st1": st1, "after": st2.txstall}

    async def _tx_stall_control(self, res: dict) -> None:
        chk = "CHK-SPI-TXSTALL"
        await self._clean()
        m = self.m
        for w in self.tx_words:
            await self.ops.push_tx(w)
        mark = self.pads.mark()
        n0 = len(self.ops.status_log)
        await self.ops.issue_command(command_word(4 * m - 1, speed=self.speed, direction=DIR_TX))
        deadline = self.pads.now() + self._seg_bound(4 * m, self.speed)
        while True:
            st = await self.ops.read_status()
            if self._done_read(st, mark, 1):
                break
            if self.pads.now() > deadline:
                self._fail(chk, f"control segment not done ({st.fmt()})")
        reads = self.ops.status_log[n0:]
        wins = self.pads.windows_since(mark)
        inside = [
            s
            for s in reads
            if any(w.start <= s.clk0 and s.clk1 < w.end for w in wins if w.end is not None)
        ]
        stalled = [s for s in inside if s.txstall]
        cycles = self.pads.leading_edges_since(mark)
        self.logger.info(
            "TX stall control seed=%d reads=%d reads_cs_low=%d txstall_set=%d cycles=%d/%d",
            self.seed,
            len(reads),
            len(inside),
            len(stalled),
            cycles,
            res["exp"],
        )
        if not inside:
            self._ctrl_missing(chk, "no STATUS read taken while chip select is low")
        if stalled:
            self._fail(chk, f"control: TXSTALL=1 with every word written ({stalled[0].fmt()})")
        self._gate(True)
        self.logger.info(
            "%s PASS seed=%d speed=%d gap_clk=%d txstall=1 sck_edges_in_stall=0 "
            "txstall_after_push=%d cycles=%d/%d control_gap0_txstall=0 m=%d m1=%d "
            "control_reads_cs_low=%d status_masked=0x%x mask=0x%x",
            chk,
            self.seed,
            self.speed,
            self.tx_gap,
            res["after"],
            res["cycles"],
            res["exp"],
            self.m,
            self.m1,
            len(inside),
            res["st1"].raw & ST_TXSTALL,
            ST_TXSTALL,
        )

    # ---- step 8 and 9 -------------------------------------------------
    async def _tx_wm_leg(self) -> None:
        chk = "CHK-SPI-WM"
        d = self.tx_depth
        wts = [0]
        if d + 1 <= TX_WM_MAX:
            wts.append(d + 1)
        else:
            self.logger.info(
                "TX watermark seed=%d depth+1=%d above %d: skipped", self.seed, d + 1, TX_WM_MAX
            )
        wts.append(self.tx_ctrl)
        await self._clean()
        for wt in wts:
            graded = wt in (0, d + 1)
            self._gate(graded)
            await self._write_control(tx_wm=wt)
            qs = sorted({q for q in (0, 1, wt - 1, wt, d) if 0 <= q <= d})
            occ = 0
            for q in qs:
                while occ < q:
                    await self.ops.push_tx(self._word())
                    occ += 1
                st = await self._poll(
                    lambda s, q=q: s.txqd == q and s.active == 0,
                    20_000,
                    f"TXQD={q} with ACTIVE=0",
                    chk,
                )
                flag = st.txwm
                if not graded:
                    self.logger.info(
                        "OBS-SPI-WM seed=%d side=tx wm=%d q=%d flag=%d", self.seed, wt, q, flag
                    )
                    continue
                expect = 0 if wt == 0 else 1
                fc = field_compare(st.raw, expect * ST_TXWM, ST_TXWM)
                if not fc.ok:
                    self._fail(chk, f"side=tx wm={wt} q={q} flag={flag} expect={expect}")
                self.logger.info(
                    "%s PASS seed=%d side=tx wm=%d q=%d flag=%d expect=%d status_masked=0x%x "
                    "mask=0x%x",
                    chk,
                    self.seed,
                    wt,
                    q,
                    flag,
                    expect,
                    st.raw & ST_TXWM,
                    ST_TXWM,
                )
            await self._sw_rst()
        await self._write_control(tx_wm=0)

    async def _tx_wm_control(self) -> None:
        await self._clean()
        await self._write_control(tx_wm=1)
        try:
            st = await self._poll(lambda s: s.txwm == 1, 20_000, "TXWM=1", "CHK-SPI-WM")
        except AssertionError:
            self._ctrl_missing("CHK-SPI-WM", "TX_WATERMARK=1 never gave TXWM=1")
        if st.txqd != 0:
            self._ctrl_missing("CHK-SPI-WM", f"TXWM=1 read shows TXQD={st.txqd}, not 0")
        self.logger.info("CTRL-SPI-WM seed=%d side=tx wm=1 q=0 flag=1", self.seed)
        await self._write_control(tx_wm=0)

    # ---- step 10 and 11 -----------------------------------------------
    async def _rx_wm_leg(self) -> dict:
        chk = "CHK-SPI-WM"
        vals = {"zero": 0, "one": 1, "mid": self.mid_rx}
        steps_ok = 0
        for name in self.rx_order:
            wr = vals[name]
            self._gate(True)
            await self._write_control(rx_wm=wr)
            rs = ([wr - 1] if wr >= 1 else []) + [wr + 1]
            for r in rs:
                await self._clean()
                self._gate(True)
                if r > 0:
                    await self._rx_segment(r, self.speed, chk)
                st = await self._poll(
                    lambda s, r=r: s.rxqd == r and s.active == 0,
                    20_000,
                    f"RXQD={r} with ACTIVE=0",
                    chk,
                )
                self._obs_qd(st, f"rx_wm wr={wr} r={r}")
                expect = 1 if r > wr else 0
                fc = field_compare(st.raw, expect * ST_RXWM, ST_RXWM)
                if not fc.ok:
                    self._fail(chk, f"side=rx wm={wr} q={r} flag={st.rxwm} expect={expect}")
                self.logger.info(
                    "%s PASS seed=%d side=rx wm=%d q=%d flag=%d expect=%d status_masked=0x%x "
                    "mask=0x%x",
                    chk,
                    self.seed,
                    wr,
                    r,
                    st.rxwm,
                    expect,
                    st.raw & ST_RXWM,
                    ST_RXWM,
                )
            # Step 11: drain after the Wr+1 run; each read lowers RXQD by 1.
            prev = rs[-1]
            crossed = False
            while True:
                st = await self.ops.read_status()
                if st.rxempty:
                    break
                await self.ops.rd(RXDATA)
                st2 = await self._poll(
                    lambda s, p=prev: s.rxqd != p, 20_000, f"RXQD below {prev}", "CHK-SPI-QD"
                )
                if st2.active != 0 or st2.rxqd != prev - 1:
                    self._fail(
                        "CHK-SPI-QD",
                        f"RXDATA read at RXQD={prev} gave RXQD={st2.rxqd} active={st2.active}",
                    )
                steps_ok += 1
                prev = st2.rxqd
                if st2.rxqd == wr:
                    self.logger.info(
                        "OBS-SPI-WM seed=%d side=rx wm=%d q=%d flag=%d (not graded)",
                        self.seed,
                        wr,
                        wr,
                        st2.rxwm,
                    )
                if wr >= 1 and st2.rxqd == wr - 1:
                    if st2.rxwm != 0:
                        self._fail(chk, f"side=rx crossing=out wm={wr} q={wr - 1} flag=1")
                    crossed = True
                    self.logger.info(
                        "%s PASS seed=%d side=rx crossing=out wm=%d q=%d flag=0 "
                        "status_masked=0x%x mask=0x%x",
                        chk,
                        self.seed,
                        wr,
                        wr - 1,
                        st2.raw & ST_RXWM,
                        ST_RXWM,
                    )
            if wr >= 1 and not crossed:
                self._fail(
                    chk, f"side=rx crossing=out wm={wr}: the drain never reached RXQD={wr - 1}"
                )
            await self._sw_rst()
        return {"rxqd_steps": steps_ok}

    # ---- step 12 and 13 -----------------------------------------------
    async def _cmdqd_leg(self) -> None:
        chk = "CHK-SPI-CMDQD"
        await self._clean()
        self._gate(True)
        mark0 = self.pads.mark()
        # An 8-byte Tx head with one word queued: the core sends that word and
        # holds the segment in TXSTALL with ACTIVE=1 until one more word arrives.
        await self.ops.push_tx(self._word())
        await self.ops.issue_command(command_word(7, speed=0, direction=DIR_TX))
        try:
            st = await self._poll(
                lambda s: s.active == 1 and s.txstall == 1, 20_000, "ACTIVE=1 and TXSTALL=1", chk
            )
        except AssertionError:
            self._ctrl_missing(chk, "the head segment is not held (ACTIVE=1, TXSTALL=1)")
        c0 = st.cmdqd
        prev = c0
        accepted = 0
        trail = [f"c0={c0}"]
        for _ in range(self.n_cmds):
            st = await self.ops.read_status()
            if not st.ready:
                trail.append(f"ready=0@cmdqd={st.cmdqd}")
                break
            await self.ops.wr(COMMAND, command_word(0, speed=0, direction=DIR_DUMMY))
            accepted += 1
            st2 = await self._poll(
                lambda s, p=prev: s.cmdqd != p, 20_000, f"CMDQD moves from {prev}", chk
            )
            if st2.cmdqd != prev + 1:
                self._fail(chk, f"CMDQD {prev} -> {st2.cmdqd} after one accepted COMMAND")
            prev = st2.cmdqd
            trail.append(f"cmdqd={st2.cmdqd} ready={st2.ready}")
        self.logger.info("CMDQD seed=%d n=%d %s", self.seed, self.n_cmds, " ".join(trail))
        if accepted == 0:
            self._ctrl_missing(chk, "no COMMAND accepted behind the held head")
        held = prev
        ready = st2.ready

        # Step 13: release the queue.
        await self.ops.push_tx(self._word())
        try:
            await self.pads.wait_windows(1 + accepted, mark0, 200_000)
        except AssertionError as exc:
            self._fail(chk, f"cs_windows short after release: {exc}")
        st = await self._poll(
            lambda s: s.active == 0 and s.cmdqd == 0, 20_000, "ACTIVE=0 and CMDQD=0", chk
        )
        got = len(self.pads.windows_since(mark0))
        if got != 1 + accepted:
            self._fail(chk, f"cs_windows={got}/{1 + accepted}")
        self.logger.info(
            "%s PASS seed=%d queued=%d cmdqd=%d ready=%d cs_windows=%d/%d drained=1 c0=%d",
            chk,
            self.seed,
            accepted,
            held,
            ready,
            got,
            1 + accepted,
            c0,
        )
        await self._sw_rst()

    # ---- step 14 -------------------------------------------------------
    async def _tx_full_active_leg(self) -> dict:
        chk = "CHK-SPI-QD"
        self._gate(False)
        await self._set_clkdiv(TXFULL_CLKDIV)
        await self._clean()
        self._gate(True)
        d = self.tx_depth
        n = d + d  # K = D
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(4 * n - 1, speed=0, direction=DIR_TX))
        written = 0
        full = None
        while written < n:
            st = await self.ops.read_status()
            if st.txfull and st.active:
                full = st
                break
            if st.txfull:
                continue
            await self.ops.wr(TXDATA, self._word())
            written += 1
        if full is None:
            self._ctrl_missing(chk, f"no TXFULL=1 with ACTIVE=1 after {written} of {n} words")
        self.logger.info(
            "TX full while active seed=%d written=%d txqd=%d %s",
            self.seed,
            written,
            full.txqd,
            full.fmt(),
        )
        while written < n:
            await self.ops.push_tx(self._word())
            written += 1
        try:
            await self.ops.wait_segment_done(
                self.pads, mark, windows=1, bound_clks=self._seg_bound(4 * n, 0)
            )
        except AssertionError as exc:
            self._fail(chk, f"TX-full segment not done: {exc}")
        cycles = self.pads.leading_edges_since(mark)
        exp = 4 * n * 8
        if cycles != exp:
            self._fail(chk, f"txfull_cycles={cycles}/{exp}")
        await self._sw_rst()
        return {"txfull_cycles": (cycles, exp), "txfull_txqd": full.txqd}

    # ---- step 15 -------------------------------------------------------
    async def _rx_full_idle_leg(self) -> dict:
        chk = "CHK-SPI-QD"
        r = self.rx_depth
        await self._clean()
        self._gate(True)
        await self._rx_segment(r, self.speed, chk)
        st = await self.ops.read_status()
        self._obs_qd(st, f"rx_full_idle R={r}")
        if st.rxfull != 1:
            fc = field_compare(st.raw, ST_RXFULL, ST_RXFULL)
            self._fail(chk, f"rxfull_at_R=0 after an Rx segment of {r} words: {fc.fields()}")
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(3, speed=self.speed, direction=DIR_RX))
        win = self._stall_win()
        bound = self._seg_bound(4, self.speed) + 4 * win
        ended = "timeout"
        for _ in range(bound):
            if self.pads.windows_since(mark):
                ended = "cs_high"
                break
            edges = self.pads.sck_edges
            last = max(mark.clk, edges[-1][0] if edges else 0)
            if self.pads.now() - last >= win and self.pads.cs_low():
                ended = "stall_window"
                break
            await self._clocks(1)
        if ended == "timeout":
            self._fail(chk, "extra Rx segment: neither chip select high nor a quiet stall window")
        st_x = await self.ops.read_status()
        self._obs_qd(st_x, f"rx_full_idle extra segment ended={ended}")
        if st_x.rxqd > r:
            self._fail(chk, f"rxqd_after_extra={st_x.rxqd} max={r}")
        words = 0
        deadline = self.pads.now() + 4 * bound + 20_000 * (r + 2)
        while True:
            st = await self.ops.read_status()
            if not st.rxempty:
                await self.ops.rd(RXDATA)
                words += 1
            elif self._done_read(st, mark, 1):
                break
            if self.pads.now() > deadline:
                self._fail(chk, f"extra segment not done, words={words} ({st.fmt()})")
        if words != r + 1:
            self._fail(chk, f"words_after_extra={words}/{r + 1}")
        await self._sw_rst()
        return {
            "rxfull_at_R": 1,
            "rxqd_after_extra": st_x.rxqd,
            "words_after_extra": words,
            "ended": ended,
        }

    # ---- step 16 and the CHK-SPI-QD verdict ------------------------------
    def _flag_pairs(self, qd: dict) -> None:
        chk = "CHK-SPI-QD"
        log = self.ops.status_log
        both = [s for s in log if (s.txfull and s.txempty) or (s.rxfull and s.rxempty)]
        seen = {
            f: int(any(getattr(s, f) for s in log))
            for f in ("txfull", "txempty", "rxfull", "rxempty")
        }
        if both:
            self._fail(chk, f"pairs_both_set={len(both)} first: {both[0].fmt()}")
        missing = [f for f, v in seen.items() if not v]
        if missing:
            self._ctrl_missing(chk, f"flags never set in {len(log)} STATUS reads: {missing}")
        if qd["rxqd_steps"] == 0:
            self._ctrl_missing(chk, "no RXDATA read with ACTIVE=0 was graded")
        got, exp = qd["txfull_cycles"]
        self._gate(True)
        self.logger.info(
            "%s PASS seed=%d idle=1 rxqd_step_ok=1 txfull_active=1 txfull_cycles=%d/%d "
            "rxfull_at_R=1 rxqd_after_extra=%d max=%d words_after_extra=%d/%d pairs_both_set=0 "
            "seen_txfull=1 seen_txempty=1 seen_rxfull=1 seen_rxempty=1 rxqd_steps=%d "
            "txfull_txqd=%d extra_ended=%s status_reads=%d",
            chk,
            self.seed,
            got,
            exp,
            qd["rxqd_after_extra"],
            self.rx_depth,
            qd["words_after_extra"],
            self.rx_depth + 1,
            qd["rxqd_steps"],
            qd["txfull_txqd"],
            qd["ended"],
            len(log),
        )
