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
* CHK-FIFO-ENABLE-LOCKED: under the lock a write of ENABLE=1 and
  ENTROPY_CHURN_ENABLE=1 completes with a B response on the bus, both fields
  read back at the value stored before the lock, and LEVEL is still 0 after
  more seed-port words cross. The response code of that write is logged as
  OBS-FIFO-ENABLE-LOCKED-RESP: no specification states it.

FCOV owner window: the leaf opens its window before the entropy bring-up and
closes it at the end. The sampler holds each conditioner-to-seed and read-path
event of the window as pending, and samples it only on the rise of the pass
label ``esrc_e2e_pass``, which the leaf writes after every check of the run,
the strict scoreboard report included, passed. A FAIL closes the window first,
so no pending event of a failing run samples.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_entropy_golden import SEED_WORDS
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_esrc_e2e_pass
from pyuvm import uvm_sequence
from sep_base_test import sep_base_test
from sep_reg_meta import CSRNG, EDN, ENTROPY_SOURCE, sym
from seq_lib.sep_esrc_bringup_seq import (
    ESRC_FIFO_CTRL,
    SepEntropyCfg,
    SepEsrcFifoReadPathSeq,
    SepEsrcRegSeq,
)
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

TEST = "sep_esrc_e2e_smoke_test"
CLOSED_PLUSARG = "esrc_fifo_closed"
FIFO_ENABLE_BIT = ENTROPY_SOURCE.fields("FIFO_CTRL")["ENABLE"]["bm"]
FIFO_CHURN_BIT = ENTROPY_SOURCE.fields("FIFO_CTRL")["ENTROPY_CHURN_ENABLE"]["bm"]
# The named FIFO_CTRL fields. Both are locked by FIPS_LOCK.LOCK
# (hw/ip/entropy_source/regs/entropy_source.rdl:269, :275).
FIFO_CTRL_FIELDS = FIFO_ENABLE_BIT | FIFO_CHURN_BIT
FIFO_WPTR_RESET = ENTROPY_SOURCE.fields("FIFO_STATUS")["WPTR"]["reset"]
INTR_FIFO_UNDERFLOW = ENTROPY_SOURCE.fields("INTR_STATUS")["FIFO_UNDERFLOW"]["bm"]
INTR_FIFO_OVERFLOW = ENTROPY_SOURCE.fields("INTR_STATUS")["FIFO_OVERFLOW"]["bm"]
# FIFO_RDATA pops per read-path sample, and the gap between samples.
READ_PATH_POPS = 2
READ_PATH_GAP = 40
# Bound on the cycles the closed checks wait for seed-port words.
SEED_WORD_TIMEOUT = 60_000
# CSRNG software port. The instantiate word is the RDL reset value of EDN
# BOOT_INS_CMD (0x901: acmd instantiate, clen 0, flag0 false), so CSRNG takes its
# seed from the entropy source (csrng.adoc CMD_REQ).
CSRNG_CMD_REQ = sym("CSRNG_CMD_REQ_REG_ADDR")
CSRNG_SW_CMD_STS = sym("CSRNG_SW_CMD_STS_REG_ADDR")
CS_STS_RDY = CSRNG.fields("SW_CMD_STS")["CMD_RDY"]["bm"]
CS_STS_ACK = CSRNG.fields("SW_CMD_STS")["CMD_ACK"]["bm"]
CS_STS_STS = CSRNG.fields("SW_CMD_STS")["CMD_STS"]
SW_INSTANTIATE = EDN.reset("BOOT_INS_CMD")
# SW_CMD_STS polls (one bus read each) before the software command gives up.
SW_CMD_POLLS = 400


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


class _EsrcWriteSeq(uvm_sequence):
    """One single-beat entropy_source register write that keeps its B response.

    ``resp_list`` holds the B response codes the bus returned (empty when no
    write was issued); ``timed_out`` is True when the B never came.
    """

    def __init__(self, name: str, *, addr: int, wdata: int) -> None:
        super().__init__(name)
        self.addr = addr
        self.wdata = wdata
        self.timed_out = False
        self.resp_list: tuple[int, ...] = ()

    async def body(self) -> None:
        item = SepAxiItem(f"{self.get_name()}_wr")
        item.op = SepAxiOp.WRITE
        item.addr = self.addr
        item.length = 4
        item.wdata = self.wdata
        await self.start_item(item)
        await self.finish_item(item)
        self.timed_out = item.timed_out
        self.resp_list = tuple(item.resp_list)


class _CsrngSwInstantiateSeq(uvm_sequence):
    """One CSRNG software-port instantiate: wait CMD_RDY, write CMD_REQ, wait CMD_ACK.

    ``ready`` and ``acked`` say whether each poll saw its bit within
    ``SW_CMD_POLLS`` reads; ``sts`` is the last ``SW_CMD_STS`` value.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.ready = False
        self.acked = False
        self.sts = -1

    async def _rd(self, addr: int) -> int:
        item = SepAxiItem(f"{self.get_name()}_rd")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def _poll(self, mask: int) -> bool:
        for _ in range(SW_CMD_POLLS):
            self.sts = await self._rd(CSRNG_SW_CMD_STS)
            if self.sts & mask:
                return True
        return False

    async def body(self) -> None:
        self.ready = await self._poll(CS_STS_RDY)
        if not self.ready:
            return
        item = SepAxiItem(f"{self.get_name()}_wr")
        item.op = SepAxiOp.WRITE
        item.addr = CSRNG_CMD_REQ
        item.length = 4
        item.wdata = SW_INSTANTIATE
        await self.start_item(item)
        await self.finish_item(item)
        self.acked = await self._poll(CS_STS_ACK)


@pyuvm.test()
class sep_esrc_e2e_smoke_test(sep_base_test):
    """The KM consumes a genbits word and stores it, and the CHK1..CHK5 scoreboard passes."""

    async def run_scenario(self) -> None:
        closed = CLOSED_PLUSARG in cocotb.plusargs
        if closed:
            cfg = SepEntropyCfg(fifo_enable=0, chk2_source="backdoor")
            self.required_evidence = (
                "CHK-ALERTS-ZERO",
                "CHK-E2E-SCOREBOARD",
                "CHK-FIFO-CLOSED",
                "CHK-FIFO-ENABLE-LOCKED",
                "CHK-SEED-SW",
            )
        else:
            cfg = SepEntropyCfg()
            self.required_evidence = ("CHK-ALERTS-ZERO", "CHK-E2E-SCOREBOARD")
        self.logger.info(
            "entropy cfg: fifo_enable=%d fifo_ctrl=0x%08x chk2_source=%s",
            cfg.fifo_enable,
            cfg.fifo_ctrl,
            cfg.chk2_source,
        )

        await self.bring_up_no_cpu()
        tap = _SeedPortTap(cocotb.top) if closed else None

        set_esrc_e2e_pass(False, self.logger)
        open_graded_window(TEST, self.logger)
        try:
            await self._graded_run(cfg, closed, tap)
        except BaseException:
            # A failure may resume from ReadOnly, where no value can be written.
            await NextTimeStep()
            self._close_window()
            raise
        await self._release_pass_label()

    # --- FCOV window -----------------------------------------------------------
    def _close_window(self) -> None:
        set_esrc_e2e_pass(False, self.logger)
        close_graded_window(self.logger)

    async def _grade(self, ok: bool, text: str) -> None:
        """Raise on a failed check; the window closes before the next clock edge.

        A check can follow a wait that resumed in ReadOnly, where no value can be
        written, so a FAIL logs first, then moves to the next time step and closes
        the window there. No clock edge lies between, so nothing pending samples.
        """
        if ok:
            return
        self.logger.error("%s", text)
        await NextTimeStep()
        self._close_window()
        raise AssertionError(text)

    async def _release_pass_label(self) -> None:
        """Every check passed: pulse ``esrc_e2e_pass`` inside the window, then close it.

        The sampler takes the pending events on the rise of the label, two
        clock edges before the label drops and three before the window closes.
        """
        set_esrc_e2e_pass(True, self.logger)
        await ClockCycles(cocotb.top.clk_i, 2)
        set_esrc_e2e_pass(False, self.logger)
        await ClockCycles(cocotb.top.clk_i, 1)
        close_graded_window(self.logger)

    async def _graded_run(self, cfg: SepEntropyCfg, closed: bool, tap) -> None:
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
        # The KM firmware reads once, so its handshake is a single event: the
        # watchers start before the release, and no later step of the leaf can
        # make them miss it.
        genbits_seen = cocotb.start_soon(self.wait_genbits())
        km_hs_seen = cocotb.start_soon(self.wait_km_entropy_handshake())
        await self.start_seq(sep_km_release_seq("km_release"))

        # Default mode: concurrent FIFO_RDATA drain so the FIFO never overflows
        # during the long genbits/KM phase (forked after the last bring-up write so
        # it owns the AXI sequencer during the signal-probe waits). Closed mode:
        # sample the read path over the same phase instead.
        if closed:
            window = await self._open_read_path_window(tap)
        else:
            self.start_fifo_drain()

        await self._grade(await genbits_seen, "CSRNG CTR_DRBG never produced genbits")
        self.logger.info("CSRNG genbits produced")

        await self._grade(
            await km_hs_seen,
            "KM never consumed an entropy word (km_entropy tvalid && tready)",
        )
        self.logger.info("KM consumed a genbits word (post-mux handshake)")

        await self._grade(
            await self.wait_km_consumed_word(),
            "KM consumed a word but never stored it to KM SRAM word0",
        )
        self.logger.info("KM landed the consumed entropy word in SRAM word0")

        await self.check_entropy_alerts_zero()
        self.logger.info("ESRC->DRBG->CSRNG->EDN->KM alive; KM consumed entropy; alerts clean")

        if closed:
            await self._close_read_path_window(tap, window)
            await self._check_fifo_enable_locked(cfg, tap)
        else:
            await self._sw_instantiate_seed()
            await self.stop_fifo_drain()
        await self._grade(
            self.drbg_sb.report(),
            "sep_drbg_scoreboard: CHK1..CHK5 report has a failure",
        )
        self.logger.info(
            "CHK-E2E-SCOREBOARD PASS: strict CHK1..CHK5 entropy scoreboard report clean"
        )

    # --- second CSRNG seed ----------------------------------------------------
    async def _sw_instantiate_seed(self) -> None:
        """CHK-SEED-SW: a CSRNG software-port instantiate takes a second entropy-source seed.

        The EDN instantiate of the bring-up is the first CSRNG seed handshake of
        the window; CHK3 of the strict report grades its 384 bits. The software
        instantiate (0x901, flag0 false) makes CSRNG request one more seed
        (csrng.adoc CMD_REQ). The check needs CMD_ACK, one more CHK3 handshake,
        and each 32-bit word of that seed equal to a conditioner word of the
        golden that no earlier seed took: the CSRNG seed comes only from the
        conditioner (entropy_source architecture.adoc:148). Which of those words
        the seed packer takes once an earlier seed is packed is stated nowhere,
        so the seed bits are logged as OBS-SEED-SW-BITS, next to the next packed
        seed of the golden, and their position is not graded.
        The CMD_STS code is logged, not graded: no text states the code of a
        successful software command.
        """
        before = self.drbg_sb.results["CHK3_seed"].dut_items
        self.drbg_sb.set_graded_items(CHK3_seed=before)
        seq = _CsrngSwInstantiateSeq("csrng_sw_instantiate")
        await self.start_seq(seq)
        after = self.drbg_sb.results["CHK3_seed"].dut_items
        observed = self.drbg_sb.observed["CHK3_seed"]
        pool = set(self.drbg_sb.chain.unconsumed_seed_words())
        for _idx, exp, _act in observed:
            if exp is not None:
                pool.update((exp >> (32 * k)) & 0xFFFFFFFF for k in range(SEED_WORDS))
        foreign = [
            (idx, k, (act >> (32 * k)) & 0xFFFFFFFF)
            for idx, _exp, act in observed
            for k in range(SEED_WORDS)
            if (act >> (32 * k)) & 0xFFFFFFFF not in pool
        ]
        await self._grade(
            seq.ready and seq.acked and after > before and observed and not foreign,
            f"CHK-SEED-SW FAIL: CSRNG software instantiate 0x{SW_INSTANTIATE:03x}: "
            f"cmd_rdy={int(seq.ready)} cmd_ack={int(seq.acked)} "
            f"SW_CMD_STS=0x{seq.sts:08x}; CHK3 seed handshakes {before} -> {after}; "
            f"seed words not from the conditioner (seed, word, value): "
            f"{[(i, k, f'0x{w:08x}') for i, k, w in foreign]}",
        )
        sts = (seq.sts & CS_STS_STS["bm"]) >> CS_STS_STS["bp"]
        self.logger.info(
            "CHK-SEED-SW PASS: CSRNG software instantiate 0x%03x acknowledged; CHK3 seed "
            "handshakes %d -> %d; all %d words of seed %d are conditioner words no earlier "
            "seed took (%d candidates)",
            SW_INSTANTIATE,
            before,
            after,
            SEED_WORDS * len(observed),
            before,
            len(pool),
        )
        for idx, exp, act in self.drbg_sb.observed["CHK3_seed"]:
            self.logger.info(
                "OBS-SEED-SW-BITS: seed %d act=0x%096x next_golden=%s (logged, not graded)",
                idx,
                act,
                "none" if exp is None else f"0x{exp:096x}",
            )
        self.logger.info("OBS-SEED-SW-STS: CMD_STS %d (logged, not graded)", sts)

    # --- closed read path ----------------------------------------------------
    async def _open_read_path_window(self, tap: _SeedPortTap) -> dict:
        """Start sampling FIFO_STATUS and FIFO_RDATA; the lock is already set."""
        intr = SepEsrcRegSeq("esrc_intr_pre", reg="INTR_STATUS")
        await self.start_seq(intr)
        # The test pops FIFO_RDATA nowhere before this point, so both FIFO
        # status bits must still be at reset: no pop of an empty FIFO, no push
        # dropped while full.
        await self._grade(
            intr.rdata & (INTR_FIFO_UNDERFLOW | INTR_FIFO_OVERFLOW) == 0,
            f"CHK-FIFO-CLOSED FAIL: INTR_STATUS=0x{intr.rdata:08x} has a FIFO status bit "
            "set before the first FIFO_RDATA pop",
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
        await self._grade(bool(samples), "CHK-FIFO-CLOSED FAIL: the read path was never sampled")
        for idx, (level, wptr) in enumerate(samples):
            await self._grade(
                level == 0 and wptr == FIFO_WPTR_RESET,
                f"CHK-FIFO-CLOSED FAIL: sample {idx} read FIFO_STATUS LEVEL={level} "
                f"WPTR={wptr} with FIFO_CTRL.ENABLE=0 (expected LEVEL=0 WPTR={FIFO_WPTR_RESET})",
            )
        pops = len(samples) * READ_PATH_POPS

        # The pops reached the FIFO: each one found it empty and latched
        # FIFO_UNDERFLOW. No push was dropped, so FIFO_OVERFLOW stays clear.
        intr = SepEsrcRegSeq("esrc_intr_post", reg="INTR_STATUS")
        await self.start_seq(intr)
        await self._grade(
            bool(intr.rdata & INTR_FIFO_UNDERFLOW) and not intr.rdata & INTR_FIFO_OVERFLOW,
            f"CHK-FIFO-CLOSED FAIL: INTR_STATUS=0x{intr.rdata:08x} after {pops} empty "
            "FIFO_RDATA pops; expected FIFO_UNDERFLOW=1 FIFO_OVERFLOW=0",
        )
        clr = SepEsrcRegSeq("esrc_intr_clr", reg="INTR_STATUS", wdata=INTR_FIFO_UNDERFLOW)
        await self.start_seq(clr)
        await self._grade(
            not clr.rdata & INTR_FIFO_UNDERFLOW,
            f"CHK-FIFO-CLOSED FAIL: INTR_STATUS=0x{clr.rdata:08x} after a W1C of FIFO_UNDERFLOW",
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

    async def _check_fifo_enable_locked(self, cfg: SepEntropyCfg, tap: _SeedPortTap) -> None:
        """Under the lock, a write of both FIFO_CTRL fields is refused and the FIFO stays empty.

        Golden: the named fields keep the value the configuration stored
        before the lock (entropy_source.rdl:269, :275 "FIPS_LOCK.LOCK prevents
        software changes"). The B response of the write is the positive probe
        that the write reached the DUT; its code is logged, not graded.
        """
        stored = cfg.fifo_ctrl & FIFO_CTRL_FIELDS
        pre = SepEsrcRegSeq("esrc_fifo_ctrl_pre", reg="FIFO_CTRL")
        await self.start_seq(pre)
        poke = ENTROPY_SOURCE.value("FIFO_CTRL", ENABLE=1, ENTROPY_CHURN_ENABLE=1)
        wr = _EsrcWriteSeq("esrc_fifo_ctrl_poke", addr=ESRC_FIFO_CTRL, wdata=poke)
        await self.start_seq(wr)
        post = SepEsrcRegSeq("esrc_fifo_ctrl_post", reg="FIFO_CTRL")
        await self.start_seq(post)
        b_seen = not wr.timed_out and len(wr.resp_list) == 1
        await self._grade(
            b_seen,
            f"CHK-FIFO-ENABLE-LOCKED FAIL: no B response for the write of 0x{poke:08x} to "
            f"FIFO_CTRL (timed_out={wr.timed_out} resp_list={list(wr.resp_list)})",
        )
        await self._grade(
            (pre.rdata & FIFO_CTRL_FIELDS) == stored and (post.rdata & FIFO_CTRL_FIELDS) == stored,
            f"CHK-FIFO-ENABLE-LOCKED FAIL: FIFO_CTRL fields read 0x{pre.rdata & FIFO_CTRL_FIELDS:08x} "
            f"before and 0x{post.rdata & FIFO_CTRL_FIELDS:08x} after a write of 0x{poke:08x} "
            f"under FIPS_LOCK; expected 0x{stored:08x} both times",
        )
        self.logger.info(
            "OBS-FIFO-ENABLE-LOCKED-RESP: B response %d for the locked FIFO_CTRL write; "
            "reserved bits read 0x%08x (logged, not graded)",
            wr.resp_list[0],
            post.rdata & ~FIFO_CTRL_FIELDS & 0xFFFFFFFF,
        )
        # The DRBG seed queue holds one seed until CSRNG takes it, so a seed
        # queued after the refused write needs a CSRNG seed request: the
        # software instantiate takes the queued seed, and the leaf waits for the
        # next one.
        words0 = tap.words
        assembled0 = tap.assembled
        await self._sw_instantiate_seed()
        await tap.wait_flow(words0 + SEED_WORDS, assembled0 + 1, "CHK-FIFO-ENABLE-LOCKED")
        probe = SepEsrcFifoReadPathSeq("esrc_fifo_status_post_poke", reads=0)
        await self.start_seq(probe)
        await self._grade(
            probe.level == 0 and probe.wptr == FIFO_WPTR_RESET,
            f"CHK-FIFO-ENABLE-LOCKED FAIL: FIFO_STATUS LEVEL={probe.level} WPTR={probe.wptr} "
            f"after {tap.words - words0} seed-port words and {tap.assembled - assembled0} "
            "queued seed(s) following the refused write",
        )
        self.logger.info(
            "CHK-FIFO-ENABLE-LOCKED PASS: a write of 0x%08x to FIFO_CTRL under FIPS_LOCK got "
            "B response %d, the fields read 0x%08x before and 0x%08x after (stored 0x%08x), "
            "and LEVEL=0 WPTR=%d after %d more seed-port words and %d more queued seed(s)",
            poke,
            wr.resp_list[0],
            pre.rdata & FIFO_CTRL_FIELDS,
            post.rdata & FIFO_CTRL_FIELDS,
            stored,
            probe.wptr,
            tap.words - words0,
            tap.assembled - assembled0,
        )
