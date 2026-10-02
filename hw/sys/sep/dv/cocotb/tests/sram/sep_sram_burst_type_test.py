# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SRAM target refuses a multi-beat FIXED or WRAP burst with SLVERR.

no_cpu / +skip_fuse_sense. RAND-NONE: one directed FIXED and one directed WRAP
burst, 4 beats of 8 bytes each, on the CPU-LSU master.

``hw/sys/sep/doc/fabric.adoc#sep-sram-target`` specifies that the SRAM target
serves INCR bursts of every length and single-beat bursts of every type, and
refuses a multi-beat FIXED or WRAP burst before it reaches the memory: the
write terminates with BRESP=SLVERR and leaves SRAM unchanged, and every beat
of the read returns RRESP=SLVERR. Any other response code, and an OKAY-served
burst, fails. The AXI4 beat addresses of each burst type (see
``seq_lib/sep_sram_burst_type_seq.py``) are diagnostic only: a failing log
names the AXI4 or the INCR image when that is what the DUT produced.

CHK-BT-STIM: the AW / AR handshake on the testbench port carries the start
address, AxLEN, AxSIZE and AxBURST of the case, so the verdict below is about
the named burst type and not a master that fell back to INCR.

CHK-BT-CONTROL: single-beat writes of a distinct background to every word in
the region read back, so the region can show where a burst landed.

CHK-BT-WRITE: the write burst answers BRESP=SLVERR and the region still equals
the background. Any other response or image fails, and the log names the AXI4
or INCR image when that is what the DUT produced.

CHK-BT-READ: over a known image, the read burst answers RRESP=SLVERR on every
beat.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_sram_burst_type_seq import (
    BURST_INCR,
    RESP_OKAY,
    RESP_SLVERR,
    SepSramBurstType,
    background,
    beat_addrs,
    burst_cases,
    burst_word,
    golden_after_write,
    golden_read,
    stim_miss,
)


def _w(v: int) -> str:
    """A 64-bit word as 0xHHHHHHHH_LLLLLLLL."""
    s = f"{v:016x}"
    return f"0x{s[:8]}_{s[8:]}"


def _tag(word: int, low: int) -> str:
    """Upper half of ``word`` once its lower half ``low`` is removed."""
    return f"0x{(word ^ low) >> 32:08x}"


def _beat_ids(case) -> range:
    return range(len(beat_addrs(case.burst, case.start)))


def _which(case, v: int) -> str:
    """Name the stimulus word ``v`` equals: a beat's data or a background word."""
    for i in _beat_ids(case):
        if v == burst_word(case, i):
            return f"d{i}"
    for a in case.region:
        if v == background(a):
            return f"the word @0x{a:08x}"
    return "no stimulus word"


@pyuvm.test()
class sep_sram_burst_type_test(sep_base_test):
    """A multi-beat FIXED or WRAP burst into SRAM is refused with SLVERR."""

    required_evidence = ("CHK-BT-STIM", "CHK-BT-CONTROL", "CHK-BT-WRITE", "CHK-BT-READ")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        bt = SepSramBurstType(self)
        fails: list[str] = []

        cases = burst_cases()
        self.logger.info(
            "burst-type data encoding: beat i writes d<i> = <tag>_<burst start> with tag %s; "
            "an untouched word holds <tag>_<addr> with tag %s",
            " ".join(
                f"{c.name}=["
                + ",".join(_tag(burst_word(c, i), c.start) for i in _beat_ids(c))
                + "]"
                for c in cases
            ),
            _tag(background(cases[0].region[0]), cases[0].region[0]),
        )

        for case in cases:
            named = [f"0x{a:08x}" for a in beat_addrs(case.burst, case.start)]
            self.logger.info(
                "burst-type config: %s start=0x%08x AXI4 beat addresses %s",
                case.name,
                case.start,
                named,
            )
            await bt.fill(case)
            img = await bt.image(case)
            bg = {a: background(a) for a in case.region}
            assert img == bg, (
                f"CHK-BT-CONTROL FAIL: {case.name} background did not read back: "
                + " ".join(f"0x{a:08x}=0x{v:016x}" for a, v in img.items() if v != bg[a])
            )
            self.logger.info(
                "CHK-BT-CONTROL PASS: %s %d background words read back",
                case.name,
                len(case.region),
            )

            # Write side.
            resp, timed_out, aw = await bt.write_burst(case)
            miss = stim_miss(case, aw)
            assert miss is None, f"CHK-BT-STIM FAIL: {case.name} write: {miss}"
            self.logger.info("CHK-BT-STIM PASS: %s write burst on the pins: %s", case.name, aw)
            after = await bt.image(case)
            golden = golden_after_write(case)
            incr = dict(bg)
            for i, a in enumerate(beat_addrs(BURST_INCR, case.start)):
                incr[a] = burst_word(case, i)
            beats = beat_addrs(case.burst, case.start)
            for a in case.region:
                hits = [i for i, b in enumerate(beats) if b == a]
                if not hits:
                    what = "untouched in AXI4"
                elif len(hits) == 1:
                    what = f"wrote beat{hits[0]} d{hits[0]}={_w(golden[a])} (AXI4 target)"
                else:
                    what = (
                        f"wrote beat{hits[-1]} d{hits[-1]}={_w(golden[a])} (AXI4 target of "
                        f"beats {','.join(str(i) for i in hits)}; the last beat stays)"
                    )
                exp = bg[a]
                note = f" (background; BRESP={resp})"
                ok = after[a] == exp
                (self.logger.info if ok else self.logger.error)(
                    "CHK-BT-WRITE %s 0x%08x: %s | read back %s (%s) | expected %s%s %s",
                    case.name,
                    a,
                    what,
                    _w(after[a]),
                    _which(case, after[a]),
                    _w(exp),
                    note,
                    "PASS" if ok else "FAIL",
                )
            if timed_out:
                verdict = "timed out"
            elif resp == RESP_SLVERR and after == bg:
                verdict = None
            else:
                if after == bg:
                    shape = "the background"
                elif after == golden:
                    shape = "the AXI4 image"
                elif after == incr:
                    shape = "the INCR image"
                else:
                    shape = "no known image"
                diff = " ".join(
                    f"0x{a:08x}:got=0x{after[a]:016x},bg=0x{bg[a]:016x}"
                    for a in case.region
                    if after[a] != bg[a]
                )
                verdict = f"BRESP={resp} (want SLVERR={RESP_SLVERR}) and SRAM holds {shape}" + (
                    f" ({diff})" if diff else ""
                )
            if verdict is None:
                self.logger.info(
                    "CHK-BT-WRITE PASS: %s write burst refused, BRESP=%d (SLVERR), "
                    "%d words unchanged",
                    case.name,
                    resp,
                    len(case.region),
                )
            else:
                fails.append(f"CHK-BT-WRITE {case.name}: {verdict}")
                self.logger.error("CHK-BT-WRITE FAIL: %s %s", case.name, verdict)

            # Read side, over a known image: restore the background first.
            await bt.fill(case)
            words, resps, rd_to, ar = await bt.read_burst(case)
            miss = stim_miss(case, ar)
            assert miss is None, f"CHK-BT-STIM FAIL: {case.name} read: {miss}"
            self.logger.info("CHK-BT-STIM PASS: %s read burst on the pins: %s", case.name, ar)
            want = golden_read(case, bg)
            self.logger.info(
                "burst-type read: %s RRESP=%s got=%s axi4=%s",
                case.name,
                resps,
                [f"0x{w:016x}" for w in words],
                [f"0x{w:016x}" for w in want],
            )
            read_fail = None
            if rd_to:
                read_fail = f"CHK-BT-READ {case.name}: read burst timed out"
            elif len(resps) != len(want):
                read_fail = (
                    f"CHK-BT-READ {case.name}: monitor captured {len(resps)} RRESP "
                    f"beat(s), expected {len(want)}; no per-beat evidence"
                )
            else:
                for i, (b, w, e, r) in enumerate(
                    zip(beat_addrs(case.burst, case.start), words, want, resps)
                ):
                    ok = r == RESP_SLVERR
                    (self.logger.info if ok else self.logger.error)(
                        "CHK-BT-READ %s beat%d: RRESP=%d (want SLVERR=%d) | AXI4 word "
                        "@0x%08x = %s | returned %s (%s) %s",
                        case.name,
                        i,
                        r,
                        RESP_SLVERR,
                        b,
                        _w(e),
                        _w(w),
                        _which(case, w),
                        "PASS" if ok else "FAIL",
                    )
                bad = [f"beat{i} RRESP={r}" for i, r in enumerate(resps) if r != RESP_SLVERR]
                if bad:
                    served = [i for i, r in enumerate(resps) if r == RESP_OKAY]
                    read_fail = (
                        f"CHK-BT-READ {case.name}: RRESP={resps}, want SLVERR={RESP_SLVERR} on "
                        f"every beat: {' '.join(bad)}"
                        + (f"; OKAY beats {served}" if served else "")
                    )
                else:
                    self.logger.info(
                        "CHK-BT-READ PASS: %s read burst refused, RRESP=%s (SLVERR on all %d beats)",
                        case.name,
                        resps,
                        len(resps),
                    )
            if read_fail is not None:
                fails.append(read_fail)
                self.logger.error("CHK-BT-READ FAIL: %s", read_fail)

        if fails:
            raise AssertionError(f"{len(fails)} burst-type check(s) failed: " + "; ".join(fails))
        self.logger.info(
            "burst-type summary: multi-beat FIXED and WRAP are refused with SLVERR, "
            "on write and on read"
        )
