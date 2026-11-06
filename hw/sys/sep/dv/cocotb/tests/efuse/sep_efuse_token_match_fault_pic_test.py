# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A token-comparator fault reaches the CPU on PIC source 40, and masking meie[40] stops re-entry.

cpu mode. Firmware arms PIC source 40 and presents a SEC_DISABLE token.
The host injects a collapse on that comparator after READY (tb port; no
LSU conflict). Firmware proves the ISR claim id, the SEC_DISABLE sticky
bit, and that masking meie[40] stops re-entry. TOKEN_MATCH_FAULT is sw=r;
there is no W1C. With meie[40] enabled again and the handler not masking,
the handler enters at least twice in a fixed window
(doc/programmer/src/sep-programming.adoc:235-237 "an unmasked handler
re-enters"); the firmware storm cap stops it after five entries.

Real fuse sense on a blank OTP image, staged with write_efuse_image before
bring-up, so the base test's post-sense shadow compare runs. The SEC_DISABLE
compare is not fuse-gated.

``sep_ras_o.token_match_fault`` is "the token comparator redundancy fault on
any token, a level sticky until reset" (``hw/sys/sep/rtl/sep_pkg.sv``,
``sep_ras_t``, the field comments that ``hw/sys/sep/doc/port_table.adoc:130``, row
``sep_ras_o``, names: "The ``sep_pkg::sep_ras_t`` field comments state how each one is
held and cleared"). The
host watches it on every clock on the bench tap ``sep_ras_probe_o``
(``env/sep_ras_map``) and grades it as three checks, each on its own line:

* CHK-RAS-TOKEN_MATCH_FAULT-IDLE   0 on every clock from the CPU release to
  the inject.
* CHK-RAS-TOKEN_MATCH_FAULT-RISE   1 before the firmware console line
  ``CHK-PIC-CLAIM PASS``.
* CHK-RAS-TOKEN_MATCH_FAULT-SHAPE  no fall from the rise to the end of the
  run, which holds ``_RAS_HOLD_CYCLES`` clocks after the inject is released,
  and 1 at the end.

Control: two clocks after the release, CTRL-RAS-TOKEN_MATCH_FAULT-RELEASE reads
back ``token_cmp_fault_inject_i`` and fails the leaf unless it is off; the line
also logs the SEC_DIS comparator rails.

The leaf applies no reset after the fault, so the clear is
``INFO-RAS-TOKEN_MATCH_FAULT-CLEAR``; the rise delay after the inject is
``OBS-RAS-TOKEN_MATCH_FAULT-DELAY``.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import SepEfuseImage
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_ras_map import RasChkLines, check_tap_width, ras_bit
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_CMP_INJECT_COLLAPSE,
    TOKEN_CMP_INJECT_OFF,
    TOKEN_CMP_SEL_SEC,
)

_TEST = "sep_efuse_token_match_fault_pic_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "token_match_fault_pic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "token_match_fault_pic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "token_match_fault_pic_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP token-match fault PIC test"
_READY = 0xE9050040
_READY_POLL = 200_000
# Clocks the leaf keeps the run open after the inject is released, so the
# hold of the sticky field does not rest on the live inject.
_RAS_HOLD_CYCLES = 2_000
_RAS_FIELD = "token_match_fault"
_RAS = "RAS-TOKEN_MATCH_FAULT"
_RAS_HALVES = ("IDLE", "RISE", "SHAPE")
_CLAIM_LINE = "CHK-PIC-CLAIM PASS"


@pyuvm.test()
class sep_efuse_token_match_fault_pic_test(sep_base_test):
    """The injected SEC_DISABLE collapse is claimed as PIC 40, sets the sticky bit, and masks."""

    build_env = False
    required_evidence = tuple(f"CHK-{_RAS}-{half}" for half in _RAS_HALVES)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _scratch0(self) -> int:
        return self.rd(cocotb.top.scratch_cold_probe_o, mask=0xFFFF_FFFF)

    async def _ras_open(self) -> None:
        """Start the per-clock watch of the field at the CPU release (boot hook)."""
        check_tap_width(cocotb.top.sep_ras_probe_o)
        self.ras_w.start()
        self.ras_m_open = self.ras_w.mark()

    async def _ras_claim_clock(self) -> None:
        """Record the watch clock at which the console first holds ``_CLAIM_LINE``."""
        seen = 0
        while True:
            await RisingEdge(cocotb.top.clk_i)
            if len(self.sb.console) != seen:
                seen = len(self.sb.console)
                if _CLAIM_LINE in self.sb.console_text():
                    self.ras_claim_clk = self.ras_w.clk
                    return

    def _ras_grade(self) -> None:
        """CHK-RAS-TOKEN_MATCH_FAULT-IDLE, -RISE and -SHAPE; the clear and the delay are OBS."""
        w, m_open, m_inj = self.ras_w, self.ras_m_open, self.ras_m_inj
        chk = self.ras_chk
        if m_open is None or m_inj is None:
            for half in _RAS_HALVES:
                chk.ok(
                    f"{_RAS}-{half}",
                    False,
                    not_reached="window",
                    open_clk=m_open.clk if m_open else None,
                    inject_clk=m_inj.clk if m_inj else None,
                )
            return
        ctrl_clk = m_inj.clk - m_open.clk
        ctrl_high = m_inj.high[_RAS_FIELD] - m_open.high[_RAS_FIELD]
        chk.ok(
            f"{_RAS}-IDLE",
            ctrl_clk > 0 and ctrl_high == 0,
            window="cpu_release..inject",
            clocks=ctrl_clk,
            high_clk=ctrl_high,
            exp=0,
        )
        rises = w.rise_clks_since(m_inj)
        falls = w.fall_clks_since(m_inj)
        claim = self.ras_claim_clk
        rise = rises[0] if rises else None
        chk.ok(
            f"{_RAS}-RISE",
            rise is not None and claim is not None and rise <= claim,
            rise_clk=rise,
            claim_line_clk=claim,
            inject_clk=m_inj.clk,
            exp="rise_before_claim",
        )
        end_clk, level = w.clk, w.level()
        late = [c for c in falls if rise is not None and c > rise]
        held_after_release = end_clk - self.ras_rel_clk
        chk.ok(
            f"{_RAS}-SHAPE",
            rise is not None and not late and level == 1 and held_after_release >= _RAS_HOLD_CYCLES,
            hold="rise..end",
            falls_after_rise=late[:4],
            level_at_end=level,
            clocks_after_inject_release=held_after_release,
            exp_min=_RAS_HOLD_CYCLES,
        )
        chk.obs(
            f"{_RAS}-DELAY", inject_to_rise_clk=rise - m_inj.clk if rise is not None else "none"
        )
        chk.info(f"{_RAS}-CLEAR", reset_in_leaf=0, held="to_end_of_window", level_at_end=level)

    def _ras_release_ctrl(self) -> None:
        """Read back the comparator inject after its release; anything but off fails.

        The SEC_DIS comparator rails (``token_cmp_match_{p,n}_o`` bits 8:6) are
        logged with it.
        """
        dut = cocotb.top
        inj = self.rd_known(dut.token_cmp_fault_inject_i)
        ok = inj == TOKEN_CMP_INJECT_OFF
        head = (
            "CTRL-RAS-TOKEN_MATCH_FAULT-RELEASE seen"
            if ok
            else "CTRL-MISSING RAS-TOKEN_MATCH_FAULT-RELEASE"
        )
        line = (
            f"{head}: seed={self.random_seed()} inject={inj} exp={TOKEN_CMP_INJECT_OFF} "
            f"sec_match_p={str(dut.token_cmp_match_p_o.value)[:3]} "
            f"sec_match_n={str(dut.token_cmp_match_n_o.value)[:3]}"
        )
        if not ok:
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)

    async def _inject_after_ready(self) -> None:
        for _ in range(_READY_POLL):
            await ClockCycles(cocotb.top.clk_i, 1)
            if self._scratch0() == _READY:
                if self.ras_m_open is not None:
                    self.ras_m_inj = self.ras_w.mark()
                open_graded_window(_TEST, self.logger)
                cocotb.top.token_cmp_fault_sel_i.value = TOKEN_CMP_SEL_SEC
                cocotb.top.token_cmp_fault_inject_i.value = TOKEN_CMP_INJECT_COLLAPSE
                self.logger.info("token-fault PIC: SEC_DISABLE collapse inject on")
                return
        raise AssertionError("firmware never published READY for the PIC inject")

    async def run_scenario(self) -> None:
        # Blank OTP image: the golden for the post-sense shadow compare.
        # dv_sim_prestage.py stages the same blank image for the t=0 load.
        self.write_efuse_image(SepEfuseImage())
        self.sb.expected_line = _BANNER
        self.ras_w = SepBitWatch(
            cocotb.top.sep_ras_probe_o, {_RAS_FIELD: ras_bit(_RAS_FIELD)}, name="sep_ras"
        )
        self.ras_m_open = self.ras_m_inj = None
        self.ras_claim_clk: int | None = None
        self.ras_chk = RasChkLines(self.logger, self.random_seed())
        cocotb.start_soon(self._inject_after_ready())
        claim = cocotb.start_soon(self._ras_claim_clock())
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
            after_bring_up_hook=self._ras_open,
        )
        cocotb.top.token_cmp_fault_inject_i.value = TOKEN_CMP_INJECT_OFF
        self.ras_rel_clk = self.ras_w.clk
        # Two clocks cover the falling-edge drain and release of the comparator force.
        await ClockCycles(cocotb.top.clk_i, 2)
        self._ras_release_ctrl()
        await ClockCycles(cocotb.top.clk_i, _RAS_HOLD_CYCLES - 1)
        claim.cancel()
        console = self.sb.console_text()
        for needle in (
            "CHK-PIC-CLAIM PASS:",
            "CHK-PIC-FAULT PASS:",
            "CHK-PIC-MASK PASS:",
            "CHK-PIC-LEVEL-REENTRY PASS:",
        ):
            if needle not in console:
                raise AssertionError(f"firmware missing {needle!r}")
        # The needles show the firmware reached each check; the magic is what
        # says it passed. Require both before logging a PASS summary.
        assert self.sb.fw_done and self.sb.fw_pass, (
            "firmware did not signal a PASS verdict; the console needles are not "
            "a verdict on their own"
        )
        self.logger.info(
            "CHK-PIC-40 PASS: claim id 40, SEC_DISABLE sticky, mask stopped re-entry, "
            "unmasked handler re-entered"
        )
        self._ras_grade()
        close_graded_window(self.logger)
        await self.ras_w.stop()
        if self.ras_chk.fails:
            raise AssertionError(
                f"{len(self.ras_chk.fails)} RAS check(s) failed: " + "; ".join(self.ras_chk.fails)
            )
