# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A scan session (test_en_i = 1 and a scan_rst_ni pulse) moves no SECURE_TM state.

RAND-REP, no_cpu on ``lsu_stub_all_live`` with real fuse sense, VCS only (the
nets can hold X across the scan pulse). The seed draws the low width ``w`` of
``scan_rst_ni`` (4 to 64 ``clk_i`` cycles; the floor is an environment
choice), its fall and release ``phase`` (10 to 90 percent of the ``clk_i``
period after a ``clk_i`` rising edge), the order of the two strap legs and
the three strap-flip cycles ``f1``, ``f2`` < ``f3`` (1 to H-1).
Every run runs the strap-0 leg, the strap-1 leg and the SEC_DIS leg (last).
``clk_wdt_i`` runs at ``P_W`` ``clk_i`` periods with its rising edge ``WDT_PHASE_PCT``
percent of a ``clk_i`` period after a ``clk_i`` rising edge (environment choice), so
``aon_rst_n`` (``rst_ni`` synchronized into ``clk_wdt_i``) releases within the tap
bound after each cold boot and no ``clk_wdt_i`` edge meets a ``clk_i`` sample.

Each leg: a cold boot with real fuse sense at the leg strap, DEMOTE_1 and
DEMOTE_2 set and locked, the Key Manager released, then the scan session:
``test_en_i`` 0 to 1, a hold, a ``scan_rst_ni`` pulse of ``w`` cycles with
``test_en_i`` = 1, a hold, ``test_en_i`` 1 to 0, a hold. With ``test_en_i`` = 1
the strap ``test_en_strap_i`` moves to the opposite of the leg strap at cycle
``f1`` of the first hold (it stays there through the pulse), back at cycle
``f2`` of the second hold and to the opposite value again at cycle ``f3``, so it
is opposite at the ``scan_rst_ni`` release and at the ``test_en_i`` fall. It is
set back after the session. Every probe is sampled on every ``clk_i`` rising
edge of the session.

Contract:

* ``hw/sys/sep/doc/test_mode.adoc`` (Entry and Exit): only a cold reset, the
  early capture under SEC_DIS and the fuse-sense completion sample the strap;
  otherwise ``SECURE_TM`` keeps its value. ``hw/sys/sep/doc/reset_controller.adoc``
  (SEP Reset Controller): ``scan_rst_ni`` replaces the outputs of
  ``u_sep_reset_sync``, the scan bypass muxes, ``u_rst_wdt_sync`` and the Key
  Manager reset conditioners; ``hw/sys/sep/doc/port_table.adoc``
  (``scan_rst_ni``): it bypasses the reset synchronizers, which include the two
  of the reference counter. ``scan_rst_ni`` is not a cold reset
  (``hw/sys/sep/doc/clk_rst.adoc``, Reset Architecture).
* ``hw/sys/sep/doc/test_mode.adoc`` (Protection While Active) and
  ``hw/sys/sep/doc/otp_fuse_controller.adoc``: while ``SECURE_TM`` = 1 the
  secret shadow outputs ``CHIPLET_UID``, ``SIP_UID``, ``SYS_UID`` and
  ``CLASS_KEY`` read zero downstream.
* ``hw/sys/sep/doc/token_processing.adoc`` (Token Submission) and
  ``hw/sys/sep/doc/security_disable.adoc`` (Reset Persistence): the computed
  digest and its valid bit survive reset and change only at a new start or a
  hash completion.

Checkers:
  CTL-SCAN-REACH        each pulse drives all 14 replaced reset nets low on
                        every clk_i edge with scan_rst_ni low (the nets of
                        sep_scan_reset_override_test, all high before).
  CHK-SCAN-TM-HOLD      secure_tm_o keeps the leg strap value (0 and 1) on
                        every sample of the session while the strap moves
                        (no cold reset and no fuse-sense completion, so no
                        sampling event). Control: at least 3 samples with
                        test_en_i = 1 and the strap opposite per session.
  CHK-SCAN-SECRET-ZERO  at strap 1 the 32 secret shadow words read 0 on every
                        sample of the session. Control: at strap 0 they read
                        the staged words before the session.
  CTL-SECDIS-SET        security_disable_o goes 0 to 1 at the SEC_DIS go with
                        the token whose digest tb_top binds.
  CHK-SCAN-SECDIS-HOLD  security_disable_o, the SEC_DIS digest and its valid
                        bit keep their values on every sample of the session.

Logged, not graded: OBS-SCAN-SENSE-HOLD (``sep_fuse_sense_done_o``),
OBS-SCAN-FEAT-HOLD (``FEAT_CTRL``, the DEMOTE state and lock bits and the
``LC_STATE`` shadow word), OBS-SCAN-CLASS1-NAME (storage names that carry
``_n0_scan``, ``demote`` or ``sense_done``), OBS-SCAN-SHADOW-WR (a ``SIP_DIS``
shadow write with ``test_en_i`` = 1 at strap 0) and OBS-SCAN-SECDIS-GO (a
mismatch SEC_DIS go with ``test_en_i`` = 1, after the last session). The
specification does not state these values under a scan reset.

The graded window (owner code of this test) is open for each session only.
"""

from __future__ import annotations

import re
from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.sep_efuse_plan import (
    CH_SEC_DIS,
    CODE_MATCH,
    CODE_MISMATCH,
    DEFAULT_VECTOR,
    FIELD_VECTORS,
    MATCH_ADDR,
    MATCH_STATUS_MASK,
    SECRET_FIELDS,
    TOKEN_OTHER,
    TOKEN_ZERO,
    feat_ctrl_profile,
    field_n_words,
    field_word,
    shadow_addr,
    words_token,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    bound_sec_dis_digest,
    probe_word,
    rst_pulse,
    sec_dis_go,
    sig_bits,
    wait_bit,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_lcc_golden import LC_PROD
from env.sep_seeded_rng import SepSeededRng
from env.sep_test_en_walk import PIN_BOUND
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_LIFECYCLE_CTRL
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_scan_mode_state_hold_test"

# The 14 replaced nets and their tb_top taps (bit 0 of km_cond_rst_probe_o is
# rst_warm_sync_n, bit 1 rst_cold_aasd_n; bit 0 of refcnt_rst_n_probe_o is the
# clk_i side of the reference counter, bit 1 the clk_ref_i side), as
# sep_scan_reset_override_test reads them.
NETS: tuple[tuple[str, str, int], ...] = (
    ("sep_reset_n", "dbg_sep_reset_n_o", 0),
    ("sep_cpu_reset_n", "sep_cpu_reset_n_o", 0),
    ("ip_rst_n[0]", "km_gated_rst_n_probe_o", 0),
    ("ip_rst_n[1]", "otbn_gated_rst_n_probe_o", 0),
    ("ip_rst_n[2]", "aes_gated_rst_n_probe_o", 0),
    ("ip_rst_n[3]", "hmac_gated_rst_n_probe_o", 0),
    ("ip_rst_n[4]", "kmac_gated_rst_n_probe_o", 0),
    ("ip_rst_n[5]", "trng_gated_rst_n_probe_o", 0),
    ("ip_rst_n[6]", "abr_gated_rst_n_probe_o", 0),
    ("aon_rst_n", "aon_rst_n_probe_o", 0),
    ("km_cond_rst[0]", "km_cond_rst_probe_o", 0),
    ("km_cond_rst[1]", "km_cond_rst_probe_o", 1),
    ("refcnt_rst[0]", "refcnt_rst_n_probe_o", 0),
    ("refcnt_rst[1]", "refcnt_rst_n_probe_o", 1),
)
N_NETS = len(NETS)

_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
M32 = 0xFFFF_FFFF

H = 32  # hold of each session step, clk_i cycles (test parameter)
PRE = 8  # samples before the test_en_i rise
P_W = 8  # clk_wdt_i period in clk_i periods
WDT_PHASE_PCT = 5  # clk_wdt_i rising edge, percent of a clk_i period after clk_i
SENSE_BOUND = 40_000
TAP_BOUND = 2_000
STM_BOUND = 16
SDIS_BOUND = 200
MATCH_READS = 400

DEMOTE_ADDR = {1: SEP_LIFECYCLE_CTRL.addr("DEMOTE_1"), 2: SEP_LIFECYCLE_CTRL.addr("DEMOTE_2")}
DEMOTE_BIT = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "demote")
LOCK_BIT = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "lock")

SECRET_WORDS: tuple[tuple[str, int], ...] = tuple(
    (f, field_word(f) + k) for f in SECRET_FIELDS for k in range(field_n_words(f))
)
SECRETS = {f: words_token(FIELD_VECTORS[DEFAULT_VECTOR[f]]) for f in SECRET_FIELDS}
LC_WORD = field_word("LC_STATE")
_CLASS1_NAME = re.compile(r"_n0_scan|demote|sense_done", re.I)


class _Cfg:
    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.w = rng.randrange(4, 65)
        self.phase = rng.randrange(10, 91)
        order = [0, 1]
        rng.shuffle(order)
        self.straps = tuple(order)
        # Strap flips with test_en_i = 1, in clk_i cycles: f1 into the hold before
        # the scan_rst_ni pulse, f2 < f3 into the hold after it.
        self.f1 = rng.randrange(1, H)
        self.f2 = rng.randrange(1, H - 1)
        self.f3 = rng.randrange(self.f2 + 1, H)


def _bit(bits: str, idx: int = 0) -> int | None:
    """Bit ``idx`` of an MSB-first bit string; None for X or Z."""
    if idx >= len(bits):
        return None
    c = bits[len(bits) - 1 - idx]
    return int(c) if c in "01" else None


def _int(bits: str) -> int | None:
    return int(bits, 2) if bits and set(bits) <= {"0", "1"} else None


def _hex(v: int | None, width: int = 8) -> str:
    return "X" if v is None else f"0x{v:0{width}x}"


@pyuvm.test()
class sep_scan_mode_state_hold_test(sep_base_test):
    """secure_tm_o, the secret mask and the SEC_DIS state hold through a scan session."""

    required_evidence = (
        "CHK-SCAN-TM-HOLD",
        "CHK-SCAN-SECRET-ZERO",
        "CHK-SCAN-SECDIS-HOLD",
    )

    # -- sampler ---------------------------------------------------------------

    def _sample(self) -> dict:
        dut: Any = cocotb.top
        nets = []
        for _n, port, b in NETS:
            nets.append(_bit(sig_bits(getattr(dut, port)), b))
        shadow = sig_bits(dut.efuse_shadow_probe_o)
        return {
            "t": int(get_sim_time("ps")),
            "te": _bit(sig_bits(dut.test_en_i)),
            "scan": _bit(sig_bits(dut.scan_rst_ni_i)),
            "strap": _bit(sig_bits(dut.test_en_strap_i)),
            "stm": _bit(sig_bits(dut.secure_tm_o)),
            "nets": nets,
            "secret": [probe_word(shadow, idx) for _f, idx in SECRET_WORDS],
            "lcw": probe_word(shadow, LC_WORD),
            "done": _bit(sig_bits(dut.sep_fuse_sense_done_o)),
            "feat": _int(sig_bits(dut.lcc_feat_ctrl_probe_o)),
            "d1": _int(sig_bits(dut.lcc_demote_state_1_probe_o)),
            "d2": _int(sig_bits(dut.lcc_demote_state_2_probe_o)),
            "l1": _bit(sig_bits(dut.lcc_demote_lock_1_probe_o)),
            "l2": _bit(sig_bits(dut.lcc_demote_lock_2_probe_o)),
            "secdis": _bit(sig_bits(dut.lcc_security_disable_probe_o)),
            "dvalid": _bit(sig_bits(dut.token_digest_sdis_valid_o)),
            "digest": _int(sig_bits(dut.token_digest_sdis_sticky_o)),
        }

    async def _sampler(self, rec: list, stop: dict) -> None:
        top: Any = cocotb.top
        while not stop["v"]:
            await RisingEdge(top.clk_i)
            await ReadOnly()
            rec.append(self._sample())

    # -- stimulus --------------------------------------------------------------

    async def _boot(self, strap: int, first: bool) -> None:
        """Cold boot with real fuse sense and the strap stable from before the release."""
        dut: Any = cocotb.top
        close_graded_window(self.logger)
        if first:
            self.drive_idle_defaults(dut, cpu_run=False)
            dut.test_en_i.value = 0
            dut.scan_rst_ni_i.value = 1
            dut.test_en_strap_i.value = strap
            await self.assert_cold_reset(dut)
            self.start_clocks(dut)
            await ClockCycles(dut.clk_i, 20)
            dut.rst_ni.value = 1
            await ClockCycles(dut.clk_i, 2)
            self.cfg.reset_done.set()
        else:
            await rst_pulse(self, strap=strap)
        await self.wait_fuse_sense(max_cycles=SENSE_BOUND)
        self.cfg.reset_done.set()
        for port in ("dbg_sep_reset_n_o", "sep_cpu_reset_n_o", "aon_rst_n_probe_o"):
            n = await wait_bit(self, port, 1, TAP_BOUND)
            await RisingEdge(dut.clk_i)
            assert n is not None, f"{port} did not read 1 within {TAP_BOUND} clk_i cycles"
        n = await wait_bit(self, "secure_tm_o", strap, STM_BOUND)
        await RisingEdge(dut.clk_i)
        assert n is not None, (
            f"CHK-SCAN-TM-HOLD FAIL: control: secure_tm_o did not read {strap} within "
            f"{STM_BOUND} cycles after sensing with the strap at {strap}"
        )
        self.logger.info("BOOT strap=%d secure_tm_o=%d after sensing", strap, strap)

    async def _demote_and_lock(self) -> None:
        for reg in (1, 2):
            for op, val in (("demote", DEMOTE_BIT), ("lock", LOCK_BIT)):
                resp = await self.fd.wr_graded_by_readback(DEMOTE_ADDR[reg], val, length=8)
                self.logger.info("DEMOTE LOG: reg=DEMOTE_%d op=%s resp=%d", reg, op, resp)

    async def _release_km(self) -> None:
        dut: Any = cocotb.top
        swrst = SepSwReset(self)
        swrst.value = await swrst.read_back()
        await swrst.release("km")
        for _ in range(TAP_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.km_cond_rst_probe_o, allow_unknown=True) == 0x3:
                break
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        base = [n for n, v in zip([x[0] for x in NETS], self._sample()["nets"]) if v != 1]
        await RisingEdge(dut.clk_i)
        assert not base, f"precondition FAIL: nets not high before the session: {base}"

    async def _shadow_write_obs(self) -> None:
        """OBS-SCAN-SHADOW-WR: a SIP_DIS shadow write with test_en_i = 1 at strap 0."""
        dut: Any = cocotb.top
        addr = shadow_addr("SIP_DIS")
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = 1
        await ClockCycles(dut.clk_i, PIN_BOUND)
        r0, before = await self.fd.rd_graded_by_data(addr)
        bit = next(i for i in range(32) if not (before >> i) & 1) if before != M32 else 0
        new = before | (1 << bit)
        wresp = await self.fd.wr_graded_by_readback(addr, new)
        r1, after = await self.fd.rd_graded_by_data(addr)
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = 0
        await ClockCycles(dut.clk_i, H)
        self.logger.info(
            "OBS-SCAN-SHADOW-WR: strap=0 test_en_i=1 field=SIP_DIS word=0 before=0x%08x "
            "wrote=0x%08x after=0x%08x landed=%d rresp=%d,%d wresp=%d",
            before,
            new,
            after,
            int(after == new),
            r0,
            r1,
            wresp,
        )

    async def _hold_flip(self, leg: str, at: dict[int, int], where: str) -> None:
        """Hold H clk_i cycles and drive the strap to ``at[n]`` after cycle ``n``."""
        dut: Any = cocotb.top
        for n in range(1, H + 1):
            await RisingEdge(dut.clk_i)
            if n in at:
                dut.test_en_strap_i.value = at[n]
                self.strap_flips.append(
                    f"leg={leg} strap->{at[n]} t={int(get_sim_time('ps'))} test_en_i=1 {where}"
                )

    async def _session(self, leg: str, strap: int) -> dict:
        """test_en_i 0 to 1, scan_rst_ni pulse, test_en_i 1 to 0, every edge sampled.

        With test_en_i = 1 the strap moves to the opposite value before the pulse
        (it stays there through the pulse), back to ``strap`` after the pulse and
        to the opposite value again before the test_en_i fall. It is set back to
        ``strap`` after the session. No cold reset and no fuse sense occur in the
        session, so none of these moves is a sampling event.
        """
        dut: Any = cocotb.top
        cfg = self.tcfg
        period_ps = self.sys_ps
        rec: list[dict] = []
        stop = {"v": False}
        task = cocotb.start_soon(self._sampler(rec, stop))
        await ClockCycles(dut.clk_i, PRE)
        open_graded_window(TEST, self.logger)
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = 1
        t_te_rise = int(get_sim_time("ps"))
        await self._hold_flip(leg, {cfg.f1: 1 - strap}, "before_pulse")
        await RisingEdge(dut.clk_i)
        await Timer(cfg.phase * period_ps // 100, unit="ps")
        dut.scan_rst_ni_i.value = 0
        t_fall = int(get_sim_time("ps"))
        for _ in range(cfg.w):
            await RisingEdge(dut.clk_i)
        await ReadOnly()
        last_edge = int(get_sim_time("ps"))
        await Timer(cfg.phase * period_ps // 100, unit="ps")
        dut.scan_rst_ni_i.value = 1
        t_rise = int(get_sim_time("ps"))
        await self._hold_flip(leg, {cfg.f2: strap, cfg.f3: 1 - strap}, "after_pulse")
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = 0
        await ClockCycles(dut.clk_i, H)
        await ReadOnly()
        t_end = int(get_sim_time("ps"))
        stop["v"] = True
        await task
        await RisingEdge(dut.clk_i)
        dut.test_en_strap_i.value = strap
        close_graded_window(self.logger)
        assert rec and rec[-1]["t"] >= t_end, f"{leg}: sampler did not sample to the session end"
        pre = [s for s in rec if s["t"] < t_te_rise]
        win = [s for s in rec if s["t"] >= t_te_rise]
        during = [s for s in rec if t_fall < s["t"] <= last_edge]
        names = [n[0] for n in NETS]
        not_low = [(s["t"], [names[i] for i, v in enumerate(s["nets"]) if v != 0]) for s in during]
        not_low = [x for x in not_low if x[1]]
        assert len(during) == cfg.w and not not_low, (
            f"CTL-SCAN-REACH FAIL: leg={leg} edges_low={len(during)} expected={cfg.w}: "
            f"nets not low with scan_rst_ni=0 test_en_i=1: {not_low[:4]}"
        )
        self.logger.info(
            "CTL-SCAN-REACH: leg=%s nets_low=%d/%d on %d edges w=%d phase=%d scan_rst_ni "
            "fell t=%d rose t=%d",
            leg,
            N_NETS,
            N_NETS,
            len(during),
            cfg.w,
            cfg.phase,
            t_fall,
            t_rise,
        )
        assert len(pre) >= PRE - 1 and win, f"{leg}: too few samples (pre={len(pre)})"
        flipped = sum(1 for x in win if x["strap"] == 1 - strap and x["te"] == 1)
        assert flipped >= 3, (
            f"CHK-SCAN-TM-HOLD FAIL: control: leg={leg} strap at {1 - strap} with test_en_i=1 "
            f"on {flipped} samples"
        )
        for line in self.strap_flips[-3:]:
            self.logger.info("STRAP-FLIP LOG: %s", line)
        return {"pre": pre, "win": win, "t_rise": t_rise, "flipped": flipped}

    # -- logged items ----------------------------------------------------------

    def _obs_hold(self, leg: str, strap: int, s: dict) -> None:
        base = s["pre"][-1]
        win = s["win"]
        done = [x["done"] for x in win]
        self.logger.info(
            "OBS-SCAN-SENSE-HOLD: leg=%s strap=%d before=%s samples=%d ones=%d zeros=%d x=%d",
            leg,
            strap,
            base["done"],
            len(done),
            done.count(1),
            done.count(0),
            done.count(None),
        )
        keys = ("feat", "d1", "d2", "l1", "l2", "lcw")
        moved = {k: sum(1 for x in win if x[k] != base[k]) for k in keys}
        feats = sorted({_hex(x["feat"], 16) for x in win})
        self.logger.info(
            "OBS-SCAN-FEAT-HOLD: leg=%s strap=%d before feat=%s demote=%s/%s lock=%s/%s "
            "lc_state_word=%s; samples=%d moved %s; feat values %s",
            leg,
            strap,
            _hex(base["feat"], 16),
            base["d1"],
            base["d2"],
            base["l1"],
            base["l2"],
            _hex(base["lcw"]),
            len(win),
            " ".join(f"{k}={v}" for k, v in moved.items()),
            ",".join(feats[:4]),
        )

    def _obs_class1_names(self) -> None:
        from cocotb.handle import HierarchyArrayObject, HierarchyObject

        top: Any = cocotb.top
        crypto = top.u_dut.u_sep.u_sep_crypto
        found: list[str] = []

        def visit(h, path: str, depth: int) -> None:
            try:
                children = list(h)
            except Exception:  # noqa: BLE001 - a scope the simulator cannot iterate
                return
            for c in children:
                name = getattr(c, "_name", "")
                p = f"{path}.{name}"
                scope = isinstance(c, (HierarchyObject, HierarchyArrayObject))
                # Storage and signal handles only: an instance or struct scope is not
                # storage, and a parameter is a constant.
                const = bool(getattr(c, "is_const", False)) or type(c).__name__ == "ConstantObject"
                if not scope and not const and _CLASS1_NAME.search(name):
                    found.append(p)
                if depth < 12 and scope:
                    visit(c, p, depth + 1)

        for inst in ("u_sep_efuse_wrapper", "u_sep_lifecycle_ctrl"):
            h = getattr(crypto, inst, None)
            if h is not None:
                visit(h, f"u_dut.u_sep.u_sep_crypto.{inst}", 0)
        for p in sorted(set(found)):
            self.logger.info("OBS-SCAN-CLASS1-NAME: %s", p)
        self.logger.info(
            "OBS-SCAN-CLASS1-NAME: names=%d n0_scan=%d demote=%d sense_done=%d",
            len(set(found)),
            sum(1 for p in set(found) if "_n0_scan" in p.lower()),
            sum(1 for p in set(found) if "demote" in p.lower()),
            sum(1 for p in set(found) if "sense_done" in p.lower()),
        )

    # -- legs ------------------------------------------------------------------

    async def _strap_leg(self, strap: int, first: bool) -> None:
        leg = f"strap{strap}"
        await self._boot(strap, first)
        if strap == 0:
            await self._shadow_write_obs()
        await self._demote_and_lock()
        await self._release_km()
        s = await self._session(leg, strap)
        self._obs_hold(leg, strap, s)
        win = s["win"]
        bad = [(x["t"], x["stm"]) for x in win if x["stm"] != strap]
        assert not bad, (
            f"CHK-SCAN-TM-HOLD FAIL: leg={leg} secure_tm_o left {strap} during the scan "
            f"session (w={self.tcfg.w}): {bad[:4]}"
        )
        self.tm_pass.append(
            f"strap={strap} secure_tm_o={strap} samples={len(win)} w={self.tcfg.w} "
            f"strap_flips=3 opposite_strap_samples={s['flipped']}"
        )
        if strap == 1:
            nz = [
                (x["t"], SECRET_WORDS[i][0], _hex(v))
                for x in win
                for i, v in enumerate(x["secret"])
                if v != 0
            ]
            assert not nz, (
                f"CHK-SCAN-SECRET-ZERO FAIL: leg={leg} secure_tm_o=1: secret shadow word not 0 "
                f"during the scan session: {nz[:4]}"
            )
            self.secret1 = len(win)
        else:
            staged = [(SECRETS[f] >> (32 * (idx - field_word(f)))) & M32 for f, idx in SECRET_WORDS]
            ctl = [x["secret"] == staged for x in s["pre"]]
            self.secret0 = (sum(ctl), len(ctl), staged[0])
            same = sum(1 for x in win if x["secret"] == staged)
            self.logger.info(
                "OBS-SCAN-SECRET0: leg=%s secure_tm_o=0 samples=%d equal_staged=%d",
                leg,
                len(win),
                same,
            )

    async def _secdis_leg(self) -> None:
        dut: Any = cocotb.top
        leg = "secdis"
        await self._boot(0, False)
        await self._demote_and_lock()
        await self._release_km()
        bound = bound_sec_dis_digest()
        await ReadOnly()
        before = self._sample()
        await RisingEdge(dut.clk_i)
        code, reads = await sec_dis_go(self.fd, TOKEN_ZERO, CODE_MATCH, max_reads=MATCH_READS)
        rose = await wait_bit(self, "lcc_security_disable_probe_o", 1, SDIS_BOUND)
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        after = self._sample()
        await RisingEdge(dut.clk_i)
        line = (
            f"strap=0 security_disable_o {before['secdis']}->{after['secdis']} code="
            f"{_hex(code, 2)} reads={reads} valid={after['dvalid']} digest="
            f"{_hex(after['digest'], 64)} bound={_hex(bound, 64)}"
        )
        assert (
            before["secdis"] == 0
            and code == CODE_MATCH
            and rose is not None
            and after["secdis"] == 1
            and after["dvalid"] == 1
            and bound is not None
            and after["digest"] == bound
        ), f"CTL-SECDIS-SET FAIL: {line}"
        self.logger.info("CTL-SECDIS-SET: %s", line)
        s = await self._session(leg, 0)
        self._obs_hold(leg, 0, s)
        win = s["win"]
        bad = [
            (x["t"], x["secdis"], x["dvalid"], _hex(x["digest"], 64))
            for x in win
            if x["secdis"] != 1 or x["dvalid"] != 1 or x["digest"] != after["digest"]
        ]
        assert not bad, (
            f"CHK-SCAN-SECDIS-HOLD FAIL: security_disable_o, digest valid or digest moved "
            f"during the scan session (w={self.tcfg.w}): {bad[:4]}"
        )
        self.logger.info(
            "CHK-SCAN-SECDIS-HOLD PASS: samples=%d security_disable_o=1 valid=1 digest=%s "
            "unchanged w=%d control_set=%s->%s",
            len(win),
            _hex(after["digest"], 64),
            self.tcfg.w,
            before["secdis"],
            after["secdis"],
        )
        tm_bad = [(x["t"], x["stm"]) for x in win if x["stm"] != 0]
        assert not tm_bad, f"CHK-SCAN-TM-HOLD FAIL: leg={leg} secure_tm_o left 0: {tm_bad[:4]}"
        self.tm_pass.append(
            f"strap=0 sec_dis=1 secure_tm_o=0 samples={len(win)} strap_flips=3 "
            f"opposite_strap_samples={s['flipped']}"
        )

        # OBS-SCAN-SECDIS-GO: a mismatch go with test_en_i = 1.
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = 1
        await ClockCycles(dut.clk_i, PIN_BOUND)
        code_te, reads_te = await sec_dis_go(
            self.fd, TOKEN_OTHER, CODE_MISMATCH, max_reads=MATCH_READS
        )
        # The poll returns None when no read in MATCH_READS gave the mismatch code;
        # one more read gives the code the register holds at the end of the poll.
        last_te = (await self.fd.rd(MATCH_ADDR[CH_SEC_DIS])) & MATCH_STATUS_MASK
        await ClockCycles(dut.clk_i, H)
        await ReadOnly()
        go = self._sample()
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = 0
        await ClockCycles(dut.clk_i, H)
        self.logger.info(
            "OBS-SCAN-SECDIS-GO: test_en_i=1 token=TOKEN_OTHER mismatch_code_seen=%d "
            "reads=%d last_code=%s security_disable_o=%s valid=%s digest_unchanged=%d",
            int(code_te is not None),
            reads_te,
            _hex(last_te, 2),
            go["secdis"],
            go["dvalid"],
            int(go["digest"] == after["digest"]),
        )

    # -- leaf ------------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.tcfg = cfg = _Cfg(seed)
        self.logger.info(
            "DRAW w=%d phase=%d strap_order=%s strap_flip=%d,%d,%d",
            cfg.w,
            cfg.phase,
            ",".join(str(s) for s in cfg.straps),
            cfg.f1,
            cfg.f2,
            cfg.f3,
        )
        self.sys_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        self.cfg.wdt_clk_period_ns = P_W * self.cfg.sys_clk_period_ns
        self.clock_phases_ps = {"clk_wdt_i": WDT_PHASE_PCT * self.sys_ps // 100}
        self.logger.info(
            "CFG H=%d pre=%d p_w=%d wdt_phase_pct=%d sense_bound=%d tap_bound=%d stm_bound=%d",
            H,
            PRE,
            P_W,
            WDT_PHASE_PCT,
            SENSE_BOUND,
            TAP_BOUND,
            STM_BOUND,
        )
        close_graded_window(self.logger)
        fixed = {"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS, "LOCKS": 0, **SECRETS}
        img = self.select_efuse_image(lc_raw=LC_PROD, fixed=fixed)
        for f in SECRET_FIELDS:
            assert img.field_int(f) == SECRETS[f], f"test bug: {f} not pinned"
        self.write_efuse_image(img)
        self.fd = SepEfuseFd(self)
        self.tm_pass: list[str] = []
        self.strap_flips: list[str] = []
        self.secret1 = 0
        self.secret0 = (0, 0, 0)
        orient = {
            d: feat_ctrl_profile(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=d, demote_2=d).value
            for d in (0, 1)
        }
        self.logger.info(
            "OBS-SCAN-FEAT-HOLD orientation: profile PROD demote 0/0=0x%016x 1/1=0x%016x "
            "(staged SIP_DIS=0x%016x SYS_DIS=0x%016x)",
            orient[0],
            orient[1],
            _SIP_DIS,
            _SYS_DIS,
        )

        for i, strap in enumerate(cfg.straps):
            await self._strap_leg(strap, first=(i == 0))
            if i == 0:
                self._obs_class1_names()
        await self._secdis_leg()

        straps_seen = sorted({int(x.split()[0].split("=")[1]) for x in self.tm_pass})
        assert straps_seen == [0, 1], f"CHK-SCAN-TM-HOLD FAIL: control: strap values {straps_seen}"
        for line in self.tm_pass:
            self.logger.info("CHK-SCAN-TM-HOLD PASS: %s control_values=0,1", line)
        ok0, n0, w0 = self.secret0
        assert n0 and ok0 == n0 and w0 != 0, (
            f"CHK-SCAN-SECRET-ZERO FAIL: control: strap-0 secret words equal the staged words "
            f"on {ok0}/{n0} samples before the session"
        )
        self.logger.info(
            "CHK-SCAN-SECRET-ZERO PASS: strap=1 words=%d zero on %d session samples; "
            "control strap=0 staged on %d/%d samples (CHIPLET_UID word0=0x%08x)",
            len(SECRET_WORDS),
            self.secret1,
            ok0,
            n0,
            w0,
        )
        self.result_pass(TEST, seed, len(self.required_evidence))
