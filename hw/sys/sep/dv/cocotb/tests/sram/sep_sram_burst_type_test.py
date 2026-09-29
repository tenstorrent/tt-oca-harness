# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FIXED and WRAP bursts into SEP SRAM are either refused or performed as named.

no_cpu / +skip_fuse_sense. RAND-NONE: one directed FIXED and one directed WRAP
burst, 4 beats of 8 bytes each, on the CPU-LSU master.

``hw/sys/sep/doc/fabric.adoc`` specifies the SEP interconnect as an AXI4
fabric, and the SRAM row of ``hw/sys/sep/doc/memory_map.adoc`` is a slave on
it. AXI4 defines the beat addresses of each burst type (see
``seq_lib/sep_sram_burst_type_seq.py``). Two outcomes are lawful for a
burst type the slave does not implement: an error response with SRAM
unchanged, or OKAY with the beats at the addresses the burst type names.

CHK-BT-STIM: the AW / AR handshake on the testbench port carries the start
address, AxLEN, AxSIZE and AxBURST of the case, so the verdict below is about
the named burst type and not a master that fell back to INCR.

CHK-BT-CONTROL: single-beat writes of a distinct background to every word in
the region read back, so the region can show where a burst landed.

CHK-BT-WRITE: after the write burst, the region equals the background (the
burst was refused, BRESP non-OKAY) or the AXI4 image of the named burst type
(BRESP OKAY). Any other image fails, and the log names the INCR image when
that is what the DUT produced.

CHK-BT-READ: over a known image, a read burst either answers non-OKAY on every
beat or returns, on OKAY beats, the words the named burst type addresses.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_sram_burst_type_seq import (
    BURST_INCR,
    RESP_OKAY,
    SepSramBurstType,
    background,
    beat_addrs,
    burst_cases,
    burst_word,
    golden_after_write,
    golden_read,
    stim_miss,
)


@pyuvm.test()
class sep_sram_burst_type_test(sep_base_test):
    """A FIXED or WRAP burst into SRAM is refused or honoured, never run as INCR."""

    required_evidence = ("CHK-BT-STIM", "CHK-BT-CONTROL", "CHK-BT-WRITE", "CHK-BT-READ")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        bt = SepSramBurstType(self)
        fails: list[str] = []

        for case in burst_cases():
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
            if timed_out:
                verdict = "timed out"
            elif resp != RESP_OKAY and after == bg:
                verdict = None
            elif resp == RESP_OKAY and after == golden:
                verdict = None
            else:
                shape = (
                    "the INCR image"
                    if after == incr
                    else ("the background" if after == bg else "neither image")
                )
                diff = " ".join(
                    f"0x{a:08x}:got=0x{after[a]:016x},axi4=0x{golden[a]:016x}"
                    for a in case.region
                    if after[a] != golden[a]
                )
                verdict = f"BRESP={resp} and SRAM holds {shape} ({diff})"
            if verdict is None:
                self.logger.info(
                    "CHK-BT-WRITE PASS: %s write burst %s (BRESP=%d)",
                    case.name,
                    "refused, SRAM unchanged" if resp != RESP_OKAY else "landed at AXI4 addresses",
                    resp,
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
                bad = [
                    f"beat{i}=0x{w:016x} want 0x{e:016x}"
                    for i, (w, e, r) in enumerate(zip(words, want, resps))
                    if r == RESP_OKAY and w != e
                ]
                mixed = any(r == RESP_OKAY for r in resps) and any(r != RESP_OKAY for r in resps)
                if bad or mixed:
                    read_fail = f"CHK-BT-READ {case.name}: RRESP={resps} " + (
                        " ".join(bad) if bad else "mixed OKAY and error beats"
                    )
                else:
                    self.logger.info(
                        "CHK-BT-READ PASS: %s read burst %s",
                        case.name,
                        "refused on every beat"
                        if all(r != RESP_OKAY for r in resps)
                        else "returned the AXI4 beat words",
                    )
            if read_fail is not None:
                fails.append(read_fail)
                self.logger.error("CHK-BT-READ FAIL: %s", read_fail)

        if fails:
            raise AssertionError(f"{len(fails)} burst-type check(s) failed: " + "; ".join(fails))
        self.logger.info(
            "burst-type summary: FIXED and WRAP are refused or performed at their "
            "AXI4 beat addresses, on write and on read"
        )
