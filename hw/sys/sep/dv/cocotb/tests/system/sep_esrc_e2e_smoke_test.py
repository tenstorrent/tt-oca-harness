# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy from ESRC reaches the KM through DRBG, CSRNG and EDN, and every stage matches its golden.

Proves the real entropy datapath produces genbits that the Key Manager actually
consumes, with no force on the DRBG/EDN -- only the permitted ESRC raw-noise force
(+esrc_noise_force) that makes the ring oscillators alive under Verilator. Bring-up
uses the order of the reusable sep_esrc_bringup_seq API: select internal DRBG,
configure ESRC (generators off), enable CSRNG, stage EDN commands, start the
generators, wait for a seed, then enable EDN last.

The KM only pulls from the EDN->KM stream when its own PicoRV32 requests entropy
(km_drbg_sampler asserts TREADY on a CPU DATA read or an enabled prefetch -- never
autonomously). After the TRNG reset and reinitialization sequence completes, this
test releases the KM CPU and runs a tiny KM ROM image (km_rom_entropy.parhex,
loaded via +km_rom_hex in crypto.toml) that disables the sampler read-timeout and
issues a single blocking DRBG DATA read -- making the KM genuinely consume one
genbits word (a real tvalid && tready handshake) and store it to KM SRAM word0.

This is a positive-evidence alive smoke (no vacuous pass): the force is proven to
have taken (lane-0 DUT noise_i tracks the driven bit), a seed is accumulated, the
CSRNG CTR_DRBG produces genbits, the KM consumes a word (post-mux tvalid && tready
handshake) and lands it in KM SRAM, and CSRNG/EDN err_code + recov_alert are zero.
On top of the alive checks, the CHK1..CHK5 golden-vs-probe scoreboard
(sep_drbg_scoreboard + sep_entropy_golden) runs bit-exact and strict: decorrelator
SR -> BIW+SHA whitener -> 384b seed -> CTR_DRBG genbits -> EDN/KM beats, each stage
the golden input to the next, every stage compared against its DUT probe. CHK5_pool
scores mux endpoint [2] (AXIS2 == pool native EDN beats). This smoke does not
drain the entropy-pool aperture (0x1095_0000); sep_entropy_pool_aperture_test
owns it.

Closed read path (+esrc_fifo_closed). hw/ip/entropy_source/doc/architecture.adoc:
``FIFO_CTRL.ENABLE`` gates only the FIFO write, so the DRBG seed stream continues
whatever its value, and ``FIPS_LOCK`` covers the field. This mode writes ENABLE=0
in the ESRC configuration, before any word reaches the FIFO and before the lock.
CHK2 then scores the FIFO input tap, because the FIFO stays empty, and CHK3/CHK4
grade the seed and genbits as in the default mode. Two more checks grade the read
path while words reach the DRBG seed port:

* CHK-FIFO-CLOSED: across the post-lock window, every ``FIFO_STATUS`` sample reads
  LEVEL=0 and WPTR at its reset, and the FIFO_RDATA pops set
  ``INTR_STATUS.FIFO_UNDERFLOW``, which is then cleared by W1C. The data an
  empty-FIFO pop returns is undefined (entropy_source.rdl) and is not graded.
  The window stays open until a full seed of words (SEED_WORDS) has crossed the
  seed port after the lock and the DRBG has packed a new seed.
* CHK-FIFO-ENABLE-LOCKED: under the lock a write of ENABLE=1 reads back 0, and
  LEVEL is still 0 after more seed-port words cross.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_entropy_golden import SEED_WORDS
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_esrc_bringup_seq import SepEntropyCfg, SepEsrcFifoReadPathSeq, SepEsrcRegSeq
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

CLOSED_PLUSARG = "esrc_fifo_closed"
FIFO_ENABLE_BIT = ENTROPY_SOURCE.fields("FIFO_CTRL")["ENABLE"]["bm"]
FIFO_WPTR_RESET = ENTROPY_SOURCE.fields("FIFO_STATUS")["WPTR"]["reset"]
INTR_FIFO_UNDERFLOW = ENTROPY_SOURCE.fields("INTR_STATUS")["FIFO_UNDERFLOW"]["bm"]
INTR_FIFO_OVERFLOW = ENTROPY_SOURCE.fields("INTR_STATUS")["FIFO_OVERFLOW"]["bm"]
# FIFO_RDATA pops per read-path sample, and the gap between samples.
READ_PATH_POPS = 2
READ_PATH_GAP = 40
# Bound on the cycles the closed checks wait for seed-port words.
SEED_WORD_TIMEOUT = 60_000


class _SeedPortTap:
    """Count the words ESRC offers on the DRBG seed port and the seeds they make.

    The seed port is ``entropy_stream_vld_o`` / ``entropy_stream_data_o``, the
    same strobe that drives the FIFO push. ``assembled`` counts rising edges of
    the DRBG seed-queue valid: the queue holds one seed, so each rise is a new
    384-bit seed packed from seed-port words. ``accepted`` counts rising edges
    of the CSRNG seed handshake, the event CHK3 scores.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.words = 0
        self.assembled = 0
        self.accepted = 0
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        dut = self.dut
        prev_valid = 0
        prev_hs = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if sep_base_test.rd(dut.esrc_compress_vld_o, allow_unknown=True):
                self.words += 1
            valid = sep_base_test.rd(dut.drbg_seed_valid_o, allow_unknown=True)
            hs = valid and sep_base_test.rd(dut.drbg_es_ack_o, allow_unknown=True)
            if valid and not prev_valid:
                self.assembled += 1
            if hs and not prev_hs:
                self.accepted += 1
            prev_valid = valid
            prev_hs = hs

    async def wait_flow(self, words: int, assembled: int, what: str) -> None:
        """Wait until the word and assembled-seed counts reach the targets."""
        for _ in range(SEED_WORD_TIMEOUT):
            if self.words >= words and self.assembled >= assembled:
                return
            await RisingEdge(self.dut.clk_i)
        raise AssertionError(
            f"{what} FAIL: {self.words}/{words} seed-port words and "
            f"{self.assembled}/{assembled} assembled seeds after {SEED_WORD_TIMEOUT} "
            "cycles; the window would be idle"
        )


@pyuvm.test()
class sep_esrc_e2e_smoke_test(sep_base_test):
    """The KM consumes a genbits word and stores it, and the CHK1..CHK5 scoreboard passes."""

    async def run_scenario(self) -> None:
        closed = CLOSED_PLUSARG in cocotb.plusargs
        if closed:
            cfg = SepEntropyCfg(fifo_enable=0, chk2_source="backdoor")
            self.required_evidence = (
                "CHK-ALERTS-ZERO",
                "CHK-FIFO-CLOSED",
                "CHK-FIFO-ENABLE-LOCKED",
            )
        else:
            cfg = SepEntropyCfg()
        self.logger.info(
            "entropy cfg: fifo_enable=%d fifo_ctrl=0x%08x chk2_source=%s",
            cfg.fifo_enable,
            cfg.fifo_ctrl,
            cfg.chk2_source,
        )

        await self.bring_up_no_cpu()
        tap = _SeedPortTap(cocotb.top) if closed else None

        # Shared entropy bring-up: starts the strict CHK1..CHK5 scoreboard (report()
        # fails on any stage mismatch; CHK2 actual data = AXI frontdoor FIFO_RDATA
        # by default, the FIFO input tap in the closed mode), drives the ESRC
        # noise, and runs the sep_esrc_bringup_seq config order through EDN-enable.
        # CHK5_pool golden: the entropy FIFO already pulls mux endpoint [2] from
        # reset, so this smoke also proves AXIS2==pool native routing. This smoke
        # does not drain the entropy-pool aperture (0x1095_0000).
        await self.bring_up_entropy(cfg, strict=True, score_sinks={"pool": "golden"})

        # Release the KM only after the initial TRNG reset/reinitialization. Its
        # blocking DRBG DATA read then consumes one word from the live stream.
        await self.start_seq(sep_km_release_seq("km_release"))

        # Default mode: concurrent FIFO_RDATA drain so the FIFO never overflows
        # during the long genbits/KM phase (forked after the last bring-up write so
        # it owns the AXI sequencer during the signal-probe waits). Closed mode:
        # sample the read path over the same phase instead.
        if closed:
            window = await self._open_read_path_window(tap)
        else:
            self.start_fifo_drain()

        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.logger.info("CSRNG genbits produced")

        assert await self.wait_km_entropy_handshake(), (
            "KM never consumed an entropy word (km_entropy tvalid && tready)"
        )
        self.logger.info("KM consumed a genbits word (post-mux handshake)")

        assert await self.wait_km_consumed_word(), (
            "KM consumed a word but never stored it to SRAM (CPU wedged?)"
        )
        self.logger.info("KM landed the consumed entropy word in SRAM word0")

        await self.check_entropy_alerts_zero()
        self.logger.info("ESRC->DRBG->CSRNG->EDN->KM alive; KM consumed entropy; alerts clean")

        if closed:
            await self._close_read_path_window(tap, window)
            await self._check_fifo_enable_locked(tap)
        else:
            await self.stop_fifo_drain()
        assert self.drbg_sb.report()

    # --- closed read path ----------------------------------------------------
    async def _open_read_path_window(self, tap: _SeedPortTap) -> dict:
        """Start sampling FIFO_STATUS and FIFO_RDATA; the lock is already set."""
        intr = SepEsrcRegSeq("esrc_intr_pre", reg="INTR_STATUS")
        await self.start_seq(intr)
        # The test pops FIFO_RDATA nowhere before this point, so both FIFO
        # status bits must still be at reset: no pop of an empty FIFO, no push
        # dropped while full.
        assert intr.rdata & (INTR_FIFO_UNDERFLOW | INTR_FIFO_OVERFLOW) == 0, (
            f"CHK-FIFO-CLOSED FAIL: INTR_STATUS=0x{intr.rdata:08x} has a FIFO status bit "
            "set before the first FIFO_RDATA pop"
        )
        window = {
            "words0": tap.words,
            "assembled0": tap.assembled,
            "accepted0": tap.accepted,
            "samples": [],
            "stop": False,
        }

        async def _sample() -> None:
            while not window["stop"]:
                seq = SepEsrcFifoReadPathSeq("esrc_fifo_read_path", reads=READ_PATH_POPS)
                await self.start_seq(seq)
                window["samples"].append((seq.level, seq.wptr))
                await ClockCycles(cocotb.top.clk_i, READ_PATH_GAP)

        window["task"] = cocotb.start_soon(_sample())
        return window

    async def _close_read_path_window(self, tap: _SeedPortTap, window: dict) -> None:
        """Keep the window open for a full seed of words and one new seed, then grade it."""
        await tap.wait_flow(
            window["words0"] + SEED_WORDS, window["assembled0"] + 1, "CHK-FIFO-CLOSED"
        )
        window["stop"] = True
        await window["task"]
        words = tap.words - window["words0"]
        assembled = tap.assembled - window["assembled0"]
        accepted = tap.accepted - window["accepted0"]
        samples = window["samples"]
        assert samples, "CHK-FIFO-CLOSED FAIL: the read path was never sampled"
        for idx, (level, wptr) in enumerate(samples):
            assert level == 0 and wptr == FIFO_WPTR_RESET, (
                f"CHK-FIFO-CLOSED FAIL: sample {idx} read FIFO_STATUS LEVEL={level} "
                f"WPTR={wptr} with FIFO_CTRL.ENABLE=0 (expected LEVEL=0 WPTR={FIFO_WPTR_RESET})"
            )
        pops = len(samples) * READ_PATH_POPS

        # The pops reached the FIFO: each one found it empty and latched
        # FIFO_UNDERFLOW. No push was dropped, so FIFO_OVERFLOW stays clear.
        intr = SepEsrcRegSeq("esrc_intr_post", reg="INTR_STATUS")
        await self.start_seq(intr)
        assert intr.rdata & INTR_FIFO_UNDERFLOW and not intr.rdata & INTR_FIFO_OVERFLOW, (
            f"CHK-FIFO-CLOSED FAIL: INTR_STATUS=0x{intr.rdata:08x} after {pops} empty "
            "FIFO_RDATA pops; expected FIFO_UNDERFLOW=1 FIFO_OVERFLOW=0"
        )
        clr = SepEsrcRegSeq("esrc_intr_clr", reg="INTR_STATUS", wdata=INTR_FIFO_UNDERFLOW)
        await self.start_seq(clr)
        assert not clr.rdata & INTR_FIFO_UNDERFLOW, (
            f"CHK-FIFO-CLOSED FAIL: INTR_STATUS=0x{clr.rdata:08x} after a W1C of FIFO_UNDERFLOW"
        )
        self.logger.info(
            "CHK-FIFO-CLOSED PASS: FIFO_CTRL.ENABLE=0 under FIPS_LOCK; %d FIFO_STATUS samples "
            "read LEVEL=0 WPTR=%d while %d seed-port words crossed and the DRBG assembled "
            "%d seed(s) and CSRNG accepted %d (bring-up to here: %d words, %d assembled, "
            "%d accepted); %d FIFO_RDATA pops set "
            "FIFO_UNDERFLOW (0x%08x), W1C cleared it (0x%08x)",
            len(samples),
            FIFO_WPTR_RESET,
            words,
            assembled,
            accepted,
            tap.words,
            tap.assembled,
            tap.accepted,
            pops,
            intr.rdata,
            clr.rdata,
        )

    async def _check_fifo_enable_locked(self, tap: _SeedPortTap) -> None:
        """Under the lock, a write of ENABLE=1 is refused and the FIFO stays empty."""
        poke = ENTROPY_SOURCE.value("FIFO_CTRL", ENABLE=1)
        ctrl = SepEsrcRegSeq("esrc_fifo_ctrl_poke", reg="FIFO_CTRL", wdata=poke)
        await self.start_seq(ctrl)
        assert not ctrl.rdata & FIFO_ENABLE_BIT, (
            f"CHK-FIFO-ENABLE-LOCKED FAIL: FIFO_CTRL read 0x{ctrl.rdata:08x} after a write "
            f"of 0x{poke:08x} under FIPS_LOCK; ENABLE must stay 0"
        )
        words0 = tap.words
        await tap.wait_flow(words0 + SEED_WORDS, 0, "CHK-FIFO-ENABLE-LOCKED")
        probe = SepEsrcFifoReadPathSeq("esrc_fifo_status_post_poke", reads=0)
        await self.start_seq(probe)
        assert probe.level == 0 and probe.wptr == FIFO_WPTR_RESET, (
            f"CHK-FIFO-ENABLE-LOCKED FAIL: FIFO_STATUS LEVEL={probe.level} WPTR={probe.wptr} "
            f"after {tap.words - words0} seed-port words following the refused write"
        )
        self.logger.info(
            "CHK-FIFO-ENABLE-LOCKED PASS: FIFO_CTRL held 0x%08x after a write of 0x%08x under "
            "FIPS_LOCK, and LEVEL=0 WPTR=%d after %d more seed-port words",
            ctrl.rdata,
            poke,
            probe.wptr,
            tap.words - words0,
        )
