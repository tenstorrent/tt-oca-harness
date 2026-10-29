# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A sense response with its status bit set leaves one shadow word at reset; a late program response.

Leg A: a shim response whose status bit is set during sensing still advances the
sensing word counter and leaves that shadow word unwritten, so it reads its reset
value 0x0, and sense done still rises. Every other word loads its staged value.
Leg B: a program request that waits for its shim response, with the program timeout
disabled, shows ``program_busy`` and not ``program_done`` while it waits, and shows
``program_done`` with ``program_status`` 0 and no busy after the response.

Sources: ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (section Fuse Sensing and Boot
Sequencing, the sensing sequence, lines 96-103: ST_READ issues a single READ command for
all 256 shadow words, the shim returns one strobe per word, a strobe with its status bit
set advances the counter and leaves that word unwritten, and sense done rises after the
strobe of the last word); ``hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc``
(reset value 0x0 of every field except ``LC_STATE``);
``hw/ip/efuse/regs/gen/adoc/efuse_interface_ctrl.adoc`` (``EFUSE_INTERFACE_CTRL_STATUS``,
``EFUSE_PROGRAM_CTRL``, ``EFUSE_PROGRAM_REQ_TIMEOUT``); ``hw/ip/efuse/doc/interface.adoc``
(section Fuse Command Protocol, the response status bit and the READ command encoding).

Image: fixed TEST_DEV image of ``env/sep_efuse_plan.py`` (non-zero distinct words in
shadow words 10 to 254, no lock bit), written before the first reset. Draws:
``plan(test, seed)`` (word class and word w, spare bits a, b, c, timeout cycles T, hold
multiple m).

Hooks: ``efuse_sense_status_inject_i`` with ``efuse_sense_status_word_i`` (status bit on
the sense response of word w) and ``efuse_shim_resp_hold_i`` (the shim response of a
program request is withheld while it is high).

Checkers:
  CHK-SENSE-STATUS  sense shape, graded in both senses (``sense=control``, then
                    ``sense=injected``): from the ``rst_ni`` release to the
                    ``sep_fuse_sense_done_o`` rise the post-guard command tap
                    (``efuse_shim_cmd_*_o``) shows exactly one READ command, the
                    response tap shows exactly one strobe per shadow word, and at the
                    sensing FSM ports (``efuse_shadow_resp_valid_o``,
                    ``efuse_shadow_sense_done_o``) there is one strobe per word and
                    ``fuse_sense_done_o`` first reads 1 exactly two cycles after the
                    cycle of the last strobe (``done_lat=2``).
                    The injected sense runs twice (``sense=injected``, then
                    ``sense=injected_binned``) and each instance also requires: sense
                    done rises within the bound, word w
                    reads 0x0 at ``efuse_shadow_probe_o`` and at the frontdoor, every
                    other word equals its staged value, and ``efuse_sense_done`` reads 1.
                    Control: the first sense loads word w with its non-zero staged value.
                    The check also requires that in the injected sense the shim responses at the
                    ``sep`` input (taps ``efuse_shim_resp_*_o``) are one per word, and
                    exactly one carries status 1: the response of word w, with the
                    staged data of word w.
  CHK-PROG-LIFE     with the response held, ``program_busy`` 1 and ``program_done`` 0 at
                    every clock of the window and every frontdoor read; after the
                    release done 1, status 0, busy 0 and the bit reads 1 at the direct
                    read. Control: the same program without a hold completes and burns.
                    Hook control: the held program shows its program command to the bit at
                    ``efuse_shim_command_req_o``, and the unheld control program completes in
                    fewer clocks than the held program spends from its go to the end of the
                    held window, so a response that the hold did not withhold would show
                    ``program_done`` inside the window (``CHK-HOOK FAIL`` otherwise). The
                    command request stays valid while the response is withheld, so the tap
                    shows one command.

  CHK-SENSE-STATUS-CTRLWORD  a last sense with the status bit on the response of a
                    control word, drawn from shadow words 0 to 9 whose staged value
                    differs from the RDL reset value: that word reads its RDL reset value
                    at ``efuse_shadow_probe_o`` and ``sep_fuse_sense_done_o`` reads 1
                    (same sensing-sequence source as CHK-SENSE-STATUS).
  CHK-SENSE-STATUS-CTRLWORD-FEAT  the same last sense, every drawn word (255 included):
                    ``lcc_feat_ctrl_probe_o`` equals the profile row of the sensed
                    ``LC_STATE``, ``SIP_DIS`` and ``SYS_DIS`` shadows, with the drawn word
                    at its RDL reset value (``hw/sys/sep/doc/lifecycle_controller.adoc``,
                    Debug and Functional Feature Control and Per-LC-state Feature
                    Control Profile; an unwritten ``LC_STATE`` word decodes as INVALID,
                    which disables every feature). Word 255 is no profile input.

Log-only: ``OBS-PROG-TIMEOUT`` (busy, done and status after m x T clocks of a held
program with the timeout enabled; the specification does not state the report).
``OBS-SENSE-STATUS-CTRLWORD`` (the same last sense when the drawn word is 255: that
shadow word, ``sep_fuse_sense_done_o`` and ``lcc_feat_ctrl_probe_o``; the sensing
sequence says both that a strobe with its status bit set leaves its word unwritten and
that the strobe at counter 255 stores the last word).

FCOV: the graded window is open over the second injected sense and the held program,
each to its own grade. The control sense and the first injected sense are graded
with the window closed, so the window opens on a sense only after the same check has
passed. Every sample of the leaf (``cp_sense_status_word``, ``cp_sense_shape``,
``x_prog_lifecycle``) is held with the tag of its graded step (``set_ef_hold_tag``)
and samples only when the leaf writes that tag to the pass label
(``set_ef_hold_pass``) after the check of that instance passed: CHK-SENSE-STATUS of
the second injected sense, and CHK-PROG-LIFE with its hook control for the held
program. The first failed check or missing control closes the window and keeps it
closed for the rest of the leaf.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import WORD_MASK, SepShimCmdMonitor
from env.sep_efuse_image import SHADOW_BASE
from env.sep_efuse_plan import (
    PROGRAM_CTRL_ADDR,
    STATUS_ADDR,
    T_SHIM_FAULT,
    feat_ctrl_profile,
    field_word,
    plan,
    program_ctrl_word,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    clocks_to_sense,
    direct_word,
    probe_words,
    rst_pulse,
    set_shadow_golden,
)
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_ef_hold_pass,
    set_ef_hold_tag,
)
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, sym, word_reset

TEST = T_SHIM_FAULT

_IC = EFUSE_INTERFACE_CTRL
_PG_TMO_ADDR = _IC.addr("EFUSE_PROGRAM_REQ_TIMEOUT")
_TMO_EN = _IC.field_mask("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_enable")
_TMO_CYC = _IC.field_mask("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_cycles")
_TMO_CYC_RESET = _IC.field_reset("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_cycles")
_M_SENSE_DONE = _IC.field_mask("EFUSE_INTERFACE_CTRL_STATUS", "efuse_sense_done")
_M_PG_BUSY = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_busy")
_M_PG_DONE = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_M_PG_STATUS = _IC.field_mask("EFUSE_PROGRAM_CTRL", "program_status")
# One shadow word per 32-bit register of the MAP window.
_N_WORDS = sym("SEP_EFUSE_MAP_REG_MAP_SIZE") // 4
# READ commands of one sense: ST_READ issues a single READ command for all shadow
# words (hw/sys/sep/doc/otp_fuse_controller.adoc:96).
_SENSE_READ_CMDS = 1
# Sense-done latency at the sensing FSM ports, in clk_i cycles from the cycle of the
# last response strobe: the last word arrives in cycle n+1, the FSM is in
# ST_FINISHED from cycle n+2 and fuse_sense_done_o is high from cycle n+3
# (hw/sys/sep/doc/otp_fuse_controller.adoc:101-102 and its sensing timing diagram).
_SENSE_DONE_LAT = 2

# Test parameters (the contract leaves them to the test).
_FIRST_SENSE_BOUND = 20_000
_SENSE_BOUND_MULT = 4  # injected-sense bound, in sense times
_HOLD_MULT = 2  # held window, in sense times (over the 64-clock sampler window)
_HOLD_READS = 4  # frontdoor reads of EFUSE_PROGRAM_CTRL inside the held window
_POLL_BOUND_MULT = 4  # bound of a program_done or busy poll, in sense times
_REL_SETTLE = 128  # clocks after the release done (over the 64-clock sampler window)
_RST_HOLD = 20
_PASS_HOLD = 2  # clocks a step tag stays on the pass label
# Hold tags of the graded steps (set_ef_hold_tag).
_TAG_SENSE, _TAG_LIFE = 1, 2


def _b(v: int, m: int) -> int:
    return int(bool(v & m))


class _SenseRec:
    """Taps of one sense, from the ``rst_ni`` release to the sense-done rise.

    ``resp`` holds (status, data) of each response strobe and ``strobe_clks`` its
    clock; ``rise_clk`` is the clock on which ``sep_fuse_sense_done_o`` first reads 1.
    ``fsm_strobe_clks`` and ``fsm_rise_clk`` are the same two events at the sensing
    FSM ports (taps ``efuse_shadow_resp_valid_o`` and ``efuse_shadow_sense_done_o``),
    where the specification states the sense-done latency.
    Clock 1 is the first clock with ``rst_ni`` high. ``shim`` is the command-tap
    monitor, started while ``rst_ni`` is low and the command valid is known (the reset
    holds it at 0, so every command it records after ``m0`` is a command of this
    sense); ``m_end`` is its mark at the sense-done rise.
    """

    def __init__(self) -> None:
        self.resp: list[tuple[int, int]] = []
        self.strobe_clks: list[int] = []
        self.rise_clk: int | None = None
        self.fsm_strobe_clks: list[int] = []
        self.fsm_rise_clk: int | None = None
        self.shim: SepShimCmdMonitor | None = None
        self.m0 = None
        self.m_end = None

    def clear(self) -> None:
        self.resp.clear()
        self.strobe_clks.clear()
        self.rise_clk = None
        self.fsm_strobe_clks.clear()
        self.fsm_rise_clk = None

    def cmds(self) -> list:
        """Command records of the sense, from ``m0`` to the sense-done rise."""
        if self.shim is None or self.m_end is None:
            return []
        return [c for c in self.shim.commands_since(self.m0) if c.clk <= self.m_end.clk]

    async def stop(self) -> None:
        if self.shim is not None:
            await self.shim.stop()

    def shape(self, done: bool) -> dict:
        """Graded sense shape; ``done`` says that the monitor saw the rise."""
        cmds = self.cmds()
        reads = sum(int(c.is_read) for c in cmds)
        last = self.fsm_strobe_clks[-1] if self.fsm_strobe_clks else None
        rise = self.fsm_rise_clk
        lat = None if rise is None or last is None else rise - last
        exact = done and len(self.fsm_strobe_clks) == _N_WORDS and lat == _SENSE_DONE_LAT
        ok = done and reads == _SENSE_READ_CMDS and len(self.resp) == _N_WORDS and exact
        return {
            "ok": ok,
            "read_cmds": reads,
            "cmds": len(cmds),
            "strobes": len(self.resp),
            "fsm_strobes": len(self.fsm_strobe_clks),
            "fsm_last_strobe_clk": "none" if last is None else last,
            "fsm_rise_clk": "none" if rise is None else rise,
            "done_lat": "none" if lat is None else lat,
            "done_lat_exp": _SENSE_DONE_LAT,
            "rise_clk": "none" if self.rise_clk is None else self.rise_clk,
        }


@pyuvm.test()
class sep_efuse_shim_response_fault_test(sep_base_test):
    """Sense status bit on one word; program lifecycle with a withheld shim response."""

    required_evidence = ("CHK-SENSE-STATUS", "CHK-PROG-LIFE", "CHK-SENSE-STATUS-CTRLWORD-FEAT")

    async def _rd(self, addr: int) -> int:
        return await self.fd.rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.fd.wr(addr, data)

    async def _direct_bit(self, spare: dict) -> tuple[int, int]:
        """(word, bit) of a programmed spare bit at the direct OTP read."""
        word = await direct_word(self, spare["addr"] // 32)
        return word, (word >> spare["bit"]) & 1

    def _probe_words(self) -> list[int]:
        return probe_words(self, cocotb.top.efuse_shadow_probe_o, _N_WORDS)

    async def _poll_pg(self, mask: int, bound: int) -> int | None:
        """Read ``EFUSE_PROGRAM_CTRL`` until every bit of ``mask`` is 1; None at the bound."""
        dut = cocotb.top
        start = self.clk
        while self.clk - start < bound:
            v = await self._rd(PROGRAM_CTRL_ADDR)
            if v & mask == mask:
                return v
            await ClockCycles(dut.clk_i, 8)
        return None

    async def _sense_mon(self, rec: _SenseRec) -> None:
        """Command and response taps of one sense, into ``rec``.

        Records, from the first clock after ``rst_ni`` was seen low to the
        ``sep_fuse_sense_done_o`` rise, (status, data) and the clock of every clock with
        the response valid at the ``sep`` input (taps ``efuse_shim_resp_*_o``). The
        sense reads words 0 to 255 in order, so response k is the response of word k.
        The clocks of the response valid and the first ``fuse_sense_done_o`` high at
        the sensing FSM ports (taps ``efuse_shadow_*_o``) are recorded in the same
        loop. Commands at the post-guard tap (``efuse_shim_cmd_*_o``) are recorded by a
        ``SepShimCmdMonitor`` started on the first clock with ``rst_ni`` low and the
        command valid known.
        """
        dut = cocotb.top
        seen_reset = False
        clk = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if not self.rd_known(dut.rst_ni) & 1:
                seen_reset = True
                rec.clear()
                clk = 0
                if rec.shim is None and str(dut.efuse_shim_cmd_valid_o.value).strip() in (
                    "0",
                    "1",
                ):
                    rec.shim = SepShimCmdMonitor(dut).start()
                    rec.m0 = rec.shim.mark()
                continue
            if not seen_reset:
                continue
            clk += 1
            if self.rd_known(dut.efuse_shim_resp_valid_o) & 1:
                rec.resp.append(
                    (
                        self.rd_known(dut.efuse_shim_resp_status_o) & 1,
                        self.rd_known(dut.efuse_shim_resp_data_o) & WORD_MASK,
                    )
                )
                rec.strobe_clks.append(clk)
            if self.rd_known(dut.efuse_shadow_resp_valid_o) & 1:
                rec.fsm_strobe_clks.append(clk)
            if rec.fsm_rise_clk is None and self.rd_known(dut.efuse_shadow_sense_done_o) & 1:
                rec.fsm_rise_clk = clk
            if self.rd_known(dut.sep_fuse_sense_done_o) & 1:
                rec.rise_clk = clk
                if rec.shim is not None:
                    rec.m_end = rec.shim.mark()
                return

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check; the first FAIL closes the graded window for the rest of the leaf."""
        if not cond:
            close_graded_window(self.logger)
            self.graded_fail = True
        return self.chk.ok(name, cond, **fields)

    def _ctrl(self, name: str, cond: bool, **fields) -> bool:
        """Log one control; a missing control closes the graded window like a FAIL."""
        if not cond:
            close_graded_window(self.logger)
            self.graded_fail = True
        return self.chk.ctrl(name, cond, **fields)

    def _open_window(self) -> None:
        """Open the graded window unless a check or control of this leaf has failed."""
        if not self.graded_fail:
            open_graded_window(TEST, self.logger)

    async def _release(self, tag: int, ok: bool) -> None:
        """End step ``tag``; its held samples sample only when ``ok`` and no FAIL so far.

        The window is still open here; the caller closes it after.
        """
        set_ef_hold_tag(0, self.logger)
        if not ok or self.graded_fail:
            return
        set_ef_hold_pass(tag, self.logger)
        await ClockCycles(cocotb.top.clk_i, _PASS_HOLD)
        set_ef_hold_pass(0, self.logger)

    async def _injected_sense(
        self,
        w: int,
        staged: list[int],
        sense_bound: int,
        ctl_ok: bool,
        ctl_w: int,
        label: str,
        binned: bool,
    ) -> bool:
        """One injected sense at word ``w`` and its ``CHK-SENSE-STATUS`` grade.

        With ``binned`` the graded window is open from before the reset to the end of
        the sense (``_open_window``: only while no check or control has failed).
        """
        dut = cocotb.top
        p = self.p
        dut.efuse_sense_status_word_i.value = w
        dut.efuse_sense_status_inject_i.value = 1
        if binned:
            self._open_window()
            set_ef_hold_tag(_TAG_SENSE, self.logger)
        rec = _SenseRec()
        resp_task = cocotb.start_soon(self._sense_mon(rec))
        await rst_pulse(self, hold=_RST_HOLD)
        n = await clocks_to_sense(self, sense_bound, started=True)
        await ClockCycles(dut.clk_i, 20)
        resp_done = resp_task.done()
        if not resp_done:
            resp_task.cancel()
        shape = rec.shape(resp_done)
        await rec.stop()
        resp = rec.resp
        # Exactly one response of the sense carries status 1, at word w,
        # with the staged data, and the sense has one response per word.
        err_idx = [k for k, (st, _d) in enumerate(resp) if st]
        resp_w = resp[w] if len(resp) > w else None
        resp_ok = (
            resp_done
            and len(resp) == _N_WORDS
            and err_idx == [w]
            and resp_w is not None
            and resp_w[1] == staged[w]
        )
        probe = self._probe_words()
        got_w = await self._rd(SHADOW_BASE + 4 * w)
        got_w1 = await self._rd(SHADOW_BASE + 4 * (w + 1))
        status = await self._rd(STATUS_ADDR)
        dut.efuse_sense_status_inject_i.value = 0
        others = [i for i in range(_N_WORDS) if i != w and probe[i] != staged[i]]
        rst_w = word_reset(SHADOW_BASE + 4 * w)
        ok = self._grade(
            "SENSE-STATUS",
            n is not None
            and ctl_ok
            and resp_ok
            and shape["ok"]
            and probe[w] == rst_w
            and got_w == rst_w
            and got_w1 == staged[w + 1]
            and not others
            and _b(status, _M_SENSE_DONE) == 1,
            sense=label,
            word=w,
            word_class=p.leg["word_class"],
            got_probe=f"0x{probe[w]:x}",
            got_read=f"0x{got_w:x}",
            reset=f"0x{rst_w:x}",
            staged=f"0x{staged[w]:08x}",
            next_read=f"0x{got_w1:08x}",
            others_equal=int(not others),
            others_bad=",".join(str(i) for i in others[:8]) or "none",
            sense_done=int(n is not None),
            t_sense_inj="none" if n is None else n,
            status_sense_done=_b(status, _M_SENSE_DONE),
            ctl_word=f"0x{ctl_w:08x}",
            resp_strobes=len(resp),
            resp_status_words=",".join(str(k) for k in err_idx[:8]) or "none",
            resp_w_status="none" if resp_w is None else resp_w[0],
            resp_w_data="none" if resp_w is None else f"0x{resp_w[1]:08x}",
            read_cmds=shape["read_cmds"],
            cmds=shape["cmds"],
            fsm_strobes=shape["fsm_strobes"],
            fsm_last_strobe_clk=shape["fsm_last_strobe_clk"],
            fsm_rise_clk=shape["fsm_rise_clk"],
            done_lat=shape["done_lat"],
            done_lat_exp=shape["done_lat_exp"],
            rise_clk=shape["rise_clk"],
        )
        if binned:
            await self._release(_TAG_SENSE, ok)
        close_graded_window(self.logger)
        return ok

    async def _clk_counter(self) -> None:
        while True:
            await RisingEdge(cocotb.top.clk_i)
            self.clk += 1

    def _set_golden(self) -> None:
        """Post-sense shadow golden of the base test: the staged image plus burned bits."""
        set_shadow_golden(self, self.p.image, burned=[b["addr"] for b in self.burned])

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.seed = seed = self.random_seed()
        self.p = p = plan(TEST, seed)
        for line in p.log_lines():
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        w = int(p.leg["word"])
        staged = list(p.image.words)
        if not (10 <= w <= 254) or staged[w] == 0 or staged[w + 1] == 0:
            raise AssertionError(f"SETUP FAIL seed={seed} reason=word_filter w={w}")
        a, b, c = p.leg["spare_a"], p.leg["spare_b"], p.leg["spare_c"]
        t_cyc, m = int(p.leg["timeout_T"]), int(p.leg["hold_m"])
        self.burned: list[dict] = []
        self.graded_fail = False
        close_graded_window(self.logger)
        set_ef_hold_tag(0, self.logger)
        set_ef_hold_pass(0, self.logger)
        dut.efuse_sense_status_inject_i.value = 0
        dut.efuse_sense_status_word_i.value = 0
        dut.efuse_shim_resp_hold_i.value = 0
        self.clk = 0
        cocotb.start_soon(self._clk_counter())

        # Steps 2-3: fixed image, strap 0; control sense with both injects low.
        self.write_efuse_image(p.image)
        ctl_rec = _SenseRec()
        ctl_task = cocotb.start_soon(self._sense_mon(ctl_rec))
        timer = cocotb.start_soon(clocks_to_sense(self, _FIRST_SENSE_BOUND, started=False))
        await self.bring_up_no_cpu(max_cycles=_FIRST_SENSE_BOUND)
        t_sense = await timer
        if t_sense is None:
            raise AssertionError("sense time not measured")
        await ClockCycles(dut.clk_i, 1)
        ctl_sense_done = ctl_task.done()
        if not ctl_sense_done:
            ctl_task.cancel()
        ctl_shape = ctl_rec.shape(ctl_sense_done)
        await ctl_rec.stop()
        self.suppress_host_axi_transaction_info()
        sense_bound = _SENSE_BOUND_MULT * t_sense
        poll_bound = _POLL_BOUND_MULT * t_sense
        hold_win = _HOLD_MULT * t_sense
        self.logger.info(
            "INFO-SHIM-PARAM seed=%d t_sense=%d sense_bound=%d hold_win=%d hold_reads=%d "
            "poll_bound=%d rel_settle=%d",
            seed,
            t_sense,
            sense_bound,
            hold_win,
            _HOLD_READS,
            poll_bound,
            _REL_SETTLE,
        )
        ctl_probe = self._probe_words()
        ctl_w = await self._rd(SHADOW_BASE + 4 * w)
        ctl_w1 = await self._rd(SHADOW_BASE + 4 * (w + 1))
        ctl_ok = ctl_probe == staged and ctl_w == staged[w] and ctl_w1 == staged[w + 1]
        self._ctrl(
            "SENSE-STATUS",
            ctl_ok,
            word=w,
            ctl_word=f"0x{ctl_w:08x}",
            ctl_next=f"0x{ctl_w1:08x}",
            staged=f"0x{staged[w]:08x}",
            probe_equal=sum(int(x == y) for x, y in zip(ctl_probe, staged)),
        )
        self._grade(
            "SENSE-STATUS",
            ctl_shape["ok"],
            sense="control",
            **{k: v for k, v in ctl_shape.items() if k != "ok"},
        )

        # Steps 4-5: injected sense at word w, twice. The first instance runs with the
        # graded window closed. The second always runs; the window is open for it only
        # when no check or control so far failed, so a sense-time FCOV sample is taken
        # only after the same check has passed on an identical sense.
        await self._injected_sense(w, staged, sense_bound, ctl_ok, ctl_w, "injected", False)
        await self._injected_sense(w, staged, sense_bound, ctl_ok, ctl_w, "injected_binned", True)

        # Step 6: control program of a, no hold.
        await self.pulse_rst_ni(max_sense_cycles=sense_bound)
        await self._wr(_PG_TMO_ADDR, _TMO_CYC_RESET)
        ctl_go = self.clk
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(a["addr"], data=1, read_back=0))
        pg = await self._poll_pg(_M_PG_DONE, poll_bound)
        ctl_clks = self.clk - ctl_go if pg is not None else None
        pg = await self._rd(PROGRAM_CTRL_ADDR) if pg is not None else None
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        ctl_word_a, ctl_bit = await self._direct_bit(a)
        ctl_done = pg is not None and _b(pg, _M_PG_DONE) == 1
        ctl_clean = pg is not None and _b(pg, _M_PG_STATUS) == 0 and _b(pg, _M_PG_BUSY) == 0
        self._ctrl(
            "PROG-LIFE",
            ctl_done and ctl_clean and ctl_bit == 1,
            bit_addr=a["addr"],
            ctl_done=int(ctl_done),
            ctl_pg="none" if pg is None else f"0x{pg:08x}",
            ctl_bit_read=ctl_bit,
            ctl_word=f"0x{ctl_word_a:08x}",
        )
        self.burned.append(a)
        self._set_golden()

        # Steps 7-9: held program of b.
        await self.pulse_rst_ni(max_sense_cycles=sense_bound)
        pg_reset = await self._rd(PROGRAM_CTRL_ADDR)
        await self._wr(_PG_TMO_ADDR, _TMO_CYC_RESET)
        cmds = SepShimCmdMonitor(dut).start()
        m_go = cmds.mark()
        dut.efuse_shim_resp_hold_i.value = 1
        self._open_window()
        set_ef_hold_tag(_TAG_LIFE, self.logger)
        held_go = self.clk
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(b["addr"], data=1))
        busy_seen = None
        start = self.clk
        while self.clk - start < poll_bound:
            v = await self._rd(PROGRAM_CTRL_ADDR)
            if _b(v, _M_PG_BUSY) and self.rd(dut.efuse_program_busy_o):
                busy_seen = v
                break
        held = {"n": 0, "bad": 0, "first_bad": None}

        async def _sample() -> None:
            for _ in range(hold_win):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                held["n"] += 1
                busy = self.rd(dut.efuse_program_busy_o)
                done = self.rd(dut.efuse_program_done_o)
                if busy != 1 or done != 0:
                    held["bad"] += 1
                    if held["first_bad"] is None:
                        held["first_bad"] = (held["n"], busy, done)

        reads: list[int] = []
        if busy_seen is not None:
            task = cocotb.start_soon(_sample())
            gap = hold_win // (_HOLD_READS + 1)
            for _ in range(_HOLD_READS):
                await ClockCycles(dut.clk_i, gap)
                reads.append(await self._rd(PROGRAM_CTRL_ADDR))
            await task
        held_span = self.clk - held_go
        if busy_seen is not None:
            await ClockCycles(dut.clk_i, 1)
        held_cmds = len(cmds.programs_since(m_go, address=b["addr"]))
        held_busy = int(
            busy_seen is not None
            and held["bad"] == 0
            and held["n"] == hold_win
            and len(reads) == _HOLD_READS
            and all(_b(r, _M_PG_BUSY) for r in reads)
        )
        held_done = int(busy_seen is None or any(_b(r, _M_PG_DONE) for r in reads))
        dut.efuse_shim_resp_hold_i.value = 0
        rel = await self._poll_pg(_M_PG_DONE, poll_bound)
        rel = await self._rd(PROGRAM_CTRL_ADDR) if rel is not None else None
        await ReadOnly()
        p_busy = self.rd(dut.efuse_program_busy_o)
        p_done = self.rd(dut.efuse_program_done_o)
        p_err = self.rd(dut.efuse_program_error_o)
        await ClockCycles(dut.clk_i, _REL_SETTLE)
        set_ef_hold_tag(0, self.logger)
        await cmds.stop()
        await self._wr(PROGRAM_CTRL_ADDR, 0)
        word_b, bit_b = await self._direct_bit(b)
        hook = held_cmds >= 1 and ctl_clks is not None and ctl_clks < held_span
        fields = {
            "check": "PROG-LIFE",
            "held_prog_cmds": held_cmds,
            "bit_addr": b["addr"],
            "ctl_clks": "none" if ctl_clks is None else ctl_clks,
            "held_span": held_span,
        }
        if hook:
            self.chk.ctrl("HOOK", True, **fields)
        else:
            self._grade("HOOK", False, **fields)
        rel_done = rel is not None and _b(rel, _M_PG_DONE) == 1
        rel_status = None if rel is None else _b(rel, _M_PG_STATUS)
        rel_busy = None if rel is None else _b(rel, _M_PG_BUSY)
        ok = self._grade(
            "PROG-LIFE",
            hook
            and held_busy == 1
            and held_done == 0
            and rel_done
            and rel_status == 0
            and rel_busy == 0
            and bit_b == 1
            and ctl_done
            and ctl_clean
            and ctl_bit == 1,
            bit_addr=b["addr"],
            held_busy=held_busy,
            held_done=held_done,
            held_samples=held["n"],
            held_bad=held["bad"],
            held_first_bad="none" if held["first_bad"] is None else held["first_bad"],
            held_reads=",".join(f"0x{r:08x}" for r in reads) or "none",
            rel_done=int(rel_done),
            rel_status="none" if rel_status is None else rel_status,
            rel_busy="none" if rel_busy is None else rel_busy,
            rel_probe=f"{p_busy}{p_done}{p_err}",
            bit_read=bit_b,
            word_read=f"0x{word_b:08x}",
            ctl_done=int(ctl_done),
            ctl_bit_read=ctl_bit,
            pg_after_reset=f"0x{pg_reset:08x}",
        )
        await self._release(_TAG_LIFE, ok and hook)
        close_graded_window(self.logger)
        self.burned.append(b)
        self._set_golden()

        # Step 10: timeout cell, logged only.
        await self.pulse_rst_ni(max_sense_cycles=sense_bound)
        await self._wr(_PG_TMO_ADDR, _TMO_EN | (t_cyc & _TMO_CYC))
        dut.efuse_shim_resp_hold_i.value = 1
        await self._wr(PROGRAM_CTRL_ADDR, program_ctrl_word(c["addr"], data=1))
        await ClockCycles(dut.clk_i, m * t_cyc)
        v = await self._rd(PROGRAM_CTRL_ADDR)
        dut.efuse_shim_resp_hold_i.value = 0
        self.logger.info(
            "OBS-PROG-TIMEOUT LOG seed=%d cycles=%d held=%dx busy=%d done=%d status=%d bit_addr=%d",
            seed,
            t_cyc,
            m,
            _b(v, _M_PG_BUSY),
            _b(v, _M_PG_DONE),
            _b(v, _M_PG_STATUS),
            c["addr"],
        )
        await ClockCycles(dut.clk_i, 64)
        await self._wr(PROGRAM_CTRL_ADDR, 0)

        # Step 11: status bit on the sense response of one control word.
        cw = int(p.leg["ctrl_word"])
        dut.efuse_sense_status_word_i.value = cw
        dut.efuse_sense_status_inject_i.value = 1
        await rst_pulse(self, hold=_RST_HOLD)
        n = await clocks_to_sense(self, sense_bound, started=True)
        await ClockCycles(dut.clk_i, 20)
        await ReadOnly()
        shadow = self._probe_words()[cw]
        done_o = self.rd(dut.sep_fuse_sense_done_o, allow_unknown=True)
        feat = self.rd_known(dut.lcc_feat_ctrl_probe_o)
        await RisingEdge(dut.clk_i)
        want = word_reset(SHADOW_BASE + 4 * cw)
        sensed = list(staged)
        sensed[cw] = want
        sip_w, sys_w = field_word("SIP_DIS"), field_word("SYS_DIS")
        row = feat_ctrl_profile(
            sensed[field_word("LC_STATE")] & 0xF,
            sensed[sip_w] | sensed[sip_w + 1] << 32,
            sensed[sys_w] | sensed[sys_w + 1] << 32,
        )
        self._grade(
            "SENSE-STATUS-CTRLWORD-FEAT",
            done_o == 1 and feat == row.value,
            word=cw,
            feat=f"0x{feat:016x}",
            exp=f"0x{row.value:016x}",
            state=row.state,
            row=row.row,
            sense_done=done_o,
        )
        if cw == _N_WORDS - 1:
            self.logger.info(
                "OBS-SENSE-STATUS-CTRLWORD LOG seed=%d word=%d shadow=0x%08x staged=0x%08x "
                "sense_done=%d t_sense=%s feat=0x%016x",
                seed,
                cw,
                shadow,
                staged[cw],
                done_o,
                "none" if n is None else n,
                feat,
            )
        else:
            self._grade(
                "SENSE-STATUS-CTRLWORD",
                n is not None and done_o == 1 and staged[cw] != want and shadow == want,
                word=cw,
                shadow=f"0x{shadow:08x}",
                want=f"0x{want:08x}",
                staged=f"0x{staged[cw]:08x}",
                sense_done=done_o,
                t_sense="none" if n is None else n,
            )
        dut.efuse_sense_status_inject_i.value = 0
        self.chk.finish()
