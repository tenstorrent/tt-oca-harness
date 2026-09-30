# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unmapped-access policy at the points no other leaf probes.

no_cpu / +skip_fuse_sense. RAND-NONE: every address comes from the generated
register export and is walked on every run.

The SEP components table of the generated memory map
(``hw/sys/sep/regs/gen/adoc/memory_map.adoc``, rendered from ``sep.rdl``)
states the contract. Per unit it gives the Decoded Extent and, for a 32-bit
access that no register backs, the read response, the read data and the write
response: inside the extent, past it, and in a reserved row between apertures.
``env/sep_decode_resp.py`` reads the table; the config refuses to build if a
probe the refusal checkers grade is not a refusal there.

CHK-UNMAPPED-LIVE is the positive control. Every programmed live word next to a
probed hole is written with a distinct value and must read it back OKAY, so the
bus reaches each block and a write or read alias is visible.

CHK-SYSCSR-HOLE-REFUSE, CHK-SYS-RESERVED-REFUSE, CHK-MBOX-UPPER-REFUSE,
CHK-EFUSE-CTRL-PAST-REFUSE, CHK-EFUSE-MMR-PAST-REFUSE and CHK-SPI-PAST-REFUSE:
every read and write in that set is refused (never OKAY, never a timeout).

CHK-TOKEN-FAULT-EXTENT: TOKEN_MATCH_FAULT, the last register the RDL gives the
eFuse token MMR, reads OKAY with its RDL reset, and the first word after it is
refused. The extent therefore ends where the RDL ends it.

CHK-ARRAY-TAIL: the tail of each remap / filter array slot (stride wider than
the slot's registers) follows the map. The array extent is the Decoded Extent
of the array's map row, whose aperture is base + SEP_TOP_<ARRAY>_TOTAL_SIZE. A
tail inside it reads zero and accepts a write with OKAY; the last slot's tail
lies past it and is refused, and so is the first word past the aperture where no
other RDL block owns that word. A re-read of an in-extent tail after its write
answers OKAY with zero, so the write was discarded. A tail write never moves a
word of its own slot or of the next slot.

CHK-UNMAPPED-CODE: every probe and tail access answers the response code the
map states for that address and channel, and every read returns the stated read
data (the word for address bit 2 where the map gives one). Where sep.rdl states
an upper word of 0 under a non-zero low word, a bit-2 read is graded on its
code only and its data is logged (UNMAPPED-RDATA-UNGRADED). Past the
efuse_interface_ctrl and spi_controller extents, reads cover both 32-bit lanes
of the bus. The monitor lane-checks the read data of every error response for
X/Z, so an unknown payload fails instead of reading as zero; every such read
must have been lane-checked.

CHK-UNMAPPED-NO-ALIAS: no refused read returns a programmed value, no probe
write moves a watched live word, and a closing re-read of every live word
matches the snapshot.

CHK-UNMAPPED-PINS: the DECERR beats the bus monitor saw equal the DECERR
responses the master reported.
"""

from __future__ import annotations

from collections import Counter

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_unmapped_access_seq import (
    GROUP_EFUSE_CTRL,
    GROUP_EFUSE_MMR,
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
    """Grade one access against the map.

    Returns ``(failure, ungraded)``: a CHK-UNMAPPED-CODE failure string or None,
    and, for a read whose data the map does not state one way, a report line.
    """
    e = cfg.expect[(addr, op)]
    graded = op == "r" and e.rdata is not None
    ungraded = None
    if op == "r" and e.rdata is None:
        ungraded = f"{where} answered {_code(resp)}, 0x{rdata:08x}; {e.rdata_note}"
    if resp == e.resp and (not graded or rdata == e.rdata):
        return None, ungraded
    want = f"{_code(e.resp)}, 0x{e.rdata:08x}" if graded else _code(e.resp)
    got = f"{_code(resp)}, 0x{rdata:08x}" if graded else _code(resp)
    return f"{where} answered {got}; the map states {want} ({e.row}, {e.column})", ungraded


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
        verdict: dict[str, list[str]] = {}

        # --- positive control -------------------------------------------
        miss = await ua.program_live()
        assert not miss, "CHK-UNMAPPED-LIVE FAIL: " + "; ".join(miss)
        assert len(ua.snap) == len(cfg.live), (
            f"CHK-UNMAPPED-LIVE FAIL: {len(ua.snap)} of {len(cfg.live)} live words snapshotted"
        )
        self.logger.info(
            "CHK-UNMAPPED-LIVE PASS: %d programmed word(s) read back their distinct "
            "value with OKAY; %d live word(s) snapshotted in total",
            len(cfg.programmed),
            len(ua.snap),
        )

        # --- TOKEN_MATCH_FAULT extent end -----------------------------------
        resp, val, to = await ua.access("r", TOKEN_MATCH_FAULT, may_refuse=True)
        tok_fail = []
        if to or resp != RESP_OKAY:
            tok_fail.append(
                f"TOKEN_MATCH_FAULT 0x{TOKEN_MATCH_FAULT:08x} resp={_code(resp)} timed_out={to}"
            )
        elif (val & TOKEN_MATCH_FAULT_MASK) != TOKEN_MATCH_FAULT_RESET:
            tok_fail.append(
                f"TOKEN_MATCH_FAULT read 0x{val:08x}, RDL reset "
                f"0x{TOKEN_MATCH_FAULT_RESET:08x} under mask 0x{TOKEN_MATCH_FAULT_MASK:08x}"
            )
        verdict["CHK-TOKEN-FAULT-EXTENT"] = tok_fail

        # --- refusal groups -------------------------------------------------
        codes: dict[tuple[str, str], Counter] = {}
        lite: dict[tuple[str, str], list[int]] = {}
        alias_fails: list[str] = []
        per_group: dict[str, list[str]] = {g: [] for g in REFUSE_GROUPS}
        code_fails: list[str] = []
        ungraded: list[str] = []
        n_code = 0
        for p in cfg.probes:
            r = await ua.probe(p)
            key = (p.group, p.op)
            codes.setdefault(key, Counter())[_code(r.resp)] += 1
            if r.lite_reached is not None:
                tally = lite.setdefault(key, [0, 0])
                tally[0] += int(r.lite_reached)
                tally[1] += 1
            where = f"{p.op} 0x{p.addr:08x} ({p.note})"
            if r.timed_out:
                per_group[p.group].append(f"{where} timed out")
            elif r.resp == RESP_OKAY:
                per_group[p.group].append(f"{where} answered OKAY")
            if not r.timed_out:
                n_code += 1
                f, u = _grade(cfg, where, p.addr, p.op, r.resp, r.rdata)
                if f:
                    code_fails.append(f)
                if u:
                    ungraded.append(u)
            if r.alias is not None:
                alias_fails.append(f"{where} returned 0x{r.rdata:08x}, the value of {r.alias}")
            if r.changed:
                alias_fails.append(f"{where} moved " + ", ".join(r.changed))
            lite_note = ""
            if r.lite_reached is not None:
                lite_note = f" system-CSR Lite {'reached' if r.lite_reached else 'not reached'}"
            self.logger.info(
                "UNMAPPED-PROBE: %s %s resp=%s rdata=0x%08x%s",
                p.group,
                where,
                _code(r.resp),
                r.rdata,
                lite_note,
            )
            if p.addr == cfg.mmr_end and p.op == "r":
                if r.timed_out or r.resp == RESP_OKAY:
                    tok_fail.append(
                        f"first word past TOKEN_MATCH_FAULT 0x{p.addr:08x} was not refused "
                        f"(resp={_code(r.resp)} timed_out={r.timed_out})"
                    )
        for g in REFUSE_GROUPS:
            verdict[_CHK[g]] = per_group[g]

        # Tally of the codes CHK-UNMAPPED-CODE graded, per group and channel.
        for (g, op), c in codes.items():
            line = ", ".join(f"{k}={v}" for k, v in sorted(c.items()))
            extra = ""
            if (g, op) in lite:
                hit, n = lite[(g, op)]
                extra = f"; {hit} of {n} reached the system-CSR AXI-Lite port"
            self.logger.info(
                "UNMAPPED-CODE: %s %s at the initiator: %s%s",
                g,
                "write BRESP" if op == "w" else "read RRESP",
                line,
                extra,
            )
        for g in LITE_WATCHED:
            self.logger.info(
                "UNMAPPED-CODE: %s: the Lite port has no response probe, so the "
                "slave-side BRESP of a write is not observable here; a read RRESP "
                "is the slave's code, passed through unchanged",
                g,
            )

        # --- array tails ----------------------------------------------------
        tail_fails: list[str] = []
        tail_codes: Counter = Counter()
        n_in = n_past = n_reread = 0
        for t in cfg.tails:
            for op in ("r", "w"):
                resp, rdata, to, changed, reread = await ua.tail(t, op)
                where = f"{t.label} {op} 0x{t.addr:08x}"
                ext_base, ext_size = cfg.array_extent[t.array]
                extent = (
                    f"array extent 0x{ext_base:08x}-0x{ext_base + ext_size - 1:08x} "
                    f"(map Decoded Extent 0x{ext_size:x})"
                )
                tail_codes[(t.in_extent, op, _code(resp))] += 1
                if not to:
                    n_code += 1
                    f, u = _grade(cfg, where, t.addr, op, resp, rdata)
                    if f:
                        code_fails.append(f)
                    if u:
                        ungraded.append(u)
                if to:
                    tail_fails.append(f"{where} timed out")
                elif t.in_extent:
                    n_in += 1
                    if resp != RESP_OKAY:
                        tail_fails.append(
                            f"{where} is inside the {extent} but answered {_code(resp)}"
                        )
                    elif op == "r" and rdata != 0:
                        tail_fails.append(f"{where} is inside the {extent} but read 0x{rdata:08x}")
                else:
                    n_past += 1
                    if resp == RESP_OKAY:
                        tail_fails.append(f"{where} is past the {extent} but answered OKAY")
                    elif op == "r":
                        hit = ua.read_alias(rdata)
                        if hit is not None:
                            alias_fails.append(f"{where} returned the value of {hit}")
                if reread is not None:
                    n_reread += 1
                    r_resp, r_data, r_to = reread
                    if r_to or r_resp != RESP_OKAY:
                        tail_fails.append(
                            f"{where} re-read after the write answered {_code(r_resp)} "
                            f"timed_out={r_to} inside the {extent}"
                        )
                    elif r_data != 0:
                        tail_fails.append(
                            f"{where} re-read after the write returned 0x{r_data:08x} inside "
                            f"the {extent}; the write was not discarded"
                        )
                if changed:
                    alias_fails.append(f"{where} moved " + ", ".join(changed))
        if n_in == 0 or n_past == 0:
            tail_fails.append(
                f"tail walk graded {n_in} in-extent and {n_past} past-extent access(es); "
                "both kinds are needed"
            )
        if n_reread == 0:
            tail_fails.append("no in-extent tail was re-read after its write")
        for (in_ext, op, code), n in sorted(tail_codes.items()):
            self.logger.info(
                "UNMAPPED-CODE: array tail %s %s: %s=%d",
                "in-extent" if in_ext else "past-extent",
                "write" if op == "w" else "read",
                code,
                n,
            )
        verdict["CHK-ARRAY-TAIL"] = tail_fails
        if n_code == 0:
            code_fails.append("no probe or tail access completed, so no code was graded")
        # Report, not a verdict: sep.rdl and the cell definition disagree on
        # this read data, so only its response code is graded.
        for line in ungraded:
            self.logger.info("UNMAPPED-RDATA-UNGRADED: %s", line)
        if ua.err_reads == 0 or ua.err_reads_lane_checked != ua.err_reads:
            code_fails.append(
                f"{ua.err_reads_lane_checked} of {ua.err_reads} error-response read(s) had "
                "their read data lane-checked for X/Z"
            )
        verdict["CHK-UNMAPPED-CODE"] = code_fails

        # --- closing full compare -----------------------------------------
        moved = await ua.compare(list(ua.snap))
        if moved:
            alias_fails.append("closing re-read: " + ", ".join(moved))
        verdict["CHK-UNMAPPED-NO-ALIAS"] = alias_fails

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
                f"{n_in} in-extent tail access(es) answered OKAY (reads zero), "
                f"{n_reread} re-read(s) after an in-extent write answered OKAY with zero, "
                f"and {n_past} past-extent tail access(es) were refused over "
                f"{len(cfg.tails)} tail words"
            ),
            "CHK-UNMAPPED-CODE": (
                f"{n_code} probe and tail access(es) answered the response code and read "
                f"data the SEP memory map states ({len(ungraded)} read(s) graded on the code "
                f"only, see UNMAPPED-RDATA-UNGRADED); all {ua.err_reads} error-response "
                "read(s) were lane-checked for X/Z"
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
        bad = []
        for chk, fails in verdict.items():
            if fails:
                for line in fails:
                    self.logger.error("%s FAIL: %s", chk, line)
                bad.append(chk)
            else:
                self.logger.info("%s PASS: %s", chk, counts[chk])
        assert not bad, "unmapped-access checker(s) failed: " + ", ".join(bad)
