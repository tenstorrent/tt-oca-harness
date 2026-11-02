# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A flash read that fails on every attempt is retried a bounded number of times, then falls back.

rom.adoc, Transfer Hardening:

    [SEP-ROM-SPI-030] A transport-level read fault shall be retried a bounded number of times
    (OpenTitan driver: 3) before being reported to the loader; a read that still fails is
    handled by slot fallback (<<sec:retry>>), never by accepting partial data.

rom.adoc, Retry and Backup Bank, which say what slot fallback is and how it ends:

    [SEP-ROM-RETRY-010] In `BOOT_MODE_SPI` the ROM shall attempt at most two slots, indexed
    `slot = attempt XOR rotate_update`: with the strap clear, primary (`0x1000`) then backup
    (`0x41000`)

    [SEP-ROM-RETRY-050] Every fatal path in the ROM shall converge in a single failure routine
    (`rom_err_fail`) that (a) records the error code in `bl0_state.error_code`, (b) writes the
    encoded `ERROR` status to `cold_scratch[1]`, (c) writes the FAIL verdict (`0xDEADBEEF`) to
    `cold_scratch[0]`, and (d) parks in `wfi`.

rom.adoc, tbl:stage_trace, [S23] manifest:

    `MANIFEST_LOAD_START` (per attempt) ... a failed storage read (WARN): ... `SPI_OT_*` (flash
    transport) ... `MANIFEST_LOAD_FAILED` (all slots exhausted)

Status words are STATUS_ENCODE(type, 1 = BL0, code), codes from the registry
include/status_values.h (SEP-ROM-STAT-030). The OpenTitan driver retries 3 times, so a read makes
at most 1 + 3 = 4 transport attempts. From the first MANIFEST_LOAD_START word to the verdict,
dma_host_rsp_err_inject_i makes every secure-DMA host response SLVERR, so each OpenTitan SPI DMA
read fails on its first beat in both slots. Each flash frame is matched to the chip-select
assertion of the same index.

* CTRL-FAULT-APPLIED: the pin rises after the first MANIFEST_LOAD_START word and is 1 at the
  chip-select assertion of every read frame in either slot; each slot's last read frame is
  followed by a WARN SPI_OT_TRANSPORT_ERROR word before the next slot's first frame; the ROM
  console reports a DMA error.
* CHK-READ-RETRIED ("shall be retried ... before being reported to the loader"): at least 2 read
  frames at the primary manifest address before the first backup frame and at least 2 at the
  backup manifest address; each slot's WARN SPI_OT_TRANSPORT_ERROR word follows its last read
  frame.
* CHK-ATTEMPTS-BOUNDED ("a bounded number of times (OpenTitan driver: 3)"): at most 4 read frames
  at each slot's manifest address.
* CHK-NO-PARTIAL-USE ("never by accepting partial data"): no MANIFEST_VALIDATED or
  PAYLOAD_VALIDATED word, no OCA_BODY=, MANIFEST_OK or PAYLOAD_OK console line, and no read frame
  in a slot returns a byte outside the span of that slot's first read frame.
* CHK-FALLBACK-OR-TERMINAL ("handled by slot fallback"; RETRY-010, RETRY-050): every read frame
  is inside the primary or backup slot span; a MANIFEST_LOAD_START word between the last primary
  frame and the first backup frame; after the last backup frame an ERROR MANIFEST_LOAD_FAILED
  word (0x0F010213), then the FAIL verdict 0xDEADBEEF, no later read frame, and for 20,000 clk
  after the verdict the retired PCs span at most 64 bytes and cold_scratch[1], cold_scratch[0]
  and the console do not change.

Partial coverage. Not graded: a fault that clears after fewer than 4 attempts (the read then
succeeds); the PIO build, which has no retry; the rotate_update order; the SRAM zeroing and
transport re-bring-up between slots (RETRY-040); `bl0_state.error_code` and the `wfi` instruction
itself; the number of MANIFEST_LOAD_START words (logged as OBS-MANIFEST-LOAD-STARTS); the final
cold_scratch[1] value, which the bench's invalid status ring overwrites with STATUS_REPORTING_INVALID,
so RETRY-050 (b) is graded from the ERROR word on the status stream.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from env.sep_chk_log import SepChkLog
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver
from ocah_spi_vip import OcahSpiFlash
from rom_fw.sep_rom_observe_base import ROM_BASE, RUN_PULSE_CYCLES, sep_rom_observe_base

_FLASH_IMAGE = (
    Path(__file__).resolve().parents[4] / "bootrom" / "prod" / "build" / "oca_non_secure_boot.bin"
)

_SPEC_RETRIES = 3
_SPEC_MAX_ATTEMPTS = 1 + _SPEC_RETRIES
_MIN_ATTEMPTS = 2

_BL0 = 1 << 16
_WARN = 0x08
_ERROR = 0x0F
_MANIFEST_LOAD_START = 0x0212
_MANIFEST_LOAD_FAILED = 0x0213
_SPI_OT_TRANSPORT_ERROR = 0x0223
_MANIFEST_VALIDATED = 0x0053
_PAYLOAD_VALIDATED = 0x0055
_VERDICT_FAIL = 0xDEADBEEF


def _status(kind: int, code: int) -> int:
    return (kind << 24) | _BL0 | code


_WARN_TRANSPORT = _status(_WARN, _SPI_OT_TRANSPORT_ERROR)
_TERMINAL = _status(_ERROR, _MANIFEST_LOAD_FAILED)
_SLOTS = {"primary": mm.PRIMARY_MANIFEST_OFFSET, "backup": mm.BACKUP_MANIFEST_OFFSET}
_USE_MARKERS = ("OCA_BODY=", "MANIFEST_OK", "PAYLOAD_OK")
_DMA_ERROR_MARKER = "dma error"
_HALT_CYCLES = 20_000
_HALT_PC_SPAN = 64
_PROGRESS_CYCLES = 250_000

_CS, _PIN = "spi_cs_n_o", "dma_host_rsp_err_inject_i"


class _HaltObserver(SepRomObserver):
    """Also keeps every retired PC once cold_scratch[0] holds the FAIL verdict."""

    def __init__(self, test) -> None:
        super().__init__(test, keep=lambda _insn: False, tracker=False, watch=(_CS, _PIN))
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


def _code_ts(status: list[tuple[int, int]], code: int) -> list[int]:
    """Times of every BL0 status word with this code, any type."""
    return [t for t, w in status if w & 0x00FF_FFFF == _BL0 | code]


def _level(changes: list[tuple[int, int]], t: int) -> int | None:
    """Value of a watched signal at time t, from its change record."""
    v = None
    for tc, vc in changes:
        if tc > t:
            break
        v = vc
    return v


@pyuvm.test()
class sep_rom_spi_retry_exhaust_test(sep_rom_observe_base):
    """SPI boot with every secure-DMA host response SLVERR from the first slot attempt on."""

    max_run_cycles = 6_000_000
    required_evidence = (
        "CHK-READ-RETRIED",
        "CHK-ATTEMPTS-BOUNDED",
        "CHK-NO-PARTIAL-USE",
        "CHK-FALLBACK-OR-TERMINAL",
    )

    async def stimulus(self, obs: _HaltObserver) -> None:
        dut = cocotb.top
        while not _code_ts(obs.status, _MANIFEST_LOAD_START):
            await ClockCycles(dut.clk_i, 16)
        self._set_pin(dut, _PIN, 1)
        self.logger.info("%s=1 at cycle %d", _PIN, obs.cycle)
        next_log = obs.cycle + _PROGRESS_CYCLES
        while obs.verdict_pass() is None:
            await ClockCycles(dut.clk_i, 16)
            if obs.cycle >= next_log:
                next_log += _PROGRESS_CYCLES
                self.logger.info(
                    "fault held: cycle=%d retired=%d status=0x%08x",
                    obs.cycle,
                    obs.retired,
                    obs.status[-1][1] if obs.status else 0,
                )
        self._set_pin(dut, _PIN, 0)
        self.logger.info("%s=0 at cycle %d", _PIN, obs.cycle)

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        dut = cocotb.top
        cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))
        self.write_efuse_image(self.build_efuse_image())
        image = _FLASH_IMAGE.read_bytes()
        self._image_len = len(image)
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_rom_boot_flash",
        )
        flash.preload(image)
        await flash.start()
        self.obs = obs = _HaltObserver(self).start()
        stim = cocotb.start_soon(self.stimulus(obs))
        reached = False
        try:
            await self.bring_up_cpu_boot(ROM_BASE >> 1, run_pulse_cycles=RUN_PULSE_CYCLES)
            reached = await obs.run_until(self.done, self.max_run_cycles)
            await ClockCycles(dut.clk_i, _HALT_CYCLES + 2 * STORE_LAG_MAX_CYCLES)
        finally:
            stim.cancel()
            self._set_pin(dut, _PIN, 0)
            t_end = int(get_sim_time("ps"))
            await obs.stop()
            await flash.stop()
            txns = flash.get_transactions()
            self.logger.info(
                "flash transport: %s", ev.summarize(txns, self._image_len, limit=len(txns))
            )
        self.chk.ctrl("RUN-REACHED", reached, cycles=obs.cycle, retired=obs.retired)
        self._grade(obs, txns, t_end)
        self.chk.finish()

    def _grade(self, obs: _HaltObserver, txns: list, t_end: int) -> None:
        chk = self.chk
        status = obs.status
        clk_ps = (
            (obs.first[-1].t_ps - obs.first[0].t_ps) // (obs.first[-1].cycle - obs.first[0].cycle)
            if len(obs.first) > 1
            else 0
        )

        cs = obs.watched[_CS]
        cs_low = [t for (t, v), (_, prev) in zip(cs[1:], cs) if v == 0 and prev == 1]
        chk.ctrl(
            "FRAME-MAP",
            bool(txns) and len(cs_low) == len(txns) and bool(cs) and cs[-1][1] == 1,
            cs_assertions=len(cs_low),
            flash_frames=len(txns),
            cs_last=cs[-1][1] if cs else -1,
        )
        frames = list(zip(cs_low, txns))
        reads = [(t, x) for t, x in frames if x["opcode"] in ev.READ_OPCODES]
        in_slot = {}
        at_addr = {}
        for name, addr in _SLOTS.items():
            lo, hi = mm.slot_span(self._image_len, name)
            in_slot[name] = [(t, x) for t, x in reads if lo <= x["addr"] < hi]
            at_addr[name] = [t for t, x in in_slot[name] if x["addr"] == addr]
        prim, back = at_addr["primary"], at_addr["backup"]
        starts = _code_ts(status, _MANIFEST_LOAD_START)
        first = {n: r[0][0] if r else None for n, r in in_slot.items()}
        t_back0 = first["backup"]
        last = {n: r[-1][0] if r else None for n, r in in_slot.items()}
        after = {"primary": first["backup"] or t_end, "backup": t_end}
        # Each slot's transport report is the first WARN after its last frame, before the next slot.
        slot_warn = {
            n: next(
                (t for t, w in status if w == _WARN_TRANSPORT and last[n] < t < after[n]),
                None,
            )
            if last[n] is not None
            else None
            for n in _SLOTS
        }
        pin = obs.watched[_PIN]
        t_on = next((t for t, v in pin if v == 1), None)
        slot_reads = in_slot["primary"] + in_slot["backup"]
        unfaulted = [_ps(t) for t, _ in slot_reads if _level(pin, t) != 1]
        dma_errors = [line for _, line in obs.console if _DMA_ERROR_MARKER in line]
        chk.ctrl(
            "FAULT-APPLIED",
            bool(starts)
            and t_on is not None
            and t_on > starts[0]
            and bool(slot_reads)
            and not unfaulted
            and all(slot_warn[n] is not None for n in _SLOTS if in_slot[n])
            and bool(dma_errors),
            first_manifest_load_start_ps=_ps(starts[0] if starts else None),
            pin_on_ps=_ps(t_on),
            slot_read_frames=len(slot_reads),
            frames_without_fault=unfaulted[:4],
            primary_warn_ps=_ps(slot_warn["primary"]),
            backup_warn_ps=_ps(slot_warn["backup"]),
            dma_error_lines=len(dma_errors),
            first_dma_error=dma_errors[0] if dma_errors else "none",
        )
        chk.ok(
            "READ-RETRIED",
            len(prim) >= _MIN_ATTEMPTS
            and (t_back0 is None or prim[-1] < t_back0)
            and len(back) >= _MIN_ATTEMPTS
            and None not in (slot_warn["primary"], slot_warn["backup"]),
            primary_frames=len(prim),
            backup_frames=len(back),
            min_attempts=_MIN_ATTEMPTS,
            last_primary_ps=_ps(last["primary"]),
            primary_warn_ps=_ps(slot_warn["primary"]),
            first_backup_ps=_ps(t_back0),
            last_backup_ps=_ps(last["backup"]),
            backup_warn_ps=_ps(slot_warn["backup"]),
        )
        chk.ok(
            "ATTEMPTS-BOUNDED",
            1 <= len(prim) <= _SPEC_MAX_ATTEMPTS and len(back) <= _SPEC_MAX_ATTEMPTS,
            primary_frames=len(prim),
            backup_frames=len(back),
            max_attempts=_SPEC_MAX_ATTEMPTS,
        )

        used = [
            f"0x{w:08x}"
            for t, w in status
            if w & 0xFFFF in (_MANIFEST_VALIDATED, _PAYLOAD_VALIDATED) and w & 0x00FF_0000 == _BL0
        ]
        use_lines = [line for _, line in obs.console if any(m in line for m in _USE_MARKERS)]
        past = []
        spans = {}
        for name, rds in in_slot.items():
            if not rds:
                continue
            lo, hi = ev.read_span(rds[0][1])
            spans[name] = f"0x{lo:06x}..0x{hi:06x}"
            past += [
                f"0x{a:06x}..0x{b:06x}"
                for a, b in (ev.read_span(x) for _, x in rds)
                if a < lo or b > hi
            ]
        chk.ok(
            "NO-PARTIAL-USE",
            bool(in_slot["primary"]) and not used and not use_lines and not past,
            validated_words=used[:4],
            use_lines=use_lines[:4],
            first_read_span=spans,
            reads_past_first_span=past[:4],
        )

        verdict = obs.verdict[-1] if obs.verdict else (None, None)
        t_v = verdict[0]
        t_prim_last, t_back_last = last["primary"], last["backup"]
        # The backup attempt's own MANIFEST_LOAD_START sits between the two slots' frames.
        t_back_start = next(
            (
                t
                for t in starts
                if t_prim_last is not None and t_back0 is not None and t_prim_last < t < t_back0
            ),
            None,
        )
        in_any = {t for t, _ in slot_reads}
        outside = [f"0x{x['addr']:06x}" for t, x in reads if t not in in_any]
        t_term = next(
            (
                t
                for t, w in status
                if w == _TERMINAL and t_back_last is not None and t > t_back_last
            ),
            None,
        )
        late_reads = [_ps(t) for t, _ in reads if t_term is not None and t > t_term]
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
        moved = [f"0x{w:08x}" for t, w in status if t_v is not None and t > t_v]
        v_moved = [f"0x{w:08x}" for t, w in obs.verdict if t_v is not None and t > t_v]
        printed = [line for t, line in obs.console if t_v is not None and t > t_v]
        chk.ok(
            "FALLBACK-OR-TERMINAL",
            None not in (t_back_start, t_term, t_v)
            and not outside
            and t_term <= t_v
            and verdict[1] == _VERDICT_FAIL
            and not late_reads
            and w_end is not None
            and span <= _HALT_PC_SPAN
            and not moved
            and not v_moved
            and not printed,
            backup_manifest_load_start_ps=_ps(t_back_start),
            reads_outside_slots=outside[:4],
            last_primary_read_ps=_ps(t_prim_last),
            first_backup_read_ps=_ps(t_back0),
            last_backup_read_ps=_ps(t_back_last),
            manifest_load_failed_ps=_ps(t_term),
            verdict="none" if verdict[1] is None else f"0x{verdict[1]:08x}",
            verdict_ps=_ps(t_v),
            reads_after_terminal=late_reads[:4],
            pc_span=span,
            status_changes=moved[:4],
            verdict_changes=v_moved[:4],
            console_after=printed[:4],
        )
        chk.obs("MANIFEST-LOAD-STARTS", count=len(starts), ps=[_ps(t) for t in starts])
        chk.obs(
            "STATUS-TAIL",
            words=[f"0x{w:08x}" for t, w in status if starts and t >= starts[0]][:48],
        )
