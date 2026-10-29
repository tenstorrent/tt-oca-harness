# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Intra-block dead-space decode: a wrap past a block's extent must be refused.

Run mode: no_cpu with +skip_fuse_sense and +sep_ext_trng_axil_responder.
RANDCFG: known wrap-offset anchors every seed, plus seed-selected dead offsets
inside each block window; the TRNG passthrough legs draw their addresses, data,
leg order, burst length and split-beat code pairs from the seed.

A write or read past a block's allocated size must answer the past-extent
response of its unit, and no live register in that block may change.
CHK-DEADSPACE-REFUSE grades the response exactly in every window except TRNG:
``hw/sys/sep/regs/sep.rdl`` sets ``<unit>->ocah_past_extent_resp`` to DECERR,
``0xBADCAB1E`` / DECERR for secure_dma, wdt_timer, aes, otbn, abr, csrng, edn,
entropy_source, sep_lifecycle_ctrl, km_mailbox_sep and the SPI controller, with
no path qualifier. A read must answer DECERR with the word ``0xBADCAB1E``, and
a write must answer DECERR. The values are read from the generated
``regs/gen/py/sep_memory_map.py`` (built from ``sep.rdl``) through
``env/sep_decode_resp.py``. For ABR (``adams_bridge.adoc``,
"abr-aperture-decode") and the SPI controller (``peripheral_subsystem.adoc``)
the prose also states DECERR, and the window build checks that the RDL agrees.
Every probe uses the CPU-LSU splice (``s_axi``).

OBS-DEADSPACE-CODE (logged only): the response code and read data of every
TRNG-window probe. ``sep.rdl`` gives that window no past-extent response; its
code is graded under CHK-TRNG-UNOWNED. A checker that only inspects the
response would pass the day the RTL starts answering DECERR while still writing
the register, so every probe reads back the window's live registers as well.
The past extent is the part of the aperture that no register backs (Decoded
Extent, generated memory map), so a probe that moves a live register has
aliased onto it.

Every probe in the set is asserted, the wrapping anchors included; the
contract is not carried by a probe that is logged or waived.

CHK-TRNG-UNOWNED covers the TRNG window, which SEP forwards whole to an
adopter endpoint. The reference integration connects no external TRNG, so no
offset owns a register and every access must be refused: never OKAY, never
the value of a neighbouring ESRC register, and no ESRC register moved.
``memory_map.adoc`` also states the code for that case: the window ends in a
DECERR slave, so a single-beat read or write answers DECERR. Each TRNG probe is
graded against that code, and each TRNG read against the read word
``0xBADCAB1E``. Only the generated memory map states that word (note 2 of the
External TRNG row, ``hw/sys/sep/regs/gen/adoc/memory_map.adoc:94``: "DECERR,
0xBADCAB1E / DECERR"); the leaf reads code and word from the same note in
``regs/gen/py/sep_memory_map.py`` and grades them as the golden.

Row cells (FCOV window). The probe walk and its checks above run with the FCOV
window closed. After they pass, the leaf issues one cell probe per block
window (a read of the first word past the extent, and a write there in the SPI
controller and TRNG windows) twice: first with the window closed, then once
more inside the graded window of this test. Each instance is graded at once
under CHK-DEADSPACE-REFUSE (code and read word of the sep.rdl past-extent
response, no live register moved) or, in the TRNG window, CHK-TRNG-UNOWNED
(the code and word of the memory-map note); the window closes on the first
FAIL. The sampler holds the row cells of each probe in the window and samples
them only on the pass label ``row_pass`` (1), which the leaf writes after the
check of that probe passed; it drops them (2) before each probe and on a FAIL.
CTRL-TRNG-RSP-OFF: the bench TRNG responder is off for these probes.

CHK-DEADSPACE-BEAT and CHK-DEADSPACE-BURST grade bursts in the crypto region
only. ``memory_map.adoc`` ("Single-Beat Register Access") limits register
regions to single beats and lets the later beats of a burst to a register region
answer an error or alias onto other registers, so a burst into any other
register region is outside the specification and is not graded. The crypto
region is the exception: ``crypto.adoc`` ("Single-Beat Access Only") answers
every access whose AxLEN is non-zero with DECERR on every beat, and no beat
reaches an accelerator. For each block window in that region the test issues a
four-beat INCR read burst and, where the window takes writes, a four-beat INCR
write burst, across the extent where the window allows it and at the window base
otherwise.

CHK-DEADSPACE-BEAT: the bus monitor's per-beat RRESP vector of every read
burst is DECERR on every beat, inside the extent as well as past it.

CHK-DEADSPACE-BURST: no read-burst beat returns the value of a live register
in the window snapshot, the write burst answers DECERR, and no armed register
moves. A burst that times out fails. At least one window must answer a single
beat at a burst address OKAY, which shows the refusal is the burst rule and
not a dead address.

TRNG window passthrough. Every check above runs with the reference DECERR slave
on the TRNG AXI-Lite port. After them the bench TRNG responder answers that port
(the SEP input ``ext_trng_axil_resp_i``, docs/SEP_TB_ARCH.adoc): the leaf sets
the code of each port B and R handshake before an access and raises
``ext_trng_axil_rsp_en_i`` once with the port idle; the responder then stays on
to the end of the leaf. ``doc/integrator/src/smu-sep.adoc`` (TRNG path) states
the reply contract and ``hw/sys/sep/doc/crypto.adoc`` ("Single-Beat Access
Only") the burst contract. The PR-TRNG and PR-TRNG-RSP taps show the port.

CTRL-TRNG-RSP-DRIVE (bench control): the responder is on with both handshake
counts at 0, and each reply beat on the port carries the code (and, for R, the
data) that the leaf set for that handshake. Every reply check below compares
the initiator code with the code seen at the port.

CHK-TRNG-REPLY: a single-beat (AxSIZE 2) read and a single-beat write, each
answered OKAY, SLVERR and DECERR at the port, reach the port as exactly one
AXI-Lite access with exactly one reply beat, and the initiator receives the
port code. SEP does not decode offsets inside the window
(``doc/integrator/src/smu-sep.adoc:117-119``), so the address of that port
access carries the issued window offset in its low 12 bits (the 4 KiB
aperture). Besides the drawn offsets, every run issues a read and a write at
the first word (offset 0x000), the last word (0xFFC) and one drawn interior
word, each code once per direction.

OBS-TRNG-PORT-ADDR (logged only): the port address bits above the window
offset of each single-beat access. The specification states forwarding, not
those bits.

CHK-TRNG-SPLIT-WR: a 64-bit single-beat write reaches the port as two AXI-Lite
writes. With the first answered SLVERR and the last OKAY, the initiator
receives SLVERR.

CHK-TRNG-BURST: a read burst and a write burst (AxLEN above 0) with the port set
to answer OKAY answer DECERR on every R beat and on the B, and no handshake of
any channel occurs on the port.

OBS-TRNG-SPLIT-PREC (logged only): the code the initiator receives for a 64-bit
write whose last fragment errs and for a 64-bit read whose two halves answer
different codes. The specification does not state that code.

FCOV window. The passthrough checks above run with the window closed. After
they pass, the leaf issues the first-word, last-word and interior singles, the
split write and the two bursts once more inside the graded window of this test,
grades each access as it completes, and closes the window on the first FAIL.
The sampler holds the legal ``cp_trng_port_reply`` and ``cp_trng_forward``
sample of each repeated access and samples it only on the pass label
``row_pass`` (4), which the leaf writes after CTRL-TRNG-RSP-DRIVE and the
CHK-TRNG-REPLY, CHK-TRNG-SPLIT-WR or CHK-TRNG-BURST compare of that access
passed: those checks grade the W-beat count, the beats on the other channels,
X on the port reply and the code the responder drove, which the sampler does
not compare. The leaf drops held samples (2) before each access and on a FAIL;
a rise to 4 samples no row cell, so the TRNG accesses fill no ``cp_row_cell``
bin. An illegal reply value samples at once.
"""

from __future__ import annotations

import re

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_decode_resp import RESP_CODE, expected_unbacked, sep_map_row
from env.sep_fabric_tap import start_taps, stop_taps
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_row_pass
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_deadspace_seq import (
    CRYPTO_HI,
    CRYPTO_LO,
    DEADSPACE_ANCHORS,
    RESP_DECERR,
    RESP_OKAY,
    DeadProbe,
    SepDeadspace,
    SepDeadspaceCfg,
    in_crypto_region,
)

RESP_SLVERR = 2
_RESP_NAME = {
    -1: "TIMEOUT",
    RESP_OKAY: "OKAY",
    1: "EXOKAY",
    RESP_SLVERR: "SLVERR",
    RESP_DECERR: "DECERR",
}

_TRNG_BASE = sym("TRNG_REG_MAP_BASE_ADDR")
# Size of the TRNG aperture (4 KiB, doc/integrator/src/smu-sep.adoc:117); the
# port address carries the window offset in these low bits.
_TRNG_SIZE = sym("TRNG_REG_MAP_SIZE")
_TRNG_OFF_MASK = _TRNG_SIZE - 1
# Response with no TRNG fitted: note 2 of the External TRNG row of the
# generated memory map (hw/sys/sep/regs/gen/adoc/memory_map.adoc:94, "DECERR,
# 0xBADCAB1E / DECERR"), read from the same note in sep_memory_map.py.
_TRNG_NOTE_RE = re.compile(
    r"answers (OKAY|SLVERR|DECERR), 0x([0-9A-Fa-f]{8}) / (OKAY|SLVERR|DECERR)\."
)


def _trng_unowned_expect() -> tuple[dict[str, int], int]:
    hole = sep_map_row(_TRNG_BASE).hole
    m = _TRNG_NOTE_RE.search(hole.text if hole is not None else "")
    if m is None:
        raise RuntimeError(
            f"sep_memory_map.py: the TRNG row at 0x{_TRNG_BASE:08x} carries no no-TRNG "
            "response note"
        )
    return {"r": RESP_CODE[m[1]], "w": RESP_CODE[m[3]]}, int(m[2], 16)


# Code per channel and read word of an unowned TRNG-window offset with no
# external TRNG connected. hw/sys/sep/doc/memory_map.adoc:82-84 states the
# DECERR code in prose; the leaf checks that the note agrees.
TRNG_UNOWNED_RESP, TRNG_UNOWNED_RDATA = _trng_unowned_expect()
if TRNG_UNOWNED_RESP != {"r": RESP_DECERR, "w": RESP_DECERR}:
    raise RuntimeError(
        f"sep_memory_map.py TRNG note codes {TRNG_UNOWNED_RESP} disagree with the DECERR "
        "of hw/sys/sep/doc/memory_map.adoc:82-84"
    )
# Windows where the row-cell sampler also takes an LSU write cell (the SPI
# controller past extent and the TRNG window); elsewhere the cell is a read.
_CELL_WRITE_WINDOWS = ("spi_controller", "trng")

TEST = "sep_fabric_deadspace_decode_test"
# Pass label u_sep_fcov.row_pass: 1 releases the held row cells of a cell probe
# whose check passed, 4 the held TRNG reply sample of a repeated TRNG access
# whose check passed, 2 drops every held sample. Each value is held this many
# clk_i edges.
ROW_PASS_RELEASE = 1
ROW_PASS_DROP = 2
ROW_PASS_RELEASE_TRNG = 4
_LABEL_CLOCKS = 2

# Codes the bench TRNG responder answers in the passthrough legs.
_TRNG_CODES = (RESP_OKAY, RESP_SLVERR, RESP_DECERR)
# Fragment codes of a split 64-bit access that smu-sep.adoc does not resolve:
# a write whose last fragment errs, and a read whose halves differ.
_SPLIT_PREC_WR = (
    (RESP_OKAY, RESP_SLVERR),
    (RESP_OKAY, RESP_DECERR),
    (RESP_SLVERR, RESP_DECERR),
    (RESP_DECERR, RESP_SLVERR),
)
_SPLIT_PREC_RD = tuple((a, b) for a in _TRNG_CODES for b in _TRNG_CODES if a != b)
# Handshake k of a channel answers entry k modulo 8 of the responder vectors.
_TRNG_SLOTS = 8
# Clocks after an access completes before its port record is read, so a beat
# that leaks after the initiator response is still counted.
_TRNG_SETTLE_CYCLES = 32
# Clocks after the enable rises before the responder state is read.
_TRNG_EN_CYCLES = 4
# Separates the passthrough stream from the probe-set stream of the same seed.
_TRNG_RNG_SALT = 0x5452_4E47
# Separates the forwarded-offset stream from the two streams above.
_TRNG_FWD_SALT = 0x4657_4430


def _rname(code) -> str:
    if code is None:
        return "X"
    return _RESP_NAME.get(code, str(code))


@pyuvm.test()
class sep_fabric_deadspace_decode_test(sep_base_test):
    """Refuse unpopulated offsets inside a block window; do not alias live CSRs."""

    async def run_scenario(self) -> None:
        cfg = SepDeadspaceCfg(self.random_seed())
        self.logger.info("deadspace config: %s", cfg.summary())
        self._trng_drive_idle()
        assert not cfg.short_windows, (
            "CHK-DEADSPACE-RAND FAIL: window(s) short of the random-probe quota: "
            + ", ".join(
                f"{name}={got}/{want}" for name, (got, want) in sorted(cfg.short_windows.items())
            )
        )
        await self.bring_up_no_cpu()
        dead = SepDeadspace(self)

        snaps = {}
        for win in cfg.windows.values():
            snaps[win.name] = await dead.snapshot(win)
            # Every watched register must answer both snapshot reads OKAY. One
            # that refuses or times out is left out of the change compare, so a
            # store that aliases onto it would go unseen.
            assert not dead.snapshot_unread, (
                f"CHK-WINDOW-LIVE FAIL: {win.name} {len(dead.snapshot_unread)} of "
                f"{len(win.watch)} watched register(s) refused or timed out on the "
                f"snapshot read: {'; '.join(dead.snapshot_unread)}"
            )
            assert snaps[win.name], (
                f"{win.name}: watch snapshot is empty; the no-alias checker cannot fail"
            )
            # Readable is what the read-alias compare uses. Armed is what the
            # per-probe change compare can fail on for a stored write: a
            # compared register with a software read-write field. A sw=r or
            # write-only register is compared too, but a store cannot show
            # there, so it does not count toward armed.
            snap = snaps[win.name]
            hw_updating = sum(1 for addr in snap if addr in win.hw_updating)
            compared = len(snap) - hw_updating
            armed = win.armed(snap)
            assert armed > 0, (
                f"CHK-WINDOW-LIVE FAIL: {win.name} has no register armed for the change "
                f"compare ({len(snap)} readable, {hw_updating} hardware-updating, "
                f"{compared} compared, none with a software read-write field); the "
                "no-store-alias check cannot fail there"
            )
            self.logger.info(
                "CHK-WINDOW-LIVE PASS: %s %d %s register(s) watched, %d refused or "
                "timed out, %d self-changing, %d readable, %d compared per probe (%d "
                "hardware-updating skipped), %d armed with a software read-write field",
                win.name,
                len(win.watch),
                f"neighbouring {win.watch_from}" if win.watch_from else "allocated",
                len(dead.snapshot_unread),
                dead.snapshot_volatile,
                len(snap),
                compared,
                hw_updating,
                armed,
            )

        refused = 0
        aliased = 0
        accepted = 0
        # Probes that answered a code or read word other than the sep.rdl
        # Past Extent response (SepDeadspace.probe(), "answered code").
        wrong_code = 0
        fails: list[str] = []
        # (op, addr, resp, refused, rdata) of every probe of an adopter window.
        adopter_probes: list[tuple[str, int, int, bool, int | None]] = []
        for item in cfg.probes:
            win = cfg.windows[item.window]
            hit = await dead.probe(win, item, snaps[win.name])
            tag = "anchor" if item.anchor else "rand"
            if win.adopter:
                adopter_probes.append(
                    (item.op, item.addr, dead.last_resp, not hit, dead.last_rdata)
                )
                self.logger.info(
                    "INFO-TRNG-UNOWNED-RESP: %s %s 0x%08x resp=%s (%s)",
                    item.window,
                    item.op,
                    item.addr,
                    _RESP_NAME.get(dead.last_resp, str(dead.last_resp)),
                    tag,
                )
            if hit:
                fails.extend(hit)
                if any("changed live" in f for f in hit):
                    aliased += 1
                if any("resp=OKAY" in f for f in hit):
                    accepted += 1
                elif any("answered code" in f for f in hit):
                    wrong_code += 1
                for line in hit:
                    self.logger.error("CHK-DEADSPACE FAIL [%s]: %s", tag, line)
            else:
                refused += 1
                self.logger.info(
                    "CHK-DEADSPACE-REFUSE PASS: %s %s 0x%08x resp=%s rdata=%s expected=%s (%s)",
                    item.window,
                    item.op,
                    item.addr,
                    _RESP_NAME.get(dead.last_resp, str(dead.last_resp)),
                    "n/a" if dead.last_rdata is None else f"0x{dead.last_rdata:08x}",
                    dead.last_expected,
                    tag,
                )

        # Bursts are graded in the crypto region only; see the module docstring.
        burst_fails: list[str] = []
        beat_fails: list[str] = []
        burst_graded: list[str] = []
        controlled: list[str] = []
        not_graded: list[str] = []
        for win in cfg.windows.values():
            if not in_crypto_region(win.base):
                not_graded.append(win.name)
                continue
            burst_graded.append(win.name)
            # Across the extent where a legal burst can reach it, so the burst
            # also carries beats past the extent; otherwise at the window base.
            crosses = win.dead_lo % 0x1000 != 0 and win.dead_lo > win.base + 8
            start = None if crosses else win.base
            start, _resps, timed_out, words, singles, beat_resps = await dead.burst_across_extent(
                win, start
            )
            for i, (word, (sresp, sdata)) in enumerate(zip(words, singles)):
                self.logger.info(
                    "deadspace burst-audit: %s beat%d 0x%08x %-9s burst=0x%08x "
                    "beat_resp=%s single=0x%08x(resp=%d)",
                    win.name,
                    i,
                    start + 4 * i,
                    "in-extent" if start + 4 * i < win.dead_lo else "past",
                    word,
                    beat_resps[i] if i < len(beat_resps) else "n/a",
                    sdata,
                    sresp,
                )
            if timed_out:
                burst_fails.append(f"{win.name} read burst at 0x{start:08x} timed out")
                continue
            if not beat_resps:
                beat_fails.append(
                    f"{win.name}: no per-beat RRESP vector for the read burst at 0x{start:08x}"
                )
            for i, r in enumerate(beat_resps):
                if r != RESP_DECERR:
                    beat_fails.append(
                        f"{win.name} beat{i} 0x{start + 4 * i:08x} answered "
                        f"{_RESP_NAME.get(r, str(r))} inside a read burst; the crypto "
                        f"demux answers every beat of a burst DECERR"
                    )
            for i, word in enumerate(words):
                for live_addr, live_val in snaps[win.name].items():
                    if word == live_val:
                        burst_fails.append(
                            f"{win.name} beat{i} 0x{start + 4 * i:08x} of the read burst "
                            f"returned 0x{word:08x}, the value of live register 0x{live_addr:08x}"
                        )
                        break
            if any(sresp == RESP_OKAY for sresp, _ in singles):
                controlled.append(win.name)
            if win.write_ok:
                bresp, wr_timed_out, moved = await dead.burst_write(win, start, snaps[win.name])
                self.logger.info(
                    "deadspace burst-audit: %s write burst 0x%08x BRESP=%s",
                    win.name,
                    start,
                    _RESP_NAME.get(bresp, str(bresp)),
                )
                if wr_timed_out:
                    burst_fails.append(f"{win.name} write burst at 0x{start:08x} timed out")
                elif bresp != RESP_DECERR:
                    burst_fails.append(
                        f"{win.name} write burst at 0x{start:08x} answered "
                        f"{_RESP_NAME.get(bresp, str(bresp))}; the crypto demux answers DECERR"
                    )
                burst_fails.extend(moved)

        # Config report. An anchor whose window is absent from the map raises when
        # the config is built.
        self.logger.info(
            "deadspace config: %d probes including %d directed anchors, seed %d",
            len(cfg.probes),
            len(DEADSPACE_ANCHORS),
            cfg.seed,
        )
        # Adjudicate refuse/no-alias first and log their verdicts, then the
        # burst contract, so a burst failure cannot stop the other two
        # summaries from reaching the log.
        if fails:
            self.logger.error(
                "CHK-DEADSPACE-REFUSE FAIL: %d fail line(s) on %d probes "
                "(%d accepted OKAY, %d wrong code, %d aliased a live register)",
                len(fails),
                len(cfg.probes),
                accepted,
                wrong_code,
                aliased,
            )
            raise AssertionError(
                f"CHK-DEADSPACE-REFUSE FAIL: {accepted} probe(s) accepted OKAY, "
                f"{wrong_code} answered a code or read word other than the sep.rdl one and "
                f"{aliased} aliased a live register"
            )
        self.logger.info(
            "CHK-DEADSPACE-REFUSE PASS: all %d dead offsets answered the sep.rdl "
            "past-extent response (TRNG: refused, code graded below)",
            len(cfg.probes),
        )
        self.logger.info(
            "CHK-DEADSPACE-NO-ALIAS PASS: no allocated register moved across any probe"
        )

        # Refusal and no-alias of the TRNG probes are part of CHK-DEADSPACE-REFUSE
        # / -NO-ALIAS above, which already raised on any OKAY, timeout or alias.
        # This checker grades the code of each probe and the word of each read,
        # and requires a read and a write in the window.
        trng_rd = sorted({r for op, _a, r, ok, _d in adopter_probes if op == "r" and ok})
        trng_wr = sorted({r for op, _a, r, ok, _d in adopter_probes if op == "w" and ok})
        assert trng_rd and trng_wr, (
            f"CHK-TRNG-UNOWNED FAIL: need a refused read and a refused write in the "
            f"TRNG window, got {len(adopter_probes)} probe(s): {adopter_probes}"
        )
        trng_bad = [
            line
            for op, addr, r, _ok, rdata in adopter_probes
            if (line := self._trng_unowned_fail(op, addr, r, rdata))
        ]
        for line in trng_bad:
            self.logger.error("CHK-TRNG-UNOWNED FAIL: %s", line)
        assert not trng_bad, (
            f"CHK-TRNG-UNOWNED FAIL: {len(trng_bad)} of {len(adopter_probes)} TRNG-window "
            "probe(s) answered a code or read word other than the memory-map one"
        )
        self.logger.info(
            "CHK-TRNG-UNOWNED PASS: %d TRNG-window probes refused, none OKAY, no ESRC "
            "register aliased or moved; every read answered %s with rdata 0x%08x and every "
            "write %s, as the memory map states with no external TRNG connected",
            len(adopter_probes),
            "/".join(_RESP_NAME[r] for r in trng_rd),
            TRNG_UNOWNED_RDATA,
            "/".join(_RESP_NAME[r] for r in trng_wr),
        )

        # Row cells: one more graded instance of each cell the FCOV window counts.
        await self._cell_pass(cfg, dead, snaps)

        # Log both checkers' failures before either asserts, so a beat failure
        # cannot hide what the write burst did.
        for line in beat_fails:
            self.logger.error("CHK-DEADSPACE-BEAT FAIL: %s", line)
        for line in burst_fails:
            self.logger.error("CHK-DEADSPACE-BURST FAIL: %s", line)
        assert not beat_fails, (
            f"CHK-DEADSPACE-BEAT FAIL: {len(beat_fails)} read-burst beat(s) in the crypto "
            f"region did not answer DECERR"
        )
        assert burst_graded, (
            f"CHK-DEADSPACE-BEAT FAIL: no window lies in the crypto region "
            f"0x{CRYPTO_LO:08x}-0x{CRYPTO_HI - 1:08x}, so the burst rule has no evidence"
        )
        self.logger.info(
            "CHK-DEADSPACE-BEAT PASS: every beat of a read burst answered DECERR in %d "
            "crypto-region window(s) (%s)",
            len(burst_graded),
            ", ".join(burst_graded),
        )
        assert not burst_fails, (
            f"CHK-DEADSPACE-BURST FAIL: {len(burst_fails)} burst finding(s) in the crypto region"
        )
        assert controlled, (
            "CHK-DEADSPACE-BURST FAIL: no crypto-region window answered a single beat "
            "at a burst address OKAY, so a dead address would pass the burst checks"
        )
        self.logger.info(
            "CHK-DEADSPACE-BURST PASS: in %d crypto-region window(s) no read-burst beat "
            "returned a live value, every write burst answered DECERR and moved no armed "
            "register; a single beat at a burst address answered OKAY in %s. Not graded, "
            "outside the crypto region (memory_map.adoc, Single-Beat Register Access): %s",
            len(burst_graded),
            ", ".join(controlled),
            ", ".join(not_graded) or "none",
        )

        await self._trng_passthrough(cfg)

    @staticmethod
    def _trng_unowned_fail(op: str, addr: int, resp: int, rdata: int | None) -> str:
        """CHK-TRNG-UNOWNED compare of one probe; empty when it matches."""
        want = TRNG_UNOWNED_RESP[op]
        want_d = TRNG_UNOWNED_RDATA if op == "r" else None
        if resp == want and (want_d is None or rdata == want_d):
            return ""
        got_d = "" if op == "w" else (" rdata=X" if rdata is None else f" rdata=0x{rdata:08x}")
        exp_d = "" if want_d is None else f" rdata=0x{want_d:08x}"
        return (
            f"{op} 0x{addr:08x} answered {_rname(resp)}{got_d}, the memory map states "
            f"{_rname(want)}{exp_d} (regs/gen/adoc/memory_map.adoc:94)"
        )

    def _grade(self, ok: bool, chk: str, line: str, graded: bool) -> None:
        """Log one check line; on FAIL close the FCOV window and drop the held
        samples first, then raise."""
        if ok:
            self.logger.info("%s PASS: %s", chk, line)
            return
        if graded:
            close_graded_window(self.logger)
            set_row_pass(ROW_PASS_DROP, self.logger)
        self.logger.error("%s FAIL: %s", chk, line)
        raise AssertionError(f"{chk} FAIL: {line}")

    @staticmethod
    async def _label(value: int) -> None:
        """Write the pass label ``row_pass`` for two clk_i edges, then 0."""
        set_row_pass(value)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)
        set_row_pass(0)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)

    async def _cell_pass(self, cfg: SepDeadspaceCfg, dead: SepDeadspace, snaps: dict) -> None:
        """Cell probes: once with the FCOV window closed, then once inside it."""
        on = self.rd_known(cocotb.top.ext_trng_axil_rsp_on_o)
        self._grade(
            on == 0,
            "CTRL-TRNG-RSP-OFF",
            f"responder on={on} before the cell probes, expected 0 (no TRNG fitted)",
            False,
        )
        items = []
        for win in cfg.windows.values():
            items.append(DeadProbe(win.name, win.dead_lo, "r", True))
            if win.write_ok and win.name in _CELL_WRITE_WINDOWS:
                items.append(DeadProbe(win.name, win.dead_lo, "w", True))
        for graded in (False, True):
            if graded:
                open_graded_window(TEST, self.logger)
            for item in items:
                win = cfg.windows[item.window]
                if graded:
                    await self._label(ROW_PASS_DROP)
                hit = await dead.probe(win, item, snaps[win.name])
                resp, rdata = dead.last_resp, dead.last_rdata
                tag = (
                    f"{item.window} {item.op} 0x{item.addr:08x} resp={_rname(resp)} rdata="
                    + ("n/a" if rdata is None else f"0x{rdata:08x}")
                    + f" ({'graded window' if graded else 'cell'})"
                )
                if win.adopter:
                    bad = self._trng_unowned_fail(item.op, item.addr, resp, rdata)
                    self._grade(
                        not hit and not bad,
                        "CHK-TRNG-UNOWNED",
                        f"{tag} expected {_rname(TRNG_UNOWNED_RESP[item.op])}"
                        + ("" if item.op == "w" else f" rdata=0x{TRNG_UNOWNED_RDATA:08x}")
                        + (f"; {bad}" if bad else "")
                        + ("; " + "; ".join(hit) if hit else ""),
                        graded,
                    )
                    if graded:
                        await self._label(ROW_PASS_RELEASE)
                    continue
                exp = expected_unbacked(item.addr, item.op)
                want_rdata = exp.rdata
                match = resp == exp.resp and (want_rdata is None or rdata == want_rdata)
                self._grade(
                    not hit and match,
                    "CHK-DEADSPACE-REFUSE",
                    f"{tag} expected {_rname(exp.resp)}"
                    + ("" if want_rdata is None else f" rdata=0x{want_rdata:08x}")
                    + f" ({exp.row} Past Extent), no live register moved"
                    + ("; " + "; ".join(hit) if hit else ""),
                    graded,
                )
                if graded:
                    await self._label(ROW_PASS_RELEASE)
            if graded:
                close_graded_window(self.logger)
        self.logger.info(
            "CHK-DEADSPACE-REFUSE PASS: %d cell probe(s) in %d window(s) answered the "
            "past-extent or memory-map response twice, the second time in the graded window",
            len(items),
            len(cfg.windows),
        )

    # ------------------------------------------------------------------
    # TRNG window passthrough (bench TRNG responder on the AXI-Lite port).
    # ------------------------------------------------------------------
    def _trng_drive_idle(self) -> None:
        """Drive every responder input to 0 (responder off, OKAY, data 0)."""
        top = cocotb.top
        top.ext_trng_axil_rsp_en_i.value = 0
        top.ext_trng_axil_rsp_bresp_i.value = 0
        top.ext_trng_axil_rsp_rresp_i.value = 0
        top.ext_trng_axil_rsp_rdata_i.value = 0
        self._trng_b = [RESP_OKAY] * _TRNG_SLOTS
        self._trng_r = [RESP_OKAY] * _TRNG_SLOTS
        self._trng_d = [0] * _TRNG_SLOTS

    def _trng_load(
        self, op: SepAxiOp, codes: tuple[int, ...], words: tuple[int, ...] = ()
    ) -> tuple[int, list[int], list[int]]:
        """Set the codes of the next port handshakes of ``op``.

        Returns the first slot and the code and data sequence that the next
        eight handshakes of that channel answer.
        """
        top = cocotb.top
        if len(codes) > _TRNG_SLOTS:
            raise ValueError(f"{len(codes)} codes exceed the {_TRNG_SLOTS} responder slots")
        if op is SepAxiOp.WRITE:
            first = self.rd_known(top.ext_trng_axil_rsp_bcnt_o) % _TRNG_SLOTS
            for k, c in enumerate(codes):
                self._trng_b[(first + k) % _TRNG_SLOTS] = c
            top.ext_trng_axil_rsp_bresp_i.value = sum(
                c << (2 * k) for k, c in enumerate(self._trng_b)
            )
            seq_c = [self._trng_b[(first + k) % _TRNG_SLOTS] for k in range(_TRNG_SLOTS)]
            return first, seq_c, [0] * _TRNG_SLOTS
        first = self.rd_known(top.ext_trng_axil_rsp_rcnt_o) % _TRNG_SLOTS
        for k, c in enumerate(codes):
            slot = (first + k) % _TRNG_SLOTS
            self._trng_r[slot] = c
            self._trng_d[slot] = words[k] if k < len(words) else 0
        top.ext_trng_axil_rsp_rresp_i.value = sum(c << (2 * k) for k, c in enumerate(self._trng_r))
        top.ext_trng_axil_rsp_rdata_i.value = sum(w << (32 * k) for k, w in enumerate(self._trng_d))
        seq_c = [self._trng_r[(first + k) % _TRNG_SLOTS] for k in range(_TRNG_SLOTS)]
        seq_d = [self._trng_d[(first + k) % _TRNG_SLOTS] for k in range(_TRNG_SLOTS)]
        return first, seq_c, seq_d

    async def _trng_access(
        self,
        leg: str,
        op: SepAxiOp,
        addr: int,
        *,
        size: int,
        codes: tuple[int, ...],
        words: tuple[int, ...] = (),
        wdata: int = 0,
        beats: int = 1,
    ) -> dict:
        """One access to the TRNG window; returns the initiator and port record."""
        first, drive_c, drive_d = self._trng_load(op, codes, words)
        mon = self.env.axi_monitor
        marks = {n: t.mark() for n, t in self.trng_taps.items()}
        is_rd = op is SepAxiOp.READ
        # Every initiator response beat may be DECERR; credit each one and
        # hand back what the fabric did not use. The checks below grade the code.
        n_resp = beats if is_rd else 1
        mon.arm_expected_decerr(n_resp)
        if is_rd and beats > 1:
            mon.start_beat_capture()
        kw = {"allow_ungraded_read_resp": True} if is_rd else {"allow_unverified_write_resp": True}
        seq = SepAxiAccessSeq(
            f"trng_{leg}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=(1 << size) * beats,
            size=size,
            **kw,
        )
        await self.start_seq(seq)
        beat_resps: list[int | None] | None = None
        if is_rd and beats > 1:
            captured = mon.take_beat_capture()
            usable = len(captured) == beats and all(r is not None for r in captured)
            beat_resps = list(captured) if usable else []
            used = (
                sum(1 for r in captured if r == RESP_DECERR)
                if usable
                else sum(1 for r in seq.resp_list if r == RESP_DECERR)
            )
        else:
            used = 1 if (not seq.timed_out and seq.resp_code == RESP_DECERR) else 0
        if n_resp > used:
            mon.release_expected_decerr(n_resp - used)
        await ClockCycles(cocotb.top.clk_i, _TRNG_SETTLE_CYCLES)
        req = self.trng_taps["PR-TRNG"].since(marks["PR-TRNG"])
        rsp = self.trng_taps["PR-TRNG-RSP"].since(marks["PR-TRNG-RSP"])
        return {
            "leg": leg,
            "op": op,
            "d": "r" if is_rd else "w",
            "addr": addr,
            "size": size,
            "beats": beats,
            "codes": codes,
            "first": first,
            "drive_c": drive_c,
            "drive_d": drive_d,
            "resp": -1 if seq.timed_out else seq.resp_code,
            "resp_list": list(seq.resp_list),
            "rdata": seq.rdata,
            "timed_out": seq.timed_out,
            "beat_resps": beat_resps,
            "req": req,
            "rsp": rsp,
            "addr_beats": [b for b in req if b.ch == ("ar" if is_rd else "aw")],
            "w_beats": [b for b in req if b.ch == "w"],
            "rep": [b for b in rsp if b.ch == ("r" if is_rd else "b")],
        }

    @staticmethod
    def _trng_tag(c: dict) -> str:
        return (
            f"leg={c['leg']} op={c['d']} addr=0x{c['addr']:08x} size={c['size']} beats={c['beats']}"
        )

    @staticmethod
    def _trng_rdata(beat) -> str:
        data = beat.fields.get("data")
        return "X" if data is None else f"0x{data:08x}"

    @staticmethod
    def _trng_port_fmt(c: dict) -> str:
        return "; ".join(b.fmt() for b in c["req"] + c["rsp"]) or "none"

    def _trng_ctl(self, c: dict, fails: list[str]) -> None:
        """CTRL-TRNG-RSP-DRIVE: each port reply beat carries the code set for it."""
        for k, b in enumerate(c["rep"]):
            slot = (c["first"] + k) % _TRNG_SLOTS
            want_c = c["drive_c"][k % _TRNG_SLOTS]
            want_d = c["drive_d"][k % _TRNG_SLOTS] if c["d"] == "r" else None
            got_d = b.fields.get("data") if c["d"] == "r" else None
            self.logger.info(
                "CTRL-TRNG-RSP-DRIVE LOG: %s ch=%s k=%d slot=%d set=%s port=%s set_data=%s "
                "port_data=%s",
                self._trng_tag(c),
                b.ch,
                k,
                slot,
                _rname(want_c),
                _rname(b.resp),
                "na" if want_d is None else f"0x{want_d:08x}",
                "na" if want_d is None else ("X" if got_d is None else f"0x{got_d:08x}"),
            )
            if b.resp != want_c or (want_d is not None and got_d != want_d):
                fails.append(
                    f"{self._trng_tag(c)} port reply k={k} {b.fmt()}; the responder was set "
                    f"to resp={_rname(want_c)}"
                    + ("" if want_d is None else f" data=0x{want_d:08x}")
                )

    def _trng_raise(self, chk: str, fails: list[str], what: str) -> None:
        for line in fails:
            self.logger.error("%s FAIL: %s", chk, line)
        if fails:
            raise AssertionError(f"{chk} FAIL: {len(fails)} {what}")

    def _chk_reply(self, c: dict, port_codes: dict[str, set[int]]) -> list[str]:
        """CHK-TRNG-REPLY of one single-beat access; logs its PASS line."""
        tag = self._trng_tag(c)
        n_addr, n_w, n_rep = len(c["addr_beats"]), len(c["w_beats"]), len(c["rep"])
        want_w = 0 if c["d"] == "r" else 1
        own = ("ar", "r") if c["d"] == "r" else ("aw", "w", "b")
        other = [b for b in c["req"] + c["rsp"] if b.ch not in own]
        if c["timed_out"]:
            return [f"{tag} timed out; port: {self._trng_port_fmt(c)}"]
        if n_addr != 1 or n_w != want_w or n_rep != 1 or other:
            return [
                f"{tag} port addr_beats={n_addr} w_beats={n_w} reply_beats={n_rep} "
                f"other_beats={len(other)}, expected 1/{want_w}/1/0: {self._trng_port_fmt(c)}"
            ]
        rep = c["rep"][0]
        if rep.resp is None:
            return [f"{tag} port reply carries X/Z: {rep.fmt()}"]
        port_addr = c["addr_beats"][0].addr
        self.logger.info(
            "OBS-TRNG-PORT-ADDR: %s port address bits above the window offset=%s",
            tag,
            "X" if port_addr is None else f"0x{port_addr & ~_TRNG_OFF_MASK:08x}",
        )
        want_off = c["addr"] & _TRNG_OFF_MASK
        port_off = None if port_addr is None else port_addr & _TRNG_OFF_MASK
        if port_off != want_off:
            return [
                f"{tag} port offset="
                + ("X" if port_off is None else f"0x{port_off:03x}")
                + f" issued offset=0x{want_off:03x}; smu-sep.adoc: SEP forwards every access "
                "and does not decode offsets inside the window"
            ]
        port_codes[c["d"]].add(rep.resp)
        if c["resp"] != rep.resp:
            return [
                f"{tag} driven={_rname(c['codes'][0])} port={_rname(rep.resp)} "
                f"init={_rname(c['resp'])}; smu-sep.adoc: the initiator receives the "
                "endpoint code verbatim"
            ]
        self.logger.info(
            "CHK-TRNG-REPLY PASS: %s driven=%s port=%s init=%s port_off=0x%03x issued_off=0x%03x "
            "port_addr_beats=%d port_beats=%d port_rdata=%s init_rdata=0x%016x",
            tag,
            _rname(c["codes"][0]),
            _rname(rep.resp),
            _rname(c["resp"]),
            port_off,
            want_off,
            n_addr,
            n_rep,
            self._trng_rdata(rep) if c["d"] == "r" else "na",
            c["rdata"],
        )
        return []

    @staticmethod
    def _reply_cover(port_codes: dict[str, set[int]]) -> list[str]:
        """Each direction answered OKAY, SLVERR and DECERR at the port."""
        return [
            f"op={d} port codes {sorted(_rname(x) for x in port_codes[d])} do not cover "
            "OKAY, SLVERR and DECERR"
            for d in ("r", "w")
            if port_codes[d] != set(_TRNG_CODES)
        ]

    def _chk_split(self, c: dict) -> list[str]:
        """CHK-TRNG-SPLIT-WR: two port writes, SLVERR then OKAY -> SLVERR."""
        tag = self._trng_tag(c)
        split_port = [b.resp for b in c["rep"]]
        if c["timed_out"]:
            return [f"{tag} timed out; port: {self._trng_port_fmt(c)}"]
        if (
            len(c["addr_beats"]) != 2
            or len(c["w_beats"]) != 2
            or split_port
            != [
                RESP_SLVERR,
                RESP_OKAY,
            ]
        ):
            return [
                f"{tag} port aw={len(c['addr_beats'])} w={len(c['w_beats'])} "
                f"b={[_rname(x) for x in split_port]}, expected two writes answered "
                f"SLVERR then OKAY: {self._trng_port_fmt(c)}"
            ]
        want_init = RESP_SLVERR
        if c["resp"] != want_init:
            return [
                f"{tag} port=[SLVERR,OKAY] init={_rname(c['resp'])} expected "
                f"{_rname(want_init)}; smu-sep.adoc: an "
                "earlier fragment erred and the last is OKAY, so the initiator receives SLVERR"
            ]
        self.logger.info(
            "CHK-TRNG-SPLIT-WR PASS: %s port_aw=%s port=[%s] init=%s",
            tag,
            ",".join("X" if b.addr is None else f"0x{b.addr:08x}" for b in c["addr_beats"]),
            ",".join(_rname(x) for x in split_port),
            _rname(c["resp"]),
        )
        return []

    def _chk_burst(self, c: dict) -> list[str]:
        """CHK-TRNG-BURST: DECERR on every beat, no handshake on the port."""
        tag = self._trng_tag(c)
        if c["timed_out"]:
            return [f"{tag} timed out; port: {self._trng_port_fmt(c)}"]
        fails: list[str] = []
        if c["req"] or c["rsp"]:
            fails.append(
                f"{tag} {len(c['req'])} request and {len(c['rsp'])} reply handshake(s) "
                f"reached the port, expected 0: {self._trng_port_fmt(c)}"
            )
        if c["d"] == "r":
            br = c["beat_resps"] or []
            if len(br) != c["beats"] or any(r != RESP_DECERR for r in br):
                fails.append(
                    f"{tag} per-beat RRESP {[_rname(r) for r in br]} (monitor), expected "
                    f"DECERR on all {c['beats']} beats"
                )
        elif c["resp"] != RESP_DECERR:
            fails.append(f"{tag} BRESP={_rname(c['resp'])}, expected DECERR")
        if not fails:
            self.logger.info(
                "CHK-TRNG-BURST PASS: %s answered %s with the port set to OKAY; port handshakes=%d",
                tag,
                "[" + ",".join(_rname(r) for r in c["beat_resps"] or []) + "]"
                if c["d"] == "r"
                else _rname(c["resp"]),
                len(c["req"]) + len(c["rsp"]),
            )
        return fails

    @staticmethod
    def _trng_edge_plan(rng: SepSeededRng, base: int) -> list[dict]:
        """First word, last word and one interior word, read and write.

        Each code answers once per direction, in a seeded order.
        """
        plan: list[dict] = []
        for op in (SepAxiOp.READ, SepAxiOp.WRITE):
            codes = list(_TRNG_CODES)
            rng.shuffle(codes)
            offs = (
                ("first", 0),
                ("last", _TRNG_SIZE - 4),
                ("interior", 4 * rng.randrange(1, _TRNG_SIZE // 4 - 1)),
            )
            for (pos, off), code in zip(offs, codes):
                plan.append(
                    {
                        "leg": f"fwd_{pos}_{_rname(code).lower()}",
                        "op": op,
                        "addr": base + off,
                        "size": 2,
                        "codes": (code,),
                        "words": (rng.getrandbits(32),),
                        "wdata": rng.getrandbits(32),
                    }
                )
        return plan

    async def _trng_passthrough(self, cfg: SepDeadspaceCfg) -> None:
        """Turn the bench TRNG responder on and grade the passthrough contract."""
        top = cocotb.top
        win = cfg.windows["trng"]
        span = win.window_end - win.base
        assert span == _TRNG_SIZE and win.base == _TRNG_BASE, (
            f"TRNG window 0x{win.base:08x} spans 0x{span:x} bytes, expected the "
            f"0x{_TRNG_SIZE:x}-byte aperture at 0x{_TRNG_BASE:08x}"
        )
        rng = SepSeededRng(cfg.seed ^ _TRNG_RNG_SALT)
        self.trng_taps = start_taps("PR-TRNG", "PR-TRNG-RSP")

        # Port idle: every access above has completed. Raise the enable once.
        top.ext_trng_axil_rsp_en_i.value = 1
        await ClockCycles(top.clk_i, _TRNG_EN_CYCLES)
        on = self.rd_known(top.ext_trng_axil_rsp_on_o)
        bcnt = self.rd_known(top.ext_trng_axil_rsp_bcnt_o)
        rcnt = self.rd_known(top.ext_trng_axil_rsp_rcnt_o)
        self.logger.info("CTRL-TRNG-RSP-DRIVE LOG: responder on=%d bcnt=%d rcnt=%d", on, bcnt, rcnt)
        assert on == 1 and bcnt == 0 and rcnt == 0, (
            f"CTRL-TRNG-RSP-DRIVE FAIL: responder on={on} bcnt={bcnt} rcnt={rcnt}; expected on=1 "
            "with both counts at 0 (the leaf runs with +sep_ext_trng_axil_responder)"
        )

        def word_addr() -> int:
            return win.base + 4 * rng.randrange(0, span // 4)

        def dword_addr() -> int:
            return win.base + 8 * rng.randrange(0, span // 8)

        # Single beats: every code on a read and on a write, in a seeded order.
        single = [(op, code) for op in (SepAxiOp.READ, SepAxiOp.WRITE) for code in _TRNG_CODES]
        rng.shuffle(single)
        singles = []
        for op, code in single:
            addr = word_addr()
            word = rng.getrandbits(32)
            singles.append(
                await self._trng_access(
                    f"single_{_rname(code).lower()}",
                    op,
                    addr,
                    size=2,
                    codes=(code,),
                    words=(word,),
                    wdata=rng.getrandbits(32),
                )
            )
        # Split write: the first fragment SLVERR, the last OKAY.
        split_spec = {
            "leg": "split_wr",
            "op": SepAxiOp.WRITE,
            "addr": dword_addr(),
            "size": 3,
            "codes": (RESP_SLVERR, RESP_OKAY),
            "wdata": rng.getrandbits(64),
        }
        split = await self._trng_access(**split_spec)
        # Bursts with the port set to answer OKAY, so a beat that reaches the
        # port answers OKAY and shows.
        n_beats = rng.choice((2, 4, 8))
        b_start = win.base + 4 * rng.randrange(0, (span - 4 * n_beats) // 4 + 1)
        burst_rd_spec = {
            "leg": "burst_rd",
            "op": SepAxiOp.READ,
            "addr": b_start,
            "size": 2,
            "codes": (RESP_OKAY,) * n_beats,
            "words": tuple(rng.getrandbits(32) for _ in range(n_beats)),
            "beats": n_beats,
        }
        burst_rd = await self._trng_access(**burst_rd_spec)
        burst_wr_spec = {
            "leg": "burst_wr",
            "op": SepAxiOp.WRITE,
            "addr": b_start,
            "size": 2,
            "codes": (RESP_OKAY,),
            "wdata": (1 << (32 * n_beats)) - 1,
            "beats": n_beats,
        }
        burst_wr = await self._trng_access(**burst_wr_spec)
        # Forwarded offsets: first word, last word and one interior word, from
        # their own stream so the draws above keep their values.
        edge_plan = self._trng_edge_plan(SepSeededRng(cfg.seed ^ _TRNG_FWD_SALT), win.base)
        edges = [await self._trng_access(**spec) for spec in edge_plan]

        graded = singles + edges + [split, burst_rd, burst_wr]
        ctl_fails: list[str] = []
        for c in graded:
            self._trng_ctl(c, ctl_fails)
        self._trng_raise("CTRL-TRNG-RSP-DRIVE", ctl_fails, "port reply beat(s) off the set code")
        self.logger.info(
            "CTRL-TRNG-RSP-DRIVE PASS: %d port reply beat(s) over %d access(es) carried the set "
            "code",
            sum(len(c["rep"]) for c in graded),
            len(graded),
        )

        # CHK-TRNG-REPLY: one port access at the issued offset, one reply beat,
        # initiator code = port code.
        reply_fails: list[str] = []
        port_codes: dict[str, set[int]] = {"r": set(), "w": set()}
        for c in singles + edges:
            reply_fails.extend(self._chk_reply(c, port_codes))
        reply_fails.extend(self._reply_cover(port_codes))
        self._trng_raise("CHK-TRNG-REPLY", reply_fails, "single-beat TRNG finding(s)")
        self.logger.info(
            "CHK-TRNG-REPLY PASS: %d single-beat accesses, %d of them at the first word, last "
            "word and an interior word; read and write each answered OKAY, SLVERR and DECERR "
            "at the port with one port access at the issued offset each, and the initiator "
            "received the port code every time",
            len(singles) + len(edges),
            len(edges),
        )

        self._trng_raise("CHK-TRNG-SPLIT-WR", self._chk_split(split), "split-write finding(s)")
        burst_fails = self._chk_burst(burst_rd) + self._chk_burst(burst_wr)
        self._trng_raise("CHK-TRNG-BURST", burst_fails, "TRNG burst finding(s)")

        # One more graded instance of each sampled shape inside the FCOV window.
        await self._trng_window_pass(edge_plan + [split_spec, burst_rd_spec, burst_wr_spec])

        # OBS-TRNG-SPLIT-PREC: halves that differ in a way the spec does not resolve.
        wr_pair = rng.choice(_SPLIT_PREC_WR)
        rd_pair = rng.choice(_SPLIT_PREC_RD)
        obs = [
            await self._trng_access(
                "prec_wr",
                SepAxiOp.WRITE,
                dword_addr(),
                size=3,
                codes=wr_pair,
                wdata=rng.getrandbits(64),
            ),
            await self._trng_access(
                "prec_rd",
                SepAxiOp.READ,
                dword_addr(),
                size=3,
                codes=rd_pair,
                words=(rng.getrandbits(32), rng.getrandbits(32)),
            ),
        ]
        for c in obs:
            self.logger.info(
                "OBS-TRNG-SPLIT-PREC: %s driven=[%s] port=[%s] port_beats=%d init=%s",
                self._trng_tag(c),
                ",".join(_rname(x) for x in c["codes"]),
                ",".join(_rname(b.resp) for b in c["rep"]),
                len(c["rep"]),
                "TIMEOUT" if c["timed_out"] else _rname(c["resp"]),
            )
        obs_ctl: list[str] = []
        for c in obs:
            self._trng_ctl(c, obs_ctl)
        self._trng_raise("CTRL-TRNG-RSP-DRIVE", obs_ctl, "port reply beat(s) off the set code")
        await stop_taps(self.trng_taps)

    async def _trng_window_pass(self, specs: list[dict]) -> None:
        """Repeat ``specs`` inside the FCOV window; grade each access as it completes.

        Every spec already passed its check with the window closed. The window
        closes on the first FAIL, so no later access samples.
        """
        port_codes: dict[str, set[int]] = {"r": set(), "w": set()}
        open_graded_window(TEST, self.logger)
        for spec in specs:
            await self._label(ROW_PASS_DROP)
            c = await self._trng_access(**{**spec, "leg": "win_" + spec["leg"]})
            fails: list[str] = []
            self._trng_ctl(c, fails)
            chk = "CTRL-TRNG-RSP-DRIVE"
            if not fails:
                if c["beats"] > 1:
                    chk, fails = "CHK-TRNG-BURST", self._chk_burst(c)
                elif c["size"] == 3:
                    chk, fails = "CHK-TRNG-SPLIT-WR", self._chk_split(c)
                else:
                    chk, fails = "CHK-TRNG-REPLY", self._chk_reply(c, port_codes)
            if fails:
                close_graded_window(self.logger)
                set_row_pass(ROW_PASS_DROP, self.logger)
                self._trng_raise(chk, fails, "finding(s) in the graded window")
            await self._label(ROW_PASS_RELEASE_TRNG)
        cover = self._reply_cover(port_codes)
        if cover:
            close_graded_window(self.logger)
            self._trng_raise("CHK-TRNG-REPLY", cover, "finding(s) in the graded window")
        close_graded_window(self.logger)
        self.logger.info(
            "CHK-TRNG-REPLY PASS: %d access(es) repeated in the graded window, each graded "
            "as it completed",
            len(specs),
        )
