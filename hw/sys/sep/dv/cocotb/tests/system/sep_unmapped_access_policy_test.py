# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Holes, reserved rows and extent ends next to live registers answer the generated map's policy.

Run mode: no_cpu with +skip_fuse_sense. RAND-NONE: every address comes from the generated
register export and is walked on every run.

The SEP components view of the SystemRDL memory map
(``hw/sys/sep/regs/gen/py/sep_memory_map.py``, generated from ``sep.rdl``)
states the contract. Per unit it gives the Decoded Extent and, for a 32-bit
access that no register backs, the read response, the read data and the write
response: inside the extent, past it, and in a reserved row between apertures.
``env/sep_decode_resp.py`` imports the view; the config refuses to build if a
probe the refusal checkers grade is not a refusal there.

CHK-UNMAPPED-LIVE is the positive control. Every programmed live word next to a
probed hole is written with a distinct value and must read it back OKAY, so the
bus reaches each block and a write or read alias is visible. A live word whose
RDL field has no reset (the generated IP-XACT gives it no reset element) has no
value before its first write, so it is written before any read of it.

CHK-SYSCSR-HOLE-REFUSE, CHK-SYS-RESERVED-REFUSE, CHK-MBOX-UPPER-REFUSE,
CHK-EFUSE-CTRL-PAST-REFUSE, CHK-EFUSE-MMR-PAST-REFUSE and CHK-SPI-PAST-REFUSE:
every read and write in that set is refused (never OKAY, never a timeout).

CHK-SYSCSR-HOLE-DECODE: no system-CSR hole or reserved-row probe reaches the
system-CSR AXI-Lite port. The system-peripherals crossbar refuses them itself,
so a write answers DECERR rather than the SLVERR the AXI-Lite converter makes of
any write error behind it. A watched write and read of SEP_NMI_VEC must each
show their handshake at that port, so a watcher that sees nothing fails.

CHK-SYS-RESERVED-NO-LOOPBACK: no system-CSR hole or reserved-row probe arrives
at the local crossbar's ext initiator. The peripheral crossbar forwards an
address outside the mailbox and system CSR windows back to that initiator
(``hw/sys/sep/doc/fabric.adoc``), so a reserved address the local crossbar sends
to sep_system_peripherals returns there instead of being refused at its first
decode. A watched write and read of the first External address, which takes
that route, must each show their handshake at the ext initiator, so a watcher
that sees nothing fails.

CHK-TOKEN-FAULT-EXTENT: TOKEN_MATCH_FAULT, the last register the RDL gives the
eFuse token MMR, reads OKAY with its RDL reset, and the first word after it is
refused. The extent therefore ends where the RDL ends it.

CHK-ARRAY-TAIL: the tail of each remap / filter array slot (stride wider than
the slot's registers) follows the extent rule. The array extent is base +
SEP_TOP_<ARRAY>_TOTAL_SIZE, the size the RDL allocates. Every tail inside it,
the last slot's tail included, reads zero and accepts a write with OKAY. The
first word past it is refused where no other RDL block owns that word. A
re-read of an in-extent tail after its write answers OKAY with zero, so the
write was discarded. A tail write never moves a word of its own slot or of the
next slot.

CHK-UNMAPPED-CODE: every probe and tail access answers the response code the
map states for that address and channel, and every read returns the stated
read data: a 32-bit RDL rdata on either bus half, and the upper word of a
64-bit rdata for address bit 2. The tail words where the map and the RDL
allocation disagree are graded by CHK-ARRAY-TAIL only and logged as
UNMAPPED-MAP-DISAGREE. Past the efuse_interface_ctrl and spi_controller
extents, reads cover both 32-bit lanes of the bus. The monitor lane-checks the
read data of every error response for X/Z, so an unknown payload fails instead
of reading as zero; every such read must have been lane-checked. The golden is
the generated map, hw/sys/sep/regs/gen/adoc/memory_map.adoc, whose codes were
assigned from the RTL; hw/sys/sep/doc/fabric.adoc:143-146 states the DECERR
class between the register blocks of the system CSR windows. The eFuse token
span past the efuse_mmr extent answers DECERR, 0xBADCAB1E (memory_map.adoc:64);
hw/sys/sep/doc/otp_fuse_controller.adoc:45-46 states SLVERR for that span, so
the leaf also logs each of its codes as OBS-EFUSE-TOKEN-PAST-CODE.
The in-extent holes, one word between two mailbox sub-blocks and one between
two SEP CPU control registers on each bus lane, are read, written and read
again: they answer the Hole in Extent cell of their row (memory_map.adoc:69,
SLVERR, 0x0; :79, OKAY, 0x0), so the second read shows the write was
discarded.

CHK-UNMAPPED-NO-ALIAS: no refused read returns a programmed value, no probe
write moves a watched live word, and a closing re-read of every live word
matches the snapshot.

CHK-UNMAPPED-PINS: the DECERR beats the bus monitor saw equal the DECERR
responses the master reported.

FCOV gate: the window of this leaf opens right before the probe walk, only
when no check has failed before it, and closes after the tail walk, before the
closing re-read and the restore. It closes at once when an access of the walk
records a failure, so no later access samples. The sampler holds the row and
array-tail cells of each access at the response beat and samples them only on
the pass label ``row_pass``: the leaf drops the held cells at the start of
each probe or tail access and releases them after every check of that access
(code, refusal, re-read, no-alias) recorded no failure; a failure drops them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_row_pass
from sep_base_test import sep_base_test
from seq_lib.sep_unmapped_access_seq import (
    EXT_LOOPBACK_CTRL,
    GROUP_EFUSE_CTRL,
    GROUP_EFUSE_MMR,
    GROUP_INEXTENT,
    GROUP_MBOX,
    GROUP_RESERVED,
    GROUP_SPI,
    GROUP_SYSCSR,
    LITE_WATCHED,
    REFUSE_GROUPS,
    RESP_NAME,
    RESP_OKAY,
    TOKEN_MATCH_FAULT,
    TOKEN_MATCH_FAULT_MASK,
    TOKEN_MATCH_FAULT_RESET,
    SepUnmappedAccess,
    SepUnmappedCfg,
)

TEST = "sep_unmapped_access_policy_test"
# Pass label u_sep_fcov.row_pass: 1 releases the held cells of an access whose
# checks passed, 2 drops them. Each value is held this many clk_i edges.
ROW_PASS_RELEASE = 1
ROW_PASS_DROP = 2
_LABEL_CLOCKS = 2

_CHK = {
    GROUP_SYSCSR: "CHK-SYSCSR-HOLE-REFUSE",
    GROUP_RESERVED: "CHK-SYS-RESERVED-REFUSE",
    GROUP_MBOX: "CHK-MBOX-UPPER-REFUSE",
    GROUP_EFUSE_CTRL: "CHK-EFUSE-CTRL-PAST-REFUSE",
    GROUP_EFUSE_MMR: "CHK-EFUSE-MMR-PAST-REFUSE",
    GROUP_SPI: "CHK-SPI-PAST-REFUSE",
}


def _code(resp: int) -> str:
    return RESP_NAME.get(resp, f"resp{resp}")


def _grade(cfg: SepUnmappedCfg, where: str, addr: int, op: str, resp: int, rdata: int):
    """Grade one access against the map; return a CHK-UNMAPPED-CODE failure or None."""
    e = cfg.expect[(addr, op)]
    graded = op == "r"
    if resp == e.resp and (not graded or rdata == e.rdata):
        return None
    want = f"{_code(e.resp)}, 0x{e.rdata:08x}" if graded else _code(e.resp)
    got = f"{_code(resp)}, 0x{rdata:08x}" if graded else _code(resp)
    return f"{where} answered {got}; the map states {want} ({e.row}, {e.column})"


@dataclass
class _Walk:
    """Failures and counts of one run. Each failure list feeds one CHK verdict."""

    tok: list[str] = field(default_factory=list)
    per_group: dict[str, list[str]] = field(default_factory=lambda: {g: [] for g in REFUSE_GROUPS})
    decode: list[str] = field(default_factory=list)
    loop: list[str] = field(default_factory=list)
    tail: list[str] = field(default_factory=list)
    code: list[str] = field(default_factory=list)
    alias: list[str] = field(default_factory=list)
    codes: dict[tuple[str, str], Counter] = field(default_factory=dict)
    lite: dict[tuple[str, str], list[int]] = field(default_factory=dict)
    tail_codes: Counter = field(default_factory=Counter)
    n_code: int = 0
    n_watched: int = 0
    n_hole: int = 0
    n_in: int = 0
    n_past: int = 0
    n_reread: int = 0

    def failures(self) -> int:
        lists = [self.tok, self.decode, self.loop, self.tail, self.code, self.alias]
        return sum(len(f) for f in lists + list(self.per_group.values()))


class _Gate:
    """The graded window of this leaf, closed at the first recorded failure.

    Inside the window each access is one instance of the pass label
    ``row_pass``: ``begin`` drops the cells held before it, ``after`` releases
    the cells of the access when every check of it passed, or drops them and
    closes the window when one failed.
    """

    def __init__(self, log, walk: _Walk) -> None:
        self.log = log
        self.walk = walk
        self.is_open = False
        self.released = 0

    @staticmethod
    async def _label(value: int) -> None:
        set_row_pass(value)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)
        set_row_pass(0)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)

    async def begin(self) -> None:
        """Start one graded access: drop every cell held since the last release."""
        if self.is_open:
            await self._label(ROW_PASS_DROP)

    def open(self) -> None:
        n = self.walk.failures()
        if n:
            self.log.info("FCOV-GATE not opened: %d failure(s) recorded before the probe walk", n)
            return
        open_graded_window(TEST, self.log)
        self.is_open = True

    async def after(self, where: str) -> None:
        """Release the cells of ``where``, or close the window when it recorded a failure."""
        if not self.is_open:
            return
        if self.walk.failures():
            close_graded_window(self.log)
            set_row_pass(ROW_PASS_DROP, self.log)
            self.is_open = False
            self.log.info("FCOV-GATE closed at the first failure: %s", where)
            await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)
            set_row_pass(0)
            return
        await self._label(ROW_PASS_RELEASE)
        self.released += 1

    def close(self) -> None:
        if self.is_open:
            close_graded_window(self.log)
            self.is_open = False


@pyuvm.test()
class sep_unmapped_access_policy_test(sep_base_test):
    """Unmapped points next to live registers are refused or read zero, never alias."""

    async def run_scenario(self) -> None:
        cfg = SepUnmappedCfg()
        self.logger.info("unmapped config: %s", cfg.summary())
        await self.bring_up_no_cpu()
        ua = SepUnmappedAccess(self, cfg)
        mon = self.env.axi_monitor
        seen0 = mon.expected_decerr_seen
        w = _Walk()

        # --- positive control -------------------------------------------
        miss = await ua.program_live()
        assert not miss, "CHK-UNMAPPED-LIVE FAIL: " + "; ".join(miss)
        assert len(ua.snap) == len(cfg.live), (
            f"CHK-UNMAPPED-LIVE FAIL: {len(ua.snap)} of {len(cfg.live)} live words snapshotted"
        )
        self.logger.info(
            "CHK-UNMAPPED-LIVE PASS: %d programmed word(s) read back their distinct "
            "value with OKAY (%d with no RDL reset, written before any read); %d "
            "live word(s) snapshotted in total",
            len(cfg.programmed),
            len(cfg.unreset),
            len(ua.snap),
        )

        # --- Lite-port and ext-initiator watcher controls ------------------
        w.decode.extend(await ua.lite_control())
        w.loop.extend(await ua.ext_control())

        # --- TOKEN_MATCH_FAULT extent end -----------------------------------
        resp, val, to = await ua.access("r", TOKEN_MATCH_FAULT, may_refuse=True)
        if to or resp != RESP_OKAY:
            w.tok.append(
                f"TOKEN_MATCH_FAULT 0x{TOKEN_MATCH_FAULT:08x} resp={_code(resp)} timed_out={to}"
            )
        elif (val & TOKEN_MATCH_FAULT_MASK) != TOKEN_MATCH_FAULT_RESET:
            w.tok.append(
                f"TOKEN_MATCH_FAULT read 0x{val:08x}, RDL reset "
                f"0x{TOKEN_MATCH_FAULT_RESET:08x} under mask 0x{TOKEN_MATCH_FAULT_MASK:08x}"
            )

        # --- graded walk: probes, then array tails --------------------------
        gate = _Gate(self.logger, w)
        gate.open()
        try:
            await self._probe_walk(cfg, ua, w, gate)
            await self._tail_walk(cfg, ua, w, gate)
        except BaseException:
            # A failure may resume from ReadOnly, where no value can be written.
            await NextTimeStep()
            gate.close()
            set_row_pass(ROW_PASS_DROP, self.logger)
            raise
        gate.close()

        # Tally of the codes CHK-UNMAPPED-CODE graded, per group and channel.
        for (g, op), c in w.codes.items():
            line = ", ".join(f"{k}={v}" for k, v in sorted(c.items()))
            extra = ""
            if (g, op) in w.lite:
                hit, n = w.lite[(g, op)]
                extra = f"; {hit} of {n} reached the system-CSR AXI-Lite port"
            self.logger.info(
                "UNMAPPED-CODE: %s %s at the initiator: %s%s",
                g,
                "write BRESP" if op == "w" else "read RRESP",
                line,
                extra,
            )
        for (in_ext, op, code), n in sorted(w.tail_codes.items()):
            self.logger.info(
                "UNMAPPED-CODE: array tail %s %s: %s=%d",
                "in-extent" if in_ext else "past-extent",
                "write" if op == "w" else "read",
                code,
                n,
            )

        verdict: dict[str, list[str]] = {"CHK-TOKEN-FAULT-EXTENT": w.tok}
        for g in REFUSE_GROUPS:
            verdict[_CHK[g]] = w.per_group[g]
        if w.n_watched == 0:
            w.decode.append("no probe watched the system-CSR AXI-Lite port")
            w.loop.append("no probe watched the local crossbar's ext initiator")
        verdict["CHK-SYSCSR-HOLE-DECODE"] = w.decode
        verdict["CHK-SYS-RESERVED-NO-LOOPBACK"] = w.loop
        if w.n_in == 0 or w.n_past == 0:
            w.tail.append(
                f"tail walk graded {w.n_in} in-extent and {w.n_past} past-extent access(es); "
                "both kinds are needed"
            )
        if w.n_reread == 0:
            w.tail.append("no in-extent tail was re-read after its write")
        verdict["CHK-ARRAY-TAIL"] = w.tail
        n_hole_want = sum(1 for p in cfg.probes if p.group == GROUP_INEXTENT)
        if w.n_hole != n_hole_want:
            w.code.append(
                f"{w.n_hole} of {n_hole_want} in-extent hole access(es) completed and were graded"
            )
        if w.n_code == 0:
            w.code.append("no probe or tail access completed, so no code was graded")
        if ua.err_reads == 0 or ua.err_reads_lane_checked != ua.err_reads:
            w.code.append(
                f"{ua.err_reads_lane_checked} of {ua.err_reads} error-response read(s) had "
                "their read data lane-checked for X/Z"
            )
        verdict["CHK-UNMAPPED-CODE"] = w.code

        # --- closing full compare (outside the window) ---------------------
        moved = await ua.compare(list(ua.snap))
        if moved:
            w.alias.append("closing re-read: " + ", ".join(moved))
        verdict["CHK-UNMAPPED-NO-ALIAS"] = w.alias

        seen = mon.expected_decerr_seen - seen0
        pin_fail = []
        if ua.decerr_reported == 0:
            pin_fail.append("no DECERR was reported, so the pin cross-check has nothing to compare")
        elif seen != ua.decerr_reported:
            pin_fail.append(
                f"master reported {ua.decerr_reported} DECERR response(s); the monitor saw {seen}"
            )
        verdict["CHK-UNMAPPED-PINS"] = pin_fail

        await ua.restore()

        # --- verdicts ---------------------------------------------------------
        counts = {
            "CHK-TOKEN-FAULT-EXTENT": (
                f"TOKEN_MATCH_FAULT 0x{TOKEN_MATCH_FAULT:08x} read OKAY with its RDL reset "
                f"and 0x{cfg.mmr_end:08x}, the first word after it, was refused"
            ),
            "CHK-ARRAY-TAIL": (
                f"{w.n_in} in-extent tail access(es) answered OKAY (reads zero), "
                f"{w.n_reread} re-read(s) after an in-extent write answered OKAY with zero, "
                f"and {w.n_past} past-extent tail access(es) were refused over "
                f"{len(cfg.tails)} tail words"
            ),
            "CHK-UNMAPPED-CODE": (
                f"{w.n_code} probe and tail access(es), {w.n_hole} of them at an in-extent "
                "hole, answered the response code and read data the SEP memory map states; "
                f"all {ua.err_reads} error-response read(s) were lane-checked for X/Z"
            ),
            "CHK-UNMAPPED-NO-ALIAS": (
                f"no refused read returned a programmed value, no probe write moved "
                f"a watched word, and all {len(ua.snap)} live words match the snapshot"
            ),
            "CHK-UNMAPPED-PINS": (
                f"{seen} DECERR beat(s) on the bus match the {ua.decerr_reported} "
                "the master reported"
            ),
        }
        for g in REFUSE_GROUPS:
            n = sum(1 for p in cfg.probes if p.group == g)
            counts[_CHK[g]] = f"all {n} {g} probe(s) were refused"
        counts["CHK-SYSCSR-HOLE-DECODE"] = (
            f"the watcher saw the {cfg.lite_ctrl.name} control write and read at the "
            f"system-CSR AXI-Lite port, and none of the {w.n_watched} "
            f"{' and '.join(LITE_WATCHED)} probe(s) reached it"
        )
        counts["CHK-SYS-RESERVED-NO-LOOPBACK"] = (
            f"the watcher saw the 0x{EXT_LOOPBACK_CTRL:08x} control write and read at the "
            f"local crossbar's ext initiator, and none of the {w.n_watched} "
            f"{' and '.join(LITE_WATCHED)} probe(s) arrived there"
        )
        bad = []
        for chk, fails in verdict.items():
            if fails:
                for line in fails:
                    self.logger.error("%s FAIL: %s", chk, line)
                bad.append(chk)
            else:
                self.logger.info("%s PASS: %s", chk, counts[chk])
        assert not bad, "unmapped-access checker(s) failed: " + ", ".join(bad)

    async def _probe_walk(self, cfg: SepUnmappedCfg, ua: SepUnmappedAccess, w: _Walk, gate):
        """Every probe in walk order, each graded before the next one starts."""
        for p in cfg.probes:
            await gate.begin()
            r = await ua.probe(p)
            key = (p.group, p.op)
            w.codes.setdefault(key, Counter())[_code(r.resp)] += 1
            where = f"{p.op} 0x{p.addr:08x} ({p.note})"
            if r.lite_reached is not None:
                tally = w.lite.setdefault(key, [0, 0])
                tally[0] += int(r.lite_reached)
                tally[1] += 1
                w.n_watched += 1
                if r.lite_reached:
                    w.decode.append(f"{where} reached the system-CSR AXI-Lite port")
                if r.ext_reached:
                    w.loop.append(f"{where} arrived at the local crossbar's ext initiator")
            if p.group == GROUP_INEXTENT:
                # Graded by CHK-UNMAPPED-CODE only: the map states OKAY for some.
                if r.timed_out:
                    w.code.append(f"{where} timed out")
                else:
                    w.n_hole += 1
            elif r.timed_out:
                w.per_group[p.group].append(f"{where} timed out")
            elif r.resp == RESP_OKAY:
                w.per_group[p.group].append(f"{where} answered OKAY")
            if not r.timed_out:
                w.n_code += 1
                f = _grade(cfg, where, p.addr, p.op, r.resp, r.rdata)
                if f:
                    w.code.append(f)
            if r.alias is not None:
                w.alias.append(f"{where} returned 0x{r.rdata:08x}, the value of {r.alias}")
            if r.changed:
                w.alias.append(f"{where} moved " + ", ".join(r.changed))
            lite_note = ""
            if r.lite_reached is not None:
                lite_note = (
                    f" system-CSR Lite {'reached' if r.lite_reached else 'not reached'},"
                    f" ext initiator {'reached' if r.ext_reached else 'not reached'}"
                )
            self.logger.info(
                "UNMAPPED-PROBE: %s %s resp=%s rdata=0x%08x%s",
                p.group,
                where,
                _code(r.resp),
                r.rdata,
                lite_note,
            )
            if p.group == GROUP_EFUSE_MMR and not r.timed_out:
                # The generated memory map (graded above) and the eFuse
                # controller text differ on the code of this span.
                e = cfg.expect[(p.addr, p.op)]
                self.logger.info(
                    "OBS-EFUSE-TOKEN-PAST-CODE: %s resp=%s rdata=%s map=%s/%s "
                    "otp_fuse_controller_text=SLVERR",
                    where,
                    _code(r.resp),
                    "-" if r.rdata is None else f"0x{r.rdata:08x}",
                    _code(e.resp),
                    "-" if e.rdata is None else f"0x{e.rdata:08x}",
                )
            if p.addr == cfg.mmr_end and p.op == "r":
                if r.timed_out or r.resp == RESP_OKAY:
                    w.tok.append(
                        f"first word past TOKEN_MATCH_FAULT 0x{p.addr:08x} was not refused "
                        f"(resp={_code(r.resp)} timed_out={r.timed_out})"
                    )
            await gate.after(f"{p.group} {where}")

    async def _tail_walk(self, cfg: SepUnmappedCfg, ua: SepUnmappedAccess, w: _Walk, gate):
        """Every array tail word, read then write, each graded before the next."""
        for t in cfg.tails:
            for op in ("r", "w"):
                await gate.begin()
                resp, rdata, to, changed, reread = await ua.tail(t, op)
                where = f"{t.label} {op} 0x{t.addr:08x}"
                ext_base, ext_size = cfg.array_extent[t.array]
                extent = (
                    f"array extent 0x{ext_base:08x}-0x{ext_base + ext_size - 1:08x} "
                    f"(base + TOTAL_SIZE 0x{ext_size:x})"
                )
                w.tail_codes[(t.in_extent, op, _code(resp))] += 1
                if not to and t.addr in cfg.map_disagree:
                    self.logger.info(
                        "UNMAPPED-MAP-DISAGREE: %s answered %s, 0x%08x; graded by "
                        "CHK-ARRAY-TAIL only; the map states %s",
                        where,
                        _code(resp),
                        rdata,
                        cfg.map_disagree[t.addr],
                    )
                elif not to:
                    w.n_code += 1
                    f = _grade(cfg, where, t.addr, op, resp, rdata)
                    if f:
                        w.code.append(f)
                if to:
                    w.tail.append(f"{where} timed out")
                elif t.in_extent:
                    w.n_in += 1
                    if resp != RESP_OKAY:
                        w.tail.append(f"{where} is inside the {extent} but answered {_code(resp)}")
                    elif op == "r" and rdata != 0:
                        w.tail.append(f"{where} is inside the {extent} but read 0x{rdata:08x}")
                else:
                    w.n_past += 1
                    if resp == RESP_OKAY:
                        w.tail.append(f"{where} is past the {extent} but answered OKAY")
                    elif op == "r":
                        hit = ua.read_alias(rdata)
                        if hit is not None:
                            w.alias.append(f"{where} returned the value of {hit}")
                if reread is not None:
                    w.n_reread += 1
                    r_resp, r_data, r_to = reread
                    if r_to or r_resp != RESP_OKAY:
                        w.tail.append(
                            f"{where} re-read after the write answered {_code(r_resp)} "
                            f"timed_out={r_to} inside the {extent}"
                        )
                    elif r_data != 0:
                        w.tail.append(
                            f"{where} re-read after the write returned 0x{r_data:08x} inside "
                            f"the {extent}; the write was not discarded"
                        )
                if changed:
                    w.alias.append(f"{where} moved " + ", ".join(changed))
                await gate.after(where)
