# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP reset releases only after all three boot terms; the shadow map refuses reads before sensing.

Contract (``hw/sys/sep/doc/reset_controller.adoc``, SEP Reset Controller;
``hw/sys/sep/doc/clk_rst.adoc``, Reset Architecture;
``hw/sys/sep/doc/otp_fuse_controller.adoc``, Fuse Sensing and Boot Sequencing;
``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``, ``SMC_FUSE_SENSE_STATUS``):

* ``sep_reset_n`` and ``sep_cpu_reset_n`` stay low until ``rst_ni`` is high,
  fuse sensing is done and ``ext_boot_seq_done_i`` is high, in any arrival
  order, and rise after the last of the three terms.
* ``SMC_FUSE_SENSE_STATUS`` follows the level of ``smc_fuse_sense_done_i``.
* From the ``rst_ni`` release until ``sep_fuse_sense_done_o`` rises, a read of
  the shadow map answers SLVERR. After sensing the same word reads OKAY with the
  staged word.

Each leaf runs three cold boots with a real sense of a staged image: a
calibration boot (graded window closed) that measures the sense time T in
``clk_i`` cycles, the error-injection epoch (``ext_boot_seq_done_i`` held low for
2 T plus a drawn extra after sensing, "H = yes") and one drawn epoch from
BOOT_FIRST, BOOT_WITH_RST, BOOT_MID and BOOT_AFTER_SENSE with H = no (weights 2,
2, 2, 1), in a drawn order. T places stimulus only and is never an expected
value. Two testlist entries run this module: the normal entry and the
``_smc_hold`` entry with ``+sep_smc_fuse_sense_hold``, which holds the bench SMC
fuse-sense model low from time 0.

Checkers:
  CHK-REL-GATE      in each epoch, both reset taps read 0 on every ``clk_i``
                    sample from the ``rst_ni`` release through the sample of the
                    last term, and both rise within the release bound after it.
                    On VCS the ``sep_reset_n`` tap is also never X while
                    ``rst_ni`` is low.
  CHK-REL-HOLD      in the H = yes epoch both taps read 0 for the whole hold (at
                    least 2 T samples after the sense rise) and rise after
                    ``ext_boot_seq_done_i`` rises.
  CHK-SMC-FOLLOW    every 64-bit poll of ``SMC_FUSE_SENSE_STATUS`` reads the
                    bench SMC input level: 0 in the hold leaf, 1 in the normal
                    leaf; bits 63:1 are masked and logged.
  CHK-PRESENSE      every window probe whose R handshake falls while
                    ``sep_fuse_sense_done_o`` is 0 answers SLVERR; each epoch
                    has at least one such probe.
  CHK-PRESENSE-CTL  after both taps rise, the same words read OKAY with the
                    staged word of the image (the golden is the staged image,
                    not a DUT read). Words staged 0 stay graded, and each epoch
                    compares at least one word with a nonzero staged value, so
                    a dead read that returns 0 fails; the zero-valued words are
                    logged in ``CTL-PRESENSE-WORDS``.

Controls and observations: in BOOT_FIRST, BOOT_WITH_RST and BOOT_MID the
sensing is the last term, so those cells are controls of CHK-REL-GATE. The
``SEP_FUSE_SENSE_STATUS`` polls are logged as ``OBS-SENSE-POLL``.

Image I: ``LC_STATE`` from {TEST_DEV, RMA_SIP, RMA_CHIPLET} and ``SIP_DIS`` /
``SYS_DIS`` from the DV set ``_DIS_VECTORS`` (the disable-vector pairs of the
real-sense fabric and eFuse tests). No ``SEC_DIS`` token is presented. The image
is written before the first ``rst_ni`` edge, which loads it into the eFuse bank
model.

Environment bounds (not from the specification): the tap rise after the last
term within ``_REL_BOUND`` ``clk_i`` cycles, sensing within ``_SENSE_BOUND``
cycles of the release, and the bench SMC input high within ``_SMC_BOUND`` cycles.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense, Verilator and VCS;
the X check of CHK-REL-GATE runs on VCS only. RANDCFG.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import Event, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SHADOW_BASE
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_lcc_golden import LC_RMA_CHIP_0, LC_RMA_SIP_0, LC_TEST_DEV, lc_state_name
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

TEST = "sep_boot_release_terms_test"

RESP_OKAY = 0
RESP_SLVERR = 2
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

SMC_STATUS = SEP_CPU_CTRL.addr("SMC_FUSE_SENSE_STATUS")
SMC_FIELD = SEP_CPU_CTRL.field_mask("SMC_FUSE_SENSE_STATUS", "smc_fuse_sense_done")
SEP_STATUS = SEP_CPU_CTRL.addr("SEP_FUSE_SENSE_STATUS")
SEP_FIELD = SEP_CPU_CTRL.field_mask("SEP_FUSE_SENSE_STATUS", "sep_fuse_sense_done")

BOOT_FIRST = "BOOT_FIRST"
BOOT_WITH_RST = "BOOT_WITH_RST"
BOOT_MID = "BOOT_MID"
BOOT_AFTER = "BOOT_AFTER_SENSE_H0"
BOOT_HOLD = "BOOT_AFTER_SENSE_H1"
# Drawn epoch E with the weights 2, 2, 2, 1.
_EPOCH_WEIGHTS = ((BOOT_FIRST, 2), (BOOT_WITH_RST, 2), (BOOT_MID, 2), (BOOT_AFTER, 1))

_LC_SET = (LC_TEST_DEV, LC_RMA_SIP_0, LC_RMA_CHIP_0)
# DV set of (SIP_DIS, SYS_DIS) pairs: the disable vectors the real-sense fabric
# and eFuse tests stage, so the inbound filter stays in a state those tests use.
_DIS_VECTORS = (
    (0x0F0F_0F0F_0F0F_0F0F, 0x00FF_00FF_00FF_00FF),
    (0x0F0F_0F0F_0F0F_0F0C, 0x00FF_00FF_00FF_00FC),
)

_CAL_W = 20
_SENSE_BOUND = 20_000
_REL_BOUND = 64
_SMC_BOUND = 1_000
_FRAC_BITS = 32
_M64 = (1 << 64) - 1


def _frac(raw: int) -> float:
    return raw / (1 << _FRAC_BITS)


def _scaled(raw: int, span: int) -> int:
    """1 + floor(u * span) for the fraction u = raw / 2^32, in integer arithmetic."""
    return 1 + ((raw * span) >> _FRAC_BITS)


def _bit(sig) -> int | None:
    """One sampled bit; None when it resolves to X or Z."""
    v = sig.value
    if not v.is_resolvable:
        return None
    return int(v) & 1


class _Epoch:
    """Draws and records of one epoch."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.w = 0
        self.delay = 0
        self.u_m = 0
        self.words: list[int] = []
        self.u_probe: list[int] = []
        self.rec: list[dict] = []
        self.probes: list[dict] = []


@pyuvm.test()
class sep_boot_release_terms_test(sep_base_test):
    """sep_reset_n waits for rst_ni, sensing and ext_boot_seq_done_i; the map refuses reads before sensing."""

    required_evidence = (
        "CHK-REL-GATE",
        "CHK-REL-HOLD",
        "CHK-SMC-FOLLOW",
        "CHK-PRESENSE",
        "CHK-PRESENSE-CTL",
    )

    # -- draws -------------------------------------------------------------

    def _draw(self, rng: SepSeededRng) -> None:
        log = self.logger
        pick = rng.randrange(sum(w for _, w in _EPOCH_WEIGHTS))
        for kind, weight in _EPOCH_WEIGHTS:
            if pick < weight:
                drawn = kind
                break
            pick -= weight
        log.info("DRAW epoch_E=%s", drawn)
        hold_first = rng.randrange(2) == 0
        self.epochs = [_Epoch(BOOT_HOLD), _Epoch(drawn)]
        if not hold_first:
            self.epochs.reverse()
        log.info("DRAW order=%s", ",".join(e.kind for e in self.epochs))
        for ep in self.epochs:
            ep.w = rng.randrange(2, 41)
            log.info("DRAW W[%s]=%d", ep.kind, ep.w)
        self.lc_raw = rng.choice(_LC_SET)
        self.sip_dis, self.sys_dis = rng.choice(_DIS_VECTORS)
        log.info(
            "DRAW image LC_STATE=%s SIP_DIS=0x%016x SYS_DIS=0x%016x",
            lc_state_name(self.lc_raw),
            self.sip_dis,
            self.sys_dis,
        )
        for ep in self.epochs:
            if ep.kind == BOOT_FIRST:
                # The term falls with rst_ni and rises d clocks before the
                # release, so it is low for at least one clock with rst_ni low.
                ep.delay = rng.randrange(1, ep.w)
                log.info("DRAW delay[%s]=%d clocks before the release", ep.kind, ep.delay)
            elif ep.kind == BOOT_WITH_RST:
                ep.delay = 0
                log.info("DRAW delay[%s]=0 (the release clock)", ep.kind)
            elif ep.kind == BOOT_MID:
                ep.u_m = rng.getrandbits(_FRAC_BITS)
                log.info("DRAW u_m[%s]=%.9f", ep.kind, _frac(ep.u_m))
            elif ep.kind == BOOT_AFTER:
                ep.delay = rng.randrange(1, 401)
                log.info("DRAW delay[%s]=%d clocks after sense done", ep.kind, ep.delay)
            else:
                ep.delay = rng.randrange(0, 401)
                log.info("DRAW hold_extra[%s]=%d clocks (added to 2T)", ep.kind, ep.delay)
        for ep in self.epochs:
            n = rng.randrange(3, 9)
            ep.words = [rng.randrange(0, 256)]
            for _ in range(n - 1):
                ep.words.append(rng.randrange(0, 256))
                ep.u_probe.append(rng.getrandbits(_FRAC_BITS))
            ep.u_probe.sort()
            log.info(
                "DRAW probes[%s] N=%d words=%s u=%s",
                ep.kind,
                n,
                ep.words,
                ",".join(f"{_frac(u):.6f}" for u in ep.u_probe),
            )
        self.n_polls = rng.randrange(8, 65)
        log.info("DRAW n_polls=%d", self.n_polls)

    # -- calibration -------------------------------------------------------

    async def _calibrate(self) -> int:
        """Cold boot with ext_boot_seq_done_i at 1; return T in clk_i cycles."""
        dut = cocotb.top
        self.drive_idle_defaults(dut, cpu_run=False)
        await self.assert_cold_reset(dut)
        self.start_clocks(dut)
        for _ in range(_CAL_W):
            await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 1
        self.cfg.reset_done.set()
        t = None
        for cyc in range(1, _SENSE_BOUND + 1):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if t is None and self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True):
                t = cyc
            if (
                t is not None
                and self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True)
                and self.rd(dut.sep_cpu_reset_n_o, allow_unknown=True)
            ):
                break
        else:
            raise AssertionError(
                f"calibration boot: sense_done={t} and both reset taps not high within "
                f"{_SENSE_BOUND} clk_i cycles of the rst_ni release"
            )
        await RisingEdge(dut.clk_i)
        self._check_efuse_shadow_after_sense()
        self.logger.info(
            "CAL-BOOT LOG: W=%d T=%d clk_i cycles (release to sep_fuse_sense_done_o); taps high "
            "at cycle %d",
            _CAL_W,
            t,
            cyc,
        )
        return t

    # -- one epoch -----------------------------------------------------------

    async def _probe_runner(self, ep: _Epoch, events: list[Event]) -> None:
        for i, idx in enumerate(ep.words):
            await events[i].wait()
            seq = SepAxiAccessSeq(
                f"presense_probe{i}",
                op=SepAxiOp.READ,
                addr=SHADOW_BASE + 4 * idx,
                length=4,
                size=2,
                allow_ungraded_read_resp=True,
            )
            await self.start_seq(seq)
            ep.probes[i]["resp"] = seq.resp_code
            ep.probes[i]["data"] = seq.rdata & 0xFFFF_FFFF
            ep.probes[i]["timed_out"] = seq.timed_out

    async def _run_epoch(self, ep: _Epoch, t_cal: int) -> None:
        dut = cocotb.top
        clk = dut.clk_i
        done_flag = {"stop": False}

        async def sampler() -> None:
            while not done_flag["stop"]:
                await RisingEdge(clk)
                await ReadOnly()
                ep.rec.append(
                    {
                        "sep": _bit(dut.dbg_sep_reset_n_o),
                        "cpu": _bit(dut.sep_cpu_reset_n_o),
                        "done": _bit(dut.sep_fuse_sense_done_o),
                        "ext": _bit(dut.ext_boot_seq_done_i),
                        "rst": _bit(dut.rst_ni),
                        "r_hs": bool(
                            _bit(dut.s_axi_rvalid)
                            and _bit(dut.s_axi_rready)
                            and _bit(dut.s_axi_rlast)
                        ),
                        "rresp": (int(dut.s_axi_rresp.value) & 0x3)
                        if dut.s_axi_rresp.value.is_resolvable
                        else None,
                    }
                )

        w = ep.w
        release_k = w
        probe_k = [release_k + 1] + [release_k + _scaled(u, t_cal - 1) for u in ep.u_probe]
        ep.probes = [{"word": idx, "target": k} for idx, k in zip(ep.words, probe_k)]
        events = [Event() for _ in ep.words]
        if ep.kind == BOOT_FIRST:
            ext_k: int | None = release_k - ep.delay
        elif ep.kind == BOOT_WITH_RST:
            ext_k = release_k
        elif ep.kind == BOOT_MID:
            ep.delay = _scaled(ep.u_m, t_cal - 1)
            ext_k = release_k + ep.delay
            self.logger.info(
                "PLACE BOOT_MID u_m=%.9f T=%d -> %d clocks after the release",
                _frac(ep.u_m),
                t_cal,
                ep.delay,
            )
        else:
            ext_k = None  # placed from the sampled sense rise
        after = ep.delay if ep.kind == BOOT_AFTER else 2 * t_cal + ep.delay
        for i, (u, k) in enumerate(zip([None, *ep.u_probe], probe_k)):
            self.logger.info(
                "PLACE probe%d word=%d u=%s -> issue %d clocks after the release",
                i,
                ep.words[i],
                "fixed" if u is None else f"{_frac(u):.6f}",
                k - release_k,
            )

        samp = cocotb.start_soon(sampler())
        await RisingEdge(clk)
        # k = 0: the assert edge. The sampler records this edge as rec[0].
        dut.rst_ni.value = 0
        dut.ext_boot_seq_done_i.value = 0
        runner = cocotb.start_soon(self._probe_runner(ep, events))
        k = 0
        sense_k = None
        deadline = release_k + _SENSE_BOUND
        while True:
            await RisingEdge(clk)
            k += 1
            if k == release_k:
                dut.rst_ni.value = 1
            if ext_k is not None and k == ext_k:
                dut.ext_boot_seq_done_i.value = 1
            for i, pk in enumerate(probe_k):
                if k == pk:
                    events[i].set()
            # The samples rec[0 .. k-1] are complete at this edge.
            if sense_k is None and k > release_k:
                for i in range(release_k, len(ep.rec)):
                    if ep.rec[i]["done"] == 1:
                        sense_k = i
                        break
                if sense_k is not None and ext_k is None:
                    ext_k = sense_k + after
                    self.logger.info(
                        "PLACE %s sense rise at sample %d -> term at sample %d",
                        ep.kind,
                        sense_k,
                        ext_k,
                    )
                    if ext_k <= k:
                        raise AssertionError(
                            f"{ep.kind}: placed term sample {ext_k} is already past ({k})"
                        )
            if sense_k is None and k > deadline:
                raise AssertionError(
                    f"CHK-REL-GATE FAIL: epoch={ep.kind} sep_fuse_sense_done_o not high within "
                    f"{_SENSE_BOUND} clk_i cycles of the rst_ni release"
                )
            if ext_k is not None and sense_k is not None:
                last = max(release_k, sense_k, ext_k)
                if k > last + _REL_BOUND:
                    break
                lastrec = ep.rec[-1] if ep.rec else None
                if (
                    lastrec is not None
                    and len(ep.rec) - 1 > last
                    and lastrec["sep"] == 1
                    and lastrec["cpu"] == 1
                    and runner.done()
                ):
                    break
        # A probe whose clock was not reached issues now; its response lands
        # after sensing and is logged, not scored.
        for ev in events:
            ev.set()
        if not runner.done():
            await runner
        await RisingEdge(clk)
        done_flag["stop"] = True
        await samp
        await RisingEdge(clk)

    # -- graders -------------------------------------------------------------

    def _grade_gate(self, ep: _Epoch, t_cal: int, four_state: bool) -> None:
        rec = ep.rec
        tag = f"epoch={ep.kind}"
        t_rel = next((i for i in range(1, len(rec)) if rec[i]["rst"] == 1), None)
        assert t_rel is not None, f"CHK-REL-GATE FAIL: {tag} no rst_ni release sample"
        t_sense = next((i for i in range(t_rel, len(rec)) if rec[i]["done"] == 1), None)
        t_boot = next((i for i in range(1, len(rec)) if rec[i]["ext"] == 1), None)
        assert t_sense is not None and t_boot is not None, (
            f"CHK-REL-GATE FAIL: {tag} sense sample={t_sense} term sample={t_boot}; a term "
            "never rose in the recorded window"
        )
        for name, t0, key in (("sense_done", t_sense, "done"), ("ext_boot", t_boot, "ext")):
            fell = [i for i in range(t0, len(rec)) if rec[i][key] != 1]
            assert not fell, f"CHK-REL-GATE FAIL: {tag} {name} left 1 at samples {fell[:8]}"
        terms = {"rst_ni": t_rel, "sep_fuse_sense_done_o": t_sense, "ext_boot_seq_done_i": t_boot}
        last = max(terms.values())
        last_name = max(terms, key=lambda n: (terms[n], n == "ext_boot_seq_done_i"))
        premature = [i for i in range(t_rel, last + 1) if rec[i]["sep"] != 0 or rec[i]["cpu"] != 0]
        assert not premature, (
            f"CHK-REL-GATE FAIL: {tag} reset tap not 0 before the last term at samples "
            f"{premature[:8]} (sep_reset_n/sep_cpu_reset_n="
            f"{[(rec[i]['sep'], rec[i]['cpu']) for i in premature[:8]]}); "
            f"t_rst_rel={t_rel} t_sense={t_sense} t_boot={t_boot} last={last_name}"
        )
        sep_rise = next((i for i in range(last + 1, len(rec)) if rec[i]["sep"] == 1), None)
        cpu_rise = next((i for i in range(last + 1, len(rec)) if rec[i]["cpu"] == 1), None)
        timeout_ok = (
            sep_rise is not None
            and cpu_rise is not None
            and sep_rise - last <= _REL_BOUND
            and cpu_rise - last <= _REL_BOUND
        )
        assert timeout_ok, (
            f"CHK-REL-GATE FAIL: {tag} taps did not rise within {_REL_BOUND} clk_i cycles of "
            f"the last term ({last_name} at sample {last}): sep_reset_n rise={sep_rise} "
            f"sep_cpu_reset_n rise={cpu_rise}"
        )
        x_low = 0
        if four_state:
            x_low = sum(1 for r in rec if r["rst"] == 0 and r["sep"] is None)
            assert x_low == 0, (
                f"CHK-REL-GATE FAIL: {tag} sep_reset_n tap is X on {x_low} sample(s) with "
                "rst_ni low"
            )
        self.logger.info(
            "CHK-REL-GATE PASS: order=%s t_rst_rel=%d t_sense=%d t_boot=%d t_sep_rst_rise=%d "
            "t_cpu_rst_rise=%d last_term=%s premature_high_cycles=0 timeout_ok=1 "
            "rel_bound=%d x_while_rst_low=%s",
            ep.kind,
            t_rel,
            t_sense,
            t_boot,
            sep_rise,
            cpu_rise,
            last_name,
            _REL_BOUND,
            x_low if four_state else "not-graded(2-state)",
        )
        ep.t = {"rel": t_rel, "sense": t_sense, "boot": t_boot, "sep_rise": sep_rise}
        if ep.kind == BOOT_HOLD:
            self._grade_hold(ep, t_cal)

    def _grade_hold(self, ep: _Epoch, t_cal: int) -> None:
        rec = ep.rec
        t_sense, t_boot, sep_rise = ep.t["sense"], ep.t["boot"], ep.t["sep_rise"]
        held = t_boot - t_sense
        assert held >= 2 * t_cal, (
            f"CHK-REL-HOLD FAIL: the hold lasted {held} samples, less than 2T={2 * t_cal}; the "
            "epoch did not hold the term after sensing"
        )
        high = [i for i in range(t_sense, t_boot + 1) if rec[i]["sep"] != 0 or rec[i]["cpu"] != 0]
        assert not high, (
            f"CHK-REL-HOLD FAIL: a reset tap was not 0 during the hold at samples {high[:8]}"
        )
        cpu_rise = next(i for i in range(t_boot + 1, len(rec)) if rec[i]["cpu"] == 1)
        self.logger.info(
            "CHK-REL-HOLD PASS: held=%d cycles sep_reset_n=0 sep_cpu_reset_n=0, rose %d cycles "
            "after ext_boot_seq_done_i (sep_cpu_reset_n %d); hold=2T+%d with T=%d",
            held,
            sep_rise - t_boot,
            cpu_rise - t_boot,
            ep.delay,
            t_cal,
        )

    def _grade_presense(self, ep: _Epoch) -> None:
        rec = ep.rec
        hs = [i for i, r in enumerate(rec) if r["r_hs"]]
        assert len(hs) == len(ep.probes), (
            f"CHK-PRESENSE FAIL: epoch={ep.kind} saw {len(hs)} R handshakes on s_axi for "
            f"{len(ep.probes)} probes"
        )
        hits = 0
        for i, (p, cyc) in enumerate(zip(ep.probes, hs)):
            assert not p["timed_out"], f"CHK-PRESENSE FAIL: epoch={ep.kind} probe{i} timed out"
            assert rec[cyc]["rresp"] == p["resp"], (
                f"CHK-PRESENSE FAIL: epoch={ep.kind} probe{i} handshake rresp={rec[cyc]['rresp']} "
                f"but the master returned resp={p['resp']}"
            )
            p["cyc"] = cyc
            p["done_at_resp"] = rec[cyc]["done"]
            if rec[cyc]["done"] != 0:
                self.logger.info(
                    "OBS-PRESENSE-LATE: epoch=%s probe%d word=%d cyc=%d resp=%s done_at_resp=%s "
                    "(not scored)",
                    ep.kind,
                    i,
                    p["word"],
                    cyc,
                    _RESP_NAME.get(p["resp"], p["resp"]),
                    rec[cyc]["done"],
                )
                continue
            assert p["resp"] == RESP_SLVERR, (
                f"CHK-PRESENSE FAIL: epoch={ep.kind} probe{i} word={p['word']} cyc={cyc} "
                f"resp={_RESP_NAME.get(p['resp'], p['resp'])} data=0x{p['data']:08x} with "
                "sep_fuse_sense_done_o=0, expected SLVERR"
            )
            hits += 1
            self.logger.info(
                "CHK-PRESENSE PASS: epoch=%s hit=%d cyc=%d word=%d resp=SLVERR done_at_resp=0",
                ep.kind,
                i,
                cyc,
                p["word"],
            )
        assert hits >= 1, (
            f"CHK-PRESENSE FAIL: epoch={ep.kind} no probe answered inside the pre-sense window"
        )

    def _ensure_nonzero_word(self, rng: SepSeededRng, image) -> None:
        """Make each epoch probe at least one word whose staged value is nonzero.

        A word staged 0 (the unlocked LOCKS words 0 to 2) stays graded, but a
        compare made only of such words also passes on a dead read that
        returns 0. When every drawn word of an epoch is staged 0, the last
        drawn word is replaced by a drawn word with a nonzero staged value, so
        N stays as drawn.
        """
        nonzero = [w for w in range(256) if image.shadow_word(w) != 0]
        assert nonzero, "test error: the staged image has no nonzero shadow word"
        for ep in self.epochs:
            if any(image.shadow_word(w) != 0 for w in ep.words):
                continue
            old = ep.words[-1]
            ep.words[-1] = rng.choice(nonzero)
            self.logger.info(
                "DRAW nonzero_word[%s]=%d replaces word %d (every drawn word staged 0)",
                ep.kind,
                ep.words[-1],
                old,
            )

    async def _presense_ctl(self, ep: _Epoch, image) -> None:
        zero_words = [w for w in ep.words if image.shadow_word(w) == 0]
        nonzero_words = [w for w in ep.words if image.shadow_word(w) != 0]
        assert nonzero_words, (
            f"CHK-PRESENSE-CTL FAIL: epoch={ep.kind} test error, every compared word is staged 0, "
            "so a dead read would pass"
        )
        for i, idx in enumerate(ep.words):
            exp = image.shadow_word(idx)
            seq = SepAxiAccessSeq(
                f"presense_ctl{i}",
                op=SepAxiOp.READ,
                addr=SHADOW_BASE + 4 * idx,
                length=4,
                size=2,
                expected=exp,
                allow_ungraded_read_resp=True,
            )
            await self.start_seq(seq)
            got = seq.rdata & 0xFFFF_FFFF
            assert seq.resp_code == RESP_OKAY and not seq.timed_out and got == exp, (
                f"CHK-PRESENSE-CTL FAIL: epoch={ep.kind} word={idx} "
                f"resp={_RESP_NAME.get(seq.resp_code, seq.resp_code)} exp=0x{exp:08x} "
                f"got=0x{got:08x}"
            )
            self.logger.info(
                "CHK-PRESENSE-CTL PASS: epoch=%s word=%d resp=OKAY exp=0x%08x got=0x%08x",
                ep.kind,
                idx,
                exp,
                got,
            )
        self.logger.info(
            "CTL-PRESENSE-WORDS: epoch=%s words=%d nonzero_expected=%s zero_expected=%s",
            ep.kind,
            len(ep.words),
            nonzero_words,
            zero_words,
        )

    async def _sense_status(self, hold: bool) -> None:
        dut = cocotb.top
        expect = 0 if hold else 1
        if not hold:
            for _ in range(_SMC_BOUND):
                await RisingEdge(dut.clk_i)
                if self.rd(dut.smc_fuse_sense_done_model, allow_unknown=True):
                    break
            else:
                raise AssertionError(
                    f"CHK-SMC-FOLLOW FAIL: bench SMC input not high within {_SMC_BOUND} cycles"
                )
        values = []
        for i in range(self.n_polls):
            level = self.rd(dut.smc_fuse_sense_done_model)
            seq = SepAxiAccessSeq(
                f"smc_status{i}", op=SepAxiOp.READ, addr=SMC_STATUS, length=8, size=3
            )
            await self.start_seq(seq)
            after = self.rd(dut.smc_fuse_sense_done_model)
            assert seq.resp_ok, f"CHK-SMC-FOLLOW FAIL: poll {i} resp={seq.resp_code}"
            assert level == expect and after == expect, (
                f"CHK-SMC-FOLLOW FAIL: bench SMC input={level}/{after} around poll {i}, the "
                f"{'hold' if hold else 'normal'} leaf requires {expect}"
            )
            fc = field_compare(seq.rdata & _M64, expect, SMC_FIELD)
            assert fc.ok, (
                f"CHK-SMC-FOLLOW FAIL: leaf={'hold' if hold else 'normal'} poll {i} "
                f"{fc.fields()} input_level={level}"
            )
            values.append(seq.rdata & SMC_FIELD)
        self.logger.info(
            "CHK-SMC-FOLLOW PASS: leaf=%s polls=%d smc_status=%d control_other_leaf=%d "
            "field_mask=0x%x",
            "hold" if hold else "normal",
            len(values),
            expect,
            1 - expect,
            SMC_FIELD,
        )
        sep_vals = []
        for i in range(self.n_polls):
            seq = SepAxiAccessSeq(
                f"sep_status{i}", op=SepAxiOp.READ, addr=SEP_STATUS, length=8, size=3
            )
            await self.start_seq(seq)
            assert seq.resp_ok, f"OBS-SENSE-POLL: poll {i} resp={seq.resp_code}"
            sep_vals.append((seq.rdata & SEP_FIELD) >> ((SEP_FIELD & -SEP_FIELD).bit_length() - 1))
        self.logger.info(
            "OBS-SENSE-POLL: polls=%d first_poll=%d ones=%d",
            len(sep_vals),
            sep_vals[0],
            sum(sep_vals),
        )

    # -- scenario --------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        hold = "sep_smc_fuse_sense_hold" in cocotb.plusargs
        rng = SepSeededRng(seed)
        self._draw(rng)
        four_state = "verilator" not in str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        self.logger.info(
            "CFG leaf=%s smc_input=%s four_state=%d",
            "hold" if hold else "normal",
            "held" if hold else "done",
            int(four_state),
        )
        close_graded_window()
        image = self.select_efuse_image(
            lc_raw=self.lc_raw, fixed={"SIP_DIS": self.sip_dis, "SYS_DIS": self.sys_dis}
        )
        self.write_efuse_image(image)

        self._ensure_nonzero_word(rng, image)
        t_cal = await self._calibrate()

        open_graded_window(TEST, self.logger)
        for ep in self.epochs:
            self.logger.info("EPOCH %s W=%d", ep.kind, ep.w)
            await self._run_epoch(ep, t_cal)
            self._grade_gate(ep, t_cal, four_state)
            self._grade_presense(ep)
            self._check_efuse_shadow_after_sense()
            await self._presense_ctl(ep, image)

        await self._sense_status(hold)
        close_graded_window(self.logger)
        self.logger.info(
            "RESULT %s seed=%d PASS checks=%d", TEST, seed, len(self.required_evidence)
        )
