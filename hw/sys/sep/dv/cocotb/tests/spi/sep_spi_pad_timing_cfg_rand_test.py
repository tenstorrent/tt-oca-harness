# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SPI host CONFIGOPTS fields set the sck idle level, period, chip-select timing and data edge.

Contract (``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc``,
CONFIGOPTS; ``hw/sys/sep/doc/clk_rst.adoc`` for the core clock):

* sck idles at the CPOL level.
* The sck period is 2*(CLKDIV+1) core clocks; a half sck cycle is CLKDIV+1.
* Chip select falls (CSNLEAD+1) half cycles before the first sck edge, rises
  (CSNTRAIL+1) half cycles after the last sck edge, and stays high at least
  (CSNIDLE+1) half cycles between commands.
* Tx data changes on the trailing sck edge when CPHA=0 and on the leading edge
  when CPHA=1.

Every seed grades two mode cells (CPOL x CPHA x FULLCYC): a drawn cell and the
cell with the other CPOL and the other CPHA. Per mode cell the leaf runs a
control pair (Tx 16 bytes with an Rx 4-byte COMMAND queued while the Tx segment
is active, CSNIDLE=0) that gives the natural chip-select gap g0, raises CSNIDLE
until its minimum is above g0, runs the graded pair, then a ratio leg of two
4-byte Tx segments at CLKDIV a and b. A test-side sampler
(``env/sep_spi_pad_sampler.py``) reads ``spi_sck_o``, ``spi_cs_n_o`` and
``spi_mosi_o`` on each core clock. No responder is attached.

Checks (one PASS line per mode cell, each with ``mode=<cpol><cpha><fullcyc>``):

* CHK-SPI-IDLE-LEVEL: sck sits at CPOL in every chip-select-high window of the
  graded pair that starts after the first transaction ends. Control: sck
  toggles in the chip-select-low windows of the same pair.
* CHK-SPI-PERIOD: every sck period of the graded pair is 2*(CLKDIV+1) clocks.
* CHK-SPI-RATIO: period_a*(b+1) equals period_b*(a+1).
* CHK-SPI-CSN: lead and trail of each graded transaction are exact, and the
  chip-select-high gap is at least (CSNIDLE+1)*(CLKDIV+1). Control: the minimum
  is above g0 of the control pair.
* CHK-SPI-CPHA: at CLKDIV 1 or more every Tx data change after the first bit
  lies in the half sck period that starts at the stated edge. Control: at least
  two such changes. The cell CPHA=1 with FULLCYC=1 logs ``OBS-SPI-CPHA`` and is
  not graded.

Graded window: owner code of this test for the graded pair, the ratio leg and
the data-edge grade; closed for bring-up and every control pair.

Run mode: ``no_cpu``, ``lsu_stub_all_live``, ``+skip_fuse_sense``, no ``rst_ni``
pulse. Every random value is a pure function of the seed (``SepSeededRng``).
"""

from __future__ import annotations

from dataclasses import dataclass

import pyuvm
from env.sep_fcov_gate import close_graded_window, fcov_present, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_pad_sampler import CsWindow, SepSpiPadSampler
from sep_base_test import sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    COMMAND,
    CONTROL,
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
    CTRL_SPIEN,
    CTRL_SW_RST,
    ERR_STATUS_MASK,
    ERROR_STATUS,
)
from seq_lib.sep_spi_host_ops import DIR_RX, DIR_TX, SepSpiHostOps, command_word, configopts_word

TEST = "sep_spi_pad_timing_cfg_rand_test"

# TXDATA word whose bytes alternate 0x55 and 0xAA on the pad.
PATTERN = 0xAA55AA55
CTRL_TX_BYTES = 16
RX_BYTES = 4
RATIO_TX_BYTES = 4
MAX_DOUBLINGS = 3
CSN_MAX = 15

# Bounds. Each expiry fails the check that the wait feeds.
QUEUE_POLLS = 64
PAIR_BOUND_CLKS = 400_000


@dataclass
class Cell:
    cpol: int
    cpha: int
    fullcyc: int
    a: int = 0
    lead: int = 0
    trail: int = 0
    idle: int = 0
    b: int = 0

    @property
    def mode(self) -> str:
        return f"{self.cpol}{self.cpha}{self.fullcyc}"

    def cfg(self, *, clkdiv: int, csnidle: int) -> int:
        return configopts_word(
            clkdiv=clkdiv,
            csnidle=csnidle,
            csntrail=self.trail,
            csnlead=self.lead,
            fullcyc=self.fullcyc,
            cpha=self.cpha,
            cpol=self.cpol,
        )


def _draw_0_15(rng: SepSeededRng) -> int:
    """0 to 15, weighted toward 0 and 15."""
    roll = rng.randrange(4)
    if roll == 0:
        return 0
    if roll == 1:
        return CSN_MAX
    return rng.randrange(1, CSN_MAX)


@pyuvm.test()
class sep_spi_pad_timing_cfg_rand_test(sep_base_test):
    """Two mode cells per seed: sck idle level, period, ratio, chip-select timing, data edge."""

    required_evidence = (
        "CHK-SPI-IDLE-LEVEL",
        "CHK-SPI-PERIOD",
        "CHK-SPI-RATIO",
        "CHK-SPI-CSN",
        "CHK-SPI-CPHA",
    )

    def _plan(self, seed: int) -> list[Cell]:
        rng = SepSeededRng(seed)
        first = rng.randrange(8)
        c1 = Cell((first >> 2) & 1, (first >> 1) & 1, first & 1)
        c2 = Cell(1 - c1.cpol, 1 - c1.cpha, rng.randrange(2))
        cells = [c1, c2]
        if rng.randrange(2):
            cells.reverse()
        for c in cells:
            c.a = _draw_0_15(rng)
            c.lead = _draw_0_15(rng)
            c.trail = _draw_0_15(rng)
            c.idle = _draw_0_15(rng)
            c.b = rng.choice([v for v in range(CSN_MAX + 1) if v != c.a])
        self.logger.info(
            "PLAN seed=%d cells=%s",
            seed,
            " ".join(
                f"[mode={c.mode} a={c.a} csnlead={c.lead} csntrail={c.trail} "
                f"csnidle={c.idle} b={c.b}]"
                for c in cells
            ),
        )
        return cells

    # ---- helpers ----------------------------------------------------------
    async def _err_status(self) -> int:
        return int(await self.ops.rd(ERROR_STATUS)) & 0xFFFF_FFFF

    async def _pair(self, cfg: int, cpol: int, tx_bytes: int, *, tag: str):
        """Tx segment with the Rx COMMAND queued while it is active.

        Returns ``(mark, windows)``, or ``None`` when a STATUS read shows READY=1
        and ACTIVE=0 before the Rx COMMAND is written.
        """
        ops, pads = self.ops, self.pads
        await ops.write_configopts(cfg)
        pads.set_idle_level(cpol)
        for _ in range(tx_bytes // 4):
            await ops.push_tx(PATTERN)
        mark = pads.mark()
        await ops.issue_command(command_word(tx_bytes - 1, speed=0, direction=DIR_TX))
        queued = None
        for _ in range(QUEUE_POLLS):
            st = await ops.read_status()
            if st.ready and st.active:
                await ops.wr(COMMAND, command_word(RX_BYTES - 1, speed=0, direction=DIR_RX))
                queued = st
                break
            if st.ready and not st.active:
                break
        if queued is None:
            await ops.wait_segment_done(pads, mark, windows=1, bound_clks=PAIR_BOUND_CLKS)
            await ops.drain_rx()
            self.logger.info(
                "%s LOG seed=%d tx_bytes=%d rx_queued_while_active=0", tag, self.seed, tx_bytes
            )
            return None
        wins = await ops.wait_segment_done(pads, mark, windows=2, bound_clks=PAIR_BOUND_CLKS)
        await ops.drain_rx()
        return mark, wins

    async def _single_tx(self, cfg: int, cpol: int) -> CsWindow:
        ops, pads = self.ops, self.pads
        await ops.write_configopts(cfg)
        pads.set_idle_level(cpol)
        await ops.push_tx(PATTERN)
        mark = pads.mark()
        await ops.issue_command(command_word(RATIO_TX_BYTES - 1, speed=0, direction=DIR_TX))
        wins = await ops.wait_segment_done(pads, mark, windows=1, bound_clks=PAIR_BOUND_CLKS)
        return wins[0]

    @staticmethod
    def _cpha_split(win: CsWindow, cpha: int) -> tuple[int, int, int]:
        """Data changes after the first bit: (in stated half, in other half, exempt)."""
        edges = win.edges
        if not edges:
            return 0, 0, len(win.mosi_changes)
        first = edges[0][0]
        stated = other = exempt = 0
        for c in win.mosi_changes:
            if c < first:
                exempt += 1
                continue
            last = [lvl for clk, lvl in edges if clk <= c][-1]
            leading = last != win.idle_level
            if leading == bool(cpha):
                stated += 1
            else:
                other += 1
        return stated, other, exempt

    # ---- one mode cell ----------------------------------------------------
    async def _mode_cell(self, c: Cell) -> None:
        seed = self.seed
        pads = self.pads
        half = c.a + 1

        # Control pair: CSNIDLE=0, window closed.
        close_graded_window(self.logger)
        tx_bytes = CTRL_TX_BYTES
        ctrl = None
        for _ in range(MAX_DOUBLINGS + 1):
            ctrl = await self._pair(
                c.cfg(clkdiv=c.a, csnidle=0), c.cpol, tx_bytes, tag="CTL-SPI-QUEUE"
            )
            if ctrl is not None:
                break
            tx_bytes *= 2
        if ctrl is None:
            raise AssertionError(
                f"CTRL-MISSING seed={seed} mode={c.mode} CHK-SPI-CSN: the Rx COMMAND never "
                f"queued while the Tx segment was active (last tx_bytes={tx_bytes // 2})"
            )
        cmark, cwins = ctrl
        g0 = cwins[1].start - cwins[0].end
        self.logger.info(
            "CTL-SPI-CSN LOG seed=%d mode=%s clkdiv=%d tx_bytes=%d control_gap=%d windows=%s",
            seed,
            c.mode,
            c.a,
            tx_bytes,
            g0,
            [w.fmt() for w in cwins],
        )

        # Raise CSNIDLE above the control gap.
        idle = c.idle
        if (idle + 1) * half <= g0:
            fits = [v for v in range(CSN_MAX + 1) if (v + 1) * half > g0]
            if not fits:
                raise AssertionError(
                    f"CTRL-MISSING seed={seed} mode={c.mode} CHK-SPI-CSN: no CSNIDLE "
                    f"gives a minimum above control_gap={g0} at clkdiv={c.a}"
                )
            idle = fits[0]
        idle_min = (idle + 1) * half
        self.logger.info(
            "DRAW seed=%d mode=%s csnidle_drawn=%d csnidle_graded=%d min=%d control_gap=%d",
            seed,
            c.mode,
            c.idle,
            idle,
            idle_min,
            g0,
        )

        # Graded pair.
        open_graded_window(TEST, self.logger)
        graded = await self._pair(
            c.cfg(clkdiv=c.a, csnidle=idle), c.cpol, tx_bytes, tag="CHK-SPI-CSN"
        )
        if graded is None:
            close_graded_window(self.logger)
            raise AssertionError(
                f"CTRL-MISSING seed={seed} mode={c.mode} CHK-SPI-CSN: the Rx COMMAND did "
                f"not queue while the Tx segment was active in the graded pair"
            )
        gmark, (w1, w2) = graded
        highs = [h for h in pads.high_windows_since(gmark) if h.start >= w1.end]
        levels = set().union(*(h.sck_levels for h in highs)) if highs else set()
        toggles = (w1.toggles, w2.toggles)

        line = (
            f"seed={seed} mode={c.mode} cpol={c.cpol} level={sorted(levels)} "
            f"windows={len(highs)} control_toggles={min(toggles)}"
        )
        if min(toggles) < 1:
            raise AssertionError(f"CTRL-MISSING CHK-SPI-IDLE-LEVEL {line}")
        if len(highs) < 2 or levels != {c.cpol}:
            raise AssertionError(f"CHK-SPI-IDLE-LEVEL FAIL {line}")
        self.logger.info(
            "CHK-SPI-IDLE-LEVEL PASS seed=%d cpol=%d level=%d windows=%d control_toggles=%d "
            "mode=%s",
            seed,
            c.cpol,
            c.cpol,
            len(highs),
            min(toggles),
            c.mode,
        )

        periods = w1.periods + w2.periods
        exp_p = 2 * half
        bad = sorted(set(p for p in periods if p != exp_p))
        line = (
            f"seed={seed} clkdiv={c.a} periods={len(periods)} "
            f"period_clk={sorted(set(periods))} expect={exp_p} mode={c.mode}"
        )
        if not periods or bad:
            raise AssertionError(f"CHK-SPI-PERIOD FAIL {line}")
        self.logger.info(
            "CHK-SPI-PERIOD PASS seed=%d clkdiv=%d periods=%d period_clk=%d expect=%d mode=%s",
            seed,
            c.a,
            len(periods),
            exp_p,
            exp_p,
            c.mode,
        )

        exp_lead = (c.lead + 1) * half
        exp_trail = (c.trail + 1) * half
        gap = w2.start - w1.end
        line = (
            f"seed={seed} clkdiv={c.a} lead={w1.lead},{w2.lead}/{exp_lead} "
            f"trail={w1.trail},{w2.trail}/{exp_trail} idle_gap={gap} min={idle_min} "
            f"control_gap={g0} csnlead={c.lead} csntrail={c.trail} csnidle={idle} mode={c.mode}"
        )
        ok = (
            w1.lead == exp_lead
            and w2.lead == exp_lead
            and w1.trail == exp_trail
            and w2.trail == exp_trail
            and gap >= idle_min
            and idle_min > g0
        )
        # A CSN failure is raised after the ratio and data-edge checks of this
        # mode cell, so the log carries every check of the cell.
        csn_fail = None
        if ok:
            self.logger.info("CHK-SPI-CSN PASS %s", line)
        else:
            csn_fail = f"CHK-SPI-CSN FAIL {line}"
            self.logger.error(csn_fail)

        # Ratio leg.
        cfg_a = c.cfg(clkdiv=c.a, csnidle=idle)
        cfg_b = c.cfg(clkdiv=c.b, csnidle=idle)
        win_a = await self._single_tx(cfg_a, c.cpol)
        win_b = await self._single_tx(cfg_b, c.cpol)
        pa_set, pb_set = set(win_a.periods), set(win_b.periods)
        pa = min(pa_set) if pa_set else 0
        pb = min(pb_set) if pb_set else 0
        lhs, rhs = pa * (c.b + 1), pb * (c.a + 1)
        line = (
            f"seed={seed} a={c.a} b={c.b} period_a={pa} period_b={pb} lhs={lhs} rhs={rhs} "
            f"mode={c.mode}"
        )
        if len(pa_set) != 1 or len(pb_set) != 1 or lhs != rhs or c.a == c.b:
            raise AssertionError(
                f"CHK-SPI-RATIO FAIL {line} periods_a={sorted(pa_set)} periods_b={sorted(pb_set)}"
            )
        self.logger.info("CHK-SPI-RATIO PASS %s", line)

        # Data edge.
        if c.cpha == 1 and c.fullcyc == 1:
            self.logger.info(
                "OBS-SPI-CPHA seed=%d cpha=1 fullcyc=1 graded=0 ambiguous=1 mode=%s",
                seed,
                c.mode,
            )
        else:
            run, div = (w1, c.a) if c.a >= 1 else (win_b, c.b)
            stated, other, exempt = self._cpha_split(run, c.cpha)
            edge = "leading" if c.cpha else "trailing"
            line = (
                f"seed={seed} cpha={c.cpha} clkdiv={div} edge={edge} in_stated_half={stated} "
                f"in_other_half={other} exempt_first={exempt} mosi_xz={run.mosi_xz} "
                f"mode={c.mode}"
            )
            if run.mosi_xz:
                raise AssertionError(f"CHK-SPI-CPHA FAIL {line}")
            if stated + other < 2:
                raise AssertionError(f"CTRL-MISSING CHK-SPI-CPHA {line}")
            if other:
                raise AssertionError(f"CHK-SPI-CPHA FAIL {line}")
            self.logger.info("CHK-SPI-CPHA PASS %s", line)
            self.ran.add("CHK-SPI-CPHA")
        close_graded_window(self.logger)
        if csn_fail:
            raise AssertionError(csn_fail)
        self.ran.update(("CHK-SPI-IDLE-LEVEL", "CHK-SPI-PERIOD", "CHK-SPI-RATIO", "CHK-SPI-CSN"))

        err = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
        if not err.ok:
            raise AssertionError(
                f"SPI-ERROR FAIL seed={seed} mode={c.mode} error_status {err.fields()}"
            )

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        cells = self._plan(self.seed)
        self.ran: set[str] = set()
        close_graded_window()

        try:
            await self.bring_up_no_cpu()
            self.suppress_host_axi_transaction_info()
            self.pads = SepSpiPadSampler()
            self.pads.start()
            self.ops = SepSpiHostOps(self, clock=self.pads.now)

            ctrl = (CTRL_RESET & ~CTRL_SW_RST) | CTRL_SPIEN | CTRL_OUTPUT_EN
            await self.ops.wr(CONTROL, ctrl)
            await self.ops.wr(CSID, 0)
            err0 = field_compare(await self._err_status(), 0, ERR_STATUS_MASK)
            if not err0.ok:
                raise AssertionError(
                    f"CTL-SPI-BRINGUP FAIL seed={self.seed} error_status {err0.fields()}"
                )
            self.logger.info(
                "CTL-SPI-BRINGUP LOG seed=%d control=0x%08x error_status=0x%02x fcov=%d",
                self.seed,
                ctrl,
                err0.got & err0.mask,
                int(fcov_present()),
            )
            for c in cells:
                await self._mode_cell(c)
            await self.pads.stop()
        finally:
            close_graded_window()

        missing = [x for x in self.required_evidence if x not in self.ran]
        if missing:
            raise AssertionError(f"CTRL-MISSING seed={self.seed} checks not run: {missing}")
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, len(self.ran))
