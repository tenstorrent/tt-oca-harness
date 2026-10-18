# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A SEC_DIS match during or before sense holds the sensed shadow, and a cold reset
under the match leaves every shadow field at its reset value.

RAND-REP. no_cpu, real fuse sense, VCS only (reset values and the retained match
need X on unreset flops). The seed draws the class (B or C), the staged image (4
to 8 fields with non-zero distinct words, at least one below byte offset 0x200
and one at or above it, every other field 0 except ``LC_STATE``) and the
disable-vector pair (``env/sep_efuse_plan.py``, ``plan_sec_dis_timing``; the
pre-sim hook stages the same image). Class B draws its match offset k at
runtime from the bounds the control sense and the match latency give.

Control sense (every leaf): the leaf samples sense done and the sensed-shadow
probe on every clock from reset release, measures the sense time, the first and
the last load of a staged non-zero word, and the match latency L of a
``TOKEN_ZERO`` go, and reads a shadow-map word before sense done (SLVERR).

Class B: a ``TOKEN_ZERO`` match lands during sense, after at least one staged
non-zero word is loaded and before every one is. From the rise of
``security_disable_o`` the probe equals its value at the rise for W clocks, and
again for W clocks after the IC_RESET TDR releases the SEP reset; sense done stays
low (``hw/sys/sep/doc/security_disable.adoc``, section Fuse Sensing and the Shadow
Map). Class C: a match held over a cold reset is present from reset release; for W
clocks every probe word except ``LC_STATE`` reads 0 and no read command reaches the
post-guard fuse port (``security_disable.adoc``, section Reset Persistence).

Both classes: a cold reset under the match leaves every shadow field except
``LC_STATE`` at its reset value 0x0 with an OKAY response
(``hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc``, reset values). The compare
takes each word's field bits and reset value from the generated IP-XACT, so the
``rsvd`` and ``reserved`` fields (access R, reset 0x0) are compared too; only a bit
with no field or no declared reset is masked and logged as ``rsvd=0x<v>``. A mismatch,
a cold reset and a full sense recover the staged image; that recovery, the sense
stop, the OKAY map read and the feature override are logged controls here.
``secure_tm_req_i`` stays 0 for the whole leaf. The shadow reset value of
``LC_STATE`` is not graded.

Checkers: CHK-BIND, CHK-SDIS-HOLD, CHK-SDIS-RESET-VALUES. A failing hook control
logs ``CHK-HOOK FAIL`` and ends the leaf.
The VPLAN evidence line of CHK-SDIS-HOLD names ``ctl_map_resp`` twice; the leaf
logs the control-sense map read as ``ctl_map_resp`` and the read in the hold window
as ``hold_map_resp``.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_plan import (
    CH_SEC_DIS,
    CODE_MATCH,
    CODE_MISMATCH,
    FIELD_NAMES,
    T_SEC_DIS_TIMING,
    TOKEN_ARRAY_ADDR,
    TOKEN_OTHER,
    TOKEN_ZERO,
    draw_match_offset,
    field_n_words,
    field_word,
    plan,
    poll_code,
    shadow_addr,
    token_go,
    token_words,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    chk_bind,
    clocks_to_sense,
    hook_fail,
    log_line,
    rst_pulse,
    sig_bits,
)
from env.sep_fabric_common import RESP_NAME, RESP_OKAY, RESP_SLVERR
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_efuse_sdis_hold_bound,
)
from env.sep_ic_reset_tdr import IC_RESET_IDLE, SepIcResetTdr, tdr_word
from sep_base_test import sep_base_test
from sep_reg_meta import register_fields, word_reset, word_unreset_mask

_NAME = "sep_sec_dis_timing_rand_test"
# Test parameters: W = _W_MULT x the measured sense time; the recovery sense is
# expected within _RECOVER_MULT x the sense time (logged).
_W_MULT = 3
_RECOVER_MULT = 2
_TRIES = 3
_SENSE_BOUND = 100_000
_POLL_READS = 400
_RST_RELEASE_BOUND = 64
_LC_WORD = field_word("LC_STATE")
_LC_MASK = 0xFFFF_FFFF << (32 * _LC_WORD)
_TO0 = str.maketrans("xXzZ", "0000")
_X1 = str.maketrans("01xXzZ", "001111")


def _probe(sig) -> tuple[int, int]:
    """(value with X/Z as 0, mask of the X/Z bits) of a packed probe."""
    s = sig_bits(sig)
    if "x" in s or "X" in s or "z" in s or "Z" in s:
        return int(s.translate(_TO0), 2), int(s.translate(_X1), 2)
    return int(s, 2), 0


def _word(value: int, w: int) -> int:
    return (value >> (32 * w)) & 0xFFFF_FFFF


def _reset_compare(name: str, k: int) -> tuple[int, int]:
    """(compared bits, reset value) of shadow word k of ``name``, from the generated
    IP-XACT of ``sep_efuse_map``.

    The compared bits are every bit of a field that declares a reset, ``rsvd`` and
    ``reserved`` fields included (access R, reset 0x0 in the map). Only a bit outside
    every field, or of a field with no declared reset, is left out.
    """
    addr = shadow_addr(name, 0)
    _width, fields = register_fields(addr)
    in_field = (sum(f.mask for f in fields) >> (32 * k)) & 0xFFFF_FFFF
    word = addr + 4 * k
    mask = in_field & ~word_unreset_mask(word)
    return mask, word_reset(word) & mask


class _Clk:
    """Free-running clk_i counter."""

    def __init__(self) -> None:
        self.n = 0
        cocotb.start_soon(self._run())

    async def _run(self) -> None:
        clk = cocotb.top.clk_i
        while True:
            await RisingEdge(clk)
            self.n += 1


class _HoldMonitor:
    """Per-clock sample of sense done, security_disable_o and the shadow probe.

    Mode ``"rise"`` (class B): waits for the rise of security_disable_o, takes the
    probe there as S, then counts every later clock where sense done is not 0,
    security_disable_o is not 1 or the probe differs from S. Mode ``"zero"``
    (class C): from its first clock, counts every clock where sense done is not 0,
    security_disable_o is not 1 or a probe word other than LC_STATE is not 0.
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.n = 0
        self.stop = False
        self.rise_at: int | None = None
        self.rise_sd: int | None = None
        self.s_val = 0
        self.s_x = 0
        self.held = 0
        self.bad_sd = 0
        self.bad_sdis = 0
        self.bad_probe = 0
        cocotb.start_soon(self._run())

    async def _run(self) -> None:
        dut = cocotb.top
        while not self.stop:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.n += 1
            sd = sig_bits(dut.sep_fuse_sense_done_o)
            sdis = sig_bits(dut.lcc_security_disable_probe_o)
            val, xm = _probe(dut.efuse_shadow_probe_o)
            if self.mode == "rise" and self.rise_at is None:
                if sdis == "1":
                    self.rise_at = self.n
                    self.rise_sd = 1 if sd == "1" else 0
                    self.s_val, self.s_x = val, xm
                continue
            self.held += 1
            self.bad_sd += int(sd != "0")
            self.bad_sdis += int(sdis != "1")
            if self.mode == "rise":
                self.bad_probe += int(val != self.s_val or xm != self.s_x)
            else:
                self.bad_probe += int((val | xm) & ~_LC_MASK != 0)

    async def until(self, n: int) -> None:
        clk = cocotb.top.clk_i
        while self.n < n:
            await RisingEdge(clk)


@pyuvm.test()
class sep_sec_dis_timing_rand_test(sep_base_test):
    """SEC_DIS match before and during sense; shadow hold and reset values."""

    required_evidence = ("CHK-BIND", "CHK-SDIS-HOLD", "CHK-SDIS-RESET-VALUES")

    # ------------------------------------------------------------------ bus

    def _sense_done(self) -> int:
        return self.rd(cocotb.top.sep_fuse_sense_done_o, allow_unknown=True) & 1

    def _sdis(self) -> int:
        return self.rd(cocotb.top.lcc_security_disable_probe_o, allow_unknown=True) & 1

    async def _write_sdis_words(self, token: int) -> None:
        """The eight SEC_DIS words, SEC_DISABLE_TOKEN_I[0] to [7] in index order."""
        for addr, word in zip(TOKEN_ARRAY_ADDR[CH_SEC_DIS], token_words(token)):
            await self.fd.wr(addr, word)

    # ------------------------------------------------------------------ steps

    async def _ctl_trace(self, out: list[tuple[int, int, int]]) -> None:
        """Per-clock (sense done, probe value, X mask) from the first clock with
        rst_ni high after a low, until sense done rises."""
        dut = cocotb.top
        seen_low = False
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            rst = sig_bits(dut.rst_ni)
            if not seen_low:
                seen_low = rst == "0"
                continue
            if rst != "1" and not out:
                continue
            val, xm = _probe(dut.efuse_shadow_probe_o)
            sd = 1 if sig_bits(dut.sep_fuse_sense_done_o) == "1" else 0
            out.append((sd, val, xm))
            if sd or len(out) > _SENSE_BOUND:
                return

    async def _sdis_rise(self, bound: int) -> int | None:
        """Clock count (of self.clk) at the first clock with security_disable_o = 1."""
        dut = cocotb.top
        for _ in range(bound):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if sig_bits(dut.lcc_security_disable_probe_o) == "1":
                n = self.clk.n
                await NextTimeStep()
                return n
        await NextTimeStep()
        return None

    async def _mismatch_drop(self, label: str) -> None:
        """TOKEN_OTHER on SEC_DIS, go, poll until 0x2a; security_disable_o drops."""
        await self._write_sdis_words(TOKEN_OTHER)
        await token_go(self.fd.wr, CH_SEC_DIS)
        code, _n = await poll_code(
            self.fd.rd, CH_SEC_DIS, max_reads=_POLL_READS, until=CODE_MISMATCH
        )
        await ClockCycles(cocotb.top.clk_i, 2)
        if code != CODE_MISMATCH or self._sdis() != 0:
            hook_fail(self.chk, reason=f"{label}_drop", code=code, secdis=self._sdis())

    async def _read_shadow_map(self) -> list[tuple[str, int, int, int, int]]:
        """Every shadow word: (field, word, data, response code, sense done at response)."""
        out = []
        for name in FIELD_NAMES:
            for k in range(field_n_words(name)):
                seq = await self.fd.access(SepAxiOp.READ, shadow_addr(name, k), ungraded_read=True)
                out.append((name, k, seq.rdata & 0xFFFF_FFFF, seq.resp_code, self._sense_done()))
        return out

    # ------------------------------------------------------------------ scenario

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        p = plan(T_SEC_DIS_TIMING, seed)
        self.plan = p
        cls = p.leg["class"]
        m = int(p.leg["m"])
        for line in p.log_lines(**{"class": cls}):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, _NAME, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        self.logger.info("STAGED seed=%d staged_nonzero_fields=%d", seed, m)
        self.logger.info("EVIDENCE-REQUIRED seed=%d ids=%s", seed, ",".join(self.required_evidence))
        staged = [w for w in range(256) if w != _LC_WORD and p.image.words[w] != 0]
        staged_val = {w: p.image.words[w] & 0xFFFF_FFFF for w in staged}

        await chk_bind(self.chk)

        # ---------------------------------------------------------- control sense
        self.write_efuse_image(p.image)
        trace: list[tuple[int, int, int]] = []
        tracer = cocotb.start_soon(self._ctl_trace(trace))
        await self.release_no_cpu_reset()
        self._set_pin(dut, "test_en_strap_i", 0)
        self.clk = _Clk()
        self.shim = SepShimCmdMonitor(dut).start()
        ctl_mark = self.shim.mark()
        ctl_map_seq = await self.fd.access(
            SepAxiOp.READ, shadow_addr(FIELD_NAMES[-1], 0), ungraded_read=True
        )
        sd_at_resp = self._sense_done()
        ctl_map_resp = RESP_NAME.get(ctl_map_seq.resp_code, str(ctl_map_seq.resp_code))
        await tracer
        await NextTimeStep()
        if sd_at_resp:
            hook_fail(self.chk, reason="control_map_read_after_sense_done", resp=ctl_map_resp)
        if not trace or not trace[-1][0]:
            raise AssertionError(f"control sense: sense done did not rise in {_SENSE_BOUND} clocks")
        t_sense = len(trace)
        changes = []
        for i in range(1, len(trace)):
            prev, cur = trace[i - 1][1], trace[i][1]
            if any(_word(prev, w) != _word(cur, w) for w in staged):
                changes.append(i + 1)
        if not changes:
            hook_fail(self.chk, reason="no_staged_load_seen", t_sense=t_sense)
        t_first, tl = changes[0], changes[-1]
        await self.wait_fuse_sense()
        ctl_sense_cmds = len(self.shim.reads_since(ctl_mark))
        # Every shadow register; each staged non-zero word reads its non-zero staged value.
        ctl_fields_ok = True
        for name in FIELD_NAMES:
            for k in range(field_n_words(name)):
                widx = field_word(name) + k
                got = await self.fd.rd(shadow_addr(name, k))
                if widx in staged_val:
                    ctl_fields_ok &= got == staged_val[widx] and got != 0
        self.chk.ctrl(
            "SDIS-STAGED-NONZERO",
            ctl_fields_ok,
            fields=len(p.leg["staged_fields"]),
            t_sense=t_sense,
            t_first=t_first,
            t_last=tl,
        )
        w = _W_MULT * t_sense
        self.logger.info(
            "TIME seed=%d t_sense=%d t_first=%d t_last=%d window=%d ctl_map_resp=%s "
            "ctl_sense_cmds=%d",
            seed,
            t_sense,
            t_first,
            tl,
            w,
            ctl_map_resp,
            ctl_sense_cmds,
        )

        # Match latency L: first token-word write to the rise of security_disable_o.
        rise = cocotb.start_soon(self._sdis_rise(w))
        c0 = self.clk.n
        await self._write_sdis_words(TOKEN_ZERO)
        await token_go(self.fd.wr, CH_SEC_DIS)
        rise_n = await rise
        if rise_n is None:
            hook_fail(self.chk, reason="match_latency_no_rise", window=w)
        lat = rise_n - c0
        await self._mismatch_drop("latency")
        await self.pulse_rst_ni(max_sense_cycles=_SENSE_BOUND)

        if cls == "B":
            hold = await self._class_b(seed, trace, t_first, tl, lat, w, staged, staged_val)
        else:
            hold = await self._class_c(seed, w)
        ctl_probe_changed = int(trace[min(hold["k_ctl"], t_sense) - 1][1] != trace[-1][1])
        controls_ok = (
            hold["bad_sd"] == 0
            and hold["bad_sdis"] == 0
            and hold["map_resp"] == RESP_OKAY
            and ctl_map_seq.resp_code == RESP_SLVERR
            and ctl_probe_changed == 1
            and ctl_sense_cmds >= 1
        )
        if cls == "C" and ctl_sense_cmds < 1:
            hook_fail(self.chk, reason="control_sense_no_read_command")
        self.chk.ok(
            "SDIS-HOLD",
            hold["bad_probe"] == 0
            and hold.get("reads_in_window", 0) == 0
            and hold.get("rst_released", 1) == 1
            and controls_ok,
            **{
                "class": cls,
                "t_sense": t_sense,
                "window": w,
                "probe_unchanged": hold.get("probe_unchanged", "na"),
                "shadow_reset_over_window": hold.get("reset_over_window", "na"),
                "ctl_sense_done_cycle": t_sense,
                "ctl_probe_changed": ctl_probe_changed,
                "ctl_map_resp": ctl_map_resp,
                "sep_rst_released": hold.get("rst_released", "na"),
                "sep_rst_pre": hold.get("rst_pre", "na"),
                "match_lat": lat,
                "k": hold.get("k", "na"),
                "n_loaded": hold.get("n_loaded", "na"),
                "ctl_sense_done": int(hold["bad_sd"] == 0) ^ 1,
                "ctl_sdis_o": int(hold["bad_sdis"] == 0),
                "hold_map_resp": RESP_NAME.get(hold["map_resp"], str(hold["map_resp"])),
                "ctl_sense_cmds": ctl_sense_cmds if cls == "C" else "na",
                "held_clocks": hold["held"],
                "bad_probe_clocks": hold["bad_probe"],
                "reads_in_window": hold.get("reads_in_window", "na"),
            },
        )

        # Reset values under the match (both classes).
        values = await self._read_shadow_map()
        bad = []
        fields_read = set()
        staged_fields = set(p.leg["staged_fields"])
        staged_zero = True
        rsvd = 0
        for name, k, data, resp, sd in values:
            if name == "LC_STATE":
                self.chk.obs("SDIS-LC-RESET", word=f"0x{data:08x}", resp=RESP_NAME.get(resp))
                continue
            fields_read.add(name)
            mask, exp = _reset_compare(name, k)
            rsvd |= data & ~mask & 0xFFFF_FFFF
            if resp != RESP_OKAY or data & mask != exp or sd:
                bad.append(
                    f"{name}[{k}]=0x{data:08x}/exp0x{exp:08x}/m0x{mask:08x}"
                    f"/{RESP_NAME.get(resp, resp)}/sd{sd}"
                )
            if name in staged_fields and data & mask != exp:
                staged_zero = False
        close_graded_window(self.logger)
        self.chk.ok(
            "SDIS-RESET-VALUES",
            not bad and staged_zero and ctl_fields_ok,
            **{
                "class": cls,
                "fields": len(fields_read),
                "staged_nonzero": m,
                "n_loaded": hold.get("n_loaded", "na"),
                "all_reset_value": int(not bad),
                "ctl_sense_done": 0,
                "rsvd": f"0x{rsvd:x}",
                "first_bad": ",".join(bad[:4]) or "none",
            },
        )

        # Recovery: mismatch, cold reset, full sense (logged control).
        await self._write_sdis_words(TOKEN_OTHER)
        await token_go(self.fd.wr, CH_SEC_DIS)
        rec_code, _n = await poll_code(
            self.fd.rd, CH_SEC_DIS, max_reads=_POLL_READS, until=CODE_MISMATCH
        )
        await ClockCycles(dut.clk_i, 2)
        rec_sdis = self._sdis()
        rec_mark = self.shim.mark()
        await rst_pulse(self)
        rec_cycles = await clocks_to_sense(self, _SENSE_BOUND, started=True)
        await NextTimeStep()
        if rec_cycles is None:
            raise AssertionError("recovery sense did not complete")
        await self.wait_fuse_sense()
        rec_cmds = len(self.shim.reads_since(rec_mark))
        eq = True
        for name in FIELD_NAMES:
            for k in range(field_n_words(name)):
                eq &= await self.fd.rd(shadow_addr(name, k)) == p.image.shadow_word(
                    field_word(name) + k
                )
        feat = await self.fd.feat_ctrl()
        probe_feat = sig_bits(dut.lcc_feat_ctrl_probe_o)
        log_line(
            self.logger,
            "OBS-SDIS-RECOVER",
            seed,
            feat=f"0x{feat:016x}",
            ctl_mismatch=f"0x{rec_code if rec_code is not None else 0:02x}",
            ctl_sense_done_cycles=rec_cycles,
            ctl_shadows_eq_staged=int(eq),
            secdis=rec_sdis,
            probe_feat=probe_feat,
            within_bound=int(rec_cycles <= _RECOVER_MULT * t_sense),
            recovery_sense_cmds=rec_cmds,
        )
        await self.shim.stop()
        self.chk.finish()

    async def _class_b(
        self,
        seed: int,
        trace: list[tuple[int, int, int]],
        t_first: int,
        tl: int,
        lat: int,
        w: int,
        staged: list[int],
        staged_val: dict[int, int],
    ) -> dict:
        """Steps 4 to 9: a match during sense, the hold, the TDR release, a cold reset."""
        dut = cocotb.top
        k_lo = max(1, t_first - lat + 1)
        k_hi = tl - lat - 1
        if k_lo > k_hi:
            hook_fail(self.chk, reason="window", k_lo=k_lo, k_hi=k_hi, match_lat=lat)
        k = draw_match_offset(self.plan, k_lo, k_hi)
        k_first = k
        open_graded_window(_NAME, self.logger)
        mon: _HoldMonitor | None = None
        n_loaded = 0
        for attempt in range(1, _TRIES + 1):
            await rst_pulse(self)
            mon = _HoldMonitor("rise")
            await ClockCycles(dut.clk_i, k)
            set_efuse_sdis_hold_bound(w, self.logger)
            await self._write_sdis_words(TOKEN_ZERO)
            await token_go(self.fd.wr, CH_SEC_DIS)
            for _ in range(w):
                if mon.rise_at is not None:
                    break
                await RisingEdge(dut.clk_i)
            if mon.rise_at is None:
                mon.stop = True
                hook_fail(self.chk, reason="no_sdis_rise", attempt=attempt, k=k)
            n_loaded = sum(1 for x in staged if _word(mon.s_val, x) == staged_val[x])
            n_reset = sum(1 for x in staged if _word(mon.s_val, x) == 0)
            accepted = mon.rise_sd == 0 and n_loaded >= 1 and n_reset >= 1
            self.chk.obs(
                "SDIS-TRY",
                attempt=attempt,
                k=k,
                k_lo=k_lo,
                k_hi=k_hi,
                rise_clk=mon.rise_at,
                sense_done=mon.rise_sd,
                n_loaded=n_loaded,
                n_reset=n_reset,
                accepted=int(accepted),
            )
            if accepted:
                break
            mon.stop = True
            set_efuse_sdis_hold_bound(0, self.logger)
            if mon.rise_sd or n_reset == 0:
                k = (k_lo + k) // 2
            else:
                k = (k + k_hi) // 2
            close_graded_window(self.logger)
            await self._mismatch_drop(f"try{attempt}")
            await self.pulse_rst_ni(max_sense_cycles=_SENSE_BOUND)
            open_graded_window(_NAME, self.logger)
        else:
            hook_fail(self.chk, reason="no_accepted_try", tries=_TRIES, k_first=k_first)
        assert mon is not None

        # Hold for W clocks from the rise, with one OKAY shadow-map read inside.
        map_seq = await self.fd.access(
            SepAxiOp.READ, shadow_addr(FIELD_NAMES[-1], 0), ungraded_read=True
        )
        await mon.until(mon.rise_at + w)
        set_efuse_sdis_hold_bound(0, self.logger)

        # Release the SEP reset through the IC_RESET TDR and hold W more clocks. The net
        # reads held (0) before the TDR step, so the release is an edge the TDR made.
        rst_pre = self.rd_known(dut.dbg_sep_reset_n_o) & 1
        tdr = SepIcResetTdr(self.rd_known)
        await tdr.reset_and_select()
        await tdr.capture_shift_update(tdr_word(apply=("sep_reset_n",)))
        released = 0
        for _ in range(_RST_RELEASE_BOUND):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True) & 1:
                released = int(rst_pre == 0)
                break
        n_rel = mon.n
        await mon.until(n_rel + w)
        await tdr.capture_shift_update(IC_RESET_IDLE)
        self._set_pin(dut, "jtag_ic_reset_tdr_en_i", 0)
        mon.stop = True
        await RisingEdge(dut.clk_i)

        # Cold reset with the token arrays and the match retained.
        await rst_pulse(self)
        await ClockCycles(dut.clk_i, 4)
        return {
            "k": k,
            "k_ctl": k,
            "n_loaded": n_loaded,
            "bad_sd": mon.bad_sd,
            "bad_sdis": mon.bad_sdis,
            "bad_probe": mon.bad_probe,
            "held": mon.held,
            "probe_unchanged": int(mon.bad_probe == 0),
            "rst_released": released,
            "rst_pre": rst_pre,
            "map_resp": map_seq.resp_code,
        }

    async def _class_c(self, seed: int, w: int) -> dict:
        """Steps 10 to 12: a match held over a cold reset, present from reset release."""
        dut = cocotb.top
        open_graded_window(_NAME, self.logger)
        rise = cocotb.start_soon(self._sdis_rise(w))
        await self._write_sdis_words(TOKEN_ZERO)
        await token_go(self.fd.wr, CH_SEC_DIS)
        code, _n = await poll_code(self.fd.rd, CH_SEC_DIS, max_reads=_POLL_READS, until=CODE_MATCH)
        rise_n = await rise
        if code != CODE_MATCH or rise_n is None:
            hook_fail(self.chk, reason="class_c_match", code=code, rise=rise_n)
        set_efuse_sdis_hold_bound(w, self.logger)
        await rst_pulse(self)
        mon = _HoldMonitor("zero")
        mark = self.shim.mark()
        map_seq = await self.fd.access(
            SepAxiOp.READ, shadow_addr(FIELD_NAMES[-1], 0), ungraded_read=True
        )
        await mon.until(w)
        reads = len(self.shim.reads_since(mark))
        mon.stop = True
        set_efuse_sdis_hold_bound(0, self.logger)
        await RisingEdge(dut.clk_i)
        self.chk.obs("SDIS-CLASS-C", window=w, reads_in_window=reads)
        return {
            "k_ctl": 1,
            "bad_sd": mon.bad_sd,
            "bad_sdis": mon.bad_sdis,
            "bad_probe": mon.bad_probe,
            "held": mon.held,
            "reset_over_window": int(mon.bad_probe == 0),
            "reads_in_window": reads,
            "map_resp": map_seq.resp_code,
        }
