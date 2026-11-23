# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A failed entropy health test stops the signed boot; the backup slot is not tried.

rom.adoc, Entropy Chain Bring-Up:

    [SEP-ROM-ENT-020] A failed bring-up shall stop the boot, reported as
    `SEP_MSG_ENTROPY_INIT_FAILED` with a console marker naming the stage that failed, and halt on
    `ROM_ERR_ENTROPY_INIT_FAILED`. It shall *not* be treated as a per-slot failure: the requirement
    is device-level, so the backup manifest slot carries the identical requirement and rotating to
    it cannot help, while allowing the failure to surface downstream would report it as a
    signature or decryption error and name the wrong cause.

    |B — generate |Enable the ESRC ring oscillators, then poll `MAIN_SM_STATUS.BOOT_PHASE_DONE`
    for the startup health test to pass, bounded by a timeout. A health-test failure or timeout
    fails the boot per SEP-ROM-ENT-020.

rom.adoc, Failure Convergence and Fatal ROM Error Codes, which say what "halt on" a code means:

    [SEP-ROM-RETRY-050] Every fatal path in the ROM shall converge in a single failure routine
    (`rom_err_fail`) that (a) records the error code in `bl0_state.error_code`, (b) writes the
    encoded `ERROR` status to `cold_scratch[1]`, (c) writes the FAIL verdict (`0xDEADBEEF`) to
    `cold_scratch[0]`, and (d) parks in `wfi`.

    The ROM core's own codes, listed in `include/errors.h`, keep the upper half zero, so
    `rom_err_fail()` also posts them to `cold_scratch[1]` as an ERROR status

    |`ERROR` |`0x0F` |Fatal; last word before the ROM parks.
    |`ROM_ERR_ENTROPY_INIT_FAILED` |`0xF009` |Entropy bring-up failed (SEP-ROM-ENT-020).

Status words are STATUS_ENCODE(type, 1 = BL0, code), codes from
hw/sys/sep/doc/gen/status_values.adoc. The noise driver is off and ``+esrc_noise_force`` stays
on, so every decorrelator input holds 0 and the startup health test fails in Phase B of the
first bring-up, which the signature callback of the primary slot starts. The failure time is the
first of the stage marker and the SEP_MSG_ENTROPY_INIT_FAILED word.

* CHK-ENTROPY-FATAL: a SEP_MSG_ENTROPY_INIT_FAILED word follows SEP_MSG_ENTROPY_INIT_START;
  the last status word is ERROR ROM_ERR_ENTROPY_INIT_FAILED (0x0F01F009) and comes after it;
  the last verdict word is 0xDEADBEEF.
* CHK-STAGE-MARKER: a console line between SEP_MSG_ENTROPY_INIT_START and the failure report
  names the health test.
* CHK-NO-SLOT-RETRY: after the failure, no slot console marker (MANIFEST_PRIMARY,
  MANIFEST_BACKUP, MANIFEST_SRC=, MANIFEST_ERR=, MANIFEST_ALL_FAILED), no MANIFEST_LOAD_START or
  MANIFEST_LOAD_FAILED word, and no SPI flash chip-select assertion.
* CHK-HALTED: for 20,000 clk after the verdict the retired PCs span at most 64 bytes and
  cold_scratch[1], cold_scratch[0] and the console do not change.

Partial coverage. Not graded: the other bring-up failures (timeout, FIFO drain, FIPS lock, EDN
Instantiate, source-selection lock, external source); the decryption-callback entry;
`bl0_state.error_code` and the `wfi` instruction itself; the type of the
SEP_MSG_ENTROPY_INIT_FAILED word, which ENT-020 does not state; status-ring reporting (the bench
ring is invalid, so each insert reports STATUS_REPORTING_INVALID); that bring-up is started by
the signature callback. CTRL-HEALTH-TRIPPED reads the
entropy source registers over the debug-module system bus after the halt window. The leaf runs
`sep_rom_ot_secure_boot_test` and keeps its transport markers; its success markers and OTBN
entropy check are replaced.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env import sep_spi_slot_evidence as ev
from env.sep_chk_log import SepChkLog
from env.sep_jtag_dmi import (
    DM_DMCONTROL,
    DMCONTROL_DMACTIVE,
    IR_DMI,
    IR_WIDTH,
    PIN_MAP,
    SepJtagDmi,
)
from env.sep_manifest_mutate import PRIMARY_MANIFEST_OFFSET
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver
from ocah_jtag_vip import OcahJtagMasterDriver
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test as _Base
from sep_reg_meta import ENTROPY_SOURCE, sym

_ERROR = 0x0F
_ENTROPY_INIT_START = 0x0225
_ENTROPY_INIT_FAILED = 0x0226
_MANIFEST_LOAD_START = 0x0212
_MANIFEST_LOAD_FAILED = 0x0213
_ROM_ERR_ENTROPY_INIT_FAILED = 0xF009
_VERDICT_FAIL = 0xDEADBEEF
_BL0 = 1 << 16


def _status(kind: int, code: int) -> int:
    return (kind << 24) | _BL0 | code


_TERMINAL = _status(_ERROR, _ROM_ERR_ENTROPY_INIT_FAILED)
_SLOT_MARKERS = (
    "MANIFEST_PRIMARY",
    "MANIFEST_BACKUP",
    "MANIFEST_SRC=",
    "MANIFEST_ERR=",
    "MANIFEST_ALL_FAILED",
)
_HALT_CYCLES = 20_000
_HALT_PC_SPAN = 64

_ESRC_MAIN_SM = sym("ENTROPY_SOURCE_MAIN_SM_STATUS_REG_ADDR")
_ESRC_INTR = sym("ENTROPY_SOURCE_INTR_STATUS_REG_ADDR")
_ESRC_REPCNT = sym("ENTROPY_SOURCE_REPCNT_TOTAL_FAILS_REG_ADDR")
_SM = ENTROPY_SOURCE.fields("MAIN_SM_STATUS")
_ALERT_OR_ERR = _SM["ALERT"]["bm"] | _SM["ERR"]["bm"]
_BOOT_PHASE_DONE = _SM["BOOT_PHASE_DONE"]["bm"]
_HT_FAILED = ENTROPY_SOURCE.fields("INTR_STATUS")["HEALTH_TEST_FAILED"]["bm"]
_TCK_CLKS = 4
_TRST_TCK = 4
_SB_BUSY_READS = 1024

_CS, _NOISE, _RO_EN = "spi_cs_n_o", "esrc_decor_noise_o", "esrc_ro_enable_o"


class _HaltObserver(SepRomObserver):
    """Also keeps every retired PC once cold_scratch[0] holds the FAIL verdict."""

    def __init__(self, test) -> None:
        super().__init__(test, keep=lambda _insn: False, tracker=False, watch=(_CS, _NOISE, _RO_EN))
        self.after_verdict: list[tuple[int, int]] = []
        self.last_before_verdict: int | None = None

    def record(self, t: int, pc: int, insn: int, exc: bool, ecause: int, interrupt: bool):
        if self.verdict and self.verdict[-1][1] == _VERDICT_FAIL:
            self.after_verdict.append((t, pc))
        else:
            self.last_before_verdict = t
        return super().record(t, pc, insn, exc, ecause, interrupt)


def _ps(t: int | None) -> int:
    return -1 if t is None else int(t)


def _code_t(status: list[tuple[int, int]], code: int, after: int = -1) -> int | None:
    """Time of the first BL0 status word with this code after ``after``, any type."""
    return next(
        (t for t, w in status if t > after and w & 0x00FF_FFFF == _BL0 | code),
        None,
    )


@pyuvm.test()
class sep_rom_entropy_health_fail_terminal_test(_Base):
    drive_esrc_noise = False
    verify_otbn_edn = False
    max_run_cycles = 4_000_000
    # Transport markers stay; the parent's success markers cannot appear on a refused boot.
    required_markers = ("BOOT_SPI", "MANIFEST_SRC=0x00001000", "PUBK_AUTHORIZED")
    required_evidence = (
        "CHK-ENTROPY-FATAL",
        "CHK-STAGE-MARKER",
        "CHK-NO-SLOT-RETRY",
        "CHK-HALTED",
        "CHK-ROM-PATH",
    )

    def log_transport(self, flash) -> None:
        self._flash_txns = list(flash.get_transactions())
        self.logger.info("flash transport: %s", ev.summarize(self._flash_txns, self._image_len))

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self.sb.expect_fw_pass = False
        self._flash_txns: list = []
        self._image_len = 0
        clk = cocotb.top.clk_i
        obs = _HaltObserver(self).start()
        esrc: dict = {}
        try:
            await super().run_scenario()
        finally:
            await ClockCycles(clk, _HALT_CYCLES + 2 * STORE_LAG_MAX_CYCLES)
            t_end = int(get_sim_time("ps"))
            esrc = await self._read_esrc()
            await obs.stop()
            self._grade(obs, t_end, esrc)
        self.chk.finish()

    async def _read_esrc(self) -> dict:
        """Entropy source state read by the debug-module system-bus master, not by the ROM."""
        dut = cocotb.top
        out: dict = {"error": "none"}
        tap = OcahJtagMasterDriver(
            dut,
            name="sep_core_tap",
            tck_period_ns=int(round(_TCK_CLKS * self.cfg.sys_clk_period_ns * 1000)),
            ir_width=IR_WIDTH,
            tap_type="dtm",
            signal_map=dict(PIN_MAP),
            time_unit="ps",
        )
        dmi = SepJtagDmi(tap, dut=dut, log=self.logger, busy_bound=_SB_BUSY_READS)
        dut.dmi_core_enable_i.value = 1
        dmi.take_pins()
        try:
            await dmi.trst_pulse(tck_cycles=_TRST_TCK)
            await tap.goto_state("RUN_TEST_IDLE")
            await tap.shift_ir(IR_DMI, IR_WIDTH, back_to_rti=True)
            await dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
            for name, addr in (
                ("main_sm", _ESRC_MAIN_SM),
                ("intr", _ESRC_INTR),
                ("repcnt", _ESRC_REPCNT),
            ):
                out[name], out[f"{name}_sberr"] = await dmi.sba_read(addr, size=4)
        # Any failure of the debug path fails CTRL-HEALTH-TRIPPED instead of skipping the grade.
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            dmi.release_pins()
            dut.dmi_core_enable_i.value = 0
        return out

    def _grade(self, obs: _HaltObserver, t_end: int, esrc: dict) -> None:
        chk = self.chk
        status = obs.status
        clk_ps = (
            (obs.first[-1].t_ps - obs.first[0].t_ps) // (obs.first[-1].cycle - obs.first[0].cycle)
            if len(obs.first) > 1
            else 0
        )

        # esrc_ro_enable_o is already set out of reset, so this shows only that the noise stayed 0.
        ro = obs.watched[_RO_EN]
        t_ro = next((t for t, v in ro if v), None)
        noise = obs.watched[_NOISE]
        nonzero = [t for t, v in noise if v and t_ro is not None and t >= t_ro]
        chk.ctrl(
            "NOISE-ZERO-WHOLE-RUN",
            t_ro is not None and not nonzero,
            ro_enable_ps=_ps(t_ro),
            ro_enable=f"0x{ro[-1][1]:03x}" if ro else "none",
            noise_changes=len(noise),
            nonzero_after_ro=len(nonzero),
        )

        main_sm = esrc.get("main_sm")
        intr = esrc.get("intr")
        sberr = [esrc.get(f"{n}_sberr") for n in ("main_sm", "intr", "repcnt")]
        chk.ctrl(
            "HEALTH-TRIPPED",
            esrc.get("error") == "none"
            and sberr == [0, 0, 0]
            and None not in (main_sm, intr)
            and bool(main_sm & _ALERT_OR_ERR)
            and not main_sm & _BOOT_PHASE_DONE
            and bool(intr & _HT_FAILED),
            main_sm_status="none" if main_sm is None else f"0x{main_sm:08x}",
            intr_status="none" if intr is None else f"0x{intr:08x}",
            repcnt_total_fails=esrc.get("repcnt", -1),
            sberr=sberr,
            dmi_error=esrc.get("error"),
        )

        t_start = _code_t(status, _ENTROPY_INIT_START)
        t_failed = _code_t(status, _ENTROPY_INIT_FAILED, -1 if t_start is None else t_start)
        failed_word = next((w for t, w in status if t == t_failed), None)
        t_term = _code_t(status, _ROM_ERR_ENTROPY_INIT_FAILED)
        last_status = status[-1][1] if status else None
        verdict = obs.verdict[-1] if obs.verdict else (None, None)
        chk.ok(
            "ENTROPY-FATAL",
            None not in (t_start, t_failed, t_term, verdict[0])
            and last_status == _TERMINAL
            and t_failed < t_term <= verdict[0]
            and verdict[1] == _VERDICT_FAIL,
            entropy_init_start_ps=_ps(t_start),
            entropy_init_failed_ps=_ps(t_failed),
            entropy_init_failed_word="none" if failed_word is None else f"0x{failed_word:08x}",
            terminal_ps=_ps(t_term),
            last_status="none" if last_status is None else f"0x{last_status:08x}",
            expected_last=f"0x{_TERMINAL:08x}",
            verdict="none" if verdict[1] is None else f"0x{verdict[1]:08x}",
            verdict_ps=_ps(verdict[0]),
        )
        chk.obs(
            "STATUS-TAIL",
            words=[f"0x{w:08x}" for t, w in status if t_start is not None and t >= t_start],
        )

        marker_end = t_failed if t_failed is not None else verdict[0]
        stage = [
            (t, line)
            for t, line in obs.console
            if t_start is not None
            and marker_end is not None
            and t_start < t <= marker_end
            and "HEALTH" in line.upper()
        ]
        chk.ok(
            "STAGE-MARKER",
            bool(stage),
            marker=stage[0][1] if stage else "none",
            marker_ps=_ps(stage[0][0] if stage else None),
            window_ps=f"{_ps(t_start)}..{_ps(marker_end)}",
        )

        t_fail = min(
            (t for t in (t_failed, stage[0][0] if stage else None) if t is not None),
            default=t_start,
        )
        cs = obs.watched[_CS]
        cs_low = [t for (t, v), (_, prev) in zip(cs[1:], cs) if v == 0 and prev == 1]
        primary = ev.covering_read(ev.reads(self._flash_txns), PRIMARY_MANIFEST_OFFSET)
        chk.ctrl(
            "SPI-LIVE",
            t_fail is not None
            and any(t < t_fail for t in cs_low)
            and primary is not None
            and bool(cs)
            and cs[-1][1] == 1,
            cs_assertions_before_fail=sum(1 for t in cs_low if t_fail is not None and t < t_fail),
            primary_manifest_read=int(primary is not None),
            cs_last=cs[-1][1] if cs else -1,
        )
        after = t_fail if t_fail is not None else 0
        lines_after = [line for t, line in obs.console if t > after]
        retry_lines = [line for line in lines_after if any(m in line for m in _SLOT_MARKERS)]
        retry_words = [
            f"0x{w:08x}"
            for t, w in status
            if t > after and w & 0xFFFF in (_MANIFEST_LOAD_START, _MANIFEST_LOAD_FAILED)
        ]
        cs_after = [t for t in cs_low if t > after]
        chk.ok(
            "NO-SLOT-RETRY",
            t_fail is not None and not retry_lines and not retry_words and not cs_after,
            fail_ps=_ps(t_fail),
            slot_lines=retry_lines[:4],
            slot_words=retry_words[:4],
            cs_assertions_after=len(cs_after),
            first_cs_after_ps=_ps(cs_after[0] if cs_after else None),
        )
        rds = ev.reads(self._flash_txns)
        chk.obs(
            "FLASH-READS",
            reads=len(rds),
            primary=len(ev.slot_read_indices(rds, "primary", self._image_len or 1)),
            backup=len(ev.slot_read_indices(rds, "backup", self._image_len or 1))
            if self._image_len
            else -1,
        )

        t_v = verdict[0]
        w_end = None if t_v is None or not clk_ps else t_v + _HALT_CYCLES * clk_ps
        chk.ctrl(
            "HALT-WINDOW",
            w_end is not None
            and t_end >= w_end
            and obs.last_before_verdict is not None
            and t_v - obs.last_before_verdict <= STORE_LAG_MAX_CYCLES * clk_ps,
            verdict_ps=_ps(t_v),
            window_end_ps=_ps(w_end),
            observed_to_ps=t_end,
            last_retire_before_verdict_ps=_ps(obs.last_before_verdict),
            clk_ps=clk_ps,
        )
        in_win = [pc for t, pc in obs.after_verdict if w_end is not None and t <= w_end]
        span = max(in_win) - min(in_win) if in_win else 0
        moved = [
            f"0x{w:08x}"
            for t, w in status
            if t_v is not None and w_end is not None and t_v < t <= w_end
        ]
        v_moved = [
            f"0x{w:08x}"
            for t, w in obs.verdict
            if t_v is not None and w_end is not None and t_v < t <= w_end
        ]
        printed = [line for t, line in obs.console if t_v is not None and t > t_v]
        chk.ok(
            "HALTED",
            w_end is not None
            and span <= _HALT_PC_SPAN
            and not moved
            and not v_moved
            and not printed,
            retired_in_window=len(in_win),
            pc_span=span,
            pcs=[f"0x{p:08x}" for p in sorted(set(in_win))[:8]],
            status_changes=moved,
            verdict_changes=v_moved,
            console_after=printed[:4],
        )
